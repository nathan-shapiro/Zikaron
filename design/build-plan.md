# Build plan

> Per-milestone briefs. `FINDINGS.md` carries the sequence and current position; this carries the detail a
> session needs to actually do one. Read `design/coding-standards.md` first — the check gate in §9 is the
> definition of "done" for every milestone below: `./check.sh` is the per-edit gate and the definition of
> done for a change, and `./check-matrix.sh` is additionally required before a milestone lands.
> **CI is not a third thing a milestone must run.** `.github/workflows/check.yml` asserts the matrix's own
> claim against a commit, by running `check.sh` once per version rather than `check-matrix.sh` at all — so
> a milestone's local obligation is unchanged, and what CI adds is that the tree identity comes from the
> SHA. `design/distribution.md` §"What CI asserts" is normative.
>
> **How to use this:** pick the lowest-numbered incomplete milestone, read its brief, read the design sections
> it names as normative, build it, make the check gate pass, then update the status line in `FINDINGS.md`.
> Do not skip ahead: every milestone assumes its predecessors exist and are tested.

## The decomposition decision, and why

**`zikaron-core` is split into seven milestones rather than built in one pass.** The reasoning matters, because
the opposite choice is defensible for smaller systems:

- Core is roughly the whole system's logic — store, config, records, chunking, retrieval, write path,
  consolidation, signals, and, since D1's amendment, the knowledge index. One-shot, that is a few
  thousand lines with **no verifiable intermediate state**, and the first end-to-end test arrives
  only after all of it exists. Every bug then surfaces at once, in a stack
  where no layer has ever been exercised alone.
- The design already supplies natural seams: an invariant per layer, in `schema.md` for the memory store
  and `knowledge-index.md` §13 for the knowledge index, plus two
  validation ladders and a state machine. Those seams are what make intermediate states *checkable* — a
  milestone is done when its invariants have tests that fail when violated.
- Each milestone below is independently testable with a fake at its lower boundary, so none waits on the next.

**What is deliberately *not* split further:** M1, M8, M10 and M11. The two clients are thin *by design* — D31's
entire argument is that they are stdlib-only and do almost nothing — so splitting them would create
coordination overhead around a few hundred lines.

**M0 comes first and is throwaway.** Four assumptions underpin the architecture and none has been exercised in
code. Discovering a broken one after M2 means rewriting the store; discovering it in a 50-line spike costs an
afternoon. This is the hook→service transport question turned into a task.

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

**The push block's text is `core`'s, not the service's.** `architecture.md` §"Service RPC surface" says
`surface` returns ready-to-print text so the hook stays dumb, and names `retrieval.md` §"Push output format" as
the spec — so the formatter is a pure function in `core/retrieval/`, built here, and M9's service only calls it.
Leaving it to M9 would put a ranking-and-labelling rule in the transport layer, where the demotion label has no
access to the reason it exists.

**Invariants:** **18 and 20.** **19 is not this milestone's** — it constrains the set of
`consolidation_group` rows one planning pass writes, a table M5 neither reads nor writes, so it moves to **M7**
with the planner that can violate it. The 18–20 grouping here was the residual after M2 (1, 3, 11), M3 (4–10),
M4 (2) and M7 (12–17), which is bookkeeping rather than analysis. What M5 owes invariant 18 is narrower than
what M9 owes it: normalization is the service's (`architecture.md` §"Resolution is a preamble"), so M5's share
is that every `event` row the read path writes carries the label it was handed, in both the returned-rows and
the nothing-eligible cases.

**Done when:** the eligibility predicate has one implementation used by all five
consumers (a test asserts no consumer adds a filter outside the documented table); a superseded row surfaces
demoted and ordered behind its replacement; `dense_stop_reason` distinguishes exhausted from cut on a fixture
sized to each case; one memory never occupies two of five slots.

**Fence:** no write verbs, no consolidation. Read path only. The read path's *internal-query* half
(`retrieval.md` §"Two kinds of query") is in scope and its consumers are not: M5 builds the query construction
and the composable retrieval core that dedup, anchoring and orphan edges will call, and calls none of them.

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

**Shipped and reviewed to `APPROVED`** (`reviews/m7-consolidation-review.md`), as
`zikaron/core/consolidation/`: `context`, `runs`, `groups`, `rowstate`, `grouping`, `planning`,
`payload`, `candidates`, `serving`, `authorization`, `verbs`. Ten items the design left to be inferred
were settled in `design/` before coding rather than only in code — group order, an anchored group's
absent cohesion pass, the anchor scan versus a rank-1 gate, the gist join, `n_gists_used = 0`, absorb
distinctness, `promote` in-place's event size fields, `remaining_groups`, the `pending`-group answer,
and invariant 14's `run_id` carve-out. `shard_count` was **not** found redundant (see the standing note
below): the payload has to carry `of` after a restart, and recomputing it would mean replanning a group
whose membership is frozen.

Normative: `design/consolidation.md` in full; `design/architecture.md` §"Consolidation lifecycle",
§"Consolidator tool surface"; `design/schema.md` invariants 12–17 and 19.

Anchor-by-retrieval, mutual top-K with the cosine floor, the complete-linkage cohesion pass, deterministic
sharding; the run and group state machine with every transition's named cause; leases with `(session_id, pid)`
ownership — expiry-only implicit takeover through `next_group`, plus unconditional explicit takeover through
`plan_groups`; the four verbs; serve-time vacating; the never-lose closure property.

**Invariants:** 12–17, **and 19** — shard identity, moved here from M5 because the planner is the only thing
that writes `consolidation_group.shard_index`/`shard_count` and so the only thing that can violate the
set-level condition; M5 neither reads nor writes that table. **Done when:** each has a test; the A~B/B~C/A≁C
chain case is explicitly tested and does
**not** over-merge; group ordering is deterministic across runs; a run abandoned mid-way loses no journal row; a
second worker in the same session with a different pid gets `{busy: true}` **from `next_group`**,
while an explicit `plan_groups` takes the run over and records it `taken_over`.

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
protection and inode-drift self-stop (M11's own round-3 review added this second exit condition after
`zikaron-hook`'s own identity check was found unable to detect a same-path store replacement on its own);
socket cleanup; the log.

**Done when:** integration tests cover start-if-absent under two racing clients, the connect-as-server-exits
race with one client retry, a stale socket file, a foreign-store handshake being refused, and a `memory.db`
deleted and recreated at the identical path while the service still holds the old one open causing the
service to self-stop within one idle-poll cycle.

---

## M10 — MCP client

Five primary tools, four consolidator tools, gated to separate agent configs. Thin: translate, call, return.

**The consolidator client calls `plan_groups`**, with its own `(session_id, pid)`, **lazily — immediately
before the first `next_group` it forwards, never when the client starts, and at most once *successfully* per
process** — and a **successful** response is a
prerequisite of that serve reaching the service (`architecture.md` §"Consolidation lifecycle"). That call *is*
the takeover a human retry performs, and without it the takeover path is unreachable, since a fresh
consolidator's first tool call is `next_group` and that refuses a live foreign run. Lazily, because the MCP
handshake is eager and a startup-wired call would take the consolidation lock before the model had been asked
anything — a spawn that then does nothing would displace a live worker for nothing. One boolean in a per-spawn
process is the whole mechanism. Both premises are **measured**, not assumed — one client process per spawn,
and an eager handshake preceding the first tool call: `research/kiro-mcp-lifecycle-probe.md`.

**Done when:** tool descriptions carry the mechanics the write policy deliberately omits (version precondition,
dedup payload, retire semantics); a consolidator config provably cannot reach `search` or `fetch`; the client
provably makes **no** service call until the model calls a tool, so a spawn that does nothing takes no lock;
the first `next_group` provably completes a successful `plan_groups` before any serve reaches the service, at
most **once successfully** per process; and the three-state machine is tested at its awkward transition — a
first `plan_groups` answering `store_busy` leaves the client `unplanned` so the retry plans and serves, with no
`next_group` having reached the service in between and exactly one takeover committed.

---

## M11 — Hook client

Normative: `design/architecture.md` §"Degraded modes", §"Subagent sessions"; `design/write-policy.md`.

`agentSpawn`: print the policy — unconditionally, since holding a string constant cannot itself fail — and
best-effort spawn a detached warm helper; a failure to spawn it changes nothing about the policy print, which
always happens either way. `userPromptSubmit`: subagent
suppression by comparing payload `session_id` against `KIRO_SESSION_ID`, then RPC, then — on any failure —
one line appended to its own `hook.log` naming the failure, via a direct `open`/`write`, **not**
`import logging` — `logging` costs ~15 ms of interpreter startup on this machine, measured against the same
argument that keeps this client stdlib-thin, and a process writing one line per invocation has no log
lifecycle for it to manage — **and** a short, model-facing relay instruction printed to stdout, naming the
same failure and pointing at `hook.log` for the exact detail. No fallback query, no direct store access under
any circumstance. Always exit 0, never stderr — a live spike against a real kiro session (`design/
architecture.md` §"Degraded modes") measured that a non-zero exit suppresses the confirmed-working stdout
channel entirely and that stderr does not visibly surface on this build, which is why the relay instruction
rides stdout on exit 0 rather than either of those. Internal deadline well under `timeout_ms`.

**Done when:** a test asserts stdlib-only imports **and specifically that `logging` is not among them**; every
failure mode exits 0, writes nothing to stderr, and touches no store of any kind — stdout carries a
model-facing relay instruction rather than staying empty, per the measured result in `architecture.md`
§"Degraded modes"; a subagent payload produces no output at all (not even a relay instruction — it is not a
failure); each of the failure kinds named in `architecture.md` §"Degraded modes" (transport, `bad_config`,
`reindexing`, `store_busy`, an identity mismatch) is exercised with the service down or unhealthy and produces
exactly one `hook.log` line naming it, with no read attempted, alongside the stdout relay.

---

## M12 — Distribution

Normative: `design/architecture.md` §"Distribution artefacts", §"Two hook formats", §"The consolidator's
model is a shipped config field", §"The install contract"; `design/consolidation.md` §"Consolidator identity
and model"; `design/write-policy.md`.

Six shipped artefacts and one program. `[project.scripts]` gives `zikaron-hook` and `zikaron-mcp` console
entry points, because a hook `command` and an `mcpServers` command need one absolute path whose shebang pins
the interpreter Zikaron is installed into — the same interpreter start-if-absent will spawn the service with.
*(M30 added a third, `zikaron`, for the commands a person types. It is named in no config file, which is
why this paragraph's argument does not reach it: `design/distribution.md` §"The front door".)*
`.kiro/agents/zikaron-consolidator.json` carries the explicit `model`, the four consolidation tools and
nothing else, all pre-approved, and no `hooks`. `.kiro/skills/zikaron-consolidate/SKILL.md` is D10's trigger,
and it is also the only place a user is told that re-invoking it **takes over** a stuck run. The `hooks` and
`mcpServers` entries ship in both formats the harness accepts, with `timeout_ms` and `max_output_size` stated
rather than inherited. D30's policy text stays a constant with an optional `.zikaron/write-policy.md`
override. `python -m zikaron.install` writes all of it, validates the model id against
`kiro-cli chat --list-models -f json` — measured: `kiro-cli agent validate` does **not** check model ids —
and merges into an existing agent config only after backing it up.

**Done when:** a clean install on a fresh directory produces a working push, pull, write and consolidation
run, driven through the **real shipped commands** rather than in-process equivalents: the installed
`zikaron-hook` as a subprocess for both triggers, and the installed `zikaron-mcp` as a stdio subprocess for
both modes — **and** an end-to-end takeover: hold a run from one worker, invoke the skill's own path again
through a real consolidator client, and observe the first run closed `taken_over` while the second serves the
replanned groups. A drift guard reads the consolidator config's `model` against the design table rather than
against a second copy of it, and another asserts the shipped entries' `max_output_size` bounds both the write
policy's real byte length and a worst-case five-row push block. No test leaves a service process behind.

**Scope fence:** the harness's own reading of these files is not testable from here — kiro is not driven by
the suite. Everything installed is verified by exercising the same commands kiro would exercise, and the one
claim that needs a live session (that kiro loads the config and fires the hooks) is the dogfooding
checkpoint, not a test.

---

## M13 — Claude Code support: the design delta

Normative to **write**: `design/harness.md` (new). Normative to **amend**: `design/overview.md` (D32, and a
new D34); `design/architecture.md` §"Both clients resolve the same label", §"Subagent sessions",
§"Two hook formats", §"The consolidator's model is a shipped config field", §"The install contract";
`design/schema.md` §"Linked sessions". **No schema change, no new RPC method and no migration** — an earlier
draft of this brief required all three, and the measurement in the model paragraph below deleted them along
with the milestone that was going to build them. Evidence: `research/claude-code-harness-probe.md` (measured) and
`research/claude-code-harness-contract.md` (documentation reading, weaker).

**One codebase, two harnesses — harness differences are data, not code paths.** D34 states the rule and the
table: for each harness, its marker variable, its session variable, its trigger names, **its output channel
per event**, its injection budget, and where its artefacts live. Detection is the marker (`CLAUDECODE` ⇒
Claude Code, else kiro — measured present in both hook processes and both MCP server starts, probe §1) and nothing
cleverer; the residual is nesting — a session of one harness launched from a shell inside the other inherits
a stale session variable — and it is **accepted as a known limit that link coverage cannot detect.**
*(**Superseded by the artifact this brief produced**, 2026-08-16: `design/harness.md` §"The nesting limit"
is normative. It corrects this paragraph's symmetry — the Claude-Code-inner direction is measured **safe**,
probe §1 — and scopes the tripwire below, which as stated here shares the kiro subagent-suppression
predicate and would fire on every subagent turn. M14's done-when carries the corrected, binding text.)* An
earlier draft of this brief claimed the shortfall would surface it; that is wrong, and wrong in the main
case: both clients read the environment by construction, so both read the *same* stale variable, they
**agree**, coverage reads ~1.0, and the nested session's pushes, writes and searches are silently attributed
to a different, live session's instruments. Agreement-by-construction is exactly what prevents the shortfall.
One cheap tripwire is therefore specified instead: the hook alone holds both the payload's `session_id` and
the resolved environment value, so it writes **one `hook.log` line when they diverge** — no RPC, no
behaviour change, and one client's worth of evidence that a nested session is contaminating another's
numbers. The seam is the only new module; everything downstream of it stays single-implementation.

What the probe settled, each item changing a settled statement rather than adding a new one:

- **The session-label ladder ports as a rename.** `CLAUDE_CODE_SESSION_ID` is exported into every process
  Claude Code spawns — both hooks, the MCP stdio server, and a subagent's subprocesses — and equals the hook
  payload's `session_id`. §"Both clients resolve the same label" holds verbatim with one more variable name in
  it. Linked sessions, link coverage, both cross-client D30 signals and the per-session recall instrument all
  survive. `CLAUDE_PID` is **not** overridden for children and must never be read.
- **D32 splits, and only one half ports.** Subagent frontmatter `tools:` genuinely restricts MCP tools, so the
  consolidator still gets the four verbs and **no `search` or `fetch`** — the half that carries D7's
  enforcement is mechanical here as it was under kiro. The other half is not reproducible: a server must be
  registered session-wide to be reachable by any subagent, `permissions.deny` is global and unregisters the
  tool for the subagent too, and per-subagent MCP registration does not exist. So "the primary agent cannot
  fire the expensive path on a whim" becomes **prompt-only** under Claude Code. D32's row must say so — and
  must state the exposure at its true size, which an earlier draft of this brief understated as "a wasted
  expensive call". It is larger: the primary agent holds the four verbs *and* `search` and `fetch`, and
  because ownership is `(session_id, pid)` over a **shared** server process it presents the same pair a real
  consolidator in that session would, so it triggers the lazy `plan_groups` or inherits a live lease and is
  served groups **as the owner**. The honest consequence is therefore *an unauthorized consolidation
  performed by a model with broad retrieval in hand* — wasted tokens, and possibly a poorly-judged merge
  written to the long-term tier, which is the "manufactures a false record" failure `consolidation.md`
  names. Never-lose, the receipts, row-level completion and the journal are untouched; long-term **content**
  is not. Under kiro this was mechanically impossible.
- **The push-suppression rule is inert here rather than ported.** `UserPromptSubmit` does not fire for
  subagents at all, so the door D32 guards is closed by the harness. The rule stays in the code for kiro and
  is documented as a no-op under Claude Code.
- **The write policy reaches subagents, precisely — through the *other* output channel.** `SessionStart`
  fires once, so a subagent would otherwise inherit Zikaron's tools having never seen D30's policy.
  `SubagentStart` carries `agent_type`, so the policy can be injected for every subagent **except
  `zikaron-consolidator`** — the exact rule §"Subagent sessions" wanted and could not express under kiro,
  where the payload carried no agent identity. **The mechanism is not the one the rest of this design uses,
  and an earlier draft of this brief asserted it without measuring.** Plain exit-0 stdout from a
  `SubagentStart` hook reaches **nobody** — not the subagent, not the parent (probe §7b). The policy arrives
  only via `{"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":…}}`, which the
  subagent then quotes verbatim while the parent still cannot see it — the isolation this delivery wants. So
  **this harness has two output channels and they are not interchangeable per event**, which is a normative
  fact for the harness table and a change `hook/main.py` cannot avoid, since it writes plain stdout for
  everything today. Whether `additionalContext` shares the 10,000 cap is **unmeasured**.
- **The injection budget is one shared conservative bound of 10,000 — and the unit is *characters*.**
  Bisected on ASCII: 9,503 arrives intact, 10,502 does not. The unit was then pinned separately, because
  the ASCII bisection could not distinguish bytes from characters and this corpus has been burned by exactly
  that conflation: 9,016 characters of `漢` — **27,016 bytes** — arrived whole (probe §7a). Claude Code has
  no `max_output_size` field, so 65536 has no analogue and cannot be raised. Overrun is **loud** — an
  explicit notice, a 2 KB preview and a path to the full text — strictly better than kiro's silent
  truncation, but the preview is small enough that the bound does the real work and the file is a backstop.
  The margin protecting open question 11 narrows 6.5×, which is what promotes it out of "deferred" — and the
  bound `gist` needs is a **character** bound, since it is *tokens* that bound neither characters nor bytes.
- **Consolidation ownership loses its discriminator, and the limit is accepted rather than repaired.** Claude
  Code runs **one or more** MCP server processes per session — **two were observed in one probe session**,
  with the second serving the call, and why two start or whether either restarts mid-session is **unmeasured**
  (probe §4). No process is spawned per subagent, so `(session_id, pid)` cannot tell two consolidators in one
  session apart. Two consequences, and the second is the one an earlier draft of this brief omitted by
  flattening "two observed" into "one per session":
  - `_PlanBridge`'s "at most one successful `plan_groups` per client process" becomes per session, so two
    consolidators launched from one session are served the same run rather than told busy.
  - The guard is **per process**, so a second or restarted consolidator-server process gets a **fresh** one,
    and its first forwarded `next_group` lazily fires `plan_groups` — **a spurious takeover of the session's
    own live run with no human invocation behind it.** This is precisely the residual open question 10 left
    open under kiro, now with measured evidence that multiple processes do occur.
  **Operator decision: accept both.** The lease still lapses, so crash recovery works, and the cost is
  bounded: a spurious self-takeover costs one worker's in-flight reasoning and a replan, never a journal row
  — never-lose and row-level completion hold. Cross-session mutual exclusion, the case the lease was built
  for, is untouched. Recorded as a stated limitation, with a run-token design named and *not* built. One
  cheap probe would tighten it: watch whether the second process ever serves calls after the first has.

**The consolidator's model becomes an alias plus a measurement plus a protocol — and it needs all three.**
Claude Code offers no `--list-models` analogue (traceable only to the documentation reading,
`contract` §9, **not** to the probe), so the shipped value is the `sonnet` alias. That alias is a **moving
target**, which is the same failure D29's no-silent-fallback rule exists to prevent — one vendor upgrade
makes two runs incomparable while both look healthy.

**Measured, and it removes the problem instead of managing it: Claude Code refuses an unknown model id
loudly.** A subagent whose frontmatter named `claude-not-a-real-model-xyz` was terminated **before any turn
executed**, with `[claude-code:unrecognized_model]` and an explicit error (probe §7d). That is the exact
opposite of kiro, whose documented behaviour is to fall back to its default — and kiro's fallback is the
*sole* reason the install-time `--list-models` check exists at all. **So under Claude Code the harness itself
enforces no-silent-fallback, at spawn, and no install-time validation is needed.**

**So the shipped default is the `sonnet` alias, and experiments pin.** Two drafts of this brief got this
wrong in opposite directions and the correction is worth keeping, because the mistake was reading a
constraint into the design that is not there. `architecture.md` requires the field to be **present
explicitly** and to be **an id the harness accepts** — an alias satisfies both, so "no silent inheritance"
holds (the field is written, not omitted) and "no silent fallback" holds (the harness serves exactly what
was asked for). The rule the second draft enforced — *the value must be stable over time* — is nowhere in
the design; it was inferred from D29's comparability goal and then treated as binding.

The division of labour that follows:

- **The shipped default is an alias**, because a pinned default **rots**: an install a year from now would
  ship last year's model, and once that id is retired the consolidator fails at spawn — breaking the
  product, which is worse than blurring an experiment. Aliases are measured to work in subagent frontmatter.
- **An experiment pins.** The A/B `consolidation.md` calls for sets the model deliberately on each arm, so a
  moving default never interferes with it: during the comparison the value is concrete by construction.
- **What the alias costs is narrow and stated**: you cannot say retrospectively which concrete model ran a
  past consolidation. That bites only when comparing runs across a vendor upgrade — which is exactly when
  you would have pinned. If a specific past run's model is ever wanted, the harness's own subagent transcript
  still records it on disk (probe §7c); it simply is not copied into the store, and the store needs no column
  to make that true.

**Neither arrangement needs install-time validation under Claude Code**, because §7d's spawn-time refusal
does that job — which is the finding that deleted a per-run recording path, a new RPC method, a schema
column, a version bump and an entire migration milestone from an earlier draft of this plan.

**Done when:** `design/harness.md` and every amendment above converge through the `self-review` skill; every
normative claim is traceable to a numbered section of the probe note or explicitly marked unmeasured; D32's
and D34's rows carry the weakened guarantee in their own text rather than only here; the consolidator's
`model` field states an alias as the shipped default with pinning named as the experiment's job, and
§"The consolidator's model is a shipped config field" says which of its rules an alias does and does not
satisfy rather than leaving it inferable; and FINDINGS' refuted migration-note claims are withdrawn **in place** per the
house rule rather than deleted.

**Scope fence:** no code. D10 stays manually invoked and `PreCompact` stays untouched — changing the
consolidation trigger and the harness at once would make the next consolidation result uninterpretable, and
that result is the phase's first priority. Open question 2 (fusion) is not opened.

---

## M14 — The harness seam, both clients, and the gist character bound

Normative: `design/harness.md`; `design/schema.md` §Bounds; `design/architecture.md` §"Degraded modes",
§"Subagent sessions".

`zikaron/harness/` answers four questions for both thin clients — which harness spawned me, what is my session
id, what internal event is this trigger name, what is my injection budget — and **nothing else**. It is
stdlib-only and import-cheap, and that is a measured constraint rather than a style preference:
`hook/envelope.py` records that importing `zikaron.core.events` costs 28 ms against a ~48 ms whole-process
hook floor, which is why that module keeps its own guarded copy of the envelope rather than importing one. A
seam that pulls in anything heavier silently triples the per-turn tax on the push path.

Trigger names normalize many-to-two: `agentSpawn`/`SessionStart` ⇒ spawn, `userPromptSubmit`/`UserPromptSubmit`
⇒ prompt, plus one Claude-Code-only arrival — `SubagentStart` ⇒ the policy-only path with its `agent_type`
exclusion. `SubagentStop` is **not** in this vocabulary: the draft that put it here existed to record the
consolidator's model, and M13's measurement (the harness refuses an unknown id at spawn, so the id can simply be trusted) deleted that whole path along with the RPC
method and the schema change behind it. The hook
therefore still has **no write path** — which is worth stating, because the `event` DDL's own comment
("pushes come from 'hook', writes from 'mcp'") stays true only as long as that holds. **The seam also owns
which output channel an event uses**, because they are not interchangeable: `SessionStart` and
`UserPromptSubmit` take plain exit-0 stdout, `SubagentStart` takes only
`hookSpecificOutput.additionalContext` (probe §7b). `main.py` writes stdout unconditionally today.

The **policy-only path is exactly that**, and it is worth saying so rather than leaving it to be guessed: it
does **not** spawn the warm helper — the session's own `SessionStart` already did, and a second spawn per
subagent would be pure cost — and it **does** honour the `.zikaron/write-policy.md` override through the same
best-effort reader, so an operator experimenting with the policy text sees it in both places. Kiro's array format
already accepts `SessionStart` as an alias for `agentSpawn`, so this is one vocabulary with synonyms, not two
languages. The prompt field is `prompt` under both harnesses and needs no change at all. Session resolution is
the marker-then-variable rule, with the reserved `zk-` namespace check applied to **whichever** variable wins,
so a harness cannot claim a service-minted label under either name.

**The gist bound lands here**, not in a later milestone, and it is a **character** bound: open question 11's
defect is that `gist_max_tokens` bounds tokens while a single `[UNK]` can be 4,000 characters, and the budget
it overflows just narrowed from 65,536 to 10,000 — measured to be counted in characters, not bytes
(probe §7a), which is the unit the bound must therefore be stated and asserted in.

**A character bound closes the question for *both* harnesses, and the derivation belongs in writing rather
than in the author's head.** *(Superseded during the build: the unit tightened to UTF-16 code units, and the
byte ceiling to ×3 per unit rather than ×4 per character — see the done-when annotation below and
`harness.md` §"Injection budgets". The paragraph stands as written, since the reasoning is right and only
the unit was wrong.)* Kiro's `max_output_size` counts **bytes**, so a character bound only helps there
if characters bound bytes — and they do: UTF-8 encodes any character in **at most 4 bytes**, so a five-row
block fitting 10,000 characters is at most ~40,000 bytes, comfortably inside the shipped 65,536. That ×4 is a
real ceiling from the encoding, and it is worth distinguishing in writing from the ×4 this corpus already
burned itself on — the invented "four bytes per token" factor in an earlier `tests/test_install_limits.py`,
which was not a ceiling at all but a guess, and which the review caught asserting the opposite of the truth.
Same number, entirely different standing.

**Done when:** the stdlib-only import test covers the new module and still names `logging` explicitly; a drift
guard reads the harness table in code against the design table rather than a second copy of it, in the shape
`tests/design_tables.py` already uses; both clients resolve an identical label under each harness's own
variable and both fall to `minted` when neither is present; the suppression rule is exercised under both
harnesses and is asserted inert under Claude Code; the `SubagentStart` path emits the policy **on the
`additionalContext` channel** for an ordinary `agent_type` and nothing at all for `zikaron-consolidator`; the
gist character bound is asserted at the write path, and a worst-case five-row push block is
asserted to fit 10,000 characters **and, at 3 bytes per UTF-16 code unit, to fit the shipped kiro
`max_output_size`** — so M12's byte assertion becomes provable rather than accidental. *(This clause
said "at 4 bytes per character" when the brief was written. Both halves tightened during the build:
the unit is UTF-16 code units, because the experiment that pinned the budget to characters used
Basic-Multilingual-Plane text and so could not separate code points from UTF-16 units; and the byte
ceiling is 3 per unit rather than 4 per character, since a 3-byte BMP character is one unit while a
4-byte astral character is two. The criterion is strictly stronger, not weaker.)* And the nesting
tripwire writes exactly one `session_env_mismatch` line to `hook.log` when payload and environment diverge
**and the detected harness is Claude Code**, while a kiro subagent turn — the same divergence, routinely —
writes **nothing**, since sharing the suppression rule's predicate unscoped would log on every subagent turn
and drown the signal.

**Scope fence:** no installer changes. The two kiro hook formats stay exactly as they are — dual support is
the decision, so the "code to delete" the migration note anticipated is not deleted.

---

## M15 — The installer adapter

Normative: `design/harness.md`; `design/architecture.md` §"The install contract", §"Distribution artefacts".

`main.py`'s flow, preflight order, collision policy and backup discipline stay as M12 built them. What varies
is serialization and merge, behind one `HarnessTarget` interface with two implementations. Kiro writes what it
writes today. Claude Code writes four artefacts — two JSON, two YAML-frontmatter Markdown: hook entries merged into
**`.claude/settings.local.json`** (decision (a) below), two servers in `.mcp.json`, the consolidator as `.claude/agents/zikaron-consolidator.md`
with YAML frontmatter and the prompt as its body, and the skill at `.claude/skills/zikaron-consolidate/SKILL.md`.
The shipped prose stays **one constant per artefact** with a harness-specific invocation snippet substituted —
the skill's spawn instruction is the only text that genuinely differs — asserted as a property rather than
duplicated, the way `tests/test_install_assets.py` already asserts the three shared prohibitions.

**Two decisions this brief makes rather than leaving to the implementer.** (a) The hook entries go in
**`.claude/settings.local.json`, not `settings.json`** — the installer writes absolute venv paths, which are
machine-local by construction for exactly the reason the install contract's console-script rule gives, and
`settings.json` is the shared, checked-in layer. Writing machine-local paths into a file the user commits
would break every other clone of the repository. (b) `.mcp.json` servers are **project-scoped and require
per-user approval before they load** *(documented only, unmeasured — `contract` §"Per-server pre-approval";
M16's end-to-end run verifies it implicitly, since no tool loads until approval)*, so a fresh install can
silently have no Zikaron tools at all until the
user approves them. The installer states the approval step in its output, the same way M12's already states
the `subagent`-tool requirement under kiro rather than editing the user's permissions for them.

New flag `--harness {auto,kiro,claude-code}`. Under Claude Code the model check is dropped in favour of M13's
per-run measurement, and the installer **reports the primary agent's exposure to the four consolidation
verbs** rather than letting the weaker guarantee pass silently — the same reflex M12 applied to the array
format's inherited `max_output_size`.

Folded in here because it is installer-shaped and already outstanding: **the installer has no notion of *same
install, older version*.** It asks only whether a shipped file names a *different* interpreter, so upgrading
Zikaron and re-running silently keeps a stale consolidator prompt unless `--force` is passed. The fix is to
compare shipped content.

**Done when:** a clean install on a fresh directory, for **each** harness, produces the artefacts that harness
reads, driven through the real shipped commands; a regression guard asserts the kiro artefacts are unchanged
from what M12 shipped; each Claude Code artefact parses in its own format (JSON, JSON, YAML frontmatter +
body, YAML frontmatter + body); re-running an install after a content change is detected and reported without
`--force`; the collision, backup and refuse-on-difference behaviours are exercised identically against both
targets; and the Claude Code install reports both the `.mcp.json` approval step and the primary agent's
exposure to the four consolidation verbs.

**Settled by the operator before any code, because each changes the shape of the work** *(added during
the build)*: (i) `--agent` is **kiro-only** and refused elsewhere, with the print-a-fragment path promoted
to an explicit `--print-only` on both harnesses rather than remaining an accident of omitting `--agent`;
(ii) `--harness auto` **refuses when there is no positive evidence** rather than inheriting
`harness.detect`'s kiro fallback — that fallback is right for the *hook*, where kiro exports no marker, and
wrong for an installer, where it would write kiro artefacts into a Claude Code project and exit 0;
(iii) the consolidator's model default becomes a **`HarnessSpec` field** with a drift-guard row, since it
is a *value* and only shapes belong in the adapter; (iv) **the shipped prose has more than one substitution
point** — this brief's "the skill's spawn instruction is the only text that genuinely differs" is wrong.

**Four things the build found that this brief did not anticipate.**
- **A Claude Code install writes *three* hook entries, not two.** M14 built the `SubagentStart` →
  write-policy path; registering only kiro's two triggers leaves it dead with nothing failing.
- **`timeout` is seconds and the `UserPromptSubmit` default is 30 s, not 600.** Measured
  (`research/claude-code-installer-probe.md` §2–3). Kiro ships `timeout_ms: 10000`; copying that integer
  into a seconds field installs a **10,000-second** budget. `hook/limits.py` now holds one canonical
  `HOOK_TIMEOUT_SECONDS` and each format converts at its own edge, so no constant anywhere carries the
  number that makes the mistake possible.
- **The consolidator's grant is a whole-server wildcard**, `mcp__zikaron-consolidator`, measured to
  exclude the primary server's tools (§7). Safer than four explicit names, because an unrecognised name
  in frontmatter refuses the spawn outright.
- **Two merge defects, both found by re-reading the new code against rules this corpus already had,
  and neither by a failing test.** The first version of the settings merge assigned each trigger key
  wholesale, which would have **deleted a user's own `SessionStart` hook** — and refused the install
  first, on the grounds that it "differed". It now replaces only Zikaron's own group, matched by
  command *basename* so another install's hook is still recognised. The second was treating a
  wrong-shaped `hooks` or `enabledMcpjsonServers` value as absent and writing over it, which is
  precisely the "defensive filtering on a write path is data loss with a reassuring shape" rule
  `writer.py` already states for kiro. Both are worth recording because the tests were green
  throughout: the new-code tests asserted what the new code did.
- **Content comparison is a *trade*, not a strict improvement, and the brief did not say so.** It fixes
  the upgrade case it was folded in for, and it reverses M12's deliberate rule that an operator's edit to
  a shipped file survives a re-run: content is the only evidence available, and "an older Zikaron wrote
  this" and "a human edited this" are indistinguishable by it. Decided toward refreshing — a stale prompt
  is silent, routine and misleading, while a clobbered edit is loud, backed up first, and reported —
  with the residual recorded: `.bak` is first-wins, so a *second* hand edit is not preserved.

**What review round 1 changed** *(`reviews/m15-installer-adapter-review.md`; two blockers, ten
improvements, three nitpicks)*. Recorded because three of them are the *same* defect class arriving in
three places, which is the useful thing to carry forward rather than the individual fixes.
- **Two blockers, both "the new code did not hold itself to a rule the old code documents two functions
  away."** The Claude planners skipped the backup-path preflight `plan_kiro_merge` runs — so a blocked
  `.bak` refused the install *after* four writes, breaking `_install`'s own "nothing has been written
  when one is raised". And they silently dropped malformed user data, which had been independently
  fixed hours earlier by re-reading against `writer.py`'s own `TestShapesThatWouldBeSilentlyDropped`;
  two readers finding one defect from opposite directions is worth noting about the rule, not the bug.
- **`--force` replaced a shipped file with no backup at all.** The content-comparison trade above
  rests on "nothing is replaced without `<name>.bak` existing first", and that sentence was false on
  the one path where it matters most — `--force` is the flag the merge-conflict refusals *instruct*
  users to pass, so it arrives alongside an unrelated conflict rather than only when someone means
  "discard my edits".
- **`enabledMcpjsonServers` is not `permissions.allow`.** The install conflated "does the server
  load" with "is each call approved", so the default Claude Code install left every
  `zikaron_memory_remember` behind a prompt — the per-write friction the design calls worse than not asking.
  Now both are written, with the consolidator's server allowed **unconditionally**: a subagent has
  nobody to answer a prompt, which is the same argument kiro's `allowedTools` already makes.
- **Harness *values* were re-spelled outside the seam** — both kiro trigger names, all three Claude
  trigger names, and the marker variable — with no guard tying them back. Exactly intent 1's own
  defect class, in the milestone whose subject is the seam. All now derived from `HarnessSpec`.
- **`--model` was interpolated into YAML frontmatter unvalidated**, so `--model "a: b"` silently
  changed what the agent file *means*. Now shape-checked.
- **The "byte-for-byte" kiro guard compared parsed dicts**, so a change to the indent or the trailing
  newline would have shipped different bytes to every install and passed. The fixture now carries the
  exact serialized string.
- **Rejected, with the reason:** that the shipped frontmatter `tools:` block-list form was unmeasured.
  It is what the probe ran (`spikes/claude-code-installer/zk-gated.md`); the *note* paraphrased it
  inline and misled the reviewer. The note now quotes the fixture — the lesson is about paraphrasing
  evidence, and it is the second time in this milestone that a research note's prose diverged from
  what was executed.

**What review round 2 changed, and the one finding worth carrying past this milestone.** Thirteen of
round 1's fifteen items verified as resolved; two rejections upheld (`--print-only` keeping the
missing-commands refusal hard, and the block-form frontmatter, confirmed from the fixture). What
round 2 caught:
- **A blocker that is this corpus's own lesson, committed while fixing a review finding.** Round 1's
  `--model` fix landed as a *docstring* over an unchanged method body: the regex constant was
  compiled and never referenced, the docstring asserted a refusal, and the body was still
  `del model`. **The gate stayed green** — neither `ruff` nor `mypy --strict` flags an unused
  module-level `Final`, and no test exercised it — so the artefact affirmatively documented a guard
  that did not exist, which is worse than the state before the fix. M14's retrospective named
  exactly this shape ("the gate was green while something material was wrong three separate times");
  the practice that catches it is the one M14 also named: **watch the guard fail**. Every
  round-1 fix now has a test that would fail if the fix were reverted
  (`TestTheFixesFromReviewRoundOneAreWatchedFailing`), which is where the remaining round-2 items
  went.
- **Notes that asserted the opposite of the file.** A `--no-trust-tools` re-run over a previously
  trusting install printed "was **not** written" about grants still sitting in the file, since the
  merge never removes one. Both notes are now conditioned on genuine absence, the way
  `plan_kiro_merge` already conditioned its equivalent.
- **`--model ""` silently became the harness default**, because the value was selected with `or`
  rather than `is None`. Found by the test written for the *shape* check rather than by the check
  itself, which never saw the value.

**Scope fence:** **do not reach for `permissions.deny` to restore the primary agent's tool gating.** It is
the obvious move and it is measured to fail destructively: deny is global and *unregisters* the tool, so the
consolidator subagent whose frontmatter names it is then refused at spawn with "zero tools" (probe §6). The
weaker guarantee is M13's accepted decision, not a gap to be closed here. No run-token build either — also
M13's decision, restated here because this is the milestone whose author would be tempted.

---

## M16 — Dogfooding checkpoint under Claude Code

Normative: `design/harness.md`; `design/write-policy.md`; `design/schema.md` §"Linked sessions".

M12's scope fence said the harness's own reading of the installed files "is not testable from here — kiro is
not driven by the suite." **That is false for Claude Code**, measured: a headless `claude -p` run in a
throwaway project proved the hooks fire, that exit-0 stdout reaches the model, and that an MCP tool is
reachable — the full loop M12 could only defer to a dogfooding checkpoint. So this milestone adds a genuine
end-to-end test that the harness loads what we installed. It needs a live model call, so it is an **opt-in
tier outside `check.sh`**, never part of the coverage-ratcheted gate.

Then the instruments are read fresh. **The recall baseline resets at this boundary**: the pre-migration
numbers were taken under a different harness, a different model, a different injection position and a
different write-policy delivery, and they are recorded as a different-harness baseline that is **not** to be
compared against. FINDINGS' existing warning — "do not quietly compare across the boundary" — becomes the
decision rather than the caution.

**Done when:** push, pull, write and one consolidation run are observed in a real Claude Code session, against
**this repository's own seeded store or a throwaway** — see the fence; link coverage is read and is ~1.0,
confirming both clients resolved one label; the recall instrument is read and recorded as a new baseline with
the harness named beside the number; the injected block is confirmed to arrive intact and under budget; the
checkpoint consolidation runs under the model the config names rather than a substituted one — spawn refuses
an unknown id loudly, so this is observed rather than trusted; and a subagent is
observed to have actually **received** the write policy, rather than only our side being observed to emit it.

**Two observations from M15 that are this milestone's to act on or decline, recorded so they are not
re-derived.**
- **The e2e suite's external dependency is mostly incidental, and could be parameterized away.** Six
  tests need a live `kiro-cli`, but only **one** — `test_the_real_validator_does_not_check_model_ids`
  — genuinely requires the binary as the *point* of the test: it asserts the measurement the whole
  install-time model check rests on, and would fail loudly if a future kiro started rejecting unknown
  ids. The other five want a working *install*, and depend on kiro only because `_install()` calls
  `main()`, which runs the model check on the way past. **Claude Code performs no model check at
  all**, so the same install → hook → MCP → consolidation path could be exercised hermetically on
  that arm. Parameterizing the e2e tests across harnesses would give the gate a fully offline arm
  while keeping the one assertion that is genuinely about kiro's binary. Real scope; M16's call.
- **`pytest.skip` guards the wrong predicate there.** Those three tests skip when `kiro-cli` is
  *absent* — and they **failed** rather than skipped when its auth had expired, because the binary
  was present and answered with an authentication error. "Installed" and "usable" are different
  properties and only the first is checked. Whether to widen the skip is a judgement with a real
  hazard on the other side: a skip that swallows a genuinely broken harness is the silent pass this
  corpus keeps finding, so *failing* on an unusable binary may well be the right behaviour and the
  fix may be nothing more than the message saying which of the two it hit.

**Scope fence:** no cross-harness comparison of any instrument, in either direction. **And the checkpoint
consolidation does not run against `~/Memory`.** That store's next consolidation is reserved for designing and
testing the positive merge criterion on a journal grown by real work (FINDINGS priority 1) — a one-shot
experiment, since the corpus cannot be regrown, and one this checkpoint would confound twice over by running
under a changed harness *and* a changed model. A future session executing this brief literally will reach for
`~/Memory`, which `FINDINGS.md` then called the primary real-work store; that is the mistake this sentence
exists to prevent.

## M17 — The cold start loses the race it was given, and the encoder is why

Normative: `design/architecture.md` §Lifecycle and §"Filesystem security"; `design/schema.md`
§"Creating the dense index". Evidence: `FINDINGS.md` priority item 6, which carries the negative
result and most of the numbers below — one range differs, and the note under the table says so.

**The defect, observed in production twice before it was understood.** The first user message after
any gap longer than `idle_timeout` (default 30 min) loses its injected memories, silently. The store's
own logs give the whole chain, and it was only diagnosable because the idle-stop record added on
2026-08-18 exists:

```
03:34:53  service.log  stopping: reason=idle store=/home/nathan/Trading/LeibaTrader/.zikaron idle_for=1810.5s
15:57:09  service.log  a new service starts — spawned by the hook's own start-if-absent
15:57:10  hook.log     transport            ← the hook gave up roughly one second later
```

The service was never broken; it was not *ready*. `zikaron-hook` gives a freshly spawned service
`HEALTH_POLL_DEADLINE_SECONDS` — **1.2 s** — to answer `health()`, and a real cold start needs
**1177–1257 ms merely to bind its socket**, before `health()` can be answered at all. So the deadline
expires on a service that is working correctly and has simply not finished starting.

**Why the deadline is not the thing to change.** Its own comment says a cold spawn racing it and
losing "is exactly the case that must degrade (log to `hook.log`, relay on stdout) rather than make
the user wait", and `test_hook_connect_integration.py` covers that degradation against a fake service
that binds 5 s after spawn. Losing is a *specified* outcome. What is not specified is that it should
happen every morning. **Do not raise the constant to make this go away** — that converts a lost push
into a slower one for every user, and on a heavily loaded machine it would produce a longer wait
*and* still lose. The commit "Stop asserting a race the design says may be lost" (2026-08-19) already
separated the test question from the product question; this milestone is the product question.

**Why the warm helper does not already cover it.** The helper is spawned by the `SessionStart` hook,
so it protects the first message of a *session*. It does nothing when the service idles out *within*
one, which is the observed case: both failures are ~20:57 UTC a day apart — the first message after
an overnight break, which is also the message most likely to need memory. The loss is bounded and
self-healing (the service the losing attempt spawned stays up, so the next message is warm), but it
is one push per idle gap, indefinitely.

### What was already tried, measured, and reverted — read this before designing

**Attempt (2026-08-19): defer `FastEmbedEncoder.load()` to a background thread so the socket binds
first.** A `BackgroundLoadedEncoder` satisfying the sync `Encoder` protocol, started on a daemon
thread at construction, every protocol member blocking on a `threading.Event`;
`ServiceContext.assemble` split so the **open** path used it and the **create** path stayed eager.
It works in
isolation — construction returns in 0.2 ms against 1059 ms, first access blocks ~985 ms, subsequent
calls ~4 ms — and `assemble` itself drops from **~1100 ms to 245 ms** on the open path.

**It changed socket-ready latency not at all: 1224 ms deferred versus 1216 ms eager, three runs
each.** Reverted.

**The cause, and it is the trap this brief exists to keep the next session out of.**
`IndexingContext.__post_init__` (`core/indexing/writes.py:83–97`) reads `encoder.model_name` and
`encoder.dim` to validate them against the store's recorded identity, so assembly blocks on the load
whenever it was started. Reading `IndexingContext.for_store`'s *body* is what produced the wrong
conclusion — the body only stores the reference and takes its dimensions from `store.meta`; the eager
read is in `__post_init__`, one frame further in. **Verify what touches the encoder by experiment,
not by reading a constructor**: disabling the load thread entirely made the service hang, and a
`traceback.print_stack` in the accessor named the caller in one run.

The guard itself is good and must survive: *"an encoder that disagrees would write vectors labelled
with a model that did not produce them."*

### Measurements to design against, all taken 2026-08-19 on a machine at load ~6

| Quantity | Value |
|---|---|
| socket-ready, cold, open path | **1177–1257 ms** (deadline 1200 ms) — see the note below |
| `FastEmbedEncoder.load()` | **1059 ms** |
| `import zikaron.service.main` | ~360 ms — and it therefore does **not** import `fastembed` eagerly |
| `import fastembed` | **640 ms**, paid inside `load()` |
| `TextEmbedding.list_supported_models()`, marginal | **0.4 ms**, and it reports `dim=384` with no weights loaded |
| `assemble`, open path, encoder deferred | **245 ms** |
| `assemble`, create path (eager, required) | ~847 ms |
| first `embed()` once loaded | 4–7 ms |

**One number in that table is unreconciled, and it is left that way deliberately.** `FINDINGS.md`
priority item 6 records socket-ready as **1184-1235 ms** where the table says **1177-1257 ms**; the
two were captured in separate sittings and no record survives of which runs fed which, so picking
one would be inventing a provenance. Both say the same thing — a cold bind straddles the 1200 ms
deadline — and the done-when's idle-machine A/B supersedes both. Do not quote either as *the*
figure.

The arithmetic that matters: ~360 ms of imports plus ~245 ms of deferred assembly is ~600 ms, which
is comfortably inside the deadline. The remaining ~600 ms in the failed attempt was the model load
being pulled back onto the critical path by the guard.

### Four facts established after this brief was first written, which move the option set

Read out of the code rather than measured, so each costs nothing to re-check.

1. **`FastEmbedEncoder.model_name` is the string it was constructed with, not a fact read off the
   artifact.** `load` sets `ArtifactFacts.model_name=model_name` from its own argument, while `dim`
   comes from one real embedding. This is load-bearing twice below: it is why a deferred wrapper can
   answer `model_name` immediately without waiting for weights, and it is why today's guard cannot
   fire on the open path at all. **It is not an argument that dropping the guard is free** — an
   earlier revision of this brief drew that conclusion, and it holds only while `assemble` passes the
   config string to `load`, which is to say only while the programming error the guard exists to
   catch has not happened.
2. **The hook's binding constraint is the 1.2 s *connect* deadline, not its 2.0 s total.**
   `push.py`'s `_DEADLINE_SECONDS = 2.0` budgets connect *plus* the `surface` request, handing
   whatever is left to the request as a socket timeout. A service that binds at ~600 ms can
   therefore finish a background model load inside the `surface` call and still answer. Deferring
   the load does not merely move the wait — it moves it across the boundary that decides whether the
   push is delivered at all. **The corollary is a new risk to size:** the whole sequence must now fit
   2.0 s rather than the bind alone fitting 1.2 s, so the margin has to be measured end to end, not
   at the socket. The arithmetic, since a fresh session will otherwise size the margin from a guess:
   a load thread starting at assemble (~360 ms after spawn) and costing ~1059 ms completes
   ~1.42-1.56 s after spawn, so a `surface` arriving at ~700 ms on the hook's clock blocks
   ~700-900 ms *inside* the call and answers ~1.5-1.6 s into the 2.0 s budget. It fits, with roughly
   400-500 ms to spare — comfortably, but not so comfortably that the end-to-end measurement can be
   skipped.
3. **Every encoder access on the read path is already off the event loop.**
   `retrieval/reads.py::_prepare` runs `query.external_query` — all of the tokenizer work — through
   `asyncio.to_thread`, and `indexing/vectors.py` embeds through it too. A deferred encoder whose
   accessors block on a `threading.Event` blocks a worker thread there, which is exactly the
   acceptable case the invariants below name.
4. **One access is *not* off the loop, and it is the one to handle explicitly.**
   `indexing/writes.py::prepare` calls `chunking.plan_chunks` directly in a coroutine, and that
   uses `count_tokens`/`token_char_spans`. Today it is free because the model is already loaded;
   under any deferral it can block the event loop once, for whatever is left of the load. Bounded
   and terminating, so it is inside the invariant — but it must be stated, and wrapping that one
   call in `asyncio.to_thread` is the cheap remedy if the block is judged too long.

### What is actually at stake in the option choice, which is narrower than it looks

**Every option below presupposes re-landing the reverted `BackgroundLoadedEncoder` deferral.** None
of them moves socket-ready latency on its own; each is a *guard-side enabler* that decides how
`IndexingContext.__post_init__` stops dragging the load back onto the critical path. An
implementation that changes the guard and leaves the eager `FastEmbedEncoder.load` at
`context.py:150` improves nothing, and the done-when would eventually say so — but a sentence here
is cheaper than a discovered dead end.

**Three things are therefore common cost, and none of them is any option's marginal price:** the
wrapper itself; a *latched-failure channel*, because `FastEmbedEncoder.load` fails after the bind
for reasons that have nothing to do with identity — `encoder._artifact_failure`'s two `BAD_CONFIG`
artifact failures, plus download and disk failures on a cold fastembed cache — and that exception
must be caught in the thread and re-raised on access; and the *self-stop*, because the
resident-zombie state that follows a latched failure is identical under every option. What the
options actually buy or decline is only the identity handoff and one comparison in the loader.

**A latched failure must end the process, not sit in it.** `health()` never touches the encoder, so
a latched service would answer `ready=true` indefinitely while rejecting every real call — and
start-if-absent never replaces a live socket, so an operator's corrected config would not take
effect until idle-stop fired, up to 30 minutes later. Worse, each rejected message refreshes
`ActivityTracker`, so a user retrying keeps the broken service alive. On a latched failure the
service drains in-flight requests through the existing shutdown path, writes `log_self_stop` with a
new reason, unlinks and exits — **initiated by the loader thread the moment it latches, not by the
first access that raises**, so a mismatched service with no traffic does not sit resident until
idle-stop. Note that invariant 1's test cannot tell those two wirings apart, since observing
`-32023` requires sending a request either way. Exiting restores today's recovery loop exactly: the
next message spawns a fresh process against the corrected config. There is a genuine improvement
over today buried here, worth stating: the in-flight caller's hook normally receives `-32023` and relays
`bad_config (-32023)` to the model, where today's startup-failure path gives it only a poll-deadline
`transport`.

**`Store.open` already performs the config-vs-store comparison, on every open, with no encoder in
hand.** `Store.open` compares `config.get_str("embed_model")` and
`config.get_int("embed_dim")` against `meta` and raises `BAD_CONFIG` — invariant 11, named in
`open`'s own docstring. It runs before the socket exists and before `IndexingContext` is ever
constructed. So the **operator-error** case — someone editing `embed_model` against an existing
store — fails at startup under every option below, unchanged, and is not what any of them is about.

What the options decide is solely the fate of the **artifact-vs-store** check in
`IndexingContext.__post_init__`: the one that catches an encoder *object* whose measured facts
disagree with what the store recorded. Note what that guard is really for. On today's open path it
cannot fire — `assemble` passes the config string to `load`, and `Store.open` has already proved
config equals meta — so it is defence against **future code drift**, not against anything a user can
do. That is worth knowing before deciding how much machinery to spend on it.

### Three candidate designs, and the trade each makes

**Chosen: (d), operator decision 2026-08-19, after two review rounds
(`reviews/m17-cold-start-review.md`).** The case that decided it is not that (d) is safest — it is
that (d) is barely more expensive than the alternatives once the bookkeeping is honest. The wrapper,
the latched-failure channel and the self-stop are common cost, so (d)'s entire premium over the
cheapest (b) is two constructor arguments, two immediate properties and one `dim` comparison in the
loader: roughly fifteen lines. Against that, (b) would have to delete a shipped invariant test,
rewrite `IndexingContext`'s "Self-validating" docstring, and record an accepted silent-corruption
channel. **(b) and (c) are kept below with their trades intact** rather than deleted, because the
reasoning that ranked them is the part worth having if this is ever revisited — and because the one
serious argument against (d), that a test is the normal defence against our own programming errors,
deserves to be findable next to the reason it lost: a test pins the call sites its author enumerated,
and the drift this guards against is by definition a call site nobody has written yet.

**(b) Delete the `IndexingContext` check and rely on what already ships.** Not something to build:
`Store.open`'s comparison above is (b), already in the product. **The trade, stated at its real
shape:** the `dim` half stays *loud* — a wrong-width vector is refused at first embed by
`vectors.py:65` (`INDEX_FAILED`) and a wrong-width query fails against `vec0`, later and
worse-labelled than a startup `BAD_CONFIG` but never silent. The silence lives in the **name half at
equal width**: a different-model, same-dim encoder object reaching the write path writes vectors
labelled `identity.embed_model` that a different model produced, and nothing downstream fires. That
is exactly the `vec0` mislabelling `__post_init__`'s docstring names and D20 exists to prevent. If
this is ever chosen, the record cannot go in the guard's own comment, because the guard is gone: it
belongs in `IndexingContext`'s class docstring, whose "Self-validating, so every write inward may
assume the encoder matches the index it is writing into" (`writes.py:67-71`) becomes false under
(b) and has to be rewritten regardless. Record the weakening *and* the accepted silent channel
there, rather than letting either be discovered later.

**(c) Keep the check exactly as it is, and perform it lazily at first encoder use.** Nothing about
the comparison changes; only its moment does. **The trade is smaller than it first reads**, because
the config-vs-store mismatch still fails inside `Store.open` before bind: the only class that moves
to first-use is the narrow artifact-disagreement one — a registry serving different weights under an
unchanged name, or call-site drift. A per-first-use check must remember its verdict, so (c) needs
the same latch (d) does; the difference between them is *when* the verdict is computed, not how much
machinery it takes.

**(d) Load in a background thread, and validate inside that thread the moment the load finishes,
latching the failure.** The loader compares the freshly loaded artifact's measured `dim` against the
store's recorded identity — the artifact's `model_name` is an echo of `load`'s own argument (fact 1),
so `dim` is that comparison's entire content — and stores either the encoder or the `ZikaronError`,
which every blocking member then raises. **What it preserves:** the same artifact-derived `dim`
comparison, the same `BAD_CONFIG` payload, and no window in which a mismatched encoder is usable —
the validation stays eager *relative to the load*, which is the only ordering the guard's rationale
actually requires.

**How `__post_init__` is satisfied without blocking, which the implementation must get right or it
re-enters the reverted trap.** A wrapper whose every accessor waits on a `threading.Event` still
blocks assembly, because `__post_init__` reads `model_name` and `dim` during it — that is the
measured 1224-vs-1216 ms failure, arrived at from a different direction. The wrapper must therefore
answer those two properties *immediately*, from the expected identity: `model_name` from config
(byte-identical to what the artifact will report, since `load` sets `ArtifactFacts.model_name` from
its own argument) and `dim` from `store.meta.embed_dim`, which is itself an artifact-derived
measurement cached at create time rather than a transcribed constant.

**What that does and does not make vacuous, stated precisely, because the loose version of this
sentence is itself a defect.** An earlier revision of this brief mandated a comment saying
`__post_init__` "structurally cannot fail" for the wrapper. That comment would be false, and a
false reassurance in the opposite direction is no better than the thing it warns about. Taken half
by half: the **name** comparison keeps *exactly* the strength it has today, because per fact 1
today's check already compares a declared string — `load`'s echoed argument, sourced from config —
against `meta`, and the wrapper's expected `model_name` comes from the same config key with the same
provenance. Nothing weakens. The **dim** comparison is the only half that goes vacuous for the
wrapper, becoming meta against meta; its real content, the *measured* width, moves into the loader's
latched comparison rather than disappearing. And the check as a whole still fires for a wrapper
seeded from one store's config and wired into another's `IndexingContext` — the cross-wiring case,
which is the concrete shape of the future drift §"What is actually at stake" says this guard exists
for. That is the comment the code should carry. One parenthetical for the implementer: since the
wrapper calls `load(expected.model_name)`, the loader's *name* comparison is an echo and vacuous by
fact 1, so `dim` is that comparison's entire content — do not write a name assertion there and
believe it tests something.

The check stays fully eager on the create path and for every direct construction, including
`FakeEncoder` and the tests. **No protocol change is needed and `FakeEncoder` is untouched**, which
is worth stating rather than leaving to be re-checked: `Embedder`'s own docstring already licenses
declared identity — "this protocol says nothing about *how* `dim` is produced; only that it is
available without embedding anything" (`embedder.py:21`) — and `FakeEmbedder` is shipped precedent.
The wrapper conforms by the protocol's charter, not by a loophole in it.

**One ordering consequence, and it is not a free choice.** The wrapper needs `store.meta.embed_dim`,
which only exists after `Store.open`. So either the load thread starts after the open — losing
~140 ms of overlap — or it starts at the top of `assemble` and waits on a set-once identity event
satisfied ~140 ms in. **Start early is the default**, on this brief's own numbers: starting after
the open pushes load completion to ~1.56-1.70 s, so a `surface` arriving at ~700 ms answers
~1.65-1.75 s into the 2.0 s budget — a margin of ~250-350 ms, straddling the ~300 ms threshold below
which the shelved split-deadline lever would have to be pulled. It spends roughly a third of fact
2's margin to avoid one event. The event costs nothing at runtime in exchange: it gates only
*validation*, and by the time `load` returns at ~1.4 s the identity has been set for over a second,
so the loader thread never actually waits on it. The milestone must still record which it chose.

**Rejected, recorded so none is re-proposed:**
- **Answering `dim` from `TextEmbedding.list_supported_models()` (the brief's original option (a)).**
  Two independent reasons, either sufficient. Its critical path is ~360 ms of service imports plus
  the ~640 ms `fastembed` import that call requires plus ~245 ms of assembly — **~1.25 s against a
  1.2 s deadline**, so it fails this brief's own done-when on this brief's own numbers, and running
  the load concurrently does not help because both threads serialize on the same module import lock.
  And it does not keep the guard as strong: `list_supported_models()` reports the registry's
  *claimed* dimension for a name, not the artifact's measured width, which is a transcribed constant
  outsourced one shelf over — the same character of thing as the model→dim table below.
- **A Zikaron-owned model→dim constant table.** Makes the lookup free by reintroducing exactly the
  transcribed-from-a-model-card constant D20 forbids and `FastEmbedEncoder.load`'s docstring
  disclaims.
- **Raising `HEALTH_POLL_DEADLINE_SECONDS`** (see above).
- **Re-triggering the warm helper on a cold start** — the service is *already* spawned by
  start-if-absent, so this changes nothing.
- **Binding the socket before assembling the store**, which `main.py`'s own docstring rules out —
  "rather than binding a socket for a store it could not open" — and which this milestone must not
  quietly reinterpret. That argument is about the **store**; it has never been about the encoder,
  and that distinction is the whole opening this milestone works in.

**One lever deliberately left on the shelf, named so it is not mistaken for an oversight.** The
1.2 s deadline is shared between two unlike situations: connecting to a service that already exists
and might be wedged, and waiting for one this very process just spawned. Splitting it — a short
deadline for the former, a longer one for the latter — is *not* the same move as raising the
constant, because only the case where we know a service is coming would wait. It is still refused
here: it makes the user wait rather than making the service ready, and the 2.0 s total would have to
move with it. Keep it as the fallback if the measured end-to-end margin turns out thin — under
~300 ms is the threshold worth acting on.

**Fix in passing:** `zikaron/hook/connect.py::_poll_until_reachable`'s docstring breaks off
mid-sentence at "…well before `ServiceContext.assemble()`'s model load" (connect.py:264-266), and
under any deferral its premise inverts — assemble no longer contains the model load, and `health()`
becomes true before the encoder is ready. M17's implementer edits exactly that behaviour story. The
same correction is owed to `health`'s own docstring (`dispatch.py:85-89`), whose justification — "a
service that can answer at all has, by construction, already opened its store" — stays true of the
*store* but stops covering the encoder: after M17 an encoder failure latches post-bind, so
`ready=true` no longer implies a working encoder, and a reader of that docstring would draw exactly
the conclusion the self-stop exists to prevent.

### Invariants to cover

- A **dimension** whose measured value disagrees with the store's recorded identity is still
  **refused** with `BAD_CONFIG` and the same payload — asserted **where a client sees it**, not at an
  internal latch: the blocking member raises the latched error, the in-flight RPC answers `-32023`,
  and the service self-stops with the new reason. Assert it by *breaking* it — hand the loader an
  artifact whose measured `dim` disagrees with the store's — rather than by unit-testing the
  comparison function alone or by asserting the happy path. **A disagreeing model *name* cannot
  reach the latch at all**, because the artifact echoes `load`'s argument (fact 1), and chasing it
  through this chain would mean writing a stub that misrepresents the real loader. It is still
  refused exactly where it always was: config-vs-meta at `Store.open`, before the bind, and
  `__post_init__` on a cross-wired wrapper — both startup-shaped, and unchanged by this milestone.
  **Under (b) this invariant could not have been met at all** and its test would have been deleted:
  the construction-time guard is gone there, a disagreeing `dim` surfaces later and differently as
  `INDEX_FAILED` at first embed (`vectors.py:65`), and a disagreeing name at equal width surfaces
  never. That was part of (b)'s price, and it is why this invariant in its original form would have
  silently decided an option choice the brief was presenting as open.
- The **create** path is unchanged: a first-ever run still loads the model before `Store.create`,
  because sizing the dense index needs `.dim`/`.model_name` before any table exists.
- Nothing blocks the event loop in a way that cannot terminate. A wait on work being done by another
  thread is acceptable and must be *stated*; a wait on work that needs the loop is the `busy_timeout`
  deadlock class `architecture.md` names and is not.
- The `Encoder` protocol does not change under (d). `FakeEncoder` (`tests/fake_encoder.py`) stays
  untouched and the whole hermetic tier keeps running on it; a change here would be evidence the
  design has drifted, not a step in implementing it.

**DONE 2026-08-25** — measurements and both arms in `research/m17-cold-start-ab.md`; the defect was
reproduced under synthetic load (old: 0/5 clean pushes, a `transport` line every run) and removed
(new: 5/5 at higher load). One thing the brief did not anticipate, worth carrying: **the defect is
load-dependent, so the idle machine this done-when asked for cannot demonstrate it** — at idle the
old code wins the race 3/3. The idle numbers are the clean timing comparison; the *outcome* needed
load.

**Done when:** socket-ready on the **open** path is measured below the hook's deadline with margin,
by the same A/B shape used above — three runs each of the old and new code on a pre-existing store,
numbers recorded — and the identity guard is shown still failing on a deliberate mismatch. The
create path's timing is explicitly *not* a target. `./check.sh` exits 0.

**And assert the defect's absence directly, not only its instruments.** The defect is "the push is
silently lost", so the outcome-level observable is the one that has to be shown gone: against a
genuinely cold service, the hook's stdout is the surface block rather than a degrade relay, and
`hook.log` gains no `transport` line — three of three runs, idle machine, load recorded.
Socket-ready-with-margin and the whole-sequence timing are the right instruments, but neither of them
*is* the defect.

**Measure the whole hook sequence, not only the bind, and record the machine's load beside every
number.** Fact 2 above moves the binding constraint from the 1.2 s connect deadline to the 2.0 s
total, so a bind that fits with margin proves nothing on its own; the end-to-end push has to be
timed against a genuinely cold service. And every number in the table above was taken at load ~6,
which is why they are stated with a range rather than a figure: this project's earlier benchmarks
were taken on a near-idle machine, and a loaded one is fine for deciding *whether* something works
but is not a source of truth for *how fast*. Take the deciding A/B on an idle machine, and say in
the note which it was.

**Scope fence:** do not change `HEALTH_POLL_DEADLINE_SECONDS`, do not change the socket-before-store
ordering, and do not weaken the identity guard without saying so where the guard's own contract is
stated — its comment under (d), and `IndexingContext`'s class docstring under (b), which is where
that claim would live once the guard itself is gone. The idle timeout is not the subject either: a
service idling out after 30 minutes is correct, and making it linger would trade a bounded,
self-healing loss for a permanent resident process per project.

---


## M18 — A group too big to deliver, and a file the consolidator can actually read

Normative: `design/architecture.md` §Components and §"Filesystem security"; `design/harness.md`
§"The table"; `design/consolidation.md` §"What `candidates` actually is". Evidence:
`research/claude-code-mcp-result-truncation.md` for every harness measurement, and
`research/consolidation-payload-sizes.md` for how large a group actually gets in a real store —
including what the rejected trimming alternative would have cost.

**The defect, observed in production before it was understood.** A consolidation run against
`~/Trading/LeibaTrader` stalled: `zikaron_memory_next_group` returned a group the harness refused to
deliver. Re-running appeared to fix it, which is the misleading part — the first run had merged
part of the journal, so the second run's groups were smaller and fit. The fault is not
intermittent; it is a function of how much prose a group happens to carry, and it returns whenever
a group is large again.

**What the harness does, measured.** Claude Code caps a tool result in *tokens*, replaces it
entirely with `Error: result (N characters) exceeds maximum allowed tokens.`, and writes the full
result to `…/tool-results/mcp-<server>-<tool>-<epoch-ms>.txt`. The threshold is content-dependent
and was never stated numerically by the harness; it is bracketed, not known.

**Why the obvious fix does not work, and this is the trap to avoid.** Granting the consolidator
`Read` so it can open that spill file fails, for a reason that is structural rather than
incidental: the harness writes the tool's JSON on **one line**, and `Read` says outright that such
a file "cannot be paginated by line". Measured: 31,247 of 104,179 characters returned, and
`offset=1, limit=1` refused outright. An earlier attempt shipped exactly this, with prompt text
telling the consolidator the file "is still your payload" — which is false.

**What makes the fix possible.** The `Read` cap applies **per read, not per file**. A
206,719-character, 2,002-line file was read to its end in three calls, the tail recovered by a
targeted `offset`, with an over-long offset degrading to an advisory naming the true line count
rather than an error. So an over-large payload is fully recoverable if — and only if — whoever
wrote the file made it line-paginable. The harness does not. Zikaron can.

### The design

**`zikaron-mcp` spills; the service does not.** The client is what hands a result to a harness and
the only component that knows which harness it is. The service keeps returning whole payloads over
the socket, unchanged, so nothing about the store, the serve path or kiro moves.

**Spill at the client's shared result-translation seam, so every tool result is covered.**
`next_group` is the observed offender, but it is not the only large shape: a `merge`/`promote`/
`discard` **conflict** response carries `current: [...]` with the full prose of every conflicting
row, and a dozen large rows is plausibly over any conservative threshold. Gating on the verb would
leave that shape to be discovered the same way this one was.

**Scoped to the consolidator client mode, though, and that qualifier is load-bearing.**
`response_to_tool_result` is shared with the primary client, so spilling at the seam unqualified
would hand a primary agent a pointer too — and everything that makes a pointer intelligible is
consolidator-only: the prompt sentence, the `Read` grant, and the pointer-shape invariant, which
discriminates against a served group rather than against a `fetch` result. A primary agent handed a
pointer would have been told nothing, anywhere, about what it means. Whether the primary client can
overrun the same cap is **unmeasured and out of scope**; mode is already a `build_server` parameter,
so the scoping costs nothing.

**What the file must satisfy, measured rather than assumed.** The requirement is *not* "short
lines". `Read` never clips a line as a line: lines of 2,000, 8,000 and 20,000 characters came back
complete, and a 60,000-character line cut from a whole-file read was recovered **intact, with no
truncation notice**, by a targeted `offset`. What bit was the per-read token cap on the whole file.

So the rule is: **no single line may exceed the per-read cap**, because a line is the smallest unit
`Read` can address and there is no sub-line pagination to fall back on. Pretty-printing is how that
is achieved, but the reason is narrower than it first appears — indentation splits JSON *structure*,
not *strings*, so a record's `content` remains exactly one line however the document is indented.
The longest line in a spill file is therefore the longest single string value it contains, and that
is the quantity to bound and to assert.

**That bound is `SPILL_MAX_LINE_BYTES`, a fixed constant of 24,000, counted in UTF-8 bytes of the
serialized line** — and the unit is the whole point. A character count would need a
characters-per-token ratio to bound anything, and that ratio is content-dependent: `json.dumps`
with `ensure_ascii=True` inflates a CJK character to six characters while it tokenizes to about
one, and with `ensure_ascii=False` the same character counts as one while still tokenizing to one,
so the two escapings differ by up to 6× and only one of them makes a ratio argument hold.

**Bytes need no ratio, because a token spans at least one byte.** Tokens are therefore bounded by
bytes for any content whatsoever — emoji, CJK, minified code, anything — **for any counter that
does not expand its input before counting**, which byte-level BPE cannot and which no measurement
here contradicts. That qualifier is the assumption, stated rather than buried: a counter that
Unicode-normalized first could expand one compatibility character into many tokens and break the
bound. A violation would surface as the loud refusal below, never as silent loss. So a 24,000-byte
line is at most 24,000 tokens, strictly under `Read`'s measured 25,000-token cap. Both measured
pairs are consistent (104,179 characters measured 70,848 tokens; 94,328 measured 31,183 — both
ASCII, so characters and bytes coincide there). It also clears the longest `content` in the observed store,
**17,275 bytes**, by 1.39×. A consequence worth having: the spill file may then be written with
`ensure_ascii=False`, which keeps non-ASCII prose readable to the consolidator, because the bound
no longer depends on the escaping.

**A record whose serialized line would exceed it is refused, loudly, when the client serializes the
spill file.** That is *client serialization* time, not `remember` time: the scope fence forbids
bounding `content`, and nothing here constrains what a user may record. The refusal is a tool error
naming the offending record's uuid and its escaped line length, because unlike the threshold there
is **no key an operator can lower** to make a single over-long record deliverable — the remedy is
amending or retiring that record, and the error is the only thing that can say which one it is.

**The response that replaces the payload is a pointer**: small, fixed in shape, naming the path and
saying plainly that the file is the payload. It must be unmistakable for a served group — a
consolidator that read a pointer as content would decide a merge from a filename — which is an
assertion about its shape, not a hope: it carries no `journal_entries` key.

**Location: the runtime directory**, beside the socket — already `0700`, already per-user, already
tmpfs, so it never enters the project tree. `architecture.md` §"Filesystem security" governs the
mode. The store directory is deliberately not used.

**Lifetime.** Between reboots the runtime directory is RAM, and a spilled serve is a verbatim copy
of record prose living outside the store. Filenames are unique per serve, so a re-serve can never
overwrite a file a `Read` is midway through. Cleanup is **two mechanisms, neither of which depends
on this process exiting**:

- **Release on `next_group`.** Safe for a narrower reason than it looks: *not* that the previous
  group becomes unreachable — authorization is rewritten per group rather than globally, a failed
  request rewrites nothing, and an unfinished group is deliberately re-served before the run
  advances — but because **every route back passes through a fresh serve, which spills a fresh
  copy**, so a released file is never the last copy of anything reachable. The trigger is a new
  *group*, not a new *file*. Runs before anything in the call that can fail, so a planning failure
  does not skip cleanup, and bounds the live set to one group's files.
- **Sweep at start.** A consolidator, before serving anything, unlinks this store's spill files
  whose pid is no longer running. A run that ends properly leaves nothing — the consolidator learns
  it is over by asking for a group and receiving `{done: true}`, and that call releases the last
  group first — so what the sweep reaches is the run that **stops without asking again**: a killed
  process, or a consolidator that quits after the final `group_complete`. One window it cannot
  close: the pid is the MCP server's, not the reader's, so a server that dies mid-session has its
  files swept by its replacement, possibly one the session is partway through reading. That fails
  loudly with a missing file and recovers on one re-serve, and it is also why the primary client
  must not sweep.

**Corrected after the end-to-end run, which is the reason there are two.** The design said "the
client unlinks what it wrote when it exits", implemented as an `atexit` handler, and a real
consolidation **left four spill files behind** — 217 KB of record prose in tmpfs. The harness runs
one MCP server per session and *terminates* it when the session ends; a terminated process runs no
`atexit` handler, and a killed one could not. The hermetic test passed because its subprocess exits
normally, so it asserted a lifecycle the production process never has. `atexit` is kept for the
clean-exit case and is explicitly **not** the mechanism. Evidence, including the transcripts copied
out of the harness's pruning window: `research/m18-spill-end-to-end.md`.

**Also withdrawn, earlier and for a different reason: "the client unlinks its previous spill when
writing the next."** It would delete a payload still in use — a conflict response spills through the
same path, so writing one would remove the group's file while the consolidator is still
dispositioning that group from it. Note how narrowly that differs from what ships: the trigger is
a new *group*, not a new *file*. `write-policy.md`'s operator erasure procedure gains one line naming the
runtime directory, because a secret erased from the store could otherwise survive in a spill file
until reboot — a fourth surface that procedure does not currently enumerate. That directory is
shared by every store this user has, so the filename must lead with the same hash the socket is
named for; without it the procedure instructs an operator to find "this store's" files among files
that do not say which store they came from.

**The threshold is a config key.** `consolidation.spill_threshold`, default **27,000**, unit
**UTF-8 bytes of the serialized result** — the bytes the client would otherwise return, not prose
characters, and the distinction matters because the *prose* figures in
`research/consolidation-payload-sizes.md` are floors; the byte pass in that same note is what the
58% below reads from.

**The default is a proof rather than a margin, and that is what makes it future-proof.** The
harness states character counts and never token counts, so its token bracket is **derived**: a
payload of 44,000 characters was delivered and one of 50,012 refused, which at the only token
accounting the harness exposes (0.68006 tokens per character) is ≈29,923 delivered and ≈34,011
refused — the arithmetic is in `research/claude-code-mcp-result-truncation.md` §"The cap in tokens,
derived". Since a token spans at least one byte, a payload of 27,000 bytes is at most 27,000
tokens, **≈2,900 tokens (9.8%) under the largest payload the harness was observed to deliver**. No
characters-per-token ratio appears in that argument, so the emoji, CJK and minified-code cases that
defeat a character threshold are bounded by construction.

**What that costs, stated because it is the visible consequence:** 67 of the observed store's 116
groups — 58% — exceed 27,000 serialized bytes and would spill. That is a large share, and it is the
right trade because of the asymmetry this whole design rests on: a spill costs one `Read`
round-trip, and the alternative costs the group.

**How much of that is the bracket being loose was checked rather than assumed.** A second
bisection tightened the delivered floor from 40,000 to 44,000 characters, which raises the largest
*provable* threshold to ~29,900 bytes — 54 of 116, 47% — or 51% at a more prudent 29,000. So a
tighter bracket does buy points, and a third could buy more: the note's table shows 37% at 32,000,
which becomes provable if ~47,000 characters ever delivers, and nothing recorded rules that out.

**The argument against chasing it is the margin, not the bracket.** Every one of those thresholds
buys spill points by hugging the measured floor — at 29,900 the margin is 0.1% — and the margin is
the whole reason this default is future-proof: it is what absorbs the harness changing its cap
between versions. Trading 9.8% protection for eleven points of round-trips inverts the property the
section is named for. That is why a third bisection is not the remedy, and it is also why the
store's median payload sitting within 3% of the proven floor matters: spilling is simply the normal
path on a mature store, which is an argument *for* the done-when exercising it end to end rather
than a defect.

**And the failure mode — if the harness ever lowers its cap below 27,000 tokens, or its counter
ever assigns a payload more tokens than it has bytes — is the honest part:**
a payload refused inline is the original loud stall, never silent loss, and the operator's remedy is
lowering the key. That is what keeps "does not need revisiting" a claim this brief can defend — the
threshold is recoverable by configuration in both directions, without a code change, and at the
default it depends on nothing about the content.

**`Read` is granted to the consolidator on Claude Code only, and spill eligibility is
`HarnessSpec` data, not a branch.** CLAUDE.md forbids a harness difference living downstream of
detection, so "kiro returns over-threshold payloads inline" must be a field the client reads, not an
`if harness is KIRO:`. `design/harness.md` states that every harness-varying value is a `HarnessSpec`
field **with a D34 table row**, and a drift test enforces it, so M18 adds rows for: the MCP-result
cap and its overrun behaviour (the table has neither today), the consolidator's `Read` capability,
and spill applicability.

The `Read` grant widens D32, which withholds retrieval so that D7's "code picks the candidates" is
enforced mechanically rather than by prose. The widening is real and is bounded by prose alone: this
harness has no per-subagent path rule, so `Read` is grantable but not scopable. Operator decision,
taken with that stated.

**One gate was unresolved, and the end-to-end run settled it: it prompts, and that is left alone.**
Measured in an operator-driven session in default permission mode — the consolidator's first `Read`
of a spilled payload raises a permission request, and the harness offers to allow reading from that
directory **for the session**. Every earlier run missed it by running with the gate pre-answered.

**A `permissions.allow` entry for the runtime directory was considered and rejected.** The argument
for one was that repeated prompts would push operators into auto-accept mode, which grants
everything and is strictly worse than a narrow entry — but the harness's own option is per-directory
and per-session, so one prompt covers a whole consolidation and that pressure does not arise.
Against an entry: `Read` is grantable but not scopable in subagent frontmatter, so this prompt is
the single point at which D32's widening becomes a check an operator *answers* rather than prose;
the session-scoped grant is narrower than anything an installed settings entry could express; D10
makes consolidation operator-invoked, so there is no unattended flow to stall; and on a mature store
spilling is the **majority** path, so a permanent entry would have the widened grant exercised
silently on essentially every consolidation forever, where the prompt costs one answer per session.
Its recurrence per session is therefore periodic re-visibility of the one widening D32 cannot
enforce, rather than friction to apologise for. What the install does owe is warning: a third note
tells the operator the prompt is coming and which option to pick.

**The Claude Code consolidator prompt gains one truthful sentence.** The pointer is, by shape, tool
output telling the reader to go and act — the same shape as the harness's own spill notice, which
both models in the probe correctly flagged as untrusted and declined to follow. A consolidator
applying that stance to *our* pointer would balk or improvise. So the prompt states plainly that an
over-large group arrives as a pointer naming a file in Zikaron's own runtime directory, that the
file is the payload, and that it is to be read to its end before anything is decided. Unlike the
reverted attempt's text, this is true.

**kiro gets none of this, deliberately.** Its consolidator has no file-reading tool, and what kiro
does with an over-large MCP result is **unmeasured** — an earlier attempt asserted it "truncates in
silence with no path", and there is no evidence for that. Recording it as unmeasured is better than
inventing a remedy for behaviour nobody has observed.

### Rejected, recorded so none is re-proposed

- **Reading the harness's own spill file.** Single-line JSON; measured unreadable. This is the
  attempt that motivated the milestone.
- **Trimming candidates to a size budget.** Works — 18 of the 20 oversized groups in the observed
  store fit once low-ranked candidates are dropped — but it *loses* data, so its threshold must be
  right, which means fitting it to one store's distribution and revisiting it as corpora grow.
  Modelled over that store, a budget low enough to fit reliably — 35,000 or below, since 40,000 prose
  characters at the maximum measured framing overhead (1.165×) reaches ≈46,600 serialized, inside
  the 44,000–50,012 spill bracket — drops 12–33% of all candidates, and
  each dropped candidate is a merge the consolidator was never offered
  (`research/consolidation-payload-sizes.md`). The spill keeps every one of them.
- **Serving candidates as gists only.** Rejected by the operator on the ground that a gist is never
  sufficient to decide from — and independently unsafe: `verbs.py` permits a merge target to be
  "its anchor or one of its candidates", and `merge` rewrites the target's whole prose, so a merge
  decided from a candidate's gist would destroy prose nobody read.
- **Bounding `content` at write time**, so the payload becomes provable by arithmetic. Attractive
  and closest to M14's gist bound, but it constrains what a user may record in order to satisfy a
  consumer's undocumented limit — the tail wagging the dog — and it cannot be applied retroactively
  to stores that already hold long records.

### Invariants to cover

- **No line in the spill file exceeds `SPILL_MAX_LINE_BYTES`**, counted in UTF-8 bytes of the
  serialized line. This is the property recovery depends on, since a line is the smallest unit
  `Read` can address. Assert the longest line, not the line count — a compact-JSON regression and
  an unsegmented over-long string must each fail it.
- **A record too long to serialize within `SPILL_MAX_LINE_BYTES` is refused loudly at client
  serialization time**, rather than written into a file whose tail cannot be reached.
- An **under-threshold** payload is returned inline and unchanged, so the spill path is reached only
  when it is needed. Note that on a mature store the majority case is *over* threshold, so this is
  not "the ordinary case pays nothing" — it is "a payload that fits is not touched".
- The pointer response **names a file that exists and is readable**, at `0600`, inside the runtime
  directory and nowhere else — and **carries no `journal_entries` key**, so it cannot be read as a
  served group.
- **Round-trip fidelity**: what the file holds parses back to exactly the payload that would have
  been returned inline. Assert by comparing the two, not by inspecting the file's shape.
- **Under a kiro-detected client an over-threshold payload is returned inline**, and this follows
  from `HarnessSpec` data rather than from a branch on the detected harness.
- **Under the primary client mode an over-threshold payload is returned inline and unchanged** —
  spilling is a property of the consolidator mode, asserted against `build_server`'s mode
  parameter. Without this, an implementation that spills at the shared seam satisfies every other
  invariant here while handing a primary agent a pointer nothing has ever explained to it.
- Nothing about the **service or the store** changes. Kiro's consolidator config gains no tool, and
  its prompt gains no truncation text.

**Done when:** a consolidation completes against a store holding a group over the threshold, driven
end to end through a real Claude Code session rather than asserted from a unit test, with the
harness refusing no result and the consolidator shown reading the spill file **to its end**. The
store used must contain **at least one record whose serialized line is 17,275 bytes or longer** —
the longest observed in a real store — otherwise "readable to its end" passes on short-lined fixtures
while every real store fails.

**The end-to-end run demonstrates one-call spill-and-read, and multi-call pagination is accepted on
the probe's evidence.** That is a decision rather than an oversight: no group in the observed store
produces a spill file over `Read`'s per-read cap — the largest serializes to 73,184 bytes, which at
prose densities measured in M14 (≥3.89 characters per token, embedding tokenizer) is about 18,800 tokens against a 25,000
cap — so an end-to-end run against a realistic store
cannot exercise the targeted-`offset` continuation however it is arranged. Manufacturing a store
that could would be testing the fixture. The continuation path is measured in
`research/claude-code-mcp-result-truncation.md` and covered in the unit tier; if a corpus ever
produces a spill file over the cap, this is the clause to revisit. The run also
settles whether `Read` of the runtime directory prompts for approval — **it does**, and the answer
is `harness.md`'s "Reading a spilled payload" row. The `permissions.allow` entry this clause
originally promised was **considered and rejected** once the prompt's shape was measured; the
reasoning is in §"The design" above.
`./check.sh` exits 0.

**Scope fence:** do not bound `content`, do not change the sharding rule, do not add a consolidator
verb, and do not invent kiro behaviour that has not been measured. The groups in the observed
store whose anchor and members alone exceed **40,000 prose characters** — two of them, sizes in
`research/consolidation-payload-sizes.md`, and that is the bound they were measured at rather than
the threshold — need no special handling here, and neither does any smaller group the byte
threshold now also spills, because **the spill delivers them all whole**; whether such a group ought to be *split* for the consolidator's benefit
is the size-aware sharding question, which needs its own brief and its own evidence.

---

## Knowledge index — M19 to M25

**Normative for all of these: `design/knowledge-index.md`.** It is APPROVED and carries no operator
sign-off. This preamble used to add *"it becomes normative when the first of these milestones lands"*
— **that trigger has now fired**, since M19 is complete, and the conditional is withdrawn rather than
silently satisfied: M19 is a spike that wrote no product code, and sign-off is not something a
milestone can supply. **Whether the document is now normative is an operator call still owed**;
`FINDINGS.md` carries the argument. Until it is made, `design/overview.md` remains the authority for
anything the two disagree on. Section references below are to `knowledge-index.md`.

**The through-line: every milestone leaves a working, shippable codebase**, and the capability grows
monotonically — you can create knowledge bases before you can index them, index them before you can
search them, search them lexically before the dense arm exists. No milestone leaves a half-wired
surface that a later one repairs.

**Why the order is what it is.** The risk is front-loaded into M19 because three of this design's
mechanisms rest on behaviour nobody here has measured, and each would force a redesign rather than a
patch if it turns out otherwise. Everything after M19 is construction against measured ground.

---

## M19 — Spikes: the three mechanisms that could force a redesign

Normative: §3.2, §4.1, §5.2, §5.6, §7.2, §8.4.

**Landed 2026-09-15 without a pre-landing review gate, on operator direction — a research spike's
output is measurement plus a design amendment. It was then reviewed post-landing** on the operator's
subsequent instruction, the results having turned out substantial enough to warrant it: **four rounds,
APPROVED 2026-09-15**, trail `reviews/m19-spikes-review.md`, which corrected a blocker and four
overstated or unmeasured claims.
All three mechanisms **held**; nothing forced a redesign. What
the probes bought is **fourteen corrections**, enumerated in the three notes' own "What changes in the
design" sections (5 + 6 + 3) and all folded into `design/knowledge-index.md`. **One of the fourteen was
found by reading rather than by probing** — §7.2 called cosine ordering "blind" while §8.3 three
sections away gives exactly such a chunk an explicit `chunks_vec` lookup — and it is counted inside
spike C's three, not added to them. Notes:
`research/knowledge-index-vec0-fts5-probe.md`, `research/knowledge-index-git-shapes.md`,
`research/knowledge-index-group-ordering.md`; harnesses `spikes/spike_vec0_fts5_ddl.py`,
`spikes/spike_git_shapes.py`, `spikes/spike_group_ordering.py`, all re-runnable.
**`design/knowledge-index.md` §16 open question 2 is closed by spike C** and question 11 is opened by
spike B (directory-level `check-ignore` pruning, throughput only, deferred to M21).

**Throwaway probes under `spikes/`, results to `research/`. No product code.** Each answers a question
the design currently *assumes*, and this project's own history is the argument for asking first:
`research/kiro-mcp-lifecycle-probe.md` exists because a documented shape turned out not to hold, and
this design's §5.2 was rewritten mid-review because a probe found `ls-files -s` lists sparse-checkout
files that are not on disk.

**Spike A — `vec0` drop-and-recreate inside one transaction, and external-content FTS5 delete/reinsert.**
§8.4's encoder-mismatch repair drops `chunks`, `chunks_fts` and `chunks_vec` and recreates the vector
table **at a new dimension in a single transaction**; §3.2 and §5.5 rest on external-content FTS5 not
observing content-table deletes, so rows must be removed explicitly. Both are asserted from
documentation. Probe: does DDL on a `vec0` table inside a transaction roll back cleanly on failure; what
does an external-content FTS5 query return when content rows are gone; does a dimension change survive
a reopen. **If any of this does not hold, §8.4's repair and §3.2's no-cascade reasoning both change.**

**Spike B — git plumbing on real repository shapes.** `git check-ignore --stdin -z` and
`check-attr --stdin -z` in batch, `ls-files -s` plus `status --porcelain -z -uall`, against: a submodule,
a sparse checkout, a linked worktree, a `safe.directory`-refusing clone, a case-insensitive mount if one
is available, and paths with spaces and newlines. §4.1, §5.2 and §5.6 are written against measured
behaviour for `ls-files`/`status` and **inferred** behaviour for `check-ignore`/`check-attr`. Extends
`spikes/spike_hash_timings.py`, which already exercises this ground.

**Spike C — group ordering on a real multi-KB corpus.** §7.2 orders groups by best dense cosine and
records (open question 2) that this is blind to a lexical-only hit, which is exactly the
code-knowledge case. Build three small KBs, run identifier-shaped and prose-shaped queries, and compare
cosine ordering against a fused-contribution ordering. **This one is a code-shape question, not a
parameter question** — the fusion parameters are `meta` keys and can be swept later, but *which
quantity orders the groups* is a branch in the ranking path.

**Invariants:** none — no product code. **Done when:** three notes under `research/`, each naming the
question, the method and whether the design's assumption survived; every re-runnable harness committed
under `spikes/`; and any assumption the probes refute is corrected in `design/knowledge-index.md`
**before M20 starts**.

**Fence:** no product code, no schema changes. Throughput measurement is deliberately *not* here — it
sizes K8's argument but cannot change the design, so it rides along in M21.

---

## M20 — The registry, and knowledge-base lifecycle without indexing

Normative: §3.1, §3.1a, §3.2, §8.4, §8.6, §9, §11; invariants 11, 14, 15.

`knowledge_bases` lands in `memory.db` — **and `design/schema.md` gains its section, closing the
deliberate deferral in §3.1a.** KB databases are created at `knowledge/<uuid4>.db` with the full §3.2
schema including `chunks_vec` and `chunks_fts`, and `meta` seeded from configuration.

**The first decision of this milestone is a compatibility one, and it is not obvious.**
`design/schema.md` §"`meta.schema_version`" supported **exactly `schema_version = 1`** when this brief was
written, and *"a newer `schema_version` is not [tolerated]"* — an unknown value is refused with
`−32024 schema_incompatible`. (It supports a range since M31; §"Migration posture" is normative, and the
additive-table rule this milestone wrote is unchanged by that.) So adding a table to `memory.db` forks:
- **Bump to 2** and every older Zikaron **refuses to open the store** — correct by the stated contract,
  and a breaking change for anyone running two versions against one project.
- **Do not bump**, on the grounds that the table is purely additive and no older code path queries it —
  which requires `schema.md` to say so explicitly, because silence plus a stated exact-match rule reads
  as the first option.

Decide it in the brief, write it into `schema.md`, and **do not let the first migration this project has
ever performed be settled by whichever line of code gets written first.**

**Decided: do not bump.** `schema.md` §"Additive tables and the version gate" now carries the rule and
its reasoning; the one-line version is that the version gates *compatibility*, and a table no older code
path reads or writes leaves every older read and write exactly as correct as it was. What the decision
obliges is that `knowledge_bases` has exactly **one** creation site and that site is idempotent: the
registry's own open runs `CREATE TABLE IF NOT EXISTS`, and the table is deliberately **not** in
`ddl.FIXED_STATEMENTS`. A second creation path for fresh stores would buy nothing — the registry needs
the idempotent one regardless, for every store predating the table — and would give the two copies room
to disagree. It is also what makes the final done-when clause below true by construction rather than by
test: the memory store's open path is not touched at all.

**No encoder dependency, which is why this milestone can precede M23.** `embed_dim` is already a
configuration key (`embedding.embed_dim`, resolved through `EffectiveConfig`), so seeding `meta` and
creating `chunks_vec` at a fixed width needs no model load and no `fastembed` import — the cost M17
measured at 1,059 ms and moved off the critical path.

~~The CLI ships as a **console script**, matching the existing pattern and for the reason
`pyproject.toml` already records: a console script's shebang pins the interpreter Zikaron is installed
into.~~ **Withdrawn, on the grounds it cites.** The reason `pyproject.toml` records for its two console
scripts is that *a config file has to name the command by one absolute path* — a hook entry's `command`
and an `mcpServers` entry's `command`. Nothing names this CLI in a config file. It is run by a person,
which is `zikaron.install`'s own recorded argument for **not** being a console script: `python -m` names
the interpreter whose Zikaron owns the store, and an ambient name on `PATH` obscures exactly that. §9,
which is normative here, already spells `python -m zikaron.knowledge`, and that is what ships.
*(**Overturned at M30, by a premise this argument did not have.** "An ambient name on `PATH` obscures
which interpreter owns the store" is still true — but under `uv tool install`, the recommended
acquisition since M28, **no interpreter is on `PATH` at all**, so the `python -m` form is the one a
user cannot reach. Both now work: `zikaron knowledge` is the front door, and `python -m` remains for
the several-virtualenvs case this paragraph was written about.)*

CLI only: `add`, `list`, `remove`, `rename`, `status`. Registry-first ordering for both `add` and
`remove`, with the interrupted states §8.4 specifies. Name lower-casing and uniqueness. `add`'s path
validation (§8.6) including the `rev-parse` probe for `git_mode_effective`. Orphan and absent-database
reporting.

**Every knowledge base reports `state: reindex_required` at the end of this milestone**, because nothing
indexes yet. That is a coherent state the design already specifies, not a placeholder.

**Invariants:** 11, 14, 15. **Done when:** a KB survives create → rename → list → remove with the file
appearing and disappearing; `remove(name="../memory")` is impossible to express, verified by a test that
tries; an interrupted `add` (kill between registry commit and file creation) leaves a KB that `list`
shows as `reindex_required`; an interrupted `remove` leaves an orphan that `status` reports and search
never opens; two KBs differing only in case collide on the `UNIQUE` constraint; a store predating the
migration opens and answers normally.

**Also lands here:** `design/knowledge-index.md` becomes **normative**, and `CLAUDE.md`'s design-document
table gains its row. **Both done, on operator sign-off.** The split of authority that follows, since two
documents now describe one file: `design/schema.md` owns `memory.db`'s tables including the registry,
`design/overview.md` owns every memory-store decision, and `knowledge-index.md` owns the rest of the
index. **D1 was amended in the same sign-off** — the separate system it delegated to is now Zikaron's
own, and what `remember` accepts is unchanged.

**Fence:** no walking, no chunking, no search. Creating and tracking corpora only.

---

## M21 — Discovery, filtering, and change detection

Normative: §4.1, §4.2, §5.1–§5.6, §6.2, §6.3, §6.4, §7.5 (the `pending` half), §8.5's skip breakdown.

The walk: directory pruning before descent, symlink refusal, `.gitignore` via batched `check-ignore`
under `all`, globs, size cap, and text detection **at first read** rather than at walk time. The
`files` table with `content_hash`, `git_blob_hash` and `size`. The two-phase scan: walk phase computes
the changed set and replaces `pending` wholesale, writing `last_walk_completed_at`; index phase disposes
of each path by one of the three disposals. Per-KB advisory lock, taken even though the indexer still
runs in the foreground of the CLI invocation — **with same-host pid reclamation, which belongs here
rather than with the rest of the lock machinery**: the lock exists from this milestone, so a process
killed mid-scan would otherwise leave a knowledge base with no way back until M23 lands. Cross-host
reporting and `--force-unlock` stay in **M23**, where the state machinery they report through exists.

**The indexer is a separate entry point from the first line of code** — invoked synchronously here,
detached in **M23**. Same module, different invocation; M23 adds spawning and progress, not a rewrite.

**Throughput is measured here and recorded**, sizing K8's separate-process argument against the ~124 s
modelled in §6.1: wall time, peak RSS, the binary-with-unknown-extension fraction that decides
§16 item 9, and — added by M19 spike B — **the fraction of a real repository that sits under a
`.gitignore`d directory which §4.1 step 1's fixed prune list does not already name**, which is the
number §16 item 11 needs to decide whether `check-ignore` should prune directories during the walk.
Three deferred questions, one walk; a session working this brief must take all three numbers, because
each item defers its decision to *this* measurement and none of them can be answered later without
re-walking.

**Invariants:** 1, 2, 4, 5, 12. **Done when:** a scan over a fixture repo produces the expected `files`
rows with no `.git` contents and no pruned directories; a submodule, a sparse checkout and a linked
worktree all behave as §5.6 states; a file that grows past the cap is deleted from the index on the next
scan; killing the indexer mid-scan leaves `pending` non-empty and the next scan completes; every skip
reason in §8.5 is reachable and counted; the git fast path and `git_mode = off` agree on a clean tree.

**Fence:** no chunking, no embedding, no search. The `files` table and its maintenance only.

**Landed 2026-09-15, APPROVED after five review rounds** (`reviews/m21-scan-review.md`), the last
closing with no findings at any tag level. Every done-when clause is covered by a test. The two
throughput questions this brief deferred to the measurement are **closed negative** in
`research/m21-scan-throughput.md` — the remembered-skip memo is not built (1 binary-with-unknown-
name file in 2,491) and directory-level `check-ignore` pruning is not adopted (4.81% and 0.00%,
with the larger repository's `.gitignore` naming directories the fixed prune list already carries).
Its timings are upper bounds taken on a loaded machine and are owed a re-run; `FINDINGS.md` carries
that as an explicit OWED item.

---

## M22 — Chunking, both index arms, and search

**COMPLETE 2026-09-15**, APPROVED after seven review rounds; trail
`reviews/m22-knowledge-search-review.md`. Not committed, per the standing rule in `CLAUDE.md`.

Normative: §4.3, §4.5, §4.6, §7.1–§7.4, §7.6, §8.1, §8.3, §8.7, §10; invariants 3, 6, 7, 9, 10, 13, 16.

Paragraph-greedy chunking with line ranges, the budget enforced against the assembled sequence, and the
path prefix applied **at embed time only** so `chunks.text` stays verbatim file content. Both index arms
written in the same per-file transaction (§4.6), with its `pending` delete: `chunks_fts` populated, and
`chunks_vec` populated by the `BackgroundLoadedEncoder` M17 already built, batched at
`knowledge_embed_batch` with **mask-aware pooling**.

Retrieval: RRF over both arms within a KB, results grouped by KB and ordered by whichever quantity M19's
spike C settled, empty groups reported with their state, the per-file chunk cap, the response byte cap
with whole-group dropping and stubs. Snippet assembly with invariant 16's governing property and the
`truncated` flag. Service RPC plus the `zikaron_knowledge_search` MCP tool in primary mode only, with the
tool description §8.3 specifies.

**Both arms land together deliberately, and the reason is invariant 3**: every `chunks` row must have
exactly one `chunks_fts` row *and* one `chunks_vec` row. A lexical-only milestone would ship a store that
violates a normative invariant and an invariant test that cannot pass — so "index the text" and "index
the vectors" are one deliverable, not two. This is the largest milestone here, and splitting it would buy
a smaller diff at the cost of a knowingly-inconsistent store.

**This is the first milestone that ships the capability the operator asked for**: search over indexed
documents that grep cannot reach.

**It inherits an obligation from M21 that nothing else will surface, because the store it produces
is internally consistent.** M21's scan writes `files` rows with `chunk_count = 0` — honestly, since
it has no chunker — and change detection reindexes on a content hash, so a knowledge base built
before this milestone would keep every one of those rows and never gain a chunk. Neither the
encoder-identity check nor any invariant can see it: the encoder matches, `chunk_count` agrees with
the zero chunks present, and `state` reports `ok`. **The lever is the per-KB `meta.schema_version`,
bumped here and given a rule this build does not yet have**: today's open path refuses only a
version *newer* than it supports, so a further `reindex_required` cause — a recorded version older
than the supported one — is what converts the bump into a rebuild. Both halves are this
milestone's, and neither is optional: the bump without the rule changes nothing, and the rule
without the bump fires on nobody.

**Withdrawn on operator ruling, before any of this milestone's code: neither half is built here.**
Nothing is deployed anywhere, so the only knowledge bases in this state are a developer's own, and the
remedy for one is `remove` followed by `add` rather than a migration lever built for a population of
one. Building the lever now would also make its first real exercise the *second* time it is needed,
which is the worse of the two orders to learn a migration path in. **What is owed instead is stated
rather than closed:** the open path still refuses only a version newer than it supports, so the first
schema change made after this build ships is the one that has to carry both halves — the bump and the
older-recorded-version `reindex_required` cause — and it inherits this paragraph's argument for why.
The reasoning above stands as written; only its conclusion moved.

**The §12 counters are not written here either, and that is M24's brief rather than an omission.**
`searches`, `searches_empty`, `results_returned` and `results_stale` are seeded at creation and
reported by `status` already; the best-effort writes that advance them, and the `SQLITE_BUSY`
behaviour they require, belong with the milestone that holds §12.

**Invariants:** 3, 6, 7, 9, 10, 13, 16. **Done when:** `Read(path, start_line, end_line)` returns a
result's snippet byte-for-byte including the no-trailing-newline case, as a property test over a fixture
corpus; a chunk over the snippet cap truncates at a line boundary and flags it; a chunk embedded alone
and in a 32-wide batch produce identical vectors; a killed reindex leaves no partial chunk, FTS or vector
state; a group with no matches appears with its state; a response over the byte cap drops whole groups
and sets `groups_dropped`; the consolidator mode cannot name the search tool.

**Fence:** no management tools over MCP, no detached indexing, and **no fusion tuning** — `rrf_k`,
`fusion_depth` and arm weighting are `meta` keys belonging to M25. Do not sweep here.

---

## M23 — The detached indexer, progress, and the repair paths

Normative: §6.1–§6.4, §8.4's repair rules, §8.5's state machinery, §11 in full, §9's `--force-unlock`;
invariants 8, 12.

The indexer detaches and outlives its invoker. Progress to `meta` after each file transaction;
`files_remaining` from `COUNT(pending)` under the `last_walk_completed_at` rule; the full `state` enum
with its precedence; search serving committed state with `state: "indexing"` while a build runs. Crash
recovery with `pending` surviving deliberately.

**The encoder-mismatch repair belongs here rather than with the dense arm**, because it is a recovery
path and shares this milestone's machinery: the state-based trigger, the one-transaction drop and
recreate at the new dimension — which records the identity about to fill the corpus as it goes, so
`meta` never describes vectors other than the ones stored — and the
`refresh full=true` semantics that are an ordinary scan with change detection bypassed rather than a
discard and rebuild.

Cross-host lock reporting and `--force-unlock` with its same-host-live refusal; the remaining §11 rows —
orphans, absent and unreadable databases, an unreadable registry.

**Invariants:** 8, 12. **Done when:** a search during a build returns committed files and reports
`indexing` with a falling `files_remaining`; `files_remaining` is `null` during the walk phase and a count
after it; a killed indexer leaves a reclaimable lock and surviving `pending` rows served as stale;
changing `embed_model` puts the KB into `reindex_required` and it refuses to serve until a refresh
completes; killing that repair leaves it still refusing and the next scan completes it; a foreign-host
lock is never auto-reclaimed and `--force-unlock` clears it while refusing a live same-host one.

**Fence:** no new retrieval behaviour. Lifecycle, state and recovery only.

---

## M24 — The MCP management surface

Normative: §8.2, §8.4, §8.5, §12.

`add`, `remove`, `rename`, `refresh`, `list`, `status` as MCP tools alongside `search` — twelve tools
total on the primary server. Tool descriptions written to the occasions standard §8.3 sets, which is this
project's measured position rather than a style preference: Amazon Q ships a 25-word description stating
what its tool *is* and never when to reach for it, and its own documentation makes the human the trigger.
The four §12 counters, written best-effort and abandoned on `SQLITE_BUSY`.

**Probe before building:** twelve tools on one server is new here, and M16 measured that tools arrive
deferred under Claude Code. Confirm the tool list is delivered whole and the descriptions are not
truncated, before writing six more.

**Three things this milestone inherits, all deliberately deferred rather than forgotten.** The search
tool's description was shipped *without* §8.3's sentence pointing at `zikaron_knowledge_list`, because
a description that names a tool the server does not register is the defect §8.4 records in a
comparable product; restoring that sentence belongs to the change that makes it true, which is this
one. The README still documents no way to create a corpus, which is why it does not mention one —
the management tools and the `knowledge/` directory they produce are documented here, in the
milestone that makes a corpus reachable without leaving the harness. And **`refresh` still requires a
name, in both surfaces**: §8.4's `refresh(name=None)` — every knowledge base, each one's lock checked
on its own and `already_indexing` reported per corpus rather than failing the call — belongs to §8.4,
which is normative here and was not in M23. §9's CLI block already spells the optional form, so this
milestone makes the CLI match it as well as adding the tool.

**Invariants:** none new. **Done when:** an agent creates, fills, searches, renames and removes a KB
without leaving the harness; `remove` without `confirm` fails and says what would be destroyed; `refresh`
under a held lock reports `already_indexing` rather than queueing; `refresh` with no name reaches every
knowledge base and reports per corpus; the consolidator mode registers none of
the twelve; counters advance, and a `SQLITE_BUSY` during a counter write does not delay a query.

**Fence:** `--force-unlock` stays CLI-only, per §8.2's stated exception.

---

## M25 — Dogfooding, and the parameters this design deliberately did not tune

Normative: `FINDINGS.md` open questions 1–3 and §16 items 1–3 of the design.

Install into a real corpus — the operator's own mirror-tree `.md` knowledge is the intended first
subject — and use it. Then run the sweep the design has been deferring since it was written:
`rrf_k`, `fusion_depth` and arm weighting against ~22,800 chunks rather than the 187-record benchmark
they were chosen on, with the identifier-versus-prose split that FINDINGS open question 8 measures at
0.194–0.233 and AWS's own guidance corroborates.

**The measurement discipline is this project's, not a new one**: name the quantity before quoting a
number, preregister the decision thresholds, and record what did not replicate.

**`limit_per_kb`'s default is one of the parameters in scope, and its crossing point is already
measured** — start from the number rather than re-deriving it. Over five real trees at the shipped
defaults, a search across three corpora fits (19,764 payload bytes of 24,000) and the **fourth**
corpus is where the response cap begins dropping whole groups; one result serializes to roughly
950–1,374 bytes on prose. Harness, re-runnable in one command: `experiments/m22_response_cap.py`.
An earlier figure putting that crossing at the third corpus was taken while the cap double-counted
the transport's two copies, and is withdrawn in place in `FINDINGS.md` — do not tune against it.

**The tool descriptions are in scope as a budget, and the measurement that decides it is the
operator's.** The primary server's `tools/list` answer is **18,594 bytes over twelve tools** —
14,971 of it descriptions, mean 1,248, and skewed: `zikaron_knowledge_search` 2,498,
`zikaron_knowledge_status` 1,982, `zikaron_knowledge_add` 1,891, against 457 for the smallest.
Harness, re-runnable in one command: `experiments/m24_tool_list_size.py`.
**What that does not establish is the cost**, which is why the number above is a size and not a
verdict: what a description costs is context-window occupancy on every turn of every session, and
that is read with a context inspector against a real session rather than computed from bytes. The
operator takes that reading; this milestone starts from it.

**The seam to cut on, if the reading says cut: *when to call and what to pass* stays, *how to read
what came back* goes.** Measured on the three largest, the second category is 1,210 of 2,498 bytes
in `search` (empty-group semantics, the five `state` values, `snippet`/`truncated`/`stale`/
`groups_dropped`), 1,252 of 1,982 in `status` (a field glossary — `files_seen` against
`files_indexed` against `files_skipped`, partials-versus-totals, `lock.live`, `orphans`), and 365
of 1,891 in `add`, whose bulk is *input* semantics and belongs where it is. That is ~2,827 bytes,
roughly 15% of the whole tool list, describing fields the model cannot see yet — a permanent cost
for information useful in exactly the turn after a call returns, when the result itself could carry
it. A tool result delivers ~29,923 tokens before truncation
(`research/claude-code-mcp-result-truncation.md`), so the transient channel is not the scarce one.

**Two things are not to be cut on size alone, and this is the half a byte count gets wrong.** The
*occasions* paragraphs are the one part of a description this corpus has evidence **for**:
`research/amazon-q-knowledge-integration.md` found the nearest comparable product ships a 25-word
description with no trigger guidance, and the consequence is that a human is the trigger — the
agent never reaches for it unprompted — while the neighbouring `todo_list` spends 78 words on
triggers. Our own recall moved 10 → 188 searches after a prose change, with that entry's stated
attribution caveats. And `zikaron_knowledge_search`'s 188-byte untrusted-reference paragraph is the
poisoning boundary. Cutting either is the change most likely to read as a clean win and quietly
stop the tools being used.
**Unmeasured, and named as such so it is not quoted as a finding:** whether a model choosing among
twelve tools chooses *worse* when each carries 2,500 bytes. That is an attention argument, nothing
in this corpus measures it, and it should not be used to justify the cut on its own.

**Invariants:** none new. **Done when:** a research note reports search-per-session use on a real
corpus, the empty-group rate from the §12 counters, and the swept parameters with the evidence for
each; any parameter moved is moved in `meta` with a stated reason; §16's open questions are each
either closed with a measurement or restated with what is still missing; and the description budget
is either cut against a context reading, or left with the reading recorded as the reason.

**Fence:** no new capability. Measurement and tuning only — and a description cut is prose, so it
moves in lockstep with the design's block quotes and the parity tests that compare them.

---

## M26 — Rerank the pull path, because retrieval finds the document and picks the wrong passage

Normative: `design/retrieval.md` §"Reranking" and **D23**, whose rejection is scoped to the *push*
path and which says in terms that the pull path is **not** rejected. Knowledge search is the pull
path. `knowledge-index.md` §7.2 (within-KB ranking) and §16 items 1 and 7.

### Why this, and why it is not more measurement

M25 measured the shipped configuration on 150 mechanically-labelled conceptual queries against
2,720 chunks of CockroachDB RFCs, and **no configuration of `rrf_k`, `fusion_depth` or an arm weight
beat it by enough to move** (`research/m25-fusion-sweep.md`). What it also measured is that the
absolute quality is poor, and **where** it is poor:

| outcome on the shipped config, post-cap top 5 | share |
|---|---|
| right section returned | **39%** |
| **right file, wrong section** | **28%** |
| right file not retrieved at all | **33%** |

**The 28% is a ranking failure inside a document retrieval already found, and a cross-encoder is the
standard fix for exactly that shape.** The 33% is an embedding or query-construction problem and is
**not** this milestone. Tuning cannot reach either: M25 showed the fusion parameters are flat on
this family, and the two query classes want opposite arm weights, so no constant serves both.

**No new dependency.** `fastembed 0.8.0` already ships `fastembed.rerank.cross_encoder.TextCrossEncoder`;
`Xenova/ms-marco-MiniLM-L-6-v2` is 80 MB, with `jinaai/jina-reranker-v1-turbo-en` (150 MB) and
`BAAI/bge-reranker-base` (1.04 GB) as alternatives. Verify the list with
`TextCrossEncoder.list_supported_models()` rather than trusting this line.

### What ships

A reranking stage in `core/knowledge/search.py`, applied to the fused candidate pool **before**
§7.3's per-file cap — the cap must act on the final order, not on an order the reranker then
rewrites. One new configuration key, **off by default until the bar below is cleared**, declared in
`schema.md`'s table like every other key.

### Decisions to settle before any code, and record with reasons

1. **Where the model is loaded, and by whom.** D22 forbids the hook loading an embedding model and
   §6.1 protects the search path's latency. A cross-encoder is heavier than the encoder. It belongs
   to the service, loaded once; a per-search load is disqualifying and must be shown not to happen.
2. **Whether the key is per-KB `meta` or read from configuration at search time.** M25 recorded
   that §10's own stated criterion — *does it describe how the index was built?* — puts search-time
   keys in the second group, and that `rrf_k`/`fusion_depth` are in the first by an argument that
   does not apply to them. **A reranker model changes no stored bytes.** Do not repeat that mistake:
   this is a search-time key.
3. **How many candidates are reranked**, and what happens when the pool is smaller.
4. **Degraded mode.** A missing or unloadable reranker model must degrade to today's ranking with a
   line in the log, never fail the search. §11 is the pattern.

### Done when — preregister before the first run, in the M25 pattern

`research/m26-rerank-preregistration.md`, written before any number exists, fixing the metric, the
query set and these thresholds. **The bar is deliberately 2.5× M25's 0.02**, because a model load
and hundreds of milliseconds must buy something *visible*, not something *detectable*:

1. **hit@5 on the `heading` family improves by ≥ 0.05 absolute** over the shipped configuration,
   with a 95% paired-bootstrap CI excluding zero.
2. **Added latency ≤ 250 ms at p50** for a five-corpus search, measured on the machine and reported
   with its load average, not asserted.
3. **No family regresses** by more than 0.01 — the span families included, since a reranker that
   improves conceptual queries by wrecking exact-phrase lookup is not an improvement.

**Miss any of the three and it does not ship**: the key is not added, §16 gains the negative result,
and the note says so. That is an acceptable outcome and naming it here is deliberate.

### The instrument already exists — this is a re-run, not a project

Everything M25 built is reusable and is the reason this is a day rather than a milestone-sized dig:

```
# 1. corpus  (~6 min; identical to M25's — same commit, same command, same 20 non-markdown chunks)
git clone --depth 1 --filter=blob:none --sparse https://github.com/cockroachdb/cockroach <c>
cd <c> && git checkout 13cb3eb27674b4a981e5c526d04c2387e81efd0b && git sparse-checkout set docs/RFCS
.venv/bin/python experiments/m25_build_sweep_corpus.py <c>/docs/RFCS <store> cockroach_rfcs
# 2. oracle + baseline: m25_fusion_sweep.py's build_queries(), heading family, 150 queries, seed 20260918
.venv/bin/python experiments/m25_fusion_sweep.py <store> cockroach_rfcs 150
```

`experiments/m25_fusion_sweep.py` carries the query builder, the filtered-ranking exclusions, the
paired bootstrap and the per-file cap mirror. `experiments/m25_verify_note_figures.py` checks every
published figure against the committed run — **extend its `SOURCES` to M26's note**, or it silently
covers only M25's.

### Traps M25 paid for, listed so M26 does not pay again

- **Preregister the *quantity*, not only the threshold.** M25 fixed 0.02 on a pooled metric later
  measured invalid; 48 cells cleared the bar as written. Fix what the number is a number *of*, and
  fix what makes a query family admissible, before the families exist.
- **Measure the instrument before measuring with it.** Seven harness corrections were needed, each
  with a symptom already visible in the harness's own output.
- **A mislabelled output field is a false claim with a number attached** — one sent a review round
  into a wrong blocker.
- **`heading` scoring requires the exclusions** M25 built (the holding chunk, and same-titled
  sections' heading chunks). A reranker will rank the holding chunk first on every query if it is
  not excluded, because it contains the query verbatim.

### Fence

Reranking only. **Not** the 33% — no embedder change, no query rewriting, no chunking change; each
is its own milestone and each has a measured share of the failure now. No change to `rrf_k`,
`fusion_depth` or arm weighting: M25 closed those.

---

## M27 — Widen the supported Python range, behind a version seam

**Every `file:line` below was read against the tree as it stood before this milestone, and the
milestone's own edits move many of them.** Locate by the name beside each number, which is why both
are given. **The `main.py` citations moved twice** — once when its docstring grew, then again when
the startup log line was reordered — so the numbers there were stale, corrected, and stale again
within the hour. Where that happened the number has simply been dropped in favour of the name. This
note is not an apology; it is the argument against citing a line into code the same change edits.

Normative: `design/coding-standards.md` §1 (structure), §6 (dependencies) and §9 (the check gate) —
**§6 and §9 are this milestone's normative output and it writes both**; `design/architecture.md`
§"Idle self-stop", which owns the socket-unlink sentence this changes the meaning of.
Measurements: `research/python-portability-probes.md`. Prior art:
`research/python-distribution-portability.md`, `research/python-313-314-porting-audit.md`.

`requires-python = "==3.12.*"` becomes `>=3.12`. The **floor** is real and stays — the package uses
PEP 695 syntax at **18 sites across 10 modules**. The **cap** had no recorded rationale anywhere in
the corpus, and D19 only ever said "latest stable versions", so it was development convenience that
hardened into a distribution constraint. **It was also hiding two defects, both found within an hour
of lifting it**, and that is this milestone's justification. Not reach, and **not** cheapness:
supporting a range is the *expensive* choice, since it buys a seam, a matrix and a porting audit
every October, where shipping a single managed interpreter would buy none of them and pin SQLite for
free. It is worth paying because a cap is a way of never finding out.

**The two differences, and why they are unequal.** `asyncio.Server._active_count` became a
`_clients` set in 3.13; `RunningServer.close_all_connections` read it in three places — its loop
condition and both `ShutdownTimeoutError` messages — and 18 tests go red. That one is **loud**,
and the existing gate finds it the moment the cap lifts. 3.13 also added `cleanup_socket` to
`create_unix_server`, **defaulting to `True`**, so a Unix server now unlinks its own socket file on
close; `serve`'s `start_unix_server` call passed no such argument and took the new default. That one
is **silent** — it
passed 2,847 tests — and it is the one that says the gate alone is not a sufficient instrument here.

**And the silent one was already written down, which is the more useful half of that story.**
`tests/test_service_main.py:555–558` states the 3.13 default, what it would do to the assertion
beneath it, and that *"`pyproject.toml` pins `==3.12.*`, so the guard holds as long as that pin
does"* — a correct, dated prediction of exactly this milestone, sitting in a test comment that no
sweep would surface because nothing reads test comments looking for the consequences of a pin.
Knowing a thing and having it *reachable* are different properties, and only the second survives a
session boundary.

### What "supported" means, and what §6 says

**§6 gains these five propositions.** They are the milestone's normative output, so they are stated
here rather than delegated:

1. **Floor `3.12`, no cap.** PEP 695 syntax at 18 sites across 10 modules is the floor's reason.
   `research/python-distribution-portability.md` §4 carries the argument against reintroducing a cap:
   a cap makes a resolver backsolve to older, possibly-broken releases instead of failing
   informatively.
2. **"Supported" means "tested", and "tested" means the minors `check-matrix.sh` runs** — today
   3.12, 3.13, 3.14. There is no second, looser sense of the word **as applied to a Python version**;
   D34 and `design/harness.md` use "supported" of *harnesses*, which is an unrelated sense.
3. **Every stdlib difference between tested minors lives in `zikaron/service/asyncio_compat.py`, as
   one row per *behaviour change*, keyed by the minor that introduced it** — not one row per
   supported minor. Lookup is the greatest key less than or equal to the running version. So today
   the table has two keys, `(3, 12)` and `(3, 13)`, and 3.14 resolves to the `(3, 13)` row rather
   than duplicating it. **The key set is a function of CPython's history, not of what we test**,
   which is why no drift test ties it to the matrix list: a minor that changed nothing gets no row,
   and that is the correct data model rather than an omission. **Nothing else under `zikaron/` — nor
   under `tests/` — reads the running version**, which done-when 3's scan covers and which this
   proposition must say, since as §6 text it is what a reader will believe. A difference in a stdlib
   module *other* than `asyncio` is a recorded decision about where the seam widens, not a second
   compat module appearing by itself.
4. **A minor newer than the matrix is installable and untested.** `>=3.12` means pip will install on
   3.15 the day it ships, and the brief chooses this behaviour deliberately: the seam applies its
   **newest row**, so a further private-API move fails loudly at the first shutdown rather than
   being masked by a fallback. A startup refusal was rejected — it is the cap this milestone removes,
   wearing a different hat. Adding a minor to `check-matrix.sh` is what makes it supported.
5. **Deprecations are errors in the matrix only**, never in `pyproject.toml` and so never in
   `check.sh`. **The reason is the interpreter, not the dependencies.** *(As built, narrower than this
   first read: the pin is on **direct** dependencies only, and §6 now states that limit — a transitive's
   release reaches any virtualenv on its next build, pin bump or not. The interpreter reason stands on
   its own and is the one that ships.)* What makes the local gate the wrong home is that it runs
   **one** interpreter: a
   deprecation raised only on a newer minor is invisible there whatever the filter says, and
   error-on-deprecation belongs where the interpreter varies. *(The decision was taken on the weaker
   "a dependency release must not redden the gate" framing. That framing is wrong for two reasons, not
   one: the pin covers only direct dependencies, so a transitive release does reach a virtualenv on its
   next build. The decision stands on the interpreter reason alone.)*

### The seam

**One stdlib-only module, `zikaron/service/asyncio_compat.py`, holding each difference as data.**
This is the discipline `CLAUDE.md` already states for `zikaron/harness/`, where the words are *"the
one seam, stdlib-only, where a harness difference is allowed to live"* and *"Add a harness difference
**there**, as data, never as a branch downstream of it"* — the same rule, applied to a second axis.
The shape is **a table keyed on `sys.version_info[:2]`**, consulted by two functions:

| function | 3.12 | 3.13, 3.14 |
|---|---|---|
| `attached_connection_count(server)` | `server._active_count` | `len(server._clients)` |
| `unix_server_kwargs()` | `{}` | `{"cleanup_socket": False}` |

`unix_server_kwargs()` must be a **function returning a fresh mapping**, never a shared module-level
dict a caller could mutate; and its 3.12 row is `{}` rather than `{"cleanup_socket": False}`, because
the parameter does not exist there and passing it raises `TypeError`. *(`FINDINGS.md` once stated that
value unconditionally and now carries the correction with a withdrawal note.)*

**"As data, not as a branch" is mechanical here, not stylistic, and it was measured in this
repository.** `pyproject.toml` fixes `python_version = "3.12"` for mypy, and mypy evaluates
`sys.version_info` comparisons against that value during semantic analysis, skipping the losing block
**without** a `warn_unreachable` report. A probe with a deliberate type error in each position, under
`strict` plus `warn_unreachable`:

| construct | mypy, `python_version = 3.12` |
|---|---|
| error inside `if sys.version_info >= (3, 13):` | **not reported** |
| error inside the matching `else:` | reported |
| errors in **both** rows of a keyed table | **both reported** |

So a version *branch* would ship the 3.13+ row un-typechecked on all three matrix interpreters, and
an unused `type: ignore` inside it would go unreported too. **No version branches inside the seam
either** — the table is the mechanism. `[tool.ruff] target-version` and mypy's `python_version` both
**stay at the floor**, `py312`/`3.12`, so the strictest row keeps being checked.

**Named for `asyncio`, deliberately.** §1 forbids `utils.py`, `helpers.py` and `common.py` because
such names attract whatever has no home, and a module called `compat` is the same trap with a
technical-sounding name.

**`cleanup_socket=False`.** The alternative — accept the new default — leaves the Python minor a live
variable in the socket lifecycle, which is the one thing this milestone exists to remove. It also
forces a rewrite of `main.py`'s *"the socket is unlinked exactly once — by whichever self-stopping
task fired"* into a version-dependent claim, and three neighbouring comments reason from that
sentence. `False` keeps it true.

### The contract nobody pinned

Today's tests assert `not sock_path.exists()` **after** shutdown — `test_service_lifecycle.py:60,98,147`,
`test_service_main.py:92,203,559,723`, `test_service_encoder_failure_stop.py:56,76`,
`test_service_lifecycle_integration.py:851` — an end state that is **identical on 3.12 and 3.13
whoever performed the unlink**, which is precisely how the change walked through 2,847 passing tests.
The new test asserts the **mechanism**: a server started through **`server.serve`, the product's own
path**, and closed through `shut_down()` **leaves its socket file on disk**, on every minor the matrix
runs. Through `serve` rather than by calling `asyncio.start_unix_server(**unix_server_kwargs())`
itself, because the latter passes with `serve`'s own call unchanged and so guards nothing. It fails on
3.13+ without the seam, and that is what makes it worth writing.

**Verify both guards by mutation before trusting either** — M14's practice, whose measured
justification is that the gate was green while something material was wrong three separate times.
The oracle for `attached_connection_count` already exists and can be named rather than designed:
`tests/test_service_server.py::test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered`.
**The mutation is of the seam row to a constant `0`, and where it fails depends on this
milestone's own other edit.** Once `:148`'s precondition poll goes through the seam — which done-when 3
requires, since it reads the private counter directly today — a zero row makes the `for … else` at
`:147–152` exhaust its turns and raise *"the server side never attached the accepted transport"*
**before `shut_down_task` is created at `:174`**. So the failure to expect is an `AssertionError` there,
**not** a `ShutdownTimeoutError`. The other valid form — mutating the **caller** in
`close_all_connections` to `len(self._connections)` — passes the poll on a correct row and fails later:
the loop at `server.py:322` never enters, nothing is cancelled, and `shut_down`'s bounded
`wait_closed()` raises `ShutdownTimeoutError` at its 5 s deadline. Both fail the same test, which is
why it is the oracle for both. **Reading the outcomes**: a green run means the mutation did not take;
a *timeout* rather than an `AssertionError` under the **row** mutation means `:148` is still reading
the private counter directly — the poll passed on the real count and handed the zero row to
`close_all_connections`, which is the pre-milestone mechanism — so done-when 3's edit to that line has
not landed. An `AssertionError` at `:152` under the **caller** mutation means the row was mutated
instead of the caller. *Which* timeout the caller mutation surfaces is not a signal: `shut_down`'s own
5 s deadline and the test's own final `wait_for` start within microseconds of each other, and the
measured run here was won by the test's, producing a bare `TimeoutError`.
**The poll goes through the seam rather than being re-targeted at something seam-free**
(`handler_started`, set inside the same window at `:128`, would also work): through the seam it
exercises the row against a raw `asyncio.Server`, which is the exact shape production hands it.
*(Not "mutate it to `len(running._connections)`": `attached_connection_count` receives an
`asyncio.Server` and cannot see the `RunningServer`'s own set, so that mutation is not expressible in
the function it would test.)*

### The matrix, and its contract

`./check.sh` keeps its **default-invocation** behaviour byte-identical and gains **one behavioural
change** — its
hard-coded `venv=.venv/bin` becomes `venv="${ZIKARON_VENV:-.venv}/bin"` — plus the two header-comment
sentences done-when 11 names, which change no behaviour. That is what lets the matrix reuse the
one gate instead of copying it — and copying it is the trap, since `tests/test_check_gate.py` polices
`check.sh`'s `--cov` package list and a second script would put that list in two places, which is the
two-sites failure this corpus keeps recording.

`check-matrix.sh` then:

- iterates the minors **3.12 3.13 3.14**, fixed in the script rather than read from the environment,
  resolving each as
  `python3.<minor>` on `PATH` — `uv python install` puts exactly such shims there, which is how "names
  interpreters rather than requiring uv" and "uv in practice" reconcile. *(As built, three sources in
  order: the override, then `uv python find --managed-python --no-project`, then `python3.<minor>` on
  `PATH` as a last resort. `uv python install --no-bin` deliberately puts **nothing** on `PATH` — the
  shim this bullet expected is exactly what pointed every matrix virtualenv into a `/tmp` session
  directory, so the reconciliation it describes was the hazard.)* **A per-minor override
  `ZIKARON_PYTHON_3_13=/path/to/python` names a path only; nothing in the environment can add or drop
  a minor**, or done-when 9's drift test would be parsing a list the environment could silently
  change;
- creates `.venv-matrix/<minor>` with `-m venv` and `pip install -e '.[dev]'` when absent, and reuses
  it while a stamp of `pyproject.toml`'s hash **and the base interpreter's `realpath`**, written only
  after a successful install, still matches
  — rebuilding rather than installing over when it does not, since `pip install -e` never removes a
  dependency the file has stopped declaring *(as built; the brief originally reasoned from exact
  pinning, which covers upstream arrivals and not our own changes failing to arrive. The interpreter
  half was added at code-review round 10: without it, repointing `ZIKARON_PYTHON_<minor>` at a
  different build of the same minor kept the existing venv and reported green for an interpreter that
  never ran — and SQLite, which no seam can absorb, comes with the interpreter)*;
- runs, per minor, `ZIKARON_VENV=.venv-matrix/<minor>` with `PYTEST_ADDOPTS` and `PYTHONWARNINGS`
  both set to error on deprecations, invoking `./check.sh` — pytest reads `PYTEST_ADDOPTS` natively,
  so the filter needs no second copy of the gate; **`PYTHONWARNINGS` is there because the pytest
  filter is applied in-process and does not reach the service, hook and MCP processes the integration
  tier spawns** *(added as built, after a review round; measured not to disturb `mypy --strict` or
  those spawning tests)*;
- fails on the first red minor, naming which — and **no interpreter from any of the three sources is a
  red minor, never a skip**, or a machine carrying only 3.12 would satisfy the milestone rule with one
  interpreter, which is the hole `conftest.pytest_runtest_makereport` already closes for the integration
  tiers;
- **checks that `.venv-matrix/<minor>/bin/python` reports the minor it is labelled with, before anything
  is installed into it**, and refuses naming the remedy otherwise *(as built, after a review round: a
  wrong override or a stray shim would otherwise run one version under another's name and report green
  for a version that never ran)*;
- **takes `--parallel`, which runs every tested version concurrently** *(as built, on operator
  request: ~3.5 minutes warm against roughly nine sequential)*. Each version gets its own coverage
  file and tool caches through `ZIKARON_CACHE_SUFFIX`, which `check.sh` reads and which defaults to
  empty so a plain `./check.sh` writes exactly the paths it always did; `.gitignore` gained trailing
  wildcards, without which those per-version paths are untracked-but-not-ignored and every parallel
  run fails on its own tree-identity guard. Virtualenv preparation stays sequential, since an
  editable install writes one `zikaron.egg-info/` that concurrent installs would race;
- **stops every process it started on `INT`, `TERM` or `HUP`** *(as built, after three review rounds)*.
  Bash starts `&` jobs with SIGINT **ignored**, so a Ctrl-C would otherwise leave every gate running,
  and the next run would merge an orphan's coverage into its own. Processes are found by a token in
  their environment rather than by walking parent links: a group-delivered `TERM` or `HUP` kills the
  intermediate shells first, after which `timeout` and `pytest` have no ancestry to walk — measured,
  six orphans survived a descendant walk and none survives the token. The handler kills before it
  prints anything, which is not cosmetic: a hangup is generated *by* the terminal going away, so the
  first write to stderr fails, and under `set -e` a handler that announced itself first exited
  having killed nothing — measured with `/dev/full` standing in for the hung-up pty, nine surviving
  processes against zero. `check.sh` additionally erases `${COVERAGE_FILE}.*` fragments before its
  gate whenever the suffix is set, so a run killed outside the trap cannot lend its data to the next;
- **prints a tree identity on its last line** — `HEAD`'s short hash alone when the tree is clean,
  otherwise `HEAD+<12 hex>` over every difference from `HEAD` plus the content of every untracked,
  non-ignored file — **samples it before and after the loop and refuses if they differ** *(as built;
  §9 makes matching identities the condition for per-version runs to count as a milestone gate, since
  three subset runs on three trees are indistinguishable from three on one)*.

**When it runs, stated once here; every site that must say it carries the phrase `additionally
required before a milestone lands`, so one grep returns them all.** *`./check.sh`
is the per-edit gate and remains the definition of done for a change; `./check-matrix.sh` is
additionally required before a milestone lands.* No conditional list — "whenever `pyproject.toml` or
the seam changes" reads tighter but turns a mechanical rule into a judgement call, and the judgement
would be made by whoever least wants to spend the seven minutes. Without this sentence §6
proposition 2 quietly voids itself: "supported means tested" would be true only on the day M27 lands
and never verified again.
**The residual, stated so it is a chosen gap rather than a discovered one**: a commit that is not a
milestone — `89a1e00` is the shape, a fix landed between milestones — is never matrix-gated. Accepted,
because the alternative is the conditional rule above, and because the next milestone to land catches
it before anything ships.

**What the deprecation filter is known to surface, and what it is not.** Measured on 3.14: **14
`asyncio.get_event_loop_policy()` call sites, all in `tests/test_service_main.py`, none in the
shipped package**, deprecated with removal in 3.16 — and **nothing else**, under an all-origins
filter. They are replaced here rather than left to redden the new script on its first run. All 14 sit
inside `async def test_…` bodies, so a running loop exists at each and `type(asyncio.get_running_loop())`
is the drop-in; `asyncio.SelectorEventLoop` is platform-shaped and `DefaultEventLoopPolicy` is itself
deprecated. ~~**3.12 and 3.13 were not run under the filter**, so a third-party deprecation there is
the one way this can still surprise on first execution.~~ *(As built: all three have since run green
under both filters — the in-process one and the exported one that reaches spawned children — and
nothing further surfaced.)*

**Coverage, stated so it is not discovered.** The `(3, 12)` row is unexecuted on 3.13 and 3.14 and the
`(3, 13)` row on 3.12, so `show_missing` lists whatever lines those bodies occupy **on their own** —
none if the rows are lambdas inside the table literal, one or more if they are `def`s — and the matrix
produces three coverage measurements against one `fail_under = 95`. **Accepted, with no pragma**
whichever shape the rows take: a row or two is far inside the measured 96.85–98.12% spread, and a
`# pragma: no cover` would suppress exactly the signal worth having if the seam ever grows a row
nothing exercises.

**Cost, likewise.** Three venvs at roughly 200 MB each — `onnxruntime` dominates — and at least
3 × ~150 s of tests, plus a first-run install per minor. That is the price of the range, and it is
the reason the matrix is not in the inner loop.

**Three interpreters have to come from somewhere**, and `uv` is how this was measured — **one
measured `uv python install`, 1.44 s**, probably cache-warm, and its python-build-standalone builds
were verified here to carry FTS5 and `enable_load_extension` with a real `vec0` query. A `pyenv` or
distro-packaged set works equally, but **uv becomes a development dependency in practice** — worth
stating plainly, because shipping a managed interpreter to *users* was considered and not chosen, and
this brings a piece of that machinery in for *developers* through the back door.

### The definition of done is stated in nine places (seven when this was written)

`CLAUDE.md`, `README.md`, this file's own header, `.claude/agents/memory-researcher.md`,
`design/coding-standards.md` §9 (~~which defines the gate without using the phrase~~ — **false; it
carries the phrase verbatim, which is what this same section's "the grep returns seven" requires
and `tests/test_definition_of_done_sites.py` now pins**), **`check.sh`'s own
header** — *"The check gate. Nothing is done until this exits 0."* — and, once it existed,
**`check-matrix.sh`'s header**, which states the same rule about itself. The brief's own rule is that
a silently incomplete rule is worse than an inconvenient one, so **all seven change**, and the sweep
is over the *claim* — not over the filename. *(Six until `check-matrix.sh` was written; the seventh
is the file the rule is about, which is the easiest one to forget.)* ~~A grep for the phrase returns
nine lines, the seven sites plus this section and done-when 11 — expected, and said here so the next
person counting does not re-derive it.~~ **— no line count is written here; run the grep, and say
which grep you ran.** *Two exist and they are not the same quantity: `additionally required before
a milestone lands` returns the sites that carry the phrase, which is what done-when 3 nominates as
the count; `definition of done` returns a much larger set including every discussion of the rule,
this section among them. Both move with every edit to this corpus.*
*~~The struck sentence was wrong in every part: the phrase returns 29 lines, 19 outside `reviews/`;
it does not occur inside this section's heading; and the second extra `build-plan.md` hit is
done-when 3.~~ **— that correction was itself wrong in all three parts, which is the finding.** It
silently switched to the *other* grep to get its totals; the heading it says lacks the phrase is
"The definition of done is stated in nine places"; and the hit it reassigns is the one in done-when
**11**, exactly where the original put it. *That clause first carried a line number, which was
stale within the same session — the correction's own insertions had already moved the line it
named. **Fourth generation**, and the first three were counts. A line number is a count of lines;
writing one into the paragraph whose subject is that hand-maintained numbers decay is the defect
rather than an instance of it.* **A stale count was replaced by a wrong one,
inside the paragraph whose subject is that hand-maintained counts decay — the third generation of
one defect.** The numbers are gone rather than corrected a third time.* **Three traps in
that grep, each of which costs or adds a site if unstated**: `build-plan.md:5` writes it as
`definition of "done"` **with quotation marks**, so a search for the bare phrase misses it;
`check.sh:2` states the claim in *different words entirely* and no phrase-grep returns it, which is
CLAUDE.md's own find-by-meaning-not-by-match lesson landing on this very sweep.
~~And the grep does return `FINDINGS-archive.md:773`, which **stays as written**, the archive's rule
being that it records what was believed and when.~~ **— struck: the archive carries no occurrence of
the phrase, in the tree or at `HEAD`, and `:773` is a section heading.** Trap three described a hit
that has never existed, while `tests/test_definition_of_done_sites.py` says in as many words that
the archive "currently filters nothing". *Of the two, the guard is the one that ran.*
*Withdrawn in place rather than renumbered, because this brief has landed and because the way it
went stale is the finding. **It is nine sites since M28**, which added `design/distribution.md` §4
and `.github/workflows/check.yml`'s header, neither existing when the seven were counted.
~~both stating the rule in the same words~~ **— backwards, and it matters because done-when 3
nominates a phrase-grep as the authoritative count.** Neither M28 site carries
`additionally required before a milestone lands`: `distribution.md` §4 writes "required before a
milestone lands" without the adverb, and `check.yml`'s header says "`check-matrix.sh` is what a
milestone needs locally". **So the two are different quantities**: the grep returns the sites
carrying the phrase, pinned by name in `tests/test_definition_of_done_sites.py::PHRASE_SITES`,
while the larger set is the sites *stating the rule in any words* — those plus
`design/distribution.md` §4 and `.github/workflows/check.yml`. Name which one you mean before
quoting either, and **write neither number**: they read *seven* and *nine* here until the kiro
mirror gained the gate rule and made them eight and ten, which is the fifth generation of one
count. Reconciling the two sets means adding the phrase to the two M28 sites or accepting that the
grep under-counts by them, and neither has been done. **And trap two is now refuted by the file it is about**:
`check.sh:2` reads "the per-edit gate and the definition of done for a change", so a phrase-grep
does return it. The paragraph warning that a hand-maintained count decays was itself a
hand-maintained count, and both halves decayed within one milestone.*

Two things travel with that edit. **The hermeticity claim becomes false by omission, in two files**:
`CLAUDE.md` §"The check gate" and `check.sh`'s own hermeticity comment carry it near-verbatim — the gate is hermetic and *"nothing is
covered only there"* — and after M27 the 3.13/3.14 rows are exercised only in the matrix, which needs
three interpreters, i.e. machine state, precisely what those paragraphs promise the gate does not
depend on. **Both** gain a sentence naming the matrix as the deliberate exception: what it needs, what
it alone covers, and that `check.sh` itself stays hermetic — **naming the set by reference, *"the
minors `check-matrix.sh` runs"*, never by listing it**, or this milestone's own edit would falsify
done-when 9's "three places". Fixing one file and not the other is this corpus's two-sites
failure committed inside the edit that exists to prevent it.
And **§9 is already drifted, independently of this milestone**: it prints `mypy --strict zikaron`
against `check.sh`'s `zikaron tests`, and `pytest --cov=zikaron/core` against seven `--cov` flags.
Leaving a known-false command line beside a new sentence is the neighbour contradiction this project
keeps paying for, so §9's block is corrected in the same pass and gains `check-matrix.sh` — when it
runs and what it adds.

### Sites that reason from the pin or from the private read

Enumerated by grepping **`3.12.3`** under `zikaron/` and `tests/` only — the same string appears
twenty-odd times in `research/`, `reviews/`, `experiments/` and at `design/schema.md:5`, none of which
is in this count. That grep catches both phrasings the corpus used, *"pinned"* and *"installed"*, where
either word alone misses sites: `zikaron/service/lifecycle.py:75`, `zikaron/service/main.py:326`,
`zikaron/service/server.py:231` and `:270`, `tests/test_service_main.py:556`,
`tests/test_service_server.py:48`. **Six sites, five files.** Every one records a measurement that
stays true, so **only the four saying "pinned" need anything** — the two saying "installed"
(`main.py:326`, `server.py:270`) already name the minor they were measured on, which is exactly what
is wanted, and they change nothing. A measurement offered as universal that was taken on one minor is
the confidently-stale claim this corpus exists to avoid.

Separately, `server.py:254–291` carries **three** docstring paragraphs reasoning about reading
`_active_count` *"directly, once per pass"* with *"`type: ignore[attr-defined]` at every read
below"*, and `tests/test_service_server.py:92–109` repeats that reasoning on the test side. Both are
false once the seam owns the read. And `tests/test_service_server.py:148` reads
`bare_server._active_count` in *code*, so the guard below must cover `tests/` too.

**Invariants:** none new in `schema.md`'s numbered sense. The new guards are ordinary tests.

**Done when:**
1. `requires-python = ">=3.12"`, no upper bound. `[tool.ruff] target-version` and mypy's
   `python_version` stay at the floor.
2. `zikaron/service/asyncio_compat.py` exists, holding both differences as a table keyed by the minor
   that introduced each, with no version branch anywhere inside it, and exposing
   `attached_connection_count(server)`, `unix_server_kwargs()` **returning a fresh mapping** — never a
   shared module-level dict a caller could mutate — and the interpreter version string done-when 10 logs.
   **The row lookup takes the version tuple as an explicit argument**, defaulting to the running one
   *inside* the seam — because proposition 4's "newest row applies" fires only on a minor the matrix
   does not run, and done-when 3 forbids any test from reading `sys.version_info`, so without an
   argument the rule is unfalsifiable. A test then asserts with literal tuples that `(3,12)→(3,12)`,
   `(3,13)→(3,13)`, `(3,14)→(3,13)` and `(3,99)→(3,13)`: no version read, no private name, no third
   allowlisted file.
   **The row *bodies* get no unit test of their own**, and that is deliberate rather than an omission:
   a stub naming `_active_count` or `_clients` would itself trip done-when 3's scan. They are verified
   by the matrix alone, through done-when 4 and 5.
3. **A source-scanning test asserts the seam is the only site.** The mechanism is
   `tests/test_check_gate.py`'s — a regex over file *text*, not `tests/test_hook_stdlib_only.py`'s
   `sys.modules` diff, which sees *imports* and would be blind to an attribute read on a module every
   file already imports. Scope: `zikaron/**/*.py` **and** `tests/**/*.py`. Spellings covered:
   `sys.version_info`, `sys.hexversion`, `sys.version`, `platform.python_version`,
   `from sys import version_info` — and `_active_count` / `_clients`, which the porting audit asks for
   by name and which `tests/test_service_server.py:148` currently violates.
   **Each is a word-bounded pattern — `\b_clients\b`, `\b_active_count\b` — never a substring.** Six
   sites under `tests/` contain `_clients` and read nothing — **four** distinct test names,
   `test_two_clients_racing…` and three `…both_clients…`, two of them quoted a second time in a
   docstring — and `_` being a word character is exactly what excludes them while keeping a
   backticked `_clients` in a docstring *in* scope. Measured: the bare substring matches those six; the
   word-bounded form matches **nothing in the tree today**, since `_clients` only enters with the seam.
   **Being textual has three consequences, all deliberate.** Prose counts, and that is the point: a
   docstring that still explains the private counter by name outside the seam is exactly the drift being
   guarded against, so the rewrites in done-when 7 say *"the private counter"* rather than the
   attribute name. `tests/test_service_server.py:189`'s assertion *message* names `_active_count` and
   is reworded. And **the scanner necessarily contains every spelling it forbids**, so it assembles its
   patterns from fragments rather than literals and exempts itself — the allowlist is
   `asyncio_compat.py` **plus the scanning test**, which is two files, not one.
4. **`tests/test_service_server.py:148` polls `attached_connection_count(bare_server)`** — the decision
   §"The contract nobody pinned" argues for, carried here so it is checkable — and
   `attached_connection_count` returns the same quantity on all three minors, verified two ways before
   the guard is trusted. **By mutating each row** to a constant `0` under an interpreter that selects it
   — the `(3, 12)` row on 3.12, the `(3, 13)` row on 3.13 or 3.14 — and confirming
   `test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered` fails **at `:152`** each
   time. **And by mutating the caller** in `close_all_connections` to `len(self._connections)` once, on
   any minor, confirming the same test fails: the row mutation, now caught at
   the poll, **never reaches the product's seam call**, so this second mutation is the only one that shows
   that call is load-bearing.
   ~~confirming the same test fails with `ShutdownTimeoutError`~~ — **withdrawn on measurement,
   2026-09-20.** It fails, which is what the guard needs, but *which* exception surfaces is a race
   between two 5-second deadlines that start within microseconds of each other: `shut_down`'s own,
   begun when the task first runs during the `:185` await, and the test's `wait_for(shut_down_task,
   5.0)` at the end of the test body. Run here, the **test's** deadline won and the failure was a
   bare `TimeoutError`
   from `asyncio/timeouts.py`, not `ShutdownTimeoutError`. Naming one of them would send an executor
   hunting for a difference that is scheduling noise. **Require only that the test fails**, and
   expect either. **Mutating only the `(3, 12)` row on `.venv` proves the test is sensitive to a
   wrong 3.12 row and says nothing about the row this milestone actually writes** — M14's "universal
   claim proven only by its best-case fixture", the same lesson §"The contract nobody pinned" cites for
   verifying both guards by mutation.
5. **A server started through `server.serve`** — the product's own path, so that what the test proves is
   `serve`'s own `start_unix_server` call passing `**unix_server_kwargs()` — and closed through
   `shut_down()` **leaves its
   socket file on disk**, on every minor the matrix runs. Verified by mutating the `(3, 13)` row to `{}`
   under 3.13 or 3.14 and confirming it fails. **On 3.12 no row can make it fail, so that run is not
   evidence** — and a test that called `asyncio.start_unix_server(**unix_server_kwargs())` itself would
   pass with `serve`'s own call unchanged and guard nothing.
6. `main.run`'s docstring claim that the socket is "unlinked exactly once" **stays true on every minor
   and says the seam is why** — it
   is true today on 3.12 and false only on 3.13+ without the seam, so this is a claim being made
   durable, not repaired. And `tests/test_service_main.py:555–558`'s comment is rewritten to say that
   `cleanup_socket=False` is what keeps `:559` distinguishing `run()`'s unlink from asyncio's, on every
   minor — rather than the pin, which by then is gone.
7. The four `3.12.3` sites that say "pinned" no longer claim one (the two saying "installed" need
   nothing), `server.py:254–291`'s three paragraphs and
   `tests/test_service_server.py:92–109` no longer describe a direct private read, and
   `design/architecture.md` §"Idle self-stop" states the mechanism the design previously left to a
   docstring: the socket is unlinked by this process alone, because the listener is opened with
   `cleanup_socket=False` through the seam, so asyncio's own 3.13+ unlink-on-close never runs.
8. The 14 `get_event_loop_policy()` sites are `type(asyncio.get_running_loop())`.
9. `./check.sh` green unchanged in default invocation; `./check-matrix.sh` green on 3.12, 3.13 and
   3.14 with deprecations as errors; and a test in `tests/test_check_gate.py`'s style asserts the
   minors named in `check-matrix.sh` are exactly the set §6 states, so those two cannot drift.
   **The set is written out in three places and drift-tested in all three**: §6 proposition 2
   (canonical), `check-matrix.sh`, and `README.md:65`. *As built there is a fourth, written after
   this brief: the `uv python install --no-bin 3.12 3.13 3.14` line in `CLAUDE.md` §"Setting up a
   development environment". It is not drift-tested and does not need to be — a stale copy installs
   a subset, and `check-matrix.sh` then refuses the missing version and prints the install command
   regenerated from `minors`, so the failure names its own remedy.*
   `test_check_gate.py` already parses prose by
   fixed sentence (`_STATED_FLOOR`), so extending it to both prose sites is the existing mechanism, not
   a new one. **`.venv-matrix/` is in `.gitignore`**, which today covers only `.venv/` and `venv/`. **§9 does not restate the set** — it says "the minors `check-matrix.sh` runs" — because a
   fourth copy buys nothing a reference does not. **The seam's key set is deliberately tied to none of
   them**: it is keyed by behaviour change, not by supported minor (§6 proposition 3).
10. The service logs its linked `sqlite3.sqlite_version` **and** its own interpreter version at
    startup, on one line **beside** the configuration dump `service/log.py` already writes, not inside
    it — that dump's documented shape is each non-default value *with the layer it came from*, and
    neither value has a layer. The version string is read **through the seam**, so done-when 3's
    allowlist gains no third file — it stays the seam plus the scanner. Both values are logged because
    this milestone is what makes both vary: Ubuntu's 3.12.3 links SQLite **3.45.1** and a uv-managed
    3.13/3.14 links **3.53.1**, `design/schema.md`'s opening line verifies exactly one of those,
    nothing in the package reads the value at all, and the minor is what selects the seam row.
11. **`coding-standards.md` §6 opens with the five propositions of §"What 'supported' means"** — each
    bold lead sentence and its reason, the interpreter being the first dependency, §6 today saying only
    *"`venv`, latest stable, pinned exactly"*, which says nothing about it. Without this item a verifier
    can pass every other one while §6 still carries none of the standing rules a later session is bound
    by, `coding-standards.md` being binding per `CLAUDE.md`.
    **In that wording except the brief-relative clauses, which are rewritten in §6's own voice** — a
    normative document cannot refer to this one, and one of these sentences becomes *false* on being
    pasted: proposition 1's count is **dated** — "measured at 18 sites across 10 modules when the floor
    was set, 2026-09-20" — or dropped, "PEP 695 syntax is the floor's reason" being sufficient as a rule,
    since no test counts those sites either and the brief's own treatment of the `3.12.3` sites is the
    model; proposition 3's *"which done-when 3's scan covers and which this proposition must say, since as
    §6 text it is what a reader will believe"* — the whole clause, the second half being an instruction to
    the writer rather than a rule — becomes "which a source-scanning test over `zikaron/` and `tests/`
    enforces", and its *"today the table has two keys…"* sentence — a count every added row
    falsifies, guarded by no drift test by this brief's own design, which is the M13-hash rule — becomes
    "the module's table is the record of which minors changed what"; proposition 4's *"the brief chooses
    this behaviour deliberately"* and *"the cap this milestone removes"* become plain statements;
    proposition 5's *"§6's own first rule pins every dependency exactly"* becomes "the pinning rule
    below", since pasted as §6's opening it would point at itself and be false, the pinning rule having
    become the sixth. Its withdrawal parenthetical stays here and in `FINDINGS.md` rather than entering a
    normative document — the operator's rule that a design document states what we are doing, with the
    history in the trail. Proposition 2's sentence is the one done-when 9's drift test parses, so it is
    written together with the regex.
    Then: every definition-of-done site pinned in `tests/test_definition_of_done_sites.py::PHRASE_SITES` ~~carry the two-script sentence from §"The matrix"
    **verbatim**~~ — **withdrawn as built**: every site adapts the wording to its own context and none
    is verbatim. What was wanted is what shipped: each carries the claim with the phrase
    **`additionally required before a milestone lands`** intact, so one grep for that phrase returns
    every site. `check.sh:2` included — and **not** `FINDINGS-archive.md:773`, struck in §"The
    definition of done…" above: the archive carries no occurrence of the phrase, in the tree or at
    `HEAD`, and `:773` is a section heading. *The sentence contradicted itself inside one clause —
    "one grep for that phrase returns every site" and then a site that grep has never returned — and
    the claim had already been struck 187 lines earlier in this same brief.* **Both** hermeticity
    paragraphs — `CLAUDE.md` §"The check gate" and `check.sh`'s hermeticity comment — name the matrix as the deliberate exception;
    `coding-standards.md` §9's command block is corrected to match `check.sh` and names
    `check-matrix.sh` and when it runs; the root `README.md`, under Requirements, states Python 3.12
    or newer with 3.12, 3.13 and 3.14 as the tested set, and its install command is
    `python3 -m venv .venv`.
    *(Both line numbers had rotted — 65 and 84 now land on the knowledge paragraph and the indexer
    table row. Every proposition still holds; only the navigation was wrong, and this brief's own
    done-when 3 already prescribes naming the passage instead.)*
12. `FINDINGS.md` §"Current state — resume here" records the outcome and the review trail, and its
    status line moves off "briefed". **Its four internal contradictions were fixed when this brief landed rather
    than deferred into the milestone** — it had said *"Nothing is decided"* sixty lines above
    *"Decisions taken with the operator"*, prescribed `filterwarnings = error` (a `pyproject.toml`
    setting, which is the outcome the matrix decision exists to avoid), and written
    `unix_server_kwargs()`'s value as `{"cleanup_socket": False}` unconditionally, which is the 3.12
    `TypeError`; and it had kept an *"**Open decision**: pass `cleanup_socket=False` … or accept the
    default"* paragraph forty lines above the one settling it. An always-loaded file that states a
    wrong plan is a defect now, not a milestone task. **The count stays four**: FINDINGS also carried
    the refuted "a `fastembed` release must not redden the gate" reason, fixed in the same pass, but
    that was a disagreement with *this brief* rather than a fifth contradiction internal to FINDINGS —
    said here so the next reader counting them arrives at four rather than five.

**Fence.** This milestone widens the *supported range*; it does not change **how Zikaron is
obtained**. No `uv tool install`, no PyPI publication, no change to the install flow — shipping a
managed interpreter and publishing a package are each their own milestone. (Done-when 1 does edit
`pyproject.toml` metadata; that is the range itself, not packaging.) **No macOS work**: the missing
`onnxruntime` x86_64 wheel, the 104-byte `sun_path` limit and the absent `$XDG_RUNTIME_DIR` are real
and are not touched here. **No SQLite pinning and no minimum-SQLite check** beyond logging the value —
pinning the library means pinning a statically-linked interpreter or vendoring the library, either
of which is the packaging milestone this one deliberately is not. *(The adjective was added at
code-review round 12: a distribution interpreter loads the system `libsqlite3.so`, so pinning it
pins nothing here — which is why §"Still open" names a **managed** interpreter as the remedy, and
always did. The vendoring alternative is round 14's.)*

**And the shutdown perturbation walk is deliberately dropped, by operator decision, recorded here as
a debt rather than as a nothing.** Those cells are socket-lifecycle questions that predate any version
work and that `cleanup_socket=False` leaves exactly as they were. The sharpest one, stated concretely
so it can be read cold: `main.run`'s `except BaseException` path calls `shut_down()` **before**
its own `sock_path.unlink`, so between `server.close()` and that unlink the socket file exists and
refuses connections; a client then takes `hook/connect.py`'s `_vet_and_clear_stale_socket` and spawns a
successor; and the old process's own unlink, running after the close, can then remove the
**successor's** live socket.
**That unlink is a bare `sock_path.unlink(missing_ok=True)` with no vet at all** — as are the four
other bare ones: `main.run`'s signal path (per its own comment) and its force-exit helper, and
the two self-stop paths, `lifecycle.py`'s `idle_self_stop` and `stop_on_encoder_failure`, which are the
*"self-stopping tasks"* `main.run`'s docstring names. Of the **seven** socket-path unlinks under
`zikaron/service/` and `zikaron/hook/`, only two vet anything —
`service/lifecycle.py`'s and `hook/connect.py`'s `_vet_and_clear_stale_socket` — identically named
in both — each of which calls `security.vet_socket_for_unlink` immediately before its `unlink()`. So the hazard is one step worse than
"unguarded against inode identity": even the client-side vet that does exist checks ownership and type
and **not** inode identity, while asyncio's own 3.13+ cleanup — the thing we are switching off — is the
only unlink in the system that checks the inode.
`research/python-portability-probes.md` §5b item 3 records that asymmetry. `CLAUDE.md`'s rule is
triggered by *editing* lifecycle code, which the seam does, so this is a decision to skip a required
step rather than an absence of one.

---

## M28 — Publication: a licence, a sweep, and a continuous instrument

Normative: creates **`design/distribution.md`**, which becomes normative for supported platforms, how
Zikaron is obtained, and what CI asserts — at least §"Platforms" (which M29's Normative line already
points at), §"Acquisition", §"The version scheme" and §"What CI asserts". Amends `design/overview.md`
§4 with **D35** (supported platforms) and **D36** (distribution and acquisition).
`design/coding-standards.md` §9 gains a CI row beside `check.sh` and `check-matrix.sh`, **stating what
CI is rather than adding a third thing to run** — done-when 3 carries the exact distinction, and the
risk this row exists to avoid is a site that merely appends "and CI" and so makes the drift worse.
Prior art: `research/python-distribution-portability.md` §§2a, 3. Measurements:
`research/python-portability-probes.md` §§4, 6, 7.

This milestone publishes the repository and builds the instrument the next one needs. **It ships no
product code.** The ordering is the operator's decision of 2026-09-21 — *publish, then macOS, then
polish* — on the argument that nothing platform-coupled should be fixed by reasoning when a runner
could check it. The cost of that order is stated rather than hidden: the first public commits are
packaging chores, and the corpus goes public with sections mid-argument.

### The decisions this milestone writes down

Settled with the operator 2026-09-21. **Recorded here because `design/distribution.md` does not exist
yet**; once it does, the document wins wherever the two disagree. **Deliberately not counted in this
heading** — a numbered list under a heading that states its own length is an enumeration with no test
behind it, which is the drift this corpus keeps recording; the list below is the count.

**Each decision carries what was rejected, and that is load-bearing rather than decorative.** The
operator's rule is that a design document states what we are doing *with rejected alternatives at the
end*, and `distribution.md` will be written from this brief — so a rejection recorded only in
`FINDINGS.md`'s index, which is explicitly not normative, would not survive into the document that is.

1. **Platforms: Linux and macOS arm64.** ~~Intel Macs are out and it is not ours to fix — `onnxruntime`
   stopped publishing macOS x86_64 wheels (reported at 1.23.2; verify against PyPI's release history
   before quoting the number).~~ **— verified 2026-09-21, and the number survives while the reasoning
   does not** (`research/onnxruntime-macos-wheels.md`). 1.23.2 (2025-10-22) is indeed the last release
   carrying a `macosx_13_0_x86_64` wheel, dropped at 1.24.1 with its own release note saying so, and no
   universal2 wheel exists near it. **But the stack still installs on an Intel Mac for two of the three
   interpreters we support**: `fastembed==0.8.0` excludes only specific broken point releases rather
   than everything below 1.24.2, so a resolver backtracks to 1.23.2 on cp312 and cp313. Only **cp314**
   forces `>=1.24.2` and so fails outright. **The decision is unchanged and its justification is
   restated**: Intel Macs are out because supporting them means supporting a year-stale pinned
   `onnxruntime` on two of three interpreters and a hard failure on the third — not because no wheel
   exists. *(The instructive part is that this brief told its executor to verify the number, and the
   number was the half that held; what was wrong was the sentence beside it that nobody flagged.)*
   Windows is out **by transport**: AF_UNIX plus asyncio's POSIX-only Unix
   transports, so supporting it means a second transport behind the RPC seam and is its own milestone,
   not a flag.
2. **`uv` is the recommended acquisition path and host Python stays supported.** Install-time uv only
   — `uv run`/`uvx` at call time costs **+20 ms** on a process that runs once per user message (probe
   note §7), which is the one budget this design has repeatedly paid to protect.
   **Rejected: requiring `uv` outright**, which is tempting because macOS is exactly where a host
   interpreter fails the `enable_load_extension` test, but reach matters more than a clean single path;
   and **shipping our own python-build-standalone build**, which would pin SQLite for free and remove
   the host question entirely, but reimplements what `uv` already does correctly. The second is kept as
   a later option rather than refuted — see §"Still open" in `FINDINGS.md`.
3. **MIT.** Every runtime dependency is permissive — `aiosqlite` MIT, `sqlite-vec` MIT/Apache-2.0
   dual, `fastembed` and `fastmcp` Apache-2.0 — *and, since M30, `huggingface_hub` Apache-2.0,
   direct rather than transitive (D19 as amended)* — so nothing in the tree constrains the choice.
   **Rejected: Apache-2.0**, whose patent grant and NOTICE mechanism corporate review prefers and which
   half the dependency tree uses, on the grounds that for a SQLite-and-ONNX CLI the grant buys little
   against MIT's shorter, more widely-recognised terms; and **AGPL-3.0**, which would keep the design
   out of a closed product but which most companies' policies forbid installing at all, so for a
   locally-run developer tool it mainly blocks the intended users — and would not bind a harness vendor
   reimplementing the ideas from the public design documents anyway.
4. **Public repository now, PyPI in M30.** Public repo ≠ published package: `uv tool install zikaron`
   before M30's front door exists would ship a release whose installer is unreachable (see M30
   §"The front door"). Until then the documented path is `uv tool install --managed-python git+…`; probe note §6
   measured that artefact shape on a **local tree copy**, and the `git+` form differs only in where the
   source comes from, so the absolute-path shebangs the install contract needs are established for it
   by inference rather than directly.
   **Rejected: a private repository plus PyPI only**, which keeps the working corpus private but gives
   up the free macOS runner — the only instrument available for the platform this work commits to; and
   **a public-code / private-corpus split**, which would get both, at the cost of a maintained
   duplication whose second site is the one nobody edits. That last failure mode is this project's own,
   recorded repeatedly in `FINDINGS.md`.
5. **Model files are fetched and never redistributed** — operator's constraint, stricter than the
   licence requires. ~~`bge-small-en-v1.5` is recorded as MIT in
   `research/embedding-models-technical-prose.md`, which is our own note rather than a primary
   reading; M30 re-verifies it against the model card before shipping a fetcher.~~ **Re-verified at
   M30 against both model cards, and the recorded licence was the wrong repository's**: MIT is
   `BAAI/bge-small-en-v1.5`, the upstream weights, while the quantized ONNX artefact actually
   fetched — `qdrant/bge-small-en-v1.5-onnx-q` — states `apache-2.0`. Both permissive.
   `research/m30-name-and-licence.md`. The constraint
   forecloses vendoring the weights in a wheel, which was the option that would have removed the
   network from first run.
6. **CI is the only macOS instrument.** No Apple hardware is available. What that buys and what it
   does not is §"What CI can and cannot prove" below.
7. **And the order: publish → macOS → polish.** So nothing platform-coupled is fixed by reasoning when
   a runner could check it. **Rejected: local work first**, which would land the front door and the
   model fixes against today's green gate but ship the macOS milestone on reasoning alone, with
   publication then re-opening it; and **paying for private macOS runner minutes** at the 10×
   multiplier, which would keep publication a deliberate act rather than a prerequisite, at the cost of
   money and of an instrument only the operator can see.

### The sweep, and why it is first

Publication exposes the working corpus, so the sweep gates everything else here. **Measured
2026-09-21 over tracked files at `HEAD`:**

| pattern | files | hits |
|---|---|---|
| `/home/nathan` | 19 | 76 |
| `LeibaTrader` | 7 | 60 |
| `~/Trading` | 7 | 22 |
| `zk-dogfood` | 6 | 11 |
| `zk-m26-cockroach` | 4 | 6 |
| the operator's email address | **0** | 0 |

**`zikaron/` itself is clean.** Every `/home/nathan` hit is in `reviews/` (6), `experiments/` (5),
`spikes/` (2), `research/` (2), `.kiro/` (2), `design/` (1) and `FINDINGS.md` (1). So the shipped
package needs no redaction and the question is entirely about the evidence directories.

**Use `git grep`, not a ripgrep-family tool, and the difference is not cosmetic.** Two of the tracked
files below are `.log`, which `.gitignore`'s `*.log` hides from every tool that honours ignore files —
so `rg` reports **17 files / 61 hits** where `git grep` reports 19 / 76. **The files it drops are
exactly the ones carrying the credentials below**, which is as adverse as a tool difference gets. A
future sweep run with the wrong tool will silently under-count and will look clean.

**The table above is necessary and was not sufficient, which review round 1 established and which is
this milestone's most important correction.** It sweeps five path strings and an address — none of
which is a secret — and an earlier draft concluded from it that history could be accepted as it stands.
**It never ran a pattern for a credential.** Measured:

| tracked file | carries |
|---|---|
| `spikes/claude-code-harness/hook.log` | `CLAUDE_CODE_MESSAGING_TOKEN` (32 hex), `CLAUDE_CODE_SESSION_ID` |
| `spikes/claude-code-harness/mcp.log` | the same |
| `research/kiro-mcp-lifecycle-probe.jsonl` | a `kiro_env` object **with values**, on all 21 lines: `KIRO_USER_ID`, `KIRO_TELEMETRY_CLIENT_ID`, `KIRO_TUI_READY_TOKEN`, `KIRO_SESSION_ID` |
| `research/kiro-session-id-probe.jsonl` | **key *names* only** — an `env_kiro_keys` list — plus one value, `env_KIRO_SESSION_ID` (a uuid4) |

**Three are per-process environment dumps** — the `/proc/<pid>/environ` reads D31's own history
describes — and **the fourth is a key listing**, whose only live-capable content is a session uuid.
~~A session-scoped messaging token is plausibly long dead and a telemetry client id is an identifier
rather than a credential, **but this brief cannot say either, because nothing looked.**~~ **— looked,
2026-09-21, on operator challenge: none of it is a risk.** `CLAUDE_CODE_MESSAGING_TOKEN` pairs with
`CLAUDE_CODE_MESSAGING_SOCKET=/run/user/1000/cc-socks/<pid>` — **a Unix socket named by pid, on tmpfs,
under a 0700 directory**. Gone at process exit, wiped at reboot, and even live reachable only by that uid
on that machine, who needs no token to use it. The session ids and `KIRO_TUI_READY_TOKEN` are uuid4s and
local handshake values naming local files. **Two are genuinely not ephemeral** — `KIRO_USER_ID` (`d-…`,
a stable AWS Builder ID directory user) and `KIRO_TELEMETRY_CLIENT_ID` (a stable per-install id) — but
neither authenticates anything, and both disclose less than the committer metadata every commit in a
public repository carries.
**So: no redaction and no history rewrite.** What survives of the finding is narrow and still correct:
*accept history* had been decided **without the relevant class on the table**, which made it uninformed
rather than wrong. It is now decided with looking, and the sweep's job is to record *"looked, nothing
live"* rather than to find something.
**The over-weighting is its own lesson, and the cheaper half was available throughout: a 32-hex string
beside the word TOKEN reads alarming, and the ten seconds of reading that dissolve it cost far less than
the escalation that skips them.** Both the reviewer and I escalated first.

**The fourth row is also a warning about the sweep's own instrument, and it caught both the reviewer
and me.** Round 1 called all four "environ dumps" and I confirmed it with a grep for variable *names* —
which matches a name inside a list exactly as well as a name in an assignment, so it could not have
told the two apart, and I nonetheless wrote "verified independently". **A name-grep cannot establish
that a value is present.** Family 1's `"[A-Z][A-Z0-9_]+":` pattern inherits the same blind spot from
the other side: in this file the JSON key is `"env_KIRO_SESSION_ID":`, lowercase-led, and the list
items are followed by `,` or `]` and never `:` — so the family as written reports **nothing** in a file
this table names. **Decided: widen it to `"[A-Z][A-Z0-9_]+"`** — any quoted upper-snake string, whatever
follows. Family 1 is a *signature* family whose job is to flag a file for a human to read, so
over-matching costs a count while the colon form costs a miss in a file this very table names. *(An
earlier draft of this paragraph said "but decide" and then did not, which is the same defect one level
up.)* The other half of the family is right as written: the token assignments in both `.log` files begin
at column 0, so `^\s*[A-Z][A-Z0-9_]+=` reports them.

**So the sweep gains three pattern families, and the accept-history decision is re-taken on their
output with the operator:**

1. **Environment-dump signatures** in tracked `.log`/`.jsonl` — `^\s*[A-Z][A-Z0-9_]+=` and
   `"[A-Z][A-Z0-9_]+"` (the quoted form **without** a trailing colon, per the decision above) — because
   the unit of exposure here is a dump, not a string.
2. **Credential-shaped names** — `TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|CLIENT_ID|USER_ID`.
3. **Credential-shaped values** — 32/40/64-character hex runs, and `-----BEGIN`.

For every hit, record **whether the value is live**, which is the fact that decides between redaction
and a note. `.gitignore` already names `*.pem`, `*.key` and `.env*`, and `.claude/settings.json`
carries a deny list, so the project knows this class exists — the sweep simply never ran it.

**Three further things the sweep must not get wrong.**

- **`git grep` reads the working tree, not history.** Every hit above also sits in committed history at
  whatever revision introduced it, and publishing a repository publishes its history. ~~**This brief's
  position: accept the history as it stands, redact nothing retroactively, and fix the working tree
  only where a path is load-bearing.**~~ **— withdrawn as premature, then reinstated once the liveness
  check was actually run.** The position was never wrong; it was **unsupported**, because nothing had
  looked at the credential class. Looked 2026-09-21: nothing live, nothing authenticating (see the
  paragraph above the table). **So accept the history as it stands, redact nothing retroactively, and
  fix the working tree only where a path is load-bearing** — now on evidence rather than by default.
  The ordering rule still binds anything *new* the sweep turns up: removing a live token from the
  working tree while leaving it in history removes nothing, so establish liveness before deciding, and
  the decision is the operator's, the only remedy being a history rewrite — destructive in exactly the
  way `CLAUDE.md` forbids an agent to attempt unasked. A home-directory path remains not a secret.
- **The committer email is in every commit's metadata** and no sweep of file *contents* will find it.
  Ordinary for an open-source repository, and named here only so it is a choice rather than a
  discovery.
- **`LeibaTrader` is a different class from a home-directory path.** It names a private project of the
  operator's, and several findings quote its store's contents. Redacting the *name* while keeping the
  quoted material discloses the same thing, so the decision is per-passage and belongs to the
  operator, not to a grep.

### What CI can and cannot prove

`check.sh` is hermetic — the two harness tiers are excluded because they need a third-party binary
and somebody else's credential state — so a runner can execute the whole default suite with nothing
installed but Python, the dependencies, **`git`, GNU `timeout`, and network access to Hugging Face for
the first model fetch**. That is what makes CI possible here at all, and the three additions are not
pedantry: `timeout` is not on macOS (done-when 4 guarantees it; M29 owns only the residual class of the
same kind), and a runner with no network reaches the model download
and stops.

**CI is strictly stronger than `check-matrix.sh` on one axis and strictly weaker on another.**

- **Stronger: tree identity comes free.** The matrix script had to build a fingerprint over `HEAD`
  plus every staged, unstaged and untracked difference, and sample it twice, because a local tree
  moves while the run is in flight — it caught its own author editing `CLAUDE.md` mid-run. A CI job
  checks out one commit, so *every version saw the same tree* is guaranteed by the SHA rather than
  asserted by a guard.
- **Weaker: it cannot dogfood.** No live harness, so `integration_claude` and `integration_kiro` stay
  local-only and nothing in CI exercises a real session pushing and searching. On macOS that is the
  residual M29 cannot close.

**The Gatekeeper question is answered by CI, which is worth stating because this project's own first
framing said otherwise.** The `integration` tier — real fastembed, real sqlite-vec, real sockets,
real subprocesses — is *in* the default run, so a macOS job performs the full
pip-install-then-`load_extension` sequence on a real Apple machine. If a pip-extracted `.dylib` were
quarantined, that job fails. Caveat: a runner's security context is not a desktop's, so this is
strong evidence and not proof.

**CI must carry the matrix's deprecation filter or it is a second, looser definition of done.**
`check-matrix.sh` sets `PYTEST_ADDOPTS="-W error::DeprecationWarning -W
error::PendingDeprecationWarning"` and the matching `PYTHONWARNINGS`; a job that omits them is green
on a tree the matrix would redden. **One job per version rather than `check-matrix.sh --parallel`**,
because per-version jobs give clearer failure attribution and CI already supplies the tree identity
that script's parallel mode exists to provide — but then the env vars are per-job and have to be
asserted rather than remembered.

**The model download is a per-job cost, and caching it takes one deliberate choice.** The embedder is
64 MB and, left to fastembed's default, lands under `tempfile.gettempdir()` — which on the macOS runner
is a per-session path `actions/cache` cannot name at authoring time. So done-when 6 sets
`FASTEMBED_CACHE_PATH` and caches *that* directory, keyed on the model name and the `fastembed` pin;
M30's revision pin then joins the key. Named here because a setup that silently pulls 64 MB per job per
version is the kind of cost nobody measures until it is a bill.

**Done when:**

1. `LICENSE` at the repository root, MIT, with the copyright holder as the operator names himself.
   **`pyproject.toml` carries `license = "MIT"` — an SPDX expression — plus
   `license-files = ["LICENSE"]`, and *no* `License :: OSI Approved :: MIT License` classifier**, which
   setuptools ≥ 77 deprecates when a licence expression is present (this project pins
   `setuptools==84.0.0`, so PEP 639 is the live shape). Stated exactly because "the classifiers a
   publishable package needs" was the earlier wording and would have sent the executor to the
   deprecated combination. Add `readme = "README.md"` and `[project.urls]` in the same pass — both are
   absent today, and without them the PyPI page is blank.
2. `version` moves off `0.0.0` to `0.1.0`, and `design/distribution.md` states the scheme: semver,
   `0.x` while the install contract may still change, and the one rule that matters — **a release
   whose installed artefacts differ in *shape* from the previous one is a minor bump, never a patch**,
   because those paths are written into harness config an upgrade must be able to refresh.
3. `design/distribution.md` exists and is normative for the decisions above, with **D35** and
   **D36** added to `design/overview.md` §4 and one-line rows in `FINDINGS.md`'s index. `CLAUDE.md`'s
   design table gains its row.
   **And every site stating the definition of done says what CI is and is not**, because CI makes a
   **third** gate and those sites currently name two. **The count is the grep, never a number written
   here**, and **the set is now pinned by name in `tests/test_definition_of_done_sites.py::PHRASE_SITES`**
   — read it there rather than re-deriving, because an addition reddens that guard and reddens
   nothing here. The grep it corresponds to is
   `grep -rn "additionally required before a milestone lands" --include=*.md --include=*.sh
   --include=*.json .`.
   ~~today spanning `check.sh`, `check-matrix.sh`, `CLAUDE.md`, `design/coding-standards.md` §9,
   `design/build-plan.md`'s own header, `README.md` and `.claude/agents/memory-researcher.md`.~~
   **— seven names, and there are eight**: `.kiro/agents/memory-researcher.json` joined the set when
   the gate rule was carried into the kiro mirror, deliberately and with the reason recorded in the
   guard, **and the `--include` list here could not have seen it** — no `*.json`. *A count-is-the-grep
   discipline enforced by a grep blind to one of its own sites, with the enumeration beside it short
   by the same one.* **The grep returns more lines than there are sites, and the
   difference is not drift**: lines inside `reviews/` are quotations of the claim, and lines inside
   this file's own briefs are briefs *about* the claim. Reconcile against `PHRASE_SITES` rather
   than against the line count. **The claim each must carry is the distinction, not the
   third name**: `check.sh` stays the per-edit gate, `check-matrix.sh` stays what a milestone needs
   locally, and **CI asserts the *matrix's* claim — every supported version green on one tree —
   against a commit rather than a working tree, by running `check.sh` once per version rather than by
   running `check-matrix.sh` at all** (done-when 4). So it is not a third thing to run; it is the same
   claim with the tree identity supplied by the SHA instead of by a fingerprint. A site that merely
   appends "and CI" has made the drift worse. **M27's own review trail is
   the evidence for doing this deliberately**: it found an enumeration of these very sites drifting
   across four consecutive rounds.
4. A GitHub Actions workflow runs `check.sh` on Linux for 3.12, 3.13 and 3.14, and on the arm64 macOS
   runner — **the label verified, not assumed** — for **3.12**, the floor, ~~chosen on wheel-availability
   grounds since `onnxruntime` cp314 arm64 wheels are unverified in this corpus~~ **— that reason is
   dead, 2026-09-21: cp314 macOS arm64 wheels have existed since 1.24.1 in February 2026, alongside
   cp314 Linux x86_64** (`research/onnxruntime-macos-wheels.md`). The version choice is now open rather
   than forced, and two facts bear on it that the original reason did not: public-repository macOS
   minutes are **free** on the standard runners, so a second version costs nothing but queue time, and
   3.12 remains the likeliest *host* interpreter on a Mac, which is the case M29 exists to make work.
   **Settled with the operator 2026-09-21: it stays 3.12, on that second ground.** The floor is the
   interpreter a macOS user is likeliest to already have, so it is the version M29's work will be
   judged on; and three advisory-red jobs on a platform already known broken is noise rather than
   instrument in the one milestone whose purpose is to *build* the instrument. The reason is now the
   host-interpreter argument and not a wheel-availability one, and a later milestone widening the
   macOS matrix is free to do so — the wheels are there.
   **The label is settled**: `macos-15`, named explicitly — `macos-latest` migrated to macOS 26
   mid-2026 and `macos-13` is sunset, so the floating label is a moving target
   (`research/github-actions-macos-runners.md`). Every job exports both
   deprecation env vars, and **the drift test asserts that per job** rather than asserting the version
   list alone — the brief's own argument for per-version jobs is that those vars are per-job and must
   be asserted rather than remembered, and a test that checks only the list leaves the thing the
   argument was about unchecked. The version list is tied to `check-matrix.sh`'s by the same test.
   **Each job's interpreter comes from `uv`, by the recipe `CLAUDE.md` §"Setting up a development
   environment" already gives**: `astral-sh/setup-uv` → `uv python install --no-bin <minor>` →
   `uv venv --seed --python <minor> .venv` → `.venv/bin/pip install -e '.[dev]'`. **This is not a
   detail.** `enable_load_extension` is compile-time, `actions/setup-python`'s builds are unverified in
   this corpus, and probe note §4 verified the flag on exactly the python-build-standalone builds `uv`
   fetches — which are also what a `uv tool install` user gets. So the recipe is what makes the
   Gatekeeper and `load_extension` evidence above evidence *about the binary users will run*. It also
   mirrors `check-matrix.sh`'s own first resolution source.
   **A macOS-only step must guarantee GNU `timeout`** (`brew install coreutils` plus its gnubin on
   `PATH`, or equivalent), because `check.sh` wraps pytest in it and macOS ships no such binary.
   Without it the advisory job dies in the shell script before one test runs, and M28 lands reporting
   "advisory red, as expected" having built nothing. Workflow-only, so inside the fence.
   **Confirmed 2026-09-21 and the "or equivalent" is not optional**: the runner image's own readme has
   zero matches for `coreutils`, `timeout` and `gtimeout` alike, so no Homebrew package provides it,
   and macOS ships BSD userland with no `timeout(1)` — *(that readme lists installed **packages**
   rather than `/usr/bin`, so the second half is the documented shape of BSD userland rather than a
   reading of the file; the job's "prove `timeout` is the GNU one" step settles it on the runner,
   since under `bash -eo pipefail` a BSD `timeout` has no `--version` and fails there)* — and
   Homebrew's coreutils installs the GNU tools **`g`-prefixed**, `gtimeout` rather than `timeout`. So both
   halves are required, `brew install coreutils` **and**
   `echo "$(brew --prefix coreutils)/libexec/gnubin" >> "$GITHUB_PATH"`, and a workflow that runs only
   the first fails exactly as if it had run neither.
5. The macOS job is advisory, and **"visible" is operationalised rather than asserted**: an
   `if: always()` step writes the job's outcome and the word *advisory* to `$GITHUB_STEP_SUMMARY`, and
   the drift test asserts that step exists. Whether `continue-on-error` still renders the job red in
   the checks UI is exactly the class done-when 10 admits is untestable before the first push, so the
   first real run records in `design/distribution.md` what the UI actually showed. **Name the
   alternative that needs no setting at all**: a plainly failing job that is simply not a required
   check — there is no branch protection today, so nothing blocks on it either way.
6. The model cache is cached in the workflow, ~~**and the job sets
   `FASTEMBED_CACHE_PATH: ${{ runner.temp }}/fastembed_cache` to make that possible**~~ **— that
   prescribes a form the build then had to reject, corrected 2026-09-22.** The `runner` context is
   available only at *step* level, not in workflow-level `env:` and not in `jobs.<id>.env:`, so a
   `job sets FASTEMBED_CACHE_PATH: ${{ runner.temp }}/…` is a reference to a context outside its
   availability and the job would not start. The built form exports it from `$RUNNER_TEMP` inside a
   `run:` step, through `$GITHUB_ENV`, which reaches every later step including `./check.sh`. The
   *reason* below is untouched and still correct — `runner.temp`
   rather than `github.workspace`, so 64 MB of untracked model does not land inside the checkout where
   `test_version_seam.py`'s tree scan and ruff both walk; `actions/cache` names either at authoring time
   equally well, and this one needs no `.gitignore` change. The
   default is `tempfile.gettempdir()/fastembed_cache`, which on the macOS runner is a per-session
   `/var/folders/…` path that `actions/cache` cannot name at authoring time — it works on Linux only
   by accident. fastembed already honours the variable, so this is workflow-only and inside the fence.
   Key it on the model name **and the `fastembed` pin — until M30 pins a revision, which then joins the
   key** (M30 done-when 7, and the reason is there: `actions/cache` saves only on a key miss, so a key
   that does not name the revision goes stale permanently rather than refreshing).
7. The sweep is run — **all four families: the path strings, and the three credential families above** —
   its per-pattern counts recorded in `FINDINGS.md`, and every decision written down with its reason.
   **Two blocker classes, not one**: any hit inside `zikaron/`, and **any live credential anywhere** —
   the second being a standing guard rather than an expectation, since the four known files were read
   2026-09-21 and hold nothing live.
   There are no `zikaron/` hits today and a test asserting that is cheaper than a habit — but **assemble
   its patterns from fragments**, as M27's version-seam scanner does, or the test file becomes a
   `/home/nathan` hit in every later sweep and the count drifts by one forever.
   **State each pattern, because two of them do not reproduce otherwise.** The email row means *the
   operator's address*: a naive `@` regex returns six hits, all `@example.invalid` placeholders in
   `spikes/spike_git_shapes.py` and two knowledge-git test files, so the pattern must exclude
   `.invalid`/`.example` or name the address directly.
   **And the table's counts are already stale by this brief's own hand.** Writing these sections put
   `/home/nathan` into `design/build-plan.md` several more times and into `FINDINGS.md` once more, and
   the other rows moved the same way, because a document that quotes the strings it counts becomes a
   site. The table is marked *"at `HEAD`"* and is true there. **Reconcile the `design/` and
   `FINDINGS.md` rows against the quoting rather than reading their growth as new exposure** — the same
   reason the test above assembles its patterns from fragments.
8. `README.md`'s install section documents the two supported paths — `uv tool install --managed-python git+…` as
   recommended, a source checkout plus a host `python3 -m venv` as the alternative — and says plainly
   that macOS is untested until M29. **The `git+` URL is not knowable until the remote exists**
   (done-when 10), so README carries the recommended path with the URL as the one placeholder the
   publishing commit fills in; everything around it is written now.
9. `./check.sh` and `./check-matrix.sh --parallel` both green on one tree identity.
   **Expect the first CI run's coverage to sit lower than a local one and do not touch the floor for
   it.** `fail_under` is 95 against a locally measured 96.85–98.12% spread that moves with load,
   because the socket-and-timing branches take error paths or not depending on how a race lands; a
   runner's core count and load differ from this machine's. A red first run on coverage is a fact about the runner, not a
   regression, and neither raising nor lowering the floor is licensed by one CI reading.
10. **The repository is prepared for publication; the operator sets the remote and pushes when it is
    time.** (Operator, 2026-09-21, on an earlier draft that made more of this than it is.) So the
    **session** brings the tree to a publishable state and stops — the *milestone* closes on a green
    push, per (b). Two consequences that do matter.
    **(a) The workflow must name the branch that exists, which is `main`.** ~~The branch name is a
    decision. The working branch is `master` while this repository's stated main branch is `main`, and a
    public repository should not carry that disagreement.~~ **— withdrawn 2026-09-21 on operator
    challenge, and there was no disagreement to withdraw.** "Stated" came from the *harness's* opening
    git-context line, which is Claude Code's own default guess; checked against the repository, there is
    **no `main` branch, no `init.defaultBranch` set locally or globally, and no remote**. ~~GitHub takes
    whatever branch is pushed first as the default, so `master` costs nothing.~~ What remains is the one
    concrete coupling: `on: push: branches:` names the branch, and a workflow keyed to the other one
    would simply never fire.
    **— and the withdrawal was itself refuted the next day, which makes this passage a three-layer
    record of one fact nobody checked.** On 2026-09-22 the operator reported that **the repository
    already exists**: `git@github.com:nathan-shapiro/Zikaron.git`, created through GitHub's own UI with
    an MIT `LICENSE`. Read with `git ls-remote` — which needs no remote configured and writes nothing —
    it has **one branch, `main`, at commit `67088208`, with `HEAD` pointing at it and no `master` at
    all**. So "GitHub takes whatever branch is pushed first" never applied: the default was set at
    creation, before any of this was written. **Local `master` was renamed to `main`** on the operator's
    decision, `git branch -m`, which moves no commit and discards nothing.
    *(The instructive part is now the shape of the error rather than the error. Layer one invented a
    fact from a harness status line. Layer two corrected it by reading the local repository — correctly,
    and it was still wrong, because the question was never local. Layer three read the remote. **Each
    layer checked one more thing than the last and each stopped at the boundary of what it thought the
    question was about.** The brief's own §M28 opening says publication is the subject; the repository's
    own existence was inside that subject and outside every check.)*
    **One consequence the milestone must hand over rather than solve**: local `main` and remote `main`
    share no history, so an ordinary push is refused. Reconciling them — force-push, or merge with
    `--allow-unrelated-histories` — rewrites or merges published history and is **the operator's, not a
    session's**, per `CLAUDE.md`'s standing rule. The remote `LICENSE` and this tree's `LICENSE` are the
    same licence and will resolve to one file either way.
    **The backup refs are a non-issue and the count here was wrong too.** There are **five** —
    `backup-pre-m15-recommit`, `backup-pre-rebase`, `-2`, `-3`, `-4` — not the two an earlier draft
    named, and `git push origin main` sends none of them. Only `--all` would.
    **(b) The workflow cannot be exercised before the first push, and the push is the operator's.**
    Every done-when item above except 5's first-run UI record is verifiable locally; these two are not,
    and a workflow file is notoriously a thing that looks correct and fails on its first real run.
    **So the session brings every locally-verifiable item to green, lands the files, and stops — and
    the milestone is not closed until the operator's push has produced a green run**, which the session
    then records in `design/distribution.md` per done-when 5. An instrument that has never run is not
    yet one, and **M29 does not start on a workflow that has not gone green.**
    *(This item said "stops" and "not complete until green" in two paragraphs that restated each other,
    one of which read as forbidding what the other required — the duplicate arose from trimming the
    item after the operator's instruction and is exactly the fresh-prose defect this trail keeps
    finding. Reconciled at review round 2: the **session** stops; the **milestone** closes on green.)*

**Fence.** No product code. No `zikaron` console script, no model-cache change, no SHA pinning, no
PyPI upload, no macOS fix — each is M29's or M30's, and this milestone's whole value is building the
instrument *before* the fixes rather than after. **The sweep does not rewrite history**, and no git
operation that discards work is performed. **`.kiro/` is not edited** even though it carries two of
the `/home/nathan` hits, per the standing rule.

---

## M29 — macOS green

Normative: `design/architecture.md` §Paths — the `sun_path` sentence and the `$XDG_RUNTIME_DIR`
fallback. `design/distribution.md` §"Platforms" records what the runner established.

**The macOS job goes from advisory to required.** Everything below was believed to be the work, and
**measurement retired the largest item on the branch macOS takes while exposing a small product change
on the branch it does not** — which is why this brief leads both with what is *not* here and with the
one thing that is.

### The `sun_path` limit: a comment defect on the branch macOS takes, an unbounded input on the other

macOS caps `sun_path` at 104 bytes against Linux's 108, both including the terminating NUL, and
`service/paths.py`'s comment on `_HASH_HEX_CHARS` sizes the hash against *"the ~108-byte `sun_path`
limit"*. **Measured 2026-09-21 against the real functions:**

| branch | socket path | length |
|---|---|---|
| `$XDG_RUNTIME_DIR=/run/user/1000` | `/run/user/1000/zikaron/<32 hex>.sock` | 60 B |
| no `$XDG_RUNTIME_DIR` (**the macOS branch**) | `/tmp/zikaron-1000/<32 hex>.sock` | 55 B |

Against macOS's 103 usable bytes (104 with the NUL) that is **48 bytes of headroom on the fallback
branch**. The only input that moves it is the uid's width: uid `501`, macOS's first user, gives 54 B
and 49 spare; a ten-digit uid gives 61 B and 42. *(This figure read **45** in three documents until
review round 1 subtracted it: 103 − 55 = 48, and no subtraction of 55 or 60 from 103 or 104 yields 45.
An arithmetic slip, propagated by copying rather than re-deriving, inside the pair of documents whose
argument is that a number you did not produce is somebody's recollection.)*

**The lock path is not a consumer of this bound**, and an earlier draft implied it was by adding its
five bytes to the figure. `lock_path` is an ordinary file opened for `flock`; `sun_path` bounds only
what is passed to `bind()`. So the test below covers the socket path, and if it covers the lock path
too that is tidiness, not a constraint.

**What is safe by construction is the *store* path's contribution, and that is narrower than "the
design is safe".** The store path is *hashed to 32 hex characters*, never embedded, so no project
nesting depth can move the number — which answers
`research/python-distribution-portability.md` §5's request to check the bound *"for deeply-nested
project directories"*. **But the runtime directory is prepended verbatim, and on the XDG branch that
input is unbounded and user-controlled.** Worked through at review round 1: the very convention §5
found in the wild for macOS, `$TMPDIR/runtime-$UID`, gives
`/var/folders/zz/<~30 chars>/T/runtime-501/zikaron/<32 hex>.sock` ≈ **106 bytes**, over the limit, so
any user who exports `XDG_RUNTIME_DIR` that way gets `OSError: AF_UNIX path too long` at bind. The
earlier draft of this brief noted that convention *"would be longer"* and then reasoned only about the
branch where nobody sets the variable — the exact shape of oversight it accuses `FINDINGS.md` of two
paragraphs later.

**So the decision is taken here rather than left for the milestone to stop on: an over-length socket
path is refused, never repaired.** That is `design/architecture.md` §"Filesystem security"'s own rule
for the runtime directory, and silently falling back to `/tmp/zikaron-<uid>` when the user asked for
somewhere else would be repair. The refusal is a `bad_config`-class error naming `XDG_RUNTIME_DIR`, the
computed length and the limit.

**Two specifics, because leaving either open lets an executor build the wrong thing.**

**(a) The check goes in the pure function — and the diagnosis cannot reach every caller, which the
first draft of this paragraph got wrong.** `socket_path` is reached from `hook/connect.py` and
`mcp/connection.py`; the service takes its `sock_path` from argv and never computes one. A refusal "at
bind" would fire *after* a client had already run start-if-absent and spawned a service, so the client
would see a spawn failure instead. In the pure function it cannot be bypassed and all three callers get
the same answer. **But "an error naming `XDG_RUNTIME_DIR`, the computed length and the limit" cannot be
delivered by the hook**: `hook/push.py` funnels every failure into `record_failure`, and `hook.log`'s
contract — `architecture.md` §"Filesystem security", restated in `failure.py` and `write_policy.py` —
is *"a fixed failure-kind label and an error code, never prompt or memory content, so neither can hold
a leaked secret"*. So:
- ~~the refusal is **a new exception defined in `service/paths.py` itself**, which must stay stdlib-only,
  since `hook/connect.py` imports that module directly for exactly that reason — it therefore cannot
  import the store's error types, and "`bad_config`" above names an RPC code the *service* returns, not
  this;~~
- ~~`push.py` maps it to one new **fixed** `hook.log` kind, `socket_path_too_long`, and that label is the
  whole of what that log may carry;~~
- **— both withdrawn, and the premise under them was false.** `zikaron/core/errors.py` is pure stdlib
  (verified by measuring `sys.modules` after importing it alongside `paths` and `security`: no
  non-stdlib module added), and `service/security.py` — already in the hook's own import set — raises
  `ZikaronError(BAD_CONFIG, source=DERIVED, key="runtime_dir")` from `ensure_runtime_dir` for the
  same class of failure. So the stdlib argument forbids nothing, and a bespoke type would have been a second
  error vocabulary for one class, against `coding-standards.md` §7's "one `IntEnum` … every raise site
  references the enum". **`paths.socket_path` raises that same existing error**, and `push.py` needs no
  change at all: its `_classify_failure` already maps any `ZikaronError` to `(wire_name, code)`, so
  `hook.log` gets the fixed label `bad_config` and `-32023` and nothing else — which is what the
  withdrawn bullet was trying to arrange.
- the variable name, length and limit reach **stderr** through the MCP server's start-up failure —
  where each harness puts that line is unmeasured, and is a row in `design/harness.md`'s table —
  and reach the user through `zikaron doctor` once M30 lands, which M30's `doctor` table carries
  as a check;
- `hook/spawn_warm.py` suppresses it, as it suppresses everything, deliberately.

**(b) The limit is per platform, held as data — and four details decide whether the guard is real.**
CPython refuses `len >= sizeof sun_path`, so usable is **103 on macOS and 107 on Linux**. M27's
"identical on every version" instinct would pick a single 103, which *tightens Linux by four bytes* and
would make this milestone's fence false for a path that binds today. So a two-row table
`{darwin: 104, linux: 108}`, **taking the platform as a parameter so both rows are tested on Linux** —
and:
1. **The comparison is `>=` against the sizeof**, which is CPython's own predicate. A `>` against 104
   admits a 104-byte path that `bind()` then refuses.
2. **The unit is bytes, not characters**: CPython measures the *encoded* path, and `$XDG_RUNTIME_DIR` is
   user-controlled and may be non-ASCII. `len(os.fsencode(path))`, never `len(str(path))`.
3. **The boundary is tested at the boundary.** Done-when 2's two cells sit 42 and 3 bytes from the edge
   and pin neither of the above; removing the check passes an off-by-one. Add exactly 103 accepted /
   104 refused under `darwin`, 107 / 108 under `linux`, and one non-ASCII runtime directory whose *byte*
   length crosses the bound while its character length does not.
4. **Exact match on `sys.platform`, and the table lives in `paths.py`** beside `_HASH_HEX_CHARS` — *not*
   in `asyncio_compat`, whose lookup is greatest-key-≤ over an ordered version tuple (platform strings
   have no order) and whose docstring reserves it for version differences. **An unknown platform takes
   the smaller row**: it can only refuse what another platform might have accepted, never pass what the
   kernel will reject, and D35 promises nothing beyond the two named.

**This is a product change and it touches Linux too** — where the same over-length export produces the
same bare `OSError` today — so it is called out against this milestone's own fence below. The fence's
"no Linux user is likely to have set this" holds **only** under (b); a single 103 would break paths that
work.

The rest of the work is to correct the comment from "~108" to 104 and put the bound in
`architecture.md` §Paths where a test can hold it.

### The absent `$XDG_RUNTIME_DIR` already has a fallback

macOS sets no such variable, so `runtime_dir` takes its `/tmp/zikaron-<uid>` branch — which exists, is
the branch `security.py` already vets as hostile-by-default, and is *shorter* than the XDG one. The
convention the research note found in the wild, `$TMPDIR/runtime-$UID`, would be **longer**
(`/var/folders/…` is deep), so **as a default it buys nothing** — which is a different claim from
"nothing about that branch needs attention", the inference the section above withdraws. **This brief's
position: keep `/tmp/zikaron-<uid>` on macOS and say so in `architecture.md` §Paths, rather than adding
a platform branch for the *default*; the *bound* on a user-exported value is a separate matter and is
decided above.**

~~**What needs verifying on the runner rather than reasoned about: that `security.py`'s vetting passes
on macOS's `/tmp`**, which is a symlink to `/private/tmp` — exactly the shape a hostile-directory
check is built to be suspicious of. **This is the one real risk in the milestone and it is a plausible
blocker**: if the vet refuses, every store on macOS fails to start, and the fix is a decision about
what the vet is defending against, not a tweak.~~

**— mis-sized, and answerable by reading, which review round 1 did.** `ensure_runtime_dir` calls
`path.lstat()` on **the leaf** — `/tmp/zikaron-<uid>` — and refuses only if *that* entry is a symlink.
`/tmp` is a parent component, which `lstat` traverses exactly as `stat` would. **So the vet is
expected to pass on macOS**, and the runner's job is to confirm it rather than to discover it. Kept in
place because the error is instructive: this brief called it *"the one real risk"* one paragraph after
criticising `FINDINGS.md` for *"a plausible worry restated across documents until its size was
assumed"* — and the two risks that were genuinely unread, the unbounded XDG branch above and the
gate script's own portability below, are the ones it did not name. **A brief is not exempt from the
rule it is citing.**

### Everything else is "run it and see" — with one item that was readable all along

Which is the point of the ordering. But *"run it and see"* is only honest about what reading cannot
reach, and one item here could have been read: **the gate script's own portability.** `check.sh` wraps
pytest in GNU `timeout`, which macOS does not ship. If the runner image lacks it, the advisory macOS
job dies in the shell script before a single test runs — and M28 would land reporting that job
"advisory red, as expected" while having built no instrument at all. M28's workflow guarantees
`timeout`; this milestone owns whatever else of the same class turns up (`bash` version, `rm -f`
globbing, anything assuming GNU coreutils flags).

Candidates genuinely needing the runner, none of them assumed: `onnxruntime`'s minimum macOS version
against the image; `fastembed`'s download path under a different `TMPDIR`; file-mode assertions where
macOS's default `umask` or ACLs differ; anything in the suite that assumes `/proc`.

**Done when:**

1. Every platform-coupled fact the runner exposes is fixed in the product, or recorded as a supported
   difference in `design/distribution.md` — never worked around in a test.
2. `service/paths.py`'s comment says 104, and `architecture.md` §Paths carries the bound, the reason
   the *store* path's contribution is safe by construction, and the fact that the runtime directory's
   is not. **The refusal is built as (a) and (b) above specify** — ~~a stdlib-only exception from
   `paths.py`, a fixed `hook.log` kind~~ **`paths.py` raising the same `BAD_CONFIG`/`runtime_dir`
   `ZikaronError` that `security.py` already raises for this class, which `push.py` already degrades on
   as a fixed label** — the detail surfacing through the MCP server and, from M30, `doctor`, and a
   per-platform byte bound compared with `>=`. Tests: the fallback branch fits with a ten-digit uid; an
   over-length `xdg_runtime_dir` is refused rather than left to `bind()`'s bare `OSError` and never
   silently redirected to the fallback; **plus (b)3's boundary cells** — 103 accepted / 104 refused under
   `darwin`, 107 / 108 under `linux`, and a non-ASCII runtime directory whose byte length crosses the
   bound while its character length does not. The function already takes `xdg_runtime_dir` as a
   parameter, so every test states the environment rather than mutating the process's.
   **Mutation-verify the refusal** — and note that the two original cells, 42 and 3 bytes from the edge,
   would pass an off-by-one, which is what (b)3 exists to catch. ~~The hook's own test asserts its
   `hook.log` line carries the fixed `socket_path_too_long` kind **and nothing else**.~~ **— the kind
   is `bad_config`, per the withdrawal in (a); the existing `test_hook_push.py` coverage of that label
   is what this asks for and it already holds.**
   **`tests/test_hook_connect.py`'s too-long-path test stays reachable**: it hands a 300-character
   path straight to `_try_connect`, *below* `paths.socket_path`. ~~is read and left … Add one clause
   saying it bypasses the new refusal deliberately~~ **— its docstring was rewritten instead, to name
   no number at all and to state the bypass, so there is nothing left for a sweep to "fix".**
   ~~**That is the third "~108" site**;
   the other two are `paths.py`'s comment and `architecture.md` §Paths.~~ **— `grep -rn 'sun_path'
   zikaron/ tests/ design/` is the enumeration; there were more sites than this named.**
3. `runtime_dir`'s macOS behaviour is stated in `architecture.md` §Paths, and the `security.py`
   vetting question is **confirmed** on the runner — expected to pass by reading, since `lstat` vets
   the leaf and not its parents, so a runner disagreement is the interesting outcome rather than the
   expected one.
4. The macOS job loses `continue-on-error`, and M28's workflow comment naming M29 goes in the same
   commit.
5. `README.md` stops saying macOS is untested and says exactly what *is* tested: the hermetic gate on
   arm64, with the live-session wiring named as the residual.
6. `./check.sh` and `./check-matrix.sh --parallel` green on Linux; the macOS job green on the same
   commit.

**Fence.** ~~**One deliberate exception**~~ **Two deliberate exceptions, named because the fence
would otherwise forbid them:** the
over-length-path refusal in done-when 2 **does** change Linux behaviour, replacing a bare `OSError` at
bind with a named `bad_config` error on an input no Linux user is likely to have set. It is in scope
because the macOS work is what discovered it and because splitting a two-line guard across milestones
would leave the platform it was found on unprotected.
**And the `zikaron-mcp` entry point's handler**, which prints any `ZikaronError` `build_server`
raises as one line on stderr and exits 1 rather than leaving a traceback — so the consolidator's
config-file refusal on Linux gains that line too. Done-when 2 requires the refusal's detail to
surface through the MCP server, and the exception's own string carries none of it; narrowing the
handler to one payload key would special-case an entry point on a field to preserve a traceback
nobody wants, and the exit status does not move either way.
Nothing else Linux-visible moves; a fix that
alters ordinary Linux behaviour is a different milestone.
**No Intel-Mac work** — no `onnxruntime` pin gymnastics, no alternate embedder; the platform is arm64
and the wheel gap is upstream's. **No front-door or model work**, which is M30. If the `security.py`
vet does refuse on the runner — contrary to the reading above — that is a design decision about what
the vet defends against, and it is raised and stopped on rather than resolved here.

---

## M30 — The front door, the model on disk, and the release

Normative: `design/distribution.md` gains §"The front door" and §"Model acquisition";
`design/architecture.md` §"The install contract" is re-read to confirm nothing here changes the
installed command strings, together with `design/harness.md` §"The installer's two targets".
*(An earlier draft cited that first section as living in `harness.md`, which has no such heading —
`harness.md` refers to it by name and it is `architecture.md`'s. A pointer a fresh session cannot
resolve, found at review round 1.)*
`design/overview.md` D19/D20 are amended withdraw-style for the pinned artefacts.

Three things, all of which a stranger's first ten minutes depend on.

### The front door

**Two user-facing CLIs are currently reachable only as `python -m`.** `zikaron.install` and
`zikaron.knowledge` each have a `__main__.py` and no console script; the shipped scripts are
`zikaron-hook` and `zikaron-mcp` alone. Under `uv tool install` the tool venv's interpreter is not on
`PATH`, so **the installer and the knowledge CLI are unreachable** without the user finding
`~/.local/share/uv/tools/zikaron/bin/python`. For a feature that took six milestones to build, that is
the defect to fix first.
**Two, not three: `zikaron/knowledge/indexer/__main__.py` is the third `__main__.py` in the tree and is
deliberately not a console script** — it is machine-spawned through `sys.executable -m`, the same shape
as the service, so it wants no entry on anyone's `PATH`. Said here so the next reader counting
`__main__.py` files arrives at the right answer instead of re-deriving the number as three.

**One `zikaron` umbrella** with `install`, `knowledge` and `doctor`. **`zikaron-hook` and `zikaron-mcp`
are not touched**, deliberately: they are machine-facing, their absolute paths are written into
harness config, and `design/harness.md` treats the install contract as normative — folding them in
would change every installed config for a cosmetic gain on two surfaces no human types.
`python -m zikaron.install` keeps working.
**While that surface is open:** `knowledge/scope.py`'s `execute` prints a `ZikaronError`'s payload
as ~~`mappingproxy({…})`, enum reprs and all~~ — **read at M30 against the running code, it is
`{'source': <BadConfigSource.FILE: 'file'>, …}`: quoted keys and enum reprs, but a plain dict, since
an f-string calls `str` and `MappingProxyType` defines only `__repr__`. The defect is what the
sentence says; its name was wrong** — render it the way `mcp/main.py` does — `name=value` per
field, one line. Left alone by M29 because it is an ordinary-Linux-behaviour change on a surface
that milestone had no reason to open.

**`doctor` exists because the interpreter decision supports two acquisition paths**, and it names each
failure **by remedy rather than by symptom**. **The pass/fail checks and one report of the table
below, and the distinction matters because done-when 2 sets an exit code:**

| | check | fails when |
|---|---|---|
| 1 | `enable_load_extension` present | the interpreter was built without it — the python.org-macOS and conda case the research note predicts, which otherwise arrives as a bare `AttributeError` |
| 2 | FTS5 available | the linked SQLite lacks it |
| 3 | `sqlite-vec` loads a real `vec0` table | importing succeeds but loading does not — the probe note's own distinction, and the reason a bare import is not the test |
| 4 | the model cache is **present at the pinned revision and hash-verified** | a file is there *at that revision* and does not match its pinned hash. A cache holding only some *other* revision is the **absent** case below, not a mismatch |
| 5 | the socket path fits `sun_path` on this platform | `paths.socket_path` refuses the runtime directory `paths.runtime_dir` resolves — the over-long `$XDG_RUNTIME_DIR` case M29 turns away at MCP start-up, on a channel no probe has measured. The remedy line is that refusal's own `expected`. **M29's done-when 2 names `doctor` as the second channel for it; this row is where that promise is kept** |
| — | the linked SQLite version beside the interpreter's | *never* — a report, not a check: this is the axis no seam can absorb (3.45.1 against 3.53.1 between two builds on one machine), and there is no correct value to compare against |

**Check 4's absent case is exit 0, not a failure, and getting this wrong ships a red first run.** With
no install-time prefetch (this milestone's fence), a stranger's very first `zikaron doctor` finds no
model at all — so *absent* reports **"not yet fetched; fetched on first service start"** and passes,
while *present and mismatched* fails. Unstated, the executor picks, and the likely pick greets every
new user with a non-zero exit before anything is wrong.
*(**Sharpened in the build**: a snapshot directory that is present fails if any pinned file is
**missing** as well as if one mismatches, each with its own remedy — only a directory that is not
there at all is the passing absent case. "Present and mismatched" names one of the two failures.)*

### The model on disk

**The 64 MB embedder is cached in a temporary directory and is lost on reboot.**
`core/indexing/encoder.py` calls `TextEmbedding(model_name=model_name)` with no `cache_dir`, and
`fastembed/common/utils.py`'s `define_cache_dir` defaults to `tempfile.gettempdir()/fastembed_cache`,
overridable only by that argument or `$FASTEMBED_CACHE_PATH`. Measured 2026-09-21:
`/tmp/fastembed_cache/models--qdrant--bge-small-en-v1.5-onnx-q` is **64 MB**, and 340 MB total once
M26's spike models are counted. **On macOS it is worse rather than better** — `TMPDIR` is a
per-session `/var/folders/…` path.

This is a product defect independent of packaging, and **M17's cold-start work never covered it**:
everything that milestone measured was the cost of loading a model already on disk.

**Fix: an explicit cache directory under the user's cache home.** Per-user, never per-store — a
per-store cache would duplicate 64 MB per project.

**And `$FASTEMBED_CACHE_PATH` becomes Zikaron's to honour — but fastembed does not stop reading it, and
an earlier draft of this paragraph said it did.** `OnnxTextEmbedding.__init__` runs
`self.cache_dir = str(define_cache_dir(cache_dir))` **before** the `download_model` call that returns
`specific_model_path` early, and `define_cache_dir` reads the variable when `cache_dir is None` **and
`mkdir`s the result**. So passing `specific_model_path` alone would still create an empty
`tempfile.gettempdir()/fastembed_cache` — the very `/var/folders/…` directory this section objects to —
on every service start.
**So pass Zikaron's resolved directory as `cache_dir` *as well as* `specific_model_path`**: the stray
`mkdir` then lands in the durable directory and `define_cache_dir` never consults the variable at all.
Our own resolver reads `$FASTEMBED_CACHE_PATH`, for continuity with anyone who already set it.
**The layout under it is `huggingface_hub`'s** — `models--<org>--<name>/snapshots/<sha>/` — byte-for-byte
what fastembed's own path writes today, which is the premise that makes M28's CI cache reusable across
this change at all.

### The pinned artefacts

The **SHA256 allowlist** `FINDINGS` has carried as unbuilt since the Amazon Q teardown: one pinned
hash per model file **including `tokenizer.json`**, verified before use. ~~the file deleted on mismatch
so the next run re-downloads rather than failing forever. ~20 lines.~~

**— that remedy is wrong against how `fastembed` actually acquires files, and the "~20 lines" with it.**
Read at review round 1 against the installed library: `download_files_from_huggingface` resolves
`model_info(<repo>).sha` — **the repository's current head** — and snapshot-downloads *that*, and
`TextEmbedding` forwards no `revision`. So a hash allowlist with no pinned revision has a second
mismatch cause that is not local corruption: **the first time `qdrant/bge-small-en-v1.5-onnx-q` pushes
any commit, every install deletes 64 MB, re-fetches the same non-matching bytes, and does it again on
the next service start — forever.** That is precisely the *"failing forever"* the sentence claimed to
avoid, with a 64 MB download attached to each attempt. Delete-and-retry is correct for a corrupt local
copy and only for that.

**So Zikaron owns the acquisition, and the pin is a revision *and* a hash set.**
`huggingface_hub.snapshot_download(repo_id, revision=<sha>, allow_patterns=[…], cache_dir=<durable>)`,
then verify the allowlist, then hand fastembed the directory through
`TextEmbedding(model_name, specific_model_path=<dir>)`, which 0.8.0 supports.

**Four mechanics, each read off the installed library rather than assumed.**

**(i) `huggingface_hub` becomes a *direct* dependency and must be pinned.** It is present transitively
today — `fastembed` imports it — and that settles availability, not policy:
`coding-standards.md` pins every **direct** dependency exactly and explicitly does not pin transitives,
which drift between virtualenvs built on different days. Product code calling `snapshot_download` makes
it direct, and `pyproject.toml` names no `huggingface_hub` at all. It joins `dependencies` with an exact
pin — **1.26.0** is what this tree resolves today.

**(ii) The revision must be the full 40-character commit sha, never a tag or a short form — and the warm
call passes `local_files_only=True` first.** `REGEX_COMMIT_HASH` is `^[0-9a-f]{40}$`, and only a
`revision` matching it **skips `repo_info` entirely**. A tag or short sha costs an HTTPS round-trip on
*every service start*; with the network **down** that stalls on the 10 s request timeout before the
`refs/` fallback, while under `HF_HUB_OFFLINE=1` it fails over at once. That lands on the cold-start path
M17 fought for, once per session.
**But "zero network calls" does not follow from the sha alone**, and the first draft here implied it
did: on the *online* path the file listing comes from the on-disk tree cache and, **if
`trees/<sha>.json` is absent, from one `list_repo_tree` API call** — whose presence is an artefact of
whichever `huggingface_hub` populated the cache. **With `local_files_only=True` and a commit hash,
`_raise_if_incomplete_snapshot` simply returns when the tree cache is missing: no API object is touched
and no request is possible.** That is also the sequence fastembed's own `download_model` uses. So: warm
call `snapshot_download(revision=<sha>, local_files_only=True)`; on `LocalEntryNotFoundError` or
`IncompleteSnapshotError`, the online call; the allowlist verifies whichever returned. **This is what
makes the offline assertion hold by construction rather than by cache state** — and it removes the only
reason the `huggingface_hub` pin would have had to join M28's cache key.

**(iii) The one re-fetch is `force_download=True`, and nothing of ours deletes anything.** *(The online
call; the warm call of (ii) stays `local_files_only=True`.)* The cache
stores content at `blobs/<etag>` with `snapshots/<sha>/<file>` as a symlink to it, and **when the blob
exists and the pointer does not it re-links without downloading**. So "delete the file and call
`snapshot_download` again" deletes the symlink, re-links the same corrupt blob, mismatches again, and
reports *upstream differs* to a user whose **disk** is bad — the two causes' diagnoses swapped. Only
`force_download` re-downloads an existing destination.
*(**Narrowed in the build**: "the one re-fetch" is right for a file that is present and wrong, and
wrong for one that is **absent**. An interrupted first fetch leaves a partial snapshot which the warm
call *returns* rather than refuses — with a commit hash and no tree cache,
`_raise_if_incomplete_snapshot` does not check — and forcing there re-downloads every pinned file
instead of the missing one. Absent and wrong are therefore repaired differently:
`design/distribution.md` §"Model acquisition".)*

*(**Narrowed in the build, on a measurement.** Verifying on **every** start — which (iii) and (iv)
assume — costs 331-396 ms under load and pushed the cold-start sequence past
`push._DEADLINE_SECONDS`, reintroducing M17's defect at 0-1 runs in 5 inside the budget against 5/5
without it. Digests are now checked on the acquisition paths only; a warm start checks presence. A
snapshot proved wrong is discarded before *and* after the forced re-fetch, so no complete-but-wrong
snapshot exists at any instant. **And (iv)'s *never another download* holds for bytes, not
requests**: after the discard, a second call in one process falls through to one plain online call
that re-links the existing blobs and transfers nothing. `design/distribution.md` §"Model
acquisition"; `research/m30-verify-cost.md`.)*

**(iv) Re-fetch is bounded to one per process**, and a second mismatch is a named failure carrying its
remedy (*"artefact at revision X differs from the pinned hash — upgrade zikaron"*), never another
download.

**It buys two distinct things and only one is supply chain.** A public package makes an unverified
64 MB fetch a real exposure. But pinning `tokenizer.json` is also what makes the tokenizer-dependent
bounds **provable** rather than assumed — `chunk_max_tokens`, the gist character bound and the
512-token window arithmetic all rest on a tokenizer nobody pinned. **And that is the second reason the
revision has to be pinned too**: a hash without one proves only that the fetch will eventually fail,
not that the artefact the bounds were computed against is the artefact in use.

**The operator's constraint is fetch, never redistribute**, so the weights stay a download and only
the revision and the hashes travel with the package. Re-verify `bge-small-en-v1.5`'s licence against
the model card first; the corpus records MIT from its own research note rather than from a primary
reading.

### The release

PyPI, once the front door exists. The name appears available — the operator reports another project
used it and renamed — which is worth confirming rather than trusting, since a name claimed between
now and then changes the install command in every document above.

**Done when:**

1. A `zikaron` console script with `install`, `knowledge` and `doctor`; `zikaron-hook` and
   `zikaron-mcp` unchanged in behaviour **and in the strings the installer writes**, asserted by a
   test over the install artefacts rather than by inspection. And `zikaron knowledge`'s refusal line
   renders a `ZikaronError` as `name=value` per field, one line, as `zikaron-mcp` does — asserted by
   a test through `execute`'s `printer`.
2. `doctor` runs **every check and the one report** of the table above, exits non-zero when any check
   fails, and every failure names a remedy. **An absent model cache is exit 0**, per that table.
   **Verified by mutation**: a stubbed-absent `enable_load_extension` produces the remedy line, not a
   traceback; and the over-long `$XDG_RUNTIME_DIR` that `tests/test_mcp_main.py` already uses
   produces the socket-path check's remedy line and a non-zero exit.
3. The model cache resolves to a durable per-user directory through **Zikaron's own resolver**, which
   honours `$FASTEMBED_CACHE_PATH` itself (fastembed never reads it once `specific_model_path` is
   passed), and a test over that resolver asserts the resolved path is not under
   `tempfile.gettempdir()`, **and that constructing the encoder creates nothing under it** — which is the
   stronger property, since fastembed's `define_cache_dir` would otherwise `mkdir` there. **State the
   mutation rather than saying "must fail against today's code"**: today there is no resolver, so such a
   test fails by `ImportError` and proves nothing. The mutation is *the resolver returning
   `define_cache_dir(None)`*.
4. **The revision (full 40-hex sha) and the hash set are both pinned; `huggingface_hub` joins
   `[project] dependencies` with an exact pin; and the two mismatch branches are proved *distinguishable*
   rather than merely both present.**
   **Expect `tests/test_publication_hygiene.py` to go red the moment those pins land, and do not read
   it as a planted secret.** M28's publication guard forbids 40- and 64-hex runs anywhere under
   `zikaron/`, which is exactly the shape of a pinned revision and a SHA256 set; its assertion text
   names "credential-shaped value", so the failure will describe the pin as one. **Choosing the
   exemption is this milestone's job and was deliberately left here**, because its shape depends on
   where the pins live — one module, a data file, one constant or several — which M28 could not know.
   Pick a per-line marker or a single-file allowlist once the tree exists, and say in the guard's
   docstring which and why. Branch one: a corrupt local copy — corrupted through the snapshot
   path, so the write reaches the blob — triggers exactly **one** `force_download` re-fetch and then
   passes. Branch two: a **source** serving wrong bytes twice (a monkeypatched `hf_hub_download`, or a
   local `HF_ENDPOINT`) fails once, loudly, with its remedy, and downloads nothing further. A test that
   exercises only the first branch is the defect this item exists to prevent — and an executor who
   implements the re-fetch as a delete will fail branch one and may "fix" it by relaxing the test.
   **Plus: a warm start makes no network call**, asserted with `HF_HUB_OFFLINE=1`, which turns any call
   into `OfflineModeIsEnabled` — so the test proves the online fallback was **not reached**. That is the
   assertion protecting M17's cold-start budget, and it holds by construction only because (ii)'s warm
   call passes `local_files_only=True` with a 40-hex sha; the sha alone leaves one `list_repo_tree` call
   possible whenever the tree cache is absent.
5. `design/distribution.md` carries both new sections; D19/D20 amended withdraw-style.
6. `README.md`'s recommended path becomes `uv tool install zikaron`, the git-URL path stays documented,
   and the distribution is **built and verified locally** — `python -m build`, then an assertion over
   the sdist and wheel that **no `research/`, `reviews/`, `experiments/`, `.kiro/` or `FINDINGS*.md`
   content ships**. setuptools' defaults should already exclude them; a test proves it, because this is
   the one place the publication sweep's conclusions could be quietly undone.
   **Uploading is the operator's act**, under the same rule as the push: it needs a PyPI credential.
   Name the mechanism rather than leaving it — trusted publishing from a release workflow, or
   `uv publish` from the operator's shell.
7. **The CI cache key gains the pinned revision — `(model name, revision)`.** The `fastembed` pin may
   leave the key, the on-disk layout under the cache directory being `huggingface_hub`'s rather than
   fastembed's. **The path does not move**: it stays `$FASTEMBED_CACHE_PATH` as M28 sets it.
   *(This item read "a no-op by construction — confirm, do not change" for one round, on review round
   1's finding 8, which review round 2 withdrew as its own defect: that finding predated the revision
   pin and the two do not compose. **`actions/cache` saves only on a key miss**, so a cache populated at
   upstream head `H` keeps hitting a key that does not mention the revision, `snapshots/<R>/` is absent,
   64 MB downloads on every job of every run, and nothing is ever saved back — the exact "cost nobody
   measures until it is a bill" M28's own paragraph names. **The lesson is the corpus's own and it has
   now cost a round twice in one trail: a correction arriving inside a review finding is still a claim,
   and must be re-derived like any other.** I applied this one as given.)*
8. `./check.sh` and `./check-matrix.sh --parallel` green; the macOS job green.

**Fence.** **No install-time model prefetch and no lexical-only degraded mode** — both were considered
and deliberately dropped: the first makes the installer need the network, which today it does not; the
second is a second retrieval configuration to test and document. No vendored weights, which the
fetch-never-redistribute constraint forecloses anyway. No change to the installed command strings. No
Windows, no Intel Macs.

---

## M31 — The knowledge CLI stops opening the store, and the schema learns to move

Normative: `design/knowledge-index.md` §9 and its account of who spawns an indexer;
`design/architecture.md` §Components' indexer row; `design/schema.md` §"Migration posture", which
gains the supported range and the migration contract that section says the first such change must
write; `design/overview.md` D31.

**Invariant 18** — every v0 event is emitted inside a client call — is the one this milestone can
break, because it is what licenses `event.client_kind` to be a closed set at all. A fourth member
that no client call ever writes would make the column's `CHECK` a claim about nothing.

**The knowledge CLI is the only human-facing surface that bypasses the service.**
`zikaron/knowledge/main.py` opens `memory.db` through `knowledge/scope.py:open_store` for all six
verbs, while `service/dispatch_knowledge.py` serves every one of those verbs over RPC already and
`zikaron-mcp` is already a thin client over them. That is two writers against one registry, two
implementations of each verb, and a CLI that cannot create a store at all, because `Store.open` is
`existing_only` and `Store.create` needs the embedding artifact for the vector width. *That last one
is fixed by `zikaron init` (item 9), not by giving the verbs the power: a verb able to start a
service is a verb able to build a second store in whatever directory it was typed in.*

**Operator rule: the CLI is a thin client, and `doctor` is the single exemption.** `doctor` reports
on an installation that may be broken in exactly the way that stops the service starting, so any
store check it grows opens the store directly. It opens none today; the exemption is standing
permission, not a description.

**The indexer keeps its direct open.** It *is* the build, it holds the model for the duration, and
it is spawned rather than typed. What this milestone splits is `scope.open_store`'s two callers: the
CLI's open goes, the indexer's stays.

### The six verbs

| Verb | Method | What the port costs beyond argument marshalling |
|---|---|---|
| `status` | `knowledge_status` | nothing; the result already carries reports and orphans |
| `rename` | `knowledge_rename` | nothing |
| `list` | `knowledge_list` | `KnowledgeListResult` carries no `orphans`, and the CLI prints them for both verbs. Widen the result rather than making `list` call `status`, so the two RPC methods keep answering the questions their names state |
| `add` | `knowledge_add` | the result carries neither the created database's path nor the spawn argv, and **`--path` means different things on the two sides**: the CLI's is relative to the shell, `_corpus_root`'s is relative to the project root. The CLI resolves to absolute before sending |
| `remove` | `knowledge_remove` | `--yes` keeps its spelling and becomes the `confirm` parameter, and the unconfirmed preview arrives as a raised `KNOWLEDGE_CONFIRM_REQUIRED` carrying `{name, state, files_indexed, chunks}` rather than as a result — so the CLI's preview is rendered from an error rather than printed on the way to exit 1 |
| `refresh` | `knowledge_refresh` | `--force-unlock` has no method at all, and the per-corpus refusal text does not survive serialization |

**`--path`'s two meanings is the one silent failure in the table.** A relative `--path` sent
unresolved creates a corpus over a directory the caller did not name, reports `ok`, and answers
searches from it — wrong, permanent and unreported, since the stored root is absolute and looks
deliberate. `_corpus_root`'s docstring already states the rule it applies; the CLI's own help already
states the other. The resolution belongs on the CLI side, where the shell's working directory is.

### What the RPC surface owes the CLI

**`knowledge_unlock(knowledge_base) -> {cleared}`.** `lifecycle.unlock` returns `LockHolder | None`
and both cases are structural: the holder's pid, host and start time, or nothing to clear. A method
rather than a parameter on `knowledge_refresh`, because clearing a lock and building an index are
different acts with different failure modes — a refusal to clear must not read as a refusal to
build — and because `knowledge_refresh` takes an optional name while clearing a lock requires one.

**The spawn argv, per corpus, in `KnowledgeBuildResult`.** The CLI prints a `foreground` line that
reproduces a detached build, and it prints *the argv the spawn reported* rather than a second
construction of it — `_start_build`'s docstring is explicit that the two must not be able to differ.
Once the service owns the spawn, that argv has to come back on the wire or the guarantee is lost.

**A code for a failure that came from outside Zikaron.** `scope.execute` today prints
`failed: <the driver's own error>` for a full disk, a revoked permission or a database that will not
open. Over RPC an `aiosqlite.Error` or `OSError` escaping a handler reaches `server.py`'s
`except Exception` and becomes `INTERNAL_ERROR` / `"internal error handling this request"` with no
payload, and the reason goes only to the service log — which is not a file the person at the shell is
reading. **`STORE_UNAVAILABLE` `{operation, cause}`** carries it: `operation` is the method, `cause`
is the foreign text.

**The rule that admits it, stated in `core/errors.py`: a caller branches on the code, never on
wording.** That is what makes a field safe to fill with a sentence a person reads —
`KNOWLEDGE_BASE_BUSY.holder` already is one. What is forbidden is the inverse: a distinction a
caller must *act* on reaching it only as prose, so that rewording silently changes behaviour. Every
such distinction gets its own code, or a declared field with a closed set of values.

**The rule governs result fields as well as error payloads**, since the same question arises there:
`KnowledgeBuildResult.reason` is a sentence beside `outcome`, and `outcome` is the closed set
anything automated keys on. `store_unavailable.cause` is the one field whose text comes from
outside Zikaron at all.

**`PlannedBuild.refusal` needs nothing.** It is an `Exception`, and `BuildObstacle` is a closed
four-member enum already serialized as `outcome`. Three members — `already_indexing`, `no_database`,
`root_missing` — are fully determined by the enum plus the corpus's status, so the CLI renders its own
sentence. The fourth, `unreadable`, is the driver's own exception, and it is `STORE_UNAVAILABLE`'s
`cause`.

**`scope.execute`'s two prefixes have to be rebuilt from codes.** It branches on Python exception
type today — `KnowledgeError` and `ZikaronError` print `refused`, an `aiosqlite.Error` or `OSError`
prints `failed` — and over RPC every one of them arrives as a wire error. The distinction is worth
keeping and is not cosmetic, and `_report_obstacle`'s docstring already states it: **`refused` is
this system declining something it understood and naming what to do instead; `failed` is a condition
nothing the caller can send differently.** `STORE_UNAVAILABLE`, `SCHEMA_INCOMPATIBLE` and
`STORE_IDENTITY` are on the second side; `BAD_CONFIG`, `STORE_BUSY` and `REINDEXING` are on the
first, each naming an action.

**Which side a code falls on belongs in `ErrorSpec`, not in a table the CLI keeps.** Every surface
that renders a rejection needs the same answer, and a second copy of it is how two surfaces come to
disagree about whether a caller can do anything. A field on the spec makes a new code state its own
side at the point it is declared, where the question is answerable.

### `cli` is a client kind, and that makes this the first schema move

The CLI sends an envelope, and `ClientKind` names only the clients that existed before it. Sending
`mcp` would be inert today — no knowledge handler records an event — and a lie that becomes
load-bearing the first time one does. So **`ClientKind` gains `CLI = "cli"`**, which widens
`_KNOWN_CLIENT_KINDS` by derivation, and `event.client_kind`'s `CHECK` has to widen with it.

**SQLite cannot alter a constraint in place.** Measured on 3.45.1: `ALTER TABLE ... DROP CONSTRAINT`,
`ADD CONSTRAINT` and `ALTER COLUMN` are all parse errors; `ALTER TABLE` supports RENAME TABLE, RENAME
COLUMN, ADD COLUMN and DROP COLUMN, and a `CHECK` lives inside the table's `CREATE TABLE` text. The
two routes that do work, timed against `~/Trading/LeibaTrader` (25,836 events, the largest store in
existence) on a `VACUUM INTO` snapshot:

| Route | Cost | Verified |
|---|---|---|
| the 12-step rebuild — new table, copy, drop, rename, recreate the five indexes | **~530 ms** | `integrity_check ok`, 25,836 rows |
| `PRAGMA writable_schema` rewrite of `sqlite_schema.sql` plus a `schema_version` pragma bump | **~2 ms** | `integrity_check ok` |

Both accept `cli` and still refuse a bogus value. Re-derive with
`.venv/bin/python spikes/m31_check_widening.py`.

**Take the 12-step.** The fast route buys half a second once per store by bypassing every validation
SQLite has — a malformed `sql` string leaves a schema nothing checks until the next open — and half a
second is affordable where it lands. The migration runs before the socket binds, and
`hook/connect.py:HEALTH_POLL_DEADLINE_SECONDS` is 1.2 s against a cold context build measured at
3.74 s, so a cold start is already past the hook's budget and the hook already degrades. It is paid
once, on the first service start after the upgrade, and is invisible to every surface that was not
going to wait anyway.

**`meta.schema_version` becomes a range, which is what `schema.md` says the first such change gets.**
That section reads *"The first version that needs to open more than one schema gets an explicit
supported range plus a migration or capability contract, written then"* — this is that change.
Version 2 is the widened `CHECK`. The contract:

- **Only the service migrates.** `service/context.py` is the one opener that holds the store at
  startup with write intent, so `Store.open` grows a parameter and only that call site passes it.
- **Every other opener accepts the range read-only.** `knowledge/scope.py` for the indexer and
  `mcp/connection.py` for the identity read open a store at either version and migrate neither. A
  store at 1 reached by the indexer is a store the service created and has not yet reopened; the
  indexer writes no events, so the narrow `CHECK` constrains nothing it does.
- **Above the range still refuses** with `SCHEMA_INCOMPATIBLE` `{found, supported}`, whose
  `supported` field stops being the constant `1`.
- **Downgrade is not offered.** A store at 2 meeting a binary that supports only 1 is refused, which
  is the gate working. `0.1.0` is one day old and has one user; the alternative — leaving the range at
  1 and converging by introspection on every start — trades a recorded fact for a re-derived one.

### Waiting, and the container case

**`refresh --wait` polls `knowledge_status` until the build is over.** No new method, no new
parameter on `knowledge_refresh`, and nothing spawned by the CLI: the build detaches exactly as it
does today and the CLI stops returning early. The embedder never enters the CLI's process because
nothing about this runs there.

**The predicate is not "while the state is `indexing`".** `state.PRECEDENCE` puts `REINDEX_REQUIRED`
ahead of `INDEXING`, so a corpus being rebuilt after an encoder mismatch reports `reindex_required`
for the whole build, and a wait keyed on `indexing` would return before it started. The build is over
when **its lock is gone** — `status`'s `details.lock`, absent or reclaimable. And "gone" alone is not
enough either, because a lock is taken shortly *after* the spawn, so a fast first poll sees no lock
and calls a build that never began finished. **`last_scan_started_at` closes that race**: the indexer
writes it when it starts, so the wait ends when that value has advanced past what it was before the
refresh *and* the lock is gone. The terminal `KnowledgeState` then decides the exit status — `ok` is
0, everything else is not.

**That is the whole CI answer, and the lock lease is deliberately not part of it.** A build lock
records a pid and a host, and `lock.probe` returns `None` — *this machine cannot say* — whenever the
recorded host is not this one. A container gets a fresh hostname per run, so an indexer killed at
step end strands a lock the next container can never reclaim without `--force-unlock`. Same-host CI
self-heals: the pid is probed, found gone, and the lock reclaimed. **`--wait` removes the
mid-flight kill** rather than the stranding, which is enough: the remaining path to a stranded lock is
a step that times out, which is a failure either way. An age-based lease would trade a stranded lock
for a stolen one — a build genuinely running on another host, cut off mid-write — and the case that
needs it, one `.zikaron` shared live across hosts, is not a case this design supports.

**A waiting CLI holds the service open, and that is the point.** `idle_timeout` counts from the last
touch and a poll is one, so the service outlives the build rather than expiring under it.

**The build still detaches under `--wait`, and a CLI that dies mid-wait leaves it running.** That is
the same situation as an agent calling `zikaron_knowledge_refresh` over MCP and then ending its
session, which is already how this works and is correct: the caller asked for a corpus to be built,
not for a process to be supervised. `--wait` adds a caller that chooses to stay.

**Done when:**

1. `zikaron knowledge`'s six verbs reach the store only through `ServiceConnection`, and the indexer
   is `knowledge/scope.py`'s only remaining caller. **Verified by a test that runs every verb against
   a project with no service running** and asserts each one starts it and succeeds — against a
   project `zikaron init` has created a store in, which item 9 makes the precondition for all six.
   Creating a store in a project that never had one is the case the direct open could not serve and
   the reason for the change; item 9 is where it ended up.
   `ErrorSpec` carries which side of refused/failed a code falls on, and `scope.execute` renders from
   that rather than from an exception type.
2. `knowledge_unlock` exists, `KnowledgeListResult` carries `orphans`, and `KnowledgeBuildResult`
   carries the created database path and the per-corpus spawn argv. **The argv is asserted equal to
   what `detach.spawn` reports**, not merely present, since a second construction is the defect the
   `foreground` line exists to avoid.
3. `STORE_UNAVAILABLE` `{operation, cause}` is raised where a knowledge handler meets an
   `aiosqlite.Error` or `OSError`, and the CLI renders it as `failed: <cause>`. **Verified by
   mutation**: with the raise site removed the same scenario reaches `INTERNAL_ERROR` and the CLI
   prints nothing actionable. `core/errors.py` states the prose rule.
4. `ClientKind.CLI` exists, `event.client_kind`'s `CHECK` lists it, and the CLI's envelope carries
   `kind: "cli"`. **A test writes an event under each of the four kinds against a store created by
   this build and against one migrated from version 1**, since those are two different tables. It
   writes at the store layer rather than through a verb: no knowledge method records an event, which
   is exactly why the widened `CHECK` has no other coverage — and why invariant 18 is worth re-reading
   before adding a member that no call site produces.
5. `meta.schema_version` supports `{1, 2}`; the service migrates 1 → 2 at open and no other opener
   does; `> 2` refuses with `SCHEMA_INCOMPATIBLE` naming the range. **Verified on a store built at
   version 1**, migrated, and then read by every opener — not on a fresh store, which never exercises
   the step. Migration is idempotent: a second open at 2 does nothing and costs nothing.
6. `refresh --wait` returns when the build is over and exits on the terminal `KnowledgeState`;
   without it the behaviour is unchanged. **Verified against a build that never takes its lock** —
   the spawn race above — which must not report success, and against one that fails, which must not
   report it either.
7. Every document that states the direct open or its rationale is corrected:
   `knowledge/scope.py`'s module docstring, `knowledge/main.py`'s,
   `design/architecture.md`'s indexer row — **reworded, not deleted**, since the indexer's own entry
   point is still shell-started and still direct — `design/overview.md` D31, and
   `design/knowledge-index.md` §9 together with its unreadable-`memory.db` row, whose two halves
   become one route once the CLI *is* the RPC path. `design/schema.md` §"Migration posture" carries
   the range and the migration contract, replacing the single-version table rather than appending to
   it.
   **Grep locates the candidates and does not decide coverage**: state each change as a before/after
   pair of propositions, write down what the old one licensed, and check each conclusion by meaning.
8. `_store_not_created`'s remedy is corrected rather than deleted. The condition does not go away: it
   is the `connect_failure` of every `Store.open`, and `python -m zikaron.knowledge.indexer` run by
   hand in a storeless project still reaches it. What stops existing is the CLI's route to it.
9. **`zikaron init` exists and is the only typed command that creates a store; every `knowledge` verb
   refuses a project that has none.** The predicate is `memory.db` rather than `.zikaron/`, since
   the service creates the directory for its log before it creates the store — **covered by the
   state a failed first start leaves**, where the directory test would report *already initialized*
   for a store that does not exist. The check runs before the connection rather than after a
   failure from it, since reaching the service is what creates a store — **verified by a test that
   asserts the refusal leaves no `.zikaron/` behind**, which a check placed after the connection
   would fail. `init` refuses a `--project` that is not a directory, since `ensure_store_dir` is
   `mkdir(parents=True)` and the verbs' own refusal ends by offering `init`. The refusal names which rung of D17's ladder resolved the directory, because a wrong
   `CLAUDE_PROJECT_DIR` is not repaired by changing directory. It may name a store found above it
   and must bind nothing — **covered by the monorepo shape**, where a sibling package's store is
   neither offered nor adopted. `init` is idempotent.

10. `./check.sh` and `./check-matrix.sh --parallel` green.

**Fence.** **No `search` verb on the CLI** — `knowledge_search` is served and the port would be
cheap, but it is a new human surface with its own output design, and this milestone is a move rather
than a widening. **No age-based lock lease**, for the reason above. **No store checks in `doctor`**:
the exemption is granted, nothing yet needs it. **No migration framework** — one ordered step and the
range that admits it, not a registry for steps nobody has written. **No change to the memory verbs or
their tools**, which never had a CLI.

## Standing notes for whoever picks this up

- **`shard_count` is flagged as possibly unnecessary** — a persisted count an invariant then polices, derivable
  as a `COUNT(*)`. Left in place pre-code deliberately. If M7 finds it genuinely redundant, that is a design
  change to propose, not to make silently.
- **Open questions in `FINDINGS.md` are open on purpose.** Open question 2 (RRF arm weighting) needs no
  reindex, so it is deliberately post-build. Do not tune fusion during M5.
  *This read "is the largest known quality lever" until 2026-09-18. M25 swept exactly those parameters on the
  knowledge index and found none worth moving **on the one query family measured valid** — best cell +0.0069
  MRR@10 against a 0.02 bar, while 48 cells cleared that bar on the pooled metric the sweep had actually
  preregistered (`research/m25-fusion-sweep.md`). Different store, so open question 2 is untouched and still
  open; the superlative went because it was stated of fusion tuning generally and the point here never rested
  on it.*
- **The design is normative; where code and design disagree, one of them is a bug.** Decide which, fix that one,
  and re-index the knowledge base if it was the design.
