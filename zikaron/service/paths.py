"""Where every file the service touches lives, as pure functions of their inputs.

`architecture.md` §Paths is normative. Every function here takes what it needs as an argument
rather than reading `os.environ` or `Path.cwd()` itself, so a test states the environment it is
checking instead of mutating the process's — the same reason `config.resolution`'s
`default_system_config_path` takes `xdg_config_home` and `home` as parameters.

The one derived value — the socket hash — is **not** a store secret: the store's own contents stay
behind the store directory's `0700` mode and the socket's `0600`, and this hash exists only to keep
two different stores' sockets from colliding inside one shared runtime directory. `sha256` is used
for its length and its output alphabet, not for any resistance property the design depends on.
"""

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError

#: `architecture.md` §Paths: "the first 32 hex characters (128 bits) of the sha256 of the
#: realpath-resolved store path" — long enough that accidental collision is not a design concern,
#: and fixed, so the store contributes the same width to the socket path however deeply the
#: project it names is nested. That is what leaves `_SUN_PATH_SIZE` a question about the runtime
#: directory alone.
_HASH_HEX_CHARS = 32

#: `sizeof(struct sockaddr_un.sun_path)` per platform, in bytes, terminating NUL included. CPython
#: refuses a socket path whose *encoded* length is `>=` this.
_SUN_PATH_SIZE: Final[Mapping[str, int]] = MappingProxyType({"darwin": 104, "linux": 108})

_DB_FILENAME = "memory.db"
_CONFIG_FILENAME = "config.toml"
_SERVICE_LOG_FILENAME = "service.log"
_WARMUP_LOG_FILENAME = "warmup.log"
_HOOK_LOG_FILENAME = "hook.log"
_WRITE_POLICY_FILENAME = "write-policy.md"


def store_dir(scope_dir: Path) -> Path:
    """The `.zikaron` directory for the store scoped to `scope_dir` (D17).

    Callers resolve `scope_dir` through `HarnessSpec.store_scope_dir`: the harness's own project
    directory where it names one, else the fallback the caller passes — `zikaron-mcp`'s own process
    cwd, or the payload's `cwd` for the hook, which are *different* inputs and is why the fallback
    is where the two clients can still diverge (`HarnessSpec.store_scope_dir`). The parameter was
    called `cwd` until the amendment, which was true of neither case in general.
    """
    return scope_dir / ".zikaron"


def scope_of(store_directory: Path) -> Path:
    """`store_dir`'s inverse: the directory a store directory was derived from.

    Needed because a knowledge-base build is spawned as its own process and takes the **project**
    rather than the store, so that the child acts on the store its parent already resolved instead
    of resolving one for itself. Written as the stated inverse, in one place, rather than as a
    `.parent` at the call site: the two are the same operation and a reader meeting only the second
    has no way to tell whether the coupling is deliberate.
    """
    return store_directory.parent


def store_db_path(store_directory: Path) -> Path:
    """Where `memory.db` lives inside a store directory."""
    return store_directory / _DB_FILENAME


def project_config_path(store_directory: Path) -> Path:
    """Where the per-store config override lives, beside `memory.db`."""
    return store_directory / _CONFIG_FILENAME


def socket_hash(store_directory: Path) -> str:
    """The `<h>` component of the socket path: derived from the store's own resolved path.

    Takes the directory already `realpath`-resolved, rather than resolving it itself, so the one
    call that must run the resolution — and can raise on a dangling or cyclic symlink — is visible
    at the call site instead of hidden inside a hash function that looks like it cannot fail.
    """
    digest = hashlib.sha256(str(store_directory).encode("utf-8")).hexdigest()
    return digest[:_HASH_HEX_CHARS]


def runtime_dir(*, xdg_runtime_dir: str | None, uid: int) -> Path:
    """Where the socket and its lock file live: `$XDG_RUNTIME_DIR/zikaron`, or a per-uid `/tmp`.

    `architecture.md` §Paths: `$XDG_RUNTIME_DIR` is already user-private `0700` when the desktop or
    login session sets it, so only the `/tmp` fallback needs the hostile-directory vetting
    `security.py` performs before use — this function only computes the path, never touches the
    filesystem, so a test can state a candidate directory without creating one.
    """
    base = Path(xdg_runtime_dir) if xdg_runtime_dir else Path(f"/tmp/zikaron-{uid}")  # noqa: S108
    return base / "zikaron" if xdg_runtime_dir else base


def sun_path_size(platform: str) -> int:
    """`sizeof(sun_path)` on `platform`: the length `bind()` refuses a socket path at or above.

    Takes the platform as an argument for the reason this module's own docstring gives, and so
    both rows are exercised wherever the suite runs rather than only the one underfoot.

    An unrecognised platform takes the smallest row. That can only refuse a path some other
    platform would have accepted, never admit one its own kernel will reject, and D35 supports
    exactly the two named here.
    """
    return _SUN_PATH_SIZE.get(platform, min(_SUN_PATH_SIZE.values()))


def _too_long_for_sun_path(runtime_directory: Path, *, measured: int, size: int) -> ZikaronError:
    """The refusal, with `runtime_dir` meaning what `security.py`'s raises make it mean.

    `value` is the directory, not the socket path derived from it: one key, one vocabulary, and
    the directory is the half a reader can act on.
    """
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.DERIVED,
        key="runtime_dir",
        value=str(runtime_directory),
        expected=(
            f"a directory under which <dir>/<32 hex>.sock fits in {size - 1} bytes on this "
            f"platform; this one makes it {measured}. It comes from $XDG_RUNTIME_DIR when set"
        ),
    )


def socket_path(runtime_directory: Path, resolved_store_dir: Path, *, platform: str) -> Path:
    """The full `<h>.sock` path for one store, inside its runtime directory.

    The store's contribution is a constant — `socket_hash` is `_HASH_HEX_CHARS` wide whatever it
    is given — so only `runtime_directory` can push the result past the bound, and on the
    `$XDG_RUNTIME_DIR` branch that is an unbounded value the user chose.

    Refused here rather than at `bind()`, because by then a client has already run start-if-absent
    and would report a spawned service's failure instead of the path's. `architecture.md`
    §"Filesystem security" rules out the other repair — silently serving the `/tmp` fallback to a
    user who named somewhere else is exactly the repair that section forbids.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `runtime_dir`, when the encoded result does not fit
            `platform`'s `sun_path`.
    """
    path = runtime_directory / f"{socket_hash(resolved_store_dir)}.sock"
    size = sun_path_size(platform)
    measured = len(os.fsencode(path))
    if measured >= size:
        raise _too_long_for_sun_path(runtime_directory, measured=measured, size=size)
    return path


def lock_path(sock_path: Path) -> Path:
    """The `flock` target guarding start-if-absent for one socket: `<sock>.lock`, beside it."""
    return sock_path.with_name(sock_path.name + ".lock")


def service_log_path(store_directory: Path) -> Path:
    """The long-running service's own log — one file, this process only."""
    return store_directory / _SERVICE_LOG_FILENAME


def warmup_log_path(store_directory: Path) -> Path:
    """The `agentSpawn` hook's detached warm helper's own log."""
    return store_directory / _WARMUP_LOG_FILENAME


def hook_log_path(store_directory: Path) -> Path:
    """The `userPromptSubmit` hook's own failure record."""
    return store_directory / _HOOK_LOG_FILENAME


def write_policy_override_path(store_directory: Path) -> Path:
    """The optional operator-authored write policy the `agentSpawn` hook prefers when it exists.

    `architecture.md` §"The install contract": D30 asks for the policy text to be experimented
    against, and an experiment that requires editing installed Python is an experiment nobody runs.
    Absent — which is the normal case — the hook prints its own constant.
    """
    return store_directory / _WRITE_POLICY_FILENAME
