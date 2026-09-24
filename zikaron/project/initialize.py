"""`zikaron init` — create this project's store, the only typed command that may.

Why it is a command of its own rather than a flag, and why every `knowledge` verb refuses a
project with no store: `design/distribution.md` §"The front door" is normative.

**It creates nothing itself.** Starting the service is what creates a store — `Store.create` needs
the embedding artifact for the vector width, which no command-line process holds — so this asks for
a service and then checks what appeared.

**The artifact is fetched on the creating run alone.** That run waits for it inside the poll
deadline and can exit 1 past it while the service goes on fetching; a run against a store that is
already there takes `Store.open`, where the encoder loads behind an already-bound socket, so a
deadline miss there is never the fetch. `_after_the_deadline` says whichever is true, and
`FINDINGS.md` Q17 is whether the budget is right.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from zikaron.core.errors import ZikaronError
from zikaron.knowledge.client import connected
from zikaron.project.report import execute, render, stderr
from zikaron.project.resolve import (
    MODULE_INITIALIZE,
    Project,
    nearest_store_above,
    resolve,
)
from zikaron.service import paths


def main(argv: Sequence[str] | None = None, *, prog: str = MODULE_INITIALIZE) -> int:
    """Create this project's store if it has none. Returns a process exit status."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Create this project's Zikaron store, so the commands that need one can run.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project to initialize. The default is the harness's own project directory "
        "where it names one, else the current directory.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        project = resolve(args.project)
    except ZikaronError as error:
        render(error)
        return 1
    if not project.directory.is_dir():
        # `ensure_store_dir` is `mkdir(parents=True)`, so without this a mistyped `--project`
        # builds the whole tree and a store inside it — and the verbs' own refusal ends by
        # offering this command, which would turn their typo into a second store by the route
        # that refusal exists to close.
        stderr(f"refused: {project.directory} is not a directory (resolved from {project.origin})")
        return 1
    # Deliberately no short-circuit on `has_store`. A `memory.db` the service cannot open — a
    # 0-byte file an extension failure or a kill inside the DDL leaves behind — is a file, so a
    # check that stopped here would report *ready* for a project permanently broken. Connecting
    # anyway puts the identity read in front of it, which reports it by disposition exactly as a
    # verb would, and costs at most the service start the next command pays regardless.
    return execute(lambda: _create(project, prog=prog, existed=project.has_store))


async def _create(project: Project, *, prog: str, existed: bool) -> int:
    """Start the service against `project` and report what is there afterwards.

    `existed` is whether a store was already present when the command began, and it decides only
    the wording — the call is made either way, so a store the service cannot open is refused here
    rather than reported as ready.

    The database is checked after the call rather than inferred from it: a service answering
    `health` has built its context, but the file is what every later command tests, and the two
    are separated by the window `has_store` documents.
    """
    if not existed:
        above = nearest_store_above(project.directory)
        if above is not None:
            # Not a refusal: a monorepo with a store per package makes this legitimate, and
            # nothing here binds what it found. But creating a second store is the defect the
            # verbs' own refusal exists to prevent, and this is the one command that reaches it by
            # design — so the reader is told while they are still looking.
            stderr(
                f"note: a store already exists at {above}; this would create a second one at "
                f"{project.store_dir}"
            )
    try:
        async with connected(project.directory) as client:
            await client.call("health", {})
    except ConnectionError as error:
        raise ConnectionError(
            f"{error}; {_after_the_deadline(project, prog=prog, existed=existed)}"
        ) from error
    if not project.has_store:
        stderr(f"failed: the service answered but no store is at {project.store_dir}")
        return 1
    _report("already initialized" if existed else "initialized", project)
    return 0


def _after_the_deadline(project: Project, *, prog: str, existed: bool) -> str:
    """What to try, given how far the service got and whether a store was already here.

    **A deadline miss has two causes no exception type separates**: a service still starting, and
    one that died inside its first start — offline with a cold cache, an unreadable `config.toml`,
    an extension that will not load. Advising a retry for both loops the second forever in the
    provisioning script this command exists for, so every wording keeps the retry and points at the
    log rather than claiming what is in it — a service that died before `configure_service_log` ran
    writes nothing, and on the `existed` path an earlier start's log is there saying nothing about
    this one. The log is on disk by the ordering `architecture.md` §"First run" chose so that a
    first-start failure would be diagnosable from it.
    """
    log = paths.service_log_path(project.store_dir)
    if not log.is_file():
        # The `touch` that would have made it is inside `.zikaron/`, and `ensure_store_dir` runs
        # before it and refuses a `.zikaron` that is a symlink — a refusal nothing else shows,
        # since the detached service's stderr goes to `DEVNULL`.
        target = project.store_dir if project.store_dir_exists else project.directory
        return (
            f"the service left no {log}, so it never reached its own logging — check that "
            f"{target} is writable and not a symlink — then run `{prog}` again"
        )
    if existed:
        # **No fetch clause on this path.** A store already here means the service takes the
        # *open* path, where the encoder loads on a background thread behind a socket that is
        # already bound, so the artifact cannot be what missed the deadline; only the create path
        # waits for it. Naming it would buy a re-run that fails the same way.
        return (
            f"the service did not answer before the deadline — run `{prog}` again in case it was "
            f"only slow; if it fails the same way, look in {log}"
        )
    return (
        f"the service may still be starting — on a cold model cache it is fetching the "
        f"embedding artifact — so run `{prog}` again; if it fails the same way, look in {log}"
    )


def _report(what: str, project: Project) -> None:
    """The two lines that say what happened and to which project.

    The rung is printed on success as well as in a refusal, because a store created against the
    wrong directory is the failure this command exists to make deliberate, and the moment to catch
    it is while the reader is still looking.
    """
    print(f"{what:<20} {project.store_dir}")
    print(f"{'resolved from':<20} {project.origin}")
