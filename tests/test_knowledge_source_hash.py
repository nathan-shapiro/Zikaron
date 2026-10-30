"""What a linked document's source hashes to, measured against git itself.

`knowledge-index.md` §7.7 ("The hash") is normative. The oracle throughout is `git add` and the id
it stores: the hash must be git's object id for the source, filters and all, whatever directory
the Zikaron root is in. Where git is meant to be absent it is taken off `PATH`; where it is meant to
misbehave a script stands in for it; the in-process read is exercised directly.

Each test isolates git from the machine's own configuration, so a `core.autocrlf` on the machine
running the suite cannot change an answer.
"""

import asyncio
import hashlib
import os
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.loop_lateness import loop_lateness
from zikaron.core.knowledge import source_hash
from zikaron.core.knowledge.source_hash import (
    HashBudget,
    Hashed,
    Source,
    SourceState,
    hash_sources,
    state_of,
)

_SHA1_WIDTH = 40
_SHA256_WIDTH = 64


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 — a fixed argv built from this file's own literals.
        ["git", *arguments],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
    return root


def _stored(repository: Path, relative: str) -> str:
    """The id `git add` stores for `relative`, which is what the hash must equal."""
    _git(repository, "add", "--", relative)
    return _git(repository, "rev-parse", f":{relative}")


def _raw_blob(content: bytes, width: int = _SHA1_WIDTH) -> str:
    digest = hashlib.sha256() if width == _SHA256_WIDTH else hashlib.sha1(usedforsecurity=False)
    digest.update(b"blob %d\0" % len(content) + content)
    return digest.hexdigest()


async def _hash(
    root: Path, *declared: str, width: int = _SHA1_WIDTH, budget: HashBudget | None = None
) -> dict[str, Hashed]:
    sources = [Source(path=path, width=width) for path in declared]
    answered = await hash_sources(root, sources, budget=budget or HashBudget())
    return {source.path: hashed for source, hashed in answered.items()}


def _without_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "no-git-here"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def _fake_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str, *, executable: bool
) -> None:
    directory = tmp_path / "fake-git"
    directory.mkdir(exist_ok=True)
    script = directory / "git"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755 if executable else 0o644)
    monkeypatch.setenv("PATH", str(directory))


class TestEveryState:
    async def test_fresh_is_the_id_git_add_stores_with_its_filters(self, repository: Path) -> None:
        (repository / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        declared = _stored(repository, "a.txt")
        hashed = (await _hash(repository, "a.txt"))["a.txt"]
        assert hashed == declared
        assert hashed != _raw_blob(b"one\r\ntwo\r\n"), "the end-of-line filter was applied"
        assert state_of(declared, hashed) is SourceState.FRESH

    async def test_changed(self, repository: Path) -> None:
        (repository / "a.txt").write_bytes(b"one\n")
        declared = _stored(repository, "a.txt")
        (repository / "a.txt").write_bytes(b"one, edited\n")
        hashed = (await _hash(repository, "a.txt"))["a.txt"]
        assert state_of(declared, hashed) is SourceState.CHANGED

    async def test_missing(self, repository: Path) -> None:
        assert (await _hash(repository, "gone.txt"))["gone.txt"] is SourceState.MISSING

    async def test_a_dangling_link_is_missing(self, repository: Path) -> None:
        (repository / "link.txt").symlink_to(repository / "nowhere.txt")
        assert (await _hash(repository, "link.txt"))["link.txt"] is SourceState.MISSING

    async def test_a_path_through_a_file_is_missing(self, repository: Path) -> None:
        (repository / "a.txt").write_bytes(b"x\n")
        assert (await _hash(repository, "a.txt/b.txt"))["a.txt/b.txt"] is SourceState.MISSING

    async def test_a_directory_is_unverifiable(self, repository: Path) -> None:
        (repository / "dir").mkdir()
        assert (await _hash(repository, "dir"))["dir"] is SourceState.UNVERIFIABLE

    async def test_a_fifo_is_unverifiable_and_never_read(self, repository: Path) -> None:
        os.mkfifo(repository / "pipe")
        assert (await _hash(repository, "pipe"))["pipe"] is SourceState.UNVERIFIABLE

    async def test_a_source_over_the_size_cap_is_unverifiable(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(source_hash, "LINK_SOURCE_MAX_BYTES", 4)
        (repository / "a.txt").write_bytes(b"too long\n")
        assert (await _hash(repository, "a.txt"))["a.txt"] is SourceState.UNVERIFIABLE

    def test_a_declared_hash_of_another_width_is_unverifiable(self) -> None:
        assert state_of("a" * _SHA256_WIDTH, "b" * _SHA1_WIDTH) is SourceState.UNVERIFIABLE

    async def test_outside_any_repository_it_is_the_raw_blob(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "a.txt").write_bytes(b"one\r\n")
        assert (await _hash(plain, "a.txt"))["a.txt"] == _raw_blob(b"one\r\n")

    @pytest.mark.parametrize("width", [_SHA1_WIDTH, _SHA256_WIDTH])
    async def test_without_git_it_is_the_raw_blob_at_the_declared_width(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int
    ) -> None:
        (repository / "a.txt").write_bytes(b"one\r\n")
        _without_git(monkeypatch, tmp_path)
        hashed = (await _hash(repository, "a.txt", width=width))["a.txt"]
        assert hashed == _raw_blob(b"one\r\n", width)

    async def test_a_root_git_declines_for_its_ownership_answers_in_the_raw_blob_form(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"one\r\n")
        monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
        assert (await _hash(repository, "a.txt"))["a.txt"] == _raw_blob(b"one\r\n")


class TestTheRootIsBelowTheRepositorysTop:
    async def test_an_attribute_anchored_to_the_root_and_a_same_named_file_at_the_top(
        self, repository: Path
    ) -> None:
        """`--stdin-paths` would resolve `a.txt` against the top and hash the other file."""
        (repository / ".gitattributes").write_text("/sub/*.txt text eol=lf\n", encoding="utf-8")
        root = repository / "sub"
        root.mkdir()
        (root / "a.txt").write_bytes(b"inner\r\n")
        (repository / "a.txt").write_bytes(b"outer\r\n")
        assert (await _hash(root, "a.txt"))["a.txt"] == _stored(repository, "sub/a.txt")

    async def test_a_source_reached_by_dot_dot_is_judged_by_its_own_path(
        self, repository: Path
    ) -> None:
        """Given as written, `sub/../top.txt` would take `sub/.gitattributes` with it."""
        (repository / ".gitattributes").unlink()
        root = repository / "sub"
        root.mkdir()
        (root / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
        (repository / "top.txt").write_bytes(b"raw\r\n")
        stored = _stored(repository, "top.txt")
        assert stored == _raw_blob(b"raw\r\n")
        assert (await _hash(root, "../top.txt"))["../top.txt"] == stored

    async def test_a_dot_dot_after_a_directory_that_does_not_exist_is_missing(
        self, repository: Path
    ) -> None:
        """A lexical collapse would name `a.txt`, which exists; the kernel answers no such file."""
        (repository / "a.txt").write_bytes(b"x\n")
        declared = "gone/../a.txt"
        assert (await _hash(repository, declared))[declared] is SourceState.MISSING


class TestABatch:
    async def test_a_source_removed_between_its_check_and_git_leaves_the_rest_hashed(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a.txt", "b.txt", "c.txt"):
            (repository / name).write_bytes(f"{name}\n".encode())
        real_git = source_hash._git_hash

        def _after_removing_b(root: Path, reals: list[str], timeout: float) -> object:
            (repository / "b.txt").unlink(missing_ok=True)
            return real_git(root, reals, timeout)

        monkeypatch.setattr(source_hash, "_git_hash", _after_removing_b)
        hashed = await _hash(repository, "a.txt", "b.txt", "c.txt")
        assert hashed["b.txt"] is SourceState.UNVERIFIABLE
        assert hashed["a.txt"] == _raw_blob(b"a.txt\n")
        assert hashed["c.txt"] == _raw_blob(b"c.txt\n")

    async def test_a_fifo_at_its_check_leaves_the_rest_hashed(self, repository: Path) -> None:
        os.mkfifo(repository / "pipe")
        (repository / "a.txt").write_bytes(b"a\n")
        hashed = await _hash(repository, "pipe", "a.txt")
        assert hashed["pipe"] is SourceState.UNVERIFIABLE
        assert hashed["a.txt"] == _raw_blob(b"a\n")

    async def test_an_unreadable_file_ranked_first_leaves_the_rest_hashed(
        self, repository: Path
    ) -> None:
        locked = repository / "locked.txt"
        locked.write_bytes(b"secret\n")
        locked.chmod(0)
        if os.access(locked, os.R_OK):
            pytest.skip("this process reads files whatever their mode, as root does")
        (repository / "a.txt").write_bytes(b"a\n")
        try:
            hashed = await _hash(repository, "locked.txt", "a.txt")
        finally:
            locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert hashed["locked.txt"] is SourceState.UNVERIFIABLE
        assert hashed["a.txt"] == _raw_blob(b"a\n")

    async def test_a_required_clean_filter_that_fails_leaves_the_rest_hashed_through_git(
        self, repository: Path
    ) -> None:
        (repository / ".gitattributes").write_text(
            "*.txt text eol=lf\n*.bin filter=x\n", encoding="utf-8"
        )
        _git(repository, "config", "filter.x.clean", "false")
        _git(repository, "config", "filter.x.required", "true")
        (repository / "bad.bin").write_bytes(b"\x00\x01")
        (repository / "ok.txt").write_bytes(b"ok\r\n")
        hashed = await _hash(repository, "bad.bin", "ok.txt")
        assert hashed["bad.bin"] is SourceState.UNVERIFIABLE
        assert hashed["ok.txt"] == _stored(repository, "ok.txt")

    async def test_a_git_that_refuses_everything_makes_everything_unverifiable(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"a\n")
        (repository / "b.txt").write_bytes(b"b\n")
        _fake_git(monkeypatch, tmp_path, "exit 1", executable=True)
        hashed = await _hash(repository, "a.txt", "b.txt")
        assert set(hashed.values()) == {SourceState.UNVERIFIABLE}

    async def test_a_git_that_is_not_executable_gives_the_in_process_form(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"one\r\n")
        _fake_git(monkeypatch, tmp_path, "exit 1", executable=False)
        assert (await _hash(repository, "a.txt"))["a.txt"] == _raw_blob(b"one\r\n")

    async def test_a_step_that_raises_leaves_every_source_unverifiable(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"a\n")

        def _broken(*_arguments: object) -> object:
            raise RuntimeError("a defect in the check")

        monkeypatch.setattr(source_hash, "_checked", _broken)
        assert (await _hash(repository, "a.txt"))["a.txt"] is SourceState.UNVERIFIABLE

    async def test_a_later_step_that_raises_leaves_what_the_check_answered(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"a\n")
        _without_git(monkeypatch, tmp_path)

        def _broken(*_arguments: object) -> object:
            raise RuntimeError("a defect in the in-process hash")

        monkeypatch.setattr(source_hash, "_blob_hash", _broken)
        hashed = await _hash(repository, "a.txt", "gone.txt")
        assert hashed == {"a.txt": SourceState.UNVERIFIABLE, "gone.txt": SourceState.MISSING}


class TestTheBudget:
    async def test_a_check_that_blocks_past_the_budget_is_abandoned_and_the_loop_stays_free(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A regular file on a hung mount blocks its thread in the kernel; the search must not."""
        released = threading.Event()

        def _hung(*_arguments: object) -> object:
            released.wait(timeout=10)
            raise AssertionError("never reached in time")

        monkeypatch.setattr(source_hash, "_checked", _hung)
        ticks = 0

        async def _tick() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(_tick())
        async with loop_lateness() as lateness:
            started = time.monotonic()
            try:
                # The ticker's count cannot be corrected for lateness — a check that blocked the
                # loop would be counted as lateness too, and the ceiling below no longer sees one —
                # so the margin is the defence: a hundred turns against five, which a stall must
                # eat nineteen-twentieths of the budget to cross.
                hashed = await _hash(repository, "a.txt", budget=HashBudget(1.0))
            finally:
                ticker.cancel()
                released.set()
            elapsed = time.monotonic() - started
        assert hashed["a.txt"] is SourceState.UNVERIFIABLE
        assert elapsed - lateness.seconds < 2, (elapsed, lateness)
        assert ticks > 5, "the event loop went on serving while the check was blocked"

    async def test_a_spent_budget_runs_no_git(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spent by the check, so the budget is still open when the call starts and shut at git.

        `_git_hash` is reached on a thread whose exceptions this path swallows, so a raising
        sentinel could not fail the test; it records the call instead.
        """
        (repository / "a.txt").write_bytes(b"a\n")

        class _SpentByTheCheck(HashBudget):
            spent = False

            def remaining(self) -> float:
                return 0.0 if self.spent else 5.0

        budget = _SpentByTheCheck()
        real_check = source_hash._checked

        def _check_then_spend(root: Path, declared: str) -> object:
            checked = real_check(root, declared)
            budget.spent = True
            return checked

        git_ran = threading.Event()

        def _git(*_arguments: object) -> object:
            git_ran.set()
            raise AssertionError("unreachable")

        monkeypatch.setattr(source_hash, "_checked", _check_then_spend)
        monkeypatch.setattr(source_hash, "_git_hash", _git)
        hashed = await _hash(repository, "a.txt", budget=budget)
        assert hashed["a.txt"] is SourceState.UNVERIFIABLE
        assert not git_ran.wait(timeout=0.5), "git ran after the budget was spent"

    async def test_every_step_runs_on_a_daemon_thread(
        self, repository: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pool's workers are joined without bound at exit; an abandoned daemon thread is not."""
        (repository / "a.txt").write_bytes(b"a\n")
        seen: list[threading.Thread] = []
        real_check, real_git = source_hash._checked, source_hash._git_hash

        def _check(root: Path, declared: str) -> object:
            seen.append(threading.current_thread())
            return real_check(root, declared)

        def _git_call(root: Path, reals: list[str], timeout: float) -> object:
            seen.append(threading.current_thread())
            return real_git(root, reals, timeout)

        monkeypatch.setattr(source_hash, "_checked", _check)
        monkeypatch.setattr(source_hash, "_git_hash", _git_call)
        await _hash(repository, "a.txt")
        assert len(seen) == 2
        assert all(thread.daemon for thread in seen)
        assert all(thread is not threading.main_thread() for thread in seen)

    async def test_a_git_that_hangs_is_given_up_on_at_the_budget(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"a\n")
        sleep = shutil.which("sleep")
        assert sleep is not None
        # Not corrected for lateness: a git waited for on the loop rather than on its own thread
        # would be lateness, and a subtraction would hide that wait. So git hangs for twenty
        # seconds against a ceiling of five, and a search that gives it up at the budget answers
        # in about a third of one.
        _fake_git(monkeypatch, tmp_path, f"exec {sleep} 20", executable=True)
        started = time.monotonic()
        hashed = await _hash(repository, "a.txt", budget=HashBudget(0.3))
        elapsed = time.monotonic() - started
        assert hashed["a.txt"] is SourceState.UNVERIFIABLE
        assert 0.25 < elapsed < 5, "it waited for git until the budget, and no longer"

    async def test_a_step_that_finishes_after_it_was_given_up_on_hands_nothing_back(
        self,
    ) -> None:
        """Its result reaches a future the search stopped waiting on, which must stay as it is."""
        loop = asyncio.get_running_loop()
        errors: list[dict[str, object]] = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        released = threading.Event()

        def _late() -> str:
            released.wait(timeout=10)
            return "late"

        with pytest.raises(source_hash._Abandoned):
            await source_hash._on_a_daemon_thread(_late, HashBudget(0.05))
        released.set()
        await asyncio.sleep(0.2)
        assert errors == []


class TestAGitThatMisbehaves:
    async def test_one_that_succeeds_printing_fewer_ids_than_paths_leaves_the_rest_unverifiable(
        self, repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (repository / "a.txt").write_bytes(b"a\n")
        _fake_git(monkeypatch, tmp_path, "exit 0", executable=True)
        async with loop_lateness() as lateness:
            started = time.monotonic()
            assert (await _hash(repository, "a.txt"))["a.txt"] is SourceState.UNVERIFIABLE
            elapsed = time.monotonic() - started
        assert elapsed - lateness.seconds < 1, (
            f"git was run again over a batch it had answered: {elapsed:.3f}s, {lateness}"
        )


class TestTheInProcessRead:
    """The read is of a descriptor that is checked, since the path may change after the check."""

    def test_a_source_gone_before_the_read_is_missing(self, tmp_path: Path) -> None:
        assert source_hash._blob_hash(str(tmp_path / "gone"), _SHA1_WIDTH) is SourceState.MISSING

    def test_a_fifo_swapped_in_after_the_check_is_refused_without_blocking(
        self, tmp_path: Path
    ) -> None:
        os.mkfifo(tmp_path / "pipe")
        hashed = source_hash._blob_hash(str(tmp_path / "pipe"), _SHA1_WIDTH)
        assert hashed is SourceState.UNVERIFIABLE

    def test_a_read_that_fails_is_unverifiable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.txt").write_bytes(b"a\n")

        def _failing(_descriptor: int) -> os.stat_result:
            raise OSError("an I/O error")

        monkeypatch.setattr(os, "fstat", _failing)
        hashed = source_hash._blob_hash(str(tmp_path / "a.txt"), _SHA1_WIDTH)
        assert hashed is SourceState.UNVERIFIABLE

    def test_a_file_that_grew_past_the_cap_after_its_stat_is_unverifiable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.txt").write_bytes(b"longer than four\n")
        monkeypatch.setattr(source_hash, "LINK_SOURCE_MAX_BYTES", 4)
        real_fstat = os.fstat

        def _as_it_was(descriptor: int) -> os.stat_result:
            fields = list(real_fstat(descriptor))
            fields[stat.ST_SIZE] = 1
            return os.stat_result(fields)

        monkeypatch.setattr(os, "fstat", _as_it_was)
        hashed = source_hash._blob_hash(str(tmp_path / "a.txt"), _SHA1_WIDTH)
        assert hashed is SourceState.UNVERIFIABLE
