"""Which store a knowledge-base command acts on, how it opens it, and how a failure reads.

Shared by the management command and by the indexer, because both are commands over one store and
a second copy of this would let them disagree about which project they were pointed at — which is
a silent, destructive kind of disagreement: two stores, two registries, and a knowledge base that
exists to one command and not to the other.

**These commands open `memory.db` directly** rather than going through the service. Neither
is on a latency path, both run when no harness process need exist, and their writes are small
transactions — which is what WAL and `busy_timeout` are for. The service reads the same registry,
and writes it too on the management verbs, so this is concurrent access between two writers rather
than a table with a single owner. Requiring a service would make managing and building corpora
depend on a harness being live.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import (
    EffectiveConfig,
    default_system_config_path,
    project_config_path,
    resolve,
)
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge.errors import KnowledgeError, RegistryUnavailableError
from zikaron.core.store.store import Store
from zikaron.harness import detect
from zikaron.service import paths as service_paths


@dataclass(frozen=True, slots=True)
class OpenStore:
    """One project's store, open and ready for a knowledge-base verb.

    Carries the directory as well as the connection because the two are used for different things
    — the registry lives in the connection, and each knowledge base's own file lives under the
    directory — and a verb given one without the other could address a knowledge base belonging to
    a different store.

    `project` is the directory the store was derived *from*, kept because a command that starts a
    build has to tell the child which project to act on, and the child takes a project rather than
    a store. Passing the resolved value is what stops the two processes resolving differently.
    """

    project: Path
    directory: Path
    connection: aiosqlite.Connection
    config: EffectiveConfig


def project_scope(project: Path | None) -> Path:
    """Which project a command acts on.

    Resolved through the same harness seam both thin clients use, so a command and the agent's own
    tools address one store rather than two. An explicit project wins over the harness, since
    naming one is the caller saying they mean a different project from the one they are sitting in.
    """
    return project if project is not None else detect.current_spec().store_scope_dir(Path.cwd())


def configuration(store_dir: Path) -> EffectiveConfig:
    """The effective configuration for this store: the system layer, then the project's override."""
    return resolve(
        default_system_config_path(os.environ.get("XDG_CONFIG_HOME"), Path.home()),
        project_config_path(store_dir),
    )


@asynccontextmanager
async def open_store(project: Path | None) -> AsyncIterator[OpenStore]:
    """Open this project's store, and close it however the command ends.

    Opened through the store's own open path rather than by connecting to the file, so a command
    inherits every check that path runs — permissions, the symlink refusal, `meta` validation — and
    refuses a store this build cannot read instead of writing into it.

    **A store that will not open is reported as the registry being unavailable**, because that is
    what it means here: the list of knowledge bases lives in `memory.db`, so none of them is
    discoverable while it cannot be read, however intact each corpus's own database is. Saying so
    is the point — the failure this rules out is a command that answers *no knowledge bases*, which
    is a real answer for a project that has none and indistinguishable from this one.

    Raises:
        RegistryUnavailableError: the store's own database could not be opened or read.
    """
    scope = project_scope(project)
    directory = service_paths.store_dir(scope)
    config = configuration(directory)
    try:
        store = await Store.open(directory, config)
    except (aiosqlite.Error, OSError) as error:
        raise RegistryUnavailableError(
            f"the store at {directory} could not be read, so no knowledge base in this project "
            f"can be found: {error}"
        ) from error
    async with store:
        yield OpenStore(
            project=scope, directory=directory, connection=store.connection, config=config
        )


def execute(
    work: Callable[[], Coroutine[object, object, int]], *, printer: Callable[[str], None]
) -> int:
    """Run one command's work, turning every predictable failure into a status and a message.

    Returns a status rather than exiting, so a test can drive a whole command in-process and read
    both what it returned and what it printed.

    Args:
        work: builds the coroutine to run. A factory rather than a coroutine, so nothing is
            created until there is an event loop to run it on.
        printer: where a failure is reported. Commands write theirs to standard error.
    """
    try:
        return asyncio.run(work())
    except KnowledgeError as error:
        printer(f"refused: {error}")
    except ZikaronError as error:
        printer(f"refused: {error.message} ({error.detail()})")
    except (aiosqlite.Error, OSError) as error:
        # Every predictable refusal is raised above. This is the remainder — a full disk, a
        # revoked permission, a database that will not open — reported as a failed command rather
        # than as a traceback, which tells whoever ran it nothing they can act on.
        printer(f"failed: {error}")
    return 1
