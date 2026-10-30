"""The two lateness meters in `tests/loop_lateness.py`, which the suite's subtracting wall-clock
ceilings rest on.

Each assertion holds under a stall of the process running it. That a block is counted is a lower
bound, which a stall only raises. That a wait is *not* counted is a comparison with a control taken
at the same moment — a ticking thread written here, apart from the code under test — since a stall
overlapping the wait is counted by both and lengthens the wait's elapsed time only past its end.
"""

import asyncio
import contextlib
import threading
import time
from collections.abc import Iterator

from tests.loop_lateness import loop_lateness, thread_lateness

_BLOCK_SECONDS = 0.3
_COUNTED_AT_LEAST = 0.25
#: How far one meter may count beyond the other over one run: a few ticks per stall, and far below
#: the 0.3 s a meter counting the wait itself would add.
_METERS_AGREE_WITHIN = 0.1


@contextlib.contextmanager
def _control() -> Iterator[list[float]]:
    """A witness to stalls of the process: a thread summing how late its own short sleeps end."""
    counted = [0.0]
    stop = threading.Event()

    def tick() -> None:
        due = time.monotonic() + 0.005
        while not stop.wait(0.005):
            now = time.monotonic()
            if now - due > 0.02:
                counted[0] += now - due
            due = now + 0.005

    witness = threading.Thread(target=tick, daemon=True)
    witness.start()
    try:
        yield counted
    finally:
        stop.set()
        witness.join()


async def test_a_block_of_the_loop_is_counted() -> None:
    async with loop_lateness() as lateness:
        await asyncio.sleep(0.05)
        time.sleep(_BLOCK_SECONDS)
        await asyncio.sleep(0.05)
    assert lateness.seconds >= _COUNTED_AT_LEAST, lateness


async def test_a_block_that_ends_as_the_meter_exits_is_counted() -> None:
    """The tick in flight at exit: nothing after the block lets the meter's own tick run."""
    async with loop_lateness() as lateness:
        await asyncio.sleep(0.05)
        time.sleep(_BLOCK_SECONDS)
    assert lateness.seconds >= _COUNTED_AT_LEAST, lateness


async def test_an_awaited_wait_is_not_lateness() -> None:
    """The property every ceiling that subtracts it rests on: what the code waited for is left."""
    with _control() as stalled:
        async with loop_lateness() as lateness:
            await asyncio.sleep(_BLOCK_SECONDS)
    assert lateness.seconds <= stalled[0] + _METERS_AGREE_WITHIN, (lateness, stalled)


def test_a_wait_that_releases_the_gil_is_not_lateness_on_the_thread_meter() -> None:
    with _control() as stalled, thread_lateness() as lateness:
        time.sleep(_BLOCK_SECONDS)
    assert lateness.seconds <= stalled[0] + _METERS_AGREE_WITHIN, (lateness, stalled)


def test_a_call_that_holds_the_gil_is_counted_on_the_thread_meter() -> None:
    """A C call that never releases the GIL stalls every other thread, the meter's included. One
    call for the whole hold, and the bar its own length, so neither rides on how fast the host is:
    a stall lengthens both sides."""
    with thread_lateness() as lateness:
        started = time.monotonic()
        sum(range(20_000_000))
        held_for = time.monotonic() - started
    assert held_for >= 0.05, f"too short a hold to tell from jitter: {held_for:.3f}s"
    assert lateness.seconds >= held_for - 0.05, (lateness, held_for)
