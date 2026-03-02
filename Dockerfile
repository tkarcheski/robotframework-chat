# Application Docker image for robotframework-chat
#
# Multi-stage build: builder installs the package, runtime copies results.
# Entry point is bash — users run robot, pytest, or explore interactively.
#
# Usage:
#   # Interactive shell
#   docker run -it ghcr.io/tkarcheski/robotframework-chat:1.0.1
#
#   # Run math tests against local Ollama
#   docker run --rm \
#     -e OLLAMA_ENDPOINT=http://host.docker.internal:11434 \
#     ghcr.io/tkarcheski/robotframework-chat:1.0.1 \
#     robot -d /results robot/math/tests/
#
#   # Dry-run validation (no Ollama needed)
#   docker run --rm ghcr.io/tkarcheski/robotframework-chat:1.0.1 \
#     robot --dryrun -d /results robot/

# ── Builder stage ────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.7 AS uv

FROM python:3.13-slim AS builder

# Copy uv binary from official image (no pip/network needed for uv itself)
COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /build

# Copy build inputs (readme.md required by hatchling for wheel metadata)
COPY pyproject.toml readme.md ./
COPY src/ src/

# Install the package and all runtime dependencies into the system site-packages
RUN uv pip install --system --no-cache .

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.13-slim

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Bundle test suites, config, and environment template
COPY robot/ robot/
COPY config/ config/
COPY .env.example .env.example

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
