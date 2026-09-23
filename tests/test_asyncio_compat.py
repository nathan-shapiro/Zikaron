"""`zikaron.service.asyncio_compat` — the row lookup, and the socket behaviour it exists to pin.

The lookup is tested with literal version tuples rather than by running under several interpreters,
because the rule that matters most is the one that fires on a release nothing here can be running
under: a version newer than any row must resolve to the newest row.

The rows' own bodies get no unit test. A stub or an assertion naming either private attribute would
itself be the thing `test_version_seam.py` forbids outside the module, and a test asserting "this
row reads the counter" could only do so by naming it. They are covered instead by running the real
shutdown path under each supported version, which is what `check-matrix.sh` is for, plus the socket
test at the bottom of this file.
"""

import asyncio
import json
from pathlib import Path

import pytest

from tests.service_fixtures import open_context
from zikaron.service import asyncio_compat, server


@pytest.mark.parametrize(
    ("version", "expected_row"),
    [
        ((3, 12), (3, 12)),
        ((3, 13), (3, 13)),
        # No row of its own: 3.14 changed neither behaviour, so it takes 3.13's rather than
        # needing a duplicate entry that could drift from the one it copies.
        ((3, 14), (3, 13)),
        # The case no test process can be: a release far newer than anything this package has been
        # run against still resolves, and to the newest row, so a further change to either private
        # name fails loudly at the first shutdown instead of being absorbed by a default.
        ((3, 99), (3, 13)),
        ((4, 0), (3, 13)),
    ],
)
def test_the_applicable_row_is_the_greatest_key_not_above_the_version(
    version: tuple[int, int], expected_row: tuple[int, int]
) -> None:
    assert asyncio_compat.row_for(version) == expected_row


def test_a_version_below_the_floor_is_refused_by_name() -> None:
    """Rather than by `max()` raising "arg is an empty sequence", which names neither the version
    asked for nor the floor it missed.

    This is a guard for an explicit caller passing a literal, not for a below-floor interpreter: one
    of those cannot run this package at all, so the lookup on the running version never reaches it.
    """
    with pytest.raises(ValueError, match="below this package's supported floor"):
        asyncio_compat.row_for((3, 11))


def test_the_server_keyword_arguments_are_a_fresh_mapping_each_call() -> None:
    """A caller that mutates what it is given must not change what the next caller gets. Cheap to
    guarantee, and the failure it prevents is a server started with arguments some unrelated code
    edited earlier."""
    first = asyncio_compat.unix_server_kwargs()
    first["cleanup_socket"] = "mutated"
    first["injected"] = True
    assert asyncio_compat.unix_server_kwargs() == asyncio_compat.unix_server_kwargs()
    assert "injected" not in asyncio_compat.unix_server_kwargs()


def test_the_interpreter_version_is_reported_as_a_dotted_string() -> None:
    reported = asyncio_compat.interpreter_version()
    assert reported.split(".")[0].isdigit()
    assert len(reported.split(".")) >= 2


async def test_closing_a_served_socket_leaves_the_file_on_disk(
    tmp_path: Path, socket_dir: Path
) -> None:
    """The one behaviour that changed silently: from 3.13, a closing Unix server removes its own
    socket path unless told not to.

    Every other test in this suite asserts the socket is *gone* after a shutdown, which is true
    whichever process removed it and so says nothing about who did. This one asserts the mechanism:
    closing the listener leaves the file, so which process unlinks it — and when — stays this
    service's own decision, before the close on its self-stop and signal paths and after it on
    `run`'s error path.

    Goes through `server.serve` and `RunningServer.shut_down`, the real paths, rather than calling
    `asyncio.start_unix_server` with the compatibility arguments directly — the latter would pass
    even if `serve` had stopped passing them, which is the only way this can actually break.
    """
    async with open_context(tmp_path) as ctx:
        sock_path = socket_dir / "survives.sock"
        running = await server.serve(ctx, str(sock_path))
        assert sock_path.is_socket()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        try:
            writer.write(b'{"jsonrpc":"2.0","id":1,"method":"health","params":{}}\n')
            await writer.drain()
            assert json.loads(await reader.readline())["result"]["ready"] is True
        finally:
            writer.close()

        await asyncio.wait_for(running.shut_down(), timeout=5.0)

        assert sock_path.is_socket(), (
            "shut_down() removed the socket file; unlinking it is the service's own step and "
            "asyncio must not take it"
        )
