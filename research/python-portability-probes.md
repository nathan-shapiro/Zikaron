# Portability probes: what actually binds Zikaron to a host Python

**Measured 2026-09-20**, on this machine (Linux 6.8, x86_64, Ubuntu-shipped `/usr/bin/python3`
3.12.3). Companion to `research/python-distribution-portability.md`, which is the delegated
literature/prior-art note; **this file is the measurement**. Where the two disagree, this one was
run.

Probe scripts and environments lived in the session scratchpad and are gone; every command is
transcribed below so any figure can be re-derived in a few minutes.

**Every `file:line` here describes the tree as it stood before M27, which is what a measurement note
is for — and M27 moved several of them.** `server.py:405` is now the call two lines below a comment
block; `main.py:197` is `:198`. The names beside each number still locate them.

---

## 1. The question

Zikaron ships as a source checkout plus `python3.12 -m venv .venv && pip install -e .`, and
`pyproject.toml` carries `requires-python = "==3.12.*"`. That assumes the user's machine has a
Python 3.12. Ubuntu 26.04, Fedora, Arch, macOS and Homebrew each ship a different minor, and some
ship builds with compile-time options that matter to us. What actually breaks, and where?

## 2. The `==3.12.*` pin has no recorded rationale anywhere in this corpus

`grep -rn "3\.12" design/coding-standards.md design/architecture.md design/overview.md` returns
**nothing**, and there is no `sys.version_info` or `sys.platform` branch anywhere in `zikaron/`.
D19 says only *"Python in a venv, latest stable versions"* — which argues for a floor, not a cap.

The **floor** is real and is 3.12: the package uses PEP 695 syntax at **18 sites across ten modules**
(`type Work[T] = ...` in `core/store/transactions.py`, `async def _in_one_transaction[T](...)` in
`core/indexing/writes.py`, and sixteen more). That is 3.12+ and is not worth giving up.
*This read "in ten places" — the module count wearing the word "places", from a grep whose output was
truncated by a `head`. Re-derived over the whole tree: 18 occurrences, 10 files.*

The **cap** appears to be development convenience that hardened into a distribution constraint
without ever being examined. It did, accidentally, hide **two** real defects — §5 and §5b.
*This said "one real defect — §5" while §5b sat in the same file; the count was corrected in
`FINDINGS.md` alone when §5b was written.*

## 3. Dependency wheel coverage is much wider than our pin

Read from `https://pypi.org/pypi/<pkg>/json`, release `1.28.0` / `0.1.9` / `0.8.0`:

| dependency | wheels shipped |
|---|---|
| `onnxruntime==1.28.0` | cp311, cp312, **cp313**, **cp314** (plus `t` free-threaded variants on Linux) × `manylinux_2_28` x86_64 + aarch64, `macosx_14_0_arm64`, `win_amd64`, `win_arm64` |
| `sqlite-vec==0.1.9` | `py3-none-` × `macosx_10_6_x86_64`, `macosx_11_0_arm64`, `manylinux_2_17` x86_64 + aarch64, `win_amd64` |
| `fastembed==0.8.0` | `py3-none-any` (pure Python) |

**No dependency stops us at 3.12.** The two that could have — onnxruntime and sqlite-vec — cover
3.11 through 3.14.

**One real platform gap, and it is not about Python at all: `onnxruntime` ships no
`macosx_*_x86_64` wheel.** ~~Intel Macs cannot install the current pin from PyPI.~~ **— refuted
2026-09-21 by `research/onnxruntime-macos-wheels.md`, which this milestone commissioned precisely to
check this sentence.** `fastembed==0.8.0` excludes only specific broken point releases rather than
everything below the cutoff, so on **cp312 and cp313** a resolver backtracks to 1.23.2 — the last
release with a `macosx_13_0_x86_64` wheel — and the install **succeeds**. Only **cp314** forces
`>=1.24.2` and fails outright. The platform decision is unchanged (`design/distribution.md` §1) and
its reason is now *supporting a year-stale pinned dependency* rather than *no wheel exists*.
That is a supported-platform question, independent of every distribution mechanism below.

## 4. The load-bearing compile-time flag, measured on the interpreters uv actually ships

`sqlite-vec` is a **loadable SQLite extension**, loaded through
`sqlite3.Connection.enable_load_extension` (`core/store/connection.py:48`). CPython only exposes
that method if it was configured with `--enable-loadable-sqlite-extensions`, and the delegated note
records python.org's macOS installer and conda-forge as shipping it **off**. So "ship our own
interpreter" is only an answer if *that* interpreter has the flag on. The note could not confirm it
for `python-build-standalone` — the build `uv python install` downloads — and named it the decision's
biggest unknown.

**It is on, and the whole storage stack works end to end on it.** `uv python install` was pointed at
a scratch `UV_PYTHON_INSTALL_DIR`, so these are downloaded interpreters, not the host's:

| interpreter | linked SQLite | FTS5 | `enable_load_extension` | `sqlite-vec` `vec0` KNN |
|---|---|---|---|---|
| uv-managed CPython **3.13.15** | 3.53.1 | ✓ | ✓ | ✓ `vec_version v0.1.9`, correct k=2 order |
| uv-managed CPython **3.14.7** | 3.53.1 | ✓ | ✓ | ✓ same |
| host `/usr/bin/python3` **3.12.3** (Ubuntu) | 3.45.1 | ✓ | ✓ | ✓ same |

The `vec0` probe was a real one — create a 4-dimensional `vec0` table, insert two vectors, run a
`MATCH ... AND k=2` query and check both the ordering and the distances — rather than a bare
`enable_load_extension(True)`, because the flag being present does not prove the extension loads.

**`uv python install 3.12` took 1.44 s** on this machine.

Not measured here, and still unconfirmed: the same flag on **macOS** python-build-standalone builds,
and whether a pip-installed `sqlite-vec` `.dylib` is Gatekeeper-quarantined. Both need real Apple
hardware.

## 5. Exactly one thing in Zikaron breaks on 3.13+, and it is our own private-API dependency

The full check gate was run against an unmodified copy of the tree with only
`requires-python` relaxed to `>=3.12`, in uv-managed venvs with the pinned dev dependencies:

| stage | 3.13.15 | 3.14.7 |
|---|---|---|
| `ruff format --check` | pass | pass |
| `ruff check` | pass | pass |
| `mypy --strict zikaron tests` | pass | pass |
| `pytest` | **18 failed, 2847 passed** | **18 failed** |
| coverage | 97.88% | 97.72% |

**Both runs fail identically**: the same 18 tests, one root cause, nothing else — so 3.12, 3.13 and
3.14 are a single shim apart, and 3.14 introduces nothing 3.13 did not. The two coverage figures
differ by 0.16 points, well inside the 97.64/96.85/97.64 flap this corpus has already measured over
an unchanged tree.

All 18 failures are one root cause, at one site:

```
AttributeError: 'Server' object has no attribute '_active_count'
zikaron/service/server.py:322
```

`RunningServer.close_all_connections` (`server.py:248`) reads `self.server._active_count` — a
**private** attribute of `asyncio.base_events.Server`, already carrying `# type: ignore[attr-defined]`
at all three call sites. CPython changed it in 3.13, as part of making `Server.wait_closed()` correct:

| | 3.12 | 3.13 / 3.14 |
|---|---|---|
| attribute | `_active_count: int` | `_clients: set[Transport]` |
| attach | `def _attach(self): self._active_count += 1` | `def _attach(self, transport): self._clients.add(transport)` |
| detach | `_active_count -= 1`; wake at 0 | `_clients.discard(transport)`; wake at `len == 0` |

**The call sites are the same points in the accept pipeline in both versions**, so
`len(server._clients)` on 3.13+ is the same quantity `_active_count` was on 3.12 — read from the
stdlib source of each interpreter rather than assumed.

Why the count cannot just come from our own `self._connections`: a connection is attached by the
server *before* its handler task registers itself in that set. `close_all_connections`'s own docstring
names this accept-pipeline race, and reading the server's count is what closes it. So the shim is
required; it is not incidental.

**Both names in this section read `ServiceServer._quiesce` until 2026-09-20, and no such class or
method exists in this repository.** The real pair is `RunningServer.close_all_connections`. The name
was invented while first summarising `server.py` and then carried into `FINDINGS.md` and
`design/build-plan.md`, surviving four review rounds, because every later reference was checked
against the summary rather than against the tree. It is the same failure as the unlink table below —
**a name or a count, once written down, stops being re-derived and starts being quoted** — and it is
worse here, because an invented identifier looks exactly like a correct one and `grep` refutes it in
one second.

Failing files: `test_service_encoder_failure_stop.py` (4), `test_service_lifecycle.py` (7),
`test_service_main.py` (4), `test_service_server.py` (3).

**The finding worth keeping is the shape, not the fix.** A version cap in `pyproject.toml` is not a
compatibility policy — it is a way of never finding out. The private-API dependency was written with
a `type: ignore` on it, reviewed, and shipped; the pin then guaranteed no run would ever contradict
it. What actually surfaced it was running the existing gate on a different interpreter, which cost
one `uv venv` and four minutes.

## 5b. The second 3.13 change, which the gate did **not** catch: sockets are now unlinked on close

**Raised by the operator as a suspicion before it was measured, and it was right as a class.** 3.13
added `cleanup_socket` to `loop.create_unix_server`, **defaulting to `True`**, so a Unix server now
removes its own socket file when it closes. `zikaron/service/server.py:405` calls
`asyncio.start_unix_server(_on_connect, path=sock_path, limit=_READ_LIMIT)` and passes no such
argument, so it takes the new default silently.

| | 3.12 | 3.13 / 3.14 |
|---|---|---|
| `create_unix_server(..., cleanup_socket=)` | parameter absent | present, default **`True`** |
| socket file after `close()` + `wait_closed()` | **survives** | **unlinked** |

**The dangerous instance is defended by CPython, and this was verified rather than read.** The
cleanup is not a blind `unlink`; `_UnixSelectorEventLoop._stop_serving` records the inode at bind
and unlinks only on a match:

```python
prev_ino = self._unix_server_sockets[sock]
try:
    if os.stat(path).st_ino == prev_ino:
        os.unlink(path)
except FileNotFoundError:
    pass
```

Probed with Zikaron's own ordering — A binds, A unlinks (as `main.py` does, *before* closing), a
successor B binds a fresh socket at the same path, then A closes:

| | A.close() deletes B's socket? | file survives A.close() with no successor? |
|---|---|---|
| 3.12 | no | **yes** |
| 3.13 | no | **no** |
| 3.14 | no | **no** |

So a dying service cannot take its successor's live endpoint with it on any supported version.

**What does change, and what it costs us.**

1. **`main.py`'s stated invariant is falsified.** It reads *"The socket is unlinked exactly once — by
   whichever self-stopping task fired"*, and the deliberate unlink-**before**-close ordering is
   justified by closing the connect-during-exit window. On 3.13+ there are two unlinkers. The
   *outcome* is unchanged, because our unlink runs first and asyncio's `stat` then hits
   `FileNotFoundError` and no-ops — but three neighbouring comments reason from that sentence.
2. **Nothing in the suite pins the contract.** Tests assert `not sock_path.exists()` *after*
   shutdown — **ten of them**, re-derived from the tree rather than carried: `test_service_lifecycle.py:60,98,147`,
   `test_service_main.py:92,203,559,723`, `test_service_encoder_failure_stop.py:56,76` and
   `test_service_lifecycle_integration.py:851`, which was added to `design/build-plan.md` §M27 after a
   review round and not to this list until a later one — an end state that is identical on both versions
   whoever performed the unlink. Nothing asserts **who** unlinks or **when**, which is precisely how
   a semantic change walked through 2,847 passing tests. The only near-miss,
   `test_hook_connect_race.py:450` (*"the pre-existing socket must never be unlinked"*), is about the
   hook's vetting, not the server's close.
3. **Asyncio's 3.13+ cleanup is the only unlink in this system that checks the inode**, and the thing
   we are about to switch off is therefore the strictest unlinker we have. There are **seven**
   socket-path unlinks under `zikaron/service/` and `zikaron/hook/`, in three guard classes —
   enumerated by `grep -rn 'unlink(' zikaron/service zikaron/hook`, which is the only method that has
   produced the right answer:

   | site | guard |
   |---|---|
   | `main.py:261` (**signal** path), `:360` (error path), `:492` (force-exit) | **none** — bare `sock_path.unlink(missing_ok=True)` |
   | `lifecycle.py:116` (idle self-stop), `:182` (encoder-failure stop) | **none** — same bare call; these are the *"self-stopping tasks"* `main.py:197` names |
   | `hook/connect.py:238`, `service/lifecycle.py:430` | `security.vet_socket_for_unlink` at the line above — socket-ness and **owner uid** only |
   | asyncio's own `_stop_serving`, 3.13+ | **inode identity**, recorded at bind |

   `vet_socket_for_unlink` is a *security* vet against a hostile `/tmp`, not an identity check. The
   asymmetry predates 3.13 and only becomes visible now that the stdlib is doing the stricter thing
   beside us.
   **This block has been wrong twice and the failure is worth more than the list.** It first said
   *"our four unlink sites"* and attributed the vet to `main.py:360`, which vets nothing; corrected, it
   said *five* and labelled `:261` "self-stop" when its own code comment at `main.py:257–260` says the
   signal path owns that unlink *because* the self-stopping tasks have already done theirs. Both
   corrections were made by re-reading **this table** rather than the tree. A grep takes ten seconds
   and was not run until a reviewer's third round. **An enumeration must be re-derived from source
   every time it is corrected, because the thing being corrected is the enumeration.**

**Decision, taken 2026-09-20 and briefed as `design/build-plan.md` §M27:** pass
`cleanup_socket=False`, which makes behaviour identical across every supported minor and keeps
"exactly one unlinker" true, at the cost of a conditional kwarg because the parameter is a
`TypeError` on 3.12. The `True` default was rejected — fewer moving parts, and it brings an inode
guard we lack, but it leaves the Python minor a live variable in the socket lifecycle, which is the
one thing the milestone exists to remove.
**The perturbation walk `CLAUDE.md` requires for lifecycle work — where the process is interrupted ×
3.12 vs 3.13+ × whether a successor bound × which unlink site ran — is dropped by operator decision
and recorded as a debt** in §M27's fence, not performed. `cleanup_socket=False` leaves those cells
exactly as they were, so the debt is pre-existing rather than created here; the sharpest cell is
written out concretely in that fence.
*The original text of this block posed the `cleanup_socket` choice as an open decision and called the
walk owed "before any review round". Both were superseded within the day; kept in outline because the
reasoning on each side is what the decision rests on.*

**The transferable half.** The `_active_count` break was loud — 18 red tests naming the attribute.
This one was **silent**, and it is the more dangerous of the two: a version cap suppresses both, but
only the loud one announces itself the moment the cap is lifted. Lifting a version cap therefore
means auditing the stdlib surfaces the code depends on *behaviourally*, not just running the suite
and reading the failures.

## 6. `uv tool install` produces exactly the artefact shape the installer needs

> **Added 2026-09-22, and it changes the documented command rather than this section's result.**
> The measurement below was run as
> `uv tool install --python 3.14 --python-preference only-managed <tree>`, "with no host 3.14
> present" — a configuration in which uv has **no choice** but to fetch a managed interpreter. §4's
> `enable_load_extension` result is about those managed builds, so a recommendation resting on both
> is only true for a command that actually gets one.
>
> **It does not, by default.** Measured in a scratch directory with an empty managed-interpreter
> directory (`UV_PYTHON_INSTALL_DIR` pointed at one), on uv 0.12.17:
>
> | command | answer |
> |---|---|
> | `uv python find 3.12` | **`/usr/bin/python3.12`** — the host build |
> | `uv python find --managed-python --no-project 3.12` | refuses: *"No interpreter found … in virtual environments or managed installations"* |
>
> uv's documented default is *prefer managed, fall back to a system Python when no managed one is
> installed* — the state of **every fresh uv install**. So on the machine the recommendation is
> written for, a Mac carrying python.org's 3.12 and a just-installed uv, the plain
> `uv tool install git+…` builds the tool environment on exactly the interpreter §4's argument says
> may not load `sqlite-vec`.
>
> **And then the same lesson applied to this very measurement.** `uv python find` **never downloads
> by design**, so "it refuses" says nothing about whether `uv tool install --managed-python` would
> go on to *fetch* one — which is the claim the README actually makes. Review round 2 caught that,
> one round after the corpus wrote down the rule it violates. **So the documented command itself was
> run**, 2026-09-22, on a copy of this tree in a scratch directory with `UV_PYTHON_INSTALL_DIR`,
> `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` all pointed at empty directories:
>
> | command, as run | interpreter the tool venv got | downloaded? |
> |---|---|---|
> | `uv tool install --managed-python <tree>` | `…/pythons/cpython-3.14.7-linux-x86_64-gnu/bin/python3.14` | **yes** — the managed directory went from empty to `cpython-3.14.7-…` |
> | `uv tool install <tree>` | **`/usr/bin/python3.12`** | **no** — its managed directory stayed empty |
>
> **And the point of the whole exercise, checked rather than assumed**: on the build the flag
> produced, `sqlite3.enable_load_extension` + `sqlite_vec.loadable_path()` loads cleanly — SQLite
> 3.53.1, CPython 3.14.7. So the flag is what makes the recommendation's own mechanism work, on the
> command a user types.
>
> `uv tool install --help` confirms the flag's meaning: *"Require use of uv-managed Python
> versions"*. `design/distribution.md` §2, `README.md` and D36 all carry it.
> **The transferable half, now earned twice in two rounds: a measurement taken under one command
> licenses no claim about another** — not about the same command without a flag, and not about a
> different subcommand of the same tool. This corpus's own `check-matrix.sh` already reaches for
> `--managed-python` for the mirror-image reason.

Zikaron's install contract depends on console scripts with **absolute paths**, written into
`.claude/settings.local.json` and `.mcp.json`, plus `sys.executable -m zikaron.service.main` for
start-if-absent (`install/entries.py` `Commands.from_this_interpreter`). Any distribution mechanism
that does not yield a stable absolute interpreter path breaks it.

`uv tool install --python 3.14 --python-preference only-managed <tree>` (the same copy, pin relaxed):

- installed the full dependency set including `onnxruntime` on **3.14**, with no host 3.14 present;
- produced `zikaron-hook` and `zikaron-mcp` whose shebang is
  `#!<UV_TOOL_DIR>/zikaron/bin/python` — an absolute path into the tool's own venv;
- put symlinks in `UV_TOOL_BIN_DIR`, with the tool venv at `tools/zikaron/lib/python3.14/`.

So `Commands.from_this_interpreter()` resolves correctly under it and the service spawn is unchanged.

**The heading overstates it, and the gap was found 2026-09-21 by asking a question this section never
asked: what does the user *type*?** Everything above is about the two **machine-facing** scripts, and
for those it holds. But `zikaron.install` and `zikaron.knowledge` are `python -m` entry points with
**no console script at all** — `[project.scripts]` names only `zikaron-hook` and `zikaron-mcp` — and
under `uv tool install` the tool venv's interpreter is not on `PATH`. So **the installer and the
knowledge CLI are both unreachable** on the very path this section recommends, short of the user
finding `<UV_TOOL_DIR>/zikaron/bin/python` by hand. `design/build-plan.md` §M30 adds a `zikaron`
umbrella.
**The shape of the miss is the transferable part**: this section verified the artefacts the *design
documents named* and was right about every one of them. Nothing here was wrong. What it never
enumerated is the set of things a human invokes, which is a different set — and the two CLIs missing
from it are the two no design document has ever had to mention, because until now the interpreter
running them was always the one the reader already had in their hand.

## 7. `uv run` / `uvx` is the wrong verb for the hook, by measurement

Minimum of 5 runs each, wall clock:

| invocation | min |
|---|---|
| bare `/usr/bin/python3 -c pass` | 17 ms |
| project venv `python -c pass` | 39 ms |
| `import zikaron.hook.main` (3.12 project venv) | 87 ms |
| `import zikaron.hook.main` (3.13 managed venv) | 75 ms |
| `uv run --no-project --python 3.12 python -c pass` | 27 ms |
| `uv run --project <tree> python -c pass` | 59 ms |

`uv run --project` costs **+20 ms** over calling the venv's interpreter directly, on every
invocation. The hook runs **once per user message** (README: ~50 ms end to end), so routing it
through `uv run` or `uvx` is a 25–40% tax on the one process whose latency this design has repeatedly
paid to protect (D22, M17's cold start). `uv tool install` writes a plain shebang and costs nothing.

**"Use uv" therefore means install-time uv, never call-time uv.** The distinction is invisible from
the documentation of either command, and the MCP ecosystem's common `uvx <package>` config pattern is
the wrong one to copy here.

Incidental: `import zikaron.hook.main` alone measures 87 ms here against the README's ~50 ms for the
whole hook process. Not chased — different machine load, and possibly a lazier import path in the
real entry point — but the two numbers should not both be quoted without reconciling them.

## 8. What is still open

1. **macOS has never been run at all** (README says so). Beyond the missing Intel wheel: `sun_path`
   is **104 bytes** on macOS against 108 on Linux, and `service/paths.py` already sizes the socket
   hash against "the ~108-byte `sun_path` limit"; `$XDG_RUNTIME_DIR` does not exist there, so every
   store falls to the `/tmp/zikaron-<uid>` branch of `runtime_dir`.
   **Measured 2026-09-21, and the result is mixed rather than a dismissal.** Calling
   `paths.runtime_dir` and `paths.socket_path` directly: **60 B** with
   `$XDG_RUNTIME_DIR=/run/user/1000`, **55 B** on the no-XDG branch — the branch macOS always takes —
   against macOS's **103 usable** bytes (104 including the NUL). *(The lock path is **not** subject to
   `sun_path`: it is an ordinary file opened for `flock`, and the bound applies only to what reaches
   `bind()`. An earlier revision added its 5 bytes to the figure as though it consumed budget.)*
   So there is
   **48 bytes of headroom on the macOS branch** — moved only by the uid's width (uid 501 leaves 49,
   a ten-digit uid 42). *(This read **45** here and in two other documents until review round 1
   subtracted it. 103 − 55 = 48, and no subtraction of 55 or 60 from 103 or 104 yields 45: an
   arithmetic slip propagated by copying rather than re-deriving.)*
   **The *store* path's contribution is safe by construction**: hashed to 32 hex characters, never
   embedded, so no project nesting depth moves the number. That answers
   `python-distribution-portability.md` §5's request to check the bound "for deeply-nested project
   directories" — the hash is the answer.
   **But the XDG branch is not bounded at all, and that is a real hole this note's first pass missed.**
   `runtime_dir` prepends `$XDG_RUNTIME_DIR` **verbatim**, and that input is user-controlled. The very
   convention §5 of the delegated note found for macOS —
   `/var/folders/zz/<~30 chars>/T/runtime-501/zikaron/<32 hex>.sock` — computes to ≈**106 bytes**, so
   anyone exporting it that way gets `OSError: AF_UNIX path too long` at bind. The earlier text here
   said that convention "would be longer … and buy nothing" and then reasoned only about the branch
   where nobody sets the variable. **`design/build-plan.md` §M29 now refuses an over-length path with
   a `bad_config`-class error**, per `architecture.md` §"Filesystem security"'s reject-never-repair
   rule.
   ~~**What remains open is narrower and is the real macOS risk**: whether `security.py`'s
   hostile-directory vetting passes on macOS's `/tmp`, which is a symlink to `/private/tmp` — exactly
   the shape such a check exists to distrust. Unmeasured, needs the runner.~~ **— mis-sized, and
   readable without a runner.** `ensure_runtime_dir` calls `lstat` on **the leaf**, not on its parents,
   so macOS's symlinked `/tmp` is traversed exactly as `stat` would traverse it and the vet is
   **expected to pass**. The runner confirms rather than discovers.
   **The genuinely unread macOS risk was somewhere else entirely**: `check.sh` wraps pytest in GNU
   `timeout`, which macOS does not ship, so a macOS CI job without a `coreutils` step dies in the
   shell script before one test runs.
   **The correction worth keeping is that the error ran both ways.** `FINDINGS.md` had called these
   items "all larger than anything M27 covers", which was oversized — but the first revision of *this*
   measurement then called two of the three "near-nothing", which was undersized, because it retired
   the branch macOS takes and never read the branch it does not. **A plausible risk restated across
   three documents acquires a size nobody measured; so does a plausible dismissal.**
   `design/architecture.md` §Paths still says "~108" and is **deliberately not edited here** — that
   sentence is normative and `design/build-plan.md` §M29 owns it.
2. ~~**Whether to support one Python or a range.**~~ **Decided 2026-09-20: a range**, `>=3.12`, behind
   the seam — §5b above and `design/build-plan.md` §M27. Shipping our own interpreter, which would
   have made one version *enough* and the seam optional rather than load-bearing, remains open as its
   own milestone; the two really were independent decisions that looked like one.
3. **Windows is out of scope by construction** — AF_UNIX transport — and nothing here changes that.
