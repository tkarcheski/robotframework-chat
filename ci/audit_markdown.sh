#!/usr/bin/env bash
# ci/audit_markdown.sh - Audit markdown file references using OpenCode + Ollama
#
# Reviews recent commits to identify file renames/deletions, then checks all
# markdown files for broken or stale file references (links, code blocks, prose).
# Produces a patch file of suggested fixes, or exits cleanly if everything is valid.
#
# Optional env vars:
#   AUDIT_MODEL    - Model to use (default: ollama/qwen3-coder:30b-a3b-q4_K_M)
#   OLLAMA_HOST    - Ollama endpoint (falls back to OLLAMA_ENDPOINT from .env)
#   COMMIT_DEPTH   - Number of recent commits to inspect (default: 20)
#   BASE_BRANCH    - Branch to diff against (default: auto-detect main/master)
#
# Usage:
#   make opencode-audit-markdown
#   AUDIT_MODEL=ollama/qwen3:8b make opencode-audit-markdown
#   COMMIT_DEPTH=50 make opencode-audit-markdown

set -uo pipefail

# ── Configuration ───────────────────────────────────────────────────

AUDIT_MODEL="${AUDIT_MODEL:-ollama/qwen3-coder:30b-a3b-q4_K_M}"
COMMIT_DEPTH="${COMMIT_DEPTH:-20}"

# OpenCode uses OLLAMA_HOST; bridge from OLLAMA_ENDPOINT if set
if [ -z "${OLLAMA_HOST:-}" ] && [ -n "${OLLAMA_ENDPOINT:-}" ]; then
    export OLLAMA_HOST="${OLLAMA_ENDPOINT}"
fi

echo "=== Markdown Reference Audit ==="
echo "Model:        ${AUDIT_MODEL}"
echo "Ollama host:  ${OLLAMA_HOST:-http://localhost:11434}"
echo "Commit depth: ${COMMIT_DEPTH}"
echo ""

# ── Detect base branch ─────────────────────────────────────────────

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
echo "Base branch:  ${BASE}"

# ── Collect recent commit context ──────────────────────────────────

echo ""
echo "--- Collecting recent commit history ---"

COMMIT_LOG=$(git log --oneline -"${COMMIT_DEPTH}" 2>/dev/null || true)
echo "Recent commits: $(echo "$COMMIT_LOG" | wc -l) entries"

# Files changed since divergence from base (renames, deletions, additions)
CHANGED_FILES=""
if git rev-parse --verify "origin/${BASE}" >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff "origin/${BASE}...HEAD" --name-status 2>/dev/null || true)
elif git rev-parse --verify "${BASE}" >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff "${BASE}...HEAD" --name-status 2>/dev/null || true)
fi

# Also include recent renames/deletions from log
RENAME_LOG=$(git log --diff-filter=RD --name-status --oneline -"${COMMIT_DEPTH}" 2>/dev/null || true)

echo "Changed files since ${BASE}: $(echo "$CHANGED_FILES" | grep -c '.' || echo 0) entries"
echo ""

# ── Gather markdown files ──────────────────────────────────────────

echo "--- Collecting markdown files ---"

# shellcheck disable=SC2044
MARKDOWN_FILES=""
MARKDOWN_CONTENT=""
MD_COUNT=0

for md_file in $(find . -name '*.md' -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' | sort); do
    MARKDOWN_FILES="${MARKDOWN_FILES}${md_file}
"
    MD_COUNT=$((MD_COUNT + 1))

    # Read file content (truncate very large files to ~500 lines)
    CONTENT=$(head -500 "$md_file" 2>/dev/null || true)
    LINE_COUNT=$(wc -l < "$md_file" 2>/dev/null || echo 0)
    TRUNCATED=""
    if [ "$LINE_COUNT" -gt 500 ]; then
        TRUNCATED=" (TRUNCATED: ${LINE_COUNT} lines, showing first 500)"
    fi

    MARKDOWN_CONTENT="${MARKDOWN_CONTENT}
--- BEGIN ${md_file}${TRUNCATED} ---
${CONTENT}
--- END ${md_file} ---
"
done

echo "Found ${MD_COUNT} markdown files"
echo ""

# ── Build repository file tree ─────────────────────────────────────

echo "--- Building file tree ---"

# Generate file tree for reference validation (exclude hidden dirs, venvs, caches)
FILE_TREE=$(find . \
    -not -path './.git/*' \
    -not -path './node_modules/*' \
    -not -path './.venv/*' \
    -not -path './__pycache__/*' \
    -not -path './.mypy_cache/*' \
    -not -path './.ruff_cache/*' \
    -not -path './htmlcov/*' \
    -not -path './results/*' \
    -not -path './.pytest_cache/*' \
    -not -name '*.pyc' \
    -type f \
    | sort)

TREE_COUNT=$(echo "$FILE_TREE" | wc -l)
echo "File tree: ${TREE_COUNT} files"
echo ""

# ── Run OpenCode audit ─────────────────────────────────────────────

echo "--- Running OpenCode markdown audit ---"
echo ""

AUDIT_RESULT=$(opencode run --model "${AUDIT_MODEL}" \
    "You are a documentation auditor for the robotframework-chat project.

Your task: audit all markdown files for broken or stale file references.
Use the recent commit history as the source of truth for what files were
renamed, moved, or deleted.

INSTRUCTIONS:
1. For every file path referenced in any markdown file (via links like
   [text](path), code blocks, Makefile target references, import paths,
   or prose mentions of file paths), check whether that path exists in
   the REPOSITORY FILE TREE below.
2. Use the RECENT COMMIT LOG and CHANGED FILES to identify renames and
   deletions that may have broken references.
3. For each broken reference found, produce a unified diff patch:

\`\`\`diff
--- a/path/to/markdown-file.md
+++ b/path/to/markdown-file.md
@@ -line,count +line,count @@
 context line
-line with broken reference
+line with corrected reference
 context line
\`\`\`

4. If a reference points to a deleted file with no obvious replacement,
   note it as a WARNING instead of producing a patch.
5. Also check for completeness: if a markdown file documents a directory
   (e.g., listing scripts or modules), verify the listing matches what
   actually exists. Suggest additions for undocumented files.
6. If ALL references are valid and complete, respond with exactly:
   ALL_REFERENCES_VALID

--- BEGIN RECENT COMMIT LOG ---
${COMMIT_LOG}
--- END RECENT COMMIT LOG ---

--- BEGIN CHANGED FILES (since ${BASE}) ---
${CHANGED_FILES}
--- END CHANGED FILES ---

--- BEGIN RENAME/DELETE LOG ---
${RENAME_LOG}
--- END RENAME/DELETE LOG ---

--- BEGIN REPOSITORY FILE TREE ---
${FILE_TREE}
--- END REPOSITORY FILE TREE ---

--- BEGIN MARKDOWN FILES ---
${MARKDOWN_CONTENT}
--- END MARKDOWN FILES ---")

# ── Process results ────────────────────────────────────────────────

echo "${AUDIT_RESULT}" | tee review-markdown-audit.md

echo ""
echo "--- Audit output saved to review-markdown-audit.md ---"

# Check if all references are valid
if echo "$AUDIT_RESULT" | grep -q "ALL_REFERENCES_VALID"; then
    echo ""
    echo "All markdown references are valid. Nothing to fix."
    echo "=== Markdown Reference Audit: PASS ==="
    exit 0
fi

# Extract and validate patches
echo ""
echo "--- Extracting patches ---"

python3 - "$AUDIT_RESULT" <<'PYEOF'
import re
import subprocess
import sys

text = sys.argv[1] if len(sys.argv) > 1 else ""
patches = re.findall(r"```diff\n(.*?)```", text, re.DOTALL)

if not patches:
    print("No patches found in audit output.")
    print("Review review-markdown-audit.md for warnings and suggestions.")
    sys.exit(0)

valid = 0
invalid = 0

for i, patch in enumerate(patches, 1):
    patch_file = f"audit-markdown-patch-{i}.diff"
    with open(patch_file, "w") as f:
        f.write(patch)

    result = subprocess.run(
        ["git", "apply", "--check", patch_file],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"  Patch {i}: VALID - can be applied with: git apply {patch_file}")
        valid += 1
    else:
        print(f"  Patch {i}: INVALID - {result.stderr.strip()}")
        invalid += 1

print(f"\nSummary: {valid} valid patch(es), {invalid} invalid patch(es)")
if valid > 0:
    print(f"\nTo apply all valid patches:")
    for i in range(1, valid + invalid + 1):
        patch_file = f"audit-markdown-patch-{i}.diff"
        check = subprocess.run(
            ["git", "apply", "--check", patch_file],
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            print(f"  git apply {patch_file}")
PYEOF

echo ""
echo "=== Markdown Reference Audit: COMPLETE ==="
echo "Review review-markdown-audit.md for full details."
exit 0
