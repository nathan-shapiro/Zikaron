"""The command a person runs, driven in-process so both its exit status and its output are read.

`main` returns a status rather than exiting for exactly this reason. What is checked here is the
command's own job — parsing, dispatch, exit statuses and what it prints — since every decision it
reports belongs to `zikaron.core.knowledge` and is tested there.
"""

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.knowledge_fixtures import config_for, corpus_root
from tests.service_fixtures import context_over, envelope
from zikaron.core.errors import Disposition, ErrorCode, ZikaronError
from zikaron.core.knowledge import lock, registry, reporting
from zikaron.core.knowledge import paths as knowledge_paths
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.core.store.transactions import in_one_transaction, propagate
from zikaron.knowledge import client
from zikaron.knowledge import main as cli
from zikaron.knowledge.indexer import detach
from zikaron.knowledge.main import _age, main
from zikaron.service import dispatch_knowledge

#: A pid no process can have, so *not running* is a fact rather than a race with the scheduler.
_DEAD_PID: Final = 2**22 + 7


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


@dataclass(frozen=True, slots=True)
class _Started:
    """One build this command asked for, as the arguments it asked with."""

    name: str
    project: Path
    full: bool


@pytest.fixture(autouse=True)
def started(monkeypatch: pytest.MonkeyPatch) -> list[_Started]:
    """Every build the command under test starts, recorded instead of run.

    Autouse rather than opt-in: `add` and `refresh` both start one, so a test that forgot this
    would spawn a real build of a real corpus — minutes of work in a test process, outliving the
    test that caused it. What the spawn itself does is checked where it lives.
    """
    asked: list[_Started] = []

    def _record(name: str, *, project: Path, full: bool = False) -> list[str]:
        asked.append(_Started(name=name, project=project, full=full))
        return detach.command(name, project=project, full=full)

    monkeypatch.setattr(detach, "spawn", _record)
    return asked


@pytest.fixture(autouse=True)
def in_process_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the command's RPC calls in this process, against the store the test made.

    **The socket is the only thing skipped.** Every call goes through the real method table, the
    real handlers and the real serialization, so what these tests read is the payload a service
    would have sent — which is the half the command's own behaviour depends on. The transport is
    covered where it lives, in `test_mcp_connection_*`; a live service per test would pay seconds
    of model load for a surface that never touches the model.

    A `ZikaronError` a handler raises becomes a `ServiceRefusalError` here, as `server.py`'s
    `encode_error` and the client's own parse would together make it — that translation is what
    the command's refusal rendering is written against.
    """

    @asynccontextmanager
    async def _connected(project: Path) -> AsyncIterator[client.KnowledgeClient]:
        yield _InProcessClient(project)

    monkeypatch.setattr(cli, "connected", _connected)


def _as_wire(payload: object) -> dict[str, object]:
    """One payload as the transport would deliver it, rather than as Python objects.

    The socket is the only thing this double skips, and JSON is half of what a socket does: a
    `Path`, an enum, a tuple or a non-string key survives an in-process hand-off and changes shape
    or fails on the wire. Round-tripping here is what stops that passing unnoticed.
    """
    encoded = json.loads(json.dumps(payload))
    assert isinstance(encoded, dict), f"a result must encode as an object, not {type(encoded)}"
    return encoded


class _Answering:
    """A `ServiceConnection` that returns one fixed response line, so `KnowledgeClient.call` runs
    for real against it — envelope, `parse_response`, and whichever of its two raises applies."""

    def __init__(self, response: dict[str, object]) -> None:
        self._response = response

    def envelope(self, *, kind: str) -> object:  # noqa: ARG002 — the signature is the contract.
        return object()

    async def request(self, *_sent: object, **_keywords: object) -> dict[str, object]:
        return self._response


class _InProcessClient(client.KnowledgeClient):
    """A `KnowledgeClient` that dispatches straight into the service's own method table.

    Deliberately holds no `ServiceConnection`: there is no socket to reach, which is the whole
    point, and `call` is overridden so nothing ever reads one.
    """

    def __init__(self, project: Path) -> None:
        self.project = project

    async def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        async with context_over(self.project / ".zikaron", self.project) as ctx:
            try:
                result = await dispatch_knowledge.KNOWLEDGE_METHODS[method](
                    ctx.store.connection, ctx, envelope(kind="cli"), params
                )
            except ZikaronError as error:
                raise client.ServiceRefusalError(
                    code=int(error.code), message=error.message, data=_as_wire(dict(error.data))
                ) from error
            return _as_wire(result.as_json())


def _run(project_dir: Path, *argv: str) -> int:
    return main(["--project", str(project_dir), *argv])


def _unlink_database(project_dir: Path, name: str) -> None:
    """Delete one named corpus's own database, leaving its registry row behind.

    Resolved through the registry rather than by emptying the `knowledge/` directory: the filename
    is a generated id, so clearing the directory takes every corpus with it and is wrong the moment
    a test has two.
    """

    async def _go() -> None:
        store_dir = project_dir / ".zikaron"
        async with await Store.open(store_dir, config_for(project_dir)) as store:
            registered = await registry.require(store.connection, name)
        knowledge_paths.knowledge_db_path(store_dir, registered.id).unlink()

    asyncio.run(_go())


def _corrupt_database(project_dir: Path, name: str) -> None:
    """Leave one named corpus's database in place and make it unopenable.

    The distinction this exists for: a database that is **gone** holds nothing, and a database that
    is **present and will not open** may hold a fully built corpus refused for a permission or a
    schema reason. Reported identically, those two would tell somebody about to delete a corpus
    that there is nothing to lose when nobody can say.
    """

    async def _go() -> None:
        store_dir = project_dir / ".zikaron"
        async with await Store.open(store_dir, config_for(project_dir)) as store:
            registered = await registry.require(store.connection, name)
        path = knowledge_paths.knowledge_db_path(store_dir, registered.id)
        path.write_bytes(b"this is not a SQLite database")

    asyncio.run(_go())


def _database_of(project_dir: Path, name: str) -> Path:
    """One corpus's own database file, resolved through the registry rather than by globbing."""

    async def _go() -> Path:
        store_dir = project_dir / ".zikaron"
        async with await Store.open(store_dir, config_for(project_dir)) as store:
            registered = await registry.require(store.connection, name)
            return knowledge_paths.knowledge_db_path(store_dir, registered.id)

    return asyncio.run(_go())


def _begin_a_build(database: Path, *, pid: int, host: str) -> None:
    """Write what an indexer writes the moment it starts: a scan mark and its own lock.

    Together these are what `_still_building` reads as *running* — the mark advanced past the
    baseline, and a lock whose process this host can see alive.
    """
    with closing(sqlite3.connect(database)) as db:
        for key, value in (
            ("last_scan_started_at", "2026-09-24T11:00:00+00:00"),
            ("lock_pid", str(pid)),
            ("lock_host", host),
            ("lock_started_at", "2026-09-24T11:00:00+00:00"),
        ):
            db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        db.commit()


def _orphan_the_lock(database: Path) -> None:
    """Leave the lock rows in place, holding a pid no process can have.

    What a killed indexer leaves: nothing releases a lock on a kill, so the rows survive with a
    holder this host can probe and find gone. Synchronous, for the same reason as its neighbours.
    """
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE meta SET value = ? WHERE key = 'lock_pid'", (str(_DEAD_PID),))
        db.commit()


def _release_the_lock(database: Path) -> None:
    """Clear a build lock synchronously, as the end of a build would.

    Takes the path rather than resolving one: the caller runs inside the command's own event loop,
    where anything reaching for `asyncio.run` raises instead of reentering it.
    """
    with closing(sqlite3.connect(database)) as db:
        db.execute("DELETE FROM meta WHERE key IN ('lock_pid', 'lock_host', 'lock_started_at')")
        db.commit()


def _mark_scan_complete(database: Path) -> None:
    """Write what a completed scan writes, without running one.

    Plain `sqlite3`, because the one caller is a `detach.spawn` stub that runs **inside** the
    command's own event loop — `asyncio.run` there raises rather than reentering it.
    """
    with closing(sqlite3.connect(database)) as db:
        for key in ("last_scan_started_at", "last_scan_completed_at"):
            db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, "2026-09-24T12:00:00+00:00"),
            )
        db.commit()


def _hold_the_lock(project_dir: Path, *, pid: int, host: str) -> None:
    """Record a build lock against the `docs` corpus, as a real indexer would when it starts.

    Written straight into the knowledge base's own `meta` rather than by starting a build, because
    what these tests are about is what the command does when it *finds* one — including the two
    holders no build of this test's own could produce: one on another machine, and one whose
    process has died.
    """

    async def _go() -> None:
        store_dir = project_dir / ".zikaron"
        config = config_for(project_dir)
        async with await Store.open(store_dir, config) as store:
            registered = await registry.require(store.connection, "docs")
            async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:

                async def _work(connection: aiosqlite.Connection) -> None:
                    await lock.acquire(
                        connection, pid=pid, host=host, started_at="2026-01-01T00:00:00+00:00"
                    )

                await in_one_transaction(opened.connection, _work, failure=propagate)

    asyncio.run(_go())


class TestTheVerbs:
    def test_an_empty_listing_names_the_project_it_looked_in(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Which project answered, on the one reply that carries nothing else identifying.

        A storeless project is refused outright (`test_project_scope.py`), so this is the other
        case: a real store with no corpora registered in it. `--project` and the harness variable
        both put that store somewhere the reader did not type, and an unqualified *no knowledge
        bases* would leave them guessing which project was asked.
        """
        assert _run(project, "list") == 0
        assert f"no knowledge bases in {project}" in capsys.readouterr().out

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

    def test_the_preview_counts_a_corpus_that_can_be_read(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A corpus that opens is counted, and a never-built one honestly holds nothing — so the
        zero here is a measurement rather than a placeholder. It is the pair to the case below,
        which is the one where zero would be a lie."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "remove", "docs") == 1
        assert "0 files, 0 chunks" in capsys.readouterr().out

    def test_the_preview_refuses_to_count_a_corpus_that_will_not_open(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Its database may hold a fully built index and be refused for a permission or a schema
        reason, so a count of zero would read as *nothing to lose* about something nobody can
        measure — on the one verb nothing undoes."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _corrupt_database(project, "docs")
        capsys.readouterr()

        assert _run(project, "remove", "docs") == 1
        printed = capsys.readouterr().out
        assert "an unknown amount" in printed
        assert "chunks" not in printed

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


class TestTheFollowLineNamesTheInvocationTheUserTyped:
    """The line every `add` and `refresh` prints, offered as the way to watch a build.

    A hard-coded `python -m zikaron.knowledge` here is a command that fails with `No module named
    zikaron` under `uv tool install`, where no interpreter is on `PATH` — printed to a user on the
    first corpus they ever build.
    """

    @pytest.mark.parametrize(
        "prog", ["zikaron knowledge", "python -m zikaron.knowledge"], ids=["console", "module"]
    )
    def test_the_follow_line_uses_the_prog_it_was_run_as(
        self, project: Path, prog: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        status = main(
            [
                "--project",
                str(project),
                "add",
                "docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
            ],
            prog=prog,
        )
        assert status == 0
        assert f"follow    {prog} status docs" in capsys.readouterr().out


class TestHowAWireErrorReadsOnThisCommand:
    """A rejection the service sent, as this command prints it.

    Driven through `ServiceRefusalError.render` rather than through a verb, because the rendering
    is what is under test and a verb would pin one code's wording as well.
    """

    @staticmethod
    def _refusal(code: ErrorCode, **data: object) -> client.ServiceRefusalError:
        """One refusal shaped exactly as the wire delivers it: a code, a message, and a payload.

        Built through `ZikaronError` so the message and the payload's field order are the
        contract's own rather than this test's invention, then reduced to what crosses the wire.
        """
        error = ZikaronError(code, **data)
        return client.ServiceRefusalError(
            code=int(error.code), message=error.message, data=dict(error.data)
        )

    def test_the_payload_reads_as_fields_not_as_a_dict(self) -> None:
        """Interpolating the payload gives `{'source': 'file', …}` — quoted keys and braces, which
        reads as a traceback fragment rather than as a diagnosis."""
        printed = self._refusal(
            ErrorCode.BAD_CONFIG,
            source="file",
            key="runtime_dir",
            value="/nope",
            expected="a directory that exists",
        ).render()
        assert "source=file, key=runtime_dir, value=/nope, expected=a directory that exists" in (
            printed
        )
        assert "{" not in printed

    def test_the_whole_refusal_is_one_line(self) -> None:
        """The message text itself is pinned against the design table in `test_error_codes.py`, so
        what is asserted here is the shape it is wrapped in and that nothing wraps onto a second.
        """
        refusal = self._refusal(ErrorCode.NOT_FOUND, uuid="a1b2")
        assert refusal.render() == f"refused: {refusal.message} (uuid=a1b2)"

    def test_a_code_the_caller_cannot_act_on_reads_as_failed(self) -> None:
        """The prefix comes from the code's own declared disposition, so this command and
        `zikaron-mcp` cannot disagree about whether there is a different call to make."""
        refusal = self._refusal(
            ErrorCode.STORE_UNAVAILABLE, operation="knowledge_list", cause="disk I/O error"
        )
        assert refusal.render().startswith("failed: ")

    def test_a_code_this_build_does_not_know_reads_as_failed(self) -> None:
        """A service newer than this client can send one. `failed` is the honest reading: nothing
        here can say what a caller might do about a rejection it cannot even name — and the
        alternative, crashing on the unknown code, would turn a readable refusal into a traceback.
        """
        unknown = client.ServiceRefusalError(code=-32098, message="something new", data={})
        assert unknown.render() == "failed: something new"


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
        printed = capsys.readouterr().err
        assert "refused" in printed
        assert str(project / "nope") in printed, "the refusal must name the path it rejected"

    def test_a_tilde_naming_no_known_user_is_refused_rather_than_traced(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A shell leaves `~someone` alone when it knows no such user, so the command receives it
        literally — and expansion then fails. This is a person's typo, and it has to read as one:
        a traceback tells whoever ran it nothing they can act on."""
        assert (
            _run(
                project, "add", "docs", "--path", "~no-such-user-zikaron/docs", "--description", "d"
            )
            == 1
        )
        printed = capsys.readouterr().err
        assert "refused" in printed
        assert "~no-such-user-zikaron/docs" in printed, (
            "the unexpanded form is what the person typed, so it is what the refusal must name"
        )

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
    run. Only a real subprocess exercises the `__main__` module that makes a package executable.

    `--help` is the whole of what belongs here: it reaches no service, so it leaves none behind.
    The status a refusal returns through `__main__` is checked in `test_knowledge_cli_integration`,
    where a subprocess that starts a real service is reaped rather than abandoned — monkeypatch
    does not cross a process boundary, so nothing here could have stubbed one out.
    """

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
            await cli._dispatch(argparse.Namespace(verb="invent"), _InProcessClient(project))

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
        _unlink_database(project, "docs")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "no database to read" in printed
        assert "reindex_required" in printed

    def test_a_knowledge_base_whose_database_will_not_open_says_so_instead(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pair to the case above, and the reason the two are not one line: this corpus's file
        may hold a fully built index and be refused for a permission or a schema reason, so
        *nothing has been built here yet* would be a confident claim about what nobody measured."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _corrupt_database(project, "docs")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "cannot be read" in printed
        assert "nothing has been built" not in printed
        assert "state error" in printed

    def test_a_failure_that_is_not_a_refusal_is_reported_rather_than_traced(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every predictable refusal is raised as one. This is the remainder — a full disk, a
        revoked permission — which tells whoever ran the command nothing they can act on if it
        arrives as a traceback."""

        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("the disk is full")

        monkeypatch.setattr(reporting, "list_bases", _fail)
        assert _run(project, "list") == 1
        printed = capsys.readouterr().err
        assert printed.startswith("failed: "), "not a refusal: nothing the caller sends fixes it"
        assert "the disk is full" in printed, "the driver's own words, or there is no diagnosis"


class TestStartingABuild:
    """`add` and `refresh` both start one and return. Nothing waits: a build is minutes of work
    over a whole tree, and the two verbs that create a corpus would otherwise be the two slowest
    things this command does."""

    def test_add_starts_a_build_of_the_corpus_it_just_created(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "add", "Docs", "--path", str(project / "docs"), "--description", "d") == 0
        )
        assert started == [_Started(name="docs", project=project, full=False)]
        printed = capsys.readouterr().out
        assert "building" in printed
        assert "status docs" in printed

    def test_refresh_starts_one_for_a_corpus_that_already_exists(
        self, project: Path, started: list[_Started]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()

        assert _run(project, "refresh", "docs") == 0
        assert started == [_Started(name="docs", project=project, full=False)]

    def test_a_full_build_is_asked_for_by_name(
        self, project: Path, started: list[_Started]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()

        assert _run(project, "refresh", "docs", "--full") == 0
        assert started == [_Started(name="docs", project=project, full=True)]

    def test_the_command_that_reproduces_a_failed_build_is_printed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A detached build's output goes nowhere, so the one way back to *why* it failed is to run
        the identical command where its output can be seen."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--full") == 0
        printed = capsys.readouterr().out
        assert "zikaron.knowledge.indexer" in printed
        assert "--full" in printed
        assert str(project) in printed

    def test_an_unknown_name_refuses_in_the_foreground_and_starts_nothing(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The build detaches with its output discarded, so a refusal it raised would reach nobody.
        Everything decidable without reading a file is decided here instead."""
        assert _run(project, "refresh", "absent") == 1
        assert started == []
        assert "refused" in capsys.readouterr().err

    def test_a_database_that_will_not_open_is_a_failure_rather_than_a_refusal(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The two prefixes mean different things. A refusal is this system declining something it
        understood and naming what to do instead; a failure is the driver's own error travelling
        out unrenamed, because nothing invented here would describe it better. Printing the second
        as the first tells a reader there is a remedy to look for."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _corrupt_database(project, "docs")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        printed = capsys.readouterr().err
        assert "failed" in printed
        assert "refused" not in printed

    def test_a_knowledge_base_with_no_database_refuses_rather_than_starting_a_build(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Everything that says what a corpus indexes lives in the file that is missing, so there
        is nothing for a walk to walk."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _unlink_database(project, "docs")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        assert "remove it and add it again" in capsys.readouterr().err

    def test_a_root_that_has_gone_refuses_in_the_foreground_and_starts_nothing(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The refusal a detached build leaves no trace of at all: it happens before the lock is
        taken, so there is not even a dead holder to find afterwards."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        for path in (project / "docs").iterdir():
            path.unlink()
        (project / "docs").rmdir()
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 1
        assert started == []
        assert "kept as it is" in capsys.readouterr().err

    def test_a_build_that_cannot_be_shown_dead_starts_no_second_one(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reported rather than refused, and the command succeeds: a refresh that met a running
        build got what it asked for — the corpus is being built. Making this a failure would turn a
        loop of refreshes against a long build into a loop of failures, and the whole point of the
        verb being idempotent is that a caller may run it whenever it likes."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs") == 0
        assert started == [], "nothing was queued and no second build began"
        printed = capsys.readouterr()
        assert "already being built" in printed.out
        assert printed.err == "", "this is not a refusal, so nothing goes to standard error"

    def test_a_lock_a_crashed_build_left_stops_nothing(
        self, project: Path, started: list[_Started]
    ) -> None:
        """Those rows survive on purpose, and the next build reclaims them. Refusing on them would
        make one dead process a permanent refusal."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host=lock.this_host())
        started.clear()

        assert _run(project, "refresh", "docs") == 0
        assert started == [_Started(name="docs", project=project, full=False)]


class TestClearingALockFromTheCommandLine:
    def test_a_foreign_lock_is_cleared_and_the_build_goes_ahead(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing reclaims a foreign lock on its own, so without this the corpus is one nothing
        can build, remove or wait out."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host="another-machine")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 0
        printed = capsys.readouterr().out
        assert "cleared the lock" in printed
        assert started == [_Started(name="docs", project=project, full=False)]

    def test_a_running_local_build_is_refused_and_nothing_is_started(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 1
        assert started == []
        printed = capsys.readouterr().err
        assert "refused" in printed
        assert str(os.getpid()) in printed, "the refusal must name who is holding it"

    def test_no_lock_at_all_is_reported_and_the_build_still_starts(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Somebody reaching for this cannot see whether a lock is still there, which is why they
        are reaching for it — and the flag is on `refresh`, so finding nothing to clear leaves the
        verb they actually asked for to go ahead."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--force-unlock") == 0
        assert "nothing to clear" in capsys.readouterr().out
        assert started == [_Started(name="docs", project=project, full=False)]


class TestWhatStatusSaysAboutABuild:
    def test_a_running_build_on_this_host_is_reported_as_running(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "still answers to that pid" in printed
        assert f"pid {os.getpid()}" in printed

    def test_a_build_whose_process_is_gone_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The only evidence a detached build died: its output went nowhere, and every counter it
        left behind looks exactly like one still climbing."""
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host=lock.this_host())
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "no longer running" in capsys.readouterr().out

    def test_a_foreign_lock_points_at_the_way_to_clear_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _hold_the_lock(project, pid=_DEAD_PID, host="another-machine")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        printed = capsys.readouterr().out
        assert "another-machine" in printed
        assert "--force-unlock" in printed

    def test_a_corpus_nobody_is_building_reports_no_lock_at_all(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "status", "docs") == 0
        assert "build     " not in capsys.readouterr().out


class TestAStoreThatCannotBeRead:
    def test_it_says_the_registry_is_unavailable_rather_than_that_there_are_none(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The list of knowledge bases lives in the memory store, so a store that will not open
        makes every corpus undiscoverable — and *no knowledge bases* is a real answer for a project
        that has none, which a caller would read as the corpora being gone."""
        (project / ".zikaron" / "memory.db").write_bytes(b"not a database at all")

        assert _run(project, "list") == 1
        printed = capsys.readouterr()
        assert printed.err, "a store that will not open must say so"
        assert "no knowledge bases" not in printed.out, (
            "*no knowledge bases* is a real answer for a project that has none, and a caller told "
            "it here would read the corpora as gone"
        )

    def test_the_driver_error_reaches_the_person_rather_than_a_traceback(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`Store.open` on a file that is not a database raises a bare `sqlite3.DatabaseError` —
        measured, not assumed. Here the double's own service-context open stands in for the
        identity read, raising the identical bare error from the identical pragma. Uncaught it
        would be a traceback; what a person needs is the driver's own sentence.
        """
        (project / ".zikaron" / "memory.db").write_bytes(b"not a database at all")

        assert _run(project, "list") == 1
        assert "not a database" in capsys.readouterr().err


class TestHowALocksAgeIsPrinted:
    """Coarse on purpose: the question is *has this been sitting here*, so a second-exact figure
    would be precision nobody acts on over a number large enough to have to be counted digit by
    digit. Each unit is checked at its own boundary, because an off-by-one there reports days as
    hours."""

    @pytest.mark.parametrize(
        ("seconds", "printed"),
        [
            (0.0, "0s"),
            (59.9, "59s"),
            (60.0, "1m"),
            (3599.0, "59m"),
            (3600.0, "1h"),
            (86399.0, "23h"),
            (86400.0, "1d"),
            (200000.0, "2d"),
        ],
    )
    def test_each_unit_takes_over_at_its_own_boundary(self, seconds: float, printed: str) -> None:
        assert _age(seconds) == printed


class TestRefreshingEveryKnowledgeBase:
    """`refresh` with no name reaches every corpus, each checked on its own — so one that cannot be
    built never denies the others a build they could have had."""

    @staticmethod
    def _two(project: Path) -> None:
        (project / "runbooks").mkdir()
        (project / "runbooks" / "a.md").write_text("a line\n", encoding="utf-8")
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        _run(project, "add", "runbooks", "--path", str(project / "runbooks"), "--description", "d")

    def test_it_starts_a_build_for_each_one(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._two(project)
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh") == 0
        assert {one.name for one in started} == {"docs", "runbooks"}

    def test_full_reaches_every_one(self, project: Path, started: list[_Started]) -> None:
        self._two(project)
        started.clear()

        assert _run(project, "refresh", "--full") == 0
        assert all(one.full for one in started)

    def test_one_corpus_that_cannot_be_built_does_not_stop_the_rest(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """And the command still reports a failure, because something the caller asked for did not
        happen — the sweep completing is not the same as the sweep succeeding."""
        self._two(project)
        _unlink_database(project, "docs")
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh") == 1
        assert [one.name for one in started] == ["runbooks"]
        printed = capsys.readouterr()
        assert "remove it and add it again" in printed.err
        assert "runbooks" in printed.out

    def test_an_empty_store_says_so_and_succeeds(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing was asked for that could not be done: a project with no knowledge bases is not
        a failed refresh."""
        assert _run(project, "refresh") == 0
        assert started == []
        assert "no knowledge bases" in capsys.readouterr().out

    def test_force_unlock_with_no_name_is_refused(
        self, project: Path, started: list[_Started], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """It clears one corpus's lock, and clearing every one on a bare `--force-unlock` is a
        destructive reading of an omitted argument rather than a convenience."""
        self._two(project)
        started.clear()
        capsys.readouterr()

        assert _run(project, "refresh", "--force-unlock") == 1
        assert started == [], "nothing is built by a call that was refused"
        assert "name one" in capsys.readouterr().err


class TestWhatTheFollowLineSays:
    def test_a_two_word_name_is_quoted_so_the_line_can_be_pasted_back(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Names are free-form and two-word ones are ordinary. Unquoted, the line offered as the way
        to follow a build is a command that fails to parse."""
        assert (
            _run(
                project,
                "add",
                "Design Docs",
                "--path",
                str(project / "docs"),
                "--description",
                "d",
            )
            == 0
        )
        printed = capsys.readouterr().out
        assert "status 'design docs'" in printed


class TestWaitingForABuild:
    """`refresh --wait` returns when the builds it started are over, and exits on what they left.

    The predicate is checked in pieces as well as end to end, because the two halves it composes
    fail in opposite directions: keyed on the lock alone it returns before a build has begun, and
    keyed on the scan mark alone it returns while one is still writing.
    """

    @staticmethod
    def _entry(*, mark: str | None, lock_live: bool | None, held: bool = True) -> dict[str, object]:
        entry: dict[str, object] = {"name": "docs", "last_scan_started_at": mark}
        entry["lock"] = {"pid": 1, "host": "h", "live": lock_live} if held else None
        return entry

    def test_an_unchanged_scan_mark_means_the_build_has_not_begun(self) -> None:
        """The spawn race: a lock is taken shortly *after* the spawn, so a fast first poll sees
        none and would otherwise call a build that never started finished."""
        entry = self._entry(mark="t0", lock_live=None, held=False)
        assert cli._still_building(entry, mark="t0")

    def test_an_advanced_mark_with_no_lock_means_it_is_over(self) -> None:
        assert not cli._still_building(
            self._entry(mark="t1", lock_live=None, held=False), mark="t0"
        )

    def test_an_advanced_mark_with_a_live_lock_means_it_is_still_running(self) -> None:
        assert cli._still_building(self._entry(mark="t1", lock_live=True), mark="t0")

    def test_a_lock_this_host_can_see_is_dead_does_not_hold_the_wait_open(self) -> None:
        """Nothing releases a killed build's lock, so a wait that treated one as running would
        never end — which is the whole failure `--wait` exists to avoid in a CI step."""
        assert not cli._still_building(self._entry(mark="t1", lock_live=False), mark="t0")

    def test_a_foreign_lock_holds_the_wait_open(self) -> None:
        """`live: null` is *this machine cannot say*, which is not evidence the build is over."""
        assert cli._still_building(self._entry(mark="t1", lock_live=None), mark="t0")

    def test_only_ok_is_reported_as_built(self, capsys: pytest.CaptureFixture[str]) -> None:
        reports = {"docs": {"name": "docs", "state": "ok"}}
        assert cli._report_terminal_states(reports, ["docs"]) == set()
        assert "built     'docs' is ok" in capsys.readouterr().out

    @pytest.mark.parametrize("state", ["reindex_required", "root_missing", "error"])
    def test_any_other_terminal_state_fails_the_command(
        self, state: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A build that ran and left the corpus unusable must not read as success: a script that
        waited for it is about to act as though the corpus can be searched."""
        reports = {"docs": {"name": "docs", "state": state}}
        assert cli._report_terminal_states(reports, ["docs"]) == {"docs"}, (
            "the set holds corpus *names*: the caller intersects it against what this call started"
        )
        assert state in capsys.readouterr().err

    def test_a_build_that_never_starts_fails_rather_than_waiting_forever(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The spawn is recorded and never run here, so nothing ever takes the lock or writes a
        scan mark — which is exactly what a spawn that died before either would leave behind."""
        monkeypatch.setattr(cli, "_APPEARANCE_DEADLINE_SECONDS", 0.2)
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()

        assert _run(project, "refresh", "docs", "--wait") == 1
        assert "no build started" in capsys.readouterr().err

    def test_a_completed_build_is_waited_for_and_reported(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A build that runs, finishes and leaves the corpus usable ends the wait and exits 0.

        The spawn writes what a completed scan writes rather than running one: what is under test
        is the command's waiting, and a real build is the integration file's business.
        """
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        database = _database_of(project, "docs")

        def _finish(name: str, **_spawned: object) -> list[str]:
            _mark_scan_complete(database)
            return ["python", "-m", "zikaron.knowledge.indexer", name]

        monkeypatch.setattr(detach, "spawn", _finish)
        assert _run(project, "refresh", "docs", "--wait") == 0
        assert "built     'docs' is ok" in capsys.readouterr().out


class TestWhatAWaitShows:
    """A wait is minutes long, so it has to say something — and not the same thing every second."""

    def test_the_walk_phase_does_not_invent_a_remaining_count(self) -> None:
        """`files_remaining` is `None` until the walk finishes, deliberately: an empty pending
        table means *still walking* and *nothing changed* alike. A line reading `0 to go` there
        would be the one number nobody can yet have."""
        line = cli._progress_line({"files_indexed": 12, "files_remaining": None})
        assert "still finding what changed" in line
        assert "0" not in line

    def test_once_the_walk_is_done_both_numbers_are_shown(self) -> None:
        line = cli._progress_line({"files_indexed": 12, "files_remaining": 30})
        assert line == "12 files indexed, 30 to go"

    def test_progress_is_printed_only_when_it_moves(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Polling is once a second over a build of minutes, so a line per poll is hundreds of
        identical lines in a CI log — which is why this prints on change rather than on a clock."""
        shown: dict[str, str] = {}
        for _ in range(3):
            cli._show_progress("docs", {"files_indexed": 1, "files_remaining": 9}, shown)
        cli._show_progress("docs", {"files_indexed": 4, "files_remaining": 6}, shown)

        printed = [line for line in capsys.readouterr().err.splitlines() if line]
        assert printed == [
            "building  docs: 1 files indexed, 9 to go",
            "building  docs: 4 files indexed, 6 to go",
        ]

    def test_progress_goes_to_stderr_so_output_stays_pipeable(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli._show_progress("docs", {"files_indexed": 1, "files_remaining": 9}, {})
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "1 files indexed" in captured.err


class TestASweepWhereOnlySomeBuildsStart:
    """One corpus building must not hold the call open on another whose spawn never appeared.

    The hang this rules out is the one `--wait` exists to remove from a CI step: a single
    appearance flag lets the corpus that *did* start suppress the only escape for the one that did
    not, and the call then waits forever on a build that will never exist.
    """

    def test_a_corpus_that_never_appears_fails_even_while_another_is_building(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli, "_APPEARANCE_DEADLINE_SECONDS", 0.2)
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        for name in ("docs", "runbooks"):
            (project / name).mkdir(exist_ok=True)
            (project / name / "a.md").write_text("x\n", encoding="utf-8")
            _run(project, "add", name, "--path", str(project / name), "--description", "d")
        capsys.readouterr()

        building = _database_of(project, "docs")

        def _only_docs_starts(name: str, **_spawned: object) -> list[str]:
            if name == "docs":
                _mark_scan_complete(building)
            return ["python", "-m", "zikaron.knowledge.indexer", name]

        monkeypatch.setattr(detach, "spawn", _only_docs_starts)
        assert _run(project, "refresh", "--wait") == 1
        printed = capsys.readouterr()
        assert "no build started" in printed.err
        assert "runbooks" in printed.err
        assert "built     'docs' is ok" in printed.out, (
            "giving up on the spawn that died must not abandon the build that started: the call "
            "fails because of the dead one, not instead of reporting the live one"
        )

    def test_a_live_build_is_still_waited_for_after_another_is_given_up_on(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Giving up on a dead spawn must not end the call while a real build is running.

        Ending there would leave the step with an indexer still going — the exact hazard `--wait`
        exists to remove — so the corpus that never appeared is dropped from what is watched and
        the rest of the wait continues. `docs` finishes only on the third poll, which is after the
        deadline for `runbooks` has passed.
        """
        monkeypatch.setattr(cli, "_APPEARANCE_DEADLINE_SECONDS", 0.05)
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        for name in ("docs", "runbooks"):
            (project / name).mkdir(exist_ok=True)
            (project / name / "a.md").write_text("x\n", encoding="utf-8")
            _run(project, "add", name, "--path", str(project / name), "--description", "d")
        capsys.readouterr()

        building = _database_of(project, "docs")
        polls = 0
        # Patched on `_InProcessClient`, not on its base: this file's fixture yields that subclass
        # and it overrides `call`, so a patch on `KnowledgeClient` would never run.
        real_call = _InProcessClient.call

        async def _counted(
            self: _InProcessClient, method: str, params: dict[str, object]
        ) -> dict[str, object]:
            nonlocal polls
            if method == "knowledge_status":
                polls += 1
                if polls == 3:
                    _release_the_lock(building)
                    _mark_scan_complete(building)
            return await real_call(self, method, params)

        def _only_docs_starts(name: str, **_spawned: object) -> list[str]:
            if name == "docs":
                _begin_a_build(building, pid=os.getpid(), host=lock.this_host())
            return ["python", "-m", "x", name]

        monkeypatch.setattr(_InProcessClient, "call", _counted)
        monkeypatch.setattr(detach, "spawn", _only_docs_starts)

        assert _run(project, "refresh", "--wait") == 1
        printed = capsys.readouterr()
        assert "no build started" in printed.err, "runbooks never appeared"
        assert "built     'docs' is ok" in printed.out, "docs was waited for to the end"
        assert polls >= 3, "the wait outlasted the deadline that killed runbooks"


class TestWaitingForABuildSomebodyElseStarted:
    """`already_indexing` is a build running against a named corpus, so `--wait` waits for it.

    The sequence that reaches this is the documented one: `add` starts a build and has no `--wait`,
    so a `refresh --wait` arriving after that build took its lock finds it already under way.
    Returning 0 there would end a CI step with the indexer alive.
    """

    def test_it_waits_for_a_local_build_already_under_way(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        database = _database_of(project, "docs")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())

        polls = 0
        real_call = _InProcessClient.call

        async def _counted(
            self: _InProcessClient, method: str, params: dict[str, object]
        ) -> dict[str, object]:
            nonlocal polls
            if method == "knowledge_status":
                polls += 1
                if polls == 3:
                    _release_the_lock(database)
                    _mark_scan_complete(database)
            return await real_call(self, method, params)

        monkeypatch.setattr(_InProcessClient, "call", _counted)

        assert _run(project, "refresh", "docs", "--wait") == 0
        printed = capsys.readouterr().out
        assert "already being built" in printed
        assert "built     'docs' is ok" in printed
        assert polls >= 3, "it polled until the build somebody else started was over"

    def test_a_lock_held_by_another_host_fails_rather_than_waiting_forever(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`live: null` is *this machine cannot say*, and nothing here will ever see it released.

        Waiting on it is waiting forever, so the command names the exit an operator already has
        rather than hanging on a judgement `lock.probe` itself declines to make.
        """
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        _hold_the_lock(project, pid=_DEAD_PID, host="another-machine")

        assert _run(project, "refresh", "docs", "--wait") == 1
        printed = capsys.readouterr().err
        assert "cannot probe" in printed
        assert "refresh docs --force-unlock" in printed, (
            "the remedy names the corpus, since `--force-unlock` refuses without one and a sweep "
            "leaves the person nothing to add"
        )

    def test_a_build_that_ran_and_left_the_corpus_unusable_fails(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End to end rather than against `_report_terminal_states` alone: a build that took its
        lock and died leaves a mark advanced, a lock whose pid is provably gone, and no completion
        — so the wait ends and the terminal state is not `ok`."""
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        database = _database_of(project, "docs")

        def _dies_mid_build(name: str, **_spawned: object) -> list[str]:
            _begin_a_build(database, pid=_DEAD_PID, host=lock.this_host())
            return ["python", "-m", "x", name]

        monkeypatch.setattr(detach, "spawn", _dies_mid_build)
        assert _run(project, "refresh", "docs", "--wait") == 1
        printed = capsys.readouterr()
        assert "the build left it" in printed.err
        assert "foreground command printed beside it" in printed.out, (
            "a build this call started ended badly, and its own output went nowhere — the note "
            "pointing at the command that reproduces it is what recovers the reason"
        )

    def test_a_full_rebuild_says_it_did_not_start_when_one_is_already_running(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--full` against a corpus already being built queues nothing, and must say so.

        The build being waited for may be an ordinary one — nothing on the wire says which, since a
        lock records pid, host and start — so the line speaks only for *this* call, which is the
        half that would otherwise go unsaid while the command exits 0.
        """
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        database = _database_of(project, "docs")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())

        polls = 0
        real_call = _InProcessClient.call

        async def _counted(
            self: _InProcessClient, method: str, params: dict[str, object]
        ) -> dict[str, object]:
            nonlocal polls
            if method == "knowledge_status":
                polls += 1
                if polls == 2:
                    _release_the_lock(database)
                    _mark_scan_complete(database)
            return await real_call(self, method, params)

        monkeypatch.setattr(_InProcessClient, "call", _counted)

        assert _run(project, "refresh", "docs", "--full", "--wait") == 0
        printed = capsys.readouterr().out
        assert "this call queued nothing" in printed
        assert "the --full rebuild asked for here did not start" in printed

    def test_a_build_it_was_waiting_for_dying_ends_the_wait_rather_than_hanging(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A lock outlives the process that took it, so a dead holder must not read as running.

        Nothing releases a lock on a kill — the rows survive on purpose, for the next build to take
        over — so a wait that treated any recorded lock as evidence would poll until the step's own
        timeout. **Bounded here**, because a regression is a hang rather than a failure and this
        suite has no per-test timeout to catch one.
        """
        monkeypatch.setattr(cli, "_POLL_SECONDS", 0.02)
        _run(project, "add", "docs", "--path", str(project / "docs"), "--description", "d")
        capsys.readouterr()
        database = _database_of(project, "docs")
        _hold_the_lock(project, pid=os.getpid(), host=lock.this_host())

        polls = 0
        real_call = _InProcessClient.call

        async def _counted(
            self: _InProcessClient, method: str, params: dict[str, object]
        ) -> dict[str, object]:
            nonlocal polls
            if method == "knowledge_status":
                polls += 1
                if polls == 3:
                    _orphan_the_lock(database)
                if polls > 20:
                    raise AssertionError("the wait did not end on a holder this host proved dead")
            return await real_call(self, method, params)

        monkeypatch.setattr(_InProcessClient, "call", _counted)

        assert _run(project, "refresh", "docs", "--wait") == 1
        printed = capsys.readouterr()
        assert "the build left it" in printed.err
        assert polls >= 3
        assert "foreground command" not in printed.out, (
            "the note points at a line printed only for a build this call started, and this one "
            "was found already running — pointing at it would send a reader looking for nothing"
        )


class TestTheProjectHandedToTheService:
    def test_a_relative_project_is_resolved_before_it_is_sent(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The service outlives this shell, resolves nothing itself, and stringifies the value into
        the `foreground` command this command prints — a line that would act on a different project
        when pasted from elsewhere. So a relative `--project` is resolved before it is sent."""
        asked: list[Path] = []

        @asynccontextmanager
        async def _recording(target: Path) -> AsyncIterator[client.KnowledgeClient]:
            asked.append(target)
            yield _InProcessClient(project)

        monkeypatch.chdir(project.parent)
        monkeypatch.setattr(cli, "connected", _recording)
        assert main(["--project", project.name, "list"]) == 0

        (given,) = asked
        assert given.is_absolute()
        assert given == project


class TestTheEnvelopeTheCommandSends:
    def test_it_carries_the_cli_kind_on_the_wire(self) -> None:
        """Done-when 4's other half: the *value* `KnowledgeClient.call` puts on the envelope.

        `CLIENT_KIND` derives from the enum, so asserting the two equal proves nothing. What is
        worth pinning is that `call` builds its envelope with it — the in-process double used
        everywhere else overrides `call`, so that line runs nowhere in this file, and the
        integration suite would pass with any member, since `envelope.resolve` accepts them all.
        The literal rather than the constant, because the point is what a service receives.
        """
        recorded: list[str] = []

        class _Recording(_Answering):
            def __init__(self) -> None:
                super().__init__({"result": {}})

            def envelope(self, *, kind: str) -> object:
                recorded.append(kind)
                return object()

        sent = asyncio.run(
            client.KnowledgeClient(_Recording(), Path("/x")).call(  # type: ignore[arg-type]
                "knowledge_list", {}
            )
        )
        assert sent == {}
        assert recorded == ["cli"]

    def test_an_error_object_on_the_wire_becomes_a_refusal(self) -> None:
        """**`call`'s own error paths run nowhere else in this file.** The double every other test
        uses overrides `call` and raises `ServiceRefusalError` itself, so it exercises the
        *handling* of a refusal while the code that builds one from the wire never executes. This
        is the only place that goes through `parse_response`.
        """
        answered = {
            "error": {"code": -32025, "message": "the store is unavailable", "data": {"op": "x"}}
        }
        with pytest.raises(client.ServiceRefusalError) as raised:
            asyncio.run(
                client.KnowledgeClient(_Answering(answered), Path("/x")).call(  # type: ignore[arg-type]
                    "knowledge_list", {}
                )
            )
        assert raised.value.code == -32025
        assert raised.value.data == {"op": "x"}
        assert raised.value.disposition is Disposition.FAILED

    def test_a_response_that_is_neither_is_a_defect_in_the_service(self) -> None:
        """Not a refusal: nothing the caller sends differently fixes a result that is not an
        object, so it must not be rendered as one."""
        with pytest.raises(TypeError, match="answered with list, not an object"):
            asyncio.run(
                client.KnowledgeClient(_Answering({"result": []}), Path("/x")).call(  # type: ignore[arg-type]
                    "knowledge_list", {}
                )
            )

    def test_a_result_without_the_expected_list_names_the_defect(self) -> None:
        """A `TypeError` here is a better report than a `KeyError` three frames later, and this is
        the one place that says which side is wrong: the service sent a shape no build of this
        client can read."""
        with pytest.raises(TypeError, match="carries no knowledge_bases list"):
            cli._entries({"knowledge_bases": "docs"})
        with pytest.raises(TypeError, match="holds str, not objects"):
            cli._entries({"knowledge_bases": ["docs"]})

    def test_an_unknown_code_is_reported_as_a_failure(self) -> None:
        """A build that meets a newer service must still print something: `disposition` cannot say
        what a caller might do about a rejection it cannot name, so it says the honest thing."""
        refusal = client.ServiceRefusalError(code=-31999, message="from the future", data={})
        assert refusal.disposition is Disposition.FAILED
        assert refusal.render() == "failed: from the future"
