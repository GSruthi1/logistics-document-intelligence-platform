"""
`audit_log`: generic, append-only, entity-agnostic event log. Every
meaningful state transition anywhere in the system writes one row here —
document created, LLM extraction ran, validation ran, item queued, human
corrected a field, document auto-approved. This is deliberately NOT
normalized into per-entity history tables; a single wide log is what lets you
answer "show me everything that happened to document X, in order" and
"show me everything reviewer Y did today" with one query each.

before_value/after_value are JSONB so this table doesn't care what shape the
entity is — a documents row, an extracted_fields row, whatever.
"""
import uuid

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # "system" for automated pipeline steps, or a reviewer's email/id for
    # human actions — one column instead of a nullable user_id + separate
    # is_system flag, since "who did this" always has an answer.
    actor: Mapped[str] = mapped_column(String(256), nullable=False, default="system")
    before_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
