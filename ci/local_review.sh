#!/usr/bin/env bash
# ci/local_review.sh - Local AI code review using OpenCode
#
# Reviews uncommitted changes (staged + unstaged) and any commits on the
# current branch that are not yet on the default branch.
#
# No CI/pipeline context required — runs entirely locally.
#
# Optional env vars:
#   REVIEW_MODEL  - Model to use (default: openrouter/moonshotai/kimi-k2.5)
#   BASE_BRANCH   - Branch to diff against (default: auto-detect main/master)
#
# Usage:
#   make local-ai-review
#   REVIEW_MODEL=openrouter/anthropic/claude-sonnet-4 make local-ai-review

set -uo pipefail

REVIEW_MODEL="${REVIEW_MODEL:-openrouter/moonshotai/kimi-k2.5}"

echo "=== Local AI Review ==="
echo "Model: ${REVIEW_MODEL}"
echo ""

# ── Detect base branch ────────────────────────────────────────────────

detect_base_branch() {
    if [ -n "${BASE_BRANCH:-}" ]; then
        echo "$BASE_BRANCH"
        return
    fi
    for candidate in main master; do
        if git rev-parse --verify "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return
        fi
    done
    echo "main"
}

BASE=$(detect_base_branch)
echo "Base branch: ${BASE}"

# ── Collect diff ──────────────────────────────────────────────────────

# Uncommitted changes (staged + unstaged)
WORKING_DIFF=$(git diff HEAD 2>/dev/null || true)

# Branch commits not yet on the base branch
BRANCH_DIFF=""
if git rev-parse --verify "origin/${BASE}" >/dev/null 2>&1; then
    BRANCH_DIFF=$(git diff "origin/${BASE}...HEAD" 2>/dev/null || true)
elif git rev-parse --verify "${BASE}" >/dev/null 2>&1; then
    BRANCH_DIFF=$(git diff "${BASE}...HEAD" 2>/dev/null || true)
fi

# Combine: prefer branch diff if available, overlay working changes
if [ -n "$WORKING_DIFF" ] && [ -n "$BRANCH_DIFF" ]; then
    DIFF="${BRANCH_DIFF}

--- UNCOMMITTED CHANGES (working tree) ---
${WORKING_DIFF}"
elif [ -n "$BRANCH_DIFF" ]; then
    DIFF="$BRANCH_DIFF"
elif [ -n "$WORKING_DIFF" ]; then
    DIFF="$WORKING_DIFF"
else
    echo "No changes detected — nothing to review."
    exit 0
fi

DIFF_LINES=$(echo "$DIFF" | wc -l)
echo "Diff size: ${DIFF_LINES} lines"
echo ""

# ── Load project guidelines ──────────────────────────────────────────

AGENTS_MD=""
if [ -f ai/AGENTS.md ]; then
    AGENTS_MD=$(cat ai/AGENTS.md)
fi

REFACTOR_MD=""
if [ -f ai/REFACTOR.md ]; then
    REFACTOR_MD=$(cat ai/REFACTOR.md)
fi

GUIDELINES=""
if [ -n "$AGENTS_MD" ]; then
    GUIDELINES="${GUIDELINES}
--- BEGIN ai/AGENTS.md ---
${AGENTS_MD}
--- END ai/AGENTS.md ---
"
fi
if [ -n "$REFACTOR_MD" ]; then
    GUIDELINES="${GUIDELINES}
--- BEGIN ai/REFACTOR.md ---
${REFACTOR_MD}
--- END ai/REFACTOR.md ---
"
fi

# ── Run review ───────────────────────────────────────────────────────

echo "--- Running OpenCode review ---"
echo ""

REVIEW=$(opencode run --model "${REVIEW_MODEL}" \
    "You are a senior code reviewer for the robotframework-chat project.

Review the following local changes. Follow the project guidelines strictly:

${GUIDELINES}

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

echo "${REVIEW}" | tee review-local.md

echo ""
echo "--- Review saved to review-local.md ---"
echo "=== Local AI Review complete ==="
