FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Hosted read-aloud voice (Batch 116 follow-up, DECISIONS #190/#191/#196/#210):
# self-hosted Piper instead of a third-party TTS API, so brief text never
# leaves our own infra even when a user opts into the hosted voice. The
# `piper` console script comes from the pip package; the voice model itself
# (.onnx + .onnx.json) is baked into the image here so a synthesize call
# never needs an outbound download at runtime. `medium` quality (not `low`):
# a live benchmark on Railway's CPU with realistic full-brief-length text
# (~2000 chars) showed `low` (23s) wasn't dramatically faster than `medium`
# (33s) — the earlier timeout was real, but low quality's speed advantage on
# short text didn't hold at brief length, so it's not worth the noticeably
# more robotic voice. Both fit comfortably inside PIPER_TIMEOUT_SECONDS.
# Voice picked from a live side-by-side comparison of 6 candidates (Craig
# listened to real synthesized samples via an artifact, not a guess): `high`
# quality (Ryan) sounded best but measured ~95s for a full brief in an
# isolated benchmark — too slow given real production requests run ~2.4x
# slower under load (a `medium` request once took 82s vs a 34s isolated
# benchmark) — so the choice stayed within `medium` tier, where Northern
# English Male benchmarked fastest (27s) of the three medium options tried.
RUN mkdir -p /app/voices \
    && curl -fsSL -o /app/voices/en_GB-northern_english_male-medium.onnx \
       https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx \
    && curl -fsSL -o /app/voices/en_GB-northern_english_male-medium.onnx.json \
       https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx.json

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
