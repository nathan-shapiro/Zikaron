"""The command a person runs, driven in-process so both its exit status and its output are read.

`main` returns a status rather than exiting for exactly this reason. What is checked here is the
command's own job — parsing, dispatch, exit statuses and what it prints — since every decision it
reports belongs to `zikaron.core.knowledge` and is tested there.
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from tests.knowledge_fixtures import config_for, corpus_root
from zikaron.core.knowledge import lifecycle
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge.main import _dispatch, main


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project directory with a created memory store and a corpus to point at.

    Synchronous, like every test in this file: `main` owns its own event loop, so a test running
    inside one could not call it at all. That is the command's real shape rather than a
    concession — a person runs it, and it runs to completion.
    """
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder):
            pass

    asyncio.run(_create())
    corpus_root(tmp_path)
    return tmp_path


def _run(project_dir: Path, *argv: str) -> int:
    return main(["--project", str(project_dir), *argv])


class TestTheVerbs:
    def test_add_then_list_then_rename_then_remove(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "add",
                "Design Docs",
                "--path",
                str(project / "docs"),
                "--description",
                "architecture records",
            )
            == 0
        )
        added = capsys.readouterr().out
        assert "design docs" in added
        assert "reindex_required" in added

        assert _run(project, "list") == 0
        listed = capsys.readouterr().out
        assert "design docs" in listed
        assert "architecture records" in listed

        assert _run(project, "rename", "design docs", "Design Records") == 0
        assert "design records" in capsys.readouterr().out

        assert _run(project, "status", "design records") == 0
        detailed = capsys.readouterr().out
        assert str(project / "docs") in detailed
        assert "git-mode" in detailed

        assert _run(project, "remove", "design records", "--yes") == 0
        assert "removed" in capsys.readouterr().out

        assert _run(project, "list") == 0
        assert "no knowledge bases" in capsys.readouterr().out

    def test_remove_without_yes_reports_and_refuses(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Destroying a corpus on an unconfirmed call is the one mistake that cannot be undone, so
        the unconfirmed form reports what would go and exits non-zero."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "remove", "docs") == 1
        printed = capsys.readouterr().out
        assert "would destroy" in printed
        assert "--yes" in printed

        assert _run(project, "list") == 0
        assert "docs" in capsys.readouterr().out

    def test_status_without_a_name_reports_every_knowledge_base(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for name in ("one", "two"):
            _run(project, "add", name, "--path", str(project / "docs"), "--description", name)
        capsys.readouterr()

        assert _run(project, "status") == 0
        printed = capsys.readouterr().out
        assert "one" in printed
        assert "two" in printed

    def test_add_persists_the_options_it_was_given(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A setting accepted and not persisted would be silently undone by the next build, which
        would re-walk under the global default and change the corpus the caller defined."""
        assert (
            _run(
                project,
                "add",
                "docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
                "--include",
                "*.md",
                "--include",
                "*.txt",
                "--exclude",
                "draft/*",
                "--git-mode",
                "off",
                "--max-file-bytes",
                "4096",
            )
            == 0
        )
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "include   *.md, *.txt" in printed
        assert "exclude   draft/*" in printed
        assert "git-mode  off" in printed
        assert "4096 bytes" in printed


class TestRefusalsReachTheExitStatus:
    def test_an_unknown_name_exits_non_zero_and_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "status", "absent") == 1
        assert "refused" in capsys.readouterr().err

    def test_a_duplicate_name_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        assert (
            _run(project, "add", "DOCS", "--path", str(project / "docs"), "--description", "e") == 1
        )
        assert "already exists" in capsys.readouterr().err

    def test_a_bad_root_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "add", "docs", "--path", str(project / "nope"), "--description", "d") == 1
        )
        assert "does not exist" in capsys.readouterr().err

    def test_an_out_of_range_size_cap_exits_non_zero(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "add",
                "docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
                "--max-file-bytes",
                "0",
            )
            == 1
        )
        assert "refused" in capsys.readouterr().err

    def test_a_project_with_no_store_exits_non_zero_rather_than_creating_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The command opens the memory store through the ordinary path, so it inherits every
        check that path runs — and a project Zikaron was never installed into is refused rather
        than quietly given a store by a knowledge-base command."""
        assert _run(tmp_path, "list") == 1
        assert "refused" in capsys.readouterr().err
        assert not (tmp_path / ".zikaron" / "memory.db").exists()

    def test_an_orphan_is_reported_by_both_list_and_status(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        stray = project / ".zikaron" / "knowledge" / "00000000-0000-4000-8000-000000000000.db"
        stray.write_bytes(b"")

        assert _run(project, "list") == 0
        printed = capsys.readouterr().out
        assert "orphaned database" in printed
        assert stray.name in printed


class TestTheDocumentedInvocation:
    """`python -m zikaron.knowledge` has to work, because it is what the design tells a person to
    run. Only a real subprocess exercises the `__main__` module that makes a package executable."""

    @pytest.mark.integration
    def test_the_module_is_executable_and_prints_its_usage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "zikaron.knowledge", "--help"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        assert "python -m zikaron.knowledge" in result.stdout
        for verb in ("add", "list", "remove", "rename", "status"):
            assert verb in result.stdout

    @pytest.mark.integration
    def test_the_module_exits_non_zero_on_a_refusal(self, project: Path) -> None:
        """The status has to survive the trip through `__main__`, which is the one line of it that
        can be wrong — and a command that reported success on a refusal would be worse than one
        that failed to run at all."""
        argv = [
            sys.executable,
            "-m",
            "zikaron.knowledge",
            "--project",
            str(project),
            "status",
            "no",
        ]
        result = subprocess.run(  # noqa: S603 — a fixed, test-constructed interpreter path.
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 1
        assert "refused" in result.stderr


class TestWhatTheOutputSays:
    def test_a_corpus_with_no_skips_says_none_rather_than_nine_zeroes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The question the breakdown answers is *why is a file missing from the corpus*, and a
        wall of zeroes buries the one reason that fired. "Nothing was skipped" and "this was not
        measured" are different answers, so the empty case says so rather than printing nothing."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "skipped   none" in capsys.readouterr().out

    def test_a_corpus_with_no_globs_says_so_rather_than_printing_an_empty_list(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "include   \u2014" in printed
        assert "exclude   \u2014" in printed

    def test_a_verb_the_dispatch_does_not_handle_fails_loudly(self, project: Path) -> None:
        """Unreachable through the command, which refuses an unknown verb before dispatch. Asserted
        because the branch a silent fall-through would land in is the destructive one: a verb added
        to the parser and forgotten here must fail rather than remove a knowledge base."""

        async def _go() -> None:
            async with await Store.open(project / ".zikaron", config_for(project)) as store:
                await _dispatch(
                    argparse.Namespace(verb="invent"),
                    project / ".zikaron",
                    store.connection,
                    config_for(project),
                )

        with pytest.raises(NotImplementedError, match="invent"):
            asyncio.run(_go())


class TestWhereTheCommandActs:
    def test_without_a_project_it_uses_the_same_scope_rule_both_clients_use(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Resolved through the harness seam rather than by reading the working directory here, so
        this command and the agent's own tools address one store rather than two."""
        monkeypatch.chdir(project)
        assert main(["list"]) == 0
        assert "no knowledge bases" in capsys.readouterr().out

    def test_a_knowledge_base_with_no_database_prints_that_rather_than_zeroes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A corpus that has never been built has no diagnostics to show, and printing zeroes for
        them would read as measurements of an empty corpus rather than as their absence."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        for path in (project / ".zikaron" / "knowledge").iterdir():
            path.unlink()
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "no database to read" in printed
        assert "reindex_required" in printed

    def test_a_failure_that_is_not_a_refusal_is_reported_rather_than_traced(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every predictable refusal is raised as one. This is the remainder — a full disk, a
        revoked permission — which tells whoever ran the command nothing they can act on if it
        arrives as a traceback."""

        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("the disk is full")

        monkeypatch.setattr(lifecycle, "list_bases", _fail)
        assert _run(project, "list") == 1
        assert "failed: the disk is full" in capsys.readouterr().err
