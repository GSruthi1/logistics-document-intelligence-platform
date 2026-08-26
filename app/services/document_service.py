"""
DocumentService: the orchestrator. This is the ONLY module that knows the
full pipeline order (extract -> score -> validate -> route -> persist). Every
other module — Extractor, ConfidenceScorer, RulesEngine, HitlService — has no
idea it's part of a pipeline; each just does its one job on plain inputs.
That's what "clean separation of concerns" cashes out to concretely: you can
unit test ConfidenceScorer with a FieldExtractionResult you typed by hand,
with no FastAPI, no DB, no HTTP involved at all.

Scope note: doc_type is a required input to /extract, not auto-detected.
Classifying "is this a BOL or a POD" is its own ML problem (a cheap text/
layout classifier, realistically) — deliberately out of scope here so this
project stays focused on the extraction/confidence/validation/HITL loop.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.extraction.base import Extractor
from app.extraction.field_schema import get_field_schema
from app.models.document import Document, DocumentStatus
from app.models.extracted_field import ExtractedField
from app.models.validation_result import ValidationResult
from app.queue import hitl_service
from app.scoring.confidence_scorer import ConfidenceScorer
from app.services import audit_service
from app.storage.file_storage import FileStorage, sha256_hex
from app.validation.rules_engine import RulesEngine

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        storage: FileStorage,
        extractor: Extractor,
        scorer: ConfidenceScorer,
        rules_engine: RulesEngine,
        settings: Settings | None = None,
    ):
        self.storage = storage
        self.extractor = extractor
        self.scorer = scorer
        self.rules_engine = rules_engine
        self.settings = settings or get_settings()

    def process_upload(
        self,
        db: Session,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        doc_type: str,
    ) -> Document:
        source_hash = sha256_hex(content)

        existing = (
            db.query(Document)
            .filter(Document.source_hash == source_hash, Document.status != DocumentStatus.FAILED.value)
            .first()
        )
        if existing is not None:
            logger.info("Duplicate upload detected (hash=%s) -> returning existing document %s",
                        source_hash[:12], existing.id)
            return existing

        file_path = self.storage.save(content, filename)
        document = Document(
            filename=filename,
            file_path=file_path,
            content_type=content_type,
            source_hash=source_hash,
            doc_type=doc_type,
            status=DocumentStatus.PROCESSING.value,
        )
        db.add(document)
        db.flush()
        audit_service.record(
            db, entity_type="document", entity_id=document.id, action="uploaded",
            after_value={"filename": filename, "doc_type": doc_type},
        )

        try:
            self._extract_and_route(db, document, content, content_type)
        except Exception:
            document.status = DocumentStatus.FAILED.value
            audit_service.record(db, entity_type="document", entity_id=document.id, action="failed")
            db.commit()
            raise

        db.commit()
        db.refresh(document)
        return document

    def _extract_and_route(self, db: Session, document: Document, content: bytes, content_type: str) -> None:
        field_specs = get_field_schema(document.doc_type)

        extraction = self.extractor.extract(content, content_type, document.doc_type)
        scored_fields = self.scorer.score_all(field_specs, extraction.fields)

        for sf in scored_fields:
            db.add(
                ExtractedField(
                    document_id=document.id,
                    field_name=sf.field_name,
                    field_value=sf.value,
                    raw_confidence=sf.raw_confidence,
                    final_confidence=sf.final_confidence,
                    extraction_method=extraction.extraction_method,
                    model_used=extraction.model_used,
                )
            )
        document.status = DocumentStatus.EXTRACTED.value
        audit_service.record(
            db, entity_type="document", entity_id=document.id, action="extracted",
            after_value={"model_used": extraction.model_used, "field_count": len(scored_fields)},
        )

        field_values = {sf.field_name: sf.value for sf in scored_fields}
        rule_outcomes = self.rules_engine.validate(document.doc_type, field_values)
        for outcome in rule_outcomes:
            db.add(
                ValidationResult(
                    document_id=document.id,
                    rule_name=outcome.rule_name,
                    field_name=outcome.field_name,
                    passed=outcome.passed,
                    message=outcome.message,
                    severity=outcome.severity,
                )
            )
        document.status = DocumentStatus.VALIDATED.value
        audit_service.record(
            db, entity_type="document", entity_id=document.id, action="validated",
            after_value={"rules_evaluated": len(rule_outcomes),
                         "rules_failed": sum(1 for o in rule_outcomes if not o.passed)},
        )

        self._route(db, document, scored_fields, rule_outcomes)

    def _route(self, db: Session, document: Document, scored_fields, rule_outcomes) -> None:
        threshold = self.settings.confidence_auto_approve_threshold

        low_confidence = [sf for sf in scored_fields if sf.final_confidence < threshold]
        failed_errors = [o for o in rule_outcomes if not o.passed and o.severity == "error"]

        if not low_confidence and not failed_errors:
            document.status = DocumentStatus.AUTO_APPROVED.value
            audit_service.record(db, entity_type="document", entity_id=document.id, action="auto_approved")
            return

        reason_parts = []
        if low_confidence:
            names = ", ".join(f"{sf.field_name} ({sf.final_confidence:.2f})" for sf in low_confidence)
            reason_parts.append(f"{len(low_confidence)} field(s) below confidence threshold: {names}")
        if failed_errors:
            names = ", ".join(o.rule_name for o in failed_errors)
            reason_parts.append(f"{len(failed_errors)} validation error(s): {names}")

        priority = 10 if failed_errors else 0  # validation errors jump the queue ahead of pure low-confidence
        hitl_service.enqueue(db, document, reason="; ".join(reason_parts), priority=priority)
