#!/usr/bin/env bash
# ci/review.sh - AI code review and pipeline debug using OpenCode + Kimi K2.5
#
# Three phases:
#   1. Detect failed pipeline jobs, diagnose root causes (following ai/roles/docker-debugger.md + gitlab-pipeline-debugger.md)
#   2. Review MR diff against project guidelines
#   3. Post debug report + review to MR
#
# Required env vars:
#   OPENROUTER_API_KEY        - OpenRouter API key
#   REVIEW_MODEL              - Model to use (default: openrouter/moonshotai/kimi-k2.5)
#
# Optional env vars:
#   GITLAB_TOKEN              - For reading job logs and posting MR comments
#   CI_MERGE_REQUEST_IID      - MR number (set by GitLab CI)
#   CI_PIPELINE_ID            - Pipeline ID (set by GitLab CI)
#   CI_MERGE_REQUEST_TARGET_BRANCH_NAME - Target branch for diff
#
# Usage: bash ci/review.sh

set -uo pipefail

REVIEW_MODEL="${REVIEW_MODEL:-openrouter/moonshotai/kimi-k2.5}"

echo "=== OpenCode Review ==="
echo "Model: ${REVIEW_MODEL}"
echo "Pipeline: ${CI_PIPELINE_ID:-unknown}"
echo ""

# ── Phase 1: Pipeline failure detection and fix ──────────────────────

fix_pipeline_failures() {
    if [ -z "${GITLAB_TOKEN:-}" ]; then
        echo "GITLAB_TOKEN not set -- skipping failure detection."
        return 0
    fi

    echo "--- Phase 1: Checking pipeline for failures ---"

    FAILED_JOBS_JSON=$(curl --silent --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/pipelines/${CI_PIPELINE_ID}/jobs?scope=failed&per_page=50")

    FAILED_COUNT=$(echo "$FAILED_JOBS_JSON" | python3 -c "
import json, sys
jobs = json.load(sys.stdin)
failed = [j for j in jobs if j.get('name') != 'opencode-review']
print(len(failed))
" 2>/dev/null || echo "0")

    echo "Failed jobs (excluding review): ${FAILED_COUNT}"

    if [ "$FAILED_COUNT" -eq "0" ]; then
        echo "No failed jobs detected -- skipping fix phase."
        return 0
    fi

    echo "Collecting failure logs..."

    FAILURE_CONTEXT="The following pipeline jobs FAILED. Analyze the logs and attempt to fix the root causes.

"
    FAILED_JOB_IDS=$(echo "$FAILED_JOBS_JSON" | python3 -c "
import json, sys
jobs = json.load(sys.stdin)
for j in jobs:
    if j.get('name') != 'opencode-review':
        print(f\"{j['id']}|{j['name']}|{j.get('stage', 'unknown')}\")
" 2>/dev/null || true)

    while IFS='|' read -r JOB_ID JOB_NAME JOB_STAGE; do
        [ -z "$JOB_ID" ] && continue
        echo "  Fetching log for: ${JOB_NAME} (job ${JOB_ID}, stage ${JOB_STAGE})"

        JOB_LOG=$(curl --silent --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/jobs/${JOB_ID}/trace" \
            | tail -200)

        FAILURE_CONTEXT="${FAILURE_CONTEXT}
--- FAILED JOB: ${JOB_NAME} (stage: ${JOB_STAGE}) ---
${JOB_LOG}
--- END JOB LOG ---
"
    done <<< "$FAILED_JOB_IDS"

    echo ""
    echo "Running OpenCode to diagnose failures (following ai/roles/docker-debugger.md + gitlab-pipeline-debugger.md)..."

    DEBUGGER_MD=$(cat ai/roles/docker-debugger.md 2>/dev/null || echo "(docker-debugger.md not found)")
    PIPELINE_DEBUGGER_MD=$(cat ai/roles/gitlab-pipeline-debugger.md 2>/dev/null || echo "(gitlab-pipeline-debugger.md not found)")
    AGENTS_MD=$(cat ai/agents.md 2>/dev/null || echo "(agents.md not found)")

    FIX_RESULT=$(opencode run --model "${REVIEW_MODEL}" \
        "You are a debugging agent for the robotframework-chat project.
Follow the docker-debugger role for Docker/container issues and the
gitlab-pipeline-debugger role for pipeline/CI issues:

--- BEGIN ai/roles/docker-debugger.md ---
${DEBUGGER_MD}
--- END ai/roles/docker-debugger.md ---

--- BEGIN ai/roles/gitlab-pipeline-debugger.md ---
${PIPELINE_DEBUGGER_MD}
--- END ai/roles/gitlab-pipeline-debugger.md ---

--- BEGIN ai/agents.md (summary) ---
Core rules: Python in src/rfc/, Robot tests in robot/, listeners always active,
TDD mandatory, type hints required, atomic commits only.
--- END ai/agents.md (summary) ---

The following pipeline jobs have FAILED. For each failure:

1. **Classify** the failure: code-bug | infra | config | environment | transient | yaml
2. **Diagnose** the root cause using the debugging layers from the appropriate role
   (Docker layers for container issues, pipeline layers for CI issues)
3. **Report** using the diagnostic report template:

## Failure: <job-name>
**Symptom:** What the log shows
**Classification:** code-bug | infra | config | environment | transient
**Root cause:** Why it actually failed
**Evidence:** Key log lines or config values
**Fix:** Patch for code-bugs, step-by-step commands for infra/config/environment

4. For code-bug failures ONLY, also produce a unified diff patch:
\`\`\`diff
--- a/path/to/file
+++ b/path/to/file
@@ ... @@
 context
-old line
+new line
 context
\`\`\`

Do NOT produce patches for infra, config, environment, or transient failures.
Document the fix steps instead.

${FAILURE_CONTEXT}")

    echo "${FIX_RESULT}" > review-fix-attempt.md
    echo "--- Fix analysis complete ---"

    # Extract and apply patches
    echo ""
    echo "Attempting to apply patches..."
    python3 - "$FIX_RESULT" <<'PYEOF'
import re, subprocess, sys

text = sys.argv[1] if len(sys.argv) > 1 else ""
patches = re.findall(r'```diff\n(.*?)```', text, re.DOTALL)

if not patches:
    print("No patches found in OpenCode output.")
    sys.exit(0)

applied = 0
for i, patch in enumerate(patches, 1):
    patch_file = f"review-patch-{i}.diff"
    with open(patch_file, "w") as f:
        f.write(patch)
    result = subprocess.run(
        ["git", "apply", "--check", patch_file],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        subprocess.run(["git", "apply", patch_file], check=True)
        print(f"  Patch {i}: applied successfully")
        applied += 1
    else:
        print(f"  Patch {i}: cannot apply cleanly -- {result.stderr.strip()}")

if applied > 0:
    print(f"\n{applied} patch(es) applied. Committing fix...")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: auto-fix pipeline failures (OpenCode)"],
        check=True
    )
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    push = subprocess.run(
        ["git", "push", "origin", branch],
        capture_output=True, text=True
    )
    if push.returncode == 0:
        print(f"Fix pushed to {branch}")
    else:
        print(f"Push failed: {push.stderr.strip()}")
else:
    print("No patches could be applied.")
PYEOF
}

# ── Phase 2: MR diff review ─────────────────────────────────────────

review_mr_diff() {
    echo ""
    echo "--- Phase 2: Code review ---"

    if [ -z "${CI_MERGE_REQUEST_IID:-}" ]; then
        echo "Not running in an MR context -- skipping diff review."
        return 0
    fi

    git fetch origin "${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}"
    DIFF=$(git diff "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}...HEAD")

    if [ -z "$DIFF" ]; then
        echo "No changes detected -- skipping review."
        return 0
    fi

    AGENTS_MD=$(cat ai/agents.md)
    REFACTOR_MD=$(cat ai/refactor.md)

    REVIEW=$(opencode run --model "${REVIEW_MODEL}" \
        "You are a senior code reviewer for the robotframework-chat project.

Review the following merge request diff. Follow the project guidelines
strictly:

--- BEGIN ai/agents.md ---
${AGENTS_MD}
--- END ai/agents.md ---

--- BEGIN ai/refactor.md ---
${REFACTOR_MD}
--- END ai/refactor.md ---

Review criteria (in priority order):
1. Correctness: broken tests, logic errors, data loss potential
2. Security: credential exposure, injection, path traversal
3. Architecture: adherence to module responsibilities and project structure
4. Code style: naming, type annotations, Robot Framework syntax conventions
5. Test coverage: new behavior must have corresponding tests
6. Commit discipline: atomic commits, proper type prefixes

For each issue found, state:
- Severity (must-fix / should-fix / consider)
- File and approximate location
- What is wrong and why
- Suggested fix

If the diff looks good, say so briefly. Do not invent issues.

--- BEGIN DIFF ---
${DIFF}
--- END DIFF ---")

    echo "${REVIEW}" > review-result.md
    echo "--- Review complete ---"
}

# ── Phase 3: Post results to MR ─────────────────────────────────────

post_mr_comment() {
    if [ -z "${GITLAB_TOKEN:-}" ] || [ -z "${CI_MERGE_REQUEST_IID:-}" ]; then
        echo "GITLAB_TOKEN or MR context not available -- review saved as artifact only."
        return 0
    fi

    echo ""
    echo "--- Posting review to MR ---"

    FIX_SECTION=""
    if [ -f review-fix-attempt.md ]; then
        FIX_CONTENT=$(cat review-fix-attempt.md)
        FIX_SECTION="
<details>
<summary>Debug Report (docker-debugger.md + gitlab-pipeline-debugger.md)</summary>

${FIX_CONTENT}

</details>
"
    fi

    REVIEW_CONTENT=""
    if [ -f review-result.md ]; then
        REVIEW_CONTENT=$(cat review-result.md)
    fi

    COMMENT_BODY=$(cat <<REVIEW_EOF
## OpenCode Review (Kimi K2.5)

<details>
<summary>Code review of MR !${CI_MERGE_REQUEST_IID}</summary>

${REVIEW_CONTENT}

</details>
${FIX_SECTION}
---
*Review generated by OpenCode (\`${REVIEW_MODEL}\`) following [ai/roles/docker-debugger.md](ai/roles/docker-debugger.md), [ai/roles/gitlab-pipeline-debugger.md](ai/roles/gitlab-pipeline-debugger.md), [ai/agents.md](ai/agents.md), and [ai/refactor.md](ai/refactor.md)*
REVIEW_EOF
    )

    if curl --fail --request POST \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${CI_MERGE_REQUEST_IID}/notes" \
        --data-urlencode "body=${COMMENT_BODY}"; then
        echo "Review posted to MR."
    else
        echo "WARNING: Could not post review comment to MR."
    fi
}

# ── Main ─────────────────────────────────────────────────────────────

fix_pipeline_failures
review_mr_diff
post_mr_comment

echo ""
echo "=== Review complete ==="
