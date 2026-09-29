"""Starting a build that outlives whoever asked for it.

A build is minutes of saturated CPU over a whole directory tree, and every surface that can ask for
one — a person at a shell, and an agent through a tool call — needs to be free the moment it has
asked. So the build runs as its own process, in its own session, with no controlling terminal and
nothing connected to its streams.

**This lives beside the command it starts, not in the library.** The argv is the indexer's own, and
a second module holding a copy of it is how a renamed option comes to fail only in production: the
spawn does not import the thing it runs, so nothing but a shared definition keeps the two agreeing.

**What the child is told, and what it is left to work out.** The project is passed explicitly,
because the parent has already resolved which store it means and the child must act on that one
rather than on whatever it would resolve for itself. The environment reaches it as a **copy** of
this process's, so it reads the same configuration layers the parent read — differing in the one
variable below, which is set per spawn rather than inherited. The working directory is left alone:
nothing the child does depends on it, and leaving it is cheaper than arguing about it.

**Its output goes nowhere, and that is the trade.** A build that fails after detaching is visible as
a fact rather than as a reason: its corpus keeps reporting that it has not been built, and the lock
it took names a process that is no longer running. The reason is recovered by running the same
command in the foreground, which is what the indexer's own entry point is for. The alternative — a
log file per knowledge base — is several concurrent writers and a retention policy, bought for a
diagnostic that one re-run produces on demand.

**One thing travels in the environment rather than the argv, and the channel is forced.** `spawn`
returns the argv the child ran and a verb prints that as the command to reproduce a build, so a flag
the printed form stripped would break that identity — while the spawning call's `op_id` is not an
input that changes what a build does, only an attribution the build's own event row carries. So the
variable is declared here, beside the argv this module already owns, and the child reads it through
this same constant: the entry point may import the spawner for it, which is the one direction this
module otherwise forbids.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Final

#: The command the child runs. Spelled once, as the module path a build is documented under, so the
#: spawn and the entry point cannot come to disagree about which one exists.
_MODULE = "zikaron.knowledge.indexer"

#: Where the spawning call's `op_id` reaches the child. Without the edge nothing joins a build's
#: cost to its requester, since the build mints a label of its own and only the spawning `call` row
#: knows whether an agent or a person asked.
SPAWNED_BY_OP_ID_VARIABLE: Final = "ZIKARON_SPAWNED_BY_OP_ID"


def spawned_by_op_id() -> str | None:
    """The `op_id` of the verb that spawned this build, or `None` if nothing set one.

    `None` is the ordinary answer for a foreground run, including a re-run of a printed
    `foreground_command`, since the token travels outside the argv.
    """
    return os.environ.get(SPAWNED_BY_OP_ID_VARIABLE)


def command(name: str, *, project: Path, full: bool) -> list[str]:
    """The argv a detached build is started with, for a caller that wants to show it to somebody.

    The knowledge-base name goes after `--`, because a name is free-form: nothing stops one
    beginning with a dash, and without the separator such a name would be read as an option and the
    build would die on its own arguments before opening anything.
    """
    argv = [sys.executable, "-m", _MODULE, "--project", str(project)]
    if full:
        argv.append("--full")
    argv.extend(["--", name])
    return argv


def spawn(
    name: str, *, project: Path, full: bool = False, spawned_by_op_id: str | None = None
) -> list[str]:
    """Start a build of `name` and return without waiting for it.

    Args:
        name: which knowledge base to build, as the registry stores it.
        project: the project whose store to act on, already resolved by the caller.
        full: reindex every admitted file rather than only what changed.
        spawned_by_op_id: the `op_id` of the call asking for this build, for the build's own event
            row to attribute itself by. Passed as a **per-spawn copy of the environment, never an
            assignment into this process's own**: a long-lived service spawning many builds would
            otherwise attribute every later one to the first caller, and the row would look complete
            while being wrong. The copy **omits** the variable when none is given rather than
            inheriting one, or a service started from a shell that exported it would attribute every
            unattributed build to that value.

    Returns:
        The argv the child was started with — what a caller shows somebody who has to reproduce
        this build in the foreground. Returned rather than rebuilt at the call site so that what is
        printed is what actually ran.

    Raises:
        OSError: the child could not be started at all — no interpreter, no permission. Raised
            rather than swallowed, because the caller has just told somebody a build is running and
            nothing else would ever correct that.
    """
    argv = command(name, project=project, full=full)
    child_environment = dict(os.environ)
    child_environment.pop(SPAWNED_BY_OP_ID_VARIABLE, None)
    if spawned_by_op_id is not None:
        child_environment[SPAWNED_BY_OP_ID_VARIABLE] = spawned_by_op_id
    process = subprocess.Popen(  # noqa: S603 — a fixed argv this process constructed, whose one
        # variable part is passed as an argument vector with no shell involved.
        argv,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_environment,
    )
    # A new session gives the child no controlling terminal and its own process group; it does not
    # reparent it, so this process stays its parent for as long as it lives. A short-lived caller
    # exits first and the child is reparented then — but a long-lived one that never waited would
    # accumulate a zombie per build, so the wait happens on a daemon thread: it reaps without
    # blocking here, and without keeping the caller alive past its own work.
    threading.Thread(target=process.wait, daemon=True).start()
    return argv
