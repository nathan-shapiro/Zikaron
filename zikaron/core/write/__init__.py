"""The tool-facing write path: `zikaron_remember`, `zikaron_amend`, `zikaron_retire`.

`design/architecture.md` §"MCP tool surface" and §"Validation precedence" (primary-agent ladder)
are normative; `design/schema.md` §Bounds is normative for `gist_max_tokens`, the one bound this
layer rejects an agent write for.

This package is deliberately thin. Every row-level rule — versioning, receipts, supersession,
chunking, the FTS5/`vec0` sync, invariant 10's rejection carve-out — already exists, in
`records.memory`, `indexing.writes` and `records.supersession`; those layers compose their own
transactions and this one calls into them rather than reimplementing any part of the ladder. What
this layer owns outright is D15's dedup hand-back (`write.dedup`), because nothing below it needs
to run a hybrid search, and catching a `ZikaronError` carrying `version_conflict` and returning it
as a typed `Conflict` value instead of letting it propagate — a Python-level discriminated union,
`Amended | Conflict` / `Retired | Conflict`, whose member the caller pattern-matches on. The wire
shape `architecture.md` states for the actual MCP response, `{conflict: true, current: ...}`, is a
transport concern: whichever client serializes `Conflict` is what writes the literal `true`, since
`isinstance(outcome, Conflict)` already *is* that fact at the Python level and a redundant boolean
field on the type would carry no information `isinstance` does not.

`zikaron_search` and `zikaron_fetch` are not here: they mutate nothing, so they stay
`retrieval.reads` and `records.memory.fetch` respectively, called directly by whichever transport
layer exposes them.
"""

from zikaron.core.write.dedup import DedupPolicy, NearDuplicate, offer
from zikaron.core.write.tools import (
    Amended,
    AmendOutcome,
    Conflict,
    Remembered,
    RememberOutcome,
    Retired,
    RetireOutcome,
    WriteCall,
    amend,
    remember,
    retire,
)

__all__ = [
    "AmendOutcome",
    "Amended",
    "Conflict",
    "DedupPolicy",
    "NearDuplicate",
    "RememberOutcome",
    "Remembered",
    "RetireOutcome",
    "Retired",
    "WriteCall",
    "amend",
    "offer",
    "remember",
    "retire",
]
