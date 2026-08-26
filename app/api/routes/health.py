from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + DB connectivity check. Azure App Service / Railway both
    poll a health endpoint to decide whether a deployment is actually up —
    without a real `SELECT 1`, this would report healthy even if the app
    can't reach Postgres, which defeats the point.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
