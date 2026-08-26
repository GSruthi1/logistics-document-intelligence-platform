"""
pytesseract-based baseline extractor — this exists purely so the benchmark
can quantify what "understanding the document" (LLM) buys you over "reading
the pixels" (OCR).

OCR gives you characters, not fields. To get from raw text to "here is the
consignee_name" you need a second layer of heuristics: find a label keyword
("Consignee:") and grab the text near it. That second layer is exactly where
this approach breaks down — it only works when the label text matches one of
your known aliases *and* sits in a position your regex expects. A different
carrier's layout, a label typo'd as "Consignee Name" instead of "Consignee",
or a value that wraps onto a second line, and the field comes back empty or
wrong. That fragility is the whole point of this baseline: it's not that
OCR "reads badly" (tesseract's character-level accuracy is often fine), it's
that character accuracy doesn't imply field accuracy.
"""
import logging
import re

import pytesseract
from PIL import Image
import io

from app.extraction.base import ExtractionOutput, Extractor, FieldExtractionResult
from app.extraction.field_schema import get_field_schema
from app.extraction.image_utils import prepare_image

logger = logging.getLogger(__name__)

# Known label text we look for on the document for each field. Real carriers
# phrase these differently ("PRO#" vs "PRO Number" vs "Tracking #") — every
# alias NOT in this list is a value this extractor will simply miss, which is
# the mechanism behind the accuracy gap the benchmark measures.
FIELD_LABEL_ALIASES: dict[str, list[str]] = {
    "bol_number": [r"bol\s*(number|#|no\.?)", r"bill of lading\s*(number|#|no\.?)"],
    "shipper_name": [r"shipper"],
    "shipper_address": [r"shipper address"],
    "consignee_name": [r"consignee"],
    "consignee_address": [r"consignee address"],
    "carrier_name": [r"carrier"],
    "pro_number": [r"pro\s*(number|#|no\.?)"],
    "pickup_date": [r"pickup date", r"ship date"],
    "total_weight_lbs": [r"total weight", r"weight"],
    "piece_count": [r"pieces", r"piece count", r"pcs"],
    "freight_charge_terms": [r"freight charge terms", r"charge terms"],
    "delivery_date": [r"delivery date"],
    "delivery_time": [r"delivery time"],
    "received_by": [r"received by"],
    "signature_present": [r"signature"],
    "condition_notes": [r"condition", r"exceptions?"],
    "invoice_number": [r"invoice\s*(number|#|no\.?)"],
    "invoice_date": [r"invoice date"],
    "total_charge": [r"total (charge|due|amount)"],
    "fuel_surcharge": [r"fuel surcharge"],
    "payment_due_date": [r"payment due", r"due date"],
}


class OCRExtractor(Extractor):
    """Baseline extractor for the accuracy benchmark. Not used in the live
    HITL pipeline — `LLM_PROVIDER` routing never selects this class; it's
    wired up explicitly by benchmark/run_benchmark.py.
    """

    def extract(self, file_bytes: bytes, content_type: str, doc_type: str) -> ExtractionOutput:
        image_bytes, _ = prepare_image(file_bytes, content_type)
        image = Image.open(io.BytesIO(image_bytes))

        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        lines = _group_words_into_lines(ocr_data)
        full_text = "\n".join(line_text for line_text, _ in lines)

        fields = get_field_schema(doc_type)
        results = []
        for f in fields:
            value, confidence = _extract_field(f.name, lines, full_text)
            results.append(FieldExtractionResult(field_name=f.name, value=value, confidence=confidence))

        return ExtractionOutput(fields=results, model_used="pytesseract", extraction_method="ocr")


def _group_words_into_lines(ocr_data: dict) -> list[tuple[str, float]]:
    """Reconstructs (line_text, avg_word_confidence) tuples from tesseract's
    flat word-level output, grouped by (block, paragraph, line).
    """
    lines: dict[tuple, list[tuple[str, float]]] = {}
    n = len(ocr_data["text"])
    for i in range(n):
        word = ocr_data["text"][i].strip()
        conf = float(ocr_data["conf"][i])
        if not word or conf < 0:  # tesseract uses -1 conf for non-text regions
            continue
        key = (ocr_data["block_num"][i], ocr_data["par_num"][i], ocr_data["line_num"][i])
        lines.setdefault(key, []).append((word, conf))

    result = []
    for key in sorted(lines.keys()):
        words = lines[key]
        text = " ".join(w for w, _ in words)
        avg_conf = sum(c for _, c in words) / len(words) / 100.0  # normalize 0-100 -> 0-1
        result.append((text, avg_conf))
    return result


def _extract_field(field_name: str, lines: list[tuple[str, float]], full_text: str) -> tuple[str | None, float]:
    aliases = FIELD_LABEL_ALIASES.get(field_name, [])
    for alias_pattern in aliases:
        for idx, (line_text, line_conf) in enumerate(lines):
            match = re.search(alias_pattern, line_text, flags=re.IGNORECASE)
            if not match:
                continue

            # Value is whatever follows the label on the same line, after an
            # optional ':' — e.g. "Consignee: Acme Corp" -> "Acme Corp".
            remainder = line_text[match.end():].lstrip(" :#-").strip()
            if remainder:
                return remainder, round(line_conf, 3)

            # Label with no same-line value (e.g. label on its own line above
            # a boxed value) — fall back to the next line, at a confidence
            # penalty since this is a guess about layout, not a direct match.
            if idx + 1 < len(lines):
                next_text, next_conf = lines[idx + 1]
                if next_text.strip():
                    return next_text.strip(), round(next_conf * 0.7, 3)

    return None, 0.0
