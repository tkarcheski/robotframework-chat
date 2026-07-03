"""Fail-closed Human-in-the-Loop approval gate (#384).

Authority model, settled with @rpelevin on issue #384: the
``hitl_interactions`` table is a shared inbox for goal, clarification,
approval, and input records — but **only a ``kind='approval'`` row can
authorize a pending action**. The approval binds to the exact
``target_action_id`` plus a sha256 digest of the canonical action
arguments, so a human approves *this* action with *these* args, not a
category of actions.

Everything else fails closed:

- a clarification / goal / input row never authorizes, even when it
  references the same action id and digest with an approved status;
- a pending, denied, or expired approval never authorizes;
- an args-digest mismatch never authorizes (the action changed after
  the human looked at it);
- an approval without an expiry never authorizes — open-ended standing
  approvals are exactly the "every human reply becomes permission"
  failure mode the schema is designed to prevent.

The gate plugs into destructive execution paths via
:class:`rfc.agent_sandbox.AgentSandbox`'s ``approval_gate`` parameter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .harness_db import HarnessDatabase

HITL_APPROVAL_KIND = "approval"


def canonical_args(args: Mapping[str, Any]) -> str:
    """Render action arguments to a canonical JSON string.

    Sorted keys and compact separators make the rendering independent of
    dict insertion order; ``default=str`` keeps exotic values (paths,
    UUIDs) digestible rather than raising.
    """
    return json.dumps(
        dict(args),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def compute_args_digest(args: Mapping[str, Any]) -> str:
    """sha256 hex digest over the canonical JSON rendering of ``args``."""
    return hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()


def parse_utc(timestamp: str) -> datetime:
    """Parse an ISO-8601 timestamp, treating 'Z' and naive values as UTC."""
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class HitlApprovalError(Exception):
    """A destructive action was attempted without a valid approval."""


@dataclass(frozen=True)
class GateDecision:
    """Outcome of one gate check, with the human-readable denial reason."""

    allowed: bool
    reason: str
    interaction_id: str = ""


class HitlApprovalGate:
    """Checks ``hitl_interactions`` for a live approval of an exact action.

    ``now`` is injectable for deterministic expiry tests; it must return
    an aware UTC datetime.
    """

    def __init__(
        self,
        db: HarnessDatabase,
        session_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(timezone.utc))

    def check(self, target_action_id: str, args: Mapping[str, Any]) -> GateDecision:
        """Decide whether ``target_action_id`` with ``args`` may execute."""
        digest = compute_args_digest(args)
        rows = self._db.list_interactions(self._session_id)
        referencing = [r for r in rows if r.target_action_id == target_action_id]
        if not referencing:
            return GateDecision(
                False,
                f"no interaction references action {target_action_id!r} "
                f"in session {self._session_id!r} — approval was never requested",
            )

        approvals = [r for r in referencing if r.kind == HITL_APPROVAL_KIND]
        if not approvals:
            kinds = sorted({r.kind for r in referencing})
            return GateDecision(
                False,
                f"only non-approval interaction(s) {kinds} reference action "
                f"{target_action_id!r}; a {'/'.join(kinds)} response never "
                "authorizes execution — a separate approval event is required",
            )

        matching = [r for r in approvals if r.args_digest == digest]
        if not matching:
            return GateDecision(
                False,
                f"args digest mismatch for action {target_action_id!r}: the "
                "approval(s) on record bind different arguments than the ones "
                "being executed",
            )

        approved = [r for r in matching if r.status == "approved"]
        if not approved:
            statuses = sorted({r.status for r in matching})
            return GateDecision(
                False,
                f"approval not granted for action {target_action_id!r} "
                f"(statuses on record: {statuses})",
            )

        now = self._now()
        for row in approved:
            if not row.expires_at:
                continue  # no expiry -> fail closed; keep looking
            if parse_utc(row.expires_at) > now:
                return GateDecision(True, "approved", row.id)
        return GateDecision(
            False,
            f"approval for action {target_action_id!r} has expired or lacks "
            "an expiry — stale approvals fail closed",
        )

    def require(self, target_action_id: str, args: Mapping[str, Any]) -> None:
        """Raise :class:`HitlApprovalError` unless the action is approved."""
        decision = self.check(target_action_id, args)
        if not decision.allowed:
            raise HitlApprovalError(decision.reason)
