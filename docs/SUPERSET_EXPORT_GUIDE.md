# Superset Dashboard Export Guide

Complete guide for exporting, importing, and backing up Apache Superset
dashboards in the robotframework-chat project. Covers the browser UI, REST API,
CLI, and automated backup approaches.

For initial stack setup and dashboard configuration, see
[SUPERSET_SETUP.md](SUPERSET_SETUP.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Dashboard Inventory](#dashboard-inventory)
4. [UI Export](#ui-export)
   - [Exporting a Single Dashboard](#exporting-a-single-dashboard)
   - [Exporting Multiple Dashboards](#exporting-multiple-dashboards)
   - [Export File Structure](#export-file-structure)
5. [REST API Export](#rest-api-export)
   - [Authentication](#authentication)
   - [Listing Dashboards](#listing-dashboards)
   - [Exporting by Dashboard ID](#exporting-by-dashboard-id)
   - [Exporting All Dashboards](#exporting-all-dashboards)
6. [CLI Export](#cli-export)
   - [Export All Dashboards](#export-all-dashboards)
   - [Export to a Timestamped File](#export-to-a-timestamped-file)
   - [Export Datasets Only](#export-datasets-only)
7. [Importing Dashboards](#importing-dashboards)
   - [UI Import](#ui-import)
   - [REST API Import](#rest-api-import)
   - [CLI Import](#cli-import)
8. [Automation](#automation)
   - [Makefile Targets](#makefile-targets)
   - [Scheduled Backups with Cron](#scheduled-backups-with-cron)
   - [CI Pipeline Integration](#ci-pipeline-integration)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The project ships three pre-configured Superset dashboards, created
automatically by `superset/bootstrap_dashboards.py` during `make bootstrap`.
While the bootstrap recreates dashboards from scratch, there are scenarios
where you want to export the current state instead:

- Preserving customizations made through the Superset UI
- Migrating dashboards between environments (dev, staging, production)
- Creating backups before upgrades
- Sharing dashboard configurations with team members

| Method   | Best For                     | Format | Requires                    |
|----------|------------------------------|--------|-----------------------------|
| UI       | One-off manual exports       | ZIP    | Browser access to Superset  |
| REST API | Scripted / programmatic      | ZIP    | `curl`, auth token          |
| CLI      | Container-level bulk exports | ZIP    | `docker compose exec` access|

---

## Prerequisites

The Docker Compose stack must be running with Superset bootstrapped:

```bash
make docker-up
make bootstrap
```

Required environment variables (set in `.env`, see `.env.example`):

| Variable                  | Default     | Purpose                    |
|---------------------------|-------------|----------------------------|
| `SUPERSET_ADMIN_USER`     | `admin`     | Superset login username    |
| `SUPERSET_ADMIN_PASSWORD` | `changeme`  | Superset login password    |
| `SUPERSET_PORT`           | `8088`      | Host port for Superset UI  |
| `POSTGRES_PASSWORD`       | `changeme`  | Needed when importing      |

Verify Superset is healthy:

```bash
curl -s http://localhost:${SUPERSET_PORT:-8088}/health
# Expected: "OK"
```

---

## Dashboard Inventory

These three dashboards are created by `make bootstrap`:

| Dashboard                     | Slug            | Charts | URL                                                              |
|-------------------------------|-----------------|--------|------------------------------------------------------------------|
| Robot Framework Test Results  | `rfc-results`   | 10     | `http://localhost:8088/superset/dashboard/rfc-results/`          |
| Pipeline Health               | `rfc-pipelines` | 6      | `http://localhost:8088/superset/dashboard/rfc-pipelines/`        |
| Model Analytics               | `rfc-models`    | 10     | `http://localhost:8088/superset/dashboard/rfc-models/`           |

Replace `8088` with your `SUPERSET_PORT` value if different.

---

## UI Export

### Exporting a Single Dashboard

1. Navigate to `http://localhost:${SUPERSET_PORT:-8088}` and log in.
2. Go to **Dashboards** in the top navigation.
3. Find the target dashboard (e.g., "Robot Framework Test Results").
4. Click the three-dot menu (kebab icon) on the dashboard row.
5. Click **Export**.
6. A ZIP file downloads containing the dashboard, its charts, datasets,
   and database connection metadata.

### Exporting Multiple Dashboards

1. On the Dashboards list page, check the checkboxes for each dashboard.
2. Click **Actions** at the top of the list.
3. Select **Export**.
4. A single ZIP file containing all selected dashboards downloads.

### Export File Structure

The exported ZIP contains YAML definitions organized by type:

```
dashboard_export/
  metadata.yaml
  dashboards/
    Robot_Framework_Test_Results.yaml
  charts/
    Pass_Rate_Over_Time.yaml
    Model_Comparison_Pass_Rate.yaml
    ...
  datasets/
    Robot_Framework_Results/
      test_runs.yaml
      test_results.yaml
      ...
  databases/
    Robot_Framework_Results.yaml
```

> **Note:** Database connection passwords are never included in exports
> (security measure). You must supply them when importing.

---

## REST API Export

The Superset REST API provides full programmatic control over exports.
This project has CSRF protection disabled (`WTF_CSRF_ENABLED = False` in
`superset/superset_config.py`), so no CSRF token is needed.

For live API exploration, visit the Swagger UI at
`http://localhost:8088/swagger/v1`.

### Authentication

Get a JWT access token:

```bash
TOKEN=$(curl -s -X POST \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/security/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "'"${SUPERSET_ADMIN_USER:-admin}"'",
    "password": "'"${SUPERSET_ADMIN_PASSWORD:-changeme}"'",
    "provider": "db"
  }' | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

echo "Token: ${TOKEN:0:20}..."
```

> **Note:** JWT tokens expire after a short period. Re-run the authentication
> step if you receive `401 Unauthorized` errors.

### Listing Dashboards

Retrieve dashboard IDs (needed for export):

```bash
curl -s -X GET \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/dashboard/" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

After a fresh bootstrap, the three project dashboards typically have IDs
1, 2, and 3. To find a specific dashboard by slug:

```bash
curl -s -X GET \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/dashboard/?q=(filters:!((col:slug,opr:eq,value:rfc-results)))" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys, json; r=json.load(sys.stdin); print(r['result'][0]['id'])"
```

### Exporting by Dashboard ID

```bash
# Export a single dashboard (returns a ZIP file)
curl -s -X GET \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/dashboard/export/?q=!(1)" \
  -H "Authorization: Bearer $TOKEN" \
  -o rfc-results-export.zip
```

> **Note:** The `q` parameter uses [Rison](https://github.com/Nanonid/rison)
> encoding, which is the Superset standard for query parameters.

### Exporting All Dashboards

```bash
# Export all three project dashboards
curl -s -X GET \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/dashboard/export/?q=!(1,2,3)" \
  -H "Authorization: Bearer $TOKEN" \
  -o all-dashboards-export.zip
```

---

## CLI Export

Run commands inside the Superset container via `docker compose exec`.
The service name is `superset` (defined in `docker-compose.yml`).

### Export All Dashboards

```bash
# Export all dashboards inside the container
docker compose exec superset superset export-dashboards \
  -f /tmp/dashboard_export.zip

# Copy the export to the host
docker compose cp superset:/tmp/dashboard_export.zip ./backups/
```

### Export to a Timestamped File

```bash
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

docker compose exec superset superset export-dashboards \
  -f "/tmp/superset_dashboards_${TIMESTAMP}.zip"

docker compose cp \
  "superset:/tmp/superset_dashboards_${TIMESTAMP}.zip" ./backups/
```

### Export Datasets Only

```bash
docker compose exec superset superset export-datasources \
  -f /tmp/dataset_export.zip

docker compose cp superset:/tmp/dataset_export.zip ./backups/
```

---

## Importing Dashboards

### UI Import

1. Navigate to **Dashboards** in Superset.
2. Click the **+** button, then **Import Dashboard**.
3. Select the ZIP file.
4. Toggle **Overwrite** if re-importing existing dashboards.
5. Enter the database password when prompted (`POSTGRES_PASSWORD`, default
   `changeme`).
6. Click **Import**.

### REST API Import

```bash
curl -s -X POST \
  "http://localhost:${SUPERSET_PORT:-8088}/api/v1/dashboard/import/" \
  -H "Authorization: Bearer $TOKEN" \
  -F "formData=@all-dashboards-export.zip" \
  -F "overwrite=true" \
  -F 'passwords={"databases/Robot_Framework_Results.yaml":"'"${POSTGRES_PASSWORD:-changeme}"'"}'
```

The `passwords` field maps database YAML paths (from the export ZIP) to
their connection passwords. This is required because Superset strips
passwords from exports.

### CLI Import

```bash
# Copy the ZIP into the container
docker compose cp ./backups/dashboard_export.zip superset:/tmp/

# Import
docker compose exec superset superset import-dashboards \
  -p /tmp/dashboard_export.zip \
  -u "${SUPERSET_ADMIN_USER:-admin}"
```

---

## Automation

### Makefile Targets

Two convenience targets are provided in the project Makefile:

```bash
# Export dashboards to backups/ with a timestamped filename
make superset-export

# Import dashboards from a ZIP file
make superset-import FILE=backups/superset_export_20260225_120000.zip
```

### Scheduled Backups with Cron

Add a daily export to your crontab:

```bash
# crontab -e
0 2 * * * cd /path/to/robotframework-chat && make superset-export >> /var/log/superset-backup.log 2>&1
```

### CI Pipeline Integration

Add `make superset-export` as a CI step to create versioned backups.

Example GitHub Actions job:

```yaml
backup-superset:
  runs-on: self-hosted
  if: github.event_name == 'schedule'
  steps:
    - uses: actions/checkout@v4
    - run: make superset-export
    - uses: actions/upload-artifact@v4
      with:
        name: superset-backups
        path: backups/
        retention-days: 30
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` on API calls | Token expired. Re-run the [authentication step](#authentication) to get a fresh token. |
| Empty export / no dashboards | Run `make bootstrap` first to create the dashboards. |
| Import fails with "database password required" | Supply the `passwords` field in the API call, or enter it in the UI prompt. See [REST API Import](#rest-api-import). |
| `superset export-dashboards` hangs | Ensure Superset is healthy: `docker compose ps superset` should show "Up (healthy)". |
| Import overwrites existing dashboards | Use `overwrite=true` intentionally. Omit the flag to skip existing items. |
| ZIP file has no extension | The CLI may omit `.zip`. Rename: `mv dashboard_export_* dashboard_export.zip`. |
| Connection refused on port 8088 | Stack not running. Start with `make docker-up`. |

For general Superset issues (container startup, database connectivity),
see the Troubleshooting section in
[SUPERSET_SETUP.md](SUPERSET_SETUP.md).
