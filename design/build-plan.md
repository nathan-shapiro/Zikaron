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
`--force`; the collision and backup behaviours are exercised identically against both targets, and
refuse-on-difference against each target's own predicate (`architecture.md` §"The install contract");
and the Claude Code install reports both the `.mcp.json` approval step and the primary agent's
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
   `aiosqlite.Error` that is not contention, or an `OSError`, and the CLI renders it as
   `failed: <cause>`. **Verified by
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

## M32 — The injected prose, and the field that makes the next one measurable

Normative: `design/retrieval.md` §"Push output format"; `design/write-policy.md` §2, which becomes
two fences; `design/schema.md` §"The `event` log, per kind", whose `surface_call` row gains a field;
`design/architecture.md` §"MCP tool surface (the five memory verbs)", whose mechanics-versus-policy
split this milestone moves; `design/harness.md` §Subagents. The authored replacement text is
`reviews/injected-prose-review.md` §Round 2 and is the input to this milestone, not its output.

**The read path is not used and the prose is the first suspect.** Of `(session, uuid)` pairs
surfaced and then written to in the same session, excluding pairs D26 compelled a fetch for, the
agent read the record first in **1 of 363** before the current preamble landed and **0 of 47**
after (`experiments/read_path_baseline.py`). The instruction to fetch is present, twice, and that
is what it achieves. D13 designed the gist to point at a record the agent then reads; on this
evidence **the gist is the whole memory**.

### The field comes first, and the reason is a measurement that already failed once

`surface_call.detail` (`design/schema.md:658`) carries twelve fields about how retrieval ran and
**nothing about which preamble the push rendered**, which `design/retrieval.md` states outright. So
the only available comparison is by timestamp, and a timestamp split bundles the text change with
the store's growth, the week's tasks and the harness. That is not hypothetical: the first attempt at
the baseline pooled both periods and reported 2.49%, six to nine times the true rate, and finding
the boundary at all needed archaeology into a service-restart instant recorded in
`FINDINGS-archive.md`.

`surface_call` is the cheap row to stamp — one per push against `surface`'s one per memory, 4,072
against 20,290 on `~/Trading/LeibaTrader`. **Add one field naming the rendered variant.**
`tests/test_event_kinds.py` parses the design table and asserts `EVENT_SPECS` matches it, so the
table and the constant move together or the gate reddens.

**Stamp a digest of the rendered preamble, and keep exactly one constant.** The field is a short
hash computed from the text the service just rendered, not a hand-assigned id and not a selector
between variants. It cannot drift from the text it names, it needs no maintenance, and it deletes
the superseded prose on schedule like everything else here. A second constant kept alive to be the
old arm would be the one thing this corpus has a standing rule against: a copy nobody maintains,
which the next reader must rule out.

**A digest is opaque, so it needs a decoder: `research/injected-prose-log.md`.** Append-only, one
entry per version — the digest, the date it went live, the exact rendered bytes in a fence, and one
line on what changed. Without it the field says only that two rows saw different text, and
recovering *which* text means the git archaeology this milestone exists to stop. This does not
reopen the superseded-prose rule: the log is **data rather than belief**, read to decode a column
and never for instruction, and its entries are **frozen at write time**, so unlike maintained prose
there is nothing in it that can drift. The gate holds its head honest — the test that asserts the
digest tracks the constant also asserts the live constant has an entry whose bytes reproduce it, so
the log cannot fall silently behind the code.

**That gives up within-period alternation, which was never powered.** `~/Trading/LeibaTrader`
produced 47 eligible pairs in the four days after the last change, and alternating arms halves that.
Only a move from ~0.3% to roughly 10% — a factor of thirty — is detectable there inside a week, and
a move that large is not something the store's growth or a week's tasks produce, so a before/after
comparison carries it. Anything smaller is undetectable on this store either way, and the arms would
buy precision the sample cannot supply. What the digest does buy is the thing that actually broke
the first attempt: every row says which text it saw, so periods are bounded exactly and forever,
with no archaeology into service-restart instants.

### The three surfaces

| Surface | Shipped | New | Budget |
|---|---|---|---|
| Push block framing | 829 | 498 | — |
| `agentSpawn`, main agent | 6,569 | 2,929 | 66% → 29% |
| `agentSpawn`, subagent | 6,569 (identical) | 2,860 | 68% → 29% |

UTF-16 units, the unit `HarnessSpec.exceeds_injection_budget` counts. Four changes carry the
argument, and each is a claim this milestone is betting on:

- **A tag pair, not a Markdown heading.** `## Project memory — reference only` is the commonest
  shape of text a model reads and writes. The block also lands *after* the user's message on Claude
  Code and *before* it on kiro, so it needs bounding at both ends: `HEADER` becomes an opening tag
  and a new `FOOTER` closes it.
- **"headline", not "abstract".** An abstract is the one summary form convention treats as
  sufficient to cite, so the shipped text names the gist with the word for the behaviour it is
  trying to stop. "Title" was considered and rejected: `design/write-policy.md` demands claim-shaped
  gists, so a frame calling the line a label is contradicted by every line beneath it. A headline is
  claim-shaped and is understood not to be the article. **The write policy's instruction does not
  move; only its noun does.**
- **The trigger is read-time task relevance**, replacing *"before you state one as fact"*, which
  names an event the model does not detect. `block.py`'s rejection of a *resemblance* test stands —
  task relevance is not belief resemblance.
- **The write-time rules move to `zikaron_memory_remember` and `zikaron_memory_amend`.** The gist
  bound, expiry-in-gist, secrets, observations-not-orders and subject-not-quote all govern the text
  of an argument, and a tool description is in context exactly when that argument is being filled.
  **That premise was unverified when this milestone relied on it.** Claude Code defers MCP tools when
  the tool list is crowded, so a description then arrives only when the verb is loaded; the install now
  writes `alwaysLoad` to exempt both
  servers (`design/harness.md` §"MCP tools may arrive deferred"). Noted because a reader would otherwise
  take the delivery for granted, which is what this milestone did.
  It also costs no injection budget, being cached prefix rather than hook output. Q18 recorded two
  of three writes lost to the 64-token bound, at a call site whose description never mentioned it.

**Two spawn variants.** The shipped text tells subagents *"If you were spawned as a subagent,
nothing is injected for you at all"* — delivered, in full, to subagents. The code already knows the
addressee (`subagent_policy.run` is a separate path), so `resolved_policy_text` takes the event and
the second paragraph differs. Every other paragraph is shared.

### Invariants and what can break

Invariant 10 — events inside the transaction they describe — is untouched; this adds a field to an
existing row, not a row. The exposure is elsewhere. `design/write-policy.md` §2's fence must move
**byte-for-byte** with the constant (`tests/test_hook_write_policy.py`), and it is now two fences
under two sub-headings. `tests/test_install_assets.py` pins eleven phrases that currently live in
the spawn text and will live in a tool description; each must be present verbatim at its new home or
deliberately re-pinned. `tests/test_install_limits.py` reads a byte figure out of a comment in
`zikaron/hook/limits.py` and another out of a heading in `design/architecture.md`; both are restated
for two variants. The full list of code lines, design passages and tests is
`reviews/injected-prose-review.md` §Round 2 §4.

### Done when

`./check.sh` and `./check-matrix.sh --parallel` are green; the three surfaces carry the new text and
the gate's phrase pins name their new homes; `surface_call.detail` carries the preamble digest in
both the design table and `EVENT_SPECS`, and a test asserts the digest tracks the constant rather
than being written down beside it; `research/injected-prose-log.md` exists with its first entries,
and the gate refuses a live constant with no entry reproducing its bytes; the two spawn variants are
delivered by addressee and a test asserts the subagent envelope carries the subagent constant; the
superseded prose is deleted from the code rather than kept as an arm;
`experiments/read_path_baseline.py` splits on the digest rather than on `--cut`; and every figure
this milestone moves is re-measured rather than restated.

### Scope fence

**Not in this milestone:** any change to what push *selects* — `surface_min_score`, a relevance
floor, `rrf_k`, `fusion_depth` (Q2). The habituation finding is real and structural, and moving the
selection at the same time as the text would confound the one comparison this milestone exists to
make possible. **Not** the structural options in §Round 2 finding 12 — pull returning `content`
(amends D5), push injecting rank-1 `content` (amends D12) — both are design changes needing the
operator, and both are cheaper to judge once the rewritten prose has reported. **Not** the M32
evaluator candidate;
a `preToolUse` gate cannot see an assertion, and no tool is called at the moment a claim is written.
**Not** running the A/B: this milestone makes it possible and leaves it to a later one.

## M33 — Everything we care about is instrumented, or is deliberately not

Normative: `design/schema.md` §"The `event` log, per kind" and §"Migration posture";
`design/knowledge-index.md` §"8.4 Management tools"; `design/architecture.md` §"Service RPC surface".
`design/overview.md` D27 fixes provenance at `created_at`/`updated_at`/`session_id` and this
milestone does not touch it: what is added is *events about calls*, not fields on records.

**Half the product records nothing, and this was found by trying to read a result off the store.**
A session on `~/Trading/LeibaTrader` reported searching both stores; the event log showed no `search`
at all, and the conclusion drawn — that the agent had named a tool it did not call — was wrong,
because `zikaron_knowledge_search` emits nothing and cannot be contradicted. **An uninstrumented
surface does not read as absent, it reads as evidence against the user.** That is the failure this
milestone exists to remove, and it is worth more than the counts it will produce.

### Instrument the seam, not the verbs — every endpoint, by default

**Operator decision: every service endpoint records that it was called.** Not a judgement per verb
about whether that one is interesting. The reason is not the metric, it is where the instrumentation
lives: `server.py`'s `_METHODS` merges the three dispatch tables into **one** mapping, and a call
logged *there* covers every method by construction. A method added later is instrumented because it
is in the table, not because somebody remembered — which is precisely how the knowledge verbs became
dark. Per-verb instrumentation makes completeness a matter of discipline; seam instrumentation makes
it structural, and a test can assert the two are the same set.

**The surface is 19 endpoints and 8 of them emit nothing today** — every knowledge verb:

| Table | n | Emits an event today |
|---|---|---|
| `PRIMARY_METHODS` | 6 | `memory_remember`/`amend`/`retire`/`search`/`surface`/`fetch` all do, semantically |
| `CONSOLIDATOR_METHODS` | 5 | all do |
| `KNOWLEDGE_METHODS` | 8 | **none**. `dispatch_knowledge.py` contains no `log_event` |

**One new kind for the whole surface, not one per verb.** A `call` event naming the method, emitted
at the seam, its fields fixed by §"The call event's shape" below. That widens `event.kind` once
rather than once per verb, and it answers the question this milestone was scoped around — *was the
endpoint called* — for all 19 at once. A second kind, `knowledge_build`, covers the expensive
operation that is not an endpoint at all (§"What the seam does not reach"); the two ship in one
migration because the rebuild is what costs, not the kind.

**It also dissolves two questions that would otherwise need their own answers.** A `BOUNDS` rejection
becomes a `call` event naming `memory_remember` and that error code, with no bespoke `refused` kind
and no event naming a row that does not exist — Q18's "three calls recorded one" closes. And "what
does a knowledge event name?" stops being a question: a call event names a **method**, not a memory,
so `memory_uuid` stays null and nothing has to generalise.

**The existing kinds stay, and are a different thing.** They are semantic — *this memory was
amended* — and a call log is an access log. Both are wanted: the first says what happened to the
store, the second says what was asked of it, including everything that was asked and refused.

**Price the volume before committing to it.** A `call` row per `memory_surface` is one extra row per
user message; `~/Trading/LeibaTrader` has 4,079 `surface_call` rows, so the order of magnitude is
thousands per store per month, against 26,300 events today. Almost certainly fine, and worth
measuring rather than assuming — `schema.md` §"Retention" already carries a measured growth figure,
and it predates `call`, so **re-derive it on the migrated snapshot that spike uses**
rather than scaling the old one: the multiplier depends on a project's mix of calls.

### A production defect this milestone also fixes: the installer is silent about agents that cannot see it

**Found in `~/Dividends` on 2026-09-27.** An `opus` subagent with persistent state files — exactly
Zikaron's workload — reported that it could not call the memory tools. Everything Zikaron writes was
correct: schema 2, service warm, 10 `surface_call` events proving the hook pushed, the MCP server
exposing 12 tools against that scope, both `enabledMcpjsonServers` and `permissions.allow` present,
and the session started 26 seconds *after* the install so it read the config. The store held **zero
memories**.

The cause was in a file the installer does not write. `.claude/agents/income-quant.md` carries an
explicit `tools:` allowlist, authored before Zikaron existed, and **an explicit list overrides the
project-wide inheritance the Claude Code target relies on.** §"The installer's two targets" documents
all four artefacts and the two-key approval dance and says nothing about this case; it was never
modelled. kiro has no equivalent gap because its entries go *into* an agent config and `--agent`
makes the merge explicit.

**The fix is to report, not to edit.** A user's allowlist is a deliberate grant — the one here
excludes `Task` and every `mcp__*` — and an installer that widens it so its own tools are reachable
is making a security-adjacent decision on the user's behalf, which is the same reasoning Zikaron
applies in reverse when it keeps the consolidator's grant narrow. So: scan `.claude/agents/*.md` at
install time, and for each agent whose frontmatter sets `tools:` without a grant of Zikaron's own
server, print a line naming it — in the voice of the existing post-install notes, which already tell
the user what to check when tools are absent. One line of install output replaces the hour this took
to diagnose.

**The predicate has to be exact, because a prefix test fails silently in the expensive direction.**
The consolidator's server is `zikaron-consolidator` (`install/entries.py`), so `mcp__zikaron` is a
prefix of `mcp__zikaron-consolidator__…` — and an agent granted *only* consolidator tools would pass a
`startswith` check while still being unable to see a single memory verb. **An entry counts iff it is
`mcp__{MCP_SERVER_NAME}` exactly, or begins `mcp__{MCP_SERVER_NAME}__`**, both derived from the
constants the installer writes rather than typed as literals.

**And the scan skips the one agent the installer writes itself.** `install/targets.py` ships
`.claude/agents/{CONSOLIDATOR_AGENT_NAME}.md` with exactly the narrow grant D32 requires, so a scan
that did not skip it would name Zikaron's own artefact as unable to see Zikaron — on every install,
in the false-positive direction this paragraph calls one of the two that cost most. It is matched on
the filename derived from that constant. **Every *other* agent holding only the consolidator's grant
is still named**: that grant belongs to the consolidator alone. The scan runs after the installer's
own writes, so a first install and a re-install report the same set.

Fixtures prove each direction: `income-quant.md`'s own frontmatter (named), an agent listing only
`mcp__zikaron-consolidator__…` (named), one listing `mcp__zikaron` (not named), the installer's own
`consolidator_agent_markdown(...)` output (not named) — rendered through that function rather than
hand-typed, per `CLAUDE.md` §Harness — and the inline comma-separated spelling of each.

**The form the post-install line advises is already measured.**
`research/claude-code-installer-probe.md` §7 established that a whole-server wildcard in subagent
frontmatter grants that server's tools and excludes others, in the block form the installer ships;
`install/entries.py` cites it as the reason the consolidator's own frontmatter is written that way,
and `research/m30-docker-end-to-end.md` exercised it under a real subagent. The residual is only that
it was measured for `zikaron-consolidator` rather than `zikaron` — the same mechanism, a different
server name. So the line can say *add `mcp__zikaron`, the form the installer's own agent uses*.

**Scope note**: detection only, on the Claude Code target, over the **project's** `.claude/agents/`.
Nothing edits a user-authored agent, and `mcp__zikaron-consolidator` is never suggested — that grant
belongs to the consolidator alone. **Two cases are out of scope and deliberately so**: an agent with
no `tools:` list and
`disallowedTools: mcp__zikaron` is equally blind and will not be named, and neither will a
**user-level agent under `~/.claude/agents/`**, which takes the same frontmatter, is usable in any
project, and sits outside a scan of the project's directory. Said here so the next person to diagnose
either knows it was considered rather than missed.

**`zikaron doctor` runs the same scan, and that is where it earns most of its keep.** The install
sees the agents that exist on the day it runs; `income-quant.md` pre-dated its install, but the next
blind agent will be authored a week *after* one, and an install-time-only check never sees it. Doctor
already reports install health, so this is the same function behind a second caller rather than a
second implementation. It **runs when `<project>/.claude/agents/` exists** — a directory condition,
since `doctor` takes `--project` and no `--harness` — and reports **`REPORTED`, never `FAILED`**: an
allowlist that excludes every `mcp__*` on purpose must not make `doctor` exit non-zero forever.
**Two documents are normative and both are updated**: `design/harness.md` §"What the install reports
rather than enforces" for the predicate, the consolidator skip and the `disallowedTools:` exclusion,
and `design/distribution.md` §"The front door", whose ordered list of checks `doctor/checks.py`'s
`run_all` binds itself to. Adding a check without that entry is the omission this milestone is
already fixing one document over.

**This is the first thing the installer reads rather than writes, and the parsing rule is load-bearing.**
`install/assets.py` states that Zikaron emits frontmatter needing "no assumption about which YAML
features the harness's own frontmatter parser supports", and the package carries no YAML dependency
at all. Reading a third party's agent file inverts that, against files the harness accepts and a
strict parser does not: an agent's prose body follows the frontmatter and is not YAML, so **only the
block between the first `---` and the next `---` may be parsed**, never the file — **and only when the
file opens with one.** A file that does not has no frontmatter at all, so it sets no `tools:` and
inherits everything; parsing between two horizontal rules in its body would be reading prose as YAML.
Claude Code accepts
`tools:` as a block list and as a comma-separated inline string, so both forms have to resolve or the
scan reports the wrong agents. **A YAML flow sequence — `tools: [Read, mcp__zikaron]` — is a third
spelling**, and a scanner treating the inline value as comma-separated text yields `[Read` and
`mcp__zikaron]`, matches neither, and names an agent that is fine. Strip enclosing brackets from the
inline form. A mis-parse fails in the two directions that cost the most: naming an
agent that is fine, or staying silent about the one that is broken — which is the diagnosis this
scan exists to shorten.

### What the seam does not reach, and which of the two is instrumented

Two surfaces are not endpoints, and they are decided in opposite directions.

**The indexer is instrumented, and it costs more than one `log_event` call.** A corpus build is the
most expensive operation the product performs and nothing records that one happened. `scope.py`
already opens `memory.db` directly — the one thing in `zikaron/knowledge/` that does — so there is no
thin-client property in the way. What *is* in the way is that a build is not a client call, and
`schema.md` is written throughout on the assumption that every event is one.

- **`client_kind` gains `'indexer'`**, a second `CHECK` widening in the same migration. None of
  `'hook'`, `'mcp'`, `'consolidator'` or `'cli'` is true of a spawned build, and filing it under one
  of them would corrupt the linkage signals that read that column.
- **The build mints its own `session_id` and `op_id`**, as the service does for a bootstrap envelope.
  The alternative is a NULL `session_id`, which invariant 18 closes by saying nothing in v0 writes
  one; a minted label keeps that true and keeps every column `NOT NULL` that already is.
- **Every sentence asserting that an event comes from a client call stops being true**, and so does
  the note that `'cli'` records no event — `call` puts every typed `zikaron knowledge` verb into the
  log. That claim is in the DDL comment, in `core/events.py`'s `ClientKind` docstring, in
  **`ClientKind.CLI`'s own member comment** — *"It records no event today"*, a separate sentence an
  editor of the docstring will not see — and in the per-kind section's own preamble; all four are
  rewritten with the CHECK, and the done-when names the further sentences in `architecture.md` and
  `knowledge-index.md` that followed from it.

**The event is `knowledge_build`**, keyed by the registry **`id`** rather than the name — `knowledge_rename`
exists, and a cost history keyed by a renameable field breaks at the rename. It carries the outcome, the
duration, `files_indexed`, and **both `full` and `rebuilt`** — the flag asked for and whether the encoder
identity forced a whole-corpus reindex anyway, which happens at `full=false` and would otherwise file those
minutes under "incremental". `files_indexed` is the count in the base's own `meta` — and `ScanCounters`
resets per scan, so `meta` answers *what does this corpus look like now* while only the log can answer
*what has building it cost over time*, which is the question a build event exists for. `schema.md` pins
what each of the three work fields means, since each is ambiguous in the direction that flatters the
history.
It also carries **`spawned_by_op_id`**, the `op_id` of the verb that spawned it, **passed through the
environment rather than the argv** and null when none was set. Without that edge nothing joins a build's
cost to the requester, since the build mints a label of its own and only the spawning `call` row knows
whether an agent or a person asked. The channel is forced: `detach.spawn` returns the argv the child ran so
that what `knowledge-index.md` §8.4 prints *is* what ran, and a flag stripped from the printed form would
break that identity — while an attribution token is not an input that changes what a build does.
**`error_code` shares `call`'s vocabulary while the numeric codes stay at the boundary**: each
`KnowledgeError` gains a `wire_name` string in `core/knowledge/errors.py` and no code, which is what that
module's docstring already argues for and what keeps `dispatch_knowledge` *"the boundary that gives them
codes"*. A test asserts each class's `wire_name` equals that of the `ErrorCode` the boundary maps it to, so
one condition keeps one name mechanically. Moving a class → `ErrorCode` table into `core/` would make
agreement unbreakable rather than checked, and was rejected: it falsifies the stated rationale in two module
docstrings, and a design should not rewrite two arguments to save one test. `schema.md` §"What is
instrumented" has the per-class rule — a `KnowledgeError`'s own `wire_name`, a `ZikaronError`'s
`code.wire_name`, `build_failed` for the unnamed remainder — the disjointness test, and the
`IndexerBusyError` case — raised as the call's own `knowledge_base_busy` by `remove` and `unlock`, on
opposite readings of the pid, but a per-corpus outcome inside a *succeeding* `refresh`/`add` and so landing
in no event at all, an accepted gap, stated.

**`build()` binds the registry id itself** — `registry.ensure`, then `require`, outside the `try` that
guards the rest — so a refusal reaching no id writes no row and everything raised after it is written
under that id whatever its class; `schema.md` §"What is instrumented" has why that split is positional
rather than by class, and why `ensure` is not optional. **And the build decides by version**: it
attempts the row only if the store it opened is at 3 or above, read from the `schema_version`
`OpenStore` carries, rather than writing one and catching the `CHECK`.

**A payload spill stays silent — operator decision.** `mcp/spill.py` emits nothing and
`zikaron/mcp/` imports no logger *by design*; telling the service would be a new RPC on the one path
that exists to keep that client thin. What makes the silence affordable is that the failure it would
report is already observable from the store: a payload the consolidator cannot be served leaves the
group undispositioned, so it is re-served until `serve_count` reaches `max_group_serves` and the
group becomes `deferred`. `spill_threshold` is therefore judged by that terminal state rather than by
a spill event, and deferred groups are the query to run.

**Both decisions go into `schema.md`'s boundary note**, the silent one with its reason and its proxy.
A decision left unwritten is read as an oversight by the next person, which is the mistake this
milestone exists to stop making.

### The cost is a schema migration, and that is the whole shape of the work

`event.kind` is a SQL `CHECK` over a closed set (`schema.md`'s DDL), written once per store and then
resident on disk. SQLite cannot alter a constraint in place — `ALTER TABLE … DROP/ADD CONSTRAINT` and
`ALTER COLUMN` are parse errors on 3.45.1 — so any new kind is the 12-step table rebuild, measured at
**~530 ms** against a 25,836-event store, and a `schema_version` bump to **3**.
`core/store/migration.py`'s `_widen_event_client_kind` is the precedent: M31 did exactly this to
widen `client_kind`, in one transaction, and D37 fixes the posture — only the service migrates, and
nothing migrates back.

**So kinds are added once, together.** A milestone per event kind would pay the rebuild per kind and
strand every store at a different version; the reason to enumerate the whole surface first is that
the migration is the expensive part and it is amortised across everything added in it.

**The published `0.1.0` already refuses schema 2, so it will refuse 3 identically** — no new class of
breakage, and `~/Trading/LeibaTrader` is already past it. Say so in the release notes rather than
discovering it again.

### The call event's shape, and what it deliberately omits

`call` carries `{method, ok, error_code, duration_ms}` with `names_memory=False`. What follows fixes
every part of that, so none of it is left to the code.

**It carries a duration, measured across the handler alone.** The seam is the cheapest place this
project will ever have to record latency, and every budget here is a latency budget —
`push._DEADLINE_SECONDS`, the health poll, M30's cold-start arithmetic — each of which needed a
bespoke harness because the store could not answer it. Envelope resolution is excluded: it is paid by
every call alike, and folding it in makes the figure less comparable without making it more true. The
standing hazard is the one `CLAUDE.md` §"Measure before you assert" names, a duration quoted without
the load it was measured under; the answer is that this field is a population to compare against a
control, never a number to cite on its own.

**It carries no argument values.** A `knowledge_search` query and a `memory_remember` gist are user
prose, and `design/write-policy.md`'s secrets boundary exists because this store is plaintext on
disk. Sizes and counts only — `search` already records `query_chars` rather than the query.

**`error_code` is stored as the name, its reachable domain declared in `EVENT_SPECS` as strings, and
its call site typed across both enums.** `ErrorCode` holds the domain refusals and `rpc.ProtocolErrorCode` the
protocol ones; a handler that raises what neither anticipated is answered `INTERNAL_ERROR` from the
second, which is a call that reached a handler and crashed and precisely what an access log is for.
**The *reachable* domain is narrower than the type** — `ErrorCode.wire_name` plus `internal_error`
alone, since the exits enumerated below decide every other protocol code before dispatch — and `schema.md` says
so, because a query is written against what can occur rather than against what the signature admits.
What follows is fixed here rather than in the code:

- **The stored value is the snake_case name** — `bounds`, `internal_error` — not the wire integer.
  `search.detail` already stores readable values, and a signal query written against `-32005` is a
  number nobody can check. `ErrorCode` has `wire_name`; `ProtocolErrorCode` gains the same property.
- **`EVENT_SPECS` keeps a real closed set, because `DetailField.values` holds strings rather than
  enum members.** The layering rule blocks importing `ProtocolErrorCode` into `core/`, not naming the
  one string a dispatched call can produce: the field declares every `ErrorCode.wire_name` —
  importable there — plus the literal `internal_error`, and `nullable=True`. A test asserts that
  literal equals `ProtocolErrorCode.INTERNAL_ERROR.wire_name`, which a test may do because it sits
  above both layers. **One literal is not a restated enumeration.** The seam's converter stays typed
  `ErrorCode | ProtocolErrorCode -> str` so `mypy --strict` refuses a bare string at the call site.
  This field's runtime check is therefore as strong as every other detail field's, and `log_event`'s
  promise of one holds without exception.
- **And the drift guard has to learn how the table states that set, or no implementation of it can
  pass the gate.** `test_detail_value_sets_match_the_design_table` binds every declared `values` to
  what its table cell states and treats a silent cell as `()`, so the composed tuple above is red;
  spelling every `ErrorCode` member plus a literal into the cell is the restated-enumeration defect
  and then fails the enum-backed-sets guard. So `parse_payload`'s beside-the-group form gains a
  **marked reference** — `` `error_code ∈ @ErrorCode.wire_name \| internal_error` `` — **marked
  because a bare token in that form already means a literal**, as `architecture.md`'s error table has
  written since before this milestone and `test_design_tables.py` pins; `@` appears in no `∈` span
  this milestone did not write, so it collides with nothing pre-existing.
  `parse_payload` returns it **unresolved**, and what resolves it imports nothing from the package:
  every drift guard imports `design_tables.py`, so a resolver there importing the package would turn
  one broken import into a collection failure in each of them. A package-free
  `design_tables.resolve(fields, references)` raises `DesignTableError` on a name the mapping lacks, so
  a typo fails closed; the mapping — the one thing that must import `ErrorCode` and
  `BUILD_ONLY_WIRE_NAMES` — is built in `test_event_kinds.py` and passed in. The enum guard widens to
  *an enum, or a tuple composed from one*. **Both tests move, and `FINDINGS.md`'s note on why
  `test_event_kinds.py` is red names this as the second cause beside the `ClientKind` `CHECK`**,
  because a builder meeting two causes under one explanation fixes one and stops.

**It commits in its own transaction, after the handler returns**, and it cannot do otherwise: the
seam sees a handler only once that handler has committed or rolled back. Invariant 10 therefore gains
a stated clause for the access log, and `schema.md`'s own rejection of a one-per-call attempt event is
rewritten rather than left standing beside this one.

**The price of that placement is a divergence the store cannot rule out.** A mutation can commit
while its call event does not, so the two logs may disagree, and the semantic kinds remain the
authority on what happened to the store.

**And "best-effort" has to be built, or this milestone reintroduces M17.** `core/store/ddl.py` puts
`PRAGMA busy_timeout = 5000` on every connection, and `_compute_response_line` returns only after
everything ahead of its `return`. An access-log write inheriting that timeout would put **five
seconds** of a caller's latency behind a lock it has no stake in.

**Be exact about where that wait lands, because it decides what any test can prove — and it differs
by verb.** A **memory** verb already held the write lock for its own semantic event (`reads.surface`
emits `surface_call` inside its own transaction), so a continuously-held lock fails the handler itself
at `store_busy` with or without this milestone, and a test conditioned on that proves nothing. A
**knowledge** verb may not: `knowledge_list`, `status`, `search`, `refresh`'s plan and `unlock` leave
the registry unwritten, and `registry.ensure_table` **reads `sqlite_master` and issues nothing when the
table is there** — so the first knowledge verb on a fresh store, which does create it, sits with the
memory verbs for that one call.
For those five the `call` row is **the call's first and only
`memory.db` write** — which gives the isolation for free, with no seam and no stubbed handler.

*This premise was written as `CREATE TABLE IF NOT EXISTS` against an existing table taking no write
lock, which the milestone's own held-lock test falsified on the connection the service holds
(`research/m33-registry-ensure-takes-the-write-lock.md`). The conclusion survives and the reason
changed: those five verbs now write nothing rather than writing cheaply.*
**`add`, `remove` and `rename` write the registry** inside `in_one_transaction` and sit with the
memory verbs, so a test built on one of them proves nothing either.

**Two properties carry it, and both are mechanical.** The response line is **encoded before the row
is attempted**, so nothing the write does can reach the caller — which matters because the write
happens after the handler has committed, and a propagating failure there would report a durable
`memory_remember` as `internal_error` and earn a retry and a duplicate. And the row goes on a
**private connection opened at `busy_timeout = 0`** rather than a toggle on the shared one, which
would leave it at zero under whatever other handler's statement ran in that window. What is borrowed
from `core/knowledge/counters.py` is its `is_contention` swallow, not its toggle — that caller owns
its connection and this one would not. Losing an audit row is a measurement gap; corrupting a
caller's answer is not.

`schema.md` §"`call` is an access log" is normative for the rest: where the connection is opened and
closed, that a `finalize`-closed connection stops the log rather than reopening it, and that it sets
**`PRAGMA synchronous = NORMAL`** where the shared connection keeps `FULL` — so the row is a WAL
append rather than an `fsync` on every response path, giving up only the last few access-log rows
after a power loss, which "best-effort" already concedes. The costs that remain are a private
connection competing for the write lock with the service's own writes and, since any foreign commit
invalidates the shared connection's page cache, a per-call re-read inside the **next** handler
(`schema.md` §"`call` is an access log"); the A/B reports the idle delta that every push pays and which
side of the seam it sits on.

### The classes of call the log does not cover

The seam is `_METHODS` dispatch, and the exits below precede it in `_compute_response_line`. Each is
excluded for its own reason, and the done-when's test drives calls rather than reading the table — so
this list is complete as of that test's inputs rather than by construction.

- **`health`.** The liveness probe, which a client's own start-if-absent sequence polls repeatedly
  while waiting for the service to become ready. An access log recording it would be mostly that.
- **An unparseable line.** `parse_request`'s three codes, or a line that is not UTF-8 — which answers
  `PARSE_ERROR` before `parse_request` runs — all raised in `_handle_line` before `_dispatch_request`
  is entered. Mechanically unloggable: there is no `RpcRequest` to attribute.
- **A malformed envelope.** Mechanically unloggable one rung later: `_resolved_envelope` raised, so no
  `session_id`, `client_kind` or `op_id` exists, and `log_event` requires a `CallParams` carrying
  those among its fields. It carries `max_depth` too, which the seam has no value for — so the access
  log takes a narrower type than `CallParams` rather than inventing a policy value it has no business
  holding.
- **An unknown method.** Loggable in principle, since a `ResolvedEnvelope` is in hand, but the name is
  not in `_METHODS` — nothing was dispatched — and the wire already answers `METHOD_NOT_FOUND`. It
  reports a client defect rather than anything about a Zikaron surface. (`method` carries no `values`
  in `EVENT_SPECS`: `core/` cannot import `_METHODS`, and it is closed by construction at the one site
  that writes it, this exit having already run.)

**A consequence worth stating before somebody writes a query against it**: because the **second and
fourth** exits take four of `ProtocolErrorCode`'s five members — `health` answers a *result* and no
error at all, and a malformed envelope answers a `ZikaronError` whose code is a domain `ErrorCode` —
**`internal_error` is the only one a `call` row can ever hold.** The converter's type stays the
union, which is what makes `mypy` the check; the
reachable domain is narrower and `schema.md` says so.

### Two prose changes this milestone carries, and the test that admitted them

**Both are facts the agent lacks, not instructions it is ignoring — that is the whole admission
test.** On 2026-09-25 an agent cited three memories from headlines without fetching and, challenged,
answered *"I quoted both from headlines without fetching them, which is exactly the thing the store's
own instructions say not to do"*. It **quoted the rule it had just broken**. Adding a fourth copy of
that instruction is the category `CLAUDE.md` measures as losing; what corrected it was a challenge.
So: **prose earns its place where the agent does not know something, and does not where it knows and
does not act.** The second case needs a boundary or a trigger, which is M32's unfinished business and
not solvable by wording.

Two additions pass that test. A third candidate does not and is named here so it is not re-proposed:
nothing about the corpus reading as *grief* or *word salad* belongs in a tool description — that is
169 records already written, and it is consolidation work.

**Operator decision: `memory-reviewer` writes the final text for both, not this agent.** M32
established it by comparison rather than preference — the shipped preamble and the author's own
merge of it both kept the hedged, self-explaining register they were meant to escape, and Round 2's
authored replacement was the one that did not. The drafts below are the *specification* of what each
sentence must carry; they are not the wording to ship. Brief the reviewer with the gap, the evidence,
and the constraint that this is information the agent lacks rather than an instruction to press
harder, and take its prose.

### A record may get shorter

`zikaron_memory_amend`'s description, because that is where the decision is made. The gap is real and
the agent diagnosed it itself: *"amendment here has been append-only… nothing ever gets shorter, so
records grow monotonically into archives"* — `13a7549f` reached ~1,900 words holding three
confirmations, a correction of a correction and a scope note, and a record that cannot be held in
working memory is cited rather than read. `remember` bounds the gist and **nothing bounds `content`**;
D16's never-lose posture makes cutting feel like deletion when splitting loses nothing.

```
Amending replaces the record; it is not an append. If a record has accumulated confirmations,
corrections and scope notes until it is an archive, cut it back to the finding and its instruction
and record the separable lessons as their own memories — nothing is lost, and a record too long to
hold in working memory gets cited rather than read.
```

### The other: a uuid is not a citation

**Operator decision, 2026-09-25: the citation rule lands here.** An agent cites memories by id in
durable project documents, and on `~/Trading/LeibaTrader` **none of six ids cited in that project's
`STATE.md`/`FINDINGS.md` is live** — two resolve to no record at all, four to superseded rows, two of
those into records amended the same day (Q20). The defect is semantic rather than mechanical: **a
uuid looks like a stable identifier and is not.** It is an internal handle that consolidation moves
the claim away from, meaningful only inside the session that read it.

**What exists already, and what is actually missing.** `design/write-policy.md` §"Why a record points
at another by subject rather than by gist — or by uuid" **already rejects uuid citation**, on grounds
that are not Q20's: a uuid is opaque to a human in a store meant to be auditable, a hallucinated one
is undetectable where a hallucinated description is obviously wrong, and — the sentence Q20 has to be
reconciled with — *"D16's never-`DELETE` rule makes a retired record still resolvable."*

That reconciles cleanly, and the reconciliation is the finding. **A uuid that ever existed always
resolves — to the row, never to the claim.** Consolidation moves the claim to another uuid and leaves
the absorbed row fetchable but demoted, so the citation resolves to a husk (D16, D25). And two of the
six ids measured on `~/Trading/LeibaTrader` resolve to *nothing*, which is that section's hallucination point
now observed rather than predicted.

**The agent-facing text is where the gap is.** `zikaron/mcp/primary.py` tells it *"Point at another
record by its subject ("the record about the deploy rollback"), never by quoting its headline, which
is rewritten on every amend"* — a **memory→memory** rule whose stated reason is gist rewriting, so an
id written into a *document* reads as outside it. M33 adds two things: the agent-facing sentence in
`zikaron_memory_remember`'s description — the uuid is a handle for this session's tool calls, not a
reference anything durable may hold — and one line extending that section's rule from gists to
documents.

**Do not instead teach `memory_fetch` to accept the 8-character prefixes those documents use.** It
would make the citations checkable and the practice permanent, and `design/retrieval.md` already
argues a prefix is not a handle — which is why the block prints uuids whole.

**Why it is admissible here despite the fence below.** M32's arm measures the **read** path and its
digest covers the block's framing; this is a **write**-side rule in a tool description, so it moves
no digest and no surfaced text. It is still a text change while an arm accumulates, and it is taken
deliberately rather than because it looked harmless: a live memory (`b04a458f`) instructs re-checking
those citations, cannot be executed against whole-uuid `fetch`, and costs a turn on every surfacing.

### Done when

**A test asserts that the set of methods in `server.py`'s `_METHODS` and the set the call log covers
are the same set** — that is the property the whole design is for, and without it this is per-verb
instrumentation wearing a seam's clothes. **It drives calls rather than reading the table**, and what
it asserts is stated rather than implied:
for every method in `_METHODS`, one well-formed call and one refused call each produce exactly one
`call` row; every exit ahead of dispatch produces none. **A parameterless method has no domain
refusal** — `knowledge_list` takes no arguments — so its refused arm is an injected driver failure,
stated here so "every method" is not quietly weakened to "every method that has a refusal". That makes the
exclusion list complete **as of that test's inputs**, not by construction — an exit added ahead of
dispatch that fires on some other input, a size or rate limit say, is invisible to it, and claiming
otherwise would be the overclaim this milestone exists to stop making.

The `call` event's shape is in `schema.md`'s per-kind table and in `EVENT_SPECS` as **`CallDetail`**,
with **`KnowledgeBuildDetail`** beside it — `log_event` takes an `EventDetail`, and a kind cannot be
logged until its type exists — and `CallDetail`'s construction is where the
`ErrorCode | ProtocolErrorCode -> str` converter lives, so "typed at the call site" has a site. **Its
`error_code` field is `str | None` holding that converter's output and never an enum member**:
`ErrorCode` is an `IntEnum` and `EventSpec.validate` tests `str(value)`, which for a member is
`'-32005'` rather than `'bounds'` — so a member would be refused inside the guarded write and dropped,
leaving an access log that holds no refusal at all. The `call` spec's `error_code` is declared in
`EVENT_SPECS` with `values` holding every `ErrorCode.wire_name` plus the literal `internal_error` and
`nullable=True`, that literal pinned to `ProtocolErrorCode.INTERNAL_ERROR.wire_name` by a test, and the
seam's converter typed `ErrorCode | ProtocolErrorCode -> str`; the migration to schema 3 runs in one
transaction; the 2→3 step is covered **hermetically** by `test_store_migration.py`'s synthetic store,
and exercised once against a `VACUUM INTO` snapshot of `~/Trading/LeibaTrader` by a re-run of
`spikes/m31_check_widening.py` extended to 3 — a spike, since the gate is hermetic and no test may
open a store under the operator's home — with its `integrity_check` and timing recorded in
`research/`; **`test_design_tables.py` gains two cases, driving `resolve` with a fake mapping** —
a resolved `@`
reference and an unknown one refused; the bare literal beside the group is already
`test_a_set_stated_beside_the_group_is_read_too`. A fake mapping keeps the unknown-name case a
hermetic literal rather than a typo in `schema.md`, which is that module's own rule: test a malformed
input without putting a malformed document on disk; **`knowledge_build` is exercised as follows** —
a schema-2 store attempts no write
and raises nothing; a child refused inside `builds.prepare` or `scan.run` writes `ok=false`, that
class's `wire_name` and a null `files_indexed`, while a refusal raised **before an id is bound**, with
or without a connection, writes no row at all —
that fixture runs on a store no knowledge verb has touched **and asserts the refusal is
`UnknownKnowledgeBaseError`**, rendered `refused:` rather than `failed: no such table`, which is what
makes it red when `registry.ensure` is missing ahead of `require`: the no-row half alone is satisfied
by the crash too; two spawns from one service, the second passing no token, leave the
second's `spawned_by_op_id` null and the service's own `os.environ` without the variable after both;
a row attempted under a held lock lands once the lock releases, inside `BUSY_TIMEOUT_MS`; a row write
raising a non-contention error after a completed scan leaves the printed report intact, the exit
status 0 **and one line on stderr naming the failure**, so a silent swallow does not pass; its
failure-path twin leaves a refused build's refusal as the printed outcome — the *original* exception
re-raised rather than the row's, so `scope.execute` still renders `refused:` — writes **no** row at
all, and prints that same one line on stderr; **a test imports every module under `zikaron/` but the
`__main__` entry points**, with `walk_packages`' `onerror` set to raise, and then walks
`KnowledgeError.__subclasses__()`
*transitively* — that call returns direct subclasses alone and sees only what is imported — holding
every concrete one's `wire_name` inside `knowledge_build.error_code`'s `values`; three `__main__`
modules run the program at import and `walk_packages` swallows `ImportError` unless told not to, so a
naive walk both crashes and hides what it missed; so a class
the boundary does not map and the export forgot is red rather than a stderr line on the build that
needed it; and every
`KnowledgeError` the boundary maps carries its `ErrorCode`'s `wire_name`, with the build-only names
disjoint from every `ErrorCode.wire_name`; **a build ending on `index_failed` — the embed stage,
forced with a stub encoder — writes `ok=false`, `error_code='index_failed'` and a null
`files_indexed`**, which is the case whose omission would have crashed a build inside the write that
records its failure; `test_doctor.py` asserts the scan row's three states —
absent when no `.claude/agents/` exists, `none` when it names nobody, the names otherwise, `REPORTED`
in both present cases; `SUPPORTED_SCHEMA_VERSIONS` covers 1–3; invariant 10 carries its access-log
clause and `schema.md`'s rejection of a one-per-call attempt event has been rewritten rather than
left to contradict it; the indexer emits `knowledge_build` under a `client_kind` the same migration
widens to admit it, with invariant 18, the DDL comments, **`core/events.py`'s `ClientKind`
docstring** — which carries the same "every v0 event is emitted inside a client call" claim outside
the DDL, **and misattributes the `CHECK` assertion to `test_ddl.py` when it is
`test_event_kinds.py::test_client_kinds_match_the_event_table_check_constraint`, corrected in the same
edit rather than left as a second stale sentence in a paragraph being fixed** — and **`ClientKind.CLI`'s
member comment**, a separate sentence saying it records no event, all corrected rather than left
standing; **a test sends `client.kind = "indexer"` and asserts `bounds`
with a `limit` that does not list it**, since the wire's accepted set is the enum minus that member;
and `dispatch_knowledge.py`'s `# noqa: ARG001` reasons narrowed
to "records no *semantic* event" on the six handlers that keep them — **`knowledge_add` and
`knowledge_refresh` lose the marker outright**, since `_spawn` now passes `envelope.op_id` to
`detach.spawn` and the argument stops being unused; **`core/events.py`'s** docstring gains the clause
that the vocabulary *imports* one layer's declared names rather than restating them, which is its own
"beside the error contract" rule read from the other side; **`_compute_response_line`'s** loses
"every branch can simply answer", which the three post-dispatch branches stop doing once they assign
a line and share one write-then-return; **`core/knowledge/errors.py`'s
and `dispatch_knowledge.py`'s module docstrings are re-read against the `wire_name` addition and left
true**, which they are only because the numeric codes stay at the boundary — the first gains one
clause saying what a `wire_name` *is* (the name the build log records, held equal by test to the code
the boundary maps it to, and not itself a code), since a reader meeting
`wire_name = "knowledge_base_busy"` under a docstring about having no wire shape will otherwise ask;
**`doctor/checks.py`'s module docstring and `run_all`'s** lose their "one row reports rather than
checks" count for *two rows report rather than check — the SQLite version, which has no correct value,
and the agent scan, whose finding is a grant the user made on purpose*; **`detach.py`'s** gains the
clause saying the shared constant is why the child may import the spawner, the reverse of the
direction that module otherwise forbids; the three normative sentences
that followed from those claims are corrected too — `architecture.md` §"What a rejected call does and
does not change" and §"Service RPC surface", and `knowledge-index.md` §6.1's "indexing never touches
`memory.db`"; the spill is named in `schema.md` as deliberately silent, with
its reason and the deferred-group proxy that replaces it; the refusal rate of a bounded write and the
per-method call volume are each answerable by query on a fresh store, with the queries in
`experiments/`; §"Retention"'s growth figure is re-derived with `call` included, on the migrated
snapshot that spike uses; **three tests isolate the access log's cost, one claim
each** — (i) the access-log writer alone,
attempted while a second connection holds the write lock, returns well inside `BUSY_TIMEOUT_MS` and
writes no row, on `tests/test_knowledge_counters.py`'s fixture and its `BUSY_TIMEOUT_MS / 5_000`
bound; (ii) a dispatched **`knowledge_list`** under that same held-lock fixture answers with the
**byte-identical** line an unlogged call would return, inside the same bound, and leaves no `call` row
— it needs no seam and no stub, because `knowledge_list` takes no write lock of its own and the row is
the call's first `memory.db` write. **That holds on a store whose `knowledge_bases` table already
exists**, so one knowledge verb runs before the lock is taken: `registry.ensure_table` reads
`sqlite_master` and issues nothing when the table is there, and takes the write lock only on the one
call that creates it — the opposite precondition to the no-id fixture above, and sharing
one store between them gets one of the two wrong; (iii) the same byte-identical property when the write raises a
non-contention error — a closed private connection, a raised `OSError`. **For a *memory* verb a
held-lock test proves nothing**, since that handler's own event write fails first and answers
`store_busy` with or without this milestone — as it would for `knowledge_add`, `remove` or `rename`,
which write the registry. That is why (ii) names `knowledge_list` specifically rather than "a
knowledge verb". The drop rate is a
query over **distinct `op_id`s** — those with a semantic row and no `call` row, over those with a
semantic row — since counting rows would let one dropped push weigh six times a dropped `remember`;
bounded as §"`call` is an access log" requires; the
added write's cost is measured against a control **idle and under a writer interleaving short
transactions at a stated rate**, the idle delta being what every push pays, recorded in `research/`,
and **against a bar preregistered before the run** on M26's precedent: an idle per-call delta at p50
and p95 that a WAL append with no `fsync` should not exceed, in milliseconds for the machine it runs
on; and under the writer, `memory_surface`'s p95 inside `push._DEADLINE_SECONDS` wherever the
control's is, with N stated. ~~**A miss moves the write after `writer.drain()` — *inside* an activity
bracket widened to cover the drain, or idle self-stop could fire between response and row — or reopens
the private connection's pragmas**, so the number decides something rather than being written down.~~
**Withdrawn 2026-09-28, operator decision: the p95 was missed and the cost is accepted as measured.**
The clause was disproportionate to what it gated — a per-call delta of about 1 ms against a
`push._DEADLINE_SECONDS` of 2,000 ms — and **a gate, once written into a done-when, is serviced by every
review round that follows it**, which is what four of this milestone's eight rounds went on. Struck in
place rather than deleted, because a reader meeting only the accepted outcome would re-propose the move.
The bar itself stays as written and is written into the `research/` note **above the results, with its
date**, since "preregistered" is only checkable if it is prior on the page;
the Claude Code install **and `zikaron doctor`** both name any agent whose `tools:` allowlist omits
`mcp__zikaron`, through one function, and edit none of them, with `design/harness.md` §"What the
install reports rather than enforces" carrying the predicate and both exclusions and
`design/distribution.md` §"The front door" carrying the new check in its ordered list, its directory
condition and its `REPORTED` outcome; **both** prose additions are in place — the citation rule in
`zikaron_memory_remember`'s
description with `design/write-policy.md` saying the subject rule covers documents as well as gists,
and the shortening rule in `zikaron_memory_amend`'s — each pinned by a phrase in
`tests/test_mcp_tool_descriptions.py` so neither can be dropped silently; `./check.sh` and
`./check-matrix.sh --parallel` are green.

### Scope fence

**Not** a change to D27's provenance fields, and **not** an actor or occasion column on a record.
**Not** the reranker, the relevance floor, or anything about what push selects. **Not** a change to
the injected block's framing: M32's arm accumulates against `d46f68677668`, and touching that text
puts a new digest on the only post-change sample there is — which is why the citation rule above is
scoped to a tool description and nothing else. **Not** repairing the six dead citations in another
project's documents; that is work in that repository, and this milestone stops the next one being
written. **Not** the harness transcript — Q16's external answer is Claude Code's and decays with
`cleanupPeriodDays`; this milestone makes the *store* answer what the store can.

## M34 — A headline carries no verdict

Normative: `design/write-policy.md` §1 "Why this text is shaped the way it is", which carries the
symptom-first rule; `design/consolidation.md` §"Consolidator identity and model";
`design/harness.md` §"Tool descriptions are capped". `FINDINGS.md` Q22 is the problem statement and
Q21 the instrument; read both before this.

**Gists are verdicts, and the verdict is what gets quoted instead of the record being read.** 93 of
169 live long-term gists on `~/Trading/LeibaTrader` carry a conclusion marker by `VERDICT_MARKER` in
`experiments/m34_gist_replay.py` — a screen that over-counts causal clauses, so reading decides — and
the common shape is *symptom, so verdict*. The write policy asks for the symptom **first**, and that instruction is obeyed; nothing
has ever said the verdict should be **absent**. That makes this missing information rather than an
ignored instruction, which is the one case where prose has been measured to bind. The target, in the
operator's wording: **a headline carries no verdict, and sparks the curiosity to read the record when
it looks relevant.** The concrete rule is *keep the symptom, drop the `so` clause*, which keeps D13's
triage intact.

### The surfaces, and why each

**The consolidator, at merge and promote — as the gatekeeper of the form, not as a repair pass.** It
already rewrites gists there, so giving it the rule makes it the one point where a verdict is checked
and corrected on everything that passes through. It is the only enforcement point the system has: D2
bars a gate on the write path, and a tool description is advisory. Its text lives in
`zikaron/install/assets.py` §"Authoring gists and content".

**`zikaron_memory_remember`'s description, because D10 makes consolidation manual and rare**, so a
record lives as a verdict for a long time before any consolidator sees it, and one that never groups
is never checked. It is also the **only** write-time carrier of headline rules: both `agentSpawn`
policies in `zikaron/hook/write_policy.py` defer to it (*"Headline and content rules are in
zikaron_memory_remember's description"*), so there is no third surface to keep in step.
`zikaron_memory_amend` inherits the rule through its own *"Both follow the rules in
`zikaron_memory_remember`"*, and names it in its summary, because an amend is where a verdict gets
corrected into another verdict.

**`remember`'s description sits at the edge of `DESCRIPTION_BUDGET`** (1,894 of 1,900 characters
after this milestone), so the rule displaced text rather than extending it: the weakest parts of
the length sentence, one of two expiry examples, and a restated mechanism. The `3e1f6c7a` exemplar
sat well inside the length bound while still being a verdict, so length is not the lever. **Kept**:
the uuid-citation paragraph, the one write-side sentence with evidence of changing behaviour, and
the `Returns` block, which truncation ate before. Re-derive the length with the command in
`design/harness.md` §"Tool descriptions are capped".

**`zikaron_memory_promote`'s description, because in-place promotion writes no prose.** The mechanism
is unchanged: a row's tier flips only when the gist and content are byte-identical, as it always has.
But that form carries the entry's own gist to long-term with no authoring rule applied, and the
replay measured it as the one path verdicts leaked through (`research/m34-gist-form-replay.md`). So
the description, and the skill's promote paragraph, say the in-place form fits only an entry that
already satisfies every rule; any other is promoted as a new record, its entry retired against it —
a new uuid, which the citation rule already tells agents not to hold.

**`memory-reviewer` writes the shipped text for every surface, verbatim** — operator decision, as in
M32 and M33. This brief specifies what each must carry; it is not the wording.

### The instrument: replay the real journal through the real consolidator

**No synthetic rewriter and no separate judge harness.** Seed a fresh store from
`~/Trading/LeibaTrader` and run the ordinary consolidation skill over it with the form rule
installed.

**The journal as written is not fully recoverable, and the seed says so.** Events carry no prose, and
amend, merge and promote rewrite rows in place. Of the 284 rows `remember` created, 100 still carry
their author's prose unamended — 79 retired journal rows and 21 live ones; the rest have been
rewritten since. So the seed is **every one of the 284 rows' current prose, re-inserted as journal
entries in `created_at` order**. That is not a historical replay; it is a realistic journal, verdicts
included.

**The seed is the baseline, so there is no control run by default.** Each seed row *is* the store's
current text, which is what the rule is judged against: whether the rewrite kept the row's facts,
conditions and severity is a comparison of output against input, and a re-run under the old prompt
would only interpose a second rewrite. What a control arm alone could show is whether plain
re-consolidation, with no rule, moves a gist the same way — merging rewrites gists on its own. **Run
one only if a bar fails and the failure could be regrouping rather than the rule**, from the same
snapshot, installed from the tree as it stood before the consolidator text changed.

**Read the source by `Connection.backup()` or `VACUUM INTO`, never by copying `memory.db`**, and
never write to it. The replay runs in a scratch project directory outside the repository, with
Zikaron installed under `--harness claude-code` (D17 scopes a store to its project directory), seeded
from the snapshot through the service's own `remember` so chunks, vectors and events are what a real
write produces. **The operator invokes the consolidation skill there by hand.**

**Planning outlasted the client, and M34 carries the fix** because the replay cannot run without it.
A 284-row journal plans in 12.2 s against the consolidator's 10 s request timeout, and the plan bridge
treats the lost response as terminal for the process. `memory_plan_groups` and `memory_next_group`,
which plans inline, now wait `_PLANNING_TIMEOUT_SECONDS`; the other consolidator verbs keep the
default.

**The comparison is row by row**: the script follows each seed row to the long-term record that
absorbed it and prints the seed prose beside the record's.

**The bars are set here, by judgement, and the outputs are read against them** — each names what
would be done on either side of it:

- **Verdicts removed.** ~~The output's long-term gists carry a conclusion marker at under a quarter
  of the seed's rate, counted by the same marker regex and confirmed by reading.~~ **Amended after
  the first run, by reading:** no order survives in any gist, and at most one gist in ten carries a
  verdict, pooled over every output gist whether the consolidator wrote it or kept it, each residual
  quoted in the research note — M34 passed at 7 in 105 (3 of 72 rewritten; 4 of 33 kept, three of
  them promoted before the promote condition existed). The regex
  selects what to read for verdicts — it matches no imperative, so the no-order clause is read over
  every output gist; its ratio is not the test, because it counts causal clauses as verdicts on
  both sides (`research/m34-gist-form-replay.md` gives both ratios). Short of the reading test, the
  wording goes back to `memory-reviewer`.
- **Severity kept.** No output gist or record understates the seed rows it absorbed — *"silently
  corrupts"* read as *"may affect"*. Any unexplained instance sends the wording back; this is the
  failure that would make the gatekeeper worse than nothing.
- **Facts and conditions kept.** The output drops no error string, identifier, expiry or scope
  condition its seed rows carry. Same consequence.
- **Triage kept.** Each output gist still says what its record is about, judged by reading. A gist
  that became a teaser with no subject fails D13 and sends the wording back.

**The write-side sentence is not measured by the replay**, which exercises the consolidator only. Its
evidence arrives after release, as the marker rate among new `remember` writes on the real stores.

### Done when

The replay script is in `experiments/` and re-runnable from a named source store, whole or by
`--rows`; the replay has run, and so has the targeted re-run of the rows the first one leaked;
`research/m34-gist-form-replay.md` holds the per-bar result and the gists that decided it. The
consolidator prompt and the `remember`, `amend` and `promote` descriptions carry `memory-reviewer`'s
wording; the golden `.kiro/agents/zikaron-consolidator.json` and the two consolidator entries of
`tests/fixtures/kiro_artefacts.json` are **re-rendered** through the installer, not hand-edited;
every description stays inside `DESCRIPTION_BUDGET`; `design/write-policy.md` states the
rule where it states the symptom-first rule. `./check.sh` is green.

### Scope fence

**Not** repairing the existing corpus: the form rule lands first, or a repair pass rewrites 169
verdicts into 169 fresh ones and reports success. **Not** Q21's tone pass, which the replay could
test but this milestone does not ship. **Not** the injected block or anything push selects — M32's
arm accumulates against its digest. **Not** a change to promote-in-place's mechanism — only to what
its description tells the caller. **Not** the embedder:
`granite-embedding-30m-english` is evaluated separately (operator decision 2026-09-29).

## M35 — One connection shared by every request, a plan that holds the writer, and a wedge nobody can see into

Normative after this milestone:
- `design/architecture.md`:
  - §"Lifecycle": the service's connections, and what a signal writes. §"Idle self-stop"'s sentence
    naming the signals left at their default disposition changes.
  - The list of clean-stop reasons (`reason=idle`, `reason=store_replaced`, `reason=encoder_failed`),
    under §"Validation: unknown keys per file, ranges on the effective config", gains
    `reason=sigterm` and `reason=sigint` (item 4).
  - §"Consolidation lifecycle": planning, including the row ceiling `_PLANNING_TIMEOUT_SECONDS`
    implies.
  - §"Errors": `store_busy`, and the new `deadline_passed` row (item 7).
  - §"Validation precedence — fixed, because the order is observable": `memory_surface`'s
    `deadline_at_ms` is validated whole by the dispatcher, before the lease and ahead of the rest of
    the parameter rung (item 7).
  - §"Service RPC surface": `memory_surface`'s optional `deadline_at_ms` (item 7).
  - §"Degraded modes — the hook must never block a user message, and it never reads the store
    itself": the hook sends `deadline_at_ms`, and its list of failure kinds gains `deadline_passed`
    (the service's refusal) and `unanswered` (a push sent and not answered by the deadline).
    `deadline_exceeded`, which the section today names only as *"the internal deadline"*, is spelled
    out as the pre-send case (item 7).
- `design/retrieval.md` §"One read is one transaction, and the instrumentation is inside it": it
  gains the one server-side retry of item 2 and its `IMMEDIATE` mode, the read's single wait budget
  with `surface`'s taken from its caller's deadline (item 7), and the connection a read runs on. Its
  cost bullet names the committed case "by another process" only; it now names the held lock too,
  and the in-process writer.
- `design/schema.md` §"Additive tables and the version gate" and §"`call` is an access log, and every
  other kind is a semantic one", and `design/knowledge-index.md` §"3.1a The registry lives in
  `memory.db`": when the registry table is created (item 2). The access-log section's bullet on its
  own connection changes too. Its stated reason — a toggle on the shared connection would leak to
  other handlers' statements — becomes: the row would otherwise queue behind the writer's lock on the
  response path. A toggle under that lock is safe, and item 1 relies on it. Its sentence on
  checkpoints changes too — *"the shared connection keeps the default, so the WAL is checkpointed at
  whichever of its commits …"* — because after M35 those commits are the writer's and every pool
  connection's, a read's `IMMEDIATE` retry included. So does its sentence that a store held
  continuously by another writer fails a memory verb's handler *"at `store_busy`"*: a `surface`
  carrying a deadline fails at `deadline_passed` (item 7).
- `design/schema.md`'s DDL comment on `surface_call`, *"push path fired; EXISTS EVEN AT ZERO
  RESULTS"*: the first clause becomes *"push answered within its deadline"*. The DDL guard strips
  comments, so the change does not touch it. The code's own statement of the rule is the
  `surface_call` payload class's docstring in `core/events.py`, *"exactly one per push, including
  when nothing was returned"*, which is on the rewrite list in §"Done when".
- `design/schema.md`, for item 7: the per-kind event table's `surface_call` row; §"`call` is an access
  log, and every other kind is a semantic one"'s sentence *"Every push writes `surface_call`"*; and
  §"Linked sessions — what makes a cross-client signal computable"'s paragraph *"Honest limit on the
  session denominator"*. Item 7 gives the replacement wording for each.
- `design/schema.md` §"The `event` log, per kind", for item 7: *"The hook's degraded path emits no
  events at all on any failure, because it never reaches the service"* is no longer true of a
  `deadline_passed` push, which reaches the service and commits no semantic event by design. For
  item 2, the `call` row's *"`duration_ms` covers the handler alone"* becomes: it spans the lease
  wait and the `deadline_at_ms` parse too.
- `design/schema.md` §"Migration posture", for items 1 and 6: its account of the build row written
  as a fresh transaction so a stale snapshot cannot refuse it becomes moot under `IMMEDIATE`, and the
  row's position changes with item 6.
- `design/schema.md` §"When the version moves", for item 2: the registry table is created
  idempotently at the first *write* that needs it, not at first use.
- `design/write-policy.md` §"3. How we find out which way it errs", its first honest limit, for
  item 7. It restates the same denominator paragraph as normative text in the document that defines
  the signals, so it is the copy that matters most. Its uniformity claim — every failed push emits
  no `surface_call` because the hook never reaches the service — gains `deadline_passed` as the one
  failure the service *does* see and still records no `surface_call` for. Its closing condition
  gains *"and answering within the hook's deadline"*.
- `design/schema.md` §"What is instrumented, what is not, and why", for item 6. Its account of where
  `knowledge_build` is written — inside `build()`, and on success after the report and after the
  `try`/`except` — becomes: for every outcome reached after the lock was taken, the row is written
  by `scan.run`'s completion callback before the lock's release, on `Exception` only, its whole
  body guarded, once per build by a latch. `build()`'s own two sites write only when the callback
  never ran — a refusal before the lock — and are no-ops otherwise. The paragraph on what the old
  placement protected and how its mutation was caught goes with it. *"No row write is ever the
  reason a build reports failure"* stays true. The same section's paragraph on `build()` resolving
  the registry row changes too. It names `unlock` among the callers of `ensure`, and gives *no such
  table* as the reason `ensure` is not optional. After item 2, the indexer's `ensure` is the one
  creation site outside `knowledge_add`, and a registry read on a store without the table answers
  from `ensure_table`'s presence read, not from a driver error.
- `design/knowledge-index.md` §"9. CLI surface (parity, not the primary path)": its `refresh --wait`
  paragraph becomes *"returns once the build's lock is gone — and, since the row is attempted before
  the release, once its `knowledge_build` row has landed or been dropped as best-effort; the indexer
  process may still be exiting"*. Its sentence on a build that fails after detaching says the row
  now names the failure's wire name (item 6).

The evidence is `spikes/m34_service_staleness_probe.py`, `spikes/m35_busy_snapshot_probe.py`,
`spikes/m35_read_upgrade_probe.py` and `reviews/m35-brief-perturbation.md`.

### What is wrong

**Every request runs on one `aiosqlite` connection, and nothing serializes their transactions.**
`server.py` hands every handler `ctx.store.connection`. Two clients' requests interleave on it, so
while one request holds a transaction another's `BEGIN` fails *cannot start a transaction within a
transaction* and is answered `internal_error`. Normally the window is milliseconds. **A consolidation
plan widens it to the whole plan**: `plan_within_transaction` inserts the run row before
`grouping.plan` computes, so the write lock is held for the whole computation — 12.2 s for a 284-row
journal — and five of eight concurrent searches failed during one
(`spikes/m34_service_staleness_probe.py`). A failed rollback in `transactions.finalize` closes the
connection, after which every later request fails.

**Every write is a deferred transaction that reads before it writes**, so a commit from **another
connection** between the read and the write refuses it at once with `SQLITE_BUSY_SNAPSHOT`, which
`busy_timeout` never retries (`spikes/m35_busy_snapshot_probe.py`). That other connection can be the
detached indexer's build row, a second service, or an operator's shell. It is the CI failure of
`test_rename_and_remove_reach_a_real_service` (run 36657562917). **An in-process lock cannot fix this
class**, because the other writer is not in this process. `memory_fetch` and `memory_retire` open raw
`BEGIN`s with no failure map, so the same contention reaches them as `internal_error` rather than the
retryable `store_busy` the error table promises.

**Two builds that start together get the wrong refusal.** The corpus lock is acquired in a deferred
transaction, so both read *no holder*, and the loser answers the driver's `database is locked`
instead of `IndexerBusyError`. The outcome is right and the refusal is wrong; `scan.py`'s own note
says only an `IMMEDIATE` variant was missing.

**A push the agent never saw is recorded as shown.** The push hook abandons a `surface` at 2 s; the
service cannot see that and commits its `surface` rows anyway, and those rows are the denominator of
D30's repair signal. The pool this milestone adds would widen it, because a read's retry waits.

**A wedged service leaves no evidence.** The LeibaTrader service on 2026-09-29 answered a `remember`
and then nothing for eleven minutes: no event, no log line, and — since a `SIGTERM` exit writes
nothing where an idle one writes `reason=idle` — a kill and a wedge read alike. Its cause is unknown,
and the shared connection is the likeliest candidate, not a demonstrated one.

### What ships

**1. Transactions on one connection are serialized, and a write claims SQLite's write lock at
`BEGIN`.** The transaction primitive (`transactions.in_one_transaction`) takes a per-connection
`asyncio.Lock` for the transaction's whole span, so no two transactions ever nest on a connection,
whoever issues them. **It gains two arguments, `immediate` and `deadline`.** Absent, the mode is
the connection's and the deadline is entry plus `ddl.BUSY_TIMEOUT_MS`. A read passes the deadline
its lease started with, and `surface` passes `deadline_at_ms` less the margin. **Which mode a
transaction uses follows from its connection**, and the two exceptions below pass it explicitly:
- **Every transaction on the writer, and every one the indexer opens against `memory.db`, is `BEGIN
  IMMEDIATE`**, so contention from any process waits for the write lock within the budget rather
  than failing on a stale snapshot.
- **A transaction on a pool connection is deferred.** That covers a read's first attempt, events
  included, and item 3's planning snapshot. The one exception is a read's retry, which opens
  `IMMEDIATE` for the reasons item 2 gives.
- **Every other connection keeps its deferred `BEGIN`**: the access log's, and the corpus databases'.
  The one exception is item 5's lock acquisition after it has seen no holder.

Item 2's classification decides which connection a method gets.

**After M35 the only `BEGIN` issued on a service connection is the primitive's.**
- `memory_fetch`'s and `memory_retire`'s raw `BEGIN`s (`records/memory.py`) move onto it, which gives
  them its failure map and rollback ladder.
- The raw wrappers with no production caller, `create` and `amend` in the same module, are deleted
  or moved onto it.
- A drift-guard test fails on any `BEGIN` issued in `zikaron/` outside `transactions.py`, `store.py`
  and `migration.py` — through `execute`, `executescript` or an f-string alike. The last two run
  before the socket exists.

**Every statement a handler issues on the writer goes through the primitive**, reads included.
Between two handlers' transactions the writer is shared. A statement issued outside the primitive,
while another task's `BEGIN IMMEDIATE` is open on the same handle, runs *inside* that transaction
and reads its uncommitted rows: one connection has one transaction state, whatever the driver's
isolation mode. Three knowledge-write sites do this today:
- `knowledge_add`'s `builds.plan` after `lifecycle.add`'s transaction;
- `lifecycle.remove`'s `ensure` and `require` before its own;
- `_what_would_be_destroyed` reaching `reporting.status`.

Each moves into a primitive transaction on the writer, and `ensure` leaves `builds.plan`.
- **Being on the writer, these are `IMMEDIATE` though they only read.** On a serialized writer an
  `IMMEDIATE` read costs nothing, and the rule then needs no judgement per site.
- **The transaction covers the registry statements only** — `require`, `list_all`. `observe`,
  `_orphans` and every corpus open stay outside it, on the writer and the pool alike. So
  `builds.plan` and `reporting.status` read the registry in one transaction and do the corpus work
  after it. Otherwise the writer's lock, or a pool connection's read snapshot, would be held across
  N corpus opens, which is the long hold item 2's closing rule on waits exists to prevent.

The rule is stated and the known sites are fixed; it is not made structural. A wrapper that refuses an
unlocked `execute` would change the type every core function takes, for a class the review walk
found in exactly these places.

**The lock is taken at the transaction, not the handler**, so the embedding a write prepares before
its `BEGIN` holds nothing.

**Each service connection is held by one object that owns its lock, the task holding the lock, and
a closed mark.** The writer and every pool connection are held this way.
- **The primitive finds a connection's holder in a module-level registry keyed by the connection**, a
  `WeakKeyDictionary` or an attribute set on the handle, created on first use. So no signature
  moves: the access log and the corpus-database sites call the primitive with a bare handle, as
  today, and get a holder whose lock is never contended.
- When `finalize` closes a handle after a failed rollback, the primitive sets the mark. It has to be
  set, because `finalize` suppresses that close silently and a later `BEGIN` on the handle raises
  `ValueError`, not a driver error.
- **The pre-statement check of the mark runs on every holder**, and raises `WriterClosedError` on
  any closed handle. It is named for its commonest case, the writer's queued requests (below), and
  the dispatch sites answer it `store_busy` wherever it arises, a read's included. On the access log
  it lands in the same `except Exception` branch its comments name for `ValueError`, with the same
  outcome, a dropped row; those comments move to the new name.
- The pool and the writer's reopen consult the mark, through the same registry, before a
  connection is handed out.

**Every transaction on the writer has one wait budget, `ddl.BUSY_TIMEOUT_MS`, for the connection lock
and the write lock together.** That is the constant, not a connection's pragma, which is zero on every
serving connection once the store is open, as it always was on the access log's.
The primitive takes a deadline at entry and waits for the connection lock on what is left of it.
~~On the writer, it then sets `PRAGMA busy_timeout` to the remainder before `BEGIN IMMEDIATE`, as
`counters.py` already does per statement on a corpus connection; that is safe because the writer's
transactions are serialized behind the lock. **The pragma is set on exactly two holders: the
writer, and a pool connection under lease for a read's retry (item 2).** It is never set on a
holder created for a bare handle, whose pragma stays what it was opened with.~~ **Withdrawn on
measurement, and the withdrawal is load-bearing**: with the SQLite uv's managed Python ships,
SQLite's busy handler overran the pragma by 0.6 to 1 s at `BEGIN IMMEDIATE` on macOS
(`research/m35-implementation-evidence.md` §"SQLite's own wait on macOS"), so no value of the pragma
bounds the wait. The store's serving connections — the writer, every pool connection, a reopened
writer — run at `busy_timeout = 0` once the store is open (`ddl.SERVING_PRAGMA`), and the primitive
retries a refused `BEGIN IMMEDIATE` itself, pausing 1 ms doubling to 25 ms, until the deadline
(`architecture.md` §"The service's connections"). A holder created for a bare handle is left to
SQLite's own wait. The primitive computes the lock-wait deadline on every holder, but only the
writer's lock is ever contended; a leased pool connection is exclusive, and polls only on a read's
retry.
- Without the single budget, the two waits compound. A writer queued behind another writer that is
  itself polling for the write lock would wait 5 s for the lock and 5 s more polling for the write
  lock.
  `mcp/connection.py`'s 10 s `REQUEST_TIMEOUT_SECONDS` was derived from one transaction under one
  `busy_timeout`, and it never retries once a byte is sent. So that writer would be reported as
  `AmbiguousMutationError` instead of a retryable `store_busy`.
- An unbounded lock wait would be worse: every writer queued behind one stuck transaction, which is
  a wedge by construction.
- A holder created on first use for a bare handle — the access log, the indexer's corpus
  connections — keeps SQLite's own wait, and its lock is never contended, so its deadline never
  binds. The indexer's own `memory.db` handle is different: it is a `Store`'s writer, and polls for
  the write lock within `ddl.BUSY_TIMEOUT_MS` like the service's.
- The access log's transaction stays deferred; with its `busy_timeout` at 0 the outcome is the same
  either way, a row dropped at once. So the `call` row never waits on the response path, the wait
  `schema.md` calls the M17 defect and `tests/test_access_log.py`'s no-wait bound guards against.

A read's budget is item 2's.

**A task that already holds a connection's lock and asks for it again fails at once** with an
internal error, rather than waiting on itself for the whole budget and answering a retryable
`store_busy` for what is a programming error. The primitive records the owning task to tell the two
apart. Today that case fails immediately as a nested `BEGIN`, and it must keep failing loudly.

**A connection the primitive has closed is never handed out again.** Today one failed rollback leaves
every later request failing on a dead connection.
- A pool connection closed that way is dropped and replaced.
- The writer is reopened with a connection-level reopen that `Store` gains for this: the store's
  pragmas, `existing_only`. It is not `Store.open`, because the schema was validated and migrated at
  startup.
- `opened_inode` stays the startup baseline. **Every connection the service opens after startup** — a
  lazy pool open, a replacement, the writer's reopen — compares the inode `open_connection` returns
  with it. On a mismatch — or a file gone, which `existing_only` refuses — the connection is closed
  and the request answers by its family's existing rule. A knowledge verb answers `store_unavailable`
  `{operation, cause}`, as for any driver or OS failure today. A memory or consolidator verb answers
  `internal_error`, the memory verbs' rule for anything not contention, with one `service.log` line
  naming the inode drift. So no verb gains a wire code. The inode-drift poll then stops the service
  inside its interval. Without the check, a store replaced at its path would answer reads from one
  file and take writes into another until the poll fired.
- `Store._db` loses `Final`. **The writer's reopen runs under the store's own lock, once per
  closure.** A dispatch that finds the mark set awaits the reopen already in progress rather than
  starting one; otherwise two writes dispatched into the gap would each reopen, and one connection
  would be abandoned with a live worker thread.
- **Requests already queued on the writer's lock when it closed answer `store_busy`.** Having
  acquired the lock, the primitive finds the handle's closed mark before any statement runs. Nothing
  ran, so `store_busy` — retryable, and true — is the honest answer, not `internal_error`. Requests
  dispatched after the reopen succeed.
  - **How it is minted.** The primitive raises a dedicated `WriterClosedError`, which is not an
    `aiosqlite.Error`. It cannot fake a driver error for the failure maps: `is_contention`'s
    contract excludes an exception carrying no result code by definition, and that sentence stays
    true.
  - **The primitive's own refusals share one base type**, none of them an `aiosqlite.Error`:
    `WriterClosedError`, and `LockWaitExpired` for a connection-lock wait that reaches its deadline.
    `LockWaitExpired` records whether the caller's deadline was the bound that cut the wait. The
    pool's lease wait raises the same on expiry, so the planning path needs no map of its own.
    Without this, a lock wait expires as `asyncio.TimeoutError`, which no failure map takes, and
    `_run_handler` answers `internal_error`.
  - The two dispatch sites that already hold the method name — `server.py`'s handler call and
    `dispatch_knowledge.py`'s wrapper — catch that base and answer `store_busy` with the method as
    its `verb`. **The one exception is a `LockWaitExpired` whose wait the caller's deadline bounded:
    it answers `deadline_passed`.**
    - For a `surface` carrying `deadline_at_ms`, the lease wait is bounded by that deadline alone,
      so its expiry answers with check point 1's code, issued at the lease wait before check point
      1 is reached.
    - It is decided by which bound cut the wait, never by re-reading the clock. The event loop
      fires a timer up to one tick of its clock's resolution early, so an expiry can land just
      before the instant a clock comparison would demand, and a second reading would then answer
      `store_busy`.
    - A `WriterClosedError` on such a request stays `store_busy`: a closed handle is not lateness.

**`next_group` waits for the model before it takes the writer.** It embeds inside its transaction
(`serving.py`, by necessity), so under `IMMEDIATE` it holds SQLite's write lock across that embed.
That costs milliseconds warm. Cold, while the model is still loading, it would cost seconds, with
every other writer meeting its budget meanwhile. So `next_group` waits for the encoder to finish
loading, off the event loop, before its first transaction, which is step 1 of item 3. Both steps
that serve and embed — step 1 when a run exists, step 3 otherwise — come after the wait, so the lock
only ever spans a warm embed.
- **The wait is the deferred encoder's `failure()`**, which blocks until the load ends and has no
  side effect. `artifact()` also blocks, but its own docstring forbids combining it with
  `declare_dim`, which the service's encoder uses.
- `next_group` needs nothing from the return value: a failed load raises at the embed regardless.

**2. The service keeps one writer connection and a small pool of read connections.**

**Each method is classified once, beside its handler in the method table, as a read or a write.** A
method is a write if it can write `memory.db` other than the event rows it emits about itself,
whatever its name suggests.
- **Writes:** `memory_remember`, `memory_amend`, `memory_retire`, `memory_fetch` (it mints receipts),
  the five consolidator methods (`memory_plan_groups`, `memory_next_group`, `memory_apply_merge`,
  `memory_apply_promote`, `memory_apply_discard`), and `knowledge_add`, `knowledge_rename` and
  `knowledge_remove`.
- **Reads:** `memory_search`, `memory_surface`, `knowledge_search`, `knowledge_list`,
  `knowledge_status`, `knowledge_refresh` (it reads the registry and spawns an indexer) and
  `knowledge_unlock` (it writes only the corpus's own database).
- A test holds the table equal to this set, so a new method cannot arrive unclassified.

**A read's first attempt never waits at its upgrade.** SQLite runs the busy handler for a write-lock
request only from a connection with no transaction open. A `search` or `surface` has read before its
event insert, so an upgrade that meets a *held* write lock is refused at once with primary
`SQLITE_BUSY`, and one that meets a *commit* since its snapshot is refused at once with
`SQLITE_BUSY_SNAPSHOT`. Measured by `spikes/m35_read_upgrade_probe.py`: a deferred reader is refused
in 0.0 s, and `BEGIN IMMEDIATE` commits at 2.03 s behind a 2 s hold. Writes wait because `BEGIN
IMMEDIATE` asks from no transaction; the two are not one case.

**A read keeps `retrieval.md`'s shape for its first attempt and gains one retry.** `retrieval.md`
makes a read one transaction including its events, and accepts a `store_busy` on the upgrade rather
than serializing every read behind every writer. That trade stands for the first attempt. What
changes is how often it is paid:
- Before M35, an in-process write could neither stale an in-process read nor hold a lock against
  it, because the two shared one connection and collided as a nested `BEGIN` instead.
- After it, every `remember`, `amend`, `fetch` or consolidator transaction opens a window in which a
  `search` or `surface` reaching its event insert is refused at once. If the writer still holds the
  lock, the refusal is primary `SQLITE_BUSY`; if it committed since the snapshot, it is
  `SQLITE_BUSY_SNAPSHOT`.
- **So a `memory_search` or `memory_surface` transaction refused for contention, by either code, is
  retried once, from `BEGIN IMMEDIATE`**, on its pool connection. They are the reads whose
  transaction writes.
- **The retry opens `IMMEDIATE`** because a deferred retry would meet a held lock exactly as the
  first attempt did, and a writer's transaction — the plan fallback, a `next_group` serve, an
  `apply_merge` — routinely outlasts a read pass. Opened `IMMEDIATE`, the retry waits for the writer,
  within the read's budget below, and can then be neither staled nor refused at once.
- **The cost is serializing retried reads behind the writer, and behind each other.** `retrieval.md`
  declines that for every read and accepts it here for a retry. A retry holds SQLite's write lock for
  its whole pass. While it does, every other read's first attempt is refused at once and retries
  behind it. So under a writer, concurrent reads serialize, bounded by the pool's size times one read
  pass. Warm, that is well inside the budget, and nothing starves past it.
- **No cycle is possible**, by the rule on waits at the end of this item.
- **The trigger is `transactions.is_contention`**: no attempt has waited, so the two codes need no
  telling apart. The retry sits around `in_one_transaction` in `reads.search` and `reads.surface`.
- **The retry is idempotent.** The refused attempt rolled back, events included. A refused retry
  answers `store_busy` as today, unless the request's deadline has passed (item 7).
- On the push path an unretried refusal is a skipped injection, and M35 is what creates the new
  traffic, so M35 owns the retry.

**A read, like a writer's transaction, has one wait budget per request.** It covers the lease wait
and the retry's wait together. The deadline travels with the leased handle (`pool.lease_deadline`),
and the retry's `BEGIN IMMEDIATE` polls for the write lock only until it; a pool connection's own
`busy_timeout` is 0 and nothing sets or restores it. A returned connection whose closed mark is set
is dropped. Without this, a lease wait and a retry wait would compound exactly as a writer's two
waits would.
- **For `memory_search` and every knowledge read, the budget is `ddl.BUSY_TIMEOUT_MS`.**
- **For `memory_surface`, it ends at the caller's deadline less the margin** (item 7), which
  validation already keeps within `ddl.BUSY_TIMEOUT_MS` of now.

**Which connection a request gets.** A read leases a pool connection for its handler's span, and a
write uses the writer, whose transactions item 1 serializes.
- **The handler signature does not change.** The dispatcher chooses which connection to pass, and
  only the planning path reaches the pool through the context. **The dispatcher obtains the writer
  through an awaitable accessor that `Store` gains with the reopen**, so a dispatch that finds the
  closed mark set can await the reopen in progress. The synchronous `connection` property remains
  for callers that run before the socket exists.
- **The lease covers the handler, not only its transaction**, because the knowledge reads run
  several transactions with autocommit reads and corpus opens between them.
- **The lease wait, and for `surface` the `deadline_at_ms` parse, sit inside `_run_handler`'s
  timer, so the access log's `duration_ms` spans them as well as the handler.** It is what the
  caller waited for, and a `store_busy` whose `duration_ms` is about one budget is what tells lease
  exhaustion from a slow handler. `schema.md`'s `call` row, which says `duration_ms` *"covers the
  handler alone"*, and `_Dispatched`'s docstring change to say so.
- The cost is that a read embedding its query before its transaction pins a lease while it embeds.
  Across a cold model load, every read that arrives pins one and waits on the same load. **The
  pool's size is a constant chosen to cover that case**: the concurrent clients of one store — the
  hook, the MCP servers, a consolidator, a CLI — each with a request in flight. Its reason is stated
  beside it, and it is not a configuration key.
- The census is one session's. A second session's reads during the same cold load degrade to the
  bounded wait, which is acceptable.
- A read that still finds the pool exhausted waits for a lease within its budget, and answers
  `store_busy` past it. For `surface` the lease wait ends at the deadline less the margin, and its
  expiry answers `deadline_passed`, as check point 1 of item 7 does, decided by the bound that cut
  it (item 1). `deadline_at_ms` is validated
  by the dispatcher before the lease (item 7), so the lease wait is bounded only by a value the
  validation ladder has accepted. **The planning path's lease is bounded the same way**, within
  `ddl.BUSY_TIMEOUT_MS`, since a `memory_plan_groups` or `next_group`
  queued forever would plan and commit after its client had given up.
- **Pool connections open lazily**, on first demand up to the constant. Opening them eagerly would
  add N × (connect + `sqlite-vec` load + pragmas) to the bind latency the hook's deadline is budgeted
  against (§"The model loads behind the socket"). The cost moves to the first read that finds no
  idle connection, and it is measured once.
- Every pool connection gets the store's pragmas and loads `sqlite-vec`. The pool closes with the
  service and on a failed startup.

**The knowledge registry table is created only by a write.** That means the first `knowledge_add`,
or the indexer, always under `IMMEDIATE`.
- **`ensure_table` splits.** Its presence read (`sqlite_master`) stays on every path, and its
  `CREATE` runs only in `knowledge_add` and the indexer, each on its writer. A registry read on a
  store without the table answers empty from that presence read, never from the driver's *no such
  table*. A bare `require` would otherwise answer `store_unavailable` through the knowledge wrapper,
  not the empty registry promised below.
- On a store without the table, a read answers as if the registry were empty. `list`, `search` and
  an unnamed `refresh` find none. `status name=…`, `unlock` and a named `refresh` answer
  `knowledge_base_unknown`.
- `rename` and `remove` are writes, but on a store without the table they have nothing to act on.
  They answer `knowledge_base_unknown` without creating it.
- So no read path ever writes DDL. A presence read followed by a `CREATE` on a pool connection is the
  CI failure's shape on the read path.
- A knowledge read's `call` row is then its only `memory.db` write on every store, and
  `schema.md`'s access-log section says so without its current precondition.

**No request holding the writer's lock waits on a pool lease, and no request waits for the writer
while holding a read snapshot open.**
- `memory_plan_groups` leases, plans, and releases its snapshot before it takes the writer.
- `next_group` releases the writer before it leases, at step 2 of item 3.
- A read's `IMMEDIATE` retry does wait for the writer while holding a lease, but it holds no
  snapshot while it waits: its `BEGIN IMMEDIATE` has not yet begun a transaction.
- Waits therefore only ever point from the pool to the writer, never back. That is what makes
  deadlock impossible, and it keeps a long-held snapshot from starving WAL checkpoints.

**3. Planning is computed from a read snapshot, and written in a short transaction that re-checks
it.**

**The plan.** `grouping.plan` runs in a read transaction on a pool connection and holds no write
lock. That transaction also records a fingerprint of the plan's input: the `(rowid, version)` of
**every active row, journal and long-term**. The plan reads both tiers — the journal as candidates,
the long-term tier as anchors — so a journal-only fingerprint would miss an anchor retired, merged
into or newly promoted while the plan ran.

**The write.** Closing a lapsed run, creating the run, inserting the groups and members, and the
events all run in one `IMMEDIATE` transaction. It first re-derives the fingerprint.
- **If it moved, the transaction plans inside itself, as today**, rather than planning again from a
  new snapshot. That is the smallest bound that still makes the check mean something, and it
  always terminates.
- The worst case is therefore two plans in one call. The journal that fits inside
  `_PLANNING_TIMEOUT_SECONDS` halves: from roughly 7,000 rows to roughly 3,500, against the measured
  12.2 s for 284. The comment on `_PLANNING_TIMEOUT_SECONDS` in `mcp/consolidator.py`, which
  derives the 7,000, is restated to match.
- The fallback holds the writer for a whole plan, as today, and only when a write landed during the
  plan.
- `version_seen` is recorded from the snapshot, which serve-time re-validation already checks.
- The run test ("effectively active") and takeover are decided inside the write transaction, as
  now, so two consolidators planning at once still end with one run.

**`next_group`'s inline replan keeps `architecture.md`'s rule that an implicit replan and the serve
after it are one atomic step.** It becomes:
1. A writer transaction asks whether an effectively-active run exists. If one does, it serves as
   today, embed included. It is short only when it finds none.
2. If none does, it releases the writer and plans on a pool snapshot.
3. One `IMMEDIATE` transaction re-checks the run, re-checks the fingerprint, and writes the plan
   **and** serves.

Step 3's run re-check has three outcomes:
- **No effectively-active run** — none, or a lapsed one the write closes as today → write the plan
  and serve.
- **The caller's own run** — a concurrent `next_group` from the same `(session_id, pid)`, which the
  one shared MCP process per Claude Code session makes ordinary, wrote first → discard the computed
  plan and serve from that run, as `serving._run_for` does today.
- **A stranger's run** → `Busy`, never replanned, since `next_group` never takes over.

**4. The wedge can be seen into.**
- **`SIGUSR1` dumps every thread's stack into `service.log`** through `faulthandler.register`, which
  works when the event loop itself is blocked. *(As built, then replaced: that handler walks other
  threads' frames without the GIL and crashed the service it was dumping, so the dump is now taken by a
  Python-level handler on the main thread. `architecture.md` §"What a service that stops answering
  writes" is normative for what that can and cannot see.)*
- **`SIGUSR2` dumps every asyncio task's stack and the in-flight requests into `service.log`**,
  through a loop signal handler. Each in-flight request is listed with its method, session id and
  age. This is the case the first dump cannot see: a loop that is idle while a coroutine awaits
  forever.
- **A request that outlives the idle poll's interval is logged at `INFO`**, by the poll that already
  wakes every 30 s (`lifecycle.idle_self_stop`). It is logged on each poll while it stays in flight,
  so the end of the log names the wedge however long it lasts. The line gives the method, session
  id and age, from the same in-flight registry `SIGUSR2` reads. An entry opens at `begin_request`
  with the method and gains the session id when the envelope resolves. A request wedged before
  that is logged as `session=unresolved`. So a wedge in which a coroutine awaits forever names
  itself in `service.log` with nobody at the terminal, which is how the 2026-09-29 one was found:
  after the fact. It costs nothing in steady state. A `memory_plan_groups` or `memory_next_group`
  entry is expected to exceed the interval on a large journal, up to `_PLANNING_TIMEOUT_SECONDS`;
  its method field is what tells that from a wedge. **The limit is the same as the stop line's**:
  the poll runs on the loop, so a *blocked* loop logs no line either, and only `SIGUSR1` sees that
  case.
- **A signal exit logs `stopping: reason=sigterm`** (or `sigint`), beside `reason=idle`. That
  separates a kill from a wedge in one direction only. A service that logged it was not wedged, but
  a wedged loop never runs the handler, so a wedge followed by `SIGKILL` still logs nothing but the
  line above.

**Both new handlers are installed alongside the `SIGTERM`/`SIGINT` pair, before `serve()`, and
removed on the same path out.** Both signals default to *terminate*, and a slow start is exactly
when an operator would send one. The `faulthandler` dump goes to the `FileHandler`'s own stream:
raw text, no timestamp or `pid=` prefix, since it bypasses `logging`. That is said where the log
format is described.

These replace the per-request start line this agent proposed (operator agreed 2026-09-29): together
they name the requests a hang is inside, and they cost no line per request.

**5. A corpus lock acquisition that sees no holder opens `BEGIN IMMEDIATE`, so two builds that start
together get the right refusal.** `scan.py`'s acquisition reads the lock row and writes it in one
deferred transaction. So two builds spawned inside one model-load window both read *no holder*, and
the loser gets the driver's `database is locked` instead of `IndexerBusyError`. `scan.py`'s own
note says the only obstacle was the lack of an `IMMEDIATE` variant of the primitive, and item 1
creates it.
- **Today's fast path stays.** The acquisition first reads the holder outside any transaction and
  refuses at once on a live holder, with no wait.
- **Only when it sees *no holder* does it open `BEGIN IMMEDIATE`**, re-read the holder inside, and
  take the lock. The second of two simultaneous builds then waits for the first's short acquisition
  to commit, reads the holder, and refuses `IndexerBusyError` as documented.
- `IMMEDIATE` on every acquisition would be worse. A build arriving during the winner's index phase
  would wait out that phase's current transaction instead of refusing at once, and past the corpus
  connection's 5 s `busy_timeout` it would answer the very `database is locked` this item removes.
- The cost is one extra `SELECT`. A wait is added only in a microsecond window: between the fast
  read and the `BEGIN IMMEDIATE`, the winner can commit its acquisition and open its walk
  transaction, and the loser then waits behind that one transaction before refusing.
- **The test** is the one `scan.py`'s note names: hold one acquisition's transaction open, for less
  than the corpus `busy_timeout`, while the other attempts its own, and assert `IndexerBusyError`.
  It is shown red under the deferred `BEGIN`.
- A second build arriving during the winner's index phase still refuses at once, and is tested.
- This is the one corpus-database transaction that changes mode.

**6. Exactly one `knowledge_build` row per build, visible when `refresh --wait` returns.** Today both
rows — `log.succeeded` and `log.failed` in `knowledge/indexer/main.py` — are written after
`scan.run`'s own `finally` has released the corpus lock that `--wait` watches.
- **The mechanism**: `scan.run` takes a completion callback and, **once it holds the lock**, invokes
  it before `_release`, on the success path and on failure by `Exception`. An acquisition that
  refuses, item 5's `IndexerBusyError` included, never took the lock, so the callback does not fire,
  and `main.build`'s own site writes that row. **It never runs for `CancelledError` or
  `KeyboardInterrupt`**: those release the lock and write no row. `schema.md` §"What is instrumented,
  what is not, and why" requires it: such a build must not wait out the write-lock budget to record
  its own death. So the callback cannot sit beside `_release` in its `finally`. It is a callback because
  `core/knowledge` cannot import `knowledge/indexer/build_log`. The indexer passes one that writes
  the row.
- **`BuildLog` writes at most once.** One latch is shared by the callback and `main.build`'s two
  existing call sites, which become no-ops once it has fired. Without it, every success and every
  post-lock failure is recorded twice. `experiments/m33_call_log_queries.py` sums `duration_ms` per
  corpus, so every build would appear to cost double.
- **The latch is set when the callback runs, not when a row commits.** So a row that is dropped on
  contention, or fails to build, is not attempted again after the release. That is best-effort, as
  today; retrying after the release would reopen exactly the ordering this item removes.
- **A failure after the release is reported by the exit status, not the row.** It can come from the
  corpus handle's close, or from `reporting.observe`'s reads inside its own open. It reaches
  `main.build`'s catch after the callback has latched, so the build exits 1 over the `ok=true` row
  its scan earned. Accepted: the row describes the scan, which committed, and `--wait`'s reader is
  told the index is built, which it is.
- **The callback never raises.** Its whole body, payload construction included, sits inside the
  row write's guard. `main.build` placed `succeeded` after its `try` for exactly this reason: a
  failure building the payload inside the `try` would write `ok=false` for a completed build. The
  callback now runs inside `scan.run`'s `try`, so the guard must be whole.
- **What this buys is narrower than "no indexer is running".** The process still outlives the
  release by its report and its store close; what becomes true is that its row has landed. Waiting
  on the holder's pid instead would race, since a build that finishes between two polls is never
  seen and its pid is never known.
- **Refusals raised before the lock is taken** (`IndexerBusyError`, `CorpusRootMissingError`, a
  dangling corpus) keep writing their row with no lock held, unchanged.
- **The cost**: the row is best-effort on a 5 s wait for `memory.db`'s write lock, so the corpus
  lock is now held up to 5 s longer while the service's writer is busy, and `--wait` sees the lock
  for that long.

**7. A push the agent never saw is never recorded as shown.** A `surface` row means *"this session
was shown this memory"*, and it is the denominator of D30's repair signal (`schema.md` §"D30's six
signals, as queries"). But the push hook abandons its request at 2 s (`hook/push.py`,
`_DEADLINE_SECONDS`), and the service, which cannot see the hook's clock, finishes and commits
anyway. That happens on a cold model load or a slow embed today. After item 2 it could also happen
on a `surface` retry waiting for the writer. Either way the rows count a block nobody read.
- **`memory_surface` gains an optional `deadline_at_ms` parameter: the caller's own deadline as an
  absolute wall-clock instant**, in milliseconds since the Unix epoch. The hook always sends it,
  computed from the same deadline it enforces. The hook reads `time.time()` at the same instant as
  its monotonic `started_at` and sends `int((wall_started + _DEADLINE_SECONDS) * 1000)`, while its
  own socket timeout stays monotonic.
  - It is absolute rather than a remaining duration because a duration is measured from when the
    service *reads* the request. A busy loop reads late, and a wedge that clears finds every push it
    missed still in its socket buffers; each would start a fresh budget and commit as shown.
  - Both ends are one machine, so they share one realtime clock. NTP slew is microseconds per
    second. A clock step is the one failure: rare, self-limiting, and stated.
  - `time.monotonic()` is not used, because its reference point is undefined across processes,
    whatever Linux and macOS happen to do.
  - Absent, there is no deadline, and the budget is `ddl.BUSY_TIMEOUT_MS` as for `search`.
  - Validation: `deadline_at_ms` is validated whole — an integer, no more than
    `ddl.BUSY_TIMEOUT_MS` in the future, or `bounds` — by the dispatcher before the lease, because
    it bounds the lease wait. It runs inside `_run_handler`'s accounting, so its `bounds` writes a
    `call` row as the handler's does; outside it, it would be a new exit with no row, which
    `schema.md`'s access-log section does not allow for. The rest of `surface`'s parameter rung runs
    in the handler after the lease. Both answer `bounds`, so the order is observable only in
    `data.field`, and §"Validation precedence" states it. The hook satisfies the bound by
    construction, because its 2 s deadline is below the 5 s budget, and a guard test pins the
    inequality (see the properties). `bounds` is checked before any deadline check, so a request
    both malformed and late answers `bounds`. A deadline already in the past is not malformed: it
    answers `deadline_passed`.
- **Past `deadline_at_ms` less a small margin, a `surface` answers `deadline_passed` at the check
  points below, and they are the rule.** A non-contention failure past the deadline — `index_failed`,
  an `internal_error` — keeps its own code, so a defect is never masked as lateness; like every
  failure, it commits nothing. The service checks at:
  1. before any work;
  2. after the query's embed, before `BEGIN` — so a push whose embed outlasted its deadline, on a
     cold load, spends no read pass that point 4 would only roll back;
  3. after a refused first attempt, before deciding to retry;
  4. inside the transaction immediately before `COMMIT`.

  The retry's `BEGIN IMMEDIATE` polls no later than the deadline less the margin, not to the whole
  deadline. **A contention refusal from the
  retry answers `deadline_passed` whenever the request carries a deadline.**
  - The retry opens from no transaction, so its only contention refusal is that wait giving up:
    `SQLITE_BUSY_SNAPSHOT` cannot occur under `IMMEDIATE`, and a retry holding the write lock meets
    no contention inside its pass. The wait was cut at the deadline, so its refusal is lateness.
  - That is decided by which bound cut the wait, never by a second reading of the clock: the
    refusal is the deadline's own, so the mapping is fixed when the deadline is.
  - Check point 3 does keep a clock read. The race there is benign: deciding to retry with a
    remainder near zero opens a retry that is refused at once, or, with the lock free, runs a pass
    that check point 4 rolls back. Either way it answers `deadline_passed` by the rule above.

  Past the deadline, the service rolls back — the `surface_call` and `surface` rows alike — and
  answers the new refusal.
- **The margin covers the whole path from the service's decision to the hook's `recv` returning, on
  the commit path.** That path runs from the pre-`COMMIT` check passing, through `COMMIT` itself —
  a WAL `fsync`, since the store's connections set no `synchronous` and WAL's default is `FULL` —
  the worker-to-loop handoff, the `call` row attempt on the response path, encoding, the socket, and
  the hook's wake.
  - The commit path sets the constant because losing the race there records a push as shown that
    nobody saw, which is the promise this item makes. The refusal path is shorter and covered by the
    same constant; losing it only turns `deadline_passed` into `unanswered` in `hook.log`.
  - It is a named constant with its reason stated beside it. It is set once from the distribution
    of the commit path over N pushes, measured under the load the host actually carries, with both
    ends stamping `time.time()` since they share a clock, at a stated high percentile. It is not set
    from socket transit on an idle host.
- **The hook's changes.**
  - It sends `deadline_at_ms`.
  - Its map from wire code to `hook.log` kind (`push._REJECTION_KINDS`) gains the new code. If the
    answer arrives inside the margin, it is a push failure like the others: one `hook.log` line and
    the relay instruction, as §"Degraded modes" already prescribes for `store_busy`. That section's
    list gains `deadline_passed`. `push.py`'s comment that counts the wire codes a `surface` can
    receive is rewritten without a count.
  - **A timeout after the send is logged under a new kind, `unanswered`**: sent, and no answer by
    the deadline. Today `push.py`'s catch-all logs it as `transport`, indistinguishable from an
    unreachable service. It gets its own word rather than `deadline_exceeded`, because `hook.log`
    records no phase and `deadline_exceeded` already means the pre-send case, where connecting
    consumed the whole budget (`push.py`'s `remaining <= 0` branch). One word for both would count a
    push the service never received together with one it received and could not answer in time.
  - **That catch sits around `rpc.surface_once` alone, not around `run()`'s whole `try`.** A
    `TimeoutError` from `connect_once` stays `transport`. That is `health()` on a listener that
    accepts and never answers, which `connect.py`'s warm branch re-raises bare: **a blocked event
    loop's** signature.
  - **A handler stuck behind a live loop is different, and where it shows depends on what it
    holds.** The service answers `health()` before any handler runs, so every such push passes
    `connect_once` and sends.
    - **A push whose own handler hangs** — an embed that never returns, a statement that never
      returns on its lease — times out in `surface_once`: `unanswered`.
    - **A wedge that holds the writer answers every later push at deadline − margin**, from the
      retry's own refusal: `deadline_passed` when that answer wins the margin race, `unanswered`
      when it loses. Its `call` row drops under the held lock either way.
    - **One that has pinned every lease is answered at its lease wait, with check point 1's code**,
      once the pool is exhausted, and its `call` row lands, since SQLite's write lock is free. So
      `deadline_passed` *with* `call` rows behind it is an exhausted pool, and *without* is a held
      writer: the one thing that tells the two apart in the store.
    - So **a run of `deadline_passed` and `unanswered` in `hook.log`, with no `call` rows behind
      it, is the post-M35 signature of the wedge this milestone was opened for**, and
      `service.log`'s long-request line (item 4) names the request holding it.
    - Before M35 every kind logged `transport`, since today's catch-all also takes a timeout after
      the send. So the 2026-09-29 wedge's `transport` lines do not say which kind it was.
- **What remains is a race stated, not a gap left.** A commit that lands just inside the margin
  whose response is then slower than the margin is still counted. The stated percentile is what
  bounds how often; a higher one costs push budget the hook has already partly spent connecting.
- **Every design sentence that states the old rule changes.** The normative-after list at the top
  names each site, in `schema.md` and `write-policy.md`. The replacement wording for the central
  ones:
  - The per-kind table's `surface_call` row: *"exactly one per `surface` call, always"* becomes
    *exactly one per `surface` call answered within its deadline*.
  - §"`call` is an access log, and every other kind is a semantic one": *"Every push writes
    `surface_call`"* becomes every push answered in time.
  - §"Linked sessions — what makes a cross-client signal computable", in its paragraph *"Honest limit
    on the session denominator"*: a push now reaches the service and emits no `surface_call` by
    design, and its closing condition gains *"and answering within the hook's deadline"*. That is
    the paragraph D30's zero-write signal is read through.
- **How often it happens, and where each part of it is counted:**
  - `hook.log`'s `deadline_passed` lines: every refusal that reached the hook before it gave up, its
    writer-wait share included, since the hook receives the answer whether or not the `call` row
    landed. This is the complete count of *delivered* refusals. A refusal answered after the hook had
    gone — a slow pass reaching check point 4 late — shows in `hook.log` as `unanswered` instead.
    A run of them across consecutive pushes is a wedge, not lateness: with no `call` rows behind
    it, a held writer; with them, an exhausted pool (see the hook bullets above).
  - The access log's `deadline_passed` among `memory_surface` calls: the refusals the service issued
    whose row landed. **This is a different population from the line above, and neither bounds the
    other.** A check-point-3 refusal answered under the held lock reaches the hook and drops its
    row. A check-point-2 refusal on a cold load lands its row and reaches a hook that has already
    gone, so it is `unanswered` in `hook.log`.
  - **What D30's denominator loses is the pushes the agent did not see**: `hook.log`'s
    `deadline_passed` plus `unanswered`, less the margin race.
  - `hook.log`'s `unanswered` lines: pushes sent and abandoned at the deadline with no answer — a
    slow embed, a writer wait the service did not refuse in time, or a handler that never answers
    behind a live loop.
  - `hook.log`'s `deadline_exceeded` lines stay what they are today: pushes abandoned before the
    send, because connecting consumed the budget. The service never received them.
- **The error table gains one code**, in the store-condition range beside `store_busy`. It records
  the wire name, the data (`{verb}`), disposition `refused` (the store is fine; the request was
  declined on its own terms), and that it is terminal for that request, not retried, because the
  caller has already gone.

### Invariants and properties to cover

- **No two transactions nest on a connection**, whatever interleaving the clients produce. A test
  holds one request's write transaction open **briefly** — well inside every budget, `surface`'s
  included, or it is testing the bounded wait instead — and issues concurrent reads and writes. The
  test asserts outcomes, not retries: all of them succeed, and none answers `internal_error`, which
  is what a nested `BEGIN` answers today. Which reads retry depends on timing: those reaching their
  event insert during the hold do, and those dispatched after the commit do not.
- **A same-task nested transaction fails at once**, not after the budget, and not as
  `store_busy`.
- **The only `BEGIN` on a service connection is the primitive's**, held by the drift guard of item 1.
- **The method table's classification equals the set in item 2.**
- **Another connection's write cannot refuse a write verb**, for every write verb. The fixture
  starts a write on a second connection while the verb's transaction is open. Under `IMMEDIATE`
  that write must wait, the verb must commit, and the second write must land after it. Under the
  old deferred `BEGIN` the same fixture refuses the verb, which is how the test is shown to test
  something: `spikes/m35_busy_snapshot_probe.py` turned into a test over the real verbs.
- **A plan holds no write lock while it computes**: during the snapshot phase, `remember`, `search`
  and a knowledge write all succeed. The fallback window that a moved fingerprint opens is the
  accepted pre-M35 cost, paid only when a memory row moved. A `search` arriving in it is refused on
  its first attempt and waits in its `IMMEDIATE` retry, which answers `store_busy` if the fallback
  outlasts its budget. The staleness probe re-run, which drives no writes, shows **no failed
  search**, where it showed five of eight.
- **Re-validation is asserted on its outcome, not its mechanism.** A journal row `remember`ed between
  the snapshot and the write transaction is among the run's members. A long-term anchor retired in
  the same window is no group's anchor.
- **`next_group` finding the caller's own run** at step 3 discards its plan and serves from that run.
- **`next_group` against a stranger's run** created between its snapshot and its write answers
  `Busy`, and serves nothing.
- **A read's upgrade meeting a held write lock is refused within milliseconds on its first
  attempt.** A second connection holds `BEGIN IMMEDIATE` across a `search` with the retry disabled,
  and the elapsed time is far below `BUSY_TIMEOUT_MS`.
- **With the retry**, the read succeeds once a hold shorter than its budget ends, and answers
  `store_busy` when the hold outlasts it. A read staled by a commit succeeds on its retry. The retry
  runs at most once.
- **A read's total wait, lease plus retry, is bounded by its budget.** The budget is patched before
  the store opens, as the writer's test does; a serving connection's pragma is 0 whatever it opened
  with, so the patched constant is the whole wait. The pinned leases return at about half the
  budget, and the writer's hold outlasts one and a half. The read answers `store_busy` at about one
  budget from its dispatch. Reverted, it answers at about one and a half, because the retry then
  polls a whole budget of its own. A pool that stayed
  exhausted throughout would answer at one budget in both arms and test nothing.
- **A `surface` past its deadline commits nothing, and answers `deadline_passed`.** Each scenario
  asserts that the store gains no `surface_call` and no `surface` row:
  - **A writer's hold that outlasts the deadline.** The first attempt is refused, and the retry
    waits only until the deadline less the margin, then answers `deadline_passed`. With the
    precedence reverted, the same call answers `store_busy` and still commits nothing, which is what
    tells the precedence from the rollback. No `call` row is asserted here, since the writer still
    holds its lock when the row is attempted.
  - **An encoder stub that sleeps past the deadline, with no writer.** It covers the older cause.
    Here the access log's `call` row carrying `deadline_passed` is asserted, because it lands. With
    both the post-embed and the pre-`COMMIT` checks reverted, the same call commits both kinds of
    row. Each check alone is shown to suffice by reverting the other.
  - **A pool whose every lease is pinned** — `search`es blocked in an encoder stub, one per pool
    connection — with a `surface` whose deadline is shorter than the leases' return. It answers
    `deadline_passed`, and its `call` row lands with that code, since the write lock is free. With
    the dispatcher's deadline exception reverted, the same call answers `store_busy`.
- **`deadline_at_ms` at its edges.**
  - A `surface` given an ample deadline behaves as today.
  - One given none uses the `search` budget and, at an exhausted pool, answers `store_busy`: the
    flag `LockWaitExpired` records is set by the deadline's presence, not by the method.
  - A deadline already past on arrival answers `deadline_passed` before any work: the encoder stub
    records no call. With check point 1 reverted, it records one and the answer is unchanged.
  - A deadline more than the budget ahead answers `bounds`, and the access log records a `call` row
    for it.
- **The hook sends `deadline_at_ms`, computed from the same deadline it enforces**, so the two cannot
  drift apart. The test patches `time.time` and asserts the sent value, rather than asserting that
  the two are "the same". A timeout after the send — the fake service answers `health` and never
  answers `surface` — is logged `unanswered`, not `transport`. A `TimeoutError` raised inside
  `connect_once` — the fake service accepts and never answers `health` — is still logged
  `transport`; with the catch widened to the whole `try`, it logs `unanswered`. The pre-send branch
  still logs `deadline_exceeded`, as its existing test asserts.
- **A `deadline_passed` answer is logged in `hook.log` as `deadline_passed`, with its code, and
  prints the relay instruction**, through the fake-service fixture the other codes use. A guard test
  holds every key of `push._REJECTION_KINDS` to an `ErrorCode` whose `wire_name` equals its mapped
  kind. The hook is stdlib-only and repeats the codes as literals, so without the guard an omitted
  entry would log `rejected_-32026` and every test would stay green.
- **`push._DEADLINE_SECONDS × 1000 ≤ ddl.BUSY_TIMEOUT_MS`**, asserted by a guard test that imports
  both, so the hook's own deadline is always a valid `deadline_at_ms`. Without it, raising one
  constant or lowering the other would make the service answer `bounds` to every push while every
  other test stayed green.
- **Contention on `fetch` and `retire` answers `store_busy`**, never `internal_error`.
- **A writer's total wait, connection lock plus write lock, is bounded by one `BUSY_TIMEOUT_MS`.** The test
  asserts the ratio to the budget, not an absolute, on a budget of about 500 ms patched before the
  store opens, with an external connection holding `BEGIN IMMEDIATE` for about 2.4 budgets and two
  writers dispatched together. The second answers `store_busy` at about one budget from its
  dispatch, whichever side of the budget refuses it: the connection lock (`LockWaitExpired`) or the
  poll for the write lock (`BEGIN IMMEDIATE` with nothing left). With the budget reverted, it
  answers at about two.
- **A connection closed by a failed rollback is replaced**: the next request dispatched succeeds.
  Two writes dispatched concurrently into the gap both succeed, over one reopened writer, with no
  leaked worker thread. A write already queued on the lock when the handle closed answers
  `store_busy` with its method as the `verb`, and ran nothing.
- **`next_group` holds no write lock while the model loads.** The fixture holds an active run of the
  caller's own with a servable group, so step 1 serves and embeds; on an empty store `next_group`
  embeds nothing and the reverted arm would pass. An encoder stub's load takes longer than the
  write budget. `next_group` is dispatched, then a `memory_fetch` while the load is still running.
  The probe is `fetch` because it writes without embedding, so it does not wait on the load itself;
  a `remember` would, and would pass either way. The `fetch` succeeds. With the wait
  reverted, it answers `store_busy` after one budget, with the load still running.
- **Two builds acquiring one corpus's lock together**: the loser answers `IndexerBusyError`, the test
  item 5 names. A build arriving during the winner's index phase refuses at once, with no wait.
- **A connection opened after startup onto a replaced or absent file** is closed, and the request
  answers by its family: `store_unavailable` for a knowledge verb, `internal_error` for a memory or
  consolidator verb, with a log line naming the drift. Each family is tested.
- **A knowledge read on a store without the registry table** answers as an empty registry and
  leaves the table absent.
- **Exactly one `knowledge_build` row per build.** When the lock was taken, it is committed before
  the lock's release; for a refusal, it is committed after that refusal. The count is tested on
  every path:
  - success, a post-lock failure, and a pre-lock refusal;
  - a failure injected into the callback's payload construction, which leaves the build's exit
    status unchanged, writes no `ok=false` row, and leaves at most one row — never a second attempt
    after the release;
  - a build cancelled mid-scan, which leaves no row and no lock;
  - a failure injected after `scan.run` returns, which leaves one `ok=true` row and exit status 1.
- **A knowledge write's registry reads on the writer run inside a transaction of their own**, see
  nothing of another handler's uncommitted transaction, and open no corpus database inside it.
- **Pool connections are all closed at shutdown and at a failed startup** — the autouse leak check
  in `tests/conftest.py` already fails a test that leaves a worker thread alive.
- **Each diagnostic writes what it promises.** The two dumps and the signal stop line are asserted
  by reading `service.log` from a real service process. The long-request line is asserted
  in-process, with `IDLE_POLL_INTERVAL_SECONDS` patched down as `test_service_lifecycle.py` does,
  since a real process would wait out a 30 s poll. The test uses an in-flight entry older than the
  interval and asserts the method, `session=unresolved` before the envelope resolves, and one line
  per poll while the request stays in flight.
- `schema.md` invariants 2 and 10 are unchanged and still hold: a mutation stays one transaction,
  and its events commit inside it. Invariant 2 is worded over *"every logical mutation"*. A
  `next_group` that now spans up to three transactions still mutates in exactly one — its
  `IMMEDIATE` step; the first step and the snapshot mutate nothing. The docstrings and
  `architecture.md` §Planning, which say *"one transaction"* per verb, are rewritten to say that.

### The perturbation table, walked before the first review round

The table has three axes. **Where a request is interrupted**: before `BEGIN`; between its read and
its write; mid-commit; while waiting for the lock; while holding a pool lease. **Who else writes**: a
request in this process on the writer, a read upgrading on a pool connection, the access log's own
connection, the indexer process, a second service, an operator's shell. **Which connection is
involved**: the writer, a pool connection, the access log's. The walk is written down in
`reviews/m35-brief-perturbation.md`, and each cell that forced a requirement above is marked there.
The implementation walks it again against the code. The access log keeps its own connection, with
`busy_timeout` at zero, and stays best-effort under invariant 10's exemption.

### Done when

Every numbered item above is in the tree, and the design sections named at the top state them.

**The CI failure this milestone was scoped to fix cannot recur:**
`test_rename_and_remove_reach_a_real_service` (run 36657562917) passes by construction, not by luck.
The busy-snapshot regression test is shown red against the old deferred `BEGIN` before it counts.

The staleness and busy-snapshot probes re-run; the read-upgrade probe is a one-off measurement with
nothing to re-run:
- The staleness probe fails no search.
- The busy-snapshot fixture is a test.
- The staleness probe gains a phase that drives `next_group` and `apply_merge` against concurrent
  `search` and `surface`. That is the traffic item 2's retry exists for, which a plan alone no longer
  produces.

Every property above has a test, each mutation-verified by reverting the fix it guards.

Every comment and docstring that describes the pre-M35 mechanism is rewritten or removed. Among
them:
- `build_log.py`'s fresh-transaction rationale.
- `dispatch_knowledge.py`'s `SQLITE_BUSY_SNAPSHOT` note.
- `server.py`'s concurrency note.
- `mcp/connection.py`'s derivation of `REQUEST_TIMEOUT_SECONDS`, whose premise item 1's single budget
  keeps true, now for a stated reason.
- `registry.ensure_table`'s and `registry.ensure`'s docstrings, which say every knowledge verb or
  read creates the table.
- `main.build`'s rationale for where `succeeded` sits, which item 6 makes moot.
- `scan.py`'s and `lock.py`'s notes that closing the two-builds race *"would mean a `BEGIN IMMEDIATE`
  variant"*, which item 5 now does.
- The comment on `ddl.ACCESS_LOG_PRAGMAS` and `AccessLog`'s class docstring, whose reason for a
  private connection changes with `schema.md`'s; and `access_log.py`'s comments naming `ValueError`
  for a closed handle, which becomes `WriterClosedError`.
- `_Dispatched`'s docstring in `server.py`, which says `duration_ms` covers the handler alone
  (item 2).
- The `surface_call` payload class's docstring in `core/events.py`, *"exactly one per push"*, which
  item 7 narrows to pushes answered in time.
- `push.py`'s two comments that put *"a timeout mid-request"* under `transport` — the catch-all's
  and `_classify_failure`'s, the second adding that `architecture.md` draws no distinction — which
  item 7's `unanswered` falsifies.

The grep for each claim, not this list, decides completeness.

**`README.md` tells an operator what they can now do and read**:
- §"Files and logs" says what `service.log` carries: the two dumps, the long-request line and the
  stop reasons.
- §"When something is wrong" gains a row for a service that stops answering. It says to look for the
  long-request line, then `kill -USR2 <pid>` for the in-flight requests and tasks, or `kill -USR1
  <pid>` for thread stacks if the loop itself is blocked. A planning method under five minutes is a
  plan, not a wedge. It also says how each kind of wedge reads in `hook.log`:
  - a blocked loop logs `transport` on every push, though the socket connects;
  - a wedge holding the writer logs `deadline_passed` — or `unanswered`, when the answer lost the
    margin race — on every push, with no `call` rows behind them; the same run *with* `call` rows is
    an exhausted pool;
  - a push whose own handler hangs logs `unanswered`.

  In every case the long-request line in `service.log` names the request. One wedge looks healthy
  in `hook.log`: pushes succeed while every write answers `store_busy` at about one budget. That is a
  wedge holding the writer's lock with no transaction open, and the long-request line names it too.
- Its `refresh --wait` paragraph says what `--wait` now guarantees.

`./check.sh` is green.

**No latency bar.** The host is busy for days (operator, 2026-09-29), and no decision here turns on
a millisecond figure. Each property above is pass or fail. These are measured once, reported
against a control run on the same machine at the same load, and decide nothing:
- the service's warm `search` time;
- the pool's footprint;
- the `store_busy` refusal rate on `memory_search` and `memory_surface` during the new probe phase,
  with and without the retry, **counted from the responses the probe receives**, per method and per
  attempt. The access log cannot supply it. A read refused at a held lock returns while the writer
  still holds the lock, so its `call` row, on a connection with `busy_timeout` 0, is dropped at
  once; only the stale-snapshot share lands. The log-derived rate, from
  `experiments/m33_call_log_queries.py`'s refusal-by-code query, is reported beside it as the access
  log's undercount. Each arm runs on its own copy of the store, over rows with `id` greater than the
  phase's first. The per-attempt counts also bound the convoy item 2 names: they show how many
  reads needed their retry, which includes any that queued behind another read's retry rather than
  the writer. The probe cannot see which held the lock, so it reports the count, not the cause.

### Scope fence

**Not** a change to any verb's result shape, to any event's payload, or to the DDL. What changes is
which refusal some calls answer, each named where it is decided:
- `fetch` and `retire` under contention, and any request the primitive finds on a closed handle,
  answer `store_busy` (item 1).
- Knowledge reads on a store without the registry table answer as an empty registry (item 2).
- The losing build answers `IndexerBusyError` (item 5).
- `memory_surface` gains one optional parameter and one wire code, and `surface_call`'s cardinality
  rule narrows to calls answered in time (item 7). This is the only new wire code.
- `call.duration_ms` spans the lease wait, and for `surface` the `deadline_at_ms` parse, as well as
  the handler (item 2). No shape changes, but the latency population
  `experiments/m33_call_log_queries.py` reads moves.

**Not** the access log's connection or its best-effort terms. **Not** a fix for the wedge beyond
making the next one diagnosable; if the dumps name a cause, that is the next milestone's. **Not**
the installer: its whole-entry compares, the file-reasons count and the `doctor` check are M36.
**Not** retrieval quality: the embedder spike closed that side for
now (`research/granite-embedder-spike.md`).

**Not** `BUSY_TIMEOUT_MS`: it is the budget for every request here except `surface`, and raising it
is the first thing a red test invites, but it stays 5 s.

## M36 — An upgrade the installer refused, a stale install nothing reported, and the release

Normative: `design/harness.md` §"The installer's two targets"; `design/architecture.md` §"The
install contract"; `design/distribution.md` §"The front door" for `doctor`'s rows and their order,
and §3 "The version scheme" for the release.

**Upgrading has two halves and neither works end to end.** The package moves on `uv tool upgrade`;
what an earlier version wrote into a project moves only when the installer is re-run, and on kiro that
re-run refuses its own previous install the day any field of an entry changes. Under Claude Code the
re-run works, but nothing tells a user they need it: an install that predates `alwaysLoad` keeps
working with its tool descriptions deferred, and only `README.md` says why. This milestone closes both
halves and then releases, because `0.1.0` is the version on PyPI and it can no longer open any store
this build has touched.

### 1. Kiro compares on ownership, as Claude Code already does

**Where.** `writer.py`'s `_guard_existing_entries` refuses when the `mcpServers.zikaron` entry is not
equal to `mcp_servers_value(...)`, and `_differing_zikaron_hooks` refuses when a recognised hook entry
is not structurally equal to the generated one. So any field this installer adds or changes — a new
key, a moved `TIMEOUT_MS` or `HOOK_TIMEOUT_SECONDS` — turns every unmodified earlier install into a
conflict, and the upgrade is refused without `--force`. Nothing tests the case.

**What changes.** Ownership, defined once and used by both targets:
- **A server entry** is owned by `entries.MCP_OWNERSHIP_FIELDS` — the interpreter path and the mode.
  A different value there refuses, naming which of the two differs, since they call for different
  responses. Any other difference is merged **per key**, as `.mcp.json` is: a key of the user's on
  Zikaron's entry is kept and named, a value this install writes is set and named. `--force`
  replaces the entry whole and names the keys that dropped.
- **A hook entry** is owned by its command, unquoted as `_entry_command` already unquotes it. An entry
  recognised as Zikaron's — by the command's file name, or in the array format by the reserved
  `name` — whose command is not this install's refuses. One whose command is this install's and whose
  other fields differ is rewritten, and the install names the trigger so a hand-edited timeout can be
  re-applied.
- **An entry on a trigger this install does not write is neither compared nor touched**, in either
  format, as the Claude Code target already treats a group outside the triggers it writes. Kiro
  refuses one today (*"not an entry this install writes"*), and in the array format its merge removes
  every entry carrying our command whatever its trigger; both narrow to the triggers this install
  writes, since an entry elsewhere is one nothing here would replace it with. An array entry carrying
  a reserved `name` stays recognised by that name, so one whose `trigger` was changed is rewritten
  and reported like any other field.

**The predicate and the per-key merge move out of `targets.py` into one place both targets import**,
since two copies of an ownership rule is the drift this item exists to end. What each target *says*
stays with the target: a kiro server entry is registered for one agent, a `.mcp.json` entry for the
whole session, and the notes must be true of their own file.

**Wording.** The server refusal says *"That is a previous install from a different interpreter"*,
which is true only once ownership is what refuses; after this change it is true of a differing
`command`, and a differing `args` says a different mode instead. The hook refusal's *"or an entry you
edited"* names the edit that is now rewritten and reported, so both kiro refusals end in the shared
place's account of another install, as Claude Code's do (`targets._ANOTHER_INSTALL`).

**Tests.** New: an earlier kiro install whose server entry carries an extra key and whose hook
entries carry an old timeout upgrades without `--force`, keeps the extra key, and reports both; the
same in the array format; our command on a trigger this install does not write, without a reserved
`name`, is left in place, in both formats; a different command still refuses, in both formats and for both halves; a different
`--mode` refuses and names the mode. **Existing: every test that asserts a refusal on a
non-ownership difference inverts into a rewrite-and-report assertion**, and a class docstring stating
the old contract goes with it; a refusal test that matches on the old sentence matches on the
field-naming one. A test of behaviour this change removes is red against the fix; one that pins
behaviour it keeps — a different command still refusing — is shown red against a mutation that
compares nothing, instead.

### 2. `doctor` reports a Claude Code install that predates `alwaysLoad`

**Operator decision 2026-09-30: `doctor` keeps the checks it has and gains exactly one — whether
Zikaron's `.mcp.json` entries carry `alwaysLoad`.** Nothing else about that file is judged: not its
syntax, not which interpreter an entry names, not its mode.

**One row, directly after `check_socket_path` and before the subagent row**, so the two rows that
read a project's Claude Code files sit together.
- **Present only when `<project>/.mcp.json` parses as a JSON object whose `mcpServers` is an object
  carrying a Zikaron server as a key** — `MCP_SERVER_NAME` or `CONSOLIDATOR_AGENT_NAME`. Anything
  else — no file, a file that cannot be read or does not parse, no Zikaron entry — produces no row:
  the question is whether an install is older than the key, and a project with nothing to ask it of
  has no answer, which is the *not checked* versus *nothing found* distinction the subagent row
  already draws.
- **Fails when a Zikaron entry that is an object has no `ALWAYS_LOAD_KEY`.** The remedy says to
  upgrade Zikaron in the interpreter the project was installed from and re-run the installer with
  `--harness claude-code`, which upgrades the entry in place — or to set the key by hand, `false`
  to keep deferral. It names no interpreter, because `doctor` may run from a different one than the
  install did.
- **Passes otherwise, whatever the key's value.** `alwaysLoad: false` is how a user asks for
  deferral, and failing on it would exit non-zero forever over a choice — the argument that made
  the subagent row `REPORTED`.

**Tests**: an entry without the key fails, with the remedy; a current install, **generated through
`claude_mcp_servers_value`** rather than written by hand, passes; `alwaysLoad: false` passes;
`"zikaron": null` produces a passing row rather than a traceback; no file, a file that cannot be read
or does not parse, and a file naming no Zikaron server produce no row. The path is `targets.py`'s,
lifted from `ClaudeCodeTarget._mcp_config` into a module-level function both the target and the row
call, as `agent_scan.agents_directory` already is for the subagent row. `test_doctor.py`'s order test
asserts only the last two rows today, so it gains a `.mcp.json` fixture and asserts this row's place.
`README.md`'s troubleshooting row for deferred tools points at this check; `distribution.md` §"The
front door" names the row in its place in the order; and every sentence that counts `doctor`'s
conditional rows, or lists what `--project` reaches, is corrected without a new count.

### 3. Counts written out in prose where the enumeration lives in code

**"The eight file reasons", and "nine" for the breakdown's keys, are spelled out across the code, the
tests and `design/knowledge-index.md`.** `SkipReason` and `SKIP_REASON_KEYS` are the enumeration, and
`SKIP_REASON_KEYS` is already guarded against the design's table, so the written count is the only
part that can drift, and it would drift silently on the next reason added. `coding-standards.md` §5
already forbids it. **The predicate, not a list of sites**: every sentence that states how many skip
reasons, file reasons or breakdown keys there are — including the ordinal form, *"inventing a
ninth"*. Find them with `grep -rnE -i '\b(six|seven|eight|nine|ten|eleven|twelve|ninth|tenth)\b'
zikaron tests design/knowledge-index.md`, which over-matches by design, and read every hit. Drop the number; where a
count genuinely helps a reader, the design's table is where they count it.

**Test**: a drift guard over `zikaron/`, `tests/` and `design/knowledge-index.md` that fails on a
number word from *six* to *twelve* or a digit in the same range, then optional emphasis, an optional *file* or
*skip*, optional emphasis, and *reasons* — or a number-word *-way* compound within a few words of
*skipped* or *breakdown*. **It matches after collapsing whitespace, newlines included, in every file
it scans**, because both kinds wrap a site across a line break — *"the eight skip / reasons"* in
`counters.py`, *"one of the eight / reasons"* in the design — and a bare *-way* would redden on
unrelated *"two-way"* prose. **Its own pattern is assembled from fragments**, as
`tests/test_publication_hygiene.py` already does, or the guard matches its own source. It cannot
pattern every phrasing — *"all nine"* names nothing it could anchor on — so the reading above is
what removes those, and the guard keeps the common form from coming back. **The bound is
deliberate**: the enumeration is eight and nine today, and the guard must catch the neighbours a
reason added or removed would produce, while *"two reasons"* and *"three reasons"* are ordinary
English this tree already uses and must stay green. Mutation: re-inserting each wrapped site — one
in code, one in the design — and one single-line site each turns it red.

### 4. A test fixture that waits ten seconds for nothing

**`tests/test_knowledge_cli_integration.py`'s `reaped` fixture spends its full deadline in every
teardown that found a service.** It kills the service and then polls `waitpid` — but
`lifecycle._spawn_detached` reaps its own child on a daemon thread, which wins, so every later
`waitpid` raises `ChildProcessError`, which the fixture suppresses, and the loop runs to its deadline.
**Fix**: after the kill, poll until the process is gone by a test that does not depend on who reaps it
— `os.kill(pid, 0)` raising `ProcessLookupError`. A zombie still answers that probe until it is
reaped, so the poll ends exactly when the daemon thread has reaped it. **Its siblings are not the same
defect**: every other `waitpid` loop under `tests/` ends its wait on `ChildProcessError` rather than
spending it — most by returning, and `test_hook_connect_race.py`'s by advancing a `for` over pids,
each waited on with a blocking `waitpid`. **Measured**: the file's wall time before and after, from
`--durations` — six teardowns at 10.02 s each and 76.5 s for the file, before; 15.8 s for the file
after, with no teardown among its slowest.

### 5. The release: `0.3.0`

**M36's commit carries `version = "0.3.0"`, and that is the commit the operator tags** `v0.3.0` after
merging it — operator decision 2026-09-30, which is the case `CLAUDE.md`'s rule against setting a
release version reserves: the number is set in the commit that gets tagged, and the tag is the
operator's. `design/distribution.md` §3 is normative, and `release.yml` refuses a tag that disagrees
with `[project] version`. **The first commit after the tag returns the tree to `0.3.1.dev0`**; that
is not this milestone's commit and not its reviewer's to check.

**Why `0.3.0` and not `0.2.0`**: two schema steps have accrued since `0.1.0` and each is a minor bump
on its own (§3), so `0.2.0` is never released. This milestone moves no artefact's *shape* — both
targets write what they wrote — so it adds nothing to the number.

**What ships beside the number:**
- **`README.md` states the product as `0.3.0` ships it.** Every section a user reads between
  `uv tool install` and a working session, checked against the tree rather than against the milestone
  list — the kiro upgrade paragraphs, the `doctor` output and its rows, and anything changed since
  `v0.1.0` that it does not yet say.
- **No document states the tree's version except `pyproject.toml`**, so the bump after a tag touches
  one file. Every sentence **in the live documents** — `CLAUDE.md`, `README.md`, `design/`,
  `FINDINGS.md`; the archive and `research/` record what was believed and are not re-pointed — that
  names the current number **or states what is unreleased** says instead what a release shipped, or
  what a `.dev` suffix means, as a fact the tag makes true rather than false:
  *`0.3.0` ships schema 3, `0.1.0` shipped schema 1, and each step between is a minor bump.*
- **Release notes for the operator**, in the pull request's description, written for someone upgrading
  from `0.1.0`: everything since `v0.1.0` that such a user meets, derived from each commit message in
  `git log v0.1.0..` and the milestone blocks in `FINDINGS-archive.md`, and at least — that the store
  migrates forward on first open and `0.1.0` cannot open it afterwards; that `zikaron init` now creates a store and every
  `knowledge` verb refuses a project without one; that the installer must be re-run and now upgrades
  in place on both harnesses; that a running service is not replaced by an upgrade until it idles out
  or is stopped; what `doctor` now checks; and why there is no `0.2.0`. Publishing them as the release
  body is the operator's act, as is the tag.

### Done when

1. Items 1–4 are in, and every new or inverted test was **seen red** — against the tree before its
   fix, or, for a guard or a test pinning behaviour that does not change, against the mutation it
   names.
2. `design/architecture.md` §"The install contract" and `design/harness.md` state one ownership rule for
   both targets; nothing in `zikaron/`, `design/` or `README.md` still says kiro compares whole; and
   `README.md`'s `--force` row covers kiro's server entry as well as `.mcp.json`'s.
3. `pyproject.toml` says `0.3.0`, `README.md` is current as item 5 defines it, and the release notes
   are drafted.
4. `./check.sh` is green. The pull request's CI is the version matrix.

### Scope fence

**Not** any `doctor` check beyond item 2's (operator decision): no validation of `.mcp.json`'s
syntax, interpreter paths or modes. **Not** a `doctor` check for kiro: its config is a path the user
supplies to `install --agent`, and `doctor` has no such flag. **Not** a staleness check on Claude
Code's hook entries in `settings.local.json`: a stale timeout there degrades nothing a user would
notice, where a deferred tool description is measured to change behaviour. **Not** a version handshake between a client and an older
running service — `distribution.md` §3 names that gap and declines it. **No change to any string the
installer writes** into either harness: the golden files under `.kiro/` and
`tests/test_install_targets.py`'s artefacts do not move. **Nothing in the service.**

## M37 — Edit guards: a find-replace edit is refused, and an edit asks to be re-read

Normative: **`design/edit-guards.md`** (all of it); `design/harness.md` §"The installer's two
targets" for where the guard selection's shape lives; `design/architecture.md` §"The install
contract". Decision: D38.

**This milestone takes up the 2026-09-24 *evaluator with teeth* proposal and supersedes it as a
candidate.** That proposal (`FINDINGS-archive.md` §"The strongest M32 candidate, and why";
`research/leibatrader-consolidation-2026-09-24.md` §"Candidate: an evaluator with teeth") argued
that evaluating behaviour and reacting is the only way a rule has held in this project, and split
rules into deterministic synchronous predicates and an asynchronous watcher. M37 builds the first
class with **no model at all**, for two rules `CLAUDE.md` already states. The watcher class is not
scoped by this milestone and stays a proposal. The proposal's stated risks are answered in
`design/edit-guards.md`: a false block (§3.4's override and §6's fail-open), per-call latency (no
model, stdlib only, operator: timing is not a constraint), and a fourth place rules live (two rules,
both already in `CLAUDE.md`; the hook is enforcement, not a new source).

Feasibility is measured, not assumed: `research/claude-code-tool-hook-probe.md` shows a
`PreToolUse` deny reaching the model as the tool result, holding under `bypassPermissions`, and
`PostToolUse` `additionalContext` reaching the model after an edit.

### What ships

1. **`zikaron/guard/`, a new stdlib-only package, and the console script `zikaron-guard`.** It reads
   the hook payload from stdin and dispatches on `hook_event_name`: `PreToolUse` runs the
   find-replace rule (`design/edit-guards.md` §3), `PostToolUse` the re-read nudge (§4). Pure
   functions from a parsed payload to a decision, with a thin `main` that does the I/O, so the rule
   table is tested without a process. The new package joins `check.sh`'s coverage list, which
   `tests/test_check_gate.py` holds complete. The script joins `[project.scripts]`, which nothing
   holds yet: `tests/test_cli_front_door.py` resolves only the `zikaron` entry, so M37 extends it to
   resolve every declared script, and an entry naming a module that does not exist fails; and
   `tests/test_distribution.py::test_the_wheel_declares_every_console_script` hand-lists three, so
   M37 makes it read `[project.scripts]` from `pyproject.toml` instead.
2. **The guard triggers and matchers are harness data.** `HarnessSpec` gains a field carrying the
   guard hooks' trigger names and matchers, `None` for kiro. The installer's kiro refusal is derived
   from that `None`, not written as a branch on the harness name. They do not enter `TRIGGERS`,
   which is `zikaron-hook`'s dispatch table. The field gets its row in `design/harness.md` §"The
   table" and its drift-guard test in `tests/test_harness_table.py`, as every differing value does.
   The payload's own field names are **not** spec data (`design/edit-guards.md` §1).
3. **An installer selection, `--components {memory,guards,both}`, default `memory`.** Without the
   flag, an install writes byte-for-byte what it writes today. `guards` writes only the guard hook
   groups; `both` writes both. `--harness kiro` with `guards` or `both` is refused before anything is
   written, and so is `--model` with `guards`. `zikaron install` passes the flag through unchanged.
4. **Ownership by selection.** The Claude Code target recognises a guard group by its command's
   file name, as it already recognises a memory group, and an install replaces or adds only the
   groups of the selection it was given. `Commands` gains the guard script, and `missing()` checks
   only the scripts the selection needs. A guards-only install is exactly `design/edit-guards.md`
   §5's: the guard groups under `hooks` and nothing else — no `enabledMcpjsonServers`, no
   `permissions.allow` entry, no `.mcp.json`, neither the consolidator nor the skill, none of the
   memory install's notes — and `--no-trust-tools` is a no-op. Each guard entry states its
   `timeout`. **The start text** (`design/edit-guards.md` §5) is carried by `zikaron-hook`'s
   existing `SessionStart`/`SubagentStart` entries: `guards` and `both` write
   `zikaron-hook --components guards|both`, a `memory` install writes the entry unchanged, and a
   guards-only install therefore writes those two groups too, with `zikaron-hook` among the
   scripts `missing()` checks. The shared start entry takes the **union** of what it carries and
   what is being installed, so `guards` over `memory` writes `both`, and `memory` over `both` keeps
   it.
5. **The guards are not installed in this repository** (operator decision 2026-10-07). This
   repository's `.venv` is an editable install of the code under development, so a guard installed
   here would run whatever the tree holds, and a broken guard would cripple the agent building it.
   They are exercised in throwaway projects outside every scratch root, as the live test does.
   `~/Trading/LeibaTrader`, which runs this `.venv`, is likewise unaffected: its
   `settings.local.json` names no guard.
6. **Documents.** Written with this brief: `design/edit-guards.md`, D38 in `design/overview.md` and
   `FINDINGS.md`, and the new document's rows in the design tables of `CLAUDE.md`,
   `design/README.md` and `design/overview.md` §5. Owed by the build: `design/harness.md` §"The
   table" (item 2), its artefact table, and §"Three flags, and what each refuses" gaining
   `--components` — its heading carries a count, so it loses the count rather than changing it, and
   `CLAUDE.md`'s `harness.md` row with it; `design/architecture.md` §"Distribution artefacts" and
   §"The install contract"; `design/distribution.md`'s console-script statement; `README.md`'s
   install section.
7. **The prompt texts, written by memory-reviewer** (operator decision 2026-10-07). Before the
   code that emits them is final, memory-reviewer writes the final wording of the guard start
   text, the deny message, the invalid-marker message, the override acknowledgement and the nudge
   into the M37 review file, against what `design/edit-guards.md` §3.4, §3.5, §4 and §5 say each
   must contain. The builder copies that wording verbatim and the tests assert it.

**The release that carries M37 should be a minor, `0.4.0`, not `0.3.1`.** A default install's
artefacts keep their shape, so `design/distribution.md` §3's artefact-shape rule — whose reason is
an upgrade that must refresh what it wrote — does not force it. But the install contract (§3: *the
set of shapes and locations of the artefacts the installer writes*) gains a selection, a console
script and two hook groups, and a patch number tells a reader the contract did not grow. The
operator set `0.4.0` in this milestone's pull request, to release it from the merge (2026-10-07);
the tag is the operator's.

### Invariants and properties to cover

- **Determinism**: the same payload, `$TMPDIR` and contents of any scratch script the command runs
  always yield the same output. A property test over generated commands calls the decision
  function twice.
- **The rule table**: every row of `design/edit-guards.md` §3.2, the command-position rule (§3.1),
  the heredoc rule (rows 1–4 scan a body only under a shell or interpreter opener; row 5 never
  looks inside one for its sink),
  line continuation, the per-form targets and exemptions (§3.3) and the "not denied" list, as a
  parametrised table of commands with their expected decision. **`design/edit-guards.md` §8 is
  the table's seed, and the one place its rows are listed**: the test table holds every row of
  §8 and every edge §7 names with the value §7 gives it, judged under §8's stated payload. The test pins `cwd` and `$TMPDIR` with `monkeypatch`, since on the
  macOS job `$TMPDIR` is set by the OS and a row judged under the runner's own value would differ
  by machine. A row
  found during the build goes into §8 in the same change as the test.
- **The override**: examined only after a form matched; a valid one returns **no
  `permissionDecision`**, only the acknowledging `additionalContext`, which names every authored
  target of every form that matched, each once, in command order, or the fixed clause where none
  resolves (`design/edit-guards.md` §3.4, amended 2026-10-07); a bare marker, a one-word
  reason, or a marker glued to a preceding word (`f#ZIKARON-FORCE`) denies with the matching
  message; a marker on a command no form matches produces no output at all.
- **`tool_name`**: a `PreToolUse` payload for any tool but `Bash`, and a `PostToolUse` payload for
  any tool outside the four, produce no output; the guard's tool sets are the spec field's matchers,
  read from it.
- **The nudge**: line ranges from `structuredPatch`, read from `tool_response` or `tool_output`;
  omitted when absent; `notebook_path` for `NotebookEdit`; no nudge for a `Write` whose result
  `type` is `"create"`, nor for a scratch path; a nudge for a `Write` with no `type`.
- **The matchers** are `|`-joined bare tool names, which the guard splits to get its tool sets.
- **Fail-open**: malformed JSON, an empty stdin, an unknown event, a missing field and an exception
  inside a rule each exit 0 with no output.
- **Stdlib only**: `zikaron/guard` is added to `tests/test_hook_stdlib_only.py`.
- **Install by selection**, on the perturbation table below.
- **Kiro refuses** `guards` and `both`, from the spec field, with nothing written.
- **The spec field's row** in `design/harness.md` §"The table", held by `tests/test_harness_table.py`.
- **Every guard entry states its `timeout`**, read from the `zikaron/guard/` constant.
- **The start text by selection**: `zikaron-hook` with no flag emits exactly today's write policy on
  `SessionStart` and `SubagentStart`; `--components guards` emits only the guard start text and
  opens no socket; `--components both` emits the policy then the guard text. The guard text
  carries no override syntax. A `memory` install's start entry is byte-identical to today's.
- **A live test** (`integration_claude`): one real session under `--permission-mode
  bypassPermissions`, **in a project created outside every scratch root** of
  `design/edit-guards.md` §3.3 — a nonce directory under `Path.home() / ".cache" /
  "zikaron-live-tests"`, removed in teardown — because pytest's `tmp_path` lies under `/tmp` or
  `$TMPDIR`, where the guard would exempt the denied command and suppress the nudge; given the exact commands to run as the probe was, so that neither the edit nor
  the override is the model's choice, and asserted on what the harness recorded rather than on what
  the model chooses to say. In it a `sed -i` is denied with the deny reason as its tool result — the
  deny holding under that mode is itself one of `design/edit-guards.md` §2's rows; the override
  runs, changes the file, and its acknowledgement reaches the model; and an `Edit` is followed by
  the nudge. **The mode is forced, and it hides one thing**: under headless `default` a
  no-decision command waits for an approval nobody can give, so the file would not change; and under
  `bypassPermissions`, `allow` and no decision look the same. So the override's withdrawing rather
  than granting is held by the hermetic test on the hook's JSON — no `permissionDecision` key — and
  the live test asserts only the file change and the acknowledgement. **The two halves are recorded in
  different places**: the deny reason is a `tool_result` in the `stream-json` output, while
  `additionalContext` never appears there and is found only in the session's own transcript under
  `~/.claude/projects/`, as an `attachment` rendered as `<system-reminder>PostToolUse:Edit hook
  additional context: …` — the fragile half (`design/edit-guards.md` §2), so that is the record
  the test reads for the nudge and the acknowledgement.
  Hermetic equivalents stub the harness as the existing tiers do; nothing is covered only live.

### The perturbation table, walked before the first review round

Axes: the prior state of `settings.local.json` (nothing; a memory install; a guards install; both;
a memory install from an older version whose groups differ; a user's own `PreToolUse` or
`PostToolUse` group, with and without a matcher equal to ours) × the selection (`memory`, `guards`,
`both`) × the mode (`--print-only`, a normal run, `--force`) × the harness (`claude-code`, `kiro`)
× the other flags (`--model`, `--no-trust-tools`, neither). Among the cells: `guards` over a memory
install leaves `enabledMcpjsonServers` and `permissions.allow` byte-identical, and `memory` over a
guards install leaves the guard groups byte-identical, and the shared start entry's flag is the
union of what it carried and what the selection adds. Every cell's expected outcome is written
into the test table before the code; any cell whose answer is not obvious from
`design/edit-guards.md` §5 is a design question, raised before the first review round, not after a
blocker.

### Done when

1. Items 1–7 are in, and every new test was **seen red** against the mutation it names.
2. **The decision function is replayed, before the guards are installed, over every `Bash`
   `tool_input.command` in this repository's existing session transcripts** —
   `~/.claude/projects/<project>/**/*.jsonl`, subagents included — under each call's recorded `cwd`
   and the machine's `$TMPDIR`. A note in `research/` reports the number of commands, how many a
   form matched, how many would have been denied, and every would-be deny verbatim with a reading
   of true or false. A false deny that recurs is a §3 change with its §8 row in this build; one
   seen once is a §7 entry. The count is the denominator `design/edit-guards.md` §7's count (a) is
   read against.
3. In one session in a throwaway project with the guards installed, outside every scratch root,
   whose prompt names a task with exact commands that include a denied form — as the live test does
   — while saying nothing about the hooks, the session's own records show a deny as a `tool_result` and a nudge as a transcript
   `attachment`, and whether a re-read of the edited path followed the nudge is reported
   (`design/edit-guards.md` §7's count (d), n=1, without a bar). The observation goes in
   `research/`.
4. `./check.sh` is green. The pull request's CI is the version matrix.

### Scope fence

**Not** kiro: no guard is offered there, and nothing probes kiro's `postToolUse` (operator decision
2026-10-06). **Not** installed in this repository (item 5). **Not** the asynchronous watcher class, nor any model on any path. **Not** an uninstall
or a removal of a selection that was not requested. **Not** a `doctor` row for the guards. **Not**
an override log or any store event: the transcript is the record. **Not** a rule beyond the two in
`design/edit-guards.md`; a third rule is a design change to that document first. **No change to
what a `memory` install writes**: the golden files under `.kiro/` and `test_install_targets.py`'s
artefacts for the default selection do not move. **Nothing in the service or the store**; the
hook client changes only to read `--components` on its start triggers, and with no flag does
exactly what it does today.

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
