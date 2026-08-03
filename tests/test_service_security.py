"""`zikaron.service.security` — the filesystem vetting rules `architecture.md` §"Filesystem
security" fixes for the runtime directory and its socket."""

import os
import threading
from pathlib import Path

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.service import security

_MY_UID = os.getuid()
_OTHER_UID = _MY_UID + 1


def test_ensure_runtime_dir_creates_an_absent_directory_at_0700(tmp_path: Path) -> None:
    target = tmp_path / "zikaron"
    security.ensure_runtime_dir(target, uid=_MY_UID)
    assert target.is_dir()
    assert (target.stat().st_mode & 0o777) == 0o700


def test_ensure_runtime_dir_accepts_an_existing_correctly_vetted_directory(tmp_path: Path) -> None:
    target = tmp_path / "zikaron"
    target.mkdir(mode=0o700)
    security.ensure_runtime_dir(target, uid=_MY_UID)  # must not raise
    assert (target.stat().st_mode & 0o777) == 0o700


def test_ensure_runtime_dir_recovers_when_a_racing_caller_creates_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two cold clients can both observe the directory absent and both attempt `mkdir` —
    `connect_start_if_absent` calls this before its own `flock`, on purpose, so nothing serializes
    two racing callers here. The loser's `mkdir` raises `FileExistsError`; this must not be
    treated as success, only as a reason to re-vet whatever now exists — simulated here by making
    the *first* `mkdir` attempt raise as if another caller had just won, then confirming the
    function recovers by re-checking the winner's directory rather than assuming it."""
    target = tmp_path / "zikaron"
    real_mkdir = Path.mkdir
    called = {"count": 0}

    def _mkdir_racing_loser(self: Path, *args: object, **kwargs: object) -> None:
        called["count"] += 1
        if called["count"] == 1:
            # Simulate another caller winning the race: create the directory correctly, as that
            # caller's own `ensure_runtime_dir` would, then report the loss this call actually saw.
            real_mkdir(self, mode=0o700, parents=True)
            raise FileExistsError(str(self))
        real_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "mkdir", _mkdir_racing_loser)
    security.ensure_runtime_dir(target, uid=_MY_UID)  # must not raise
    assert target.is_dir()
    assert (target.stat().st_mode & 0o777) == 0o700
    assert called["count"] == 1, "the recovery path re-vets an existing directory, not mkdir again"


def test_ensure_runtime_dir_still_refuses_a_hostile_directory_a_racing_loser_finds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dangerous half of the race: what a losing `mkdir` finds is not necessarily a fellow
    caller's legitimate directory — it could be exactly the hostile pre-existing path the whole
    vetting rule exists to catch, and the recovery path must apply the identical scrutiny rather
    than treating "someone got there first" as proof of safety."""
    target = tmp_path / "zikaron"
    real_dir = tmp_path / "hostile"
    real_dir.mkdir(mode=0o700)

    def _mkdir_finds_a_symlink(self: Path, *_args: object, **_kwargs: object) -> None:
        self.symlink_to(real_dir)
        raise FileExistsError(str(self))

    monkeypatch.setattr(Path, "mkdir", _mkdir_finds_a_symlink)
    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_survives_two_genuinely_concurrent_callers(tmp_path: Path) -> None:
    """The monkeypatch-based tests above pin the exact recovery mechanism; this is the same
    guarantee under real OS-level concurrency, with an absent directory and several real threads
    racing `mkdir` against each other rather than a simulated loss."""
    target = tmp_path / "zikaron"
    errors: list[Exception] = []

    def _call() -> None:
        try:
            security.ensure_runtime_dir(target, uid=_MY_UID)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert not any(thread.is_alive() for thread in threads), (
        "a worker never returned within the join timeout — a hang here must fail the test "
        "outright rather than be masked by another worker's success leaving `errors` empty"
    )
    assert not errors, f"a legitimate racing caller was refused: {errors}"
    assert target.is_dir()
    assert (target.stat().st_mode & 0o777) == 0o700


def test_ensure_runtime_dir_gives_up_after_too_many_create_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounded-loop half of the fix: a path that keeps disappearing and reappearing between
    this function's own `mkdir` failure and its next `lstat` — simulated here by making `mkdir`
    always lose — must end in a controlled `BAD_CONFIG` rejection, never an unbounded retry."""
    target = tmp_path / "zikaron"

    def _always_loses(self: Path, *_args: object, **_kwargs: object) -> None:
        raise FileExistsError(str(self))

    monkeypatch.setattr(Path, "mkdir", _always_loses)
    # `lstat` must also keep reporting absence, or the loop would exit through the "exists"
    # branch instead of exhausting its create-attempt bound — the scenario under test is
    # specifically a path that is absent every time this function looks, not one that exists but
    # fails some other check.
    real_lstat = Path.lstat

    def _always_absent(self: Path, *args: object, **kwargs: object) -> object:
        if self == target:
            raise FileNotFoundError(str(self))
        return real_lstat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", _always_absent)

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_refuses_a_symlink_rather_than_repairing_it(tmp_path: Path) -> None:
    """`architecture.md`: "reject, never repair, a hostile runtime path" — unlike the store
    directory's own `ensure_store_dir`, which does tighten a wide mode, a `/tmp`-class path is
    reachable by every user on the machine and must never be silently trusted."""
    real_dir = tmp_path / "real"
    real_dir.mkdir(mode=0o700)
    symlink = tmp_path / "zikaron"
    symlink.symlink_to(real_dir)

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(symlink, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_refuses_a_directory_owned_by_someone_else(tmp_path: Path) -> None:
    target = tmp_path / "zikaron"
    target.mkdir(mode=0o700)

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_OTHER_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_refuses_a_directory_wider_than_0700(tmp_path: Path) -> None:
    target = tmp_path / "zikaron"
    target.mkdir(mode=0o755)

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_refuses_a_directory_narrower_than_0700_too(tmp_path: Path) -> None:
    """The check is `!=`, not "wide enough" — a directory this process cannot itself write into
    (e.g. `0500`) is exactly as wrong as one that is too permissive, since the whole point is that
    the mode is *exactly* what this module set it to, not merely a ceiling on it."""
    target = tmp_path / "zikaron"
    target.mkdir(mode=0o500)

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "runtime_dir"


def test_ensure_runtime_dir_refuses_a_plain_file_at_the_path(tmp_path: Path) -> None:
    target = tmp_path / "zikaron"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ZikaronError) as excinfo:
        security.ensure_runtime_dir(target, uid=_MY_UID)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG


def test_vet_socket_for_unlink_accepts_a_real_socket_owned_by_this_uid(tmp_path: Path) -> None:
    import socket as socket_module  # noqa: PLC0415 — only this test needs a real bound socket.

    sock_path = tmp_path / "server.sock"
    sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))
        assert security.vet_socket_for_unlink(sock_path, uid=_MY_UID) is True
    finally:
        sock.close()


def test_vet_socket_for_unlink_returns_false_for_an_absent_path(tmp_path: Path) -> None:
    """Absence is the ordinary case of a store that has never been served — not a vetting
    failure, since the caller's own next step (bind a fresh socket) handles it correctly."""
    assert security.vet_socket_for_unlink(tmp_path / "never-served.sock", uid=_MY_UID) is False


def test_vet_socket_for_unlink_refuses_a_plain_file(tmp_path: Path) -> None:
    """Never unlink a socket you have not vetted — a file masquerading at the socket path is
    exactly the shape a local attack would take."""
    fake = tmp_path / "server.sock"
    fake.write_text("not a socket", encoding="utf-8")
    assert security.vet_socket_for_unlink(fake, uid=_MY_UID) is False


def test_vet_socket_for_unlink_refuses_a_symlink_even_to_a_real_socket(tmp_path: Path) -> None:
    import socket as socket_module  # noqa: PLC0415

    real_sock_path = tmp_path / "real.sock"
    sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        sock.bind(str(real_sock_path))
        symlink = tmp_path / "server.sock"
        symlink.symlink_to(real_sock_path)
        assert security.vet_socket_for_unlink(symlink, uid=_MY_UID) is False
    finally:
        sock.close()


def test_vet_socket_for_unlink_refuses_a_socket_owned_by_someone_else(tmp_path: Path) -> None:
    import socket as socket_module  # noqa: PLC0415

    sock_path = tmp_path / "server.sock"
    sock = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))
        assert security.vet_socket_for_unlink(sock_path, uid=_OTHER_UID) is False
    finally:
        sock.close()


def test_current_uid_matches_os_getuid() -> None:
    assert security.current_uid() == os.getuid()
