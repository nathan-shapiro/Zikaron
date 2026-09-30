"""The instant a request stops waiting, and whose instant it is.

`architecture.md` §"The service's connections" is normative. Every wait a request makes — for a
connection's lock, for a pool lease, for the write lock — is cut at one instant, so the waits
cannot compound past the budget a client's own timeout was derived from.

**Two kinds of instant, told apart by `set_by_caller`.** Most requests get the service's own budget,
`ddl.BUSY_TIMEOUT_MS` from when the wait is asked for — a read's dispatch, a write's own `BEGIN` —
and a wait it cuts is contention: `store_busy`, retryable. A `memory_surface` carrying
`deadline_at_ms` gets its caller's instant instead, and a wait that one cuts is lateness: the caller
has gone, and `deadline_passed` says so. Which bound cut a wait travels with the deadline, and is
never decided by reading the clock a second time: the event loop fires a timer up to one tick of its
clock's resolution early, so a wait can end just before the instant a second reading would demand.
"""

import math
import time
from dataclasses import dataclass
from typing import Self

from zikaron.core.store import ddl

_MS_PER_SECOND = 1000.0


def now_ms() -> int:
    """The wall clock in whole milliseconds since the epoch, rounded up.

    An integer, so a caller's `deadline_at_ms` of any size compares and subtracts exactly; rounded
    up, so a deadline derived from it errs early rather than late.
    """
    return math.ceil(time.time() * _MS_PER_SECOND)


@dataclass(frozen=True, slots=True)
class Deadline:
    """An instant on this process's monotonic clock, and whether a caller supplied it.

    Monotonic, because a wall-clock step inside the service must not stretch or cut a wait. A
    caller's instant arrives on the wall clock and is converted once, at `from_caller`.
    """

    at: float
    set_by_caller: bool

    @classmethod
    def budget(cls) -> Self:
        """The service's own budget, `ddl.BUSY_TIMEOUT_MS` from now.

        Read from the module at call time, so a test that patches the constant before a store opens
        patches every wait with it.
        """
        return cls(at=time.monotonic() + ddl.BUSY_TIMEOUT_MS / _MS_PER_SECOND, set_by_caller=False)

    @classmethod
    def from_caller(cls, deadline_at_ms: int, *, margin_ms: int) -> Self:
        """A caller's wall-clock deadline, less `margin_ms`, as an instant on the monotonic clock.

        Both ends run on one machine and share its realtime clock, so the conversion is exact
        except across a clock step between the two readings — rare, and self-limiting, since the
        next request converts afresh. Computed in integers, so a caller's value of any size converts
        without overflowing a float; every past deadline is alike, so it is clamped at just past.
        """
        remaining_ms = max(deadline_at_ms - margin_ms - now_ms(), -1)
        return cls(at=time.monotonic() + remaining_ms / _MS_PER_SECOND, set_by_caller=True)

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(self.at - time.monotonic(), 0.0)

    def passed(self) -> bool:
        """Whether the instant has been reached."""
        return time.monotonic() >= self.at
