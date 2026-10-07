"""The six forms of `design/edit-guards.md` §3.2, matched over one pipeline, with their targets.

Every command word of every simple command is tried against the six rows; a row that matches
yields a `FormMatch` naming its targets, each resolved and tested for scratch (§3.3). **A match is
exempt when every one of its targets is scratch and it has at least one** — so a write whose
target the rules cannot resolve is never exempt.

Rows 1 to 5 are judged from the pipeline alone. Row 6 — a scratch script run — also needs what
the rest of the command staged and, failing that, the file itself, so the caller supplies its
judge (`zikaron.guard.script_file`); without one, row 6 never matches.

>>> from zikaron.guard.heredoc import delimit
>>> from zikaron.guard.lexer import annotate
>>> from zikaron.guard.grammar import parse
>>> here = Location(cwd="/home/u/proj")
>>> def forms(command: str) -> list[tuple[str, tuple[str | None, ...], bool]]:
...     pipelines = parse(annotate(delimit(command.split("\\n"))))
...     found = [m for p in pipelines for m in match_pipeline(p, here)]
...     return [(m.form.name, tuple(t.path for t in m.targets), m.is_exempt) for m in found]
>>> forms("sed -i 's/a/b/' /tmp/x && echo y > f")
[('SED_IN_PLACE', ('/tmp/x',), True), ('LITERAL_TEXT', ('/home/u/proj/f',), False)]
>>> forms('''python3 -c "open(sys.argv[1], 'w')" /tmp/x''')
[('INLINE_SCRIPT', (None,), False)]
>>> forms("sed 's/a/b/' f > g")
[]
"""

import enum
from collections.abc import Callable
from dataclasses import dataclass

from zikaron.guard.expression import Named, Scratch
from zikaron.guard.grammar import Pipeline
from zikaron.guard.inplace import Family, edits_in_place, family_of, in_place_targets
from zikaron.guard.interpreter import inline_script
from zikaron.guard.literal_text import WORDS as LITERAL_TEXT_WORDS
from zikaron.guard.literal_text import literal_targets
from zikaron.guard.position import command_name, command_words
from zikaron.guard.programs import is_interpreter, is_shell
from zikaron.guard.scratch import Location
from zikaron.guard.writes import write_targets


class Form(enum.Enum):
    """The rows of §3.2's table, by number."""

    SED_IN_PLACE = 1
    PERL_RUBY_IN_PLACE = 2
    AWK_IN_PLACE = 3
    INLINE_SCRIPT = 4
    LITERAL_TEXT = 5
    SCRATCH_SCRIPT = 6


_IN_PLACE_FORMS = {
    Family.SED: Form.SED_IN_PLACE,
    Family.PERL: Form.PERL_RUBY_IN_PLACE,
    Family.RUBY: Form.PERL_RUBY_IN_PLACE,
    Family.AWK: Form.AWK_IN_PLACE,
}


@dataclass(frozen=True, slots=True)
class Target:
    """One target of a match: its path as resolved, or `None` where the rules found no path."""

    path: str | None
    is_scratch: bool


@dataclass(frozen=True, slots=True)
class FormMatch:
    """A form that matched, the command word it matched on — as written, without its path
    prefix — and its targets."""

    form: Form
    word: str
    targets: tuple[Target, ...]

    @property
    def is_exempt(self) -> bool:
        return bool(self.targets) and all(target.is_scratch for target in self.targets)

    @property
    def authored_paths(self) -> tuple[str, ...]:
        """The resolved paths among the targets that are not scratch."""
        return tuple(t.path for t in self.targets if t.path is not None and not t.is_scratch)


#: Row 6's judge for the shell or interpreter word at `(command, word)` of a pipeline, named
#: `name`, which no inline script feeds: its match, or `None`.
ScriptRunJudge = Callable[[Pipeline, int, int, str, Location], "FormMatch | None"]


def match_pipeline(
    pipeline: Pipeline, location: Location, script_run: ScriptRunJudge | None = None
) -> list[FormMatch]:
    """Every form matching in `pipeline`, in command-word order; row 6 only with `script_run`."""
    matches: list[FormMatch] = []
    for index, command in enumerate(pipeline):
        for word in command_words(command):
            name = command_name(command.tokens[word])
            found = _match(pipeline, index, word, name, location)
            if found is None and script_run is not None and _may_run_a_file(pipeline, index, word):
                found = script_run(pipeline, index, word, name, location)
            if found is not None:
                matches.append(found)
    return matches


def script_targets(script: str, location: Location) -> tuple[Target, ...] | None:
    """Row 4's judgement of a script's text: each write call's target, or `None` when the text
    holds no write call."""
    judged = write_targets(script)
    if judged is None:
        return None
    return tuple(_script_target(target, location) for target in judged)


def _match(
    pipeline: Pipeline, command: int, word: int, name: str, location: Location
) -> FormMatch | None:
    """The one of rows 1 to 5 a command name can belong to, judged; `None` when it does not
    match."""
    family = family_of(name)
    if family is not None:
        arguments = pipeline[command].tokens[word + 1 :]
        if not edits_in_place(family, arguments):
            return None
        raws = in_place_targets(family, arguments)
        return FormMatch(_IN_PLACE_FORMS[family], name, _word_targets(raws, location))
    if is_interpreter(name):
        script = inline_script(pipeline, command, word)
        targets = script_targets(script, location) if script is not None else None
        return None if targets is None else FormMatch(Form.INLINE_SCRIPT, name, targets)
    if name in LITERAL_TEXT_WORDS:
        raws = literal_targets(pipeline, command, word)
        return FormMatch(Form.LITERAL_TEXT, name, _word_targets(raws, location)) if raws else None
    return None


def _may_run_a_file(pipeline: Pipeline, command: int, word: int) -> bool:
    """Whether row 6 may judge this word: a shell, or an interpreter no inline script feeds."""
    name = command_name(pipeline[command].tokens[word])
    if is_shell(name):
        return True
    return is_interpreter(name) and inline_script(pipeline, command, word) is None


def _word_targets(raws: list[str], location: Location) -> tuple[Target, ...]:
    return tuple(_word_target(raw, location) for raw in raws)


def _word_target(raw: str, location: Location) -> Target:
    return Target(location.resolve(raw), location.is_scratch(raw))


def _script_target(judged: Named | Scratch | None, location: Location) -> Target:
    if isinstance(judged, Named):
        return Target(location.resolve_literal(judged.path), location.is_scratch(judged.path))
    return Target(None, isinstance(judged, Scratch))
