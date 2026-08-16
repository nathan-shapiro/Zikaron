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

## M7 — Consolidation — **complete**

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
  fires once, so a subagent would otherwise inherit the memory tools having never seen D30's policy.
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

## M14 — The harness seam, both clients, and the gist character bound — **complete**

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
silently have no memory tools at all until the
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

**Scope fence:** no cross-harness comparison of any instrument, in either direction. **And the checkpoint
consolidation does not run against `~/Memory`.** That store's next consolidation is reserved for designing and
testing the positive merge criterion on a journal grown by real work (FINDINGS priority 1) — a one-shot
experiment, since the corpus cannot be regrown, and one this checkpoint would confound twice over by running
under a changed harness *and* a changed model. A future session executing this brief literally will reach for
the primary real-work store; that is the mistake this sentence exists to prevent.

---

## Standing notes for whoever picks this up

- **`shard_count` is flagged as possibly unnecessary** — a persisted count an invariant then polices, derivable
  as a `COUNT(*)`. Left in place pre-code deliberately. If M7 finds it genuinely redundant, that is a design
  change to propose, not to make silently.
- **Open questions in `FINDINGS.md` are open on purpose.** Open question 2 (RRF arm weighting) is the largest
  known quality lever and needs no reindex, so it is deliberately post-build. Do not tune fusion during M5.
- **The design is normative; where code and design disagree, one of them is a bug.** Decide which, fix that one,
  and re-index the knowledge base if it was the design.
