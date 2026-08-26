"""
Import every model module here, once, so:
  1. SQLAlchemy's declarative registry has all classes registered before any
     relationship() string forward-reference gets resolved.
  2. Alembic's env.py can do `from app.models import Base` and autogenerate
     sees the *complete* schema, not just whichever models happened to be
     imported first.

Anything that touches the DB should import `Base` from here (or from
app.db.base directly) — never construct models before this module has run.
"""
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.correction import Correction
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.extracted_field import ExtractedField, ExtractionMethod
from app.models.hitl_queue_item import HitlQueueItem, QueueStatus
from app.models.validation_result import Severity, ValidationResult

__all__ = [
    "Base",
    "AuditLog",
    "Correction",
    "Document",
    "DocumentStatus",
    "DocumentType",
    "ExtractedField",
    "ExtractionMethod",
    "HitlQueueItem",
    "QueueStatus",
    "ValidationResult",
    "Severity",
]
