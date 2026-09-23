"""`zikaron.mcp.main` — what a store this process cannot serve says on its way out.

A `ZikaronError` carries its detail in `data`; its string is the wire name and the code's generic
message. So an uncaught one ends a traceback naming neither the key at fault nor its value. stdout
is the transport, so stderr is what is left; the payload is printed there because the traceback
would not carry it.
"""

import os
from pathlib import Path

import pytest
from fastmcp import FastMCP

from zikaron.core.errors import ZikaronError
from zikaron.mcp import main as mcp_main
from zikaron.service import paths

_OVER_LONG_RUNTIME_DIR = "/" + "x" * 110


@pytest.fixture(autouse=True)
def _never_actually_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    """`FastMCP.run()` reads stdin forever. Stubbed so that a build which *should* have failed
    fails this test instead of hanging it — the difference between a red run and a wedged one
    under the mutation this file exists to catch."""
    monkeypatch.setattr(
        FastMCP, "run", lambda *_a, **_k: pytest.fail("served a store it could not")
    )


def test_an_unusable_runtime_directory_is_named_on_stderr_rather_than_traced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", _OVER_LONG_RUNTIME_DIR)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        mcp_main.main(["--mode", "primary"])

    assert raised.value.code != 0
    printed = capsys.readouterr().err
    assert "runtime_dir" in printed
    assert (
        str(paths.runtime_dir(xdg_runtime_dir=_OVER_LONG_RUNTIME_DIR, uid=os.getuid())) in printed
    )

    # The whole payload, pinned through the cause rather than through the message's wording: the
    # length and the limit live in `expected`, and a print that dropped it would otherwise stay
    # green while losing both.
    cause = raised.value.__cause__
    assert isinstance(cause, ZikaronError)
    assert str(cause.data["expected"]) in printed
