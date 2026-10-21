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
| D7 | Consolidation is the only extra LLM; code picks candidates, model judges — **amended 2026-10-14 (D39)**: the memory store's only one; D39's documenter is a second, outside both stores |
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
| D31 | ~~Four~~ **Five** components: core / service / mcp / hook, plus the detached knowledge indexer (D1's amendment), over a Unix-socket JSON-RPC — **amended at M31**: the typed `zikaron` commands are clients, not store-openers, and `init` alone creates a store — **amended 2026-10-13 (M39)**: `health()` reports the service's package version, and a typed command refuses a service of any other version |
| D32 | Two tool sets: ~~five for the primary agent~~ — **five memory verbs plus the knowledge index's seven, twelve in all** (D1's amendment) — and four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |
| D34 | Two harnesses, one implementation: kiro-cli and Claude Code, differences carried as data behind one seam |
| D35 | Supported platforms = Linux + macOS arm64; Windows out by transport, Intel Macs out on `onnxruntime` |
| D36 | Obtained by `uv tool install --managed-python zikaron` from PyPI (the flag is load-bearing), host Python still supported; MIT; model fetched never redistributed; semver `0.x`, ~~with an artefact-shape rule~~ — **amended 2026-10-11**: a minor bump means a schema bump, nothing else |
| D37 | `meta.schema_version` is a supported range; only the service migrates a store forward, in one transaction; nothing migrates back — **amended 2026-10-13 (M39)**: a corpus database is brought forward by whichever process opens it with `memory.db` at version 4 or later, and a corpus schema move moves `memory.db`'s too; a corpus schema version is the `memory.db` version that introduced its shape (corpora go 1 → 4), so a corpus is never ahead of its store |
| D38 | Guards: deterministic regex-only Claude Code hooks deny find-replace edits (override `#ZIKARON-FORCE #Reason: …`) and nudge a re-read after edits; installed only on request, memory/guards/both; not on kiro — **amended 2026-10-07**: a script run from scratch is judged too, the guard's one file read — **amended 2026-10-11 (M38)**: a `pgrep -f`/`pkill -f` matching its own command is denied too, on `Bash` and `Monitor`, per platform |
| D39 | Code knowledge: primitives, no workflow — a command classifies a module's per-source-file documents and removes or moves what that implies, a skill has the agent spawn documenters for the rest until the command reports it up to date; K14 front matter on every document; forward `Depends on:` lines only; on demand; corpus `git_mode: off` (operator, 2026-10-14; `design/code-knowledge.md`) — **amended 2026-10-16**: under Claude Code the skill forks to a background orchestrator subagent; one corpus per module; the documenter and orchestrator hold Zikaron's tools |

## Current state — resume here

**M0–M39 are built, reviewed and landed**, the last as `4f60a15` (PR #26). M26 shipped
**nothing** — neither the reranker nor any chunking change — and that is the result, not a stall.
Each milestone's record is in `FINDINGS-archive.md`, M39's in §"M39 as built"; the briefs
are in `design/build-plan.md`; M32's shipped prose surfaces are normative in `design/retrieval.md`
and decoded in `research/injected-prose-log.md`.

**`0.3.2` is released** — tag `v0.3.2` on `e7b91c4`, on PyPI since 2026-10-12; its note says
to re-run `install` so that `Monitor` is judged. **`main` carries `0.4.0.dev0`** (operator,
2026-10-13), since M39 moved the schema, so the next release is `0.4.0`. **A minor bump means a
`meta.schema_version` bump and nothing else** (operator, 2026-10-11; D36,
`design/distribution.md` §3).

**The guards (M37, M38, D38, `design/guards.md`) are installed in `~/Trading/LeibaTrader`,
`~/Dividends` and `~/Memory`** (operator, 2026-10-07), with `--components both`, re-run on
2026-10-11 so that each routes `Bash|Monitor` to the guard, and they replace
every hand-written instruction about how to edit in those projects' `CLAUDE.md`, which were
removed: a project that installs the guards instructs agents about edits not at all (operator,
2026-10-07). **This repository does not install them** (operator, 2026-10-07): its `.venv` runs
the code under development, so a broken guard would cripple the agent building it. **§3's rules
change only on an observed command, never on a conceived edge**
(`design/guards.md` §7); after any §3 or §8 edit, run
`.venv/bin/pytest -q --no-cov tests/test_guard_rule_table.py`. **Claude Code runs a hook `command`
through a shell** (`research/claude-code-hook-command-shell-probe.md`), so every hook path the
installer writes is shell-quoted.

**The replay's full verbatim deny list stays out of the repository** (operator, 2026-10-16): it
names private paths and other projects, the research notes carry the counts and their readings,
and it is re-derivable on this machine with `experiments/m37_guard_replay.py --dump`.

**The self-match rule (M38, `design/guards.md` §9) moves only on an observed command, and never
toward evaluating the shell** — the operator's line against a "mini shell" is stated in §9.4,
where a review brief can cite it.

**The next milestones: code knowledge** (operator, 2026-10-13) — agents that write
per-source-file documentation into a knowledge base, and a search that says whether each result's
source has moved since it was documented. **K14** (linked knowledge) is settled in
`design/knowledge-index.md` §7.7 and its §14 index; **D39** (the producer) was settled in M40's
brainstorm with the operator, 2026-10-14, and is specified in `design/code-knowledge.md`.
**Each milestone is brainstormed with the operator before its brief is written** (operator,
2026-10-13). The plan, in order:

1. **M39 — linked knowledge: landed** as `4f60a15` (PR #26). **`~/Trading/LeibaTrader`,
   `~/Dividends` and `~/Memory` run this tree's `.venv`**; the first two are at schema 4, and
   `~/Memory` moves the next time a service starts there, when an agent session open across that
   start loses its memory and knowledge tools — refused `schema_incompatible` by its own old
   `zikaron-mcp` — until it restarts its MCP server.
2. **Done — M40's prior art and brainstorm** (2026-10-14): `research/generated-repo-docs-prior-art.md`,
   `research/code-localization-benchmarks.md`, `research/nested-subagent-probe.md` and
   `research/m40-eval-repository-candidates.md`; every decision is in `design/code-knowledge.md`.
3. **Done — M40's brief** (`design/build-plan.md` §M40) **and its spec** (`design/code-knowledge.md`,
   normative for D39), APPROVED by memory-reviewer (`reviews/m40-code-knowledge-brief-review.md`).
   Uncommitted in the main tree, with the post-M39 FINDINGS edits.
4. **In progress — M40's build**, on branch `m40-code-knowledge` (operator's go, 2026-10-16:
   build through the review, then the toy run and the evaluation together with the operator). In
   order, each step done before the next:
   1. **done** — the planner: `zikaron/core/code_knowledge/` (the decisions, pure),
      `zikaron/code_knowledge/` (walk, hashing, `--apply`, JSON), `python -m` and `zikaron/cli`
      dispatch, the gate's `--cov`, coding-standards §1's tree, distribution's front door;
   2. **done** — `HarnessSpec.file_tools` and its `design/harness.md` row; the documenter's prompt,
      memory-reviewer's wording copied verbatim; the skill with its two per-harness constants;
   3. **done** — installation per §5.4 on both harnesses, and the prose that enumerates an install;
      what an install ships is snapshotted for both harnesses under `tests/fixtures/installed/`, and
      `.kiro/` holds no installer output (operator, 2026-10-16; `CLAUDE.md` §Harness);
   4. **done** — the root README's section on code knowledge;
   5. **done** — the build APPROVED by memory-reviewer (`reviews/m40-code-knowledge-build-review.md`),
      every new line executed by a test.

   **▶ RESUME HERE (2026-10-20).** **M40 is committed locally** on `m40-code-knowledge`, the
   branch's first commit over `main`, everything through the documenter's rules against claims
   nothing read supports folded in (`reviews/m40-code-knowledge-build-review.md`); nothing is
   pushed and there is no PR yet. **That PR carries several commits** (operator, 2026-10-20): M40,
   then M40's four follow-ups, each a commit of its own, in this order, each briefed in
   `design/build-plan.md` §"M40's follow-ups — M40-1 to M40-4":
   1. **M40-1, committed as `bed5430`** — the edit guard exempting a background job's
      `$CLAUDE_JOB_DIR/tmp`, brief and build APPROVED (`reviews/m40-1-job-dir-review.md`,
      `reviews/m40-1-job-dir-build-review.md`), measured in
      `research/claude-code-job-dir-hook-probe.md`. Live in the three projects that run this
      tree, so LeibaTrader's memory `f6eb10e5-6cf1-4805-bdf4-5d24ed0a71f5` is now false;
      retiring it is the operator's.
   2. **M40-2, committed over `bed5430`** — `foreground_command` gone from both build verbs and
      the CLI; each build the service spawns writes its output to `knowledge/<id>.log`, which
      `status` names as `build_log`; brief and build APPROVED
      (`reviews/m40-2-indexer-log-review.md`, `reviews/m40-2-indexer-log-build-review.md`). Live
      in the three projects at each build's spawn and each service's next start; a service
      started before it answers without `build_log` until it restarts. The status tool's
      description is at 1,896 of the 1,900 characters `tests/test_mcp_tool_descriptions.py`
      allows, so a sentence added to it later must be paid for.
   3. **M40-3** — a `--model` flag per agent;
   4. **M40-4** — the reminder that a grepped module has a knowledge base.

   **Next: M40-3, worked as M40-1 and M40-2 were** (operator, 2026-10-20: review the brief, write
   the code and tests to the coding standards, pass the done criteria, then review the code —
   re-read loops mandatory before every round), each step done before the next:
   1. **The brief alone**, `design/build-plan.md` §"M40-3 — One model for every agent, and a flag
      for each": first ground it in the code and write into it what it leaves to the builder,
      re-read loop to a clean pass; then memory-reviewer on M40-3 alone in
      `reviews/m40-3-model-flag-review.md` to APPROVED, the standing operator lines of §"How the
      next review should be briefed" in every brief. At the fifth round without approval, report
      what is open and ask.
   2. **A worktree only if the brief says one is needed.** M40-1 and M40-2 used one because the
      three projects import the guard, the service and the indexer from this tree; M40-3 changes
      the installer, which runs only when someone re-installs, so the brief should say so and
      build here.
   3. **The build**: code, tests and documents as the brief's items say; every new test seen red
      against its mutation, applied in memory by a pytest plugin that patches one named mutation
      in on load (`PYTHONPATH=<its directory> pytest -p <plugin>`), never by editing a file —
      M40-2's plugin and runner, `m40_2_mut/` in this session's scratchpad, are the template,
      and a runner must not add `-q`, since `addopts` already has one and `-qq` drops the
      summary line it reads. Then `./check.sh`, and `.venv/bin/python
      experiments/new_line_coverage.py` reporting 0 uncovered.
   4. **The code review**, in `reviews/m40-3-model-flag-build-review.md`, to APPROVED.
   5. **Landing**, on the operator's go: check `git rev-parse --short HEAD` is M40-2's commit,
      then commit `M40-3: …` in the milestone style.

   A commit is amended only while it is `HEAD`, its hash checked first. A feature built for
   Claude Code alone is entered in `design/kiro-gaps.md` (`CLAUDE.md` §Harness). The dependency
   blob and
   the partial-coverage field change K14's format and are brainstormed with the operator first,
   so they are not in this PR. **The
   evaluation's harness now refuses**: `state.json` records `06deae8` as its first start, and
   the M40 commit moved the planner and the installer, which §7's package check covers
   though no run executes them. **Before the repeats, proposed:** narrow that check to what a run
   executes — leave `zikaron/code_knowledge`, `zikaron/core/code_knowledge` and `zikaron/install`
   out of both the porcelain and the diff, one sentence in §7 — which keeps the slice, run under
   an unchanged server, service, hook and index; or re-`prepare` at the new commit and re-run the
   slice (about $49). The M40 commit carries the skill's report wording from the Warp slice, with
   spec §5.2 step 4 to match and snapshots re-rendered; **the evaluation rewritten as issue triage
   on Warp** — spec
   §7, brief §M40 items 6–7, done-when and fence, APPROVED in
   `reviews/m40-code-knowledge-brief-review.md` — `research/m40-evaluation.md`,
   `experiments/m40_eval.py`'s probe stage, `experiments/m40_eval_issues.json` and
   `experiments/m40_eval_diffs/`; and the toy run's record. **The toy run is done**
   (`research/m40-toy-run.md` §1): Warp's
   `app/src/terminal` in a clone at `~/Zikaron-m40/warp`, HEAD `b80b4e3e0`, 407 documents in 57 min,
   `up_to_date`, corpus `code-knowledge/app/src/terminal` built; its re-runs and wrong-claim sample
   are recorded (§3–§4), and the documenter's two new rules measured (§5–§9). **Settled with the
   operator, 2026-10-17**: the documenter **checks every dependency path exists, in one search,
   and leaves out a path that does not — never the dependency**, which keeps its bullet by the
   module's name and the names used from it; on the 77 hardest documents that took missing paths
   from 23% to 4.1%, and to none in a six-document trial, at 1.65× a document's dollars, the
   shell call owed below being the cheaper route; and a source too long to read whole is
   **documented in part and says so** in its role line and Purpose, which `view.rs`'s document
   did once of twice, so its K14 field is owed too. Both rules are tuned for Sonnet 5.5, tested
   separately, not for the evaluation's Sonnet 4.6 (*"There is no need to optimize for legacy
   model"*). The clone at `~/Zikaron-m40/warp` — `view.rs` documented under a 5 MiB cap it sets
   for this experiment (operator) — is what the evaluation reads. **APPROVED**, under the
   operator's *"focus on correctness of prompts / probes / code only … goal is to unblock testing
   of warp"* (2026-10-17): the probe stage of `experiments/m40_eval.py` (`prepare`, `check`,
   `probe`, `install-hook`, `restore`), §7's prompts and the shipped documenter text; the reader's
   tools are an allowlist, measured (`research/m40-evaluation.md` §3). **Prepared and probed
   2026-10-17** (§4 of that note): seed `20261017`, treatment `b`, control `a`; every `Bash` rule
   held natively, so no hook. **The run, judge and score stages are written** (`run`, `judge`,
   `score`, `reanalyze` in `experiments/m40_eval.py`), APPROVED with the live test
   (`reviews/m40-code-knowledge-brief-review.md`, rounds 27 on).
   **The slice ran and was judged** (note §4): 8 runs, $49.19, no discard; the treatment ranked a
   truth file first on 4 of 4 issues, the control on 3; the judge's 32 controls all graded as
   expected. Ceilings from it: `--budget 39 --timeout 4887`. **The repeats are deferred: no
   capacity this week** (operator, 2026-10-17) — about $540 and 14 hours for all of them; when
   they resume, repeat 1's twelve other issues first (`run --repeat 1 --budget 39 --timeout
   4887`, about $150, which skips the slice's cells), then ask again for repeats 2 and 3. **The M40 live test is written and seen red**
   (`tests/test_code_knowledge_claude_live.py`): green on a real `claude`, red with the installed
   documenter removed.

   **Done and APPROVED — the README lists no files** (operator, 2026-10-17: *"code knowledge
   should not have table of content because it is searched with knowledge tool"*;
   `reviews/m40-code-knowledge-build-review.md`; `design/code-knowledge.md` §3.6 is normative). A
   README is current when its digest is, its first line after the block is its title and it has
   no `## Files` heading, so one that lists files is written again — LeibaTrader's and the
   playground's were, 2026-10-18. Its documenter reads the role lines from
   `.zikaron/code-knowledge/<module>/roles.md`, which `--apply` writes and removes, taking a long
   list in samples (operator). **Warp's README is regenerated later** (operator: token capacity),
   so the pilot runs on its corpus as documented and `prepare` accepts it.

   **The playground** (`~/PythonPlayground`, the operator's; commits are theirs) is where the
   amendment below was found and measured; it carries this tree's install.

   **Built and APPROVED — M40's amendment of 2026-10-16** (operator, from the playground runs;
   folded into M40's one commit; `reviews/m40-code-knowledge-build-review.md`): under Claude Code
   the skill forks to a background `zikaron-code-orchestrator` (`context: fork`), so the invoking
   session stays free, while kiro keeps the loop in the session; the documenter and the
   orchestrator hold Zikaron's tools, memory verbs included, so the documenter's start-text
   exemption and scan skip are gone; one corpus per module, `code-knowledge/<module>`; **each
   behavior a document states says whether a test pins it**, and one no test covers is documented
   all the same; under Claude Code the documenter runs at `effort: medium`, the deliberate cost
   tradeoff, and the orchestrator at `effort: high`, while kiro sets effort only per model
   (operator, 2026-10-16). Spec §5 is normative; the evidence, headless and
   interactive, is `research/claude-code-background-subagents.md` and
   `research/forked-skill-probe.md`. **§M40 item 6's interactive playground invocation is done.**
   **Installed into `~/Trading/LeibaTrader` itself** (operator, 2026-10-16; `--components both`,
   default model): the operator documents its code there
   and explains to its agents how to use it. **Its run is recorded** in `research/m40-toy-run.md`:
   198 documents of `sugar-leiba` in 23 min 20 s, every item on its first attempt, no memory
   written; batches of 20, Claude Code's measured concurrency limit, issued together (operator,
   2026-10-16; spec §5.2) — 19 since 2026-10-20, a slot being still held when the next batch goes
   out (operator).

   **M40's evaluation is issue triage on Warp's `app/src/terminal`, replacing the LeibaTrader
   question set** (operator, 2026-10-16; spec §7 is normative, brief §M40 item 7): open issues at
   the clone's HEAD, each scored against the files of a person-written open PR, with the documents
   and without; Sonnet 4.6 documents and Opus 4.6 reads, pinned by full id; the treatment's prompt
   names the knowledge base and both arms' ask for a check against the code; Warp's triage bot
   scored beside both arms, toward a report on how Zikaron could have improved it — publishing one
   is the operator's call. **Selected and frozen**: 16 issues, 4 of them *located* (the body names a
   fix file), in `experiments/m40_eval_issues.json`, listed in `research/m40-evaluation.md` with
   the bot's static scores — a truth file among its first five on all 9 it diagnosed. **The
   closed-issue stage** — hand-picked closed issues at the commits their fixes merged onto, the
   documents rebuilt there — **is a milestone of its own.**

   **Harness versions are recorded, never re-probed** (operator, 2026-10-16): a new Claude Code or
   kiro release is not a reason to re-test a measured behavior.

The dated measurements in §"Owed work" below run on their dates regardless: the guards' field
counts (2026-10-21), the `bounds`-on-first-call re-run (2026-10-29) and Q22's post-release
measurement (2026-10-30).

**The host is busy (operator, 2026-09-29, and again 2026-10-11)**, so no latency figure measured
meanwhile is comparable with an idle-host budget.

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

**Nothing is installed into this repository**, deliberately — M37's guards included, since
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

- **The guards' field counts — compute them 2026-10-21.** The guards went into three real
  projects on 2026-10-07, so `design/guards.md` §7's counts (a)–(d) can now be read from their
  transcripts against each project's pre-install replay (`experiments/m37_guard_replay.py
  --project <dir>`). This is the measurement the interactive test could not make: whether the start
  text holds over a long session, whether overrides carry true reasons or boilerplate, and whether
  agents route around a deny. What it would decide: a reflexive override rate argues for the reason
  rule, a route-around for a new §3.2 row on the observed command. **Count (e), the self-match
  rule's denies, runs from 2026-10-11** — live on `Bash` from the build's landing in this tree and
  on `Monitor` from the re-install that day — against the pre-landing replay's rate
  (`research/m38-selfmatch-replay.md`, which reads every project at once). What it would decide:
  whether a deny is followed by `-A`, a bracket, an override or a route-around, and so whether
  §9.3's fix text works.

- **A stop guard for the turn that ends on a promise** — the agent writes *"I'll now run …"* and
  stops without the tool call. Nathan's practice backed this with a monitor that asked every stopping
  agent whether its goal was met, in phrasing drawn from a large corpus rather than one fixed line,
  and on a "yes" had a second agent check that the artifact existed (operator, 2026-10-14). kiro's
  `/goal` grew from it: planning sets measurable acceptance criteria, and a "done" is verified
  against them. **In this repository the goal already exists and is checkable** — a self-review
  loop's is the review file's last `VERDICT:` line reading `APPROVED`, a milestone's its brief's
  done-when, an edit's a green `./check.sh` — and only the check at the stop is missing. Read
  `/goal`'s implementation before designing one. **Proposed:** a deterministic D38 guard
  on the stop hook both harnesses have, firing only when the last message promises an action and no
  tool call followed, once per turn, asking for the evidence the goal is met or the blocker — never a
  yes/no — and installed on request like the others. **Measure first**: count such turns in the three
  guarded projects' transcripts with the `experiments/m37_guard_replay.py` approach, for the base
  rate and the regex's false positives. Claude Code's `Stop` output handling is ambiguous in its docs
  (`research/claude-code-harness-contract.md`), so a probe precedes any build.

- **A document whose dependency changed reads `fresh`** — proposed by LeibaTrader's
  `leiba-engineer`, endorsed by the operator (2026-10-16). A document records only its own
  source's blob, so when `B.scala` changes, `A.scala`'s account of how it uses `B` can go stale
  while `A`'s source, and so its `source.state`, does not move. **Proposed:** the planner — the
  documenter cannot hash — records, on the first run after a document is written, the blob of each
  file its `Depends on:` lines name, in the document's front matter; search then reports
  `dependencies_changed: [paths]` beside `source.state`, which stays about the file itself; and
  **the planner does not regenerate on it**, since one edit to a widely used file would otherwise
  rewrite every document that names it. The same check closes `design/code-knowledge.md` §8's
  dangling `Depends on:` gap. It changes K14's format and search-time check
  (`design/knowledge-index.md` §7.7) and refines D39's "a file's own hash covers its imports", so
  it is a milestone after M40, brainstormed first. **Measure first**: how often the evaluation's
  wrong-claim sample finds a document wrong because a dependency changed and its own source did
  not.

- **Check a document's dependency paths in one shell call** (operator, 2026-10-17: the area of
  improvement). Checking every path exists made Warp's dependency lines accurate — 4.1% missing,
  then none in a six-document trial — but each check is a search call and a turn, so a document
  costs 1.65× in dollars (`research/m40-toy-run.md` §8–§9). A single `ls`/`test` over every path
  is one call, and a check rather than a search: the file search behaves like `find`, not `ls`
  (operator), and the documenters used its brace patterns to explore directories, not to check a
  list (§9). **Both tools have a job**: resolving where an import lives needs the search, since a
  Rust crate in a workspace or a C++ header on an include path is no 1:1 map from the root
  (operator), while confirming a path already written needs only `ls`/`test` — so the cheap shape
  searches only for an import whose file is unknown, then confirms every path in one call. **The constraint**: the documenter holds no shell, by design, since it writes
  nothing but its document. **Proposed:** grant it a shell restricted to `ls` and `test` — **probe
  first** whether an agent definition's `tools:` line honors `Bash(ls:*)`, since a rule naming a
  tool wrongly is silent — or let the planner run the check after the document is written, which
  costs no model call at all. Tune on Sonnet 5.5, not on 4.6 (operator).

- **Settled — Haiku 5.5 documents, Opus 5.5 orchestrates** (operator, 2026-10-20: *"overall, I
  think it is a win - on the cost side mostly"*). Claude Code's defaults: `haiku` for the
  documenter (`HarnessSpec.documenter_model`), `opus` for the orchestrator (`ORCHESTRATOR_MODEL`,
  at `effort: high`), `sonnet` for the consolidator; `--model` sets all three; kiro keeps
  `claude-sonnet-5`, offering no Haiku 5.5. **Measured on LeibaTrader's 197 documents**
  (`research/m40-toy-run.md` §14): $17.73 against Sonnet's $52.86 — documenters $2.49, the
  orchestrator $15.24, now most of a run's cost, its context growth about 2,000 tokens a document
  the next lever; its output $0.18, so `effort: high` costs nothing that matters. Dependency paths
  alike (2 naming no file each); Haiku's documents 1.49× as long; in four of five sampled
  documents checked and the README, Haiku two wrong claims, both unsupported by what it read —
  the prompt now forbids both — and Sonnet one. On the playground's four documents the run cost
  more (§12): the orchestrator's cost is mostly fixed.

- **An interactive orchestrator waits for background documenters; it cannot ask for the
  foreground** (operator, 2026-10-20). Interactively Claude Code removes the spawn tool's
  `run_in_background` parameter and runs every spawn in the background
  (`research/claude-code-background-subagents.md` §Q3), so neither prose nor a hook can ask for the
  foreground there; only headless `-p` offers the parameter, and needs it (`research/m40-toy-run.md`
  §5). LeibaTrader's Sonnet orchestrator, 2026-10-19, waited for its 35 spawns with a `sleep`/`find`
  loop counting written files, which the skill forbids; the playground's Opus orchestrator,
  2026-10-20, took the absent parameter as the skill means it and waited for the notifications.
  **Done:** the orchestrator on `opus`, and the skill's spawn clause names the parameterless case
  as expected and says the harness keeps the orchestrator running until its spawns report, so it
  waits by issuing nothing — never forbidding the end of its turn, which beside the bans on
  sleeping and polling would leave only busy-work to wait with. **Next:** read LeibaTrader's next
  regeneration transcript for a `sleep` or a file count; if one recurs, a `PreToolUse` hook denying
  `sleep` to the orchestrator is the cheap enforcement.
- **A cheap reader in the triage evaluation.** Practice reported by the operator (2026-10-17): a
  strong model orchestrates, a mid one writes documents, a cheap one codes — the installer's half
  is M40-3. **Proposed:** the documents may help a cheap reader more than a strong one, since a
  strong one finds its way unaided, so the triage evaluation gains a third reader, Haiku 5.5, over
  the same two copies — a hypothesis to measure, not a result.

- **A partial document is partial only where a search seldom lands** — measured on Warp's
  30,181-line `view.rs`, read 3,000 lines deep (`research/m40-toy-run.md` §6). A search result
  carries the matching lines, the path and `source.state`, so the documenter's *"describes the
  file in part"* in its role line reaches a reader only on a hit there (operator, 2026-10-17).
  **Proposed:** a K14 front-matter field the documenter writes for a source it could not read
  whole — `zikaron-coverage: partial` — reported with every result beside `source.state`, the same
  path the blob's state takes; it changes K14's format (`design/knowledge-index.md` §7.7), so it is
  a milestone after M40, best brainstormed with the dependency-blob item above, which touches the
  same front matter. **Measure first**: how many sources in a real module are past the
  documenter's window.

- **Does a reader still verify a document against the code late in a long session?** The rule
  lives in the project's `CLAUDE.md`, which a long session weights less (operator, 2026-10-16), as
  the edit rules were before D38's guards; at the point of use every search group carries the
  corpus description — *"A lead for where to look, checked against the code"* — and every result
  its `source.state`. **Measure first** — not in LeibaTrader, whose agent edits a few files it
  already knows, so it rarely navigates (operator, 2026-10-16), but where a session works across
  unfamiliar code, such as the triage evaluation on Warp (§"Current state"): how
  often a code-knowledge search is followed within a few tool calls by a read or search of the
  top result's source, and how often an edit to that source follows with none, by position in the
  session. **Proposed if
  it decays:** a D38-style `PostToolUse` hook on `zikaron_knowledge_search` whose results include a
  linked document, emitting one deterministic line to verify against the code before editing,
  installed with the guards.

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

**A finding is weighed by how likely its case is against what its fix costs** (operator,
2026-10-13: *"Reviewer tends to find crazy edge cases (and stuck network drive sounds like that).
Please escalate to me if reviewer continues pushing for over-engineered solutions against unlikely to
happen situations."*). A rare case with a cheap fix is applied; a rare case with a heavy one is
declined with its reason in the review file, or brought to the operator if the reviewer presses it.
Those words go verbatim into the brief's `On the operator's authority:` line.

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
  it**: whether a script owes the retry, or this surface owes a longer deadline — a miss here fails
  a command, where on the hook's path it costs only a skipped injection. Measurement:
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

**The knowledge index's own open questions, from M25's dogfooding** — evidence in
`FINDINGS-archive.md` §"M25, and the last three pre-knowledge-index milestones"; field use in
`research/code-knowledge-sizing.md` §3. M39 settled none of them; each is settled in M40 where it
touches it, and stays here otherwise.
- **Nothing owns refreshing a corpus**, and a file never indexed is invisible to search with no
  `stale` signal. In the field refreshes outnumber searches 26 to 9, because the project's
  `CLAUDE.md` asks for one after every write. **For code knowledge it is settled**: the skill
  refreshes its corpus at the end of every run (`design/code-knowledge.md` §5.2). **Proposed** for
  hand-written corpora: give `knowledge_scan_on_session_start`
  (`design/knowledge-index.md` §16, item 6) to the session-start warm helper, once a no-change
  refresh is measured.
- **The `git_mode` default, `tracked`, hides a document until it is committed**, and the one real
  user overrode it on both corpora. **For code knowledge it is settled** (M40's brainstorm,
  2026-10-14): persistence is the user's choice, so the producer registers its corpus with `off`
  (`design/code-knowledge.md` §5.3). **Proposed for hand-written corpora:** keep the default,
  since nothing yet says a user would rather see uncommitted drafts.
- **Intra-document supersession has no representation**: a chunk carrying a withdrawn claim is as
  findable as its correction. **Proposed:** no product change; the steering caveat stands until a
  withdrawn claim is observed quoted as current.
- **`rrf_k` and `fusion_depth` are frozen in each corpus's `meta` at creation**, with no path to
  change them, though they describe one response rather than how the index was built.
  **Proposed:** stop seeding them at creation, and read configuration at search time wherever a
  corpus's `meta` does not already carry a value.

### Harness

Both thin clients and the installer speak both harnesses. `.claude/` is the live crew; `.kiro/`
stays as the kiro fallback, and what the product installs on either harness is snapshotted under
`tests/fixtures/installed/` (`CLAUDE.md` §Harness). Two fidelity losses from the move, both
deliberate: memory-reviewer runs `fable`, a different model from the author's `opus` but from
the same vendor, where under kiro it was GPT, so **cross-vendor independence is gone** and an
APPROVED is weaker evidence wherever a blind spot shared by one vendor's models is plausible; and
per-agent write scoping has no frontmatter equivalent, so it is stated in prompts and
enforced by nothing.

**The self-review loop has a single point of failure, observed failing twice** — the reviewer model
down, and the reviewer model rate-limited. There is no degraded mode, only a halt. The file-based
protocol held both times: the trail ends cleanly at the last completed round.

**Do not compare recall numbers across the kiro→Claude Code boundary, in either direction.** The
harness, the model, the injection position and the policy delivery all changed at once.
