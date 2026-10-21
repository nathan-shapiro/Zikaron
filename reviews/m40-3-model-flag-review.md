# M40-3 — One model for every agent, and a flag for each — brief review

Artifact: `design/build-plan.md` §"M40-3 — One model for every agent, and a flag for each"
(lines 6881–6979 at round 1).

## Round 1 — 2026-10-20

**Summary judgment.** The brief is grounded in the code it changes: every claim I checked against
`zikaron/install/main.py`, `targets.py`, `writer.py` and `code_knowledge.py` holds (the `is None`
selection at `main.py:200–205`, the guards refusal running ahead of the `--print-only` branch,
`doctor/checks.py` importing `targets.claude_mcp_config`, kiro's `refuse_unknown_model` being a
membership test an alias fails, `accepts_agent_flag` as the abstract-property precedent), and the
normative list reaches every passage in the corpus that says what `--model` sets or where it is
refused — I found none it misses in `design/`, `README.md`, `CLAUDE.md`, `.claude/`, `.kiro/` or
`tests/fixtures/installed/`. D34's split is respected: the three flags are values, and
`ships_orchestrator` reads a difference of which files exist, which `design/harness.md` §"The
installer's two targets" assigns to the target. Two things stop it being buildable without a
decision: one invariant is false as stated for a plan the code can produce, and the brief gives a
line-count reason for a new module while leaving undecided the one addition that would grow the
file it is protecting.

### Findings

1. **[IMPROVEMENT] The `ships_orchestrator` invariant is false as written for a guards-only Claude
   Code plan.** Brief line 6954–6955: *"true exactly where `shipped_files` includes the
   orchestrator's definition"*. `ClaudeCodeTarget.shipped_files` (`targets.py:427–428`) returns
   `()` whenever `plan.components.memory` is false, so for a `guards` plan `shipped_files` includes
   no orchestrator while `ships_orchestrator` must answer true — the property is about the target,
   not about a plan, and the universal does not hold over plans. At runtime it never matters,
   because refusal 1 fires before the property is consulted; but the invariant is what the test is
   written from, and as stated it either fails on the first plan a builder happens to pick or gets
   quietly narrowed by the builder. Suggested text: *"**`ships_orchestrator` agrees with what the
   target writes for the memory store** — true exactly where `shipped_files` for a plan whose
   `components` include `memory` includes the orchestrator's definition (Claude Code's answering
   false; kiro's answering true)."* Naming both mutations also closes the "exactly" in both
   directions, where the brief names only one.

2. **[IMPROVEMENT] Item 4 leaves undecided where the three new `add_argument` calls live, and its
   own rationale turns on the answer.** Brief lines 6931–6934 put the resolution, both refusals and
   the model check in `zikaron/install/models.py` *"moving … out of `zikaron/install/main.py`,
   which is already past … roughly 400 lines"*. What that move removes from `main.py` is about 24
   lines (`_refuse_model_without_consolidator`, `_refuse_unknown_models`, the `ORCHESTRATOR_MODEL`
   import, the three `Plan` model lines); three parser entries in the style of the existing ones
   (`main.py:98–104`) add about 18 plus an import. So if the parser entries stay in `main.py` the
   file ends where it started, and the brief's stated reason for the module is not served by the
   module as described — which is exactly the kind of choice a builder then makes alone. Decide
   it in the brief, either way. Suggested text, appended to item 4: *"`models.py` also owns the
   parser's four model options — `--model` and the three — through one function `main.py`'s
   `_parser` calls, so the file the flags are about is the file that defines them and `main.py`
   grows by one line."* (Or, if the entries are to stay in `main.py`, say so and drop the
   line-count clause, since it would then be false as a motivation.)

3. **[NITPICK] "Decision: D34's split, unchanged — a value per agent, no new shape"** (line 6888)
   sits against item 2's *"the orchestrator is a difference of shape"* (line 6924) and the new
   `ships_orchestrator` property that reads it. Both are right; the sentence reads as if they were
   not. Suggested: *"— a value per agent, and no new shape: the one difference of shape it reads,
   whether a target writes an orchestrator, already exists and gains a property."*

4. **[NITPICK] The "before anything is written" half of the refusals invariant names no
   mutation.** Lines 6951–6953 give mutations for the two refusals' existence but none for their
   placement, which is the half `--print-only included` is about. The existing test pattern
   (`tests/test_install_components.py:343`, `_tree(project) == {}`) catches it; the brief's own
   rule is "each with the mutation". Suggested parenthetical addition: *"(… ; either refusal moved
   below `write_shipped_files`)"*.

5. **[NITPICK] The deduplication mutation is only red on an input where models coincide.** Line
   6957: *"(the deduplication dropped; …)"*. Under Claude Code's defaults the three models are
   distinct (`sonnet`, `haiku`, `opus`), so dropping `dict.fromkeys` changes nothing and the test
   stays green; the mutation is red only with `--model x` (all three the same) or under kiro's
   defaults (`claude-sonnet-5` twice). Say which: *"(the deduplication dropped, seen with `--model`
   given so the three coincide; …)"*.

6. **[NITPICK] The rename reaches the snapshot renderer, not only the three uses the brief counts.**
   Item 1's `Plan.model` → `Plan.consolidator_model` also touches every `Plan(` constructed in
   `tests/install_snapshots.py:35`, `tests/test_install_writer.py:76`, `tests/test_install_targets.py:188`
   and `:1823`. `mypy --strict` finds them, so nothing is at risk; but the invariant at line
   6959–6960 says the snapshots "do not move … as it stands", and a builder may read that as the
   renderer being untouched. Suggested: *"— the fixtures under `tests/fixtures/installed/` do not
   move, though the renderer `tests/install_snapshots.py` follows the rename."*

7. **[NITPICK] "The defaults already differ per agent"** (line 6895) is true under Claude Code only;
   kiro's consolidator and documenter both default to `claude-sonnet-5` (`spec.py:268–269`).
   *"may already differ per agent"* or *"differ per agent under Claude Code"*.

Checked and found sound, so not raised: the scope fence; the normative list (no other passage in
the corpus states what sets an agent's model — `architecture.md`'s install-contract table and
`distribution.md`'s front door do not name the flag); the precedence rule and its `is None`
handling, including the empty-value path under a real install; the refusal order against
`_refuse_unoffered_guards`, so no command line reaches two refusals; the kiro `ORCHESTRATOR_MODEL`
exclusion from the check; the kiro-gaps placement; and the in-tree build, since nothing outside
`zikaron/install/` imports it but `doctor` and the lazy `zikaron install` dispatch.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-20

**Summary judgment.** All seven round-1 findings are applied as suggested, and the brief now
reads as one a builder can execute without a decision of their own on the code side: I re-checked
every claim against `main.py`, `targets.py`, `writer.py`, `code_knowledge.py`, `spec.py`,
`cli/main.py` and `doctor/checks.py` (the `is None` selection, the guards refusal running ahead of
the `--print-only` branch, the two Claude Code defaults and kiro's shared one, the regex refusing an
empty id, the lazy subcommand loading that makes the in-tree build safe, the absence of any module
enumeration a new `models.py` would have to join) and found none false; every invariant now names a
mutation a test can be seen red against. What remains is on the document side: the one new refusal
the milestone creates — `--orchestrator-model` under a target that ships no orchestrator — has a
normative home named in the brief's `Normative:` line but no done-when clause that compels the
sentence into it, so done-when 2 as written is satisfiable with that section carrying no mention
of the refusal.

### Findings

1. **[IMPROVEMENT] Done-when 2's predicate does not reach the kiro refusal, so the design record
   can end the milestone without the sentence that governs it.** Brief lines 6972–6976 bind two
   facts — what sets an agent's model, and which flags `--components guards` refuses — and the
   normative line (6883–6884) names `design/harness.md` §"The flags, and what each refuses", whose
   existing bullets (harness.md:660–686) are exactly the per-flag refusal list. Applying the
   predicate to that section yields only "any model flag under `guards` is refused"; nothing
   compels a bullet saying `--orchestrator-model` is refused where the target ships no
   orchestrator, and why. `main.py`'s own docstring (lines 3–4) says a refusal's normative home is
   `architecture.md`'s contract for the shared part and `harness.md` for what varies, and this one
   varies by target — so a build that satisfies the brief as written leaves a refusal the code
   performs with no normative sentence, which is the drift class the prose guards exist for.
   `design/kiro-gaps.md`'s row (item 5, line 6941–6942) does not cover it: "Closing it takes" says
   kiro lacks the flag, not that the installer refuses it. Suggested, two edits: in item 5, after
   "the passages in the normative list", add *"— `design/harness.md` §"The flags, and what each
   refuses" gaining a bullet for the three flags, the agent each sets, and `--orchestrator-model`
   refused under a target that ships no orchestrator, as `--agent` is under Claude Code"*; and in
   done-when 2, after "names the agent's own flag beside `--model`", add *", and `design/harness.md`
   §"The flags, and what each refuses" states the refusal of `--orchestrator-model` where no
   orchestrator ships"*. (If the kiro-gaps row is meant to carry the flag as part of what exists
   rather than only what closing it takes, say "in what Claude Code has and in what closing it
   takes"; as written a reader scanning the "Under Claude Code" column will not find it.)

2. **[NITPICK] The rename strands the `Plan` field comment, which nothing in the brief reaches.**
   `writer.py:128–129`, the `#:` comment over `documenter_model`: *"The code documenter's and
   Claude Code's code orchestrator's; `model` is every other agent's."* After item 1's
   `Plan.model` → `Plan.consolidator_model` it names a field that no longer exists, and "every
   other agent's" is one agent. `mypy` does not read comments, and done-when 2's predicate is
   "what sets an agent's model", which this comment does not say. Suggested, appended to item 1's
   last sentence: *"…and none reads as `--model`; the `#:` comment over `documenter_model` that
   says `model` is every other agent's goes with it."*

3. **[NITPICK] Two of the model-check mutations are red only on an input the parenthetical does
   not name.** Line 6961–6964: *"(the deduplication dropped, seen with `--model` given so the three
   coincide; the orchestrator's left out under Claude Code; the orchestrator's checked under
   kiro)"*. The first mutation's qualifier is right; but on that same input — `--model x`, three
   equal — *leaving the orchestrator out under Claude Code* still yields one check, so that
   mutation stays green there and is red only where the orchestrator's model differs from the
   other two (the defaults, `sonnet`/`haiku`/`opus`, or an `--orchestrator-model`). A builder
   reading the qualifier as governing the list writes one test and sees one of three mutations.
   Suggested: *"(the deduplication dropped, seen with `--model` given so the three coincide; the
   orchestrator's left out under Claude Code, seen at the defaults, where the three differ; the
   orchestrator's checked under kiro, seen at the defaults, where the two coincide)"*.

4. **[NITPICK] The in-tree-build enumeration omits the planner, the one process a live run
   executes with nobody typing it.** Lines 6903–6907 list the hook, the guard, the MCP server, the
   service and the indexer, plus `doctor`; LeibaTrader's orchestrator runs `zikaron code-knowledge
   plan` mid-run, and that is the case a reader of this paragraph would ask about. I verified the
   claim holds for it — `zikaron/cli/main.py` loads each subcommand only when it is the one being
   run, and `zikaron/code_knowledge/` imports nothing from `zikaron/install/` — so this is
   completeness of the sentence, not a defect in the decision. Suggested: *"the hook, the guard,
   the MCP server, the service, the indexer and the planner import nothing from
   `zikaron/install/`"*.

Checked and found sound, so not raised: the Decision sentence's reconciliation of "no new shape"
with the `ships_orchestrator` property, which `design/harness.md` §"The installer's two targets"
and its line 339–341 ("no `HarnessSpec` field, since no other harness ships one") together
license; the precedence rule including the empty-value path under both harnesses (the regex needs
one character; kiro's membership test fails on `""`); the refusal order, where kiro + `guards` is
taken by `_refuse_unoffered_guards` before either new refusal and no other command line reaches
both; item 4's line-count rationale now that the parser options move too; the normative list,
which still reaches every passage in `design/`, `README.md`, `zikaron/` and `tests/` that says what
`--model` sets (architecture.md's contract table and §"The consolidator's model is a shipped config
field" name no flag; `distribution.md` enumerates no install flags; no test binds the README's
options table to the parser); the snapshot invariant against `tests/install_snapshots.py:38`; and
the scope fence.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-20

**Summary judgment.** All four round-2 findings are applied as suggested and none of the edits
introduced drift: item 5 now has `design/harness.md` §"The flags, and what each refuses" gain the
per-flag bullet and the `--orchestrator-model` refusal, done-when 2's new last sentence compels it
there while the exemption still governs only the first sentence, the `#:` comment is retired in
item 1, each model-check mutation names the input that reddens it, and the in-tree paragraph names
the planner. I re-read the brief whole (lines 6881–6992) against `main.py`, `targets.py`,
`writer.py`, `code_knowledge.py`, `spec.py`, `cli/main.py` and `doctor/checks.py`, and against
every document the normative line names at the sections it names — `code-knowledge.md` line 447
is in §5.1 and lines 664–728 in §5.4 (headings at 382 and 645), `guards.md` §5's bullet at 601,
`harness.md`'s last paragraph of §"The consolidator's model" at 337–341, the README table at
541–551, the kiro-gaps row at line 23 — and found no claim false and no passage the list misses:
no decision row in `overview.md` and nothing in `architecture.md` or `distribution.md` says what
sets an agent's model by flag. The brief is buildable without a decision of the builder's own;
what remains is two trivia.

### Findings

1. **[NITPICK] `design/code-knowledge.md` §5.4's enumeration paragraph attributes the help and the
   refusal to `main.py`, which item 4 moves.** Line 726–728: *"`main.py`'s `--model` help and its
   refusal of `--model` under `--components guards`"*. The normative line names this paragraph and
   done-when 2 reaches it by meaning, but its predicate — *names the agent's own flag beside
   `--model`* — is satisfiable with `main.py` left standing as the file, and nothing in the gate
   resolves a backticked file name (`test_design_pointers_resolve.py` reads `§` pointers only; no
   test scans `install/main.py` by name). Suggested, appended to item 5's first sentence: *"…as
   `--agent` is under Claude Code, and `design/code-knowledge.md` §5.4's paragraph on the prose
   that enumerates an install naming `models.py` as where the help and the refusal now live"*.

2. **[NITPICK] The retired `#:` comment is two lines, and the second is the one that goes stale
   differently.** `writer.py:128–129`: *"The code documenter's and Claude Code's code
   orchestrator's; `model` is every other agent's. Kiro ships no orchestrator and ignores its
   model."* Item 1 names the comment by its first sentence; after item 2 kiro *refuses* the
   orchestrator's flag rather than ignoring it, so a builder who strips the first line and keeps
   the second leaves a sentence that contradicts the refusal beside the field it describes.
   Suggested: *"the two-line `#:` comment over `documenter_model`, which says `model` is every
   other agent's and that kiro ignores the orchestrator's, goes with it"*. (Relatedly, and
   optional: `design/kiro-gaps.md` line 25's "Closing it takes" for the Haiku row could add that a
   kiro user may pass `--documenter-model <id>` the day the list offers one, before the default
   moves — the flag is the first thing a reader of that row would reach for.)

Checked and found sound, so not raised: the Decision sentence; the precedence rule with the
`is None` handling and the empty-value path on both harnesses, under a real install and under
`--print-only`, where the shape check degrades to a note as it does today; the refusal order
(`_refuse_unoffered_guards` takes kiro + `guards` first, so no command line reaches two of the
new refusals); the `ships_orchestrator` property as a shape in `targets.py` under `harness.md`
§"The installer's two targets" and its line 339–341, with `accepts_agent_flag` as the precedent;
item 4's `models.py` against the import graph (`targets` → `writer`/`code_knowledge`/`entries`,
none importing back, so `main` → `models` → `targets` is acyclic) and against the corpus — neither
`design/coding-standards.md` §1's tree, which lists `install/` as a directory, nor
`zikaron/install/__init__.py` enumerates modules, so a new module joins no list; the in-tree
build, since only `doctor/checks.py` and the lazy `zikaron install` dispatch import from
`zikaron/install/` outside it, and `zikaron/code_knowledge/` imports none of it; every invariant's
mutation now reddening a test on the input it names, including the three model-check mutations at
the defaults (`sonnet`/`haiku`/`opus` give three checks, `claude-sonnet-5` twice gives one); the
snapshot invariant, since no fixture under `tests/fixtures/installed/` carries `--model` text; and
the scope fence.

VERDICT: APPROVED
