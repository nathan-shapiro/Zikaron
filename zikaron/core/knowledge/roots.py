"""What can be established about a corpus root before anything is built over it.

Two questions, both answered from the filesystem and from git rather than from configuration:
is this path a root a corpus may legitimately have, and will the requested `git_mode` actually
take effect there.

**The root is the one caller-supplied string in this system with any path semantics at all** — a
knowledge base's *name* has none, because the registry generates the filename. So this is the only
module where a supplied string is validated as a path, and the validation is deliberately narrow:
a corpus root outside the project directory is a legitimate use (a docs tree, a vendored
dependency), so the rule rejects only roots that are degenerate rather than merely distant.
"""

import asyncio
import subprocess
from pathlib import Path

from zikaron.core.knowledge.errors import InvalidRootError
from zikaron.core.knowledge.meta import GitMode

#: How long the one synchronous git probe may take before it is treated as no answer. Generous
#: against a sub-millisecond call, and present at all because a hung `git` on a network filesystem
#: would otherwise hang the command a person is waiting on.
_PROBE_TIMEOUT_SECONDS = 5.0


def validate_root(path: Path, *, home: Path) -> Path:
    """The resolved corpus root, or a refusal naming what is wrong with it.

    Resolution happens **before** the degenerate-root test, so a symlink pointing at `/` is
    refused rather than admitted under its own name.

    Args:
        path: the root as supplied.
        home: the user's home directory, passed rather than read from the environment so a test
            states the home it is checking instead of mutating the process's.

    Raises:
        InvalidRootError: the path does not exist, is not a directory, or resolves to the
            filesystem root or to the home directory itself — both of which would index a machine
            rather than a corpus. A directory *inside* the home directory is fine, and common.
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise InvalidRootError(f"{path} does not exist")
    if not resolved.is_dir():
        raise InvalidRootError(f"{path} is not a directory")
    if resolved == Path(resolved.anchor):
        raise InvalidRootError(f"{path} resolves to the filesystem root, which is not a corpus")
    if resolved == home.expanduser().resolve():
        raise InvalidRootError(f"{path} resolves to the home directory, which is not a corpus")
    return resolved


def _inside_work_tree(root: Path) -> bool:
    """Whether `git` reports `root` as inside a work tree.

    Every failure is one answer — *no* — rather than an enumeration of causes, which is the same
    rule the scan itself degrades under and it bites here for the same reason. `git` missing from
    `PATH`, a directory that is not a repository, and a `safe.directory` refusal inside a
    container all return different things, and the last is the common modern case that an
    enumeration of the first two would classify wrongly. Anything that is not a clean exit 0
    saying `true` is therefore not an answer that git is available here.
    """
    try:
        # A fixed argument vector with no shell and no caller value in it; `git` is
        # resolved from `PATH`, which is what makes this the same git the operator uses.
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "true"


async def effective_git_mode(root: Path, requested: GitMode) -> GitMode:
    """The `git_mode` that will actually apply at `root`, which may be weaker than the one asked
    for.

    Outside a git work tree, `tracked` and `all` both degrade to `off`. That case is ordinary
    rather than exotic: the default is `tracked` while indexing a docs tree outside any repository
    is an endorsed use, so a caller that was not told would discover it as a silently different
    corpus.

    The probe is run here, synchronously, purely so a caller learns at creation time that its
    choice will not take effect. It is not the authority afterwards — what explains an *indexed
    corpus* is the mode the build that produced it actually used, which that build records.
    """
    if requested is GitMode.OFF:
        return GitMode.OFF
    inside = await asyncio.to_thread(_inside_work_tree, root)
    return requested if inside else GitMode.OFF
