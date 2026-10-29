"""The session relay's writer: this hook's session label, left for the MCP client that shares its
parent.

`design/harness.md` §"The session relay" is normative. Under a harness whose session variable
reaches hooks and no MCP server, the hook writes its payload's `session_id` to a file named for its
own parent, the agent server, and `zikaron.harness.detect.session_label` reads it from the MCP
client, whose parent is the same process.

Written at every start and every prompt, before anything else the hook does, so a hook killed at
its timeout while waiting on a starting service has already left the label. The last writer wins:
hooks fire only for top-level sessions, and both run before any tool call of their turn, so the file
names the session whose turn is running.

Best-effort as a whole, as the warm-helper spawn is: a failure anywhere costs the relay alone, and
the MCP client then mints a label of its own.
"""

import contextlib
import os
from pathlib import Path

from zikaron.harness import detect
from zikaron.harness.spec import HarnessSpec
from zikaron.service import paths, security

_TEMPORARY_SUFFIX = ".tmp"


def relay_dir() -> Path:
    """The relay's directory, as both clients derive it."""
    runtime_directory = paths.runtime_dir(
        xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid()
    )
    return paths.session_relay_dir(runtime_directory)


def record(spec: HarnessSpec, payload_session_id: object, *, sweep: bool) -> None:
    """Leave `payload_session_id` for this process's parent, if `spec` relays and it is a label.

    `sweep` also removes every file whose process is gone, which a session's start does once so the
    directory holds about one file per live agent server. Never raises.
    """
    if not spec.session_variable_misses_mcp_server:
        return
    if not isinstance(payload_session_id, str) or not payload_session_id:
        return
    with contextlib.suppress(Exception):
        directory = relay_dir()
        uid = os.getuid()
        security.ensure_runtime_dir(directory.parent, uid=uid)
        security.ensure_runtime_dir(directory, uid=uid)
        if sweep:
            _remove_the_dead(directory)
        _write(directory, payload_session_id)


def _write(directory: Path, label: str) -> None:
    """Replace the parent's file whole: a hook killed mid-write leaves the old label or the new one,
    never part of either."""
    target = detect.relay_file(directory, os.getppid())
    temporary = target.with_name(f"{target.name}.{os.getpid()}{_TEMPORARY_SUFFIX}")
    # Named for this process, so a file already there is a killed hook's that drew the same pid.
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            remaining = memoryview(label.encode("utf-8"))
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("the relay file accepted no bytes")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _remove_the_dead(directory: Path) -> None:
    """Remove each file named for a process that no longer exists: a relay file by the agent server
    it names, a temporary one by the hook that was writing it."""
    for entry in os.scandir(directory):
        owner = _owning_pid(entry.name)
        if owner is not None and not _alive(owner):
            Path(entry.path).unlink(missing_ok=True)


def _owning_pid(name: str) -> int | None:
    if _is_pid(name):
        return int(name)
    stem, dot, writer = name.removesuffix(_TEMPORARY_SUFFIX).rpartition(".")
    if name.endswith(_TEMPORARY_SUFFIX) and dot and _is_pid(stem) and _is_pid(writer):
        return int(writer)
    return None


def _is_pid(text: str) -> bool:
    return text.isascii() and text.isdigit()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
