import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.hitl_queue_item import HitlQueueItem, QueueStatus
from app.queue import hitl_service
from app.schemas.queue import QueueCorrectionRequest, QueueItemOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/queue", tags=["hitl_queue"])


def _to_out(item: HitlQueueItem) -> QueueItemOut:
    return QueueItemOut(
        id=item.id,
        document_id=item.document_id,
        filename=item.document.filename,
        doc_type=item.document.doc_type,
        status=item.status,
        reason=item.reason,
        priority=item.priority,
        assigned_to=item.assigned_to,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        fields=item.document.extracted_fields,
        validation_results=item.document.validation_results,
    )


@router.get("", response_model=list[QueueItemOut])
def list_queue(
    status: str | None = Query(default=QueueStatus.PENDING.value, description="pending | in_review | resolved | null for all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[QueueItemOut]:
    items = hitl_service.list_queue(db, status=status, limit=limit, offset=offset)
    return [_to_out(i) for i in items]


@router.get("/{queue_item_id}", response_model=QueueItemOut)
def get_queue_item(queue_item_id: uuid.UUID, db: Session = Depends(get_db)) -> QueueItemOut:
    try:
        item = hitl_service.get_queue_item(db, queue_item_id)
    except hitl_service.HitlQueueItemNotFound:
        raise HTTPException(status_code=404, detail="Queue item not found") from None
    return _to_out(item)


@router.patch("/{queue_item_id}/correct", response_model=QueueItemOut)
def correct_queue_item(
    queue_item_id: uuid.UUID, body: QueueCorrectionRequest, db: Session = Depends(get_db)
) -> QueueItemOut:
    try:
        item = hitl_service.correct(db, queue_item_id, body.corrections, body.corrected_by)
    except hitl_service.HitlQueueItemNotFound:
        raise HTTPException(status_code=404, detail="Queue item not found") from None
    except hitl_service.FieldNotFoundOnDocument as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    db.commit()
    db.refresh(item)
    return _to_out(item)
