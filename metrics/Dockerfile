# robotframework-metrics dashboard
# Generates HTML metrics reports from Robot Framework output.xml files
# and serves them via nginx.
#
# Usage (standalone):
#   docker build -t rf-metrics ./metrics
#   docker run -v ./results:/app/results:ro -p 8089:80 rf-metrics

FROM python:3.13-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir robotframework-metrics==3.3.3

COPY nginx.conf /etc/nginx/sites-available/default
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Pre-create directories
RUN mkdir -p /app/results /var/www/html/metrics

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:80/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
