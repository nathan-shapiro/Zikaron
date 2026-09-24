"""The `zikaron` umbrella: what it dispatches, what it refuses, and that its wiring resolves.

**The console script is checked by resolving what `pyproject.toml` declares, not by running
`.venv/bin/zikaron`.** That file appears only when someone reinstalls the package, so a subprocess
test would pass on a freshly built virtualenv and fail on the one a contributor already had — a
result about the environment rather than about the code. Resolving the declared target catches the
failure that matters, which is an entry point naming a module path that does not exist.
"""

import importlib
import importlib.metadata
import tomllib
from pathlib import Path
from typing import Final

import pytest

from zikaron.cli.main import NAME, main

_ROOT: Final = Path(__file__).resolve().parent.parent

#: Every subcommand the umbrella offers, as the help text lists them. Spelled here rather than read
#: from the dispatch table, so that a command silently dropped from that table fails rather than
#: quietly agreeing with itself.
_SUBCOMMANDS: Final = ("install", "knowledge", "doctor")


def test_the_console_script_resolves_to_something_callable() -> None:
    declared = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    target = declared["project"]["scripts"][NAME]
    module_path, _, attribute = target.partition(":")
    entry = getattr(importlib.import_module(module_path), attribute)
    assert callable(entry)


def test_bare_invocation_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Status 2 rather than 1, which is `argparse`'s own for a usage error, so the umbrella and the
    parsers it dispatches to cannot disagree about what a mistyped command line costs.
    """
    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"usage: {NAME} <command>")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_goes_to_stdout_and_succeeds(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([flag]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith(f"usage: {NAME} <command>")


def test_help_lists_every_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--help"])
    printed = capsys.readouterr().out
    for name in _SUBCOMMANDS:
        assert f"\n  {name}" in printed, f"{name} is dispatchable but unlisted"


def test_version_reports_the_installed_distribution(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip() == f"{NAME} {importlib.metadata.version(NAME)}"


def test_version_is_honest_when_no_distribution_is_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A source tree nobody installed carries no metadata, and saying so is the point: raising here
    would break the flag in the one situation it exists for, which is working out what is running.
    """

    def _absent(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError(NAME)

    monkeypatch.setattr(importlib.metadata, "version", _absent)
    assert main(["--version"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(f"{NAME} unknown")
    assert "source tree" in printed


def test_usage_advertises_the_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Unadvertised, it is a flag only somebody who already knew it would type — and it is the first
    thing a bug report needs, from the reporter least able to guess at it.
    """
    main(["--help"])
    assert f"{NAME} --version" in capsys.readouterr().out


def test_an_unknown_command_names_what_was_typed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["knowledgee"]) == 2
    captured = capsys.readouterr()
    assert "unknown command 'knowledgee'" in captured.err
    assert f"usage: {NAME} <command>" in captured.err


@pytest.mark.parametrize("name", _SUBCOMMANDS)
def test_every_listed_subcommand_dispatches(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    """`--help` is the one argument every subcommand accepts without touching a store or a project,
    so it reaches the dispatched parser and nothing else. `argparse` exits rather than returning.
    """
    with pytest.raises(SystemExit) as exit_status:
        main([name, "--help"])
    assert exit_status.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: {NAME} {name}")


@pytest.mark.parametrize(
    ("module", "invocation"),
    [
        ("zikaron.install.main", "python -m zikaron.install"),
        ("zikaron.knowledge.main", "python -m zikaron.knowledge"),
    ],
)
def test_the_module_invocation_still_names_itself(
    module: str, invocation: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Threading `prog` from the umbrella must not have moved what `python -m` prints, which is the
    form the install documentation gives for a host-Python install with several virtualenvs.
    """
    with pytest.raises(SystemExit):
        importlib.import_module(module).main(["--help"])
    assert capsys.readouterr().out.startswith(f"usage: {invocation}")
