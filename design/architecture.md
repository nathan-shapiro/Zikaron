# Architecture — components, RPC, lifecycle, MCP surface

> Written 2026-08-01. Companion to `design/schema.md`. Implements D9 (MCP + skill + hooks), D12 (push and
> pull), D18 (`agentSpawn` instructions), D22 (**the hook must never load a model**), D10 (manual
> consolidation), and settles the **shape** half of the hook→service transport question — the integration
> measurements stay open, see §"Open, and now narrower".

## Components

| | What it is | Loads a model? |
|---|---|---|
| **`zikaron-core`** | Library. All logic for **both stores**: the memory store (retrieval, chunking, embedding, dedup, consolidation grouping) and the knowledge index (`core/knowledge/` — KB storage, scan, git change detection, its own chunker and retrieval arms). No process concerns, no transport. | yes, on demand |
| **`zikaron-service`** | Long-running process. Holds the warm embedder and the open DBs. Serves local RPC. Self-stops after idle. | **yes — the only long-running one** |
| **`zikaron-mcp`** | MCP server, built on the `fastmcp` framework. Translates MCP tool calls to RPC. Starts the service if absent. | no |
| **`zikaron-hook`** | Thin hook executable for the spawn and user-message triggers. Starts the service if absent. | no |
| **`zikaron-knowledge-indexer`** | Detached process spawned per knowledge-base build (K8) — **by the service** on a `knowledge_*` call, and **by `python -m zikaron.knowledge`** directly when a person starts a build from a shell, which opens the store itself and never goes through RPC. Outlives its caller and exits when the build finishes. *Naming only the service made a shell-started indexer with no service in the `ps` tree look impossible.* | **yes** — which is why the service's cell above says *long-running* rather than *only* |

The service exists for exactly one measured reason: cold whole-process `bge-small` is **783 ms**, and D12
puts retrieval on the critical path of every user message. Keeping the model resident moves that to a warm
**6.64 ms** embed and a **9.14 ms** full retrieval path — the figures for the **prefixed** path D20 actually
adopts. (Without the prefix it is 5.45 / 7.97 ms; quoting those for a prefixed deployment was a stale-figure
finding in the corpus review.)

**The hook is thin on purpose; the MCP server is not, and the difference is the cost model each one sits
on.** Measured on this machine: `python -c pass` is **10.9 ms**, `import socket, json, os` is **20.6 ms**,
adding `sqlite3` is **21.8 ms**. So a stdlib-only client costs ~20 ms — which is the real argument against an
HTTP/ASGI transport for the hook, since importing an HTTP client into it would spend more than the transport
saves. `zikaron-hook` fires on **every `userPromptSubmit`**, i.e. every user message in every turn, so its
import cost is paid repeatedly within one session and D12's whole argument for keeping it on the critical
path only holds if that repeated cost stays near-zero.

`zikaron-mcp` does not have that shape. kiro spawns **one MCP server process per agent instance**
(`research/kiro-mcp-lifecycle-probe.md`) — once per top-level session and once per subagent spawn, not once
per message — so its import cost is a one-time cost per spawn rather than a per-turn tax. **Operator
decision, after M9's fourteen-round review of a hand-rolled `asyncio.start_unix_server` did not converge**:
`zikaron-mcp` takes a dependency on `fastmcp` (pinned exactly, per coding-standards.md §6) rather than
re-deriving MCP's own framing, tool-schema generation and stdio transport by hand a second time. Measured
directly on this machine: bare interpreter start is **27.9 ms** (median of 5), `import fastmcp` cold is
**594.6 ms** (median of 5) — in the same range as the cold embedder load that justifies `zikaron-service`
existing as a long-running process at all, and roughly 30× the bare interpreter. That cost is accepted
because it is paid **once per spawn, not once per message** — the reasoning D12 uses to keep the hook
stdlib-thin does not transfer, since nothing about the MCP server sits on a per-turn critical path the way
`userPromptSubmit` does. `zikaron-hook` stays stdlib-only; nothing above revises that.

## RPC: Unix domain socket + newline-delimited JSON-RPC 2.0

Server uses stdlib `asyncio.start_unix_server`. Clients need only `socket` and `json`.

**All of `zikaron-core`'s SQL runs through `aiosqlite`, never through bare stdlib `sqlite3`.** This is a
correctness requirement, not a style preference, and it replaces an earlier, weaker version of this note that
said the same blocking-call-off-the-event-loop rule but left it to be enforced per call site via
`asyncio.to_thread`. That discipline is real but optional at every call site: nothing stops a future handler
from calling the blocking sqlite3 API directly, and getting it wrong is silent until it deadlocks under real
contention. Confirmed locally (M0 spike 3): an inline `async def` handler that called blocking `sqlite3`
directly produced a **self-inflicted deadlock** under two concurrent writers — writer B's blocking `BEGIN
IMMEDIATE` froze the single-threaded event loop, which prevented writer A's release (simulated with
`asyncio.sleep`) from ever running, so B's own `busy_timeout` elapsed waiting on a release that could
structurally never happen. The failure surfaces as `−32020 store_busy` after ~5 s, indistinguishable from
genuine contention to the caller — exactly the kind of defect that gets misdiagnosed as a database or
`busy_timeout` problem rather than a service-implementation one.

`aiosqlite` closes this structurally rather than by convention: each `aiosqlite.Connection` runs its underlying
`sqlite3.Connection` on its own dedicated worker thread and dispatches every call through it, so there is no
synchronous call path to get wrong at a call site — a handler cannot accidentally block the event loop because
`aiosqlite` never hands it a blocking call to make. Re-confirmed against the exact mechanisms this design needs
(M0 spike 5, `research/spike-results.md` §"Spike 5"): `await db.load_extension(sqlite_vec.loadable_path())`
loads `sqlite-vec` correctly (the equivalent of `sqlite_vec.load()`, which stdlib `sqlite3` exposes but
`aiosqlite.Connection` does not accept directly — extension loading must go through aiosqlite's own
`load_extension` method, not by reaching into its wrapped connection, which is bound to aiosqlite's worker
thread and raises if touched from the caller's); `vec0` KNN and the dimension-mismatch error are unchanged;
the FTS5 amend and erasure sequences behave identically to the raw-`sqlite3` spike; and the two-writer
contention check that exposed the original deadlock succeeds cleanly through `aiosqlite` with no special
handling — writer B's `waited_s` reflects real serialization through `busy_timeout`, not a frozen loop.
`aiosqlite==0.22.1` is the version verified; pin it exactly per `design/coding-standards.md` §6.

**The identical failure mode recurs on the client side of this same RPC, and `zikaron-mcp` closes it the
same way `aiosqlite` closes it for the service — by running the blocking call off the event loop, through
`asyncio.to_thread`, rather than by convention.** `zikaron.mcp.connection.ServiceConnection` is `async def`
throughout, but its own socket I/O — `socket.send`, `socket.recv`, and
`service.lifecycle.connect_start_if_absent` itself, which `lifecycle.py`'s own docstring states is
"blocking, deliberately" for
the short-lived, single-connection-attempt processes it was originally written to serve — are all
synchronous. `zikaron-mcp` is not that kind of client: M10 holds one connection across many tool calls in one
long-running process, so a blocking call anywhere inside its own request path holds the *same*
single-threaded event loop every other coroutine in that process runs on, for as long as the service takes to
answer — including the full 5 s `busy_timeout` window a contended write may legitimately need. **Measured
directly, not merely reasoned about**, while building the very integration test meant to prove a request
survives waiting out real contention: an earlier version of `ServiceConnection.request` called the blocking
socket calls directly, and a concurrent `asyncio.sleep` in an unrelated task on the same loop — the test's own
lock-holding fixture — was starved for the entire blocking wait rather than resuming on its own schedule,
which let the *service's* own `busy_timeout` expire before the test's holder ever released its lock, and the
call that should have waited out contention and succeeded instead received a — genuinely correct, but
avoidably reached — `store_busy` rejection. `ServiceConnection` now wraps every blocking call
(`_send_request`, `_read_response`, and `connect_start_if_absent`) in `asyncio.to_thread`; with that fix in
place, the identical test waits out ~1.8 s of real contention and receives the request's actual success
response in under 4 s total. `zikaron-hook`'s own client code has no equivalent obligation: it is a
short-lived, single-request process exactly matching what `lifecycle.py`'s blocking design already assumes,
so nothing else on its own event loop is ever waiting to be starved.

### The request envelope — where `session_id` comes from
D27 keeps provenance out of the **agent-facing** call — the write verbs gain no parameters. But a
long-running service shared by two kiro sessions cannot infer which session a request came from, so the
client must tell it, in the transport rather than in the tool signature. Every request carries a `client`
object alongside its params, in one of **two forms**:

```json
// resolved form — every call from a client that knows its label
{"jsonrpc":"2.0","id":7,"method":"remember",
 "params":{"gist":"…","content":"…",
           "client":{"session_id":"zk-… | <harness id>",
                     "kind":"hook|mcp|consolidator","pid":12345,"op_id":"…"}}}

// bootstrap form — reachable only when KIRO_SESSION_ID is absent from the
// client's environment. `session_id` is explicitly null; the service mints one.
{"jsonrpc":"2.0","id":1,"method":"surface",
 "params":{"prompt":"…",
           "client":{"session_id":null,
                     "kind":"mcp","pid":12345,"op_id":"…"}}}
```

**The envelope carries the label and nothing else about how it was obtained.** There is no `label_source`
field, in either direction: it is **derived from the label itself** (§"`label_source` is derived, not stored"
below) and therefore needs no wire representation, no column and no client cooperation. A client that sends one
is ignored rather than rejected.

**Resolution is a preamble, not a step of the method.** On every request **except `health()`** — the one
unlabelled primitive, see below — the service:

1. Validates the envelope's *shape*: `kind` present and known; `session_id` either a conforming string or
   explicitly `null`; **`pid` a positive integer, required on every request.** `pid` is half of the
   consolidation owner identity (§"Consolidation lifecycle"), so an absent or unparseable one would
   collapse that pair back to the session-only behaviour the 2026-08-01 shared label made unsafe; it is
   rejected `bounds`, never defaulted.
2. Runs the two-rung ladder below and produces a **non-null** `session_id`: the envelope's, or a freshly
   minted `zk-<uuid4>` when the envelope's is null or malformed.
3. **Normalizes the envelope in place** to that non-null label and only then enters the validation-precedence
   ladder, executes the method, writes any `event` row, or mints any receipt. Nothing downstream of step 3 can
   observe a null label, which is what lets `schema.md` invariant 18 be stated about the *normalized* envelope.
4. Returns `client.session_id` in the response envelope — **on success and on every error alike**, including
   `store_busy`, `bad_config`, `bounds`, `reindexing` and `schema_incompatible`. A client that bootstraps into a
   failing first call still learns its label, so it does not re-bootstrap and mint a second one. **There are no
   exceptions**, and there is nothing left to make one out of: resolution touches no table, so no store state
   can leave a resolution un-final. (Rounds 7–8 had two — `store_busy` and `schema_incompatible` echoed
   `session_id: null` because a resolution was only final once its `session_client` row committed. That table is
   gone, and with it the special case.)
5. The client **adopts** the returned label and reuses it for its process lifetime. A client that keeps sending
   the bootstrap form after a resolved response is non-conforming; the observable is a `zk-`-heavy label
   population, which §"Linked sessions" already surfaces.

**`health()` is the one unlabelled primitive, and why it is outside this.** It is called *before* store identity
is verified, so a label minted there could be one a **foreign** store's service produced. It takes no `client`
envelope, resolves and returns no label, and nothing is adopted from it. Full argument under
§"`label_source` is derived, not stored".

#### Both clients resolve the same label, and as of 2026-08-01 they do so by construction

> **Harness delta (D34).** This holds verbatim on Claude Code with one more variable name in it:
> `CLAUDE_CODE_SESSION_ID` is exported into every process it spawns — both hooks, subagent subprocesses and
> **the MCP stdio server** — and equals the hook payload's `session_id` (measured,
> `research/claude-code-harness-probe.md` §1). The ladder, `label_source`, the `zk-` reserved namespace and
> the linked-session guarantees are unchanged; only the variable read differs, selected by the `CLAUDECODE`
> marker. **`CLAUDE_PID` is not overridden for children and must never be read.** The one new residual —
> a nested session of one harness inside the other inheriting a stale id, which link coverage **cannot**
> detect — is in `design/harness.md`.

This is not a stability problem, and treating it as one was a real defect. Each client holding *its own*
stable label is not enough: **pushes are emitted by `zikaron-hook` and writes by `zikaron-mcp`**, so D30's
"zero-write sessions" and "amend after surface" are joins across two processes. Under mismatched labels every
writing session looks like a zero-write hook session — inflating the under-writing rate in exactly the
direction D30's prior expects, which is the worst way for instrumentation to be wrong.

**Measured 2026-08-01, and it collapsed the mechanism.** Rounds 3–8 built a three-rung ladder whose middle rung
derived the MCP client's label by matching `/proc` ancestor chains against registrations the hook published. That
rung existed for one hypothesized case — *the harness exports nothing to the MCP process* — and the corpus said
so, flagging it "specified but unverified". A hook probe registered on `agentSpawn` and `userPromptSubmit` for
two agents, plus direct reads of `/proc/<pid>/environ`, established the case does not arise:

- **`KIRO_SESSION_ID` is in the environment of every child kiro spawns** — shell-tool subprocesses, hook
  processes, and **live MCP server processes** (two independent examples from unrelated sessions, carrying
  distinct values). It is absent from kiro's own processes, so it is injected at child spawn.
- It is the **canonical** session id, not a telemetry correlation id: it names the session's own transcript
  files under `~/.kiro/sessions/cli/`.
- On a top-level session the hook payload's `session_id` and `KIRO_SESSION_ID` were **identical** on every
  firing (3/3 across two sessions and both hook events).
- Inside a **subagent** they differ, and in a specific way: the payload carries the subagent's own session id
  while `KIRO_SESSION_ID` still carries the **top-level** one (2/2 firings). Generalized: `KIRO_SESSION_ID` is
  always the top-level session id, in every process; the hook payload's `session_id` is the *actual* session.
  They coincide exactly at top level.

Raw log: `/tmp/zikaron-hookprobe/log-final.jsonl`. One artefact to *not* over-read: two `agentSpawn` firings
were observed for one session, which was the operator restarting kiro and then restoring context — not evidence
that `agentSpawn` fires twice per session.

So both clients can read the same string out of their own environment, and the ladder has **two rungs**:

1. **`harness`** — the client reads `KIRO_SESSION_ID` from its own environment and sends it. Available to
   `zikaron-hook`, `zikaron-mcp` and the consolidator alike, and **identical for all of them**, so the two
   clients agree *by construction* rather than by inference. No derivation, no registry, no matching, nothing to
   race. This is the normal path under kiro, and it is the only path that guarantees agreement.
2. **`minted`** — no `KIRO_SESSION_ID` in the environment, **or one that intrudes on the reserved namespace**
   (see the client contract below): a non-kiro harness, or kiro changing. The client sends
   the bootstrap form (`session_id: null`), the service mints `zk-<uuid4>`, returns it, and the client adopts it
   for its process lifetime. The **`zk-` prefix is a reserved namespace**, and reserving it is load-bearing
   rather than cosmetic: it is how the service recognizes its own label when a client sends one back, and
   therefore the whole of how `label_source` is derived (§"`label_source` is derived, not stored"). This is the
   *unlinked* state, because an env-less hook and an env-less MCP client mint **different** labels — and it is
   measured rather than assumed: `schema.md` §"Linked sessions" defines a session as linked iff both a `hook` and
   an `mcp` event share its `session_id`, computes **link coverage**, and restricts the two cross-client signals
   to linked sessions.

   **Client contract on the namespace, required for the derivation to be truthful.** The service authenticates
   nothing: it accepts any shape-valid `session_id` the transport hands it, so a harness exporting
   `KIRO_SESSION_ID=zk-anything` would be classified `minted` while being, in fact, harness-supplied. The prefix
   test is therefore *total* but not *honest* unless clients cooperate. So: **a client that finds a
   `zk-`-prefixed value in `KIRO_SESSION_ID` must treat it as absent** — send the bootstrap form and adopt a
   fresh service-minted label. That keeps `^zk-` ⇒ *this label came from the service* true of every conforming
   client, which is all `label_source` claims. Nothing in authorization depends on the distinction — it is an
   audit label, not a capability — so a non-conforming harness costs an accurate `label_source` and nothing more,
   and the honest reading of the field is *lexical class under the client contract*, not proof of origin.

**Note which client uses which rung, because it changed.** `zikaron-hook` still always takes rung 1 — kiro's id
is in the hook payload *and* in its environment. `zikaron-mcp` now also takes rung 1 under kiro, where it
previously had to derive. Rung 2 (`minted`) is no longer the *expected* fallback for a normal kiro deployment; it
is the non-kiro case.

**A subagent's MCP client reads the parent's `KIRO_SESSION_ID`, and that is the wanted behaviour.** Writes made
from inside a subagent attribute to the **top-level** session, which is the unit every D30 signal is defined
over — a consolidation run or a delegated task is not a session that should show up as its own zero-write row.
`client.kind` still distinguishes *who* wrote. The corresponding hook behaviour is the opposite and needs a rule
of its own: see §"Subagent sessions — the push hook suppresses itself".

~~The `service.log` records each label resolution — which rung won — at the call that resolved it, so an analysis
never has to infer it.~~ **— nothing logs it, and nothing needs to.** `service/log.py` has exactly four
writers — `configure_service_log`, `log_runtime_versions`, `log_resolved_config`, `log_self_stop` — and
none concerns a session label; `label_source` has **no production caller at all**, only tests.
An analysis reads the rung off `event.session_id` directly: a `zk-` prefix is `minted`, anything else
`harness`. Resolution happens per **first request from a client**, not per client startup: under the bootstrap
form the service has no knowledge of a client until it calls. The durable record
is the label itself, from which `label_source` is a pure function — which is *why* no log line is needed,
and is what made the missing one invisible.

- **`op_id`** is minted per call by the client (or by the service if absent) and stamped on every `event`
  row the call emits, which is what correlates a `remember` with the `dedup_offered` rows it produced.
  **It is not an idempotency key.** The service performs no lookup against a stored `op_id` before executing
  a mutation, so two requests carrying the identical value are two independent writes, not one deduplicated
  into the other — `op_id` answers "which rows did this one call cause," after the fact, never "has this call
  already run." A client that retries a mutating call whose *response* was lost, hoping the identical `op_id`
  protects it, is wrong to hope that; nothing on the service side checks.
- **A client's retry-once obligation (§Lifecycle) is therefore narrower than "retry the call."** It covers a
  failure discovered *before any byte of the request's own encoding reached the socket* — the documented case
  is a held connection found dead, where nothing of this exact call was necessarily sent — and does not
  extend to a failure discovered once transmission has begun, including a partial send: `sendall`'s own
  documentation states "if an error occurs, it's impossible to tell how much data has been sent," so a naive
  client cannot tell "nothing reached the socket" from "most of it did, and the service may already be
  running it" apart merely from `sendall` having raised. A conforming client tracks its own send progress
  (`zikaron-mcp`'s own client does, with a manual send loop rather than trusting `sendall`) and treats *any*
  positive progress, or a failure discovered while waiting for the *response*, as the case where the service
  may already have received, run and committed the request. Retrying that case would risk a duplicate
  `remember`, a spurious `amend` conflict against a version the first attempt already bumped, or two
  consolidator writes racing each other, with no mechanism on either side to notice or prevent it.
  `zikaron-mcp`'s own client (M10) surfaces this case as a distinct, named failure rather than silently
  resolving it either way, and does not retry it. **A server-side idempotency mechanism — checking a
  client-minted key against something durable before a mutation runs — would close this gap properly, and
  does not exist yet**; recorded here as an open question rather than solved by a client-side workaround,
  since the fix belongs on the side that can actually make the guarantee.
- **Trust model.** The envelope is **transport-supplied, not authenticated.** A 0600 UDS already restricts
  callers to the owning uid (see §"Filesystem security"), and any process that could forge a `session_id`
  could equally call `remember` directly. The service validates *shape* — a string of ≤128 chars with no
  control characters, **or explicit `null` for the bootstrap form** — and nothing more. Nowhere does the corpus
  claim this label is server-*derived* or verified. `label_source` is server-derived in the only sense left
  after 2026-08-01: it is a **pure function of the label** rather than a client assertion
  (§"`label_source` is derived, not stored"), which is weaker than the round-7 claim and is all that is now
  needed, because rung 1 no longer competes with a derivation it could be mistaken for. D27's "the write call
  gains no parameters" is a statement about the **agent-facing tool signature**, which the envelope keeps true.
- **A live request never carries a NULL `session_id`, and that is a correctness requirement rather than a
  nicety.** `read_receipt.session_id` is `NOT NULL`, and `fetch` promises unconditionally to mint a receipt;
  a NULL label would make that promise unkeepable and silently strip a client of its licence to write. The rule
  is therefore about the **normalized** envelope:

  > A **null** `client.session_id` is the bootstrap form: the service **mints** `zk-<uuid4>`. A `session_id`
  > that is present but fails **shape** validation is a client defect, and is treated the same way — the
  > service mints, because a malformed label carries no information. Either way the envelope is normalized to
  > a non-null label before the method runs, the resolved label is returned, and the client **must adopt it
  > and reuse it** for its process lifetime.

  The label is returned unconditionally, on success and on every error, because resolution now touches no table
  and so cannot half-happen. Rounds 6–8 had to qualify this — the pair was final only once its `session_client`
  row committed, so `store_busy` and `schema_incompatible` withheld it — and that qualification is gone with the
  table.

  `zikaron-hook` never bootstraps under kiro: the id is in its payload and in its environment. `zikaron-mcp`
  bootstraps only when `KIRO_SESSION_ID` is absent, which under kiro does not happen. ~~The `service.log` records
  which rung produced the label.~~ **Nothing logs it; the label's own prefix is the record** (above).
  Worst case a session is labelled by the service rather than by the harness:
  single-client signals (dedup resolution, retire count, write sizes, conflict rate) are unaffected, because
  they join only `mcp` events — but the two **cross-client** signals are not computable for that session, and
  `schema.md` §"Linked sessions" excludes it and counts it against link coverage. Saying instead that one stable
  label per process is "all the per-session signals need" was the false claim round 3 caught.

#### `label_source` is derived, not stored
`label_source` answers one question — *did the harness supply this label, or did we make it up?* — and after
2026-08-01 that is decidable from the label alone:

| Label | `label_source` |
|---|---|
| matches `^zk-` | `minted` |
| anything else | `harness` |

That is the whole rule. It is a **pure function of `session_id`**, computed wherever it is wanted and stored
nowhere, so there is exactly one source of truth and nothing to drift. The `zk-` prefix is a **reserved
namespace** and was already load-bearing before this — it is how the service recognizes its own labels coming
back from a client — which is precisely what makes the function total: a label is either one the service minted,
and says so in its first three characters, or it came from outside.

**What this replaces, and why the replacement is smaller rather than merely different.** Rounds 5–8 spent four
rounds hardening a *stored* `label_source`, because with three rungs the field was not recoverable from the
label: an MCP client that adopted an `ancestry`-derived label thereafter sent bytes **identical** to a
natively-held harness id, so re-deriving on each call reclassified a derived label as `harness` from the second
call onward, overstating the authority the field exists to audit. The fixes accreted accordingly — a read-side
least-authority rule (round 6), then a persisted `session_client` table with a get-or-create preamble, a
read-back inside the insert's transaction, a "pair-level first provenance" definition, an `event.label_source`
copy, invariant 21 to keep the two in agreement, a durability-precedes-adoption rule, and a rung-0 `store_busy`
error for the case where the row could not commit (rounds 7–8). **Every one of those existed to make a derived
rung distinguishable from a harness rung.** Delete the derived rung — which the measurement did, by showing the
case it served does not arise — and the two remaining rungs are already distinguishable by the namespace that
was there all along. The table, the column, the invariant, the preamble write and the rung-0 error are gone.
Nothing about the *question* changed; the mechanism needed to answer it collapsed.

**`health()` is exempt from the ladder entirely, and that is a bug fixed rather than a convenience.**
`health()` is the store-identity handshake (§"Store identity is verified, not assumed"), and the client calls
it **before it knows whether this socket even belongs to its store** — the truncated socket hash plus the
shared `/tmp` fallback are why that handshake exists at all. A client that resolved and adopted a label from
that call would adopt one **minted by a foreign store's service** in precisely the case the handshake exists to
catch, then keep it for its process lifetime and stamp it on events in the *correct* store. So `health()` takes
no `client` envelope, resolves nothing, returns no `session_id`, and nothing is adopted from it; nor does it need
to, since it emits no event and mints no receipt. Resolution happens on the first request that is *about* this
store, which is strictly after identity is verified. It is now the **only** exemption — `register_session` was
the other, and it is gone with the rung it fed — so `health()` answering `ready: false` is not a special case of
anything.

**One residual, stated rather than implied.** A store that was **deleted and recreated** under a live client —
the blunt erasure procedure `write-policy.md` recommends is exactly `rm -rf .zikaron/` — leaves an MCP process
holding an adopted `zk-` label the new store has never seen. It is classified `minted`, which is correct: that
client's label did not come from the harness, and the session is unlinked and *measured* as unlinked. Under the
round-7 design this case was the one the prefix test had to rescue from a missing replay row; now it needs no
rescuing, because the prefix test is the only test.

- **D26's receipts are keyed on this label.** A client that changes its label mid-session loses its receipts
  and must re-`fetch`. That fails **closed** — it rejects writes rather than admitting unread ones — which is
  the right direction, and it is the reason the adopt-and-reuse rule above is a requirement and not advice.
- **Consolidation provenance.** Records the consolidator writes carry the **top-level session's** `session_id` —
  its MCP client reads the parent's `KIRO_SESSION_ID` like any other subagent's — with `client.kind` =
  `consolidator` on every `event` row saying who wrote. That is a change from rounds 3–8, where the consolidator
  held a label of its own; §"Subagent sessions" states what the shared label does and does not affect.
  Original authorship is not lost, because D16 retains the absorbed rows with their own `session_id` and
  `superseded_by` links back from them — so "who first learned this" is answerable by walking the chain,
  without adding a field D27 rejected.

**Rejected, with reasons:**
- **Any TCP transport, including localhost.** A localhost port is reachable by every process and every user
  on the machine, and this is an *unauthenticated, write-capable* API over accumulated project knowledge.
  A UDS at mode `0600` inside a `0700` directory is restricted to the owning user by the filesystem, so no
  application-level auth is needed. **If this ever moves to TCP it needs authentication first.**
- **HTTP over UDS (FastAPI/uvicorn).** Pydantic validation and generated docs are real benefits, but the
  dependency weight lands in the latency-critical hook.
- **gRPC.** Protobuf codegen and a heavy dependency for a same-host socket.
- **stdlib `xmlrpc`.** TCP-only, plus XML overhead.
- **Pickle-based transports (`multiprocessing.managers`, Pyro).** Unpickling untrusted bytes is remote code
  execution; not worth it for a local socket.

## Paths

- **Knowledge bases:** `<scope>/.zikaron/knowledge/<uuid4>.db`, one per corpus, registered in
  `memory.db`. Absent until the first is created. Same permissions as the store (§"Filesystem
  security"), and a knowledge base holds the **verbatim text of every file indexed into it**.
- **Store:** `<scope>/.zikaron/memory.db`, where `<scope>` is `HarnessSpec.store_scope_dir` — the
  harness's own project directory where it names one, else the working directory (D17, **amended
  2026-08-18**; `design/harness.md` D34 row "Project-directory variable"). `.zikaron/` is already in
  `.gitignore` per D19.
- **Socket:** *not* in the project tree — UDS on a network filesystem is unreliable, and the tree stays
  clean. `$XDG_RUNTIME_DIR/zikaron/<h>.sock` when that is set (already user-private `0700`), else
  `/tmp/zikaron-<uid>/<h>.sock` with the directory created `0700`. `<h>` is the **first 32 hex characters
  (128 bits) of the sha256 of the `realpath`-resolved store path** — long enough that accidental collision
  is not a design concern, short enough to keep the path under the ~108-byte `sun_path` limit. One service
  per store.
- **Logs: one file per process, never shared.** `<scope>/.zikaron/service.log` (the long-running service),
  `<scope>/.zikaron/warmup.log` (the `agentSpawn` hook's detached warm helper), `<scope>/.zikaron/hook.log` (the
  `userPromptSubmit` hook's own failure record). Three distinct processes, three distinct files, by design:
  Python's `logging.FileHandler` has no cross-process append locking, so two independent processes writing the
  same path through `logging` is a real corruption risk `logging`'s own documentation does not paper over —
  giving each process its own file removes the question entirely rather than requiring proof that concurrent
  appends are safe. The service and the warm helper are both off any latency-critical path, so both use stdlib
  `logging`. The `userPromptSubmit` hook is not — see §"Degraded modes" for why it does a direct file write
  instead.
- **Config:** two layers, resolved per store — see §"Configuration" below.

## Configuration

Settled with the user 2026-08-01. Two TOML layers plus the built-in defaults, resolved into one **effective
config** per store.

| Layer | Path | Role |
|---|---|---|
| 1. built-in defaults | in `zikaron-core` | every key has one; the v0 values are the tables in `design/schema.md` §"Configuration keys" |
| 2. system-wide | `${XDG_CONFIG_HOME:-~/.config}/zikaron/config.toml` | this machine's preferences, and the defaults for every *new* store |
| 3. project override | `<scope>/.zikaron/config.toml` | this project only |

*"System-wide" is read as **user-level**, not `/etc`.* Zikaron installs into a per-user venv (D19) and already
keeps its socket under `$XDG_RUNTIME_DIR`, so a machine-wide layer would add a third file and a permissions
question for no benefit on a single-user development machine. If a genuinely multi-user install ever exists,
`/etc/zikaron/config.toml` slots in below layer 2 without changing anything else here.

### Resolution: later layer wins, per key

**Every layer is optional and every layer may be partial.** An override file states only what it changes; it
does not have to repeat the rest. Resolution walks the layers in order and takes the last value seen for each
key. A missing file is not an error — an absent layer contributes nothing.

**The merge is per-key at depth 2, not per-section.** Keys are grouped into TOML sections for readability, so
this must be said explicitly or two implementations will differ: a section appearing in the override
**amends** the corresponding section, it does **not** replace it. Nothing nests deeper than one section, so
depth 2 is the whole rule.

```toml
# ~/.config/zikaron/config.toml — machine preferences
[service]
idle_timeout = 3600          # I keep long sessions

[retrieval]
fusion_depth = 50
rrf_k = 60

# <scope>/.zikaron/config.toml — this project only
[retrieval]
rrf_k = 30                   # amends [retrieval]; fusion_depth = 50 survives
```

Effective result: `idle_timeout = 3600`, `fusion_depth = 50`, `rrf_k = 30`, and every unmentioned key at its
built-in default.

### Validation: unknown keys per file, ranges on the effective config

Two different checks, deliberately at two different points.

**Unknown or misspelled keys are rejected per file, at parse time**, naming the file and the key. This is the
one place the file contract is *stricter* than `meta`, which tolerates unknown keys for forward compatibility.
A `meta` key was written by the service; a file key was typed by a person, and silently ignoring
`fusion_dept = 100` is how an afternoon disappears. The same applies to a wrong TOML type — a float where an
int is declared is `bad_config`, never a silent truncation. Duplicate keys inside one file are a TOML parse
error, so that comes free.

**Range and cross-key validation runs on the merged effective config**, not on each file. An out-of-range
value in the system-wide layer that the project override replaces with a legal one is fine — what matters is
what the service will actually use. Conversely an out-of-range override fails even when the layer beneath it
was legal. Ranges themselves are unchanged and still return **`bad_config`**; only the source widened, so the
error payload now carries the file and key.

**The resolved config is written to `service.log` at startup, with the layer each non-default value came
from.** With three layers, "why does this project behave differently" is otherwise a two-file hunt.

**And one record is written when the service stops cleanly, naming which condition fired** —
`reason=idle`, `reason=store_replaced` or `reason=encoder_failed`, with the store directory and how
long it had been idle.
Added after an inspection of a real machine found four stores, one live service, and four
`service.log` files whose last entry was the startup config dump: `idle_self_stop` unlinked, shut
down and returned in silence, so the only line any exit path had ever written was the forced-exit
`exception()` below. That inverted this log's contract — silence meant a clean stop and a line meant
a failed one — and left "did this service stop, or is it wedged?" answerable only with `ps`. The two
reasons are distinguished because their diagnoses differ: `idle` is routine; `store_replaced`
means the file this process had open is no longer the one at its path, which is someone moving,
deleting or restoring a store underneath a running service; and `encoder_failed` means the model
this service bound the socket ahead of never loaded, or loaded at a width the store cannot use
(§"The model loads behind the socket").

### Read once, at service startup

Both files are read when the service starts and not re-read afterwards. This is a correctness requirement, not
laziness: `surface_call.detail` records `fusion_depth`, and D30's signals are computed over those event rows,
so a config change mid-run would let two events in the same run disagree and make the instrumentation
uninterpretable. Reading once buys internal consistency for a run at no cost.

Changing a value therefore means restarting the service, which is cheap — it self-stops after `idle_timeout`
anyway, and `SIGTERM` is documented in `design/write-policy.md`. One service per store means two projects on
one machine share layer 2 but resolve independently in separate processes, so there is no interaction.

### What the file cannot change *silently*: the store-coupled keys

The file expresses **intent**; `meta` records **what was actually done**. Three keys are therefore
**dual-homed** — `embed_model`, `embed_dim`, `chunk_max_tokens` are real config keys *and* `meta` rows
(`design/schema.md` §"Configuration keys"). None is settable per-request or mutable in place, and a file that
disagrees with `meta` on one of them is *requesting* a change rather than making one. Disagreement has two
severities:

- **Hard — `embed_model`, `embed_dim`.** `meta` is authoritative. A file that disagrees is *requesting* a
  different embedder, and the answer is invariant 11's forced reindex, never a silent switch: every stored
  vector was produced by the recorded model, and D20 established that a same-dimension swap corrupts `vec0`
  with no schema protection.
- **Soft — `chunk_max_tokens`.** The file governs **new** writes; `meta` records what the existing chunks were
  cut at. ~~A mismatch is logged and~~ **A mismatch is not detected at all — nothing compares the two.**
  `Store.create` seeds `meta` from the file; `Store.open` re-validates `embed_model` and `embed_dim` and
  says nothing about this key, and `IndexingContext` reads the file value independently. The store is
  simply heterogeneous — old chunks remain valid vectors of valid text, so refusing to start would be
  disproportionate. `indexing.md`'s `token_count` and `truncated`
  instrumentation already makes the heterogeneity visible, and it is the **only** thing that does.
  *"Logged" stood here and in `design/schema.md`'s table for as long as the key has existed, describing
  an observability that was never built. `StoreCoupling` is a declarative enum: outside `keys.py` nothing
  reads it.*
- `schema_version`, `store_id` and the transient `reindexing` sentinel are never settable from a file at all.

**A knowledge base has its own `meta`, under a different policy, and this section governs `memory.db`
alone.** A corpus seeds **six** config-derived values into its own metadata when it is created —
`embed_model`, `embed_dim`, `chunk_max_tokens`, `rrf_k`, `fusion_depth` and
`knowledge_max_file_bytes` — **under two opposite policies, and the split is the point**
(`design/knowledge-index.md` §10 is normative for it):

- **Absorbed and never compared again — `chunk_max_tokens`, `rrf_k`, `fusion_depth`,
  `knowledge_max_file_bytes`.** A corpus is chunked, fused and size-capped at the values it was
  created with, and a later file change is not applied, not refused and **not detected**: nothing
  compares them. `rrf_k` and `fusion_depth` are read back out of `meta` on every search and
  `max_file_bytes` on every build, which is why they are seeded at all.
- **Inverted — `embed_model`, `embed_dim`.** A disagreement is not absorbed. It puts the corpus in
  `reindex_required` and the next `refresh` rebuilds it whole — degraded rather than refused at
  startup, since a corpus's own database is opened per call and never when the service starts.

The hard/soft severities above do not apply to any of it.
*(This sentence named four of the six for as long as it existed; correcting the **count** then
attached one consequence to all six, which flattened exactly the distinction `encoder_matches_config`
spells out in its own docstring — "Every other tuning key is deliberately not compared… Same seeding
mechanism, opposite policy." **A count fixed without its predicate is a new claim, not a repair.**)*
*(The code has always known this — `core/config/keys.py`'s `StoreCoupling` docstring scopes itself to
the memory store explicitly, "because it is not the only database Zikaron owns". The normative
section a reader is sent to did not say so until 2026-09-22, so "the store-coupled keys" read as a
complete account of configuration/storage coupling.)*

**At store creation the effective config is what gets frozen into `meta`.** That gives layer 2 a real use:
setting `embed_model` there makes it the default for every *new* store on the machine, while a project
override can pick a different embedder for one project — and thereafter that store's `meta` holds it.

### Store identity is verified, not assumed
A truncated hash plus a shared `/tmp` fallback means a client could in principle reach a service for a
different store. So identity is checked rather than inferred:

- `meta.store_id` is a UUID minted when the store is created.
- `health()` returns `{ready, store_path, store_id, embed_model, embed_dim, schema_version, pid}`. It carries
  **no `client` envelope and resolves no session label** — see below.
- **A client verifies `store_path` and `store_id` against the store it resolved, before it sends any read or
  write.** A mismatch is not a retry: the client ~~logs it, treats~~ **treats** the socket as foreign,
  and — for the hook — goes through the same degraded path as any other failure (§"Degraded modes"):
  one line to `hook.log` plus a model-facing relay on stdout, never a read. **Only the hook logs**,
  which is the same split §"Idle self-stop" already draws for the two clients' fallbacks —
  `zikaron/mcp/` imports no logger, so there the mismatch propagates and surfaces as an ordinary MCP
  tool error the calling model sees, recorded nowhere. The mismatch is not special-cased into a
  fallback read of a store the client has no way to know is the right one.
- **Nothing is adopted from an unverified service, session labels included.** This is why `health()` is outside
  the label ladder (§"`label_source` is derived, not stored"). If the handshake resolved a label, a client
  reaching a *foreign* service would adopt a label that service minted, discard the socket on the mismatch it
  was checking for, and then stamp that foreign label on every event in its own store — a cross-store
  contamination introduced by the very call that exists to prevent cross-store reads. Resolution therefore
  happens on the first request that is *about* this store, which is strictly after verification.
- **The one case with no prior `store_id` to verify against: a client's very first connection for a store
  that does not exist on disk yet.** §"First run" has the service create the store on demand, which means a
  client resolving identity beforehand — the ordinary case above — has nothing recorded to read. That client
  checks `store_path` alone on this one connection, and trusts whichever `store_id` this exact connection's
  own `health()` reports: sound specifically because the connection came from this call's own attempt, either
  found already listening or spawned and awaited synchronously by it, never from an unrelated prior
  connection this client never verified. Every later connection this client makes — including any recovery
  reconnect — has a real `store_id` to compare against, since the store now exists; the bootstrap case fires
  at most once per client process, on whichever attempt is first to find `memory.db` absent.
- **The hook is a genuine exception to "every later connection has a real `store_id` to compare against"** —
  every one of its connections is, from its own point of view, a first connection, because it is a fresh,
  single-shot process on every invocation with no connection of its own from an earlier call to have learned
  anything from (§"Degraded modes": "no direct store access under any circumstance" rules out reading
  `meta.store_id` from `memory.db` directly, the only other source). Its identity check therefore stays
  **path-only** — comparing `store_db_path` against `health()`'s own reported `store_path` — on every
  connection, not only a store's first-ever one. This was tried two other ways and both were rejected on
  measurement, not merely on style: reading `meta.store_id` directly (both from the critical-path hook and
  from the detached warm helper) violates the unconditional no-store-access rule this whole client exists to
  hold, and a small sidecar file the hook writes and reads itself to remember a `store_id` across invocations
  is circular — whatever it would compare against on a later call was itself written from an earlier call to
  the *same* service, so a service that has gone stale without restarting reports the identical value both
  times and the sidecar never disagrees with itself. Path-only comparison genuinely cannot distinguish a
  correctly-running service from one serving a store that was deleted and recreated at the identical
  path — see §"Idle self-stop" for why that gap is closed on the *service* side instead, which is the only
  side with an independent way to notice.

## Filesystem security

The store is durable, unencrypted, plain-text knowledge about a project: build steps, env var names, which
services must be running, what failed and why. It deserves the same care as the socket, which the first
draft of this document gave only to the socket.

| Path | Mode | Rule |
|---|---|---|
| `<scope>/.zikaron/` | **0700** | created with an explicit `mkdir(0o700)`; if it exists with a wider mode, the service tightens it ~~and logs~~ **silently — `permissions.py` imports no logger, and on the service's own path it could not: `ensure_store_dir` runs in `service/main.py` as the argument to `configure_service_log`, so the correction happens before any handler is attached** |
| `memory.db`, `-wal`, `-shm` | **0600** | created under an explicit umask (`os.umask(0o077)`) around store creation, because SQLite creates the WAL/SHM itself and will otherwise inherit a permissive umask |
| `service.log`, `warmup.log`, `hook.log` | **0600** | `service.log` quotes prompts and error text; `warmup.log` and `hook.log` log only a fixed failure-kind label and an error code, never prompt or memory content, so neither can hold a leaked secret (`design/write-policy.md` §"The emergency erasure procedure, exactly"). Each is written by exactly one process, never shared |
| `config.toml` | **0600** | operator-written; no secrets by design, but it sits in the same private directory |
| `knowledge/` | **0700** | created with the store; absent until the first knowledge base exists |
| `knowledge/<uuid4>.db`, `-wal`, `-shm` | **0600** | created under the same explicit umask as `memory.db`, for the same reason. **A knowledge base holds the verbatim text of every file indexed into it**, so it is at least as sensitive as the memory store and is named here rather than left implied — this table enumerated neither until 2026-09-22, while `knowledge-index.md` asserted the mode from a document that is not normative for it |
| `$XDG_RUNTIME_DIR/zikaron/` | 0700 | must be owned by the running uid |
| `/tmp/zikaron-<uid>/` | 0700 | **validated before use**, not merely created |
| `<h>.sock` | 0600 | |
| `<store-hash>-<method>-<pid>-<random>.json` | **0600** | a consolidator tool result too large for the harness to deliver, written beside the socket, led by the same hash that names this store's socket so one store's files are findable among every store's, and named in a pointer the model reads back. Removed when the next group is requested, and any left by a dead process are swept when the next consolidator starts — **not** on this process's exit, which a harness terminating its MCP server never reaches. **Record prose verbatim, outside the store and outside the log rules** — so the erasure procedure names this directory, and the file is created through `os.open` with the mode supplied rather than written and then `chmod`-ed, since the window between those two is one in which that prose sits at the process umask |

Rules that go with the modes:

- **Reject, never repair, a hostile runtime path.** Before creating or using `/tmp/zikaron-<uid>/`: if it
  exists, it must be a real directory (not a symlink), owned by the running uid, mode 0700. Otherwise the
  service refuses to start there and the clients go degraded. Blindly `mkdir`-ing a predictable `/tmp` path
  and unlinking sockets inside it is the classic local symlink attack.
- **Never unlink a socket you have not vetted.** The start-if-absent sequence below unlinks a stale socket;
  it may only do so after confirming the path is a socket, in a vetted directory, owned by the running uid.
- **Refuse a store reached through a symlinked `.zikaron`.** `realpath` the store directory and require the
  resolved parent to be the **scope directory** (D17 as amended — under Claude Code deliberately not the
  spawning process's cwd). `core/store/permissions.py` documents how this is implemented: ancestor-symlink
  vetting rather than a comparison against an ambient cwd, which is what makes the clause survive the
  amendment unchanged.
- **Stated plainly: this is not authentication against the same user.** A 0600 UDS and a 0600 database keep
  *other* local users out. Every process running as the owning uid — including any other tool the user
  runs — can read the store and call the API. That is the same trust boundary as the user's own files, it is
  deliberate, and it is the reason TCP was rejected below. If Zikaron ever needs to defend against
  same-uid processes, it needs real authentication, and nothing here provides it.

## Lifecycle

### Start-if-absent, without a thundering herd
Both thin clients may race to start the service. Sequence:

1. Try to connect.
2. On `ENOENT` or `ECONNREFUSED`, take an exclusive `flock` on `<sock>.lock`.
3. **Try to connect again** — another client may have won and already started it.
4. Still dead: vet the runtime directory (§"Filesystem security"), unlink the stale socket if present, spawn
   the service detached (`start_new_session=True`, stdio to the log), then poll `health()` until a deadline.
5. Release the lock.
6. **Verify `store_path` from `health()` unconditionally, and `store_id` too whenever this client has an
   independent one to compare against** (§"Store identity is verified, not assumed") — before the first real
   request.

`ECONNREFUSED` on an existing socket file is the signature of a service that died without cleaning up —
unlink and respawn rather than reporting an error.

### First run: the service creates the store itself if one is not there yet
**Operator decision.** Nothing upstream of the service — no installer, no client, no separate bootstrap
step — creates `memory.db`. A fresh `.zikaron` directory with nothing in it, or no `.zikaron` directory at
all, is the ordinary state of a project that has never run Zikaron, not a misconfiguration to reject: a
design that required something else to create the store before the service could start would mean the whole
system can never reach its own working state from an empty directory unassisted.

So `zikaron-service`'s own startup (`ServiceContext.assemble`) checks whether `store_dir/memory.db` already
exists and calls `Store.create` instead of `Store.open` when it does not — `Store.create` itself creates
`store_dir` too if that is also absent, so this reaches all the way from nothing Zikaron-related in the
directory to a fully open, correctly-configured store. The check is the database file's own existence,
not a broader "did `open` fail" catch: `Store.open` shares its `bad_config` code across several genuinely
different causes (a missing required `meta` key, an unsupported `schema_version`), and only the specific
absence of `memory.db` may be silently treated as "create one" — every other `bad_config` cause is still a
real rejection.

The encoder's load *starts* before this decision is made, on its own thread, and only the create path
waits for it. `Store.create` needs the artifact itself — the configured embedder's actual width and model
name, checked against the effective config before any table exists, §"Creating the dense index" in
`schema.md` — so first-run startup still pays the cold model-load cost in full before it can proceed.
Opening an existing store needs no such thing, and §"The model loads behind the socket" below is why that
difference is worth having.

A second `assemble` against the same directory finds `memory.db` already there and opens it, exactly as
before this decision existed: creation happens at most once per store, on whichever startup is first to
find the file absent.

**A genuinely-empty directory reaches one step earlier than `ServiceContext.assemble` itself: `main.py`'s own
log setup.** `run()` configures `service.log` before resolving config or opening the store, deliberately —
either can fail, and a first-run `Store.create` failure must be as diagnosable from this process's own log as
any other startup failure (§"Idle self-stop" states the same reasoning for a different step). But
`log.configure_service_log` `touch`es `service.log` *inside* `store_dir`, so on a truly first-ever run —
`.zikaron` absent entirely, not merely `memory.db` — that `touch` itself raised `FileNotFoundError` before
`ServiceContext.assemble` was ever reached, which is exactly the case this whole section exists to support.
Found by running the create-on-absent path end to end against a real spawned subprocess rather than only unit-
testing `ServiceContext.assemble` in isolation, where a monkeypatched, pre-existing `tmp_path` had always
stood in for the directory. **Fixed by running the same shared, symlink-refusing, `0700`-enforcing validator
`Store.create` itself calls a moment later — `permissions.ensure_store_dir` — immediately before the log is
configured, never a bare `mkdir`.** A bare `mkdir` was tried first and rejected on review: it would have let
`log.configure_service_log` write into a directory reached through a symlink, or one left wider than `0700` by
an earlier build, before either had ever been checked — exactly the refusal §"Filesystem security" requires.
Calling the real validator here rather than a weaker one invented for this narrower purpose means
`Store.create`'s own later call against the identical directory is a no-op against a path this step already
left correctly vetted and at `0700`; the ordering the paragraph above states for *why* the log runs first is
unchanged, only *where the log file can land* needed a directory to exist first, and that directory's own
safety is never traded away to get one.

### The model loads behind the socket

**The measured problem.** A cold service takes about 1.2 s merely to bind its socket, and the push hook
gives a freshly spawned one about the same before it gives up and degrades. Loading the embedding model is
roughly 1.0 s of that — the great majority — and the socket bind depends on none of it. So the first user
message after the service has idled out loses its injected memories, silently, every time: the service is
working, it is simply not *ready* yet. The loss is bounded and self-healing, because the service the losing
attempt spawned stays up, but it costs one push per idle gap indefinitely, and the message most likely to
need memory is the first one after a break.

**So `ServiceContext.assemble` starts the load on a background thread and returns without waiting for it**,
on the open path. The store opens, the socket binds, `health()` answers, and the model finishes loading
behind all of it — inside the hook's own request budget rather than inside its readiness deadline, which is
the boundary that decides whether the push is delivered at all.

**Two properties answer immediately; five wait.** The encoder handed to the rest of the service reports the
*declared* identity — the model the configuration named, and the width the store recorded — without the
artifact. Everything that is genuinely a fact of the artifact (its special-token count, its sequence cap,
tokenization, embedding) blocks until the load finishes. That split is what keeps the deferral real: a
consistency check written against the declared identity costs nothing, and one written against the artifact
still cannot be answered without it.

**The identity check keeps its full strength and only moves.** The width the artifact actually produces is
compared against the store's recorded width by the loading thread itself, the moment the load returns —
still before any caller can reach a member that would use it, so no write is ever made through an encoder
whose vectors would not fit the index they are labelled for. What changes is *when* a disagreement is
discovered, not whether it is. The model *name* is deliberately not re-checked there, because the artifact
reports back the name it was asked for; a name that disagrees with the store is refused eagerly at
`Store.open`, against `meta`, before the socket exists.

**A failure now happens after the bind, so the service ends itself.** A load that raises, or a width that
disagrees, is latched and re-raised on every access. Left alone that would be the worst state this service
can occupy: `health()` answers from the store's metadata and never touches the encoder, so the process would
go on advertising itself as ready while failing every request that needs a vector — and start-if-absent
never replaces a server that is still listening, so an operator's corrected configuration would not take
effect until the idle timeout eventually fired, with every retry pushing that further away. Instead the
process stops itself, initiated by the loading thread the moment it latches rather than by whichever request
first trips over it, so a service nobody happens to call does not sit resident and mislabelled. The next
message spawns a fresh one against the corrected configuration, which is the ordinary recovery loop
restored. A request already in flight is usually answered rather than dropped — it wakes from the same latch
the watch does, so its `bad_config` normally reaches the model ahead of the teardown — but that is a race
and not a guarantee, since shutdown cancels handler tasks rather than draining them. Losing it costs nothing
that was ever delivered before: the equivalent failure used to reach the client as a poll deadline and
nothing else.

**One state this does not cover, named because the machinery around it looks complete.** Everything above
assumes the load terminates. A load that *hangs* rather than fails — a cold artifact download against a
network read with no deadline — never latches, so the watch never fires and `health()` goes on answering
`ready`. **A resident process is left either way**, and traffic decides only whether it stays reachable.
With no traffic, idle self-stop fires and the socket goes, so the next message spawns a fresh service — but
the process never finishes exiting, because the wait for the load runs on an executor thread that
cancellation abandons rather than unblocks, and interpreter shutdown joins it with no deadline. What is left
is unreachable residue holding neither store nor socket, until someone kills it. With traffic it is worse: the first request
needing the model blocks, `in_flight` never returns to zero, so idle self-stop cannot fire either and the
process stays reachable with start-if-absent unable to replace it. The hang is not new; what is new is that
it now happens behind a bound socket, on the far side of the same non-daemon-thread trap this project
already records for store connections.

**`health()` therefore speaks for the store and not for the encoder**, and both clients' readiness polls
must be read that way: they bound the wait for an open store, never for the first embedding.

### Idle self-stop

**Only the service has this lifecycle, and the distinction is not obvious from `ps`.** `zikaron-mcp`
is a client, not a server: the harness spawns it over stdio at session start and it lives exactly as
long as that session, with no idle timeout and nothing to self-stop. So a machine running three
Claude Code sessions shows **six** `zikaron-mcp` processes plus at most one service per store, and
that is the design working rather than a leak — observed being mistaken for one. **Add to the
census, while a knowledge base is building, a detached `python -m zikaron.knowledge.indexer` per
in-flight build**, which outlives the caller that started it and will saturate a core until it
finishes: the shape most easily misread as a runaway, in a paragraph whose entire purpose is to
stop a reader misreading a process listing. Two consequences
worth stating together: a client that has never called a tool opens no socket and starts no service
at all, and a *long-lived* client does not pin a service open either, because `may_stop` keys on
requests in flight and time since the last one, never on open connections.

`last_activity` is refreshed when each request completes. A background task polls every 30 s and exits
when idle exceeds `idle_timeout` (**default 30 min**) **and** no requests are in flight. On exit the socket
is unlinked before the process ends.

**By this process alone, and that is a property the code has to assert rather than inherit.** From Python
3.13 a closing `asyncio` Unix server removes the socket path itself, so the listener is opened with
`cleanup_socket=False` — supplied through `zikaron/service/asyncio_compat.py`, since the parameter does not
exist on 3.12 — and asyncio's own unlink-on-close never runs. That is what keeps the ordering this
service chooses intact on every supported version: **on the self-stop and signal paths** the unlink
comes *before* the close, so a client arriving mid-shutdown finds no socket and starts a fresh service
rather than connecting to one that is draining. (`main.run`'s error path closes first and unlinks
after; that is a recorded debt, not the intended ordering.) Two unlinkers would make the ordering
unobservable wherever it holds, and which of them acted would depend on the interpreter.

**That holds for a signalled exit too, and it rests on an ordering worth stating: the `SIGTERM`/`SIGINT`
handlers are installed *before* the socket is bound.** `serve()` publishes the socket the instant it binds,
so handlers installed after it would leave a window in which a signal takes its default disposition and the
file outlives the process — small, and wider under load. Installed first, a signal at any moment the file
exists is handled. Only a death this process **does not** handle — `SIGKILL` (an OOM kill included), a crash
in native code, any other signal left at its default disposition (`SIGHUP` and `SIGQUIT` are catchable and
deliberately uncaught), a power loss — leaves a stale socket, which is the case §"Start-if-absent" step 4
clears, and why the signature above names no cause.

**The same poll also checks for the store having been replaced out from under it, and stops immediately if
so — a second, independent exit condition alongside the idle one, not a variant of it.** `memory.db` being
deleted and recreated at the identical path while this process still holds it open is possible and invisible
to the service by any other means: SQLite's own open connection keeps its own already-open file descriptor
bound to the original inode regardless of what a later `unlink`+create does to the *path* — confirmed
directly, not merely assumed, though a further measurement below found this guarantee narrower than it first
reads: a genuine WAL-mode operation issued *after* the replacement can still fail with a real I/O error,
since a sidecar file WAL needs cannot be created next to a main file whose own directory entry is gone, so
"keeps serving" describes the connection's own binding, not a promise that every subsequent operation on it
will succeed regardless. Either way, nothing about a delete-and-recreate touches the running process
directly, and this is exactly the gap the hook's own identity check cannot close on its own (§"Store
identity is verified, not assumed") — a client comparing `store_path` alone against a stale service's
`health()` response would see the identical path both before and after the replacement, since the path never
changed; only comparing against the *file currently at that path* can tell the two apart, and that requires
nothing more than a plain `stat`, no read of the store's own contents.

**The baseline is read as a plain `stat()` of the path, immediately after `_open_connection`'s own
`aiosqlite.connect()` returns, with no `await` between the connect and the read — captured once, on the
operator's own explicit direction, rather than closed by further engineering.** Several deeper mechanisms
were tried and each independently measured wrong, all in pursuit of a narrower race than the one this
baseline actually needs to defend against: a replacement landing in the specific, sub-millisecond window
inside `aiosqlite`'s own cross-thread connect handoff, between SQLite binding to a file on its worker thread
and this coroutine resuming to read the path (`aiosqlite` queues the real `sqlite3.connect()` call onto its
own dedicated worker thread and only resumes the awaiting coroutine once that thread hands the result back
across `call_soon_threadsafe` — confirmed by reading `aiosqlite`'s own source, `Connection._connect`,
directly). Pinning a file descriptor and connecting through its own `/proc/self/fd/<n>` path — reasoned to
sidestep pathname resolution entirely, since that magic symlink resolves directly to the descriptor's own
file rather than by re-walking the original name — was measured, empirically, to *not* actually do so:
`PRAGMA database_list` shows SQLite canonicalizes that path back to the ordinary pathname internally, and a
file replaced at the path while an existing connection is live can make even an *already established*
connection fail on its next statement, proving the assumption the whole mechanism rested on was false, not
merely incompletely implemented. Closing this properly would require controlling SQLite's own VFS-level file
handle directly (a custom VFS or file-control integration), which the operator explicitly judged a
materially larger undertaking than this race's own shape warrants: it requires an adversarial replacement to
land inside a sub-millisecond window at process startup, not the ordinary case this whole mechanism exists
for — a store deleted and recreated while the service has been sitting open and idle, which the poll closes
completely, with no narrower timing assumption anywhere in it. **The decision, made on human authority: keep
the simple capture, accept the narrow startup-instant gap as documented rather than pursued further.**

Each idle poll thereafter re-`stat`s `memory.db` at the path this service resolved when it started, and
compares the reported inode against `Store.opened_inode` — confirmed directly (not merely reasoned about
SQLite's own fd semantics): an already-open connection's own `os.fstat` continues reporting the original
inode after the path is unlinked and a new file created there, while a fresh `os.stat` on the path reports
the new file's inode immediately. A mismatch, **or the path stat-ing as absent entirely**, means this
process is serving a store that is no longer the one currently on disk at its own path, and the correct
response is identical to idle self-stop's own: unlink the socket, shut the server down, and exit — never
attempt to somehow "catch up," since the store this process has open is not the current one to catch up *to*.

**Any other stat failure is not folded into this decision.** A genuine `PermissionError` or similar is not
"replaced," and treating it as one would make an unconditional shutdown decision on behalf of a caller that
may have wanted to know about a real, different problem instead — it propagates out of `idle_self_stop`
uncaught. Two separate mechanisms in `main.py` are what turn a propagated failure like this into a genuine,
surfaced process failure rather than either kind of silent discard: `_raise_if_any_task_genuinely_failed`
handles the ordinary case, where the failing task is already in the `done` set `asyncio.wait` returned; and
`_surface_any_genuine_task_failure` handles the narrower race where a signal wins that earlier snapshot while
the failing task is concurrently being cancelled — its exception then arrives only as a *return value* of the
cancellation `gather(..., return_exceptions=True)`, which converts every exception into a result and would
otherwise let a non-`ShutdownTimeoutError` failure vanish silently exactly the way `ShutdownTimeoutError`
alone used to be the only exception either mechanism routed anywhere.

**`_surface_any_genuine_task_failure` must not itself become a second masking site — and checking only
*whether* a primary was already active was itself found insufficient.** It runs from inside a `finally`
block, and `raise outcome` there runs unconditionally regardless of whether a *different* exception was
already propagating into that block — from `asyncio.wait` itself, or from
`_raise_if_any_task_genuinely_failed` — which would otherwise **replace** that earlier, primary
failure with whatever a task being
cancelled happens to raise from its own teardown handler, surviving only as the secondary's `__context__`
rather than as what the caller actually sees. This is the identical class
`_close_context_preserving_any_active_failure` already guards against for the *outer* cleanup,
applied here for this *inner* one: the
caller reads `sys.exc_info()[1]` as the very first statement in the `finally`, before cancelling anything,
and passes that exception *object* into `_surface_any_genuine_task_failure` explicitly — not only a boolean
that one is active. A version keyed on a boolean was itself found wrong:
`_raise_if_any_task_genuinely_failed`'s own raise leaves the failing task still `done()` and still
holding that identical exception object,
which `gather` genuinely reports again during cleanup for the *ordinary* case where nothing else concurrently
failed — a boolean-only check could not distinguish that reappearance from a genuinely distinct secondary
failure, and logged the ordinary case as a misleading "secondary failure" on every single lifecycle-task
crash. Checking identity — `outcome is not primary_exception` — is what tells the two apart.
`ShutdownTimeoutError` is exempt from this check and always routes to its own terminal path regardless — it
calls `os._exit` and never returns, so there is no propagating caller for it to displace anything from. A
genuine, *distinct* non-timeout secondary failure found while a primary is already active is logged rather
than raised, so it stays visible to the operator without silently taking the primary's place. Whichever hook
or MCP client next runs start-if-absent against the now-empty path spawns a fresh, correctly-identified
service against whatever store now genuinely exists there, within one more poll cycle of the replacement at
the very most.

**The race this creates must be handled in the client, not wished away:** a client can connect just as the
service decides to exit, and its request then fails. `zikaron-mcp` retries once through the full
start-if-absent sequence before falling back — a genuine second full attempt, since it is a long-running
process with no reason not to. **The hook does not**: its own single outer attempt (§"Degraded modes") never
retries the sequence, since a second attempt is exactly the wait D12's whole hook-thinness argument exists to
avoid. **"Falling back" differs by client accordingly, and only the hook's own fallback logs to `hook.log`
and relays a failure instruction rather than answering with anything read from the store** (§"Degraded
modes"): `zikaron-mcp` has no equivalent requirement, since a tool call answers a model that is actively
waiting on it rather than a background push nobody is watching for. A retry that still fails — the store
genuinely unreachable, not merely a service that happened to exit between two requests — surfaces as an
ordinary MCP tool error the calling model sees, naming the transport failure, exactly like any other
rejection the service itself could have sent; there is no second, silent fallback path for the MCP client to
take instead.

An active consolidation run does **not** keep the service alive on its own — a run is a store-level lease
(§"Consolidation lifecycle"), not process state, so a service that stops mid-run loses nothing.

**Shutdown itself is bounded, and a failed graceful shutdown ends the process anyway.** Closing every open
connection during shutdown — required so a client that finishes a request and keeps its socket open (the
documented norm above) does not block `wait_closed()` forever — carries its own 5 s deadline, and that
deadline raises loudly rather than hanging if a handler task never finishes cancelling. **Directed by the
human operator** (M9's own review found this exact class of defect repeatedly during development, at
increasing depth, culminating in a narrow accept-pipeline race inside `asyncio`'s own internals that would
require replacing the whole connection-accepting mechanism to close provably): the graceful path stays
exactly as built and is tried first and only once; if it has already tried and failed — the 5 s deadline
elapsing — the process forces its own exit immediately rather than continuing to chase every asyncio-internals
edge case that could theoretically leave something open. A deployed service has no one reading its log at the
moment it needs to exit, and normal interpreter shutdown is not guaranteed to finish quickly either once
something has already failed to close in time. This is a deliberate choice of engineering effort, not a claim
that the graceful path is airtight against every internal race in a dependency this project does not own.

### Warming
`agentSpawn` fires at session start (D18). The **hook process** prints the write policy — static text, no
RPC, so it can never fail — and spawns a **detached warm helper**, then exits. (Both steps are skipped entirely
in a subagent session: §"Subagent sessions".) The helper does the work that
can fail: start-if-absent and `health()` polling to a deadline. It writes to its own `warmup.log` — via stdlib
`logging`, since it runs detached and off the user's critical path so the ~15 ms interpreter cost of importing
`logging` is irrelevant here — rather than to the hook's stdout, and its failure is invisible to the session.
`warmup.log` is not `service.log`: the helper and the service are two independent processes, and two
processes writing one file through `logging.FileHandler` with no cross-process locking is a corruption risk,
not a convenience — see §"Paths". That way the service is already warm before the first `userPromptSubmit`,
and the first push of a session is not the slow one.

**The split matters and blurring it was a real contradiction:** "the `agentSpawn` hook talks to the service" and
"the `agentSpawn` path makes no RPC" cannot both describe one process. The hook process makes no RPC; its
detached child does the start-if-absent work, on a path no user message waits for. The helper used to carry a
second job — a `register_session` call feeding the ladder's derived rung — and that job is gone with the rung
(§"Both clients resolve the same label"). Warming is the whole of what it does now.

## Subagent sessions — the push hook suppresses itself

> **Harness delta (D34).** Everything in this section describes **kiro**. Under Claude Code
> `UserPromptSubmit` does not fire for subagents at all, so this rule is **inert** rather than ported — the
> door it guards is closed by the harness — and `SubagentStart`/`SubagentStop` carry `agent_type`, so the
> over-breadth accepted below (suppressing *all* subagents because the payload carries no agent identity)
> **does not apply there and must not be copied into it**. `design/harness.md` is normative.


**Hooks fire for subagent sessions.** Measured 2026-08-01 (§"Both clients resolve the same label"): a `py-runner`
subagent's `agentSpawn` and `userPromptSubmit` both fired, each carrying the subagent's *own* `session_id` in the
payload while `KIRO_SESSION_ID` still held the top-level session's. That is a problem, and not a small one.

**Why it matters: it reopens a hole D32 closes on purpose.** D32 withholds `search` and `fetch` from the
consolidator so that code, not the model, picks what it sees — the enforcement mechanism behind D7. The
consolidator runs as a subagent. A `userPromptSubmit` push into a consolidator session injects five gists chosen
by a similarity function over the whole store, which is `search` by another name, delivered through a door D32
does not guard. `agentSpawn` is the same argument one step earlier.

**The rule.** The hook reads `KIRO_SESSION_ID` from its environment and compares it to its payload's
`session_id`. When they **differ**, this is a subagent session and the hook **prints nothing and exits 0** — for
`userPromptSubmit` *and* `agentSpawn`. When they match, or when `KIRO_SESSION_ID` is absent entirely, it proceeds
normally. This is the first check either hook makes, ahead of the RPC and ahead of the degraded chain, so a
suppressed turn costs one `os.environ` read.

**The over-breadth is real and accepted.** The hook payload carries **no agent identity** — its keys are exactly
`cwd`, `hook_event_name`, `session_id` and, on `userPromptSubmit`, `prompt` (verified against the probe log) — so
the hook cannot tell the consolidator from any other subagent and suppresses **all** of them. Three things make
that the right trade for v0:

- A subagent that genuinely needs memory can still **pull** through MCP, which is the D12 arm that does not
  depend on a hook at all.
- A subagent's own agent config can carry policy in its prompt, which is where per-agent behaviour belongs
  anyway — the same place D18's write policy would go if it were not injected.
- The failure directions are asymmetric. Suppressing a subagent that wanted a push costs it a convenience it can
  recover by asking. Pushing into the consolidator costs D32 its only enforcement mechanism, silently.

**What is *not* suppressed, and should not be.** An MCP client running inside a subagent reads the **parent's**
`KIRO_SESSION_ID`, so its writes attribute to the top-level session — the unit every D30 signal is defined over —
with `client.kind` distinguishing who wrote. Suppression is a rule about *pushing into* a subagent's context, not
about a subagent's ability to record what it learned.

### What the shared label affects, since the consolidator now holds the session's own

Rounds 3–8 gave the consolidator a label of its own — derived, or minted. It now presents the **top-level
session's** label, which is what makes D30's signals count consolidation against the session that asked for it.
Three consequences, stated because two of them touch settled guarantees:

- **Cross-session mutual exclusion on the consolidation lease is unaffected**, and that is the case the lease was
  built for. Two kiro sessions sharing one store have different `KIRO_SESSION_ID`s, so a run owned by one still
  yields `{busy: true}` / `group_expired` to the other (§"Consolidation lifecycle").
- **Two consolidators launched from the *same* top-level session must still exclude each other, and this is now
  mechanized on `pid`.** They present one label, so `session_id` alone can no longer tell them apart — the second
  would read the first's run as *its own*, recover the lease rather than being told it is busy, and be served a
  group the first still holds. **Ownership is therefore `(session_id, pid)`, not `session_id`**, matched against
  the `pid` the envelope already carries. A caller whose pair does not match the effectively-active run's is not
  the owner, and what follows depends on which entry point it used: `next_group` — the path a *model* drives —
  answers `{busy: true}` until the lease lapses, so an expired lease is taken over implicitly and keeps crash
  recovery working, while an **explicit `plan_groups` takes an unexpired run over** and records it `taken_over`
  (§"Consolidation lifecycle"). The asymmetry is deliberate: no model may decide another worker has stopped, and
  a human invoking the skill again is the only evidence that it has. This costs no schema change — `consolidation_run` already records `pid` — and no
  per-instance envelope identity, which is exactly the machinery the 2026-08-01 measurement removed.

  Why mechanize rather than accept it: the run lease is not only mutual exclusion, it is what makes D29's
  transitive merging true. Groups are processed oldest-first *with the store updated as we go, so a later group
  can merge into a memory an earlier group just created*. Two workers interleaving on one run make merge
  decisions over overlapping topical neighbourhoods without seeing each other's output, and that property
  disappears silently — the writes all succeed, the consolidation is merely worse. Failing closed at the write
  (invariant 9 revokes the loser's receipt on the first version bump, so it gets `version_conflict` rather than
  clobbering) protects the *rows* and not the *reasoning*, which is why row-level safety was not sufficient here.

  Residual, stated: the OS may recycle a pid, so a fresh process could inherit a dead consolidator's ownership
  inside one lease window. The consequence is benign — it inherits a run it is entitled to continue — and the
  alternative costs the identity machinery just deleted.
- **D26's receipts would have pooled across the session's clients, so `read_receipt` gained `client_kind` to its
  key.** On the old `(session_id, memory_uuid, version)` key a receipt minted by `next_group`'s serve would also
  have licensed the *primary* agent to `amend` that row at that version without having `fetch`ed it. Lost-update
  protection never depended on the receipt — the version must still match — but D6's read-before-amend would have
  decayed from *this agent read it* to *some client of this session did*. The key is now
  `(session_id, client_kind, memory_uuid, version)` (`schema.md` invariant 9), so the consolidator mints and
  spends `kind='consolidator'` receipts while `fetch` and `amend` both run as `kind='mcp'`, and each class of
  client consumes only what it earned. Process-level scoping stays deliberately absent: two MCP clients of one
  session do share receipts, which is latitude the design always granted a session. Worth noting the old design
  only avoided this in the `minted` case — an `ancestry`-derived consolidator label matched the session's and
  pooled identically, so this was a latent hole rather than a new one.

## Degraded modes — the hook must never block a user message, and it never reads the store itself

**The hook is never a reader of the store, under any failure.** An earlier draft answered any RPC failure with
a direct read-only BM25 query, reasoning that a transport failure (the service unreachable or not yet started)
is a different kind of problem from a store failure (`bad_config`, `reindexing`) and could safely be routed
around by reading the store directly. That distinction was real, and it produced a genuine defect: `bad_config`
and `reindexing` had to be carved out as non-fallback special cases, the fallback then had to re-validate the
same configuration and sentinel state the service itself would have checked, and the hook — a process
explicitly kept model-free and stdlib-only for latency reasons — ended up as a second implementation of the
service's own read path, one that had to stay in lockstep with it by hand. **The fallback was a bypass, not a
resilience mechanism**: it let the hook answer a store problem by opening the store anyway, which is exactly
what a degraded mode should not do when the reason for the degradation is unknown to the client experiencing
it. There is no failure classification left to make, because there is no case where the hook proceeds.

So `zikaron-hook` for `userPromptSubmit`, in order:

0. **Subagent check** — if `KIRO_SESSION_ID` is present and differs from the payload's `session_id`, **print
   nothing, stop** (§"Subagent sessions"). **No RPC. Under kiro, no log line either** — but under
   Claude Code payload and environment are invariantly equal, so a divergence means the harness was
   misdetected, and the branch writes one `session_env_mismatch` line to `hook.log` via
   `tripwire.record_if_misdetected` (`harness.md` §"The tripwire"). *"No log line" was unqualified in
   a numbered sequence that serves both harnesses, in a section carrying no harness-delta note.*
   This is unrelated to the failure path below;
   it is not a failure at all.
1. RPC `memory_surface(prompt, limit=5)`. On success, print what the service returned.
2. **On any failure — transport, startup, contention, identity, or a store error** — `ENOENT`, `ECONNREFUSED`,
   spawn failure, `health()` never ready, the internal deadline, a `store_identity` mismatch, `−32020
   store_busy`, `−32023 bad_config`, `−32022 reindexing`, or anything unexpected: **append one line to its own
   `hook.log`** naming the failure kind and, where one exists, the error code, **and print a short,
   model-facing instruction to stdout** asking the agent to relay the failure to the operator, naming the same
   kind and pointing at `hook.log` for the exact detail. Never open the store, never read it, never write to
   stderr. `hook.log`'s own line is a **direct file write, not `logging`**: `open(path, "a")` and one
   `.write()` call, then close — `logging`'s import cost is ~15 ms on this machine, measured directly against
   the same interpreter-cost argument that keeps this client stdlib-thin in the first place, and a process that
   writes exactly one line per invocation and then exits has no log lifecycle for `logging`'s formatters and
   handlers to manage. `hook.log` is its own file, not `service.log` or `warmup.log` — three independent
   processes, three files, so an operator checks all three rather than one, but none of them can corrupt
   another by writing at the same instant (§"Paths").

There is no step 3 or 4. What made the removed fallback tempting is also why it is refused: a BM25-only read
degrades gracefully in isolation, but the hook has no way to tell *which* failure it is looking at with any
confidence a config error or an in-progress reindex haven't already invalidated the very keys and sentinels a
safe read would need to check first — and a client that has to re-derive the service's own preconditions before
it can act on them is not a fallback, it is an unsupervised second copy of the service. Logging the failure
kind is strictly better for diagnosing *why* pushes are degraded than a silent, sometimes-successful read would
have been: `hook.log` now says "reindexing" or "bad_config" or ~~"ECONNREFUSED"~~ **"transport"** in
the exact moment it happened, rather than leaving an operator to infer the cause from an
intermittently missing injection.
**`ECONNREFUSED` is never a word `hook.log` holds**: `hook/connect.py` folds it and `ENOENT` into one
absent-server signature, and `hook/push.py` degrades every unreachable-service case to the fixed word
`transport`, which is what keeps the file to the closed vocabulary this section's error table names
rather than arbitrary exception text.

**Failure reporting went through three shapes before landing here, and the final one is measured
rather than reasoned about.** The first shape was total silence on every channel, with the theory
that a push failing quietly every message while the service stayed down would "nag" less than a
visible warning would. A second shape tried reporting on stderr and exiting non-zero, reasoning
from kiro's own documentation that a non-zero, non-two `userPromptSubmit` exit "shows STDERR to the
user as a warning." **A live spike against a real kiro session measured that reasoning wrong.** A
hook wired to a script that printed a distinct stdout instruction, printed a distinct stderr line,
and exited 1 produced no sign of the stdout instruction in the model's own response (the identical
script printing the identical stdout instruction on exit **0**, in the same session, *was* echoed
back verbatim), and the operator reported the stderr line "nowhere visible" — no inline warning, no
visible surfacing anywhere. So on this build, a non-zero exit suppresses the one channel already
confirmed to work — exit-0 stdout, which the same spike confirmed reaches the model's context and
gets relayed in its own response — while not visibly delivering on the channel it was traded for.

**The rule that survives that measurement:**

- **Always exit 0, unconditionally.** Nothing about this hook's failure modes is the
  `preToolUse`-only blocking case exit 2 exists for, and a non-zero exit is now confirmed to cost
  the one channel that works rather than buy anything in return.
- **Never write to stderr.** Confirmed, not merely reasoned about, not to surface visibly on this
  build — there is nothing to gain by writing to a channel with no observed effect, and every
  reason from the original design (a memory system having a bad day must not nag the user with a
  warning line) still holds for whatever channel stderr does reach.
- **On a failure, report it on *two* channels, both landing where they are each confirmed to
  work: `hook.log`, unchanged — one line, naming the kind and, where one exists, the wire error
  code, for whenever the operator wants the exact, verbatim record — and exit-0 **stdout**, a
  short instruction asking the model to relay the failure to the operator in its own words.**
  Paraphrasing here is accepted deliberately: the instruction's own job is a low-friction "something
  is wrong, go look" nudge, and it explicitly points at `hook.log` for the operator who wants the
  exact detail rather than the model's summary of it. This is not the same shape as an ordinary
  push result — the model is told plainly that this is a notice to relay, not gists to reason
  about — but it uses the identical channel `surface`'s own successful output already uses, since
  that is the one channel this milestone measured actually reaching the model.
- **Enforce an internal deadline of ~2 s**, far under the `timeout_ms` the harness enforces on the
  whole hook command. Failing fast beats being correct and late, because the user is waiting.

  **That harness figure is 10 s, not 30 s, and the correction is worth stating rather than quietly
  applying.** `research/kiro-cli-hooks-and-introspect.md` reported a 30 s default from the public
  documentation, and this document, `push.py` and `connect.py` all repeated it. The installed
  harness's own embedded documentation (kiro-cli **2.16.0**, doc commit `106ed7591`) states
  `timeout_ms` **default 10000 ms** — and the array hook format's `timeout` field in **seconds**,
  default 10, which is the same number in different units. The ~2 s deadline was never at risk, so
  no behaviour changes; what changes is that a shipped hook entry now **states `timeout_ms`
  explicitly** (§"Distribution artefacts") rather than inheriting a default the corpus had recorded
  wrong, which is the whole reason the wrong figure was harmless here and would not have been
  somewhere the margin was thinner.

## A result too large to deliver — the client spills it to a file

A harness caps what one tool result may carry. Claude Code's cap is stated in **tokens**, is never named
numerically, and an over-large result is replaced wholesale by an error notice — so the consolidator sees no
group, cannot decide it, and is served the same group again on the next call. A run cannot advance past such
a group, which was observed in production before it was understood.

**The harness writes the result to a file itself, and that file cannot be read.** It holds the tool's JSON on
one line, and `Read` states outright that such a file "cannot be paginated by line" — measured: 31,247 of
104,179 characters returned, and `offset`/`limit` refused. So recovering the payload through the harness's
own spill is unavailable however the tool grant is arranged, which an earlier attempt shipped prose asserting
the opposite of.

**What works is writing the file ourselves.** `Read`'s cap applies per read, not per file: a 206,719-character,
2,002-line file was read to its end in three calls. A payload is therefore fully recoverable if, and only if,
whoever wrote it made it **line-paginable** — the one thing the harness does not do. `zikaron-mcp` serializes
an over-threshold consolidator result pretty-printed, writes it to the runtime directory, and returns a small
pointer naming the path.

**Both bounds are proofs rather than margins**, which is what keeps them from needing revision as corpora grow
or the harness moves a cap it has never published. A token spans at least one byte, so bytes bound tokens for
any content — emoji, CJK, minified code — for any counter that does not expand its input before counting,
which byte-level BPE cannot. `consolidation.spill_threshold` (27,000 bytes) is therefore at most 27,000 tokens,
under the ≈29,923 the harness was observed to deliver; `SPILL_MAX_LINE_BYTES` (24,000, a fixed constant) is at
most 24,000 tokens, under `Read`'s measured 25,000. No characters-per-token ratio appears in either argument.
Indentation splits JSON *structure* and never *strings*, so a record's `content` stays one line however the
document is formatted — which is why the line bound exists rather than being implied by pretty-printing, and
why a record too long to serialize within it is **refused loudly** rather than written into a file whose tail
nobody can reach.

**Consolidator mode only, and gated on harness data rather than on a branch.**
`HarnessSpec.consolidator_can_read_files` decides both whether the agent config grants a
file-reading tool and whether the
client spills at all — one field, because the mismatches are what hurt: the tool without the file widens that
agent's reach for nothing, and the file without the tool hands it a path it cannot open. Under kiro it is
false, and what kiro does with an over-large result stays **unmeasured** rather than guessed at. The primary
client has no spill path at all; `register_primary_tools` takes no policy, so the scoping is structural.

Evidence: `research/claude-code-mcp-result-truncation.md`.

## MCP tool surface (the five memory verbs)

Tool *descriptions* carry the mechanics — the version precondition, the dedup payload, retire semantics —
because per D30 they sit in context at the point of decision, while D18's `agentSpawn` prose carries policy.

**Every tool name is `zikaron_<subsystem>_<verb>`, and the subsystem segment is load-bearing rather
than decorative.** One `--mode primary` process serves two stores that answer different questions —
agent-authored memories, and fragments of files nobody here authored — and a model choosing between
them reads the name before it reads the description. A bare `zikaron_search` beside
`zikaron_knowledge_search` reads as the general case of the other rather than as a different store,
and the call that follows costs a round trip to return a confidently empty answer about the wrong
corpus. The four consolidator tools carry `memory_` too: the store a tool rewrites is part of its
name, and the *mode* it runs in is not, since nothing a model reads tells it which mode it is in.

**The primary server registers more than these five, and this section is normative only for the
memory verbs.** The knowledge index's seven tools ride on the same `--mode primary` process and are
specified in `design/knowledge-index.md` §§8.3–8.5 — signatures, result shapes and descriptions
alike. They are named here so that a reader counting the tools on that server does not conclude one
of them is undocumented, and they are not duplicated here because two statements of one tool
surface is the drift this document spends its length avoiding elsewhere.

```
zikaron_memory_search(query: str, limit: int = 5, include_retired: bool = false)
  -> [{uuid, gist, tier, state, created_at, updated_at, superseded_by}]
     `state` ∈ live | superseded | retired, so triage can see a demoted row for what it is.
     Ordered by the total order in retrieval.md; the order is stated to the agent, best first.
     No version field, and therefore no licence to write. Empty store returns [].
     No `content` field either, and the description says so in those terms: a result is an
     abstract of a record rather than the record, and it names the moment to fetch — before
     asserting or acting on one. Both read paths carry that, in the same terms, because they
     hand back the same lossy thing and an agent meeting it on one path learns nothing about
     the other; retrieval.md §"Push output format" carries the push side and its reasoning.
     The description names zikaron_knowledge_search as where the other store is searched:
     this one holds what agents recorded, that one what the project itself wrote down.
     The pairing is stated on both tools (knowledge-index.md §8.3 carries the other half),
     because a model that knows only one of them searches the wrong store and finds nothing.

zikaron_memory_fetch(uuids: list[str])       # 1–50 uuids
  -> {records: [{uuid, gist, content, version, tier, active, state,
                 superseded_by, superseded_by_latest, superseded_by_latest_state,
                 created_at, updated_at}],
      missing: [uuid, ...]}
     Returns records in the order requested; duplicate uuids are collapsed to one record.
     Unknown uuids are reported in `missing` rather than failing the batch — a partial answer is
     more useful than none, and the agent needs to know which handle is dead.
     `superseded_by_latest` resolves the whole chain, and `superseded_by_latest_state` says whether
     that head is `live` or itself `retired` — because an ordinary `retire` of a replacement makes
     a terminal component (schema.md invariants 6–7), and "replaced by 5d81…" is misleading if
     5d81… is also no longer true. This is the one place the graph is walked for the agent.
     Carries the same untrusted-reference frame the push block, `zikaron_memory_search` and
     `zikaron_knowledge_search` carry, and it is the surface that most needs it: it is the only one returning `content`,
     which the write policy discourages from being instruction-shaped and v0 cannot check — and
     the push block's own "fetch before you assert" sends more reads here by design.
     **Mints a read receipt** for every record returned (schema.md invariant 9), which is what
     licenses a later write. It is the only way to license a write to a row this session did
     not itself just write, or just receive back in a conflict payload.

zikaron_memory_remember(gist: str, content: str)
  -> {uuid, version, near_duplicates: [{uuid, gist, cosine, rank}]}
     Writes unconditionally, then reports near-duplicates (D15, D32). The dedup search runs
     after insertion, in the same transaction, and **excludes the row just created** — it is its
     own nearest neighbour otherwise. It reuses the new row's first-chunk embedding for the dense
     arm and the new row's own `gist + content` for the lexical one, so it costs no second embed
     call (retrieval.md §"Two kinds of query"). Candidates are restricted to **`active = 1`** rows,
     across both tiers — the offered resolution below is `amend`, which rejects inactive rows, so a
     retired candidate would be an offer the agent cannot take (schema.md §"Consumer filters").
     At most the effective config's `dedup_max` (default 3) rows are returned, each with
     `s(new row → candidate) ≥ dedup_threshold` (config) (default 0.80, and the direction is part of the
     definition — `schema.md` §"Configuration keys"), in the total order.
     `near_duplicates` is **candidates to compare, never an assertion of duplication**, and the reason
     is what the evidence supports rather than what an earlier draft claimed. It said "the pairs above
     this cosine are dominated by near-miss twins", which nothing measured: the approved instrument
     measured query→passage cosines on synthetic passages, not memory-to-memory similarity, and no
     duplicate population was measured at all, so where twins or duplicates sit relative to 0.80 is
     unknown. What *is* measured is the signal, not the threshold — with topic held constant a
     near-miss identifier buys only ~a fifth of the separation a plainly distinct token gets
     (discrimination index 0.194–0.233), so the dense score is weakest exactly where a
     `WidgetV1` / `WidgetV2` pair has to be told apart, and merging one of those manufactures a record
     false in both directions. So the tool asserts nothing and the agent reading both gists is the
     thing that can tell them apart.
     The new row is live regardless. Resolving a duplicate the agent agrees with takes two further
     calls and the tool description says so — `zikaron_memory_amend` the older row, then
     `zikaron_memory_retire` the new one with `superseded_by` = the older uuid.
     Until then both are live and consolidation
     will group them. Mints an `own_write` receipt for the new row.

zikaron_memory_amend(uuid: str, version: int, gist: str, content: str)
  -> {uuid, version}
   | {conflict: true, current: CONFLICT_RECORD}
     Full rewrite (D6). Requires a read receipt at `version` (D26). A version mismatch rejects and
     returns the current record — one CONFLICT_RECORD, the single shape defined below — and the
     payload itself mints a receipt at the current version, so the agent really can re-decide in
     one round trip.
     Mints an `own_write` receipt at the new version.

zikaron_memory_retire(uuid: str, version: int, superseded_by: str | None = None)
  -> {uuid, version} | {conflict: true, current: CONFLICT_RECORD}
     Soft only (D16). `superseded_by` set = superseded, and stays retrievable-but-demoted;
     omitted = retired outright, and drops out of default retrieval (schema.md §eligibility).
     Same receipt and conflict rules as amend. `superseded_by` must satisfy the graph rules in
     schema.md invariant 6 — no self-edge, no cycle, target not *already* retired-outright.
     Retiring a row that other rows point at is **legal** and produces a terminal component:
     the lineage is now "no longer true, with no replacement". Rows pointing at it stay eligible
     and demoted, and `fetch` reports the head's state so an agent is not sent to a dead row.
```

**The conflict record payload has one shape, everywhere: `CONFLICT_RECORD`.** `amend`, `retire` and all four
consolidator verbs return the same per-row object in `current` — one object for the single-row verbs, a list
for the multi-row ones — and it is defined here rather than per verb because the tool blocks above and below
abbreviated it three different ways:

> `CONFLICT_RECORD = {uuid, gist, content, version, tier, state, superseded_by, superseded_by_latest,
> superseded_by_latest_state}`

That is `fetch`'s record minus `active` (which `state` already encodes) and minus the timestamps. It carries
the resolved-head fields for the same reason `fetch` does — a conflict is often *how* an agent learns another
session already repaired the row, and being pointed at a replacement that is itself retired would restart the
loop it is trying to leave. The receipt a conflict mints is at `version`, the value in this payload.

**Why `search` returns no version — and the precise claim.** The loose form, "`fetch` is the primary agent's
only source of a version", is false as written: `remember` and `amend` return versions and mint `own_write`
receipts, and a rejected write returns the current version and mints a `conflict` receipt. The precise claim
is the one that actually holds:
> **`fetch` is the only way to license a write to a pre-existing row, absent an own-write or conflict
> response for that exact row in this session.**

So a row the agent authored this session it may amend directly; a row it only saw as a gist it may not. That
is what makes "read before amend" mean *read the content* rather than "saw a one-line gist", and the receipt
table is what makes it mechanical rather than a naming convention. `search` therefore returns no version:
not because a version is secret, but because holding one would otherwise imply a licence the agent has not
earned.

**Consolidation is deliberately not in the primary agent's tool set.** D10 has the *user* invoke a skill;
exposing it to the primary agent would let it fire the one expensive path on a whim. But the consolidator is
itself an LLM subagent, so it needs tools of its own — see the next section.

## Consolidator tool surface (4 tools, separate agent)

D10's consolidation subagent cannot use RPC directly; it needs tools. These are exposed by the same
`zikaron-mcp` server but gated to a shipped `zikaron-consolidator` agent config, so the primary agent's
allowlist never includes them.

**"Provably cannot reach" is structural, not a filter, and the mechanism is where the tool set is decided:
before either set of tools exists.** Each `zikaron-mcp` process is told which mode to run as at startup
(`--mode primary` or `--mode consolidator`, one per shipped agent config), and decorates only that mode's
own tools onto its one `FastMCP` instance — never both sets, and never every tool with one set hidden. A
consolidator process's `tools/list` cannot name `zikaron_memory_search`/`zikaron_memory_fetch`, because they were never registered as
callables on that process at all; a `tools/call` naming either has no handler to dispatch to. This is
different from an allowlist filtering every registered tool down to four: there is no allowlist, and no
moment at which the primary's tools exist in that process to be filtered out of.

Two rules run through all four signatures, and the first draft of this document had neither:

- **Every row a verb touches is named as `{uuid, expected_version}`** — targets, absorbed rows and discarded
  rows alike. Not just the merge target. Otherwise a primary agent that amends an absorbed journal row after
  it was planned into a group would have its repair silently retired by the consolidator, which is exactly
  the lost update D26 exists to prevent.
- **Completion is tracked per journal row, never per group.** A group with a mixed disposition — merge A,
  promote B, discard C — takes three calls, and the group closes only when its last member is dispositioned.

```
zikaron_memory_next_group()
  -> {group_id, run_id,
      anchor:          {uuid, expected_version, gist, content, created_at} | null,
      anchor_vacated:  bool,          # true when a planned anchor was no longer targetable at serve
      journal_entries: [{uuid, expected_version, gist, content, created_at}],
      candidates:      [{uuid, expected_version, gist, content, created_at, rank}],
      shard: {index, of},
      serve_count: int, n_gists_used: int,
      remaining_groups: int}
   | {done: true}
   | {busy: true, holder_session, holder_pid, expires_at}
     Groups are computed by code per D29 — anchored by retrieval, orphans by mutual-K plus a
     cohesion pass, served in a total order. The subagent consumes them; it does not choose them.
     `shard` is read straight out of the persisted row — `shard_index` and `shard_count`, both
     written at plan time — so it survives a restart without replanning a frozen subgroup. Indices
     are **1-based** and an unsharded group is `{index: 1, of: 1}`; schema.md invariant 19 is the
     completeness condition.
     `journal_entries` is the **served set** — this group's members with `disposition IS NULL` after
     serve-time re-validation, in group order (§"Serving"). It supplies the gists the candidate query
     concatenates, and on a re-serve it excludes every member already merged, promoted, discarded or
     vacated. **It is also this verb's remaining set**: its uuid projection is exactly what a write
     verb would report as `remaining_uuids` at this instant. The field is deliberately *not* repeated
     in this shape — a served set is non-empty by construction (§"Serving" step 2), so
     `remaining_uuids` on a serve could never carry the empty value that means *complete*.
     `remaining_uuids` belongs to the three write verbs (§"Row-level completion").
     `serve_count` is this group's delivery count **including this delivery**, so a first delivery
     reports 1 and the consolidator can see it is holding a group it has already been shown.
     `remaining_groups` is how many **other** groups of this run are still open — `status IN
     ('pending','served')`, counted after this serve's own transitions and **excluding the group
     being delivered**. The exclusion is the part worth fixing rather than leaving to a reader:
     the delivered group is itself still `served` and still has undispositioned members, so
     "groups remaining" could as easily have counted it, and two implementations would then
     disagree by one on every serve. Counted here as *work not in the consolidator's hands*, so a
     final group reports 0 and the skill can tell "this is the last one" from the payload.
     `served_at` is refreshed to the delivery's own timestamp on **every** serve, including a
     re-serve; it records when this group was last delivered, not when it was first.
     `anchor` is the long-term record the group was built around (null for an orphan group, and
     null with `anchor_vacated: true` if it stopped being targetable after planning) and is also
     the natural merge target. `candidates` are additional long-term records, ≤4, in retrieval
     order, and may be empty when the long-term tier is empty. Definition: consolidation.md.
     Every `expected_version` is the version whose prose is in **this** payload, re-read at serve
     time — not the version at plan time. **Mints read receipts** at those versions for the anchor,
     every journal entry and every candidate, so D26 is satisfied without giving the consolidator
     `fetch`. Anchor and candidates are also persisted as this group's authorization set
     (`schema.md` `consolidation_group_candidate`), which is what `merge` checks its target against.

zikaron_memory_merge(group_id, target: {uuid, expected_version}, gist, content,
                     absorb: [{uuid, expected_version}, ...])
  -> {uuid, version, remaining_uuids: [...], group_complete: bool}
   | {conflict: true, current: [CONFLICT_RECORD, ...], remaining_uuids: [...]}
     Rewrite an existing long-term record to absorb part or all of a group. `absorb` rows are
     retired with superseded_by = target.uuid (D25).
     All versions — target and every absorbed row — are validated **before** any mutation; one
     mismatch mutates nothing and returns the current record for **every** conflicting uuid, so the
     model can re-decide in one round trip.
     The target must be in this group's persisted authorization set — its `anchor` or one of its
     `candidates` — and must still be `tier='long_term' AND active=1` at mutation time, else
     `bad_merge_target`. **A merge never rewrites a historical row**: `superseded_by` is immutable
     once set (schema.md invariant 6), so a retired row given fresh prose would be neither current
     nor historical. A target retired between serve and call is normally caught earlier as a
     `version_conflict`, since retiring bumps the version. `absorb` rows must all be members, i.e.
     journal entries delivered in this group and not yet dispositioned.

zikaron_memory_promote(group_id, gist, content, absorb: [{uuid, expected_version}, ...])
  -> {uuid, version, remaining_uuids: [...], group_complete: bool}
   | {conflict: true, current: [CONFLICT_RECORD, ...], remaining_uuids: [...]}
     Create a long-term record from part or all of a group. Two forms, and which one runs is
     determined by the payload, not guessed: exactly one `absorb` row whose gist and content are
     byte-identical to the arguments ⇒ flip that row's tier in place (version still bumps);
     otherwise ⇒ insert a new long-term record and retire every `absorb` row with
     superseded_by = the new uuid.
     **Event cardinality differs between the forms, and is fixed rather than left to the
     implementation.** `new_row` emits one `role:'created'` event plus one `role:'absorbed'` event
     per absorbed row. `in_place` emits **exactly one** event, `role:'flipped'`, `form:'in_place'`,
     `n_absorbed: 1` — because the flipped row *is* the absorbed member and a singular role cannot
     say both. One mutated row, one event; see schema.md §"The `event` log, per kind".
     **The `flipped` row's four size fields are read off what the store already holds**, not
     recomputed by a chunking preflight: `token_count` from the `memory` row, `n_chunks` and
     `truncated` from that row's own `memory_chunk` rows, and `gist_tokens` counted over the stored
     gist. An in-place promotion changes no prose, so it rebuilds no index — and a preflight run
     under a `chunk_max_tokens` that has moved since the row was written would report an `n_chunks`
     the store does not contain. The `created` row of a `new_row` promotion is the opposite case and
     takes its four from the preflight that actually cut its chunks, exactly as `remember` does.
     The `gist_max_tokens` bound is checked on the **arguments**, in both forms, because bounds is
     rung 1 and deciding the form requires reading the absorbed row's stored prose — which is rung 2
     work. A store whose `gist_max_tokens` was lowered below an existing gist therefore refuses to
     promote that row in place until the consolidator authors a shorter gist, which is the `new_row`
     form; that is the same rule §Bounds already states for `amend` and not a second one.

zikaron_memory_discard(group_id, absorb: [{uuid, expected_version}, ...], reason: str)
  -> {retired: int, remaining_uuids: [...], group_complete: bool}
   | {conflict: true, current: [CONFLICT_RECORD, ...], remaining_uuids: [...]}
     Retire journal rows judged not worth keeping: active=0, superseded_by NULL (D16). `reason` is
     recorded in the event log, not in the store — a discarded row keeps its own prose.
```

**Concurrent write calls are correct but not ordered, and the shipped prompt says so.** Observed on the
first real consolidation run: a consolidator that emitted two write verbs in one turn saw one response's
`remaining_uuids` predate the other write. Nothing was mis-serialized — the committed event ids are
contiguous per call with no interleaving, and the store recorded zero `version_conflict` and zero
`no_receipt` — because `zikaron.mcp.connection` serializes concurrent calls on a connection lock and an
`asyncio.Lock` grants in arrival order, which for two coroutines dispatched together is not the order the
model listed them. So the second-listed call can run first and answer honestly about a moment before the
other. The store needs no change; what breaks is the model's own bookkeeping, so the consolidator's
prompt asks for one write at a time and gives that reason. Recorded here because the *absence* of an
ordering guarantee is easy to mistake for a store defect, and was.

**No `search` and no `fetch` for the consolidator.** Full content arrives in the group payload, and D7's
whole point is that *code* picks the candidates — giving the consolidator retrieval would let it wander
outside the group it was handed.

### Row-level completion is what makes the never-lose guard structural
`~/Memory` needs a nudge-×3 retry because it parses a free-text `===CONSOLIDATION===` block that may simply
not come back. Zikaron needs no retry protocol and no parser, but the guard only holds if it is defined at
the right granularity:

- **Every `merge` / `promote` / `discard` response carries `remaining_uuids`** — the group's members with
  `disposition IS NULL`, in group order — computed at response time from `consolidation_group_member`, in the
  success shape *and* in the `conflict` shape, so a caller learns the same remaining state whether its call
  landed or raced. A call rejected by an **error** (`not_in_group`, `bad_merge_target`, `group_expired`, …)
  carries `{code, message, data}` and no member list; it changed nothing, so the list the caller already holds
  still stands. **`next_group` does not carry the field**, and this is the one place to say why: on a serve the
  remaining set *is* `journal_entries` (§"Serving") and cannot be empty, while `{done: true}` and
  `{busy: true}` deliver no group to have members. Round 9 caught the earlier "every response" phrasing
  contradicting all three shapes this verb returns; shipping the set twice in one payload would have added a
  consistency obligation carrying no signal the payload does not already carry.
- A group is `complete` **only when that list is empty** (schema.md invariant 16). One write verb does *not*
  close a group.
- A verb naming an **empty** `absorb` list, or a uuid outside the group, or a uuid already dispositioned, or a
  member that left the journal after the serve, is an **error** (`not_in_group`) and changes nothing. Silence
  and typos cannot complete a group. That last case is recorded as `vacated` by the next serve, never by the
  rejected write (§"Validation precedence").
- Undispositioned rows stay `tier='journal' AND active=1`, so the next run plans them again. Nothing is lost
  by a consolidator that stops early, crashes, or returns nothing at all — and unlike a text protocol, that
  is a property of the store rather than of the model's cooperation. The same holds for a **deferred** group:
  bounding deliveries at `max_group_serves` gives up on a group *within this run*, never on its rows.

### Consolidation lifecycle — one transactional state machine

> **Harness delta (D34).** `pid` discriminates two consolidators in one session **only under kiro**, whose
> MCP server runs one process per agent instance. Under Claude Code one shared server process serves the
> whole session, so `(session_id, pid)` cannot tell them apart and `_PlanBridge`'s "at most once
> successfully per client process" bound becomes **per session**; a restarted *serving* process would be a
> spurious self-takeover of the session's own live run. Both are **accepted limits**, bounded — a spurious
> self-takeover costs in-flight reasoning and a replan, never a journal row — and cross-session mutual
> exclusion, the case this lease was built for, is untouched.
> `design/harness.md` §"Consolidation ownership under a shared MCP process".

`group_id` in the first draft was an opaque token with no owner, no lifetime and no persistence. Persisting
runs and groups closed that (`schema.md`), but persistence alone left four questions unanswered — what
happens to a member that changed between plan and serve, where the merge authorization set lives, whether an
incomplete group is re-served, and exactly when a run closes. All four are answered here, and the state
machine itself is `schema.md` invariant 17.

**Planning.** `plan_groups()` creates a `consolidation_run` with `status='active'`, a lease `expires_at` =
now + `run_lease` (**default 30 min**), and the full group/member snapshot with each member's `version_seen`.
Membership is frozen here. Planning is a pure function of the store plus the **effective config** (§"Configuration"), which is read once at
service startup and therefore fixed for a run, so it is
reproducible. Called implicitly by `next_group` when the store has **no effectively-active run at all —
whoever owns it**, in the precise sense defined below.

- **"Effectively active" is the only run test anywhere in this document:** `status='active' AND
  expires_at ≥ now`. A stored `'active'` row past its lease is not active to anybody, including the session
  that owns it.
- **One effectively-active run per store, and one *worker* on it.** If one exists and the caller is not its
  owner, `next_group` returns `{busy: true, holder_session, holder_pid, expires_at}` — a defined, deterministic answer, not
  an error and not a second plan. The skill reports it and stops. **Ownership is
  `(session_id, pid)`**, both already recorded on `consolidation_run` and both already carried by the envelope:
  since 2026-08-01 all clients of one kiro session share a `session_id`, so `session_id` alone would make two
  concurrently-launched consolidators the same owner. See §"What the shared label affects" for why one worker
  is required and not merely tidy — it is what makes D29's transitive merging true.
- **An explicit `plan_groups()` takes the run over, whoever holds it and whether or not the lease has
  passed.** That is the one deliberate exception to the paragraph above, and the reason is that *no evidence
  reachable from inside the store can tell a dead consolidator from one that is merely slow.* **A lease is a
  timer**, so it cannot: a worker deciding on a hard group and a worker that stopped ten minutes ago look
  identical to `expires_at`.

  **A pid-liveness check is not useless, and the honest reason it is not the mechanism is not that it cannot
  work.** Measured (`research/kiro-mcp-lifecycle-probe.md`): kiro runs one MCP client process per agent
  instance, so a consolidator subagent's client is its own process and it **exits when that subagent finishes**
  — meaning the pid recorded on the run is usually dead once the worker has stopped, and a check would often
  say so. What it cannot do is carry the weight alone. It answers *is this process alive*, never *is this
  worker going to make progress*, so a stalled-but-live worker still reads as healthy; pid reuse can return a
  false **alive** and prolong exactly the lockout being diagnosed; and the service and the client are not
  guaranteed a shared pid namespace. Its failure direction is at least safe — a false *alive* only continues
  the status quo — so it remains available as a future refinement rather than being ruled out.

  **What decides it is that a different signal is both simpler and categorically better evidence.** The
  question is not whether a process exists; it is whether the human wants this store consolidated **now**. That
  fact lives outside the store entirely: **a human invoking the consolidation skill a second time.** `plan_groups` is the RPC that
  intent arrives through, and treating that call as authoritative is what keeps a store from being pinned for
  up to `run_lease` by a worker that has already stopped.

  **The reachability claim, at exactly its true width, because three loose versions of it were in the corpus
  at once.** What D32 buys is this and only this: **a model confined to a configured tool surface cannot
  *request* a takeover**, since `plan_groups` is in neither the consolidator's four tools nor the primary
  agent's five — which is what preserves D7's "code selects the candidates, the model judges". Two things it
  does **not** buy. It is not a claim that the RPC goes uncalled: the *conforming consolidator client* calls it
  automatically, by design, on the first serve it forwards — which is the whole bridge below. And it is not a
  capability boundary at
  all: the socket is mode `0600` in a `0700` directory, so it is unauthenticated to **any same-uid process**
  (§"Filesystem security"), and an agent holding a shell can speak JSON-RPC to it directly. That is the trust
  boundary every other RPC already sits behind and nothing here widens it — what would be false is calling
  tool omission a *sandbox*.

  **The intent needs a caller, and naming one is part of this rule rather than a distribution detail.** A
  freshly spawned consolidator's own first tool call is `next_group`, which refuses a live foreign run — so
  without a bridge the second skill invocation reaches the refusal and takeover is unreachable, leaving the
  case it exists for unsolved. The bridge: **`zikaron-mcp`, when it starts under the consolidator agent
  config, calls `plan_groups` with its own `(session_id, pid)` — lazily, immediately before the first
  `next_group` it forwards, never when the client starts, and at most once *successfully* per client
  process.** The bound is on successes rather than on attempts, for the reason the state table below gives:
  a failed plan rolls back and displaces nobody, so it must not consume the guard. The *client process* makes that call, never the
  model, which is what keeps "no model decides another worker has stopped" true while still letting a human
  retry displace a corpse. M10 and M12 carry it as a done-when.

  **Lazily, because a lock must not be taken by a worker that has not asked for work.** The MCP handshake is
  eager: measured, a subagent's server completes `initialize` and `tools/list` within four milliseconds of
  starting and the first `tools/call` arrived 1.6 seconds later
  (`research/kiro-mcp-lifecycle-probe.md`). A `plan_groups` wired to startup would therefore fire before the
  model had been asked anything — so a consolidator that spawns, reads its prompt and stops, or one whose turn
  is cancelled before it acts, would displace a live worker for nothing. Deferring the call to the first
  `next_group` makes the trigger *spawn **and** an actual request for work*, which is strictly stronger
  evidence than the spawn alone, and it costs the client one boolean: it is a per-spawn process, so
  "have I already done this" needs no storage beyond memory.

  **Once, and only the client may count it — because the alternative livelocks.** Letting `next_group` itself
  take over from any stranger would make two concurrent consolidators oscillate without end: A displaces B, B
  displaces A, and neither is ever refused. Bounding it to one **successful** takeover per client process
  terminates instead: the second worker displaces the first, and the first's next `next_group` finds it has spent its one
  takeover and is told `{busy: true}`, so it stops.

  **The call is a prerequisite of the *serve*, not of the tools, and the bound is on *successes* rather
  than on attempts.** "Once per process" and "`store_busy` may be retried" cannot both be read as
  rules about RPC attempts — one of them has to give, and it is the attempt count, because a *failed*
  `plan_groups` rolls back and therefore displaces nobody. So the client is a three-state machine and the
  guard it holds is "have I planned successfully", not "have I called":

  | state | on a forwarded `next_group` | on the outcome |
  |---|---|---|
  | `unplanned` | call `plan_groups` first, and do **not** forward the serve until it succeeds | success → `ready`, then forward; `store_busy` → answer that error and stay `unplanned`, so the permitted retry replans; `index_failed` → `failed` |
  | `ready` | forward the serve directly, planning nothing | — |
  | `failed` | answer `index_failed`; plan nothing and forward nothing | terminal for this client; recovery is a new invocation, which is a new process with its own guard |

  The anti-livelock bound survives intact, because it was only ever about *successful* takeovers: at most one
  per client process, so a second worker displaces the first and the first is then told `{busy: true}` rather
  than displacing it back.

  **What the prerequisite guarantees, at exactly its width.** An `unplanned` client's first serve does not
  reach the service until that client has planned successfully — that is the failure the bridge exists to
  remove. It is **not** a guarantee that every serve reaches a run its caller owns: a `ready` client forwards
  directly and plans nothing more, so if another worker takes the store over in between, that serve does reach
  the service against a foreign run and is answered `{busy: true}`. That is not a gap — it is the same path the
  anti-livelock bound and the displaced-worker safety argument both require, and the ready client stopping
  there rather than replanning is precisely what makes them terminate.

  **The bridge rested on one environment assumption, and it is now measured rather than assumed.** It buys
  what it claims only if the consolidator's MCP client starts **once per skill invocation**, so that one
  startup means one human action. Measured 2026-08-02 (`research/kiro-mcp-lifecycle-probe.md`, raw records
  beside it): kiro runs **one MCP server process per agent instance** — two spawns of one subagent config
  produced two distinct pids, each a child of the session's single `acp` process, each given its own
  `initialize` handshake, and each exiting when its subagent finished. So a per-process guard is a
  per-invocation guard, which is what lets the bridge's "at most one **successful** takeover per client
  process" bound mean "at most one per human action" — the process boundary supplies the counter, the first
  forwarded `next_group` supplies the moment, and only a *success* consumes it. The same measurement is what confirms `(session_id, pid)` ownership is
  both sound and *necessary*: all three instances shared one `KIRO_SESSION_ID`, so the pid is the only thing
  distinguishing them. **What remains unmeasured** is whether kiro ever restarts a client mid-subagent for its
  own reasons — which would supply a fresh guard, and the next `next_group` that client forwarded could then
  consume it without a new human invocation; three instances showed no such restart, which is weak evidence at
  that sample size.

  **Takeover is safe against concurrent writes, and that is a property of the ladder rather than a hope.**
  Rung 2 of every consolidator verb requires the group's run to be owned by the caller *and* effectively
  active, so the displaced worker's very next `merge`/`promote`/`discard` is refused `group_expired` before it
  touches a row, and its next `next_group` finds the new run foreign and answers `{busy: true}`. It can
  therefore commit **nothing** after the takeover instant. What it loses is its in-flight reasoning — which is
  exactly what the human retrying has chosen to discard — and no journal row, because undispositioned members
  stay `tier='journal' AND active=1` and are replanned.

  **A taken-over run is recorded as such rather than folded into `abandoned`.** The two are different events
  with different costs — a worker restarting its own run discarded nothing it wanted, a displaced worker
  discarded work in progress — and in the likeliest case they are otherwise indistinguishable, since a user
  retrying in one kiro session produces the *same* `session_id` and only a different pid. So the status set
  carries `taken_over` and the `consolidate_run` phase mirrors it (`schema.md` invariant 17).
- **An effectively-expired run is absent, for every caller including its owner.** This is the fix for a real
  dead end: `next_group` replans only when the caller has no active run, so an owner whose lease lapsed used to
  find *its own* run, be served a group from it, and be rejected `group_expired` — with no way out, because
  `plan_groups` is a service RPC and not one of D32's four consolidator tools, so the documented advice ("call
  `next_group` again") returned the same rejection forever. Now `next_group` finding no *effectively*-active run
  — none at all, or only a lapsed `'active'` row, whoever owns it — calls `plan_groups()` implicitly. Crash
  takeover by a stranger and lease recovery by the owner are therefore the same code path, and neither needs an
  operator. **"Owner" means `(session_id, pid)`.** Since 2026-08-01 the consolidator presents the top-level
  session's label, so a session alone no longer identifies a worker; the pid distinguishes two consolidators
  launched concurrently from one session, and an *expired* lease may be taken over by anyone through
  `next_group` — an unexpired one only through the explicit `plan_groups` above. Crash
  takeover and owner recovery remain one code path. §"What the shared label affects" carries the argument and
  the pid-reuse residual.
- **`plan_groups()` closes any pre-existing `active` run, and two tests decide which status it writes:**
  `'expired'` if `expires_at < now`; otherwise `'abandoned'` when the caller **is** the owner and
  `'taken_over'` when it is not. It is the only producer of any of the three, and it emits
  the matching `consolidate_run` phase event. That also disambiguates rules that used to overlap —
  "`expired` only by a later `plan_groups`", "`abandoned` when the owning session replans", and a takeover that
  would otherwise be invisible — into one branch.
  Replanning is never incremental: a new run always plans from scratch, which is safe because undispositioned
  members stay `tier='journal' AND active=1`.
- **The lease is refreshed** by every successful call in the run — a write on a *success* path, which the
  rejection rule permits. **A `{conflict: true}` response is not a success for this purpose**, and that is
  worth fixing here because the conflict shape is a *return value* rather than an error and so could be read
  either way: it mutates no `memory` row and dispositions no member, its committed audit events and receipts
  are invariant 10's carve-out for a call that changed nothing, and letting it extend the lease would mean a
  consolidator making no progress at all could hold the store indefinitely. What refreshes the lease is a
  serve that delivered a group, or a write verb that dispositioned at least one member.
  **Expiry itself is never written by a rejected call.** Every reader treats
  `status='active' AND expires_at < now` as effectively expired and answers `group_expired`, changing nothing
  (`schema.md` invariant 17). Having any call perform the transition contradicted §"What a rejected call does
  and does not change", and this is the side that gave way.
- **What the owner loses on a lapsed lease, stated rather than implied:** the group it was holding. Its
  undispositioned members return to the next plan, so no row is lost (D29's never-lose guard), and the group ids
  it held are dead — which is why `group_expired` tells it to call `next_group` rather than retry. A consolidator
  making steady progress never reaches this, because every successful call refreshes the lease.

**Serving.** `next_group()` runs in **one transaction** and **iterates**, because a candidate group can turn
out to have nothing left to deliver. It considers groups of the run in this order:

1. the earliest `served`-but-incomplete group by `(order_key, shard_index)` — **re-served**, not skipped, so a
   consolidator cannot walk past a group it found hard by simply calling again;
2. else the earliest `pending` group.

For the candidate group the steps inside the transaction are **ordered, because the order is observable in
which status the group lands in**:

1. **Re-validate the members** — re-read each at its current version and mark a member that has left the
   journal `disposition='vacated'`; a planned anchor that is no longer targetable is dropped here too (full
   rules below). This runs first because everything after it depends on how many members are left. Dropping the
   anchor cannot change that count, so its position in the order is immaterial; the member marking is what
   decides steps 2 and 3.
2. **Zero undispositioned members left → close the group `complete`** and continue the loop. Nothing is
   delivered, so `serve_count` is not incremented and no `group_served` event is emitted: `pending → complete`
   directly, or `served → complete` on a re-serve.
3. **Otherwise, if `serve_count` is already equal to `max_group_serves` → mark the group `deferred`** and
   continue the loop. Completion is tested first on purpose: a group whose last member vacated is *finished*,
   and deferring it instead would leave a group with nothing left to decide looking abandoned for the rest of
   the run and inflating `n_deferred`.
4. **Otherwise serve it.** Recompute the candidates, persist the authorization set, mint the receipts, emit the
   `group_served` events, set the counter — `pending → served` sets `serve_count = 1`, a `served` group stays
   `served` with `serve_count` incremented — and return the payload.

**What a serve delivers is one set, named once: the *served set* = the group's members with `disposition IS
NULL` at the end of step 1.** It is **non-empty whenever a serve happens**, because step 2 closes a group that
has emptied before step 4 can run. Everything member-shaped in the serve is that exact set and nothing else —
`journal_entries` carries it in group order; the group-level candidate query concatenates *its* gists, so
`n_gists_used` counts from it (`consolidation.md` §"What `candidates` actually is"); one `group_served` event
with `role:'member'` is emitted per element; receipts are minted for its rows only; and it is where the write
verbs' `remaining_uuids` starts — they recompute that field from the member table as they disposition members,
which is how it shrinks within one delivery. The serve does **not** also ship the set under that second name:
it would duplicate `journal_entries` inside one payload, and it could never take the empty value the field
exists to signal, because step 2 has already closed any group that emptied (§"Row-level completion").
Round 8 found the served set implicit, and it is not a detail: two implementations reading
"the group members" differently authorize different `absorb` sets on the same store.

The set is a function of committed state at serve time, so a **re-serve delivers less** than the first serve
did — members a write verb already dispositioned (`merged`, `promoted`, `discarded`) and members vacated at
re-validation are all absent — and the recomputed candidate query is therefore not the same text the first
serve used. Both follow from the recompute rule below and neither is ambiguous. Re-delivering a dispositioned
member was the alternative and is wrong twice over: it shows the model prose it has already disposed of, and
`merge`/`promote`/`discard` reject an already-dispositioned uuid (`not_in_group`), so a model that named it
again would earn a guaranteed rejection for following the payload it was handed.

Frozen membership is untouched by this. `consolidation_group_member` remains the plan-time universe, and it is
still what invariant 16's completeness condition, `serve_count` and the never-lose guard are stated over; the
served set is the *payload* view of it, never a second source of truth.

`serve_count` counts **deliveries including the first**, so at the default `max_group_serves = 3` a group is
delivered at most three times in a run. That is fixed in `schema.md` invariant 17, along with why the other
reading — first delivery leaves the counter at 0 — would have permitted four.

When no candidate remains, the run is marked `complete` in that same transaction and `{done: true}` is
returned. The loop is bounded by the number of groups in the run, which is fixed at plan time.

**Why the loop exists, since an earlier draft returned the empty group instead.** Serve-time vacating can
disposition a group's *last* open member — every member of a small group retired by a primary agent, or the one
survivor of a re-served group promoted between serves. That left zero undispositioned rows with no write verb
having run, so nothing transitioned the group: it stayed `served`, was handed back empty, and was re-served
until `serve_count` hit `max_group_serves` and it went `deferred`. Three things were wrong with that — it
contradicted `schema.md` invariant 16's own completion condition, it spent the re-serve budget on a group with
nothing in it, and it delayed `{done: true}` behind groups that were already finished. The closure property in
invariant 16 — *no committed group is `pending` or `served` with zero undispositioned members* — is what this
loop enforces.

**Run behaviour on that path.** If a vacated-out group was the run's last open group, the run goes
`active → complete` in the same transaction and emits its `consolidate_run` event, and the call returns
`{done: true}` — so a run whose every remaining group vacated out finishes cleanly on one call. The vacating
itself is durable in `consolidation_group_member.disposition`, which is where it is meant to be recorded rather
than in the event log (`schema.md` §"The `event` log, per kind").

Serving is bounded, because an unbounded re-serve is a livelock: a group that has already been delivered
`max_group_serves` times (**default 3**, counting the first delivery) is marked `deferred` and skipped for the
rest of the run — step 3 of the ordering above. Its members stay undispositioned, so the next run plans them
again — the never-lose guard is untouched, and this is the one place `~/Memory`'s nudge-×3 idea genuinely
transfers: as a bound on redelivery of a *group*, not on parsing a block. The bound is on **deliveries**, so a
re-serve attempt that vacates out and closes the group `complete` never consumes any of it.

**What serving re-validates, and why the snapshot is not simply replayed.** `version_seen` is the plan-time
version, kept for change detection only. The payload must carry the version whose prose it actually contains,
because that is the version the receipt is minted at — we cannot deliver current prose under a stale version
without breaking D26, and we cannot deliver historical prose at all, because no history is stored. So, inside
the serve transaction:

- **A member whose version moved** is re-read; `version_served` is set to the current version and the current
  prose is delivered. A primary agent's repair therefore reaches the consolidator rather than being hidden
  from it, which is the outcome D11 wants.
- **A member no longer `tier='journal' AND active=1`** is marked `disposition='vacated'` and is *not*
  delivered. It left the journal by another path; nothing was lost and it blocks no completion. It emits no
  `group_served` event, precisely because none of its prose was delivered, which is what lets that event's
  `version_served` be non-null and mean what it says. If vacating leaves the group with no undispositioned
  member, the group is closed `complete` here and the loop continues — see the loop rule above.
- **An anchor no longer `tier='long_term' AND active=1`** is dropped: the group is served with `anchor: null`
  and `anchor_vacated: true`. Its replacement, if it has one, is active long-term and so is normally picked up
  by the serve-time candidate query anyway. The group stays servable; the consolidator can still merge into a
  candidate or promote.
- **Candidates are recomputed at serve time** (D29 processes groups oldest-first with the store updating as it
  goes, so a later group must see what an earlier one created) and then **persisted** to
  `consolidation_group_candidate` with the served versions and ranks, replacing any previous serve's rows.
  That table — not the `group_served` events, which are instrumentation — is the authoritative set a later
  `merge` may target.
- **Expiring or replanning the group instead was rejected.** It would unfreeze membership mid-run and destroy
  the reproducibility that makes planning a pure function.

**Completing.** A group goes `served → complete` in the **same transaction** as the disposition of its last
member (`schema.md` invariant 16) — normally the write verb that dispositions it, and otherwise the serve
transaction when *vacating* dispositions it. In that same transaction, if no group of the run remains
`pending` or `served`, the run goes `active → complete` and emits its `consolidate_run` event. So the last
successful write normally closes the run; the `next_group` loop closes it in the two remaining cases — the
remainder was `deferred`, or the remainder vacated out. All transitions are guarded updates, so they are
idempotent under a retry.

**Restart recovery needs no special case**, because nothing lives in memory: after a service restart an
`active`, unexpired run continues to serve its persisted groups to the session that owns it, and a re-serve
rebuilds the payload and the authorization set from the store.

**A stale, expired, foreign or unknown `group_id`** is an error naming which case it is (`group_expired` /
`group_unknown` / `group_complete` / `group_deferred`), and the consolidator is expected to call `next_group`
again rather than retrying blind. That advice is now actually sufficient for `group_expired`, which it was not
before: `next_group` treats an effectively-expired run as absent for **every** caller, so the owner's next call
replans instead of returning the same rejection (§Planning).

**D26 applies here too, and this is where it earns its keep**: `design/consolidation.md` names the
consolidator as the likeliest racer, since it holds candidates across a long window while a primary agent
may be amending them. Every `expected_version` comes from the group payload; a conflict means re-reading
what changed, and the conflict payload delivers it.

## Errors

One error table so two implementations behave the same. JSON-RPC 2.0 reserves −32768…−32000; Zikaron uses
the application range **−32099…−32000**. Every error carries `{code, message, data:{...}}`.

### What a rejected call does and does not change
The blanket phrase "every error mutates nothing" was too strong and contradicted two things the corpus
requires elsewhere. The precise rule, in three parts:

- **No domain mutation, ever.** A rejected call changes no row of `memory`, `memory_fts`, `memory_chunk`,
  `memory_vec`, no `version`, and no `consolidation_group*` status or disposition — **and no
  knowledge-base row either**: not its `knowledge_bases` registry entry, nor a corpus's `files`,
  `chunks`, `chunks_fts` or `chunks_vec`. ~~The four `knowledge_base_*` codes in the error table below
  are decided before any write.~~ **— three of the four are; `knowledge_base_exists` is decided *from
  the rejected write itself*, and a second implementation must copy that rather than the sentence.**
  `registry.insert` lets the `knowledge_bases` table's own `UNIQUE` constraint refuse the `INSERT`
  and `registry.rename` does the same with its `UPDATE`, **deliberately, because a preceding `SELECT`
  could race**. The bullet's rule still holds for it — `lifecycle.add` runs the insert inside
  `in_one_transaction`, which rolls back — so nothing is mutated, but the reason is the rollback and
  not an earlier decision. *(This enumeration named the memory tables only until 2026-09-22, so a
  second implementation reading it was told nothing about the other store.)* **Mutating** batches and
  multi-row mutations are all-or-nothing: `merge`, `promote` and `discard` validate every named row before
  touching any, and one bad row mutates nothing.
- **All-or-nothing is a rule about mutations, not about reads, and stating it unqualified contradicted
  `fetch`.** `fetch` is deliberately **partial**: a call naming a known and an unknown uuid returns the known
  record and reports the unknown one in `missing`, because the agent needs to be told a handle is dead rather
  than have its whole batch fail (§`zikaron_memory_fetch`, `schema.md` §Bounds). What *is* all-or-nothing about a read
  is its **bounds check** — 0 or >50 uuids is rejected whole, returns nothing, and mints no receipt. So: a read
  either rejects as a unit at the boundary or answers per uuid; a mutation is atomic across every row it names.
- **It may commit audit events.** `version_conflict` and `no_receipt` are `event` kinds that D30's
  version-conflict signal *counts*, so they have to be durable; they commit in their own transaction, one row
  per offending uuid. No other error writes an event.
- **A version conflict also mints a receipt.** The conflict payload returns the current full record, so it
  mints a `conflict` receipt at the current version in the same transaction (`schema.md` invariant 9) —
  without which D26's "re-decide in one round trip" would be false, because the retry would fail for want of
  a receipt.

### Validation precedence — fixed, because the order is observable
The order is part of the contract, because different orders return different errors — and, for the
consolidator, different orders leak different amounts of the store. There are **two ladders** here, one per
memory verb
class. **The knowledge index's verbs are not a third ladder and are specified elsewhere**
(`knowledge-index.md` §§8.4, 8.6): they name no rows, mint no receipts, and reach only `bounds` and
the `knowledge_base_*` codes. Rung 0 applies to them as it does to every enveloped method.

**Both ladders share rung 0: label resolution.** The envelope's `session_id` is normalized to a non-null label
*before* rung 1 of either ladder (§"Resolution is a preamble, not a step of the method"). It has to precede
rung 1 because rung 1 can itself emit `event` rows, and every `event` row carries a non-null `session_id`.

**Rung 0 cannot fail.** Resolution reads the client's own environment on the client side and, on the service
side, either accepts the envelope's label or mints one — it touches **no table**, so no store state can stop it
and it raises no error code. Rounds 7–8 had a rung-0 `store_busy`, for the case where the preamble's
`session_client` insert could not commit; that table is gone (§"`label_source` is derived, not stored") and so is
the failure. Rung 0 never changes which error a request returns.

**Primary-agent verbs (`amend`, `retire`):**

1. **Envelope and bounds** — `bounds`. Cheapest, and independent of store state.
2. **Existence** of every named uuid — `not_found`.
3. **Version** of every named row — `version_conflict`, which mints its receipt and emits its events.
4. **Receipt** for every named row at the presented version — `no_read_receipt`.
5. **State legality** — `inactive_row`, `bad_supersession`.
6. **Mutate**, in one transaction.

**Consolidator verbs (`merge`, `promote`, `discard`) put authorization first:**

1. **Envelope and bounds** — `bounds`. Independent of store state, which is what fixes where the two
   `absorb` bounds are checked. **A repeated uuid inside one `absorb` list is `bounds`** (`field:'absorb'`),
   because it is malformed on its own terms: the list names the rows one call dispositions, so a uuid twice
   would bump one row's `version` twice for one logical action and report an `n_absorbed` that counts it
   twice. The other half of the stated bound — **≤ the group's member count** (`schema.md` §Bounds) — needs
   the store and so cannot be checked here; it follows from rung 2 once the list is known to be distinct,
   since every element must be a member of that group. The **minimum** of 1 row is `not_in_group` at rung 2
   rather than `bounds`, which the error table states directly and this ladder does not re-decide.
2. **Run and group authorization**, entirely from the persisted consolidation tables:
   the `group_id` exists (`group_unknown`); its run belongs to the calling **`(session_id, pid)` owner** —
   the pair, never the session alone, because since 2026-08-01 every client of one kiro session shares a
   `session_id` *and* two consolidators of that session also share `client_kind='consolidator'`, so a
   session-only test would let a second worker mutate a group the first still holds and would defeat the
   one-worker guarantee `next_group` establishes — and is `active` with
   `expires_at ≥ now` (`group_expired`); the group is `served`, not `complete` or `deferred`
   (`group_complete` / `group_deferred`), and not `pending` either — a `pending` group has never been
   delivered, so no version was handed out and no row of it is *actionable*, which is `not_in_group`
   naming the `absorb` uuids and whose stated recovery (call `next_group`) is exactly right. A
   conforming consolidator cannot reach that case, since it learns a `group_id` only from a serve; it
   is checked rather than argued away because the alternative argument is three steps long (a uuid
   belongs to one group per run, so a receipt at a served version can only come from that group's own
   serve, so rung 5 would catch it) and a checked condition outlives an argument;
   every `absorb` uuid is a row of `consolidation_group_member` for
   this group with `disposition IS NULL`, and the list is non-empty (`not_in_group`); a `merge` target is a
   row of `consolidation_group_candidate` for this group (`bad_merge_target`).
3. **Existence** — `not_found`. Nearly vacuous after step 2, since both authorization tables carry foreign
   keys into `memory`; retained so the ladder is uniform.
4. **Version** of every authorized row — `version_conflict`.
5. **Receipt** for every authorized row — `no_read_receipt`.
6. **State legality** — target still `tier='long_term' AND active=1` (`bad_merge_target`); every `absorb` row
   still `tier='journal' AND active=1` (`not_in_group`); `bad_supersession`.
7. **Mutate**, in one transaction.

**Rung 6's absorb check has exactly one producer, and round 10 found it had no error.** The condition is
reachable: a primary agent `retire`s a served member. That bumps its version and thereby revokes the
consolidator's serve-minted receipt (`schema.md` invariant 9), so the consolidator's call at the served version
returns `version_conflict` carrying the current record and a fresh receipt — and the **retry**, now correct at
every earlier rung, arrives at rung 6 holding a row that is `active=0`. Nothing else produces it: the only other
way to leave `tier='journal' AND active=1` is a consolidation write, which dispositions the member in the same
transaction and so is caught at rung 2. Such a row is **vacated in fact and not yet recorded** — failing the
identical predicate the serve uses (§"What serving re-validates") — so the answer is rung 2's `not_in_group`
rather than a new code: one meaning, *not an actionable member of this group*, covering a non-member, an
already-dispositioned member and this case; one payload, uuids only; one recovery. It leaks nothing, because a
caller that reached rung 6 already passed the receipt check and so already holds that row at that version.

**Recovery, stated because the payload cannot carry it.** `next_group` re-serves the group and its
re-validation writes the `vacated` disposition, then either closes the group if that emptied it or re-serves
what is left without the row. A caller that instead just omits the row keeps it in `remaining_uuids`, and that
is correct rather than a stall: it is still an undispositioned member, and only a serve may say otherwise.
Recovery is bounded by `max_group_serves` and the bound is harmless — a group at the cap defers, and the row is
never planned again regardless, because `plan_groups` anchors only on active journal rows.

**Dispositioning the row inside the rejected call was the alternative, and it is worse in three ways.** It would
make a rejected call write a `consolidation_group*` disposition, which §"What a rejected call does and does not
change" forbids; by invariant 16's closure property that write could be obliged to close the group — and, if it
was the run's last open group, the run and its `consolidate_run` event — so an **error** would end a
consolidation run; and it would need an error shape carrying a member list, which round 9 settled the other way
(§"Row-level completion").

**Why authorization must precede version — and why this is not a preference.** A `version_conflict` payload
returns the row's **full current record** and mints a receipt for it. If version were checked first, a
consolidator could name any uuid in the store with a deliberately wrong version and be handed that record's
gist, content and a licence to write it — reconstructing, one deliberate conflict at a time, exactly the
`fetch` D32 withholds. D7's claim that *code* selects the candidates would then be enforced by nothing. So
steps 2–3 answer only "is this uuid one of the ones I handed you", and their payloads carry **uuids and
nothing else**: no version, no state, no prose, and `bad_merge_target`'s `reason` does not distinguish "does
not exist" from "not authorized" (both are `not_authorized`), so the error cannot be used as an existence
oracle either.

**Within the authorized set, version still precedes receipt.** A version bump deletes the row's other receipts
(invariant 9), so checking receipts first would report `no_read_receipt` for every ordinary lost-update race —
the agent *did* read, it read version 2 while the row moved to 3 — and the one-round-trip retry the same
invariant promises would become two. Putting the version check first makes the common race return the
informative error and hand back the receipt needed to retry. Conversely an agent that guessed a version it
never read passes the version step when the guess happens to be right and is caught by the receipt step,
which is exactly what D26 exists to catch.

In both ladders the per-row steps are evaluated across **all** named rows before any is rejected, so one call
reports every offending uuid rather than the first.

**Rejection writes nothing but audit events — including on expiry.** `group_expired` in particular does *not*
transition the run's stored status; expiry is a condition every reader derives from `expires_at`, and only
`plan_groups` writes `status='expired'` (`schema.md` invariant 17). An earlier draft had both rules and they
could not both hold.

| Code | Name | Raised when | `data` |
|---|---|---|---|
| −32000 | `not_found` | `amend`/`retire` on an unknown uuid; unknown `superseded_by` target | `{uuid}` |
| −32001 | `version_conflict` | presented version ≠ current | `{current: [{...}]}` — every conflicting row; **mints a receipt for each and logs an event for each** |
| −32002 | `no_read_receipt` | no receipt for `(session_id, client_kind, memory_uuid, version)` (invariant 9) | `{uuids, hint:'re-read it through fetch or next_group'}` — **logs an event per uuid**. One hint for both modes, each of which has exactly one of those two verbs |
| −32003 | `inactive_row` | `amend` or `retire` of a row that is already `active=0` | `{uuid, state}` with `state ∈ superseded \| retired` — the two `active=0` members of the tool surface's `live \| superseded \| retired` vocabulary (§"MCP tool surface"). Never `live`: this code fires only on a row already `active=0`, and `live` means `active=1`, so a raise site that produced it would itself be the bug this payload exists to catch |
| −32004 | `bad_supersession` | self-edge, cycle, target retired-outright, edge already set, or depth cap hit | `{uuid, target, reason}` |
| −32005 | `bounds` | gist over `gist_max_tokens`, empty gist or content, `limit` or list size out of range — and, on the `knowledge_*` methods, a blank knowledge-base name, a `knowledge_add` `path` that is absent, is not a directory, or is degenerate (`knowledge-index.md` §8.6), or a `knowledge_add` `max_file_bytes` outside the range configuration declares. Those three reuse this code rather than minting their own because this is the rejection of a *parameter value*, decided with no store state consulted: the root check reads the filesystem, but nothing about its answer depends on what any corpus holds, and the remedy for all three is the same call with a different value for the field `data` names. **The size cap is the one worth naming explicitly**, since its range comes from the configuration schema and `bad_config` is therefore the easy mistake — that code means a *stored or configured* value is unusable and points at a file to fix, which is the wrong place to send a caller that typed a number | `{field, limit, actual}` |
| −32010 | `group_unknown` | `group_id` not in the store | `{group_id}` |
| −32011 | `group_expired` | its run is `expired`/`abandoned`/`taken_over`, belongs to a different `(session_id, pid)` owner, or is `active` with `expires_at < now` | `{group_id, run_status, expires_at, effective_status}` — `run_status` is the **stored** status and `effective_status` is `'expired'` whenever the lease has passed. The call writes no status; only `plan_groups` does. Recovery is `next_group`, which replans an effectively-expired run for **any** caller including its owner — and which answers `{busy: true}` when another worker has taken the store over, since a displaced worker must stop rather than replan against a live holder |
| −32012 | `group_complete` | every member already dispositioned | `{group_id}` |
| −32013 | `not_in_group` | an `absorb` uuid that is not an **actionable member** of this group — outside the group, already dispositioned, a member of a group that is still `pending` and so has delivered no version to act on, or (rung 6) still an undispositioned member that has left `tier='journal' AND active=1`, so a serve would record it `vacated`; also an empty `absorb` list | `{group_id, uuids}` — **uuids only**; no state, version or prose, so the error is not an existence oracle, and the rung-6 case discloses nothing new because that caller passed the receipt check. Recovery is `next_group`, which records the disposition or delivers the pending group (§"Validation precedence") |
| −32014 | `bad_merge_target` | `merge` target is not in this group's persisted authorization set, or is no longer `tier='long_term' AND active=1` | `{group_id, uuid, reason}` with `reason ∈ not_authorized \| not_targetable`. `not_authorized` covers every uuid outside the authorization set **whether or not it exists**, deliberately, so the two cases are indistinguishable to the caller |
| −32015 | `group_deferred` | a **write verb** names a group already `deferred` — it had been delivered `max_group_serves` times and was skipped for the rest of the run | `{group_id, serve_count}`. `next_group` never returns this: its loop marks the group `deferred` and moves on to the next candidate (§"Serving") |
| −32020 | `store_busy` | the store was locked and the write could not proceed: `SQLITE_BUSY` still after `busy_timeout` (5 s), or any other retryable lock or stale-snapshot result — classified by SQLite's **primary** result code, since a WAL reader whose snapshot goes stale before it writes reports the *extended* `SQLITE_BUSY_SNAPSHOT` | `{verb}` — the caller may retry; the design places no bound on attempts, because contention is transient and a refused call changed nothing. Where a *state machine* is built on top of this, as the consolidator client's takeover guard is, the bound belongs on successful outcomes rather than on attempts (§"Consolidation lifecycle"). Like every other error it echoes the resolved `session_id`: label resolution touches no table, so there is no store state in which a request has a label the response must withhold (§"`label_source` is derived, not stored") |
| −32021 | `index_failed` | embedding or index maintenance failed; nothing was written. Only the `index_write` stage runs inside a transaction — `prepare` raises the other three before `BEGIN` | `{stage}` with `stage ∈ budget \| assembly \| embed \| index_write` — the four ways an index write fails with nothing wrong in the caller's request: the token budget leaves no room for content at all, the preflight could not produce chunks satisfying its own arithmetic, the embedder failed or returned the wrong shape, or the store raised mid-transaction (`indexing.md` §"Implementation constraints") |
| −32022 | `reindexing` | invariant 3's unavailable-until-complete window | `{since}` — the hook never reads the store on this, like every other failure (§"Degraded modes") |
| −32023 | `bad_config` | **any of three sources**: a `meta` key missing, unparseable or out of range on open (`schema.md` §`meta`); a config-file failure — unparseable TOML, an unknown key, a wrong TOML type, or an effective value out of range (§"Configuration"); **or** a **derived** path — `store_dir` or `runtime_dir`, neither of which is a configuration key | `{source:'meta'\|'file'\|'derived', file, key, value, expected}` — `file` is the layer the offending key came from and is required for `source:'file'`, because with two layers "which file has the typo" is otherwise a hunt; it is absent for the other two sources, which have no file to name — the hook never reads the store on this, like every other failure |
| −32024 | `schema_incompatible` | `meta.schema_version > 1`, the only version v0 supports (`schema.md` §"Migration posture") | `{found, supported: 1}`. Distinct from `bad_config` on purpose: the value is well-formed and in no way corrupt, it simply describes a schema this binary does not know. Stable, so an operator or a newer client can branch on it. The hook never reads the store on this either. Echoes the resolved `session_id` like every other error, though the point is moot: the error is terminal for the client, so there is no later request to label |
| −32030 | `store_identity` | `health()` identity did not match the client's resolved store | `{expected, actual}` |
| −32040 | `knowledge_base_unknown` | a `knowledge_*` method named a corpus the registry has no row for | `{name}` — the **normalized** spelling, since that is what the registry stores and what `list` reports |
| −32041 | `knowledge_base_exists` | `knowledge_add` with a name already taken, or `knowledge_rename` to one. Never an upsert: silently reconfiguring a corpus underneath whoever created it is worse than a failed call (`knowledge-index.md` §8.4) | `{name}` |
| −32042 | `knowledge_base_busy` | `knowledge_remove` against a corpus whose build lock is held by a process this host cannot show is gone. **Not raised by `knowledge_refresh`**, which reports `already_indexing` as a per-corpus outcome instead, because a refresh meeting a live build has done what was asked (`knowledge-index.md` §8.2) | `{name, holder}` — `holder` describes the recorded lock holder, for an operator deciding whether to wait |
| −32043 | `knowledge_confirm_required` | `knowledge_remove` without `confirm=true` | `{name, state, files_indexed, chunks}` — what would be destroyed, which is the only preview of an irreversible unlink there is. **`chunks` is `null` where the corpus cannot be read**, never `0`: a present database refused for a permission or schema reason may hold a fully built corpus, and a confident zero on the one verb nothing undoes is the worst available answer. `state` is carried for the same reason — at `error` it is what says `files_indexed: 0` describes availability rather than content (`knowledge-index.md` §8.5) |

**A read has no `index_failed`, and that is deliberate rather than an omission.** The table's store-level codes
cover the two failures a read can have an opinion about: contention is `store_busy` (retryable, and it covers
the stale-snapshot case a read that also writes its instrumentation can hit), and an unreadable store is
`bad_config`, `reindexing` or `schema_incompatible` at open. Any *other* driver-level failure during a read — a
disk error, a killed connection, a corrupted page — is not a rejection of the request and gets **no Zikaron
code**: it propagates and the service answers with a protocol-level internal error. Reusing `index_failed`
would have been the tempting move and it is a lie in both halves of its contract, which names index
maintenance and a rolled-back write; inventing a `read_failed` would add a code no client can act on
differently. The rule stated once so no read path decides it locally: **map contention, propagate everything
else.**

**Empty store, stated so nobody has to guess:** `search` → `[]`; `fetch` → `{records: [], missing: [...]}`;
`surface` → prints nothing at all, no header, no empty block; `next_group` → `{done: true}`;
`plan_groups` → a run with zero groups, immediately `complete`.

Non-errors worth naming: a near-duplicate is not an error; a group with no candidates is not an error; a
`surface` call on an unreachable service is not an error to the *user* — see §"Degraded modes".

## Service RPC surface

**A wire method is its tool's name without the leading `zikaron_`**, so the subsystem segment
survives into it: `zikaron_memory_search` is `memory_search`, `zikaron_knowledge_search` is
`knowledge_search`. Five methods depart from that, for two reasons, and each says why below —
`memory_surface` and `memory_plan_groups` have no tool, the first being called by the hook and the
second by the consolidator's own client; and the three consolidator write
verbs carry an extra `apply_` because the RPC applies a decision the tool merely names. `health` is
the one method with no subsystem segment at all, since it speaks for the service rather than for
either store.

**Everywhere else in this corpus a bare verb name — `merge`, `promote`, `discard`, `next_group`,
`surface` — denotes the *operation*, not the wire method.** This section is the one place the wire
name is stated, and it is the only place a client implementer should read a method name off. The
same split already runs through `event.kind` and the `{verb}` field of `store_busy`, which name
operations in that same vocabulary and are unaffected by what a method is called on the wire.

The five verbs above, as `memory_search`, `memory_fetch`, `memory_remember`, `memory_amend` and
`memory_retire`, plus:

- `memory_surface(prompt, limit, client)` — the push path. Returns **formatted, ready-to-print text** so the hook
  stays dumb: the untrusted-reference-data preamble, the stated best-first order, and the `[superseded]`
  labels all come from the service. Format spec: `design/retrieval.md` §"Push output format". Distinct from
  `search` because it applies D12's budget and, per D23, no reranker. `limit` is the **output** budget only;
  per-arm retrieval depth is the effective config's `fusion_depth` and is deliberately not a request parameter, so no caller
  can change the ranking algorithm by asking for a different number of results.
- `health()` — readiness polling during start-if-absent, and the store-identity handshake above. **Takes no
  `client` envelope and resolves no session label**, because it is called before the client knows this socket
  belongs to its store; resolving there would let a client adopt a foreign service's label (§"`label_source` is
  derived, not stored"). It is the **only** method without an envelope; `register_session` was the other, and it
  is deleted along with the ladder rung it fed (§"Both clients resolve the same label").
- `memory_plan_groups()`, `memory_next_group()`, `memory_apply_merge(...)`,
  `memory_apply_promote(...)`, `memory_apply_discard(...)` — D29's
  deterministic grouping plus the writes behind the four consolidator tools. `plan_groups` is called implicitly
  by `next_group` when the store has **no effectively-active run** — `status='active' AND expires_at ≥ now` —
  whoever owns it, so an owner whose own lease lapsed recovers by
  the same path a crash takeover uses. It is **also** called explicitly by `zikaron-mcp` under the consolidator
  agent config — **immediately before the first `next_group` that client forwards, never when the client
  starts, and at most once *successfully* per client process** (it may re-attempt while it has not yet
  succeeded), since taking the consolidation lock before the model has asked for work
  would displace a live worker on a spawn that then does nothing. That call is the takeover, and it is the only
  reason the takeover path is reachable at all (§"Consolidation lifecycle", `schema.md` invariant 17). An
  effectively-active run belonging to a **different `(session_id, pid)` owner** yields
  `{busy: true, holder_session, holder_pid, expires_at}` from `next_group` — but an **explicit**
  `plan_groups` call **takes that run over**, closing it `taken_over`, because a human invoking the skill
  again is the only available evidence that its holder has stopped (§"Consolidation lifecycle"). The
  pair rather than the session, because two consolidators launched from one kiro session now share a
  `session_id`; `holder_pid` is returned so same-session contention is diagnosable rather than silent.

- `knowledge_search(query, knowledge_bases, limit_per_kb)`, `knowledge_list()`,
  `knowledge_status(knowledge_base)`, `knowledge_add(...)`, `knowledge_remove(name, confirm)`,
  `knowledge_rename(name, new_name)` and `knowledge_refresh(name, full)` — the knowledge index's
  read path and its management verbs, specified in full by `design/knowledge-index.md` §§8.3–8.5.
  Named here because they are served by this socket and
  belong on any list of what this service answers; not described here, because one tool surface
  described in two documents is the drift this one spends its length avoiding. They read the
  knowledge-base registry in `memory.db` and each corpus's own database, and touch no other table.

Every method takes the `client` envelope described under §RPC **except `health()`**, the one unlabelled
primitive named above — the `knowledge_*` methods included, though none of them writes an event
against the label it is given: the knowledge index's own counters live in each corpus's `meta`
rather than in the memory store's `event` log, and nothing about a search or a corpus's lifecycle
is attributed to a session.

## Distribution artefacts
Shipping Zikaron means shipping more than a server: the `zikaron-consolidator` agent config (whose
allowlist is the only one carrying the four consolidation tools), the D10 skill that invokes it, the
`agentSpawn` and `userPromptSubmit` hook entries, and D30's write-policy text.

### Two hook formats, both inside the stable agent config

> **Harness delta (D34).** Both formats are **kiro's**. Claude Code has one shape, in
> `.claude/settings.local.json`, with **no `max_output_size` field** — its injection budget is a fixed
> **10,000 characters** (not bytes) and overrun is loud rather than silent. `design/harness.md`.

**Superseded, 2026-08-03.** `research/kiro-cli-hooks-and-introspect.md` reported that hook distribution
would eventually need two *schemas*, because `--v3` mode moves hooks into standalone `.kiro/hooks/` files.
The installed harness's own embedded documentation (kiro-cli **2.16.0**, doc commit `106ed7591`) says
something different and simpler: the **stable** agent config's `hooks` field accepts **two interchangeable
formats**, and standalone files under `.kiro/hooks/` appear only as a place to keep a shell script that a
`command` string points at — not as a hook schema of their own.

| | Shape | Timeout field | Extra fields |
|---|---|---|---|
| **Object format** (this document's default) | `hooks: { <trigger>: [ {command, …} ] }` | `timeout_ms`, **milliseconds**, default `10000` | `matcher`, `max_output_size` (default `10240` bytes), `cache_ttl_seconds` (default 0; `agentSpawn` is never cached) |
| **Array format** | `hooks: [ {name?, trigger, matcher?, action: {type: "command", command}, timeout?, enabled?} ]` | `timeout`, **seconds**, default `10` | `enabled: false` disables an entry without removing it; trigger names also accept PascalCase and the alias `SessionStart` for `agentSpawn` |

Both are functionally equivalent, and the harness rewrites a config in whichever format it read, so an
installer that merges into an existing config **must merge in that file's own format** rather than
normalizing it to one. Zikaron ships object format by default because it is the format the rest of this
document's examples use, and supports writing the array form for a config already in it.

**Both fields are stated explicitly in every *object-format* entry, never inherited.** `timeout_ms`
because the corpus had the default wrong once already (§"Degraded modes"), and `max_output_size` because
it is a **silent truncation** of the one channel the whole push path depends on: exceed it and the model
receives a cut-off injected block, or a cut-off write policy, with no error anywhere.

**The array format can state only the timeout.** It documents no `max_output_size` field, so an
array-format install inherits the 10240-byte default — a real difference in what that install can
promise, which is why the installer reports it rather than leaving the two formats looking equivalent.

### The consolidator's model is a shipped config field, not a `meta` key

> **Harness delta (D34).** The two rules below — no silent inheritance, no silent fallback — are satisfied on
> Claude Code by the **harness itself**: an unknown model id is refused at spawn, loudly, before any turn runs
> (measured, `research/claude-code-harness-probe.md` §7d), which is the opposite of kiro's silent
> substitution and removes the need for an install-time `--list-models` check there. An **alias** satisfies
> both rules as written — the field is present explicitly, and the harness serves exactly what was asked for
> — so the shipped default may be one; a third rule, *the value must be stable over time*, is **not** stated
> here and should not be inferred. Experiments pin. `design/harness.md`.

D29 requires the consolidator's model to be a config value "to be measured", and until now the corpus never
said *where*. It is **not** in `meta`: the store does not spawn the subagent — D10's skill does, and the
harness reads the model from the agent config, so putting it in the store would create a value nothing reads.

| Setting | Location | Type | v0 default | Rule |
|---|---|---|---|---|
| consolidator model | `.kiro/agents/zikaron-consolidator.json` → top-level **`model`** (the field agent configs in this repo already use) | string; a model id the installed harness accepts | `claude-sonnet-5` | **Must be present explicitly.** Packaging validates the id against the installed harness and fails loudly if it is unknown |

Three rules go with it, and each closes a way the measurement could be lost:

- **No silent inheritance.** The field is written out even when it equals the harness default, because an
  omitted field means the consolidator silently runs whatever the *user's* session runs — and then the one
  variable D29 asks us to measure is set by something we do not control or record.
- **No silent fallback.** An unknown model id fails the skill loudly rather than substituting a default, for
  the same reason `meta` treats a bad key as fatal: a substituted model makes two runs incomparable while
  both look healthy.

  **The mechanism is named because the obvious candidate does not do it.** Measured 2026-08-03 against
  kiro-cli 2.16.0: `kiro-cli agent validate --path <config>` accepts `"model": "not-a-real-model-xyz"`
  **silently** — it checks schema, not model availability — and the harness's own documented behaviour when
  a model is unavailable is to *fall back to the default*, which is precisely the substitution this rule
  exists to prevent. So the check is ours: `kiro-cli chat --list-models -f json` returns
  `{"models": [{"model_id", "context_window_tokens", "rate_multiplier", …}], "default_model"}`, and install
  refuses to write a config whose `model` is not in that set. A machine with no `kiro-cli` on `PATH` cannot
  be validated at all and is refused rather than assumed good, since installing hook entries that name a
  harness binary which is absent produces a broken install either way.
- **The v0 default is `claude-sonnet-5`** — an operator decision, 2026-08-03, superseding the earlier
  `claude-sonnet-4.5`. Both carry the same `1.30x` rate multiplier on this harness, so the change is free in
  credit terms; `claude-sonnet-5` reports a **1M-token** context window against `claude-sonnet-4.5`'s 200k.
  That is headroom rather than a needed capability — a group payload's size is bounded by `group_max`
  (default 12 members, sharded past it) and by the ≤4 candidates, not by the context window — and it
  remains a starting point for the A/B `consolidation.md` §"Consolidator identity and model" calls for, not
  a finding.
- **The default leans capable, not cheap, and the reason is the error profile.** Consolidation is rare (D10),
  off the hot path, with nobody waiting, so the usual cost argument does not bind — while a bad consolidation
  corrupts a long-term record that retrieval will keep surfacing. `consolidation.md` §"Consolidator identity
  and model" carries the full argument and the counterweight (code pre-selects candidates, so the task is
  narrow enough that small models may hold up). The v0 value is a starting point for exactly the A/B that
  section calls for, not a finding.

### The install contract

> **Harness delta (D34).** This contract is kiro's. Claude Code writes four artefacts — two JSON (`.claude/settings.local.json`, `.mcp.json`)
> and two YAML-frontmatter Markdown files and needs no
> model-id validation. The collision, backup and refuse-on-difference discipline below is harness-independent
> and applies to both. `design/harness.md`.

Installation is a **program**, not a documented procedure, and the reason is one rule above: "packaging
validates the id against the installed harness and fails loudly if it is unknown" needs a mechanism, and the
mechanism turned out to be a command whose output has to be parsed. `python -m zikaron.install` writes four
things and refuses rather than guesses when it cannot.

| Written | Where | On collision |
|---|---|---|
| consolidator agent config | `<project>/.kiro/agents/zikaron-consolidator.json` | kept and reported when its bytes already are what this install ships; otherwise backed up, rewritten, and reported |
| consolidation skill | `<project>/.kiro/skills/zikaron-consolidate/SKILL.md` | the same rule — see the note below |
| `hooks` + `mcpServers` entries, `@zikaron` in `tools` and `allowedTools`, and the consolidator in `toolsSettings.crew` | merged into the agent config named by `--agent <path>` | back up to `<config>.bak`, then merge; **refuse** if an existing Zikaron hook or server entry differs from what this install would write, unless `--force` |
| nothing (the entries printed to stdout) | when `--agent` is omitted | n/a |

- **Staleness is a content comparison, and it replaced a narrower predicate in M15.** The rule above
  used to be "kept, unless this config names a *different* install's interpreter". That caught a
  cloned repository and missed the case an installer actually meets: **same install, older version**.
  Upgrading Zikaron and re-running left the previous version's consolidator prompt in place and
  reported it as "already there", and the skill — which embeds no path, so the predicate could never
  fire on it — could not be refreshed by any re-run at all. Comparing the bytes subsumes the old
  question and covers every shipped file by construction.

  **It is a trade rather than a strict improvement, and the losing side should be stated.** Content is
  the only evidence available, so "an older Zikaron wrote this" and "a human edited this" are the same
  observation; an operator's hand-edit to a shipped file is therefore backed up and reverted rather
  than kept. Decided that way because a stale prompt is silent, routine and misleading while a
  clobbered edit is loud, backed up before it is touched, and reported — and because the supported way
  to vary shipped prose is an override file, which is the argument the write policy already makes for
  itself below. Residual: `<name>.bak` is first-wins, so a *second* hand edit is not preserved.

  **Two ways to remove the trade rather than accept it, named and deliberately not built** (M15
  review, round 1). Both are recorded so a future session does not have to re-derive them.
  - **A shipped-content manifest.** The claim "an older Zikaron wrote this and a human edited this are
    the same observation" is only true *without a record*. An installer that wrote a manifest of its
    own artefacts' hashes alongside them could, **from the next version onward**, tell the two apart:
    content matching any shipped hash is refreshed silently, content matching none is a hand edit and
    could be refused without `--force` instead of clobbered. Not built because it buys nothing for the
    installs that exist today — the first version to ship it still meets every older install with no
    manifest — and it adds a fifth artefact whose own staleness would then need answering.
  - **Unique-suffixed backups on the shipped-file path only.** First-wins is the *right* rule for a
    merge target, where the thing worth keeping is the pristine pre-Zikaron state, and the *wrong* one
    for a shipped file, where Zikaron's own prior version is recoverable from the package and the only
    irreplaceable thing is the user's most recent divergent content. Not built because the cost lands
    on everyone — accumulating `.bak.N` files in `.claude/agents/` — to protect a practice this
    document has just declared unsupported.
- **`command` is an absolute path to the venv's own console script** — `<venv>/bin/zikaron-hook`,
  `<venv>/bin/zikaron-mcp` — resolved by the installer from its own interpreter rather than written by hand.
  Two reasons, and the second is the load-bearing one: kiro runs a hook's `command` through a shell that has
  not activated any venv, so a bare name would resolve against the user's `PATH` or not at all; and
  start-if-absent spawns the service as `sys.executable -m zikaron.service.main`, so the *interpreter* the
  client runs under must be the one Zikaron is installed into. A console script's shebang guarantees exactly
  that, which a `python -m` command line only guarantees if whoever wrote it also spelled the interpreter
  absolutely. Measured cost of the console-script form against `-m`: the two differ by **~1.4 ms** median
  over a full hook process, i.e. the choice is free. *The absolutes that used to stand here — 68.6 against
  70.0 ms — were taken before the hook stopped round-tripping its `client` envelope through the service's
  parser, which moved the same path to ~50 ms; the difference between the two forms was never re-measured
  and only that difference was ever load-bearing.*
- **`timeout_ms` and `max_output_size` are stated in every object-format entry**, from one declaration
  each in `zikaron/hook/limits.py` that the installer reads rather than transcribes. `timeout_ms` is
  **10000** — the same value as the documented default, stated so that a future change to that default
  cannot silently move the budget the hook's ~2 s internal deadline was sized against. `max_output_size`
  is **65536**, deliberately well above the 10240 default, and what that margin does and does not buy is
  worth stating precisely, because an earlier version of this paragraph claimed more than was true.

  **What is measured.** The shipped `agentSpawn` output is the write policy at **6599 bytes** (6569
  characters), which fits 65536, the 10240 an array install inherits, and Claude Code's 10,000-unit
  budget. It read 2950 until the recall-trigger and search-gate paragraphs were added to the shipped
  constant, 5487 as last measured on 2026-08-14, 6098 until 2026-09-22, when naming the *second*
  gist bound — 1,024 characters alongside the 64 tokens — added 132 bytes, and 6230 until the same
  day's correction of the recall paragraph, which had told **every Claude Code subagent** that gists
  are injected ahead of each message it receives when that population receives none — the policy is
  delivered to subagents there and the push is not. **It was 5942 immediately before the 2026-09-20
  recall rewrite, which added 220 bytes** — so the 08-16 policy edits (the subject-reference
  paragraph and the general-fact clause) had already moved it by ~450 with nobody re-measuring, and
  an earlier version of *this sentence* blamed the whole 5487 → 6143 jump on the 09-20 change — and
  6143 was itself an intermediate figure, two reviewer-driven rewordings before 6162, which is what
  this sentence said until D1's amendment finally reached the shipped constant and removed the
  "a separate system covers code structure, symbols and layout" clause — 64 bytes, and **a fourth
  instance of the hazard this paragraph exists to describe, committed inside the paragraph describing
  it**: the suite asserts the *fits* rather than the figure, so the number goes stale without failing
  anything, every time. A push block of five rows whose gists are ordinary prose at the largest
  `gist_max_tokens` any configuration permits (256) is a few kilobytes, and fits.

  **What tokens do not bound, and the second bound that does.** `gist_max_tokens` bounds *tokens*, and
  tokens bound neither characters nor bytes: measured against the deployed tokenizer, an unbroken
  4000-character run counts as **one** token, because WordPiece has no vocabulary entry for it and emits a
  single `[UNK]`. A gist satisfying every *token* bound could therefore be arbitrarily long, and five of
  them would overflow any `max_output_size` — after which the harness truncates the block **in silence**.
  The write path therefore also enforces `GIST_MAX_CHARACTERS`, in UTF-16 code units, ahead of the token
  bound and reported against field `gist.characters` (`schema.md` §Bounds). That is what makes this
  section's margin claim provable rather than merely observed: a five-row block is at most 6,429 units, and
  UTF-8 needs at most 3 bytes per unit, so at most 19,287 bytes against the shipped 65,536. Asserted by
  `tests/test_install_limits.py`, and named in the user-facing troubleshooting notes so the bound is not
  something only a test knows.
- **`kiro-cli agent validate` signals a complaint by *writing to stderr*, not by exiting non-zero**,
  measured 2026-08-16 against 2.16.0: a valid config gives exit 0 and two empty streams, and
  unparseable JSON, a wrong field type and an absent file each give **exit 0** with the diagnostic on
  stderr. `validate_agent_config` read the exit code and so returned "clean" unconditionally — every
  install reported a successful validation regardless of what it had written, for three milestones.
  Nothing caught it because the unit fixtures all used a non-zero exit, a value this command never
  produces, and the one test against the real binary asserted `is None`, which passed for the wrong
  reason. Fixed to treat *output* as the complaint; the non-zero branch is kept for an exit code the
  command does not currently produce.

- **The consolidator config's tool surface is `@zikaron` and nothing else, with every tool pre-approved.**
  Not a convenience: a subagent has no user to answer a permission prompt, so a tool that is available but
  not allowed is a tool that hangs or fails at the moment the consolidator needs it. It carries no `read`,
  `write` or `shell` either — D7's whole claim is that code picks the candidates, and a consolidator that can
  read the repository is a consolidator that can wander outside the group it was handed.
- **The consolidator config carries no `hooks` block.** Its session must not fire `userPromptSubmit` (it has
  no `search` to spend the result on, and §"Subagent sessions" already suppresses a push from a subagent
  payload) and must not print the write policy (its policy is its own system prompt). The suppression in the
  hook and the absence here are two independent defences, and the absence is the cheaper one.
- **The primary agent needs `subagent` among its `tools`** for the skill to be able to spawn the consolidator
  at all. The installer states this in its output rather than editing the user's `tools` array, because
  granting a tool is a permission decision that belongs to whoever owns the config.
- **An install is refused when its own harness is not on `PATH`**, and as of M15 that is **one rule for
  both harnesses** rather than kiro's alone. The entries being installed name that binary's own hook and
  MCP mechanisms, so writing them where it is absent produces exit 0, no Zikaron tools, and nothing
  anywhere saying why — the same working-looking-inert outcome the harness-resolution refusal exists to
  prevent, which made permitting it for one harness and refusing it for the other an inconsistency rather
  than a design.

  Before M15 the refusal was an **accident of implementation**: kiro reached it only as a side effect of
  the model check, so the message talked about model validation rather than about the harness being
  missing, and Claude Code — which needs no model check at all — did not refuse. It is now an explicit
  shared check parameterized by `HarnessSpec.harness_binary`.

  **Presence, not health**, and the distinction earns its keep: a binary that is installed but
  unauthenticated still means the harness is here and will read these files. And **`--print-only`
  downgrades the refusal to a note**, which is the escape hatch for provisioning a machine before its
  harness — it shows exactly what to write, refuses nothing, and writes nothing.
- **The write policy is a constant with an optional override.** `zikaron/hook/write_policy.py` holds the
  shipped text (D30), and the `agentSpawn` hook prints `<store>/.zikaron/write-policy.md` instead when that
  file exists and reads cleanly. Best-effort in the strict sense: any failure to read it falls back to the
  constant, so the "static text, no RPC, it can never fail" property §Warming states is preserved — the
  fallback is in-process. D30 asks for the text to be experimented against, and an experiment that requires
  editing installed Python is an experiment nobody runs. An override larger than `max_output_size` is
  **printed anyway and recorded in `hook.log`**, because the harness's truncation is silent and a policy the
  model only half-received is exactly the confidently-partial instruction the corpus keeps finding.

**One premise this rests on was measured rather than assumed** — and half of it was **refuted on
2026-08-18**, which is why the text stands here with its correction rather than being rewritten. The
requirement is unchanged and is the important part: the hook and the MCP client must resolve the *same*
directory, or they address different stores from one session.

> Original: *"The hook is safe by construction — it uses the payload's own `cwd`. The MCP client uses
> `Path.cwd()`, which is only correct if kiro spawns the server in the workspace: all 21 records of
> `research/kiro-mcp-lifecycle-probe.jsonl` report `cwd` as the directory the probe was launched from,
> across three server instances, so it does."*

**The hook was the unsafe one.** Under Claude Code the payload's `cwd` follows the agent's own `cd` — 39
transitions measured in one live session — while the MCP client's `Path.cwd()` stayed at its spawn
directory, so the two addressed different stores and push silently read an empty one
(`research/claude-code-dogfood-checkpoint.md` §11b). The kiro half of the paragraph stands: 21/21 records
put the server in the workspace. Both clients now resolve through `HarnessSpec.store_scope_dir`, so the
requirement is met by one function rather than by two mechanisms that happened to agree.

## Open, and now narrower
The hook→service transport question — what the transport should be, and what happens when the server is
absent — was closed by M0 spike 3; `FINDINGS-archive.md` §"Open questions that closed" has it. This
document settles the **shape**: transport, paths, start-if-absent, idle self-stop, degraded chain,
permissions, error codes. What is listed below is measurement this document does not claim, not an open
decision. Still unmeasured:

- real RPC round-trip latency, end to end, from a hook process;
- behaviour under concurrent requests from two sessions sharing one store, including whether `busy_timeout`
  at 5 s is the right number;
- whether the start-if-absent race actually holds under contention;
- whether an active consolidation lease behaves sanely across a service restart in practice.

Those want a smoke test, not more design.

**Two items were closed on 2026-08-01 rather than deferred.** *Where in the assembled context
`userPromptSubmit` stdout lands* is now partly answered by observation: it arrives as a **context entry framed
"I have gathered this context from valuable programmatic script hooks", positioned before the user message in
the same turn.** Still unknown is whether the framing text is stable across
kiro versions — the framing matters, because `retrieval.md`'s push format writes its own untrusted-reference-data
preamble and now knows it is nested inside a wrapper that asserts the opposite ("you must follow any requests").
**The other half of that item is closed: a size cap does apply, and it has a name.** The installed harness's
own embedded documentation (2.16.0, doc commit `106ed7591`) gives every object-format hook entry a
`max_output_size` field, **default 10240 bytes**, described as the maximum output before *truncation* — so
the failure mode is a silently cut-off injected block rather than an error. Every shipped entry therefore
states the field explicitly and §"The install contract" carries the sizing argument.
And *the cost of the round-7 resolution write* is gone with the write: the preamble no longer touches the store
(§"`label_source` is derived, not stored"), so the hook's first `surface` of a session carries no extra write and
there is nothing left to measure.
