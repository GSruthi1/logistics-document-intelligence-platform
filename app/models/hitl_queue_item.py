"""
`hitl_queue_items`: the human-in-the-loop work queue. A document lands here
when routing decides it needs a human — low-confidence fields and/or failed
validation rules. `reason` is a short human-readable summary generated at
enqueue time so a reviewer doesn't have to reverse-engineer why a doc showed
up in their queue.
"""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class QueueStatus(str, enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class HitlQueueItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "hitl_queue_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_review','resolved')", name="ck_hitl_queue_items_status"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=QueueStatus.PENDING.value)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Higher = more urgent. Lets a client's ops team prioritize e.g.
    # high-dollar freight invoices over routine PODs without changing code.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_to: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="hitl_queue_items")
