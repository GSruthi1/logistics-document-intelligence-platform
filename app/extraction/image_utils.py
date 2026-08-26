"""
Shared PDF/image preprocessing used by both the LLM extractor and the OCR
baseline extractor — kept in one place so "how do we rasterize a PDF" has
exactly one implementation, not one per extractor that could drift.
"""
import io

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def prepare_image(file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    """Returns (image_bytes, media_type). PDFs are rasterized to a PNG of the
    first page (needs the system `poppler` binary via pdf2image).
    """
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes

        pages = convert_from_bytes(file_bytes, dpi=200, first_page=1, last_page=1)
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        return buf.getvalue(), "image/png"

    if content_type in SUPPORTED_IMAGE_TYPES:
        return file_bytes, content_type

    raise ValueError(f"Unsupported content_type: {content_type}")
