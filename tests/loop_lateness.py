"""How late the event loop ran — or, for a test with no loop, a thread — for a test that bounds
how long a request took.

A stall of the whole process — a loaded runner descheduling it, a collection pause — delays every
task alike, so a request's elapsed time grows by it whatever the code under test did, and a ceiling
meant for the code is crossed by the machine. Measured beside the request and subtracted from its
elapsed time, the loop's lateness leaves the time the code took. A lower bound needs none of this,
since a stall only lengthens what it bounds.

A tick that wakes more than `_JITTER_SECONDS` after it was due counts its whole lateness; ordinary
scheduling jitter below that is not counted, so it is never subtracted from what the code took.
Measured with every core loaded twice over, in separate runs under that uncontrolled load: a
threshold of 3 ms counted up to 42 ms over an idle half second and one of 10 ms up to 111 ms, while
20 ms counted none in eight and still counted a 0.3 s stall whole.

What it gives up: a wait that blocks the loop itself is lateness too, so a bound that subtracts it
cannot see such a wait. Every wait these tests bound runs off the loop — SQLite's busy wait on
`aiosqlite`'s thread, a lock or a deadline awaited — so none is hidden. And a stall that overlaps an
awaited wait is counted whole, though it lengthens the wait only past the wait's end, so in a
stalled run a ceiling is looser by that much: a stalled run can pass a defect an unstalled one
catches, and cannot fail correct code. `thread_lateness` is the same meter for synchronous code, on
a thread of its own, which a stall of the process delays as it delays the caller; it gives up a
caller that holds the GIL for longer than a tick, which none of the socket and subprocess waits it
is used beside does.

    async with loop_lateness() as lateness:
        started = time.monotonic()
        await request()
        elapsed = time.monotonic() - started
    assert elapsed - lateness.seconds < ceiling
"""

import asyncio
import contextlib
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Final

_TICK_SECONDS: Final = 0.005
_JITTER_SECONDS: Final = 0.02


@dataclass(slots=True)
class Lateness:
    """The meter's counted lateness so far, in seconds, and when its next tick is due."""

    seconds: float = 0.0
    _due: float = 0.0

    def _count(self, now: float) -> None:
        late = now - self._due
        if late > _JITTER_SECONDS:
            self.seconds += late


@contextlib.asynccontextmanager
async def loop_lateness() -> AsyncIterator[Lateness]:
    """The running loop's lateness while the block runs, final once the block has exited.

    The tick in flight at exit is counted too: a stall that ends just as the request answers may
    let the request's continuation run before the tick that slept through it.
    """
    loop = asyncio.get_running_loop()
    lateness = Lateness(_due=loop.time() + _TICK_SECONDS)

    async def measure() -> None:
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            now = loop.time()
            lateness._count(now)
            lateness._due = now + _TICK_SECONDS

    meter = asyncio.create_task(measure())
    try:
        yield lateness
    finally:
        meter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await meter
        lateness._count(loop.time())


@contextlib.contextmanager
def thread_lateness() -> Iterator[Lateness]:
    """A ticking thread's lateness while the block runs, final once the block has exited."""
    lateness = Lateness(_due=time.monotonic() + _TICK_SECONDS)
    stop = threading.Event()

    def measure() -> None:
        while not stop.wait(_TICK_SECONDS):
            now = time.monotonic()
            lateness._count(now)
            lateness._due = now + _TICK_SECONDS

    meter = threading.Thread(target=measure, daemon=True)
    meter.start()
    try:
        yield lateness
    finally:
        stop.set()
        meter.join()
        lateness._count(time.monotonic())
