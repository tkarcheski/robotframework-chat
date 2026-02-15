FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy project files
COPY pyproject.toml ./
COPY src/ src/
COPY dashboard/ dashboard/
COPY config/ config/

# Install the project with dashboard and superset extras
RUN uv pip install --system --no-cache ".[dashboard,superset]"

EXPOSE 8050

CMD ["python", "-m", "dashboard.cli", "--host", "0.0.0.0", "--port", "8050"]
