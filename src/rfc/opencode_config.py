"""opencode.json comparability gate: the durable home of the #191/#273 check.

The load-bearing honesty check for RFC-007 Tier A — the *selected* model must
resolve to a **declared local** provider — used to live procedurally inside
``rfc.harness_comparison`` and only ran when a runner remembered to call it. It
lives here now (#278), in the layer that materializes the opencode config for a
run, so **any** consumer of that config gets the gate for free:

  * :class:`rfc.harness_adapters.OpenCodeAdapter` gates through
    :meth:`~rfc.harness_adapters.OpenCodeAdapter.verify_local_model`, and
  * :class:`rfc.harness_comparison.ComparisonRow` accepts a Tier-A model only as
    a :class:`VerifiedLocalModel` token — the exact type, minted with a key that
    lives only in the gate's closure (#314) — so an unverified (remote /
    undeclared) model cannot be recorded as a Tier-A result by any honest or
    type-checked path a future runner takes. (Not an absolute: of the four
    deliberate in-process forge paths test-design demonstrated on #313, two
    remain — ``object.__new__`` fabrication and closure-cell introspection of
    the mint key — both conspicuous, review-defended acts the #314 design
    ruling deliberately left to review + dual sign-off.)

This module is a leaf: it imports only the stdlib, so both the adapter layer and
the comparison runner can depend on it without a cycle.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

# Repo opencode.json (the Tier-A comparability substrate, #191/#226). Lives at
# the core/ root, two parents up from this package (src/rfc/ -> src/ -> core/).
_DEFAULT_OPENCODE_CONFIG = (
    Path(__file__).resolve().parent.parent.parent / "opencode.json"
)

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


class ComparabilityError(RuntimeError):
    """The Tier-A fixed-model contract cannot be honoured (RFC-007 section 5).

    Raised when ``opencode.json`` is not self-contained local-Ollama, so a
    "same model for every harness" claim would be a lie. #218 hard-blocks on
    #191 rather than assuming it (RFC-007 section 11).
    """


def _is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in _LOCAL_HOSTS


@dataclass(frozen=True)
class VerifiedLocalModel:
    """A model ref PROVEN to resolve to a declared-local opencode provider (#278).

    The Tier-A capability token. Its intended producers are
    :func:`assert_model_resolves_local` / :func:`gate_config`, which mint with a
    key bound inside the gate's closure (#314) — not an importable module
    attribute — so direct construction fails closed and the #313-era one-line
    key grab (``rfc.opencode_config._GATE_MINT_KEY``) no longer exists. A Tier-A
    :class:`rfc.harness_comparison.ComparisonRow` requires one — the exact type,
    not a duck-typed or subclassed stand-in (#314) — so accidental omission of
    the gate fails closed and type-checked code cannot skip it: the layering
    defense that survives the addition of a second comparison runner.
    Of the four deliberate in-process forge paths test-design demonstrated on
    #313, #314 closes two (the importable mint key; the duck-typed/subclassed
    row token) and two remain: ``object.__new__`` + ``object.__setattr__``
    fabrication, and extracting the mint key by introspecting the gate's
    closure cells. Both are inherent to Python capability tokens, glaring in a
    diff, and per the #314 design ruling defended by review + dual sign-off
    rather than chased to an impossible absolute. Equality/hash key on
    ``model_id`` alone; the mint key is an :class:`~dataclasses.InitVar`, never
    a stored field.
    """

    model_id: str
    _mint_key: dataclasses.InitVar[object] = None

    def __post_init__(self, _mint_key: object) -> None:
        if not _is_gate_mint_key(_mint_key):
            raise ComparabilityError(
                "VerifiedLocalModel may only be minted by the comparability gate "
                "(assert_model_resolves_local / gate_config); a hand-built "
                "verification token is refused so an unverified model cannot forge "
                "Tier-A provenance (#278)."
            )
        if not (self.model_id or "").strip():
            raise ComparabilityError(
                "VerifiedLocalModel requires a non-empty model_id — the gate must "
                "never mint a token for an empty model reference."
            )


def load_opencode_config(path: Path) -> dict:
    """Read + parse opencode.json, or raise :class:`ComparabilityError`."""
    if not path.is_file():
        raise ComparabilityError(
            f"opencode.json not found at {path} -- the Tier-A comparability gate "
            "(#191) cannot be verified; refusing to claim a fixed-model run."
        )
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ComparabilityError(f"opencode.json is not valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise ComparabilityError(
            f"opencode.json ({path}) is not a JSON object -- cannot verify the "
            "Tier-A local-model contract."
        )
    return config


class _LocalModelGate(Protocol):
    """Callable shape of :func:`assert_model_resolves_local` (closure-built, #314)."""

    def __call__(
        self, model_ref: str, config: dict, *, source: str
    ) -> VerifiedLocalModel: ...


def _bind_gate() -> tuple[Callable[[object], bool], _LocalModelGate]:
    """Bind the Tier-A mint key in a closure (#314).

    The key used to be an importable module global (``_GATE_MINT_KEY``), so any
    in-package caller could mint a genuine token for a remote id with a one-line
    import — mypy-clean. It now lives only in this closure. The two callables
    that can reach it are the ``is_mint_key`` predicate (which compares, never
    reveals) and the gate function itself, which runs the full local-resolution
    checks BEFORE it mints — there is deliberately no unchecked mint helper at
    module scope. This cannot be made airtight: CPython exposes closure cells to
    deliberate introspection, and ``object.__new__`` fabricates a token outright
    — the two forge paths the #314 design ruling left to review + dual sign-off.
    """
    mint_key = object()

    def is_mint_key(candidate: object) -> bool:
        return candidate is mint_key

    def assert_model_resolves_local(
        model_ref: str, config: dict, *, source: str
    ) -> VerifiedLocalModel:
        """Require ``model_ref`` (``provider/model``) to resolve to a DECLARED LOCAL provider.

        The load-bearing honesty check (#273): a Tier-A "fixed local model" is only
        honest if the *selected* model is actually served locally. So the model's
        ``provider/`` prefix must name a provider DECLARED in ``config`` whose
        ``options.baseURL`` is present AND points at localhost. Nothing is
        whitelisted: an undeclared provider (built-in ``openai``/``anthropic`` egress
        to their real endpoints by default), an absent ``baseURL`` (same egress), a
        remote ``baseURL``, or a model the local provider does not list all FAIL
        closed. Returns a gate-minted :class:`VerifiedLocalModel` on success.
        """
        ref = (model_ref or "").strip()
        if not ref:
            raise ComparabilityError(
                f"{source}: empty model reference -- cannot verify a local model."
            )
        if "/" not in ref:
            raise ComparabilityError(
                f"{source}: model {ref!r} is not in 'provider/model' form -- cannot "
                "resolve it to a declared local provider, so it is not verifiably local."
            )
        provider_prefix, model_name = ref.split("/", 1)
        providers = config.get("provider") or {}
        if provider_prefix not in providers:
            raise ComparabilityError(
                f"{source}: model provider {provider_prefix!r} is not declared in "
                "opencode.json -- built-in providers (openai/anthropic/...) egress to "
                "their real endpoints by default, so this is not a local model "
                "(RFC-007 section 5, the single most common way this benchmark lies)."
            )
        provider = providers.get(provider_prefix) or {}
        base_url = ((provider.get("options") or {}).get("baseURL") or "").strip()
        if not base_url:
            raise ComparabilityError(
                f"{source}: provider {provider_prefix!r} declares no baseURL -- an "
                "absent baseURL means built-in remote egress, not a local model "
                "(RFC-007 section 5)."
            )
        if not _is_local_url(base_url):
            raise ComparabilityError(
                f"{source}: provider {provider_prefix!r} baseURL {base_url!r} is not "
                "local -- external egress breaks the fixed-local-model comparability "
                "contract (#191)."
            )
        models = provider.get("models") or {}
        if models and model_name not in models:
            raise ComparabilityError(
                f"{source}: model {model_name!r} is not among the models served by "
                f"local provider {provider_prefix!r} ({sorted(models)}) -- refusing "
                "to record a model the local provider does not declare."
            )
        return VerifiedLocalModel(ref, mint_key)

    return is_mint_key, assert_model_resolves_local


_is_gate_mint_key, assert_model_resolves_local = _bind_gate()


def gate_config(config: dict, *, source: str) -> VerifiedLocalModel:
    """Run the #191/#273 comparability gate over an already-loaded config.

    Returns the gate-minted :class:`VerifiedLocalModel` for the pinned default;
    raises :class:`ComparabilityError` otherwise.
    """
    model = config.get("model")
    if not model:
        raise ComparabilityError(
            f"{source} declares no top-level 'model' -- without a pinned default "
            "the harnesses would not share one local model."
        )
    # Defense in depth: no DECLARED provider may egress off-localhost, even if the
    # selected model does not use it (a remote provider in the file is a smell).
    for provider_name, provider in (config.get("provider") or {}).items():
        base_url = ((provider or {}).get("options") or {}).get("baseURL") or ""
        if base_url and not _is_local_url(base_url):
            raise ComparabilityError(
                f"opencode.json provider {provider_name!r} baseURL {base_url!r} is "
                "not local -- external egress breaks the fixed-local-model "
                "comparability contract (#191)."
            )
    # The load-bearing check (#273): the SELECTED model must resolve to a local
    # provider -- not merely "no declared baseURL is remote".
    return assert_model_resolves_local(str(model), config, source=source)


def assert_opencode_comparable(config_path: Path | None = None) -> str:
    """Hard-block on #191/#273: opencode.json must pin one LOCAL model, no egress.

    Returns the pinned default model id (for the row ``model_id``) on success;
    raises :class:`ComparabilityError` otherwise. Verified: (1) a top-level
    ``model`` default exists, (2) no declared provider ``baseURL`` egresses
    off-localhost, and (3) -- the check #273 added -- the *selected* model
    resolves to a DECLARED provider whose ``baseURL`` is present and local, so
    the Tier-A "same local model for every harness" claim is honest instead of
    assumed. An absent baseURL or an undeclared/built-in provider FAILS closed.

    Returns the model id string (not the token) for backwards compatibility;
    callers wanting the :class:`VerifiedLocalModel` capability call
    :func:`gate_config` / :func:`assert_model_resolves_local` directly.
    """
    path = config_path or _DEFAULT_OPENCODE_CONFIG
    return gate_config(
        load_opencode_config(path), source=f"opencode.json ({path})"
    ).model_id
