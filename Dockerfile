# Multi-stage build. The goal: a small final image, because image size affects
# pull time, cold-start time, and your cloud bill.
#
#   Build stage: has compilers, headers, dev tools — discarded.
#   Runtime stage: only what running the app actually needs.
#
# Compare `docker images` before and after you switch to this pattern. The
# difference is usually 700 MB vs 150 MB, and being able to explain *why* is a
# solid interview answer.

# ---------- build ----------
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for any wheel that needs compiling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install into an isolated prefix so we can copy just the result.
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[postgres,s3]"

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="kisanmandi" \
      org.opencontainers.image.description="Mandi price intelligence for Indian farmers" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    DATA_DIR=/app/data

# Run as a non-root user. Trivy will flag you for this if you don't.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
RUN mkdir -p /app/data && chown -R app:app /app

USER app

# Basic liveness check so orchestrators know whether to restart the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)" \
    || exit 1

EXPOSE 8000

ENTRYPOINT ["kisanmandi"]
CMD ["--help"]
