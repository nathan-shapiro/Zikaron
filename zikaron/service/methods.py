"""What each RPC method is to the dispatcher: its handler, and whether it reads or writes.

`architecture.md` §"The service's connections" is normative. The classification decides which
connection a request gets: a read leases a pool connection for its handler's span, and a write runs
on the writer, whose transactions the primitive serializes. A method is a write if it can write
`memory.db` other than the event rows it emits about itself, whatever its name suggests —
`memory_fetch` mints receipts.

Declared beside each handler in its dispatch module's table, so a method cannot arrive unclassified.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from zikaron.core.errors import ZikaronError
from zikaron.core.store.deadline import Deadline
from zikaron.service.params import Handler


class Access(Enum):
    """Which connection a method's handler runs on."""

    READ = "read"
    WRITE = "write"


def _service_budget(_params: dict[str, object]) -> Deadline:
    return Deadline.budget()


#: How a method names a failure to obtain its connection that is a fact about the filesystem: the
#: wire error it becomes, or `None` to answer it `internal_error` as a memory verb does.
type StoreFailure = Callable[[str, OSError], ZikaronError | None]


def _unnamed(_method: str, _error: OSError) -> None:
    return None


@dataclass(frozen=True, slots=True)
class Method:
    """One dispatch-table entry.

    `deadline` reads the request's own deadline from its parameters, before any connection is
    obtained, so the wait for that connection is bounded by a value validation has accepted. Every
    method but `memory_surface` takes the service's budget.
    """

    handler: Handler
    access: Access
    deadline: Callable[[dict[str, object]], Deadline] = _service_budget
    store_failure: StoreFailure = _unnamed
