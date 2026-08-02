"""Memory rows: versioning, soft retirement, supersession edges, and read receipts.

This package is the row-level layer `design/build-plan.md`'s M3 brief scopes: `memory` and
`read_receipt` mechanics with **no chunking** — `memory_chunk`, `memory_vec` and `memory_fts` stay
untouched here, per the milestone's own fence. Two consequences follow from that fence, stated
once here rather than at each place they bite:

- `create`/`amend` do not, themselves, emit `remember`/`amend` `event` rows. Those kinds carry
  `token_count`, `gist_tokens`, `n_chunks` and `truncated` — outputs of `indexing.md`'s chunking
  preflight — and `schema.md`'s own nullability table does not list them as nullable for these
  two kinds, unlike `merge`/`promote`, where a non-authoring row genuinely has none. An authoring
  write always has real prose, so these fields are meant to always be populated, which this
  milestone's fake embedder cannot do honestly. M4 wraps `create`/`amend` with the chunking
  preflight, in the **same** transaction (`indexing.md` §"Atomicity"), and emits the composed
  `remember`/`amend` event there, once real values exist to put in it. Each of `create`, `fetch`,
  `amend` and `retire` in `memory.py` is a thin, transaction-owning wrapper around a
  `_<verb>_within_transaction` function that assumes an already-open transaction and neither
  commits nor rolls back — M4 calls the neutral form directly, inside its own wider `BEGIN` that
  also covers the chunking writes and the composed event, rather than calling the wrapper, which
  would raise on a nested `BEGIN`.
- `create`/`amend`/`retire` here are row primitives, not the wire-facing `zikaron_remember` /
  `zikaron_amend` / `zikaron_retire` tools. M6 owns "core logic" for those three verbs — D15's
  dedup hand-back and the `gist_max_tokens` bound both live there — and composes them from what
  this package provides.

What this package *does* own outright, because none of it depends on chunking: `retire`'s event
(its `detail` has no chunking-derived field), and `fetch`, `version_conflict` and `no_receipt`,
none of which name a memory's size at all. Invariant 10 is asserted for exactly these four kinds
at this milestone; M4 and M6 each re-assert it for their own write paths, per the build plan's own
note that invariant 10 is cross-cutting.
"""
