#!/usr/bin/env python
"""
Generates N synthetic freight documents (default 100, split evenly across
bill_of_lading / proof_of_delivery / freight_invoice) as PDFs, plus a
ground_truth.json manifest recording the true field values for each one.

Pipeline: Faker generates realistic field values -> a random carrier profile
picks label text + layout for those fields -> Jinja2 renders HTML -> WeasyPrint
renders HTML to PDF. Two profiles per doc type (see carrier_profiles.py) is
the "realistic formatting variation" — same fields, different label wording
and layout, the way two different carriers' paperwork actually differs.

Usage:
    python -m benchmark.generate_synthetic_docs --count 100 --seed 42
"""
import argparse
import json
import random
from pathlib import Path

from faker import Faker
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.extraction.field_schema import get_field_schema
from benchmark.carrier_profiles import DOC_TITLES, PROFILES_BY_DOC_TYPE
from benchmark.field_generators import generate_fields

TEMPLATES_DIR = Path(__file__).parent / "templates"
DOC_TYPES = ["bill_of_lading", "proof_of_delivery", "freight_invoice"]


def render_document(doc_type: str, fields: dict[str, str | None], profile, env: Environment) -> bytes:
    field_order = [spec.name for spec in get_field_schema(doc_type)]
    # Omitted optional fields (value is None) don't appear on the document at
    # all — real freight paperwork doesn't print a "PRO Number: (blank)" line
    # for a field nobody filled in, it just isn't there. This also matches
    # what the LLM extraction prompt expects: null means genuinely absent,
    # not "present but empty".
    rows = [(profile.labels[name], fields[name]) for name in field_order if fields.get(name) is not None]

    template = env.get_template("document.html.j2")
    html_str = template.render(
        doc_title=DOC_TITLES[doc_type],
        profile_name=profile.name,
        layout=profile.layout,
        accent_color=profile.accent_color,
        font_family=profile.font_family,
        rows=rows,
    )
    return HTML(string=html_str).write_pdf()


def generate(count: int, seed: int, output_dir: Path) -> None:
    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    output_dir.mkdir(parents=True, exist_ok=True)
    for doc_type in DOC_TYPES:
        (output_dir / doc_type).mkdir(exist_ok=True)

    manifest = []
    for i in range(count):
        doc_type = DOC_TYPES[i % len(DOC_TYPES)]  # even split across the three types
        profile = random.choice(PROFILES_BY_DOC_TYPE[doc_type])
        fields = generate_fields(doc_type, fake)

        pdf_bytes = render_document(doc_type, fields, profile, env)
        filename = f"{i:03d}_{profile.name}.pdf"
        file_path = output_dir / doc_type / filename
        file_path.write_bytes(pdf_bytes)

        manifest.append(
            {
                "id": i,
                "doc_type": doc_type,
                "profile": profile.name,
                "file_path": str(file_path.relative_to(output_dir)),
                "ground_truth": fields,
            }
        )

    manifest_path = output_dir / "ground_truth.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Generated {count} documents -> {output_dir}/")
    print(f"Ground truth manifest -> {manifest_path}")
    counts_by_type = {dt: sum(1 for m in manifest if m["doc_type"] == dt) for dt in DOC_TYPES}
    counts_by_profile = {}
    for m in manifest:
        counts_by_profile[m["profile"]] = counts_by_profile.get(m["profile"], 0) + 1
    print(f"By doc_type: {counts_by_type}")
    print(f"By profile:  {counts_by_profile}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42, help="reproducibility: same seed -> same documents")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "synthetic_docs")
    args = parser.parse_args()
    generate(args.count, args.seed, args.output_dir)
