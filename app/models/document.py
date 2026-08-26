"""
The `documents` table: one row per uploaded file.

Design note worth remembering for an interview: status and doc_type are
stored as plain `String` columns with a Postgres CHECK constraint, not as a
native Postgres ENUM type. Native enums are appealing at first but painful in
production — adding a new value later requires `ALTER TYPE ... ADD VALUE`,
which can't run inside a transaction and complicates zero-downtime
deploys. A CHECK constraint gives the same validation guarantee and is a
one-line Alembic migration to change.
"""
import enum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    # Only imported for static type checkers (mypy/ruff/IDEs) resolving the
    # string forward references below — never executed at runtime, so this
    # can't create the document<->extracted_field<->... circular import the
    # note at the bottom of this file describes.
    from app.models.extracted_field import ExtractedField
    from app.models.hitl_queue_item import HitlQueueItem
    from app.models.validation_result import ValidationResult


class DocumentType(str, enum.Enum):
    BILL_OF_LADING = "bill_of_lading"
    PROOF_OF_DELIVERY = "proof_of_delivery"
    FREIGHT_INVOICE = "freight_invoice"
    UNKNOWN = "unknown"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    AUTO_APPROVED = "auto_approved"
    IN_REVIEW = "in_review"
    CORRECTED = "corrected"
    FAILED = "failed"


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('bill_of_lading','proof_of_delivery','freight_invoice','unknown')",
            name="ck_documents_doc_type",
        ),
        CheckConstraint(
            "status IN ('uploaded','processing','extracted','validated',"
            "'auto_approved','in_review','corrected','failed')",
            name="ck_documents_status",
        ),
        Index("ix_documents_status", "status"),
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 of the file bytes. Lets /extract detect "this exact file was
    # already uploaded" and short-circuit instead of paying for a second LLM
    # call on an accidental duplicate upload — a real cost concern once you're
    # paying per-page for GPT-4o/Claude vision calls.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentType.UNKNOWN.value)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.UPLOADED.value)

    extracted_fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    hitl_queue_items: Mapped[list["HitlQueueItem"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# NOTE: no imports of ExtractedField/ValidationResult/HitlQueueItem here.
# The `Mapped[list["ExtractedField"]]` annotations above are *string* forward
# references — SQLAlchemy's declarative registry resolves them by class name
# at mapper-configuration time, not at module-import time. That means every
# model module can reference its siblings by name without a circular
# `import document` <-> `import extracted_field` loop. The one requirement is
# that all model modules get imported *somewhere* before the first query
# runs, which is exactly what app/models/__init__.py does.
