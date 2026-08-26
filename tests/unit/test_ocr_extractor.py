"""
Unlike the LLM extractor (which needs a live API key and isn't something we
want unit tests hitting), pytesseract runs locally — so this test renders a
real synthetic image and runs the real OCR extractor against it, no mocking.
It exists mostly to prove `_group_words_into_lines` / `_extract_field` work
against actual tesseract output shapes, not just hand-built dicts.
"""
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.extraction.ocr_extractor import OCRExtractor

pytesseract = pytest.importorskip("pytesseract")


def _render_label_value_image(lines: list[str]) -> bytes:
    """Renders simple "Label: Value" lines onto a white image — a crude but
    OCR-friendly stand-in for a document field block.
    """
    img = Image.new("RGB", (900, 60 * len(lines) + 40), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("Arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default()
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black", font=font)
        y += 60
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract binary not installed on this machine")
def test_ocr_extractor_finds_field_after_matching_label():
    image_bytes = _render_label_value_image(["BOL Number: BOL-1001", "Carrier: FastFreight Inc"])
    extractor = OCRExtractor()
    output = extractor.extract(image_bytes, "image/png", "bill_of_lading")

    by_name = {f.field_name: f for f in output.fields}
    assert "BOL-1001" in (by_name["bol_number"].value or "")
    assert by_name["bol_number"].confidence > 0
    assert "FastFreight" in (by_name["carrier_name"].value or "")


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract binary not installed on this machine")
def test_ocr_extractor_returns_none_for_absent_label():
    image_bytes = _render_label_value_image(["BOL Number: BOL-1001"])
    extractor = OCRExtractor()
    output = extractor.extract(image_bytes, "image/png", "bill_of_lading")

    by_name = {f.field_name: f for f in output.fields}
    # "Shipper" was never on the image at all -> the label-search heuristic
    # has nothing to match, which is exactly the failure mode the benchmark
    # is built to quantify.
    assert by_name["shipper_name"].value is None
    assert by_name["shipper_name"].confidence == 0.0
