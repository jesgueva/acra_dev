# ACRA MES backend — FastAPI/uvicorn (ACR-42 / A10-1).
#
# Python 3.13 matches backend/pyproject.toml's requires-python; tests/test_packaging.py fails the
# build if this drifts from the declared version.
#
# Build from the REPO ROOT so the build context can see nothing but backend/:
#   docker build -f backend/Dockerfile -t acra-backend backend/
#
# The same image serves three compose roles — the API, the one-shot `migrate` job, and the opt-in
# `seed` job — by overriding the command. They must share an image or the migration could run
# against a different dependency set than the app.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ----------------------------------------------------------------------------- dependencies
# Copied and installed before the source so an application-code change does not invalidate the
# dependency layer. Installs from the LOCK, not requirements.txt, so the image resolves exactly
# what CI resolves.
FROM base AS deps

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# ----------------------------------------------------------------------------- runtime
FROM base AS runtime

# curl is needed by the compose healthcheck; kept to the runtime stage only.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# Run as an unprivileged user. Done after COPY so the copied tree is owned correctly.
RUN useradd --create-home --uid 1001 acra \
    && chown -R acra:acra /app
USER acra

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
