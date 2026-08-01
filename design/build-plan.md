# Build plan

> Per-milestone briefs. `FINDINGS.md` carries the sequence and current position; this carries the detail a
> session needs to actually do one. Read `design/coding-standards.md` first — the check gate in §9 is the
> definition of "done" for every milestone below.
>
> **How to use this:** pick the lowest-numbered incomplete milestone, read its brief, read the design sections
> it names as normative, build it, make the check gate pass, then update the status line in `FINDINGS.md`.
> Do not skip ahead: every milestone assumes its predecessors exist and are tested.

## The decomposition decision, and why

**`zikaron-core` is split into seven milestones rather than built in one pass.** The reasoning matters, because
the opposite choice is defensible for smaller systems:

- Core is roughly the whole system's logic — store, config, records, chunking, retrieval, write path,
  consolidation, signals. One-shot, that is a few thousand lines with **no verifiable intermediate state**, and
  the first end-to-end test arrives only after all of it exists. Every bug then surfaces at once, in a stack
  where no layer has ever been exercised alone.
- The design already supplies natural seams: twenty invariants, each attached to a specific layer, plus two
  validation ladders and a state machine. Those seams are what make intermediate states *checkable* — a
  milestone is done when its invariants have tests that fail when violated.
- Each milestone below is independently testable with a fake at its lower boundary, so none waits on the next.

**What is deliberately *not* split further:** M1, M8, M10 and M11. The two clients are thin *by design* — D31's
entire argument is that they are stdlib-only and do almost nothing — so splitting them would create
coordination overhead around a few hundred lines.

**M0 comes first and is throwaway.** Four assumptions underpin the architecture and none has been exercised in
code. Discovering a broken one after M2 means rewriting the store; discovering it in a 50-line spike costs an
afternoon. This is `FINDINGS.md` open question 4 turned into a task.

---

## M0 — Spikes: exercise the four unverified assumptions

**Throwaway scripts under `spikes/`, no production code, no tests required.** Write findings to
`research/spike-results.md` and raise any design correction before M1.

1. **sqlite-vec loads and the schema pattern works.** Load the extension from a venv install; create
   `memory_vec` from the `float[<embed_dim>]` template at a non-384 width; confirm explicit-rowid inserts work
   and that `memory_vec.rowid == memory_chunk.chunk_id` supports the join; confirm a KNN query returns
   distances. Confirm what happens on a dimension mismatch — the error, and whether it is detectable before
   insert.
2. **FTS5 external-content behaves as `design/schema.md` assumes** under the amend sequence: delete-then-insert
   inside one transaction with `content='memory'`, and the documented erasure sequence (the `'delete'` command
   using current values). Confirm a stale term is genuinely unmatchable afterwards.
3. **The transport, end to end.** A UDS JSON-RPC server plus a *cold* client process: measure round-trip from
   process start, then warm. Two clients racing start-if-absent under `flock`. A client connecting exactly as
   the server exits on idle. `busy_timeout` behaviour with two writers.
4. **fastembed cold vs warm, in this venv.** Confirm the 783 ms / 5.5 ms figures the architecture rests on, and
   the on-disk footprint.

**Done when:** `research/spike-results.md` records each measurement, and any assumption that failed has a
design correction applied and re-indexed in the knowledge base.

**Fence:** do not start writing `zikaron/` here. Spikes are allowed to be ugly; they are not allowed to become
the implementation.

---

## M1 — Skeleton and the check gate

Package layout per `design/coding-standards.md` §1. venv, exact-pinned dependencies, `ruff`, `mypy --strict`,
`pytest` + `pytest-cov`, and the single check command wired and passing on an empty typed package.

Then the three declarative singletons, because everything downstream references them: the **error-code
`IntEnum`** (`design/architecture.md` §Errors), the **config key schema** with type/range/default per key
(`design/schema.md` §"Configuration keys"), and the **`event` kind enum** (`design/schema.md` §"The `event` log,
per kind").

**Done when:** the check gate passes, and a test asserts each of the three singletons matches its design table
exactly — every name, every number, every range. That test is the guard against the drift class this corpus
spent sixteen review rounds fighting.

**Fence:** no store, no SQL, no behaviour. This milestone is scaffolding plus three tables.

---

## M2 — Store and configuration

Normative: `design/schema.md` §Tables, §`meta`, §"Creating the dense index", §"File permissions";
`design/architecture.md` §Configuration, §Paths.

Schema creation from the DDL template with the validated effective dimension and the embedder-width check;
open-path `meta` validation; the `reindexing` sentinel including the present-on-open case; layered config
resolution (two files, per-key amend at depth 2, unknown-key rejection per file, range validation on the merged
result, `bad_config` naming source and key); `0600` permissions; WAL and `busy_timeout`.

**Invariants:** 1, 3, 11. **Done when:** those have failing-when-violated tests, a store round-trips
create→close→open, a config fixture set covers missing/partial/unknown-key/out-of-range/wrong-type across both
layers, and a dimension mismatch is rejected before any table exists.

**Carried from M1:** the schema version this build supports is already declared once, as the fixed value of
`schema_incompatible`'s `supported` field in `zikaron/core/errors.py`. Whatever `store/` needs the number for,
it must agree with that declaration rather than restate it — a test asserting the two are equal is cheaper than
discovering they are not.

**Fence:** no records, no embedding. A fake embedder that reports a width is enough.

---

## M3 — Records, versioning, receipts

Normative: `design/schema.md` §Tables, invariants 4–9; `design/architecture.md` §"Validation precedence".

`memory` row lifecycle; monotonic `version` on every mutation including tier flips and `superseded_by` writes;
soft retire; supersession edges with the terminal-component case; `read_receipt` mint and spend on the
`(session_id, client_kind, memory_uuid, version)` key; version-before-receipt ordering in both ladders.

**Invariants:** 4–9, **and 10** — every `event` row commits in the same transaction as the mutation it
describes. Invariant 10 is **cross-cutting**: it is first testable here, and M4, M6 and M7 each add write
paths that must re-assert it, so each of those milestones repeats the check for its own verbs rather than
assuming this one covered them. A rolled-back mutation that left an event behind makes every D30 signal
carry an unquantifiable error term, which is why it is an invariant and not a convention.
**Done when:** each has a test; a version bump provably revokes other clients' receipts but
not the writer's; retired-vs-superseded are distinguishable and no query assumes `active=0 ⇒ superseded_by NOT
NULL`; a consolidator receipt does **not** license a `kind='mcp'` amend.

**Fence:** fake embedder, no chunking yet — rows only.

**Settle before building, carried from M1:** `inactive_row`'s payload is `{uuid, state}` and the design states
no value set for `state`, while §"MCP tool surface" gives the row-state vocabulary as
`live | superseded | retired`. An `inactive_row` cannot be `live`, so the intended subset is presumably
`superseded | retired` — but two implementations can currently disagree, and closing it to all three would be
wrong. Decide the subset in `architecture.md` §Errors, then define the row-state enum here and have
`ERROR_SPECS` reference the subset of it. M1's payload guard already fails the moment the design states a set,
so this cannot be forgotten, only deferred.

---

## M4 — Indexing

Normative: `design/indexing.md` in full; `design/schema.md` invariant 2.

Paragraph-greedy chunking to `chunk_max_tokens`, no overlap, gist prepended to every chunk, hard-split only an
oversized paragraph; FTS5 sync over the whole record; `vec0` writes keyed to `chunk_id`; `token_count` and the
`truncated` canary; **atomic amend** — version bump, prose rewrite, FTS resync, chunk delete and reinsert, all
in one transaction.

**Invariants:** 2. **Done when:** a killed amend leaves no partial state (simulate by raising mid-transaction);
chunk boundaries are deterministic across runs; a short memory yields exactly one chunk; the oversized-paragraph
path sets `truncated`.

**Fence:** no retrieval. Writing the indexes only.

---

## M5 — Retrieval

Normative: `design/retrieval.md` in full; `design/schema.md` §"Retrieval eligibility", §Bounds, invariants
18–20.

Both arms; RRF at `rrf_k`; the eligibility predicate with its per-consumer filter table; `max` rollup then
memory-level dedup; supersession demotion with the labelling and precedence rules; query construction and
bounds on both arms; the depth and stop-reason instrumentation with its three terminal reasons.

**Invariants:** 18–20. **Done when:** the eligibility predicate has one implementation used by all five
consumers (a test asserts no consumer adds a filter outside the documented table); a superseded row surfaces
demoted and ordered behind its replacement; `dense_stop_reason` distinguishes exhausted from cut on a fixture
sized to each case; one memory never occupies two of five slots.

**Fence:** no write verbs, no consolidation. Read path only.

---

## M6 — Write path and dedup

Normative: `design/architecture.md` §"MCP tool surface", §"Validation precedence"; `design/schema.md` §Bounds.

`remember` / `amend` / `retire` core logic; D15's dedup search-then-hand-back with `dedup_max` and
`dedup_threshold`; `gist_max_tokens` as the one bound that rejects an agent write; the conflict payload that
returns the current record and mints a receipt.

**Done when:** a dedup hand-back returns candidates without blocking the write; a conflict returns the full
record and its receipt in one round trip; every rejection path emits the events the signals require and no
others.

**Fence:** no consolidation verbs.

---

## M7 — Consolidation

Normative: `design/consolidation.md` in full; `design/architecture.md` §"Consolidation lifecycle",
§"Consolidator tool surface"; `design/schema.md` invariants 12–17.

Anchor-by-retrieval, mutual top-K with the cosine floor, the complete-linkage cohesion pass, deterministic
sharding; the run and group state machine with every transition's named cause; leases with `(session_id, pid)`
ownership and expiry-only takeover; the four verbs; serve-time vacating; the never-lose closure property.

**Invariants:** 12–17. **Done when:** each has a test; the A~B/B~C/A≁C chain case is explicitly tested and does
**not** over-merge; group ordering is deterministic across runs; a run abandoned mid-way loses no journal row; a
second worker in the same session with a different pid gets `{busy: true}`.

**Fence:** this is the largest milestone. If it needs splitting, split at the state machine — grouping first,
then the verbs — but keep the invariant tests with whichever half owns them.

---

## M8 — The six signals, as SQL

Normative: `design/schema.md` §"D30's six signals, as queries", §"`signal_horizon_days`";
`design/write-policy.md` §3.

Each signal as executable, tested SQL. The horizon deadline semantics with the `pending` class; the dedup
four-state machine with early close on `A ∧ R`; the `(session_id, memory_uuid)` pair unit; linked-session
restriction and link coverage.

**Done when:** each signal runs against a fixture whose expected value is computed by hand in the test; a
follow-up after the deadline provably does **not** change a matured classification; a rate can never exceed 1.

**Fence:** no reporting UI. SQL plus tests.

---

## M9 — Service

Normative: `design/architecture.md` §RPC, §"Resolution is a preamble", §Lifecycle, §"Service RPC surface".

asyncio UDS server; newline-delimited JSON-RPC 2.0; the resolution preamble including required `pid`; the
two-rung label ladder and derived `label_source`; `health()` with store identity; idle self-stop with in-flight
protection; socket cleanup; the log.

**Done when:** integration tests cover start-if-absent under two racing clients, the connect-as-server-exits
race with one client retry, a stale socket file, and a foreign-store handshake being refused.

---

## M10 — MCP client

Five primary tools, four consolidator tools, gated to separate agent configs. Thin: translate, call, return.

**Done when:** tool descriptions carry the mechanics the write policy deliberately omits (version precondition,
dedup payload, retire semantics), and a consolidator config provably cannot reach `search` or `fetch`.

---

## M11 — Hook client

Normative: `design/architecture.md` §"Degraded modes", §"Subagent sessions"; `design/write-policy.md`.

`agentSpawn`: print the policy, warm the service, print nothing on failure. `userPromptSubmit`: subagent
suppression by comparing payload `session_id` against `KIRO_SESSION_ID`, then RPC, then — on any failure —
silence plus one line appended to its own `hook.log` naming the failure, via a direct `open`/`write`, **not**
`import logging` — `logging` costs ~15 ms of interpreter startup on this machine, measured against the same
argument that keeps this client stdlib-thin, and a process writing one line per invocation has no log
lifecycle for it to manage. No fallback query, no direct store access under any circumstance. Always exit 0,
never stderr, internal deadline well under `timeout_ms`.

**Done when:** a test asserts stdlib-only imports **and specifically that `logging` is not among them**; every
failure mode exits 0 with empty stdout and no store access of any kind; a subagent payload produces no output;
each of the failure kinds named in `architecture.md` §"Degraded modes" (transport, `bad_config`, `reindexing`,
`store_busy`, an identity mismatch) is exercised with the service down or unhealthy and produces exactly one
`hook.log` line naming it, with no read attempted.

---

## M12 — Distribution

The `zikaron-consolidator` agent config, the consolidation skill, hook entries for both the stable and `--v3`
formats, the write-policy text as a shipped asset, and install docs.

**Done when:** a clean install on a fresh directory produces a working push, pull, write and consolidation run.

---

## Standing notes for whoever picks this up

- **`shard_count` is flagged as possibly unnecessary** — a persisted count an invariant then polices, derivable
  as a `COUNT(*)`. Left in place pre-code deliberately. If M7 finds it genuinely redundant, that is a design
  change to propose, not to make silently.
- **Open questions in `FINDINGS.md` are open on purpose.** Open question 2 (RRF arm weighting) is the largest
  known quality lever and needs no reindex, so it is deliberately post-build. Do not tune fusion during M5.
- **The design is normative; where code and design disagree, one of them is a bug.** Decide which, fix that one,
  and re-index the knowledge base if it was the design.
