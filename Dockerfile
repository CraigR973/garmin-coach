FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/src/ ./src/
COPY migrations/ ./migrations/
COPY apps/api/alembic.ini ./alembic.ini

# Rewrite script_location from the monorepo-relative path
# (%(here)s/../../migrations) to the container layout (/app/migrations).
RUN sed -i 's|%(here)s/\.\./\.\./migrations|/app/migrations|g' alembic.ini

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Railway routes inbound traffic to the EXPOSE'd port. Without this,
# Railway's healthcheck can't reach the service ("service unavailable").
EXPOSE 8000

# Apply pending Alembic migrations before starting the API. If migrations
# fail the container exits — Railway's restartPolicy will retry, surfacing
# the failure in logs rather than masking it with a broken-but-up service.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
