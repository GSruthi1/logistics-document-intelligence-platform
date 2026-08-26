"""Pydantic schemas for the HITL queue endpoints."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.extraction import ExtractedFieldOut, ValidationResultOut


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    doc_type: str
    status: str
    reason: str
    priority: int
    assigned_to: str | None
    created_at: datetime
    resolved_at: datetime | None
    fields: list[ExtractedFieldOut]
    validation_results: list[ValidationResultOut]


class FieldCorrectionIn(BaseModel):
    field_name: str
    corrected_value: str | None


class QueueCorrectionRequest(BaseModel):
    corrections: list[FieldCorrectionIn] = Field(min_length=1)
    corrected_by: str = Field(min_length=1, description="Reviewer identity, e.g. email")
