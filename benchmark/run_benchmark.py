#!/usr/bin/env python
"""
Runs the LLM extractor and/or the pytesseract OCR baseline against the
synthetic document set and reports field-level accuracy, broken down by
document type and by carrier profile (standard vs altcarrier label
wording) — the profile breakdown is what makes the "why" of any gap
inspectable instead of a single opaque number.

For documents the LLM actually extracted, it also runs them through the
SAME ConfidenceScorer + RulesEngine used in the live API (app/scoring,
app/validation) to report what fraction would be auto-approved vs sent to
the HITL queue — that's the basis for the "% reduction in human review"
claim: reviewing zero documents isn't realistic, but reviewing only the
ones the pipeline is actually unsure about is the entire value proposition.

Usage:
    python -m benchmark.run_benchmark --methods ocr           # free, local
    python -m benchmark.run_benchmark --methods llm --limit 5 # costs API credits
    python -m benchmark.run_benchmark --methods both
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from app.core.config import get_settings
from app.extraction.base import Extractor, ExtractionOutput
from app.extraction.field_schema import get_field_schema
from app.extraction.llm_extractor import LLMExtractor
from app.extraction.ocr_extractor import OCRExtractor
from app.scoring.confidence_scorer import ConfidenceScorer
from app.validation.rules_config import get_rules_engine
from benchmark.scoring import values_match

DEFAULT_MANIFEST = Path(__file__).parent / "synthetic_docs" / "ground_truth.json"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "results"


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def run_method(
    method_name: str,
    extractor: Extractor,
    manifest: list[dict],
    docs_dir: Path,
    scorer: ConfidenceScorer | None = None,
    rules_engine=None,
) -> dict:
    field_results = []  # one row per (document, field): correct bool + metadata
    doc_routing = []  # one row per document, only meaningful when scorer/rules_engine given (LLM)
    errors = 0
    start = time.time()

    for entry in manifest:
        pdf_path = docs_dir / entry["file_path"]
        content = pdf_path.read_bytes()
        doc_type = entry["doc_type"]
        ground_truth = entry["ground_truth"]

        try:
            output: ExtractionOutput = extractor.extract(content, "application/pdf", doc_type)
        except Exception as e:
            errors += 1
            print(f"  [{method_name}] ERROR on {entry['file_path']}: {e}")
            continue

        by_name = {f.field_name: f for f in output.fields}
        for field_name, expected in ground_truth.items():
            extracted = by_name.get(field_name)
            correct = values_match(extracted.value if extracted else None, expected)
            field_results.append(
                {
                    "doc_id": entry["id"],
                    "doc_type": doc_type,
                    "profile": entry["profile"],
                    "field_name": field_name,
                    "correct": correct,
                }
            )

        if scorer is not None and rules_engine is not None:
            specs = get_field_schema(doc_type)
            scored = scorer.score_all(specs, output.fields)
            threshold = get_settings().confidence_auto_approve_threshold
            field_values = {s.field_name: s.value for s in scored}
            rule_outcomes = rules_engine.validate(doc_type, field_values)
            low_conf = any(s.final_confidence < threshold for s in scored)
            failed_rule = any(not o.passed and o.severity == "error" for o in rule_outcomes)
            doc_routing.append({"doc_id": entry["id"], "needs_review": low_conf or failed_rule})

    elapsed = time.time() - start
    return {
        "method": method_name,
        "field_results": field_results,
        "doc_routing": doc_routing,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
    }


def summarize(run: dict) -> dict:
    results = run["field_results"]
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    overall_accuracy = correct / total if total else 0.0

    by_doc_type = defaultdict(lambda: [0, 0])
    by_profile = defaultdict(lambda: [0, 0])
    for r in results:
        by_doc_type[r["doc_type"]][1] += 1
        by_doc_type[r["doc_type"]][0] += int(r["correct"])
        by_profile[r["profile"]][1] += 1
        by_profile[r["profile"]][0] += int(r["correct"])

    summary = {
        "method": run["method"],
        "overall_accuracy": round(overall_accuracy, 4),
        "total_fields_graded": total,
        "errors": run["errors"],
        "elapsed_seconds": run["elapsed_seconds"],
        "accuracy_by_doc_type": {k: round(v[0] / v[1], 4) for k, v in by_doc_type.items()},
        "accuracy_by_profile": {k: round(v[0] / v[1], 4) for k, v in by_profile.items()},
    }

    if run["doc_routing"]:
        n = len(run["doc_routing"])
        needs_review = sum(1 for d in run["doc_routing"] if d["needs_review"])
        summary["documents_scored_for_routing"] = n
        summary["pct_sent_to_hitl_queue"] = round(needs_review / n, 4)
        summary["pct_reduction_in_human_review_vs_review_everything"] = round(1 - (needs_review / n), 4)

    return summary


def print_summary_table(summaries: list[dict]) -> None:
    print("\n" + "=" * 70)
    print(f"{'Method':<10} {'Overall Acc.':<14} {'BOL':<8} {'POD':<8} {'Invoice':<8} {'Errors':<8}")
    print("-" * 70)
    for s in summaries:
        by_type = s["accuracy_by_doc_type"]
        print(
            f"{s['method']:<10} {s['overall_accuracy']*100:>10.1f}%   "
            f"{by_type.get('bill_of_lading', 0)*100:>5.1f}%  "
            f"{by_type.get('proof_of_delivery', 0)*100:>5.1f}%  "
            f"{by_type.get('freight_invoice', 0)*100:>5.1f}%  "
            f"{s['errors']:<8}"
        )
        by_profile = s["accuracy_by_profile"]
        print(
            f"  -> by profile: standard={by_profile.get('standard', 0)*100:.1f}%  "
            f"altcarrier={by_profile.get('altcarrier', 0)*100:.1f}%"
        )
        if "pct_sent_to_hitl_queue" in s:
            print(
                f"  -> HITL routing: {s['pct_sent_to_hitl_queue']*100:.1f}% of documents queued for review "
                f"({s['pct_reduction_in_human_review_vs_review_everything']*100:.1f}% reduction vs reviewing everything)"
            )
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--methods", choices=["ocr", "llm", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None, help="only run N documents (smoke testing)")
    parser.add_argument("--offset", type=int, default=0, help="skip the first N documents — lets a paid LLM "
                         "run resume/extend a prior partial run instead of re-paying for documents already done")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    if not args.manifest.exists():
        raise SystemExit(
            f"No manifest at {args.manifest}. Run `python -m benchmark.generate_synthetic_docs` first."
        )
    manifest = load_manifest(args.manifest)
    if args.offset:
        manifest = manifest[args.offset :]
    if args.limit:
        manifest = manifest[: args.limit]
    docs_dir = args.manifest.parent

    settings = get_settings()
    run_ocr = args.methods in ("ocr", "both")
    run_llm = args.methods in ("llm", "both")

    if run_llm:
        has_key = (settings.llm_provider == "anthropic" and settings.anthropic_api_key) or (
            settings.llm_provider == "openai" and settings.openai_api_key
        )
        if not has_key:
            print(
                f"WARNING: LLM_PROVIDER={settings.llm_provider} but no API key is set — "
                "skipping the LLM method. Set ANTHROPIC_API_KEY/OPENAI_API_KEY in .env to run it."
            )
            run_llm = False

    summaries = []
    all_runs = {}

    if run_ocr:
        print(f"Running OCR baseline on {len(manifest)} documents...")
        ocr_run = run_method("ocr", OCRExtractor(), manifest, docs_dir)
        all_runs["ocr"] = ocr_run
        summaries.append(summarize(ocr_run))

    if run_llm:
        print(f"Running LLM extractor ({settings.llm_provider}) on {len(manifest)} documents "
              f"— this calls a paid API {len(manifest)} times.")
        llm_run = run_method(
            "llm", LLMExtractor(settings), manifest, docs_dir,
            scorer=ConfidenceScorer(), rules_engine=get_rules_engine(),
        )
        all_runs["llm"] = llm_run
        summaries.append(summarize(llm_run))

    print_summary_table(summaries)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.output_dir / "benchmark_results.json"
    results_path.write_text(json.dumps({"summaries": summaries, "raw_runs": all_runs}, indent=2))
    print(f"Full results written to {results_path}")


if __name__ == "__main__":
    main()
