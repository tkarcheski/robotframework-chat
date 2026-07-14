#!/usr/bin/env python3
"""Read-only stand-up aggregator: derive the fleet stand-up from live board state.

The four roles (engineering, test-design, project-management, design) communicate
ONLY through GitHub — claim comments, ``TEST-PLAN:``/``DESIGN:`` verdicts, sign-off
labels, and the status/priority label taxonomy in modules/agents/ROLES.md. A
stand-up is therefore *mechanically derivable* from the board, and derivation is
more honest than any agent self-report: this script reads the board and answers
the three stand-up questions for every role plus the owner.

  1. Working  — status:in-progress issues (claiming role + branch parsed from the
                claim comment) and open PRs (head, age, which sign-offs present).
  2. Stuck    — status:blocked issues (named blocker from the block comment); PRs
                awaiting a verdict (which role owes it); FAIL verdicts awaiting
                engineering; owner-gated items; stranded mirror/publish-* branches;
                status:ready items untouched > --stale-days.
  3. Next     — the status:ready queue in priority order (P0->P3, oldest first);
                explicitly-gated dispatches (promote-when / dispatch-after comments).

Plus a compact owner-actions header — the human's only moves.

This tool is **strictly read-only**: it runs `gh ... list/view/api` and never a
mutating verb. It sets no labels, posts no comments, touches no branches. The
session that invokes it does the interpretation; this script does the plumbing.

Usage:
  uv run --project core python modules/ops/scripts/standup_report.py
  uv run --project core python modules/ops/scripts/standup_report.py --format json
  uv run --project core python modules/ops/scripts/standup_report.py --stale-days 5
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_REPO = "tkarcheski/rfc-monorepo"
DEFAULT_MIRROR = "tkarcheski/robotframework-chat"
DEFAULT_STALE_DAYS = 7

# --- label / state constants (mirrors modules/agents/ROLES.md) --------------

STATUS_IN_PROGRESS = "status:in-progress"
STATUS_BLOCKED = "status:blocked"
STATUS_READY = "status:ready"
SIGNOFF_TEST = "signoff:test-design"
SIGNOFF_DESIGN = "signoff:design"
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Personas (ROLES.md "The cast") are unambiguous single-role tokens — the most
# reliable role signal, since a claim comment often *mentions* other roles in
# passing (e.g. "claiming for engineering … the normal PM promotion").
PERSONA_TO_ROLE = {
    "scotty": "engineering",
    "meeseeks": "test-design",
    "tusk": "design",
    "gantt": "project-management",
}

# Role-word aliases, applied to the claim's *subject* only (see _role_of).
# Order matters: test-design before design ("test-design" contains "design"),
# and project-management before the bare "pm".
ROLE_ALIASES: list[tuple[str, re.Pattern[str]]] = [
    ("test-design", re.compile(r"\btest[- ]design\b", re.I)),
    ("project-management", re.compile(r"\bproject[- ]management\b|\bpm\b", re.I)),
    ("engineering", re.compile(r"\bengineering\b", re.I)),
    ("design", re.compile(r"\bdesign\b", re.I)),
]

# The role a claim is *for*: "claiming for <role>" / "claim … for <role>".
CLAIM_FOR_RE = re.compile(r"claim(?:ing|ed)?[^.\n]*?\bfor\s+([a-z][a-z -]+)", re.I)

# A branch token: `<type>/<num>-<slug>` etc. — at least one slash, no spaces.
BRANCH_RE = re.compile(r"`([a-z][a-z0-9]*(?:/[A-Za-z0-9._-]+)+)`")
BRANCH_BARE_RE = re.compile(r"\bbranch\s+([a-z][a-z0-9]*/[A-Za-z0-9._-]+)")
BLOCKED_ON_RE = re.compile(r"blocked[- ]on:?\s*(#\d+(?:\s*(?:,|and|\+)\s*#\d+)*)", re.I)
# Loose owner-gating signal — used only to phrase a *blocked* issue's blocker.
OWNER_GATED_RE = re.compile(r"owner[- ]gated|owner[- ]action", re.I)
# Strict owner-ACTION signal for the top-of-report owner-actions section: the
# PM's canonical "owner action, not an engineering queue item" phrasing, an
# explicit "owner action required", or the "OWNER-GATED" directive marker
# (case-sensitive — a lowercase "owner-gated" in prose must not trip it, so a
# comment that merely *describes* owner-gating is not itself an owner action).
OWNER_ACTION_RE = re.compile(
    r"(?i:owner[- ]action,\s*not|owner[- ]action required)|OWNER-GATED"
)
GATED_DISPATCH_RE = re.compile(
    r"(promote[- ]when|dispatch (?:after|when|once)|do\s*n[o']?t\s+dispatch"
    r"|hold\b[^\n.]*?until|gated on|unblock[s]? when)[^\n.]{0,120}",
    re.I,
)
# The strongest claim signal is the word "claim" itself: engineering's claim
# comment ("Claiming for engineering (Scotty) … on branch `feat/…`"). A PM
# promotion/triage note that merely mentions "status:in-progress" must NOT be
# mistaken for a claim — otherwise the work shows under the wrong role.
STRONG_CLAIM_RE = re.compile(r"\bclaim(?:ing|ed)?\b", re.I)
VERDICT_FAIL_RE = re.compile(r"\b(TEST-PLAN|DESIGN):\s*FAIL\b")
VERDICT_TESTPLAN_PASS_RE = re.compile(r"\bTEST-PLAN:\s*PASS\b")


# --- data model -------------------------------------------------------------


@dataclass
class WorkingItem:
    number: int
    title: str
    role: str
    branch: str | None


@dataclass
class OpenPR:
    number: int
    title: str
    head: str
    age_days: int
    is_draft: bool
    has_test_signoff: bool
    has_design_signoff: bool
    owes: str  # which role owes the next move


@dataclass
class BlockedItem:
    number: int
    title: str
    blocker: str


@dataclass
class OwnerAction:
    number: int
    title: str
    priority: str
    why: str


@dataclass
class ReadyItem:
    number: int
    title: str
    priority: str
    created: str
    stale_days: int | None  # days since last touch if stale, else None
    gated: str | None  # gated-dispatch phrase if any


@dataclass
class Standup:
    repo: str
    generated_at: str
    stale_days: int
    owner_actions: list[OwnerAction] = field(default_factory=list)
    working_by_role: dict[str, list[WorkingItem]] = field(default_factory=dict)
    open_prs: list[OpenPR] = field(default_factory=list)
    blocked: list[BlockedItem] = field(default_factory=list)
    prs_awaiting_verdict: list[OpenPR] = field(default_factory=list)
    fails_awaiting_engineering: list[OpenPR] = field(default_factory=list)
    stranded_mirror_branches: list[str] = field(default_factory=list)
    stale_ready: list[ReadyItem] = field(default_factory=list)
    next_queue: list[ReadyItem] = field(default_factory=list)
    gated_dispatches: list[ReadyItem] = field(default_factory=list)


# --- pure helpers (hermetically tested via fake gh JSON) --------------------


def label_names(item: dict) -> list[str]:
    return [lbl["name"] for lbl in item.get("labels", [])]


def status_of(item: dict) -> str | None:
    for name in label_names(item):
        if name.startswith("status:"):
            return name
    return None


def priority_of(item: dict) -> str:
    for name in label_names(item):
        if name in PRIORITY_ORDER:
            return name
    return ""


def _comment_bodies(item: dict) -> list[str]:
    """Comment bodies newest-last, as attached by the fetch layer."""
    out: list[str] = []
    for c in item.get("comments", []):
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict):
            out.append(c.get("body", ""))
    return out


def _role_of(body: str) -> str:
    """The role a claim comment names — persona first, then the 'for <role>'
    subject, then any role word. Other roles mentioned in passing don't win."""
    low = body.lower()
    for persona, role in PERSONA_TO_ROLE.items():
        if persona in low:
            return role
    m = CLAIM_FOR_RE.search(body)
    subject = m.group(1) if m else body
    for name, pat in ROLE_ALIASES:
        if pat.search(subject):
            return name
    return "unknown"


def _role_and_branch(body: str) -> tuple[str, str | None]:
    role = _role_of(body)
    branch = None
    m = BRANCH_BARE_RE.search(body)
    if m:
        branch = m.group(1)
    else:
        for cand in BRANCH_RE.findall(body):
            if "/" in cand:
                branch = cand
                break
    return role, branch


def parse_claim(item: dict) -> tuple[str, str | None]:
    """(claiming role, branch) parsed from the claim comment.

    Every role speaks under one GitHub account (the owner drives all sessions),
    so the *body* — not the comment author — names the claiming role. Prefer an
    explicit "claim" comment (newest first); only if none exists fall back to the
    newest comment that names a branch. This keeps a PM promotion note that just
    flips the status label from being read as the engineering claim.
    """
    bodies = _comment_bodies(item)
    for body in reversed(bodies):
        if STRONG_CLAIM_RE.search(body):
            return _role_and_branch(body)
    for body in reversed(bodies):
        role, branch = _role_and_branch(body)
        if branch:
            return role, branch
    return "unknown", None


def parse_blocker(item: dict) -> str:
    """Short human-readable blocker, from the most recent blocking comment."""
    for body in reversed(_comment_bodies(item)):
        low = body.lower()
        if "block" not in low:
            continue
        m = BLOCKED_ON_RE.search(body)
        if m:
            refs = re.sub(r"\s+", " ", m.group(1)).strip()
            return f"blocked-on {refs}"
        if OWNER_GATED_RE.search(body):
            return "owner-gated (owner decision required)"
        # first clause after a "blocked" mention, stripped of markdown noise
        idx = low.find("block")
        clause = re.split(r"[.\n]", body[idx:], maxsplit=1)[0]
        clause = clause.replace("`", "").replace("*", "")
        clause = re.sub(r"\s+", " ", clause).strip()
        # drop the leading "blocked"/"blocker"/"blocked-on" word and punctuation
        clause = re.sub(r"^blocked?(?:-on)?\b", "", clause, flags=re.I)
        clause = re.sub(r"^\W+", "", clause).strip()
        if not clause:
            return "blocked (see comment)"
        return (clause[:140] + "…") if len(clause) > 140 else clause
    return "blocker not stated in comments"


def is_owner_action(item: dict) -> bool:
    return any(OWNER_ACTION_RE.search(b) for b in _comment_bodies(item))


def owner_action_reason(item: dict) -> str:
    for body in reversed(_comment_bodies(item)):
        if OWNER_ACTION_RE.search(body):
            clause = re.split(r"[.\n]", body, maxsplit=1)[0]
            clause = re.sub(r"\s+", " ", clause).strip(" -—:")
            return (clause[:160] + "…") if len(clause) > 160 else clause
    return "owner action required (see issue)"


def parse_gated_dispatch(item: dict) -> str | None:
    for body in _comment_bodies(item):
        m = GATED_DISPATCH_RE.search(body)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_days(created: str, now: datetime) -> int:
    return max(0, (now - parse_dt(created)).days)


def ready_sort_key(item: dict) -> tuple[int, str]:
    """P0->P3 then oldest-first; unprioritised items sort last."""
    return (PRIORITY_ORDER.get(priority_of(item), 99), item.get("createdAt", ""))


def pr_verdict_owed(pr: dict) -> str:
    """Which role owes the next move on an open PR (from labels + verdicts)."""
    if pr.get("isDraft"):
        return "engineering (draft — not yet up for review)"
    labels = label_names(pr)
    bodies = _comment_bodies(pr)
    has_test = SIGNOFF_TEST in labels or any(
        VERDICT_TESTPLAN_PASS_RE.search(b) for b in bodies
    )
    has_design = SIGNOFF_DESIGN in labels
    # A standing FAIL is engineering's to service before either reviewer re-verdicts.
    for body in reversed(bodies):
        m = VERDICT_FAIL_RE.search(body)
        if m:
            return f"engineering (service {m.group(1)}: FAIL)"
    if not has_test:
        return "test-design (owes TEST-PLAN verdict)"
    if not has_design:
        return "design (owes DESIGN verdict)"
    return "human (dual sign-off present — merge gate)"


# --- aggregation (pure) -----------------------------------------------------


def build_standup(
    issues: list[dict],
    prs: list[dict],
    mirror_branches: list[str],
    now: datetime,
    stale_days: int,
    repo: str = DEFAULT_REPO,
) -> Standup:
    su = Standup(
        repo=repo,
        generated_at=now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        stale_days=stale_days,
    )

    for issue in issues:
        st = status_of(issue)
        if st == STATUS_IN_PROGRESS:
            role, branch = parse_claim(issue)
            su.working_by_role.setdefault(role, []).append(
                WorkingItem(issue["number"], issue["title"], role, branch)
            )
        elif st == STATUS_BLOCKED:
            su.blocked.append(
                BlockedItem(issue["number"], issue["title"], parse_blocker(issue))
            )
        elif st == STATUS_READY:
            stale = age_days(issue.get("updatedAt", issue["createdAt"]), now)
            gated = parse_gated_dispatch(issue)
            item = ReadyItem(
                issue["number"],
                issue["title"],
                priority_of(issue),
                issue.get("createdAt", "")[:10],
                stale if stale > stale_days else None,
                gated,
            )
            su.next_queue.append(item)
            if item.stale_days is not None:
                su.stale_ready.append(item)
            if gated:
                su.gated_dispatches.append(item)

        # owner-actions cut across status: any issue a comment flags as an owner move.
        if is_owner_action(issue):
            su.owner_actions.append(
                OwnerAction(
                    issue["number"],
                    issue["title"],
                    priority_of(issue),
                    owner_action_reason(issue),
                )
            )

    su.next_queue.sort(key=lambda r: (PRIORITY_ORDER.get(r.priority, 99), r.created))
    su.stale_ready.sort(key=lambda r: (r.stale_days or 0), reverse=True)
    su.owner_actions.sort(key=lambda o: PRIORITY_ORDER.get(o.priority, 99))

    for pr in prs:
        owes = pr_verdict_owed(pr)
        opr = OpenPR(
            pr["number"],
            pr["title"],
            pr.get("headRefName", "?"),
            age_days(pr["createdAt"], now),
            bool(pr.get("isDraft")),
            SIGNOFF_TEST in label_names(pr),
            SIGNOFF_DESIGN in label_names(pr),
            owes,
        )
        su.open_prs.append(opr)
        if owes.startswith("engineering (service"):
            su.fails_awaiting_engineering.append(opr)
        elif "owes" in owes:
            su.prs_awaiting_verdict.append(opr)

    su.stranded_mirror_branches = sorted(
        b for b in mirror_branches if b.startswith("mirror/publish-")
    )
    return su


# --- rendering --------------------------------------------------------------


def _fmt_signoffs(pr: OpenPR) -> str:
    t = "✓" if pr.has_test_signoff else "✗"
    d = "✓" if pr.has_design_signoff else "✗"
    return f"test-design {t} / design {d}"


def render_text(su: Standup) -> str:
    L: list[str] = []
    L.append(f"# Fleet stand-up — {su.repo} — {su.generated_at}")
    L.append("")
    L.append(
        "Derived from live board state (labels + claim/verdict comments). "
        "Read-only: no state was changed."
    )
    L.append("")

    L.append("## Owner actions (the human's only moves)")
    if su.owner_actions:
        for o in su.owner_actions:
            pri = f" {o.priority}" if o.priority else ""
            L.append(f"- #{o.number}{pri} — {o.title}\n    ↳ {o.why}")
    else:
        L.append("- None.")
    L.append("")

    L.append("## 1. Working")
    if su.working_by_role:
        for role in sorted(su.working_by_role):
            L.append(f"### {role}")
            for w in su.working_by_role[role]:
                br = (
                    f" — branch `{w.branch}`"
                    if w.branch
                    else " — branch (unclaimed in comment)"
                )
                L.append(f"- #{w.number} — {w.title}{br}")
    else:
        L.append("- No issues status:in-progress.")
    L.append("### Open PRs")
    if su.open_prs:
        for pr in su.open_prs:
            draft = " [draft]" if pr.is_draft else ""
            L.append(
                f"- #{pr.number}{draft} `{pr.head}` — {pr.age_days}d old — "
                f"{_fmt_signoffs(pr)} — awaiting: {pr.owes}"
            )
    else:
        L.append("- No open PRs.")
    L.append("")

    L.append("## 2. Stuck / blocked / waiting")
    L.append("**Blocked issues:**")
    if su.blocked:
        for b in su.blocked:
            L.append(f"- #{b.number} — {b.title}\n    ↳ {b.blocker}")
    else:
        L.append("- None.")
    L.append("**PRs awaiting a verdict:**")
    if su.prs_awaiting_verdict:
        for pr in su.prs_awaiting_verdict:
            L.append(f"- #{pr.number} `{pr.head}` — {pr.owes}")
    else:
        L.append("- None.")
    L.append("**FAIL verdicts awaiting engineering:**")
    if su.fails_awaiting_engineering:
        for pr in su.fails_awaiting_engineering:
            L.append(f"- #{pr.number} `{pr.head}` — {pr.owes}")
    else:
        L.append("- None.")
    L.append("**Stranded mirror-publish branches:**")
    if su.stranded_mirror_branches:
        for b in su.stranded_mirror_branches:
            L.append(f"- {b}")
    else:
        L.append("- None.")
    L.append(f"**status:ready untouched > {su.stale_days}d:**")
    if su.stale_ready:
        for r in su.stale_ready:
            pri = f" {r.priority}" if r.priority else ""
            L.append(f"- #{r.number}{pri} — {r.title} ({r.stale_days}d stale)")
    else:
        L.append("- None.")
    L.append("")

    L.append("## 3. Next")
    L.append("**status:ready queue (P0→P3, oldest first):**")
    if su.next_queue:
        for i, r in enumerate(su.next_queue, 1):
            pri = r.priority or "(unprioritised)"
            L.append(f"{i}. #{r.number} {pri} — {r.title}")
    else:
        L.append("- Queue empty.")
    L.append("**Gated dispatches (promote-when / dispatch-after):**")
    if su.gated_dispatches:
        for r in su.gated_dispatches:
            L.append(f"- #{r.number} — {r.gated}")
    else:
        L.append("- None.")
    return "\n".join(L)


def _as_dict(obj: object) -> object:
    if isinstance(obj, list):
        return [_as_dict(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _as_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    return obj


def render_json(su: Standup) -> str:
    return json.dumps(_as_dict(su), indent=2)


# --- fetch layer (the only place that shells out; read-only gh verbs) -------


def _gh_json(args: list[str]) -> object:
    out = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out) if out.strip() else []


def fetch_issue_comments(repo: str, number: int) -> list[dict]:
    data = _gh_json(
        ["issue", "view", str(number), "--repo", repo, "--json", "comments"]
    )
    assert isinstance(data, dict)
    return data.get("comments", [])


def fetch_issues(repo: str, limit: int = 300) -> list[dict]:
    """Open issues with metadata; comment bodies attached for the subset of
    states whose stand-up meaning lives in a comment (in-progress/blocked/ready)."""
    issues = _gh_json(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,labels,assignees,createdAt,updatedAt",
        ]
    )
    assert isinstance(issues, list)
    for issue in issues:
        st = status_of(issue)
        if st in (STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_READY):
            issue["comments"] = fetch_issue_comments(repo, issue["number"])
        else:
            issue["comments"] = []
    return issues


def fetch_prs(repo: str, limit: int = 100) -> list[dict]:
    prs = _gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,headRefName,labels,isDraft,createdAt",
        ]
    )
    assert isinstance(prs, list)
    for pr in prs:
        pr["comments"] = fetch_issue_comments(repo, pr["number"])
    return prs


def fetch_mirror_branches(mirror_repo: str) -> list[str]:
    try:
        data = _gh_json(["api", f"repos/{mirror_repo}/branches", "--paginate"])
    except subprocess.CalledProcessError:
        return []
    assert isinstance(data, list)
    return [b["name"] for b in data]


# --- entrypoint -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--mirror-repo", default=DEFAULT_MIRROR)
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    issues = fetch_issues(args.repo)
    prs = fetch_prs(args.repo)
    mirror_branches = fetch_mirror_branches(args.mirror_repo)
    su = build_standup(
        issues,
        prs,
        mirror_branches,
        datetime.now(timezone.utc),
        args.stale_days,
        repo=args.repo,
    )
    print(render_json(su) if args.format == "json" else render_text(su))
    return 0


if __name__ == "__main__":
    sys.exit(main())
