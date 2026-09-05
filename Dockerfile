# =============================================================================
# TRUE STORY  ·  python services
# =============================================================================
# One image, three entrypoints. The API, the clearance tool server and the
# webhook receiver are separate Cloud Run services with different identities
# and different scaling, and they share this image because they share the
# domain layer.
#
#   docker build -t truestory .
#   docker run -p 8080:8080 truestory
# =============================================================================

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── dependencies ─────────────────────────────────────────────────────────────
# Copied first so a source change does not invalidate the dependency layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ── application ──────────────────────────────────────────────────────────────
COPY src/ ./src/
COPY policy/ ./policy/
COPY schemas/ ./schemas/
COPY a2a/ ./a2a/
COPY pyproject.toml README.md LICENSE ./

RUN pip install --no-cache-dir -e .

# The demo screenplay ships in the image so the hosted URL has something to
# show without an upload. It is our own work, so there is no rights question.
COPY demo/ ./demo/

# ── runtime user ─────────────────────────────────────────────────────────────
# Nothing here needs root, and this service handles pre release scripts.
RUN useradd --create-home --uid 1000 truestory \
    && chown -R truestory:truestory /app
USER truestory

ENV PORT=8080 \
    TRUESTORY_MODE=live \
    TRUESTORY_ENV=cloud-run \
    PYTHONPATH=/app/src

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8080)}/healthz')" || exit 1

# Default entrypoint is the API. Cloud Run overrides the command for the other
# two services, see the deploy targets in the Makefile.
#
# One worker, deliberately. A run's live progress (_RUNS, _STREAMS,
# _PIPELINES in api/main.py) lives in that worker's own process memory, not
# in Firestore -- only the initial placeholder and the final state are ever
# persisted. With more than one worker, Render's proxy round robins requests
# between processes that share nothing: a status poll or SSE connection that
# lands on the worker that didn't start the run finds no record of it in
# memory and falls back to the Firestore placeholder, reporting a run that
# is actively executing elsewhere as an archived one stuck at QUEUED.
# Observed live: a fresh run alternated between real progress and "restored
# from durable storage" depending which of the two workers answered.
CMD exec uvicorn truestory.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
