"""The builds this service spawned that have not yet shown themselves by their corpus's lock.

`knowledge-index.md` §8.4 is normative, and invariant 19 is what this holds. A build loads its model
before it takes its corpus's lock, so for about a second after its spawn nothing in the corpus says
it is running; going by the lock alone, a `refresh` arriving then would spawn a second build. So the
service remembers, per corpus id, the process it last spawned and the corpus's
`last_scan_started_at` as the spawning call read it. While that process is alive and the mark is
unchanged, the build is under way and has not reached its lock. A build writes its mark in the
transaction that takes the lock, so once the mark has moved the lock decides, and the entry is
dropped.

**Liveness is the process handle's own `poll()`, never a probe of the pid**, so a recycled number
cannot keep an entry alive. **Keyed by id**, because a rename touches no file and a build may be
alive across one. Only what this service spawned is visible here: a build run by hand, or one a
previous service spawned, shows itself only by its lock.
"""

from dataclasses import dataclass
from uuid import UUID

from zikaron.core.clock import timestamp
from zikaron.core.knowledge import lock
from zikaron.knowledge.indexer.detach import BuildProcess


@dataclass(frozen=True, slots=True)
class _Spawned:
    process: BuildProcess
    mark: str | None
    holder: lock.LockHolder


class SpawnedBuilds:
    """Per corpus id, the build this service last spawned for it.

    Every method is synchronous, so a caller that consults the table, spawns and records with
    nothing awaited between them has made one step of the three: of two concurrent calls for one
    corpus, the second sees what the first recorded.
    """

    def __init__(self) -> None:
        self._by_id: dict[UUID, _Spawned] = {}

    def __len__(self) -> int:
        """How many builds are remembered: at most one per corpus, live or recently finished."""
        return len(self._by_id)

    def loading(self, kb_id: UUID, *, mark: str | None) -> lock.LockHolder | None:
        """The holder of the build this service spawned for `kb_id`, while it has not yet taken the
        lock — its process alive, and `mark` still the `last_scan_started_at` read at its spawn.

        An entry whose process has exited, or whose mark has moved, is dropped.
        """
        spawned = self._by_id.get(kb_id)
        if spawned is None:
            return None
        if spawned.process.poll() is None and spawned.mark == mark:
            return spawned.holder
        del self._by_id[kb_id]
        return None

    def record(self, kb_id: UUID, process: BuildProcess, *, mark: str | None) -> None:
        """Remember a build just spawned for `kb_id`, and forget every one whose process has exited.

        The holder it is reported under is the process's pid, this host and this instant, which is
        what a person needs in order to find the process and what `remove` names when it refuses.
        """
        exited = [
            known for known, spawned in self._by_id.items() if spawned.process.poll() is not None
        ]
        for known in exited:
            del self._by_id[known]
        self._by_id[kb_id] = _Spawned(
            process=process,
            mark=mark,
            holder=lock.LockHolder(pid=process.pid, host=lock.this_host(), started_at=timestamp()),
        )
