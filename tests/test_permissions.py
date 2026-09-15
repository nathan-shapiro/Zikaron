"""`0700`/`0600` enforcement, checked against `architecture.md` §"Filesystem security"."""

import os
from pathlib import Path

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.store.permissions import (
    database_files,
    enforce_existing_store_permissions,
    enforce_store_file_mode,
    ensure_store_dir,
    restrictive_umask,
)


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_ensure_store_dir_creates_a_fresh_directory_at_0700(tmp_path: Path) -> None:
    target = tmp_path / ".zikaron"
    ensure_store_dir(target)
    assert target.is_dir()
    assert _mode(target) == 0o700


def test_ensure_store_dir_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dirs" / ".zikaron"
    ensure_store_dir(target)
    assert target.is_dir()
    assert _mode(target) == 0o700


def test_ensure_store_dir_tightens_an_existing_wider_directory(tmp_path: Path) -> None:
    target = tmp_path / ".zikaron"
    target.mkdir(mode=0o755)
    assert _mode(target) == 0o755
    ensure_store_dir(target)
    assert _mode(target) == 0o700


def test_ensure_store_dir_leaves_an_already_correct_directory_alone(tmp_path: Path) -> None:
    target = tmp_path / ".zikaron"
    target.mkdir(mode=0o700)
    before = target.stat().st_mtime_ns
    ensure_store_dir(target)
    assert target.stat().st_mtime_ns == before


def test_ensure_store_dir_refuses_a_symlinked_directory(tmp_path: Path) -> None:
    real_target = tmp_path / "real"
    real_target.mkdir(mode=0o700)
    target = tmp_path / ".zikaron"
    target.symlink_to(real_target)

    with pytest.raises(ZikaronError) as excinfo:
        ensure_store_dir(target)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "store_dir"


def test_ensure_store_dir_refuses_a_symlinked_ancestor_even_when_the_final_component_is_real(
    tmp_path: Path,
) -> None:
    """`architecture.md`'s rule names the *resolved path*, not merely the final component: a
    `.zikaron` that is itself a genuine directory, reached only through a symlinked parent, is
    exactly as misdirected as a `.zikaron` that is a symlink itself."""
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    (real_parent / ".zikaron").mkdir(mode=0o700)
    symlinked_parent = tmp_path / "symlinked-parent"
    symlinked_parent.symlink_to(real_parent)
    target = symlinked_parent / ".zikaron"

    assert target.is_dir()  # the final component itself is a real directory, not a symlink
    with pytest.raises(ZikaronError) as excinfo:
        ensure_store_dir(target)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "store_dir"


def test_restrictive_umask_forces_new_files_to_0600(tmp_path: Path) -> None:
    target = tmp_path / "created-inside.db"
    with restrictive_umask():
        target.touch()
    assert _mode(target) == 0o600


def test_restrictive_umask_restores_the_previous_umask_on_exit(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        with restrictive_umask():
            pass
        after_touch = tmp_path / "after.db"
        after_touch.touch()
        assert _mode(after_touch) == 0o644
    finally:
        os.umask(previous)


def test_restrictive_umask_restores_even_if_the_block_raises(tmp_path: Path) -> None:
    def _boom() -> None:
        raise ValueError("boom")

    previous = os.umask(0o022)
    try:
        try:
            with restrictive_umask():
                _boom()
        except ValueError:
            pass
        after = tmp_path / "after-raise.db"
        after.touch()
        assert _mode(after) == 0o644
    finally:
        os.umask(previous)


def test_enforce_store_file_mode_tightens_an_existing_wider_file(tmp_path: Path) -> None:
    target = tmp_path / "memory.db"
    target.touch(mode=0o644)
    target.chmod(0o644)
    enforce_store_file_mode(target)
    assert _mode(target) == 0o600


def test_enforce_store_file_mode_does_nothing_to_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "memory.db-wal"
    enforce_store_file_mode(missing)  # must not raise
    assert not missing.exists()


def test_enforce_existing_store_permissions_tightens_a_wider_directory(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o755)
    enforce_existing_store_permissions(store_dir)
    assert _mode(store_dir) == 0o700


def test_enforce_existing_store_permissions_tightens_wider_store_files(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    db = store_dir / "memory.db"
    db.touch(mode=0o644)
    db.chmod(0o644)
    enforce_existing_store_permissions(store_dir)
    assert _mode(db) == 0o600


def test_enforce_existing_store_permissions_refuses_a_symlinked_directory(
    tmp_path: Path,
) -> None:
    real_target = tmp_path / "real"
    real_target.mkdir(mode=0o700)
    store_dir = tmp_path / ".zikaron"
    store_dir.symlink_to(real_target)

    with pytest.raises(ZikaronError) as excinfo:
        enforce_existing_store_permissions(store_dir)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG


def test_enforce_existing_store_permissions_refuses_a_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    (real_parent / ".zikaron").mkdir(mode=0o700)
    symlinked_parent = tmp_path / "symlinked-parent"
    symlinked_parent.symlink_to(real_parent)
    store_dir = symlinked_parent / ".zikaron"

    with pytest.raises(ZikaronError) as excinfo:
        enforce_existing_store_permissions(store_dir)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG


def test_enforce_existing_store_permissions_does_nothing_to_an_absent_directory(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "does-not-exist" / ".zikaron"
    enforce_existing_store_permissions(absent)  # must not raise or create anything
    assert not absent.exists()


class TestTheThreeFilesOneDatabaseIs:
    """In WAL mode a database at rest is one file and a database in use is three, so every
    operation that moves, removes or re-permissions one has to handle all of them. Enumerating
    them in one place is what keeps a caller from tightening `memory.db` while leaving its `-wal`
    world-readable, or from unlinking a knowledge base and leaving its journal for the next
    database at that path to inherit."""

    def test_the_database_and_its_two_siblings_are_returned_in_order(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.db"
        assert database_files(db_path) == (
            db_path,
            tmp_path / "memory.db-wal",
            tmp_path / "memory.db-shm",
        )

    def test_the_rule_is_the_suffix_rather_than_a_hardcoded_name(self, tmp_path: Path) -> None:
        """A knowledge base's database is the same three files by the same rule, which is why the
        enumeration takes a path instead of assuming `memory.db`."""
        db_path = tmp_path / "knowledge" / "7f3a9c21-0000-4000-8000-000000000000.db"
        assert [path.name for path in database_files(db_path)] == [
            "7f3a9c21-0000-4000-8000-000000000000.db",
            "7f3a9c21-0000-4000-8000-000000000000.db-wal",
            "7f3a9c21-0000-4000-8000-000000000000.db-shm",
        ]

    def test_every_returned_path_sits_beside_the_database(self, tmp_path: Path) -> None:
        """Siblings, not children: building them by appending to the name rather than by joining
        onto the path is what keeps `-wal` a file next to the database instead of one inside a
        directory that does not exist."""
        db_path = tmp_path / "nested" / "store.db"
        assert {path.parent for path in database_files(db_path)} == {db_path.parent}
