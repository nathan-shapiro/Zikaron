"""Which targets are scratch: `design/guards.md` §3.3.

A target is **scratch** when, with its quotes removed and a relative path joined to the payload's
`cwd` and normalised as a string — no filesystem access — it is or lies under one of the scratch
roots, compared component-wise; or when it is written as the literal `$TMPDIR/…` or `${TMPDIR…}/…`,
or as a background job's `$CLAUDE_JOB_DIR/tmp/…`. A target that begins with a variable the same
command bound (`S=/tmp/x; … > "$S/a"`) is read with that variable's value in its place.

>>> job = Location(cwd="/home/u/proj", job_dir="/home/u/.claude/jobs/j")
>>> [job.is_scratch(t) for t in ("/home/u/.claude/jobs/j/tmp/a", "/home/u/.claude/jobs/j/x")]
[True, False]
>>> spelled = ("$CLAUDE_JOB_DIR/tmp", '"${CLAUDE_JOB_DIR}/tmp/a"', "$CLAUDE_JOB_DIR/x")
>>> [Location(cwd="/home/u/proj").is_scratch(t) for t in spelled]
[True, True, False]
>>> here = Location(cwd="/home/u/proj", tmpdir="/var/folders/x/T")
>>> [here.is_scratch(t) for t in ("/tmp", "/tmpfoo", "'/tmp/a b'", "x", "../../../tmp/x")]
[True, False, True, False, True]
>>> [here.is_scratch(t) for t in ('"$TMPDIR"/p', "${TMPDIR:-/tmp}/p", "/private/var/folders/x/T")]
[True, True, True]
>>> here.resolve("~/f")
'/home/u/proj/~/f'
>>> bound = here.binding("S", "/tmp/s")
>>> [bound.is_scratch(t) for t in ('"$S/a"', "${S}/a", "$S", "$SP/a")], bound.resolve("$SP/a")
([True, True, True, False], '/home/u/proj/$SP/a')
"""

import posixpath
import re
from dataclasses import dataclass, replace
from typing import Final

#: The roots that are scratch on every machine. Compared as strings, never opened.
FIXED_ROOTS: Final = ("/tmp", "/var/tmp", "/dev")  # noqa: S108 — compared, not written

#: The roots macOS spells through `/private` when a tool canonicalises them. Every platform takes
#: them, since nothing on Linux lives there and the rule then needs no platform pin.
_PRIVATE_ALIASED: Final = ("/tmp", "/var/tmp")  # noqa: S108 — compared, not written

_QUOTE: Final = re.compile(r"\\?['\"]")
_TMPDIR_LITERAL: Final = re.compile(r"\$TMPDIR(?:/|$)|\$\{TMPDIR[^}]*\}(?:/|$)")
#: A leading `$TMPDIR`, `${TMPDIR}` or `${TMPDIR:-DEFAULT}`, or any other `${TMPDIR…}` form.
_TMPDIR_PREFIX: Final = re.compile(
    r"(?:\$TMPDIR|\$\{TMPDIR\}|\$\{TMPDIR:-(?P<default>[^}]*)\}|(?P<other>\$\{TMPDIR[^}]*\}))"
    r"(?=/|$)"
)
_JOB_DIR_VARIABLE: Final = r"\$(?:CLAUDE_JOB_DIR|\{CLAUDE_JOB_DIR\})"
_JOB_TMP_LITERAL: Final = re.compile(_JOB_DIR_VARIABLE + r"/tmp(?:/|$)")  # noqa: S108 — compared
_JOB_DIR_PREFIX: Final = re.compile(_JOB_DIR_VARIABLE + r"(?=/|$)")
#: A variable at a target's start, as `$NAME` or `${NAME}`, ending the target or followed by `/`.
_LEADING_VARIABLE: Final = re.compile(r"\$(?:\{(\w+)\}|(\w+))(?=/|$)")


def unquote(target: str) -> str:
    """`target` with every quote, and the backslash escaping it, removed."""
    return _QUOTE.sub("", target)


def normalise(path: str, cwd: str) -> str:
    """`path` joined to `cwd` when relative, and normalised as a string.

    >>> normalise("a/../b//c", "/w"), normalise("//x", "/w")
    ('/w/b/c', '/x')
    """
    joined = path if path.startswith("/") else f"{cwd}/{path}"
    return "/" + posixpath.normpath(joined).lstrip("/")


def is_under(path: str, root: str) -> bool:
    """Whether `path` is `root` or lies under it, component-wise."""
    return path == root or path.startswith(root.rstrip("/") + "/")


@dataclass(frozen=True, slots=True)
class Location:
    """Where a command runs: the payload's `cwd`, the machine's `$TMPDIR`, the payload's
    `scratchpad_dir` where a version sends one, and a background job's directory, the hook's
    `CLAUDE_JOB_DIR`."""

    cwd: str
    tmpdir: str | None = None
    scratchpad: str | None = None
    job_dir: str | None = None
    #: The variables the command bound before the target, as `(name, value)`, latest last.
    bindings: tuple[tuple[str, str], ...] = ()

    def binding(self, name: str, value: str) -> "Location":
        """This location with `name` bound to `value`, replacing any earlier binding of it."""
        kept = tuple(pair for pair in self.bindings if pair[0] != name)
        return replace(self, bindings=(*kept, (name, unquote(value))))

    def moved_to(self, directory: str) -> "Location":
        """This location after a `cd` to `directory`, read as a target is."""
        return replace(self, cwd=self.resolve(directory))

    def resolve(self, target: str) -> str:
        """A target as the rules read it, so a misread shows in a message (`<cwd>/~/f`)."""
        return self.resolve_literal(unquote(target))

    def resolve_literal(self, text: str) -> str:
        """`resolve` for text that is no shell word — a script literal's contents, whose quotes are
        its own."""
        return normalise(self._substituted(text), self.cwd)

    def in_child(self) -> "Location":
        """Where a program this command runs starts: the same directory, and none of the
        command's unexported variables (§3.2, row 6's judging)."""
        return replace(self, bindings=())

    def file_path(self, target: str) -> str | None:
        """Where `target` is on disk, for row 6's one read: `resolve`'s path, except that a
        leading `$TMPDIR` is this machine's, or `${TMPDIR:-DEFAULT}`'s default when that is unset,
        and a leading `$CLAUDE_JOB_DIR` the hook's; `None` where the target names no file the rules
        can locate.

        >>> here = Location(cwd="/w", tmpdir="/t", job_dir="/j")
        >>> [here.file_path(t) for t in ('"$TMPDIR/a"', "${TMPDIR}/a", "x", "${TMPDIR%/}/a")]
        ['/t/a', '/t/a', '/w/x', None]
        >>> here.file_path("$CLAUDE_JOB_DIR/tmp/a"), here.file_path("${CLAUDE_JOB_DIR}/tmp/a")
        ('/j/tmp/a', '/j/tmp/a')
        >>> unset = Location(cwd="/w")
        >>> unset.file_path("${TMPDIR:-/tmp}/a"), unset.file_path("$TMPDIR")
        ('/tmp/a', None)
        >>> unset.file_path("$CLAUDE_JOB_DIR/tmp/a") is None
        True
        """
        text = self._substituted(unquote(target))
        job = _JOB_DIR_PREFIX.match(text)
        if job is not None:
            job_dir = self._usable(self.job_dir)
            return None if job_dir is None else normalise(job_dir + text[job.end() :], self.cwd)
        prefix = _TMPDIR_PREFIX.match(text)
        if prefix is None:
            return normalise(text, self.cwd)
        if prefix.group("other") is not None:
            return None
        value = self._usable(self.tmpdir) or prefix.group("default")
        return None if value is None else normalise(value + text[prefix.end() :], self.cwd)

    def is_scratch(self, target: str) -> bool:
        """Whether `target` is scratch."""
        text = self._substituted(unquote(target))
        if _TMPDIR_LITERAL.match(text) or _JOB_TMP_LITERAL.match(text):
            return True
        path = self.resolve(target)
        return any(is_under(path, root) for root in self.roots)

    def _substituted(self, target: str) -> str:
        """`target` with a bound variable at its start replaced by its value."""
        variable = _LEADING_VARIABLE.match(target)
        if variable is None:
            return target
        value = dict(self.bindings).get(variable.group(1) or variable.group(2))
        return target if value is None else value + target[variable.end() :]

    @property
    def roots(self) -> tuple[str, ...]:
        """Every scratch root here.

        A `$TMPDIR` or scratchpad that is empty or normalises to `/` is ignored, since it would
        make everything scratch. A job directory is normalised the same way, and only its `tmp` is
        scratch: the harness keeps the job's own state beside it.

        >>> Location(cwd="/w", job_dir="/j/").roots[-1], Location(cwd="/w", job_dir="rel").roots[-1]
        ('/j/tmp', '/w/rel/tmp')
        """
        tmpdir = self._usable(self.tmpdir)
        aliased = (*_PRIVATE_ALIASED, *([tmpdir] if tmpdir else []))
        scratchpad = self._usable(self.scratchpad)
        job_dir = self._usable(self.job_dir)
        return (
            *FIXED_ROOTS,
            *([tmpdir] if tmpdir else []),
            *(f"/private{root}" for root in aliased),
            *([scratchpad] if scratchpad else []),
            *([f"{job_dir}/tmp"] if job_dir else []),  # noqa: S108 — compared, not written
        )

    def _usable(self, root: str | None) -> str | None:
        if not root:
            return None
        resolved = normalise(root, self.cwd)
        return None if resolved == "/" else resolved
