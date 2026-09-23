"""`zikaron.service.paths` — every path is a pure function of its inputs."""

import hashlib
import os
from pathlib import Path

import pytest

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.service import paths

#: What `socket_path` appends to the runtime directory: a separator, the hash, and `.sock`.
#: Spelled from the module's own hash rather than as a literal, so a changed hash width moves the
#: boundary cases below with it instead of silently aiming them a few bytes off the edge.
_SUFFIX_BYTES = len(os.fsencode(f"/{paths.socket_hash(Path('/x'))}.sock"))


#: A platform name `sys.platform` will never report, so the fallback-row tests below keep testing
#: the fallback even if a row is added for a platform that once stood in for it.
_UNSUPPORTED_PLATFORM = "an-unsupported-platform"


def _runtime_dir_of_exactly(total_bytes: int) -> Path:
    """A runtime directory whose socket path will encode to exactly `total_bytes`."""
    return Path("/" + "x" * (total_bytes - _SUFFIX_BYTES - 1))


def test_store_dir_is_dot_zikaron_under_cwd() -> None:
    assert paths.store_dir(Path("/home/user/project")) == Path("/home/user/project/.zikaron")


def test_store_db_path_is_memory_db_inside_the_store_dir() -> None:
    assert paths.store_db_path(Path("/x/.zikaron")) == Path("/x/.zikaron/memory.db")


def test_project_config_path_sits_beside_memory_db() -> None:
    assert paths.project_config_path(Path("/x/.zikaron")) == Path("/x/.zikaron/config.toml")


def test_socket_hash_is_the_first_32_hex_chars_of_sha256_of_the_resolved_path() -> None:
    resolved = Path("/home/user/project/.zikaron")
    expected = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:32]
    assert paths.socket_hash(resolved) == expected
    assert len(paths.socket_hash(resolved)) == 32


def test_socket_hash_is_deterministic_and_distinguishes_stores() -> None:
    a = paths.socket_hash(Path("/home/user/project-a/.zikaron"))
    b = paths.socket_hash(Path("/home/user/project-b/.zikaron"))
    assert a != b
    assert a == paths.socket_hash(Path("/home/user/project-a/.zikaron"))


def test_runtime_dir_prefers_xdg_runtime_dir_when_set() -> None:
    result = paths.runtime_dir(xdg_runtime_dir="/run/user/1000", uid=1000)
    assert result == Path("/run/user/1000/zikaron")


def test_runtime_dir_falls_back_to_a_per_uid_tmp_path_when_xdg_is_unset() -> None:
    result = paths.runtime_dir(xdg_runtime_dir=None, uid=1000)
    assert result == Path("/tmp/zikaron-1000")  # noqa: S108 - asserting the documented fallback path itself


def test_runtime_dir_falls_back_when_xdg_is_the_empty_string() -> None:
    """An empty `XDG_RUNTIME_DIR` is not "set" in any meaningful sense — the same rule
    `config.resolution.default_system_config_path` applies to `XDG_CONFIG_HOME`."""
    result = paths.runtime_dir(xdg_runtime_dir="", uid=1000)
    assert result == Path("/tmp/zikaron-1000")  # noqa: S108


def test_socket_path_combines_the_runtime_dir_and_the_hash() -> None:
    runtime = Path("/run/user/1000/zikaron")
    store = Path("/home/user/project/.zikaron")
    result = paths.socket_path(runtime, store, platform="linux")
    assert result == runtime / f"{paths.socket_hash(store)}.sock"
    assert result.suffix == ".sock"


@pytest.mark.parametrize(
    ("platform", "size"),
    [("darwin", 104), ("linux", 108)],
)
def test_the_sun_path_bound_is_the_platform_s_own_sizeof(platform: str, size: int) -> None:
    assert paths.sun_path_size(platform) == size


def test_an_unrecognised_platform_takes_the_tightest_known_bound() -> None:
    """Refusing a path some other kernel would have taken is survivable; handing one to a kernel
    that will reject it is the failure this bound exists to prevent. D35 supports Linux and macOS
    arm64, and every other platform is guessed at conservatively rather than left unguarded.

    A name that can never become a row, so this keeps testing the fallback rather than quietly
    becoming a test of a supported platform if one is ever added.
    """
    known = (paths.sun_path_size("darwin"), paths.sun_path_size("linux"))
    assert paths.sun_path_size(_UNSUPPORTED_PLATFORM) == min(known)
    assert paths.sun_path_size(_UNSUPPORTED_PLATFORM) in known


@pytest.mark.parametrize("platform", ["darwin", "linux", _UNSUPPORTED_PLATFORM])
def test_a_socket_path_one_byte_inside_the_bound_is_accepted(platform: str) -> None:
    size = paths.sun_path_size(platform)
    runtime = _runtime_dir_of_exactly(size - 1)
    result = paths.socket_path(runtime, Path("/x"), platform=platform)
    assert len(os.fsencode(result)) == size - 1


@pytest.mark.parametrize("platform", ["darwin", "linux", _UNSUPPORTED_PLATFORM])
def test_a_socket_path_at_the_bound_is_refused(platform: str) -> None:
    """`>=` rather than `>`, because that is CPython's own predicate: a path whose encoded length
    equals `sizeof(sun_path)` has no room left for the terminating NUL and `bind()` refuses it.
    Measured directly on Linux — 107 bytes binds, 108 raises `OSError: AF_UNIX path too long`."""
    size = paths.sun_path_size(platform)
    with pytest.raises(ZikaronError) as raised:
        paths.socket_path(_runtime_dir_of_exactly(size), Path("/x"), platform=platform)
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert raised.value.data["source"] == BadConfigSource.DERIVED
    assert raised.value.data["key"] == "runtime_dir"
    assert str(size - 1) in str(raised.value.data["expected"])


def test_the_bound_counts_encoded_bytes_rather_than_characters() -> None:
    """`$XDG_RUNTIME_DIR` is user-controlled and may be non-ASCII, and CPython measures the
    encoded path. A directory of two-byte characters crosses the bound while its character count
    is still well inside it, so `len(str(path))` would admit a path `bind()` then refuses."""
    runtime = Path("/" + "é" * 40)
    path = runtime / f"{paths.socket_hash(Path('/x'))}.sock"
    assert len(str(path)) < paths.sun_path_size("darwin")
    assert len(os.fsencode(path)) >= paths.sun_path_size("darwin")
    with pytest.raises(ZikaronError):
        paths.socket_path(runtime, Path("/x"), platform="darwin")


def test_the_tmp_fallback_fits_on_macos_even_for_a_ten_digit_uid() -> None:
    """The branch macOS takes, since it sets no `$XDG_RUNTIME_DIR`. The only input that can move
    this number is the uid's width, and the widest one a system will issue still leaves room."""
    runtime = paths.runtime_dir(xdg_runtime_dir=None, uid=4_294_967_294)
    path = paths.socket_path(runtime, Path("/home/user/project/.zikaron"), platform="darwin")
    assert len(os.fsencode(path)) < paths.sun_path_size("darwin")


def test_an_over_long_xdg_runtime_dir_is_refused_rather_than_redirected_to_the_fallback() -> None:
    """`architecture.md` §"Filesystem security" — reject, never repair. Serving the `/tmp`
    fallback to a user who named somewhere else would put the socket, and every store secret
    reachable through it, in a directory they did not choose."""
    runtime = paths.runtime_dir(xdg_runtime_dir="/var/folders/" + "x" * 80, uid=501)
    with pytest.raises(ZikaronError) as raised:
        paths.socket_path(runtime, Path("/x"), platform="darwin")
    assert raised.value.data["value"] == str(runtime)


def test_lock_path_is_the_socket_path_with_dot_lock_appended() -> None:
    sock = Path("/run/user/1000/zikaron/abc123.sock")
    assert paths.lock_path(sock) == Path("/run/user/1000/zikaron/abc123.sock.lock")


def test_the_three_logs_are_distinct_files_in_the_store_dir() -> None:
    store = Path("/x/.zikaron")
    service_log = paths.service_log_path(store)
    warmup_log = paths.warmup_log_path(store)
    hook_log = paths.hook_log_path(store)
    assert {service_log, warmup_log, hook_log} == {
        store / "service.log",
        store / "warmup.log",
        store / "hook.log",
    }
