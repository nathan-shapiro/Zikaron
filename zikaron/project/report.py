"""How a typed command turns a predictable failure into a status and a sentence.

Shared by every `zikaron` subcommand that reaches the service, because the failures are the
connection's rather than any one verb's: no service reachable, a store this build cannot open, a
socket path that will not fit. A second copy of this ladder would drift, and the branch that would
drift first is the one nothing obvious reaches.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import aiosqlite

from zikaron.core.errors import ZikaronError
from zikaron.knowledge.client import ServiceRefusalError, ServiceVersionError
from zikaron.mcp.connection import AmbiguousMutationError
from zikaron.project.messages import render, stderr


def execute(work: Callable[[], Coroutine[Any, Any, int]]) -> int:
    """Run one command's asynchronous body, reporting anything predictable it raises.

    A refusal the service sent is rendered from its own code's declared disposition, so a typed
    command and `zikaron-mcp` cannot disagree about whether a caller has a move; a service of
    another version is refused here with the remedies its own refusal names. The remainder
    arrives as an exception raised while *establishing* the connection, before any request existed
    — except `AmbiguousMutationError`, which is the service dying after one was sent.
    """
    try:
        return asyncio.run(work())
    except (ServiceRefusalError, ServiceVersionError) as refusal:
        stderr(refusal.render())
    except ZikaronError as error:
        render(error)
    except (OSError, ConnectionError, aiosqlite.Error, AmbiguousMutationError) as error:
        # `aiosqlite.Error` is not covered by the two above and is genuinely reachable: the
        # identity read `ServiceConnection` performs opens the store, and a `memory.db` that is
        # not a database fails at the first pragma as a bare `sqlite3.DatabaseError`.
        # `AmbiguousMutationError` is the service dying mid-request, which `mcp/primary.py` also
        # catches; uncaught it is a traceback where a person needs a sentence.
        stderr(f"failed: {error}")
    return 1
