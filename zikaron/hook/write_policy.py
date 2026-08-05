"""The `agentSpawn` prompt text, transcribed once from `design/write-policy.md` §2.

`architecture.md` §"Warming": the hook process "prints the write policy — static text, no RPC, so
it can never fail." The shipped text below is that string, and `read_policy` is the one deliberate
extension to it: an operator-authored `.zikaron/write-policy.md` is printed instead **when it reads
cleanly**, and every reason it might not falls back to this constant — so the never-fail property
holds because the fallback is in-process, not because nothing is attempted
(`architecture.md` §"The install contract").

Why an override exists at all: the design ships this text as a *draft to be experimented against*,
and an
experiment that requires editing installed Python is an experiment nobody runs.

Transcribed rather than read from disk by default: the design document is not shipped alongside
the installed package, and `design/write-policy.md` itself is drafted for revision, so a test
(`tests/test_hook_write_policy.py`) parses that document at test time and compares it against this
constant — the same drift-guard shape `tests/design_tables.py` already uses for the design's own
tables, applied here to a piece of text rather than a table.
"""

import errno
import os
import stat
from pathlib import Path
from typing import NamedTuple

from zikaron.hook.limits import MAX_OUTPUT_SIZE
from zikaron.service.paths import write_policy_override_path

#: The override's own file name, derived from the one place its path is constructed so the two
#: cannot
#: disagree. A name rather than a path, because it is opened relative to a directory descriptor.
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

This directory has a memory store holding **tribal knowledge**: what has been learned by working
here that the source code does not tell you. It persists across sessions, and other agents will
read what you write.

**Look things up before you spend time.** A few relevant gists are injected ahead of each message
you receive, but they are only what matched *that message* — the store holds more, and nothing else
arrives unasked. Search it whenever you are about to spend real effort: a step failed in a way you
did not expect, something behaves differently from how it reads, or you are planning, brainstorming
or weighing options. Planning is the case most often skipped and often the most valuable, because
this is where "we tried that already, and here is how it failed" lives — one query costs a fraction
of rediscovering it. What you find is evidence about what happened then, not a ruling about what
must happen now: check that its conditions still hold before letting it decide anything.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out — a separate system covers code structure, symbols and layout. This store is for what cost
someone time to discover.

Worth recording:
- How to build, test, run and deploy — especially the step that is not in the README
- Failures and their causes, above all silent ones: the symptom, what it actually was, what fixed it
- Environment requirements: which env vars and services must be set up, which versions matter, and
  **which** credentials are needed and how to obtain them
- Constraints and prohibitions *with their reason*: "do not use X yet, because Y"
- Approaches already tried that did not work, so nobody spends that afternoon twice
- Conventions and preferences that are settled but written down nowhere

**Never record a secret.** No tokens, passwords, API keys, private keys, connection strings with
credentials in them, or copied `.env` contents — and no personal data. Names and procedures, never
values: "needs GITHUB_TOKEN with repo scope, mint one at <settings page>" is right;
"GITHUB_TOKEN=ghp_..." is not. This store is plaintext on disk, it is read by every future
session, and retiring a memory does not erase it.

Not worth recording: where code lives or what a function does, or anything else derivable from the
source; transient state ("currently on branch fix-123"); facts about a language or tool in general
rather than about this project.

**Write observations, not orders.** Record what was learned and what happened — "deploying without
--force left the old worker running" — rather than standing instructions to future agents. Other
agents read these as reference material, and a memory phrased as a command will be obeyed by
someone with less context than you have.

**If a claim expires, the gist has to say so.** Some things are true only for now — during a
migration, until a fix lands, for one version of a dependency. A future agent sees the gist first
and often sees nothing else, so a condition you leave in the content is a condition that gets
dropped: "do not use the new API" recalled without "until the 2.0 release" becomes a permanent rule
nobody intended. Put the condition in the gist itself, or do not record the claim. If it will not
fit in one line, that is a sign the observation is about a passing situation rather than about this
project, and the right move is to leave it out.

**Err toward writing.** The common failure is recording nothing, not recording too much. If you just
spent real time discovering something, record it — near-duplicates are detected and handed back to
you, so you do not need to check first.

**Gists are for triage.** A future agent sees only gists and must judge from them alone whether to
read further. Lead with the observable symptom or situation rather than the conclusion:
"integration tests flake on CI unless PGHOST is set" beats "notes on test configuration".

**Keep a gist to one sentence of about 20 to 25 words.** The limit is 64 tokens — roughly 50 words
of ordinary prose — and a write over it is rejected outright, costing you the call. If a gist
strains toward that limit it is usually carrying content that belongs in `content`.

**Repair what misled you.** If a memory surfaces, you act on it, and it turns out to be wrong or
stale, correcting it is your job: establish the current truth and amend the memory. Fetch it first
— you need its version to write. Retire a memory only when it is simply no longer true and has no
replacement."""


class _RefusedError(Exception):
    """The override, or the directory it would have come from, is not something to print."""


def _read_override(store_directory: Path) -> str:
    """The override's text, read through a **descriptor for the directory that was validated**.

    The shape here is the point: the directory is opened once and never resolved by name again. An
    earlier version called `store_directory.stat()`, returned a verdict, and then opened
    `store_directory / "write-policy.md"` — two resolutions of one pathname with a window between
    them. In a writable project parent another local user could swap the directory after it passed
    the
    ownership and mode check, or create an attacker-owned `.zikaron` after an absent one had been
    accepted, and the second resolution would read a policy out of the replacement. This text goes
    straight into a model's context, so that window is the whole risk.

    So: open `.zikaron` with `O_DIRECTORY | O_NOFOLLOW`, check ownership and mode on **that
    descriptor**, then open the override *relative to it* with `O_NOFOLLOW`. Every check applies to
    the
    inode that is actually read.

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
    print
    it into a model's context. `architecture.md` §"Filesystem security" draws the `0700`/ownership
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
    by
    a read: those are two resolutions of one name, and whatever is decided about the first can be
    replaced before the second. Here the descriptor being read *is* the one whose type was checked.

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


def read_policy(store_directory: Path) -> Policy:
    """The policy text to print: the override at `<store>/write-policy.md`, or the shipped constant.

    Six conditions, and only the first is silent, because only the first is normal:

    - **absent** — the ordinary case. The constant, no label.
    - **a symlink, reached through a `.zikaron` that is a symlink, or found in a store directory any
      other user could have written into** — refused; `_read_override` holds the whole condition,
      and
      it checks the directory it actually reads from rather than a pathname. The store directory is
      `0700`, so this is defence in depth rather than a live threat, but the cost of being wrong is
      specific: this text is printed straight into a model's context, so a link pointing at a
      private
      key or an `.env` file would exfiltrate exactly what the policy's own "never record a secret"
      paragraph exists to keep out of the store. The final component is refused by `O_NOFOLLOW`,
      which
      speaks for that component only — hence the separate check on the directory above.
    - **not a regular file** — refused, same reasoning; and a fifo would additionally block the one
      path `architecture.md` promises cannot fail, which `O_NONBLOCK` and the `fstat` together
      prevent.
    - **unreadable** — the constant. Permissions, a decoding error, a disk problem: one case.
    - **blank** — the constant. An empty override is far likelier an accident than an instruction to
      inject no policy at all, and silently dropping the write policy entirely is the worse of the
      two readings to be wrong about.
    - **larger than `MAX_OUTPUT_SIZE`** — used **anyway**, with a label. The harness truncates past
      that bound silently, so an operator would otherwise be left with a policy the model received
      half of and nothing anywhere saying so. Truncating it ourselves would be the same failure with
      our name on it; refusing it would discard the operator's stated intent.
    """
    try:
        text = _read_override(store_directory)
    except FileNotFoundError:
        return Policy(WRITE_POLICY_PROMPT, None)
    except _RefusedError:
        return Policy(WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)
    except (OSError, UnicodeDecodeError):
        return Policy(WRITE_POLICY_PROMPT, OVERRIDE_UNREADABLE)
    return _classify(text)


def _classify(text: str) -> Policy:
    """An override that was read: blank, oversize, or good as it is."""
    if not text.strip():
        return Policy(WRITE_POLICY_PROMPT, OVERRIDE_EMPTY)
    if len(text.encode("utf-8")) > MAX_OUTPUT_SIZE:
        return Policy(text, OVERRIDE_OVERSIZE)
    return Policy(text, None)
