# Application Docker image for robotframework-chat
#
# Dev-ready image: includes make, uv, and the full project so users can
# run any Makefile target inside the container.
#
# Usage:
#   # Interactive shell
#   docker run -it ghcr.io/tkarcheski/robotframework-chat:1.4.2
#
#   # Run math tests against local Ollama
#   docker run --rm \
#     -e OLLAMA_ENDPOINT=http://host.docker.internal:11434 \
#     ghcr.io/tkarcheski/robotframework-chat:1.4.2 \
#     make robot-math
#
#   # Dry-run validation (no Ollama needed)
#   docker run --rm ghcr.io/tkarcheski/robotframework-chat:1.4.2 \
#     make robot-dryrun
#
#   # Full stack with Superset frontend
#   docker compose up -d
#   docker compose exec app make robot-dryrun

# ── UV binary ──────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.7 AS uv

# ── Runtime stage ──────────────────────────────────────────────────
FROM python:3.13-slim

# System tools needed for dev workflow
RUN apt-get update && apt-get install -y --no-install-recommends \
    make \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from official image
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile + manifest first (cache-friendly layer)
COPY pyproject.toml uv.lock readme.md ./

# Copy source and project files
COPY src/ src/
COPY robot/ robot/
COPY config/ config/
COPY scripts/ scripts/
COPY tests/ tests/
COPY ci/ ci/
COPY Makefile tasks.py .env.example ./

# Install all dependencies (dev + superset extras for full make target support)
RUN uv sync --frozen --extra dev --extra superset

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash rfc && \
    mkdir -p /results && \
    chown -R rfc:rfc /app /results

USER rfc

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLLAMA_ENDPOINT=http://localhost:11434 \
    DEFAULT_MODEL=llama3 \
    OLLAMA_TIMEOUT=300

LABEL org.opencontainers.image.source="https://github.com/tkarcheski/robotframework-chat" \
      org.opencontainers.image.description="Robot Framework test harness for LLM testing" \
      org.opencontainers.image.licenses="Apache-2.0"

CMD ["bash"]
