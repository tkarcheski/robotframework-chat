FROM apache/superset:6.0.0

USER root
# Superset 6.0 runs from a uv-managed virtualenv at /app/.venv. Plain `pip
# install` lands in /usr/local system site-packages, which the runtime python
# never sees, so install into the venv explicitly via uv instead.
RUN uv pip install --python /app/.venv/bin/python psycopg2-binary redis flask-cors
USER superset
