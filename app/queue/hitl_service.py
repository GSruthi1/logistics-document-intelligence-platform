"""
HITL (human-in-the-loop) queue service: enqueue documents that need review,
list the queue for a reviewer UI, and apply corrections.

This module owns the *queue* lifecycle. It does not decide *whether* a
document should be queued — that routing decision belongs to
DocumentService, which is the only caller of `enqueue`. Keeping that decision
out of this module is what lets DocumentService's routing logic (confidence
threshold + validation errors) be unit-tested without touching the database
at all.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.document import Document, DocumentStatus
from app.models.correction import Correction
from app.models.extracted_field import ExtractedField
from app.models.hitl_queue_item import HitlQueueItem, QueueStatus
from app.schemas.queue import FieldCorrectionIn
from app.services import audit_service


class HitlQueueItemNotFound(Exception):
    pass


class FieldNotFoundOnDocument(Exception):
    pass


def enqueue(db: Session, document: Document, reason: str, priority: int = 0) -> HitlQueueItem:
    item = HitlQueueItem(
        document_id=document.id,
        status=QueueStatus.PENDING.value,
        reason=reason,
        priority=priority,
    )
    db.add(item)
    db.flush()  # assigns item.id without committing, so we can audit-log it below

    document.status = DocumentStatus.IN_REVIEW.value
    audit_service.record(
        db,
        entity_type="hitl_queue_item",
        entity_id=item.id,
        action="queued",
        after_value={"document_id": str(document.id), "reason": reason, "priority": priority},
    )
    return item


def list_queue(
    db: Session, status: str | None = QueueStatus.PENDING.value, limit: int = 50, offset: int = 0
) -> list[HitlQueueItem]:
    stmt = (
        select(HitlQueueItem)
        .options(
            selectinload(HitlQueueItem.document).selectinload(Document.extracted_fields),
            selectinload(HitlQueueItem.document).selectinload(Document.validation_results),
        )
        .order_by(HitlQueueItem.priority.desc(), HitlQueueItem.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        stmt = stmt.where(HitlQueueItem.status == status)
    return list(db.execute(stmt).scalars().all())


def get_queue_item(db: Session, queue_item_id: uuid.UUID) -> HitlQueueItem:
    stmt = (
        select(HitlQueueItem)
        .options(
            selectinload(HitlQueueItem.document).selectinload(Document.extracted_fields),
            selectinload(HitlQueueItem.document).selectinload(Document.validation_results),
        )
        .where(HitlQueueItem.id == queue_item_id)
    )
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        raise HitlQueueItemNotFound(str(queue_item_id))
    return item


def correct(
    db: Session,
    queue_item_id: uuid.UUID,
    corrections: list[FieldCorrectionIn],
    corrected_by: str,
) -> HitlQueueItem:
    """Applies one or more field corrections and resolves the queue item.

    Every correction is: read the current ExtractedField -> write an
    immutable Correction row recording the before/after -> update the
    ExtractedField's live value -> mark it human-verified (final_confidence
    = 1.0, since a human just confirmed it). All of this plus the queue
    item's resolution happens in one DB transaction (the caller commits),
    so a failure partway through never leaves the queue item resolved with
    only half its corrections applied.
    """
    item = get_queue_item(db, queue_item_id)

    fields_by_name: dict[str, ExtractedField] = {
        f.field_name: f for f in item.document.extracted_fields if f.extraction_method == "llm"
    }

    for c in corrections:
        field = fields_by_name.get(c.field_name)
        if field is None:
            raise FieldNotFoundOnDocument(
                f"Document {item.document_id} has no extracted field '{c.field_name}'"
            )

        original_value = field.field_value
        db.add(
            Correction(
                extracted_field_id=field.id,
                original_value=original_value,
                corrected_value=c.corrected_value,
                corrected_by=corrected_by,
            )
        )
        field.field_value = c.corrected_value
        field.final_confidence = 1.0

        audit_service.record(
            db,
            entity_type="extracted_field",
            entity_id=field.id,
            action="corrected",
            actor=corrected_by,
            before_value={"value": original_value},
            after_value={"value": c.corrected_value},
        )

    item.status = QueueStatus.RESOLVED.value
    item.resolved_at = datetime.now(timezone.utc)
    item.document.status = DocumentStatus.CORRECTED.value

    audit_service.record(
        db,
        entity_type="hitl_queue_item",
        entity_id=item.id,
        action="resolved",
        actor=corrected_by,
        after_value={"corrected_fields": [c.field_name for c in corrections]},
    )
    return item
