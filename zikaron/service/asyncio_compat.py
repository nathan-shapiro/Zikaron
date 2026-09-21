"""The one place a difference between supported Python versions is allowed to live, as data.

Two `asyncio` behaviours differ across the versions this package supports, and both are load-bearing
for the service's shutdown path:

* **How many connections a server has attached.** 3.12 keeps an integer counter; 3.13 replaced it
  with a set of attached transports. Both are private, both are incremented and decremented at the
  same points in the accept pipeline, and there is no public accessor for the quantity in either.
* **Whether closing a Unix server unlinks its own socket file.** From 3.13, `create_unix_server`
  removes the socket path on close unless told not to. On its self-stop and signal paths this
  package unlinks the socket itself *before* closing the listener, so that a client arriving
  mid-shutdown finds nothing to connect to; a second unlinker would make that ordering meaningless
  wherever it holds. So the option is switched off wherever it exists. It does not exist on 3.12,
  where passing it raises `TypeError`.

Rows are keyed by the version that *introduced* a behaviour, not by every version supported, and a
lookup takes the greatest key not above the version asked about. So a release that changed neither
of these needs no row, and a release newer than anything this package has been tested on gets the
newest row — which means a further change to either private name surfaces as a loud failure on the
first shutdown rather than as a silent fallback.

**Rows rather than `if sys.version_info >= (3, 13):`, for a mechanical reason.** Type checking runs
against a single configured version, and a version comparison is evaluated at analysis time, so the
losing branch is skipped — silently, even with unreachable-code warnings on. Measured here with a
deliberate type error in each position: inside the `if`, unreported; inside the `else`, reported; in
both rows of a keyed table, reported. A branch would ship one row unchecked on every interpreter. So
this module contains no version comparisons outside `row_for`, whose two are on its *argument*
rather than on the running version — nothing to constant-fold, and both rows stay checked.

Nothing else in this package or its tests reads the running version or either private attribute; a
test enforces that by scanning the tree, and this module and that test are its only two exemptions.
"""

import asyncio
import platform
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

#: The lowest version any row covers. A lookup below it is refused by name rather than left to the
#: bare `max()` below, which would say "max() arg is an empty sequence" and name nothing. This is
#: for an explicit caller passing a literal: a below-floor *interpreter* cannot reach it, since the
#: package uses syntax those releases cannot parse and the packaging metadata refuses to install
#: there, so the lookup on the running version never sees one.
_FLOOR: Final = (3, 12)


def _count_by_active_count(server: asyncio.Server) -> int:
    """The integer counter, through 3.12."""
    return int(server._active_count)  # type: ignore[attr-defined]


def _count_by_clients(server: asyncio.Server) -> int:
    """The set of attached transports, from 3.13."""
    return len(server._clients)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class _Behaviour:
    """One row: everything that differs from the row below it.

    The server keyword arguments are held as a tuple of pairs rather than a mapping so that a caller
    handed the built value cannot mutate what every later caller gets.
    """

    attached_connection_count: Callable[[asyncio.Server], int]
    unix_server_kwargs: tuple[tuple[str, object], ...]


#: Keyed by the version that introduced each behaviour. 3.14 changed neither, so it has no row of
#: its own and resolves to 3.13's — adding a key here says "something changed in this release",
#: which is a different statement from "this release is supported".
_ROWS: Final[Mapping[tuple[int, int], _Behaviour]] = {
    (3, 12): _Behaviour(
        attached_connection_count=_count_by_active_count,
        unix_server_kwargs=(),
    ),
    (3, 13): _Behaviour(
        attached_connection_count=_count_by_clients,
        unix_server_kwargs=(("cleanup_socket", False),),
    ),
}


def row_for(version: tuple[int, int]) -> tuple[int, int]:
    """Which row applies to `version`: the greatest key not above it.

    Takes the version explicitly, with no default, so that the interesting case can be asked about
    at all: the rule that matters most is the one that fires on a release no test process can be
    running under.
    """
    if version < _FLOOR:
        raise ValueError(
            f"Python {version[0]}.{version[1]} is below this package's supported floor "
            f"{_FLOOR[0]}.{_FLOOR[1]}"
        )
    return max(key for key in _ROWS if key <= version)


def _running_row() -> _Behaviour:
    return _ROWS[row_for(sys.version_info[:2])]


def attached_connection_count(server: asyncio.Server) -> int:
    """How many connections the server currently has attached.

    This is the quantity `wait_closed()` itself waits on, which is why shutdown polls it rather than
    its own set of handler tasks: a transport is attached synchronously, while the task that
    registers the handler is scheduled separately and runs several event-loop turns later.
    """
    return _running_row().attached_connection_count(server)


def unix_server_kwargs() -> dict[str, object]:
    """The keyword arguments `asyncio.start_unix_server` must be called with on this interpreter."""
    return dict(_running_row().unix_server_kwargs)


def interpreter_version() -> str:
    """This interpreter's version, as a string, for logging.

    Read here rather than where it is logged so that reading the running version stays confined to
    this module.
    """
    return platform.python_version()
