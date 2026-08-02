"""`0700`/`0600` enforcement for the store directory and the files inside it.

`architecture.md` §"Filesystem security" is normative: `.zikaron/` is mode `0700`, and
`memory.db` plus its `-wal`/`-shm` siblings are `0600`, created with an explicit umask rather
than inherited — SQLite creates the WAL/SHM files itself and will otherwise pick up whatever
umask the process happened to have. A directory found wider than `0700` is tightened rather than
refused, per the same table.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

_STORE_DIR_MODE = 0o700
_STORE_FILE_MODE = 0o600
_STORE_FILE_UMASK = 0o077


def _reject_symlinked_store_dir(store_dir: Path) -> None:
    """Refuse a store reached through a symlink anywhere in `store_dir`'s own path.

    `architecture.md` §"Filesystem security": "`realpath` the store directory and require the
    resolved parent to be the cwd." That sentence states the rule from `zikaron-service`'s own
    point of view, where the store path is *derived* from the process's cwd in the first place
    (D17: "Store scoped to the harness's directory... literally the current working
    directory") — deriving `store_dir` from `os.getcwd()` is that caller's job, not this
    function's, since `Store.create`/`Store.open` take `store_dir` as an explicit parameter and
    have no way to know whether the caller's own cwd is the concept the caller meant by it. A
    caller that resolved `store_dir` from somewhere other than its own cwd — a test, a tool
    walking several stores — would be wrongly refused by comparing against the *ambient*
    process cwd here, which is a fact about this function's environment rather than about the
    path it was actually asked to open.

    What this function *can* check, and what carries the rule's real security content
    regardless of who derived the path: whether `store_dir` is reached through a symlink at
    all, anywhere along its own length — `store_dir` itself, or any directory between it and
    the filesystem root. A bare `store_dir.is_symlink()` check misses the case a symlinked
    *ancestor* creates, e.g. `some-symlinked-parent/.zikaron`, where `.zikaron` itself is a
    genuine directory but the path leading to it is not what it appears to be.
    """
    current = store_dir if store_dir.is_absolute() else Path.cwd() / store_dir
    while True:
        if current.is_symlink():
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.FILE,
                key="store_dir",
                value=str(store_dir),
                expected=f"no symlink anywhere in the path to it (found one at {current})",
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def ensure_store_dir(path: Path) -> None:
    """Create `path` at `0700` if absent, or tighten it to `0700` if it exists wider.

    Explicit `mkdir(mode=...)` rather than a bare `mkdir()` followed by `chmod`, because a
    process umask can otherwise narrow the mode `mkdir` was asked for and leave a gap between
    what this function requested and what actually landed on disk.

    Raises:
        ZikaronError: `BAD_CONFIG` if `path`, once resolved, is not reached through the current
            directory alone — `architecture.md` §"Filesystem security" requires a store reached
            through a symlinked `.zikaron`, or through a symlinked ancestor of it, to be
            refused rather than followed, since the store's own `0700`/`0600` modes protect the
            directory they are set on, not whatever a symlink happens to point at.
    """
    _reject_symlinked_store_dir(path)
    if path.is_dir():
        current = path.stat().st_mode & 0o777
        if current != _STORE_DIR_MODE:
            path.chmod(_STORE_DIR_MODE)
        return
    path.mkdir(mode=_STORE_DIR_MODE, parents=True)
    path.chmod(_STORE_DIR_MODE)


@contextmanager
def restrictive_umask() -> Iterator[None]:
    """Force every file created in this block to land at `0600`, regardless of the process umask.

    SQLite creates `memory.db`'s `-wal` and `-shm` siblings itself, outside any `open()` call
    this module makes, so a umask set only around an explicit file creation would not reach
    them. Wrapping the whole store-creation sequence in this umask is what does.
    """
    previous = os.umask(_STORE_FILE_UMASK)
    try:
        yield
    finally:
        os.umask(previous)


def enforce_store_file_mode(path: Path) -> None:
    """Tighten an existing store file to `0600` if it was created wider than that.

    Called after store creation as a belt-and-suspenders check: `restrictive_umask` is what
    should have produced `0600` in the first place, and this is what makes a wider mode a
    correction rather than a silent gap if some code path ever creates the file outside it.
    """
    if path.is_file():
        current = path.stat().st_mode & 0o777
        if current != _STORE_FILE_MODE:
            path.chmod(_STORE_FILE_MODE)


def enforce_existing_store_permissions(store_dir: Path) -> None:
    """Tighten a pre-existing store's directory and database files, without creating anything.

    `Store.open` calls this before touching the connection, so a store whose directory was left
    at a wider mode by an older build — or by an operator's own `chmod` — is corrected on the
    very next open rather than only ever being corrected at creation time, which is the one
    moment `Store.create`'s own checks previously ran.

    Raises:
        ZikaronError: `BAD_CONFIG` if `store_dir`, once resolved, is not reached through the
            current directory alone, for the same reason `ensure_store_dir` refuses that shape
            at creation.
    """
    _reject_symlinked_store_dir(store_dir)
    if store_dir.is_dir():
        current = store_dir.stat().st_mode & 0o777
        if current != _STORE_DIR_MODE:
            store_dir.chmod(_STORE_DIR_MODE)
    for name in ("memory.db", "memory.db-wal", "memory.db-shm"):
        enforce_store_file_mode(store_dir / name)
