"""Which install a Zikaron entry in a file the user owns belongs to, and what merging over it costs.

`architecture.md` §"The install contract" is normative, for both targets alike. **An entry is
refused only when another install owns it** — a server entry by `MCP_OWNERSHIP_FIELDS`, the
interpreter path and the mode; a hook entry by its command, which each target reads from its own
hook shape. Any other difference is this install's own entry as an earlier version wrote it, so it
is an upgrade: merged and reported, never refused. Comparing entries whole makes every install
refuse its own upgrade the day an entry gains a key or a timeout moves.

Written once and imported by both targets, because two copies of the rule that decides a refusal
is how one of them ends up comparing something the other does not.
"""

from pathlib import Path
from typing import Final

from zikaron.install.entries import MCP_OWNERSHIP_FIELDS
from zikaron.install.harness import InstallError

#: The explanation every ownership refusal ends in, whichever shape of entry it guards.
ANOTHER_INSTALL: Final = (
    "That usually means another Zikaron install owns them, whose paths may point at a venv this "
    "one knows nothing about. Re-run with --force to replace them."
)


def ownership(entry: object) -> dict[str, object]:
    """The part of a server entry that says which install wrote it.

    A non-object entry projects to `{}`, which compares unequal to ours and is therefore refused —
    the safe direction for a malformed entry we did not write.
    """
    if not isinstance(entry, dict):
        return {}
    return {name: entry[name] for name in MCP_OWNERSHIP_FIELDS if name in entry}


def differing_ownership_fields(existing: object, ours: object) -> str:
    """Why one entry's ownership disagrees, in the reader's terms.

    Each differing field is named with both values, rather than only the entry, because the two
    call for different responses: `command` says another install points at a different interpreter
    — possibly a venv that no longer has Zikaron in it — while `args` says the same interpreter
    registered a different mode.
    """
    if not isinstance(existing, dict):
        return "not an object"
    theirs, mine = ownership(existing), ownership(ours)
    return "; ".join(
        f"{name} is {theirs.get(name)!r}, this install writes {mine.get(name)!r}"
        for name in MCP_OWNERSHIP_FIELDS
        if theirs.get(name) != mine.get(name)
    )


def refuse_conflicting(
    existing: object,
    ours: dict[str, object],
    *,
    path: Path,
    key: str,
    force: bool,
) -> None:
    """Refuse when a server entry we write is already present and another install owns it.

    Only the entries this install writes are compared. Anything else under the same key is the
    user's and is merged around, never inspected.

    Raises:
        InstallError: a Zikaron-owned entry's ownership differs and `--force` was not passed.
    """
    if force or not isinstance(existing, dict):
        return
    differing = {
        name: differing_ownership_fields(existing[name], value)
        for name, value in ours.items()
        if name in existing and ownership(existing[name]) != ownership(value)
    }
    if not differing:
        return
    named = ", ".join(f"{name} ({reason})" for name, reason in sorted(differing.items()))
    raise InstallError(
        f"{path} already carries {key} entries that differ from what this install would write "
        f"({named}). {ANOTHER_INSTALL}"
    )


def merged_server(
    existing: object, ours: object, *, name: str, force: bool, registered_for: str
) -> tuple[object, list[str]]:
    """One server entry: ours over theirs, keeping keys this installer does not write.

    Every direction of that is silent by construction and worth saying out loud, so the merge
    reports each. A key of ours the entry lacked is how an upgrade arrives, and the user should see
    it arrive. A value of ours that **replaces** a different one may be a deliberate choice being
    reverted — `alwaysLoad: false` set by a user who wants deferral — and it is reported on
    **either** path, because `--force` arrives for reasons of its own and is not a request to revert
    that. A key of *theirs* that survives rides into a server this install registers, and `env` in
    particular carries execution consequence; `registered_for` says for whom, since that differs by
    harness and the note must be true of its own file.

    `--force` replaces the entry whole, and names what it dropped. **It points at the backup without
    claiming what is in it**, because it cannot: the first backup wins, so the `.bak` on disk may
    predate the user's key, postdate it, or hold an older value of the same field.
    """
    if not isinstance(existing, dict) or not isinstance(ours, dict):
        if force and existing is not None and not isinstance(existing, dict):
            # No field can be named, but something was there and is now gone. Without the flag this
            # shape is refused and the refusal names it; `--force` skips that, and it arrives for
            # reasons of its own on which nothing else has mentioned this file.
            return ours, [
                f"`{name}`: --force replaced an entry that was not an object. "
                "Check the .bak beside the file for it."
            ]
        return ours, []
    kept = sorted(field for field in existing if field not in ours)
    # Ownership fields are excluded so a takeover stays unannounced, which is the decision the hook
    # paths make too. On the merging path this filters nothing: a differing `command` or `--mode`
    # was refused before reaching here.
    reported = [field for field in ours if field not in MCP_OWNERSHIP_FIELDS]
    overwritten = sorted(
        field for field in reported if field in existing and existing[field] != ours[field]
    )
    added = sorted(field for field in reported if field not in existing)
    kept_fields = ", ".join(f"`{field}`" for field in kept)
    it = "it" if len(kept) == 1 else "them"
    notes: list[str] = []
    if overwritten:
        fields = ", ".join(f"`{field}`" for field in overwritten)
        notes.append(f"`{name}`: {fields} differed and was set to this install's value.")
    if added:
        fields = ", ".join(f"`{field}`" for field in added)
        notes.append(f"`{name}`: {fields} added, which the entry did not carry before.")
    if force:
        if kept:
            notes.append(
                f"`{name}`: --force replaced the entry whole, dropping {kept_fields}. "
                f"Check the .bak beside the file for {it}."
            )
        return ours, notes
    if kept:
        notes.append(
            f"`{name}`: kept {kept_fields}, which this install did not write — "
            f"review {it}, since this install registers that server {registered_for}."
        )
    return {**existing, **ours}, notes
