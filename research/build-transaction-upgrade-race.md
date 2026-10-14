# A build killed by a brief concurrent writer, and a second build `refresh` should never have spawned

**Diagnosed 2026-10-13**, for the flaky
`tests/test_knowledge_cli_integration.py::test_the_foreground_command_the_verb_prints_actually_builds_the_corpus`,
which failed once under `./check.sh` at load ~6.5 with *the build left it reindex_required*. The
diagnosis was delegated and its load-bearing claims were re-checked against the tree; the
reproduction harness lived in a session scratchpad and is not kept. **Two product defects, and the
test is right**: it runs the provisioning sequence `design/knowledge-index.md` §9 names, `add` then
`refresh --wait`, and a user running the same two commands hits both.

## 1. A build's per-file transaction fails at once when another connection holds the write lock

A build's transactions on its corpus database open a deferred `BEGIN`, and the first statement of
each is a read — `writes._clear`'s `_stored_chunks` SELECT. **SQLite refuses the read-to-write
upgrade immediately when another connection holds the write lock, and `busy_timeout` does not
retry it.** The build fails, releases its lock without recording completion, and the corpus is
left `reindex_required`.

Measured with no Zikaron code (`spikes/sqlite_deferred_upgrade_busy.py`, WAL mode, SQLite 3.45.1,
another connection holding the write lock for 0.300 s, `busy_timeout` 5 s):

| first statement | outcome |
|---|---|
| `BEGIN` | `database is locked` (extended code 5) after **0.000 s** |
| `BEGIN IMMEDIATE` | committed after 0.339 s |

**Two writers reach a corpus database during a build, and either can kill it:**

- **A losing build's lock acquisition.** `scan._begin` reads the holder without a transaction,
  then takes the lock under `BEGIN IMMEDIATE`. A second build spawned in the same model-load window
  passes the first read, waits for the write lock, gets it, reads the winner's holder and refuses —
  holding the write lock for the moment that takes. A winner whose per-file transaction is between
  its SELECT and its first write in that moment fails. Under load the moment stretches.
- **A search's counter commit** (`counters.py`), landing between a build's SELECT and its first
  write. So searching a corpus while it builds — which `design/knowledge-index.md` §6.3 supports —
  can kill the build.

**The design states the general rule and exempted this case from it.** `design/architecture.md`
§"The service's connections" says a deferred transaction that reads before it writes is refused at
once and that `IMMEDIATE` closes it, then keeps the corpus databases deferred except for a build's
lock acquisition; `design/knowledge-index.md` §6.2 makes that acquisition the one corpus transaction
that opens `IMMEDIATE`. **Embedding runs before each per-file transaction opens**
(`zikaron/core/knowledge/disposal.py`, `_record_indexed`), so those transactions are short and
holding the write lock from their `BEGIN` costs only the read that precedes the first write.

Reproduced deterministically by pinning the interleaving — the loser holding the write lock for
500 ms across the winner's entry into its index phase: 5/5 failures with the test's exact message,
5/5 passes with the build's transactions made `IMMEDIATE`. A core-level variant, a second
connection holding `BEGIN IMMEDIATE` for 300 ms from the start of the index phase, failed 5/5 with
`database is locked` and passed 5/5 fixed; the counter-commit variant failed 3/3 and passed 3/3.

**Signature in a store**, for recognizing a recurrence: the winner's `knowledge_build` row has
`ok=false` and `error_code` `build_failed`, the loser's `knowledge_base_busy`; the corpus's `meta`
carries `last_scan_started_at` and `last_walk_completed_at` but no `last_scan_completed_at`, and
no lock rows.

## 2. `refresh` spawns a second build while the first is still loading its model

`add` spawns an indexer, which takes the corpus lock only after loading the model — about 1.2 s
after the spawn. `refresh` answers `already_indexing` only when a lock is held, so in that window it
answers `started` and spawns a second indexer. Over 25 natural runs at load ~8: `started` in 25 of
25, the second indexer spawned ~20 ms after the first, both builds running one after the other in
12. Run as two separate commands, `refresh` reached the service 0.62 s after `add`'s spawn, against
the first indexer's lock at ~1.29 s.

This duplicate spawn is what sets up §1's interleaving, and it breaks a promise of its own: in the
separate-command run, `refresh --wait` returned at 23.453 s while the build *it* started took the
lock at 23.614 s — after the command had exited, against §9's promise that the call returns only
once no indexer it started is running.

## 3. The fix proposed

- **Every transaction a build opens on its corpus connection is `BEGIN IMMEDIATE`**, set once on
  the build's connection rather than per call site, so a short hold by any other writer is waited
  out under `busy_timeout` instead of failing at the upgrade. The same for the read-then-clear in
  the lock's operator clearing. Amends `design/architecture.md` §"The service's connections" and
  `design/knowledge-index.md` §6.2 in the same commit.
- **The service answers `already_indexing` for a corpus whose spawned build is still alive**, before
  it holds the lock — the service already holds each spawned process — and the client's `--wait`
  waits on that answer the way it waits on a build it started.
- **Pinned by tests**: a second connection holding the write lock across the build's entry into its
  index phase, and a counter commit between a build's read and its write, each asserting the scan
  completes — both fail deterministically today; a structural test that every `BEGIN` a build
  issues is `IMMEDIATE`; and a service test that a refresh during a live spawned build spawns
  nothing.
