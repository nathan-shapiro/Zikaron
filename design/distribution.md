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
| macOS arm64 | **supported, verified** | the hermetic gate runs green on a `macos-<n>` runner (arm64) and that job is required; no Apple hardware is available, so nothing there exercises a live harness |
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
uv tool install --managed-python zikaron

# The same from the repository, for a version that has not been released.
uv tool install --managed-python git+https://github.com/nathan-shapiro/Zikaron.git

# Alternative: a source checkout and a host interpreter.
git clone https://github.com/nathan-shapiro/Zikaron.git && cd Zikaron
python3 -m venv .venv && .venv/bin/pip install -e .
```

**Published to PyPI by trusted publishing, and no credential exists in this repository.** PyPI is
told once that the `release` environment of this repository, running `.github/workflows/release.yml`,
may publish `zikaron`; each run mints a short-lived OIDC token. A stored API token is the failure
mode this removes, and there is nothing left to leak. The workflow fires on a **published GitHub
release** rather than a tag push — a tag is cheap to create by accident and cheap to move — and its
first step refuses a release whose tag disagrees with `pyproject.toml`'s version, which is the one
mistake a human makes here. **`check.yml` is not re-run there**: every commit on `main` has already
been through it, so re-running would test the same tree twice; what the release workflow adds is
that the artefact uploaded was built from that tree.

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
recommendation is strongest there. *(Unmeasured, and closable for about a dollar of runner time —
a python.org build is one `curl` away on the macOS job. No milestone owns it.)*

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

### The front door

**One `zikaron` console script, with `install`, `knowledge` and `doctor`.** Before M30 both of the
first two were reachable only as `python -m zikaron.<x>`, which under the recommended acquisition is
not reachable at all: `uv tool install` puts a package's console scripts on `PATH` and never the tool
virtualenv's interpreter, so using them meant finding
`~/.local/share/uv/tools/zikaron/bin/python` first.

**`--version` is the only flag the umbrella answers itself**, beside `-h`/`--help`. It reports the
installed distribution's version through `importlib.metadata`, and where there is no distribution —
a source tree nobody installed — it says so rather than raising, because the flag exists precisely
for someone establishing what they are running. `doctor` deliberately does not repeat it — it could,
by the same one-line call, and the choice is that a version belongs on the cheapest command rather
than behind five checks that resolve a socket path and load an extension.

**`zikaron-hook` and `zikaron-mcp` are deliberately not folded in.** Their absolute paths are written
into harness configuration at install time — `architecture.md` §"The install contract" is normative —
so absorbing them would rewrite every installed config to shorten two command lines no human types.
The install contract is unchanged by M30, and `tests/test_install_targets.py`'s golden artefacts are
what assert it rather than inspection.

**`python -m zikaron.install` and `python -m zikaron.knowledge` keep working**, because a host-Python
install with several virtualenvs needs the form that says *which* interpreter's Zikaron is acting.
`doctor` has no such form: it is new with the umbrella, so there is no documented invocation
predating it to keep working, and `zikaron/knowledge/indexer/` likewise has none — it is spawned as
`sys.executable -m`, and an entry on a user's `PATH` is not what a machine-spawned process wants.

**`doctor` exists because the interpreter decision supports two acquisition paths**, and the host one
can be built in ways that make Zikaron unrunnable. It names each failure **by remedy rather than by
symptom**. Five checks and one report, in order: `enable_load_extension` present; FTS5 available;
`sqlite-vec` loading a real `vec0` table — a bare import establishes neither; the model cache present
at the pinned revision and hash-verified; the socket path fitting this platform's `sun_path`, which
is the second channel M29 owed for a refusal a user would otherwise meet only as a dead MCP server.
The report is the linked SQLite version beside the interpreter that linked it, and it **cannot
fail** — that is the axis no seam absorbs, 3.45.1 against 3.53.1 between two builds on one machine,
with no correct value to compare against.

**An absent model cache is exit 0.** There is no install-time prefetch, so a stranger's first
`zikaron doctor` finds no model at all; it reports *not yet fetched* and passes. A cache holding only
some *other* revision is that same absent case, not a mismatch — nothing is wrong with bytes this
release does not claim. A snapshot directory that **is** there fails if any pinned file is missing or
does not match, each with its own remedy; only a directory that is not there at all is the absent
case that passes.

### Model acquisition

**Model files are fetched, never redistributed** — an operator constraint, stricter than the licence
requires. Only the revision and the digests travel with the package.

**The cache is durable and per user**, at `$XDG_CACHE_HOME/zikaron/models`, or
`~/Library/Caches/zikaron/models` on macOS where that variable is unset. `$FASTEMBED_CACHE_PATH` is
honoured verbatim and outranks both, which is what keeps CI's existing cache working. A **relative**
value of either variable is ignored rather than resolved: it would resolve against the working
directory, which for the service is whichever project spawned it, turning a per-user cache into a
per-store one silently at 64 MB per project. Before M30 the cache was fastembed's default —
`tempfile.gettempdir()/fastembed_cache`, lost on reboot, and on macOS a per-session `/var/folders/…`
path. Zikaron passes `cache_dir` **as well as** `specific_model_path`, because
`OnnxTextEmbedding.__init__` runs `define_cache_dir(cache_dir)` — which `mkdir`s — before the
download call the specific path returns early from.

**The pin is a revision *and* a digest set, and the revision is what makes the digests mean
anything.** fastembed's own acquisition resolves `model_info(<repo>).sha` — the repository's current
head — and forwards no `revision`, so a digest allowlist alone has a second mismatch cause that is
not local corruption: the first time upstream pushes any commit, every install fetches bytes that
cannot match and does it again on the next start, forever. Zikaron therefore owns the acquisition:
`snapshot_download(repo_id, revision=<full 40-hex sha>, allow_patterns, cache_dir)`, verify, then
hand fastembed the directory. **Five files, not the repository's nine** — measured against a warm
cache, fastembed loads `config.json`, `model_optimized.onnx`, `special_tokens_map.json`,
`tokenizer.json` and `tokenizer_config.json`, and pinning the other four would make the product
download more than it runs.

**It buys a second thing that is not supply chain**: pinning `tokenizer.json` is what makes
`chunk_max_tokens`, the gist character bound and the 512-token window arithmetic *provable* rather
than assumed, since all three rest on a tokenizer nothing previously pinned.

**A warm start makes no network call, by construction.** The warm call passes `local_files_only=True`
together with the 40-hex sha: the sha alone skips `repo_info`, but on the online path the file listing
still comes from the on-disk tree cache and, when `trees/<sha>.json` is absent, from one
`list_repo_tree` call. `local_files_only=True` removes that door —
`_raise_if_incomplete_snapshot` simply returns. Asserted under `HF_HUB_OFFLINE=1`, which turns any
request into an error, so a green run proves the online fallback was *not reached*.

**A file that is absent and a file whose bytes are wrong get different repairs, because they are
different faults.** An interrupted first fetch leaves a snapshot with some files linked and the rest
missing — and the warm call *returns* that directory rather than raising, since with a commit hash
and no tree cache `_raise_if_incomplete_snapshot` does not check. A plain online call fills the gaps;
`force_download` would pay for every pinned file again, which is the wrong answer to a Ctrl-C. So
absent files are filled, and **`force_download=True` is reserved for a fetch that verified wrong**.
Whether a file is absent or wrong decides the *first* repair — fill or force — and `missing_files` is
what decides it, before any hashing; `Verification`'s own absent/wrong split now serves `doctor`'s
two remedies. A file the source never sends comes back from the fill as absent and goes to the forced
re-fetch like any other verification failure.

**Nothing deletes a file to repair it.** The cache stores content at `blobs/<etag>` with
`snapshots/<sha>/<file>` as a symlink to it, and re-links without downloading when the blob exists
and the pointer does not — so deleting the file and re-calling deletes the symlink, re-links the same
corrupt blob, mismatches again, and reports *upstream differs* to a user whose disk is bad. The two
diagnoses swapped. *(The deletions in this path are a proved-wrong snapshot being discarded, below —
the opposite act, replacing nothing and fetching nothing — and `doctor`'s remedy for a wrong file,
which tells a user to remove the snapshot for the same reason: it is what makes the next start
re-acquire down the path that verifies.)*

**Digests are checked when bytes arrive from the network, and never on a warm start.** The cold
fetch, the fill after an interrupted one, and the single forced re-fetch all verify; a warm start
does five `stat` calls and nothing else. **This was measured into place, not reasoned into place.**

The quantity that decides it is the margin left in the hook's 2.0 s budget, not the share of any
latency: `push.py`'s `_DEADLINE_SECONDS` bounds connect *plus* the `surface` request, and a request
that outlives it degrades — no memories injected, a `transport` line in `hook.log`, and a relay
instruction the model reads out to the user. That is M17's defect.

**Verifying on every start reintroduced it.** A/B on one machine under one load source, `load1`
rising 8.01 → 12.25 across the arms, alternating — so each control ran heavier than the arm before
it and the delta is conservative. The control empties the pin table so `pin_for` returns `None`:

| arm | `surface` median | range | inside 2000 ms |
|---|---|---|---|
| verify every start | 2076 / 2181 ms | 1984–2409 | **1/5, then 0/5** |
| no verification (pre-M30) | 1745 / 1785 ms | 1648–1914 | 5/5 |
| **verify on acquisition only** | **1677 ms** | 1637–1786 | **7/7** |

Through the shipped hook (`experiments/m17_hook_outcome.sh`), per-start verification gave **1/5**
clean pushes at `load1 7.35`. The walk costs **331–396 ms** under load, not the 185 ms an unloaded
in-process timing suggests, because it is CPU-bound and contends. Full data, both harnesses and the
control shim: `research/m30-verify-cost.md`.

**What the change trades away, stated rather than implied.** Corruption *after* acquisition — disk
rot, a file replaced on disk — is no longer caught at startup. `zikaron doctor` verifies the full
digest set on demand and is the channel for it. What stays covered is the threat the pin exists for:
a source handing over bytes that are not the pinned ones, checked at the moment it does.

**A snapshot this process has proved wrong is discarded, and the invariant is that no such complete
snapshot exists at any instant** — because presence is all a warm start checks, so any moment where
all five pointers resolve to bytes already proved wrong is a moment another process loads them.
There are **two** such moments, not one. The obvious is after a failed re-fetch. The longer by far
is *during* the forced re-fetch: `snapshot_download` creates a pointer only when one does not
already exist, so every existing pointer stays aimed at the old blob for the whole download, and a
process killed there leaves the wrong bytes complete. So the discard happens **before** the re-fetch
as well as after it — which also fixes a second consequence of that line, where a changed etag lands
the download at a new blob while the surviving pointer is never re-aimed and the re-fetch cannot
succeed at all.

It is not the delete this document rules out above: that one deletes a file to *repair* it and
re-links the same blob; this discards symlinks already proved not to be the artefact, and fetches
nothing on the way out. If the removal itself fails, the refusal names the directory, because
refusing while leaving those bytes where a warm start looks is worth more than a sentence.

**Re-derive** with `experiments/m17_cold_start_ab.py` and `experiments/m17_hook_outcome.sh`, both of
which read the deadlines from the shipped constants. The figure to watch is the worst-run spare
against 2.0 s, and **compare it against the no-pin control in `research/m30-verify-cost.md` rather
than against a constant**: `design/build-plan.md` §M17 names under ~300 ms as the threshold worth
acting on, but sized it at `load1 0.55–1.10` and `7.0–8.9`, and at the `load1` 9–12 measured here
*both* the fixed tree (214 ms) and the pre-M30 control (86 ms) are already under it. The baseline
moves with load, so the control is the comparison that means something. The lever if it comes to
that is the split connect deadline M17 left on the shelf; the marker file is spent, since a warm
start no longer hashes.

**The forced re-fetch is bounded to one per process per artefact**, so a lazily reconstructed encoder
is not a fresh licence to download. The bound is deliberately not durable across processes: a source
serving the wrong bytes therefore costs one extra fetch *per service start*, and the service is
respawned by any client that finds the socket absent. That is the accepted price of a bound needing
no state on disk — and, since the discard removes pointers rather than blobs, a proved-wrong blob
stays under `blobs/` until the cache is cleared: one of them for a source with a stable etag, one per
service start for a source whose etag varies. Nothing in the product or in `doctor` names or removes
them, which is accepted for a case that already requires a broken source. It ends when an upgrade
carries a new pin. A second mismatch inside one process
is a named failure carrying its remedy, never another *forced* fetch — after the discard the warm
call falls through to one plain online call, which re-links the existing blobs and transfers
nothing.

**The artefact's licence is `apache-2.0`**, read from `qdrant/bge-small-en-v1.5-onnx-q`'s model card.
~~`bge-small-en-v1.5` is MIT~~ — that is the **upstream `BAAI/bge-small-en-v1.5` weights**, which are
`mit`; the quantized ONNX redistribution Zikaron actually fetches states `apache-2.0` and gives no
reason for the difference. Both are permissive and neither constrains a fetch-only consumer, but the
corpus named the wrong repository's licence for the artefact it ships a fetcher for.
`research/m30-name-and-licence.md`.

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

**A release is tagged `v<version>`, and `pyproject.toml` is what the version *is*.** The tag is a
label on a commit and the file is the thing PyPI receives, so they can disagree — tagging `v0.2.0`
against a tree that still says `0.1.0` would publish a version the release page does not name.
`release.yml` refuses that before it builds, comparing the tag with its leading `v` stripped against
`[project] version`. A bare `0.2.0` tag passes the same check; the `v` is the convention, not the
mechanism.

**Between releases the file carries a `.dev` suffix, and that is what says "not a release".** After
`0.1.0` shipped the tree became `0.1.1.dev0`: PEP 440 sorts that *before* `0.1.1`, so it reads as
"working toward the next version, not at it". The version number is only made a release number in
the commit that gets tagged. **The check above is what enforces it** — `release.yml` compares the
tag's stripped name against `[project] version`, so `v0.1.1` against a tree saying `0.1.1.dev0`
fails before anything is built, and the suffix cannot survive a release by accident.

What this buys is that `--version` (§"The front door") never reports a number that lies. A PyPI
install reports a release; a `git+` or checkout install reports a `.dev` version, which identifies
itself as unreleased rather than impersonating one. A bug report from such an install still needs
the commit, because one `.dev` number spans every commit until the next bump.

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
  a post step gated on job success, so a job that stays red across a run of failures would never write
  one — 64 MB downloaded every time, exactly when the loop most needs to be short — and it would delay
  the first write until the first green run, which §"Coverage on a runner" predicts may not be the
  first run. **But `always()` on a split save is
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

### The macOS job is required

It carries no `continue-on-error`: a red macOS job is a red run, on the same terms as any Linux one.
**There is still no branch protection, so nothing mechanically blocks a merge** — what the setting
changes is whether the run reports the truth, not what it gates. That absence is a decision rather
than an oversight: with a single contributor, protection enforces a handoff there is nobody to hand
off to. It is the first thing to add if that changes.

**What the advisory run established before the job was promoted.** It was red, which is what it was for.
81 of 2950 tests failed, every one of them reaching `OSError: AF_UNIX path too long`, and **the product
was not the cause**: its own socket path is short by construction, with room to spare
(`architecture.md` §Paths holds the arithmetic). The suite was — it built socket paths under pytest's
`tmp_path`, which on macOS sits under a per-session `/var/folders/…/T` prefix deep enough to cross
the limit on its own. Everything before the gate passed, the
64 MB model fetch included, so `fastembed` and `onnxruntime` install cleanly on arm64 and the GNU
`timeout` the job installs for `check.sh` works.

Two things the run confirmed rather than discovered, both predicted by reading: `security.ensure_runtime_dir`
vets the **leaf** with `lstat`, so macOS's `/tmp` being a symlink to `/private/tmp` is a traversed parent
and never refused; and no `/proc`, file-mode or `umask` difference surfaced.

**What it still cannot prove, and this is unchanged by promotion**: there is no harness binary on the
runner, so `integration_kiro` and `integration_claude` stay local-only and nothing on macOS exercises a
real session pushing or searching. macOS is verified for the hermetic gate, not for a live install.

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
