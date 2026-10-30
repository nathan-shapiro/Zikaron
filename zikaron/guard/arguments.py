"""The arguments an installed `zikaron-guard` command carries, and how the guard reads them back
(`design/guards.md` §5).

The guard takes its harness from its command line, not from the environment: a kiro launched from
Claude Code inherits `CLAUDECODE` (`design/harness.md` §"The nesting limit"), and a guard detecting
from it would answer in the envelope kiro ignores, failing open with nothing said. The installer
knows which harness's file it writes. No argument means Claude Code, so a command installed before
the flag existed keeps its meaning.

>>> harness_arguments(Harness.KIRO), harness_arguments(Harness.CLAUDE_CODE)
(('--harness', 'kiro'), ())
>>> spec_from_arguments(["--harness", "kiro"]).harness, spec_from_arguments([]).harness
(<Harness.KIRO: 'kiro'>, <Harness.CLAUDE_CODE: 'claude-code'>)
"""

from collections.abc import Sequence
from typing import Final

from zikaron.harness.spec import CLAUDE_CODE, SPECS, Harness, HarnessSpec

FLAG: Final = "--harness"


def harness_arguments(harness: Harness) -> tuple[str, ...]:
    """The arguments a guard command installed for `harness` carries."""
    return () if harness is Harness.CLAUDE_CODE else (FLAG, harness.value)


def spec_from_arguments(arguments: Sequence[str]) -> HarnessSpec:
    """The harness `arguments` name. Anything but exactly `--harness <harness>` reads as Claude
    Code, the meaning every command had before the flag existed."""
    match tuple(arguments):
        case (flag, value) if flag == FLAG and value in {member.value for member in Harness}:
            return SPECS[Harness(value)]
        case _:
            return CLAUDE_CODE
