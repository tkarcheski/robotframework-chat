"""Tests for rfc.commit_graph (git DAG collector) and the commit_graph /
commit_edges data layer in rfc.test_database.

The pure parser (``parse_commit_log``) is tested without a repo; the git
walker and the database round-trip are exercised against a throwaway repo /
in-memory SQLite so the whole suite stays fast and offline.
"""

import subprocess
from pathlib import Path

from rfc.commit_graph import (
    _FIELD_SEP,
    _RECORD_SEP,
    parse_commit_log,
    walk_commit_graph,
)
from rfc.test_database import CommitGraphNode, TestDatabase


def _record(sha: str, parents: str, subject: str) -> str:
    fields = [
        sha,
        parents,
        "Ada",
        "ada@example.com",
        "2024-01-01T00:00:00+00:00",
        "",
        subject,
    ]
    return _FIELD_SEP.join(fields)


class TestParseCommitLog:
    def test_parses_single_commit(self) -> None:
        raw = _record("aaa", "", "initial commit") + _RECORD_SEP
        nodes = parse_commit_log(raw)
        assert len(nodes) == 1
        assert nodes[0].sha == "aaa"
        assert nodes[0].parent_shas == []
        assert nodes[0].subject == "initial commit"
        assert nodes[0].is_merge is False

    def test_parses_parents_and_flags_merge(self) -> None:
        raw = _record("ccc", "aaa bbb", "merge branch") + _RECORD_SEP
        nodes = parse_commit_log(raw)
        assert nodes[0].parent_shas == ["aaa", "bbb"]
        assert nodes[0].is_merge is True

    def test_subject_with_field_like_chars_survives(self) -> None:
        # A subject containing spaces, pipes and unit-like punctuation must
        # not break parsing — that's why we use ASCII 0x1f/0x1e separators.
        raw = _record("aaa", "", "fix: a | b, c (d) e") + _RECORD_SEP
        nodes = parse_commit_log(raw)
        assert nodes[0].subject == "fix: a | b, c (d) e"

    def test_empty_input_yields_no_nodes(self) -> None:
        assert parse_commit_log("") == []


class TestWalkCommitGraph:
    def test_walks_real_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()

        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

        git("init", "-q")
        git("config", "user.email", "ada@example.com")
        git("config", "user.name", "Ada")
        (repo / "a.txt").write_text("one")
        git("add", ".")
        git("commit", "-q", "-m", "first commit")
        (repo / "a.txt").write_text("two")
        git("commit", "-q", "-am", "second commit")

        nodes = walk_commit_graph(cwd=str(repo))
        assert len(nodes) == 2
        subjects = {n.subject for n in nodes}
        assert subjects == {"first commit", "second commit"}
        # Newest first; the second commit lists the first as its parent.
        assert nodes[0].subject == "second commit"
        assert nodes[0].parent_shas == [nodes[1].sha]
        assert nodes[1].parent_shas == []

    def test_non_repo_returns_empty(self, tmp_path: Path) -> None:
        assert walk_commit_graph(cwd=str(tmp_path)) == []


class TestCommitGraphDataLayer:
    def _nodes(self) -> list[CommitGraphNode]:
        return [
            CommitGraphNode(sha="aaa", parent_shas=[], subject="root"),
            CommitGraphNode(sha="bbb", parent_shas=["aaa"], subject="feature"),
            CommitGraphNode(
                sha="ccc",
                parent_shas=["aaa", "bbb"],
                subject="merge",
                is_merge=True,
            ),
        ]

    def test_upsert_and_read_nodes(self, tmp_path: Path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "t.db"))
        written = db.upsert_commit_nodes(self._nodes())
        assert written == 3
        nodes = db.get_commit_graph_nodes()
        by_sha = {n["sha"]: n for n in nodes}
        assert set(by_sha) == {"aaa", "bbb", "ccc"}
        assert by_sha["ccc"]["is_merge"] in (1, True)
        assert by_sha["aaa"]["is_merge"] in (0, False)

    def test_edges_are_derived_from_parents(self, tmp_path: Path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "t.db"))
        db.upsert_commit_nodes(self._nodes())
        edges = {(e["child_sha"], e["parent_sha"]) for e in db.get_commit_edges()}
        assert edges == {("bbb", "aaa"), ("ccc", "aaa"), ("ccc", "bbb")}

    def test_upsert_is_idempotent(self, tmp_path: Path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "t.db"))
        db.upsert_commit_nodes(self._nodes())
        db.upsert_commit_nodes(self._nodes())
        assert db.get_table_row_count("commit_graph") == 3
        assert db.get_table_row_count("commit_edges") == 3

    def test_upsert_updates_changed_metadata(self, tmp_path: Path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "t.db"))
        db.upsert_commit_nodes([CommitGraphNode(sha="aaa", subject="old")])
        db.upsert_commit_nodes([CommitGraphNode(sha="aaa", subject="new")])
        nodes = db.get_commit_graph_nodes()
        assert len(nodes) == 1
        assert nodes[0]["subject"] == "new"

    def test_empty_upsert_is_noop(self, tmp_path: Path) -> None:
        db = TestDatabase(db_path=str(tmp_path / "t.db"))
        assert db.upsert_commit_nodes([]) == 0
        assert db.get_commit_graph_nodes() == []
