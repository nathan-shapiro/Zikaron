# Architecture — four components, RPC, lifecycle, MCP surface

> Written 2026-08-01. Companion to `design/schema.md`. Implements D9 (MCP + skill + hooks), D12 (push and
> pull), D18 (`agentSpawn` instructions), D22 (**the hook must never load a model**), D10 (manual
> consolidation), and settles the **shape** half of Open question 4 — the integration measurements stay open,
> see §"Open, and now narrower".

## Components

| | What it is | Loads a model? |
|---|---|---|
| **`zikaron-core`** | Library. All logic: store, hybrid retrieval, chunking, embedding, dedup, consolidation grouping. No process concerns, no transport. | yes, on demand |
| **`zikaron-service`** | Long-running process. Holds the warm embedder and the open DB. Serves local RPC. Self-stops after idle. | **yes — the only one** |
| **`zikaron-mcp`** | Thin MCP server. Translates MCP tool calls to RPC. Starts the service if absent. | no |
| **`zikaron-hook`** | Thin hook executable for `agentSpawn` and `userPromptSubmit`. Starts the service if absent. | no |

The service exists for exactly one measured reason: cold whole-process `bge-small` is **783 ms**, and D12
puts retrieval on the critical path of every user message. Keeping the model resident moves that to a warm
**6.64 ms** embed and a **9.14 ms** full retrieval path — the figures for the **prefixed** path D20 actually
adopts. (Without the prefix it is 5.45 / 7.97 ms; quoting those for a prefixed deployment was a stale-figure
finding in the corpus review.)

Both thin clients are thin on purpose. Measured on this machine: `python -c pass` is **10.9 ms**,
`import socket, json, os` is **20.6 ms**, adding `sqlite3` is **21.8 ms**. So a stdlib-only client costs
~20 ms — which is the real argument against an HTTP/ASGI transport, since importing an HTTP client into the
hook would spend more than the transport saves.

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

The `service.log` records each label resolution — which rung won — at the call that resolved it, so an analysis
never has to infer it. That is per **first request from a client**, not per client startup: under the bootstrap
form the service has no knowledge of a client until it calls. The log is a convenience only; the durable record
is the label itself, from which `label_source` is a pure function.

- **`op_id`** is minted per call by the client (or by the service if absent) and stamped on every `event`
  row the call emits, which is what correlates a `remember` with the `dedup_offered` rows it produced.
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
  bootstraps only when `KIRO_SESSION_ID` is absent, which under kiro does not happen. The `service.log` records
  which rung produced the label. Worst case a session is labelled by the service rather than by the harness:
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

- **Store:** `<cwd>/.zikaron/memory.db` — D17 scopes to the working directory literally, and `.zikaron/` is
  already in `.gitignore` per D19.
- **Socket:** *not* in the project tree — UDS on a network filesystem is unreliable, and the tree stays
  clean. `$XDG_RUNTIME_DIR/zikaron/<h>.sock` when that is set (already user-private `0700`), else
  `/tmp/zikaron-<uid>/<h>.sock` with the directory created `0700`. `<h>` is the **first 32 hex characters
  (128 bits) of the sha256 of the `realpath`-resolved store path** — long enough that accidental collision
  is not a design concern, short enough to keep the path under the ~108-byte `sun_path` limit. One service
  per store.
- **Logs: one file per process, never shared.** `<cwd>/.zikaron/service.log` (the long-running service),
  `<cwd>/.zikaron/warmup.log` (the `agentSpawn` hook's detached warm helper), `<cwd>/.zikaron/hook.log` (the
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
| 3. project override | `<cwd>/.zikaron/config.toml` | this project only |

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

# <cwd>/.zikaron/config.toml — this project only
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
  cut at. A mismatch is logged and the store is simply heterogeneous — old chunks remain valid vectors of
  valid text, so refusing to start would be disproportionate. `indexing.md`'s `token_count` and `truncated`
  instrumentation already makes the heterogeneity visible.
- `schema_version`, `store_id` and the transient `reindexing` sentinel are never settable from a file at all.

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
  write.** A mismatch is not a retry: the client logs it, treats the socket as foreign, and — for the hook —
  goes through the same degraded path as any other failure (§"Degraded modes"): nothing printed, nothing read,
  one line to `hook.log`. The mismatch is not special-cased into a fallback read of a store the client has
  no way to know is the right one.
- **Nothing is adopted from an unverified service, session labels included.** This is why `health()` is outside
  the label ladder (§"`label_source` is derived, not stored"). If the handshake resolved a label, a client
  reaching a *foreign* service would adopt a label that service minted, discard the socket on the mismatch it
  was checking for, and then stamp that foreign label on every event in its own store — a cross-store
  contamination introduced by the very call that exists to prevent cross-store reads. Resolution therefore
  happens on the first request that is *about* this store, which is strictly after verification.

## Filesystem security

The store is durable, unencrypted, plain-text knowledge about a project: build steps, env var names, which
services must be running, what failed and why. It deserves the same care as the socket, which the first
draft of this document gave only to the socket.

| Path | Mode | Rule |
|---|---|---|
| `<cwd>/.zikaron/` | **0700** | created with an explicit `mkdir(0o700)`; if it exists with a wider mode, the service tightens it and logs |
| `memory.db`, `-wal`, `-shm` | **0600** | created under an explicit umask (`os.umask(0o077)`) around store creation, because SQLite creates the WAL/SHM itself and will otherwise inherit a permissive umask |
| `service.log`, `warmup.log`, `hook.log` | **0600** | `service.log` quotes prompts and error text; `warmup.log` and `hook.log` log only a fixed failure-kind label and an error code, never prompt or memory content, so neither can hold a leaked secret (`design/write-policy.md` §"The emergency erasure procedure, exactly"). Each is written by exactly one process, never shared |
| `config.toml` | **0600** | operator-written; no secrets by design, but it sits in the same private directory |
| `$XDG_RUNTIME_DIR/zikaron/` | 0700 | must be owned by the running uid |
| `/tmp/zikaron-<uid>/` | 0700 | **validated before use**, not merely created |
| `<h>.sock` | 0600 | |

Rules that go with the modes:

- **Reject, never repair, a hostile runtime path.** Before creating or using `/tmp/zikaron-<uid>/`: if it
  exists, it must be a real directory (not a symlink), owned by the running uid, mode 0700. Otherwise the
  service refuses to start there and the clients go degraded. Blindly `mkdir`-ing a predictable `/tmp` path
  and unlinking sockets inside it is the classic local symlink attack.
- **Never unlink a socket you have not vetted.** The start-if-absent sequence below unlinks a stale socket;
  it may only do so after confirming the path is a socket, in a vetted directory, owned by the running uid.
- **Refuse a store reached through a symlinked `.zikaron`.** `realpath` the store directory and require the
  resolved parent to be the cwd.
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
6. **Verify `store_id` and `store_path` from `health()`** before the first real request.

`ECONNREFUSED` on an existing socket file is the signature of a service that died without cleaning up —
unlink and respawn rather than reporting an error.

### Idle self-stop
`last_activity` is refreshed when each request completes. A background task polls every 30 s and exits
when idle exceeds `idle_timeout` (**default 30 min**) **and** no requests are in flight. On exit the socket
is unlinked before the process ends.

**The race this creates must be handled in the client, not wished away:** a client can connect just as the
service decides to exit, and its request then fails. Clients retry once through the full start-if-absent
sequence before falling back.

An active consolidation run does **not** keep the service alive on its own — a run is a store-level lease
(§"Consolidation lifecycle"), not process state, so a service that stops mid-run loses nothing.

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
  the owner and gets `{busy: true}` until the lease lapses; only an **expired** lease may be taken over, which
  keeps crash recovery working. This costs no schema change — `consolidation_run` already records `pid` — and no
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
   nothing, stop** (§"Subagent sessions"). No RPC, no log line. This is unrelated to the failure path below;
   it is not a failure at all.
1. RPC `surface(prompt, limit=5)`. On success, print what the service returned.
2. **On any failure — transport, startup, contention, identity, or a store error** — `ENOENT`, `ECONNREFUSED`,
   spawn failure, `health()` never ready, the internal deadline, a `store_identity` mismatch, `−32020
   store_busy`, `−32023 bad_config`, `−32022 reindexing`, or anything unexpected: **print nothing to stdout,
   open nothing, read nothing, and append one line to its own `hook.log`** naming the failure kind and, where
   one exists, the error code. This is a **direct file write, not `logging`**: `open(path, "a")` and one
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
have been: `hook.log` now says "reindexing" or "bad_config" or "ECONNREFUSED" in the exact moment it
happened, rather than leaving an operator to infer the cause from an intermittently missing injection.

Two hard rules:

- **Always exit 0, and never write to stderr.** Per the hooks research, exit codes other than 0 and 2 cause
  stderr to be shown to the user as a warning. A memory system having a bad day must not nag on every
  message. Writing to `hook.log` is not writing to stderr, and is required on every failure rather than
  merely permitted.
- **Enforce an internal deadline of ~2 s**, far under the 30 s `timeout_ms`. Failing fast and silently beats
  being correct and late, because the user is waiting.

## MCP tool surface (5 tools)

Tool *descriptions* carry the mechanics — the version precondition, the dedup payload, retire semantics —
because per D30 they sit in context at the point of decision, while D18's `agentSpawn` prose carries policy.

```
zikaron_search(query: str, limit: int = 5, include_retired: bool = false)
  -> [{uuid, gist, tier, state, created_at, updated_at, superseded_by}]
     `state` ∈ live | superseded | retired, so triage can see a demoted row for what it is.
     Ordered by the total order in retrieval.md; the order is stated to the agent, best first.
     No version field, and therefore no licence to write. Empty store returns [].

zikaron_fetch(uuids: list[str])       # 1–50 uuids
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
     **Mints a read receipt** for every record returned (schema.md invariant 9), which is what
     licenses a later write. It is the only way to license a write to a row this session did
     not itself just write, or just receive back in a conflict payload.

zikaron_remember(gist: str, content: str)
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
     calls and the tool description says so — `zikaron_amend` the older row, then `zikaron_retire`
     the new one with `superseded_by` = the older uuid. Until then both are live and consolidation
     will group them. Mints an `own_write` receipt for the new row.

zikaron_amend(uuid: str, version: int, gist: str, content: str)
  -> {uuid, version}
   | {conflict: true, current: CONFLICT_RECORD}
     Full rewrite (D6). Requires a read receipt at `version` (D26). A version mismatch rejects and
     returns the current record — one CONFLICT_RECORD, the single shape defined below — and the
     payload itself mints a receipt at the current version, so the agent really can re-decide in
     one round trip.
     Mints an `own_write` receipt at the new version.

zikaron_retire(uuid: str, version: int, superseded_by: str | None = None)
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

Two rules run through all four signatures, and the first draft of this document had neither:

- **Every row a verb touches is named as `{uuid, expected_version}`** — targets, absorbed rows and discarded
  rows alike. Not just the merge target. Otherwise a primary agent that amends an absorbed journal row after
  it was planned into a group would have its repair silently retired by the consolidator, which is exactly
  the lost update D26 exists to prevent.
- **Completion is tracked per journal row, never per group.** A group with a mixed disposition — merge A,
  promote B, discard C — takes three calls, and the group closes only when its last member is dispositioned.

```
zikaron_next_group()
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
     `anchor` is the long-term record the group was built around (null for an orphan group, and
     null with `anchor_vacated: true` if it stopped being targetable after planning) and is also
     the natural merge target. `candidates` are additional long-term records, ≤4, in retrieval
     order, and may be empty when the long-term tier is empty. Definition: consolidation.md.
     Every `expected_version` is the version whose prose is in **this** payload, re-read at serve
     time — not the version at plan time. **Mints read receipts** at those versions for the anchor,
     every journal entry and every candidate, so D26 is satisfied without giving the consolidator
     `fetch`. Anchor and candidates are also persisted as this group's authorization set
     (`schema.md` `consolidation_group_candidate`), which is what `merge` checks its target against.

zikaron_merge(group_id, target: {uuid, expected_version}, gist, content,
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

zikaron_promote(group_id, gist, content, absorb: [{uuid, expected_version}, ...])
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

zikaron_discard(group_id, absorb: [{uuid, expected_version}, ...], reason: str)
  -> {retired: int, remaining_uuids: [...], group_complete: bool}
   | {conflict: true, current: [CONFLICT_RECORD, ...], remaining_uuids: [...]}
     Retire journal rows judged not worth keeping: active=0, superseded_by NULL (D16). `reason` is
     recorded in the event log, not in the store — a discarded row keeps its own prose.
```

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
  an error and not a second plan. The skill reports it and stops. An explicit `plan_groups()` RPC in that
  situation returns the same `{busy: true}` shape rather than stealing the run. **Ownership is
  `(session_id, pid)`**, both already recorded on `consolidation_run` and both already carried by the envelope:
  since 2026-08-01 all clients of one kiro session share a `session_id`, so `session_id` alone would make two
  concurrently-launched consolidators the same owner. See §"What the shared label affects" for why one worker
  is required and not merely tidy — it is what makes D29's transitive merging true.
- **An effectively-expired run is absent, for every caller including its owner.** This is the fix for a real
  dead end: `next_group` replans only when the caller has no active run, so an owner whose lease lapsed used to
  find *its own* run, be served a group from it, and be rejected `group_expired` — with no way out, because
  `plan_groups` is a service RPC and not one of D32's four consolidator tools, so the documented advice ("call
  `next_group` again") returned the same rejection forever. Now `next_group` finding no *effectively*-active run
  — none at all, or only a lapsed `'active'` row, whoever owns it — calls `plan_groups()` implicitly. Crash
  takeover by a stranger and lease recovery by the owner are therefore the same code path, and neither needs an
  operator. **"Owner" means `(session_id, pid)`.** Since 2026-08-01 the consolidator presents the top-level
  session's label, so a session alone no longer identifies a worker; the pid distinguishes two consolidators
  launched concurrently from one session, and only an *expired* lease may be taken over by anyone. Crash
  takeover and owner recovery remain one code path. §"What the shared label affects" carries the argument and
  the pid-reuse residual.
- **`plan_groups()` closes any pre-existing `active` run, and the lease decides which status it writes:**
  `'expired'` if `expires_at < now`, `'abandoned'` otherwise. It is the only producer of either, and it emits
  the matching `consolidate_run` phase event. That also disambiguates two rules that used to overlap —
  "`expired` only by a later `plan_groups`" and "`abandoned` when the owning session replans" — into one test.
  Replanning is never incremental: a new run always plans from scratch, which is safe because undispositioned
  members stay `tier='journal' AND active=1`.
- **The lease is refreshed** by every successful call in the run — a write on a *success* path, which the
  rejection rule permits. **Expiry itself is never written by a rejected call.** Every reader treats
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
  `memory_vec`, no `version`, and no `consolidation_group*` status or disposition. **Mutating** batches and
  multi-row mutations are all-or-nothing: `merge`, `promote` and `discard` validate every named row before
  touching any, and one bad row mutates nothing.
- **All-or-nothing is a rule about mutations, not about reads, and stating it unqualified contradicted
  `fetch`.** `fetch` is deliberately **partial**: a call naming a known and an unknown uuid returns the known
  record and reports the unknown one in `missing`, because the agent needs to be told a handle is dead rather
  than have its whole batch fail (§`zikaron_fetch`, `schema.md` §Bounds). What *is* all-or-nothing about a read
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
consolidator, different orders leak different amounts of the store. There are **two ladders**, one per verb
class.

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

1. **Envelope and bounds** — `bounds`.
2. **Run and group authorization**, entirely from the persisted consolidation tables:
   the `group_id` exists (`group_unknown`); its run belongs to the calling **`(session_id, pid)` owner** —
   the pair, never the session alone, because since 2026-08-01 every client of one kiro session shares a
   `session_id` *and* two consolidators of that session also share `client_kind='consolidator'`, so a
   session-only test would let a second worker mutate a group the first still holds and would defeat the
   one-worker guarantee `next_group` establishes — and is `active` with
   `expires_at ≥ now` (`group_expired`); the group is `served`, not `complete` or `deferred`
   (`group_complete` / `group_deferred`); every `absorb` uuid is a row of `consolidation_group_member` for
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
| −32002 | `no_read_receipt` | no receipt for `(session_id, client_kind, memory_uuid, version)` (invariant 9) | `{uuids, hint:'fetch it first'}` — **logs an event per uuid** |
| −32003 | `inactive_row` | `amend` or `retire` of a row that is already `active=0` | `{uuid, state}` with `state ∈ superseded \| retired` — the two `active=0` members of the tool surface's `live \| superseded \| retired` vocabulary (§"MCP tool surface"). Never `live`: this code fires only on a row already `active=0`, and `live` means `active=1`, so a raise site that produced it would itself be the bug this payload exists to catch |
| −32004 | `bad_supersession` | self-edge, cycle, target retired-outright, edge already set, or depth cap hit | `{uuid, target, reason}` |
| −32005 | `bounds` | gist over `gist_max_tokens`, empty gist or content, `limit` or list size out of range | `{field, limit, actual}` |
| −32010 | `group_unknown` | `group_id` not in the store | `{group_id}` |
| −32011 | `group_expired` | its run is `expired`/`abandoned`, belongs to a different `(session_id, pid)` owner, or is `active` with `expires_at < now` | `{group_id, run_status, expires_at, effective_status}` — `run_status` is the **stored** status and `effective_status` is `'expired'` whenever the lease has passed. The call writes no status; only `plan_groups` does. Recovery is `next_group`, which replans an effectively-expired run for **any** caller including its owner |
| −32012 | `group_complete` | every member already dispositioned | `{group_id}` |
| −32013 | `not_in_group` | an `absorb` uuid that is not an **actionable member** of this group — outside the group, already dispositioned, or (rung 6) still an undispositioned member that has left `tier='journal' AND active=1`, so a serve would record it `vacated`; also an empty `absorb` list | `{group_id, uuids}` — **uuids only**; no state, version or prose, so the error is not an existence oracle, and the rung-6 case discloses nothing new because that caller passed the receipt check. Recovery is `next_group`, which records the disposition (§"Validation precedence") |
| −32014 | `bad_merge_target` | `merge` target is not in this group's persisted authorization set, or is no longer `tier='long_term' AND active=1` | `{group_id, uuid, reason}` with `reason ∈ not_authorized \| not_targetable`. `not_authorized` covers every uuid outside the authorization set **whether or not it exists**, deliberately, so the two cases are indistinguishable to the caller |
| −32015 | `group_deferred` | a **write verb** names a group already `deferred` — it had been delivered `max_group_serves` times and was skipped for the rest of the run | `{group_id, serve_count}`. `next_group` never returns this: its loop marks the group `deferred` and moves on to the next candidate (§"Serving") |
| −32020 | `store_busy` | the store was locked and the write could not proceed: `SQLITE_BUSY` still after `busy_timeout` (5 s), or any other retryable lock or stale-snapshot result — classified by SQLite's **primary** result code, since a WAL reader whose snapshot goes stale before it writes reports the *extended* `SQLITE_BUSY_SNAPSHOT` | `{verb}` — the caller may retry once. Like every other error it echoes the resolved `session_id`: label resolution touches no table, so there is no store state in which a request has a label the response must withhold (§"`label_source` is derived, not stored") |
| −32021 | `index_failed` | embedding or index maintenance failed; the transaction rolled back | `{stage}` with `stage ∈ budget \| assembly \| embed \| index_write` — the four ways an index write fails with nothing wrong in the caller's request: the token budget leaves no room for content at all, the preflight could not produce chunks satisfying its own arithmetic, the embedder failed or returned the wrong shape, or the store raised mid-transaction (`indexing.md` §"Implementation constraints") |
| −32022 | `reindexing` | invariant 3's unavailable-until-complete window | `{since}` — the hook **prints nothing** on this, like every other failure (§"Degraded modes") |
| −32023 | `bad_config` | **either source**: a `meta` key missing, unparseable or out of range on open (`schema.md` §`meta`), **or** a config-file failure — unparseable TOML, an unknown key, a wrong TOML type, or an effective value out of range (§"Configuration") | `{source:'meta'\|'file', file, key, value, expected}` — `file` is the layer the offending key came from, absent for `source:'meta'`, and it is required because with two layers "which file has the typo" is otherwise a hunt — the hook **prints nothing** on this, like every other failure |
| −32024 | `schema_incompatible` | `meta.schema_version > 1`, the only version v0 supports (`schema.md` §"Migration posture") | `{found, supported: 1}`. Distinct from `bad_config` on purpose: the value is well-formed and in no way corrupt, it simply describes a schema this binary does not know. Stable, so an operator or a newer client can branch on it. The hook **prints nothing**. Echoes the resolved `session_id` like every other error, though the point is moot: the error is terminal for the client, so there is no later request to label |
| −32030 | `store_identity` | `health()` identity did not match the client's resolved store | `{expected, actual}` |

**Empty store, stated so nobody has to guess:** `search` → `[]`; `fetch` → `{records: [], missing: [...]}`;
`surface` → prints nothing at all, no header, no empty block; `next_group` → `{done: true}`;
`plan_groups` → a run with zero groups, immediately `complete`.

Non-errors worth naming: a near-duplicate is not an error; a group with no candidates is not an error; a
`surface` call on an unreachable service is not an error to the *user* — see §"Degraded modes".

## Service RPC surface

The five verbs above, plus:

- `surface(prompt, limit, client)` — the push path. Returns **formatted, ready-to-print text** so the hook
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
- `plan_groups()`, `next_group()`, `apply_merge(...)`, `apply_promote(...)`, `apply_discard(...)` — D29's
  deterministic grouping plus the writes behind the four consolidator tools. `plan_groups` is called implicitly
  by `next_group` when the store has **no effectively-active run** — `status='active' AND expires_at ≥ now` —
  whoever owns it, so the skill never has to call it explicitly and an owner whose own lease lapsed recovers by
  the same path a crash takeover uses (§"Consolidation lifecycle", `schema.md` invariant 17). An
  effectively-active run belonging to a **different `(session_id, pid)` owner** yields
  `{busy: true, holder_session, holder_pid, expires_at}` instead, from both this RPC and `next_group`. The
  pair rather than the session, because two consolidators launched from one kiro session now share a
  `session_id`; `holder_pid` is returned so same-session contention is diagnosable rather than silent.

Every method takes the `client` envelope described under §RPC **except `health()`**, the one unlabelled
primitive named above.

## Distribution artefacts
Shipping Zikaron means shipping more than a server: the `zikaron-consolidator` agent config (whose
allowlist is the only one carrying the four consolidation tools), the D10 skill that invokes it, the
`agentSpawn` and `userPromptSubmit` hook entries, and D30's write-policy text. Note the hooks research
finding that `--v3` mode uses an incompatible standalone `.kiro/hooks/` schema, so hook distribution
eventually needs two formats.

### The consolidator's model is a shipped config field, not a `meta` key
D29 requires the consolidator's model to be a config value "to be measured", and until now the corpus never
said *where*. It is **not** in `meta`: the store does not spawn the subagent — D10's skill does, and the
harness reads the model from the agent config, so putting it in the store would create a value nothing reads.

| Setting | Location | Type | v0 default | Rule |
|---|---|---|---|---|
| consolidator model | `.kiro/agents/zikaron-consolidator.json` → top-level **`model`** (the field agent configs in this repo already use) | string; a model id the installed harness accepts | `claude-sonnet-4.5` | **Must be present explicitly.** Packaging validates the id against the installed harness and fails loudly if it is unknown |

Three rules go with it, and each closes a way the measurement could be lost:

- **No silent inheritance.** The field is written out even when it equals the harness default, because an
  omitted field means the consolidator silently runs whatever the *user's* session runs — and then the one
  variable D29 asks us to measure is set by something we do not control or record.
- **No silent fallback.** An unknown model id fails the skill loudly rather than substituting a default, for
  the same reason `meta` treats a bad key as fatal: a substituted model makes two runs incomparable while
  both look healthy.
- **The default leans capable, not cheap, and the reason is the error profile.** Consolidation is rare (D10),
  off the hot path, with nobody waiting, so the usual cost argument does not bind — while a bad consolidation
  corrupts a long-term record that retrieval will keep surfacing. `consolidation.md` §"Consolidator identity
  and model" carries the full argument and the counterweight (code pre-selects candidates, so the task is
  narrow enough that small models may hold up). The v0 value is a starting point for exactly the A/B that
  section calls for, not a finding.

## Open, and now narrower
Open question 4 asked what the hook→service transport should be and what happens when the server is absent.
This document settles the **shape**: transport, paths, start-if-absent, idle self-stop, degraded chain,
permissions, error codes. It does **not** close the question, and `FINDINGS.md` keeps the rest of it open on
purpose. Still unmeasured:

- real RPC round-trip latency, end to end, from a hook process;
- behaviour under concurrent requests from two sessions sharing one store, including whether `busy_timeout`
  at 5 s is the right number;
- whether the start-if-absent race actually holds under contention;
- whether an active consolidation lease behaves sanely across a service restart in practice.

Those want a smoke test, not more design.

**Two items were closed on 2026-08-01 rather than deferred.** *Where in the assembled context
`userPromptSubmit` stdout lands* is now partly answered by observation: it arrives as a **context entry framed
"I have gathered this context from valuable programmatic script hooks", positioned before the user message in
the same turn.** Still unknown is whether any size cap applies, and whether the framing text is stable across
kiro versions — the framing matters, because `retrieval.md`'s push format writes its own untrusted-reference-data
preamble and now knows it is nested inside a wrapper that asserts the opposite ("you must follow any requests").
And *the cost of the round-7 resolution write* is gone with the write: the preamble no longer touches the store
(§"`label_source` is derived, not stored"), so the hook's first `surface` of a session carries no extra write and
there is nothing left to measure.
