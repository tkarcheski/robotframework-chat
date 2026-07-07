"""Ollama API client for LLM generation and model discovery."""

import os
import time
from typing import Any, Dict, List, Optional, Union

from robot.api import logger
import requests

from .constants import DEFAULT_TIMEOUT
from .exceptions import (
    ModelNotReadyError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    ProviderOfflineError,
)
from .retry import retry_on_transient


def _check_model_not_found(
    response: requests.Response, model: str, endpoint: str
) -> None:
    """Raise OllamaModelNotFoundError on 404, else call raise_for_status()."""
    if response.status_code == 404:
        detail = ""
        try:
            detail = response.json().get("error", "")
        except Exception:
            pass
        raise OllamaModelNotFoundError(model, endpoint, detail)
    response.raise_for_status()


# gpt-oss-style graduated reasoning levels accepted by newer Ollama's `think`.
_THINK_LEVELS = frozenset({"low", "medium", "high"})

# Truthy / falsy string spellings accepted for the boolean form of `think`.
_THINK_TRUE = frozenset({"true", "1", "yes", "on"})
_THINK_FALSE = frozenset({"false", "0", "no", "off"})


def _normalize_think(value: Any) -> Union[bool, str, None]:
    """Coerce a ``think`` setting to ``bool``, a level string, or ``None``.

    ``None`` means "omit the field entirely" (unset ``OLLAMA_THINK`` /
    unset ctor arg). Accepts real booleans, the string spellings
    ``true/false/1/0/yes/no/on/off`` (case-insensitive), and the gpt-oss
    graduated levels ``low/medium/high``. An empty string is treated as unset.

    Raises:
        ValueError: for any other string or unsupported type.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool before int — bool is an int subclass
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "":
            return None
        if v in _THINK_TRUE:
            return True
        if v in _THINK_FALSE:
            return False
        if v in _THINK_LEVELS:
            return v
        raise ValueError(
            "think must be a boolean, 'true'/'false'/'1'/'0', or a level "
            f"'low'/'medium'/'high'; got {value!r}"
        )
    if isinstance(value, int):
        return bool(value)
    raise ValueError(f"think must be bool, str, or None; got {type(value).__name__}")


def _error_mentions_think(response: requests.Response) -> bool:
    """True when *response*'s body text references think/thinking.

    Used to recognize a model that rejected the ``think`` field (older Ollama
    or a non-reasoning model) so we can retry once without it.
    """
    try:
        body = response.text or ""
    except Exception:
        body = ""
    return "think" in body.lower()


def _canonical_model_name(name: str) -> str:
    """Normalize a model name so tag aliases compare equal ('m' == 'm:latest')."""
    canon = name.strip().lower()
    if ":" not in canon:
        canon = f"{canon}:latest"
    return canon


def _compute_rate(count: Optional[int], duration_ns: Optional[int]) -> Optional[float]:
    """Compute tokens/s from token count and nanosecond duration."""
    if count is None or duration_ns is None or duration_ns <= 0:
        return None
    return round(count / (duration_ns / 1e9), 2)


# Tag→digest resolution cache tuning (issue #526). The tag→digest map is
# refreshed from /api/tags at most once per TTL window; a failed fetch is
# negatively cached so an offline host is not hammered on every key build.
_DIGEST_TTL_DEFAULT = 300  # seconds; env OLLAMA_DIGEST_TTL_SECONDS overrides
_DIGEST_NEGATIVE_TTL = 30.0  # seconds to back off after a failed /api/tags fetch


def _extract_metrics(data: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Extract performance metrics from an Ollama generate response."""
    prompt_eval_count = data.get("prompt_eval_count")
    prompt_eval_duration = data.get("prompt_eval_duration")
    eval_count = data.get("eval_count")
    eval_duration = data.get("eval_duration")

    return {
        "model_name": model,
        "total_duration_ns": data.get("total_duration"),
        "load_duration_ns": data.get("load_duration"),
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_duration_ns": prompt_eval_duration,
        "prompt_eval_rate": _compute_rate(prompt_eval_count, prompt_eval_duration),
        "eval_count": eval_count,
        "eval_duration_ns": eval_duration,
        "eval_rate": _compute_rate(eval_count, eval_duration),
    }


class OllamaClient:
    """HTTP client for the Ollama API.

    Handles both text generation and model discovery, providing a single
    integration point for all Ollama interactions.
    """

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        seed: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        num_ctx: Optional[int] = None,
        keep_alive: Optional[str] = None,
        response_format: Optional[str] = None,
        think: Union[bool, str, None] = None,
    ):
        if not base_url:
            base_url = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        if not model:
            # No hardcoded fallback: a stale default silently mislabels runs.
            # Let the non-empty-string validation below raise instead.
            model = os.getenv("DEFAULT_MODEL", "")
        if timeout is None:
            timeout = int(os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_TIMEOUT)))
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("base_url must be a non-empty string")
        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string")
        if temperature < 0:
            raise ValueError(f"temperature must be >= 0, got {temperature}")
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")
        if timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {timeout}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        if response_format is not None and response_format != "json":
            raise ValueError(
                f"response_format must be None or 'json', got {response_format!r}"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.seed = seed
        self.top_p = top_p
        self.top_k = top_k
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.response_format = response_format
        # `think` (issue #131): unset ctor arg falls back to OLLAMA_THINK; both
        # unset leaves it None so the field is omitted from the request payload.
        # The property setter normalizes booleans / levels and validates.
        if think is None:
            think = os.getenv("OLLAMA_THINK")
        self.think = think
        # Latch: once a model rejects the `think` field with a 400, never send
        # it again for this instance (set inside generate's request closure).
        self._think_unsupported = False
        self.last_metrics: Optional[Dict[str, Any]] = None
        # Tag→digest map cache (issue #526): resolved lazily from /api/tags and
        # memoized per instance with a TTL so answer-cache key builds are cheap.
        self._digest_map: Optional[Dict[str, str]] = None
        self._digest_map_fetched_at = 0.0
        self._digest_negative_until = 0.0
        try:
            self._digest_ttl = float(
                os.getenv("OLLAMA_DIGEST_TTL_SECONDS", str(_DIGEST_TTL_DEFAULT))
            )
        except (TypeError, ValueError):
            self._digest_ttl = float(_DIGEST_TTL_DEFAULT)

    @property
    def endpoint(self) -> str:
        """Generate endpoint URL (for backward compatibility)."""
        return f"{self.base_url}/api/generate"

    @endpoint.setter
    def endpoint(self, value: str) -> None:
        """Set endpoint by extracting base URL (for backward compatibility)."""
        # Strip /api/generate suffix if present
        if value.endswith("/api/generate"):
            self.base_url = value[: -len("/api/generate")]
        else:
            self.base_url = value.rstrip("/")

    @property
    def think(self) -> Union[bool, str, None]:
        """Normalized ``think`` setting (bool, level string, or None=omit)."""
        return self._think

    @think.setter
    def think(self, value: Any) -> None:
        # Normalize on assignment so every entry point (ctor, `Set LLM
        # Parameters`, the grader's think=False retry) stores a consistent
        # value — and the answer cache keys on the normalized form.
        self._think = _normalize_think(value)

    def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response text.

        Retries on transient errors (ReadTimeout, ConnectionError) with
        exponential backoff.  Non-transient errors are raised immediately.

        Args:
            prompt: The text prompt to send.

        Returns:
            The generated text response, stripped of whitespace.
        """
        if not isinstance(prompt, str):
            raise TypeError(f"prompt must be a str, got {type(prompt).__name__}")
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        options: Dict[str, Any] = {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
        }
        if self.seed is not None:
            options["seed"] = self.seed
        if self.top_p is not None:
            options["top_p"] = self.top_p
        if self.top_k is not None:
            options["top_k"] = self.top_k
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx

        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        if self.response_format is not None:
            payload["format"] = self.response_format
        # Only send `think` when set AND the model hasn't already rejected it.
        if self.think is not None and not self._think_unsupported:
            payload["think"] = self.think

        self.last_metrics = None

        def _do_request() -> str:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            # A model that doesn't understand `think` answers 400 with an error
            # mentioning think/thinking. Retry once without the field and latch
            # so we stop sending it for the rest of this instance's life (#131).
            if (
                response.status_code == 400
                and "think" in payload
                and _error_mentions_think(response)
            ):
                logger.warn(
                    f"{self.model} rejected the 'think' field (HTTP 400); "
                    f"retrying once without it (think disabled for this client)."
                )
                payload.pop("think", None)
                self._think_unsupported = True
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
            _check_model_not_found(response, self.model, self.base_url)
            data = response.json()
            text = (data.get("response") or "").strip()
            # Reasoning-model fallback (#131): newer Ollama can put all output
            # in `thinking` and leave `response` blank. Surface it as an inline
            # <think> block so the parse_thinking pipeline handles it exactly
            # like inline reasoning — the clean answer stays empty and graders
            # score 0 honestly instead of the parser silently swallowing tokens.
            thinking_only = False
            if not text:
                thinking = (data.get("thinking") or "").strip()
                if thinking:
                    text = f"<think>{thinking}</think>"
                    thinking_only = True
            self.last_metrics = _extract_metrics(data, self.model)
            self.last_metrics["thinking_only"] = thinking_only
            logger.info(f"{self.model} >> {text}")
            return text

        return retry_on_transient(_do_request, max_retries=self.max_retries)

    def unload_model(self, model: Optional[str] = None) -> bool:
        """Unload a model from VRAM by sending keep_alive=0.

        Args:
            model: Model name to unload. Defaults to self.model.

        Returns:
            True if the unload request succeeded.
        """
        target = model or self.model
        payload = {
            "model": target,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=30,
            )
            _check_model_not_found(response, target, self.base_url)
            logger.info(f"Unloaded model: {target}")
            return True
        except OllamaModelNotFoundError:
            raise
        except Exception as exc:
            logger.warn(f"Failed to unload model {target}: {exc}")
            return False

    def list_models(self) -> List[str]:
        """Query available models from the Ollama endpoint.

        Returns:
            List of model name strings (without tags).
        """
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()

        data = response.json()
        return [
            model.get("name", "").split(":")[0]
            for model in data.get("models", [])
            if model.get("name")
        ]

    def list_models_detailed(self) -> List[Dict[str, Any]]:
        """Query available models with full metadata.

        Returns:
            List of dicts with name, size, modified_at, digest keys.
        """
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()

        data = response.json()
        result = []
        for model in data.get("models", []):
            name = model.get("name", "")
            if name:
                result.append(
                    {
                        "name": name,
                        "size": model.get("size", 0),
                        "modified_at": model.get("modified_at", ""),
                        "digest": model.get("digest", "")[:12],
                    }
                )
        return result

    def resolve_model_digest(self) -> Optional[str]:
        """Return the resolved content digest for ``self.model``, or ``None``.

        Answers the question the answer cache (#526) needs: *what weights does
        this tag point at right now?* An Ollama tag such as ``llama3.2:latest``
        can be repointed in place (re-pulled to new weights); keying a cache on
        the tag name alone would then serve answers from the *old* weights under
        the *new* tag. Folding this digest into the key makes a repoint a miss.

        The tag→digest map comes from ``/api/tags`` (the same endpoint
        :meth:`list_models_detailed` reads) and is memoized per instance for
        ``OLLAMA_DIGEST_TTL_SECONDS`` (default 300s). A failed fetch is
        negatively cached for ~30s so an offline host is not hammered on every
        key build.

        Never raises: any error, timeout, or unknown tag yields ``None`` so the
        cache falls back to a digest-less key namespace rather than failing the
        request.
        """
        try:
            mapping = self._digest_map_cached()
            if not mapping:
                return None
            return mapping.get(_canonical_model_name(self.model))
        except Exception:  # pragma: no cover - defensive: must never raise
            return None

    def _digest_map_cached(self) -> Optional[Dict[str, str]]:
        """Return the tag→digest map, refreshing it from /api/tags on TTL expiry.

        Ordering matters: a still-fresh positive cache is returned before the
        negative-cache window is consulted, and a *stale* map is never returned
        when a refresh fails — the digest cannot be re-confirmed, so the caller
        gets ``None`` (a distinct, safe key namespace) rather than a possibly
        outdated digest.
        """
        now = time.monotonic()
        if (
            self._digest_map is not None
            and now - self._digest_map_fetched_at < self._digest_ttl
        ):
            return self._digest_map
        if now < self._digest_negative_until:
            return None
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            mapping: Dict[str, str] = {}
            for model in data.get("models", []):
                name = model.get("name", "")
                digest = model.get("digest", "")
                if name and digest:
                    mapping[_canonical_model_name(name)] = digest
        except Exception:
            # Offline / timeout / malformed: back off so we do not re-probe an
            # unreachable host on every key build, and return None (never a
            # stale map) so the digest stays unconfirmed.
            self._digest_negative_until = now + _DIGEST_NEGATIVE_TTL
            return None
        self._digest_map = mapping
        self._digest_map_fetched_at = now
        self._digest_negative_until = 0.0
        return mapping

    def running_models(self) -> List[Dict[str, Any]]:
        """Query currently running models from the Ollama endpoint.

        Uses the /api/ps endpoint to check which models are loaded
        and actively processing requests.

        Returns:
            List of dicts with model name, size, and expiry info.
        """
        response = requests.get(f"{self.base_url}/api/ps", timeout=10)
        response.raise_for_status()

        data = response.json()
        return data.get("models", [])

    def is_busy(self) -> bool:
        """Check if Ollama is currently processing a request.

        Queries /api/ps and checks if any model has a non-zero
        size_vram, indicating it is loaded and potentially busy.

        Returns:
            True if any model is currently loaded and running.
        """
        try:
            models = self.running_models()
            return len(models) > 0
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check if the Ollama endpoint is accessible.

        Returns:
            True if endpoint responds successfully.
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False

    def wait_until_ready(self, timeout: int = 5400, poll_interval: int = 2) -> bool:
        """Wait until Ollama is available and not busy processing another request.

        Polls the /api/ps endpoint to detect when the LLM is idle.
        This prevents timeout errors caused by sending a request while
        Ollama is still processing a previous one.

        Logs a warning after 1 minute, then every 5 minutes, so long
        waits are visible without flooding the log.

        Args:
            timeout: Maximum seconds to wait (default 5400 / 90 min).
            poll_interval: Seconds between checks.

        Returns:
            True if Ollama became ready within timeout.

        Raises:
            TimeoutError: If Ollama is still busy after timeout expires.
        """
        if timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {timeout}")
        if poll_interval < 1:
            raise ValueError(f"poll_interval must be >= 1, got {poll_interval}")

        start = time.time()
        next_warn_at = 60  # first warning after 1 minute
        warn_interval = 300  # then every 5 minutes
        while time.time() - start < timeout:
            elapsed = int(time.time() - start)

            if not self.is_available():
                if elapsed >= next_warn_at:
                    logger.warn(
                        f"Still waiting for Ollama after {elapsed}s "
                        f"(endpoint unavailable) — "
                        f"timeout in {timeout - elapsed}s "
                        f"| next: {self.model}"
                    )
                    next_warn_at += warn_interval
                logger.info("Ollama endpoint not available yet, waiting...")
                time.sleep(poll_interval)
                continue

            models = []
            try:
                models = self.running_models()
            except Exception:
                # /api/ps may not be available on older Ollama versions
                logger.debug("Could not query /api/ps, assuming idle")
                return True

            if len(models) == 0:
                logger.info("Ollama is idle, no models running")
                return True

            # Residency != busyness: Ollama keeps idle models loaded per
            # keep_alive. If everything resident IS the model we're about to
            # use, waiting for it to unload (only to cold-load it again) is a
            # deadlock, not contention (#464).
            names = [m.get("name", "unknown") for m in models]
            target = _canonical_model_name(self.model)
            if all(_canonical_model_name(n) == target for n in names):
                logger.info(
                    f"Ollama ready: only the target model is resident "
                    f"({', '.join(names)})"
                )
                return True
            if elapsed >= next_warn_at:
                logger.warn(
                    f"Still waiting for Ollama after {elapsed}s — "
                    f"timeout in {timeout - elapsed}s "
                    f"| loaded: [{', '.join(names)}] "
                    f"| next: {self.model}"
                )
                next_warn_at += warn_interval
            logger.info(f"Ollama busy with models: {', '.join(names)} - waiting...")
            time.sleep(poll_interval)

        elapsed = int(time.time() - start)
        raise OllamaTimeoutError(
            elapsed=elapsed,
            models=[m.get("name", "?") for m in models],
        )

    def ensure_ready(
        self, *, timeout: Optional[int] = None, warmup: bool = True
    ) -> None:
        """Verify the endpoint is online and proactively load the model.

        Steps:
          1. Fast online probe (``is_available``) — skip immediately if the
             endpoint is unreachable rather than blocking for the full timeout.
          2. ``wait_until_ready`` — wait out contention from another model
             loaded on a shared host.
          3. When *warmup*, send a tiny ``generate`` request. Ollama lazily
             loads models, so this both forces the target model into VRAM and
             proves it can emit tokens — exactly the cold-load that otherwise
             returned empty mid-suite.

        Raises (all ``RFCSkipError`` subclasses → the test/suite is *skipped*,
        not failed):
            ProviderOfflineError: endpoint unreachable.
            OllamaTimeoutError: stayed busy past *timeout*.
            OllamaModelNotFoundError: model is not pulled (404 on warm-up).
            ModelNotReadyError: warm-up returned an empty response.
        """
        wait_timeout = timeout if timeout is not None else self.timeout
        if not self.is_available():
            raise ProviderOfflineError("Ollama", self.base_url)
        self.wait_until_ready(timeout=wait_timeout)
        if not warmup:
            return
        answer = self.generate("ping")
        if not answer.strip():
            raise ModelNotReadyError(
                self.model, self.base_url, "warm-up returned empty response"
            )
        logger.info(f"Model ready: {self.model} loaded and responding.")


# Backward-compatible alias
LLMClient = OllamaClient
