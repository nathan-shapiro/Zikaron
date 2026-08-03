"""`zikaron.hook.failure.record_failure`: one line to `hook.log`, direct file write, mode 0600.

`architecture.md` §"Degraded modes" and §"Filesystem security" are normative.
"""

import os
import stat
from pathlib import Path

from zikaron.hook.failure import record_failure


def test_creates_the_file_at_mode_0600(tmp_path: Path) -> None:
    log_path = tmp_path / "hook.log"
    record_failure(log_path, "transport")
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600


def test_appends_one_line_naming_the_kind(tmp_path: Path) -> None:
    log_path = tmp_path / "hook.log"
    record_failure(log_path, "transport")
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "transport" in lines[0]


def test_appends_the_code_when_one_is_given(tmp_path: Path) -> None:
    log_path = tmp_path / "hook.log"
    record_failure(log_path, "store_busy", code=-32020)
    line = log_path.read_text(encoding="utf-8").splitlines()[0]
    assert "store_busy" in line
    assert "-32020" in line


def test_omits_any_code_marker_when_none_is_given(tmp_path: Path) -> None:
    log_path = tmp_path / "hook.log"
    record_failure(log_path, "reindexing")
    line = log_path.read_text(encoding="utf-8").splitlines()[0]
    # No stray trailing token where a code would have gone.
    assert line.split() == [line.split()[0], "reindexing"]


def test_two_calls_append_two_lines_rather_than_overwriting(tmp_path: Path) -> None:
    log_path = tmp_path / "hook.log"
    record_failure(log_path, "transport")
    record_failure(log_path, "store_busy", code=-32020)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "transport" in lines[0]
    assert "store_busy" in lines[1]


def test_an_existing_files_mode_is_not_altered_on_append(tmp_path: Path) -> None:
    """`os.open`'s `mode` argument only applies to a newly created file — POSIX `open(2)` ignores
    it when `O_CREAT` finds the path already there. An operator-widened `hook.log` (or one this
    process itself already created at 0600) must keep whatever mode it already has rather than
    being silently tightened or loosened by every single append.
    """
    log_path = tmp_path / "hook.log"
    log_path.touch()
    log_path.chmod(0o644)
    record_failure(log_path, "transport")
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o644


def test_creates_the_parent_directory_when_it_does_not_exist(tmp_path: Path) -> None:
    """The most common way to reach `record_failure` at all is a service that has never run for
    this project — the ordinary first-ever session, where `.zikaron/` does not exist yet either.
    An earlier version of this function silently lost the record in exactly this case, since
    `os.open`'s own `ENOENT` on a missing parent was swallowed by the same catch-all this
    function's own docstring describes for a genuine last-resort failure — making the one
    failure this function exists to make durable the one case guaranteed not to be.
    """
    missing_dir_log = tmp_path / "does-not-exist" / "hook.log"
    record_failure(missing_dir_log, "transport")
    assert missing_dir_log.exists()
    assert "transport" in missing_dir_log.read_text(encoding="utf-8")
    parent_mode = stat.S_IMODE(missing_dir_log.parent.stat().st_mode)
    assert parent_mode == 0o700


def test_never_raises_when_given_a_directory_as_the_log_path(tmp_path: Path) -> None:
    directory_as_log = tmp_path / "a-directory"
    directory_as_log.mkdir()
    record_failure(directory_as_log, "transport")  # must not raise


def test_a_restrictive_process_umask_does_not_leave_the_file_unreadable(tmp_path: Path) -> None:
    """The exact fix for the umask claim an earlier version of this module's own docstring made
    incorrectly: `os.open`'s `mode` argument is masked by the process umask like any other POSIX
    `open(2)` call, so a `0600` process umask — legal, if unusual — would leave a file created
    with `mode=0o600` at `0000` unless the mode is forced afterward with `os.fchmod`. Verified
    directly against a real restrictive umask, restored in `finally` regardless of outcome so
    this test cannot leak a process-wide umask change into whichever test runs after it.
    """
    log_path = tmp_path / "hook.log"
    previous_umask = os.umask(0o600)
    try:
        record_failure(log_path, "transport")
    finally:
        os.umask(previous_umask)
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600


def test_never_raises_when_the_parent_would_require_following_a_symlink(tmp_path: Path) -> None:
    """`ensure_store_dir` raises `ZikaronError` — a plain `Exception`, not an `OSError` subclass
    — for a `.zikaron` reached through a symlink, per `architecture.md` §"Filesystem security":
    "refuse a store reached through a symlinked `.zikaron`." That failure must be swallowed here
    exactly like any other, and specifically must not propagate merely because it is not an
    `OSError`.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    symlinked_zikaron = tmp_path / "project" / ".zikaron"
    symlinked_zikaron.parent.mkdir()
    symlinked_zikaron.symlink_to(real_dir)
    log_path = symlinked_zikaron / "hook.log"
    record_failure(log_path, "transport")  # must not raise
