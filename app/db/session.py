"""
Engine + session factory, and the FastAPI dependency that hands each request
its own DB session and guarantees it's closed afterward.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # detects dropped connections (e.g. after DB restart) before using them
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: `db: Session = Depends(get_db)`.

    Using a generator + try/finally (not a plain return) is what makes FastAPI
    treat this as a context manager — the session is closed even if the route
    raises an exception, so we never leak connections under errors.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
