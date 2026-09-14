"""Writing a tool result too large to return, to a file the model can actually read.

A harness caps what a tool result may contain. Claude Code's cap is stated in tokens, is never
named numerically, and an over-large result is replaced wholesale by an error notice — so the
consolidator sees no group, cannot decide it, and is served the same group again on the next call.
The run cannot advance past it.

**The harness already writes the result to a file, and that file is unreadable.** It holds the
tool's JSON on one line, and `Read` says outright that such a file "cannot be paginated by line":
measured, 31,247 of 104,179 characters returned and `offset`/`limit` refused. So recovering the
payload through the harness's own spill is not available, however the grant is arranged.

**What is available is writing the file ourselves.** `Read`'s cap applies per read, not per file —
a 206,719-character, 2,002-line file was read to its end in three calls — so a payload is fully
recoverable if, and only if, whoever wrote it made it line-paginable. That is the one thing the
harness does not do and this module does.

Both bounds here are **proofs rather than margins**, which is what keeps them from needing revision
as corpora grow or the harness moves a cap it has never published. A token spans at least one byte,
so bytes bound tokens for any content whatsoever — emoji, CJK, minified code — provided the counter
does not expand its input before counting, which byte-level BPE cannot. No characters-per-token
ratio appears anywhere below.
"""

import atexit
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The largest line this module will write, in UTF-8 bytes of the serialized line. At most this
#: many tokens, therefore, and `Read`'s measured per-read cap is 25,000 — so any line under this is
#: addressable, and a line is the smallest unit `Read` can address. Not a config key, because there
#: is no operator remedy for a single over-long record: the answer is to amend or retire it, and
#: raising a number would only move where the unreachable tail begins.
SPILL_MAX_LINE_BYTES: Final = 24_000

#: `json.dumps` indent. Structure goes onto its own lines, which is what makes `offset`/`limit`
#: work at all — but note what it does *not* do: indentation splits structure, never strings, so a
#: record's `content` remains exactly one line however this is set. That is why the line bound
#: above exists rather than being implied by pretty-printing.
_INDENT: Final = 2

#: `{store_key}-{tool}-{pid}-{random}`: four hyphen-separated fields, which is what lets a
#: name be read back for the pid without a regex, and what a shorter name is rejected against.
_NAME_FIELDS: Final = 4

#: `0600`. The file holds record prose verbatim, outside the store and outside the log rules.
_FILE_MODE: Final = 0o600


class PayloadLineTooLongError(Exception):
    """A single value is too long to write on a line any reader could address.

    Raised instead of writing a file whose tail is unreachable — the failure this whole module
    exists to prevent, arriving through its own output. Carries the offending record's uuid where
    one can be found, because unlike the threshold there is no key to lower: the remedy is to amend
    or retire that record, and this is the only thing that can say which.
    """

    def __init__(self, *, uuid: str | None, line_bytes: int) -> None:
        where = f"record {uuid}" if uuid else "a value in this payload"
        # The tail stays uuid-neutral because `where` may not have named one: an instruction to
        # report "that uuid" after a message that never gave one is worse than no instruction.
        super().__init__(
            f"{where} serializes to {line_bytes} bytes on one line, over the {SPILL_MAX_LINE_BYTES}"
            " byte maximum a reader can address, so this payload cannot be delivered whole."
            " Report this refusal and carry on with the run: shortening the record needs the"
            " primary agent or the operator, and neither verb for it is yours."
        )
        self.uuid = uuid
        self.line_bytes = line_bytes


@dataclass(frozen=True, slots=True)
class SpillPolicy:
    """Whether to spill, above what size, and where to put the file.

    `enabled` comes from the harness seam rather than from a branch on the detected harness, and
    it is one flag for both the capability and its use: a harness whose consolidator cannot read a
    file must not be handed a path, and one that can gains nothing from being told about a file
    that was never written.
    """

    enabled: bool
    threshold_bytes: int
    directory: Path
    #: Identifies this store in a filename. The runtime directory is shared by every store this
    #: user has — sockets disambiguate by the same hash — so without it an operator erasing a
    #: secret cannot tell one store's spill files from another's without reading them.
    store_key: str


def apply(result: object, *, policy: SpillPolicy, tool: str) -> object:
    """`result` if it fits, else a pointer to a file holding it.

    Args:
        result: the value a tool handler would otherwise return.
        policy: whether spilling is available here, and its bound.
        tool: names the file, so a directory of them is readable by eye.

    Returns:
        `result` unchanged when it fits or when spilling is unavailable, otherwise a pointer
        object. The pointer carries no `journal_entries` key, which is what stops it being read as
        a served group by a consolidator that skimmed it.

    Raises:
        PayloadLineTooLongError: a single value would exceed `SPILL_MAX_LINE_BYTES`.
        OSError: the file could not be written.
    """
    if not policy.enabled:
        return result
    # The threshold is compared against the **compact** encoding, because that is what the inline
    # path would have sent and therefore what the harness would have had to carry. Indentation is
    # added only once the decision to spill has been made: measuring the indented form would test a
    # document that is never transmitted, and would put the decision a few percent above the
    # quantity the default was calibrated against.
    inline = json.dumps(result, ensure_ascii=False)
    if len(inline.encode("utf-8")) <= policy.threshold_bytes:
        return result
    document = json.dumps(result, ensure_ascii=False, indent=_INDENT)
    _refuse_unaddressable_line(result, document)
    path = _write(document, directory=policy.directory, tool=tool, store_key=policy.store_key)
    return {
        "spilled": True,
        "path": str(path),
        "bytes": len(inline.encode("utf-8")),
        "note": (
            "This result was too large for this harness to deliver, so Zikaron wrote it to the "
            "file above. That file is your payload: read it, to its end, and decide from it "
            "exactly as you would have from a result delivered inline."
        ),
    }


def _refuse_unaddressable_line(result: object, document: str) -> None:
    """Raise if any line of `document` is longer than a reader can address.

    Checked against the rendered document rather than against the values it came from, because it
    is the rendered line a reader has to fetch — an escape expansion that happens during
    serialization would otherwise be invisible to a check run before it.
    """
    longest = max((len(line.encode("utf-8")) for line in document.splitlines()), default=0)
    if longest <= SPILL_MAX_LINE_BYTES:
        return
    raise PayloadLineTooLongError(uuid=_uuid_of_longest_value(result), line_bytes=longest)


def _uuid_of_longest_value(result: object) -> str | None:
    """The uuid of the record carrying the longest string in `result`, if it has one.

    Best effort by design: the bound is enforced on the rendered line above, and this only makes
    the failure actionable. A payload shape with no uuids still raises, just without naming one.
    """
    worst_uuid: str | None = None
    worst_length = -1
    stack: list[object] = [result]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            uuid = current.get("uuid")
            for value in current.values():
                if isinstance(value, str):
                    # Measured as it will be *rendered*, not raw, so this ranks by the same
                    # quantity the refusal does. A value heavy in quotes, backslashes or newlines
                    # nearly doubles when escaped, and ranking raw lengths can therefore name a
                    # record that is not the one over the bound.
                    rendered = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
                    if rendered > worst_length:
                        worst_length = rendered
                        worst_uuid = uuid if isinstance(uuid, str) else None
                elif isinstance(value, dict | list):
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return worst_uuid


def _write(document: str, *, directory: Path, tool: str, store_key: str) -> Path:
    """Write `document` and return its path, at `0600`, with a name unique to this write.

    **Unique per write rather than per group**, and nothing already written is removed to make
    room. A re-serve must not overwrite a file a reader is partway through — and deleting the
    previous spill would be worse than overwriting it: a `merge`/`promote`/`discard` conflict
    response spills through this same path, so "delete the last one" would remove the group's own
    payload while the consolidator is still dispositioning that group from it.

    The name carries `store_key` because the runtime directory is shared by every store this user
    has, and an operator erasing a secret needs to find one store's files without reading them.

    Created at `0700` explicitly rather than at the process umask. The directory is the socket's
    own home and so provably existed moments ago, vetted by whoever spawned the service; this
    neither repeats that vetting nor silently relaxes it — the file itself is `0600`, `O_EXCL` and
    unpredictably named, which is what the contents actually rest on.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{store_key}-{tool}-{os.getpid()}-{os.urandom(8).hex()}.json"
    # Opened through `os.open` with the mode supplied, rather than written and then chmod-ed: the
    # window between those two is one in which record prose sits at the process umask.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(document)
    except BaseException:
        # A tmpfs that filled mid-write would otherwise leave a truncated file behind, occupying
        # the space that caused the failure and looking from the outside like a readable payload.
        path.unlink(missing_ok=True)
        raise
    _written.append(path)
    return path


#: Every spill this process has written and has not yet released.
_written: Final[list[Path]] = []


def release_finished(policy: SpillPolicy) -> None:
    """Unlink every spill this process wrote before now. Call when the next group is requested.

    **Safe for a narrower reason than it first appears, and the narrow one is what holds.** It is
    *not* that the previous group becomes unreachable: authorization is rewritten per group rather
    than globally, a failed request rewrites nothing at all, and an unfinished group is deliberately
    re-served before the run advances — so a consolidator can and does come back to it. What makes
    the release safe is that **every route back passes through a fresh serve, which spills a fresh
    copy**, so a released file is never the last copy of anything still reachable.

    **Releasing on any earlier signal would not be safe.** A `merge`/`promote`/`discard` conflict
    response spills through this same path, so "release when writing the next file" would delete the
    group's own payload while the consolidator is still reading it to disposition that very group.
    The trigger is a new *group*, not a new *file*, and that distinction is the whole of it.

    This bounds what is live to one group's files rather than a whole run's, and a run that ends
    properly leaves nothing: a consolidator learns the run is over by calling for a group and
    receiving `{done: true}`, and that call releases the last group first. What `sweep_stale`
    reaches is the run that *stops without asking again* — a killed process, or a consolidator that
    quits after the final `group_complete`.
    """
    if not policy.enabled:
        return
    _unlink_all(_written)
    _written.clear()


def sweep_stale(policy: SpillPolicy) -> None:
    """Unlink this store's spill files left behind by processes that are no longer running.

    **This is the mechanism that actually reaches a killed process, and killed is how these
    processes end.** A harness runs one MCP server per session and terminates it when the session
    ends; a terminated process runs no `atexit` handler, and one killed outright could not run one
    anyway. So cleanup cannot depend on this process's own exit — it depends on the *next* one's
    start, which needs nothing from the dead.

    Scoped by store key and by liveness, both read straight off the filename. A file whose pid is
    still running is left alone: it may belong to a concurrent consolidator on the same store, and
    it may be being read right now.

    **One window this cannot close, named so it is not met as a bug.** The pid in the name is the
    MCP *server's*; the reader is the harness session's own file-reading tool. If a server dies
    mid-session and the harness starts a replacement, that replacement sweeps its predecessor's
    files — possibly including the group the session is partway through reading. The failure is the
    acceptable kind: the continuation read fails loudly with a missing file, and one more request
    re-serves the group with a fresh copy. It is also the real reason the primary client must not
    sweep — liveness alone would protect a *live* consolidator's files, but a primary sweeping at
    every session start would widen exactly this dead-writer window.
    """
    if not policy.enabled:
        return
    ours = os.getpid()
    stale = []
    for path in policy.directory.glob(f"{policy.store_key}-*.json"):
        pid = _pid_of(path.name)
        if pid is None or pid == ours or _is_running(pid):
            continue
        stale.append(path)
    _unlink_all(stale)


def _pid_of(name: str) -> int | None:
    """The pid component of a spill filename, or `None` if this is not one of ours.

    The name is `{store_key}-{tool}-{pid}-{random}.json`; the store key is hex and tool names carry
    underscores rather than hyphens, so the pid is the second-to-last hyphen-separated field. An
    unparseable name is left alone rather than guessed at — this function decides what to delete.
    """
    parts = name.removesuffix(".json").split("-")
    if len(parts) < _NAME_FIELDS:
        return None
    try:
        return int(parts[-2])
    except ValueError:
        return None


def _is_running(pid: int) -> bool:
    """Whether `pid` is a live process. `PermissionError` means it exists under another user."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _unlink_all(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # One file this process cannot remove must not strand the rest.
            continue


def _unlink_written_at_exit() -> None:
    """Registered for a clean exit, which is not how these processes usually end.

    Kept because it costs nothing and covers the case where one does exit normally — a test, an
    embedding, a harness that terminates gracefully. It is explicitly **not** the mechanism the
    design relies on; `sweep_stale` is, and the reason is measured: a real consolidation left four
    spill files behind, because the harness killed the server rather than letting it exit.
    """
    _unlink_all(_written)
    _written.clear()


atexit.register(_unlink_written_at_exit)
