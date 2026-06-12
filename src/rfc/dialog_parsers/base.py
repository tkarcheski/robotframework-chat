"""Shared types for dialog transcript parsers (#355).

A parser turns one external transcript file into a
:class:`ParsedTranscript`: recording-level metadata fingerprinted from
the transcript header plus the ordered :class:`rfc.harness_models.DialogTurn`
list. ``recording_id`` is left empty on every turn — the importer
assigns it when it creates the ``dialog_recordings`` row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rfc.harness_models import DialogTurn


class DialogParseError(Exception):
    """A transcript file is missing, malformed, or contains no turns."""


@dataclass
class ParsedTranscript:
    """Parser output: recording metadata + ordered turns."""

    tool_version: str = ""
    model_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    metadata_json: str = ""
    turns: list[DialogTurn] = field(default_factory=list)
