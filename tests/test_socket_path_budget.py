"""Every socket path this suite binds must fit the *tightest* platform's `sun_path`, not this one's.

The asymmetry is the whole reason this file exists. A test directory that fits the wider bound and
not the tighter one fails on exactly one platform. Pinning the *smaller* bound on whatever platform
happens to be running turns that into an ordinary red test wherever it is introduced.

What it guards is the `socket_dir` fixture's budget rather than any one test's use of it: a change
to how that fixture names its directories, or to the runtime directory the session exports, is the
move that silently spends the headroom.
"""

import os
from pathlib import Path
from typing import Final

from zikaron.service import paths

#: The tightest bound the table holds, which is the one a shared fixture must satisfy regardless
#: of where the suite runs. Asked for by `sun_path_size`'s own unrecognised-platform contract
#: rather than by listing the platforms, so a row added with a smaller bound tightens this with no
#: list here to keep in step.
_TIGHTEST: Final = paths.sun_path_size("an-unsupported-platform")

#: What a real client appends to the runtime directory. The worst case among the two derivations:
#: `hook.connect` and `mcp.connection` both build `<runtime>/zikaron/<32 hex>.sock`, while a test
#: binding directly under `socket_dir` spends less.
_LONGEST_PRODUCTION_SUFFIX: Final = len(
    os.fsencode(Path("zikaron") / f"{paths.socket_hash(Path('/x'))}.sock")
)


def test_the_socket_dir_fixture_leaves_room_for_a_derived_socket_path(socket_dir: Path) -> None:
    derived = len(os.fsencode(socket_dir)) + 1 + _LONGEST_PRODUCTION_SUFFIX
    assert derived < _TIGHTEST, (
        f"socket_dir is {len(os.fsencode(socket_dir))} bytes, so a client deriving "
        f"<runtime>/zikaron/<hash>.sock under it reaches {derived} against {_TIGHTEST - 1} usable"
    )


def test_the_session_runtime_directory_leaves_the_same_room() -> None:
    """The `$XDG_RUNTIME_DIR` the session exports, which real clients and real subprocesses read.

    Separate from the fixture above because they are set up independently and either can grow
    without the other: this one is what `test_install_e2e.py` and `test_install_takeover.py` bind
    under, through a real hook and a real service rather than through any path a test composes.
    """
    exported = os.environ["XDG_RUNTIME_DIR"]
    runtime = paths.runtime_dir(xdg_runtime_dir=exported, uid=os.getuid())
    derived = len(os.fsencode(runtime / f"{paths.socket_hash(Path('/x'))}.sock"))
    assert derived < _TIGHTEST, (
        f"$XDG_RUNTIME_DIR is {exported!r}, making a derived socket path {derived} bytes "
        f"against {_TIGHTEST - 1} usable"
    )
