"""`zikaron.service.paths` — every path is a pure function of its inputs."""

import hashlib
from pathlib import Path

from zikaron.service import paths


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
    result = paths.socket_path(runtime, store)
    assert result == runtime / f"{paths.socket_hash(store)}.sock"
    assert result.suffix == ".sock"


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
