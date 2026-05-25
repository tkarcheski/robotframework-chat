"""Self-healing decorator and strategy engine for Robot Framework keywords.

Provides an opt-in ``@self_healing`` decorator that wraps keyword methods
with automatic retry using escalating strategies:

1. **Prompt modification** — LLM rewrites the prompt with clarifications.
2. **Parameter adjustment** — Vary temperature, seed, max_tokens.
3. **Model fallback** — Try alternative models from a configured list.
4. **Escalation** — Create a GitHub issue with full failure context.

Each attempt is recorded as a :class:`HealingAttempt` and emitted via
RFC_DATA for capture by :class:`~rfc.self_healing_listener.SelfHealingListener`.

Usage::

    @self_healing(config=SelfHealingConfig(fallback_models=["qwen2.5:32b"]))
    @keyword("My Graded Keyword")
    def my_keyword(self, prompt, expected):
        ...
"""

import json
import subprocess
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from robot.api import logger

from .models import GradeResult
from .rfc_data import emit_rfc_data


@dataclass
class HealingAttempt:
    """Record of a single self-healing attempt."""

    attempt_number: int
    strategy: str  # "original", "prompt", "params", "model", "escalate"
    prompt_used: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    model_used: str = ""
    result: Optional[GradeResult] = None
    success: bool = False
    error: str = ""


@dataclass
class SelfHealingConfig:
    """Configuration for the self-healing decorator."""

    max_prompt_retries: int = 2
    max_param_retries: int = 3
    fallback_models: List[str] = field(default_factory=list)
    escalate_to_github: bool = True
    github_repo: str = "tkarcheski/robotframework-chat"
    score_threshold: float = 1.0
    param_temperatures: List[float] = field(default_factory=lambda: [0.0, 0.3, 0.7])
    param_seeds: List[int] = field(default_factory=lambda: [42, 123, 7])


def _extract_prompt_arg(args: tuple, kwargs: dict) -> Tuple[Optional[str], int]:
    """Extract the prompt string from keyword arguments.

    Returns (prompt, positional_index). The prompt is the first
    positional string arg, or kwargs["prompt"].
    """
    if "prompt" in kwargs:
        return kwargs["prompt"], -1
    for i, arg in enumerate(args):
        if isinstance(arg, str):
            return arg, i
    return None, -1


def _replace_prompt_arg(
    args: tuple, kwargs: dict, new_prompt: str, index: int
) -> Tuple[tuple, dict]:
    """Return copies of args/kwargs with the prompt replaced."""
    if "prompt" in kwargs:
        new_kwargs = dict(kwargs)
        new_kwargs["prompt"] = new_prompt
        return args, new_kwargs
    new_args = list(args)
    new_args[index] = new_prompt
    return tuple(new_args), kwargs


def _capture_params(instance: Any) -> Dict[str, Any]:
    """Snapshot the current LLM parameters from the keyword library."""
    params: Dict[str, Any] = {}
    client = getattr(instance, "client", None)
    if client is None:
        return params
    for attr in ("temperature", "max_tokens", "seed", "top_p", "top_k", "model"):
        val = getattr(client, attr, None)
        if val is not None:
            params[attr] = val
    return params


def _rewrite_prompt(
    instance: Any,
    original_prompt: str,
    expected: str,
    actual: str,
    failure_reason: str,
) -> str:
    """Ask the LLM to rewrite a prompt that failed grading.

    Uses the same client but asks for a clarified version of the prompt.
    Falls back to the original prompt if rewriting fails.
    """
    client = getattr(instance, "client", None)
    if client is None:
        return original_prompt

    rewrite_request = (
        "You are a prompt engineer. A test prompt failed to get the correct "
        "answer from an LLM. Rewrite the prompt to be clearer and more "
        "likely to produce the correct answer.\n\n"
        f"Original prompt:\n{original_prompt}\n\n"
        f"Expected answer:\n{expected}\n\n"
        f"Actual (wrong) answer:\n{actual}\n\n"
        f"Failure reason:\n{failure_reason}\n\n"
        "Return ONLY the rewritten prompt, nothing else."
    )
    try:
        rewritten = client.generate(rewrite_request)
        if rewritten and rewritten.strip():
            return rewritten.strip()
    except Exception as exc:
        logger.warn(f"Prompt rewrite failed: {exc}")
    return original_prompt


def _apply_params(instance: Any, params: Dict[str, Any]) -> None:
    """Apply parameter overrides to the LLM client."""
    client = getattr(instance, "client", None)
    if client is None:
        return
    for key, value in params.items():
        if hasattr(client, key):
            setattr(client, key, value)


def _restore_params(instance: Any, params: Dict[str, Any]) -> None:
    """Restore LLM client parameters from a snapshot."""
    _apply_params(instance, params)


def _param_variations(
    config: SelfHealingConfig,
    original_params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate parameter variations to try during healing."""
    if config.max_param_retries <= 0:
        return []
    variations: List[Dict[str, Any]] = []
    for temp in config.param_temperatures:
        if temp != original_params.get("temperature"):
            variation = dict(original_params)
            variation["temperature"] = temp
            variations.append(variation)
            if len(variations) >= config.max_param_retries:
                return variations
    for seed in config.param_seeds:
        if seed != original_params.get("seed"):
            variation = dict(original_params)
            variation["seed"] = seed
            variations.append(variation)
            if len(variations) >= config.max_param_retries:
                return variations
    return variations[: config.max_param_retries]


def _create_github_issue(
    config: SelfHealingConfig, attempts: List[HealingAttempt]
) -> bool:
    """Create a GitHub issue for unresolved test failures.

    Returns True if issue was created successfully.
    """
    title = f"Self-healing exhausted: {len(attempts)} attempts failed"
    body_lines = [
        "## Self-Healing Exhausted",
        "",
        f"The self-healing system tried {len(attempts)} strategies but "
        "could not resolve this test failure.",
        "",
        "### Attempts",
        "",
    ]
    for attempt in attempts:
        body_lines.append(
            f"**Attempt {attempt.attempt_number}** "
            f"(strategy: `{attempt.strategy}`, model: `{attempt.model_used}`)"
        )
        if attempt.result:
            body_lines.append(
                f"- Score: {attempt.result.score}, Reason: {attempt.result.reason}"
            )
        if attempt.error:
            body_lines.append(f"- Error: {attempt.error}")
        body_lines.append("")

    body = "\n".join(body_lines)

    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                config.github_repo,
                "--title",
                title,
                "--body",
                body,
                "--label",
                "self-healing",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Created GitHub issue: {result.stdout.strip()}")
            return True
        logger.warn(f"Failed to create GitHub issue: {result.stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warn(f"GitHub issue creation failed: {exc}")
    return False


def _emit_healing_data(
    attempts: List[HealingAttempt], success: bool, duration: float
) -> None:
    """Emit RFC_DATA keys for self-healing metadata."""
    emit_rfc_data("self_healing_attempts", str(len(attempts)))
    emit_rfc_data("self_healing_success", str(success))
    emit_rfc_data("self_healing_duration_seconds", f"{duration:.2f}")

    strategies_tried = [a.strategy for a in attempts]
    emit_rfc_data("self_healing_strategies_tried", json.dumps(strategies_tried))

    if success:
        final = next((a for a in reversed(attempts) if a.success), None)
        emit_rfc_data("self_healing_strategy", final.strategy if final else "unknown")
    else:
        emit_rfc_data("self_healing_strategy", "exhausted")

    if attempts:
        emit_rfc_data("self_healing_original_error", attempts[0].error)

    prompt_history = [a.prompt_used for a in attempts]
    emit_rfc_data("self_healing_prompt_history", json.dumps(prompt_history))


def _is_passing(result: Any, threshold: float) -> bool:
    """Check if a grading result meets the score threshold."""
    if isinstance(result, GradeResult):
        return result.score >= threshold
    if isinstance(result, tuple) and len(result) >= 1:
        try:
            return float(result[0]) >= threshold
        except (ValueError, TypeError):
            pass
    return False


def _extract_grade_result(result: Any) -> Optional[GradeResult]:
    """Extract a GradeResult from various return types."""
    if isinstance(result, GradeResult):
        return result
    if isinstance(result, tuple) and len(result) >= 2:
        try:
            return GradeResult(score=float(result[0]), reason=str(result[1]))
        except (ValueError, TypeError):
            pass
    return None


def _extract_expected_arg(args: tuple, kwargs: dict) -> str:
    """Extract the expected answer from keyword arguments."""
    if "expected" in kwargs:
        return str(kwargs["expected"])
    str_args = [a for a in args if isinstance(a, str)]
    if len(str_args) >= 2:
        return str_args[1]
    return ""


def self_healing(
    config: Optional[SelfHealingConfig] = None,
) -> Callable:
    """Decorator that adds self-healing retry to a grading keyword.

    Composes with ``@keyword()`` — apply ``@self_healing()`` ABOVE
    ``@keyword()``::

        @self_healing(config=SelfHealingConfig(fallback_models=["qwen2.5:32b"]))
        @keyword("My Graded Keyword")
        def my_keyword(self, prompt, expected):
            ...

    The decorator intercepts low-scoring results and applies escalating
    strategies: prompt rewriting, parameter variation, model fallback,
    and finally GitHub issue escalation.

    Args:
        config: Healing configuration. Uses defaults if not provided.

    Returns:
        A decorator function.
    """
    cfg = config or SelfHealingConfig()

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(self_instance: Any, *args: Any, **kwargs: Any) -> Any:
            attempts: List[HealingAttempt] = []
            start_time = time.monotonic()
            original_params = _capture_params(self_instance)
            prompt, prompt_idx = _extract_prompt_arg(args, kwargs)
            expected = _extract_expected_arg(args, kwargs)

            # --- Original execution ---
            attempt = HealingAttempt(
                attempt_number=1,
                strategy="original",
                prompt_used=prompt or "",
                parameters=dict(original_params),
                model_used=original_params.get("model", ""),
            )
            try:
                result = fn(self_instance, *args, **kwargs)
                grade = _extract_grade_result(result)
                attempt.result = grade
                if _is_passing(result, cfg.score_threshold):
                    attempt.success = True
                    attempts.append(attempt)
                    _emit_healing_data(attempts, True, time.monotonic() - start_time)
                    return result
                attempt.error = grade.reason if grade else "Score below threshold"
            except Exception as exc:
                attempt.error = str(exc)
                result = None
            attempts.append(attempt)

            if prompt is None:
                logger.warn(
                    "Self-healing: no prompt found in arguments, "
                    "skipping healing strategies"
                )
                _emit_healing_data(attempts, False, time.monotonic() - start_time)
                if result is not None:
                    return result
                raise  # noqa: PLE0704  — re-raise the caught exception

            # --- Strategy 1: Prompt modification ---
            last_error = attempt.error
            for i in range(cfg.max_prompt_retries):
                actual = ""
                if attempt.result:
                    actual = attempt.error
                modified_prompt = _rewrite_prompt(
                    self_instance, prompt, expected, actual, last_error
                )
                new_args, new_kwargs = _replace_prompt_arg(
                    args, kwargs, modified_prompt, prompt_idx
                )
                attempt = HealingAttempt(
                    attempt_number=len(attempts) + 1,
                    strategy="prompt",
                    prompt_used=modified_prompt,
                    parameters=dict(original_params),
                    model_used=original_params.get("model", ""),
                )
                try:
                    result = fn(self_instance, *new_args, **new_kwargs)
                    grade = _extract_grade_result(result)
                    attempt.result = grade
                    if _is_passing(result, cfg.score_threshold):
                        attempt.success = True
                        attempts.append(attempt)
                        _emit_healing_data(
                            attempts, True, time.monotonic() - start_time
                        )
                        return result
                    last_error = grade.reason if grade else "Score below threshold"
                    attempt.error = last_error
                except Exception as exc:
                    attempt.error = str(exc)
                    last_error = str(exc)
                attempts.append(attempt)

            # --- Strategy 2: Parameter adjustment ---
            variations = _param_variations(cfg, original_params)
            for params in variations:
                _apply_params(self_instance, params)
                attempt = HealingAttempt(
                    attempt_number=len(attempts) + 1,
                    strategy="params",
                    prompt_used=prompt,
                    parameters=dict(params),
                    model_used=params.get("model", ""),
                )
                try:
                    result = fn(self_instance, *args, **kwargs)
                    grade = _extract_grade_result(result)
                    attempt.result = grade
                    if _is_passing(result, cfg.score_threshold):
                        attempt.success = True
                        attempts.append(attempt)
                        _restore_params(self_instance, original_params)
                        _emit_healing_data(
                            attempts, True, time.monotonic() - start_time
                        )
                        return result
                    attempt.error = grade.reason if grade else "Score below threshold"
                except Exception as exc:
                    attempt.error = str(exc)
                attempts.append(attempt)
            _restore_params(self_instance, original_params)

            # --- Strategy 3: Model fallback ---
            original_model = original_params.get("model", "")
            client = getattr(self_instance, "client", None)
            for model_name in cfg.fallback_models:
                if model_name == original_model:
                    continue
                if client is not None:
                    client.model = model_name
                attempt = HealingAttempt(
                    attempt_number=len(attempts) + 1,
                    strategy="model",
                    prompt_used=prompt,
                    parameters=_capture_params(self_instance),
                    model_used=model_name,
                )
                try:
                    result = fn(self_instance, *args, **kwargs)
                    grade = _extract_grade_result(result)
                    attempt.result = grade
                    if _is_passing(result, cfg.score_threshold):
                        attempt.success = True
                        attempts.append(attempt)
                        if client is not None:
                            client.model = original_model
                        _emit_healing_data(
                            attempts, True, time.monotonic() - start_time
                        )
                        return result
                    attempt.error = grade.reason if grade else "Score below threshold"
                except Exception as exc:
                    attempt.error = str(exc)
                attempts.append(attempt)
            if client is not None:
                client.model = original_model

            # --- Strategy 4: Escalate ---
            if cfg.escalate_to_github:
                _create_github_issue(cfg, attempts)

            _emit_healing_data(attempts, False, time.monotonic() - start_time)
            return result

        return wrapper

    return decorator


__all__ = [
    "HealingAttempt",
    "SelfHealingConfig",
    "self_healing",
]
