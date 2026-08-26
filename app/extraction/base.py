"""
The interface every extractor (LLM-based, OCR-based, future ones) must
implement. This is the seam that makes the pipeline swappable: DocumentService
depends on `Extractor`, never on `LLMExtractor` or `OCRExtractor` directly.
Swapping Claude for GPT-4o, or adding a Textract-based extractor later, means
writing a new class here — zero changes anywhere else in the pipeline.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FieldExtractionResult:
    field_name: str
    value: str | None
    # Self-reported / heuristic confidence in [0, 1]. This is the *raw* signal
    # — ConfidenceScorer (a separate module) turns this into the final,
    # trusted confidence used for routing. An extractor should never decide
    # routing itself; that's a separation-of-concerns boundary we keep hard.
    confidence: float


@dataclass
class ExtractionOutput:
    fields: list[FieldExtractionResult]
    model_used: str
    extraction_method: str  # "llm" | "ocr"


class Extractor(ABC):
    @abstractmethod
    def extract(self, file_bytes: bytes, content_type: str, doc_type: str) -> ExtractionOutput:
        """Extract structured fields for `doc_type` from a document's raw bytes.

        `content_type` is the uploaded MIME type (application/pdf, image/png,
        image/jpeg, ...) since PDFs and images need different preprocessing
        before they can be sent to a model or OCR engine.
        """
        raise NotImplementedError
