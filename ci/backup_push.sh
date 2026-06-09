#!/usr/bin/env bash
# ci/backup_push.sh — Commit the contents of the local backups directory to
# the robotframework-chat-backups repo and push to main.
#
# Called by `make superset-export` after it writes the Superset export zip and
# the PostgreSQL dump into BACKUPS_DIR. The backup repo is treated as optional:
# if it cannot be cloned or the push fails, the artifacts stay on disk, the
# script logs a warning, and exits 0 — so the export itself never hard-fails
# on a backup-side hiccup.
#
# Env vars:
#   BACKUPS_DIR       Local backups directory (default: backups)
#   BACKUPS_REPO_URL  Backup repo to clone/push to
#                     (default: git@github.com:tkarcheski/robotframework-chat-backups.git)
#
# Usage:
#   ci/backup_push.sh "chore: backup 20260527_010203"

set -euo pipefail

MSG="${1:-chore: backup $(date +%Y%m%d_%H%M%S)}"
BACKUPS_DIR="${BACKUPS_DIR:-backups}"
BACKUPS_REPO_URL="${BACKUPS_REPO_URL:-git@github.com:tkarcheski/robotframework-chat-backups.git}"

mkdir -p "$BACKUPS_DIR"

# Ensure BACKUPS_DIR is a working clone of the backup repo. The caller may have
# already written artifacts into BACKUPS_DIR, so we can't `git clone` directly
# into it (clone requires an empty target). Instead clone into a sibling temp
# and graft its .git into BACKUPS_DIR, preserving any artifacts in place.
if [ ! -e "$BACKUPS_DIR/.git" ]; then
    tmp="${BACKUPS_DIR}.clone.$$"
    rm -rf "$tmp"
    if git clone --quiet "$BACKUPS_REPO_URL" "$tmp" 2>/dev/null; then
        mv "$tmp/.git" "$BACKUPS_DIR/.git"
        rm -rf "$tmp"
        # Restore tracked files from HEAD without clobbering new artifacts.
        # An empty remote has no HEAD to restore from, so swallow the error.
        git -C "$BACKUPS_DIR" checkout -- . 2>/dev/null || true
        echo "Initialized $BACKUPS_DIR/ as a clone of $BACKUPS_REPO_URL"
    else
        rm -rf "$tmp"
        echo "WARNING: could not clone $BACKUPS_REPO_URL — backups stay local only" >&2
        exit 0
    fi
else
    # Existing clone — try to fast-forward so the upcoming push is clean. Don't
    # fail if pull errors (detached HEAD, no upstream, offline, ...): we'd
    # rather attempt the push and let it report the real reason.
    git -C "$BACKUPS_DIR" pull --ff-only --quiet 2>/dev/null || true
fi

git -C "$BACKUPS_DIR" add -A
if git -C "$BACKUPS_DIR" diff --cached --quiet; then
    echo "No new backup artifacts to commit"
    exit 0
fi

if git -C "$BACKUPS_DIR" commit --quiet -m "$MSG"; then
    if git -C "$BACKUPS_DIR" push origin HEAD:main; then
        echo "Pushed backups to main"
    else
        echo "WARNING: backups push failed — commit is local only" >&2
    fi
else
    echo "WARNING: backups commit failed" >&2
fi
