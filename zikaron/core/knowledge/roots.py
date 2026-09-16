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

from pathlib import Path

from zikaron.core.knowledge import git
from zikaron.core.knowledge.errors import InvalidRootError
from zikaron.core.knowledge.meta import GitMode


def validate_root(path: Path, *, home: Path) -> Path:
    """The resolved corpus root, or a refusal naming what is wrong with it.

    Resolution happens **before** the degenerate-root test, so a symlink pointing at `/` is
    refused rather than admitted under its own name.

    Args:
        path: the root as supplied.
        home: the user's home directory, passed rather than read from the environment so a test
            states the home it is checking instead of mutating the process's.

    Raises:
        InvalidRootError: the path does not exist — which includes a `~` prefix naming no home
            directory this machine can find — or is not a directory, or resolves to the filesystem
            root or to the home directory itself, both of which would index a machine rather than a
            corpus. A directory *inside* the home directory is fine, and common.
    """
    try:
        expanded = path.expanduser()
    except RuntimeError as error:
        # `~someone` for a user this machine has no record of. `expanduser` hands the string back
        # unchanged and `Path` then refuses to say what it means, which is a caller's mistake
        # rather than a defect — so it is refused in the same terms as any other root that names
        # nothing, instead of travelling out as an internal error to a caller that typed a path.
        raise InvalidRootError(f"{path} does not exist", path=path) from error
    resolved = expanded.resolve()
    if not resolved.exists():
        raise InvalidRootError(f"{path} does not exist", path=resolved)
    if not resolved.is_dir():
        raise InvalidRootError(f"{path} is not a directory", path=resolved)
    if resolved == Path(resolved.anchor):
        raise InvalidRootError(
            f"{path} resolves to the filesystem root, which is not a corpus", path=resolved
        )
    if resolved == home.expanduser().resolve():
        raise InvalidRootError(
            f"{path} resolves to the home directory, which is not a corpus", path=resolved
        )
    return resolved


def missing_root_message(root: Path) -> str:
    """What a caller is told when the directory a corpus indexes has gone.

    One wording for the two places that refuse it — the command that was asked for a build, and the
    build itself — because they refuse the same condition and a reader who met both should not have
    to work out whether they mean the same thing.
    """
    return f"{root} is gone, so there is nothing to index; the existing index is kept as it is"


async def effective_git_mode(root: Path, requested: GitMode) -> GitMode:
    """The `git_mode` that will actually apply at `root`, which may be weaker than the one asked
    for.

    Outside a git work tree, `tracked` and `all` both degrade to `off`. That case is ordinary
    rather than exotic: the default is `tracked` while indexing a docs tree outside any repository
    is an endorsed use, so a caller that was not told would discover it as a silently different
    corpus.

    Probed at creation, so the caller learns immediately that its choice will not take effect
    there, and again at the start of every build, whose opening transaction persists the answer as
    the mode that build began under.

    **Neither answer is the authority on an indexed corpus afterwards.** What explains one is the
    effective mode the build that produced it actually ran under — which a degradation discovered
    later in the walk may weaken further, and which that build rewrites when it does.
    """
    if requested is GitMode.OFF:
        return GitMode.OFF
    return requested if await git.inside_work_tree(root) else GitMode.OFF
