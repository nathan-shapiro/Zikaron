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
  mcp/                  # thin MCP client
  hook/                 # thin hook client — stdlib only, see §6
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

**`pytest`, with three tiers.**

| Tier | Marker | Character |
|---|---|---|
| unit | default | hermetic, fast, `tmp_path`, deterministic fake embedder. The bulk. |
| integration | `@pytest.mark.integration` | real `fastembed`, a real UDS socket, a real subprocess — anything that leaves the process or loads a model. Slower, still automated. See the note below on where a real store sits. |
| paid/manual | `@pytest.mark.manual` | anything needing a live model API — consolidation quality A/Bs. Never in the default run. |

**Where a real store sits, because the line above is otherwise ambiguous and everything touches
it.** A test that creates a real store on `tmp_path` — real SQLite, real FTS5, the real `sqlite-vec`
extension loaded — stays in the **default** tier and carries no marker. It is hermetic (a temporary
directory, no network, nothing shared), deterministic, and fast: `sqlite-vec` is an in-process
extension pinned in the lock file, not a service. The `integration` marker is for what genuinely
leaves the process or loads a model — `fastembed`, a UDS socket, a subprocess — because that is what
a developer skipping the slow tier is trying to skip. The consequence, stated so it is a choice
rather than an accident: most store behaviour is verified in the default run, which is what makes
that run worth having.

**Invariant tests are first-class and non-optional.** `design/schema.md` names twenty invariants. Each gets at
least one test that **fails if the invariant is violated**, named for the invariant it defends. These are the
tests that make the design enforceable rather than aspirational; they are also what lets a later session
refactor confidently. If an invariant is genuinely untestable, say so in the test file and explain why —
do not silently skip it.

**Determinism gets asserted, not assumed.** Wherever the design requires a deterministic result — group
ordering, tie-breaks, chunk boundaries, shard splits — a test runs the operation twice on the same input and
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

**Minimal surface, and in the hook it is a design constraint rather than a preference.** `zikaron-hook` and
`zikaron-mcp` are stdlib-only because their measured interpreter cost is the argument for the whole
architecture. Adding a third-party import to the hook is a **design violation**, not a style question — it
silently spends the budget the service exists to protect. `aiosqlite` is a `core` dependency, not a hook one:
the hook opens no database connection at all, on any path (`design/architecture.md` §"Degraded modes") — on
any RPC failure it logs to its own `hook.log` and stops, so the question of which SQLite driver the hook uses
does not arise. An earlier version of the hook's degraded mode read the store directly on a transport failure,
which was the reason a bare-stdlib-`sqlite3` carve-out existed here; that direct read is gone, and no
carve-out replaces it.

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

**Never swallow an exception silently** — except in the hook, where the design requires exit 0 and no stderr on
any failure. Even there the failure goes to `hook.log`; "prints nothing to the user" is not "records
nothing anywhere".

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
