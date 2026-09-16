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
rather than on whatever it would resolve for itself. Everything else it inherits — the environment,
so that it reads the same configuration layers the parent read, and the working directory, which
nothing it does depends on but which is cheaper to leave alone than to argue about.

**Its output goes nowhere, and that is the trade.** A build that fails after detaching is visible as
a fact rather than as a reason: its corpus keeps reporting that it has not been built, and the lock
it took names a process that is no longer running. The reason is recovered by running the same
command in the foreground, which is what the indexer's own entry point is for. The alternative — a
log file per knowledge base — is several concurrent writers and a retention policy, bought for a
diagnostic that one re-run produces on demand.
"""

import subprocess
import sys
import threading
from pathlib import Path

#: The command the child runs. Spelled once, as the module path a build is documented under, so the
#: spawn and the entry point cannot come to disagree about which one exists.
_MODULE = "zikaron.knowledge.indexer"


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


def spawn(name: str, *, project: Path, full: bool = False) -> list[str]:
    """Start a build of `name` and return without waiting for it.

    Args:
        name: which knowledge base to build, as the registry stores it.
        project: the project whose store to act on, already resolved by the caller.
        full: reindex every admitted file rather than only what changed.

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
    process = subprocess.Popen(  # noqa: S603 — a fixed argv this process constructed, whose one
        # variable part is passed as an argument vector with no shell involved.
        argv,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # A new session gives the child no controlling terminal and its own process group; it does not
    # reparent it, so this process stays its parent for as long as it lives. A short-lived caller
    # exits first and the child is reparented then — but a long-lived one that never waited would
    # accumulate a zombie per build, so the wait happens on a daemon thread: it reaps without
    # blocking here, and without keeping the caller alive past its own work.
    threading.Thread(target=process.wait, daemon=True).start()
    return argv
