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
| D38 | Edit guards: deterministic regex-only Claude Code hooks deny find-replace edits (override `#ZIKARON-FORCE #Reason: …`) and nudge a re-read after edits; installed only on request, memory/guards/both; not on kiro — **amended 2026-10-07**: a script run from scratch is judged too, the guard's one file read |

## Current state — resume here

**M0–M36 are built, reviewed and landed**, the last merged as `c22ad2b` (PR #15), and **`0.3.0` is
released** — tagged `v0.3.0` on that commit and on PyPI (2026-09-30). M26 shipped **nothing** —
neither the reranker nor any chunking change — and that is the result, not a stall. Each milestone's
record is in `FINDINGS-archive.md`, M36's in §"Closed with `0.3.0`"; the briefs are in
`design/build-plan.md`; M32's shipped prose surfaces are normative in `design/retrieval.md` and
decoded in `research/injected-prose-log.md`.

**`main` is `0.3.1.dev0`; M37's pull request sets `0.4.0`**, which the operator releases from
its merge (operator, 2026-10-07), so the first commit after that tag returns the tree to
`0.4.1.dev0`. PR #19 (`b2dd415`) carried the post-release bump, this archive pass and
the `SIGUSR1` dump's move off `faulthandler.register` (`research/sigusr1-dump-crash.md`). Three
runtime-library bumps landed beside it — `fastmcp` 4.0.10 (PR #17), `fastembed` 0.8.1 (PR #20) and
`huggingface_hub` 1.33.0 (PR #21) — and each passed both live-harness tiers before it merged; 0.8.1
embeds bit-identically to 0.8.0 for the pinned model.

**M37, edit guards, is built and reviewed, not yet landed (operator, 2026-10-06).** These are
deterministic, regex-only Claude Code hooks:
- one denies a Bash command that edits an authored file by find-replace, unless every target is
  scratch or the command carries `#ZIKARON-FORCE #Reason: <at least two words>`;
- one nudges, after each edit, for one re-read once that file's editing is done;
- a short start text rides `zikaron-hook`'s existing `SessionStart`/`SubagentStart` entry.

This is the first, model-free class of the 2026-09-24 *evaluator with teeth* proposal
(`FINDINGS-archive.md` §"The strongest M32 candidate, and why"); the async-watcher class stays
unscoped. The installer offers the memory store, the guards, or both, with guards only on request.
Kiro gets no guards. **This repository does not install the guards** (operator, 2026-10-07): its
`.venv` runs the code under development, so a broken guard would cripple the agent building it.

**The design is approved**: spec `design/edit-guards.md`, brief `design/build-plan.md` §M37,
decision D38, trail `reviews/m37-edit-guards-brief-review.md`. **The build is in progress
(2026-10-07); its plan, in the brief's order:**
1. **done** — the prompt texts, by memory-reviewer, in `reviews/m37-edit-guards-review.md`;
2. **done** — `zikaron/guard/`, at 100% coverage; `tests/test_guard_rule_table.py` reads §8,
   which now also holds every §7 edge as a row;
3. **done** — `HarnessSpec.edit_guards`, `zikaron-hook --components`, the installer's
   `--components` (`tests/test_install_components.py` walks the perturbation table), the console
   script and the gate's lists;
4. **done** — the owed documents (item 6), the README's install, options and uninstall included;
5. **done** — the replay, `research/m37-guard-transcript-replay.md`: 1,227 of 20,051 commands
   would be denied, every false deny one-session or §7-stated. It found two recurring false denies,
   and the operator took both §3.3 changes (2026-10-07): a variable bound earlier in the same
   command, and a `cd` in the same command, are now followed;
6. **done** — `tests/test_guard_claude_live.py` passes against Claude Code 2.1.285, and
   `research/m37-guard-live-observation.md` records three sessions. In the two natural ones the
   start text alone kept opus and sonnet off `sed -i`, so the deny was seen only where the prompt
   left no choice;
7. **done** — the build review, APPROVED (`reviews/m37-edit-guards-review.md`); `./check.sh`
   and `./check-matrix.sh --parallel` green on `93615a0+3fb5dbc5c7e3`. Nothing is committed; a
   pull request is the operator's to ask for, and its release should be `0.4.0` (brief).
8. **done (2026-10-07)** — the operator's interactive 2×2 of start text × deny-and-nudge,
   `research/m37-guard-interactive-test.md`, its fixtures and scores in
   `~/ZikaronTesting/story-key/`. The start text alone kept arms B and D off scripts; the deny
   redirected C into reading every file first, and was then overridden with a true reason; the
   nudge gave B its full re-read pass, through `git diff -U4`; C's overridden script rewrote all
   fourteen files and no nudge reached any, which is step 10.
9. **done (2026-10-07)** — **§3.2 row 6, a scratch script that is run** (operator, 2026-10-07:
   make the change first, then re-run the arms). Round 3's arm A did its bulk edit with
   `cat > <scratchpad>/fix.py <<'EOF'` … `python3 <scratchpad>/fix.py`, which passed two
   exemptions at once. Measured (`research/m37-scratch-script-replay.md`): 231 runs of a `/tmp`
   script in local transcripts, 85 staged by a heredoc in the same command; replayed through the
   product, row 6 is the first deny on 54 of 33,069 calls — 47 authored rewrites, 2 golden files,
   5 the stated argv false deny. The rule: a shell or row-4 interpreter whose script operand is
   scratch has that script judged as a scanned heredoc body fed to the same word — its text a
   body a `cat`/`tee` heredoc staged for that path earlier in the same unit, else **one bounded
   read of the file**, the guard's one file read (§1), wired at `main` alone. The start text and
   row 6's deny label are memory-reviewer's; the build review is APPROVED
   (`reviews/m37-edit-guards-review.md`). **Row 4's script-flag test stays unchanged** (operator,
   2026-10-07), so a Python `-W`/`-X` cluster ending in `e` keeps a run row 4's, a §7 miss.
10. **done (2026-10-07) but the post-release install** — **the override's acknowledgement asks
   for a re-read** (operator, 2026-10-07: implement it, re-run arm C, then the work is done),
   since the nudge fires only after `Edit`/`Write`. Steps: (a) **done** — design §3.4; (b)
   **done** — memory-reviewer's acknowledgement text; (c) **done** — the build, its review
   rounds, `./check.sh` green; (d) **done** — arm C2 re-run and scored, in the note; (e) **done** —
   `research/m37-guard-interactive-test.md`, and §7's count (d) now counts a `git diff` that shows
   content, wherever after the last edit. **The landing** (operator, 2026-10-07: done means
   documented, swept, version bumped, deployed, PR sent): (f) **done** — the sweep of every claim
   this build changed; (g) **done** — `[project] version` is `0.4.0` (operator, 2026-10-07: "it
   is v0.4.0 - since I'm going to release it"); (h) **PR #23**, branch `m37-edit-guards`, its CI
   the matrix; (i) **after the operator's release** — the guards installed with
   `--components both` into `~/Trading/LeibaTrader` and `~/Dividends`, and into `~/Memory` only
   on the operator's say-so, since this agent treats it as read-only. Test debris lives in
   `~/ZikaronTesting/` (operator, 2026-10-07).

**Open with the operator:** whether to commit the replay's full verbatim deny list, which this
build keeps out of `research/` because it names private paths and other projects.

**Claude Code runs a hook `command` through a shell** (measured,
`research/claude-code-hook-command-shell-probe.md`), so every Claude Code hook path is now
shell-quoted — the memory install's too, which wrote an unquoted path that a venv directory
containing a space broke. `shlex.quote` leaves a safe path unchanged, so no default install moves.

`experiments/m37_guard_prototype.py` is superseded by the package and fails §8's subscript-chain
row by design: §3.3 says a chain containing `.stem` yields nothing, and the prototype stopped
reading a chain at a subscript.

**Operator direction for the build and its review (2026-10-07):** the approved design and the
filtering rules are fixed — nothing new is invented and nothing existing is changed unless it
breaks the product — and the product's rule logic follows the prototype's algorithm but is
organised, documented from examples and referenced to the rules, rather than transcribed.

After any §3 or §8 edit, run `.venv/bin/pytest -q --no-cov tests/test_guard_rule_table.py`.
**§3's rules change only on an observed command, never on a conceived edge**
(`design/edit-guards.md` §7).

**The host is busy for days (operator, 2026-09-29)**, so no latency figure measured meanwhile is
comparable with an idle-host budget.

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

**Nothing is installed into this repository**, deliberately — M37's edit guards included, since
the `.venv` runs the code under development. `python -m zikaron.install --project .
--harness claude-code` would install the memory store; `--harness auto` refuses here because the repo carries both
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
**It runs this repository's working tree, deliberately** (operator decision 2026-09-30: agents in
real projects exercise the dev build, so their friction reaches this repository at once rather than
a release later). Its `.mcp.json` and its service both launch `/home/nathan/Zikaron/.venv`, an
editable install, so every service or MCP client it starts imports whatever the tree holds at that
moment — an uncommitted edit here is live there at its next start.
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

- **The `bounds`-on-first-call query ran 2026-09-29: 0 of 18** (session, verb) first calls refused
  `bounds`, across all three real stores. That is only a day of `call` rows, 61 of them on
  `~/Trading/LeibaTrader`, so it says nothing yet. **Re-run it 2026-10-29**, with the query below
  (read-only, per store). It measures how often an agent worked from a guessed schema. **It does not
  verify `alwaysLoad`**, which was checked directly, by reading a session's tool list.
  `WITH c AS (SELECT session_id s, json_extract(detail,'$.method') m, json_extract(detail,'$.error_code') e, id FROM event WHERE kind='call' AND session_id IS NOT NULL) SELECT c.m, count(*), sum(coalesce(c.e,'')='bounds') FROM c JOIN (SELECT s, m, min(id) i FROM c GROUP BY s, m) f ON c.id=f.i GROUP BY c.m`
- **Q22's post-release measurement — re-run 2026-10-30.** M34's headline form rule shipped in `0.3.0`;
  what it has not been measured on is new `remember` writes. Run `VERDICT_MARKER` from
  `experiments/m34_gist_replay.py` over each real store's gists written since 2026-09-30, read the
  marked ones, and compare with the 169-record baseline Q22 records (`FINDINGS-archive.md` §"Closed
  with `0.3.0`"). A rate near
  the baseline says the write-side description does not bind and the consolidator is the only
  enforcement; that would argue for the corpus repair pass below before anything else.

- **`tests/test_service_writer.py::test_the_wait_for_the_write_lock_ends_at_the_deadline` is
  load-sensitive.** It asserts an overrun under `0.25 × budget` (125 ms) of wall clock, and measured
  147 ms once on a host at load 6–7. **Fix proposed:** bound it at `0.5 × budget`, which still tells
  "refused at the deadline" from "a whole budget late" — the property the test names. Outside M37's
  fence (the service), so for the next milestone that touches the writer.

**An owed item goes here the moment it is identified**, not into the section that happens to have
measured it.

**A corpus repair pass is owed, now that M34's form rule has shipped** — the rule was sequenced first
so a pass over the 169 records would not rewrite them into 169 fresh verdicts. Proposed shape:
re-seed the live long-term records as journal entries — `experiments/m34_gist_replay.py`'s
`_SEED_ROWS` selects only rows a `remember` created, so this needs a `--tier long_term` option — and
consolidate them in a replay store first, judged on the
same four bars, before touching a live store. The consolidator reaches a long-term record otherwise
only as a merge target, which would leave most of them unchecked.

**Cheap and never run, in dependency order.**

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
not a proxy**, where the form rule had its own instrument in M34's replay.

**Machinery Q12, Q19 and Q21 are blocked on.** Q21's **offline replay harness** — a rewriter fed the
real corpus and a *different* agent ranking whether substance survived, blind, A/B in random order,
against a preregistered bar, on a `VACUUM INTO` snapshot rather than the live store, scoring a fact
dropped / a condition dropped / severity reduced separately. Q12 and Q19 lack the same machinery.

**Unrecoverable, recorded so it is not looked for.** The consolidation A/B has **no pre-run baseline**
— both `/tmp` snapshots are gone, and `~/Memory` as it stands is the *post*-run state.

### How the next review should be briefed

From M33's review trail, which cost about 20% of a week's reviewer capacity (operator measurement,
2026-09-28), and M37's, which cost about half of one (operator, 2026-10-07).

**The brief is the self-review skill's template, filled with facts and nothing else**
(`.claude/skills/self-review/SKILL.md` step 6). Operator direction goes in its `On the operator's
authority:` line in the operator's exact words. Any framing the author composes — what to look for,
how hard, what is wanted — tells the reviewer which findings to produce.

**Do not narrow a review's scope to cut it, and do not name the artifact you expect the findings in.**
M33's late blockers were in surfaces nobody thought were touched — the envelope deriving its accepted
`client_kind`s from the enum, the drift guard binding the per-kind table to `EVENT_SPECS` — and a scope
of "the seams this change reaches" excludes those by construction, since *which seams it reaches* is
what the review finds out.

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
polishing research notes. Put this decision in the brief's `On the operator's authority:` line as
recorded here, and decline such findings when a round returns them anyway.

### Live design questions

D1 was amended 2026-09-15: the knowledge index is Zikaron's own. `design/knowledge-index.md` is
normative and APPROVED; M19–M25 landed. What is still open:

**Ids are stable and retired rather than reused.** 4, 8, 10, 11, 13, 15, 18, 20 and 22 closed and their numbers stay spent, so an `open question N` citation written anywhere in the corpus still means what it meant; the closed entries are in `FINDINGS-archive.md`. Ids sit outside the list marker because a Markdown renderer renumbers `1. 2. 3.` sequentially and would undo this.
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
