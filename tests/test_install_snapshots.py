"""The tracked snapshot of what an install ships is what an install ships now, on both harnesses.

`tests/install_snapshots.py` says why the snapshot exists and how to re-render it after a
deliberate change.
"""

from pathlib import Path

from tests.install_snapshots import SNAPSHOT_ROOT, rendered, tracked
from zikaron.harness.spec import SPECS


def test_every_shipped_file_matches_its_snapshot_and_nothing_else_is_tracked() -> None:
    assert tracked() == rendered()


def test_the_snapshot_covers_every_harness() -> None:
    harnesses = {relative.split("/", 1)[0] for relative in tracked()}
    assert harnesses == {spec.harness.value for spec in SPECS.values()}


def test_no_snapshot_lies_under_a_dot_directory() -> None:
    """A path under `.claude/` or `.kiro/` is one a harness would load as its own."""
    for relative in tracked():
        assert not [part for part in Path(relative).parts if part.startswith(".")], relative


def test_the_snapshot_root_is_under_the_tests_tree() -> None:
    assert SNAPSHOT_ROOT.parts[-3:] == ("tests", "fixtures", "installed")
