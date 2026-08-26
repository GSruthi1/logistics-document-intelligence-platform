"""
`extracted_fields`: one row per (document, field). e.g. a single BOL upload
produces ~12 rows here — shipper_name, consignee_name, pro_number, weight...

This is an EAV-ish (entity-attribute-value) shape rather than one wide column
per field. Deliberate trade-off: BOLs, PODs, and freight invoices each have a
different field set, and new document types will show up later (this is a
platform, not a single form). A wide table would need a schema migration
every time a client wants a new field extracted; this shape doesn't.
The cost is you lose SQL-level type checking per field and pay a small join
tax on reads — acceptable here since reads are per-document, not high-QPS
analytical queries.
"""
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.correction import Correction
    from app.models.document import Document

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExtractionMethod(str, enum.Enum):
    LLM = "llm"
    OCR = "ocr"


class ExtractedField(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        CheckConstraint("extraction_method IN ('llm','ocr')", name="ck_extracted_fields_method"),
        CheckConstraint(
            "raw_confidence IS NULL OR (raw_confidence >= 0 AND raw_confidence <= 1)",
            name="ck_extracted_fields_raw_confidence_range",
        ),
        CheckConstraint(
            "final_confidence IS NULL OR (final_confidence >= 0 AND final_confidence <= 1)",
            name="ck_extracted_fields_final_confidence_range",
        ),
        # A document shouldn't have two LLM extractions of the same field —
        # re-extraction should overwrite/version, not duplicate silently.
        Index(
            "ux_extracted_fields_doc_field_method",
            "document_id", "field_name", "extraction_method",
            unique=True,
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The model's own stated confidence (0-1), taken as-is from the LLM response.
    raw_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # What ConfidenceScorer computes after applying heuristics on top of raw_confidence.
    # This — not raw_confidence — is what routing decisions use.
    final_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    extraction_method: Mapped[str] = mapped_column(String(16), nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="extracted_fields")
    corrections: Mapped[list["Correction"]] = relationship(
        back_populates="extracted_field", cascade="all, delete-orphan"
    )
