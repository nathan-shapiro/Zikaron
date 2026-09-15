"""Where a knowledge base's file lives, as pure functions of their inputs.

Every function takes what it needs as an argument rather than reading `os.environ` or
`Path.cwd()` itself, the same way `zikaron.service.paths` does — so a test states the layout it is
checking instead of mutating the process's.

**The security property this module carries: no caller-supplied string ever becomes a path
segment under `.zikaron/`.** It takes both halves to enforce. `knowledge_db_path`
takes a `UUID` rather than a string, so no caller-supplied name reaches a path under `.zikaron/`
even by mistake — but an annotation alone is a *static* promise, and this one was measured not to
hold at runtime: the filename is interpolated, and interpolation formats whatever it is handed, so
passing the string `"../memory"` produced `knowledge/../memory.db` and resolved straight onto the
memory store. The id is therefore re-parsed as a `UUID` when the path is built. For a real id that
round-trip is a no-op; for anything else it raises, which is what makes the property hold in the
code rather than only in a type checker that somebody remembered to run.
"""

from pathlib import Path
from uuid import UUID

_KNOWLEDGE_DIR_NAME = "knowledge"
_DB_SUFFIX = ".db"


def knowledge_dir(store_directory: Path) -> Path:
    """The directory holding every knowledge-base database for one store."""
    return store_directory / _KNOWLEDGE_DIR_NAME


def knowledge_db_path(store_directory: Path, kb_id: UUID) -> Path:
    """Where the knowledge base with this id lives.

    Args:
        store_directory: the `.zikaron` directory this store lives in.
        kb_id: the id the registry generated for this knowledge base.

    Raises:
        ValueError: `kb_id` is not a uuid. Re-parsed rather than trusted because interpolation
            formats whatever it is handed: the annotation stops a *typed* caller, and this stops
            the untyped one whose value would otherwise become path segments.
    """
    return knowledge_dir(store_directory) / f"{UUID(str(kb_id))}{_DB_SUFFIX}"


def orphan_candidates(store_directory: Path) -> tuple[Path, ...]:
    """Every file in the knowledge directory that could be a knowledge-base database.

    Sorted, and shaped by suffix alone — it does not ask the registry anything, because its
    caller is what compares the two. Returns nothing at all when the directory is absent, which
    is the ordinary state of a store with no knowledge bases rather than a condition to report.
    """
    directory = knowledge_dir(store_directory)
    if not directory.is_dir():
        return ()
    return tuple(sorted(path for path in directory.iterdir() if path.suffix == _DB_SUFFIX))
