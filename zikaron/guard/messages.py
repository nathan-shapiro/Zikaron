"""The texts the guard hooks put in front of a model; the start text is `start_text`'s.

The wording is not this module's to choose: `design/edit-guards.md` §5 assigns it to
memory-reviewer, whose final text is `reviews/m37-edit-guards-review.md` §"Prompt texts", and a
test holds these constants to that file. The design states what each text must contain — the
deny message §3.5, the invalid-marker message and the acknowledgement §3.4, the nudge §4.

>>> from zikaron.guard.forms import Form, FormMatch, Target
>>> match = FormMatch(Form.LITERAL_TEXT, "tee", (Target("/home/u/proj/f", False),))
>>> message = deny_message(match, invalid_marker=False, marker_in_content=False)
>>> "`tee` writes literal text to a file; it names `/home/u/proj/f`." in message
True
>>> reread_nudge("/home/u/proj/a.md", ((12, 18), (40, 40)))[:50]
'`/home/u/proj/a.md` was edited (lines `12-18, 40`)'
"""

from collections.abc import Sequence
from typing import Final

from zikaron.guard.forms import Form, FormMatch

DENY_TEMPLATE: Final = (
    "Zikaron's find-replace guard refused this command: `{word}` {form}; it names {targets}. "
    "That is an edit made to text you have not read in its current state. Authored files are "
    "edited with Read then Edit, or with Write for a new file; a target under /tmp, /var/tmp or "
    "$TMPDIR is scratch and exempt. If this command is nonetheless the right tool here (a file "
    "whose bytes a program owns, a bulk mechanical change, or a deny that is mistaken), run it "
    "again with a shell comment of exactly this form, giving your own reason in at least two "
    "words on that line: #ZIKARON-FORCE #Reason: regenerate golden file."
)

INVALID_MARKER_TEMPLATE: Final = (
    "Zikaron's find-replace guard refused this command: `{word}` {form}; it names {targets}. "
    "It carries #ZIKARON-FORCE, but no comment in it is a valid override. A valid override is "
    "one shell comment in which the marker stands at the start of a line or after whitespace, "
    "#Reason: follows it with that spelling and capital R, and your own reason follows on the "
    "marker's line, at least two words outside angle brackets: "
    "#ZIKARON-FORCE #Reason: regenerate golden file."
)

PLACEMENT_CLAUSE: Final = (
    "The #ZIKARON-FORCE in this command is inside a heredoc body or a quoted string, where it is "
    "content rather than a comment. The override is a shell comment outside both: on the heredoc "
    "opener's line, on a line after its delimiter, or after a multi-line string's closing quote; "
    "on the delimiter line it would stop the heredoc terminating and be written into the file."
)

NO_TARGET: Final = "no target the guard could resolve"

ACKNOWLEDGEMENT_TEMPLATE: Final = (
    "#ZIKARON-FORCE accepted by Zikaron's find-replace guard, reason: {reason}. The guard's deny "
    "is withdrawn for this command only; the usual permission flow applies to it, and the "
    "override and its reason are recorded in the transcript. This command changes {targets}. "
    "No re-read reminder follows a Bash call, so once it has run, the next step is to re-read all "
    "the changed material and its surroundings."
)

NUDGE_WITH_RANGES_TEMPLATE: Final = (
    "`{path}` was edited (lines `{ranges}`) and has not yet been re-read for flow and consistency "
    "with the rest of the file. Once editing of this file is finished, the next step is to "
    "re-read all the edited material and its surroundings."
)

NUDGE_TEMPLATE: Final = (
    "`{path}` was edited and has not yet been re-read for flow and consistency with the rest of "
    "the file. Once editing of this file is finished, the next step is to re-read all the edited "
    "material and its surroundings."
)

#: Each form's `{form}` label, a verb phrase following `` `{word}` ``.
FORM_LABELS: Final[dict[Form, str]] = {
    Form.SED_IN_PLACE: "edits a file in place (-i or --in-place)",
    Form.PERL_RUBY_IN_PLACE: "edits a file in place (-i)",
    Form.AWK_IN_PLACE: "edits a file in place (-i inplace)",
    Form.INLINE_SCRIPT: "runs an inline script that writes a file",
    Form.LITERAL_TEXT: "writes literal text to a file",
    Form.SCRATCH_SCRIPT: "runs a scratch script that writes a file",
}


def deny_message(match: FormMatch, *, invalid_marker: bool, marker_in_content: bool) -> str:
    """The `permissionDecisionReason` for a deny of `match`."""
    template = INVALID_MARKER_TEMPLATE if invalid_marker else DENY_TEMPLATE
    targets = _targets(match.authored_paths)
    message = template.format(word=match.word, form=FORM_LABELS[match.form], targets=targets)
    return f"{message} {PLACEMENT_CLAUSE}" if marker_in_content else message


def acknowledgement(reason: str, targets: Sequence[str]) -> str:
    """The `additionalContext` for a valid override: its reason, and what the command changes."""
    return ACKNOWLEDGEMENT_TEMPLATE.format(reason=reason, targets=_targets(targets))


def _targets(paths: Sequence[str]) -> str:
    """The resolved paths in backticks, joined, or the fixed clause where none resolved."""
    return ", ".join(f"`{path}`" for path in paths) if paths else NO_TARGET


def reread_nudge(path: str, ranges: Sequence[tuple[int, int]] | None) -> str:
    """The `additionalContext` after an edit; `ranges` are new-side inclusive line ranges, or
    `None` where the result carried no patch the hook recognises."""
    if not ranges:
        return NUDGE_TEMPLATE.format(path=path)
    rendered = ", ".join(str(start) if start == end else f"{start}-{end}" for start, end in ranges)
    return NUDGE_WITH_RANGES_TEMPLATE.format(path=path, ranges=rendered)
