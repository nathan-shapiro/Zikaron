"""The `agentSpawn` hook's detached warm helper — a separate process image, not on any critical
path, and therefore under a different contract than the rest of `zikaron.hook`.

`architecture.md` §"Warming": "the helper does the work that can fail: start-if-absent and
`health()` polling to a deadline. It writes to its own `warmup.log`... via stdlib `logging`, since
it runs detached and off the user's critical path so the ~15 ms interpreter cost of importing
`logging` is irrelevant here." This is the one module in the `zikaron.hook` package tree that is
**not** covered by the package's own stdlib-only rule, for exactly the reason `service/log.py`
is not either: its import cost is paid by a process nothing is waiting on, spawned detached by
`spawn_warm.py` and never awaited by the `agentSpawn` hook itself.

**Freely imports `zikaron.service.lifecycle`, unlike every other module in this package.** That
module pulls in `aiosqlite`, `sqlite-vec` and `fastembed`'s dependency chain (verified directly:
importing it adds `aiosqlite`, `numpy` and `sqlite_vec` to `sys.modules`), which is exactly why
`connect.py` reimplements a narrower version of the same sequence rather than importing it — but
that reasoning is specific to a process on the `userPromptSubmit` or `agentSpawn` critical path.
This process has no such deadline: nothing waits for it, its failure is invisible to the session
it is warming, and reusing `connect_start_if_absent` here means this helper's start-if-absent
behaviour is *identical* to `zikaron-mcp`'s own, rather than a third independently-written copy
that could disagree with the other two about the exact race conditions it exists to survive.
"""

import logging
import stat
import sys
from pathlib import Path
from typing import Final

from zikaron.core.store.permissions import ensure_store_dir
from zikaron.service.lifecycle import connect_start_if_absent, default_server_command
from zikaron.service.paths import store_db_path, warmup_log_path

_FILE_MODE: Final = 0o600

#: `architecture.md`: "start-if-absent and `health()` polling to a deadline." Generous relative to
#: the ~101 ms measured cold-start figure, since this process has no user waiting on it and can
#: afford to absorb a slow environment rather than declaring the service unreachable prematurely —
#: `zikaron.service.lifecycle`'s own `_HEALTH_POLL_DEADLINE_SECONDS` (10 s) is exactly the budget
#: this helper inherits by calling that function unmodified, so no separate constant is declared
#: here to disagree with it.


def _configure_warmup_log(path: Path) -> logging.Logger:
    """One logger, writing only to `warmup.log`, exactly as `zikaron.service.log`'s own
    `configure_service_log` sets up `service.log` — a dedicated `FileHandler` on this path alone,
    never the root logger, so this helper cannot accidentally emit anything to whatever
    stdout/stderr it was spawned with (`subprocess.DEVNULL` on `spawn_warm.py`'s side makes that
    moot in practice, but the logger's own configuration should not depend on that detail holding).

    Idempotent-enough for the process's own lifetime, mirroring `configure_service_log`'s own
    stated assumption exactly: this is called once, at the top of `run()`, before anything logs.

    `architecture.md` §"Filesystem security" states `warmup.log` at mode `0600`, identically to
    `service.log` and `hook.log` — created that way here rather than left to the umask, and
    tightened if an existing file were found wider (mirroring `configure_service_log`'s own
    `touch`-then-`chmod` sequence, since `logging.FileHandler` itself has no mode parameter for a
    newly created file).
    """
    path.touch(exist_ok=True)
    current_mode = stat.S_IMODE(path.stat().st_mode)
    if current_mode != _FILE_MODE:
        path.chmod(_FILE_MODE)
    logger = logging.getLogger("zikaron.hook.warm_helper")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def run(sock_path: Path, store_dir: Path) -> None:
    """Warm the service for this store: start it if absent, wait for it to answer `health()`,
    log the outcome. Never raises past its own attempt — this process's own exit code is not
    observed by anything, and a traceback on stderr from a detached, `stderr=DEVNULL`-spawned
    child would go nowhere useful anyway, so every failure this function can have, including one
    in its own setup, is caught and logged instead of propagating.

    **Securing `store_dir` runs in its own leading failure boundary, before anything else**,
    because `_configure_warmup_log`'s own `Path.touch()` needs that directory to exist — the
    ordinary first-ever session, where `.zikaron/` does not exist yet, is exactly the case this
    helper is warming *for*. Configuring the log before this directory is secured would let a
    fresh project's own `FileNotFoundError` crash the detached helper silently, before it ever
    attempted the one thing it exists to do: start-if-absent for a store that had never been
    started. `ensure_store_dir` is the identical helper `zikaron.core.store.store.Store.create`
    and `zikaron.hook.failure.record_failure` both already call for the same reason, so this
    helper's own directory creation cannot disagree with either about what "exists correctly"
    means. This step's own failures have nowhere to log to yet —
    the logger this function's own second half writes to does not exist until this step
    succeeds — so they are silently absorbed rather than reported, which is the one case in this
    file where a failure genuinely leaves no trace anywhere.
    """
    try:
        ensure_store_dir(store_dir)
        logger = _configure_warmup_log(warmup_log_path(store_dir))
    except Exception:
        # A detached process nothing awaits simply stops here — see this function's own
        # docstring for why a failure at this specific step has nowhere left to log to.
        return
    try:
        store_db = store_db_path(store_dir)
        _sock, _health = connect_start_if_absent(
            sock_path,
            store_db_path=store_db,
            store_id=None,
            server_command=default_server_command(sock_path, store_dir),
        )
        _sock.close()
        # A fixed status label only, per `architecture.md`'s filesystem-security table:
        # `warmup.log` "log[s] only a fixed failure-kind label and an error code, never prompt or
        # memory content" — a rule stated for the file as a whole, not only its failure lines,
        # and one `health.store_path`/`health.store_id` would violate directly since neither is
        # a label or a code.
        logger.info("service_warm")
    except Exception:
        # `architecture.md` §"Filesystem security" states `warmup.log` "log[s] only a fixed
        # failure-kind label and an error code, never prompt or memory content" — the same
        # guarantee `hook.log` gives, and `logger.exception` would break it, since it records
        # the full traceback and message text of whatever failed, which is not a fixed label.
        # Nothing this helper's own call chain touches is expected to hold a secret, but keeping
        # the guarantee uniform across every log this design names is worth more than the extra
        # diagnostic detail a traceback would add to a file nothing automated ever reads.
        logger.error("warm_failed")  # noqa: TRY400 — deliberately not `.exception`, per above.


def main(argv: list[str] | None = None) -> None:
    """Invoked as `python -m zikaron.hook.warm_helper <sock_path> <store_dir>` — the exact argv
    `spawn_warm.py` builds when it spawns this module detached.
    """
    args = sys.argv[1:] if argv is None else argv
    sock_path = Path(args[0])
    store_dir = Path(args[1])
    run(sock_path, store_dir)


if __name__ == "__main__":
    main()
