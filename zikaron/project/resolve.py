"""Which project a typed command acts on, and whether it has a store yet.

**D17 answers the first question and this module adds only *which rung answered*.** The ladder is
unchanged — an explicit `--project`, then the harness's own project directory where it exports one,
then the working directory — but a refusal that cannot say where the directory came from cannot say
how to repair it: a wrong `CLAUDE_PROJECT_DIR` is not fixed by changing directory, and a mistyped
`--project` is not fixed by exporting one.

**Neither supported harness exports a project directory to a shell.** `CLAUDE_PROJECT_DIR` reaches
the hook and `zikaron-mcp` — the client a typed command has to agree with — but not the terminal a
person or an agent types in, and kiro names no such variable at all, so the fallback rung is what a
typed command resolves through in practice
(`research/claude-project-dir-reaches-hooks-not-shells.md`). That is why the rung is worth naming
in a message: it is the usual one, not the exotic one.

**Nothing here walks up to find a store to *use*.** `nearest_store_above` exists to name a store in
a refusal and is acted on nowhere. A monorepo holding a store per package is exactly where adopting
an ancestor's store would bind a command to the wrong one with nothing said, so the search stays on
the error path where its only power is to make a message specific.

Why the refusal exists at all: `design/distribution.md` §"The front door".
"""

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.harness import detect
from zikaron.service import paths

#: How a person reaches `init` when the console script is on `PATH`, and when only an interpreter
#: is. A refusal naming the wrong one is a command that fails for a reader already stuck.
CONSOLE_INITIALIZE: Final = "zikaron init"
MODULE_INITIALIZE: Final = "python -m zikaron.project"

#: The rungs a refusal names, and what it may advise under each. Moving is a remedy only under the
#: fallback: above it the directory does not come from where the command was typed, so a `cd`
#: resolves to the same place and refuses again. Naming `--project` is a remedy only when the
#: reader did not already pass one.
WORKING_DIRECTORY: Final = "the working directory"
EXPLICIT_PROJECT: Final = "--project"


@dataclass(frozen=True, slots=True)
class Project:
    """One directory, and the rung of D17's ladder that produced it."""

    directory: Path
    origin: str

    @property
    def store_dir(self) -> Path:
        """Where this project's store lives, whether or not anything is there."""
        return paths.store_dir(self.directory)

    @property
    def has_store(self) -> bool:
        """Whether a store has been created here.

        **The database, not the directory.** The service creates `.zikaron/` before it creates the
        store — `service/main.py` configures the log inside it ahead of `ServiceContext.assemble`
        — so every first start that fails or is still running leaves a directory with no
        `memory.db`. Keying on the directory would make `init` report that state as already
        initialized and let every verb past the check, and the service would then create the store
        behind whichever verb ran first — the defect this refusal exists to remove, with one more
        precondition in front of it.
        """
        return paths.store_db_path(self.store_dir).is_file()

    @property
    def store_dir_exists(self) -> bool:
        """Whether `.zikaron/` is there at all, which decides how a refusal reads."""
        return self.store_dir.is_dir()


def resolve(explicit: Path | None) -> Project:
    """Run D17's ladder, keeping the rung that answered.

    **An explicit path is resolved, not merely made absolute, and the difference is a defect.**
    `Path.absolute()` collapses neither `..` nor a symlink, and store identity is compared on
    *spellings*: the socket is keyed on the resolved path while `health.store_path` reports what
    the service was started with, so `--project ..` or a symlinked path starts a service the
    agent's own MCP server and hook then refuse with `store_identity` on every call until it idles
    out. `Path.cwd()` is already physical, which is what the fallback rung and the clients on it
    agree by. Whether the *harness's* value is physical is unmeasured — it is taken verbatim
    everywhere it is read — so a symlinked `CLAUDE_PROJECT_DIR` would reproduce the mismatch in the
    other direction (`architecture.md` §"Store identity is verified, not assumed"). Resolving also
    fixes `nearest_store_above`, whose `parents` would otherwise begin at a sibling.

    The service resolves nothing, outlives this shell, and stringifies the value into the
    `foreground` command a build result prints, which would act on a different project when pasted
    from elsewhere.

    **The rung is read from whether the variable answered, never from comparing directories.** A
    variable exported by hand to the directory the reader is standing in resolves to that directory
    and still came from the variable — so reporting the working directory there would advise a `cd`
    that resolves to the same place and refuses again, which is the loop `refusal` exists to avoid.

    Raises:
        ZikaronError: `--project` cannot be resolved — a symlink loop on 3.12, or an `OSError`
            such as a deleted working directory under a relative path, on every version.
    """
    if explicit is not None:
        try:
            return Project(explicit.resolve(), EXPLICIT_PROJECT)
        except (OSError, RuntimeError) as error:
            # **Both types, and which one arrives depends on the interpreter.** Measured across
            # the supported versions: 3.12 reports a symlink loop as `RuntimeError`, while 3.13 and
            # 3.14 resolve it without raising and return the unresolved path, which the `is_dir()`
            # check below then refuses. So what reaches this branch on 3.13+ is an `OSError` —
            # `os.getcwd()` failing inside `realpath` for a relative `--project` whose working
            # directory has been deleted is the reachable one.
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.DERIVED,
                key="store_dir",
                value=str(explicit),
                expected=f"a path this machine can resolve ({error})",
            ) from error
    spec = detect.current_spec()
    named = spec.named_project_dir()
    if named is not None:
        return Project(named, f"${spec.project_dir_variable}")
    return Project(Path.cwd(), WORKING_DIRECTORY)


def nearest_store_above(directory: Path) -> Path | None:
    """The closest ancestor holding a store, for a refusal to name. Binds nothing.

    The database rather than the directory, for the reason `has_store` gives: naming a `.zikaron/`
    that a failed first start left behind would send the reader somewhere that refuses too.
    """
    for ancestor in directory.parents:
        candidate = paths.store_dir(ancestor)
        if paths.store_db_path(candidate).is_file():
            return candidate
    return None


def refusal(project: Project, *, initialize: str) -> str:
    """What to print when a command needs a store and the resolved project has none.

    **Only routes that work under the rung that answered are offered.** Moving helps only under the
    fallback: above it the directory does not come from where the command was typed, so a `cd`
    resolves to the same place and refuses again. Naming `--project` helps only when the reader did
    not already pass one — telling somebody who did to pass one is the same loop.
    """
    lines = [
        f"refused: no Zikaron store in {project.directory}",
        f"         (resolved from {project.origin})",
        "",
    ]
    if project.store_dir_exists:
        # A directory with no database is what a first start that failed or was interrupted leaves
        # behind, so this reader is in the right project and repairing it. What a lost reader needs
        # — an ancestor to move to, a `--project` to correct — is wrong advice here, hence the
        # early return rather than falling through to it.
        lines.append(f"  {project.store_dir} exists but holds no store")
        lines.append(f"  `{initialize}` finishes what an interrupted first start left")
        return "\n".join(lines)
    found = nearest_store_above(project.directory)
    if found is not None:
        root = found.parent
        reach = f"  a store exists at {found}; reach it with --project {shlex.quote(str(root))}"
        if project.origin == WORKING_DIRECTORY:
            reach += f", or run this from {root}"
        lines.append(reach)
    elif project.origin == EXPLICIT_PROJECT:
        lines.append("  check the path given to --project")
    elif project.origin == WORKING_DIRECTORY:
        lines.append("  pass --project to name the project, or run this from its root")
    else:
        lines.append(f"  pass --project to name the project, or check {project.origin}")
    lines.append(f"  or `{initialize}` to create a store here")
    return "\n".join(lines)
