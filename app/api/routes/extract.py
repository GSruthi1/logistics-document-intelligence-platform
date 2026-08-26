import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_document_service
from app.extraction.field_schema import FIELD_SCHEMAS
from app.schemas.extraction import ExtractResponse
from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["extraction"])

ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB — generous for a scanned freight doc, cheap to bound


@router.post("/extract", response_model=ExtractResponse, status_code=201)
async def extract_document(
    file: UploadFile = File(...),
    doc_type: str = Form(..., description=f"One of: {list(FIELD_SCHEMAS)}"),
    db: Session = Depends(get_db),
    service: DocumentService = Depends(get_document_service),
) -> ExtractResponse:
    if doc_type not in FIELD_SCHEMAS:
        raise HTTPException(status_code=400, detail=f"Unknown doc_type '{doc_type}'. Must be one of {list(FIELD_SCHEMAS)}")
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content_type '{file.content_type}'. Must be one of {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit")

    try:
        document = service.process_upload(
            db, content=content, filename=file.filename, content_type=file.content_type, doc_type=doc_type
        )
    except Exception:
        logger.exception("Extraction pipeline failed for upload %s", file.filename)
        raise HTTPException(status_code=502, detail="Extraction failed — see server logs") from None

    pending_queue_items = [q for q in document.hitl_queue_items if q.status != "resolved"]
    queue_item = pending_queue_items[0] if pending_queue_items else None

    return ExtractResponse(
        document_id=document.id,
        filename=document.filename,
        doc_type=document.doc_type,
        status=document.status,
        fields=document.extracted_fields,
        validation_results=document.validation_results,
        queued_for_review=queue_item is not None,
        queue_item_id=queue_item.id if queue_item else None,
        uploaded_at=document.created_at,
    )
