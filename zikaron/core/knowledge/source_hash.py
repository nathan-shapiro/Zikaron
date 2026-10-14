"""What a linked document's source hashes to now, under one search's hashing budget.

`knowledge-index.md` §7.7 ("The hash") is normative. The hash is git's object id: `git hash-object
-- <path>…`, run with the Zikaron root as its working directory, each source passed as an argument
by its absolute real path, so git applies the clean and end-of-line filters the source's own path
calls for and the id matches git's index. Where git is not installed, the same blob form is computed
in-process, which is what git itself prints outside a work tree.

**Only a regular file this process may read, no larger than `LINK_SOURCE_MAX_BYTES`, is hashed.**
Each source is first resolved strictly — symlinks first, the way the kernel resolves it — and
checked; anything else answers `missing` or `unverifiable` and never reaches a hashing call.

**Nothing here may hold a search past its budget, or the service past its exit.** Every step — the
check over a batch, each git call, the in-process reads — runs on a daemon thread of its own and is
abandoned once the budget is spent, since a regular file on a hung network mount blocks a thread in
the kernel and a thread cannot be killed. A pool would not do: its workers are joined without bound
when the interpreter exits (`coding-standards.md` §6).

**Nothing raised on this path leaves it.** A source git cannot hash, or one whose step outlasts the
budget, is `unverifiable`; a step that raises makes every source it was given `unverifiable`, and
the search goes on answering.
"""

import asyncio
import contextlib
import errno
import functools
import hashlib
import os
import re
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

#: The largest source that is hashed, generous because a summary of a large document is one of the
#: uses; the hashing budget, not this, bounds a search's worst case.
LINK_SOURCE_MAX_BYTES: Final = 64 * 1024 * 1024

#: All the hashing one search does, across every corpus, from its first call.
LINK_HASH_TIMEOUT_SECONDS: Final = 5.0

#: A resolution or `stat` failing with one of these found nothing at the path; any other failure is
#: a path that cannot be checked. Classified by number because the exception class raised for a
#: given failure is not the same across the interpreters this project supports.
_NOTHING_THERE: Final = frozenset({errno.ENOENT, errno.ENOTDIR})

_GIT_ID: Final = re.compile(rb"[0-9a-f]{40}|[0-9a-f]{64}")

#: The width, in hexadecimal digits, of a SHA-256 object id. Any other declared width is SHA-1's.
_SHA256_WIDTH: Final = 64


class SourceState(StrEnum):
    """What a search reports about a linked document's source."""

    FRESH = "fresh"
    CHANGED = "changed"
    MISSING = "missing"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class Source:
    """One source to hash: its path as declared, relative to the Zikaron root, and the width of the
    hash it was declared with — which is the width the in-process form computes."""

    path: str
    width: int


#: A source's id, or the state that answers for it when no id could be had.
type Hashed = str | SourceState


class HashBudget:
    """The time one search may spend hashing, across every corpus, counted from its first call."""

    def __init__(self, seconds: float | None = None) -> None:
        self._seconds = LINK_HASH_TIMEOUT_SECONDS if seconds is None else seconds
        self._deadline: float | None = None

    def remaining(self) -> float:
        """Seconds left, starting the budget if nothing has spent it yet."""
        if self._deadline is None:
            self._deadline = time.monotonic() + self._seconds
        return max(0.0, self._deadline - time.monotonic())


class _Abandoned(Exception):  # noqa: N818 — a step given up on, not an error in it.
    """A step outlasted the budget and was left to finish on its own."""


async def _on_a_daemon_thread[T](work: Callable[[], T], budget: HashBudget) -> T:
    """Run `work` on a daemon thread of its own, waiting for it no longer than the budget.

    Its result is handed back through the event loop only while the search still waits for it and
    the loop is still open; past the budget the thread is abandoned and dies with the process.

    Raises:
        _Abandoned: the budget ran out first.
        Exception: whatever `work` raised.
    """
    loop = asyncio.get_running_loop()
    handed: asyncio.Future[T] = loop.create_future()

    def _succeed(value: T) -> None:
        if not handed.done():
            handed.set_result(value)

    def _fail(error: Exception) -> None:
        if not handed.done():
            handed.set_exception(error)

    def _run() -> None:
        try:
            try:
                value = work()
            except Exception as raised:
                loop.call_soon_threadsafe(_fail, raised)
            else:
                loop.call_soon_threadsafe(_succeed, value)
        except RuntimeError:
            return  # The loop has closed: nobody is waiting.

    threading.Thread(target=_run, name="zikaron-source-hash", daemon=True).start()
    try:
        async with asyncio.timeout(budget.remaining()):
            return await handed
    except TimeoutError:
        raise _Abandoned from None


def _checked(root: Path, declared: str) -> str | SourceState:
    """`declared`'s absolute real path, if it names a regular file this process may hash."""
    try:
        real = os.path.realpath(root / declared, strict=True)
        found = Path(real).stat()
    except OSError as error:
        return SourceState.MISSING if error.errno in _NOTHING_THERE else SourceState.UNVERIFIABLE
    if (
        not stat.S_ISREG(found.st_mode)
        or found.st_size > LINK_SOURCE_MAX_BYTES
        or not os.access(real, os.R_OK)
    ):
        return SourceState.UNVERIFIABLE
    return real


class _NoGit(Exception):  # noqa: N818 — a fact about the machine, not an error in the caller.
    """Git could not be started at all: not installed, or not executable."""


def _git_hash(root: Path, reals: Sequence[str], timeout: float) -> tuple[int, list[str]]:
    """Run `git hash-object` over `reals` and return its exit status and the ids it printed.

    Raises:
        _NoGit: git could not be started.
        subprocess.TimeoutExpired: it did not finish in `timeout`; it has been killed.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — a fixed argument vector with no shell in it.
            ["git", "hash-object", "--", *reals],  # noqa: S607 — the operator's own git, from `PATH`.
            cwd=root,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except OSError as error:
        raise _NoGit from error
    printed = [line.decode("ascii") for line in completed.stdout.split() if _GIT_ID.fullmatch(line)]
    return completed.returncode, printed


def _blob_hash(real: str, width: int) -> Hashed:
    """The blob form git prints outside a work tree, read through a descriptor that is checked,
    never the path, so a FIFO swapped in after the check is refused at once."""
    try:
        descriptor = os.open(real, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as error:
        return SourceState.MISSING if error.errno in _NOTHING_THERE else SourceState.UNVERIFIABLE
    try:
        with os.fdopen(descriptor, "rb") as handle:
            found = os.fstat(handle.fileno())
            if not stat.S_ISREG(found.st_mode) or found.st_size > LINK_SOURCE_MAX_BYTES:
                return SourceState.UNVERIFIABLE
            content = handle.read(LINK_SOURCE_MAX_BYTES + 1)
    except OSError:
        return SourceState.UNVERIFIABLE
    if len(content) > LINK_SOURCE_MAX_BYTES:
        return SourceState.UNVERIFIABLE
    digest = hashlib.sha256() if width == _SHA256_WIDTH else hashlib.sha1(usedforsecurity=False)
    digest.update(b"blob %d\0" % len(content))
    digest.update(content)
    return digest.hexdigest()


async def _through_git(root: Path, reals: Sequence[str], budget: HashBudget) -> list[Hashed] | None:
    """Each real path's id through git, in order, or `None` where git could not be started.

    git stops at the first path it cannot hash and prints the ids before it, so the source at that
    position is `unverifiable` and git runs again over the rest, until the batch is done or the
    budget is spent.
    """
    answers: list[Hashed] = []
    while len(answers) < len(reals):
        rest = reals[len(answers) :]
        timeout = budget.remaining()
        if timeout <= 0:
            break
        try:
            status, printed = await _on_a_daemon_thread(
                functools.partial(_git_hash, root, rest, timeout), budget
            )
        except _NoGit:
            return None if not answers else [*answers, *[SourceState.UNVERIFIABLE] * len(rest)]
        except (_Abandoned, subprocess.TimeoutExpired):
            break
        answers.extend(printed[: len(rest)])
        if status != 0 and len(answers) < len(reals):
            answers.append(SourceState.UNVERIFIABLE)
        elif status == 0 and len(printed) < len(rest):
            break
    answers.extend([SourceState.UNVERIFIABLE] * (len(reals) - len(answers)))
    return answers


async def hash_sources(
    root: Path, sources: Sequence[Source], *, budget: HashBudget
) -> dict[Source, Hashed]:
    """Every source's id as git computes it now, or the state that answers for it.

    Args:
        root: the Zikaron root — the project directory holding `.zikaron/` — which the declared
            paths are relative to and git runs in.
        sources: what to hash, each once.
        budget: the search's hashing budget, which this spends from and shares with every other
            corpus the search reaches.
    """
    answered: dict[Source, Hashed] = dict.fromkeys(sources, SourceState.UNVERIFIABLE)
    if not sources or budget.remaining() <= 0:
        return answered
    # A defect in a step is a state of every source it was given, never a failed search: each of
    # those still holds the `unverifiable` it started with, and an earlier step's answers stand.
    with contextlib.suppress(Exception):
        checked = await _on_a_daemon_thread(
            lambda: [_checked(root, source.path) for source in sources], budget
        )
        hashable = []
        for source, outcome in zip(sources, checked, strict=True):
            if isinstance(outcome, SourceState):
                answered[source] = outcome
            else:
                hashable.append((source, outcome))
        if not hashable:
            return answered
        reals = [real for _source, real in hashable]
        through_git = await _through_git(root, reals, budget)
        if through_git is None:
            through_git = await _on_a_daemon_thread(
                lambda: [_blob_hash(real, source.width) for source, real in hashable], budget
            )
        for (source, _real), hashed in zip(hashable, through_git, strict=True):
            answered[source] = hashed
    return answered


def state_of(declared_blob: str, hashed: Hashed) -> SourceState:
    """A linked result's state, from the hash its document declared and its source's hash now."""
    if isinstance(hashed, SourceState):
        return hashed
    if len(hashed) != len(declared_blob):
        return SourceState.UNVERIFIABLE
    return SourceState.FRESH if hashed == declared_blob else SourceState.CHANGED
