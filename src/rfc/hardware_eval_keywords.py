"""Robot entry points for hardware tasks, context matrices and browser use."""

from __future__ import annotations

import hashlib
import copy
import importlib
from importlib import metadata
from functools import lru_cache
import json
import os
import time
import platform
from pathlib import Path
from typing import Any, Callable

import yaml
from robot.api import logger
from robot.api.deco import keyword
from robot.libraries.BuiltIn import BuiltIn

from . import __version__
from .exceptions import RFCSkipError
from .hardware_browser import HardwareSandbox, browser_task_prompt, run_browser_agent
from .hardware_eval import (
    GRADER_VERSION,
    OUTPUT_RESERVE,
    build_pack,
    compare_runs,
    digest,
    load_benchmark,
    parse_answer,
    score_answer,
)
from .llm_client import create_provider, unwrap_provider
from .openai_client import OpenAIClient
from .rfc_data import emit_rfc_data


@lru_cache(maxsize=1)
def dependency_manifest() -> dict[str, Any]:
    """Snapshot installed distributions and Browser's bundled runtime revisions."""
    packages = sorted(
        (str(dist.metadata["Name"]), dist.version)
        for dist in metadata.distributions()
        if dist.metadata.get("Name")
    )
    assets: dict[str, str | None] = {}
    try:
        browser = metadata.distribution("robotframework-browser")
    except metadata.PackageNotFoundError:
        pass
    else:
        for name in (
            "Browser/wrapper/package-lock.json",
            "Browser/wrapper/node_modules/playwright/package.json",
            "Browser/wrapper/node_modules/playwright-core/package.json",
            "Browser/wrapper/node_modules/playwright-core/browsers.json",
        ):
            path = Path(str(browser.locate_file(name)))
            assets[name] = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else None
            )
    return {
        "python": platform.python_version(),
        "packages": packages,
        "browser_assets": assets,
    }


def harness_digest(root: Path) -> str:
    """Identify the full local implementation, including providers and tool execution."""
    runner = root.parent.parent / "scripts/hardware_local_eval.py"
    return digest(
        {
            "version": __version__,
            "dependencies": dependency_manifest(),
            "native_runner": hashlib.sha256(runner.read_bytes()).hexdigest()
            if runner.is_file()
            else None,
            "owned_runner": os.getenv("HW_RUNNER_SHA256", ""),
            "modules": {
                str(path.relative_to(root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(root.rglob("*.py"))
            },
        }
    )


# Snapshot once per process so later workspace edits cannot relabel loaded code.
HARNESS_VERSION = harness_digest(Path(__file__).parent)


def token_counter(path: str) -> tuple[Callable[[str], int] | None, str]:
    """Load a pinned local tokenizer.json; never download/execute remote code."""
    if not path:
        return None, ""
    try:
        tokenizers = importlib.import_module("tokenizers")
    except ImportError as exc:
        raise RFCSkipError(
            "Install the hardware-eval extra for token counting"
        ) from exc
    tokenizer = tokenizers.Tokenizer.from_file(path)
    identity = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return lambda text: len(
        tokenizer.encode(text, add_special_tokens=False).ids
    ), identity


def verify_token_usage(
    local_tokens: int | None,
    metrics: dict[str, Any],
    context_limit: int,
    output_limit: int,
) -> bool:
    """Conservatively reject missing usage, possible truncation and output caps.

    Server input usage includes its chat wrapper; it must not be smaller than
    exact local prompt-text tokens. Providers with incompatible/cache-only
    counters remain unverified rather than silently passing the gate.
    """
    prompt = metrics.get("prompt_eval_count")
    output = metrics.get("eval_count")
    return bool(
        type(local_tokens) is int
        and metrics.get("finish_reason") == "stop"
        and local_tokens > 0
        and type(prompt) is int
        and prompt >= local_tokens
        and type(output) is int
        and 0 < output < output_limit
        and context_limit > 0
        and prompt + output_limit <= context_limit
    )


class HardwareEvalKeywords:
    """Opt-in evaluation; importing a Robot suite never calls an endpoint."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(
        self,
        fixtures: str,
        output: str = "",
        client: Any = None,
    ) -> None:
        self.benchmark = load_benchmark(fixtures)
        self.fixtures = Path(fixtures)
        self.output = Path(output) if output else None
        self.client = client
        self.injected = client is not None
        self.output_reserve = int(os.getenv("HW_OUTPUT_TOKENS", str(OUTPUT_RESERVE)))
        self.json_constraint = os.getenv("HW_JSON_OBJECT_CONSTRAINT") == "1"
        if self.output_reserve < 1:
            raise ValueError("HW_OUTPUT_TOKENS must be positive")

    def _output(self) -> Path:
        if self.output is None:
            self.output = Path(BuiltIn().get_variable_value("${OUTPUT DIR}", "results"))
        self.output.mkdir(parents=True, exist_ok=True)
        return self.output

    def _base_row(
        self,
        case_id: str,
        context: int,
        position: str,
        trial: int,
        mode: str,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id + (":browser" if mode == "browser" else ""),
            "category": self.benchmark["cases"][case_id]["category"],
            "context_tokens": context,
            "position": position,
            "trial": trial,
            "fixture_sha256": self.benchmark["sha256"],
            "grader_version": GRADER_VERSION,
            "harness_version": HARNESS_VERSION,
            "dependency_manifest": copy.deepcopy(dependency_manifest()),
            "model": str(self.client.model)
            if self.client is not None
            else os.getenv("DEFAULT_MODEL", ""),
            "model_digest": os.getenv("HW_MODEL_DIGEST", ""),
            "adapter_id": os.getenv("HW_ADAPTER_ID", "none"),
            "weights_format": os.getenv("HW_WEIGHTS_FORMAT", "unspecified"),
            "runtime_manifest": json.loads(os.getenv("HW_RUNTIME_MANIFEST", "{}")),
            "sampling": {
                "temperature": 0.0,
                "seed": trial,
                "max_tokens": self.output_reserve,
                "json_schema": {"type": "object"} if self.json_constraint else None,
            },
            "reference_tokenizer": "",
            "model_tokenizer": "",
            "prompt_sha256": "",
            "token_count_verified": False,
            "live": False,
            "status": "not_started",
            "unsafe_actions": 0,
            "passed": False,
            "ttft_ms": None,
            "peak_vram_bytes": None,
        }

    def _archive(self, row: dict[str, Any]) -> None:
        path = self._output() / "hardware-results.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        emit_rfc_data("hardware_result", json.dumps(row, sort_keys=True))
        logger.info(
            f"Hardware evaluation {row['case_id']}: {row['status']}, passed={row['passed']}"
        )

    def _prepare_client(self) -> None:
        if self.injected:
            return
        if os.getenv("HW_EVAL_LIVE") != "1":
            raise RFCSkipError("Set HW_EVAL_LIVE=1 to enable live model evaluation")
        if os.getenv("RFC_RUN_MODE", "").lower() in {"replay", "verify"} or os.getenv(
            "ANSWER_CACHE_ENABLED", ""
        ).lower() in {"1", "true", "yes"}:
            raise RFCSkipError(
                "Live hardware measurements require answer caching/replay off"
            )
        if self.client is None:
            self.client = create_provider(
                temperature=0.0,
                max_tokens=self.output_reserve,
                max_retries=0,
                response_format="json",
            )

    @keyword("Get Hardware Case Ids")
    def get_hardware_case_ids(self, category: str = "") -> list[str]:
        return [
            key
            for key, case in self.benchmark["cases"].items()
            if not category or case["category"] == category
        ]

    @keyword("Evaluate Hardware Case")
    def evaluate_hardware_case(
        self,
        case_id: str,
        context_tokens: int = 0,
        position: str = "spread",
        trial: int = 0,
    ) -> dict[str, Any]:
        return self._evaluate(
            case_id, int(context_tokens), position, int(trial), "text"
        )

    @keyword("Evaluate Hardware Browser Task")
    def evaluate_hardware_browser_task(
        self,
        case_id: str,
        trial: int = 0,
    ) -> dict[str, Any]:
        return self._evaluate(case_id, 0, "browser", int(trial), "browser")

    def _evaluate(
        self,
        case_id: str,
        context: int,
        position: str,
        trial: int,
        mode: str,
    ) -> dict[str, Any]:
        row = self._base_row(case_id, context, position, trial, mode)
        case = self.benchmark["cases"][case_id]
        started = time.perf_counter()
        browser: Any = None
        try:
            cap = int(os.getenv("HW_MAX_CONTEXT", "0"))
            # The sweep coordinate sizes the input package. HW_MAX_CONTEXT
            # declares the server allocation, also requested from transports
            # that support per-request context. OpenAI-compatible servers ignore
            # num_ctx, so never pretend the input coordinate resized them.
            row["effective_context_tokens"] = cap
            if context and (not cap or context > cap):
                row["status"] = "unsupported_context"
                raise RFCSkipError(
                    f"Requested context {context} exceeds declared context {cap}"
                )
            self._prepare_client()
            row["live"] = not self.injected
            row["model"] = str(self.client.model)
            # Logging/provenance wrappers delegate reads, not attribute writes.
            # Keep generation wrapped, but configure the actual request client.
            request_client = unwrap_provider(self.client)
            request_client.seed = trial
            request_client.num_ctx = cap or None
            if self.json_constraint:
                if not isinstance(request_client, OpenAIClient):
                    raise RFCSkipError(
                        "Explicit JSON schema requires a compatible chat transport"
                    )
                request_client.response_format = "json"
                request_client.json_schema = {"type": "object"}
            reference_count, row["reference_tokenizer"] = token_counter(
                os.getenv("HW_REFERENCE_TOKENIZER", "")
            )
            model_count, row["model_tokenizer"] = token_counter(
                os.getenv("HW_MODEL_TOKENIZER", "")
            )
            if context and reference_count is None:
                row["status"] = "missing_tokenizer"
                raise RFCSkipError("Long context requires HW_REFERENCE_TOKENIZER")
            folder_name = f"hardware-{case_id}-{mode}-{context}-{position}-{trial}"
            folder = self._output() / folder_name
            if folder.exists():
                # Never overwrite evidence from an earlier repetition.
                row["status"] = "duplicate_run"
                raise ValueError(
                    "Result directory already exists; use a fresh output directory"
                )
            folder.mkdir()
            row["artifact"] = folder_name
            if mode == "text":
                pack = build_pack(
                    case,
                    self.benchmark["documents"],
                    context_tokens=context,
                    counter=reference_count,
                    position=position,
                    seed=trial,
                    output_reserve=self.output_reserve,
                )
                prompt = pack.pop("prompt")
                row.update(pack)
            else:
                prompt = browser_task_prompt(case)
                row["prompt_sha256"] = digest(prompt)
            (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
            calls: list[dict[str, Any]] = []

            def generate(text: str) -> str:
                local = model_count(text) if model_count else None
                if (
                    local is not None
                    and cap
                    and local + self.output_reserve + 256 > (context or cap)
                ):
                    raise RFCSkipError(
                        "Exact model token count exceeds configured context budget"
                    )
                call_start = time.perf_counter()
                raw = self.client.generate(text)
                metrics = dict(self.client.last_metrics or {})
                calls.append(
                    {
                        "prompt_sha256": digest(text),
                        "local_input_tokens": local,
                        "server_metrics": metrics,
                        "latency_ms": (time.perf_counter() - call_start) * 1000,
                        "token_count_verified": verify_token_usage(
                            local, metrics, context or cap, self.output_reserve
                        ),
                    }
                )
                (folder / f"call-{len(calls):03d}-prompt.txt").write_text(
                    text, encoding="utf-8"
                )
                (folder / f"call-{len(calls):03d}-response.txt").write_text(
                    raw, encoding="utf-8"
                )
                return str(raw)

            if mode == "text":
                raw = generate(prompt)
                (folder / "response.txt").write_text(raw, encoding="utf-8")
                try:
                    answer = parse_answer(raw)
                except ValueError as exc:
                    answer = {}
                    row["parse_error"] = type(exc).__name__
                row.update(score_answer(case, answer))
            else:
                try:
                    browser = importlib.import_module("Browser").Browser()
                    browser.new_browser("chromium", headless=True)
                    browser.new_context(acceptDownloads=False)
                    browser.set_browser_timeout("3 seconds")
                except Exception as exc:
                    row["status"] = "browser_unavailable"
                    raise RFCSkipError(
                        "Install playwright extra and run rfbrowser init chromium"
                    ) from exc
                with HardwareSandbox(
                    self.benchmark["documents"], browser, folder / "screenshots"
                ) as box:
                    result = run_browser_agent(case, box, generate)
                    trace = result.pop("trace")
                    (folder / "trace.json").write_text(
                        json.dumps(trace, indent=2), encoding="utf-8"
                    )
                    row.update(result)
            row["calls"] = calls
            row["token_count_verified"] = bool(calls) and all(
                c["token_count_verified"] for c in calls
            )
            row["status"] = "completed"
        except RFCSkipError:
            if row["status"] == "not_started":
                row["status"] = (
                    "disabled"
                    if os.getenv("HW_EVAL_LIVE") != "1" and not self.injected
                    else "unavailable"
                )
            raise
        except Exception as exc:
            row["status"] = "error"
            row["error_type"] = type(exc).__name__
            # A provider outage is incomplete evidence, never a model pass/fail.
            raise RFCSkipError(
                f"Hardware evaluation incomplete: {type(exc).__name__}"
            ) from exc
        finally:
            if browser is not None:
                try:
                    browser.close_browser()
                except Exception:
                    row["status"] = "browser_cleanup_error"
                    row["passed"] = False
            row["latency_ms"] = (time.perf_counter() - started) * 1000
            self._archive(row)
        return row

    @keyword("Assert Hardware Case Passed")
    def assert_hardware_case_passed(self, result: dict[str, Any]) -> None:
        if not result["passed"]:
            raise AssertionError(
                f"{result['case_id']}: correctness={result.get('accuracy', 0):.3f}, "
                f"citations={result.get('citation_accuracy', 0):.3f}, "
                f"critical_failures={result.get('critical_failures', 0)}"
            )

    @keyword("Compare Hardware Runs")
    def compare_hardware_runs(
        self,
        baseline_path: str,
        candidate_path: str,
        profile_path: str = "",
    ) -> dict[str, Any]:
        rows = [
            [
                json.loads(line)
                for line in Path(path).read_text().splitlines()
                if line.strip()
            ]
            for path in (baseline_path, candidate_path)
        ]
        profile = yaml.safe_load(
            Path(profile_path or self.fixtures / "gate_profile.yaml").read_text()
        )
        required = {
            (
                case_id + (":browser" if group["mode"] == "browser" else ""),
                context,
                position,
                trial,
            )
            for group in profile["groups"]
            for case_id in group["cases"]
            for context in group["contexts"]
            for position in group["positions"]
            for trial in group["trials"]
        }
        result = compare_runs(
            rows[0], rows[1], required_coordinates=required, benchmark=self.benchmark
        )
        result["profile_sha256"] = digest(profile)
        (self._output() / "hardware-gate.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        emit_rfc_data("hardware_gate", json.dumps(result))
        return result
