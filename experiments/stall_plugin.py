"""A pytest plugin that stalls the whole test process, to check timing tests against
`design/coding-standards.md` §4: a wall-clock bound must survive a stall of the process.

    PYTHONPATH=experiments .venv/bin/pytest -p stall_plugin --stall 0.75 --every 1.0 tests/...

A thread holds the GIL in one C call for about `--stall` seconds, once every `--every` seconds, for
each test, which stalls every other thread of the process — the event loop, `aiosqlite`'s worker
and any meter alike — the way a loaded runner or a collection pause does. The call's length is
calibrated on this host at start-up, so a hold is the same length on any machine. The first stall
of each test starts at a random point in the cycle, since a test is vulnerable to a stall at some
phases and not others, and a fixed phase probes only one; run a test several times to sample them.
Keep the working directory off `PYTHONPATH`: `tests/test_spawned_interpreter.py` is red, correctly,
while a checkout there shadows the install.

Measured on 2026-10-30 against the change that brought §4 in, with every stall starting at its
test's start, the phase this plugin then had: at `--stall 0.75 --every 1.0`, the test files whose
bounds it changed failed 8 tests as they stood at `8617308` and none after it, and the whole suite
passed at `--stall 0.35 --every 0.6`. At that fixed phase ten runs of the four tests whose verdicts
rested on two timers' order passed every time; at a random phase, fifteen runs at `--stall 0.3
--every 0.4` failed two of them as they stood at `8617308` — the lifecycle test twice, the
diagnostics test once — and the rewritten four none in seventy-five, which is why the phase is
sampled. `tests/loop_lateness.py`'s jitter threshold was chosen by the measurement its docstring
records.
"""

import random
import threading
import time
from collections.abc import Iterator

import pytest

_CALIBRATION_N = 1_000_000


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--stall", type=float, default=0.35, help="seconds each stall holds the GIL")
    parser.addoption(
        "--every", type=float, default=0.6, help="seconds from one stall's start to the next"
    )


def _hold_n(seconds: float) -> int:
    """How large a `sum(range(n))` holds the GIL for about `seconds` on this host."""
    started = time.monotonic()
    sum(range(_CALIBRATION_N))
    per_call = time.monotonic() - started
    return max(1, int(_CALIBRATION_N * seconds / per_call))


@pytest.fixture(autouse=True)
def _process_stalls(request: pytest.FixtureRequest) -> Iterator[None]:
    stall = float(request.config.getoption("--stall"))
    every = float(request.config.getoption("--every"))
    gap = max(0.0, every - stall)
    n = _hold_n(stall)
    stop = threading.Event()
    phase = random.uniform(0.0, every)  # noqa: S311 — a test's stall phase, not a secret.

    def stalls() -> None:
        if stop.wait(phase):
            return
        sum(range(n))
        while not stop.wait(gap):
            sum(range(n))

    holder = threading.Thread(target=stalls, daemon=True)
    holder.start()
    yield
    stop.set()
    holder.join()
