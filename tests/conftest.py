"""
Shared pytest fixtures.

IMPORTANT ordering detail: we point DATABASE_URL at the test database and
clear get_settings' cache *before* importing anything from `app`. Settings
are read once and memoized (`@lru_cache` in app/core/config.py) — if any
`app.*` module imported earlier in the test session, the engine in
app/db/session.py would already be bound to the dev database and every test
would silently run against real data. This is a real footgun with
lru_cache + settings in FastAPI apps, so it's worth understanding, not just
copy-pasting.
"""
import io
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL_TEST", "postgresql+psycopg2://ldip:ldip@localhost:5432/ldip_test"
)

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db, get_document_service
from app.core.config import get_settings
from app.extraction.base import ExtractionOutput, Extractor, FieldExtractionResult
from app.main import app
from app.models import Base
from app.scoring.confidence_scorer import ConfidenceScorer
from app.services.document_service import DocumentService
from app.storage.file_storage import LocalFileStorage
from app.validation.rules_config import get_rules_engine

get_settings.cache_clear()  # force re-read now that DATABASE_URL is pinned to the test DB


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(get_settings().database_url, future=True)
    # create_all/drop_all instead of running Alembic here: this suite tests
    # application *behavior* against the schema, not the migrations
    # themselves — migration correctness is verified separately (`alembic
    # upgrade head` / `downgrade -1` against a real Postgres, done during
    # development and re-checked in CI's migration step).
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """One test = one transaction that's always rolled back. This gives each
    test a clean database without the cost of recreating tables per test.
    """
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, future=True)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


class FakeExtractor(Extractor):
    """Deterministic stand-in for the real LLM extractor. Tests set
    `FakeExtractor.next_output` to control exactly what a "call" returns,
    so extraction-pipeline behavior (scoring, validation, routing) can be
    tested without hitting Anthropic/OpenAI or depending on model output
    variance.
    """

    def __init__(self):
        self.next_output: ExtractionOutput | None = None
        self.calls: list[tuple[str, str]] = []

    def extract(self, file_bytes: bytes, content_type: str, doc_type: str) -> ExtractionOutput:
        self.calls.append((content_type, doc_type))
        if self.next_output is None:
            raise RuntimeError("FakeExtractor.next_output was not set before calling extract()")
        return self.next_output


@pytest.fixture()
def fake_extractor():
    return FakeExtractor()


@pytest.fixture()
def client(db_session, fake_extractor, tmp_path):
    document_service = DocumentService(
        storage=LocalFileStorage(str(tmp_path)),
        extractor=fake_extractor,
        scorer=ConfidenceScorer(),
        rules_engine=get_rules_engine(),
    )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_document_service] = lambda: document_service

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def make_field(name: str, value: str | None, confidence: float) -> FieldExtractionResult:
    return FieldExtractionResult(field_name=name, value=value, confidence=confidence)


def png_bytes(color=(255, 255, 255), size=(50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()
