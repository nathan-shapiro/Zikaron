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
from pathlib import Path

#: `architecture.md` §Paths: "the first 32 hex characters (128 bits) of the sha256 of the
#: realpath-resolved store path" — long enough that accidental collision is not a design concern,
#: short enough to keep the socket path under the ~108-byte `sun_path` limit.
_HASH_HEX_CHARS = 32

_DB_FILENAME = "memory.db"
_CONFIG_FILENAME = "config.toml"
_SERVICE_LOG_FILENAME = "service.log"
_WARMUP_LOG_FILENAME = "warmup.log"
_HOOK_LOG_FILENAME = "hook.log"
_WRITE_POLICY_FILENAME = "write-policy.md"


def store_dir(scope_dir: Path) -> Path:
    """The `.zikaron` directory for the store scoped to `scope_dir` (D17, amended 2026-08-18).

    Callers resolve `scope_dir` through `HarnessSpec.store_scope_dir`: the harness's own project
    directory where it names one, else the fallback the caller passes — `zikaron-mcp`'s own process
    cwd, or the payload's `cwd` for the hook, which are *different* inputs and is why the fallback
    is where the two clients can still diverge (`HarnessSpec.store_scope_dir`). The parameter was
    called `cwd` until the amendment, which was true of neither case in general.
    """
    return scope_dir / ".zikaron"


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


def socket_path(runtime_directory: Path, resolved_store_dir: Path) -> Path:
    """The full `<h>.sock` path for one store, inside its runtime directory."""
    return runtime_directory / f"{socket_hash(resolved_store_dir)}.sock"


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
