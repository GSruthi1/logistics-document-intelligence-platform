# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

# System dependencies pytesseract and pdf2image need at runtime.
# These are NOT pip-installable — pdf2image shells out to poppler's
# `pdftoppm`, and pytesseract shells out to the `tesseract` binary. Missing
# this step is the single most common "works locally, breaks in Docker"
# failure for this kind of project, because pip install succeeds either way
# and the error only shows up the first time a PDF/image actually gets
# processed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy just the requirements file first so Docker's layer cache is reused on
# every rebuild that only changes application code — `pip install` (the slow
# step) only reruns when requirements.txt itself changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as a non-root user — a container root user is a root user on any host
# path it can reach via a volume mount or a kernel exploit; no reason to
# accept that risk for a process that only needs to bind a port and write to
# its own storage dir.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/storage/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# $PORT falls back to 8000 for environments (local Docker, docker-compose)
# that don't set it, so the same image works unmodified on a host that
# injects a dynamic PORT (Railway) and one that doesn't.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
