"""`zikaron` — one console script dispatching to the commands a person runs.

**Why an umbrella at all.** `uv tool install` puts only a package's console scripts on `PATH`, never
the tool virtualenv's interpreter, so a command reachable solely as `python -m zikaron.<x>` is
reachable only by a user who first finds `~/.local/share/uv/tools/zikaron/bin/python`. The `python
-m` forms keep working and stay documented, for the case a host Python install makes real: several
virtualenvs, where naming the interpreter is the point.

**`zikaron-hook` and `zikaron-mcp` stay separate and are deliberately not reachable from here.**
Their absolute paths are written into harness configuration at install time
(`architecture.md` §"The install contract"), so folding them in would rewrite every installed config
to shorten two command lines no human types.

**Each subcommand is imported only when it is the one being run.** `doctor` reports on an
installation that may be broken in exactly the way that stops another subcommand importing — a
missing `aiosqlite` is enough — and a module-level import would let the diagnosis fail with the
traceback it exists to replace. `doctor`'s own imports are stdlib plus this package, bar
`sqlite_vec`, which it imports inside the check that reports on it.
"""

import sys
from collections.abc import Callable, Sequence
from typing import Final, NamedTuple, Protocol

NAME: Final = "zikaron"


class Entry(Protocol):
    """One subcommand's `main`, as this dispatcher calls it.

    `prog` is passed rather than defaulted because each subcommand's parser owns its own `--help`,
    and a usage line reading `python -m zikaron.install` under `zikaron install --help` would name
    an invocation the reader did not type.
    """

    def __call__(self, argv: Sequence[str], /, *, prog: str) -> int: ...


class _Subcommand(NamedTuple):
    summary: str
    load: Callable[[], Entry]


def _install() -> Entry:
    from zikaron.install.main import main  # noqa: PLC0415

    return main


def _knowledge() -> Entry:
    from zikaron.knowledge.main import main  # noqa: PLC0415

    return main


def _doctor() -> Entry:
    from zikaron.doctor.main import main  # noqa: PLC0415

    return main


#: The dispatch table and the help text are the same object, so a command cannot be runnable
#: without being listed or listed without being runnable. Order is the order `--help` prints.
_SUBCOMMANDS: Final[dict[str, _Subcommand]] = {
    "install": _Subcommand(
        "write Zikaron's hook, MCP and consolidator entries into a project", _install
    ),
    "knowledge": _Subcommand("manage this project's knowledge bases", _knowledge),
    "doctor": _Subcommand("check that this machine can run Zikaron", _doctor),
}


def _installed_version() -> str:
    """The installed distribution's version, or a stand-in when there is no distribution metadata.

    A source tree that was never installed has none, and raising there would make `--version` fail
    in the one situation it exists for: establishing what is being run. It identifies a *build* only
    for a released install — a `git+` one reports whatever `pyproject.toml` said at that commit.
    """
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        return version(NAME)
    except PackageNotFoundError:
        return "unknown — no installed distribution, so this is a source tree"


def _usage() -> str:
    width = max(len(name) for name in _SUBCOMMANDS)
    listed = [f"  {name:<{width}}  {command.summary}" for name, command in _SUBCOMMANDS.items()]
    return "\n".join(
        [
            f"usage: {NAME} <command> [options]",
            "",
            "commands:",
            *listed,
            "",
            f"`{NAME} <command> --help` describes one command.",
            f"`{NAME} --version` names this version, which is what a bug report needs first.",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch on the first argument. Returns a process exit status.

    Returns rather than exiting, so a test drives the whole front door in-process. The console
    script generated from `[project.scripts]` is what turns the status into an exit.

    A usage error is status 2, which is `argparse`'s own, so the umbrella and the parsers it
    dispatches to cannot disagree about what a mistyped command line costs.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print(_usage(), file=sys.stderr)
        return 2
    name, rest = arguments[0], arguments[1:]
    if name in ("-h", "--help"):
        print(_usage())
        return 0
    if name == "--version":
        print(f"{NAME} {_installed_version()}")
        return 0
    command = _SUBCOMMANDS.get(name)
    if command is None:
        print(f"{NAME}: unknown command {name!r}", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2
    return command.load()(rest, prog=f"{NAME} {name}")


if __name__ == "__main__":
    sys.exit(main())
