# FINDINGS — Zikaron

> **Working memory for this project.** It loads every session, so it stays lean: the decision index,
> where the work stands, and what is still open.
>
> **What belongs here** — a settled decision and where its rationale lives; where the work stands
> and what is next; an open question with what would close it and the answer proposed; a defect
> with the fix proposed; a measured fact that constrains a
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
> **`FINDINGS-archive.md`** holds the finished record — every landed milestone, the evidence behind
> it, and the ideas that were surveyed and refused. Its own `##` headings are its index. Read
> **§"Dogfooding notes" before proposing anything** — most of what a fresh session would think to
> try has already been measured there, and several plausible ideas are refuted.
>
> **§"Owed work" below is the pool the next brief is drawn from.** Anything owed and unscoped belongs
> there rather than inside a milestone's narrative, where it disappears when that milestone is
> archived.

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
| D31 | ~~Four~~ **Five** components: core / service / mcp / hook, plus the detached knowledge indexer (D1's amendment), over a Unix-socket JSON-RPC — **amended at M31**: the typed `zikaron` commands are clients, not store-openers, and `init` alone creates a store |
| D32 | Two tool sets: ~~five for the primary agent~~ — **five memory verbs plus the knowledge index's seven, twelve in all** (D1's amendment) — and four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |
| D34 | Two harnesses, one implementation: kiro-cli and Claude Code, differences carried as data behind one seam |
| D35 | Supported platforms = Linux + macOS arm64; Windows out by transport, Intel Macs out on `onnxruntime` |
| D36 | Obtained by `uv tool install --managed-python zikaron` from PyPI (the flag is load-bearing), host Python still supported; MIT; model fetched never redistributed; semver `0.x` with an artefact-shape rule |
| D37 | `meta.schema_version` is a supported range; only the service migrates a store forward, in one transaction; nothing migrates back |

## Current state — resume here

**M0–M34 are built, reviewed and landed**, the last merged as `c66295f`. M26 shipped **nothing** —
neither the reranker nor any chunking change — and that is the result, not a stall. Each milestone's
record is in `FINDINGS-archive.md`; the briefs are in `design/build-plan.md`; M32's shipped prose
surfaces are normative in `design/retrieval.md` and decoded in `research/injected-prose-log.md`.

**M34 landed as `c66295f`** — the headline form rule and the consolidator's planning timeout;
`FINDINGS-archive.md` §"M34 as built" has the record.

**M35 is built, reviewed and in a pull request (branch `m35-serialized-transactions`, operator ask
2026-09-30); the operator merges.** Serialized transactions with `BEGIN IMMEDIATE` for writes, a read
pool with one `IMMEDIATE` retry, planning off the writer, wedge diagnostics, and `deadline_at_ms` on
`memory_surface`. The brief is `design/build-plan.md` §M35 (`reviews/m35-brief-review.md`, APPROVED);
the implementation review is `reviews/m35-review.md`, whose last round is the verdict; the evidence —
probes against a true HEAD control, the margin's distribution, every guard's mutation — is
`research/m35-implementation-evidence.md`. **Once it merges**: move this paragraph to
`FINDINGS-archive.md` as §"M35 as built", and write M36's brief. The PR's CI is the version matrix;
`gh pr checks` says where it stands.
**PR #14's required macOS job was red before the fix; the fix is in the tree, and all four jobs and
Codecov's patch (100%) are green on the PR's current head (`gh pr checks`).** SQLite's own busy
wait overruns `busy_timeout` on macOS with the SQLite uv's managed Python ships, so the store's
serving connections run at zero and the transaction primitive polls for the write lock itself
(`architecture.md` §"The service's connections"; evidence in
`research/m35-implementation-evidence.md`). The same amend carries the
coverage items the operator asked for and a test-fixture race the new timing exposed. **The review
round on this change is bounded to `git diff f5bb459..HEAD`** (operator; `f5bb459` is reachable
from the reflog only, since the PR's commit is amended in place); its trail is
`reviews/m35-review.md` from round 9.

**M36, next — the installer upgrade path (proposed 2026-09-29; brief to be written into
`design/build-plan.md` when M35 lands).** One subsystem, `zikaron/install/` and `zikaron/doctor/`,
and nothing in the service. Normative: `design/harness.md` §"The installer's two targets" and
`design/architecture.md` §"The install contract".
1. **Kiro's two compares are whole, so the next change refuses every kiro install's own upgrade.**
   - *Where*: `writer.py` compares the `mcpServers` entry with `!=` against `mcp_servers_value(...)`,
     and the hook entries through `_differing_zikaron_hooks`, which tests structural equality with
     the generated entry.
   - *Effect*: any added field, or a changed `TIMEOUT_MS`/`HOOK_TIMEOUT_SECONDS`, makes an
     unmodified old install "differ", and the upgrade is refused without `--force`. This is the
     defect `alwaysLoad` exposed in `.mcp.json`, fixed under Claude Code, still latent on both kiro
     artefacts, and covered by no test.
   - *Fix*: the predicate Claude Code already uses (`targets.py` `_ownership`, `_differing_ownership_fields`,
     `MCP_OWNERSHIP_FIELDS`). Ownership is the command, plus `args` for a server entry; any other
     difference is an upgrade to rewrite and report, not a conflict.
   - *Wording*: the server refusal's *"That is a previous install from a different interpreter"*
     becomes true only once the predicate is fixed — say so in the same change.
   - *Tests*: an old kiro install with an extra field and an old timeout upgrades without `--force`
     and reports what it rewrote. A different command still refuses. Each is shown red before the
     fix.
2. **"The eight file reasons" is spelled out in five places and pinned in none.** The sites are
   `zikaron_knowledge_status`'s description (`mcp/primary.py`), its mirror in `knowledge-index.md`,
   two comments in `core/knowledge/counters.py`, and a docstring in `tests/test_knowledge_counters.py`.
   `SKIP_REASON_KEYS` is already guarded against the design's table, so only the spelled-out count
   can drift. *Fix*: drop the number from prose ("the file reasons"), or derive it where a count is
   shown. *Test*: a drift guard that fails on a spelled-out count beside `SKIP_REASON_KEYS`'s
   length.
3. **An install that predates `alwaysLoad` is stale until re-run, and only `README.md` says so.**
   *Fix*: a `doctor` check in `doctor/checks.py`, beside `check_model_cache` and its peers, that
   reads the project's `.mcp.json` and fails, naming the re-install command, when a Zikaron server
   entry lacks the key. *Test*: a stale fixture fails the check, and a current install passes it.

Done when: all three are in, each test is mutation-verified, `README.md`'s troubleshooting row points
at the `doctor` check, and `./check.sh` is green.

**The embedder spike ran 2026-09-29: keep `bge-small`.** No candidate — granite-30m, granite-125m,
e5-small-v2 — clears the preregistered swap gate in the deployed hybrid (granite-30m −0.0052
useful-recall@5, CI [−0.0365, +0.0208], against +0.05). `research/granite-embedder-spike.md`; Q8 closed
on it and Q2 gained a second instance. The host is busy for days (operator, 2026-09-29), so no
latency figure measured meanwhile is comparable with an idle-host budget.

**The release is due now: it was to go out after the milestone following M33 — operator decision
2026-09-29 — and M34 has landed.** Tagging is the operator's act. What the gap means until then:
`0.1.0` has no `init`, so on that release `zikaron knowledge` still creates a store wherever it is typed, and it
declares `SUPPORTED_SCHEMA_VERSION = 1`, so it cannot open any store this build has touched. The number
is `0.3.0.dev0`: two unreleased `MIGRATIONS` steps since `0.1.0`, and a schema bump is a minor bump
(`design/distribution.md` §3, which also says why the minor matching the schema number is a
coincidence of this history rather than a rule).

**All three real stores are at schema 3 — `~/Trading/LeibaTrader`, `~/Memory` and `~/Dividends`,
migrated 2026-09-29 by the services a reinstall check started.** Nothing announced it, which is the
migration posture working as designed and still worth a release note: an installed `0.1.0` supports
schema 1 alone and can no longer open any of them. Re-derive with
`select value from meta where key='schema_version'` on a read-only connection.

**The five queries the log exists for are in `experiments/m33_call_log_queries.py`**, verified against
an exercised store rather than only a fresh one: per-method volume with its latency population, what
each method refuses by code, the refusal rate of a bounded write, the drop rate over distinct
`op_id`s, and what building each corpus has cost.

**Three consequences that are not obvious from the brief and are easy to re-open.** `call` is
**exempt from invariant 10** and best-effort, so the access log undercounts under contention while
`knowledge_build` is best-effort on the *opposite* terms — a build has no latency budget, waits its
full wait budget for the write lock, and no row write is ever the reason a build reports failure. **A payload spill
stays uninstrumented** (operator decision): deferred groups are how `spill_threshold` is judged
instead. And **link coverage is not comparable across the schema 3 boundary**, because linkage is
defined over `client_kind` and a session whose only `mcp` traffic was refused now counts as linked.

**`main` is published at `github.com/nathan-shapiro/Zikaron`, and CI runs four jobs on it**: linux
3.12/3.13/3.14 and macOS 3.12, the last **required** since M29. `gh run list --branch main` says
where the most recent stands. **The operator merges; this agent does not.** There is no branch
protection — operator decision, rationale in `design/distribution.md` §"The macOS job is required".

### Facts that constrain how you work in this repository

**A schema change is one commit with its design.** `test_ddl.py` and `test_event_kinds.py` read
`schema.md`'s DDL block and per-kind table verbatim, so a PR carrying the code without the document —
or the document without the code — is red by construction. That is the drift guard working, not an
obstacle to route around.

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

**Operator decision 2026-09-22: `research/`, `experiments/` and `spikes/` are out of scope for any
sweep.** They are the evidence trail, read as a record rather than as instruction.
`design/build-plan.md` and `design/evaluation.md` stay in scope.

**Use `Explore`, not `general-purpose`, for a read-only sweep** — `general-purpose` carries the
`Agent` tool and fans out.

**The task tracker does not survive compaction** — operator, 2026-09-28. `TaskList` came back empty
after one, taking every task description with it. So a plan that lives only in the tracker is lost at
the first compaction: it goes here, and the tracker is the live view of it.

### Where the stores are

`<project>/.zikaron/`, one per directory, no global tier. **`~/Trading/LeibaTrader` is the primary
real-work store** — 252 memories and 116 planned groups as of 2026-09-13
(`research/consolidation-payload-sizes.md`) — and every production report since M17 came from it.
**It runs this repository's working tree**: its `.mcp.json` and its service both launch
`/home/nathan/Zikaron/.venv`, an editable install, so every service or MCP client it starts imports
whatever the tree holds at that moment — an uncommitted edit here is live there at its next start.
Its service running M35's code was confirmed 2026-09-30 from `SigCgt` and both signal dumps.
`~/Memory` is a sibling project's store: 31 long-term records, 26 journal entries, one consolidation
run completed. It is **read-only for this agent**; writing there needs the operator's per-task
say-so.

**Never snapshot a store with `cp memory.db`.** Measured against a live store: the main file alone,
copied while the service held a WAL, gave 27 events and 2 memories against the live 38 and 4 — and
18 minutes earlier the same store was a 4,096-byte `memory.db` beside a 3.8 MB `-wal`, so the copy
would have opened, answered every query, and contained nothing. Use `Connection.backup()` or
`VACUUM INTO`, or copy all three of `memory.db`, `-wal` and `-shm`.

### Owed work — the candidate pool for the next milestone

Scanned 2026-09-28, after M33 shipped something FINDINGS had assigned elsewhere. **Nothing here is
scoped; this is the pool a brief is drawn from.** Each entry names what would close it and the fix
proposed.

**Tool descriptions arrived late, or truncated, or not at all; the install now exempts them and all four
over-long ones were rewritten — fixed 2026-09-29, with the items below still owed.** Claude Code defers
MCP tools when the tool list is crowded, listing them by name with schemas unloaded, so a description
reaches the model only when that verb is loaded — per verb and late, which a LeibaTrader transcript
shows happening just before each first use. It also **truncates any description past a cap**, taking
the tail, which had been eating `remember`'s whole `Returns` block; `design/harness.md` §"Tool
descriptions are capped" holds the bracket and says which part of `DESCRIPTION_BUDGET` is measured and
which is a bet on the constant. The install writes `alwaysLoad` on both `.mcp.json` servers, and every
description now sits under that budget. Verified from a fresh session, not inferred: **every verb on both
servers carries a full description, none name-only, and none truncated.**
`design/harness.md` §§"MCP tools may arrive deferred" and "Tool descriptions are capped" carry the
mechanism, the decision, what it costs in context and the unverified `instructions`-field alternative.

**What is still owed.** The installer items that were here are now M36, in §"Current state".

- **The `bounds`-on-first-call query ran 2026-09-29: 0 of 18** (session, verb) first calls refused
  `bounds`, across all three real stores. That is only a day of `call` rows, 61 of them on
  `~/Trading/LeibaTrader`, so it says nothing yet. **Re-run it 2026-10-29**, with the query below
  (read-only, per store). It measures how often an agent worked from a guessed schema. **It does not
  verify `alwaysLoad`**, which was checked directly, by reading a session's tool list.
  `WITH c AS (SELECT session_id s, json_extract(detail,'$.method') m, json_extract(detail,'$.error_code') e, id FROM event WHERE kind='call' AND session_id IS NOT NULL) SELECT c.m, count(*), sum(coalesce(c.e,'')='bounds') FROM c JOIN (SELECT s, m, min(id) i FROM c GROUP BY s, m) f ON c.id=f.i GROUP BY c.m`

**M35's defects left this pool: `design/build-plan.md` §M35 carries them** — every request's
transactions on one unserialized connection, a plan holding the writer for its whole run, a deferred
`BEGIN` that another process's commit refuses (the CI flake), a push the hook abandoned still
recorded as shown (which inflates D30's repair-signal denominator), two builds starting together
answering `database is locked` instead of `IndexerBusyError`, and the LeibaTrader wedge of
2026-09-29 (pid 3002334, silent 20:14–20:25Z, cause unknown). Re-derive the first two with
`.venv/bin/python spikes/m34_service_staleness_probe.py <scratch-project-dir>`, which needs a store
freshly made by `experiments/m34_gist_replay.py seed`, since the collision needs a plan lasting
seconds; the third with `python3 spikes/m35_busy_snapshot_probe.py <scratch-dir>`.

**`tests/test_knowledge_cli_integration.py`'s `reaped` fixture spends 10 s in every teardown**, six
tests a run. It `waitpid`s the service after killing it, but `lifecycle._spawn_detached` already reaps
its own child on a daemon thread, which wins: every later `waitpid` raises `ChildProcessError`, which
the fixture suppresses, so it polls until its deadline. Neither the fixture nor the spawn changed in
M35. *Fix*: after the `SIGKILL`, poll `os.kill(pid, 0)` until `ProcessLookupError`, which does not
depend on who reaps; a minute off every gate run. Proposed as its own chore commit after M35 lands,
since M35's fence does not reach the test harness's reaping.

**An owed item goes here the moment it is identified**, not into the section that happens to have
measured it.

**Q22's form rule left this pool: it is M34** (`design/build-plan.md` §M34 carries the gatekeeper
reasoning, the surfaces and the sequencing constraint). **Still owed after it — a corpus repair pass**,
which the form rule was sequenced ahead of so a pass over the 169 records does not rewrite them into
169 fresh verdicts. Proposed shape: once M34 ships, re-seed the live long-term records as journal
entries — `experiments/m34_gist_replay.py`'s `_SEED_ROWS` selects only rows a `remember` created, so
this needs a `--tier long_term` option — and consolidate them in a replay store first, judged on the
same four bars, before touching a live store. The consolidator reaches a long-term record otherwise
only as a merge target, which would leave most of them unchecked.

**Cheap and never run, in dependency order.**

- ~~**Q2's fusion sweep.**~~ **Already run and closed by M25 — do not re-propose it** (operator,
  2026-09-28). 252 cells over `rrf_k` × `fusion_depth` × **an arm weight**, 2,720 chunks of
  `cockroachdb/cockroach` `docs/RFCS/`: the best cell on `heading` — the only family whose queries are
  not substrings of their own answers — beat the shipped configuration by **+0.0069 MRR@10, 95% paired
  bootstrap CI [−0.0084, +0.0227]**, against a 0.02 threshold fixed before any cell ran. Defaults stood.
  `design/build-plan.md` §M26's fence states it: *"No change to `rrf_k`, `fusion_depth` or arm weighting:
  M25 closed those."* **What that turns Q2 into is below** — a structural finding, not a tuning one.
- **Q17's `init` connect-deadline measurement.** `design/knowledge-index.md` §9 names it.
- **Trademark clearance.** Never run; only a light search finding no software or registered mark on
  `Zikaron` in a computing class. `zikaron.app` is an unrelated cemetery-records platform.

**Read-path changes to what push emits — refused 2026-09-28, and recorded here because the 87% figure
invites re-proposing them.** Evidence: `FINDINGS-archive.md` §"The read path is barely used". Both were
deferred by M32's fence; that reason expired when M32 shipped, and they were then judged on merit and
declined.

- ~~**`surface_min_score`, a relevance floor on push.**~~ **Refused: it optimises the wrong quantity.**
  A floor raises push→fetch rate by emitting fewer gists — and this corpus has already established that
  fetch rate is *not* the mechanism, because the record is almost never read and **the gist is the
  payload**. The block's job is to put the finding in front of the agent, so a floor removes product to
  improve a proxy. The 87% figure (3,686 of 4,251 pushes surfaced no uuid that session had not already
  been shown) says push is low-signal; it does not say the remedy is emitting less.
- ~~**Degrade the re-show** — full gist first, bare id and a tag after.~~ **Refused on arithmetic.** It
  saves roughly 320 tokens a turn against a 200k context — **0.16%** — while the attention benefit it is
  justified by is unmeasurable, and it costs a new `preamble_digest` that splits M32's accumulating arm.
  The reasoning that produced it still holds and is not what was rejected: suppression proper is unsafe
  because attention decays within a context even without compaction, and **the store cannot observe
  compaction**, so a uuid shown at turn 40 may be gone by turn 400 with no event saying so.

**The general argument against that class, so it is not re-derived per item.** Retrieval-quality work
tunes the order things arrive in; the constraints this project has actually measured are what the payload
*contains* — a verdict that reads as sufficient — and that prose does not bind where the agent already
knows. **And D14 defers end-task evaluation, so nothing in that class has a dependent variable that is
not a proxy**, where the form rule builds its own instrument in Q21's harness.

**Machinery three questions are blocked on.** Q21's **offline replay harness** — a rewriter fed the
real corpus and a *different* agent ranking whether substance survived, blind, A/B in random order,
against a preregistered bar, on a `VACUUM INTO` snapshot rather than the live store, scoring a fact
dropped / a condition dropped / severity reduced separately. **Q22's closure is defined as running
through it**, with a fourth dimension: whether a reader who saw only the line would believe they
already had the finding. Q12 and Q19 lack the same machinery.

**Unrecoverable, recorded so it is not looked for.** The consolidation A/B has **no pre-run baseline**
— both `/tmp` snapshots are gone, and `~/Memory` as it stands is the *post*-run state.

### How the next review should be briefed

From M33's review trail, which cost about 20% of a week's reviewer capacity (operator measurement,
2026-09-28).

**Do not narrow a review's scope to cut it, and do not name the artifact you expect the findings in.**
M33's late blockers were in surfaces nobody thought were touched — the envelope deriving its accepted
`client_kind`s from the enum, the drift guard binding the per-kind table to `EVENT_SPECS` — and a scope
of "the seams this change reaches" excludes those by construction, since *which seams it reaches* is
what the review finds out. Worse, seven briefs in a row pointed at one research note and got findings
in it; the first brief that asked **where the earlier rounds had not looked** immediately found a
three-round-old self-contradiction between two `design/` files.

**A bar is a gate, and a gate is serviced by every round that follows it — so size it to the decision it
is supposed to force.** M33 preregistered a p50/p95 bar on the access-log row's per-call cost, missed the
p95 by ~1 ms against a 2,000 ms budget, and that miss then had to be adjudicated across four of eight
review rounds and three documents before the operator withdrew the clause as disproportionate. The
measurement was cheap and correct; **the error was writing a decision gate for a quantity nobody would
act on.** Before preregistering: name what you would *do* differently at each side of the threshold, and
if the answer is "nothing", measure and report without a bar.

**A count written into a brief becomes the specification.** §M33 says *"**Two** prose changes this
milestone carries"*, and from then on every review brief and every task inherited the number instead of
re-deriving the set — which is how Q22 was dropped without anyone noticing. State the predicate, never
the tally: `design/coding-standards.md` §5 already forbids this and a normative brief is the worst
place to break it.

**Research notes and experiment harnesses are reviewed for the decision they support, not for academic
completeness — operator decision 2026-09-29.** A finding on a note counts only if it would change what
the milestone ships or decides: a wrong conclusion, a number the decision rests on, a claim a code or
design change cites. Wording, provenance detail, methodological polish and arithmetic that moves no
decision are declined with that reason, not applied. Past milestones spent tens of review rounds
polishing research notes. Say this in the review brief, and decline such findings when a round
returns them anyway.

### Live design questions

D1 was amended 2026-09-15: the knowledge index is Zikaron's own. `design/knowledge-index.md` is
normative and APPROVED; M19–M25 landed. What is still open:

**Ids are stable and retired rather than reused.** 4, 8, 10, 11, 13, 15 and 18 closed and their numbers stay spent, so an `open question N` citation written anywhere in the corpus still means what it meant; the closed entries are in `FINDINGS-archive.md`. Ids sit outside the list marker because a Markdown renderer renumbers `1. 2. 3.` sequentially and would undo this.
- **Q1** — **The push hook fires at the wrong moment for half the use case.** `userPromptSubmit` fires once
  per user message; the moment a memory is most needed arrives twenty tool calls later, when no
  injectable hook fires. Push covers task-framing recall only.
- **Q2** — **Fusion erases the signal an embedder upgrade would buy, and config cannot recover it.**
  Dense-only, `bge-large` beats `bge-small` by MRR@10 +0.0705; the hybrid erases it. All 960 fused top-5
  slots are held by documents both arms returned, while the arms intersect in ~28% of their union.
  **M25 swept that and closed it** — 252 cells over `rrf_k` × `fusion_depth` × an arm weight, best
  +0.0069 MRR@10 with a CI spanning zero against a 0.02 preregistered bar, defaults standing
  (`design/build-plan.md` §M26's fence: *"M25 closed those"*). **So this is structural within RRF rather
  than a tuning question**, and what stays open is narrow: RRF is rank-based, and a *score*-based fusion
  with per-arm normalisation was never tested. That is a design change amending D5, not a config sweep —
  do not re-propose the sweep. Detail: `design/retrieval.md`.
  **A second model family shows the same thing (2026-09-29)**: `granite-embedding-125m`'s dense-only
  gain, +0.0677 useful-recall@5 with a CI excluding 0, is exactly 0.0000 in the hybrid
  (`research/granite-embedder-spike.md`). **So no embedder swap is worth proposing until the fusion
  scheme changes**, and score-based fusion is the next thing to test if retrieval quality is reopened.
- **Q3** — **Chunking follows entry length, not provenance.** 93 authored writes run 162–879 tokens, median
  273, against `chunk_max_tokens` 450. A record can also *become* chunked by amendment.
- **Q5** — **Nothing tells the agent *why* a demoted memory is shown.** D27 keeps no reason-for-supersession
  field, so the block can say "replaced, by that" but not why. The display half is specified in
  `design/retrieval.md`; the editorial half is open.
- **Q6** — **Residual staleness under D11, and the case D11 has no trigger for at all.** The repair
  loop fires only when a memory surfaces, is acted on, and fails loudly. Silently-obsolete memories
  and memories that stopped surfacing are missed — **and so is a memory that was wrong when
  written.** Observed once (`research/leibatrader-consolidation-2026-09-24.md`): a claim authored by
  consolidation itself surfaced ~20 times at rank 1–3 over days and was reported to the operator as
  fact. The agent's behaviour was correct throughout, including fetching before it amended. Only the
  operator's own knowledge stopped it.
- **Q7** — **Write discipline, and the scope test is the live half.** Delivery is settled (D18);
  content is a v0 draft (D30). Open: how much detail belongs in `content` versus `gist`, and —
  sharper, from `research/kiro-container-run.md` — **whether a decision taken in conversation is in
  scope at all.** The policy gates on *"what cost someone time to discover"* and lists six
  retrospective bullets, then lists *"conventions and preferences that are settled but written down
  nowhere"*, which cost nobody anything to discover. An agent made three settled design decisions
  with Zikaron as its only persistence channel, wrote nothing, and justified it from that gate; on
  genuinely hard-won material in the next session it wrote unprompted. That is a D1 question, not a
  prompt-wording one: widening scope to decisions invites every passing preference in, and leaving
  it invites the next argument to be had twice.
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
  genuine repeat. **It also happens at *write* time, which this was not framed for**
  (`research/kiro-container-run.md`): an agent put two debugging findings and a standing convention
  into one record, gist led with the first, and the convention is now reachable only on queries
  shaped like the bug — in the store, and not findable by anyone who needs it. Operator reading:
  that one is the model's judgement, against a prompt already leaning the other way.
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
  as long as they survive `cleanupPeriodDays`. **Observed once from the outside**
  (`research/kiro-container-run.md`): on a prompt with no memory affordance in it, the agent's first
  three actions were `memory_search`, `knowledge_list` and `knowledge_search`, each with a stated
  purpose, and it read the empty results as *greenfield* rather than inventing content. n=1, under
  kiro's `auto` routing, so not attributable to a model.
- **Q17** — **Does `zikaron init` owe a connect deadline longer than the 10 s it shares with
  `zikaron-mcp`?** It can report *no server became reachable* while the service is still fetching
  the 64 MB artifact; a second run succeeds, because the client gives up at
  `lifecycle._HEALTH_POLL_DEADLINE_SECONDS` (10 s) while the service keeps starting — which the
  command now says, so what is open is the budget rather than the reporting. **`init` is the only
  typed command that can reach this**, since every `knowledge` verb refuses a storeless project
  before it connects and `install` and `doctor` never connect at all — so the question is now about
  one command rather than about whichever verb a script happened to run first. A fresh CI container
  is a cold
  cache by definition, and `init` is what opens a provisioning sequence there. **What would close
  it**: whether a script owes the retry, or this surface owes a longer deadline than the hook's
  1.2 s — where a miss costs only a skipped injection, not a failed command. Measurement:
  `design/knowledge-index.md` §9.

- **Q19** — **The corpus skews negative by construction, and the agent reads it as a verdict on its
  own work.** Sampled 14 of 169 active long-term gists on `~/Trading/LeibaTrader`: **one** is
  unambiguously positive. Several are grammatically prohibitions. The operator reports the agent
  behaves persistently defeatist there. **This is the scope gate working as designed** — *"what cost
  someone time to discover"* selects for failures, because things that work are cheap to re-derive
  from the code — so it is not fixable by better reading discipline, and the push preamble already
  says everything a preamble can. **What would close it**: whether outcome belongs in the record and
  in push's selection, so five slots are never five failures when something else is eligible. That
  needs Q7's scope question answered first. `research/leibatrader-consolidation-2026-09-24.md`.
- **Q20** — **A claim copied out of the store escapes every withdrawal mechanism it has.** Agents
  cite memories by uuid in project documents. A merge moves the *claim* to the target's uuid while
  the absorbed record stays fetchable but demoted (D16, D25), so the citation resolves to a husk —
  four were found and repointed on one store. Retiring a memory retracts nothing from a document
  quoting it. **What would close it**: either a rule that memories are cited by subject rather than
  uuid, the way `design/write-policy.md` already demands for gists, or `memory_fetch` returning the
  successor alongside a superseded row — the same missing edge Q5 notes from the other direction.
  **Measured on `~/Trading/LeibaTrader`, 2026-09-25: of six memory ids cited in that project's
  `STATE.md`/`FINDINGS.md`, none is live.** Two (`1a445c0e`, `994cdcd5`) resolve to no record at all;
  four are superseded, two of them into records amended the same day, so the citations point at rows
  whose content moved under them. **The defect is semantic, not a tool gap — operator reading,
  2026-09-25.** A uuid looks like a stable identifier and is not: it is an internal handle that
  consolidation moves the claim away from, meaningful only inside the session that read it. **An
  agent should cite a memory by its subject, never by its id**, and nothing tells it so — the write
  policy's *"point at another record by its subject"* is a memory→memory rule whose stated reason is
  that a gist gets rewritten, so a uuid in a document reads as outside it. **Teaching `memory_fetch`
  to accept the 8-character prefixes those docs use would be the wrong fix**, legitimising the
  practice; the missing thing is one sentence in `zikaron_memory_remember`'s description, **and it
  lands in M33** (operator decision 2026-09-25; `design/build-plan.md` §M33 carries the reasoning and
  why a write-side tool description does not disturb the read arm). A live memory (`b04a458f`, v1) instructs
  re-checking those citations after consolidation: it surfaces, cannot be executed with whole-uuid
  `fetch`, and costs a turn producing a flag — and it is phrased as an order, which the write policy
  prohibits and nothing enforces.
  **The sentence shipped and an agent acted on it unprompted — `~/Trading/LeibaTrader`, 2026-09-29.**
  Having edited `STATE.md` to cite a record by its id, it went back and repointed that citation to the
  record's *subject*, giving the reason the description gives: ids go stale when consolidation moves
  the claim. Nothing in the prompt asked for it. That is one observation, not a rate, and it does not
  touch the six citations already in that project's documents — but it is the first evidence the
  write-side sentence changes what gets written, and it doubles as evidence the description **arrived**,
  which `alwaysLoad` and the budget are what made possible.
- **Q21** — **Should the consolidator neutralise a record's register, and what must it not touch?**
  Operator proposal 2026-09-25, and the placement is right: the consolidator is already an extra LLM
  rewriting records at a seam, off the critical path, so D2 is untouched. The problem is real — a
  record inherits the register of the session that wrote it, and the operator's own reading of this
  corpus is *"grief"* and *"word salad"*. **The boundary is the whole question.** Register is
  hedging, self-narration, drama and profanity; **severity is content** — *"this silently corrupts
  the store"* is the finding, and a pass that flattens it to *"may affect"* destroys the record while
  reporting success. Three further constraints before this is scoped: it would touch records needing
  no substantive change, so it is the widest rewrite surface consolidation has ever had and the
  never-lose guard was not designed for it; **it is probably not Q19's fix**, since Q19's cause is
  the scope gate selecting for failures, so a tone pass makes five failures *sound* calmer without
  making them four; and "stop words" needs a definition or it is unimplementable.
  **What would close it — offline replay, operator proposal 2026-09-25, and it is testable before
  anything ships.** An `experiments/` harness feeds the real corpus to a rewriter and has a
  *different* agent rank whether substance and urgency survived. Five properties make it evidence
  rather than a demo: the judge is not the rewriter and not its model — consolidator is `sonnet`, so
  the judge is `fable`; **the comparison is blind**, A/B in random order, or the judge finds losses
  in whatever is labelled "rewritten"; the bar is **preregistered** on M26's precedent; the input is
  a `VACUUM INTO` snapshot of `~/Trading/LeibaTrader`'s 169 live long-term records, never the live
  store; and three things are scored separately rather than as "better" — **a fact dropped**, **a
  condition or scope dropped**, and **severity reduced**, the last being the one that should fail the
  feature outright. The harness is reusable: any future change to how records are written can be
  replayed through it, which is machinery Q12 and Q19 also lack.
- **Q22** — **Gists are verdicts, and a headline should create the desire to read rather than
  satisfy it.** Operator observation 2026-09-25, measured: **58 of 169** live long-term gists on
  `~/Trading/LeibaTrader` carry an explicit conclusion marker and **37 contain a literal " so "** —
  a floor, since the regex catches only overt markers (93 by the wider `VERDICT_MARKER` screen in
  `experiments/m34_gist_replay.py`, which also counts causal clauses). **M34 (2026-09-29) put the rule
  on `remember`, `amend` and `promote`'s descriptions and the consolidator prompt, and
  `design/write-policy.md` §1 states it; the replay verified the consolidator half
  (`research/m34-gist-form-replay.md`).** Still open: the marker rate among new `remember` writes after
  release — proposed: re-run the screen on each real store a month after release, read the marked
  gists, and compare against this 169-record baseline. **Known limit of the shipped wording:** a gist
  shaped *mechanism, so symptom* — where the `so` clause is what was seen (*"… so a live job looks
  dead"*) — gets the symptom cut, losing the words push needs (1 of 8 in the re-run). **Accepted, not
  fixed: the obvious one-clause fix is refuted** (2026-09-29). Telling the consolidator that "so"
  introduces either an observation or a verdict kept every causal symptom — and let three real
  verdicts back through in place (*"was a July artifact"*, *"is significantly harmful"*, *"only work
  AFTER the fact"*), 19 of 20 rows unchanged. A leaked verdict is the failure the rule exists for; a
  cut symptom costs push only, since content keeps it and pull finds it. `research/m34-gist-form-replay.md`
  §"A fix for the over-fire, refuted". The shape is consistent: *symptom*, then *so
  [verdict]* — *"Ticks can share one microsecond timestamp at different prices, **so matching
  persisted trades to ticks by timestamp alone is wrong**."* The first clause triages; the second is
  what gets quoted instead of read. **M32 attacked the wrong half.** It renamed the object on the
  *read* side and told the agent a headline is not the record; it changed nothing about what the
  writer emits, and no framing makes a verdict stop reading like one. The existing guard is narrower
  still — the consolidator is told not to produce a *list* ("a merged gist that becomes a list"),
  which is about conflation, not about conclusions. **The target, operator's wording 2026-09-26: a headline carries no verdict and sparks
  curiosity to read the record when it looks relevant.** The concrete rule to test is **keep the
  symptom, drop the `so` clause** — preserving D13's triage, since you can still tell what the record
  is about, while removing what makes the line sufficient.
  **This is missing information, not an ignored instruction**, which is why prose can fix it:
  before M34 the write-side rule said *"lead with the observable symptom rather than the conclusion"*,
  an instruction about **ordering** that was being obeyed — symptom first, verdict appended — while
  nothing prohibited the verdict's *presence*.
  **Both surfaces, for different reasons.** The primary agent at write time
  (`zikaron_memory_remember`'s description), because D10 makes consolidation manual and rare so a
  record lives as a verdict for a long time; and the consolidator at merge and promote, **as the
  gatekeeper of the form rather than as a repair pass** (operator, 2026-09-28) — it already rewrites
  gists there, so the rule makes it the one place *"a headline carries no verdict"* is checked and
  corrected on everything passing through, and the only enforcement point the system has, since D2
  bars a gate at write time and a tool description is advisory. Repairing the records already written
  is a consequence of that, not the reason for it. **How it closes**: Q21's replay harness, with a
  fourth dimension beside fact/scope/severity — whether a reader who saw only the line would believe
  they already had the finding.
  **The exemplar, observed live 2026-09-26 under the new block text**: `3e1f6c7a` on
  `~/Trading/LeibaTrader`, gist *"ZSpreadScale re-EVALUATES whenever any variant transacts, but that
  is NOT re-selection — and every attempt to DAMP re-selection has deepened losses"*, carrying
  **5,378 characters** of qualifying content. The agent repeated the headline's absolute across turns
  and read the record only when the operator told it to. **Three things that makes concrete.** At 147
  characters the gist is well inside the bound, so **the length rule is satisfied and the form is
  still a verdict** — the bound is not the lever. The block's *"a headline is not the record"* was in
  context on every one of those turns and did not prevent it, which is the measured case for acting
  on the write side rather than adding read-side prose. And the record is **v6 with 5.4 KB of
  content**, instantiating the accretion defect and Q21's register — the shouting capitals — at the
  same time.
  **And that gist is the repaired one. The repair worked on the axis it was aimed at**: the previous
  wording was *incorrect*, and this one reflects reality (operator, 2026-09-26). What it did not
  change is the **form** — the absolute and the capitals survive the rewrite. **Accuracy and form are
  orthogonal, and only the first has a mechanism.** D11 repairs a memory that is *wrong*, the agent
  applied it correctly, and nothing anywhere says a true headline may still be shaped so that reading
  the record looks unnecessary — so rewriting a verdict yields another verdict.
  **The sequencing consequence is load-bearing: the form rule must land before any corpus-wide gist
  repair**, or a pass over the 169 existing records rewrites them into 169 fresh verdicts and reports
  success. That applies to Q21's tone pass on the same surface.

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
