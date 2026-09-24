"""How `zikaron knowledge` reaches the service, and how a rejection it sends becomes a printed line.

**The CLI is a thin client and opens no store of its own.** Every verb is an RPC call against the
same methods `zikaron-mcp` calls, so the two surfaces cannot come to disagree about what a verb
means. **A project with no store is `zikaron init`'s to create, and every verb here refuses before
it connects until one exists** — `zikaron/project/resolve.py` implements that and
`design/distribution.md` §"The front door" says why. `zikaron doctor` is the one command exempted
from the thin-client rule — it may open the store directly — because it reports on an installation
that may be broken in the way that stops the service starting.

**The one open it does make is `ServiceConnection`'s identity read**, read-only and shared with
`zikaron-mcp` — **not with the hook**, whose check stays path-only because it may never read the
store at all (`architecture.md` §"Store identity is verified, not assumed"). It reads `memory.db`'s
`meta.store_id` and checks it against the service's own on every connect that finds `memory.db`
already there, which is every one but the first in a project's life. It is refused for the same
reasons the service's own start would be, which is why `REINDEXING`, `SCHEMA_INCOMPATIBLE`,
`BAD_CONFIG` and a driver error reach this command at all.

**`ServiceConnection` is reused rather than reimplemented.** It already carries the retry, the store
identity check and the session label every client of it adopts — this command included, which is the
point of reusing it rather than writing a third transport; `hook/connect.py`'s stdlib-only
`connect_once` is *not* the thing to reuse, since that exists for the hook's own deadline contract,
which a command at a shell is not under.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from zikaron.core.errors import ERROR_SPECS, Disposition, ErrorCode
from zikaron.core.events import ClientKind
from zikaron.mcp.connection import ServiceConnection
from zikaron.service.rpc import WireError, parse_response

CLIENT_KIND: Final = ClientKind.CLI.value


class ServiceRefusalError(Exception):
    """A rejection the service sent, carried as the wire states it.

    Not a `ZikaronError`: reconstructing one would re-validate the payload against this build's own
    contract, so a service newer than this client would turn a readable rejection into a crash over
    a field this build has never heard of.

    **An ordinary class rather than a frozen dataclass**, because exception machinery assigns
    `__cause__` and `__traceback__` on the instance: a `frozen=True, slots=True` dataclass refuses
    those writes, and under `slots=True` fails with a `super()` mismatch rather than a clear one.
    """

    def __init__(self, *, code: int, message: str, data: Mapping[str, object]) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"zikaron error {code}: {message}")

    @property
    def disposition(self) -> Disposition:
        """Whether the caller has a move, per the code's own declaration.

        A code this build does not know is `FAILED`, which is the honest reading: nothing here can
        say what a caller might do about a rejection it cannot name.
        """
        try:
            return ERROR_SPECS[ErrorCode(self.code)].disposition
        except ValueError:
            return Disposition.FAILED

    def render(self) -> str:
        """The one line this refusal prints, prefixed by what it is.

        The payload is `name=value` per field, matching `ZikaronError.detail` rather than
        interpolating a dict, whose repr reads as a traceback fragment.
        """
        detail = ", ".join(f"{name}={value}" for name, value in self.data.items())
        suffix = f" ({detail})" if detail else ""
        return f"{self.disposition.value}: {self.message}{suffix}"


class KnowledgeClient:
    """One connection to this project's service, for the life of one command."""

    def __init__(self, connection: ServiceConnection, project: Path) -> None:
        self._connection = connection
        #: The directory whose store this command acts on, carried so an empty answer can name it:
        #: under D17 a command typed one level too deep addresses a project of its own — refused
        #: before the connection when that project has no store, and answered from when it has one.
        self.project = project

    async def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """Send one request and return its result object.

        Raises:
            ServiceRefusalError: the service answered with an error object.
            TypeError: the response was neither a well-formed result nor a well-formed error,
                which is a defect in the service rather than a rejection.
        """
        envelope = self._connection.envelope(kind=CLIENT_KIND)
        response = await self._connection.request(method, params, envelope=envelope)
        parsed = parse_response(response)
        if isinstance(parsed, WireError):
            raise ServiceRefusalError(code=parsed.code, message=parsed.message, data=parsed.data)
        if not isinstance(parsed, dict):
            raise TypeError(f"{method} answered with {type(parsed).__name__}, not an object")
        return parsed


@asynccontextmanager
async def connected(project: Path) -> AsyncIterator[KnowledgeClient]:
    """A client for `project`'s service, starting one if none is listening, closed however it ends.

    Starting a service is the ordinary case rather than a fallback: a project with no store has no
    service, and the first call is what creates both.

    **On a cold model cache that first call can report no reachable server, and a second succeeds.**
    The socket binds only once the context is built, building it creates the store, and creating one
    needs the embedding artifact — a 64 MB fetch when nothing has cached it. The poll deadline is
    `lifecycle._HEALTH_POLL_DEADLINE_SECONDS`; past it this client gives up while the service keeps
    starting. `knowledge-index.md` §9 carries the measurement and what is still open about it.
    """
    connection = ServiceConnection(project)
    try:
        yield KnowledgeClient(connection, project)
    finally:
        connection.close()


def relative_to_shell(path: Path) -> str:
    """One `--path` argument as the service must receive it: absolute.

    **The two sides mean different things by a relative path and both are right.** At a shell it is
    relative to the working directory the person typed it from; over RPC `dispatch_knowledge`
    resolves it against the project root, because the service's own working directory is inherited
    from whichever client happened to spawn it and names nothing a caller can see. Sent unresolved,
    a relative `--path` would create a corpus over a directory nobody named, report `ok`, and answer
    searches from it — wrong, permanent, and silent, since the stored root is absolute and looks
    deliberate.

    A leading `~` is passed through untouched, to be expanded where every other path this system
    accepts is expanded; joining it to the cwd first would produce a path that expands to nothing.
    """
    written = str(path)
    if written.startswith("~"):
        return written
    return str(Path.cwd() / path)
