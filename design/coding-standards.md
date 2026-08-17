# Coding standards

> Binding for all Zikaron code. Quality is non-negotiable: this is held to the standard of a senior engineer's
> production work, not a prototype's. `~/Memory` is prior art for *mechanisms*, not for code structure.
>
> A future session should read this **before** writing code, and treat a violation as a defect to fix rather
> than a style preference to debate.

## 1. Structure

**Package layout mirrors the domain, not a layer cake.**

```
zikaron/
  core/                 # the library. no transport, no process concerns.
    store/              # schema, open/create, migrations, permissions
    records/            # Memory, versioning, receipts, supersession
    indexing/           # chunking, FTS5 sync, vector writes
    retrieval/          # arms, fusion, eligibility, rollup, demotion
    consolidation/      # grouping, run/group state machine, the four verbs
    signals/            # D30's six, as SQL
    config/             # layered resolution, declarative key schema
    errors.py           # the wire error codes, one enum
  service/              # asyncio UDS server, JSON-RPC, lifecycle
  mcp/                  # MCP server, built on fastmcp — see §6 on why it is not stdlib-only
  hook/                 # thin hook client — stdlib only, see §6
  install/              # the shipped kiro artefacts and the command that writes them (M12)
```

**No `utils.py`, no `helpers.py`, no `common.py`.** Those names are where cohesion goes to die: they attract
anything that does not obviously belong elsewhere, and within a month nothing can be found or tested in
isolation. If something has no home, the domain model is missing a concept — add the concept.

**A module holds one cohesive concept.** Past roughly 400 lines, or the moment a file needs a table of
contents to navigate, split it. Length is a symptom, not the rule; the rule is one reason to change.

**No gigantic modules of loose functions.** Behaviour that operates on a type belongs with that type.

## 2. Domain model

**Types, not dicts.** Every payload the design specifies becomes a typed object — `Memory`, `Chunk`,
`ReadReceipt`, `ClientEnvelope`, `ConsolidationGroup`, `SurfaceResult`. Frozen dataclasses for values,
`Enum`/`IntEnum` for closed sets. A renamed field then fails at type-check time instead of surfacing as a
`KeyError` in production.

**Anything the design states as a table becomes data, not scattered literals.** The design gives error codes,
config keys with types and ranges, and `event` kinds as tables. Each gets exactly one declarative definition in
code, and a test asserts it matches the design table — same names, same numbers, same ranges. Drift between a
spec table and a literal buried in a call site is the most expensive class of bug this project can have, and it
is entirely preventable.

**Parse, don't validate downstream.** Validate at the boundary, construct a typed value, and let everything
inward assume it is well-formed. The validation-precedence ladders are boundary logic and belong in one place
each, in the documented order — that order is observable, so it is behaviour, not an implementation detail.

## 3. Typing

Full annotations on everything. `mypy --strict` (or pyright strict) passes with no ignores; a genuinely
necessary ignore carries a comment saying **why** it is unavoidable. No `Any` crossing a module boundary.

## 4. Tests

**`pytest`, with five tiers.**

| Tier | Marker | Character | In the default run |
|---|---|---|---|
| unit | default | hermetic, fast, `tmp_path`, deterministic fake embedder. The bulk. | yes |
| integration | `@pytest.mark.integration` | real `fastembed`, a real UDS socket, a real subprocess — anything that leaves the process or loads a model. Slower, still automated. See the note below on where a real store sits. | yes |
| harness, kiro | `@pytest.mark.integration_kiro` | needs a real, **working** `kiro-cli` on `PATH` | **no** |
| harness, Claude Code | `@pytest.mark.integration_claude` | needs a real Claude Code binary on `PATH` | **no** |
| paid/manual | `@pytest.mark.manual` | anything needing a live model API — consolidation quality A/Bs. | **no** |

**Why a third-party binary is a different tier from `integration`, added in M15 and earned rather
than anticipated.** Everything `integration` calls "real" is **Zikaron's own** — our subprocess, our
socket, our model download — and is reproducible on any machine that can run the suite. A harness
binary is neither: it must be installed *and* in a working state, which is somebody else's
credential. An expired `kiro-cli` token turned `./check.sh` red for a reason with no relationship to
the code, and the same tests would go **green** on a machine whose harness behaved differently. A
gate that can mislead in both directions is not a gate, so these leave the default run and are asked
for by name:

```bash
.venv/bin/pytest -m integration_kiro
.venv/bin/pytest -m integration_claude
```

**The rule that keeps this honest: nothing may live *only* in those tiers.** A behaviour they cover
must also be covered hermetically, by stubbing the binary — `conftest.stub_harness_binaries` exists
for exactly that, and it is opt-in rather than autouse so that tests *about* the binary checks can
still see the real functions. What legitimately remains binary-only is claims about the
**harness's own** behaviour, where a stub would only assert our belief back to us, each saying so in
its docstring. Deliberately not listed or counted here — that clause went stale twice in one
afternoon, which is the tell: **the tiers are the enumeration**
(`pytest -m integration_kiro --collect-only -q`), and what makes a test belong in one is the test
above, not membership in a paragraph.

**A tier that cannot fail is worse than no tier**, and both of these nearly shipped that way. The
Claude Code name test originally asserted a value the module's own autouse fixture had stubbed to
`True`, and skipped when the binary was absent — so a wrong name made the tier exit 0. The kiro tier
then kept the same shape one review round longer, guarded by `pytest.skip`, while this paragraph
already claimed otherwise.

So: **every test in these tiers fails rather than skips when its binary is absent**, because the
tier is only ever reached by explicit request — running it on a machine that cannot serve it is a
mistake about the machine, and a skip reports success for it. It also reports success for the other
cause, which is the one no other test can see: `HarnessSpec.harness_binary` naming a binary that
does not exist. The spec↔design drift guard cannot catch that (it pins the code against
`harness.md`, not against the machine, and an upstream rename lands on both at once), so these tiers
are the only place a wrong name is observable at all.

**That rule is enforced, not requested** — `tests/conftest.py`'s `pytest_runtest_makereport` wrapper
converts a skip inside either tier into a failure, keeping the original reason in the message. It is
mechanical because *stating* it did not work: this paragraph asserted the rule while five of the six
tests it governed used `pytest.skip`, and correcting the prose would have left it able to go stale
again the next time someone added a test. A normative sentence the suite can falsify is the
always-loaded-file defect one layer up.

**Verified by mutation, both directions:** with both seam names deliberately misspelled, all six
tests fail; restored, all six pass; and a deliberately-skipping test added to a tier fails through
the wrapper. A rule of this kind is worth exactly the check that was run against it.

**Markers use underscores** — `integration_kiro`, not `integration-kiro` — because a marker is an
attribute lookup on `pytest.mark`, so a hyphen is not expressible.

**Where a real store sits, because the line above is otherwise ambiguous and everything touches
it.** A test that creates a real store on `tmp_path` — real SQLite, real FTS5, the real `sqlite-vec`
extension loaded — stays in the **default** tier and carries no marker. It is hermetic (a temporary
directory, no network, nothing shared), deterministic, and fast: `sqlite-vec` is an in-process
extension pinned in the lock file, not a service. The `integration` marker is for what genuinely
leaves the process or loads a model — `fastembed`, a UDS socket, a subprocess — because that is what
a developer skipping the slow tier is trying to skip. The consequence, stated so it is a choice
rather than an accident: most store behaviour is verified in the default run, which is what makes
that run worth having.

**The identical reasoning places `fastmcp.Client(mcp)` in the default tier too.** Connecting an
in-memory `Client` to a `FastMCP` instance built by `zikaron.mcp.server.build_server` never opens a
socket, spawns a subprocess, or loads a model — it calls Python objects directly inside the test
process, which is exactly what the default tier's own definition asks for. What a test built this
way *cannot* exercise is `zikaron.mcp.connection.ServiceConnection`'s own real behaviour, since that
class is normally monkeypatched out for a tool-surface test; a test that instead needs a real
service on the other end of `ServiceConnection` — start-if-absent, reconnect after the service dies —
is real UDS-and-subprocess work and belongs in `integration`, per the rule above.

**And the identical reasoning again for a real `AF_UNIX` socket bound entirely in-process, on a
background thread of the same test process.** `socket.socketpair()`, or a `socket.socket(AF_UNIX,
...)` bound by a small fake-server thread the test itself starts and joins, is a real socket — real
`bind`/`connect`/`send`/`recv` calls, exercising the actual framing and error-handling code a mock
would paper over — but it never leaves the test process, spawns a subprocess, or talks to anything
outside it, which is exactly the property the tier boundary is defined by, not by whether a socket
API happens to be involved. `zikaron.hook`'s own test suite uses this pattern extensively (a
background-thread fake `zikaron-service` standing in for the real one) specifically to exercise
`connect.py`/`rpc.py`'s real socket code paths — partial sends, malformed responses, the exact
byte-level framing — at unit-test speed and determinism, reserving `integration` for what actually
needs a second process: a real spawned `zikaron.service.main`, or two real racing clients whose
concurrency guarantees only mean something across genuinely separate threads or processes
contending for the same file descriptor. The consequence, stated the same way the store carve-out
above states it: most of the hook client's own socket-framing behaviour is verified in the default
run, and only its real process-lifecycle behaviour (start-if-absent against a real subprocess, the
lock actually serializing two genuinely concurrent racers) needs `integration`.

**A test holds its store with `async with`, for the reason §6 gives.** A test is the one caller whose cleanup
is routinely skipped — a failing assertion jumps straight over whatever close follows it — so the fragile form
is what turns a one-line failure into a session that never exits and never prints. `tests/conftest.py` fails
any test that leaks a connection and stops the thread it left, which is what keeps a mistake here reportable
rather than fatal.

**Invariant tests are first-class and non-optional.** `design/schema.md` names twenty invariants. Each gets at
least one test that **fails if the invariant is violated**, named for the invariant it defends. These are the
tests that make the design enforceable rather than aspirational; they are also what lets a later session
refactor confidently. If an invariant is genuinely untestable, say so in the test file and explain why —
do not silently skip it.

**Determinism gets asserted, not assumed.** Wherever the design requires a deterministic result — groupordering, tie-breaks, chunk boundaries, shard splits — a test runs the operation twice on the same input and
asserts byte-identical output. "It was deterministic on my machine" is how ordering bugs ship.

**Coverage is measured and gated.** `pytest-cov`, with a floor on `zikaron/core` (start at **90%**) and the
report published on every run. The floor is a ratchet: it may rise, never fall. Do not chase 100% — the last
few percent buys tests written for the coverage tool rather than for the code.

**Property-based tests where the design states a property.** `hypothesis` for things like: chunking never
loses content, RRF is monotone in each arm's rank, a receipt key is unique per `(session, kind, uuid, version)`.
Optional per-module, valuable where it applies.

## 5. Comments and docstrings

**Comment *why*, never *what*.** If what the code does is not obvious from the code, fix the code. A comment
restating the line above it is worse than no comment: it doubles the maintenance surface and drifts silently.

**No circumstantial provenance in code. Ever.** No review-round numbers, no `FINDINGS` references, no dates, no
ticket ids, no "as discussed". The design corpus will be reorganized; a comment pointing into it rots on the
first move, and a reader who cannot follow the pointer is left worse off than if the reason had simply been
stated.

State the reason on its own terms so it survives:

```python
# BAD — circumstantial, rots, and tells the reader nothing they can act on
# get-or-create per round 7 finding 1; see FINDINGS open question 4

# GOOD — the reason, timelessly, in terms of this code
# Read the row back inside the insert's transaction: on a conflict the stored
# row wins, and returning the value we computed would disagree with what every
# later request replays.
```

**Docstrings state the contract, not the implementation** — what a caller may rely on, what it must supply,
what it will be told when it is wrong. Public API only; a docstring on a three-line private helper is noise.

## 6. Dependencies

**`venv`, latest stable, pinned exactly.** Those are not in tension: resolve to current stable versions, then
pin them exactly in a lock file so a build is reproducible, and bump deliberately rather than drifting. An
unpinned range means a green run today and a red one tomorrow with no change of ours.

**`zikaron-core`'s SQL runs through `aiosqlite`, never bare stdlib `sqlite3`.** Not a preference: a handler
that calls the blocking sqlite3 API directly can hold the single-threaded event loop for as long as SQLite's
own `busy_timeout` retries, starving whichever other coroutine holds the lock it is waiting on — confirmed
locally as a genuine self-inflicted deadlock (M0 spike 3), which surfaces as an ordinary-looking
`store_busy` and is indistinguishable from real contention without tracing it back to the handler.
`aiosqlite` closes this structurally: each connection runs on its own dedicated worker thread, so there is no
synchronous call path for a handler to get wrong. Re-verified against every mechanism `core` needs — extension
loading (`sqlite-vec`, via `aiosqlite.Connection.load_extension`, not by reaching into the wrapped connection),
`vec0` KNN, the FTS5 external-content amend/erasure sequence, and two-writer `busy_timeout` contention — in
M0 spike 5, `research/spike-results.md` §"Spike 5". `aiosqlite==0.22.1` verified; pin exactly.

**A `Store` is held with `async with`, or closed in a `finally`. That is a rule about process exit, not about
tidiness.** The dedicated worker thread above is **not a daemon thread**, so a connection nobody closes keeps
its process alive after all its work is done — and it prints nothing while not exiting, because CPython joins
non-daemon threads *before* running `atexit` handlers, so there is no hook late enough to rescue it. Measured
in this repository's own suite: a run whose tests all completed in 0.76 s then hung indefinitely with an empty
output pipe, the only evidence being a `threading._shutdown` traceback after an interrupt. For
`zikaron-service` the same defect is worse than a hang: idle self-stop would run to completion and unlink the
socket while the process stayed alive, so the next client's start-if-absent would raise a **second** server
against a store the first still holds.

Two consequences, neither optional. `Store` implements `__aenter__`/`__aexit__` precisely so that the correct
form is also the shortest one, and every holder — the service, a future migration tool, a test — uses it or an
equivalent `finally`. And the test suite makes a violation **loud** rather than silent: an autouse fixture in
`tests/conftest.py` fails the test that leaked and stops the thread it left, so the session still reports
instead of hanging. Marking the thread a daemon was considered and rejected — it needs private-attribute
surgery on a pinned dependency to hide a convention we can simply hold, and it would trade a loud hang for a
silent exit, when the loud version is what found this in the first place.

**Minimal surface in the hook is a design constraint, not a preference — and it does not extend to the MCP
client.** `zikaron-hook` is stdlib-only because its measured interpreter cost is the argument for the whole
push architecture: it fires on every `userPromptSubmit`, so its import cost is paid once per user message, and
D12's whole case for keeping retrieval on that critical path only holds if that repeated cost stays near-zero.
Adding a third-party import to the hook is a **design violation**, not a style question — it silently spends
the budget the service exists to protect. `aiosqlite` is a `core` dependency, not a hook one: the hook opens
no database connection at all, on any path (`design/architecture.md` §"Degraded modes") — on any RPC failure
it logs to its own `hook.log` and stops, so the question of which SQLite driver the hook uses does not arise.
An earlier version of the hook's degraded mode read the store directly on a transport failure, which was the
reason a bare-stdlib-`sqlite3` carve-out existed here; that direct read is gone, and no carve-out replaces it.

`zikaron-mcp` is a **deliberate exception to "minimal surface," decided by the operator, and the reason is a
different cost model rather than a relaxed standard.** It takes an exact-pinned dependency on `fastmcp`
(`design/architecture.md` §Components has the measurement: `import fastmcp` costs ~595 ms cold on this
machine, in the same range as the cold embedder load that justifies the service's own existence). That cost is
acceptable specifically because kiro spawns one MCP server process per agent instance — once per session or
subagent, not once per message — so it is a one-time cost per spawn, never a per-turn tax the way the hook's
import cost would be. The decision was made after M9's own fourteen-round review of a hand-rolled
`asyncio.start_unix_server` failed to converge: reusing a maintained framework's own tested tool-registration,
schema-generation and stdio-transport machinery, rather than re-deriving that surface by hand a second time
inside `zikaron-mcp` too, was judged the better trade at this cost model. Nothing about this revises the
hook's own rule, and nothing about the hook's rule should be read backward onto the MCP client.

**Logging is split by process, on purpose, and it is a documented exception rather than an inconsistency.**
`zikaron-service` and the `agentSpawn` hook's detached warm helper both use stdlib `logging` — each to its own
file (`service.log`, `warmup.log`), never a shared one, since `logging.FileHandler` has no cross-process append
locking and two independent processes writing one path through it is a real corruption risk, not a style
choice. Both processes are off any latency-critical path (the service is long-running and warm; the helper
runs detached, before the first `userPromptSubmit`), so `logging`'s import cost is irrelevant to them.
`zikaron-hook` does **not** use `logging`, even though `logging` is itself stdlib and so would not violate the
minimal-surface rule above on its own terms: measured on this machine, `import logging` alone costs **~15 ms**
of interpreter startup — in the same range as the `socket`/`json`/`os` cost this document's whole
stdlib-thinness argument rests on, and roughly double the hook's bare interpreter-launch cost. A hook
invocation writes at most one line to `hook.log` and then exits; it has no log lifecycle for `logging`'s
formatters, handlers or levels to manage, so the entire mechanism is `open(path, "a")` and one `.write()` call.
The rule, stated plainly so a future change has to name it rather than drift into it: **`logging` for anything
long-running or off the critical path; a direct minimal write for anything that is neither.**

## 7. Errors

The design's numeric codes are a wire contract. One `IntEnum`, one mapping from code to message and payload
shape, and every raise site references the enum. Never a bare integer at a call site.

**Never swallow an exception silently** — except in the hook, where the design requires exit 0 on
any failure. Even there the failure is never lost: it goes to `hook.log` verbatim, and a short
relay instruction goes to stdout so the model can tell the operator something is wrong — measured
directly (a live spike against a real kiro session) to be the one channel that actually reaches
the model on this build; stderr, tried first, was measured not to surface visibly at all.
"prints nothing to the user" was the original design and no longer describes the failure path —
see `design/architecture.md` §"Degraded modes" for the full history and the measurement.

## 8. SQL

Parameterized, always. No string interpolation of values, ever.

SQL for an aggregate lives with that aggregate, in one place, not inlined across call sites — a schema change
should touch one module. The six D30 signals ship as **executable SQL** with tests, which is what turns a prose
definition into something that can be wrong in a detectable way.

## 9. The check gate

One command runs everything: format check, lint, type check, unit tests with coverage. It must pass before any
milestone is called done.

```
ruff format --check .   &&  ruff check .   &&  mypy --strict zikaron  &&  pytest --cov=zikaron/core
```

Formatter output is authoritative; formatting is not reviewed.
