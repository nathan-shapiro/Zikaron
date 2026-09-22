# Distribution — supported platforms, how Zikaron is obtained, and what CI asserts

> **Normative** for the four subjects below. `design/overview.md` §4 carries **D35** (supported
> platforms) and **D36** (distribution and acquisition) as one-line decisions with rationale; this
> document is where their detail lives. Where this document and `design/build-plan.md` §M28 disagree,
> **this one wins** — §M28 recorded these decisions only because this file did not exist yet.
>
> Written at M28, 2026-09-22. Rejected alternatives are at the end, per the standing rule that a
> design document states what we are doing and keeps the discarded options together rather than
> interleaved.

---

## 1. Platforms

**Linux and macOS arm64 are supported. Windows and Intel Macs are not.**

| platform | state | what decides it |
|---|---|---|
| Linux x86_64 | **supported, verified** | the gate runs here on 3.12, 3.13 and 3.14 |
| Linux aarch64 | **unverified** | wheels exist for every dependency (`onnxruntime` ships `manylinux_2_28_aarch64`); nothing has run there, and no milestone claims it |
| macOS arm64 | **supported, unverified until M29** | CI is the only instrument; no Apple hardware is available |
| macOS x86_64 (Intel) | **not supported** | `onnxruntime`, below |
| Windows | **not supported** | transport, below |

**Windows is out by transport, not by effort.** The RPC layer is an `AF_UNIX` socket, and asyncio's
Unix transports are POSIX-only. Supporting Windows means a second transport behind the RPC seam, with
its own security model — a named pipe's ACLs are not a socket's 0600 — and its own tests. That is a
milestone, not a flag, and nothing about it is started.

**Intel Macs are out because of `onnxruntime`, and the reason is narrower than "no wheel exists".**
Measured from PyPI and the project's own release notes (`research/onnxruntime-macos-wheels.md`,
2026-09-21):

- **1.23.2** (2025-10-22) is the last release publishing a `macosx_13_0_x86_64` wheel.
- **1.24.1** dropped it, saying so in its release notes: *"x86_64 binaries for macOS/iOS are no longer
  provided and minimum macOS is raised to 14.0."* There is no 1.24.0 on PyPI.
- No `universal2` wheel exists near the cutoff — the only one the note found was at 1.12.0 in 2022,
  and split arm64/x86_64 wheels have been used ever since. *(The note checked four releases rather
  than every one, and says so; "exactly one, ever" would overstate it.)*

**But `fastembed==0.8.0` does not require ≥ 1.24.2 on every interpreter.** It excludes specific broken
point releases rather than everything below the cutoff, so on **cp312 and cp313** a resolver backtracks
to 1.23.2 and the whole stack installs on an Intel Mac. Only **cp314** forces a release with no x86_64
wheel at all.

So the honest statement, and the one to repeat rather than the short version: **supporting Intel Macs
would mean supporting a year-stale pinned `onnxruntime` on two of three interpreters and a hard install
failure on the third.** That is a maintenance commitment to somebody else's abandoned build, not a
missing wheel we could work around.

---

## 2. Acquisition

**`uv` is the recommended path. A host Python remains supported.**

```bash
# Recommended. `--managed-python` is not optional — see below.
uv tool install --managed-python git+https://github.com/nathan-shapiro/Zikaron.git

# Alternative: a source checkout and a host interpreter.
git clone https://github.com/nathan-shapiro/Zikaron.git && cd Zikaron
python3 -m venv .venv && .venv/bin/pip install -e .
```

**Why `uv` is recommended rather than required.** `enable_load_extension` is a **compile-time** CPython
option and `sqlite-vec` cannot load without it. It is **reported** off in some widely used
distributions — python.org's macOS installer and conda-forge among them — and on in others.
**The asymmetry of evidence is the whole argument and is worth stating exactly**: the
python-build-standalone builds `uv` fetches were *measured* to have it
(`research/python-portability-probes.md` §4), while the two builds named above are
`research/python-distribution-portability.md`'s delegated reading, which hedges them
("historically", "most likely to fail") and files conda-forge at medium confidence. So `uv` is the
path **known** to work; the others are not known to fail. That asymmetry is enough to found a
recommendation and not enough to found a refusal, which is exactly why a host Python stays
supported. **macOS is where a host interpreter is likeliest to fail this test**, which is why the
recommendation is strongest there. *(M29 can close the hedge for one dollar of runner time: a
python.org build is one `curl` away on the macOS job.)*

**`--managed-python` is what makes the previous paragraph true, and without it the recommendation is
false on exactly the machine it is written for.** uv's default preference is *managed, but fall back
to a host interpreter when no managed one is installed* — which is the state of every fresh uv
install. **Measured on the documented command itself**, 2026-09-22, against a copy of this tree in a
scratch directory with `UV_PYTHON_INSTALL_DIR`, `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR` all empty
(probe note §6):

| command, as run | interpreter the tool venv got | downloaded a managed build? |
|---|---|---|
| `uv tool install --managed-python <tree>` | `cpython-3.14.7-linux-x86_64-gnu` | **yes** |
| `uv tool install <tree>` | **`/usr/bin/python3.12`** | **no** |

And on the build the flag produced, `sqlite_vec` loads cleanly — SQLite 3.53.1. So on a fresh Mac
carrying python.org's 3.12, precisely the build whose `enable_load_extension` is reported off, the
plain command would build the tool environment on the interpreter this section says may not work,
and retrieval would fail at first use with nothing pointing back here.
*(Two review rounds shaped this paragraph and both taught one rule. Round 1: the recommendation was
argued from a probe that had run `--python-preference only-managed` explicitly, while the documented
command carried no such flag. Round 2: the fix then rested on `uv python find --managed-python`,
which **never downloads by design** — so "it refuses" said nothing about whether `uv tool install`
would go on to fetch. **A measurement taken under one command licenses no claim about another**, and
the corpus had written that rule down one round before breaking it again.)*

**Why install-time only, never at call time.** `uv run`/`uvx` cost **+20 ms per invocation** (probe note
§7), and `zikaron-hook` runs once per user message. That budget is the one this design has repeatedly
paid to protect: D31 kept the thin clients **stdlib-only** on measured interpreter cost — 10.9 ms bare,
20.6 ms with `socket` and `json`, 21.8 ms adding `sqlite3` — on the argument that an HTTP client in the
hook would spend more than the transport saves. *(An earlier draft of this sentence said D31 made that
choice "for 11 ms". D31 states no such figure; 11 was this document subtracting two of its numbers and
presenting the result as a quotation. The measurements are D31's; the delta was not.)* So `uv` builds the
environment and then gets out of the way; the installed console scripts carry absolute shebangs and
invoke no resolver.

**SQLite comes with the interpreter, and that is the one axis no seam absorbs.** Measured on this
machine: 3.45.1 on a distribution-packaged 3.12 against 3.53.1 on downloaded 3.13/3.14 builds. FTS5
ranking can therefore vary by host. **M27 made this observable rather than solved**: the service logs
both the Python and the SQLite version at startup, and CI prints them per job. Pinning a
*statically-linked* interpreter is the only fix short of vendoring the library — and the adjective is
load-bearing, since a distribution build loads the system `libsqlite3.so` and so pins nothing.

**Model files are fetched, never redistributed** — an operator constraint, stricter than the licence
requires. The embedder is acquired at first use and cached. M30 owns the durable cache, the pinned
Hugging Face revision and the SHA256 allowlist; until then the cache is fastembed's default, which is a
temporary directory and is lost on reboot.

---

## 3. The version scheme

**Semver, `0.x` while the install contract may still change.** The install contract is the set of
shapes and locations of the artefacts the installer writes into a harness's configuration.

**The one rule that matters: a release whose installed artefacts differ in *shape* from the previous
one is a minor bump, never a patch.** Those paths are written into harness configuration files that an
upgrade must be able to refresh, and a patch bump tells a reader that nothing needs refreshing. A
version number is the only signal an upgrading user gets before the harness reads a config that no
longer matches what is installed.

`0.1.0` is the first version with this scheme; everything before it was `0.0.0`, which was never a
statement about anything.

---

## 4. What CI asserts

**CI is not a third gate.** Three names now exist and they make one claim between them:

| instrument | claim | tree identity comes from |
|---|---|---|
| `./check.sh` | the per-edit gate and the definition of done for a change | the working tree in front of you |
| `./check-matrix.sh` | every supported version green on one tree — required before a milestone lands | a fingerprint over `HEAD` plus every staged, unstaged and untracked difference, sampled twice |
| CI (`.github/workflows/check.yml`) | **the same claim as the matrix**, against a commit | the SHA |

**So CI runs `check.sh` once per version rather than running `check-matrix.sh` at all.** A site that
describes the definition of done by appending "and CI" to a list of two has made the drift worse, not
better: the distinction is the content.

**Stronger than the matrix on one axis.** The matrix has to build and sample a tree fingerprint because
a local tree moves while a run is in flight — it caught its own author editing `CLAUDE.md` mid-run. A
job checks out one commit, so *every version saw the same tree* is guaranteed rather than asserted.

**Weaker on another, and this is the residual M29 cannot close.** There is no live harness in CI, so
`integration_kiro` and `integration_claude` remain local-only and nothing in CI exercises a real
session pushing or searching. What CI proves about macOS is that the package builds, imports,
loads the `sqlite-vec` extension and passes the whole hermetic suite there. **No test count is written
here** — this document quoted one when it was drafted, taken from `FINDINGS.md` rather than from a run,
and M28's own new test files had already falsified it. The count is whatever `check.sh` prints. What CI
cannot prove is that a real Claude Code or kiro session on a Mac writes and reads memories — nor,
equally unproven and more platform-coupled, that `zikaron_knowledge_add` there spawns a detached
indexer which survives its caller and finishes a build, since that rests on POSIX process-group
behaviour (`knowledge/indexer/detach.py`) no hermetic test exercises on that platform.

**What the macOS job does prove, which this project's own first framing got wrong.** The `integration`
tier — real fastembed, real sqlite-vec, real sockets, real subprocesses — is *in* the default hermetic
run. So a macOS job performs the whole pip-install-then-`load_extension` sequence on real Apple
hardware, and a quarantined `.dylib` would fail it. **Caveat: a runner's security context is not a
desktop's**, so this is strong evidence about Gatekeeper rather than proof.

### What a job must carry, and why each would be silent if lost

- **Both deprecation filters**, `PYTEST_ADDOPTS` and `PYTHONWARNINGS`, exactly as `check-matrix.sh`
  sets them. One reaches pytest's own process and the other propagates to the subprocesses this suite
  spawns. A job omitting either is **green on a tree the matrix would redden**, which would make CI the
  looser definition of done.
- **An interpreter from `uv`**, not `actions/setup-python`, for the `enable_load_extension` reason in
  §2 — it is what makes the evidence above evidence *about the binary users will run*.
- **GNU `timeout` on macOS.** `check.sh` wraps pytest in it; the runner image's readme lists no
  `coreutils` among its installed packages, and macOS ships BSD userland with no `timeout(1)`, so
  nothing provides it. *(That readme lists packages rather than `/usr/bin`, so the second half is the
  documented shape of BSD userland rather than a reading of the file. The job's own "prove `timeout`
  is the GNU one" step settles it on the runner either way — under `bash -eo pipefail` a BSD
  `timeout`, which has no `--version`, fails there.)* Both halves are required: `brew install
  coreutils` **and** the `gnubin` prepend, because Homebrew installs the GNU tools `g`-prefixed. A job
  with only the first fails identically to a job with neither — in the shell, before one test runs.
- **A pinned runner label on the macOS job, and a deliberately floating one on linux.** `macos-latest`
  migrated to macOS 26 mid-2026 and `macos-13` was sunset, and that job exists to characterise one
  platform version — a floating label there changes its whole subject without notice. The linux job
  runs `ubuntu-latest` on purpose: **both** jobs install their interpreter with
  `uv python install --no-bin`, so neither measures the image's own Python or its system SQLite, and
  what a moving ubuntu image changes is the kernel and libc beneath a managed interpreter — which is
  a thing worth tracking forward rather than freezing. *This bullet read "**A** pinned runner label"
  and was enforced on the macOS job alone while the linux job floated, so the rule and its guard
  disagreed and the document was the one that was wrong. The split is now stated and both halves are
  asserted.*
- **`FASTEMBED_CACHE_PATH` exported from `$RUNNER_TEMP` inside a `run:` step.** The `runner` context is
  available only at step level, so a `${{ runner.temp }}` in workflow- or job-level `env:` is a
  reference to a context outside its availability and **the whole run is refused at validation** —
  no job in the file starts, with an *"Unrecognized named-value"* annotation. That is documented
  behaviour rather than something observed here, and stays so until the first push. The export
  belongs in a `run:` either way, where `$RUNNER_TEMP` is an ordinary variable and `$GITHUB_ENV`
  carries it to every later step.
- **The cache split into restore → an explicit fetch → save, all before the gate, with the save gated
  on the restore's `cache-hit` and carrying no `always()`.** `actions/cache`'s combined form saves in
  a post step gated on job success, so the advisory-red macOS job would never write one — 64 MB
  downloaded every run — and on Linux it would delay the first write until the first green run, which
  §"Coverage on a runner" predicts may not be the first run. **But `always()` on a split save is
  worse, not better**: it runs on the *cancelled* path, `cancel-in-progress` cancels on every push to
  the same ref, and a cancel mid-fetch would upload `huggingface_hub`'s `.incomplete` blobs under a
  key that never refreshes — silently, forever. Hoisting the fetch into its own step means the save
  completes before anything can redden or be cancelled, and the `cache-hit` gate skips a 64 MB
  re-upload on a hit.
- **The deprecation filters scoped to the gate step, not to the job or the workflow.**
  `check-matrix.sh` applies them around `./check.sh` alone and builds its virtualenvs without them.
  Wider here would apply them to `pip install`, its PEP 517 backend and setuptools' editable build, so
  a `DeprecationWarning` from inside pip on 3.13/3.14 would redden CI's *install* step on a tree the
  matrix passes — **CI as the stricter definition of done for a reason that is not this code**, which
  is the mirror of the looser-CI failure and equally wrong.

`tests/test_ci_workflow.py` asserts each of the above, parsing the workflow rather than grepping it.
**Each assertion added or reworked during this milestone's review rounds was mutation-verified**
against a deliberately broken copy — seventeen mutations, all caught. *(Not "every assertion": a
handful predate those rounds and were never put under a mutation, and a universal here would be the
same unearned sweep this milestone has already corrected twice.)* **Two properties it also
asserts are worth naming because presence checks are blind to them**: that the interpreter comes from
`uv` and not `actions/setup-python` — swapping those is green and silently changes what the
`load_extension` evidence is *about* — and **step order**, since an export or a `brew install` placed
after the gate satisfies every "is it there?" assertion and fails exactly as if it were missing.

### Coverage on a runner

**Expect a first CI run's coverage below a local one, and do not move the floor for it.** `fail_under`
is 95 against a locally measured 96.85–98.12% spread that moves with machine load, because the
socket-and-timing branches take error paths or not depending on how a race lands. A runner's core
count and load differ from this machine's — the macOS standard runner is 3 vCPU, and no figure for
the Linux one is recorded in this corpus. **A red first run on coverage is a fact about the runner, not a regression**, and
neither raising nor lowering the floor is licensed by one CI reading.

### The macOS job is advisory

It sets `continue-on-error` and writes the word *advisory* to the step summary under `if: always()` —
the red path being the only one where that matters. **There is no branch protection, so nothing blocks
on it either way**; the setting exists for how the run reads, not for what it gates.

Whether `continue-on-error` still renders the job red in the checks UI is not knowable before the first
real push. **The first run records here what the UI actually showed**, and until that line exists this
section is describing an instrument that has never run.

> **First-run record.** *(Not yet written — M28 does not close until the operator's push produces a
> green run. An instrument that has never run is not yet one, and M29 does not start on a workflow that
> has not gone green.)*

---

## 5. Rejected alternatives

**Requiring `uv` outright.** Tempting, because macOS is exactly where a host interpreter fails the
`enable_load_extension` test and a single supported path is far cheaper to document and to debug.
Rejected on reach: a developer who already has a working Python and no interest in another package
manager is a user we would be turning away for a problem they may not have.

**Shipping our own python-build-standalone build.** Would remove the host-interpreter question
entirely *and* pin SQLite for free, which is the one axis §2 admits no seam can absorb. Rejected
because it reimplements what `uv` already does correctly, and the maintenance is per-platform and
forever. **Kept as a later option rather than refuted** — if the SQLite variance ever produces a real
ranking defect, this is the fix.

**A `pysqlite3`-style wheel carrying its own statically-linked SQLite**, reached through a
`sys.modules["sqlite3"]` shim since `aiosqlite` imports the stdlib module by name. Would pin SQLite
*without* pinning the interpreter. Not chosen and not refuted; recorded so that "only a managed
interpreter can pin SQLite" is not over-weighted.

**A lexical-only degraded mode** for platforms where the embedder will not install. Rejected: it is a
second retrieval configuration, and every claim this project has measured about retrieval would need
measuring again against it. M25 measured the hybrid at +0.0764 over lexical-only with a CI excluding
zero, so the degraded mode would also be meaningfully worse, not merely different.

**Vendoring the model weights in a wheel.** Would remove the network from first run, which is the
single largest remaining first-use cost. Foreclosed by the operator's *fetch, never redistribute*
constraint, independently of the licence.

**Install-time model prefetch.** Would move the download somewhere a user expects to wait. Rejected
because it makes the installer need the network, which it does not today — and the installer is run in
container builds and provisioning scripts where that is a real constraint.

**A private repository plus PyPI only.** Keeps the working corpus private. Rejected because it gives up
the free macOS runner, which is the *only* instrument available for a platform this design now commits
to supporting.

**A public-code / private-corpus split.** Would get both. Rejected because it manufactures a second
site for every claim that lives in both halves, and the second site is the one nobody edits — a failure
mode this project has recorded against itself repeatedly rather than one imagined here.

**Apache-2.0**, whose patent grant and NOTICE mechanism corporate review prefers, and which half the
dependency tree already uses. Rejected for MIT on the grounds that for a SQLite-and-ONNX CLI the grant
buys little against MIT's shorter and more widely recognised terms.

**AGPL-3.0.** Would keep the design out of a closed product. Rejected because most companies' policies
forbid installing AGPL software at all, so for a locally-run developer tool it mainly blocks the
intended users — and it would not bind a harness vendor reimplementing the ideas from the public design
documents anyway.

**Running `check-matrix.sh` in one CI job** instead of one job per version. Rejected because per-version
jobs give clearer failure attribution, and the tree identity that script's parallel mode exists to
provide is supplied by the SHA. The cost is that the deprecation env vars become per-job and must be
asserted rather than remembered, which `tests/test_ci_workflow.py` does.

**Paying for private macOS runner minutes** at the 10× multiplier. Rejected: publication makes them
free. Standard GitHub-hosted runners, macOS included, are free and unlimited on public repositories —
only `-large`/`-xlarge` variants are billed there.
