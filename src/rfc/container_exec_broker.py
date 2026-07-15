"""Host-side broker routing a live agent's code-exec tool calls into the
pre-warmed, network-isolated sandbox container (#235).

Per Elon Tusk's design note on Issue #235, the interception point for
per-tool-call code execution is *tool substitution*: deny each harness's native
host-executing code tools and hand it replacements whose implementation is
``docker exec`` into a pre-warmed container owned by this single host-side
broker. The broker is the ONE choke point where egress isolation and timing
instrumentation live. Non-code tool calls (model I/O, reasoning, clarifying
questions) never touch the broker -- only ``kind in {bash, write, edit}`` route
into the container ("relocate the hands, not the head").

The contract is harness-agnostic. Every remoted tool marshals into a
:class:`SandboxToolCall`; the broker runs it via ``docker exec`` and returns a
:class:`SandboxToolResult`, which the CLI hands back to the model as that tool's
output. One contract, three harnesses.

Performance (owner doctrine: always track cost/time/compute). The broker wraps
each dispatch in a monotonic timer and records ``sandbox_exec_overhead_ms`` per
call -- broker-dispatch wall time minus the in-container command's own runtime.
Budget: p50 <= 120 ms, p95 <= 300 ms added per code-exec call over an equivalent
host exec. Over budget regresses cross-harness comparability (a chattier harness
pays proportionally more overhead), so :func:`check_overhead_budget` gates it.
"""

from __future__ import annotations

import base64
import posixpath
import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from rfc.harness_models import METRIC_SANDBOX_EXEC_OVERHEAD_MS, AgenticMetric

# The single working tree inside the sandbox container (coherence ruling, #235).
_WORKSPACE = "/workspace"

# Code-exec tool kinds the broker services. Anything else is a host-side,
# non-code tool call and never reaches the broker.
CODE_EXEC_KINDS: tuple[str, ...] = ("bash", "write", "edit")

# Per-call overhead budget over an equivalent host exec (design note, #235).
OVERHEAD_P50_BUDGET_MS = 120.0
OVERHEAD_P95_BUDGET_MS = 300.0

# In-container command self-timing (#235 B2). Every dispatched command is wrapped
# so the shell reports the command's OWN in-container runtime (excluding the
# docker-exec transport) on a sentinel line the broker strips from the output.
# sandbox_exec_overhead_ms = broker wall time - this inner runtime = docker-exec
# transport + marshalling -- the cost #235 ADDS over an equivalent host exec,
# which is exactly what the budget gate must be able to see (a create-per-call
# regression inflates the transport, not the command runtime, so it now fires).
# The sentinel is appended directly after the command's own output (no leading
# separator), so the pattern strips ONLY from the sentinel onward -- the command's
# own trailing newline is its output and is preserved.
_TIMING_SENTINEL = "__RFC_EXEC_MS__"
_TIMING_RE = re.compile(re.escape(_TIMING_SENTINEL) + r"(-?\d+)[ \t]*\r?\n?\Z")

# Inline-argv ceiling avoidance (#235 B3). A single ``sh -c <cmd>`` argv token is
# capped by the kernel's MAX_ARG_STRLEN (128 KiB), so a base64 payload inlined
# whole fails above ~96 KiB raw. Small writes stay single-shot; larger ones
# stream the base64 to an out-of-tree temp file in bounded chunks, then decode.
_SAFE_INLINE_B64 = 60_000  # base64 chars kept well under MAX_ARG_STRLEN
_CHUNK_B64 = 60_000  # base64 chars appended per exec on the chunked path
_TMP_PREFIX = "/tmp/rfc-exec-write-"  # out of /workspace so it is never churn


class ContainerExecBackend(Protocol):
    """The one method the broker needs from a container manager (``docker exec``).

    Satisfied by :class:`rfc.container_manager.ContainerManager` and by the same
    fake backends the sandbox tests already inject, so the broker round-trips
    hermetically without a Docker daemon.
    """

    def execute_command(
        self,
        container_id: str,
        command: str,
        timeout: int = 30,
        workdir: Optional[str] = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SandboxToolCall:
    """One code-exec tool call marshalled for the broker (harness-agnostic).

    ``kind`` is one of :data:`CODE_EXEC_KINDS`. For ``bash`` the ``payload`` is
    the shell command; for ``write``/``edit`` it is the full file content and
    ``path`` is the workspace-relative target. ``cwd`` is the in-container
    working directory (always ``/workspace`` -- the single working tree).
    """

    kind: str
    payload: str
    path: Optional[str] = None
    cwd: str = _WORKSPACE


@dataclass(frozen=True)
class SandboxToolResult:
    """The broker's reply for one :class:`SandboxToolCall`.

    ``duration_ms`` is the in-container command's OWN runtime (self-timed inside
    the shell, EXCLUDING the docker-exec transport), not the broker's dispatch
    overhead -- the latter is recorded separately as ``sandbox_exec_overhead_ms``
    and is precisely ``broker_wall - duration_ms`` (transport + marshalling).
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float


def _workspace_target(path: str) -> str:
    """Resolve a workspace-relative ``path`` to its ``/workspace/<rel>`` target.

    Raises :class:`ValueError` (S1) when the path escapes ``/workspace`` via
    ``..`` traversal -- the contract declares ``path`` workspace-relative, and a
    ``find /workspace`` churn manifest must see every file the agent writes.
    Absolute paths are re-rooted under ``/workspace`` (``/etc/x`` ->
    ``/workspace/etc/x``), which stays in-tree. Symlink-parent escapes cannot be
    seen host-side and are rejected in-container by the write command's guard.
    """
    rel = path.lstrip("/")
    normalized = posixpath.normpath(rel)
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError(
            f"write path {path!r} escapes {_WORKSPACE} (workspace-relative required)"
        )
    return f"{_WORKSPACE}/{rel}"


def _parent_dir(target: str) -> str:
    head, sep, _ = target.rpartition("/")
    return head if sep else "."


def _workspace_guard(target: str) -> str:
    """A shell guard that aborts (exit 3) if ``target`` resolves outside /workspace.

    ``realpath -m`` canonicalizes symlinks in existing path components without
    requiring the target to exist, so a symlink *parent* pointing out of the tree
    is caught here even though it is invisible host-side (S1).
    """
    q = shlex.quote(target)
    return (
        f'case "$(realpath -m -- {q})" in '
        f"{_WORKSPACE}|{_WORKSPACE}/*) : ;; "
        f'*) echo "rfc-exec: write path escapes {_WORKSPACE}" >&2; exit 3 ;; esac'
    )


def _inline_write_command(target: str, encoded: str) -> str:
    """Single-shot write: guard, mkdir -p, then decode the inlined base64."""
    parent = shlex.quote(_parent_dir(target))
    quoted = shlex.quote(target)
    return (
        f"{_workspace_guard(target)} && mkdir -p {parent} && "
        f"printf %s {encoded} | base64 -d > {quoted}"
    )


def _chunk(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _timed_wrapper(command: str) -> str:
    """Wrap ``command`` so the shell reports its own in-container runtime (ms).

    The command runs in a subshell (so its ``exit``/``cd`` don't skip the timer),
    bracketed by ``date +%s%N``; the delta is emitted on a trailing sentinel line
    the broker strips. If nanosecond ``date`` is unavailable the marker carries
    ``-1`` and the broker falls back to the backend's own duration. The wrapped
    command preserves the inner exit code.
    """
    return (
        "__rfc_s=$(date +%s%N 2>/dev/null); "
        f"( {command} ); __rfc_rc=$?; "
        "__rfc_e=$(date +%s%N 2>/dev/null); "
        'case "$__rfc_s$__rfc_e" in "" | *[!0-9]*) __rfc_ms=-1 ;; '
        "*) __rfc_ms=$(( (__rfc_e - __rfc_s) / 1000000 )) ;; esac; "
        f"printf '%s%s\\n' '{_TIMING_SENTINEL}' \"$__rfc_ms\"; "
        "exit $__rfc_rc"
    )


def _parse_timing(raw: str) -> tuple[str, Optional[float]]:
    """Split the trailing timing sentinel off ``raw``.

    Returns ``(clean_stdout, inner_ms)``. ``inner_ms`` is None when no marker is
    present (e.g. a hermetic fake backend) or the shell reported ``-1``.
    """
    match = _TIMING_RE.search(raw)
    if match is None:
        return raw, None
    reported = int(match.group(1))
    clean = raw[: match.start()]
    return clean, (float(reported) if reported >= 0 else None)


class ContainerExecBroker:
    """Host-side broker: one ``docker exec`` channel into one live container.

    Bound to a single pre-warmed, network-isolated container for the whole run.
    Dispatches :class:`SandboxToolCall` -> :class:`SandboxToolResult` and records
    ``sandbox_exec_overhead_ms`` per dispatch so the perf budget is measurable.
    """

    def __init__(
        self,
        backend: ContainerExecBackend,
        container_id: str,
        *,
        default_timeout: int = 300,
        metrics_sink: Optional[Path] = None,
    ) -> None:
        self._backend = backend
        self._container_id = container_id
        self._default_timeout = default_timeout
        self._overheads_ms: list[float] = []
        # When the broker runs inside the rfc-exec MCP server child process, the
        # sandbox parent can't read in-memory samples; each overhead sample is
        # also appended here (one float per line) so the parent collects them
        # after the run via :func:`read_overhead_samples`.
        self._metrics_sink = metrics_sink

    @property
    def container_id(self) -> str:
        return self._container_id

    @property
    def overhead_samples_ms(self) -> tuple[float, ...]:
        """Per-dispatch overhead samples in ms.

        Each sample = broker-dispatch wall time - the in-container command's OWN
        runtime = docker-exec transport + marshalling, i.e. the cost this path
        ADDS over an equivalent host exec (#235 B2).
        """
        return tuple(self._overheads_ms)

    def _timeout(self, timeout: Optional[int]) -> int:
        return timeout if timeout is not None else self._default_timeout

    def _exec(self, command: str, timeout: Optional[int], cwd: str) -> dict:
        return self._backend.execute_command(
            self._container_id,
            command,
            timeout=self._timeout(timeout),
            workdir=cwd or _WORKSPACE,
        )

    def _run_timed(
        self, command: str, timeout: Optional[int], cwd: str
    ) -> tuple[int, str, str, Optional[float]]:
        """Exec ``command`` self-timed; return (exit, clean_stdout, stderr, inner_ms).

        ``inner_ms`` is the command's own in-container runtime parsed from the
        timing sentinel (None -> fall back to the backend's duration).
        """
        raw = self._exec(_timed_wrapper(command), timeout, cwd)
        stdout, inner_ms = _parse_timing(str(raw.get("stdout") or ""))
        if inner_ms is None:
            duration = raw.get("duration_ms")
            inner_ms = float(duration) if duration is not None else None
        return (
            int(raw.get("exit_code") or 0),
            stdout,
            str(raw.get("stderr") or ""),
            inner_ms,
        )

    def _run_write(
        self, call: SandboxToolCall, timeout: Optional[int]
    ) -> tuple[int, str, str, Optional[float]]:
        """Materialize a write/edit's whole-file content in the container.

        Small payloads go single-shot (one timed exec). Large ones stream the
        base64 to an out-of-tree temp file in bounded chunks (each an exec, all
        pure transport that correctly counts as overhead) then decode it in a
        final timed exec -- so writes are unbounded without hitting the inline
        argv ceiling (#235 B3).
        """
        if not call.path:
            raise ValueError(f"{call.kind!r} tool call requires a path")
        target = _workspace_target(call.path)
        cwd = call.cwd or _WORKSPACE
        encoded = base64.b64encode(call.payload.encode("utf-8")).decode("ascii")

        if len(encoded) <= _SAFE_INLINE_B64:
            return self._run_timed(_inline_write_command(target, encoded), timeout, cwd)

        tmp = f"{_TMP_PREFIX}{uuid.uuid4().hex}.b64"
        q_tmp = shlex.quote(tmp)
        for idx, part in enumerate(_chunk(encoded, _CHUNK_B64)):
            redirect = ">" if idx == 0 else ">>"
            raw = self._exec(f"printf %s {part} {redirect} {q_tmp}", timeout, cwd)
            if int(raw.get("exit_code") or 0) != 0:
                self._exec(f"rm -f {q_tmp}", timeout, cwd)
                return int(raw["exit_code"]), str(raw.get("stdout") or ""), "", None
        parent = shlex.quote(_parent_dir(target))
        quoted = shlex.quote(target)
        finalize = (
            f"{_workspace_guard(target)} && mkdir -p {parent} && "
            f"base64 -d {q_tmp} > {quoted}; __rc=$?; rm -f {q_tmp}; exit $__rc"
        )
        return self._run_timed(finalize, timeout, cwd)

    def dispatch(
        self, call: SandboxToolCall, *, timeout: Optional[int] = None
    ) -> SandboxToolResult:
        """Run one code-exec tool call in the container, timing the overhead.

        Overhead recorded (#235 B2) = broker-dispatch wall time minus the
        in-container command's OWN runtime (self-timed in-shell, NOT the backend's
        transport-inclusive duration) = docker-exec transport + marshalling. So a
        create-per-call / transport regression inflates the sample and trips the
        budget, instead of being subtracted away. Clamped at zero.
        """
        started = time.perf_counter()
        if call.kind == "bash":
            exit_code, stdout, stderr, inner_ms = self._run_timed(
                call.payload, timeout, call.cwd or _WORKSPACE
            )
        elif call.kind in ("write", "edit"):
            # write and edit both materialize the full new file content at
            # ``path`` (single-payload contract). Structured old/new-string edits
            # are a follow-up; a whole-file write is the honest, correct subset.
            exit_code, stdout, stderr, inner_ms = self._run_write(call, timeout)
        else:
            raise ValueError(
                f"Unsupported tool kind {call.kind!r}; expected one of {CODE_EXEC_KINDS}"
            )
        wall_ms = (time.perf_counter() - started) * 1000.0

        resolved_inner = inner_ms if inner_ms is not None else 0.0
        overhead_ms = max(0.0, wall_ms - resolved_inner)
        self._overheads_ms.append(overhead_ms)
        self._record_sample(overhead_ms)

        return SandboxToolResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=resolved_inner,
        )

    def _record_sample(self, overhead_ms: float) -> None:
        if self._metrics_sink is None:
            return
        try:
            with self._metrics_sink.open("a", encoding="utf-8") as handle:
                handle.write(f"{overhead_ms:.4f}\n")
        except OSError:
            # A metrics-sink write must never break the tool call it measures.
            pass

    def overhead_metrics(
        self, session_id: str, recorded_at: str, *, test_run_id: int = -1
    ) -> list[AgenticMetric]:
        """One ``sandbox_exec_overhead_ms`` EAV row per recorded dispatch.

        Lands on the RFC-007 S1 reserved-metric-key spine (EAV, no migration);
        the scoreboard aggregates per ``(harness, scenario, run)`` via the same
        ``AVG`` path the other reserved keys use. Callers own persistence.
        """
        return [
            AgenticMetric(
                session_id=session_id,
                metric_key=METRIC_SANDBOX_EXEC_OVERHEAD_MS,
                metric_value=sample,
                recorded_at=recorded_at,
                test_run_id=test_run_id,
            )
            for sample in self._overheads_ms
        ]


def read_overhead_samples(path: Path) -> list[float]:
    """Read overhead samples an MCP-child broker appended to ``path`` (one/line).

    Missing file or unparseable lines yield an empty / partial list rather than
    raising -- a missing sink just means the broker was never exercised.
    """
    if not path.is_file():
        return []
    samples: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(float(line))
        except ValueError:
            continue
    return samples


def percentile(samples: list[float] | tuple[float, ...], pct: float) -> float:
    """Linear-interpolated percentile of ``samples`` (``pct`` in 0..100).

    Empty input yields ``0.0``. Deliberately dependency-free (no numpy) so the
    budget gate runs anywhere the harness does.
    """
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


@dataclass(frozen=True)
class OverheadBudget:
    """Verdict of the per-call overhead budget check (design note, #235)."""

    n: int
    p50_ms: float
    p95_ms: float
    p50_budget_ms: float
    p95_budget_ms: float
    within_budget: bool
    samples_ms: tuple[float, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        verdict = "WITHIN budget" if self.within_budget else "OVER budget"
        return (
            f"sandbox_exec_overhead_ms n={self.n} "
            f"p50={self.p50_ms:.1f}ms (<= {self.p50_budget_ms:.0f}) "
            f"p95={self.p95_ms:.1f}ms (<= {self.p95_budget_ms:.0f}): {verdict}"
        )


def check_overhead_budget(
    samples: list[float] | tuple[float, ...],
    *,
    p50_budget_ms: float = OVERHEAD_P50_BUDGET_MS,
    p95_budget_ms: float = OVERHEAD_P95_BUDGET_MS,
) -> OverheadBudget:
    """Gate ``sandbox_exec_overhead_ms`` against the p50/p95 budget.

    Over budget means the broker path regresses cross-harness comparability and
    must be optimized before it is allowed to feed the scoreboard. With no
    samples the budget is vacuously met (nothing was routed through the broker).
    """
    p50 = percentile(samples, 50.0)
    p95 = percentile(samples, 95.0)
    within = p50 <= p50_budget_ms and p95 <= p95_budget_ms
    return OverheadBudget(
        n=len(samples),
        p50_ms=p50,
        p95_ms=p95,
        p50_budget_ms=p50_budget_ms,
        p95_budget_ms=p95_budget_ms,
        within_budget=within,
        samples_ms=tuple(samples),
    )
