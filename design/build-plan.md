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
  `zikaron_remember` behind a prompt — the per-write friction the design calls worse than not asking.
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
the primary real-work store; that is the mistake this sentence exists to prevent.

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
thread at construction, every protocol member blocking on a `threading.Event`; `ServiceContext.
assemble` split so the **open** path used it and the **create** path stayed eager. It works in
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
for reasons that have nothing to do with identity — `encoder.py:151-155`'s two `BAD_CONFIG`
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
hand.** `zikaron/core/store/store.py:472-475` compares `config.get_str("embed_model")` and
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
§"The D34 table"; `design/consolidation.md` §"Candidate construction". Evidence:
`research/claude-code-mcp-result-truncation.md` for every harness measurement, and
`research/consolidation-payload-sizes.md` for how large a group actually gets in a real store —
including what the rejected trimming alternative would have cost.

**The defect, observed in production before it was understood.** A consolidation run against
`~/Trading/LeibaTrader` stalled: `zikaron_next_group` returned a group the harness refused to
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

## Standing notes for whoever picks this up

- **`shard_count` is flagged as possibly unnecessary** — a persisted count an invariant then polices, derivable
  as a `COUNT(*)`. Left in place pre-code deliberately. If M7 finds it genuinely redundant, that is a design
  change to propose, not to make silently.
- **Open questions in `FINDINGS.md` are open on purpose.** Open question 2 (RRF arm weighting) is the largest
  known quality lever and needs no reindex, so it is deliberately post-build. Do not tune fusion during M5.
- **The design is normative; where code and design disagree, one of them is a bug.** Decide which, fix that one,
  and re-index the knowledge base if it was the design.
