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
    write/              # the write verbs and their validation
    consolidation/      # grouping, run/group state machine, the four verbs
    knowledge/          # the knowledge index: KB storage, scan, git change
                        # detection, its own chunker and retrieval arms, lifecycle
    signals/            # D30's six, as SQL
    config/             # layered resolution, declarative key schema
    errors.py           # the wire error codes, one enum
  service/              # asyncio UDS server, JSON-RPC, lifecycle
  harness/              # the one seam where a harness difference lives, as data (D34)
  knowledge/            # the detached indexer process and the `python -m` CLI
  mcp/                  # MCP server, built on fastmcp — see §6 on why it is not stdlib-only
  hook/                 # thin hook client — stdlib only, see §6
  install/              # the shipped artefacts for both harnesses, and the command that writes them
  cli/                  # the `zikaron` front door: dispatch only, no rule of its own
```

**Nothing shipped sits directly under `zikaron/`.** Every module lives in a package, because the
gate names packages in `--cov` flags and a loose module would be measured by none of them —
`tests/test_check_gate.py` asserts both halves.

*(This tree listed neither `core/knowledge/`, `core/write/`, `zikaron/knowledge/` nor
`zikaron/harness/` until 2026-09-22 — four real packages, one of them thirty modules — while §1's own
rule is that **package layout mirrors the domain**. A session following it would have put knowledge
code somewhere that already had a home. The file contradicted itself: §9 below already names
`zikaron/knowledge` and records that it shipped a milestone with no coverage floor over it. The
`install/` comment also said "the shipped **kiro** artefacts", stale since M15 gave both harnesses an
installer.)*

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
extension, pinned exactly in `pyproject.toml` like every other direct dependency, not a service.
The `integration` marker is for what genuinely leaves the process or loads a model — `fastembed`, a
UDS socket, a subprocess — because that is what a developer skipping the slow tier is trying to
skip. The consequence, stated so it is a choice rather than an accident: most store behaviour is
verified in the default run, which is what makes that run worth having.

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

**Invariant tests are first-class and non-optional.** `design/schema.md` names the **memory store's**
invariants and `design/knowledge-index.md` §13 the **knowledge index's**; no count is written here, since
either document may add one. *(This read "names twenty invariants", which covered the memory store alone
and left the knowledge index's outside a rule that calls itself non-optional. The practice already
exceeded the rule — `tests/test_knowledge_invariants.py` exists — which is the tell.)* Each gets at
least one test that **fails if the invariant is violated**, named for the invariant it defends. These are the
tests that make the design enforceable rather than aspirational; they are also what lets a later session
refactor confidently. If an invariant is genuinely untestable, say so in the test file and explain why —
do not silently skip it.

**Determinism gets asserted, not assumed.** Wherever the design requires a deterministic result —
group ordering, tie-breaks, chunk boundaries, shard splits — a test runs the operation twice on the
same input and asserts byte-identical output. "It was deterministic on my machine" is how ordering
bugs ship.

**Coverage is measured and gated.** The floor is **95%**, raised from 90% once the measured margin made
that safe, and it is a ratchet: it may rise, never fall. A test compares this sentence against
`pyproject.toml`, so the two cannot drift.

**It is measured over every package under `zikaron/`, and that list is checked rather than remembered.**
A package nobody names in a `--cov` flag reports *nothing* rather than reporting zero, so its absence is
invisible from a green gate — which is how `zikaron/knowledge` went a milestone with no floor over it at
all, the second time this project has lost a package that way. A test now asserts the flags in `check.sh`
name every package that exists.

**Two rules about where the floor sits, and they pull in opposite directions on purpose.** It is raised as
the suite earns it, and it is never set close to the figure a run happens to report, because the total is
load-sensitive: the socket-and-timing code takes error branches or
not depending on how a race lands, and three consecutive runs over one unchanged tree measured 97.64%,
96.85% and 97.64% with everything passing. A floor inside that spread turns a gate into a coin toss.

**Do not chase 100% on the total** — the last few percent buys tests written for the coverage tool rather
than for the code. **Do expect it of a new module**, where it is cheap and means something: a line nothing
reaches is either dead or untested, and both are worth knowing at the moment the module is written rather
than a year later. Where a line genuinely cannot be reached, delete it or mark it with a reason, rather
than leaving a reader to work out which of the two it is.

**Property-based tests where the design states a property.** `hypothesis` for things like: chunking never
loses content, RRF is monotone in each arm's rank, a receipt key is unique per `(session, kind, uuid, version)`.
Optional per-module, valuable where it applies.

## 5. Comments and docstrings

**Comment *why*, never *what*.** If what the code does is not obvious from the code, fix the code. A comment
restating the line above it is worse than no comment: it doubles the maintenance surface and drifts silently.

**The shipped product is the code. Commentary is overhead that has to earn its place, and the
default is not to add it.** A comment is a claim, nothing in the gate compares it to anything, and
it goes stale silently on the next edit to the code beneath it. Three rules follow, and they bind:

- **Never annotate a repair.** When you correct a defect, correct it. Do not add a paragraph
  explaining what was wrong, what it used to say, or how it was found — that belongs in the review
  file or in `FINDINGS.md`, which exist for it. Measured over a thirty-round audit of this
  repository: each pass's explanatory prose became the next pass's findings, at roughly one new
  defect per one-and-a-half fixes, while the software itself changed about four times.
- **Do not restate a fact the reader can get from the code, a constant, or a test name.** A
  docstring that enumerates what a function checks is a second copy of the function.
- **State a number, a count or an enumeration in one place only** — the place closest to the code
  that determines it. A figure repeated in prose is falsified by the next edit and nothing reddens.

**Do not treat the existing commentary in this repository as the standard to match.** It is denser
than these rules allow, because it accreted under an earlier reading of them. New code is held to
the rules above, not to the surrounding files; and a passage you are editing anyway is one you may
shorten.

**No circumstantial provenance in `zikaron/` or `tests/`. Ever.** No review-round numbers, no `FINDINGS`
references, no dates, no ticket ids, no *completed* milestone ids, no "as discussed". A reader who cannot
follow such a pointer is left worse off than if the reason had simply been stated — and the referent
usually stops existing: milestones end, rounds are forgotten, and `M12` means nothing to anyone who was
not there.

**Nor is a milestone that has not happened yet.** §5's rationale is that the referent stops
existing — milestones end, rounds are forgotten. That does not hold forward: when a temporary state
has an end condition, the planned work's name is the only way to say what ends it, and deleting it
leaves *"macOS is untested until …"* unanswerable. So `check.sh`, `.github/workflows/` and
`pyproject.toml` may name **planned** work. A milestone that has already happened is provenance and
goes.

**A normative pointer is not provenance, and this rule does not ban it.** `` `architecture.md`
§"Filesystem security" is normative `` names the **contract this code implements**, which a reader needs in
order to decide whether the code or the document is wrong. Provenance says *when and why this was written*;
a contract pointer says *what this must agree with*. Several drift tests parse exactly those sections, so the
pointer is load-bearing rather than decorative. **The distinction is stated because the rule's earlier
wording did not make it, and a sweep of the former nearly took ~350 of the latter with it.**

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

**The interpreter is the first dependency, and it is a floor with no cap.** `requires-python` is
`>=3.12`. The floor is real — the package uses PEP 695 type-parameter syntax, which is 3.12+. A cap is
deliberately absent: it makes a resolver backsolve to older, possibly broken releases of everything
else rather than failing with a clear message about the interpreter.

**Tested versions: 3.12, 3.13, 3.14.** "Supported" means "tested", and "tested" means the versions
`check-matrix.sh` runs — there is no looser sense of the word applied to a Python version anywhere in
this repository. Adding a version to that script is what makes it supported.

**Every stdlib difference between tested versions lives in `zikaron/service/asyncio_compat.py`, as one
row per behaviour change, keyed by the version that introduced it.** Nothing else under `zikaron/` or
`tests/` reads the running version, and a source-scanning test over both trees enforces that. Rows are
keyed by behaviour change rather than by supported version, so the module's table is the record of
which releases changed what; a release that changed nothing needs no row. A difference in a stdlib
module other than `asyncio` is a decision about where that seam widens, to be taken deliberately —
not a second compatibility module appearing beside the first.

**A version newer than the tested set is installable and untested.** `>=3.12` means an install on a
release newer than anything here has run against will succeed, and that is intended: the seam applies
its newest row, so a further change to a private name it depends on fails loudly at the first shutdown
rather than being absorbed by a fallback. Refusing such a version at startup was rejected — it is the
cap above, wearing a different hat.

**Deprecations are errors in `check-matrix.sh` only, never in `pyproject.toml`.** The local gate runs
one interpreter, so a deprecation raised only on a newer version is invisible to it whatever the
filter says; error-on-deprecation belongs where the interpreter varies.

**`venv`, latest stable, pinned exactly.** Resolve to current stable versions, pin each **direct**
dependency exactly in `pyproject.toml`, and bump deliberately rather than drifting: an unpinned range
means a green run today and a red one tomorrow with no change of ours.

**How far that pin reaches, and where it stops.** The transitive set is resolved when a virtualenv is
built, so two virtualenvs built on different days can carry different transitive versions, and the
outcome the direct pin prevents for direct dependencies is still open for transitives: under
error-on-deprecation, a transitive's deprecation on a newer interpreter can redden the matrix with no
change of ours.

**No lock file closes that gap here, and none is tracked.** The constraint route works — measured
2026-09-21, `pip install --constraint <a freshly generated lock> -e '.[dev]'` resolves on 3.14 — and
it is one `pip freeze` away against whichever virtualenv is verified on the day it is wanted. It is
not adopted because it changes what every virtualenv installs and needs its own verification on each
version. **A tracked lock file that nothing installs from buys none of that**: no gate reads such a
file, so it drifts with nothing to say so, and a resolution nobody verifies reads as authority over
an environment it no longer describes. Do not reintroduce one without making something install from
it.

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

**Any database handle — a `Store` or a `KnowledgeDatabase` — is held with `async with`, or closed in a
`finally`. That is a rule about process exit, not about tidiness.** The dedicated worker thread above is
**not a daemon thread**, so a connection nobody closes keeps
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

**A test that opens a raw `sqlite3` connection wraps it in `contextlib.closing`, or closes it in a
`finally`. `with sqlite3.connect(...)` is not closing it.** That form is a *transaction* context
manager: it commits or rolls back and leaves the connection open, which the module's own
documentation states and which five sites in this suite got wrong anyway.
It is invisible on 3.12, which emits nothing for an unclosed connection,
and on 3.13+ it emits `ResourceWarning: unclosed database` — **attributed to whichever test the
garbage collector happened to be inside, and not reliably to the test that opened it**, because since
3.11 the connection is held back by its own statement cache and survives until the cyclic collector
reaches it. Measured here: five sites, **47–49 warnings on 3.13 and 48–56 on 3.14 against 0 on 3.12**,
the count moving between runs of one tree because collection timing moves, and filed against two test
files that contained none of them. The leak detector above cannot see this class at all — it watches
`aiosqlite` worker threads, and a raw connection has none — and the project virtualenv is 3.12, which
says nothing, so in this repository only `./check-matrix.sh` reports it, and it reports it in the
wrong place. It never *fails* a run: both gate filters error on deprecations alone.
**The enumeration is `grep -rn 'sqlite3\.connect(' tests/` — nine lines today — and then reading each
hit for a `closing(` or a `finally`**, because two of the nine wrap across lines and show neither on
the matching line. The grep locates; the reading decides. Reading only the modules where such a
connection *ought* to be is a third thing, and it is what missed the fifth site.

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
long-running or off the critical path; a direct minimal write for anything that is neither; and
*nothing at all* for a process nobody is positioned to read.**

**The third case is the detached indexer, and it was missing until 2026-09-22 — shipped code
falsifying a binding rule.** `zikaron.knowledge.indexer` runs with all three streams sent to
`DEVNULL` (`knowledge/indexer/detach.py`). It is off the critical path, so the two-case rule as
written predicted it would use `logging`. The trade it actually makes: a log file per knowledge base
is several concurrent writers and a retention policy, bought for a diagnostic that one foreground
re-run produces on demand.

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

One command runs everything: format check, lint, type check, unit tests with coverage. `./check.sh` is the
per-edit gate and the definition of done for a change; `./check-matrix.sh`, which runs that whole script once
per version in §6's tested set, is additionally required before a milestone lands.

**CI is a third name and not a third gate, and the distinction is the content of this paragraph.**
`.github/workflows/check.yml` asserts the **matrix's** claim — every version in §6's tested set green on one
tree — against a commit rather than a working tree, by running `check.sh` once per version rather than by
running `check-matrix.sh` at all. The tree identity therefore comes from the SHA instead of from the
fingerprint `check-matrix.sh` has to sample twice, which is the one axis on which CI is stronger. It is
weaker on another, and that one does not close: there is no live harness on a runner, so the two harness
tiers stay local-only. A job carries the matrix's deprecation filters per job, or it is green on a tree the
matrix would redden. **Appending "and CI" to the two names above, without the distinction, makes the drift
worse rather than better.** `design/distribution.md` §"What CI asserts" is normative;
`tests/test_ci_workflow.py` enforces the properties that make the claim true.

```
ruff format --check .  &&  ruff check .  &&  mypy --strict zikaron tests  &&  pytest --cov  # every package
```

The type check covers the tests as well as the package, and the coverage floor covers **every** package under
`zikaron/` — one `--cov` flag each, checked against the tree by a test rather than maintained from memory.
`check.sh` is the authority on the exact flags; the line above is its shape, not a second copy of it.

`check-matrix.sh` adds one thing beyond running under each version: it turns deprecations into errors. That
belongs there and not in `pyproject.toml` — see §6.

**`--parallel` runs every tested version at once and is the normal form**, about 3.5 minutes on a warm tree
against roughly nine sequential. Each version gets its own coverage file and tool caches
(`ZIKARON_CACHE_SUFFIX`, which `check.sh` reads), because otherwise three runs share one `.coverage` and a
floor computed from three interleaved runs is not a floor. Virtualenv preparation stays sequential: an
editable install writes one `zikaron.egg-info/` at the project root, which concurrent installs would race.
Given version arguments instead it runs only those and labels its last line `SUBSET RUN`; a subset is not a
milestone gate.

**The milestone gate is every tested version green on one tree identity**, which the script prints on its
last line after `on`. Three subset runs are a gate only if their identities match — otherwise they are three
results about three different trees, which looks identical to three results about one.

**A sweep is also voided by an edit landing during it, whatever the file.** The script samples the identity
before and after and refuses if they differ, and the identity covers every difference from `HEAD` plus every
untracked file — so a review round appending to `reviews/`, or a note added to `FINDINGS.md`, costs the whole
set even though no reader of either is in the gate. Spawn writers after the last version reports, not into a
running sweep. Both halves of that have already happened here, once by an edit and once by a review round.
**`--parallel` removes the cross-run half of this** — one invocation samples the identity once, so there is
nothing to reconcile between versions — but not the during-a-run half, which is why the rule stays.

Formatter output is authoritative; formatting is not reviewed.

## 10. Bulk edits to prose in code

Comments and docstrings are the bulk of this codebase's text, and a sweep across many of them —
renaming a concept, dropping a convention, restating a reason — is an ordinary task. **It is also the single
most reliable way to introduce defects here**: one such sweep over ~85 files produced defects that four
successive review rounds were still finding, and a scripted repair of the first batch produced a syntax
error. The count is whatever the review trail records — the point is the rate, not the number.
Three rules, each earned; the third is stated as two passes.

**Never run a scripted reflow over mixed code and prose.** A wrapper that strips `#` to rejoin a
paragraph cannot tell a comment between two statements from the statements themselves. Stripping the
marker merges real code into prose and yields something that *looks* like a docstring: in the
measured case, a `# A stand-in for …` comment and the `await store.connection.execute(` beneath it
became one sentence. Reflow by hand, or leave the wrapping ugly — an awkward line break costs a
reader nothing, and this costs them a file that does not import.

**`ast.parse` every changed `.py` after a bulk edit.** One command over `git diff --name-only`, and
it is what caught the case above. The formatter will not: `ruff format` reports a parse failure only
for the file it is asked to rewrite, and a syntax error inside a string or a mis-merged comment can
survive it.

**The hunk is where you start, and it is not where the damage ends.** `CLAUDE.md`'s rule for
ordinary edits — *"after any edit, re-read the changed passage end to end together with the
passages around it"* — is unaffordable at 85 files, so a bulk edit needs two cheaper passes
instead of one expensive one.

**Pass one, mechanical, over the added lines.** Flag a line that is a lone connective (`rather`,
`and`, `which`), one ending in a dangling em dash, one under a dozen characters that is not
punctuation, and any line beginning lowercase after a closing parenthesis. This catches the
**cosmetic** half — every mangled wrap from the measured sweep was on that list.

**Pass two, over each changed file, for the damage that is nowhere near the hunk — and this is the
half that matters.** Deleting a clause orphans whatever pointed at it, and the pointer can be
hundreds of lines away: a sweep that removed *"the M5 done-when conditions"* from line 1 of a test
module left *"the five things the build plan asks **this milestone** to demonstrate"* on line 3 and
*"**the milestone's own done-when**"* on line 243, both now referring to nothing. So after editing
a file, grep **that file** for the deictics the deleted words were the antecedent of — `this
milestone`, `that round`, `an earlier version`, `the same`, `the clause`, `this fence` — and read
every hit.

*An earlier version of this section asserted the damage is "always **in the hunk**", which is the
convenient claim and the false one: a review round found nine orphans of exactly this shape, none
of them in a hunk. A rule that licenses not looking is worth checking against the sweep it was
written from.*
