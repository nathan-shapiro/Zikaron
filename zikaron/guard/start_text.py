"""The guard start text `zikaron-hook --components guards|both` emits (`design/guards.md` §5).

A module of its own, importing only the seam, because the hook that emits it runs on every session
and subagent start and must not load the rule engine to print a text. Its wording is
memory-reviewer's — Claude Code's held to `reviews/m37-edit-guards-review.md` by a test, kiro's to
`reviews/m41-2-review.md` — like `messages`.

Each harness's text is a template of its own, since the tool ids change the article and the wrapping
and no rendering of one reproduces the other's bytes; the tools it names are filled from
`HarnessSpec.tool_ids`. The sentence about the re-read reminder is there only where the harness has
the re-read hook.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from zikaron.harness.spec import Harness, HarnessSpec

_HEADING: Final = "## Editing files (Zikaron edit guards)"

_BODIES: Final[Mapping[Harness, str]] = MappingProxyType(
    {
        Harness.CLAUDE_CODE: (
            "Authored files in this project are edited with {read} then {edit}, or with {write} "
            "for a new file, and\n"
            "never with `sed -i`, an inline interpreter script, a script written to scratch and "
            "then run, or\n"
            "a heredoc or other redirect of literal text into a file, each of which changes text "
            "that has not\n"
            "been read in its current state. A hook in this project refuses a {shell} command "
            "that does so.\n"
            "A path under /tmp, /var/tmp or $TMPDIR is scratch and exempt as a target; a script "
            "run from\n"
            "there is judged by what it writes, not by where it is."
        ),
        Harness.KIRO: """\
Authored files in this project are edited with {read} then {edit}, or with {write} for
a new file, and never with `sed -i`, an inline interpreter script, a script written to scratch
and then run, or a heredoc or other redirect of literal text into a file, each of which changes
text that has not been read in its current state. A hook in this project refuses an {shell}
command that does so. A path under /tmp, /var/tmp or $TMPDIR is scratch and exempt as a target;
a script run from there is judged by what it writes, not by where it is.""",
    }
)

_REREAD_SENTENCE: Final = """ After each edit, a reminder from this
project's hooks notes that the file has not been re-read; it asks for one re-read of the edited
material and its surroundings once that file's editing is finished, not one re-read per edit."""


def guard_start_text(spec: HarnessSpec) -> str:
    """The start text for `spec`'s harness, in the tool names its model sees."""
    ids = spec.tool_ids
    body = (
        _BODIES[spec.harness]
        .replace("{read}", ids.read)
        .replace("{edit}", ids.edit)
        .replace("{write}", ids.write)
        .replace("{shell}", ids.shell)
    )
    reread = spec.guards is not None and spec.guards.reread is not None
    return f"{_HEADING}\n\n{body}{_REREAD_SENTENCE if reread else ''}"
