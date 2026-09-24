# FINDINGS — Zikaron

> **Working memory for this project.** It loads every session, so it stays lean: the decision index,
> where the work stands, and what is still open.
>
> **What belongs here** — a settled decision and where its rationale lives; where the work stands
> and what is next; an open question with what would close it; a measured fact that constrains a
> choice, stated once with the command that re-derives it. The test is whether a fresh session
> would act differently without it.
>
> **What does not** — how a defect was found, what a review or sweep covered, what a sentence used
> to say, round counts, and any account of an agent's own mistakes. That goes nowhere, not to the
> archive. Findings live in `reviews/`, measurements in `research/`, fixes in the tree, and a
> lesson that became a rule lives in that rule alone. See `CLAUDE.md` §"Project memory".
>
> **The design lives in `design/overview.md`** — the system in one page and the decision table with
> rationale. §"Settled decisions" below is a one-line index; never re-litigate a decision from it.
>
> **`FINDINGS-archive.md`** holds the finished record. Its own `##` headings are its index. Read
> **§"Dogfooding notes" before proposing anything** — most of what a fresh session would think to
> try has already been measured there, and several plausible ideas are refuted.

## Settled decisions — index
One line each. **Rationale, measurements and rejected alternatives are in `design/overview.md` §4.**

| # | Decision |
|---|---|
| D1 | Tribal knowledge only; ~~codebase KB is a separate system~~ — **amended 2026-09-15: that separate system is now Zikaron's own** (`design/knowledge-index.md`). What `remember` accepts is unchanged |
| D2 | No extra LLM on the write path — hard constraint |
| D3 | Two tiers: journal (unconsolidated) + long-term (consolidated) |
| D4 | Memory record = `{uuid, gist, content}` |
| D5 | Read = hybrid vector + full-text top-K → ids + gists |
| D6 | Write = primary agent's own judgment: new entry / amend (if read first) / nothing; it authors its own gist |
| D7 | Consolidation is the only extra LLM; code picks candidates, model judges |
| D8 | Store scoped to the harness's directory; no global tier in v0 |
| D9 | Delivered as an MCP server plus a distributed skill and hooks |
| D10 | Consolidation trigger = a manually-invoked skill spawning a subagent (no compaction hook exists) |
| D11 | Staleness is repaired in-band by the agent the memory misled |
| D12 | Read = push **and** pull; a `userPromptSubmit` hook injects the top 5 gists |
| D13 | The gist's job is relevance triage |
| D14 | End-to-end task-benefit evaluation stoved until an implementation exists (component benchmarks are not) |
| D15 | Write-time dedup, agent-resolved: `remember` writes, then hands back near-duplicates for the agent to resolve |
| D16 | Soft delete only — retire, never `DELETE` |
| D17 | Scope key = the harness's own project directory where it names one, else the cwd (**amended 2026-08-18**) |
| D18 | Write policy injected by an `agentSpawn` hook |
| D19 | Python venv, latest stable; SQLite + FTS5 + sqlite-vec + fastembed; store never in git |
| D20 | Keep `bge-small-en-v1.5`, pass the BGE query prefix, record model id + dim per vector |
| D21 | Embed gist + content, not gist alone |
| D22 | The hook must never load an embedding model |
| D23 | No cross-encoder reranker on the push path; open for pull |
| D24 | Reject the extracted-identifier `tokens` column as specified |
| D25 | Supersession is structural via `superseded_by`, and it **demotes rather than hides** |
| D26 | Optimistic concurrency: `version` + a read receipt required on every `amend`/`retire` |
| D27 | Provenance = `created_at`, `updated_at`, `session_id` only |
| D28 | Chunk the dense side, parameterized; FTS5 stays unchunked; `max` rollup |
| D29 | Consolidation groups topically using retrieval as the adjacency function, mutual-K plus a cohesion pass; session grouping rejected |
| D30 | Write policy v0 drafted, to be experimented against; six signals instrumented |
| D31 | ~~Four~~ **Five** components: core / service / mcp / hook, plus the detached knowledge indexer (D1's amendment), over a Unix-socket JSON-RPC |
| D32 | Two tool sets: ~~five for the primary agent~~ — **five memory verbs plus the knowledge index's seven, twelve in all** (D1's amendment) — and four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |
| D34 | Two harnesses, one implementation: kiro-cli and Claude Code, differences carried as data behind one seam |
| D35 | Supported platforms = Linux + macOS arm64; Windows out by transport, Intel Macs out on `onnxruntime` |
| D36 | Obtained by `uv tool install --managed-python zikaron` from PyPI (the flag is load-bearing), host Python still supported; MIT; model fetched never redistributed; semver `0.x` with an artefact-shape rule |

## Current state — resume here

**M0–M29 are built, reviewed and landed.** M26 shipped **nothing** — neither the reranker nor any
chunking change — and that is the result, not a stall.

**`main` is published at `github.com/nathan-shapiro/Zikaron`, and CI runs four jobs on it**: linux
3.12/3.13/3.14 and macOS 3.12, the last **required** since M29. `gh run list --branch main` says
where the most recent stands. **The operator merges; this agent does not.** There is no branch
protection — operator decision, rationale in `design/distribution.md` §"The macOS job is required".

**M30 is built, reviewed to APPROVED and green on both gates**: the `zikaron` umbrella (`install` /
`knowledge` / `doctor`), the durable per-user model cache, the revision-and-digest pin with Zikaron
owning the fetch, and `release.yml`. Its brief in `design/build-plan.md` is normative;
`design/distribution.md` §§"The front door" and "Model acquisition" are where the shipped design now
lives. **Merged as `f18c5cb`**, all four CI jobs green on `main`, Codecov reporting.

### The release

**`zikaron` 0.1.0 is on PyPI** — published 2026-09-24 from `release.yml`, sdist and wheel,
`requires-python >=3.12`, MIT. **Trusted publishing is exercised rather than assumed**: no token
exists in this repository or its secrets, the `release` environment carries no protection rules, and
`invalid-publisher` did not occur. `README.md`'s `uv tool install --managed-python zikaron` and D36
now resolve. `research/m30-operator-setup.md` holds the setup procedure.

**`pypa/gh-action-pypi-publish` is pinned `@v1.14.2`, never a sha** — it is a Docker action.
`release.yml`'s comment and `test_no_action_is_pinned_to_a_moving_branch` are normative. Cutting a
release: `design/distribution.md` §3 and `research/m30-operator-setup.md`.

**No lock file is tracked**, and `design/coding-standards.md` §6 says why and forbids adding one
back without a reader.

**Dependabot is live** (`.github/dependabot.yml`): actions weekly and grouped, pip monthly and
ungrouped.

**The publication guard's exemption for the pins is a single-file allowlist**, decided at M30 as
that guard's docstring asked. A per-line marker would sit on every digest line and on each new one,
and one pasted onto a line that is genuinely a secret would be indistinguishable from one pasted
onto a digest. The exemption is narrowed by a positive check — every hex run in
`core/indexing/model_pin.py` must be a value that module declares — so it is not a standing hole.

**Operator decisions 2026-09-23.** Releases go out by **PyPI trusted publishing** from a
release-triggered workflow, never an API token in a secret. **Coverage is published to Codecov**,
because the only honest alternatives are a live service or no badge at all: a percentage typed into
`README.md` is the stale-number class this corpus has a standing rule to delete. **A badge that
carries a measured value must derive it rather than state it** — that is what governs the next one
somebody wants to add. **A badge that merely names a tool need not**: the `ruff` and `mypy` ones are
static claims that nothing asserts, kept deliberately (operator decision) on the grounds that not
every claim earns a guard.

**The pinned artefact's digests are checked when bytes arrive from the network, never on a warm
start — operator decision 2026-09-23, taken on a measurement.** Hashing the five files costs
**331–396 ms under load**, not the 185 ms an unloaded in-process timing shows, because the walk is
CPU-bound; that pushed the cold-start sequence past `push._DEADLINE_SECONDS` and reintroduced M17's
defect, at **0–1 of 5 runs inside the budget against 5/5 without it**, 1/5 clean pushes through the
shipped hook. Moving the check to the acquisition paths restores parity — 5/5 against the pre-M30
control at `load1` 10.86 and 11.88. **What this gives up is startup detection of corruption that
happens *after* acquisition**; `zikaron doctor` is the channel for it. A failed acquisition discards
the snapshot, or the next warm start would trust bytes already proven wrong.
`research/m30-verify-cost.md`; rationale in `design/distribution.md` §"Model acquisition".

**The cold-start budget is re-measured with `experiments/m17_cold_start_ab.py` and
`experiments/m17_hook_outcome.sh` under generated load**, against the no-pin control rather than a
constant — the baseline moves with load. Commands in `research/m30-verify-cost.md` §"Re-deriving
this".

**The artefact Zikaron fetches is `qdrant/bge-small-en-v1.5-onnx-q`, its head is
`52398278842ec682c6f32300af41344b1c0b0bb2`, and it is licensed `apache-2.0` — not the `mit` of the
`BAAI/bge-small-en-v1.5` weights it is derived from.** Read from the Hub API rather than from our
own note. Re-derive both facts, and the file list the digest set must cover, with:
`.venv/bin/python -c "from huggingface_hub import HfApi;i=HfApi().model_info('qdrant/bge-small-en-v1.5-onnx-q');print(i.sha,i.cardData['license'],sorted(s.rfilename for s in i.siblings))"`

**The name stays `zikaron` — operator decision 2026-09-23, taken knowing that `zikkaron` is held on
PyPI by a near-identical product**: one keystroke away, actively maintained, and by its own
description a biologically-inspired persistent memory engine for Claude Code on SQLite. The grounds
are that the markets differ enough that a user reaching for one will not land on the other. Do not
re-open this from the collision alone. `zikaron` itself is unregistered — both `/simple/` and the
JSON API answer 404 — but a 404 cannot distinguish never-registered from deleted-and-unreserved, so
the name is only *proven* free by an upload, which is the operator's act.
`research/m30-name-and-licence.md`.

**A derived path that cannot be used is refused as the existing `BAD_CONFIG`/`runtime_dir`
`ZikaronError` — no bespoke type, and no new `hook.log` kind.** `service/security.py` and
`hook/push.py` already had both halves; rationale in `design/build-plan.md` §M29's withdrawal.

**`sun_path` is tighter on macOS than Linux, and only the runtime directory can spend it.** The
store is hashed to a fixed width, so **project nesting depth cannot move the socket path's length**;
`$XDG_RUNTIME_DIR` is prepended verbatim and is unbounded, so an over-long one is now refused rather
than left to `bind()`. **`design/architecture.md` §Paths holds every figure — do not restate one
here.** Re-derive the fallback-branch figure with (vary `uid` and `platform` for the rest):
`.venv/bin/python -c "import os;from pathlib import Path;from zikaron.service import paths as p;rd=p.runtime_dir(xdg_runtime_dir=None,uid=501);print(len(os.fsencode(p.socket_path(rd,Path('/x'),platform='darwin'))), p.sun_path_size('darwin'))"`

**A long `TMPDIR` reproduces macOS's path geometry on Linux, and that is how to test this class
without a runner.** Point it at a directory as long as macOS's own `/var/folders/…/T`:
`d=/tmp/mac/$(printf 'x%.0s' {1..39}); mkdir -p "$d" && TMPDIR="$d" .venv/bin/pytest -q`.
Verified both ways: green as the tree stands, red with the `socket_dir` fixture pointed back at
the default tempdir.

**Both local gates are green on one tree**: `./check.sh`, and `./check-matrix.sh --parallel` across
3.12, 3.13 and 3.14. The matrix refuses if anything changes while it runs, so do not edit during a
sweep.

**Nothing is installed into this repository**, deliberately. `python -m zikaron.install --project .
--harness claude-code` would do it; `--harness auto` refuses here because the repo carries both
dotdirs. Until then the memory tools and the push hook are **not live in this session**.

**`design/harness.md` is normative for every harness-coupled fact.** Read it before touching the
hook, the MCP client or the installer; do not re-derive one from an older section of
`architecture.md`.

**The gate is hermetic and that is verified.** `addopts` deselects `manual`, `integration_kiro` and
`integration_claude`; the default suite passes with neither harness binary on `PATH`. Nothing lives
only in those tiers. `design/coding-standards.md` §"five tiers" is binding.

### Where the stores are

`<project>/.zikaron/`, one per directory, no global tier. **`~/Trading/LeibaTrader` is the primary
real-work store** — 252 memories and 116 planned groups as of 2026-09-13
(`research/consolidation-payload-sizes.md`) — and every production report since M17 came from it.
`~/Memory` is a sibling project's store: 31 long-term records, 26 journal entries, one consolidation
run completed. It is **read-only for this agent**; writing there needs the operator's per-task
say-so.

**Never snapshot a store with `cp memory.db`.** Measured against a live store: the main file alone,
copied while the service held a WAL, gave 27 events and 2 memories against the live 38 and 4 — and
18 minutes earlier the same store was a 4,096-byte `memory.db` beside a 3.8 MB `-wal`, so the copy
would have opened, answered every query, and contained nothing. Use `Connection.backup()` or
`VACUUM INTO`, or copy all three of `memory.db`, `-wal` and `-shm`.

### The install path is proven end to end, on a machine that had never seen the project

**Run 2026-09-24 in `ubuntu:26.04`; the record and the commands to re-derive it are in
`research/m30-docker-end-to-end.md`.** Four things were exercised for real there for the first time:
**`sqlite-vec` loading on a uv-managed interpreter on a foreign OS**; the `/tmp` socket fallback,
since a container has no `$XDG_RUNTIME_DIR`; **D32's tool withholding and push suppression under a
real Claude Code subagent** rather than a stub; and both branches of the model-cache check in one
container.

**What it did not cover.** Push and pull: no `UserPromptSubmit` gist block was captured and no search
was called — both have run for real many times under kiro on `~/Trading/LeibaTrader`, and what has
never happened is a real Claude Code session doing either on another machine, or any *automated* run.
macOS arm64, since the container is amd64 Linux, so the platform where `enable_load_extension` is
reported off stays CI's alone. And memory *behaviour*, which needs a real workload rather than a
container — operator decision.

### `main` carries user-facing fixes that `0.1.0` does not

Four defects found by installing the published artefact, all fixed in the tree and none of them in
the release on PyPI: **`zikaron --version`** now exists (it was `unknown command`, exit 2); the
**no-store refusal names what actually creates a store** — the service's first start, never the
installer, per `architecture.md` §"First run"; **`README.md` names `--harness` in the install
command**; and README now says where `uv` itself comes from.

### Next PR: the knowledge CLI becomes a thin client of the service

**Operator decision 2026-09-24, to be done once the `--version` work lands.**
`zikaron/knowledge/main.py` opens `memory.db` directly through `zikaron/knowledge/scope.py:
open_store`, while `zikaron/service/dispatch_knowledge.py` already serves all seven knowledge
methods over RPC and the MCP server is already a thin client over them.

**The indexer shares `open_store` and keeps it** — it is the service's own detached child and the
process that holds the model for a build — so this **splits the CLI's open from the indexer's**
rather than rerouting the shared helper. `mcp/connection.py`'s `Store.open`, which reads
`meta.store_id` on every connect after the first, stays too — and is what keeps §9's foreground
refusal true, since without it an unreadable store costs the CLI the full 10 s poll and a generic
"no server became reachable" instead of a reason. What the change deletes is the one
**human-facing management** surface that bypasses the service — the indexer's own entry point, run
in the foreground by an operator, stays direct.

It buys a CLI that **bootstraps without an agent** — what a provisioning script preparing a repo
needs — and keeps the embedder out of the CLI, which the rejected alternative (`open_store` creating
the store itself) could not, since `Store.create` needs the artifact for the vector width. The client
half exists: `service/lifecycle.py:connect_start_if_absent`, already wrapped with retry and identity
by `mcp/connection.py:ServiceConnection`. **Not** `hook/connect.py`, whose `connect_once` is a
stdlib-only re-implementation for the hook's contract, which the CLI is not under.

**Cost, and it is a latency question rather than a download one.** The cache is per user, so a cold
*project* on a warm cache pays the model load and store creation; only a cold *cache* pays the
64 MB. The socket is bound after the whole context is built, so `health()` cannot answer until the
fetch lands and the store exists: the warm helper saw it answer **3.74 s** after the service's first
log line in the container, the fetch at most 3.30 s of that, against
`lifecycle._HEALTH_POLL_DEADLINE_SECONDS = 10.0` measured from spawn. It waits there; on a slower
network the first call reports no reachable server while the service keeps fetching, and the second
succeeds — M17's class on a surface with no degraded mode.

**The provisioning-script case has a cost of its own**: after the change, a `knowledge add` from a
script leaves a service running until `idle_timeout`, beside the detached indexer it already leaves.
In a `docker build` step or a CI job everything alive at step end is killed, cutting the build off
and leaving a dead lock holder and `reindex_required`. So the script case is a live shell, or a
foreground/`--wait` option is owed — out of this PR's scope either way.

**What the PR must correct, because each states the direct open or its rationale:**
`zikaron/knowledge/scope.py`'s module docstring (*"Requiring a service would make managing and
building corpora depend on a harness being live"* — already untrue, since the service starts on
demand); `design/architecture.md`'s indexer row (*"opens the store itself and never goes through
RPC"* — **reworded, not deleted**: the indexer's own entry point run by hand is still shell-started
and still direct); `design/overview.md:81` and `:102`; `design/knowledge-index.md:1038`
(*"spawned by the CLI (§9) or by the service"*), §9's account of who spawns and who refuses, and
`:2468`'s unreadable-`memory.db` row, whose two halves become one route once the CLI *is* the RPC
path; and `zikaron/knowledge/main.py`'s module docstring.

**`_store_not_created`'s remedy is deleted rather than reworded** — but not because the condition
goes away. It is the `connect_failure` of *every* `Store.open`, and of the three callers only
`scope.open_store` omits the file check, so `python -m zikaron.knowledge.indexer` run by hand in a
storeless project still reaches it. What stops existing is the *CLI's* route to it, since the service
it now talks to creates the store; a one-line refusal suffices for the by-hand case, and
`test_a_missing_store_points_at_the_service_rather_than_the_installer` goes with the remedy.

**Bundle a live kiro-cli install in a container with it** (operator decision 2026-09-24) — the
operational half of the same change. The 2026-09-24 run covered **Claude Code only**, so half of
D34 has never been installed on a machine that had not seen the project.

**An agent config must exist first** — kiro's hooks and `mcpServers` live inside one, and `--agent`
refuses a path that is not a file — **and where it lives decides detection.** Stable kiro reads them
from `.kiro/agents/` **or** `~/.kiro/agents/` (`research/kiro-cli-hooks-and-introspect.md`), and
nothing in `install/` requires `--agent` to point inside the project. A project-local config creates
`.kiro/` and detection sees it; a global one creates nothing in the project, so that first install
needs `--harness kiro` exactly as Claude Code's does. Either way the shipped files put `.kiro/`
there, so the second install detects. **Run both locations** — `--agent` pointing outside the project
has never met the real binary.

**Cases to run:** the three content cases under `--format`'s already-has-hooks rule (no `hooks`
block, object-format present, array-format present), and **no `--agent` at all**, where
`KiroTarget.plan_merges` returns `()` — shipped files written, nothing merged, exit **0**. Whether a
person reading that realises nothing is live is what eyes judge and no test can.

**What needs the real binary:** `kiro-cli agent validate`'s complaints relayed through the installer,
and the consolidator model-id check. Auth is *expected* to be a browser-link flow like Claude Code's,
so the attached-pane procedure carries over — operator report, second-hand and unverified, and
`research/kiro-mcp-lifecycle-probe.md` is why a documented kiro behaviour is not taken on trust.

**`pyproject.toml` carries `0.1.1.dev0`, and a release number is only set in the commit that gets
tagged** — operator decision 2026-09-24. A `.dev` suffix between releases is what stops an
unreleased tree reporting a version that reads as a release; `release.yml`'s tag check refuses to
build while the suffix is there, so it cannot survive a release by accident.
`design/distribution.md` §3 is normative, including the artefact-shape rule that decides patch
versus minor when the number is finally set.

### Owed measurements

- **The read-path fix has no baseline.** The quantity is the pre-change share of surfaced uuids
  fetched before their session's next write, over `~/Trading/LeibaTrader`. Full specification is in
  `FINDINGS-archive.md` §"The gist-as-abstract fix, and M27".
- **The consolidation A/B has no pre-run baseline.** Both `/tmp` snapshots are gone. `~/Memory` as
  it stands is the *post*-run state and cannot serve as the pre-run arm.
- **No trademark clearance has been run**, only a light search finding no software or registered
  mark on `Zikaron` in a computing class. `zikaron.app` is an unrelated cemetery-records platform.
  The friction that turned up is a package name, not a mark — §"Current state" above.

### The audit loop, and what it established

Thirty rounds plus a parallel batch, run on operator instruction after the M28 commit. **The
per-round write-ups have been deleted rather than archived**; findings are in `reviews/`, fixes are
in the tree. What is worth carrying:

- **The software was not the problem.** Thirty rounds produced roughly four behavioural changes to
  the package. Everything else was prose.
- **The prose was, and the loop fed it.** Each pass's explanatory commentary supplied the next
  pass's findings, at roughly one new defect per one-and-a-half fixes. `CLAUDE.md` and
  `design/coding-standards.md` §5 were changed 2026-09-22 to stop it at the source: the code is the
  product, and a repair is never annotated.
- **Coverage claims were overstated.** Round 28 enumerated 1,225 absolute-bearing sentences,
  checked 249, and was written up as having closed the class. **No round may report a class closed
  without stating enumerated-vs-checked.** Any "closed" recorded before round 27 is unverified.
- **A closure decays the moment the surface is edited again**, including by the round that closed
  it. An enumeration is valid only against the tree it ran on.
- **Deletion is the only move that has ever ended a class here.** Every number this corpus
  corrected came back stale; every one it deleted stayed dead.

**Findings from those audits are in `reviews/`, and the working tree is the authority on which are
still outstanding.** `git diff HEAD` is how to tell; a list here is a second copy of state that
moves every time one is applied.

**Operator decision 2026-09-22: `research/`, `experiments/` and `spikes/` are out of scope for any
sweep.** They are the evidence trail, read as a record rather than as instruction.
`design/build-plan.md` and `design/evaluation.md` stay in scope.

**Use `Explore`, not `general-purpose`, for a read-only sweep** — `general-purpose` carries the
`Agent` tool and fans out.

### Live design questions

D1 was amended 2026-09-15: the knowledge index is Zikaron's own. `design/knowledge-index.md` is
normative and APPROVED; M19–M25 landed. What is still open:

**Ids are stable and retired rather than reused.** 4, 10, 11, 13 and 15 closed and their numbers stay spent, so an `open question N` citation written anywhere in the corpus still means what it meant; the closed entries are in `FINDINGS-archive.md`. Ids sit outside the list marker because a Markdown renderer renumbers `1. 2. 3.` sequentially and would undo this.
- **Q1** — **The push hook fires at the wrong moment for half the use case.** `userPromptSubmit` fires once
  per user message; the moment a memory is most needed arrives twenty tool calls later, when no
  injectable hook fires. Push covers task-framing recall only.
- **Q2** — **Unweighted RRF discards the signal an embedder upgrade would buy.** Dense-only, `bge-large`
  beats `bge-small` by MRR@10 +0.0705; the hybrid erases it. All 960 fused top-5 slots are held by
  documents both arms returned, while the arms intersect in ~28% of their union. `rrf_k` and
  `fusion_depth` are config keys, so the sweep needs no reindex. Detail: `design/retrieval.md`.
- **Q3** — **Chunking follows entry length, not provenance.** 93 authored writes run 162–879 tokens, median
  273, against `chunk_max_tokens` 450. A record can also *become* chunked by amendment.
- **Q5** — **Nothing tells the agent *why* a demoted memory is shown.** D27 keeps no reason-for-supersession
  field, so the block can say "replaced, by that" but not why. The display half is specified in
  `design/retrieval.md`; the editorial half is open.
- **Q6** — **Residual staleness under D11.** The repair loop fires only when a memory surfaces, is acted on,
  and fails loudly. Silently-obsolete memories and memories that stopped surfacing are missed.
- **Q7** — **Write discipline.** Delivery is settled (D18); content is a v0 draft (D30) with six signals
  instrumented. Open: how much detail belongs in `content` versus `gist`.
- **Q8** — **Does model capacity help identifier discrimination?** Discrimination index 0.194–0.233 for all
  four models; `bge-large − bge-small` is +0.029 against a preregistered 0.15 bar. fastembed serves
  a quantized small against an unquantized large, so this compares artifacts, not capacity.
- **Q9** — **Evaluation** (deferred by D14). Plan: `design/evaluation.md`, proposal not normative. No
  surveyed benchmark scores an end-task coding outcome; LoCoMo cannot score abstention; every
  published comparison in this space is vendor self-report. CTIM-Rover is a published negative
  result for approximately this system, and what the knowledge index differs in is the live
  question.
- **Q12** — **Merging degrades the gist's triage value, and the tension is structural.** A 64-token gist
  cannot lead with the observable symptom of six findings. The damage is asymmetric: pull survives
  because D21 embeds gist *and* content; push degrades, because the block shows gists only. The
  prompt now has reasons to split and none to merge — **operator decision: do not revert that on
  the strength of the 11-merges-to-0 result.** The next real test needs a journal containing a
  genuine repeat.
- **Q14** — **Preferences are collected into a store designed not to bind.** `design/retrieval.md`'s
  untrusted-reference preamble is what stops a poisoned store steering the agent, but a standing
  preference is exactly the class that wants to bind, and the write policy invites them. Three
  ways out, none taken; `CLAUDE.md` is the right side of that seam for a rule that must bind.
  **A fourth appeared unaided, n=1**: given both stores, a Claude Code session put the *evidentiary*
  form of one fact in Zikaron — dated, scoped to what was observed — and the *directive* form
  (*"Assume Unreal Engine conventions … when working here"*, no expiry) in Claude Code's own memory,
  which has no such preamble. The cost is duplication with two staleness clocks and no link either way.
  `research/m30-docker-end-to-end.md` §Coexistence.
- **Q16** — **Recall: does the agent reach for memory unprompted?** Instrumented but unattributable — the
  `search` event records no actor and no occasion, and every agent in a session shares one id.
  Bursty, at 6–11% of turns. Under Claude Code the harness transcripts answer it externally, for
  as long as they survive `cleanupPeriodDays`.

### Harness

Both thin clients and the installer speak both harnesses. `.claude/` is the live crew; `.kiro/`
stays as the reference for what the product still installs. Two fidelity losses from the move, both
deliberate: memory-reviewer runs `fable` rather than a different family, so **cross-family
independence is gone** and an APPROVED is weaker evidence wherever shared-family blind spots are
plausible; and per-agent write scoping has no frontmatter equivalent, so it is stated in prompts and
enforced by nothing.

**The self-review loop has a single point of failure, observed failing twice** — the reviewer model
down, and the reviewer model rate-limited. There is no degraded mode, only a halt. The file-based
protocol held both times: the trail ends cleanly at the last completed round.

**Do not compare recall numbers across the kiro→Claude Code boundary, in either direction.** The
harness, the model, the injection position and the policy delivery all changed at once.
