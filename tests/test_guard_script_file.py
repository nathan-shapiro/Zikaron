"""Row 6's one file read fails open where `design/edit-guards.md` §8.1 cannot reach.

§8.1 holds every reading edge a file on disk can show — a symlink, a FIFO, a directory, the size
limit, an undecodable byte. Two more need the filesystem to misbehave between two calls, so they
are made to here: an error after the file is open, and a file that grows past the limit between
the size check and the read.
"""

import os
from pathlib import Path

import pytest

from zikaron.guard.script_file import MAXIMUM_BYTES, read_script


def _read_with_fstat(path: Path, fstat: object, monkeypatch: pytest.MonkeyPatch) -> str | None:
    """`read_script(path)` with `os.fstat` replaced for that one call only."""
    with monkeypatch.context() as patched:
        patched.setattr(os, "fstat", fstat)
        return read_script(str(path))


def test_an_error_after_the_open_reads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fix.py"
    script.write_text("open('f', 'w')\n", encoding="utf-8")

    def failing(descriptor: int) -> os.stat_result:
        raise OSError(descriptor, "stat failed")

    assert _read_with_fstat(script, failing, monkeypatch) is None


def test_a_file_grown_past_the_limit_after_its_size_was_checked_reads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "fix.py"
    script.write_bytes(b"#" * (MAXIMUM_BYTES + 1))
    fields = list(script.stat()[:10])
    fields[6] = 1  # st_size, as the size check saw it before the file grew
    reported = os.stat_result(fields)

    def stale(descriptor: int) -> os.stat_result:
        del descriptor
        return reported

    assert _read_with_fstat(script, stale, monkeypatch) is None
