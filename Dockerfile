FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Hosted read-aloud voice (Batch 116 follow-up, DECISIONS #190): self-hosted
# Piper instead of a third-party TTS API, so brief text never leaves our own
# infra even when a user opts into the hosted voice. The `piper` console
# script + its espeak-ng-phonemize dependency come from the pip package;
# the voice model itself (.onnx + .onnx.json) is baked into the image here
# so a synthesize call never needs an outbound download at runtime.
RUN mkdir -p /app/voices \
    && curl -fsSL -o /app/voices/en_GB-alan-medium.onnx \
       https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx \
    && curl -fsSL -o /app/voices/en_GB-alan-medium.onnx.json \
       https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json

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
