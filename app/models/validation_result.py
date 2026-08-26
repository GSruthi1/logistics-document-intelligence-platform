"""
`validation_results`: one row per business rule evaluated against a document.
field_name is nullable because some rules are cross-field / document-level
(e.g. "delivery_date must be after pickup_date") rather than about one field.
"""
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document


class Severity(str, enum.Enum):
    ERROR = "error"      # blocks auto-approval outright
    WARNING = "warning"  # informational, doesn't by itself force HITL


class ValidationResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "validation_results"
    __table_args__ = (
        CheckConstraint("severity IN ('error','warning')", name="ck_validation_results_severity"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.ERROR.value)

    document: Mapped["Document"] = relationship(back_populates="validation_results")
