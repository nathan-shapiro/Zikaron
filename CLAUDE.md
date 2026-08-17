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
references. Read on demand. **Read its §"Dogfooding notes" before proposing anything**: most of what a
fresh session would think to try has already been measured there, and several plausible ideas are refuted.

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
| **`design/harness.md`** | **The two supported harnesses as one table (D34)**: detection, session identity and its nesting limit, trigger and output-channel mapping, injection budgets, subagent rules, where D32's gating splits, consolidation ownership, the consolidator's model, and **the installer's two targets** — the value/shape split, the three flags and what each refuses |
| `design/prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across |

Evidence is separated by kind and stays that way: **`research/`** measured results and literature notes,
**`reviews/`** review rounds, **`experiments/`** re-runnable harnesses, **`spikes/`** throwaway probes.

## The check gate
**`./check.sh` is the definition of done.** Nothing is finished until it exits 0. It runs `ruff format
--check`, `ruff check`, `mypy --strict` over **the package and the tests**, then pytest with a coverage
ratchet across all five shipped packages under a 300 s `timeout`.

**It is hermetic, and deliberately so.** Two tiers are excluded — `integration_kiro` and
`integration_claude` — because they need a third-party harness binary installed *and working*, which
is somebody else's credential state rather than anything in this repository. Run them by name when
you mean to (`.venv/bin/pytest -m integration_kiro`). **Nothing is covered only there**; the
hermetic equivalents stub the binary through `conftest.stub_harness_binaries`.
`design/coding-standards.md` §"five tiers" is normative.

The formatter's output is authoritative: a `format --check` failure means running `.venv/bin/ruff format
.`, not adjusting the code by hand to satisfy it.

**`design/coding-standards.md` is binding** — read it before writing any code.

## How this project works

- **Milestones, not tasks.** Work is scoped by a brief in `design/build-plan.md` (scope, normative
  sections, invariants to cover, done-when, and an explicit **scope fence**), lands as one commit, and
  leaves a review file behind. Work the lowest-numbered incomplete milestone; do not skip ahead.
- **Pressure-test consequential work with the `self-review` skill** before finalizing a design doc, plan,
  spec, schema, or config. It delegates an independent critique to **memory-reviewer** and iterates to
  convergence. Reserve it for work that is expensive to get wrong — each loop spends extra cycles.
- **Measure before you assert.** Token counts, retrieval hit rates and end-task success are the currency;
  "it feels better" is not a result. **Name the quantity before quoting a number about it** — this corpus
  has caught itself violating that rule against a live store, and the entry stayed.
- **Withdraw claims in place.** When a finding is refuted, the original text stays with the refutation
  beside it. Several entries in FINDINGS are structured that way deliberately. Do not quietly delete a
  claim that turned out wrong — the fact that it was believed is itself evidence.
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
| `py-runner` | haiku | Any command whose output is verbose or token-heavy — test suites, builds, installs, indexing runs. Returns exit code, a terse verdict, failing ids and a temp-file path |
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
