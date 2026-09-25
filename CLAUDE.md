# Zikaron — project instructions

## What Zikaron is
**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") gives a coding agent the two kinds of
project knowledge that are not in its source code. **They are not interchangeable** (D1, as
amended; `design/knowledge-index.md` is normative for the second):

- **the memory store** — *tribal* knowledge: what nobody wrote down, because it was learned by
  living through the work — how to build and test, which steps fail silently, which env vars the
  integration tests need, what was already tried and how it failed. **The operational test governs
  this store**: *could you learn it by reading the code?* If yes, it is out of scope.
- **the knowledge index** — *institutional* knowledge: named corpora of files the project already
  wrote — docs trees, run books, design records — searched and returned as fragments with line
  ranges. **No authored content** — an agent creates, renames, refreshes and removes corpora, but
  nothing it writes becomes searchable text — so no write policy, no consolidation, and **no scope
  test**: it is whatever corpus somebody points it at.

## Project memory
`FINDINGS.md` is this project's **living working memory** — the decision index, where the work stands, and
what is still open. It is imported below, so it is in context every session. **Maintain it continuously**:
when state changes, edit it; when a section stops being live, move it to `FINDINGS-archive.md` rather than
letting this file sprawl. It is the thing a fresh session resumes from, and it is only worth that if it is
current.

**What belongs in it is narrow, and the test is: would a fresh session act differently without
this?** Four kinds do — a settled decision and where its rationale lives; where the work stands and
what is next; an open question with what would close it; and a measured fact that constrains a
choice, stated once, with the command that re-derives it.

**Everything else goes nowhere.** Not to the archive — nowhere. Specifically: how a defect was
found, what a sweep or review round covered, what an earlier version of a sentence said, how many
rounds something took, and any account of an agent's own mistakes. **A lesson that has become a
rule belongs in that rule and nowhere else** — once it is in `CLAUDE.md` or
`design/coding-standards.md`, the story behind it is a second copy that can only drift. Review
findings live in `reviews/`, measurements in `research/`, and the fix lives in the tree; none of
the three needs restating here.

`FINDINGS-archive.md` holds the finished record — build history, the milestone plan, dogfooding
evidence, references, the open questions that closed, and **every milestone block that has stopped
being live**. Read on demand. **Its own `##` headings are the index; never write a list or a range
of them here — that is a number every archive pass falsifies, in the one place nobody edits.**
**Read its §"Dogfooding notes" before proposing anything**: most of what a fresh session would
think to try has already been measured there, and several plausible ideas are refuted.
**"This file" inside a moved block means `FINDINGS.md`**, where that text was written; the archive
records what was believed and when, so moved blocks are not re-pointed.

@FINDINGS.md

## The design record
`design/` is normative. **`design/overview.md` is the entry point** — the system in one page and the full
decision table *with rationale*. FINDINGS.md carries a one-line index only; **never re-litigate a
settled decision from that index alone.** Read `overview.md` first.
**Never write the table's range here or in the row below** — a range is a number every new decision
falsifies, in the one place nobody edits when adding one.

| Document | Covers |
|---|---|
| **`design/overview.md`** | **Start here.** What we are building, the system in one page, provenance, and the full decision table with rationale |
| `design/schema.md` | v0 SQLite tables, the knowledge-base registry table, indexes, the retrieval-eligibility predicate and its per-consumer filter table, the `meta` initialization contract, bounds, 20 invariants (21 withdrawn), per-kind event shapes, linked sessions, what is deliberately absent |
| `design/architecture.md` | the components, RPC choice and rejections, request envelope (resolved and bootstrap forms), the two-rung session-label ladder and derived `label_source`, subagent-session push suppression, paths, filesystem security, lifecycle, degraded modes, both tool surfaces, two validation-precedence ladders, error table, distribution artefacts including the consolidator's model field |
| `design/retrieval.md` | the read path: hybrid fusion, push vs pull, fusion depth vs output budget, total order, query construction on both arms for external and internal queries, embedding, no reranker, supersession demotion, the known fusion defect |
| `design/indexing.md` | chunking contract: boundaries, gist-prepending, rollup, and §"Implementation constraints" — one transaction per mutation of indexed prose |
| `design/consolidation.md` | grouping mechanism and rejected alternatives, candidate construction, provisional parameter seeds and what they are not, consolidator identity and model, never-lose guard |
| `design/write-policy.md` | the `agentSpawn` prompt text, its rationale, the secrets and poisoning boundary, the operator erasure procedure, six instrumented signals, known gaps |
| **`design/build-plan.md`** | **Per-milestone briefs: scope, normative sections, invariants, done-when, scope fence.** Read the brief for the milestone you are on |
| **`design/coding-standards.md`** | **Binding.** Structure, domain model, typing, the test tiers, invariant tests, comment rules, dependency rules, the check gate, and the rules for bulk edits to prose in code |
| **`design/knowledge-index.md`** | **Normative.** The knowledge index: one SQLite file per knowledge base, the registry in `memory.db`, discovery and filtering, chunking, both index arms, grouped cross-KB search, the indexer process, the seven MCP tools and the CLI, K1–K13 and 16 invariants. `design/schema.md` still owns `memory.db`'s tables — including the registry — and `design/overview.md` every memory-store decision |
| **`design/distribution.md`** | **Normative for D35/D36**: supported platforms and what rules each out, acquisition (`uv` recommended, host Python supported) and why install-time only, publication by trusted publishing, **the `zikaron` front door and what `doctor` checks**, **model acquisition — the durable cache, the pinned revision and digest set, when digests are checked and why not on every start**, the version scheme and its artefact-shape rule, **what CI asserts and what it provably cannot** |
| **`design/harness.md`** | **The two supported harnesses as one table (D34)**: detection, session identity and its nesting limit, trigger and output-channel mapping, injection budgets, subagent rules, where D32's gating splits, consolidation ownership, the consolidator's model, and **the installer's two targets** — the value/shape split, the three flags and what each refuses |
| `design/prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across |
| `design/evaluation.md` | **Proposal, not normative.** The product claim as six links, three arms, why resolve rate is probably the wrong dependent variable, the benchmark landscape, the sample-size arithmetic |

Evidence is separated by kind and stays that way: **`research/`** measured results and literature notes,
**`reviews/`** review rounds, **`experiments/`** re-runnable harnesses, **`spikes/`** throwaway probes.

## Setting up a development environment

**Nothing here is in the repository, and none of it needs a Python already on the machine.** Run this
once per machine, in this order — the order matters, since step 3 has no interpreter to use until
step 2 has run.

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

After that, `./check.sh` and `./check-matrix.sh --parallel` both work with **no interpreter on
`PATH`** — only `uv`, which step 1 puts in `~/.local/bin`. `check-matrix.sh` asks `uv` for a
**managed** interpreter (`uv python find --managed-python --no-project`, both flags required — the
plain form answers with the project virtualenv), and that branch is guarded by `command -v uv`, so
`uv` being findable is not optional: without it the resolver falls through to a bare `python3.13`
that step 2's `--no-bin` ensures does not exist. A machine that already has a Python ≥ 3.12 it
would rather use for `.venv` can substitute `python3 -m venv .venv` for step 3; the matrix still
needs step 2.

**`--no-bin` is the part to get right.** Without it, `uv python install` puts a `python3.12` in
`~/.local/bin`, which on a normal `PATH` sits *ahead of* `/usr/bin/python3.12` and silently becomes
what every bare `python3.12` means — including for tools unrelated to this project.

**The managed interpreters live in `~/.local/share/uv/python/`**, which survives a reboot.
`.venv-matrix/<version>/` is built from them on first use, and rebuilt whenever `pyproject.toml`
changes or its base interpreter changes or disappears — so switching `ZIKARON_PYTHON_3_13` to a
different build, or letting `uv python upgrade` move the managed one, rebuilds rather than silently
reusing the old one. **Never point these at a scratchpad or `/tmp` path**: a virtualenv whose base
interpreter is deleted has a dangling `bin/python`, and `-m venv` run over it does *not* repair it.

## The check gate
**`./check.sh` is the gate for an ordinary edit and the definition of done for a change. Nothing is
finished until it exits 0.** `./check-matrix.sh` is additionally required before a milestone lands —
**and a pull request satisfies that requirement**, since `check.yml` runs `check.sh` once per
supported version against the commit, which is the matrix's own claim with the tree identity taken
from the SHA rather than from a fingerprint. So run the matrix locally when you want that answer
*before* pushing, not as a ritual before every PR; re-running it after each prose fix in a review
loop is waste, because the next edit invalidates the run anyway.
`check.sh` runs `ruff format --check`, `ruff check`, `mypy --strict` over **the package and the
tests**, then pytest with a coverage ratchet across **every** package under `zikaron/` — a test
asserts that list is complete — under a 600 s `timeout`. **Pass the Bash tool's maximum timeout
(600000 ms) when you run it**; the default kills it partway through the suite.

**Never start a gate while another is running.** Two on one tree share a coverage file, the tool
caches, `.venv-matrix/` and the editable install, and the second one's log redirect truncates the
first one's log. Check with `pgrep -af '[c]heck.*\.sh'` **in a command of its own** — put it in the
same command as the gate and it matches that command instead. Every project has a `check.sh`, so a
hit is only yours if `readlink /proc/<pid>/cwd` is this repository.

**CI is not a third thing to run.** `.github/workflows/check.yml` asserts the ***matrix's*** claim — every supported version
green on one tree — against a commit rather than a working tree, by running `check.sh` once per
version rather than by running `check-matrix.sh` at all. So it is the same claim with the tree
identity supplied by the SHA instead of by a fingerprint. **It is stronger on that axis and weaker on
another**: no live harness, so `integration_kiro` and `integration_claude` stay local-only and
nothing in CI exercises a real session pushing or searching. It also carries the matrix's deprecation
filters per job, because a job without them is green on a tree the matrix would redden.
`design/distribution.md` §"What CI asserts" is normative; `tests/test_ci_workflow.py` enforces it.

**It is hermetic, and deliberately so.** Three markers are deselected by `addopts` — `manual`,
`integration_kiro` and `integration_claude`. The latter two need a third-party harness binary
installed *and working*, which is somebody else's credential state rather than anything in this
repository. Run them by name when you mean to (`.venv/bin/pytest -m integration_kiro`). **Nothing
is covered only there**; the hermetic equivalents stub the binary through
`conftest.stub_harness_binaries`.
`design/coding-standards.md` §"five tiers" is normative.

**`check-matrix.sh` is the one deliberate exception to that hermeticity, and is a separate script
for exactly that reason.** It needs an interpreter per version it runs — a uv-managed one, an
explicit `ZIKARON_PYTHON_3_13`, or a bare `python3.<minor>` on `PATH` as the last resort — machine
state, which `check.sh` depends on nothing of. It builds a virtualenv per version under
`.venv-matrix/`. What it alone covers is the two version-dependent rows in
`zikaron/service/asyncio_compat.py`, each unexecuted on the versions that do not select it, plus
deprecations-as-errors. An absent interpreter is a **red** version, never a skip.
**Run it as `./check-matrix.sh --parallel`** — every version at once, about 3.5 minutes on a warm
tree, one result line. **Do not edit anything while it runs**: it compares the working tree before
and after and refuses if anything moved *anywhere*, so a review round appending to `reviews/` voids
the run — a refusal far broader than what the gate reads.
**What needs a matrix re-run is a change that can behave differently on one interpreter than
another — code, `pyproject.toml`, the scripts. Prose cannot**, so a documentation edit needs
`./check.sh` and nothing more. Note that `check.sh` *does* read much of the prose: the drift guards
parse `README.md`, `CLAUDE.md`, `FINDINGS.md`, `FINDINGS-archive.md` and the design corpus, so
"it's only a document" is never a reason to skip the gate.

**But the gate goes at the end of the editing, not after each edit.** A prose change cannot alter
`ruff`, `mypy` or coverage, and the guards that read it are a small subset of a **~330 s** suite —
the six files that parse the prose run in **~39 s**, an order of magnitude cheaper:

```bash
.venv/bin/pytest -q --no-cov tests/test_design_pointers_resolve.py tests/test_distribution.py \
  tests/test_publication_hygiene.py tests/test_markdown_renders_as_written.py \
  tests/test_definition_of_done_sites.py tests/test_quoted_design_prose_is_verbatim.py
```

**Iterate against that subset; run `./check.sh` once, when the editing is done.** Nothing here
relaxes the gate as the definition of done — what it forbids is spending a full suite per paragraph,
and then spending another because the next message changed the paragraph. **When a conversation is
still live, the edits are not done**, however finished a given one feels.

**Deriving that subset needs both halves, and a name-grep alone is wrong.**
`grep -rn '<filename>' tests/*.py` finds the guards that name the file, and **misses every test that
globs the corpus** — `test_quoted_design_prose_is_verbatim.py` reaches `FINDINGS.md` through
`REPO.rglob("*.md")` and never spells the name. Add `grep -rn -E 'rglob|glob' tests/*.py` and read
what the matches cover. A subset that is wrong about its inputs is worse than the slow suite,
because it is green for the wrong reason.

The formatter's output is authoritative: a `format --check` failure means running `.venv/bin/ruff
format .`, not adjusting the code by hand to satisfy it.

**Read `design/coding-standards.md` before writing any code.** It is binding.

## How this project works

- **Milestones, not tasks.** Work is scoped by a brief in `design/build-plan.md` (scope, normative
  sections, invariants to cover, done-when, and an explicit **scope fence**), lands as one commit, and
  leaves a review file behind. Work the lowest-numbered incomplete milestone; do not skip ahead.
- **Never commit to `main`, and never merge. The operator does both.** Not when the gate is green,
  not when a review reaches APPROVED, and not as a step inside some larger task that was asked for.
  The bullet above says a milestone "lands as one commit" — that describes what a milestone *is*,
  not permission to land it.
- **The one way work leaves this session is a pull request, and only when the operator asks for
  one.** Until then, staging, branching and reading history are what you may do. On that request:
  branch (`m<N>-<slug>` for milestone work, `<slug>` otherwise), commit, push, open the PR against
  `main`, then report and stop. **The PR is what makes CI run on the merge candidate** — the
  workflow triggers on `push`/`pull_request` to `main` only, so a branch push alone tests nothing
  and a green branch is not evidence.
  **One commit per PR.** Subsequent work on the same PR **amends that commit and force-pushes with
  `--force-with-lease`**, which updates the open PR in place and re-runs CI — never a stack of
  fix-ups, and never a second PR, which would abandon the review trail. Delete the remote branch
  after the merge.
  **`--amend` is permitted here and has exactly one hazard: amending onto a moved `HEAD`**, which
  folds your changes into whatever commit happens to be there and says nothing. So check first —
  `git rev-parse --short HEAD` against the commit you believe you are amending — every time, and
  never amend a commit the operator has merged.
  **The commit message follows the milestone style** (`git show 9e86cad`): a title naming what the
  work found rather than what it touched, led by `M<N>:` for milestone work, then prose paragraphs
  — what was discovered, what was decided and why, what was withdrawn. No bullet lists, no
  narration of the process.
- **Never set a release version in `pyproject.toml`.** Between releases the file carries a `.dev`
  suffix — `0.1.1.dev0` after `0.1.0` shipped — and the release number is set *only* in the commit
  that gets tagged, which is the operator's act. A PR that bumps `0.1.0` to `0.1.1` claims a release
  that does not exist, and a `git+` or checkout install then reports a version indistinguishable
  from a published one. When user-facing change lands and the next number is not yet decided, the
  `.dev` suffix is already doing its job and nothing needs bumping. `design/distribution.md` §3 is
  normative, and `release.yml`'s tag check refuses to build while the suffix is present, so it
  cannot survive a release by accident.
- **Never run a git command that discards uncommitted work.** Not `git checkout -- <path>`, not
  `git restore <path>`, not `git reset --hard`, not `git stash`, not `git clean`. Work is committed
  only at the moment a PR is asked for, so at any other time *everything* you have produced is
  uncommitted, and none of these has an undo you will find in time. **The trigger is tidying up, not a big dangerous
  operation** — reverting a probe line you just added takes the whole file with it.
  **Instead:** probe in a throwaway `git init` under the scratchpad, never in the repository; undo
  your own edit by re-editing the file; get a pristine copy with `git show HEAD:<path>` written
  somewhere else. **`git checkout` is for branches here, never for paths.** Staging, branching and
  reading history remain fine.
- **Pressure-test consequential work with the `self-review` skill** before finalizing a design doc, plan,
  spec, schema, or config. It delegates an independent critique to **memory-reviewer** and iterates to
  convergence. Reserve it for work that is expensive to get wrong — each loop spends extra cycles.
- **A green gate is not "ready for review". Sweep the class before you spawn a round.** A review
  round is the most expensive tool in this crew and a grep is nearly free, so a finding the grep
  would have produced is pure waste — and it is invisible from inside the loop, because every round
  still ends in a green gate and a tidy summary. Before spawning: grep every claim you changed **in
  all of its phrasings**, not the one you just edited; re-read every file you touched, at the scope
  the re-reading bullet below sets; mutation-verify every guard added since the last round — by
  running the mutation, not by describing it; and when a defect turns up in one caller of a shared
  helper, audit its **other** callers for the same class.
  **Grep locates candidates. It does not decide coverage.** A string search only finds sentences
  that resemble the one you edited, and the sentences that go stale are the ones that *followed
  from* it, which share none of its words. The check that works: **state the change as a
  before/after pair of propositions, write down what the old proposition licensed you to conclude,
  and decide for each conclusion whether it still holds.** Then read the passages about those
  subjects — by meaning, not by match.
  **For recovery, lifecycle or state-machine work, build the perturbation table and walk every cell
  before the first review round, not after the first blocker.** The axes are the ones the feature
  already names — where the process can be interrupted × what a human may change underneath it ×
  which values move and which do not. **Count the axes you actually named, and write no cell
  total** — a total drifts from its own predicate the moment either changes.
  **The tell that you have skipped this is in the brief you are writing**: if it asks the reviewer
  to check something you have the means to check, check it first and tell the reviewer what you
  found. **Narrating a rule is not running it** — writing well about a lesson feels the same from
  the inside as having applied it.
- **Measure before you assert.** Token counts, retrieval hit rates and end-task success are the
  currency; "it feels better" is not a result. **Name the quantity before quoting a number about it.**
  **A cost is measured under the condition its budget was set for, not under the one that is
  convenient** — a CPU-bound cost timed in an idle in-process loop understated one here by 2×, and
  the comparison that decides such a question is an A/B against a control on the same machine at the
  same load, never a figure from another day.
- **The documents carry current truth; the decision behind a change is recorded elsewhere.**
  `CLAUDE.md`, the agent definitions and everything in `design/` state what is believed **now** — a
  refuted sentence is replaced by the true one, deleted rather than struck. Three places already hold
  what a reader would otherwise need it for: `FINDINGS.md` §"Settled decisions", whose rationale is in
  `design/overview.md`; `FINDINGS-archive.md`, for what has stopped being live; and the commit
  message, which the pull-request bullet above already requires to say what was withdrawn.
  **None of that is licence to log the deleted sentence** — §"Project memory" above is unchanged, and
  what an earlier version of a sentence said still goes nowhere. What survives a deletion is the
  decision, never its old wording.
  **Strike the original and set the correction beside it only when the withdrawal is load-bearing** —
  when a reader who never saw the old claim would re-propose it, or would misread a decision that was
  taken *because* it was believed. A reversal on evidence usually qualifies; a wrong detail in a
  subordinate clause never does. **`design/overview.md`'s decision table is the standing case that
  qualifies** — its `Rationale` column is the audit trail for a decision the user took, and one that
  hides the claim it replaced cannot be checked against the evidence that replaced it. Do not strip
  that table under this rule. Everywhere else the cost is measured rather than stylistic: prose that
  exists to explain earlier prose is where this corpus's audit rounds found most of their defects
  (`FINDINGS.md` §"The audit loop"), so every struck sentence is both a paragraph each later reader
  must rule out and a fresh surface for the next one to be wrong about.
- **Edit *authored* files with `Read` and `Edit`/`Write`, never with find-replace scripts.** Do not
  edit them through `sed`, `python` string-replacement, heredoc rewrites, or any other script that
  mutates text you have not read in its current state. This **overrides** any ambient instruction to
  prefer shell tooling for file changes.
  The rule is about **mutating prose you have not read**. Read the passage, edit it, and for a
  multi-part change read the *whole* affected section rather than the lines you intend to match.
  **The one exception is a file whose bytes a program owns.** The golden installer output under
  `.kiro/` (§Harness) is **re-rendered** through `install/assets.py`'s own function —
  `skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION)` reproduces
  `skills/zikaron-consolidate/SKILL.md` byte-for-byte. Hand-typing those files is the defect there.
  **After any edit, grep for the *claim* you changed — not the phrasing you happened to replace —
  across the whole corpus rather than only the file you were editing.** A matched-once replacement
  proves you changed what you aimed at and nothing about the sentences around it, and an
  enumeration drifts across documents rather than only within one. Re-reading is the next bullet.
- **Re-read at a *handoff*, not after an edit — the trigger is what makes this rule work or fail.**
  "After an edit" has no event attached to it: `Edit` answers *updated successfully*, confirming the
  one thing never in doubt — that the string matched — while saying nothing about the sentences
  around it, so it reads as completion and attention moves to the next item. Worse, in a list of
  findings to apply, re-reading is not itself a finding, so it is never on the list being executed.
  **The trigger that holds is external: before spawning a reviewer, before running the gate, and
  before reporting work as done, re-read every file you have touched since you last did.** Whole
  file for anything you wrote from scratch or edited more than twice; the changed passage with its
  neighbours otherwise.
  **Prose you composed yourself is the case that most needs this and most resists it**, because
  reading it back confirms the intent you are still holding rather than the words on the disk — a
  new module's own docstring can contradict the code three screens below it and survive several
  review rounds. The same holds for a passage edited over and over, where confidence about what is
  in it peaks and accuracy does not: successive edits to one paragraph strand sentences the topic
  has moved past, push `Raises:` blocks into the middle of a docstring, and ravel the wrapping.
- **Comments explain measured reasons**, not intentions — and **the code is the product, not the
  commentary.** `design/coding-standards.md` §5 is binding: *why*, never *what*, and a comment must
  earn its place against the cost of being wrong later.
  **Do not read this codebase's existing commentary as a standard to match.** Much of it records
  what was observed to break, which is worth keeping; much more of it is narration added while
  fixing something, which is not. **Every comment is a claim that can go stale, and nothing in the
  gate compares it to anything.** **Adding a comment to explain a fix you just made is the single
  most reliable way to create the next defect.** Fix the code or the sentence; do not annotate the
  repair.
- **Dogfooding is a requirements source.** This is a coding agent with a memory problem working on
  the memory problem. When context loss makes you re-derive an established fact, or a handoff to a
  subagent goes badly, that is evidence about the product. **Act on it where it belongs**: change
  the rule, the prompt or the code it implicates, and put a measurement in `research/`. Do not
  write the incident into `FINDINGS.md` — §"Project memory" above says why.

## The crew
Four agent definitions in `.claude/agents/`. Three are subagents to delegate to rather than doing
their work inline; the fourth is the session you are probably in.

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
This project was built in **kiro-cli** and is being migrated to **Claude Code**. Three things follow:

- **`.kiro/` stays in the repository, and what "not to be edited" means depends on which kind of file
  it is.** It is the reference for what the shipped product still installs, and the fallback if the
  migration goes badly. `.claude/` is the live crew. **Five kinds of file live under `.kiro/` and
  the rule is not the same for all five:**
  - **Installer output** — `skills/zikaron-consolidate/SKILL.md`, `agents/zikaron-consolidator.json`.
    These are **golden files pinned by tests against what `install/assets.py` emits today**, so they
    are *supposed* to move when the shipped text does; a tracked copy that disagrees with the code is
    a **broken** reference, not a preserved one. Never hand-edit them — **re-render them through
    the installer's own function** so the bytes are whatever it would actually write, e.g.
    `skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION)`. The red test is asking "did
    you mean this?", not "you may not".
  - **Crew configs** — `agents/memory-*.json`, `agents/py-runner.json`. The kiro mirrors of
    `.claude/agents/`. **Editable**, per the operator, and worth keeping in step with their twins.
    Validate the JSON after any edit — these are one-line-per-field files where a stray quote is
    silent until an agent fails to load.
  - **`agents/zikaron-dogfood.json`** — a real installed config. **Its machine-specific parts —
    the virtualenv paths in `hooks` and `mcpServers` — are left alone**, since they describe one
    machine and the installer rewrites them. Its **prose** (`description`, `prompt`,
    `welcomeMessage`) is editable and should be kept true. Validate the JSON after any edit.
  - **Crew skills** — `skills/self-review/SKILL.md`, the kiro mirror of `.claude/skills/`.
    **Editable**, on the same terms as the crew configs, and worth keeping in step with its twin.
  - **`settings/lsp.json`** — gitignored, machine-local. Leave alone.
- **The clients and the installer all speak both harnesses.** The MCP server and the hook read trigger
  names, session variables, output channels and injection budgets through `zikaron/harness/` —
  the one seam, stdlib-only, where a harness difference is allowed to live. Add a harness difference
  *there*, **as data**, never as a branch downstream of it. The installer writes either
  harness's artefacts through `zikaron/install/targets.py`, which is the **only** place a difference
  may take a different *shape* rather than a different value; a value that migrates into a
  `HarnessTarget` method is the seam failing, and `design/harness.md` §"The installer's two targets"
  is normative for the split.
- **No Zikaron is installed into this repository**, by choice. **Do not assume Zikaron's tools or
  the push hook are live in this session.** To install it, `python -m zikaron.install --project .
  --harness claude-code`; `--harness auto` refuses here, since the repo carries both dotdirs.
