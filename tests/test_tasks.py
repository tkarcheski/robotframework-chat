"""Tests for tasks.py — stash depth checks in update()."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import tasks


class TestStashDepth:
    """Verify _stash_depth() runs from the repo root."""

    @patch("tasks.subprocess.run")
    def test_stash_depth_uses_repo_root(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="stash@{0}: WIP\n")
        depth = tasks._stash_depth()
        mock_run.assert_called_once_with(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(tasks.ROOT),
        )
        assert depth == 1

    @patch("tasks.subprocess.run")
    def test_stash_depth_empty(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        assert tasks._stash_depth() == 0


class TestUpdate:
    """Verify update() stash-pop logic."""

    @patch("tasks._uv")
    @patch("tasks._run")
    @patch("tasks._stash_depth")
    def test_pops_stash_when_stashed(
        self,
        mock_depth: MagicMock,
        mock_run: MagicMock,
        mock_uv: MagicMock,
    ) -> None:
        # Depth increases after stash → something was stashed
        mock_depth.side_effect = [0, 1]
        mock_run.return_value = 0

        tasks.update()

        mock_run.assert_any_call(["git", "stash", "pop"], check=False)

    @patch("tasks._uv")
    @patch("tasks._run")
    @patch("tasks._stash_depth")
    def test_skips_pop_when_nothing_stashed(
        self,
        mock_depth: MagicMock,
        mock_run: MagicMock,
        mock_uv: MagicMock,
    ) -> None:
        # Depth unchanged → nothing was stashed
        mock_depth.side_effect = [2, 2]
        mock_run.return_value = 0

        tasks.update()

        pop_calls = [
            c
            for c in mock_run.call_args_list
            if c == call(["git", "stash", "pop"], check=False)
        ]
        assert pop_calls == []

    @patch("tasks._uv")
    @patch("tasks._run")
    @patch("tasks._stash_depth")
    def test_pops_and_exits_on_pull_failure(
        self,
        mock_depth: MagicMock,
        mock_run: MagicMock,
        mock_uv: MagicMock,
    ) -> None:
        mock_depth.side_effect = [0, 1]

        def run_side_effect(args: list[str], *, check: bool = True) -> int:
            if args == ["git", "pull"]:
                return 1
            return 0

        mock_run.side_effect = run_side_effect

        with pytest.raises(SystemExit) as exc_info:
            tasks.update()

        assert exc_info.value.code == 1
        mock_run.assert_any_call(["git", "stash", "pop"], check=False)

    @patch("tasks._uv")
    @patch("tasks._run")
    @patch("tasks._stash_depth")
    def test_skips_pop_on_pull_failure_when_nothing_stashed(
        self,
        mock_depth: MagicMock,
        mock_run: MagicMock,
        mock_uv: MagicMock,
    ) -> None:
        mock_depth.side_effect = [3, 3]

        def run_side_effect(args: list[str], *, check: bool = True) -> int:
            if args == ["git", "pull"]:
                return 1
            return 0

        mock_run.side_effect = run_side_effect

        with pytest.raises(SystemExit):
            tasks.update()

        pop_calls = [
            c
            for c in mock_run.call_args_list
            if c == call(["git", "stash", "pop"], check=False)
        ]
        assert pop_calls == []
