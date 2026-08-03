"""`hook.log`: exactly one line per failed `userPromptSubmit`, written without `logging`.

`architecture.md` §"Degraded modes": on any failure, the hook must log to `hook.log` — "a **direct
file write, not `logging`**: `open(path, "a")` and one `.write()` call, then close."
`coding-standards.md` §6 gives the number the rule rests on: `import logging` alone costs ~15 ms
on this machine, in the same range as the whole stdlib-thinness argument the hook exists to
satisfy, and a process that writes one line and exits has no log lifecycle for `logging`'s
formatters and handlers to manage.

`hook.log` is `0600` and this process's alone (`architecture.md` §"Paths"): never `service.log` or
`warmup.log`, and no other process shares this path, so the append below needs no cross-process
locking — the one property that would have made `logging.FileHandler` safe to use here in the
first place, and does not hold for `service.log`/`warmup.log`'s multi-process cases either.
"""

import contextlib
import os
import time
from pathlib import Path

from zikaron.core.store.permissions import ensure_store_dir


def record_failure(hook_log_path: Path, kind: str, *, code: int | None = None) -> None:
    """Append one line naming `kind` (and `code`, if this failure carried a wire error code) to
    `hook_log_path`, creating both the file (at mode `0600`) and, if absent, its parent
    directory (at `0700`, symlink-refusing) as needed.

    **Ensuring the parent directory exists is required, not optional**, because this function is
    the hook's failure path and the most common way to reach it is a service that has never run
    for this project at all — the ordinary first-ever session, where `.zikaron/` does not exist
    yet either. Skipping that step would let `os.open`'s own `ENOENT` on a missing parent be
    swallowed by the same `except OSError` this docstring's next paragraph describes, making the
    very failure this function exists to make durable the one case guaranteed to be lost.
    `ensure_store_dir` is the identical helper `zikaron.core.store.store.Store.create` calls for
    the same directory — reused rather than reimplemented, so the hook's own directory creation
    cannot silently disagree with the service's about what "exists correctly" means (real
    directory, not a symlink, exactly `0700`).

    Never raises past its own attempt: this is the *last* thing a failure path does, called after
    every other action (the RPC attempt, any socket cleanup) has already failed or been abandoned,
    so a second failure here — the disk full, a permissions problem this process cannot fix — must
    not propagate and turn a silent degraded push into a crashing one. `architecture.md`'s own
    error table has no code for "the hook could not even log its own failure"; there is nothing to
    report it as, and nothing downstream is waiting for this call to succeed. Swallowing the
    failure here is therefore the one deliberate exception to `coding-standards.md` §7's "never
    swallow an exception silently" — the section's own text names it: "except in the hook, where
    the design requires exit 0... even there the failure goes to `hook.log`", and this is the
    function that tries to make that true, on a best-effort basis, when even that attempt does not
    land.

    The file is opened with `O_CREAT | O_APPEND`, not appended through `Path.open("a")`'s own
    higher-level call, and a **freshly created** file's mode is forced to exactly `0600` with
    `os.fchmod` after opening, rather than trusted to the `mode` argument `os.open` itself
    accepts. `os.open`'s `mode` parameter is **not** umask-independent — POSIX `open(2)` applies
    `mode & ~umask`, so a restrictive process umask (an unusual but legal `0600`, say) can leave a
    newly created file at `0000` even though `0o600` was passed — confirmed directly on this
    machine rather than assumed.
    `os.fchmod` on the already-open descriptor sets the mode outright, independent of umask,
    closing that gap. **Creation is detected with `O_EXCL` first** — attempted before the
    ordinary `O_CREAT | O_APPEND` open — specifically so the `fchmod` step only ever runs on a
    file this exact call created: an *existing* `hook.log` must keep whatever mode it already
    has, per this function's own stated contract below, and `fchmod`-ing it back to `0600` on
    every append would silently re-tighten a mode an operator had deliberately widened.
    """
    line = _format_line(kind, code=code)
    with contextlib.suppress(Exception):
        # Never narrowed to `OSError` alone: `ensure_store_dir` raises `ZikaronError` — a plain
        # `Exception`, not an `OSError` subclass — for a hostile or symlinked `.zikaron`, and that
        # failure must be swallowed here exactly like any other, per this function's own contract
        # that it is the *last* thing a failure path does and must never itself become the reason
        # a degraded push crashes instead of relaying.
        ensure_store_dir(hook_log_path.parent)
        try:
            fd = os.open(str(hook_log_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # The ordinary case after the first failure of a session: append without touching
            # the mode, per this function's own contract — an existing file keeps whatever mode
            # it already has.
            fd = os.open(str(hook_log_path), os.O_APPEND | os.O_WRONLY)
        else:
            # This call won the creation race: force the exact mode now, on the descriptor this
            # process itself just opened, before any content is written to it.
            os.fchmod(fd, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)


def _format_line(kind: str, *, code: int | None) -> str:
    """One newline-terminated line: an ISO-8601 UTC timestamp, the failure kind, and the wire
    error code when this failure carried one.

    Deliberately excludes anything from the prompt or a memory record: `architecture.md`
    §"Filesystem security" states plainly that `hook.log` "log[s] only a fixed failure-kind label
    and an error code, never prompt or memory content, so neither can hold a leaked secret" — a
    guarantee this function keeps by construction, since its only inputs are the failure
    classification and an optional integer, never the prompt text or any RPC response body.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if code is None:
        return f"{timestamp} {kind}\n"
    return f"{timestamp} {kind} {code}\n"
