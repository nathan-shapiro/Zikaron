# Zikaron — project instructions

## What Zikaron is
**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the **tribal knowledge** a
project accumulates: how to build and test, which steps fail silently, which env vars the integration tests
need, which API is not safe to use yet and why, what was already tried and how it failed.

Scope line, set by the user: Zikaron is **not** a codebase knowledge base — a separate system handles code
structure, symbols and repo maps. Zikaron stores what is learned by living through the work. The
operational test: *could you learn this by reading the code?* If yes, it is out of scope.

## Project memory
`FINDINGS.md` is this project's **living working memory** — the decision index, where the work stands, and
what is still open. It is imported below, so it is in context every session. **Maintain it continuously**:
when state changes, edit it; when a section stops being live, move it to `FINDINGS-archive.md` rather than
letting this file sprawl. It is the thing a fresh session resumes from, and it is only worth that if it is
current.

`FINDINGS-archive.md` holds the finished record — build history, the milestone plan, dogfooding evidence,
references, and §"The knowledge index as built" (M19–M24, moved there 2026-09-18). Read on demand.
**Read its §"Dogfooding notes" before proposing anything**: most of what a
fresh session would think to try has already been measured there, and several plausible ideas are refuted.
**"This file" inside a moved block means `FINDINGS.md`**, where that text was written; the section
header says so, and nothing was re-pointed, because the archive records what was believed and when.

@FINDINGS.md

## The design record
`design/` is normative. **`design/overview.md` is the entry point** — the system in one page and the full
D1–D33 decision table *with rationale*. FINDINGS.md carries a one-line index only; **never re-litigate a
settled decision from that index alone.** Read `overview.md` first.

| Document | Covers |
|---|---|
| **`design/overview.md`** | **Start here.** What we are building, the system in one page, provenance, and the full D1–D33 table with rationale |
| `design/schema.md` | v0 SQLite tables, indexes, the retrieval-eligibility predicate and its per-consumer filter table, the `meta` initialization contract, bounds, 20 invariants (21 withdrawn), per-kind event shapes, linked sessions, what is deliberately absent |
| `design/architecture.md` | four components, RPC choice and rejections, request envelope (resolved and bootstrap forms), the two-rung session-label ladder and derived `label_source`, subagent-session push suppression, paths, filesystem security, lifecycle, degraded modes, both tool surfaces, two validation-precedence ladders, error table, distribution artefacts including the consolidator's model field |
| `design/retrieval.md` | the read path: hybrid fusion, push vs pull, fusion depth vs output budget, total order, query construction on both arms for external and internal queries, embedding, no reranker, supersession demotion, the known fusion defect |
| `design/indexing.md` | chunking contract: boundaries, gist-prepending, rollup, atomicity |
| `design/consolidation.md` | grouping mechanism and rejected alternatives, candidate construction, provisional parameter seeds and what they are not, consolidator identity and model, never-lose guard |
| `design/write-policy.md` | the `agentSpawn` prompt text, its rationale, the secrets and poisoning boundary, the operator erasure procedure, six instrumented signals, known gaps |
| **`design/build-plan.md`** | **Per-milestone briefs: scope, normative sections, invariants, done-when, scope fence.** Read the brief for the milestone you are on |
| **`design/coding-standards.md`** | **Binding.** Structure, domain model, typing, the three test tiers, invariant tests, comment rules, dependency rules, the check gate |
| **`design/knowledge-index.md`** | **Normative.** The knowledge index: one SQLite file per knowledge base, the registry in `memory.db`, discovery and filtering, chunking, both index arms, grouped cross-KB search, the indexer process, the seven MCP tools and the CLI, K1–K13 and 16 invariants. `design/schema.md` still owns `memory.db`'s tables — including the registry — and `design/overview.md` every memory-store decision |
| **`design/harness.md`** | **The two supported harnesses as one table (D34)**: detection, session identity and its nesting limit, trigger and output-channel mapping, injection budgets, subagent rules, where D32's gating splits, consolidation ownership, the consolidator's model, and **the installer's two targets** — the value/shape split, the three flags and what each refuses |
| `design/prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across |

Evidence is separated by kind and stays that way: **`research/`** measured results and literature notes,
**`reviews/`** review rounds, **`experiments/`** re-runnable harnesses, **`spikes/`** throwaway probes.

## Setting up a development environment

**Nothing here is in the repository, and none of it needs a Python already on the machine.** Run this
once per machine, in this order — the order matters, since step 3 has no interpreter to use until
step 2 has run. Verified end to end on 2026-09-21.

```bash
# 1. uv. A static binary; needs no Python, which is why it comes first.
curl -LsSf https://astral.sh/uv/install.sh | sh          # adds only `uv` and `uvx` to ~/.local/bin

# 2. The tested interpreters. `--no-bin` is not optional — see below.
uv python install --no-bin 3.12 3.13 3.14

# 3. The project virtualenv the gate runs in. `--seed` provides `pip`, which `uv venv` omits by
#    default and which the editable install below needs.
uv venv --python 3.12 --seed .venv
.venv/bin/pip install -e '.[dev]'
```

After that, `./check.sh` and `./check-matrix.sh --parallel` both work with no `PATH` setup of any kind.
`.venv-matrix/<version>/` builds itself on first use. A machine that already has a Python ≥ 3.12 it
would rather use for `.venv` can substitute `python3 -m venv .venv` for step 3; the matrix still
needs step 2.

**`--no-bin` is the part to get right.** Without it, `uv python install` puts a `python3.12` in
`~/.local/bin`, which on a normal `PATH` sits *ahead of* `/usr/bin/python3.12` and silently becomes
what every bare `python3.12` means — including for tools that have nothing to do with this project.
It happened here: an earlier setup left exactly that shim pointing into a `/tmp` session directory,
which then made all three matrix virtualenvs ephemeral. `check-matrix.sh` asks `uv` for a
**managed** interpreter instead (`uv python find --managed-python --no-project`, both flags
required — the plain form answers with the project virtualenv), so nothing needs to be on `PATH` at
all.

**Where they live, and why it matters**: `~/.local/share/uv/python/`, which survives a reboot.
`.venv-matrix/<version>/` is built from them on first use and rebuilt whenever `pyproject.toml`
changes, or its base interpreter changes or disappears — so switching `ZIKARON_PYTHON_3_13` to a
different build, or letting `uv python upgrade` move the managed one, rebuilds rather than silently
reusing the old one. **Never point these at a scratchpad or `/tmp` path** —
a virtualenv whose base interpreter is deleted has a dangling `bin/python`, and `-m venv` run over
it does *not* repair the link.

## The check gate
**`./check.sh` is the per-edit gate and the definition of done for a change; `./check-matrix.sh` is
additionally required before a milestone lands.** Nothing is finished until both exit 0. `check.sh` runs `ruff format
--check`, `ruff check`, `mypy --strict` over **the package and the tests**, then pytest with a coverage
ratchet across **every** package under `zikaron/` — a test asserts that list is complete — under a
600 s `timeout`.

**It is hermetic, and deliberately so.** Two tiers are excluded — `integration_kiro` and
`integration_claude` — because they need a third-party harness binary installed *and working*, which
is somebody else's credential state rather than anything in this repository. Run them by name when
you mean to (`.venv/bin/pytest -m integration_kiro`). **Nothing is covered only there**; the
hermetic equivalents stub the binary through `conftest.stub_harness_binaries`.
`design/coding-standards.md` §"five tiers" is normative.

**`check-matrix.sh` is the one deliberate exception to that hermeticity, and it is a separate script for
exactly that reason.** It needs an interpreter per version it runs — a uv-managed one, an explicit
`ZIKARON_PYTHON_3_13`, or a bare `python3.<minor>` on `PATH` as the last resort — machine
state, which `check.sh` depends on nothing of. It builds a virtualenv per version under
`.venv-matrix/`. What it alone covers is the two version-dependent rows in
`zikaron/service/asyncio_compat.py`, each unexecuted on the versions that do not select it, plus
deprecations-as-errors. An absent interpreter is a **red** version, never a skip. `check.sh` itself
stays hermetic and stays the gate for an ordinary edit.
**Run it as `./check-matrix.sh --parallel`** — every version at once, about 3.5 minutes on a warm
tree, one result line carrying the tree identity all three were measured against. **Do not edit
anything while it runs**: it samples that identity before and after and refuses if they differ, and
the identity covers untracked files, so a review round appending to `reviews/` voids the run.

The formatter's output is authoritative: a `format --check` failure means running `.venv/bin/ruff format
.`, not adjusting the code by hand to satisfy it.

**`design/coding-standards.md` is binding** — read it before writing any code.

## How this project works

- **Milestones, not tasks.** Work is scoped by a brief in `design/build-plan.md` (scope, normative
  sections, invariants to cover, done-when, and an explicit **scope fence**), lands as one commit, and
  leaves a review file behind. Work the lowest-numbered incomplete milestone; do not skip ahead.
- **Never commit. The operator commits.** No `git commit`, no `git push`, no `--amend` — not when the
  gate is green, not when a review reaches APPROVED, and not as a step inside some larger task that
  was asked for. Staging, branching and reading history are fine. When work reaches the point where
  committing is the obvious next move, say so and stop there.
  **The sentence above is the one this exists to disarm**: "lands as one commit" describes what a
  milestone *is*, not permission to land it. An agent reading that line at the end of a green
  milestone has every reason to think it has been told to commit, which is precisely why the
  prohibition sits directly beneath it rather than somewhere more logical.
  **Recorded here rather than in Zikaron's own store, deliberately**, and the reasoning is the
  project's own: `retrieval.md`'s preamble frames every retrieved memory as *untrusted reference
  material* rather than instruction, which is correct for a store an agent writes into and wrong for
  a standing rule that must bind. A memory record would be advisory. This file is not. That is
  FINDINGS open question 14 resolved for one concrete case — the seam is real, and the instruction
  file is the right side of it.
- **Never run a git command that discards uncommitted work.** Not `git checkout -- <path>`, not
  `git restore <path>`, not `git reset --hard`, not `git stash`, not `git clean`. **None of them has
  an undo an agent will find in time** — `git stash` technically keeps what it took, but it takes all
  of it in one step, and a stash nobody remembers is as gone as a revert —
  and **in this repository they are maximally destructive by construction**: the rule directly above
  says the agent never commits, so *everything* an agent has produced — every design edit, every
  finding, hours of it — is uncommitted at all times. The two rules compose into a trap, which is
  why this one sits here rather than somewhere more logical.
  **The trigger is never a big dangerous-looking operation. It is tidying up.** Measured here,
  2026-09-21: verifying that a new tree-fingerprint responded to content, I appended one probe line
  to `FINDINGS.md` and removed it with `git checkout FINDINGS.md`. That reverts the **whole file**,
  and it took the entire session's work on it — the file has no notion of "the line I just added".
  It was recovered only because the content still sat in this session's context; one compaction
  earlier and it would have been gone. **The operator reports this is not the first session it has
  happened in**, which is what moved it from an incident to a rule.
  **It happened a second time the same day, and that instance is the argument for the remedy.** While
  walking a failure table in a throwaway repo, a `git clean -qfd` in one cell silently deleted the
  untracked helper script the next cell needed. Identical class, zero cost — because it was a scratch
  repo and the file was one heredoc away. That is the whole difference between the two instances.
  **What to do instead.** Probe in a scratch directory, never in the repository — a throwaway
  `git init` under the scratchpad answers every question about git's behaviour at zero risk, and it
  is what the fingerprint's own failure table was eventually walked in. To undo *your own* recent
  edit, re-edit the file. If you genuinely need a pristine copy of a tracked file, read it with
  `git show HEAD:<path>` and write it somewhere else. **`git checkout` is for branches here, never
  for paths.** Staging, branching and reading history remain fine.
- **Pressure-test consequential work with the `self-review` skill** before finalizing a design doc, plan,
  spec, schema, or config. It delegates an independent critique to **memory-reviewer** and iterates to
  convergence. Reserve it for work that is expensive to get wrong — each loop spends extra cycles.
- **A green gate is not "ready for review". Sweep the class before you spawn a round.** A review
  round is the most expensive tool in this crew and a grep is nearly free, so a finding the grep
  would have produced is pure waste — and it is invisible from inside the loop, because every round
  still ends in a green gate and a tidy summary. Before spawning: grep every claim you changed **in
  all of its phrasings**, not the one you just edited; re-read each changed passage together with
  its neighbours; mutation-verify every guard added since the last round; and when a defect turns up
  in one caller of a shared helper, audit its **other** callers for the same class.
  **Grep locates candidates. It does not decide coverage, and treating it as though it does is the
  single most expensive habit this project has recorded.** Measured on M23: six review rounds, three
  of them spent on *one* hole, against an operator budget of 53% of a week's reviewer capacity in a
  day. Every one of those sweeps was run honestly and every one missed, because a string search can
  only find sentences that resemble the sentence you edited — and the sentences that go stale are
  the ones that *followed from* what you edited, which share none of its words. The check that works
  is reasoning, and it is cheap: **state the change as a before/after pair of propositions, write
  down what the old proposition licensed you to conclude, and decide for each conclusion whether it
  still holds.** Then go read the passages about those subjects — by meaning, not by match. On M23
  the change was "the identity is written by the drop, not at completion"; the conclusion that
  silently died was "a revert restores agreement, so nothing compared disagrees", which shares no
  phrase with the change and survived two sweeps in seven places.
  **For recovery, lifecycle or state-machine work, do this before the first review round, not after
  the first blocker: build the perturbation table and walk every cell.** The axes are the ones the
  feature already names — where the process can be interrupted × what a human may change underneath
  it × which values move and which do not. M23's table is eight cells (killed before/after the drop
  and before/after the first commit × configuration reverted or seen through × same width or
  different), and three separate review blockers all lived in cells nobody had walked. Walking them
  costs an hour of reading; each one cost a round.
  **The tell that you have skipped this is in the brief you are writing**: if it asks the reviewer
  to check something you have the means to check, check it first and tell the reviewer what you
  found. **Counted on M22** — 14 of rounds 3–5's 17 findings were self-findable, nearly all of them
  failures to apply rules stated on this page. `FINDINGS.md` §"PROCESS FAILURE" carries the full
  accounting. Narrating a rule is not running it, and a well-written entry about a lesson reads
  exactly like having learned it.
  **This bullet has already caught itself**: the sentence above first read "roughly 14 of 18", the
  18 was never counted, and when that was corrected it was corrected in `FINDINGS.md` alone — a site
  fix, inside the pair of documents that define why a site fix is not enough. A review round found
  the survivor here. **Two documents stating one number is two sites, and the second is the one you
  are not editing.**
- **Measure before you assert.** Token counts, retrieval hit rates and end-task success are the currency;
  "it feels better" is not a result. **Name the quantity before quoting a number about it** — this corpus
  has caught itself violating that rule against a live store, and the entry stayed.
- **Withdraw claims in place.** When a finding is refuted, the original text stays with the refutation
  beside it. Several entries in FINDINGS are structured that way deliberately. Do not quietly delete a
  claim that turned out wrong — the fact that it was believed is itself evidence.
- **Edit with `Read` and `Edit`/`Write`, never with find-replace scripts.** Do not edit files in this
  repository through `sed`, `python` string-replacement, heredoc rewrites, or any other script that
  mutates text you have not read in its current state. This **overrides** any ambient instruction to
  prefer shell tooling for file changes. Read the passage, edit it, and for a multi-part change read
  the *whole* affected section rather than the lines you intend to match.
  **Measured, in this repository, 2026-09-14.** A 1,000-line design document was revised across three
  review rounds using `python` replacement scripts. The scripts were disciplined — every replacement
  asserted exactly one match, and two aborted correctly on a miss — and the mechanical part never
  failed. **The document still accumulated contradictions at a rate the reviewer described as its
  dominant defect class**: a fix landing in one section while a neighbouring section kept asserting
  the pre-fix world. Round 2 was *four blockers, every one of them an artifact of editing round 1's
  fixes in place* — a citation corrected in one sentence and left standing in the next; a counter
  added in §12 that falsified an "exactly one writer" claim in §3.3; an invariant that contradicted
  the crash story three sections away *and* would have destroyed the signal it named if enforced.
  A matched-once replacement proves you changed what you aimed at. It proves nothing about the
  sentences around it, and those are where this failure lives.
  **So, and this is the half that actually catches it: after any edit, re-read the changed passage
  end to end *together with the passages around it*, then grep for the *claim* you changed — not for
  the phrasing you happened to replace — across the whole corpus rather than only the file you were
  editing.** This corpus has convicted itself of that exact distinction before
  (`FINDINGS-archive.md`, M18: audits that "enumerate the *phrasings* a reviewer quoted rather than
  the *claim*").
  **That step is required whatever tool made the edit — `Read`/`Edit` does not exempt you.** Measured
  again in M19's review, where every edit went through `Read`/`Edit` and no script was involved:
  **two of round 2's findings were artifacts of editing round 1's own fixes in place** — a multiplier
  contradicted by the table printed beside it, and a "median 3 of 3" claim refuted by numbers the
  same run had produced. Round 3 then found a sentence that was false **in two files at once** and
  had survived two fix passes over its neighbouring lines. That last one is why the grep is over the
  corpus and not the file: an enumeration drifts *across* documents, not only within one.
  **What M19 does not license is a rate comparison**, and an earlier draft of this note tried to make
  one — 4 review rounds against 12, amendments to an already-reviewed document against a fresh one.
  It establishes that the failure happens without scripts. It does not establish that scripts are
  innocent, and per round the scripted case still looks worse: its round 2 alone was four blockers of
  this class.
- **Comments explain measured reasons**, not intentions. Much of this codebase's commentary records what
  was actually observed to break and why the code is shaped around it. Match that when you add to it.
- **Dogfooding is a requirements source.** This is a coding agent with a memory problem working on the
  memory problem. When context loss makes you re-derive an established fact, or a handoff to a subagent
  goes badly, that is evidence — capture it rather than working around it silently.

## The crew
Four subagents, in `.claude/agents/`. Delegate to them rather than doing their work inline.

| Agent | Model | Use it for |
|---|---|---|
| `memory-assistant` | sonnet | **All literature and prior-art search.** Give it a precise brief and a target `research/<slug>.md`; it writes the full note there and returns a synthesis plus the path |
| `memory-reviewer` | fable | Independent critique of a **file-based** artifact. Appends tagged findings and a `VERDICT:` line to `reviews/<slug>-review.md`. Driven by the `self-review` skill |
| `py-runner` | haiku | Any command whose output is verbose or token-heavy — `./check.sh`, `./check-matrix.sh --parallel` (all tested Python versions at once, ~3.5 min warm), test suites, builds, installs, indexing runs. Returns exit code, a terse verdict, failing ids and a temp-file path |
| `memory-researcher` | opus | The primary research and engineering partner. Normally the **main session** (`claude --agent memory-researcher`), not a subagent |

`~/Memory` is a sibling project — a human-like memory system for character agents, with agents of the same
names. Mine it for reusable mechanisms and lessons, **strictly read-only**. Writing there needs the
operator's explicit per-task say-so.

## Harness
This project was built in **kiro-cli** and is being migrated to **Claude Code**. Two things follow:

- **`.kiro/` stays in the repository and is not to be edited.** It is the reference for what the shipped
  product still installs, and the fallback if the migration goes badly. `.claude/` is the live crew.
- **Both clients and the installer now speak both harnesses.** As of M14 the two thin clients read
  trigger names, session variables, output channels and injection budgets through `zikaron/harness/` —
  the one seam, stdlib-only, where a harness difference is allowed to live. Add a harness difference
  *there*, **as data**, never as a branch downstream of it. As of M15 the installer writes either
  harness's artefacts through `zikaron/install/targets.py`, which is the **only** place a difference
  may take a different *shape* rather than a different value; a value that migrates into a
  `HarnessTarget` method is the seam failing, and `design/harness.md` §"The installer's two targets"
  is normative for the split.
- **This repository still has no Zikaron installed into it**, and that is now a choice rather than a
  missing capability: `python -m zikaron.install --project .` would write `.claude/settings.local.json`
  hooks and `.mcp.json` servers here. Until someone runs it, **do not assume the memory tools or the
  push hook are live in this session.** Note that `--harness auto` deliberately **refuses** in this
  repository, since it carries both `.kiro/` and `.claude/` — name the harness.
