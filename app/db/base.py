"""
Declarative base for all ORM models.

Kept in its own module (not inside session.py, not inside main.py) so that
Alembic's env.py can `import app.db.base` and see every model's metadata
without also importing the FastAPI app, the API routes, or anything that
needs a running event loop. This is a common gotcha: if your migrations file
imports your app, `alembic revision --autogenerate` can crash trying to spin
up things migrations don't need.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
