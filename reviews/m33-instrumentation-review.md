# M33 instrumentation — review trail

Artifact: the M33 design changes — `design/build-plan.md` §M33, `design/schema.md` (event DDL, per-kind
table, the two new subsections, invariants 10 and 18, §"Linked sessions", the D30 honest-limit paragraph,
§"Migration posture"), `FINDINGS.md` §"Current state" M33 paragraphs, `design/write-policy.md`'s two
gist-bound bullets, `FINDINGS-archive.md`'s closed Q18 entry.

## Round 1 — 2026-09-28

**Summary judgment.** The central decision — instrument the `_METHODS` seam rather than the verbs — is
right, argued from the defect that motivated it, and the schema text mostly carries its consequences
(invariants 10 and 18, linkage comparability, the migration rationale). Three things stop it shipping
as a design: the `call` write's placement relative to the response is unspecified, and on the code as it
stands the only reading puts up to a full `busy_timeout` on the push path under contention — the M17
class, reintroduced by the instrumentation that was meant to measure it; sentences that followed from the
changed claims are left standing in two normative documents the brief did not list (`architecture.md`
§Errors and §RPC surface, `knowledge-index.md` §6.1); and `call.error_code` is declared "fixed so none of
it is left to the code" while neither its stored form nor a validation site compatible with the layering
rule is stated. The rest is improvements, mostly of the enumeration-restated and tense classes this corpus
already names.

### Findings

1. **[BLOCKER] The `call` write blocks the response under contention, and the design says it does not.**
   `design/build-plan.md` §"The call event's shape" ¶"The price of that placement", and
   `design/schema.md` §"`call` is an access log" last paragraph: *"The event is best-effort for that
   reason; the alternative is blocking a response on a lock the caller has already been told to retry."*
   Nothing chooses the non-blocking alternative. As the code stands, `core/store/ddl.py:20` sets
   `PRAGMA busy_timeout = 5000` on the service's single connection, and `server._compute_response_line`
   returns its line only after everything before the `return` completes. A `call` INSERT issued there,
   on that connection, waits up to 5 s whenever the store is locked. Two consequences, neither stated:
   (a) a `STORE_BUSY` refusal — which already spent one `busy_timeout` — pays a second one before the
   client hears it; (b) a *successful* `memory_surface` under a concurrent writer pays the same wait before
   the hook receives its block, against `hook/push.py:40`'s `_DEADLINE_SECONDS = 2.0`, so the hook drops
   the injection — exactly M17's defect. The corpus already has the pattern to adopt:
   `design/knowledge-index.md` §12 *"Counter writes are best-effort and never block a search"* —
   `busy_timeout` set to zero for the write and restored after (`core/knowledge/counters.py:219–227`).
   **Change:** in `schema.md` §"`call` is an access log", replace *"The event is best-effort for that
   reason"* with a mechanical statement — *"The row is written with the connection's `busy_timeout` set
   to zero for the statement and restored afterwards, as `knowledge-index.md` §12 does for a counter, so a
   locked store costs the row and never the response"* — and state its ordering: before the response line
   is returned (cheap, but then the zero-wait is load-bearing) or after `writer.drain()` inside the
   `ActivityTracker` bracket so idle self-stop cannot fire between response and row. Name the primitive
   too — `transactions.in_one_transaction` with a failure map that swallows contention and propagates
   nothing else — rather than a bare autocommit INSERT on a connection other handlers share. Add to
   done-when: *"a `memory_surface` against a store held by a second connection's open write transaction
   answers inside `push._DEADLINE_SECONDS`, asserted by a test"*, and make the A/B's *load* a concurrent
   writer on `memory.db`, since on an idle store the added cost is one INSERT and the question is moot.

2. **[BLOCKER] Sentences that followed from the changed claims are left stale in normative documents
   outside the brief's list.** Intent 4 is the brief's own test, and a checker reading only the five named
   files cannot find these.
   - `design/architecture.md:1844–1846` §"What a rejected call does and does not change": *"It may commit
     audit events. `version_conflict` and `no_receipt` … No other error writes an event."* Invariant 10
     (`schema.md:1288–1291`) points here as the enumeration; after M33 every refusal that reached dispatch
     — `bounds` included — writes a `call` row. Replace the last sentence with: *"No other error writes a
     **semantic** event; every refusal that reached dispatch is recorded by the access log's `call` row,
     in its own transaction after the handler, best-effort (`schema.md` §"`call` is an access log")."*
   - `design/architecture.md:2092–2096` §"Service RPC surface": *"the `knowledge_*` methods included,
     though none of them writes an event against the label it is given … nothing about a search or a
     corpus's lifecycle is attributed to a session"*, and `:2090` *"touch no other table"*. False on both
     halves after M33: every `knowledge_*` call writes a `call` row under its label, and a build writes
     `knowledge_build` under a minted one. Replace with: *"the `knowledge_*` methods included. None emits
     a semantic event — the index's counters live in each corpus's `meta` — but each is recorded by the
     access log's `call` row under the label it was given, and a build by `knowledge_build` under a label
     the indexer mints (`schema.md` §"What is instrumented, what is not, and why")."*
   - `design/knowledge-index.md:1017–1018` §6.1 *"combined with K1, means indexing never touches
     `memory.db` at all"* and `:1339` *"K1 keeps it off `memory.db` entirely"*. Already inaccurate (the
     registry lives in `memory.db` per §3.1a and `knowledge/scope.py` opens it); M33 makes the indexer
     *write* `memory.db`'s `event` table. Rewrite as: *"K1 keeps a build's writes off `memory.db` — one
     `knowledge_build` row at the end of a build is the exception, and it is best-effort."*
   - Add all three to the done-when's list of corrected prose, beside the DDL comments and invariant 18.

3. **[BLOCKER] `call.detail.error_code` has no stated representation, and the stated validation site
   conflicts with the layering rule.** `schema.md:684` and build-plan §"The call event's shape" say
   `EVENT_SPECS` validates it against `ErrorCode` **and** `rpc.ProtocolErrorCode`; the done-when repeats
   it. (a) `EVENT_SPECS` is `core/events.py`; `ProtocolErrorCode` is `service/rpc.py:25`.
   `coding-standards.md` §1 gives `core/` *"no transport, no process concerns"*, and nothing in `core/`
   imports `service/` today. Validating there needs that import or a second copy of the enum — the
   restated-enumeration defect. (b) Whether the row stores the int wire code (`-32005`) or the snake_case
   name (`bounds`) is unstated; `ErrorCode` has `wire_name`, `ProtocolErrorCode` does not; and the
   done-when's *"refusal rate of a bounded write … answerable by query"* cannot be written without knowing
   which. **Change:** state the stored form in the `schema.md` row (the name, with `ProtocolErrorCode`
   given the same `wire_name` property — or the int, since the two ranges are disjoint), and choose one
   of: move `ProtocolErrorCode` into `core/errors.py` beside `ErrorCode` (it is wire contract, which that
   module already owns for the application range), or validate at the seam in `service/` and have
   `EVENT_SPECS` declare `error_code` a free string. Say which in build-plan and schema.

4. **[IMPROVEMENT] The `tools:` scan predicate is ambiguous in exactly the direction the brief says costs
   most.** build-plan §"A production defect": *"whose frontmatter sets `tools:` without `mcp__zikaron`"*.
   The consolidator's server is `mcp__zikaron-consolidator` (`install/entries.py:42`), which begins with
   `mcp__zikaron`; a prefix or substring test marks an agent that lists only consolidator tools as fine —
   the false-silent case. State the predicate: an entry equal to `mcp__{MCP_SERVER_NAME}` or beginning
   `mcp__{MCP_SERVER_NAME}__` (`entries.py:244`'s form), derived from the constants the installer writes,
   never a literal. Name the fixtures that prove both directions: `income-quant.md`'s frontmatter (named),
   one listing only `mcp__zikaron-consolidator__…` (named), one listing `mcp__zikaron` (not named), and
   the inline comma-separated form of each. Separately: that Claude Code accepts the bare server form
   `mcp__zikaron` inside a subagent's `tools:` field — as distinct from `permissions.allow` — is asserted
   nowhere; the post-install line will advise it, so measure it once and cite `research/`.

5. **[IMPROVEMENT] The intro paragraph to §"The `event` log, per kind" asserts the universal the section
   then breaks.** `schema.md:659–665`: *"one RPC call emits one `op_id`'s worth of events, inside the same
   transaction as the mutation it describes (invariant 10) … Every event also carries `client_kind`
   straight from the request envelope."* False for `call` (own transaction) and `knowledge_build` (no RPC,
   no envelope). Rewrite: *"Every **semantic** event … inside the same transaction (invariant 10); the
   access log's `call` row commits after it, and a build's `knowledge_build` has no RPC at all — §"`call`
   is an access log" and §"What is instrumented". `client_kind` comes from the envelope for every kind but
   `knowledge_build`, whose writer mints its own label."*

6. **[IMPROVEMENT] The nullability table omits both new kinds while claiming to be the one place.**
   `schema.md:746–764`: *"exactly the nulls this document already states, gathered so they can be read and
   checked in one place"* — and row 684 states `call.error_code` is NULL when `ok`. Add: `call` |
   `error_code` | null iff `ok`; `knowledge_build` | `error_code`, `files_indexed` | `error_code` null iff
   `ok`, and decide `files_indexed` on a build that never reached a scan (null, or 0 — say which).

7. **[IMPROVEMENT] `knowledge_build.detail` is under-specified against the standard `call` is held to.**
   (a) `knowledge_base` — name or `id`? `knowledge_rename` exists (`core/knowledge/registry.py:173`) and
   the row's stated purpose is *"what building it has cost over time"*; keyed by name that history breaks
   at a rename. Carry `id` (`schema.md:347`: stable, names the file), and the name at the time if wanted.
   (b) `error_code`'s domain: a build's failures are `KnowledgeError` subclasses
   (`core/knowledge/errors.py:33–160`), which carry no wire code, plus `ZikaronError`s. State what is
   stored for each, as a closed set, or the kind cannot be validated. (c) build-plan:3899–3900 and
   `schema.md:1438` say a minted `op_id` *"makes a build's events correlatable to each other"* — plural —
   while the table says one row per build. If one, drop the plural; if more are intended, list them.

8. **[IMPROVEMENT] Tense: documents claim as done what the code does not do.** `FINDINGS.md:75` says the
   code is not started. `design/write-policy.md:538–540`: *"M33's `call` event records … so the rate is
   **now** a query rather than an observation"*; `:544–545` *"a refusal **is** a `call` event"*;
   `FINDINGS-archive.md:4944` *"The turned-away write **is now** a `call` event"*. Intent 4's own test. The
   closure and move are intentional and not re-flagged; the tense is. Either write *"at M33 … becomes a
   query"* / *"closes at M33 with"*, or land these sentences with the M33 commit rather than ahead of it.

9. **[IMPROVEMENT] The done-when overclaims what a call-driving test proves.** build-plan §"The classes of
   call the log does not cover": *"so that no further exclusion can appear without a red test"*. Driving
   every `_METHODS` entry proves each reaches the log **on the inputs driven**; an exit added ahead of
   dispatch that fires on other inputs (a size limit, a rate limit) is invisible to it. State what the
   test asserts: for every method in `_METHODS`, one well-formed call and one refused call each produce
   exactly one `call` row; `health`, a malformed envelope and an unknown method produce none; the
   exclusion list is complete *as of that test*, not by construction.

10. **[IMPROVEMENT] Counts restated away from what determines them, in the live file.** `FINDINGS.md:79–81`
    *"covers all 19 … 8 of the 19"*; build-plan:3815–3821 the per-table count table. `len(_METHODS)` and
    `len(KNOWLEDGE_METHODS)` determine both, and the rubric names this class. In `FINDINGS.md` write
    *"every method in `_METHODS`; every `KNOWLEDGE_METHODS` entry emits nothing today"*; a brief may carry
    a dated count once as its record of scope, but not FINDINGS a second time. Also build-plan:3986
    *"`log_event` requires a `CallParams` carrying all three"* — it carries four (`max_depth`,
    `core/records/memory.py:60–63`), which the seam has no value for; say *"among its fields"* and decide
    whether the seam passes the config's value or gets a narrower type.

11. **[IMPROVEMENT] §Retention's growth figure predates `call`, and the brief points at the wrong
    section.** `schema.md:994–998` prices ~1,000 events/day from `surface_call` rows; a five-gist push is
    now seven rows not six, a search two not one, a fetch of *n* uuids *n*+1. build-plan:3843 says
    *"`schema.md` §Bounds is where a row-growth figure would go"* — it already lives in §Retention. Point
    there, and add to done-when: re-derive the per-day figure with `call` included, on the migrated
    LeibaTrader snapshot the migration test already uses.

12. **[IMPROVEMENT] The uuid-citation paragraph misquotes and misattributes.** build-plan:4039–4041
    attributes *"point at another record by its subject, not by quoting its headline"* to
    `design/write-policy.md`; that string appears nowhere in the corpus. The agent-facing sentence is
    `zikaron/mcp/primary.py:406` (*"Point at another record by its subject … never …"*), and the archive's
    Q15 says "gist". And `write-policy.md` §"Why a record points at another by subject rather than by
    gist — **or by uuid**" (452–469) already rejects uuid citation, on different grounds — opaque to a
    human, a hallucinated uuid is undetectable, and *"a retired record [is] still resolvable"*. So *"Nothing
    tells the agent that"* is true only of the agent-facing text, and *"whose stated reason is that a gist
    is rewritten"* misdescribes the policy. Quote `primary.py` verbatim, cite §452 as the existing
    rationale, and state M33's addition as (a) the agent-facing sentence and (b) extending §452's rule to
    documents — reconciling *"still resolvable"* with Q20's husks: a uuid that ever existed always resolves
    (D16) to the *row*, not the claim; one that resolves to nothing never existed, which is §452's
    hallucination point, now measured. Worth knowing that the verbatim-quote guard did not reach this
    attribution form.

13. **[NITPICK]** Invariant 10, `schema.md:1296–1297`: *"both kinds are counted **per call**"* —
    `knowledge_build` is per build. *"per call or per build"*.

14. **[NITPICK]** DDL comment `schema.md:142–143`: *"2 admitted 'cli', 3 'indexer'"* — version 3 is also
    the two-kind widening on `kind` below; *"3 'indexer' here and two kinds below"*.

15. **[NITPICK]** §"Linked sessions" bullet, `schema.md:871–876`: add that a `label_source` population
    count must exclude `client_kind='indexer'` — every build is `minted` by construction and would read as
    a client that fell to minting.

16. **[NITPICK]** Done-when *"the DDL comments that assumed every event is a client call corrected"* —
    `core/events.py:53` (`ClientKind`'s docstring, *"every v0 event is emitted inside a client call"*) is
    not a DDL comment and says the same thing; name it. `dispatch_knowledge.py:350`'s `# noqa` reason
    *"this method records no event"* stays literally true of the handler and will read as a contradiction;
    *"records no semantic event"*.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-28

**Summary judgment.** Round 1's three blockers are resolved as described, and the private-connection
decision is the right call with its cost stated. Two new things stop it shipping, both in mechanism the
text now specifies rather than in intent: the `tools:` scan as written names the installer's **own**
consolidator agent on every install — `targets.py:363` writes `.claude/agents/zikaron-consolidator.md`
with `tools: [mcp__zikaron-consolidator, Read]`, which is exactly the fixture the brief says must be
named — and the access-log write's failure map "propagates everything else", which at this seam turns a
committed mutation into an `internal_error` response, the correctness failure the same paragraph says it
will not commit. The rest is precision on closed sets and one measurability gain the design already has
the data for. Verified against `server.py`, `rpc.py`, `transactions.py`, `counters.py`, `migration.py`,
`entries.py`, `targets.py`, `test_ddl.py` and `research/claude-code-installer-probe.md` §7.

### Findings

1. **[BLOCKER] The scan names the installer's own consolidator agent, on every Claude Code install.**
   `design/build-plan.md:3866–3879`: scan `.claude/agents/*.md`, name each agent whose `tools:` lacks
   `mcp__{MCP_SERVER_NAME}` exactly or as a `__` prefix, and — fixture two — *"one agent listing only
   `mcp__zikaron-consolidator__…` (named)"*. `install/targets.py:363` writes
   `project/.claude/agents/{CONSOLIDATOR_AGENT_NAME}.md`, and `entries.py:331–333` gives it
   `tools: [mcp__zikaron-consolidator, Read]`. That file satisfies the predicate, so the post-install line
   names Zikaron's own artefact as unable to see Zikaron — the *"naming an agent that is fine"* direction
   `:3897–3898` calls one of the two that cost most — and D32 makes that agent's narrow grant deliberate.
   **Change:** at `:3872–3879`, add *"The scan skips the one agent the installer writes itself,
   `{CONSOLIDATOR_AGENT_NAME}.md`, matched on the filename derived from that constant; every other agent
   holding only the consolidator's grant is a user file holding a grant that belongs to the consolidator
   alone, and is named."* Add the fixture: the installer's own `consolidator_agent_markdown(...)` output,
   **not named** — rendered through that function rather than hand-typed, per `CLAUDE.md` §Harness. State
   the order too: the scan runs after the installer's own writes, so a first install and a re-install
   report the same set.

2. **[BLOCKER] "Propagates everything else" at the seam reports a committed mutation as failed.**
   `design/schema.md:841–844` and `build-plan.md:4012–4013`: the row goes through `in_one_transaction`
   *"with a failure map that swallows contention and propagates everything else"*. Two problems.
   (a) A `FailureMap` cannot swallow — `transactions.py:36–38` types it as *driver error → wire error or
   `None`-to-re-raise* — so the swallow is the caller's `except` around the call, as `counters.py:221–225`
   does; fine, but say so. (b) What "propagates" reaches: the write sits in `_compute_response_line`
   (`server.py:132–159`) after `result = await handler(...)` has **committed**. A non-contention failure
   there — disk full on the WAL append, or the private connection having been **closed by `finalize`**
   (`transactions.py:127–148` closes a connection whose rollback fails; the next statement on it raises
   `ValueError`, not `aiosqlite.Error`, per `dispatch_knowledge.py:517–518`) — lands in `except Exception`
   and answers `internal_error` for a `memory_remember` that is durably in the store. The agent retries and
   writes a duplicate. That is the *"corrupting a caller's answer"* the same paragraph at `:848–849`
   declares off the table, and once the private connection is closed it happens on **every** subsequent
   call. **Change:** replace the failure-map sentence with: *"Nothing raised by the access-log write reaches
   the response. The response line is encoded **before** the row is attempted and returned unchanged
   whatever the write does; contention is dropped silently, and any other exception is logged once to the
   service log and dropped. A private connection that `finalize` has closed is reopened on the next call, or
   the log stops and the service log says so once — choose one and state it."* Encoding first is what makes
   the property hold by construction rather than by a guard. Add to done-when: *"a `call` write that raises
   a non-contention error (closed private connection; a raised `OSError`) leaves the response line
   byte-identical to the one an unlogged call would return."* While here, state the ordering the text now
   only implies — row before the response line, not after `writer.drain()` — and its idle cost, which round
   1 called moot and was wrong to: the store sets no `synchronous` pragma (`ddl.py:18–21`), so under the
   default a WAL commit syncs the file, and every dispatched RPC now pays a second commit on its response
   path (the semantic events share the handler's). Have the A/B report the idle-store delta as well as the
   concurrent-writer one; the first is what every push pays.

3. **[IMPROVEMENT] The bare-server `tools:` form is already measured, and the brief says it is not.**
   `build-plan.md:3881–3884`: *"that Claude Code accepts the bare server form `mcp__zikaron` inside a
   subagent's `tools:` field … Nothing in this corpus measures it. Measure it once and cite `research/`."*
   `research/claude-code-installer-probe.md` §7 (line 111) — *"A whole-server wildcard in subagent
   frontmatter works, and excludes other servers"* — measured `tools:\n  - mcp__zikaron-consolidator`
   granting that server's tools; `entries.py:297–302` cites it as the reason the installer writes that
   form; `research/m30-docker-end-to-end.md:163–169` exercised it under a real subagent. Same feature,
   different server name. **Change:** replace the paragraph with the citation and the residual — measured
   for one server name, the mechanism is not per-server — and drop the owed measurement from the brief. The
   advice line can then say *"add `mcp__zikaron`, the form the installer's own agent uses"*.

4. **[IMPROVEMENT] The pre-dispatch exit list omits the parse exits, and `call.error_code`'s protocol
   half is one member, not five.** `schema.md:817–827` and `build-plan.md:4021–4035` list `health`, a
   malformed envelope, an unknown method. `rpc.parse_request` (`rpc.py:97–128`) raises `PARSE_ERROR`,
   `INVALID_REQUEST` and `INVALID_PARAMS` in `_handle_line` (`server.py:163–170`) before `_dispatch_request`
   runs — a fourth exit, mechanically unloggable (no `RpcRequest`), which the done-when's test at
   `:4119–4120` does not drive. Consequently, of `ProtocolErrorCode`'s five members exactly one —
   `internal_error` — can ever appear in a `call` row; `schema.md:689` and `build-plan.md:3979–3982`
   say the field *"spans both error enums"*, and a signal query written to expect `invalid_params` there
   waits forever. **Change:** add the table row *"an unparseable line — `parse_request`'s three codes: no
   `RpcRequest` exists, so nothing to attribute"*, add it to the test's inputs, and narrow both domain
   statements to *"`ErrorCode.wire_name`, or `internal_error` — the one `ProtocolErrorCode` a dispatched
   call can produce, the other four being decided before dispatch"*. The converter's type can stay the
   union; the stored domain should be stated as what is reachable.

5. **[IMPROVEMENT] `knowledge_build.error_code`'s "closed set" has four open edges.**
   `schema.md:690`, `build-plan.md:3928–3929`: *"a `ZikaronError`'s `wire_name` or a `KnowledgeError`'s,
   the latter a closed set … a test holds unique."* (a) Unique among `KnowledgeError`s says nothing about
   collision with `ErrorCode.wire_name`; state the union is disjoint and test that. (b) The same condition
   gets two names across the two kinds: `DanglingKnowledgeBaseError` refused at `knowledge_refresh` is
   `knowledge_base_dangling` in `call` via `dispatch_knowledge._translated` (`:162–196`), and would be
   whatever its new `wire_name` is in `knowledge_build`. Either route the build's name through the same
   map where one exists and invent names only for the build-only classes (`CorpusRootMissingError`,
   `RegistryUnavailableError`, …), or declare the vocabularies separate and say a query must not join them.
   (c) A build that dies on a driver error, an `OSError`, or an unexpected exception — *"one per indexer
   build, whatever its outcome"* promises a row — has no value in either set, and `internal_error` lives in
   `service/rpc.py`, which the indexer must not import. Name a member for it in `core/knowledge/errors.py`.
   (d) `IndexerBusyError` at the lock: is a refused spawn "a build" with a row, or not a build? Say which.

6. **[IMPROVEMENT] The private connection's opener, pragmas and lifetime are left to the code.**
   `schema.md:845–849`, `build-plan.md:4014`: *"on a connection of its own"*, and *"the shape
   `core/knowledge/counters.py` already uses"* — but `counters.py:219–227` toggles `busy_timeout` on a
   **shared** connection, which is precisely what the next sentence rejects; what is borrowed is the
   `is_contention` swallow, not the shape. **Change:** state that the connection is opened through
   `connection.open_connection` (never bare `sqlite3` — `connection.py:123–126`), with a pragma list that
   sets `busy_timeout = 0` **at open** so there is no toggle and no window; opened in `ServiceContext`
   **after** `Store.open(migrate=True)` so it never meets the old `CHECK`; closed with the store; and that it
   loads no extension it does not need, or say the shared loader is used and the cost accepted.

7. **[IMPROVEMENT] Decide the indexer's write by version, not by catching the constraint.**
   `schema.md:1588–1593`: *"a `CHECK` violation and contention alike cost the row"* implies catching
   `IntegrityError`, a net wide enough to hide a NOT NULL defect. The indexer opens through `Store.open`
   (`knowledge/scope.py:95`) and holds `store.meta.schema_version`. **Change:** *"the row is written only
   when the store opened at a version whose `CHECK` admits it (≥ 3), decided from `meta` the opener already
   read; below that no write is attempted"*. The failure map then stays contention-only, as
   `counters.py`'s is, and the test drives a version-2 store without provoking a constraint.

8. **[IMPROVEMENT] State that `call` carries the envelope's `op_id`, because it makes the undercount
   measurable.** `schema.md:829–832, 855–857`: *"a divergence the store cannot rule out"*, *"a permanent
   limit"*. The DDL comment at `:150` gives every event of one RPC one `op_id`, so a `remember`/`amend`/…
   row whose `op_id` has no `call` row **is** a dropped access-log row, and the drop rate over the
   mutation population is one query. **Change:** say `call` shares its call's `op_id` explicitly in the
   `:689` row; add the query beside the per-method volume one in done-when; and make the contention test at
   `:4141–4143` assert both halves — response inside `push._DEADLINE_SECONDS` **and** the row absent — so
   it proves the drop rather than only the latency.

9. **[IMPROVEMENT] `knowledge_build` has no edge to the call that spawned it.** `schema.md:690` mints a
   fresh `session_id`/`op_id`; the `knowledge_refresh` `call` row carries the requester's `client_kind`
   (agent vs operator CLI) and a `duration_ms` covering only the spawn. Nothing joins them, so *"what did
   this agent's refresh cost"* is unanswerable while both rows exist. The spawning handler holds
   `envelope` — the argument `dispatch_knowledge.py:350` etc. mark `# noqa: ARG001` as unused — and
   `_spawn` (`:329`) builds the argv. **Change:** add `spawned_by_op_id: str | null` to the detail (null
   for a direct argv run), passed on the command line; add it to the nullability table at `:768`.

10. **[IMPROVEMENT] The done-when still carries round 1's wording on `error_code`.**
    `build-plan.md:4125–4126`: *"in `EVENT_SPECS`, its `error_code` accepting both `ErrorCode` and
    `rpc.ProtocolErrorCode`"* — contradicts `:3988–3993`, which now has `EVENT_SPECS` declare a nullable
    string and the seam's converter carry the union. A builder reads the done-when. Write *"declared a
    nullable string in `EVENT_SPECS`, its domain enforced by the seam's converter typed
    `ErrorCode | ProtocolErrorCode -> str`"*.

11. **[NITPICK]** `schema.md:689` cardinality *"exactly one per dispatched RPC"* and `:690` *"one per
    indexer build, whatever its outcome"* — both are **at most** one under the best-effort rule the same
    document states; the cardinality column is what a query author reads.

12. **[NITPICK]** `duration_ms` — integer or float, and which clock (`time.monotonic()`/`perf_counter`)?
    A `knowledge_list` handler is sub-millisecond; an integer field reads 0 for it.

13. **[NITPICK]** Invariant 10, `schema.md:1340`: *"A build describes no store mutation"* — it mutates its
    corpus database; *"no `memory.db` mutation"*.

14. **[NITPICK]** Claude Code subagent frontmatter also takes `disallowedTools:`; an agent with no `tools:`
    and `disallowedTools: mcp__zikaron` is equally blind and unnamed. Worth a sentence saying it is out of
    scope, so the next diagnosis does not re-derive it.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-28

**Summary judgment.** Both round-2 blockers are resolved as the brief describes, and the encode-before-write
property is the right mechanism — it holds by construction and the byte-identical assertion pins it. One
thing still stops this shipping, and it is in the one test that guards the M17 class: the contention test in
the done-when specifies a condition under which `memory_surface`'s **own** handler already waits the full
`busy_timeout` and answers `store_busy`, so the assertion "answers inside `push._DEADLINE_SECONDS`" is red
before a line of M33 exists and cannot distinguish the access log's cost from the pre-existing one. The rest
is consistency on the indexer's error vocabulary (the text forbids and requires the same import), one wrong
claim about where a refused spawn is recorded, a cheap pragma the design prices but does not consider, and
the fact that the tree is red now while `FINDINGS.md` says the brief is the only uncommitted thing. Verified
against `server.py`, `transactions.py`, `connection.py`, `reads.py`, `counters.py`, `builds.py`,
`dispatch_knowledge.py`, `knowledge/scope.py`, `knowledge/indexer/{main,detach}.py`, `core/errors.py`,
`core/knowledge/errors.py`, `tests/test_ddl.py`, `tests/test_event_kinds.py`, `tests/test_knowledge_counters.py`
and `design/harness.md` §"The installer's two targets".

### Findings

1. **[BLOCKER] The contention test cannot pass as specified, because the handler under test already pays
   the wait the test is meant to exclude.** `build-plan.md:4188–4190`: *"a `memory_surface` issued while a
   second connection holds an open write transaction on `memory.db` answers inside `push._DEADLINE_SECONDS`
   and leaves no `call` row"*. `reads.surface` (`core/retrieval/reads.py:248–295`) runs inside
   `in_one_transaction` on the **shared** connection and emits `surface_call` by `log_event` — an INSERT,
   which under WAL needs the write lock. With a second connection holding it, that INSERT sits in SQLite's
   busy handler for `ddl.BUSY_TIMEOUT_MS` = 5000 ms and the handler answers `store_busy`; the response
   cannot be inside 2.0 s whatever the access log does. `tests/test_knowledge_counters.py:187–206` is the
   same fixture on the counters and shows the shape. So the test as written is red on day one of M33, and
   a builder meeting it will weaken the assertion or change the condition without the design saying which.
   Two consequences follow. (a) `build-plan.md:4038–4040` and `schema.md:844–845` — *"paid on a
   **successful** `memory_surface`"* — overstate where the added wait lives: a surface that succeeded held
   the lock for its own INSERT, so the access-log write contends only if a writer takes the lock in the
   window between the handler's commit and the row attempt, or against the service's own other in-flight
   handlers. That window is real and is the case that matters; say it rather than "whenever the store is
   locked". (b) The A/B arm *"under a concurrent writer"* (`:4193–4194`) measures nothing if the writer
   *holds* a transaction — both arms answer `store_busy` after 5 s — so the writer must interleave short
   write transactions at a stated rate. **Change:** replace the done-when sentence with three tests, each
   isolating one claim: *the access-log writer alone, attempted while a second connection holds the write
   lock, returns within a stated bound (`test_knowledge_counters.py:206`'s form, `< BUSY_TIMEOUT_MS / 5000` s)
   and writes no row*; *a dispatched call whose handler has committed, with the lock taken by a second
   connection between that commit and the row attempt — through a test seam on the writer, or a stubbed
   handler that acquires it on return — answers with the byte-identical unlogged line inside the same
   bound*; and *the A/B under an interleaving writer at N short transactions per second, both arms, both
   measured, with N stated*. Reword (a) in both documents.

2. **[IMPROVEMENT] The indexer's error vocabulary both forbids and requires importing `service/`.**
   `schema.md:892–903` and `build-plan.md:3947–3951`: the build *"reuses that map"* —
   `dispatch_knowledge._translated` (`:162–197`), a private function in `service/` that constructs
   `ZikaronError`s with payloads (`name`, `taken`, `holder`) a build does not hold — and, two lines later,
   *"`internal_error` lives in `service/rpc.py`, which the indexer must not import."* No rule backs the
   second: `zikaron/knowledge/scope.py:33` already imports `zikaron.service.paths`, and `coding-standards.md`
   §1 puts `zikaron/knowledge/` beside `service/`, not under `core/`. If the indexer may import `service/`,
   the third edge dissolves and no new member is needed; if it may not, it cannot reuse the map either.
   **Change:** state the rule once — *the indexer takes nothing from `service/` beyond `paths`* — and put
   the `KnowledgeError` type → `ErrorCode` table in `core/knowledge/errors.py`, beside the classes it names
   (`ErrorCode` is importable there today), with `_translated` reading its code from that table and adding
   the payload. The build-only members and the unexpected-exception member are declared in the same table,
   so "one condition, one name" is a property of one table rather than of two call sites agreeing.

3. **[IMPROVEMENT] "Recorded on the refusing `call` row instead" is false for the two verbs that spawn.**
   `schema.md:904–905`. `builds._stopped_by` (`core/knowledge/builds.py:127–132`) returns `IndexerBusyError`
   as a `PlannedBuild.refusal` with obstacle `ALREADY_INDEXING`, and `knowledge_refresh`
   (`dispatch_knowledge.py:382–405`) reports it as a per-corpus **outcome inside a succeeding result** —
   its docstring: *"one unbuildable knowledge base never denies the others a build"*. `knowledge_add` goes
   through the same `_spawn`. So that `call` row reads `ok=true, error_code=null`, and the refused spawn
   appears in no event at all; only `remove` raises it through `_translated` as `knowledge_base_busy`.
   **Change:** *"For `refresh` and `add` the refusal is a per-corpus outcome in a succeeding call and is
   recorded in no event; for `remove` it is the call's own `knowledge_base_busy`."* Whether that gap is
   accepted is a decision to write down, since a corpus that is *always* busy is a real diagnosis.

4. **[IMPROVEMENT] The build should wait for its row, not decline to.** `schema.md:1640–1642`:
   *"Contention still costs the row and never the build … it need only decline to wait."* A build has no
   latency budget — it has just spent minutes — and the row is the only record of that cost, which is the
   question the kind exists for. Declining drops it whenever the service is mid-write, and every push
   writes events, so an active session drops it often for no benefit. **Change:** the build's row goes
   through its connection's ordinary `busy_timeout` and swallows contention only after it — dropped only
   under five continuous seconds of contention — stated here and at `build-plan.md:3952–3954`. Write it as
   a fresh `in_one_transaction` with no read left open on that connection, or a stale snapshot turns the
   attempt into an immediate `SQLITE_BUSY_SNAPSHOT`, which `is_contention` swallows without a trace.

5. **[IMPROVEMENT] The idle-store cost the design prices has a one-pragma answer it does not consider.**
   `schema.md:875–878`, `build-plan.md:4054–4057`: every dispatched RPC pays *"a second synced commit on
   its response path"*, to be measured. `PRAGMA synchronous` is per-connection; under WAL, `NORMAL` syncs
   the WAL at checkpoint only, so a commit on the private connection is a WAL append with no `fsync`. What
   that gives up — the last few access-log rows after a power loss — is already inside "best-effort", and
   the store's own connection keeps `FULL`. An `fsync` under load is the class M30 measured at 2× its idle
   figure. **Change:** add `PRAGMA synchronous = NORMAL` to the private connection's pragma list, state the
   trade in the same bullet, and have the A/B report the idle delta with it in place — or say why `FULL`
   is kept for a row the design already calls droppable.

6. **[IMPROVEMENT] The scan runs once, at install, and the ordinary case from here is an agent authored
   after it.** `build-plan.md:3900`: *"detection only … at install time"*. `income-quant.md` pre-dated the
   install; the next blind agent will be written a week later, and nothing checks then. `zikaron doctor`
   is the surface that already reports install health (`distribution.md` §"The front door"). **Change:**
   run the same scan from `doctor` on the Claude Code target — same function, same line — or say in the
   scope note why an agent added after install is out of scope. One sentence either way.

7. **[IMPROVEMENT] The install behaviour lands with no sentence in the document that is normative for
   the installer.** `build-plan.md:3856–3859` says `harness.md` §"The installer's two targets" *"says
   nothing about this case; it was never modelled"* — and then leaves it unmodelled: the done-when names
   `architecture.md` and `knowledge-index.md` and not `harness.md`. `FINDINGS.md`: *"`design/harness.md`
   is normative for every harness-coupled fact. Read it before touching … the installer."* **Change:**
   add a bullet under `harness.md:567` §"What the install reports rather than enforces" — the scan, the
   exact predicate, the consolidator skip, the `disallowedTools:` exclusion, and that kiro has no analogue
   because its entries go *into* the agent config — and name it in the done-when beside the other three
   corrected documents.

8. **[IMPROVEMENT] The tree is red now, and `FINDINGS.md` says the brief is the only uncommitted thing.**
   `FINDINGS.md` §"Current state": *"that brief is the only uncommitted thing in the tree"*. `git status`
   shows eight modified files, and two drift guards read the DDL block this milestone edited:
   `tests/test_ddl.py:47–57` compares `ddl.FIXED_STATEMENTS` against `schema.md` §Tables verbatim, and
   `tests/test_event_kinds.py:433–445` compares `ClientKind` against the block's `client_kind` `CHECK`.
   Both are red until `ddl.py` and `ClientKind` move — that is, until M33's code lands — which is
   §"Migration posture"'s own alarm firing as designed. Two consequences a fresh session needs: the design
   cannot land as a prose-only PR, and `./check.sh` run first, as `CLAUDE.md` says to, meets two red guards
   with nothing saying they are expected. **Change:** *"The M33 design — the brief, `schema.md`'s DDL
   block and per-kind table, and the sentences in `architecture.md`, `knowledge-index.md`,
   `write-policy.md` and the archive that followed — is uncommitted and lands with the M33 code:
   `test_ddl.py` and `test_event_kinds.py` read the DDL block and are red on this tree until `ddl.py` and
   `ClientKind` catch up, by design."*

9. **[IMPROVEMENT] The drop-rate query has no lower bound, and the store records none.** `schema.md:689`,
   `build-plan.md:4192–4193`: *"a semantic row whose `op_id` carries no `call` row is a dropped row"*.
   Every pre-schema-3 row qualifies — 26,300 on `~/Trading/LeibaTrader` — and every `knowledge_build` row
   qualifies by construction (minted `op_id`, no RPC). Nothing in `meta` records *when* the version moved.
   The same bound is owed by the §Retention re-derivation. **Change:** the query excludes
   `client_kind='indexer'` and bounds at `event.id > (SELECT min(id) FROM event WHERE kind='call')` — a
   floor, since the first post-migration rows may themselves have dropped — or the migration step writes
   `meta.schema_migrated_at` in the same transaction that writes `schema_version`. Say which.

10. **[NITPICK]** `spawned_by_op_id` rides the argv, and `knowledge-index.md:1601–1605` makes that argv the
    `foreground_command` a person re-runs — *"never a second construction of it"*. A re-run then attributes
    a direct build to the verb's `op_id`, against `schema.md:690`'s *"null for a build run directly"*.
    Either the printed command omits the flag, with §8.4 given that one stated exception, or the row's rule
    reads *"null unless the argv carried one"* and names the re-run case.

11. **[NITPICK]** `FINDINGS.md` §"Current state" still carries *"covers all 19"* and *"8 of the 19"* — round 1
    finding 10, not re-raised in round 2, still present in the file that loads every session. *"every method
    in `_METHODS`; every `KNOWLEDGE_METHODS` entry emits nothing today"*.

12. **[NITPICK]** `schema.md:852–853` *"any other exception is logged once to the service log and dropped"*
    — once per failure or once ever? A full disk fails every call: one line per call floods, one line ever
    hides the recovery. *"once per failure"*, or *"once, until the next row succeeds"*.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-28

**Summary judgment.** Round 3's blocker is resolved correctly: the three-test split isolates the access
log's cost from the handler's own, and the encode-before-write, private-connection, `synchronous = NORMAL`
mechanism is sound and buildable as written. No blocker remains. What stops an APPROVED is three factual
errors in normative text, each in the direction that misleads a reader of the log or a builder of the
tests: the "held lock fails the handler first" claim is false for the five knowledge handlers that write
nothing to `memory.db` — which also makes the done-when's test seam unnecessary; `IndexerBusyError` is
raised as `knowledge_base_busy` by `unlock` as well as `remove`; and `zikaron doctor` gains a check while
`distribution.md`'s closed enumeration of its checks — the one `doctor/checks.py`'s own docstring binds
to — is untouched, the class round 3 finding 7 raised for `harness.md`. Verified against `server.py`,
`registry.py`, `lock.py`, `lifecycle.py`, `dispatch_knowledge.py`, `knowledge/client.py`,
`doctor/{main,checks}.py`, `core/knowledge/errors.py`, `distribution.md` §"The front door" and
`research/claude-project-dir-reaches-hooks-not-shells.md`.

### Findings

1. **[IMPROVEMENT] "A store held continuously by another writer fails the handler itself" is false for
   every handler that writes nothing to `memory.db`, and the truth removes the test seam.**
   `build-plan.md:4051–4057` and `schema.md:846–853` state it as universal, and `build-plan.md:4212–4214`
   draws the conclusion: *"A test that merely holds the lock throughout proves nothing"*, so test (ii) goes
   *"through a seam on the writer"* — production code added for a test. But `knowledge_list`,
   `knowledge_status` and `knowledge_search` read the registry and write only a corpus database;
   `knowledge_refresh`'s plan and `knowledge_unlock` likewise touch `memory.db` read-only.
   `registry.ensure_table`'s docstring (`core/knowledge/registry.py:108–111`) records the measurement:
   `CREATE TABLE IF NOT EXISTS` against an existing table *"takes no write lock at all — it succeeds while
   another connection holds the writer lock"*. So under `test_knowledge_counters.py`'s held-lock fixture a
   dispatched `knowledge_list` **answers**, and the access-log row is that call's first and only
   `memory.db` write — which is exactly property (ii) with no seam and no stubbed handler. **Change:** in
   both documents, narrow the claim to *"a handler that writes `memory.db` — every memory verb — already
   held the lock for its semantic event; the knowledge verbs that read it do not, and for those the access
   log's row is the call's first write"*. Replace test (ii)'s seam with: *a dispatched `knowledge_list`
   under the held-lock fixture answers the byte-identical unlogged line inside the bound and leaves no
   `call` row*. Keep the "holds the lock throughout proves nothing" sentence but scope it to the memory
   verbs, since for them it is true and is the trap.

2. **[IMPROVEMENT] "Only `remove` raises it as the call's own `knowledge_base_busy`" is false — `unlock`
   does too.** `schema.md:927` and `build-plan.md:3961–3963`. `lifecycle.unlock` (`:319`) calls
   `lock.clear`, which raises `IndexerBusyError` when the recorded pid is provably live
   (`core/knowledge/lock.py:268–275`); `knowledge_unlock` wraps it in `_refusals_as_wire_errors`, so
   `_translated` answers `KNOWLEDGE_BASE_BUSY` (`dispatch_knowledge.py:189–192`). The two verbs refuse on
   *opposite* evidence — `remove` when the holder cannot be shown dead (`lifecycle.py:384–391`), `unlock`
   when it can be shown alive — and both land as the same string in `call.error_code`, which a reader of
   the accepted-gap paragraph should know. **Change:** *"`remove` and `unlock` raise it as the call's own
   `knowledge_base_busy` — on opposite readings of the pid, indistinguishable in the row"*; and in
   build-plan drop *"only `remove`"* if it is restated there.

3. **[IMPROVEMENT] `doctor` gains a check with no sentence in the document that enumerates its checks,
   and two decisions it needs are unmade.** `build-plan.md:3906–3913` and the done-when at `:4219–4221`
   name `harness.md` and not `distribution.md`. `distribution.md:182–190` §"The front door": *"Five checks
   and one report, in order: …"* — a closed list — and `doctor/checks.py:210–211`'s `run_all` docstring is
   *"Every check and the one report, in the order `distribution.md` states them."* The scan added without
   that sentence is the round-3 finding 7 omission again, one document over. Two things the design has not
   said and the builder cannot infer: (a) **how `doctor` decides to scan** — it has `--project` and no
   `--harness`, and `install --harness auto` refuses a tree carrying both dotdirs; the natural condition is
   *`<project>/.claude/agents/` exists*, harness-independent, and it should be stated; (b) **what outcome the
   row takes.** `Outcome` (`checks.py:40–45`) has `PASSED`, `FAILED` and `REPORTED`, and the exit status
   *"is what a script reads"* (`doctor/main.py:5`). A user whose agent deliberately excludes every
   `mcp__*` — `income-quant.md`'s own case — would make `doctor` exit 1 forever under `FAILED`; the install
   line is advisory by design. **Change:** add the check to `distribution.md`'s list with its condition and
   its outcome — `REPORTED` reads as the honest fit for detection-only — and name `distribution.md`
   §"The front door" in the done-when beside `harness.md`.

4. **[IMPROVEMENT] The `label_source` population exclusion covers `indexer` and not `cli`, which mints for
   a reason equally unrelated to the diagnosis.** `schema.md:986–988`: *"every build mints by
   construction, so counting builds as clients would read as a client population falling to minting"*.
   Before M33 `'cli'` wrote no row at all; after it every typed `zikaron knowledge` verb writes one. The CLI
   adopts the harness label where its shell carries one — `CLAUDE_CODE_SESSION_ID` *is* exported to the
   Bash tool (`research/claude-project-dir-reaches-hooks-not-shells.md:26`) — and **mints in any terminal
   outside a harness**, which is the ordinary operator case. So a `minted`-heavy `cli` population is a
   person at a terminal, not *"`KIRO_SESSION_ID` absent from some client's environment"*, and it would be
   read as the latter. **Change:** define the population positively rather than by exclusion — *"a
   `label_source` population count is taken over `client_kind IN ('hook','mcp')`, the two clients the
   diagnosis is about: a build mints by construction and a typed command mints legitimately from any shell
   no harness spawned"*.

5. **[IMPROVEMENT] Two module docstrings become false when the table moves, and the done-when names
   neither.** `core/knowledge/errors.py:3–10`: *"Deliberately **not** `ZikaronError` … The boundary that
   gives them codes is `service/dispatch_knowledge.py` … Raising `ZikaronError` here instead would put the
   wire contract in the layer that cannot know whether it is being reached over one"*; and
   `dispatch_knowledge.py:15–21`: *"`core` raises one class per refusal and gives none of them a numeric
   code, deliberately"*. After M33 the type → `ErrorCode` table lives in the first module, so the second
   sentence is false and the first argues for moving it back — the exact reader a future session will be.
   The done-when already names `ClientKind`'s docstring for the same class of sentence
   (`build-plan.md:4196–4198`). **Change:** add both to that list, with the replacement claim: *the table
   gives each class its code beside the class; `dispatch_knowledge` still constructs the `ZikaronError`
   and its payload, because only the wire boundary holds `name`, `taken` and `supplied`*.

6. **[NITPICK]** `build-plan.md:4183–4184` *"for every method in `_METHODS`, one well-formed call and one
   refused call"* — `knowledge_list` takes no parameters (`dispatch_knowledge.py:253–258`) and has no
   domain refusal; its only refused arm is `_naming_the_store`'s `store_unavailable` on a driver failure.
   Say the refused arm may be an injected driver failure for a parameterless method, so a builder does
   not quietly weaken "every" to "every method that has a refusal".

7. **[NITPICK]** `schema.md:882–888` *"a WAL append with no `fsync`"* — per commit, yes; but
   `wal_autocheckpoint` is per-connection, so a private-connection commit that crosses the 1000-page
   threshold runs the checkpoint, db-file `fsync` included, on the response path. Either set
   `PRAGMA wal_autocheckpoint = 0` on the private connection — the shared one commits on every semantic
   event and will checkpoint — or say the tail is shared with the store's own connection and inside the
   A/B's distribution.

8. **[NITPICK]** DDL comment `schema.md:169` *"one per dispatched RPC"* against the table's *"at most one"*
   (`:689`). `test_ddl.py` is red on this tree anyway and the literal moves with the code, so this is the
   cheap moment.

9. **[NITPICK]** `FINDINGS.md:100–101` lists three pre-dispatch exits where `schema.md:823–828` has four —
   the unparseable line is missing; an index that enumerates drifts, so *"the exits ahead of dispatch —
   `schema.md`'s table"*. And `:98–99` *"which a directly-run indexer may write against an unmigrated
   store"* — it now declines to (`schema.md:1662–1667`); *"declines to write against"*.

10. **[NITPICK]** `build-plan.md:3948–3955`: *"That count is the one already in the base's own `meta`"*
    now follows the `spawned_by_op_id` sentence and no longer names `files_indexed`. Move the
    `spawned_by_op_id` sentence after the `meta` one.

11. **[NITPICK]** Nullability row `schema.md:768` *"`spawned_by_op_id` is null **iff** the build was run
    directly"* against `:690`'s *"null unless the argv carried one"* — the second is the rule the re-run
    case was written for; make the table say *"null iff the argv carried no `--spawned-by-op-id`"*.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-28

**Summary judgment.** Round 4's eleven findings are applied as the brief says, and the two changes it made on
its own initiative are both right: the environment channel for `spawned_by_op_id` is the only one that keeps
`detach.spawn`'s returned-argv identity, and restoring `error_code`'s closed set through `DetailField.values`
strings is exactly what the layering rule permits. But that second change was applied in two places and the
three sentences that *followed from* the old decision were left standing — one of them in the done-when,
which is the sentence a builder implements. The design now says in one paragraph that `EVENT_SPECS` holds a
real closed set and in the next that the field is a free string checked only by a converter, and that is not
a shippable definition. The rest is precision: the "knowledge verbs take no write lock" claim is still one
notch too wide (three of the eight write the registry), the environment variable that now carries the
attribution token is named nowhere, and a spawned child refused by its own lock re-check falls between the
"not a build" paragraph and the "any outcome" cardinality. Verified against `core/events.py` (`DetailField`,
`EventSpec.validate`), `core/knowledge/errors.py`, `knowledge/indexer/{detach,main}.py`, `knowledge/scope.py`,
`core/knowledge/{builds,lifecycle,registry,lock}.py`, `service/{server,rpc,context,dispatch_knowledge}.py`,
`core/store/{connection,transactions,ddl}.py`, `doctor/{checks,main}.py`, `tests/test_knowledge_counters.py`
and every named passage of the seven design documents, `FINDINGS.md` and the archive's Q18 entry.

### Findings

1. **[BLOCKER] The design states two incompatible mechanisms for `call.error_code`, and the done-when
   carries the withdrawn one.** The brief says the membership check is restored: `EVENT_SPECS` declares
   every `ErrorCode.wire_name` plus the literal `internal_error`, `nullable=True`. Two passages say so —
   `schema.md:809–819` and `build-plan.md:4037–4045`. Three normative sentences still say the opposite:
   - `schema.md:690`, the per-kind table row that *is* the field's specification: *"the union is enforced
     by the seam's typed converter rather than by `EVENT_SPECS`, which cannot see `service/`"*.
   - `build-plan.md:4025–4026`, the bold sentence heading the very section whose bullet contradicts it:
     *"checked by the type system rather than by `EVENT_SPECS`"*.
   - `build-plan.md:4202–4204`, the done-when: *"its `error_code` **declared a nullable string there** with
     the domain enforced by the seam's converter typed `ErrorCode | ProtocolErrorCode -> str`"*.
   A builder reads the done-when and ships a free string; `test_event_kinds.py`'s spec test then passes on
   either shape, and the closed set the brief says is restored never exists. **Change**, three edits: in
   `:690`, replace the quoted clause with *"the field's `values` declare every `ErrorCode.wire_name` plus the
   one literal `internal_error`, `nullable=True`, so `log_event`'s membership check holds here as for every
   other closed-set field; the seam's converter is typed `ErrorCode | ProtocolErrorCode -> str` in addition,
   so `mypy` refuses a bare string at the call site"*. In `:4025–4026`, make the heading *"`error_code` is
   stored as the name, its reachable domain declared in `EVENT_SPECS` as strings, and its call site typed
   across both enums"*. In `:4202–4204`, *"its `error_code` declared in `EVENT_SPECS` with
   `values = (every `ErrorCode.wire_name`, 'internal_error')` and `nullable=True`, the literal pinned to
   `ProtocolErrorCode.INTERNAL_ERROR.wire_name` by a test, and the seam's converter typed
   `ErrorCode | ProtocolErrorCode -> str`"*. Then grep `nullable string|typed converter|cannot see` once more
   — this round found the three above and the brief's own sweep found neither.

2. **[IMPROVEMENT] "The knowledge verbs do not [hold the lock]" is still stated as a class, and three of
   the eight do.** `schema.md:857` (bullet header **"The knowledge verbs do not."**) and `:866` (*"for a
   knowledge verb — any held lock at all"*); `build-plan.md:4064–4065` (*"A **knowledge** verb does not"*).
   The body then lists five. `knowledge_add` runs `registry.insert` inside `in_one_transaction` on
   `memory.db` (`lifecycle.add`), `knowledge_remove` deletes the registry row, `knowledge_rename` updates
   it — all three take the write lock before the seam, so under a held lock they fail in the handler after
   the full `busy_timeout`, exactly the memory-verb position round 4 carved out. Test (ii) chose
   `knowledge_list` and is unaffected; the prose licenses a reader to pick `knowledge_rename` for the same
   test and get round 3's blocker back. **Change:** *"Five of the knowledge verbs do not — `list`, `status`,
   `search`, `refresh` and `unlock` leave the registry unwritten (`registry.ensure_table`'s measurement);
   `add`, `remove` and `rename` write it and sit with the memory verbs"*, in both documents, and change
   `:866`'s *"for a knowledge verb"* to *"for one of those five"*.

3. **[IMPROVEMENT] The environment variable that now carries `spawned_by_op_id` is named nowhere, and the
   one hazard of the channel is unstated.** `schema.md:691`, `build-plan.md:3957–3962`,
   `knowledge-index.md:1606–1612` all say *"through the environment"* and stop. `detach.spawn`
   (`detach.py:50–83`) takes no `env` and lets `Popen` inherit the service's; its module docstring's rule is
   that *"nothing but a shared definition keeps the two agreeing"* because the spawn does not import the
   thing it runs — so the variable's name is exactly the kind of fact that needs one declaration both sides
   read, and the design leaves it to two files to agree on by luck. The hazard: a service is long-lived and
   spawns many builds, so a token set on `os.environ` rather than on a per-spawn copy is inherited by every
   later build from every later verb, attributing them all to the first caller — silently, since the row
   would look complete. **Change:** name the variable (e.g. `ZIKARON_SPAWNED_BY_OP_ID`), state where the
   constant lives (one module both `detach` and the indexer's entry import — `detach.py` itself is the
   natural owner, since `main.py` already treats it as the argv's owner), and state that `spawn` passes
   `env={**os.environ, VAR: op_id}` **as a copy, never by assignment into the service's environment**, so a
   build spawned by a verb that set no token inherits none. Add a fixture to the done-when: two spawns from
   one service, the second with no token, and the second's row null.

4. **[IMPROVEMENT] A spawned child refused by its own re-check is neither "not a build" nor covered by "any
   outcome".** `schema.md:948–949`: *"`IndexerBusyError` is not a build … The lock refuses the spawn and no
   process starts"* — true of `builds.plan` in the service. But the child re-establishes every refusal
   (`indexer/main.py:74–78`, *"the check and the build are not one transaction"*): `builds.prepare`
   (`builds.py:182–204`) raises `IndexerBusyError`, `DanglingKnowledgeBaseError` and
   `CorpusRootMissingError` inside the spawned process, and `scan.run` (`scan.py:186, 377`) raises
   `IndexerBusyError` again at the lock. A process that started, opened `memory.db`, loaded nothing and
   exited 1 is either a build with a row (`ok=false`, `error_code=knowledge_base_busy`, `files_indexed`
   null — consistent with `:928`'s *"whether a `knowledge_refresh` was refused or a build died on it"*) or
   it is not, and the cardinality *"one per indexer build, whatever its outcome"* cannot say which. The
   two-spawn race — an agent's `refresh` and an operator's foreground run — is the ordinary way to reach
   it. **Change:** one sentence after `:949`: *"A child that started and was refused by its own re-check is
   a build with a row, `error_code` the refusing class's `wire_name`; what has no row is the spawn the
   service never made."* And name the case in the done-when's `knowledge_build` fixtures.

5. **[IMPROVEMENT] The `doctor` row's shape when the scan ran and named nobody is unstated, and it is the
   case `checks.py`'s own principle says must be distinguishable.** `distribution.md:188–194` fixes the
   condition (directory exists) and the outcome (`REPORTED`); `Finding.__post_init__` (`checks.py:61–63`)
   forbids a `remedy` on anything but `FAILED`, so the advice line — *add `mcp__zikaron`* — must ride in
   `detail`. Unstated: whether a clean scan emits a row saying *none* or emits nothing. `_by_reason`
   (`indexer/main.py:151–159`) already states the rule this project applies — *"nothing was skipped" and
   "this was not measured" are different answers* — and an absent row is the second. **Change:** *"The row
   is present whenever the directory exists, names the agents or says `none`, and is absent only when there
   was no directory to scan; the advice travels in `detail`, since `REPORTED` carries no remedy."* Add the
   three states to `test_doctor.py`'s list in the done-when.

6. **[NITPICK]** `knowledge_build.duration_ms` (`schema.md:691`) inherits neither the type nor the clock
   `call`'s row fixes at `:690` (*"a float, from `time.perf_counter()`"*). A build is minutes, so an integer
   would do — say which, or write *"as `call`'s"*.

7. **[NITPICK]** `core/knowledge/errors.py:1–10` will carry `wire_name` strings beside *"raised down in
   `core` where no wire shape exists yet"* and *"putting the wire contract in the layer that cannot know
   whether it is being reached over one"*. The brief judges both true as written, and they are — but a
   reader meeting `wire_name = "knowledge_base_busy"` under that docstring will ask what it is for. One
   clause in the module docstring — *a `wire_name` is the name the build log records for the class, held
   equal by test to the code the boundary maps it to; it is not a code* — is a contract statement, not the
   annotated repair `CLAUDE.md` forbids.

8. **[NITPICK]** `harness.md:601–616`'s bullet says *"The install scans"* and does not say `doctor` re-runs
   it. `distribution.md` points at `harness.md` for the predicate; nothing points back. Add *"`zikaron
   doctor` runs the same function (`distribution.md` §"The front door")"*, so a reader of the normative
   installer document learns the scan outlives the install.

9. **[NITPICK]** `schema.md:1693` *"the argv `detach.command` prints"* — `command` returns it;
   `knowledge_refresh`'s result prints it as `foreground_command`. `architecture.md:2093–2094` *"the `call`
   row … is the one thing any of them adds to `memory.db`"* — `knowledge_add` adds a registry row; *"the
   one thing any of them adds outside the registry"*.

10. **[NITPICK]** `schema.md:902–906` *"the shared connection commits on every semantic event and keeps the
    default, so the WAL still gets checkpointed"* — conditional on a semantic commit occurring. A session
    that only searches the knowledge index writes one WAL frame per `call` and nothing checkpoints until the
    shared connection's next commit or the store's close. Bounded in practice, since every push writes
    `surface_call`; say *"checkpointed at the shared connection's next commit or at close"* so the bound is
    stated rather than assumed.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-28

**Summary judgment.** Round 5's blocker is closed at all five sites — the per-kind row, the section
heading, the done-when, `schema.md` §"`call` is an access log" and build-plan's bullet now state one
mechanism, and a grep for the withdrawn phrasings finds nothing in the corpus. The lock split, the
`ZIKARON_SPAWNED_BY_OP_ID` channel, the refused-child rule, the `doctor` row and the checkpoint bound
are each stated correctly and hold against the code; `FINDINGS.md` §"Current state" now says two kinds,
two widenings and a tree that is red by design. What remains is completeness rather than contradiction,
and it is concentrated in `knowledge_build`: the refused-child rule promises a row for three refusals
that arrive before the child holds the registry `id` the row is keyed by, the kind's closed set is left
to the code in exactly the way round 5 refused for `call`, and the done-when carries no test for any of
the kind's five stated properties — three of round 5's asks landed in `schema.md` and not in the done-when
the brief reports them applied to. Verified against `core/knowledge/{builds,lifecycle,errors}.py`,
`knowledge/{scope,indexer/detach,indexer/main}.py`, `service/{server,dispatch_knowledge}.py`,
`doctor/{checks,main}.py`, `harness/spec.py`, `core/events.py` and every named passage of the seven
documents, `FINDINGS.md` and the archive's Q18 entry.

### Findings

1. **[IMPROVEMENT] "A child that started and was then refused is a build with a row" cannot be
   implemented for three of the refusals a child can raise, because they arrive before it holds a
   registry `id`.** `schema.md:955–961` names `IndexerBusyError`, `DanglingKnowledgeBaseError` and
   `CorpusRootMissingError` — each raised *after* `builds.prepare` has resolved the name to a
   `KnowledgeBase`, so an `id` is in hand. But `prepare`'s own `Raises:` (`builds.py:190–198`) leads
   with `InvalidNameError` and `UnknownKnowledgeBaseError`, both raised with no registry row resolved,
   and `scope.open_store` (`scope.py:94–100`) raises `RegistryUnavailableError` before `build()` runs
   at all — no connection, so no row is even possible. The nullability table (`:769`) does not list
   `knowledge_base_id`, and `:771` declares only `group_served.version_served` NOT NULL outright, so by
   the table's own rule (`:757–758`) the field's null case is *"a design question, not an inference"*
   — and a builder reaches it on the first `unknown`-name fixture. The cases are ordinary: a foreground
   re-run with a typo, and `knowledge_remove` racing a `knowledge_refresh`'s spawn. **Change:** one
   sentence after `:961`: *"Three refusals arrive before the child holds an `id` or a connection —
   `knowledge_base_unknown` and a blank name from `builds.prepare`, and a store that would not open
   (`RegistryUnavailableError`) — and those write no row: there is no corpus whose cost this is, and a
   row keyed by nothing joins to nothing. The record of such a child is the spawning verb's `call` row
   — for the `remove`-races-`refresh` case, `remove`'s — or the operator's own terminal."* Add
   `knowledge_base_id` to `:771`'s NOT-NULL sentence so the table stops being silent about it.

2. **[IMPROVEMENT] The done-when states no test for `knowledge_build`, and three of round 5's asks
   were applied in `schema.md` but not here.** `build-plan.md:4191–4252` mentions the kind once
   (`:4211–4212`, *"the indexer emits `knowledge_build` under a `client_kind` the same migration widens"*)
   and names no fixture for any of its five stated properties: the version gate (round 2 #7 — *"the
   test drives a version-2 store without provoking a constraint"*), the refused-child row (round 5 #4
   asked for it in the done-when's fixtures), the per-spawn environment copy (round 5 #3 — *"two spawns
   from one service, the second with no token, and the second's row null"*), the build waiting its
   ordinary `busy_timeout` for the row (round 3 #4), and the `wire_name` equality and disjointness tests
   `schema.md:936–949` describes. `doctor`'s three row states (round 5 #5 — *"add the three states to
   `test_doctor.py`'s list"*) are likewise absent: `:4244–4248` names the function, the list entry, the
   condition and the outcome, and no test. A grep of the brief for `test_doctor`, `two spawns`,
   `refused by its own`, `version-2 store` and `spawned_by` finds none. The done-when is the builder's
   contract, and a property with no test in it ships on discipline — the failure mode this milestone
   names for the knowledge verbs. **Change:** add one clause per property, in the existing style:
   *"`knowledge_build` is exercised five ways — a schema-2 store attempts no write and raises nothing; a
   child refused in `builds.prepare` or `scan.run` writes `ok=false`, that class's `wire_name`,
   `files_indexed` null; two spawns from one service, the second passing no token, leave the second's
   `spawned_by_op_id` null and the service's `os.environ` without the variable after both; the row
   written under a held lock lands once the lock releases inside `BUSY_TIMEOUT_MS`; and every
   `KnowledgeError` the boundary maps carries its `ErrorCode`'s `wire_name`, with the build-only names
   disjoint from every `ErrorCode.wire_name`. `test_doctor.py` asserts the scan row's three states —
   absent when no `.claude/agents/` exists, `none` when it names nobody, the names otherwise, `REPORTED`
   in both present cases."*

3. **[IMPROVEMENT] `knowledge_build.error_code`'s `values` tuple is unstated, and the member an
   unexpected exception takes is unnamed.** Round 5's blocker was that `call.error_code`'s closed set
   was left to the code; `knowledge_build` has the same gap one row down. `schema.md:691` says the
   domain is *"defined below and is deliberately one vocabulary with `call`'s"*, and §"What is
   instrumented" (`:931–953`) defines it as the mapped classes' `wire_name`s, the build-only classes'
   names, and *"a member is named for it here"* for a driver error or unexpected exception — without the
   name. So the set is a strict superset of `call`'s `values` (it holds `corpus_root_missing` and the
   unexpected member, which `call`'s cannot), a builder cannot write `EVENT_SPECS`'s tuple from the text,
   and a query for failed builds has no string to match. `core/events.py` can import
   `core/knowledge/errors.py` (both `core/`, no cycle: that module imports stdlib and a `TYPE_CHECKING`
   `lock`), but enumerating subclasses by `__subclasses__()` would be the fragile way. **Change:** in the
   `:691` row, *"`values` is the tuple `core/knowledge/errors.py` exports — every `KnowledgeError`
   class's `wire_name` plus `build_failed` for a driver error, an `OSError` or an unexpected exception —
   `nullable=True`; it contains every `ErrorCode.wire_name` a build can produce and is a superset of
   `call`'s, agreeing with it wherever one condition appears in both"*, naming the exported tuple (a
   module-level `WIRE_NAMES`, say) so `EVENT_SPECS` reads a declaration rather than walking a class
   tree. Fix the literal `build_failed` or choose another, but state it: it is the string the failed-build
   query is written against.

4. **[IMPROVEMENT] Two `doctor` docstrings go false at M33, and `distribution.md` files the scan among
   "the checks" while giving it the report's outcome.** `checks.py:11` — *"**One row reports rather than
   checks.**"* — and `:211` — *"Every check and the one report"* — are both counts, and after M33 two rows
   carry `REPORTED`. `distribution.md:184` lists *"The checks, and one report, in order:"* with the scan as
   the sixth check, then `:198` *"The report is the linked SQLite version"* — but `Outcome`'s docstring
   (`checks.py:41`) defines `REPORTED` as *"a row [that] cannot fail"*, which makes the scan a report in
   the module's own vocabulary. The done-when (`:4212–4220`) names `ClientKind`'s docstring and the two
   error-module docstrings for exactly this class and not these two. **Change:** `distribution.md:184`
   *"The checks and the reports, in order:"*, `:198` *"The other report is the linked SQLite version"*;
   and add `checks.py`'s module docstring and `run_all`'s to the done-when's docstring list, with the
   replacement claim *"two rows report rather than check: the SQLite version, which has no correct value,
   and the agent scan, whose finding is a grant the user made on purpose"*.

5. **[NITPICK]** `detach.py:12–16` — *"Everything else it inherits — the environment, so that it reads the
   same configuration layers the parent read"* — becomes *the environment plus one variable* at M33, and
   the module's rule that *"the spawn does not import the thing it runs"* will sit beside `main.py`
   importing `detach` for the constant, which is the reverse direction and fine. Name the docstring in the
   done-when's list and give it the one clause that says the constant is why the child may import the
   spawner.

6. **[NITPICK]** `schema.md:691` *"`env={**os.environ, …}` — a per-spawn copy"* — when no token is passed
   the copy should **drop** `ZIKARON_SPAWNED_BY_OP_ID` rather than carry whatever the service's own
   environment holds, or a service started from a shell that happened to export it attributes every
   unattributed build to that value. One clause: *"and the copy omits the variable when no token is
   passed, rather than inheriting one"*.

7. **[NITPICK]** `build-plan.md:3900–3904` and `harness.md:611–613` name `disallowedTools:` as the
   considered-and-excluded case. Claude Code also loads user-level agents from `~/.claude/agents/`,
   which take the same `tools:` frontmatter and are usable in any project; an explicit allowlist there is
   equally blind and the scan over the *project's* directory never sees it. Add it to the same sentence,
   for the same reason the sentence gives — so the next diagnosis knows it was considered.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-28

**Summary judgment.** Round 6's seven findings are applied as the brief says, and the structural cut to the
`knowledge_build` cell is right: the row now states five fields and a clause each, and every rationale it
shed appears exactly once in §"What is instrumented". One thing stops this shipping, and it is in the closed
set that round was asked to name: `WIRE_NAMES` as declared — every `KnowledgeError`'s `wire_name` plus
`build_failed` — cannot hold the three `ZikaronError` codes a build raises today (`index_failed`,
`bad_config`, `schema_incompatible`), so a build ending on any of them has no admissible `error_code`, and
the sentence calling the set *"a superset of `call`'s `values`"* is false. That wording was round 6's own
and was wrong there too. The rest is precision on the three fields that describe a build's *work*, and
three small consistency items. Verified against `core/knowledge/{errors,builds,lifecycle,scan,counters,
disposal,database,meta,registry}.py`, `core/knowledge/{writes,vectors,chunking}.py`'s raise sites,
`knowledge/{scope,indexer/detach,indexer/main}.py`, `service/{server,envelope,dispatch_knowledge,
context}.py`, `core/{errors,events}.py`, `core/store/{ddl,connection,transactions}.py`,
`doctor/checks.py`, the on-disk `FINDINGS.md` §"Current state" and live-question preamble, the archive's
Q18 entry, and every named passage of the seven documents.

### Findings

1. **[BLOCKER] `knowledge_build.error_code`'s closed set omits three codes a build raises today, and the
   "superset" sentence is false.** `schema.md:947–956` gives the domain as the mapped `KnowledgeError`
   classes' names, the build-only classes' names, and `build_failed` for *"a driver error, an `OSError`, or
   an unexpected exception"*; `:691` fixes `values` as that `WIRE_NAMES`. But a build propagates
   `ZikaronError`s that are none of those: `core/knowledge/database.py:37` raises `SCHEMA_INCOMPATIBLE`
   for a corpus file newer than the build, `meta.py:178` raises `BAD_CONFIG`, and `writes.py:103,112`,
   `vectors.py:27` and `chunking.py:138` raise `INDEX_FAILED` at three stages — `builds.prepare`'s and
   `lifecycle.refresh`'s `Raises:` both list `ZikaronError`, and `scope.execute` (`scope.py:130–133`)
   handles it as its own class, so it is not "unexpected". Under the stated *one vocabulary with `call`'s*
   rule the natural value is `error.code.wire_name` — `index_failed` — which is in `call`'s `values` and
   **not** in `WIRE_NAMES`, so `EventSpec.validate` (`events.py:210–211`) raises `ValueError` from inside
   the row write; the build's failure map is contention-only by design (`:1005–1009`), `execute` catches
   neither `ValueError` nor anything but its three classes, and the build ends in a traceback *because it
   tried to record why it failed*. And `:996–999` — *"It is a **superset** of `call`'s `values`"* — is false
   as the set is defined: `call`'s `values` hold `not_found`, `store_busy`, `version_conflict` and twenty
   more that no `KnowledgeError` carries. **Change**, in `:947–956` and the `:691` cell: state the rule per
   exception class — *a `KnowledgeError` records its `wire_name`; a `ZikaronError` records
   `code.wire_name`; anything else records `build_failed`* — and declare `values` as **every
   `ErrorCode.wire_name`, plus the build-only `KnowledgeError` names, plus `build_failed`**.
   `core/knowledge/errors.py` may import `ErrorCode` to compose that tuple (`core` → `core`; importing a
   code to name a set is not raising one, so its docstring's *"deliberately not `ZikaronError`"* stands),
   or `core/events.py` composes it from `ErrorCode` and a `BUILD_ONLY_WIRE_NAMES` export — say which.
   Replace the superset sentence with the true relation: *"the two share every `ErrorCode.wire_name`;
   `internal_error` is `call`'s alone, and `corpus_root_missing` and `build_failed` are the build's
   alone."* Add a done-when fixture: a build ending on `index_failed` — the embed stage, forced with a
   stub encoder — writes `ok=false, error_code='index_failed'`, `files_indexed` null. Grep `superset` once
   more afterwards; `schema.md:999` is the only design site today.

2. **[IMPROVEMENT] The three fields that describe a build's *work* are each ambiguous in the direction
   that misreads a cost history.** The kind exists to answer *"what has building it cost over time"*
   (`schema.md:1001–1003`), and each of `full`, `files_indexed` and `duration_ms` can be read two ways:
   - `full` (`:691`, *"distinguishes a rebuild from an incremental pass"*) — requested or effective?
     `scan.py:368–372` and `disposal.py:53–54` make an identity-forced rebuild (`ScanResult.rebuilt_identity`)
     a whole-corpus reindex at `full=false`, and `main._print_rebuild` exists because *"nothing in its
     numbers would show it"*. A query grouping cost by `full` files those minutes under incremental.
   - `files_indexed` — `counters.py:8–14` defines it as **the corpus the scan leaves behind**, not files this
     scan wrote: a 0.26 s no-change rebuild reports 2,034, the same as the full build before it. The cell
     says only that it is *"the count `meta` holds"*.
   - `duration_ms` — *"as `call`'s"* fixes the type and the clock, not the span: whether the ~1 s model
     load in `build_settings` and `prepare`'s registry reads are inside, which matters for exactly the
     short builds the float was chosen for.
   **Change:** in the `:691` cell, *"`full` is the flag the build was asked for; `rebuilt` says whether the
   encoder identity forced a whole-corpus reindex regardless"* (a sixth field, never null, from
   `rebuilt_identity is not None`) — or record `full` as effective and say so; *"`files_indexed` is the
   files in the index after the build, `counters.py`'s reading, not the files this build wrote"*; and
   name the span — from `prepare` to the completing transaction, or across `build()` including the load —
   and pick one. If `rebuilt` is added, `EVENT_SPECS`'s order and the done-when's field list move with it.

3. **[NITPICK] Where the build's row is written is unstated, and the obvious site is a closed connection.**
   `scope.execute` renders a failure *after* `open_store`'s `async with store` has exited
   (`scope.py:101–104, 126–139`), so a row for a refused or failed child must be written inside `build()`
   or `_run`, on the connection `open_store` yielded, before the exception leaves that scope — and for
   *"an unexpected exception"* that means catching `Exception` there, writing, and re-raising. One sentence
   in §"What is instrumented", since the done-when's fixtures pin the outcome and a builder who puts the
   write in `execute` meets the `ValueError`-on-closed-connection class §"`call` is an access log" already
   names.

4. **[NITPICK] `envelope` stops being unused on the two spawning handlers.** `_spawn`
   (`dispatch_knowledge.py:329–344`) takes `ctx`, `planned` and `full`; the token it must now pass to
   `detach.spawn` is `envelope.op_id` (`envelope.py:63`, a `str` on every resolved envelope), which
   `knowledge_add` and `knowledge_refresh` hold under `# noqa: ARG001`. On those two the marker comes
   off rather than being reworded; the done-when's *"narrowed to 'records no semantic event'"* applies to
   the other six. Worth one clause there so a builder does not narrow all eight.

5. **[NITPICK] `RegistryUnavailableError` gets a `wire_name` no row can hold.** *"Every `KnowledgeError`'s
   `wire_name`"* (`:691`) includes it, and `:966–972` says it writes no row. Either exclude it from the
   declaration or say in that paragraph that the name is declared and unreachable, so the disjointness
   test's author is not left wondering which was meant.

6. **[NITPICK] `core/events.py`'s docstring joins the list the done-when already keeps.** `events.py:9–13`
   argues the vocabulary sits *"beside the error contract rather than inside any one layer"* so that no
   layer *"import[s] across the domain to reach it"*; after M33 it imports `core/knowledge/errors.py` for
   `WIRE_NAMES`. No cycle — nothing under `core/knowledge/` imports `core.events` — but it is the class
   round 4 #5 and round 6 #4 named: add it to the done-when's docstring list with the clause that the
   vocabulary *imports* one layer's declared names rather than restating them, which is the same rule
   from the other side.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-28

**Summary judgment.** Round 7's blocker is closed correctly: the per-exception-class rule, the composed
`values`, the crash-path rationale and the `index_failed` fixture are each stated once and hold against
the raise sites (`database.py:38`, `meta.py:179`, `writes.py:103,112`, `vectors.py:27`, `chunking.py:138`)
and against `_translated`, which maps seven classes and leaves exactly `CorpusRootMissingError` and
`RegistryUnavailableError` unmapped. The consolidation of §"What is instrumented" reads as one argument
now, and every corrected passage in the other six documents and `FINDINGS.md` is as the brief says. What
remains is confined to `knowledge_build`'s **failed-build** cells, where three sentences do not survive
contact with `indexer/main.py` and `scan.py`: the nullability table's rule for `files_indexed` contradicts
the done-when's own embed-stage fixture; `rebuilt` is declared never-null from a `ScanResult` that does not
exist when the scan raised; and the row site the design fixes — inside `build()` — has no registry `id` in
hand for the refusals the design says produce a row. None is a blocker; each is one or two sentences, and
each is the kind a builder resolves silently in whichever direction is nearest. Verified against
`knowledge/indexer/main.py`, `knowledge/scope.py`, `core/knowledge/{builds,lifecycle,scan,counters,errors}.py`,
`core/{errors,events}.py`, `service/{rpc,dispatch_knowledge}.py`, `core/store/store.py`, and every named
passage of the seven documents, `FINDINGS.md` and the archive's Q18 entry.

### Findings

1. **[IMPROVEMENT] The nullability table's rule for `files_indexed` contradicts the done-when's
   `index_failed` fixture, and `rebuilt` cannot be "never null" on the rows where `files_indexed` is null.**
   `schema.md:769`: *"`files_indexed` is null when the build failed **before the scan began** — 0 means a
   scan ran and indexed nothing"*. `build-plan.md:4222–4225` and the `:691` cell: a build ending on
   `index_failed` at the embed stage writes *"a null `files_indexed`"* — and the embed stage is inside the
   scan (`scan.run` → `disposal.run`, `scan.py:412–416`), after `_begin` took the lock, so by the table's
   rule that row would carry a count. The code settles which is right: `counters` is local to `scan.run`
   and `ScanResult` is returned only after `_complete` (`:418–429`), so on a raise nothing holds the count
   and the corpus `meta` still carries the *previous* build's — null is the only honest value, and the
   fixture is correct while the table is not. The same object decides `rebuilt`: `:691` and `:1024–1026`
   make it *"never null"*, read off `rebuilt_identity`, which exists only on that same returned
   `ScanResult`. A child refused in `prepare` has no scan and no identity comparison; a build that died at
   embed inside an identity-forced rebuild spent its minutes on a reindex and `drop_derived` already ran
   (`:398–401`), and nothing outside `scan.run` can say so. **Change:** in `:769`, *"`files_indexed` and
   `rebuilt` are null **iff** `ok` is false — a build that did not complete its scan has no corpus-left-
   behind to count and no settled answer to whether it rebuilt, whether it was refused before the scan or
   died inside it; **0 means a completed scan indexed nothing**"*; in `:691` and `:1024–1026`, replace
   *"never null"* with *"null only on a failed build, beside `files_indexed`"*. If the design would rather
   keep `rebuilt` non-null, it must say what a failed build records and why `false` is not a claim about
   minutes that were in fact spent on a rebuild.

2. **[IMPROVEMENT] The row site the design fixes has no registry `id` for the refusals it says produce a
   row.** `schema.md:987–991` puts the write *"inside `build()`, on the connection `open_store` yielded"*,
   and `:979–985` says a child refused in `builds.prepare` by `IndexerBusyError`, `DanglingKnowledgeBaseError`
   or `CorpusRootMissingError` *"is a build with a row"* under a `knowledge_base_id` declared NOT NULL
   (`:771–774`). But `prepare` (`builds.py:201–204`) raises `planned.refusal` and discards the
   `PlannedBuild` that held the `KnowledgeBase`; none of those three exception classes carries an `id`
   (`errors.py:113–166`); and `build()` (`main.py:88`) does not even bind `prepare`'s return value. So at
   the only catch site the design names, the ordinary case — *"an agent's `refresh` racing an operator's
   foreground run"* — arrives with nothing to key the row by. The `:993–999` split (*"arrive before the
   child holds an `id`"*) describes `plan()`'s internal state, which `build()` cannot see from the
   exception. The fix is one sentence and follows the design's own class split: **`build()` resolves the
   registry row itself, before `prepare`** — `registry.require(db, name)` raises exactly `InvalidNameError`
   and `UnknownKnowledgeBaseError`, the two `prepare`-refusals that write no row — and holds that `id`
   across `prepare` and `refresh`; a refusal after it is written under that `id` whatever class it is,
   including an `UnknownKnowledgeBaseError` from `refresh`'s own second `prepare` (`lifecycle.py:312`)
   when a `remove` landed between the two reads. State it as a rule by **class**, not by whether an id
   "was resolved", since the second is not observable at the catch. While there: `OpenStore`
   (`scope.py:36–53`) yields `connection` and `config` and not `meta`, so *"read from the `meta` its
   opener has already read"* (`:1037–1038`, `:1772–1773`) needs `OpenStore` to carry `schema_version` —
   one field, worth naming beside the version gate so a builder does not reopen `meta` on the connection.

3. **[IMPROVEMENT] The "true relation" sentence omits a declared member.** `schema.md:975–977`: *"the
   build's alone are `corpus_root_missing` and `build_failed`"*. Two paragraphs up (`:953–955`)
   `RegistryUnavailableError`'s name is *"declared and unreachable … declared anyway"*, and `:967–969`
   defines `BUILD_ONLY_WIRE_NAMES` as *"the classes no wire path maps"* — which `_translated` makes exactly
   `{CorpusRootMissingError, RegistryUnavailableError}`. So `registry_unavailable` is in the build's
   `values` and in nobody else's, and a disjointness or set-difference test written from this sentence is
   red by one member. This is the restated-enumeration class the corpus has a rule for. **Change:** *"the
   two share every `ErrorCode.wire_name`; `internal_error` is `call`'s alone, and `BUILD_ONLY_WIRE_NAMES`
   plus `build_failed` are the build's alone"* — naming the export rather than its members, so the sentence
   stays true when a third build-only class lands.

4. **[NITPICK]** `build-plan.md:3975–3977` still summarises `schema.md`'s vocabulary as *"the disjointness
   test, `build_failed` for an unexpected exception, and the `IndexerBusyError` case"* — the
   `ZikaronError → code.wire_name` rule that round 7's blocker was about is absent from the brief's own
   sentence, and a reader of the brief alone would file `index_failed` under "unexpected". Four words:
   *"a `ZikaronError`'s own `wire_name`, `build_failed` for the unnamed remainder"*.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-28

**Summary judgment.** Round 8's four findings are applied as the brief says, and each holds against the
code: the `files_indexed`/`rebuilt` rule matches `scan.run`'s single return site (`scan.py:421–429`),
`Store.meta` exists (`store.py:237`) for `OpenStore` to carry `schema_version` forward, the true-relation
sentence names the export, and the brief's own summary carries the per-class rule. No blocker remains, and
the other six documents, `FINDINGS.md` and the archive's Q18 entry are as the brief reports. What remains
is confined to the paragraph round 8 asked for, and it is that finding's own correction turned around: the
text describes a **positional** rule — nothing before `require` returns, everything after it under the id
it bound — and labels it a rule "by exception class", then names, in its own last clause, a class that
lands on both sides. And hoisting `require` above `prepare` moves it above the only call that creates the
registry table, which `Store.open` never does. Both are one or two sentences. Verified against
`core/knowledge/{registry,builds,lifecycle,scan,meta}.py`, `knowledge/{scope,indexer/main}.py`,
`core/store/store.py`, the on-disk `FINDINGS.md` §"Current state", and every named passage of the seven
documents and the archive.

### Findings

1. **[IMPROVEMENT] The split is positional, the text calls it "by class", and one class falls on both
   sides of it.** `schema.md:998–1003`: *"`registry.require(db, name)` supplies it and raises **exactly**
   `InvalidNameError` and `UnknownKnowledgeBaseError`, which are the two refusals that write no row. That
   makes the split a rule by **exception class**, which the catch can see, rather than by whether an id
   'was resolved', which it cannot: a refusal raised after `require` succeeds is written under that id
   whatever its class — including an `UnknownKnowledgeBaseError` from `refresh`'s own second resolution"*.
   So `UnknownKnowledgeBaseError` writes no row from `require` and a row from `refresh` — the same class,
   two outcomes — which is exactly not a rule by class. And *"whether an id was resolved, which it
   cannot"* is backwards: with `require` outside the `try`, the id is a bound local at the catch, so that
   is precisely what the catch sees, by construction. `:1010` then opens *"Three refusal classes write no
   row"* and lists `UnknownKnowledgeBaseError` among them, unqualified. The enumeration is also short: a
   `ZikaronError` from `Store.open` itself — `schema_incompatible` on a store a newer service migrated,
   `bad_config` on a missing `meta` key — passes through `open_store`'s `except (aiosqlite.Error, OSError)`
   un-renamed (`scope.py:94–100`) and likewise arrives with no connection, so it is a fourth no-row case
   the by-class list omits and the positional rule covers without naming. A builder taking "by class"
   literally adds `except (InvalidNameError, UnknownKnowledgeBaseError): raise` inside the `try` and drops
   the row for the `remove`-races-`refresh` case the same paragraph promises. The done-when at
   `build-plan.md:4218–4219` already has the right form — *"a refusal reaching neither an `id` nor a
   connection writes no row at all"*. **Change:** at `:998–1003`, *"`registry.require(db, name)` supplies
   it, **outside the `try` that guards the rest**, so the rule is positional and the catch reads no class:
   nothing raised before `require` returns writes a row, because no id exists; everything raised after it
   is written under the id it bound, whatever its class. `require`'s two documented refusals therefore
   write none — and the same `UnknownKnowledgeBaseError` raised later by `refresh`'s own resolution, when
   a `remove` landed between the reads, is written, since by then `build()` holds the id."* At `:1010`,
   replace *"Three refusal classes write no row"* with *"Nothing raised before an id or a connection
   exists writes a row"*, and give the cases as instances rather than as the set: `require`'s two
   refusals; `RegistryUnavailableError` from `open_store`; and a `ZikaronError` from `Store.open`, which
   `open_store` does not rename. Drop "exactly" (finding 2 says why).

2. **[IMPROVEMENT] `require` hoisted above `prepare` now runs ahead of the only call that creates the
   registry table.** `Store.open` creates no `knowledge_bases` table — `registry.py:30–35`: *"This is the
   **only** site that creates the table"*, and `store.py`'s `_create_tables_and_meta` runs `ddl`'s
   statements alone — so the table exists only once some knowledge verb has run `registry.ensure`.
   `prepare` → `plan` does exactly that first (`builds.py:162`) and *then* resolves the name. Placing
   `require` ahead of `prepare` (`schema.md:994–998`) puts a `SELECT … FROM knowledge_bases` ahead of the
   `CREATE TABLE IF NOT EXISTS`, so on a store no knowledge verb has ever touched — a memory-only store
   and a hand-typed `python -m zikaron.knowledge.indexer <name>` — `build()`'s first statement raises
   `aiosqlite.OperationalError: no such table`, which `scope.execute` renders `failed:` where today the
   same input renders `refused: no knowledge base named …`. The done-when's fixture for *"a refusal
   reaching neither an `id` nor a connection"*, driven on a fresh store with an unknown name, meets that
   error rather than the `UnknownKnowledgeBaseError` it is written against. `lifecycle.unlock:340–341`
   and `remove:382–383` are the pattern: `await registry.ensure(db)` then `await registry.require(db,
   name)`. **Change:** at `:998`, *"`registry.ensure(db)` and then `registry.require(db, name)` — the pair
   `lifecycle.unlock` and `remove` open with, since `Store.open` creates no registry table and `prepare`
   was the call that did"*. Soften *"raises **exactly**"* to *"its two documented refusals"*: `require`
   also propagates a driver error and `parse_id`'s `ValueError` on a hand-edited `id` (`meta.py:286–312`),
   and under finding 1's positional rule neither needs naming. Add to the done-when's fixture at `:4218`
   that the store in it has had no knowledge verb run on it, so the test is red if `ensure` is missing.

3. **[NITPICK]** Two version-gate sentences outside `schema.md` still phrase the source as the opener's
   `meta` rather than the field a builder must add: `FINDINGS.md:99–100` *"deciding from the `meta` its
   opener already read"* and `build-plan.md:3980–3982` *"read from the `meta` its opener already holds"*.
   Both are true now that `OpenStore` carries it, and neither names `OpenStore.schema_version`, which is
   the thing that makes them true. One clause each: *"from the `schema_version` `OpenStore` carries"*.

4. **[NITPICK]** `schema.md:1002` *"`refresh`'s own second resolution"* — with `build()`'s `require`
   hoisted, `refresh`'s `prepare` → `plan` → `require` is the third resolution of the name inside
   `build()`. *"`refresh`'s own later resolution"*.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-09-28

**Summary judgment.** Round 9's four findings are applied and each holds against the code: `registry.py:32–35`'s
only-creation-site docstring, `builds.plan:162`'s opening `ensure`, the `ensure`/`require` pair at
`lifecycle.unlock:340–341` and `remove:382–383`, `require`'s two documented raises, `open_store:96`'s
`except (aiosqlite.Error, OSError)` with `ZikaronError(Exception)` passing through it, and `Store.open`'s
documented `SCHEMA_INCOMPATIBLE`/`BAD_CONFIG` raises (`store.py:380–386`). The positional rule is stated once,
correctly, and the catch-site reasoning is right. No blocker. What remains is two consequences of that rewrite
not carried through — the no-row paragraph keeps a pre-rewrite example, *a corpus removed while a build for it
was in flight*, that the positional paragraph a few lines up assigns to the row-writing side without either
naming the window; and the done-when says a fixture is red without `ensure` when the assertion it specifies is
green either way — plus the success path of the build's row write, which is unspecified in the one respect the
`call` design was held to. Verified against `core/knowledge/{registry,builds,lifecycle,meta,counters}.py`,
`knowledge/{scope,indexer/main}.py`, `core/store/store.py`, `core/errors.py`, and the on-disk `schema.md`
§"What is instrumented", `build-plan.md` §M33 done-when and `FINDINGS.md` §"Current state". Line numbers are as
read this round; `schema.md`'s moved by four between two reads, so the bold lead-ins are the durable citation.

### Findings

1. **[IMPROVEMENT] The `remove`-races-build example sits on both sides of the positional split, and only one
   side names the window.** `schema.md:1011–1013` ¶"The rule is positional": *"the same
   `UnknownKnowledgeBaseError` raised later, by `refresh`'s own resolution after a `remove` landed between the
   reads, *is* written"*. `schema.md:1027–1029` ¶"Nothing raised before an id or a connection exists": *"The
   record of such a child is the spawning verb's `call` row — for a `remove` racing a `refresh`, `remove`'s …
   Both cases are ordinary: a foreground re-run with a typo, and a corpus removed while a build for it was in
   flight."* Same trigger, opposite outcomes, and the second passage does not say which window it means. There
   are two: a `remove` landing between the service's `plan` and the child's `require` refuses at `require` and
   writes no row; one landing between the child's `require` and `refresh`'s own `prepare` (`lifecycle.py:312`)
   writes a row under the id. A reader of the no-row paragraph alone concludes the race writes nothing; a reader
   of the positional paragraph alone, the opposite. **Change:** at `:1027–1029`, *"for a `remove` that landed
   **before the child's `require`** — after it is the written case above — `remove`'s … and a corpus removed
   while a build for it was still resolving its name"*. Worth one more clause, since it is the actual record: a
   `refresh` `call` row that spawned, with no `knowledge_build` row carrying its `op_id` as `spawned_by_op_id`,
   is the signature of a child that died before it held an id — indistinguishable from a dropped row, which
   the paragraph should say.

2. **[IMPROVEMENT] The done-when says the fresh-store fixture is red without `ensure`; as specified, it is
   green either way.** `build-plan.md:4218–4220`: *"a refusal reaching neither an `id` nor a connection writes
   no row at all — that fixture runs on a store no knowledge verb has touched, so it is red if `registry.ensure`
   is missing ahead of the `require` that binds the id"*. With `require` outside the `try`
   (`schema.md:1008–1009`), a missing `ensure` makes `require` raise `aiosqlite.OperationalError: no such
   table: knowledge_bases`; that propagates out of `build()` with no row written — which is exactly what the
   fixture asserts, so it passes. The omission is visible only in *what* was raised: `UnknownKnowledgeBaseError`,
   rendered `refused: no knowledge base named …` by `scope.execute`, against `failed: no such table`
   (`scope.py:128–138`). Separately, *"reaching neither an `id` nor a connection"* reads as "no id and no
   connection", which excludes the very case the fixture drives — an unknown name on an open store has a
   connection and no id. **Change:** *"a refusal raised before an id is bound — with or without a connection —
   writes no row; that fixture runs on a store no knowledge verb has touched **and asserts the refusal is
   `UnknownKnowledgeBaseError`** (`refused:` through `scope.execute`, not `failed: no such table`), which is
   what makes it red if `registry.ensure` is missing ahead of `require` — the no-row assertion alone is
   satisfied by the crash too"*.

3. **[IMPROVEMENT] The build's row is placed on the failure path only, and a non-contention failure of the row
   changes the outcome a landed build reports.** `schema.md:992–996` ¶"The row is written inside `build()`"
   fixes where a *failed* build's row goes; ¶"The build decides by version" (`:1069–1073`) fixes the failure
   map as contention-only, propagating everything else *"as `counters.py`'s is"* (`counters.py:219–228`: swallow
   `is_contention`, re-raise the rest). Nothing says where on the success path the row is attempted relative
   to `_print_report` and `return 0` (`main.py:88–93`), nor what a propagating row failure does to a build whose
   corpus `meta` already records completion: as written, `scope.execute` prints `failed: <driver error>` and
   returns 1 over a built corpus, so a foreground run and the next `knowledge status` disagree — and on the
   failure path the same propagation replaces `refused: a build is already running …` with
   `failed: <driver error>`, chained. This is the class round 2's blocker held `call` to (*"Losing an audit row
   is a measurement gap; corrupting a caller's answer is not"*); the design's stated reason for propagating —
   a `NOT NULL` defect should be loud — argues the other way. Either is defensible and neither is chosen.
   **Change:** one sentence after `:996`: *"On the success path the row is attempted after `_print_report`, so
   the account of the build is printed whatever the row does; a non-contention failure of the row write
   [is printed to stderr and leaves the status 0 | is the build's reported outcome, exit 1, because a row that
   will not write on a store that just accepted a corpus is a defect worth a red exit]"* — pick one — and a
   done-when fixture: *a row write raising a non-contention error after a completed scan leaves the printed
   report and the exit status as stated*.

4. **[NITPICK]** `schema.md:1016–1017`: *"`OpenStore` carries `schema_version` for the version gate. It yields
   the project, directory, connection and config and no `meta`"* — `open_store` yields; `OpenStore` is the
   dataclass it yields (`scope.py:37–53`), and the second sentence is today's code where the first is M33's
   addition. *"`open_store` yields an `OpenStore` of project, directory, connection and config today, and no
   `meta`; at M33 it gains `schema_version`, so …"*.

5. **[NITPICK]** `build-plan.md:4220`'s *"the `require` that binds the id"* has no antecedent in the brief:
   nothing in §M33's `knowledge_build` paragraph (`:3954–3982`) says `build()` resolves the registry row before
   `prepare`, so a builder reading the brief first meets the clause cold. One clause before *"And the build
   decides by version"* at `:3980`: *"`build()` binds the registry id itself — `ensure`, then `require`, outside
   the `try` — so a refusal that reaches no id writes no row and everything after it is written under that id
   (`schema.md` §"What is instrumented")"*.

VERDICT: NEEDS_CHANGES

## Round 11 — 2026-09-28

**Summary judgment.** Round 10's five findings are applied as the brief says, and the two self-found repairs
are right. No blocker. What remains is the consequence of the choice finding 3 asked for and got — *a
non-contention failure of the build's row goes to stderr and leaves status 0* — carried through neither to the
version-gate rationale two paragraphs down, which still rejects catching the constraint *because* it would
hide a `NOT NULL` defect the new rule now hides identically, nor to the failure path, where the natural
placement of the success-path write lands its own failure in the `except Exception` that writes a failure row.
And the "signature" paragraph round 10 asked for overclaims what a `call` row can show: it carries no argument
and no result, so a `refresh` row cannot say it spawned, and the signature is shared by a per-corpus refusal and
an in-flight build as well as the two states named — that suggestion was mine and was wrong on that point.
Verified against `knowledge/scope.py` (`OpenStore`, `open_store`, `execute`), `knowledge/indexer/main.py`
(`build`, `_run`, `_print_report`), `core/knowledge/{registry,builds,lifecycle}.py`, the on-disk `FINDINGS.md`
§"Current state", the archive's Q18 entry, `write-policy.md:536–547`, `architecture.md:1844–1848, 2090–2102`,
`knowledge-index.md:1017–1020, 1341, 1601–1609`, `harness.md:601–619`, `distribution.md:182–200`, and the
existence of every test file the done-when names.

### Findings

1. **[IMPROVEMENT] The version gate's stated reason is now the thing the success-path rule does.**
   `schema.md` ¶"The build decides by version" (`:1087–1089`): *"Catching an `IntegrityError` instead would be a
   net wide enough to swallow a `NOT NULL` defect"*; §"Migration posture" `:1821–1822`: *"rather than writing
   one and catching the constraint, which would be a net wide enough to hide a `NOT NULL` defect"*. Two
   paragraphs up, ¶"On the success path" (`:998–1005`) now has every non-contention failure of the row write —
   an `IntegrityError` from a `NOT NULL` defect included — go to stderr with status 0, and says outright that
   *"the loudness a `NOT NULL` defect deserves comes from the done-when's fixtures and the gate, not from
   failing somebody's build"*. So the document rejects one catch for hiding a defect and adopts a wider one that
   hides it exactly as much, and a reader cannot tell which principle governs. The gate is still right, for a
   reason that survives: under the swallow rule a direct build against a schema-2 store — which a direct run
   never migrates (D37) — would print a `CHECK` failure to stderr on **every** run, reporting an ordinary state
   as a defect, and the version is in hand before the write. **Change:** in both places replace the `NOT NULL`
   clause with *"deciding by version rather than by catching the constraint, because a store below 3 is an
   ordinary state for a direct run and not a failure to print — and now that a failed row write is reported
   rather than raised, a caught `CHECK` would say `could not record build` on every foreground build against
   an unmigrated store"*. Keep *"the failure map stays contention-only"* only if finding 2 keeps the
   asymmetry; otherwise it is a third statement of the same thing.

2. **[IMPROVEMENT] Where each row write sits relative to the `try` is unstated, and the natural placement of
   the success-path write makes its failure write a failure row.** `schema.md:992–996` fixes the failure path
   — *"catching `Exception` at that point, writing the row, and re-raising"* — and `:998–999` puts the success
   write *"after `_print_report`"*. `build()` (`main.py:88–93`) is `prepare`, `refresh`, `_print_report`,
   `return 0`; a builder wrapping that body in `try … except Exception` puts the success write at the end of
   the body, **inside** the `try`. A non-contention failure there then enters the `except`, which writes a
   *second* row — `ok=false`, `error_code='build_failed'` — for a build that completed, and re-raises: status 1,
   `failed: <driver error>` from `scope.execute`, which is the outcome `:1000–1002` forbids, with a false
   failure row on top if the second attempt happens to land. Two consequences follow, and the design chooses
   neither. (a) **The success write must sit after the `try`/`except`, not at the end of its body**, so its
   failure cannot reach the failure-row catch. (b) **On the failure path, what is re-raised when the row write
   itself raises non-contention** is round 10 finding 3's second half, applied only on the success side: as
   written the row failure replaces the original — `refused: a build is already running …` becomes
   `failed: <driver error>` chained, or a bare traceback for a `ValueError`, since `execute` catches neither.
   `:963–965` currently relies on that propagation as the argument for fixing the set's shape (*"nothing would
   catch it — a build would die in a traceback because it tried to record why it failed"*). **Change:** after
   `:996`, *"A failure of that write goes to stderr as on the success path and the original exception is what
   is re-raised: the build's own outcome is the answer, the row is the audit. Nothing raised by either write
   is ever the reason a build reports failure."* — then rewrite `:963–965` to the reason that survives, *"the
   row for the build's own failure would be lost to a `ValueError` on stderr, and the one failure worth
   recording would go unrecorded"*. Or keep the asymmetry and say why a refused build's row failure may replace
   its refusal where a completed build's may not. State (a) either way, and add to the done-when's fixture at
   `build-plan.md:4229–4231` the failure-path twin: *a row write raising after a refused build leaves the
   refusal as the printed outcome and writes no second row*.

3. **[IMPROVEMENT] The signature paragraph claims the `call` row shows a spawn, and it cannot.**
   `schema.md:1038–1041`: *"A `refresh` `call` row that spawned, with no `knowledge_build` row carrying its
   `op_id` as `spawned_by_op_id`, is what a child that died before it held an id looks like — and is exactly
   what a child whose row was dropped under contention looks like too. The log cannot separate them."* `call`
   carries `{method, ok, error_code, duration_ms}` and, by `:806–809`, no argument and no result — so a
   `refresh` row cannot say whether it spawned. The same section (`:1043–1052`) says a per-corpus
   `IndexerBusyError` inside a succeeding `refresh` *"appears in no event at all"* with the row at `ok=true`:
   that row has the same signature and spawned nothing. So does every build still in flight, since the row is
   written at the end, and `knowledge_add` spawns too (`:1043`). A query written from the paragraph counts
   every per-corpus refusal and every running build as a lost child. The same overclaim sits in `:1033–1034`,
   *"the record of such a child is the spawning verb's `call` row — for a `remove` that landed before the
   child's `require`, `remove`'s"*: neither row names the corpus, and `remove` deleted the registry row, so
   after the race nothing in `memory.db` says which corpus this was. This was round 10's own suggested clause
   and it was wrong about what the row holds. **Change:** replace `:1038–1041` with *"The absence of the join
   proves nothing. A `refresh` or `add` `call` row at `ok=true` with no `knowledge_build` row carrying its
   `op_id` is what four states look like — a per-corpus refusal that spawned nothing (below), a build still
   running, a child that died before it held an id, and a row dropped under contention — and the `call` row,
   holding no argument or result, cannot say which. Only the presence of the join is evidence."* And at
   `:1033–1034`, *"the record of such a child is that a build was asked for — the spawning verb's `call` row,
   which names no corpus — and, in the race, a `remove` row near it in time; the operator's own terminal is the
   only record that names it."*

4. **[NITPICK]** `FINDINGS.md:97–99`: *"the access log undercounts under contention; the same applies to
   `knowledge_build`"* — the build's row waits its full `busy_timeout` and drops only after it, an asymmetry
   §"Migration posture" (`:1824–1830`) calls *"the point"*. In the file that loads every session, *"the same
   applies"* invites re-deriving the wrong mechanism. *"`knowledge_build` is best-effort too, on the opposite
   terms — it waits its full `busy_timeout` and drops only after it — and a directly-run indexer declines to
   write it against a store below schema 3 …"*.

5. **[NITPICK]** Done-when `build-plan.md:4229–4231`: *"a row write raising a non-contention error after a
   completed scan leaves the printed report intact and the exit status 0"* — a builder who swallows silently
   passes. Add *"and one line on stderr naming the failure"*, since the line is what keeps the drop from being
   silent.

6. **[NITPICK]** Three under-length lines are ravel remnants of the last edits, where the brief checked only
   for over-length: `schema.md:668–669` (*"envelope and mints its own label;"* alone on a line),
   `:1074` (*"load**, because that is the elapsed cost"*), and `:1085–1087`, where *"It opens through
   `Store.open`, so a build attempts the row only when the store it opened admits the kind"* is also a
   non-sequitur — opening through `Store.open` is not what makes the row conditional; reading
   `schema_version` is. Fold into *"at M33 it gains `schema_version`, from the `meta` `Store.open` validated,
   so a build attempts the row only when the store it opened is at 3 or above and writes nothing below that"*,
   and rewrap the three passages.

VERDICT: NEEDS_CHANGES

## Round 12 — 2026-09-28

**Summary judgment.** Round 11's six findings and the self-found guard are applied as the brief says, and each
holds against the code: the version gate now rests on the reason that survives (`schema.md` ¶"The reason is not
that catching hides a defect", §"Migration posture" ¶"So the indexer can meet a store"), the success write sits
after the `try`/`except` with the failure write inside its own guard and the original re-raised, the symmetric
"no row write is ever the reason" rule is stated once in `schema.md` and once in `FINDINGS.md`, and the
signature paragraph now claims only what a `call` row holds. The withdrawn phrasings are gone from the corpus
— `NOT NULL` defect, *the same applies*, *die in a traceback*, *contention-only*, *failure map*, *superset* all
grep empty across `design/`, `FINDINGS.md` and the archive. No blocker. What remains is small and confined to
the `knowledge_build` cells: one enumeration with a bold count that misses the most ordinary way a build ends
with no row, one test the closed set still lacks to be closed by construction rather than by a list somebody
maintains, and the failure-path twin fixture carrying the gap round 11 closed on the success path. Verified
against `knowledge/indexer/{main,detach}.py`, `knowledge/scope.py`, `core/knowledge/errors.py`, the on-disk
`FINDINGS.md` §"Current state", the archive's Q18 entry, `architecture.md:1844–1848, 2089–2102`,
`knowledge-index.md:1017–1020, 1601–1610`, `harness.md:601–619`, `distribution.md:182–200`,
`write-policy.md:536–547`, `schema.md`'s DDL comment, invariants 10 and 18, the nullability table, and
§§"`call` is an access log", "What is instrumented", "Migration posture" in full.

### Findings

1. **[IMPROVEMENT] The "four states" enumeration misses a child that died with no catch to run, and
   "whatever its outcome" invites the wrong repair.** `schema.md:1047–1052`: *"what **four** states look like:
   a per-corpus refusal that spawned nothing, a build still running …, a child that died before it held an id,
   and a row dropped under contention"*. A child killed mid-scan — the OOM killer on an embedding batch, a
   `SIGTERM`/`SIGKILL` from an operator clearing a stuck build, or a foreground run's Ctrl-C — has the same
   signature and is in none of the four, and it is the ordinary way minutes are lost with no record. The
   mechanism the design fixes cannot see it: `:996–997` catches `Exception`, and `KeyboardInterrupt` and
   `asyncio.CancelledError` are `BaseException`, while a signal's default action runs no handler at all. So
   `:691`'s *"at most one per indexer build, **whatever its outcome** — 'at most' for the same best-effort
   reason as `call`"* attributes every missing row to contention, which is not why these are missing, and a
   builder reading "whatever its outcome" will reach for `except BaseException` to write the row on
   interrupt — which would make Ctrl-C wait up to `busy_timeout` on a lock, the one thing an interrupt must not
   do. **Change:** at `:1047–1049` drop the count — *"is what **at least** these states look like: … and a
   child killed before its catch ran"* — and at `:691` *"whatever outcome its own code reaches — a process
   killed, or a foreground run interrupted, writes none, since `KeyboardInterrupt` and `CancelledError` sit
   outside `except Exception` by design and a row write on interrupt would hold Ctrl-C behind `busy_timeout`"*.
   One clause at `:996–997` saying `Exception` and not `BaseException` is deliberate, so the next reader does
   not "fix" it.

2. **[IMPROVEMENT] `BUILD_ONLY_WIRE_NAMES` is a hand-maintained list, and no stated test makes it complete.**
   `schema.md:972–978` composes `values` as every `ErrorCode.wire_name` plus `BUILD_ONLY_WIRE_NAMES` plus
   `build_failed`; the tests stated (`:944–945`, `:976–978`, `build-plan.md:4232–4234`) are that every mapped
   class's `wire_name` equals its `ErrorCode`'s, and that the build-only names are disjoint from
   `ErrorCode.wire_name`. Neither asserts that **every concrete `KnowledgeError` subclass** lands in one half
   or the other. `errors.py` holds nine today, seven mapped by `_translated` and two build-only; a tenth added
   later, unmapped and forgotten from the export, records a `wire_name` outside `values`, `EventSpec.validate`
   raises inside the failure-path write, the line goes to stderr, and the build's own failure goes unrecorded —
   exactly the outcome `:963–966` calls *"worse than"* a crash, and the class round 7's blocker was about one
   level up. The design's *"declared, not walked over `__subclasses__()`"* rule (`:972`) is about composing
   `values` in `core/`, and a **test** walking the tree is the opposite case — it sits above the layers and
   controls its own imports. **Change:** add to `:976–978` and to the done-when at `:4232–4234`: *"and a test
   holds that every concrete `KnowledgeError` subclass's `wire_name` is in `knowledge_build.error_code`'s
   `values` — walked over `__subclasses__()` in the test, where import order is the test's own — so a class
   the boundary does not map and the export forgot is red rather than a stderr line on the build that
   needed it"*.

3. **[IMPROVEMENT] The failure-path twin fixture passes on a silent swallow, and "no second row" is
   vacuous there.** `build-plan.md:4231–4232`: *"its failure-path twin leaves a refused build's refusal as the
   printed outcome and writes no second row"*. `schema.md:1007–1008` says a non-contention failure of
   **either** write goes to stderr; the success-path fixture asserts *"one line on stderr naming the failure,
   so a silent swallow does not pass"* (round 11 #5), and the twin does not — a guard that catches and says
   nothing satisfies it. And on the failure path there is no first row for a second to follow: the write
   raised, so the store holds **no** row for that build; "no second row" was the success-path hazard carried
   over. **Change:** *"its failure-path twin leaves a refused build's refusal as the printed outcome — the
   original exception re-raised, not the row's, so `scope.execute` still renders `refused:` — writes **no**
   row, and prints the same one line on stderr"*.

4. **[IMPROVEMENT] "The operator's own terminal is the only record that names it" is false for the case the
   paragraph is about.** `schema.md:1040–1045`: for a child refused before `require` after a `remove` landed,
   *"the operator's own terminal is the only record that names it"*. The race is between an agent's `refresh`
   and a `remove`, so the child is **detached**, and `detach.spawn` (`detach.py:73–75`) opens it with
   `stderr=DEVNULL` — its `refused: no knowledge base named …` goes nowhere. The name existed once, in the
   `refresh` result's `foreground_command` the agent received (`knowledge-index.md:1601–1605`), which is in a
   context window and on no disk. Only a *foreground* run has a terminal. **Change:** *"For a foreground run
   the operator's terminal names it; for a spawned child nothing durable does — its stderr is `DEVNULL` by
   `detach`'s design, and the name was last seen in the `refresh` result's `foreground_command`, in the
   caller's context and nowhere on disk."* This is the honest statement of what the log cannot give, in the
   direction the paragraph exists to state.

5. **[NITPICK]** `build-plan.md:4221` *"**`knowledge_build` is exercised five ways**"* — the list that follows
   has seven clauses by its own semicolons (schema-2; refused child / no-id refusal; two spawns; held lock;
   row-write failure and its twin; `wire_name` agreement and disjointness; `index_failed`), and finding 2 adds
   one. A stale count in the builder's contract is the class this corpus has a rule for. *"is exercised as
   follows"*.

6. **[NITPICK]** `schema.md:1011` *"That is round 2's trade for `call`"* — a review-round reference inside a
   normative document, which `CLAUDE.md` §"Project memory" sends nowhere; a reader of `schema.md` has no round
   2 to consult, and the trade is already stated as a rule at `build-plan.md:4091–4092`. *"That is the trade
   `call` already takes — …"*.

7. **[NITPICK]** `schema.md:667–670`: round 11's ravel remnant moved one line rather than closing —
   `:669` is *"rather than assumed (§"Linked sessions" below). It"* at ~50 characters, followed by a
   ~113-character line. Rewrap `:667–671` as one run.

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-09-28

**Summary judgment.** Round 12's seven findings are applied as the brief says and each holds against the
code: the killed child is in the enumeration and the `Exception`-not-`BaseException` clause sits at the
catch (`scope.execute` runs under `asyncio.run`, so a Ctrl-C arrives in `build()` as `CancelledError`,
which is what the clause names); the completeness test is stated in both documents and the done-when;
the twin fixture asserts no row, the original exception and the stderr line; the terminal sentence is
scoped to foreground runs, which `detach.spawn`'s `stderr=DEVNULL` makes true. No blocker. The tree moved
under this review — `build-plan.md` gained the *transitively* clause between two reads, so line numbers
are as read on the second pass and the bold lead-ins are the durable citation. What remains is three
things a builder or a query author would get wrong from the text as it stands: a factual error about
which pre-dispatch exits carry protocol codes, an unstated precondition on test (ii) that is the mirror
of the one the no-id fixture states — and which, unstated, makes the natural fixture red for the reason
the same sentence says proves nothing — and the completeness test's dependence on *which* modules are
imported, which is the hole the transitive clause just closed on the other axis. Verified against
`service/{server,envelope,rpc,dispatch_knowledge}.py`, `core/knowledge/{reporting,registry,errors}.py`,
`core/store/transactions.py`, `knowledge/{scope,indexer/main,indexer/detach}.py`, `core/events.py`, the
on-disk `FINDINGS.md` §"Current state", the archive's Q18 entry, `architecture.md:1844–1848, 2089–2102`,
`knowledge-index.md:1013–1020, 1601–1612`, `harness.md:601–619`, `distribution.md:182–200`,
`write-policy.md:536–547`, `schema.md`'s DDL comment, invariants 10 and 18, the nullability table,
§Retention, §"Migration posture", and §§"`call` is an access log" and "What is instrumented" in full.

### Findings

1. **[IMPROVEMENT] "The first and third exits take four of `ProtocolErrorCode`'s five members" names
   the wrong two exits.** `build-plan.md:4122–4123` ¶"A consequence worth stating". In the list at
   `:4109–4120` the first exit, `health`, answers a **result** and no error code at all
   (`server.py:110–112`); the third, a malformed envelope, answers a `ZikaronError` from
   `_resolved_envelope` (`server.py:115–121`), whose `code` is a domain `ErrorCode` — `envelope.py`
   imports `ErrorCode` and nothing from `rpc`. The four protocol members are taken by the **second**
   exit (`parse_request`'s three, `server.py:164–170`) and the **fourth** (`METHOD_NOT_FOUND`,
   `:124–130`). The conclusion — `internal_error` alone is reachable — is unaffected, but the sentence
   is the one a query author reads to learn what `health` and an envelope refusal answer, and it says
   both answer protocol codes. **Change:** *"because the second and fourth exits take four of
   `ProtocolErrorCode`'s five members"*. `schema.md:836–839` states the same conclusion without the
   ordinal and is correct.

2. **[IMPROVEMENT] Test (ii) has an unstated precondition, the mirror of the one the no-id fixture
   states, and without it the natural fixture is red for exactly the reason the sentence says proves
   nothing.** `build-plan.md:4279–4282`: *"(ii) a dispatched `knowledge_list` under that same held-lock
   fixture answers with the byte-identical line … it needs no seam and no stub, because `knowledge_list`
   takes no write lock of its own"*. `knowledge_list` → `reporting.list_bases` (`reporting.py:408–411`)
   → `registry.ensure(db)` → `in_one_transaction(ensure_table)` under a deferred `BEGIN`
   (`transactions.py:167`). Against an **existing** table that is a schema read, which is
   `ensure_table`'s measurement (`registry.py:108–111`) and what `schema.md:861–862` cites — *"against an
   existing table"*. On a store where `knowledge_bases` does not yet exist the `CREATE TABLE` runs, takes
   the write lock, and under the held-lock fixture waits `BUSY_TIMEOUT_MS` and fails **in the handler** —
   the memory-verb position `:4283–4286` says a held-lock test proves nothing about. `ensure_table`'s own
   docstring names it: *"the one occasion it contends is the one occasion it has real work to do"*. The
   no-id fixture two clauses earlier (`:4227`) requires *"a store no knowledge verb has touched"*; (ii)
   requires the opposite and does not say so, and a builder sharing one store between them gets one of
   the two wrong. **Change:** at (ii), *"on a store whose `knowledge_bases` table already exists — one
   knowledge verb run before the lock is taken — because `registry.ensure`'s `CREATE TABLE IF NOT EXISTS`
   is a schema read only against an existing table and takes the write lock on the one call that
   creates it"*. In `schema.md:859–864`'s bullet, add the same qualification: *"on a store whose registry
   table exists; the first knowledge verb on a fresh store creates it, and for that one call sits with
   the memory verbs"*. `build-plan.md:4078–4081` restates the five-verb claim and needs the clause too.

3. **[IMPROVEMENT] The completeness test's walk depends on which modules are imported, and the
   precondition is unstated — the same hole the transitive clause just closed, one axis over.**
   `schema.md:980–990` and `build-plan.md:4237–4241`: *"walked over `__subclasses__()` transitively and
   in the test, where import order is the test's own"*. What `__subclasses__()` can see is not a matter
   of order but of **which modules have been imported**: a `KnowledgeError` subclass declared outside
   `core/knowledge/errors.py` — in `scan.py` or `lock.py`, say, beside the code that raises it — and
   imported by nothing the test imports is invisible to the walk, and the test is green while the export
   is incomplete. The transitive clause was added because *"an intermediate base added later would hide
   its children from the one test that exists to catch a class nobody registered"*; a module nobody
   imports hides them the same way. **Change:** state that the test imports every module under
   `zikaron/` before it walks — `pkgutil.walk_packages` over the package, which a test may do and
   production must not — so a subclass declared anywhere is seen; and replace *"where import order is the
   test's own"* with *"where what is imported is the test's own"*, since order was never the dependency.
   Asserting instead that every walked class's `__module__` is `errors.py` cannot close it, because an
   un-imported class is not walked to be asserted about.

4. **[NITPICK]** `build-plan.md:4043` *"since the exits above decide every other protocol code before
   dispatch"* — the exits are enumerated in §"The classes of call the log does not cover" at `:4103`,
   below. *"the exits enumerated below"*. The brief reports every direction reference in both sections
   verified; this one points the wrong way.

5. **[NITPICK]** Over-length lines in the edited ranges, where the brief reports the class closed against
   the file's p90 of 110: `build-plan.md:4237` (the fresh *transitively* clause, ~120 characters),
   `:4277` and `:4298` (~130 and ~125, both in the done-when, pre-existing), and `schema.md:1304`
   (~170 characters, in §Retention, which M33 edited at `:1296–1301`). Rewrap all four.

6. **[NITPICK]** `build-plan.md:3927–3929` *"Claude Code accepts `tools:` as a block list and as a
   comma-separated inline string, so both forms have to resolve"* — a YAML flow sequence,
   `tools: [Read, mcp__zikaron]`, is a third spelling any YAML parser accepts, and a scanner treating the
   value as a comma-separated string yields `[Read` and `mcp__zikaron]`, matches neither, and names an
   agent that is fine — the direction the paragraph says costs most. Either strip enclosing brackets
   from the inline form, or measure once whether Claude Code's frontmatter parser accepts it and say the
   form is excluded. One clause either way; `harness.md:605–607` carries the parsing rule and takes the
   same clause.

7. **[NITPICK]** `FINDINGS.md:120–123` *"The install will name such agents and edit none of them"* —
   `zikaron doctor` runs the same scan and `build-plan.md:3909–3911` says that is *"where it earns most of
   its keep"*, since the next blind agent is authored after the install. The file that loads every
   session names only the install. *"The install and `zikaron doctor` will name such agents"*.

VERDICT: NEEDS_CHANGES

## Round 14 — 2026-09-28

**Summary judgment.** Round 13's seven findings are applied as the brief says and each holds against the
code: `health` answers `encode_result` (`server.py:110–112`) and `envelope.py` imports `ErrorCode` and
nothing from `rpc`, so *second and fourth* is right; `reporting.list_bases` opens with `registry.ensure`
(`reporting.py:410`) and test (ii)'s precondition is now stated on both sides; the completeness test
imports before it walks; the directional reference, the flow-sequence spelling, the `doctor` mention and
the rewraps are in place. No blocker. What this round found is in places no earlier round looked: a
stated property of `client_kind='indexer'` that the envelope parser will silently falsify the day the
enum gains the member, a test specification that executes three CLI entry points on import as written,
a measurement with no bar it can fail, and a "migration test" the done-when leans on twice that does not
exist in `tests/`. Verified against `service/{server,envelope,rpc,dispatch,dispatch_knowledge}.py`,
`core/{events,errors}.py`, `core/knowledge/{errors,registry,builds,lifecycle,scan,reporting}.py`,
`core/store/{transactions,connection,ddl,store}.py`, `knowledge/{scope,indexer/main,indexer/detach}.py`,
every `__main__.py` under `zikaron/`, `tests/{test_event_kinds,test_service_envelope,
test_store_migration,test_knowledge_counters}.py`, `spikes/m31_check_widening.py`'s existence, the
on-disk `FINDINGS.md` §"Current state", the archive's Q18 entry, and every named passage of the seven
documents.

### Findings

1. **[IMPROVEMENT] `client_kind = 'indexer'` "exists for it alone", and nothing in the design stops a
   client sending it.** `schema.md:939`, and the reasoning built on it — the indexer *"enters neither
   side"* of linkage (`:1178–1179`), the drop-rate query *excludes* `client_kind='indexer'` (`:690`),
   the `label_source` population is taken over `('hook','mcp')` because a build *"mints by
   construction"* (`:1180–1183`). `envelope.py:33` derives the wire's accepted set from the enum —
   `_KNOWN_CLIENT_KINDS = frozenset(str(kind) for kind in ClientKind)` — and `parse_envelope`
   (`:113–115`) accepts any member. The day `ClientKind.INDEXER` lands, a client sending
   `client: {kind: "indexer", …}` is accepted, and every semantic event and every `call` row it causes
   is filed under the kind the design reserves for a spawned build: a `memory_remember` that the
   drop-rate query then excludes, a session that linkage ignores, and a `bounds` payload whose `limit`
   advertises `indexer` as a value to send (`:115`, `sorted(_KNOWN_CLIENT_KINDS)`).
   `tests/test_service_envelope.py:62–65` refuses `"primary-agent"` and would stay green. Nothing
   malicious is needed — a client author reading the `CHECK` would take it as the wire set.
   **Change:** in `schema.md` §"What is instrumented" after `:939`, *"— and the wire refuses it:
   the envelope's accepted kinds are `ClientKind` minus `INDEXER`, declared once beside the enum (a
   `WIRE_CLIENT_KINDS` export, say) and read by `parse_envelope`, so the `CHECK` admits one value more
   than any request may carry. A test sends `kind: "indexer"` and asserts `bounds` on `client.kind`
   with a `limit` that does not list it."* Add the test to the done-when beside the `ClientKind`
   docstring item, and one clause at `build-plan.md:3946–3948`.

2. **[IMPROVEMENT] "Imports every module under `zikaron/`" executes three entry points as written, and
   the walk's default swallows the failure the clause exists to catch.** `schema.md:987–991` and
   `build-plan.md:4244–4246` specify `pkgutil.walk_packages` over the package followed by an import of
   every name. `walk_packages` yields `__main__` submodules, and three of the four call the program
   unconditionally at import: `install/__main__.py:18`, `knowledge/__main__.py:17` and
   `knowledge/indexer/__main__.py:17` are each a bare `sys.exit(main())` — under pytest's `argv` that
   is an argparse `SystemExit(2)` from inside `import_module`, and for the indexer a `scope.execute`
   attempted first. Only `project/__main__.py:7–8` is guarded. Separately, `walk_packages`'s documented
   default — *"if no `onerror` function is supplied, `ImportError`s are caught and ignored"* — means a
   package that fails to import is skipped silently, which leaves the walk green over exactly the
   un-imported classes the clause was added to see. **Change:** at both sites, *"every module but the
   `__main__` entry points, which run the program at import, with `onerror` set to raise so a package
   that will not import is red rather than skipped"*. The `__main__` modules define no classes, so
   excluding them loses nothing.

3. **[IMPROVEMENT] The A/B is specified with no bound it can fail.** `build-plan.md:4303–4306`: *"the
   added write's cost is measured against a control idle and under a writer interleaving short
   transactions at a stated rate, the idle delta being what every push pays, and recorded in
   `research/`"*; `schema.md:924–927` likewise. That is a measurement, not a criterion: whatever the
   number is, the done-when is satisfied by writing it down. This project's own precedent is the other
   way — M26 preregistered its bar and shipped nothing when it was not cleared, and M30 moved a check
   off the start path on a measured overrun of `push._DEADLINE_SECONDS`. The placement decision here
   (row on the response path, before the line is returned) is exactly the kind a number should be able
   to reverse. **Change:** preregister, in the done-when, before the run: an idle per-call delta bound
   at p50 and p95 (the design's own claim is *one WAL append, no `fsync`* — say what that is worth in
   milliseconds on this machine, and hold it to that); under the interleaving writer, `memory_surface`'s
   p95 inside `push._DEADLINE_SECONDS` wherever the control's is, with `N` transactions per second
   stated; and the consequence of a miss — the write moves after `writer.drain()`, or the private
   connection's pragmas are revisited — so the measurement decides something.

4. **[IMPROVEMENT] "The migrated snapshot the migration test already uses" names a test that does not
   exist, and the gate cannot run the one described.** `build-plan.md:3844` and `:4284–4285` both defer
   to it; the done-when at `:4228–4230` says the migration *"is exercised against a `VACUUM INTO`
   snapshot of `~/Trading/LeibaTrader`"*. No file in `tests/` mentions `LeibaTrader` or `VACUUM INTO`;
   `tests/test_store_migration.py:80–103` builds a **synthetic** version-1 store in `tmp_path` and
   migrates that, and M31's snapshot run was `spikes/m31_check_widening.py` — a spike, which
   `FINDINGS.md` cites as the re-derivation. The gate is hermetic by rule, so a test that opens a store
   under the operator's home directory is either `manual`-marked or a spike; the done-when says neither,
   and a builder meets the sentence with nothing to point it at. **Change:** at `:4228–4230`, *"the
   2→3 step is covered hermetically by `test_store_migration.py`'s synthetic store, and exercised once
   against a `VACUUM INTO` snapshot of `~/Trading/LeibaTrader` by a re-run of
   `spikes/m31_check_widening.py` extended to 3, its `integrity_check` and timing recorded in
   `research/`"*; at `:3844`, `:4284–4285` and `schema.md:1307–1310`, *"the snapshot that spike uses"*.

5. **[NITPICK]** `schema.md:929–931`: *"A `STORE_BUSY` refusal is the **systematic** case — the store that
   refused the mutation refuses the row recording it"*. The handler's `busy_timeout` expired 5 s into the
   contention; nothing says the lock is still held when the row is attempted moments later, and a
   `store_busy` row that *does* land is ordinary. *"the likeliest case"* — a query author reading
   "systematic" would conclude the value never appears.

6. **[NITPICK]** One post-dispatch exit is unnamed: `encode_result` raising inside the result branch
   (`server.py:134–136`) leaves no line assigned, so under encode-before-write no row is attempted, and
   `_handle_line`'s outer guard (`:173–185`) answers `internal_error` — a dispatched call with no `call`
   row, answered with the one code the design says means *a handler crashed*. Rare and a service defect,
   but `schema.md:876–881` describes the three branches as exhaustive. One clause: accept it as an
   unlogged exit, or have the branch assign an `internal_error` line and write the row.

7. **[NITPICK]** The unparseable-line row (`schema.md:832`, `build-plan.md:4116–4117`) names
   `parse_request`'s three codes; `server.py:165–166` answers `PARSE_ERROR` for a line that is not UTF-8
   *before* `parse_request` runs. Same class, same code, but the done-when's *"every exit ahead of
   dispatch produces none"* test is driven from that row. Add *"or a line that is not UTF-8"*.

8. **[NITPICK]** `build-plan.md:3952–3955` files *"the note that `'cli'` records no event"* under
   *"`core/events.py`'s `ClientKind` docstring"*, and the done-when (`:4259–4261`) names only the
   docstring. That note is the **member's** attribute comment, `events.py:71–73` — *"It records no event
   today — no knowledge method does"* — a separate sentence a builder editing the docstring at `:53–54`
   will not see. Name `ClientKind.CLI`'s comment.

9. **[NITPICK]** `harness.md:605` and `build-plan.md:3926–3927`: *"only the block between the first `---`
   and the next `---` may be parsed"*. Frontmatter exists only when the file **begins** with `---`; a
   file with no frontmatter and two horizontal rules in its body would otherwise have prose parsed as
   YAML. One clause: *"and only when the file opens with one — a file that does not has no `tools:` and
   inherits everything"*.

10. **[NITPICK]** Two lines over the p90 remain inside M33's edited ranges, where the brief reports the
    class closed: `build-plan.md:4046` (121 characters — the line round 13 #4's edit landed on) and
    `:4296` (115, in the done-when). Rewrap both.

VERDICT: NEEDS_CHANGES

## Round 15 — 2026-09-28

**Summary judgment.** Round 14's ten findings are applied as the brief says and each holds against the
code: `envelope.py:33` derives the wire set from the enum, so *`ClientKind` minus `INDEXER`* is the right
cut; `install`, `knowledge` and `knowledge/indexer` `__main__` are each a bare `sys.exit(main())` and
`project/__main__` is guarded, so the exclusion is exactly three; nothing in `tests/` names the
snapshot and `test_store_migration.py:80–103` is synthetic; the bar is preregistered with a consequence.
No round has yet looked at the drift guard that binds `EVENT_SPECS` to the per-kind table, and it
refuses the `error_code` mechanism this trail spent rounds 3, 5 and 7 settling — on both of the ways a
builder could implement it — while the design names neither the guard nor a change to it. That is the
one blocker. The rest is a closed-set claim about `method` the same guard makes unimplementable, a
drop-rate denominator that counts rows where it means calls, and four small items. The tree moved
between two reads of `build-plan.md` — a stray `**` at `:4257` on the first read was gone on the second
— so the done-when is judged as last read, where its bold count is even. Verified against
`tests/test_event_kinds.py`, `tests/design_tables.py`, `core/events.py`, `core/errors.py`,
`service/{rpc,server,envelope}.py`, `core/records/memory.py` (`log_event`, `CallParams`), all four
`__main__` modules, `tests/{test_store_migration,test_service_envelope,test_markdown_renders_as_written}.py`,
`spikes/m31_check_widening.py`'s existence, the on-disk `FINDINGS.md` §"Current state", the archive's
Q18 entry, and every named passage of the seven documents.

### Findings

1. **[BLOCKER] The guard that binds `EVENT_SPECS` to the per-kind table refuses `error_code`'s closed
   set on both branches, and the design does not mention it.** `schema.md:690–691` and `:811–821`,
   `build-plan.md:4058–4066` and the done-when at `:4231–4234` fix the mechanism: `values` is
   `tuple(code.wire_name for code in ErrorCode) + ('internal_error',)` for `call`, and every
   `ErrorCode.wire_name` plus `BUILD_ONLY_WIRE_NAMES` plus `build_failed` for `knowledge_build`, both
   `nullable=True`. `tests/test_event_kinds.py::test_detail_value_sets_match_the_design_table`
   (`:109–128`) asserts, for every field of every kind's table row, `declared.values == expected`, where
   `expected` is what the cell states — inside the group after a colon, or beside it as `` `name ∈ a | b` ``
   (`design_tables.py:274–318`) — and **`()` when it states neither**. Neither row states a set for
   `error_code`, so the guard asserts `values == ()` against the composed tuple and is red. The only way
   to satisfy it as written is to spell the set in the cell: `ErrorCode` has **24** members
   (`errors.py:45–68`), so that is 25 literals in one cell for `call` and more for the build — the
   restated-enumeration class this corpus has a rule against — and then
   `test_the_closed_sets_are_enums_carrying_exactly_the_designs_values` (`:180–197`) is red instead,
   because its dictionary is exactly six enum-backed sets and its docstring's rule — *every closed
   detail set is an enum* — is the one the design deliberately breaks with a string tuple. So the
   done-when's *`./check.sh` … green* cannot be met by any implementation of the text, and the nearest
   repair a builder reaches for is dropping `values` — round 5's withdrawn mechanism, silently green.
   **Change:** decide and state, in `schema.md` §"`call` is an access log" beside the *one literal is
   not a restated enumeration* paragraph, and in the done-when. The option that keeps the table the one
   declaration: extend `parse_payload`'s beside-the-group form to accept a **reference** — the `call`
   cell carries `` `error_code ∈ ErrorCode.wire_name | 'internal_error'` `` and the build's
   `` `error_code ∈ ErrorCode.wire_name | BUILD_ONLY_WIRE_NAMES | 'build_failed'` `` — resolved by the
   guard, which may import both layers on the design's own argument for the `internal_error` test; and
   widen `test_the_closed_sets_are_enums…`'s dictionary and docstring to *an enum, or a tuple composed
   from one*. The fallback: exempt the two fields by name in the first guard, with the composition
   checked by the tests already named. Either way, say which tests in `test_event_kinds.py` move —
   `FINDINGS.md:79–83` attributes that file's redness to the `ClientKind` `CHECK` alone, and a builder
   meeting two causes under one explanation fixes one and stops.

2. **[IMPROVEMENT] `method` is described as a closed set the spec validates, and the same guard makes
   that unimplementable without restating `_METHODS` in `core/`.** `schema.md:834` — *"the method name is
   outside this kind's closed set"* — and `build-plan.md:4129–4131` — *"outside the closed set the spec
   validates"*. `_METHODS` is `service/server.py:34–38`; `core/events.py` cannot import it; the table
   states no set for `method`; and finding 1's guard would demand the 19 names inline if `values` were
   declared. A builder either restates them in `core/` or ships a free string against text that says
   otherwise. **Change:** state that `method` carries no `values` in `EVENT_SPECS` and is closed by
   construction at its only call site — `request.method` is a `_METHODS` key by the time a row is
   attempted, since the unknown-method exit precedes it — and reword both passages: *"the method name is
   not in `_METHODS`, so nothing was dispatched, and the wire already answers `METHOD_NOT_FOUND`"*.

3. **[IMPROVEMENT] The drop-rate query counts rows where it means calls.** `schema.md:690` and
   `build-plan.md:4316–4318`: *"a semantic row whose `op_id` carries no `call` row is a dropped row and
   the drop rate is one query"*. A push writes six semantic rows under one `op_id` (`surface_call` plus
   five `surface`), a `fetch` of *n* uuids *n*, a `merge` *n*+1 — so a dropped push counts six times a
   dropped `remember`, and the "rate" moves with the mix of verbs rather than with the drop. **Change:**
   *"the rate is over **distinct `op_id`s** — those with a semantic row and no `call` row, over those
   with a semantic row — bounded as stated"*, in both places.

4. **[NITPICK]** `FINDINGS.md:97–98`: *"a `STORE_BUSY` refusal cannot be logged into the store that
   refused it"* — an absolute that `schema.md:933–937` now disclaims (*likeliest*; *"not a guarantee that
   the value never appears"*), in the file that loads every session. *"is the refusal likeliest to go
   unlogged"*.

5. **[NITPICK]** The miss contingency at `build-plan.md:4324–4325` — *"moves the write after
   `writer.drain()`"* — puts it outside the `ActivityTracker` bracket, which closes in
   `_dispatch_request` (`server.py:98–102`) before `_handle_connection` drains; idle self-stop could then
   fire between response and row, the race round 1's own clause named. One clause: *"still inside the
   activity bracket, which widens to cover the drain"*.

6. **[NITPICK]** The typed detail classes are unnamed. `log_event` takes an `EventDetail`
   (`memory.py:220–226`), `events.py:413–417` says a new kind cannot be logged until its type exists, and
   `test_every_kind_has_exactly_one_typed_value` and `test_every_typed_detail_matches_its_kinds_declared_fields`
   (`test_event_kinds.py:314–381, 401`) hand-build one of each. Name `CallDetail` and
   `KnowledgeBuildDetail` in the done-when's `EVENT_SPECS` clause, and say `CallDetail`'s construction is
   where the `ErrorCode | ProtocolErrorCode -> str` converter lives, so *"typed at the call site"* has a
   site.

7. **[NITPICK]** `core/events.py:63–65` (`ClientKind`'s docstring): *"`test_ddl.py` asserts the `CHECK`
   lists exactly this enum"* — it is `test_event_kinds.py::test_client_kinds_match_the_event_table_check_constraint`
   (`:433–445`) today. The done-when (`:4271–4273`) rewrites that docstring; correct the attribution in
   the same edit rather than leaving a second stale sentence in a paragraph being fixed.

8. **[NITPICK]** *"against a bar preregistered before the run"* (`build-plan.md:4321`) says when and not
   where. A bar is only verifiably prior if it is written in the `research/` note above the results with
   its date; one clause.

VERDICT: NEEDS_CHANGES

## Round 16 — 2026-09-28

**Summary judgment.** Round 15's blocker is closed with the right option, and the reasoning for rejecting
the exemption — two fields nothing compares to the table — is the guard's own. The other seven findings are
applied as the brief says, and each holds against the code: `method` closed by construction at the seam,
the drop rate over distinct `op_id`s in both places, the softened absolute in `FINDINGS.md`, the activity
bracket widened to the drain, `CallDetail`/`KnowledgeBuildDetail` named with the converter's site, the
`ClientKind` docstring's misattribution folded into the same edit, and the bar dated above the results. No
blocker. What this round found is one level below where round 15 looked: the beside-the-group form the
design extends **already has a grammar** — a bare token is a literal — pinned by `test_design_tables.py`
and relied on by three rows of `architecture.md`'s error table through the *same* `parse_payload`, and the
design's two cells invert it (references bare, the literal quoted) without saying so or saying where
resolution happens. And one sentence in the brief was falsified by this round's own `FINDINGS.md` fix.
Verified against `tests/design_tables.py` (`literal`, `_parse_alternatives`, `_STATED_SET`,
`_with_stated_sets`), `tests/test_design_tables.py`, `tests/test_error_codes.py`, `tests/test_event_kinds.py`,
`core/errors.py`, `core/events.py`, `service/rpc.py`, `core/knowledge/__init__.py` and `errors.py`'s import
lines, the DDL block, invariants 10 and 18, the nullability table, §Retention, §"Migration posture", the
on-disk `FINDINGS.md` §"Current state", the archive's Q18 entry, and every named passage of the other six
documents.

### Findings

1. **[IMPROVEMENT] The reference form inverts the beside-the-group grammar the shared parser already
   has, and the design does not say which token is a reference or where it is resolved.**
   `schema.md:829–835` ¶"And the table states that set by reference", the `:690`/`:691` cells, and
   `build-plan.md:4058–4066` give the two spellings — `` `error_code ∈ ErrorCode.wire_name | 'internal_error'` ``
   and `` `error_code ∈ ErrorCode.wire_name | BUILD_ONLY_WIRE_NAMES | 'build_failed'` `` — with the
   references bare and the literal quoted. But the beside-the-group form is not new and not
   `schema.md`'s alone: `architecture.md:1986, 1993, 1996` write `state ∈ superseded \| retired`,
   `reason ∈ not_authorized \| not_targetable` and `stage ∈ budget \| assembly \| embed \| index_write`
   with **bare tokens as literals**; `tests/test_design_tables.py:200–202` pins exactly that
   (`values == ("not_authorized", "not_targetable")`); and `tests/test_error_codes.py:71–76, 79–98`
   compare those rows to `ERROR_SPECS` through the same `parse_payload`. So a builder who reads
   `schema.md` and implements *bare after `∈` = reference* reddens four rows of the error table and a
   parser unit test, and one who keeps *bare = literal* cannot resolve either cell. Two more things the
   text leaves to the code: `literal()` (`design_tables.py:207–209`) strips `*` and backticks and **keeps
   single quotes**, so `'internal_error'` reaches `_with_stated_sets` (`:298–318`) as `'internal_error'`
   with its quotes — the `_QUOTED` strip at `:261` runs only for the in-group form — and
   `design_tables.py` is imported by **18** test modules, so a resolver that imports
   `zikaron.core.knowledge.errors` *there* turns one broken import into 18 modules failing at collection.
   **Change**, in the `schema.md` paragraph and the build-plan bullet: (a) state the grammar of the beside
   form once — *a `'quoted'` token is a literal, as inside the group; a bare token is a literal, as
   `architecture.md`'s error table has always written them; a token that contains a `.` or is written in
   SCREAMING_CASE is a **reference** — `Enum.attr` maps the attribute over the enum's members in order, a
   bare `NAME` is a module-level export* — or, if that rule is judged too implicit, mark references with a
   sigil no existing cell uses and change both cells to match; (b) state that `parse_payload` returns a
   reference **unresolved** and package-free, and that `test_event_kinds.py` resolves it through a mapping it
   builds itself (`{"ErrorCode.wire_name": …, "BUILD_ONLY_WIRE_NAMES": …}`), raising `DesignTableError` on a
   name outside the mapping so a typo fails closed rather than surviving as a literal string that merely
   compares unequal; (c) add to the done-when that `test_design_tables.py` gains one case per token shape —
   a quoted literal beside the group, a resolved reference, an unknown reference refused — since that
   module's docstring is that a malformed input is tested without a malformed document on disk.

2. **[IMPROVEMENT] The brief now asserts a `FINDINGS.md` defect this round fixed.**
   `build-plan.md:4064–4066`: *"Both tests move, and `FINDINGS.md`'s note that `test_event_kinds.py` is red
   on this tree names only the `ClientKind` `CHECK` — a builder meeting two causes under one explanation
   fixes one and stops."* `FINDINGS.md:81–85` now names both causes, in this round's own edit, so the
   sentence is false in the document a builder reads first and sends them to check a note that is already
   correct. **Change:** *"Both tests move, and `FINDINGS.md`'s note on why `test_event_kinds.py` is red on
   this tree names this as the second cause beside the `ClientKind` `CHECK`, because a builder meeting two
   causes under one explanation fixes one and stops."*

3. **[NITPICK]** `build-plan.md:4060` *"spelling 24 `ErrorCode` members plus a literal into the cell"* —
   the brief reports this count replaced by *"every `ErrorCode` member"*; it was, in `schema.md:826`, and
   not here. The restated-count class, in the brief's own bullet.

4. **[NITPICK]** `schema.md:828` *"`test_the_closed_sets_are_enums_carrying_exactly_the_designs_values`,
   whose dictionary is six enum-backed sets"* — a count the design's own change makes false the day it
   lands, since the same paragraph adds two entries. *"whose dictionary today holds only enum-backed sets"*.

5. **[NITPICK]** Both cells carry a backticked `` `nullable=True` `` beside the reference, which reads as
   a parsed token. The beside form has no `null` alternative — `_with_stated_sets` (`design_tables.py:314`)
   copies `nullable` from the in-group field, which is bare here — so nullability for both fields comes
   from the nullability table alone (`:768–769`), which is where `test_nullable_detail_fields_match_the_design_table`
   reads it. Either unbacktick it as prose or say *"nullable per the table below"*, so nobody writes
   `| null` into a reference span expecting it to parse.

6. **[NITPICK]** `ErrorCode` is an `IntEnum` (`core/errors.py:42`), and `EventSpec.validate` checks
   `str(value) not in field.values` (`core/events.py:210`) — so the interchangeability every other closed set
   enjoys (`test_an_enum_member_and_its_plain_value_are_interchangeable`) does not hold for `error_code`:
   `str(ErrorCode.BOUNDS)` is `'-32005'`, and a `CallDetail` typed to hold the member would have every
   refusal's row refused inside the guarded write and dropped with one log line. The design's converter
   already answers this; say in the done-when's `CallDetail` clause that its `error_code` is `str | None`
   holding the converter's output and never a member, for that reason.

VERDICT: NEEDS_CHANGES

## Round 17 — 2026-09-28

**Summary judgment.** Round 16's six findings are applied as the brief says, and the `@` sigil is the
right cut: `design_tables._STATED_SET` (`[^`]+` after `∈`) and `literal()` (strips `*` and backticks only)
pass `@ErrorCode.wire_name` through unchanged, so the parser already returns the two cells as
`("@ErrorCode.wire_name", "internal_error")` and `("@ErrorCode.wire_name", "@BUILD_ONLY_WIRE_NAMES",
"build_failed")` with no code change — "returns a reference unresolved" is true of the tree as it stands,
and `architecture.md:1986, 1993, 1996`'s bare-token rows keep their meaning under `test_design_tables.py:200–202`.
`ErrorCode` is an `IntEnum` (`errors.py:42`) and `validate` tests `str(value)` (`events.py:210`), so the
`str | None` rule in the done-when is the right one. The self-found bullet swap and the rejected-exemption
paragraph both read correctly now. No blocker. One thing a builder cannot resolve from the text: the
mechanism paragraph puts resolution in `test_event_kinds.py`, the done-when puts two resolution tests in
`test_design_tables.py`, and only one placement satisfies both. Verified against `tests/design_tables.py`,
`tests/test_design_tables.py`, `tests/test_event_kinds.py`, `tests/test_error_codes.py`, `core/errors.py`,
`core/events.py`, `service/rpc.py`, the `design_tables` importer list under `tests/`, the DDL block's
two `CHECK` widenings, `architecture.md:1844–1848, 2089–2102`, `knowledge-index.md:1017–1018, 1341, 1607`,
`harness.md:601–622`, `distribution.md:182–200`, `write-policy.md:536–547`, `FINDINGS.md:75–133` and the
archive's Q18 entry.

### Findings

1. **[IMPROVEMENT] The resolver's home is stated two incompatible ways, and the done-when's
   `test_design_tables.py` cases are unwritable under one of them.** `schema.md:842–847`: *"`parse_payload`
   returns a reference unresolved and imports nothing from the package. `design_tables.py` is imported by 18
   test modules, so a resolver living there would turn one broken import into 18 collection failures.
   `test_event_kinds.py` resolves through a mapping it builds itself and raises `DesignTableError` on a name
   outside it"*; `build-plan.md:4075–4077` the same. Read literally — no resolver in `design_tables.py`,
   resolution inline in `test_event_kinds.py` — the done-when at `:4262–4264`, *"`test_design_tables.py`
   gains one case per token shape beside the group — a bare literal, a resolved `@` reference, an unknown
   reference refused"*, cannot be met: that module tests `design_tables.py`'s functions on literal input,
   and "resolved" and "refused" are properties of a resolver it would have to import from another test
   module. The only placement that satisfies both passages is a **pure function in `design_tables.py`**,
   `resolve(fields, references: Mapping[str, tuple[str, ...]])`, raising `DesignTableError` on an `@name`
   absent from the mapping — package-free, so the 18-importer argument still holds — with
   `test_event_kinds.py` supplying the mapping. Round 5's blocker was exactly this shape: a mechanism
   paragraph and a done-when naming different mechanisms, and a builder shipping the done-when's.
   **Change:** at `schema.md:842–847`, *"…so the **mapping** — the one thing that must import `ErrorCode`
   and `BUILD_ONLY_WIRE_NAMES` — lives in `test_event_kinds.py`, which passes it to a package-free
   `design_tables.resolve(...)` that raises `DesignTableError` on a name the mapping lacks"*; mirror the
   clause at `build-plan.md:4075–4077`; and at `:4262–4264` say the three cases drive `resolve` with a
   fake mapping, so the unknown-name case is a hermetic literal rather than a typo in `schema.md`. Note
   also that "a bare literal beside the group" is `test_a_set_stated_beside_the_group_is_read_too` today,
   so the done-when's "gains" is two cases, not three.

2. **[NITPICK]** `build-plan.md:4254`: *"…dropped with one log line, on every refusal. Its its `error_code`
   declared there with `values` holding…"* — a doubled word and a sentence that lost its verb in this
   round's insertion, in the done-when. The brief reports ravels checked; this one is the edit's own seam.
   Two further precision points in the same sentence: "there" now has no antecedent (the preceding sentence
   is about `CallDetail`'s field type, not `EVENT_SPECS`), and "one log line, on every refusal" reads as
   one line per refusal where `schema.md:919–921` fixes it at once until the next row succeeds. Write:
   *"…refused inside the guarded write and dropped, so the access log would hold no refusal at all. The
   `call` spec's `error_code` is declared in `EVENT_SPECS` with `values` holding…"*.

3. **[NITPICK]** *"`@` appears in no cell today"* (`schema.md:835`, `build-plan.md:4074`) is false as a
   corpus fact and true for the spans that matter: `harness.md:75` (`tools: ["@zikaron"]`),
   `architecture.md:2207` (`@zikaron` in `tools`), `coding-standards.md:88–91` (`@pytest.mark.…`) and
   `overview.md:174` (`useful-recall@5`) are all table cells. None is read by `parse_payload` and none sits
   in a `∈` span, which is the claim that carries the argument. *"`@` appears in no `∈` span today"* — a
   grep confirms it, where the current sentence a grep refutes.

4. **[NITPICK]** *"imported by 18 test modules"* / *"18 test modules import `design_tables.py`"*
   (`schema.md:843`, `build-plan.md:4075`) — accurate today (19 files match the string, one in a comment)
   and the restated-count class `FINDINGS.md` §"The audit loop" names, in two normative places. The
   argument needs "every drift guard", not the number: *"every drift guard imports `design_tables.py`, so a
   resolver there that imported the package would turn one broken import into a collection failure in
   each of them"*.

VERDICT: NEEDS_CHANGES

## Round 18 — 2026-09-28

**Summary judgment.** Round 17's four findings are applied as the brief says, and the resolver is now
stated one way everywhere a builder reads: a package-free `design_tables.resolve(fields, references)`
raising `DesignTableError` on an `@name` the mapping lacks, the mapping built in `test_event_kinds.py`
and passed in, and the done-when's two `test_design_tables.py` cases driving `resolve` with a fake
mapping. Each claim holds against the tree: `_split_row` unescapes `\|`, `_STATED_SET` takes `[^`]+`
after `∈` and `literal()` strips only `*` and backticks, so `parse_payload` already returns the two
cells as `("@ErrorCode.wire_name", "internal_error")` and `("@ErrorCode.wire_name",
"@BUILD_ONLY_WIRE_NAMES", "build_failed")` with no parser change; `test_a_set_stated_beside_the_group_is_read_too`
(`test_design_tables.py:200–202`) is the bare-literal case, so "gains two" is the right count; the
composition order §"What is instrumented" states (`schema.md:1022–1024`) is the cell's own, which matters
because `test_detail_value_sets_match_the_design_table` compares tuples for equality; the nullability rows
both cells defer to (`schema.md:768–769`) carry the right fields; and the quote attributed to
`primary.py:406–407` is verbatim. The withdrawn phrasings — *18 test modules*, *appears in no cell*,
*Its its*, *declared there*, *on every refusal* — occur in no `.md` outside `reviews/`; a doubled-word
sweep over `design/`, `FINDINGS.md` and the archive finds nothing; the named passages in the other five
documents and the archive's Q18 entry (`FINDINGS-archive.md:4757, 4932–4951`) are as round 17 left them.
No blocker and no improvement remain. What is left is three nitpicks, two of them consequences of
wording I supplied in earlier rounds. Verified against `tests/design_tables.py` in full,
`tests/test_design_tables.py:195–212`, `tests/test_event_kinds.py:60–209`, `zikaron/mcp/primary.py:406–407`,
every `∈` span under `design/`, `schema.md:686–691, 755–775, 800–940, 1010–1035`, `build-plan.md:4050–4100,
4161–4237, 4238–4388`, `FINDINGS.md:73–134`, `architecture.md:1840–1851, 2086–2103`,
`knowledge-index.md:1012–1023, 1336–1345, 1598–1613`, `harness.md:598–625`, `distribution.md:180–203`,
`write-policy.md:533–548`, and the existence of `tests/test_mcp_tool_descriptions.py`.

### Findings

1. **[NITPICK]** *"`@` appears in no `∈` span today"* (`schema.md:835–836`, `build-plan.md:4074–4075`)
   is now literally false of the tree it sits in: a grep for `∈.*@` under `design/` finds exactly five
   lines, all this milestone's own — `schema.md:690, 691, 838, 839` and `build-plan.md:4072`. The
   wording was mine in round 17 and was true of the tree before the cells were written into it; the
   argument it carries is that the marker collides with nothing *pre-existing*, which is what the
   sentence should say. *"`@` appears in no `∈` span this milestone did not write"* — the pre-existing
   spans are `architecture.md:1986, 1993, 1996` and `schema.md:1826, 1831`, and none carries one.

2. **[NITPICK]** Ravels at the seams of the last edits. `schema.md:837` — *"parser reads. The `call` cell
   therefore"* — is 39 characters between two full lines, where the round-17 #3 sentence was inserted;
   `build-plan.md:4082–4083` — *"*an enum, or a tuple composed from"* / *"one*. **Both tests move…"*;
   and `build-plan.md:4267` runs ~113 characters against the file's p90 of 110. Rewrap the three. The
   done-when also still carries short lines older than this round — `:4272, :4275, :4288, :4292,
   :4294, :4337, :4362, :4366, :4372` — which render identically and are optional.

3. **[NITPICK]** `build-plan.md:4218` and `:4226` cite *"§452's hallucination point"* and *"§452's
   rule"* — a line number from round 1 of this trail, written into a normative document as though it
   were a section. `write-policy.md`'s section is already named in full at `:4209–4210`, and the number
   drifts the next time that file is edited above it. *"that section's"* in both places. My round-1
   wording.

VERDICT: APPROVED
