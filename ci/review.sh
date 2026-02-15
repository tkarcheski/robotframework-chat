#!/usr/bin/env bash
# ci/review.sh - AI code review and pipeline fix using OpenCode + Kimi K2.5
#
# Two phases:
#   1. Detect failed pipeline jobs and attempt automated fixes
#   2. Review MR diff against project guidelines
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
    echo "Running OpenCode to analyze and fix failures..."

    FIX_RESULT=$(opencode run --model "${REVIEW_MODEL}" \
        "You are a CI/CD engineer for the robotframework-chat project.
Read the project guidelines in ai/AGENTS.md and ai/REFACTOR.md.

The following pipeline jobs have failed. Analyze the failure logs below
and produce a concrete fix for each failure.

For each failure, output:
1. Which job failed and why (root cause, not just the symptom)
2. The file(s) that need to change
3. A unified diff (patch) that fixes the issue

Format each patch as:
\`\`\`diff
--- a/path/to/file
+++ b/path/to/file
@@ ... @@
 context
-old line
+new line
 context
\`\`\`

If a failure is environmental (missing service, network timeout, runner
misconfiguration) and cannot be fixed by code changes, say so and skip
the patch.

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

    AGENTS_MD=$(cat ai/AGENTS.md)
    REFACTOR_MD=$(cat ai/REFACTOR.md)

    REVIEW=$(opencode run --model "${REVIEW_MODEL}" \
        "You are a senior code reviewer for the robotframework-chat project.

Review the following merge request diff. Follow the project guidelines
strictly:

--- BEGIN ai/AGENTS.md ---
${AGENTS_MD}
--- END ai/AGENTS.md ---

--- BEGIN ai/REFACTOR.md ---
${REFACTOR_MD}
--- END ai/REFACTOR.md ---

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
<summary>Pipeline fix attempt</summary>

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
*Review generated by OpenCode (\`${REVIEW_MODEL}\`) following [ai/AGENTS.md](ai/AGENTS.md) and [ai/REFACTOR.md](ai/REFACTOR.md)*
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
