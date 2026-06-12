"""Tests for ``rfc dialog replay`` — prompt mode (#356).

Given a recording with N user turns, the replay engine must open a
fresh agentic_harnesses row pointing back at the source recording,
re-prompt a target model for every user turn, capture the new
responses as a *new* recording, grade each response against the
original via the DialogGrader wrapper, and land per-turn metrics in
agentic_metrics. Hermetic: fake providers only — no live LLM.
"""

import json

import pytest

from rfc.dialog_grader import DialogGrader
from rfc.dialog_replay import (
    PARTIAL_THRESHOLD,
    SUCCESS_THRESHOLD,
    derive_outcome,
    replay_prompt_mode,
)
from rfc.harness_cli import main
from rfc.harness_db import HarnessDatabase
from rfc.harness_models import DialogRecording, DialogTurn


class FakeProvider:
    """Minimal LLMProvider double returning fixed strings with metrics."""

    def __init__(self, responses=None, model="fake-target"):
        self.model = model
        self.temperature = 0.0
        self.max_tokens = 256
        self.seed = None
        self.top_p = None
        self.top_k = None
        self.num_ctx = None
        self.keep_alive = None
        self.response_format = None
        self.last_metrics = None
        self.prompts: list[str] = []
        self._responses = list(responses or [])

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        reply = (
            self._responses.pop(0)
            if self._responses
            else f"fresh answer #{len(self.prompts)}"
        )
        self.last_metrics = {
            "model_name": self.model,
            "prompt_eval_count": 11,
            "eval_count": 7,
        }
        return reply


class FakeGraderProvider(FakeProvider):
    """Provider double whose generate() returns grader JSON verdicts."""

    def __init__(self, scores=None):
        super().__init__(model="fake-grader")
        self._scores = list(scores or [])

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        score = self._scores.pop(0) if self._scores else 0.9
        return json.dumps({"score": score, "reason": "fixed verdict"})


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'h.db'}"


@pytest.fixture()
def db(db_url):
    return HarnessDatabase(database_url=db_url)


def seed_recording(db, *, recording_id="rec-source", user_turns=2):
    """Insert a source recording with alternating user/assistant turns."""
    db.save_recording(
        DialogRecording(
            id=recording_id,
            source_type="imported",
            started_at="2026-06-12T00:00:00Z",
            tool_name="claude-code",
            model_id="original-model",
        )
    )
    turns = []
    number = 1
    for i in range(user_turns):
        turns.append(
            DialogTurn(
                recording_id=recording_id,
                turn_number=number,
                role="user",
                timestamp=f"2026-06-12T00:00:{number:02d}Z",
                content=f"question {i + 1}",
            )
        )
        number += 1
        turns.append(
            DialogTurn(
                recording_id=recording_id,
                turn_number=number,
                role="assistant",
                timestamp=f"2026-06-12T00:00:{number:02d}Z",
                content=f"original answer {i + 1}",
            )
        )
        number += 1
    db.save_turns(turns)
    return recording_id


class TestDeriveOutcome:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (1.0, "success"),
            (SUCCESS_THRESHOLD, "success"),
            (0.79, "partial"),
            (PARTIAL_THRESHOLD, "partial"),
            (0.49, "failed"),
            (0.0, "failed"),
        ],
    )
    def test_thresholds(self, score, expected):
        assert derive_outcome(score) == expected


class TestReplayPromptMode:
    def test_opens_harness_row_with_replay_pointer(self, db):
        rec_id = seed_recording(db)
        result = replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            target_tool="codex",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider()),
        )
        harness = db.get_harness(result.session_id)
        assert harness is not None
        assert harness.replay_of_recording_id == rec_id
        assert harness.model_id == "target-model"
        assert harness.tool_name == "codex"
        assert harness.ended_at != ""
        assert harness.outcome == "success"

    def test_walks_user_turns_and_prompts_target(self, db):
        rec_id = seed_recording(db, user_turns=3)
        provider = FakeProvider()
        replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=provider,
            grader=DialogGrader(FakeGraderProvider()),
        )
        assert provider.prompts == ["question 1", "question 2", "question 3"]

    def test_per_turn_metrics_written(self, db):
        rec_id = seed_recording(db, user_turns=2)
        result = replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider(scores=[0.9, 0.7])),
        )
        scores = db.get_metrics(result.session_id, metric_key="grader_score")
        assert [m.metric_value for m in scores] == [0.9, 0.7]
        tokens_in = db.get_metrics(result.session_id, metric_key="tokens_in")
        tokens_out = db.get_metrics(result.session_id, metric_key="tokens_out")
        latency = db.get_metrics(result.session_id, metric_key="latency_ms")
        assert [m.metric_value for m in tokens_in] == [11.0, 11.0]
        assert [m.metric_value for m in tokens_out] == [7.0, 7.0]
        assert len(latency) == 2
        assert all(m.metric_value >= 0 for m in latency)

    def test_new_recording_is_itself_replayable(self, db):
        rec_id = seed_recording(db, user_turns=2)
        result = replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=FakeProvider(responses=["new answer 1", "new answer 2"]),
            grader=DialogGrader(FakeGraderProvider()),
        )
        new_rec = db.get_recording(result.new_recording_id)
        assert new_rec is not None
        assert new_rec.source_type == "replay"
        assert new_rec.session_id == result.session_id
        assert new_rec.model_id == "target-model"
        assert new_rec.ended_at != ""
        metadata = json.loads(new_rec.metadata_json)
        assert metadata["replay_of_recording_id"] == rec_id
        assert metadata["mode"] == "prompt"

        turns = db.get_turns(result.new_recording_id)
        assert [t.role for t in turns] == ["user", "assistant"] * 2
        assert turns[0].content == "question 1"
        assert turns[1].content == "new answer 1"
        assert turns[1].prompt_tokens == 11
        assert turns[1].completion_tokens == 7
        assert turns[1].latency_ms >= 0

        # The replay output can be replayed again: same engine, new source.
        second = replay_prompt_mode(
            db,
            result.new_recording_id,
            target_model="target-model",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider()),
        )
        assert second.source_recording_id == result.new_recording_id

    @pytest.mark.parametrize(
        ("scores", "outcome"),
        [
            ([0.9, 0.9], "success"),
            ([0.9, 0.3], "partial"),
            ([0.2, 0.3], "failed"),
        ],
    )
    def test_outcome_from_aggregate_score(self, db, scores, outcome):
        rec_id = seed_recording(db, user_turns=2)
        result = replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider(scores=scores)),
        )
        assert result.outcome == outcome
        harness = db.get_harness(result.session_id)
        assert harness is not None
        assert harness.outcome == outcome

    def test_grader_sees_original_answer_as_expected(self, db):
        rec_id = seed_recording(db, user_turns=1)
        grader_provider = FakeGraderProvider()
        replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=FakeProvider(responses=["brand new answer"]),
            grader=DialogGrader(grader_provider),
        )
        grading_prompt = grader_provider.prompts[0]
        assert "question 1" in grading_prompt
        assert "original answer 1" in grading_prompt
        assert "brand new answer" in grading_prompt

    def test_missing_recording_raises_lookup_error(self, db):
        with pytest.raises(LookupError, match="no-such-recording"):
            replay_prompt_mode(
                db,
                "no-such-recording",
                target_model="target-model",
                provider=FakeProvider(),
                grader=DialogGrader(FakeGraderProvider()),
            )

    def test_recording_without_user_turns_raises_value_error(self, db):
        db.save_recording(
            DialogRecording(
                id="rec-empty",
                source_type="imported",
                started_at="2026-06-12T00:00:00Z",
            )
        )
        with pytest.raises(ValueError, match="no user turns"):
            replay_prompt_mode(
                db,
                "rec-empty",
                target_model="target-model",
                provider=FakeProvider(),
                grader=DialogGrader(FakeGraderProvider()),
            )

    def test_target_tool_defaults_to_source_tool(self, db):
        rec_id = seed_recording(db)
        result = replay_prompt_mode(
            db,
            rec_id,
            target_model="target-model",
            provider=FakeProvider(),
            grader=DialogGrader(FakeGraderProvider()),
        )
        harness = db.get_harness(result.session_id)
        assert harness is not None
        assert harness.tool_name == "claude-code"


class TestDialogGrader:
    def test_wraps_grade_answer_machinery_without_robot(self):
        grader = DialogGrader(FakeGraderProvider(scores=[0.42]))
        result = grader.grade("q", "expected", "actual")
        assert result.score == 0.42
        assert result.reason == "fixed verdict"

    def test_rejects_none_client(self):
        with pytest.raises(TypeError):
            DialogGrader(None)  # type: ignore[arg-type]


class TestReplayCli:
    def _patch_providers(self, monkeypatch):
        created: list[dict] = []

        def fake_create_provider(provider: str = "", **kwargs):
            created.append({"provider": provider, **kwargs})
            if len(created) == 1:
                return FakeProvider(model=kwargs.get("model", ""))
            return FakeGraderProvider()

        monkeypatch.setattr("rfc.dialog_replay.create_provider", fake_create_provider)
        return created

    def test_cli_replays_and_prints_json(self, db, db_url, monkeypatch, capsys):
        created = self._patch_providers(monkeypatch)
        rec_id = seed_recording(db, user_turns=2)
        rc = main(
            [
                "dialog",
                "replay",
                rec_id,
                "--target-model",
                "claude-haiku-4-5",
                "--mode",
                "prompt",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["replayed"] is True
        assert payload["source_recording_id"] == rec_id
        assert payload["mode"] == "prompt"
        assert payload["turns"] == 2
        assert payload["outcome"] == "success"
        assert created[0]["model"] == "claude-haiku-4-5"
        harness = db.get_harness(payload["session_id"])
        assert harness is not None
        assert harness.replay_of_recording_id == rec_id

    def test_cli_mode_defaults_to_prompt(self, db, db_url, monkeypatch, capsys):
        self._patch_providers(monkeypatch)
        rec_id = seed_recording(db)
        rc = main(
            [
                "dialog",
                "replay",
                rec_id,
                "--target-model",
                "claude-haiku-4-5",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["mode"] == "prompt"

    def test_cli_grader_model_flag_creates_separate_grader(
        self, db, db_url, monkeypatch, capsys
    ):
        created = self._patch_providers(monkeypatch)
        rec_id = seed_recording(db)
        rc = main(
            [
                "dialog",
                "replay",
                rec_id,
                "--target-model",
                "claude-haiku-4-5",
                "--grader-model",
                "judge-model",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 0
        assert created[1]["model"] == "judge-model"

    def test_cli_missing_recording_is_clean_error(self, db_url, monkeypatch, capsys):
        self._patch_providers(monkeypatch)
        rc = main(
            [
                "dialog",
                "replay",
                "nope",
                "--target-model",
                "m",
                "--database-url",
                db_url,
            ]
        )
        assert rc == 1
        assert "nope" in capsys.readouterr().err

    def test_cli_requires_database(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DIALOG_DATABASE_URL", raising=False)
        rc = main(["dialog", "replay", "rec", "--target-model", "m"])
        assert rc == 2


class TestOriginalResponseSelection:
    """Tool-only assistant turns must not become the grading reference (#485)."""

    def _turn(self, number, role, content):
        return DialogTurn(
            recording_id="rec-ref",
            turn_number=number,
            role=role,
            timestamp=f"2026-06-12T00:01:{number:02d}Z",
            content=content,
        )

    def test_skips_tool_only_assistant_turn(self):
        from rfc.dialog_replay import _original_response_for

        turns = [
            self._turn(1, "user", "do the thing"),
            self._turn(2, "assistant", ""),  # tool_use-only turn (#485)
            self._turn(3, "assistant", "the real textual answer"),
            self._turn(4, "user", "next question"),
        ]
        assert _original_response_for(turns, 0) == "the real textual answer"

    def test_aggregates_multi_part_assistant_response(self):
        from rfc.dialog_replay import _original_response_for

        turns = [
            self._turn(1, "user", "do the thing"),
            self._turn(2, "assistant", "first I will look"),
            self._turn(3, "assistant", ""),  # tool call in between
            self._turn(4, "assistant", "here is the result"),
            self._turn(5, "user", "next"),
        ]
        assert _original_response_for(turns, 0) == (
            "first I will look\n\nhere is the result"
        )

    def test_all_tool_only_yields_empty(self):
        from rfc.dialog_replay import _original_response_for

        turns = [
            self._turn(1, "user", "do the thing"),
            self._turn(2, "assistant", ""),
            self._turn(3, "user", "next"),
        ]
        assert _original_response_for(turns, 0) == ""
