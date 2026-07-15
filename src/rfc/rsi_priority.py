"""RSI-model update detection for prioritized re-testing.

Goal context: "keep testing running 24/7, prioritize the RSI model when it
updates."

The ``run-local-models`` scheduler tests every model discovered on each host
equally (model-major queue plus loaded-in-VRAM affinity) and never inspects
Ollama's per-model ``digest`` — so an updated RSI model is not re-tested until
the general rotation happens to reach it again. This module supplies the pure,
side-effect-free logic that the fleet's RSI priority watcher (a monorepo-side
ops script) uses to notice, from ``GET /api/tags`` responses, when the RSI
model's digest has changed and a prioritized test run is warranted.

Keeping the decision logic here (rather than inline in the watcher) makes it
unit-testable without a live Ollama endpoint.
"""

from __future__ import annotations

from typing import Any

#: Default Ollama tag of the recursive-self-improvement model under watch.
DEFAULT_RSI_MODEL = "rsi-qwen:round"


def extract_digest(tags_payload: dict[str, Any], model_tag: str) -> str | None:
    """Return the Ollama manifest digest for ``model_tag``.

    Args:
        tags_payload: Parsed JSON from Ollama ``GET /api/tags`` (a dict with a
            ``"models"`` list).
        model_tag: Exact model name to look up (e.g. ``rsi-qwen:round``).

    Returns:
        The digest string for the model, or ``None`` when the model is absent
        from the payload or carries an empty digest.
    """
    for model in tags_payload.get("models", []):
        if model.get("name") == model_tag:
            digest = model.get("digest") or ""
            return digest or None
    return None


def needs_retest(previous_digest: str | None, current_digest: str | None) -> bool:
    """Decide whether the RSI model should be (re)tested now for one host.

    Args:
        previous_digest: The digest last tested on this host, or ``None`` if the
            model has not been seen on this host before.
        current_digest: The digest observed this cycle, or ``None`` if the model
            is not present on the host right now.

    Returns:
        ``True`` when a prioritized test run is warranted:

        * ``current_digest is None`` (model absent now) -> ``False``; nothing to run.
        * ``previous_digest is None`` (first sighting) -> ``True``; run a baseline.
        * digest changed -> ``True``.
        * digest unchanged -> ``False``.
    """
    if current_digest is None:
        return False
    if previous_digest is None:
        return True
    return previous_digest != current_digest
