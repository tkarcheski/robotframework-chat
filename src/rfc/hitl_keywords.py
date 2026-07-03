"""Robot Framework keywords for Human-in-the-Loop flows (#384, MVP).

Non-interactive by design: a human (or a test standing in for one)
resolves interactions by updating the ``hitl_interactions`` table —
``Resolve Interaction`` is that table-update path — while the agent
side polls with ``Wait For Human Input``. Timeouts fail closed to
``expired``. Slack / email / web-UI transports are post-v2; when they
land they resolve the *same* table rows, never minting
transport-specific authority (per @rpelevin's design on #384).

Only ``Request Human Approval`` rows can ever authorize execution, and
only for the exact ``target_action_id`` + args digest they bind — see
:mod:`rfc.hitl_gate` for the fail-closed authority model.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional

from robot.api import logger
from robot.api.deco import keyword

from .harness_db import HarnessDatabase
from .harness_models import HitlInteraction
from .hitl_gate import (
    HitlApprovalError,
    HitlApprovalGate,
    compute_args_digest,
    parse_utc,
)

DEFAULT_EXPIRES_IN_SECONDS = 3600.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HitlKeywords:
    """Robot Framework keywords for goal / clarification / approval / input
    flows backed by the ``hitl_interactions`` table (HarnessDatabase)."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self, db_path: str = "", database_url: str = "") -> None:
        self._db: Optional[HarnessDatabase] = None
        if db_path or database_url:
            self.connect_hitl_database(db_path=db_path, database_url=database_url)

    @property
    def db(self) -> HarnessDatabase:
        if self._db is None:
            raise RuntimeError(
                "No HITL database connected — call 'Connect Hitl Database' "
                "(or construct the library with db_path= / database_url=) first."
            )
        return self._db

    # -- plumbing -----------------------------------------------------------

    @keyword("Connect Hitl Database")
    def connect_hitl_database(self, db_path: str = "", database_url: str = "") -> None:
        """Connect the library to the HITL database.

        Exactly one of ``db_path`` (SQLite file) or ``database_url``
        (sqlite:/// or postgresql://) must be given.
        """
        if bool(db_path) == bool(database_url):
            raise ValueError(
                "Connect Hitl Database needs exactly one of db_path= or database_url="
            )
        if db_path:
            self._db = HarnessDatabase(db_path=db_path)
        else:
            self._db = HarnessDatabase(database_url=database_url)
        logger.info(f"HITL database connected ({self.db.get_version()})")

    @keyword("Get Interaction")
    def get_interaction(self, interaction_id: str) -> Dict[str, Any]:
        """Return one interaction row as a dict; fails if it is missing."""
        return dataclasses.asdict(self._get_or_raise(interaction_id))

    # -- creation keywords ---------------------------------------------------

    @keyword("Set Goal")
    def set_goal(self, session_id: str, goal: str) -> str:
        """Record a human-authored goal for the session.

        Goals are created already resolved (the human's act of setting the
        goal is the response); they never expire and never authorize tool
        execution (the gate keys on ``kind == 'approval'``).
        """
        now = _utc_now().isoformat()
        interaction_id = self.db.save_interaction(
            HitlInteraction(
                session_id=session_id,
                kind="goal",
                prompt=goal,
                created_at=now,
                response=goal,
                status="approved",
                resolved_at=now,
            )
        )
        logger.info(f"Goal set for session {session_id}: {goal!r} ({interaction_id})")
        return interaction_id

    @keyword("Get Current Goal")
    def get_current_goal(self, session_id: str) -> str:
        """Return the most recently set goal for the session."""
        goals = self.db.list_interactions(session_id, kind="goal")
        if not goals:
            raise LookupError(f"no goal set for session {session_id!r}")
        return goals[-1].prompt

    @keyword("Request Clarification")
    def request_clarification(
        self,
        session_id: str,
        question: str,
        target_action_id: str = "",
        args: Optional[Mapping[str, Any]] = None,
        expires_in: float = DEFAULT_EXPIRES_IN_SECONDS,
    ) -> str:
        """Create a pending clarification request and return its id.

        ``target_action_id`` / ``args`` are recorded as *context only*: a
        clarification response resumes reasoning but can never authorize
        the referenced action, regardless of these fields.
        """
        return self._create_pending(
            session_id,
            kind="clarification",
            prompt=question,
            target_action_id=target_action_id,
            args_digest=compute_args_digest(args) if args is not None else "",
            expires_in=expires_in,
        )

    @keyword("Request Human Approval")
    def request_human_approval(
        self,
        session_id: str,
        prompt: str,
        target_action_id: str,
        args: Mapping[str, Any],
        expires_in: float = DEFAULT_EXPIRES_IN_SECONDS,
    ) -> str:
        """Create a pending approval bound to an exact action and args.

        The approval only ever authorizes ``target_action_id`` executed
        with arguments whose canonical digest equals the one recorded
        here; it expires fail-closed after ``expires_in`` seconds.
        """
        if not target_action_id:
            raise ValueError("Request Human Approval requires a target_action_id")
        return self._create_pending(
            session_id,
            kind="approval",
            prompt=prompt,
            target_action_id=target_action_id,
            args_digest=compute_args_digest(args),
            expires_in=expires_in,
        )

    @keyword("Request Human Input")
    def request_human_input(
        self,
        session_id: str,
        prompt: str,
        expires_in: float = DEFAULT_EXPIRES_IN_SECONDS,
    ) -> str:
        """Create a pending free-form input request and return its id."""
        return self._create_pending(
            session_id, kind="input", prompt=prompt, expires_in=expires_in
        )

    # -- resolution & polling -------------------------------------------------

    @keyword("Resolve Interaction")
    def resolve_interaction(
        self, interaction_id: str, status: str, response: str = ""
    ) -> Dict[str, Any]:
        """Resolve a pending interaction — the human/table-update path.

        ``status`` must be ``approved`` or ``denied``. Resolving a row that
        already timed out fails closed: the row is marked ``expired`` and
        the stale response is rejected (never applied).
        """
        if status not in ("approved", "denied"):
            raise ValueError(
                f"Resolve Interaction status must be 'approved' or 'denied', "
                f"got {status!r}"
            )
        row = self._get_or_raise(interaction_id)
        if row.status != "pending":
            raise HitlApprovalError(
                f"interaction {interaction_id} is already {row.status} — "
                "it cannot be resolved again"
            )
        if self._is_past_expiry(row):
            self._mark_expired(interaction_id)
            raise HitlApprovalError(
                f"interaction {interaction_id} expired at {row.expires_at} — "
                "stale responses fail closed"
            )
        transitioned = self.db.resolve_interaction(
            interaction_id, status, response, _utc_now().isoformat()
        )
        if not transitioned:
            fresh = self._get_or_raise(interaction_id)
            raise HitlApprovalError(
                f"interaction {interaction_id} was resolved concurrently "
                f"(now {fresh.status}) — this response was not applied"
            )
        logger.info(f"Interaction {interaction_id} resolved: {status}")
        return self.get_interaction(interaction_id)

    @keyword("Check Approval Status")
    def check_approval_status(self, interaction_id: str) -> str:
        """Return the effective status of an interaction.

        A pending row whose ``expires_at`` has passed reports ``expired``
        even before a poller persists the transition (fail-closed view).
        """
        row = self._get_or_raise(interaction_id)
        if row.status == "pending" and self._is_past_expiry(row):
            return "expired"
        return row.status

    @keyword("Wait For Human Input")
    def wait_for_human_input(
        self,
        interaction_id: str,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """Poll an interaction until it resolves, expires, or times out.

        Returns the final row as a dict. On wall-clock timeout (or when the
        row's own ``expires_at`` passes) the row is marked ``expired`` in
        the table — fail-closed, so a late human response can no longer
        resurrect the request — and the expired row is returned.
        """
        deadline = time.monotonic() + float(timeout)
        while True:
            row = self._get_or_raise(interaction_id)
            if row.status != "pending":
                return dataclasses.asdict(row)
            if self._is_past_expiry(row) or time.monotonic() >= deadline:
                self._mark_expired(interaction_id)
                logger.warn(
                    f"Interaction {interaction_id} received no human response "
                    "in time — marked expired (fail closed)"
                )
                return dataclasses.asdict(self._get_or_raise(interaction_id))
            time.sleep(max(0.0, min(float(poll_interval), deadline - time.monotonic())))

    # -- enforcement keywords --------------------------------------------------

    @keyword("Is Action Approved")
    def is_action_approved(
        self, session_id: str, target_action_id: str, args: Mapping[str, Any]
    ) -> bool:
        """True only when a live approval binds this exact action + args."""
        decision = HitlApprovalGate(self.db, session_id).check(target_action_id, args)
        if not decision.allowed:
            logger.info(f"Action {target_action_id!r} not approved: {decision.reason}")
        return decision.allowed

    @keyword("Ensure Action Approved")
    def ensure_action_approved(
        self, session_id: str, target_action_id: str, args: Mapping[str, Any]
    ) -> str:
        """Fail unless the action is approved; returns the authorizing row id."""
        decision = HitlApprovalGate(self.db, session_id).check(target_action_id, args)
        if not decision.allowed:
            raise HitlApprovalError(decision.reason)
        return decision.interaction_id

    # -- internals --------------------------------------------------------------

    def _create_pending(
        self,
        session_id: str,
        *,
        kind: str,
        prompt: str,
        target_action_id: str = "",
        args_digest: str = "",
        expires_in: float = DEFAULT_EXPIRES_IN_SECONDS,
    ) -> str:
        now = _utc_now()
        interaction_id = self.db.save_interaction(
            HitlInteraction(
                session_id=session_id,
                kind=kind,
                prompt=prompt,
                created_at=now.isoformat(),
                target_action_id=target_action_id,
                args_digest=args_digest,
                expires_at=(now + timedelta(seconds=float(expires_in))).isoformat(),
            )
        )
        logger.info(
            f"HITL {kind} requested for session {session_id} "
            f"({interaction_id}, expires in {expires_in}s)"
        )
        return interaction_id

    def _get_or_raise(self, interaction_id: str) -> HitlInteraction:
        row = self.db.get_interaction(interaction_id)
        if row is None:
            raise LookupError(f"no hitl_interactions row with id={interaction_id!r}")
        return row

    @staticmethod
    def _is_past_expiry(row: HitlInteraction) -> bool:
        return bool(row.expires_at) and parse_utc(row.expires_at) <= _utc_now()

    def _mark_expired(self, interaction_id: str) -> None:
        # Compare-and-set: if a human resolution landed in the same instant,
        # that resolution wins and this no-ops (the caller re-reads the row).
        self.db.resolve_interaction(
            interaction_id, "expired", "", _utc_now().isoformat()
        )
