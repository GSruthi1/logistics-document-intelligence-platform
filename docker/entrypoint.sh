#!/bin/sh
# Runs pending Alembic migrations before the app starts, then hands off to
# whatever CMD was passed (uvicorn in production, pytest in CI — see
# docker-compose.yml and ci.yml). Doing this here rather than manually before
# every deploy is what makes "deploy = docker run" actually true instead of
# "deploy = docker run, and also remember to migrate first".
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting: $@"
exec "$@"
