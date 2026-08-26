"""
One function, used everywhere state changes: `record`. Centralizing this
means every audit row has the same shape and nobody accidentally forgets a
field. Every write to this table is app-level, in the same DB transaction as
the state change it's describing — see hitl_service.py and document_service.py
for the pattern of "mutate the row, then record(), then commit once".
"""
import uuid

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor: str = "system",
    before_value: dict | None = None,
    after_value: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        before_value=before_value,
        after_value=after_value,
    )
    db.add(entry)
    return entry
