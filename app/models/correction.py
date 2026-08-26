"""
`corrections`: append-only log of every human edit to an extracted field.
Never UPDATE an extracted_field's value in place when a human corrects it —
insert a Correction row and update the ExtractedField's current value. This
is what makes "what did the human actually change" answerable later, which
matters both for audit and for measuring how good the LLM extraction really
is (the whole point of the benchmark).
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.extracted_field import ExtractedField


class Correction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "corrections"

    extracted_field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_fields.id", ondelete="CASCADE"), nullable=False
    )
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by: Mapped[str] = mapped_column(String(256), nullable=False)

    extracted_field: Mapped["ExtractedField"] = relationship(back_populates="corrections")
