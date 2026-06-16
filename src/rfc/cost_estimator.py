"""Cost & usage telemetry for external providers (issue #511).

Records estimated spend from per-request token usage so paid external models
are observable and alarmed before surprises. Three pieces:

* :func:`load_pricing` — a static ``model -> ($/Mtok in, $/Mtok out)`` table
  from ``config/local_models.yaml`` (``pricing:``). Unlisted models — every
  current provider is a *free* tier — cost nothing.
* :func:`estimate_cost` — dollars for one request's prompt/completion tokens.
* :class:`MonthlySpend` — a file-backed per-UTC-month dollar accumulator with
  an >N% budget alarm, mirroring the #515 counter's fail-open file discipline.

The Superset cost panel (the dashboard half of #511) rides the Superset
bootstrap cluster (#465-474); this module is the data + alarm core.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: (input $/Mtok, output $/Mtok) for a model.
ModelPrice = tuple[float, float]


def load_pricing(config: dict) -> dict[str, ModelPrice]:
    """Parse the ``pricing:`` table from local_models.yaml.

    Each entry maps a model id to ``{input_per_mtok, output_per_mtok}`` in USD
    per million tokens. Returns ``{}`` when the section is absent.
    """
    raw = config.get("pricing") or {}
    pricing: dict[str, ModelPrice] = {}
    for model, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        pricing[str(model)] = (
            float(entry.get("input_per_mtok", 0.0)),
            float(entry.get("output_per_mtok", 0.0)),
        )
    return pricing


def _default_config_path() -> Path:
    """Absolute path to ``config/local_models.yaml`` (repo-root relative)."""
    return Path(__file__).resolve().parents[2] / "config" / "local_models.yaml"


def load_pricing_table(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, ModelPrice]:
    """Load the pricing table from ``config/local_models.yaml`` (fail-open).

    A thin wrapper over :func:`load_pricing` that reads the YAML file from
    disk. Any read/parse error — or a missing PyYAML — returns ``{}`` so a
    run is never aborted for the sake of cost telemetry (CLAUDE.md skip-and-log
    discipline). Defaults to the in-repo config when *path* is omitted.
    """
    cfg_path = Path(path) if path else _default_config_path()
    try:
        import yaml

        data = yaml.safe_load(cfg_path.read_text())
    except (OSError, ValueError, ImportError) as exc:
        logger.warning("Pricing config unreadable (%s); treating as no pricing.", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return load_pricing(data)


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pricing: dict[str, ModelPrice],
) -> float:
    """Estimated USD for one request. Unlisted (free-tier) models cost 0."""
    price_in, price_out = pricing.get(model, (0.0, 0.0))
    return (max(0, prompt_tokens) / 1e6) * price_in + (
        max(0, completion_tokens) / 1e6
    ) * price_out


def _utc_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


class MonthlySpend:
    """File-backed estimated-spend accumulator, reset each UTC month (#511)."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        month: str | None = None,
        create_parents: bool = True,
    ) -> None:
        self._path = Path(path)
        self._month_override = month
        self._create_parents = create_parents

    def _month(self) -> str:
        return self._month_override or _utc_month()

    def spent(self) -> float:
        """Total estimated USD recorded this month (0.0 on miss / error)."""
        try:
            data = json.loads(self._path.read_text())
        except FileNotFoundError:
            return 0.0
        except (OSError, ValueError, TypeError):
            logger.warning("Monthly spend file unreadable/corrupt; treating as 0.")
            return 0.0
        if not isinstance(data, dict) or data.get("month") != self._month():
            return 0.0
        value = data.get("usd", 0.0)
        return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0

    def record(self, usd: float) -> None:
        """Add *usd* to this month's spend (best-effort, fail-open)."""
        if usd <= 0:
            return
        total = self.spent() + usd
        payload = json.dumps({"month": self._month(), "usd": total})
        try:
            if self._create_parents:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(payload)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Monthly spend unwritable (%s); not recording.", exc)

    def over_threshold(self, cap_usd: float, fraction: float = 0.8) -> bool:
        """True when spend has reached *fraction* of *cap_usd*.

        ``cap_usd <= 0`` means no cap and never alarms.
        """
        return cap_usd > 0 and self.spent() >= cap_usd * fraction


__all__ = [
    "ModelPrice",
    "MonthlySpend",
    "estimate_cost",
    "load_pricing",
    "load_pricing_table",
]
