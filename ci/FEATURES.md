# CI Features Matrix

> **Note:** The canonical feature tracker is `ai/FEATURES.md`. This file
> tracks CI-specific features and test coverage only.

Feature inventory with implementation status and test coverage.

## Pipeline Features

| Feature | Script | Tests | Status |
|---------|--------|-------|--------|
| Ruff lint + format checks | `ci/lint.sh` | - | Active |
| Robot Framework test execution | `ci/test.sh` | - | Active |
| Dynamic pipeline generation | `ci/generate.sh` | - | Active |
| Repo metrics report | `ci/report.sh` | - | Active |
| GitHub mirror sync | `ci/sync.sh` | - | Active |
| Superset deployment | `ci/deploy.sh` | - | Active |
| Dashboard tests (pytest) | `ci/test_dashboard.sh` | - | Active |
| Dashboard tests (Playwright) | `ci/test_dashboard.sh` | - | Active |
| AI code review | `ci/review.sh` | - | Active |
