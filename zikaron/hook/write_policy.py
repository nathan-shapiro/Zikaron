"""The `agentSpawn` prompt text, transcribed from `design/write-policy.md` §2's two fences.

`architecture.md` §"Warming": the hook process "prints the write policy — static text, no RPC, so
it can never fail." The shipped texts below are those strings, and `read_policy` is the one
deliberate extension to them: an operator-authored `.zikaron/write-policy.md` is printed instead
**when it reads cleanly**, and every reason it might not falls back to the constant its caller
named — so the never-fail property holds because the fallback is in-process, not because nothing is
attempted (`architecture.md` §"The install contract").

**Two constants, differing in one paragraph**, because the main-agent text describes a block the
subagent is never sent. One override replaces either: an operator writing a policy is stating what
this project's agents should do, not maintaining our split.

Why an override exists at all: the design ships this text as a *draft to be experimented against*,
and an experiment that requires editing installed Python is an experiment nobody runs.

Transcribed rather than read from disk by default: the design document is not shipped alongside
the installed package, and `design/write-policy.md` itself is drafted for revision, so a test
(`tests/test_hook_write_policy.py`) parses that document at test time and compares it against these
constants — the same drift-guard shape `tests/design_tables.py` already uses for the design's own
tables, applied here to a piece of text rather than a table.
"""

import contextlib
import errno
import os
import stat
from pathlib import Path
from typing import NamedTuple

from zikaron.harness.spec import HarnessSpec
from zikaron.hook import failure
from zikaron.service.paths import hook_log_path, store_dir, write_policy_override_path

#: The override's own file name, derived from the one place its path is constructed so the two
#: cannot disagree. A name rather than a path, because it is opened relative to a directory
#: descriptor.
_OVERRIDE_FILENAME = write_policy_override_path(Path()).name

#: Fixed `hook.log` labels for the four conditions under which an override is not simply used as
#: found. Fixed labels rather than formatted messages, because `architecture.md` §"Filesystem
#: security" holds `hook.log` to "a fixed failure-kind label and an error code, never prompt or
#: memory content" — and an operator's own policy file *is* content.
OVERRIDE_REFUSED = "write_policy_override_refused"
OVERRIDE_UNREADABLE = "write_policy_override_unreadable"
OVERRIDE_EMPTY = "write_policy_override_empty"
OVERRIDE_OVERSIZE = "write_policy_override_oversize"

WRITE_POLICY_PROMPT = """## Project memory (Zikaron)

This project has a memory store of what was learned by working here and is not in the source
code. It persists across sessions, and other agents read what you write.

**Look things up before you spend time.** A block of headlines is injected with each user message,
chosen for the words in that message, not for the problem as you understand it now. Each headline
names a record; the record holds the finding, its conditions and its exceptions. The block does
not follow the task once you reframe it, and nothing new arrives until the user speaks again.

Search with zikaron_memory_search when one of these happens, not when the effort ahead feels big
enough to deserve it:
- **Something surprised you.** A step failed in a way you did not predict, or code behaves
  differently from how it reads.
- **You are about to propose** a design, a mechanism or a plan.
- **You are about to say an approach will not work.**
- **You are about to rename, move or delete** something other work depends on.

When you propose a design or a plan, or call an approach a dead end, say what you searched for and
what came back, including "searched X, found nothing relevant". A hit is evidence about what
happened then, not a ruling about what must happen now: it tells you what to re-check, not which
option to drop.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out. This store is for what cost someone time to discover.

Worth recording with zikaron_memory_remember:
- How to build, test, run and deploy, above all the step the README omits
- Failures and their causes, especially silent ones: the symptom, the actual cause, the fix
- Environment requirements: env vars, services and versions that matter, and which credentials
  are needed and where to obtain them
- Constraints and prohibitions with their reason: "do not use X yet, because Y"
- Approaches already tried that did not work, and how they failed
- Conventions and preferences that are settled and written down nowhere

Not worth recording: what the source already says; transient state ("currently on branch
fix-123"); a general fact about a language or tool on its own. Record the decision a general fact
forced here: not "the test runner parallelizes by default" but "tests here run serially, because
the fixtures share one database".

**Never record a secret or personal data.** The store is plaintext on disk, and retiring a record
does not erase it. Headline and content rules are in zikaron_memory_remember's description.

**Err toward writing.** The common failure is recording nothing. Near-duplicates are detected and
handed back, so write without checking first.

**Repair what misled you.** If a record you acted on turns out wrong or stale, establish the
current truth and amend it with zikaron_memory_amend. Retire a record only when it is no longer
true and has no replacement."""

#: The same policy for an agent the push never reaches. Only the second paragraph differs, and
#: it differs because the main text describes a block this reader is never sent: a subagent told
#: "nothing is injected for you" *as* an injection has been handed a false sentence first.
SUBAGENT_WRITE_POLICY_PROMPT = """## Project memory (Zikaron)

This project has a memory store of what was learned by working here and is not in the source
code. It persists across sessions, and other agents read what you write.

**Look things up before you spend time.** Nothing is pushed to you: no headlines arrive with a
message. Memory reaches you when you call zikaron_memory_search, or zikaron_memory_fetch with ids
you were handed. Each result is a headline naming a record; the record holds the finding, its
conditions and its exceptions.

Search with zikaron_memory_search when one of these happens, not when the effort ahead feels big
enough to deserve it:
- **Something surprised you.** A step failed in a way you did not predict, or code behaves
  differently from how it reads.
- **You are about to propose** a design, a mechanism or a plan.
- **You are about to say an approach will not work.**
- **You are about to rename, move or delete** something other work depends on.

When you propose a design or a plan, or call an approach a dead end, say what you searched for and
what came back, including "searched X, found nothing relevant". A hit is evidence about what
happened then, not a ruling about what must happen now: it tells you what to re-check, not which
option to drop.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out. This store is for what cost someone time to discover.

Worth recording with zikaron_memory_remember:
- How to build, test, run and deploy, above all the step the README omits
- Failures and their causes, especially silent ones: the symptom, the actual cause, the fix
- Environment requirements: env vars, services and versions that matter, and which credentials
  are needed and where to obtain them
- Constraints and prohibitions with their reason: "do not use X yet, because Y"
- Approaches already tried that did not work, and how they failed
- Conventions and preferences that are settled and written down nowhere

Not worth recording: what the source already says; transient state ("currently on branch
fix-123"); a general fact about a language or tool on its own. Record the decision a general fact
forced here: not "the test runner parallelizes by default" but "tests here run serially, because
the fixtures share one database".

**Never record a secret or personal data.** The store is plaintext on disk, and retiring a record
does not erase it. Headline and content rules are in zikaron_memory_remember's description.

**Err toward writing.** The common failure is recording nothing. Near-duplicates are detected and
handed back, so write without checking first.

**Repair what misled you.** If a record you acted on turns out wrong or stale, establish the
current truth and amend it with zikaron_memory_amend. Retire a record only when it is no longer
true and has no replacement."""


class _RefusedError(Exception):
    """The override, or the directory it would have come from, is not something to print."""


def _read_override(store_directory: Path) -> str:
    """The override's text, read through a **descriptor for the directory that was validated**.

    The shape here is the point: the directory is opened once and never resolved by name again. An
    earlier version called `store_directory.stat()`, returned a verdict, and then opened
    `store_directory / "write-policy.md"` — two resolutions of one pathname with a window between
    them. In a writable project parent another local user could swap the directory after it passed
    the ownership and mode check, or create an attacker-owned `.zikaron` after an absent one had
    been accepted, and the second resolution would read a policy out of the replacement. This text
    goes straight into a model's context, so that window is the whole risk.

    So: open `.zikaron` with `O_DIRECTORY | O_NOFOLLOW`, check ownership and mode on **that
    descriptor**, then open the override *relative to it* with `O_NOFOLLOW`. Every check applies to
    the inode that is actually read.

    Raises:
        FileNotFoundError: no store directory, or no override in it — the ordinary case.
        _RefusedError: the directory is a symlink or not a directory, is owned by somebody else, is
            reachable by group or other, or the override is not a regular file.
        OSError: it could not be opened or read.
        UnicodeDecodeError: it is not UTF-8.
    """
    try:
        directory = os.open(store_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except NotADirectoryError as exc:
        raise _RefusedError(str(store_directory)) from exc
    except OSError as exc:
        # `O_NOFOLLOW` reports a symlink as ELOOP and `O_DIRECTORY` a non-directory as ENOTDIR —
        # refusals, not absences. Anything else propagates.
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _RefusedError(str(store_directory)) from exc
        raise
    try:
        _require_private(directory, store_directory)
        return _read_regular_file(_OVERRIDE_FILENAME, directory=directory)
    finally:
        os.close(directory)


def _require_private(directory: int, store_directory: Path) -> None:
    """Refuse a store directory another user could have written into. Checked, never repaired.

    The condition an earlier version was missing, for a reason that was wrong: the argument was that
    any remaining writer must be the same uid, which is false of a store directory that is group- or
    world-writable for whatever reason. Another local user could then leave an ordinary
    `write-policy.md` there — no symlink involved, nothing `O_NOFOLLOW` can see — and this would
    print it into a model's context. `architecture.md` §"Filesystem security" draws the
    `0700`/ownership
    boundary for exactly that.

    Tightening a mode stays the warm helper's job (`ensure_store_dir`): doing it here would put a
    filesystem mutation on the one path whose contract is that it cannot fail.
    """
    info = os.fstat(directory)
    if info.st_uid != os.geteuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise _RefusedError(str(store_directory))


def _read_regular_file(name: str, *, directory: int) -> str:
    """`name`'s text, opened relative to `directory` without following a link, confirmed regular.

    `O_NOFOLLOW` and then `fstat` on the descriptor, rather than `is_symlink()`/`is_file()` followed
    by a read: those are two resolutions of one name, and whatever is decided about the first can
    be replaced before the second. Here the descriptor being read *is* the one whose type was
    checked.

    Opening a fifo would otherwise block the one path that must never fail, which `O_NONBLOCK` and
    the
    `fstat` together prevent.

    Raises:
        FileNotFoundError: nothing is there — the ordinary case.
        _RefusedError: something is there and it is not a regular file, a symlink included.
        OSError: it could not be opened or read.
        UnicodeDecodeError: it is not UTF-8.
    """
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _RefusedError(name) from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _RefusedError(name)
        with os.fdopen(descriptor, encoding="utf-8", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


class Policy(NamedTuple):
    """The text to print, and the one `hook.log` label this read earned, if any.

    A returned label rather than a log call inside the reader: this keeps the reader a pure function
    of the directory it is pointed at — testable with no log path and no directory creation — and
    keeps every `hook.log` write in the module that owns that file's contract (`failure.py`) rather
    than adding a second writer to it.
    """

    text: str
    note: str | None


def read_policy(store_directory: Path, *, spec: HarnessSpec, default: str) -> Policy:
    """The policy text to print: the override at `<store>/write-policy.md`, or `default`.

    `default` is the shipped constant for this reader — the main-agent text, or the subagent one
    for an agent the push never reaches. A single override replaces both, because an operator who
    writes a policy is stating what this project's agents should do, not maintaining our split.

    Six conditions, and only the first is silent, because only the first is normal:

    - **absent** — the ordinary case. `default`, no label.
    - **a symlink, reached through a `.zikaron` that is a symlink, or found in a store directory any
      other user could have written into** — refused; `_read_override` holds the whole condition,
      and it checks the directory it actually reads from rather than a pathname. The store directory
      is `0700`, so this is defence in depth rather than a live threat, but the cost of being wrong
      is specific: this text is printed straight into a model's context, so a link pointing at a
      private key or an `.env` file would exfiltrate exactly what the policy's own "never record a
      secret" paragraph exists to keep out of the store. The final component is refused by
      `O_NOFOLLOW`, which speaks for that component only — hence the separate check on the directory
      above.
    - **not a regular file** — refused, same reasoning; and a fifo would additionally block the one
      path `architecture.md` promises cannot fail, which `O_NONBLOCK` and the `fstat` together
      prevent.
    - **unreadable** — `default`. Permissions, a decoding error, a disk problem: one case.
    - **blank** — `default`. An empty override is far likelier an accident than an instruction to
      inject no policy at all, and silently dropping the write policy entirely is the worse of the
      two readings to be wrong about.
    - **larger than this harness will inject** — used **anyway**, with a label. An operator would
      otherwise be left with a policy the model received part of and nothing anywhere saying so.
      Truncating it ourselves would be the same failure with our name on it; refusing it would
      discard the operator's stated intent. **The bound is the running harness's, in the running
      harness's unit**, which is why `spec` is a parameter rather than a module constant: the two
      supported harnesses differ by more than sixfold *and* by unit, so a single hard-coded byte
      figure would label almost nothing under the smaller of the two.
    """
    try:
        text = _read_override(store_directory)
    except FileNotFoundError:
        return Policy(default, None)
    except _RefusedError:
        return Policy(default, OVERRIDE_REFUSED)
    except (OSError, UnicodeDecodeError):
        return Policy(default, OVERRIDE_UNREADABLE)
    return _classify(text, spec, default)


def _classify(text: str, spec: HarnessSpec, default: str) -> Policy:
    """An override that was read: blank, oversize, or good as it is."""
    if not text.strip():
        return Policy(default, OVERRIDE_EMPTY)
    if spec.exceeds_injection_budget(text):
        return Policy(text, OVERRIDE_OVERSIZE)
    return Policy(text, None)


def resolved_policy_text(
    scope_dir: Path, *, spec: HarnessSpec, default: str = WRITE_POLICY_PROMPT
) -> str:
    """The policy text to inject: the override when it reads cleanly, else `default` — plus one
    `hook.log` line naming why, whenever the answer was something other than "no override is there".

    `default` is the main-agent text unless the caller says otherwise; `subagent_policy` passes the
    subagent one. It defaults rather than being required because the main agent is every trigger but
    that one, and a required argument here would be answered identically at every other call site.

    The impure companion to `read_policy`, which stays a pure function of the directory it is
    pointed at so it can be tested with no log path and no directory creation. Every caller that
    actually injects a policy wants the same three steps in the same order, and every one of them
    must survive a failure in any of them, so they are stated once here rather than repeated per
    trigger.

    Guarded whole rather than per-step: a caller's one guarantee is that it produces a policy, and
    no failure inside here — including a failure while logging another failure — may cost it that.
    """
    text = default
    with contextlib.suppress(Exception):
        directory = store_dir(scope_dir)
        policy = read_policy(directory, spec=spec, default=default)
        text = policy.text
        if policy.note is not None:
            failure.record_failure(hook_log_path(directory), policy.note)
    return text
