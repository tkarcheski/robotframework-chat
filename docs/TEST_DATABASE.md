# Test Results Database

This document describes the SQLite database for storing and analyzing test results with Git LFS support.

## Overview

The test database provides persistent storage for Robot Framework test results, enabling:
- Historical tracking of model performance
- Comparison between models over time
- Analysis of test trends and patterns
- Export for external analysis

## Database Location

**File**: `data/test_history.db` (tracked with Git LFS)

## Schema

### Tables

#### `test_runs`
One row per pipeline execution:
- `id`: Primary key
- `timestamp`: When the test ran
- `model_name`: LLM model used (e.g., llama3, mistral)
- `model_release_date`: Model release date from metadata
- `model_parameters`: Model size (e.g., 8B, 70B)
- `test_suite`: Test suite name (math, docker, safety)
- `gitlab_commit`: Git commit SHA
- `gitlab_branch`: Git branch name
- `gitlab_pipeline_url`: Link to CI pipeline
- `runner_id`: CI runner identifier
- `runner_tags`: Runner capabilities
- `total_tests`, `passed`, `failed`, `skipped`: Test counts
- `duration_seconds`: Test execution time

#### `test_results`
Individual test case results:
- `run_id`: Foreign key to test_runs
- `test_name`: Test case name
- `test_status`: PASS, FAIL, or SKIP
- `score`: Graded score (0 or 1) if applicable
- `question`: Test question/prompt
- `expected_answer`: Expected correct answer
- `actual_answer`: Model's response
- `grading_reason`: Explanation from grader

#### `models`
Model metadata:
- `name`: Model identifier
- `full_name`: Human-readable name
- `organization`: Model creator
- `release_date`: Model release date
- `parameters`: Model size
- `last_tested`: Timestamp of last test

## Usage

### Initialize Database

```bash
uv run python -m rfc.test_database init
```

### Import Test Results

After running tests, import the results:

```bash
# Import single output.xml
uv run python scripts/import_test_results.py results/math/output.xml

# Import all output.xml files in directory (recursive)
uv run python scripts/import_test_results.py results/ --recursive

# Import with specific model name
uv run python scripts/import_test_results.py results/math/output.xml --model llama3.1
```

### Query Results

#### View Performance Summary

```bash
uv run python scripts/query_results.py performance
```

Output:
```
Model Performance Summary
================================================================================
Model                | Runs | Pass Rate | Passed  | Failed | Avg Duration
llama3               | 15   | 87.5%     | 131     | 19     | 45.2s
mistral              | 12   | 84.2%     | 101     | 19     | 42.8s
codellama            | 8    | 91.3%     | 63      | 6      | 38.5s
```

#### View Recent Runs

```bash
# Show last 10 runs
uv run python scripts/query_results.py recent

# Show last 20 runs
uv run python scripts/query_results.py recent --limit 20
```

#### View Test History

```bash
# Show history for specific test
uv run python scripts/query_results.py history "IQ 100 Basic Addition"
```

#### Compare Models

```bash
uv run python scripts/query_results.py compare
```

#### Export to JSON

```bash
# Export full database
uv run python scripts/query_results.py export

# Export to specific file
uv run python scripts/query_results.py export --output my_export.json
```

### Programmatic Access

```python
from rfc.test_database import TestDatabase

# Initialize
db = TestDatabase()

# Get performance stats
stats = db.get_model_performance()
for stat in stats:
    print(f"{stat['model_name']}: {stat['avg_pass_rate']:.1f}%")

# Get recent runs
runs = db.get_recent_runs(limit=5)

# Get test history
history = db.get_test_history("IQ 100 Basic Addition")

# Export to JSON
db.export_to_json("export.json")
```

## CI/CD Integration

The GitLab CI pipeline automatically imports test results after each run:

1. Tests execute and produce `output.xml`
2. `import-test-results` job parses and imports into database
3. Database artifact is saved with each pipeline
4. Database is committed back to repository (main branch only)

### Automatic Import

The pipeline runs:
```bash
uv run python scripts/import_test_results.py results/math/output.xml
uv run python scripts/import_test_results.py results/docker/output.xml
uv run python scripts/import_test_results.py results/safety/output.xml
```

## Git LFS Configuration

The database is tracked with Git LFS:

```
# .gitattributes
data/*.db filter=lfs diff=lfs merge=lfs -text
```

### Working with LFS

```bash
# Pull LFS files
git lfs pull

# Check LFS status
git lfs status

# View LFS tracked files
git lfs ls-files
```

## Database Maintenance

### Size Management

The database grows with each test run. Expected sizes:
- 100 test runs: ~1-2 MB
- 1,000 test runs: ~10-15 MB
- 10,000 test runs: ~100-150 MB

### Cleanup Old Data

To archive old data:

```bash
# Export old data
uv run python scripts/query_results.py export --output archive_2024.json

# Vacuum database to reclaim space
sqlite3 data/test_history.db "VACUUM;"
```

### Backup

The database is backed up via Git LFS. For additional backup:

```bash
# Create timestamped backup
cp data/test_history.db "data/test_history_$(date +%Y%m%d).db"
```

## Analysis Examples

### Pass Rate Trend

```python
from rfc.test_database import TestDatabase
import matplotlib.pyplot as plt

db = TestDatabase()

# Get runs for a specific model
runs = db.get_recent_runs(limit=100)
llama3_runs = [r for r in runs if r['model_name'] == 'llama3']

# Extract dates and pass rates
dates = [r['timestamp'] for r in llama3_runs]
pass_rates = [r['passed'] / r['total_tests'] * 100 for r in llama3_runs]

plt.plot(dates, pass_rates)
plt.title('Llama 3 Pass Rate Over Time')
plt.xlabel('Date')
plt.ylabel('Pass Rate (%)')
plt.show()
```

### Model Comparison

```python
from rfc.test_database import TestDatabase

db = TestDatabase()
stats = db.get_model_performance()

print("Model Ranking by Pass Rate:")
for i, stat in enumerate(sorted(stats, key=lambda x: x['avg_pass_rate'], reverse=True), 1):
    print(f"{i}. {stat['model_name']}: {stat['avg_pass_rate']:.1f}%")
```

## Troubleshooting

### Database Locked

If you get "database is locked" errors:
```bash
# Check for other processes
lsof data/test_history.db

# Wait and retry, or copy database
cp data/test_history.db data/test_history_temp.db
# Use temp database
```

### Corrupted Database

If the database becomes corrupted:
```bash
# Try to recover
sqlite3 data/test_history.db ".recover" > recover.sql
rm data/test_history.db
sqlite3 data/test_history.db < recover.sql
```

### LFS Issues

If Git LFS is not working:
```bash
# Install Git LFS
git lfs install

# Pull LFS files
git lfs pull

# Track database
git lfs track "data/*.db"
```

## Best Practices

1. **Import regularly**: Import test results after each local test run
2. **Commit database**: Push database changes with test code changes
3. **Query before running**: Check historical performance before re-running tests
4. **Export for sharing**: Use JSON export to share results with team
5. **Monitor size**: Watch database size and archive old data if needed

## Future Enhancements

Potential improvements:
- Web dashboard for viewing results
- Automated trend analysis
- Performance regression detection
- Integration with model comparison tools
- Export to cloud storage (S3, GCS)
