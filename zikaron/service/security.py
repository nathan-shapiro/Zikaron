"""Filesystem vetting for the runtime directory and the socket inside it.

`architecture.md` §"Filesystem security" is normative: "reject, never repair, a hostile runtime
path" and "never unlink a socket you have not vetted." Both rules exist because a predictable path
under a world-writable `/tmp` is the classic setup for a local symlink attack — an attacker who
races the service to create `/tmp/zikaron-<uid>/` first, or replaces the socket with a symlink to
somewhere else, must be refused rather than silently worked around.

`$XDG_RUNTIME_DIR` itself is **not** vetted here: `architecture.md` states it is already
user-private `0700` when a desktop or login session sets it, and re-deriving trust for a path the
platform already guarantees would be redundant rather than defensive. Only the directory this
module *creates on demand* — the `zikaron` subdirectory beneath either root — is checked, because
that is the one this service is responsible for having gotten right.
"""

import os
import stat
from pathlib import Path

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

_RUNTIME_DIR_MODE = 0o700

#: How many `lstat` → `mkdir` cycles `ensure_runtime_dir` will retry against a `FileExistsError`
#: before giving up and reporting it as an ordinary vetting failure. Bounded rather than
#: recursing without limit: an adversary who can repeatedly create and remove the path between
#: this process's `mkdir` failure and its next `lstat` could otherwise drive unbounded recursion
#: purely by timing, and a security-relevant check must never be able to crash with an unhandled
#: `RecursionError` when a controlled, bounded rejection is available instead. Two cooperating
#: callers — the only case this retry exists for — resolve on the very first retry, since the
#: winner never removes what it created; this bound exists for the adversarial case, not the
#: ordinary one.
_MAX_CREATE_ATTEMPTS = 10


def _not_a_real_directory(path: Path) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        key="runtime_dir",
        value=str(path),
        expected="a real directory, not a symlink — refused rather than followed",
    )


def _wrong_owner(path: Path, *, found_uid: int, expected_uid: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        key="runtime_dir",
        value=str(path),
        expected=f"owned by uid {expected_uid}, found {found_uid}",
    )


def _wrong_mode(path: Path, *, found_mode: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        key="runtime_dir",
        value=str(path),
        expected=f"mode {oct(_RUNTIME_DIR_MODE)}, found {oct(found_mode)}",
    )


def _too_many_create_attempts(path: Path) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        key="runtime_dir",
        value=str(path),
        expected=(
            f"a stable directory — {_MAX_CREATE_ATTEMPTS} create/vet cycles all lost to a "
            "path that kept disappearing and reappearing between them"
        ),
    )


def ensure_runtime_dir(path: Path, *, uid: int) -> None:
    """Create `path` at `0700` if absent, or vet it strictly if it already exists.

    An absent directory is created outright — nothing to distrust yet. An *existing* one is
    checked against three things before it is used, and none of them is repaired on a failure: it
    must be a real directory (`lstat`, so a symlink is caught before it is ever followed rather
    than compared against its target), owned by `uid`, and exactly `0700`. `architecture.md` is
    explicit that this case is refused rather than repaired, unlike the store directory's own
    `ensure_store_dir`, which *does* tighten a wide mode — the two differ because a `/tmp` path is
    reachable by every user on the machine and an attacker could have created it before this
    process ever ran, where a store directory the caller already owns carries no such risk from
    merely being wide.

    **Two callers racing the absent-directory path is a real case, not a theoretical one** —
    `connect_start_if_absent` calls this before its own `flock`, specifically so a socket already
    reachable through a hostile directory is never trusted even on the fast, no-lock-needed path,
    which means two cold clients can both observe `FileNotFoundError` and both attempt `mkdir`.
    The loser's `mkdir` raises `FileExistsError`, which this function catches and responds to by
    re-vetting the identical path an already-existing directory gets — never by assuming the
    winner created something trustworthy, since "another one of my own racing callers won" and "an
    attacker's directory was already there" look identical from this function's own vantage
    point, and only one of the two is safe to proceed past silently. The retry is a **bounded
    loop**, not recursion: two cooperating callers resolve on the very first retry, since the
    winner never removes what it created, but an adversary able to repeatedly create and remove
    the path between this process's own `mkdir` failure and its next `lstat` must be met with a
    controlled rejection rather than an unbounded call stack.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `runtime_dir` if the path exists as anything but a real,
            correctly-owned, `0700` directory, or if `_MAX_CREATE_ATTEMPTS` consecutive
            create/vet cycles were all lost to `FileExistsError`.
    """
    for _attempt in range(_MAX_CREATE_ATTEMPTS):
        try:
            info = path.lstat()
        except FileNotFoundError:
            try:
                path.mkdir(mode=_RUNTIME_DIR_MODE, parents=True)
            except FileExistsError:
                continue  # Another caller won the create race — re-vet on the next iteration.
            path.chmod(_RUNTIME_DIR_MODE)
            return
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise _not_a_real_directory(path)
        if info.st_uid != uid:
            raise _wrong_owner(path, found_uid=info.st_uid, expected_uid=uid)
        found_mode = stat.S_IMODE(info.st_mode)
        if found_mode != _RUNTIME_DIR_MODE:
            raise _wrong_mode(path, found_mode=found_mode)
        return
    raise _too_many_create_attempts(path)


def vet_socket_for_unlink(path: Path, *, uid: int) -> bool:
    """Whether `path` is safe to unlink as a stale socket: a real socket, owned by `uid`.

    Called immediately before start-if-absent unlinks what it believes is a dead server's leftover
    socket file. Returns `False` rather than raising for "nothing is there" — the caller's own next
    step (create the listening socket) handles an absent path correctly on its own, so that is not
    a vetting failure, only the ordinary case of a store that has never been served.

    A path that *exists* but is not a plain socket, or is not owned by this uid, is refused rather
    than unlinked — `architecture.md`: "never unlink a socket you have not vetted." `lstat` is used
    throughout so a symlink is identified as itself rather than dereferenced into whatever it
    points at, which is exactly the distinction that makes this check meaningful.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(info.st_mode):
        return False
    return info.st_uid == uid


def current_uid() -> int:
    """This process's real uid, the one identity every ownership check above compares against."""
    return os.getuid()
