"""Consolidation: D29's grouping, the run and group state machine, leases, and the four verbs.

`design/consolidation.md` is normative for the grouping, `design/architecture.md` §"Consolidation
lifecycle" and §"Consolidator tool surface" for the lifecycle and the verbs, and `design/schema.md`
invariants 12-17 and 19 are what this package must hold. The shape of it, lowest layer first:

- `context` — what one call holds constant: the `(session_id, pid)` owner, the six `[consolidation]`
  keys, and the index it writes through.
- `runs` — the `consolidation_run` aggregate: the one effectively-active-run test, the lease and its
  arithmetic, the four statuses as guarded updates, and the `consolidate_run` events.
- `groups` — `consolidation_group` and its two child tables: group order, the state machine's
  transitions, dispositions, `remaining_uuids`, and the merge authorization set.
- `rowstate` — the two row-state re-checks a serve and the ladder both run, evaluated through the
one
  filter table's own SQL rather than mirrored in Python.
- `grouping` — the partition itself: anchor by retrieval, mutual-K with the cosine floor, connected
  components, the complete-linkage cohesion pass, deterministic sharding.
- `planning` — `plan_groups`: write one run's whole partition and close whatever preceded it.
- `payload` — the shapes the tools return, as unions a caller pattern-matches.
- `candidates` — the group-level candidate query: the one external query built from stored prose.
- `serving` — `next_group`: re-validate, close, defer or deliver, and iterate.
- `authorization` — the consolidator ladder, authorization before version, version before receipt.
- `verbs` — `merge`, `promote`, `discard`.

**Two things this package does not do.** It does not choose what to consolidate: code selects the
candidates and the model exercises judgment (D7), so nothing here decides that two memories *should*
merge — only which ones a consolidator is shown together. And it does not retry: the store's own
state is the record of what happened, so a model that returns nothing loses no rows and needs no
nudge protocol, which is what the prior art's `===CONSOLIDATION===` block needed one for.
"""
