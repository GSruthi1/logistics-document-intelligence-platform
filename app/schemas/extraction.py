"""Pydantic schemas shared by the /extract and /queue API responses."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExtractedFieldOut(BaseModel):
    # protected_namespaces=() disables Pydantic's default "model_*" field
    # guard — we have a genuine `model_used` field (which LLM produced this
    # extraction), not an accidental collision with Pydantic's own
    # model_config/model_fields internals.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    field_name: str
    field_value: str | None
    raw_confidence: float | None
    final_confidence: float | None
    extraction_method: str
    model_used: str


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_name: str
    field_name: str | None
    passed: bool
    message: str | None
    severity: str


class ExtractResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    doc_type: str
    status: str
    fields: list[ExtractedFieldOut]
    validation_results: list[ValidationResultOut]
    queued_for_review: bool
    queue_item_id: uuid.UUID | None = None
    uploaded_at: datetime
