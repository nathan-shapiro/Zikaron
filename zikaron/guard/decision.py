"""The command hook's decision on one `Bash` or `Monitor` command: `design/guards.md` §3 and §9.

Two rules judge every command. **The find-replace rule** (§3): does a form match (§3.2), and if
so, is a target not scratch (§3.3). **The self-match rule** (§9): does a `pgrep -f`/`pkill -f`
pattern match the command's own text, on this platform. **The override** (§3.4) is read only
when one of them denies: a valid one withdraws both rules' denies, and is acknowledged only when
the find-replace rule denied, since the acknowledgement asks for the re-read of what the command
changed. Without one, the find-replace rule's deny comes first, naming its first form (§9.2).

| Command (`cwd` `/home/u/proj`, `linux`) | Decision |
|---|---|
| `grep -rn "sed -i" tests/` | silent: `sed` is an argument, not a command |
| `sed -i 's/a/b/' /tmp/x` | silent: every target is scratch |
| `sed -i 's/a/b/' f` | deny, naming `/home/u/proj/f` |
| `sed -i 's/a/b/' f #ZIKARON-FORCE #Reason: regenerate golden` | acknowledge |
| `sed -i 's/a/b/' f #ZIKARON-FORCE` | deny, the invalid-marker message |
| `ls #ZIKARON-FORCE #Reason: a b` | silent: no rule denied, so the marker is never read |
| `pkill -f month_monitor.py` | deny, the self-match rule's |
| `pkill -f month_monitor.py #ZIKARON-FORCE #Reason: kill every copy` | silent |

The same command, `Location`, platform and scratch scripts always give the same decision. Nothing
here reads the environment or the clock, and the one file read is row 6's, through a `read` the
caller passes: the hook's `main` passes `read_script`, and everything else reads nothing unless it
says so.

>>> here = Location(cwd="/home/u/proj")
>>> decide("sed -i 's/a/b/' f", here, platform="linux").match.authored_paths
('/home/u/proj/f',)
>>> decide("sed -i 's/a/b/' f #ZIKARON-FORCE #Reason: regenerate golden", here, platform="linux")
Acknowledge(reason='regenerate golden', targets=('/home/u/proj/f',))
>>> decide("pkill -f month_monitor.py", here, platform="linux").match.word
'pkill'
"""

from dataclasses import dataclass

from zikaron.guard.forms import FormMatch, match_pipeline
from zikaron.guard.grammar import Boundary, parse
from zikaron.guard.heredoc import Unit, delimit
from zikaron.guard.lexer import annotate
from zikaron.guard.override import State, read_override
from zikaron.guard.position import bound_variables, changed_directory
from zikaron.guard.scratch import Location
from zikaron.guard.script_file import Reader, ScriptRuns, staged_texts
from zikaron.guard.selfmatch import SelfMatch, first_self_match


@dataclass(frozen=True, slots=True)
class Silent:
    """No output: the harness decides as if no guard were installed."""


@dataclass(frozen=True, slots=True)
class Deny:
    """A deny, and what its message says."""

    #: The first matching form with a target that is not scratch, or else the first self-match.
    match: FormMatch | SelfMatch
    #: The marker stands outside every body and string, but no comment carries a valid override.
    invalid_marker: bool
    #: The marker appeared only inside a heredoc body or a quoted string.
    marker_in_content: bool


@dataclass(frozen=True, slots=True)
class Acknowledge:
    """A valid override: no decision, only its acknowledgement — which names what the command
    changes, so the re-read the nudge cannot ask after a Bash call is asked here (§3.4)."""

    reason: str
    #: Every target that is not exempt, of every form that matched, resolved, in command order.
    targets: tuple[str, ...]


Decision = Silent | Deny | Acknowledge


def decide(
    command: str, location: Location, *, platform: str, read: Reader | None = None
) -> Decision:
    """The hook's decision on `command` run at `location` on `platform`, a `sys.platform` value,
    row 6 reading scripts with `read` — by default none, so only what the command itself staged
    is judged."""
    top = delimit(command.split("\n"))
    denying = [match for match in all_matches(top, location, read=read) if not match.is_exempt]
    first = denying[0] if denying else first_self_match(top, command, platform)
    if first is None:
        return Silent()
    override = read_override(annotate(top), command)
    if override.state is State.VALID and override.reason is not None:
        if not denying:
            return Silent()
        changed = (path for match in denying for path in match.authored_paths)
        return Acknowledge(override.reason, tuple(dict.fromkeys(changed)))
    return Deny(
        first,
        invalid_marker=override.state is State.INVALID,
        marker_in_content=override.marker_in_content,
    )


def all_matches(top: Unit, location: Location, *, read: Reader | None) -> list[FormMatch]:
    """Every form matching anywhere in the command, scanned bodies included, in order.

    Each pipeline is judged under what the pipelines before it in its own unit changed: the
    variables they bound, the directory a `cd` moved to — the latter only in a unit with no `(`
    subshell, whose `cd` would not outlive it — and, for row 6, the scripts a heredoc staged. A
    same-line `$(…)` is a subshell too, so what its commands bind or move is not carried on, and a
    `(` inside one is not the unit's. A scanned body starts from the payload's own location,
    under-exempting rather than guessing what its shell inherited. A scratch script's text is
    judged here too, from where it runs and with `read` withheld, so it reads no file of its own.
    """
    matches: list[FormMatch] = []
    for unit in top.walk():
        pipelines = parse(annotate(unit))
        own = [
            command for pipeline in pipelines for command in pipeline if not command.in_substitution
        ]
        follows_cd = not any(
            token.boundary is Boundary.SUBSHELL for command in own for token in command.tokens
        )
        here = location
        staged: dict[str, str] = {}
        script_runs = ScriptRuns(staged, read, _script_text_matches)
        for pipeline in pipelines:
            matches.extend(match_pipeline(pipeline, here, script_runs))
            staged.update(staged_texts(pipeline, here))
            for command in pipeline:
                if command.in_substitution:
                    continue
                for name, value in bound_variables(command):
                    here = here.binding(name, value)
                directory = changed_directory(command) if follows_cd else None
                if directory is not None:
                    here = here.moved_to(directory)
    return matches


def _script_text_matches(unit: Unit, location: Location) -> list[FormMatch]:
    return all_matches(unit, location, read=None)
