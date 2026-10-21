"""Starting a build that outlives whoever asked for it.

A build is minutes of saturated CPU over a whole directory tree, and every surface that can ask for
one — a person at a shell, and an agent through a tool call — needs to be free the moment it has
asked. So the build runs as its own process, in its own session, with no controlling terminal and
nothing to read from.

**This lives beside the command it starts, not in the library.** The argv is the indexer's own, and
a second module holding a copy of it is how a renamed option comes to fail only in production: the
spawn does not import the thing it runs, so nothing but a shared definition keeps the two agreeing.

**What the child is told, and what it is left to work out.** The project is passed explicitly,
because the parent has already resolved which store it means and the child must act on that one
rather than on whatever it would resolve for itself. The environment reaches it as a **copy** of
this process's, so it reads the same configuration layers the parent read — differing in what is
set per spawn rather than inherited: the attribution below, and unbuffered output, so that its two
streams reach the log in the order it printed them. The working directory is left alone: nothing
the child does depends on it, and leaving it is cheaper than arguing about it.

**Its output goes to the corpus's build log**, which `status` names, because a build that fails
after detaching has nobody watching it and a reason recorded nowhere else. The log is emptied at
each spawn, so it holds the latest build alone and needs no retention, and opened to append as
well, because two children can write it for a moment — the previous build still printing its
last lines after releasing the corpus's lock when the next is spawned, or a restarted service
spawning beside a child it does not know of — and appended lines land after one another where
positioned ones overwrite.

**One thing travels in the environment rather than the argv.** The spawning call's `op_id` is not
an input that changes what a build does, only an attribution the build's own event row carries, so
it has no place on the command line. The variable is declared here, beside the argv this module
already owns, and the child reads it through this same constant: the entry point may import the
spawner for it, which is the one direction this module otherwise forbids.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Final, Protocol

#: The command the child runs. Spelled once, as the module path a build is documented under, so the
#: spawn and the entry point cannot come to disagree about which one exists.
_MODULE = "zikaron.knowledge.indexer"

#: Where the spawning call's `op_id` reaches the child. Without the edge nothing joins a build's
#: cost to its requester, since the build mints a label of its own and only the spawning `call` row
#: knows whether an agent or a person asked.
SPAWNED_BY_OP_ID_VARIABLE: Final = "ZIKARON_SPAWNED_BY_OP_ID"

#: A child's stdout to a file is block-buffered and its stderr is not, so without this a line it
#: wrote to stderr could land in the log ahead of stdout lines it had printed before it.
_UNBUFFERED_VARIABLE: Final = "PYTHONUNBUFFERED"

#: The store's own file mode: a build's output names the paths it indexed and the reasons it failed.
_LOG_MODE: Final = 0o600


def spawned_by_op_id() -> str | None:
    """The `op_id` of the verb that spawned this build, or `None` if nothing set one.

    `None` is the ordinary answer for a build run by hand, which nothing sets the variable for.
    """
    return os.environ.get(SPAWNED_BY_OP_ID_VARIABLE)


class BuildProcess(Protocol):
    """A started build as its spawner watches it: its pid, and whether it has exited."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None:
        """The exit status once the process has exited, `None` while it runs."""
        ...


def command(name: str, *, project: Path, full: bool) -> list[str]:
    """The argv a detached build is started with.

    The knowledge-base name goes after `--`, because a name is free-form: nothing stops one
    beginning with a dash, and without the separator such a name would be read as an option and the
    build would die on its own arguments before opening anything. `-P` keeps the working directory
    off `sys.path`, as `service.lifecycle.default_server_command` says.
    """
    argv = [sys.executable, "-P", "-m", _MODULE, "--project", str(project)]
    if full:
        argv.append("--full")
    argv.extend(["--", name])
    return argv


def open_log(log: Path) -> int:
    """A descriptor on `log`, emptied and appending, at `0600` whatever mode it was found at.

    Raises:
        OSError: the file could not be created or opened.
    """
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, _LOG_MODE)
    # The mode `os.open` is given reaches only a file it creates; one left at a wider mode keeps
    # that mode through being emptied.
    os.fchmod(descriptor, _LOG_MODE)
    return descriptor


def spawn(
    name: str,
    *,
    project: Path,
    log: Path,
    full: bool = False,
    spawned_by_op_id: str | None = None,
) -> BuildProcess:
    """Start a build of `name` and return without waiting for it.

    Args:
        name: which knowledge base to build, as the registry stores it.
        project: the project whose store to act on, already resolved by the caller.
        log: where the child's stdout and stderr go — emptied, then appended to, at `0600`.
        full: reindex every admitted file rather than only what changed.
        spawned_by_op_id: the `op_id` of the call asking for this build, for the build's own event
            row to attribute itself by. Passed as a **per-spawn copy of the environment, never an
            assignment into this process's own**: a long-lived service spawning many builds would
            otherwise attribute every later one to the first caller, and the row would look complete
            while being wrong. The copy **omits** the variable when none is given rather than
            inheriting one, or a service started from a shell that exported it would attribute every
            unattributed build to that value.

    Returns:
        The child's handle, whose `poll()` answers `None` until the reaper below has collected the
        child and its exit status after.

    Raises:
        OSError: the log could not be opened, or the child could not be started at all — no
            interpreter, no permission. Raised rather than swallowed, because the caller has just
            told somebody a build is running and nothing else would ever correct that.
    """
    argv = command(name, project=project, full=full)
    child_environment = dict(os.environ)
    child_environment.pop(SPAWNED_BY_OP_ID_VARIABLE, None)
    if spawned_by_op_id is not None:
        child_environment[SPAWNED_BY_OP_ID_VARIABLE] = spawned_by_op_id
    child_environment[_UNBUFFERED_VARIABLE] = "1"
    output = open_log(log)
    try:
        process = subprocess.Popen(  # noqa: S603 — a fixed argv this process constructed, whose
            # one variable part is passed as an argument vector with no shell involved.
            argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            env=child_environment,
        )
    finally:
        os.close(output)
    # A new session gives the child no controlling terminal and its own process group; it does not
    # reparent it, so this process stays its parent for as long as it lives. A short-lived caller
    # exits first and the child is reparented then — but a long-lived one that never waited would
    # accumulate a zombie per build, so the wait happens on a daemon thread: it reaps without
    # blocking here, and without keeping the caller alive past its own work.
    threading.Thread(target=process.wait, daemon=True).start()
    return process
