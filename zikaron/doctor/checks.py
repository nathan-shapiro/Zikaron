"""The probes `zikaron doctor` runs, each returning a finding that names a remedy rather than a
symptom.

**The interpreter decision is why this command exists.** `distribution.md` supports two acquisition
paths — a uv-managed interpreter and the host's own — and the second can be built in ways that make
Zikaron unrunnable. Each of those arrives, unprompted, as something a user cannot act on: a bare
`AttributeError` on `enable_load_extension`, an `OperationalError` on a `CREATE VIRTUAL TABLE`, or
an MCP server that starts and dies. A probe run on request turns each into a sentence naming what to
change.

**One row reports rather than checks.** The linked SQLite version is the axis no seam can absorb —
3.45.1 against 3.53.1 between two builds on one machine — and there is no correct value to compare
against, so stating it is the whole contribution.

**Probed with `sqlite3` directly rather than through the store.** These questions are about the
interpreter, and routing them through `aiosqlite` would make a failure of the probe
indistinguishable from a failure of the thing probed.
"""

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from zikaron.core.errors import ZikaronError
from zikaron.core.indexing.acquisition import verify
from zikaron.core.indexing.model_cache import resolved_model_cache_dir, snapshot_dir
from zikaron.core.indexing.model_pin import PINNED_ARTIFACTS, PinnedArtifact
from zikaron.service import paths, security
from zikaron.service.asyncio_compat import interpreter_version

#: Any width: `vec0` fixes a column's width at `CREATE` time, and this table is discarded. What is
#: under test is that the extension loaded and registered its module, which a bare import does not
#: establish — the probe note's own distinction.
_PROBE_VECTOR_WIDTH: Final = 4


class Outcome(StrEnum):
    """Whether a row can fail. `REPORTED` cannot, which is a property of the row not of the run."""

    PASSED = "ok"
    FAILED = "FAIL"
    REPORTED = "--"


@dataclass(frozen=True)
class Finding:
    """One row of the report.

    `remedy` is what separates this command from a traceback, so it is required on a failure and
    absent otherwise — `test_doctor.py` asserts both halves rather than leaving it to review.
    """

    name: str
    outcome: Outcome
    detail: str
    remedy: str | None = None

    def __post_init__(self) -> None:
        if (self.outcome is Outcome.FAILED) != (self.remedy is not None):
            raise ValueError(f"{self.name}: a failure names a remedy and nothing else carries one")


def _passed(name: str, detail: str) -> Finding:
    return Finding(name=name, outcome=Outcome.PASSED, detail=detail)


def _failed(name: str, detail: str, remedy: str) -> Finding:
    return Finding(name=name, outcome=Outcome.FAILED, detail=detail, remedy=remedy)


def check_extension_loading() -> Finding:
    """Whether this interpreter's `sqlite3` was built with extension loading at all.

    Absent on the python.org macOS builds and in some conda distributions, where it otherwise
    surfaces as an `AttributeError` from deep inside a store open.
    """
    name = "sqlite extension loading"
    with sqlite3.connect(":memory:") as connection:
        if not hasattr(connection, "enable_load_extension"):
            return _failed(
                name,
                "this interpreter's sqlite3 was built without it",
                "install Python through `uv python install`, which builds it in; a python.org "
                "macOS build or a conda interpreter will not work",
            )
    return _passed(name, "available")


def check_fts5() -> Finding:
    """Whether the linked SQLite carries FTS5, which the lexical arm is built on."""
    name = "sqlite FTS5"
    with sqlite3.connect(":memory:") as connection:
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5 (body)")
        except sqlite3.OperationalError as error:
            return _failed(
                name,
                f"the linked SQLite does not provide it: {error}",
                "install Python through `uv python install`; a SQLite built without "
                "SQLITE_ENABLE_FTS5 cannot run the lexical arm",
            )
    return _passed(name, "available")


def check_sqlite_vec() -> Finding:
    """Whether `sqlite-vec` loads *and registers its module*.

    A bare import proves the package is installed and nothing about whether the shared object
    loads into this SQLite, so the probe creates a real `vec0` table.
    """
    name = "sqlite-vec"
    remedy = (
        "reinstall zikaron so `sqlite-vec` matches this platform; on macOS check that the "
        "interpreter and the wheel are both arm64"
    )
    try:
        import sqlite_vec  # noqa: PLC0415
    except ImportError as error:
        # Caught rather than allowed to propagate: an absent dependency is exactly the state this
        # command exists to report, and a traceback out of the reporter is the outcome it replaces.
        return _failed(name, f"not installed: {error}", remedy)
    with sqlite3.connect(":memory:") as connection:
        if not hasattr(connection, "enable_load_extension"):
            return _failed(name, "not probed: extension loading is unavailable", remedy)
        connection.enable_load_extension(True)
        try:
            connection.load_extension(sqlite_vec.loadable_path())
            connection.execute(
                f"CREATE VIRTUAL TABLE probe USING vec0 (embedding float[{_PROBE_VECTOR_WIDTH}])"
            )
        except (sqlite3.OperationalError, OSError) as error:
            return _failed(name, f"present but would not load: {error}", remedy)
        finally:
            connection.enable_load_extension(False)
    return _passed(name, "loads, and registers vec0")


def check_model_cache(pin: PinnedArtifact, *, cache_dir: Path) -> Finding:
    """Whether the pinned artefact is on disk and hashes to what this release pins.

    **Absent is a pass.** There is no install-time prefetch, so a stranger's first run of this
    command finds no model at all — and a non-zero exit before anything is wrong is worse than no
    command. A cache holding only some *other* revision is the absent case, not a mismatch: nothing
    is wrong with bytes this release does not claim.
    """
    name = f"model cache ({pin.model_name})"
    snapshot = snapshot_dir(cache_dir, repo_id=pin.repo_id, revision=pin.revision)
    if not snapshot.is_dir():
        return _passed(name, f"not yet fetched; fetched on first service start, into {cache_dir}")
    # The acquisition path's own walk, not a second one: two implementations of "are these the
    # pinned bytes" are two answers that can disagree the day either changes.
    checked = verify(pin, snapshot)
    if not checked.complete():
        faults = []
        if checked.absent:
            faults.append(f"{', '.join(checked.absent)} missing")
        if checked.wrong:
            faults.append(f"{', '.join(checked.wrong)} not matching the pinned digests")
        # **Two faults, two remedies, and the difference is what the service will do about each.**
        # A start fills files that are *absent* and verifies what it fetched. It does nothing about
        # a file that is present with wrong bytes — a warm start checks presence only — so telling
        # a user to start the service there sends them round a loop that cannot repair, and then
        # blames the source for what is their disk. Removing the snapshot is what makes the next
        # start re-acquire down the path that verifies.
        return _failed(
            name,
            f"at revision {pin.revision}, with {'; '.join(faults)}",
            (
                "start the service, which fetches the missing files and verifies them"
                if not checked.wrong
                else f"remove {snapshot} and start the service, which re-acquires and verifies; if "
                "it then refuses naming the same file, the source is serving something else and "
                "upgrading zikaron is what carries a new pin"
            ),
        )
    return _passed(
        name, f"present at {pin.revision} under {cache_dir}, {len(pin.digests)} files verified"
    )


def check_socket_path(*, store_dir: Path, environ: Mapping[str, str], platform: str) -> Finding:
    """Whether the socket this machine would derive fits the platform's `sun_path`.

    The refusal is the one `service.paths` already raises, so this reports the same sentence the
    MCP server would die with — on a channel a user can reach before meeting it that way.
    """
    name = "socket path length"
    runtime = paths.runtime_dir(
        xdg_runtime_dir=environ.get("XDG_RUNTIME_DIR"), uid=security.current_uid()
    )
    try:
        socket = paths.socket_path(runtime, store_dir.resolve(), platform=platform)
    except ZikaronError as refusal:
        return _failed(name, refusal.detail(), str(refusal.data["expected"]))
    return _passed(name, f"{socket} fits {paths.sun_path_size(platform)} bytes")


def report_sqlite_version() -> Finding:
    """The linked SQLite beside the interpreter that linked it. Never a failure."""
    return Finding(
        name="sqlite version",
        outcome=Outcome.REPORTED,
        detail=f"{sqlite3.sqlite_version} linked by Python {interpreter_version()}",
    )


def run_all(*, store_dir: Path, environ: Mapping[str, str], platform: str) -> Sequence[Finding]:
    """Every check and the one report, in the order `distribution.md` states them."""
    cache_dir = resolved_model_cache_dir()
    return (
        check_extension_loading(),
        check_fts5(),
        check_sqlite_vec(),
        *(check_model_cache(pin, cache_dir=cache_dir) for pin in PINNED_ARTIFACTS.values()),
        check_socket_path(store_dir=store_dir, environ=environ, platform=platform),
        report_sqlite_version(),
    )
