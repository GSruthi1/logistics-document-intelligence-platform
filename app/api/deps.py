"""
FastAPI dependency wiring. This is the one place that constructs concrete
implementations (LLMExtractor, LocalFileStorage/AzureBlobFileStorage) and
hands them to DocumentService through its abstract interfaces. Routes never
import a concrete extractor or storage class directly — only this module and
DocumentService's constructor know those concrete types exist.
"""
from functools import lru_cache

from app.core.config import get_settings
from app.db.session import get_db  # re-exported for convenience: `from app.api.deps import get_db`
from app.extraction.llm_extractor import LLMExtractor
from app.scoring.confidence_scorer import ConfidenceScorer
from app.services.document_service import DocumentService
from app.storage.file_storage import get_file_storage
from app.validation.rules_config import get_rules_engine

__all__ = ["get_db", "get_document_service"]


@lru_cache
def get_document_service() -> DocumentService:
    settings = get_settings()
    return DocumentService(
        storage=get_file_storage(settings),
        extractor=LLMExtractor(settings),
        scorer=ConfidenceScorer(),
        rules_engine=get_rules_engine(),
        settings=settings,
    )
