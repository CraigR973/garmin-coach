FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

WORKDIR /app

# pg_dump refuses to dump a server newer than itself. Supabase runs PostgreSQL
# 17, but bookworm's own `postgresql-client` is 15 — so pinning the base image
# to slim-bookworm (from a floating `3.12-slim` tag that had moved on to trixie)
# silently broke the nightly backup with "aborting because of server version
# mismatch". Take the 17 client from PGDG so the pinned digest above can stay.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && install -d /etc/apt/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /etc/apt/keyrings/pgdg.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

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
