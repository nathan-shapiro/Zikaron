# Review — M40-6: a test absence wider than the search behind it, and a harness block read as the file's

Artifact: the brief (`design/build-plan.md` §M40-6) and the build — `zikaron/install/code_knowledge.py`
(`DOCUMENTER_PROMPT`, the Claude Code skill's Permissions section), `design/code-knowledge.md` §4, §5.1,
§5.2, `README.md` §"Code knowledge", `tests/test_install_code_knowledge.py`, the re-rendered snapshots
under `tests/fixtures/installed/`, `research/m40-toy-run.md` §17 and §18 — as the working tree stands
against `9455d52`.

## Round 1 — 2026-10-30

**Summary judgment.** The build does what the brief says, and the two prompt rules clear the bar for
a prompt: each names what to write, what never to write, and why, in words a Haiku documenter can act
on without a tool name, and §18 measures the one wording that mattered against the one it replaced.
All three snapshots carry both phrases, the tests pin each rule by a phrase a rewording would lose,
and the research note is honest about its sample. What keeps it short of APPROVED is prose that
*followed from* the propositions this milestone changed and was not re-read for them: two provenance
sentences now false, the interactive-permissions paragraph that assumed the planner's command was the
orchestrator's first shell call, a headless recipe documented in a form slightly different from the
one that was run, and the "read none" branch of the new rule, which has no example and no
measurement although it is the common case in a real module.

### Findings

1. **[IMPROVEMENT] Two provenance claims are now false.** `design/code-knowledge.md` §5.1 line 482:
   *"Its prompt's final wording is memory-reviewer's, written at build time from this section, as
   D38's prompt texts were."* and `zikaron/install/code_knowledge.py` lines 10–11: *"Its wording is
   memory-reviewer's (`design/build-plan.md` §M40 item 2)."* The brief (line 7621) says M40-6's wording
   is the author's, and the Behavior bullet, the Rules bullet's permitted absence and the harness-block
   rule are now the author's text. A normative document stating the wrong author for a shipped prompt
   is exactly the kind of sentence `CLAUDE.md` §"re-read at a handoff" is about. Suggested edits:
   §5.1 — *"Its prompt's wording is memory-reviewer's as of M40, written at build time from this
   section as D38's prompt texts were; M40-6's test-absence and harness-block rules are the author's,
   held to that bar in review (`design/build-plan.md` §M40-6)."* Docstring — *"Its wording is
   memory-reviewer's (`design/build-plan.md` §M40 item 2), less M40-6's two rules, which are the
   author's."* The earlier briefs' statements (`build-plan.md` lines 6327, 7213) are what was decided
   then and can stand.

2. **[IMPROVEMENT] The interactive-permissions paragraph followed from the proposition item 5
   refuted, and was not updated.** `README.md` lines 803–806, the skill's Permissions
   (`code_knowledge.py` lines 583–586, hence the SKILL.md snapshot) and §5.2 lines 682–685 all say an
   interactive session *"is asked to approve the planner's command when it first runs … and the
   first document a documenter writes"*. The headless refusal in §18 shows the orchestrator's first
   shell call is `pwd -P && cat .mcp.json`, and §5.2 line 682 says the install pre-approves *"no
   shell command"*, so under `default` permission mode the user is asked for that command before the
   planner's. The paragraph is true only under auto mode, which is the only mode the interactive
   measurements ran under (`research/m40-5-spawned-orchestrator-probe.md` §2a). Suggested edit, at all
   three sites, then `python -m tests.install_snapshots`: *"… is asked to approve the shell command
   the orchestrator finds the project root with, then the planner's command when it first runs — and
   at later batches unless the user allows it for the session — and the first document a documenter
   writes"*, with §5.2 adding that the first of those follows from §18's headless refusal rather than
   from an interactive measurement.

3. **[IMPROVEMENT] The documented headless recipe is not the one that was run.** `research/m40-toy-run.md`
   §18 line 671: the two runs that reached `up_to_date` carried `--permission-mode acceptEdits` *and*
   `--allowedTools`. `README.md` lines 809–816, §5.2 lines 698–707 and the skill document
   `--allowedTools` alone, in the default mode, and §5.2 line 706 cites §18 for *"with them two runs went
   to `up_to_date`"*. The difference is whether `Write`/`Edit` in `--allowedTools` suffices for the
   documenters' writes without the mode; it should, but the brief's intent is a documented list *"that
   works"*, and this one is inferred, not run. Either of two one-line fixes: (a) re-run one of the two
   regenerations with the documented list and no `--permission-mode` (about $0.20 by §18's figures)
   and record it in §18; or (b) §18 states that the file-tool allow rules were beside `acceptEdits`
   and the list without the mode is inferred, and §5.2's citation says the same. (a) is preferred,
   since it costs less than the review round that would otherwise re-raise it.

4. **[IMPROVEMENT] The "read none" branch has no form, and the brief's own evidence says an
   un-exampled form drifts.** `DOCUMENTER_PROMPT` lines 199–200: *"and where you found no test to read,
   it says you read none."* The scoped absence gets a quoted form and a forbidden form; this branch
   gets neither, and *"it"* has no clear antecedent (*every sentence saying so*? the document?). §18's
   first row shows what happens to the un-exampled case: 6 of 16 bare, 0 of 10 by path. Both
   documents §18 regenerated had test files, so this branch is unmeasured — and in a real module it
   is the common case, since most sources have no test file at all. The likely drift is *"No tests
   exist for this file"*, which the Rules bullet (line 242) forbids and which is the whole-project
   claim the milestone exists to remove. Suggested edit, wording the author's: give the form and its
   place — e.g. *"— and where you found no test to read, Behavior says so once, at its start —
   *"No test file was read for this file"* — and no behavior then names a test"* — then add the
   phrase to `TestThePromptCarriesTheSpecsRules` and see it red. `README.md` needs nothing; §4's
   *"or that it read none"* already covers it.

5. **[IMPROVEMENT] §4 does not carry the path-from-root requirement or the measurement that forced
   it.** `design/code-knowledge.md` §4 lines 368–370 says the absence names the files read, *"naming
   them"*; §5.1 line 422 says *"no test in the files it read"*. The prompt's *"by their paths from the
   root"* rests on §18's finding that under the softer wording the 10 files named were all bare file
   names, and the design records neither the requirement nor the evidence. A later editor trimming the
   prompt — *"the general rule that every path is relative to the root already covers it"* — would
   reintroduce the drift with nothing in the normative text to stop them. Suggested edit to §4's
   bullet, after *"naming them"*: *"by their paths from the root — under a wording that did not say
   so, every test file named was a bare file name (`research/m40-toy-run.md` §18) —"*.

6. **[NITPICK] Done-when 2's "each" against §18's 17 of 18.** `research/m40-toy-run.md` §18 line 684
   counts one sentence, *"No test covers that either"*, as *"scoped by the sentence before it"*;
   `FINDINGS.md` line 93 says *"17 of 18 absences scoped"*; the brief's done-when 2 (line 7678) says
   *each* absence names its files or says none was read. The reader is left to decide whether the
   done-when is met. Say so in §18 — that the done-when is read as met with a sentence scoped by its
   predecessor, or that it is met in 17 and the 18th accepted as English rather than drift — so the
   next reader does not re-derive the judgment.

7. **[NITPICK] The relay is attached to the wrong case.** Brief lines 7636–7637: *"(`roles.md` in the
   probe; 1 answer of 407 in §17, which the orchestrator relayed to the user as a file to check)"*
   attaches the relay to §17's headless run, whose note records no relay; the hand-back the operator
   read was the probe's interactive one (`research/m40-5-spawned-orchestrator-probe.md` §2, lines
   63–65). §5.1 line 443's *"once relayed to the user"* names neither. Attach the relay to the probe's
   case in both.

8. **[NITPICK] `pwd -P && cat .mcp.json` is described as what the orchestrator does, where it is what
   it chose.** `README.md` line 812, the skill (line 589) and §5.2 line 705 state the command as the
   orchestrator's first call; its prompt (`CLAUDE_CODE_PLANNER_COMMAND`) asks only to open `.mcp.json`
   in the directory it was started in, and the command is the model's choice in three runs. The fence
   keeps the command; the description can still say *"has found the project root with"* or *"in every
   measured run"*, so a user whose headless run is refused on a different command knows the list was
   derived from observation and what to add.

9. **[NITPICK] Brief grammar.** Line 7667–7668: *"each phrase one a rewording that drops the rule would
   remove"* — read as *"each phrase one that a rewording dropping the rule would remove"*.

**Checked and not raised.** The three snapshots carry both phrases (`claude-code/agents/zikaron-documenter.md`
lines 109 and 169; `kiro/agents/zikaron-documenter.json` line 6; the SKILL.md snapshot line 61);
`test_no_sentence_asks_for_a_test_absence_over_the_whole_project` would go red on the old *"no test
covers it"* and on a deleted forbidden form, taken with the phrase test; the harness-block rule does not
conflict with the rule that everything in a file is the file's, since it is scoped to what arrives
*beside* a read, and it does not tell the documenter to ignore the harness, which would be wrong;
`FINDINGS.md`'s Owed-work entry for the two fixes is gone and the resume block names M40-6; §8 Known
gaps carries nothing this milestone closes; the `--allowedTools` list appears at exactly the three
sites the brief names; `Bash(cat:*)` grants nothing `Read` does not already.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-30

**Summary judgment.** All nine round-1 findings are applied as the brief says, and I confirmed each
against the files rather than the brief: the two provenance sentences are true again, the
interactive paragraph names the root-finding command before the planner's, §4 carries the
path-from-root requirement with §18's evidence, the read-none form has a quoted sentence, a place
and three test phrases, run 4 used the documented list with no `--permission-mode` and reached
`up_to_date`, and the relay is no longer attached to §17. The prompt's two new rules clear the bar
in isolation. What keeps this short of APPROVED is four small corrections, none an edge case: the
prompt's Rules bullet still says a search may state *one* absence where Behavior now asks for two;
the sentence in §18 that justifies done-when 2 says the wording does not demand a path in every
sentence when the prompt's wording does exactly that; the user-facing `--allowedTools` list still
leaves the planner rule's form to be guessed, and the natural guess is one the orchestrator never
matches; and `FINDINGS.md`'s release-note plan says nothing Claude Code users install has changed,
which M40-6 itself falsified.

### Findings

1. **[IMPROVEMENT] Rules and Behavior disagree on how many absences a search may state.**
   `zikaron/install/code_knowledge.py` lines 246–247: *"the one absence a search may state is the
   one Behavior asks for, that no test in the files you read covers a behavior."* Behavior (lines
   197–201) now asks for two: the scoped per-file absence and the read-none opener *"No test file
   was read for this file."* — itself an absence a search produced. The brief (line 7647) asserts a
   parity that does not hold: *"The Rules bullet's one permitted absence says the same."* §5.1 line
   424–425 mirrors it: *"the one absence a search states being §4's, that no test in the files it
   read covers a behavior"*, while §4 names both forms. Run 4 shows the gap in use: with no
   sanctioned read-none form in Rules, `blockgrid_element.rs`'s documenter added a third form, a
   sentence about its search (§18 lines 698–700), which Rules' *"what you could not find goes
   unsaid"* forbids and Behavior does not mention. Suggested edits, wording the author's: Rules
   bullet — *"the absences a search may state are the two Behavior asks for: that no test in the
   files you read covers a behavior, and, once at Behavior's start, that no test file was read"* —
   which keeps the test phrase at `tests/test_install_code_knowledge.py` line 416 intact; §5.1 —
   *"the absences a search states being §4's two"*; brief line 7647 — *"The Rules bullet's
   permitted absences are the same two."* Then `python -m tests.install_snapshots`. Whether the
   opener may also name what was searched for, as run 4's did, is the author's call; the point here
   is that the two sections should agree.

2. **[IMPROVEMENT] §18's justification of done-when 2 misstates the prompt.**
   `research/m40-toy-run.md` lines 692–695: *"The path is not repeated in every sentence, and the
   wording does not demand it be."* The prompt's wording does demand it — *"every sentence saying
   so names the test files it is about, by their paths from the root"* (`code_knowledge.py` lines
   197–198); only done-when 2's wording does not. As written the sentence hides a measurement the
   table shows: the shipped wording met the prompt's literal rule in 6 of 11 sentences in run 4
   against 17 of 18 under run 3's, one run each. The read-none paragraph (lines 697–700) has the
   same gap in the other direction: it reports that `blockgrid_element.rs` placed the sentence as a
   later bullet, not first, and does not say whether that counts. Suggested edit: *"done-when 2's
   wording does not demand it; the prompt's *every sentence* does, and run 4 met that in 6 of 11
   against run 3's 17 of 18 — one run each, so no difference is claimed — and the shortfall is
   accepted because a reference to a path just given is not a claim about the project. The
   read-none opener's place bound in 1 of 2; done-when 2 asks for the statement, not its place."*
   This is the sentence the next editor reads to decide whether *every sentence* is doing work, so
   it should be true of the prompt.

3. **[IMPROVEMENT] The documented `--allowedTools` is not writable from the README: the
   planner rule's form is left to be guessed, and the natural guess does not match.** `README.md`
   lines 811–815 and `design/code-knowledge.md` §5.2 lines 708–709 say *"`--allowedTools` naming the
   planner command"*. §18 line 675 gives the form that worked — `Bash(<venv>/bin/zikaron
   code-knowledge plan:*)`, an absolute path — and the loop (`code_knowledge.py` lines 353–355)
   forbids the orchestrator a `zikaron` on `PATH`, so the rule a user would naturally write,
   `Bash(zikaron code-knowledge plan:*)`, is a prefix the command never has, and the first planner
   run is refused: the same failure item 5 just fixed for `pwd`/`cat`, on the next command. The
   README also says *"the subagent and skill tools"* where §18 names `Agent` and `Skill`, and the
   README already names `Grep` and `Glob` (line 833), so naming them is in its register. Suggested
   edit at both user-facing sites, leaving the skill — model-facing — and its snapshot alone:
   *"`--allowedTools` naming the planner command by the path the orchestrator runs it with —
   `Bash(<venv>/bin/zikaron code-knowledge plan:*)`, never a bare `zikaron`, which it does not use —
   `Bash(pwd:*)`, `Bash(cat:*)`, `Agent`, `Skill`, the file tools and `mcp__zikaron`"*. The text
   predates M40-6, but item 5's intent is a documented list that works, and this is the one element
   of it a reader cannot get right from the page.

4. **[IMPROVEMENT] `FINDINGS.md`'s release-note plan was falsified by this milestone.** Lines
   78–80: the `0.4.1` note tells *"Claude Code users that upgrading is enough, since nothing they
   install has changed since `0.4.0`"*. M40-6 changes `DOCUMENTER_PROMPT` and the Claude Code
   skill's Permissions, and both are written into the project at install time —
   `tests/fixtures/installed/claude-code/agents/zikaron-documenter.md` is the file an install
   leaves, prompt and all — so a Claude Code user who only upgrades the package keeps the old
   prompt. The sentence followed from the tree before M40-6 and ships in this pull request; a fresh
   session writing the note would act on it. Suggested edit: *"and Claude Code users to re-run the
   installer too, since M40-6 changes the documenter's prompt and the skill, which the install
   writes into the project."*

5. **[NITPICK] The document-write clause lacks the qualifier the planner clause carries.**
   `README.md` lines 806–807, `design/code-knowledge.md` lines 689–690, `code_knowledge.py` lines
   587–588 (hence the SKILL.md snapshot lines 58–59): *"and the first document a documenter
   writes"*. The planner's clause says *"at later batches unless the user allows it for the
   session"*; the write's does not, and §5.2 line 690–692 says no interactive measurement ran
   under default mode, so *"the first"* is inferred, and holds only if the user allows edits for
   the session — otherwise each documenter's write asks. Suggested, at the three sites then the
   snapshot: *"— and a documenter's document write, each one unless the user allows edits for the
   session"*. Carried forward from earlier text; one clause.

**Checked and not raised.** The three snapshots carry the shipped `DOCUMENTER_PROMPT` and skill
text byte for byte against the module; the eight new phrases in `TestThePromptCarriesTheSpecsRules`
each pin a sentence a rewording would lose, and `test_no_sentence_asks_for_a_test_absence_over_the_whole_project`
still counts the bare form once; the module docstring and §5.1 line 485–487 state the provenance
correctly; `research/m40-5-spawned-orchestrator-probe.md` lines 63–70 support both *"beside a
subagent's first tool result"* and the `roles.md` attribution, and the brief's and §5.1's citations
now point there; §4 lines 368–374 match §18's row 2 (0 by path, 10 short names, 6 bare); run 4's
`Bash(pwd:*)`/`Bash(cat:*)` against the compound `pwd -P && cat .mcp.json` is measured, not
inferred; `tests/test_code_knowledge_claude_live.py` runs under `bypassPermissions`, so §5.2's
*"runs the shape end to end"* is unaffected by the list; the provenance sweep's remaining hits
(`design/guards.md` line 1294, `design/build-plan.md` lines 6327 and 7213, `design/overview.md`
D38) are about other prompts or earlier decisions and stand; the `FINDINGS-archive.md` §"M41-2 as
built" heading exists and the resume block names M40-6 and its plan; the fence's exclusions are
respected; §18 records the harness version, the models, the effort levels and the cost per run,
and says its sample is small.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-30

**Summary judgment.** All five round-2 findings are applied, and each was checked against the
files: Rules and Behavior now name the same two absences, §5.1 and the brief agree with them, §18's
done-when paragraph is true of the prompt's *every sentence* and gives the 6-of-11 against 17-of-18
with the shortfall accepted, README and §5.2 give the planner rule by its path and name `Agent` and
`Skill`, the release-note plan tells every user to re-install, and the document-write clause carries
its qualifier at all three sites. The harness-block rule clears the prompt bar outright. What keeps
this short of APPROVED is one defect in the prompt under the bar the operator asked for — the
read-none opener's condition is *"found no test file to read"*, which a source holding its own tests
satisfies, so the rule tells a documenter to open a tested Rust file's Behavior with *"No test file
was read for this file."* and then name none of them — plus a normative sentence §18 falsified, and
done-when 2's truth clause met on the shipped wording for 1 absence of 11.

### Findings

1. **[IMPROVEMENT] The read-none opener fires on a file that holds its own tests, and then forbids
   naming them.** `zikaron/install/code_knowledge.py` lines 199–201: *"Where you found no test file
   to read, Behavior opens by saying so, once — "No test file was read for this file." — and no
   behavior after it says anything of tests."* A Rust source with `#[cfg(test)] mod tests { … }` at
   its foot — the language's default idiom, and the language the evaluation corpus is in — has no
   test *file*, so the condition holds literally; the opener is then true in words and false in
   effect (a reader takes the file as untested), and *"no behavior after it says anything of tests"*
   contradicts the bullet's own first sentence, *"Each behavior says whether a test pins it: the
   test's name where one does."* The prompt leaves a Haiku documenter to pick one; §18's two
   read-none sources had *"no test module, no sibling test file"*, so the inline case is unmeasured.
   Suggested edit, wording the author's: make the condition exclude a source with tests of its own —
   e.g. *"Where you found no test file to read, and the source holds no tests of its own, Behavior
   opens by saying so, once …"* — and say what an absence sentence names in the inline case, which
   the scoped form already implies: the source's own path, *"No test in `src/a/x.rs` covers this"*.
   Then the same clause in `design/code-knowledge.md` §4 line 370 (*"or, once at Behavior's start,
   that it read none"*), §5.1 line 426 (*"and, once, that it read no test file"*) and the brief's
   item 1 (`design/build-plan.md` lines 7645–7646), and `python -m tests.install_snapshots`. The
   phrase test's three read-none phrases survive the edit as suggested.

2. **[IMPROVEMENT] A §5.2 sentence this milestone's own measurement falsified.**
   `design/code-knowledge.md` line 708: a headless run passes `--permission-mode
   bypassPermissions` — *"every headless experiment in this corpus's precedent"*. §18's four runs
   are headless experiments in this corpus, three under `acceptEdits` and one under `--allowedTools`
   alone, and the same paragraph cites §18 nine lines later. Suggested edit: *"every headless
   experiment before §18's"* — or drop the clause, since §1 line 17 already shows the form.

3. **[IMPROVEMENT] Done-when 2's truth clause is met on the shipped wording for 1 absence of
   11.** Brief line 7682–7683: *"a check by search finds each one true of the files it names"*.
   `research/m40-toy-run.md` lines 707–716: run 3's 17 were each checked and none is false; *"of
   run 4's, the bash-mode one was checked the same way, and is true"*. Run 4 is the shipped prompt,
   and its 5 reference-form sentences (*"no test there"*, `mod_tests.rs` under a path given at the
   section's start) are the ones whose truth needs the referent resolved — exactly the check the
   brief asks §18 to say how it reads. The done-when paragraph (lines 692–698) reads the naming
   clause as met and says nothing of the truth clause. Two fixes, either sufficient: (a) check run
   4's remaining 10 by the method run 3's were — a search of the named file per absence, with the
   referent resolved for the 5 — and add them to the list, which costs minutes; or (b) say in the
   done-when paragraph that the truth clause is read as met by run 3's 17 under the identical scoped
   sentence plus run 4's one, since the two runs differ only in the read-none form. (a) is preferred:
   the document under the shipped prompt is what the claim is about.

4. **[IMPROVEMENT] The accepted shortfall's rationale omits the reason the rule is per sentence,
   and a later editor reading it would relax the rule.** `research/m40-toy-run.md` lines 696–697:
   *"the shortfall is accepted because a reference to a path just given is not a claim about the
   project"*. True, and not the whole reason the prompt asks for the path in every sentence: a
   search returns a chunk, not a section — `chunk_max_tokens` 450 against the assembled sequence
   (`design/knowledge-index.md` §4.3 line 576), the snippet capped at 1,200 code points (line
   3011) — so *"no test there covers X"* in a later chunk of a long Behavior reaches a reader with
   no *there*. §4 line 382–385 already makes this argument for dependency bullets (*"every chunk
   holding one then carries the words that find it … a section heading reaches only the chunk it is
   in"*). Suggested edit, one sentence after the acceptance: *"The rule stays per sentence all the
   same: a search returns a chunk of about 450 tokens, not the section, so a reference form in a
   later chunk reaches a reader without its referent; the 6 of 11 is the cost of a wording not yet
   found that the model follows."* Optionally a clause in §4's test bullet pointing at the
   dependency bullet's chunk argument. No prompt change is asked for.

5. **[NITPICK] The README's `--allowedTools` says "the file tools" where a user has to type
   names.** `README.md` line 817. `CLAUDE_CODE.file_tools` is `Read`, `Grep`, `Glob`, `Write`,
   `Edit` (`zikaron/harness/spec.py` line 386), and §18 line 676 lists them; the README names
   `Grep` and `Glob` at line 836 already. Suggested: *"the file tools — `Read`, `Grep`, `Glob`,
   `Write`, `Edit` —"*. §5.2 line 712 may stay, its reader knowing `HarnessSpec.file_tools`.

6. **[NITPICK] "Bare file name" overstates row 2.** `design/code-knowledge.md` line 372 (*"every
   test file named was a bare file name"*) and the brief line 7650 (*"named the files by bare file
   name"*), against §18's row 2, whose 10 are `cli_agent_tests.rs` and `listener/mod_tests.rs` —
   the second a two-component path. Suggested, at both: *"by a short name — `cli_agent_tests.rs`,
   `listener/mod_tests.rs` — never by its path from the root"*.

7. **[NITPICK] §18 reports a third absence form without judging it.** Lines 700–703:
   `blockgrid_element.rs`'s *"the search for `BlockGridElement` and `blockgrid_element` across
   `app/src` found no test file that names it"* — *"a claim about that search, which is true"*. The
   Rules bullet (lines 246–248) now enumerates exactly two absences a search may state, and this is
   not one; whether it is tolerated as a statement of the search rather than of the project, or is a
   drift the enumeration should bind, is the next editor's first question on reading the row. One
   clause either way.

**Checked and not raised.** The reworded Rules bullet names the same two absences Behavior does,
in the same order, and the test phrase at line 416 still matches; the kiro documenter snapshot
carries the reworded bullet (`tests/fixtures/installed/kiro/agents/zikaron-documenter.json` line 6,
one hit for *"the two Behavior asks for"* in each harness's snapshot); the harness-block rule
(lines 260–263) names what to write, what never to write and why, and the rule before it — content
*inside* a read is the file's — already covers a planted block that mimics the harness's framing,
whose failure cost is an omission in a lead the reader checks against the code, so no further
rule is wanted; `test_no_sentence_asks_for_a_test_absence_over_the_whole_project` still counts the
bare form once, and neither new quoted sentence contains it; the installer's default `--components`
is `memory` (`zikaron/install/main.py` line 120), so §18's *"`--components memory` and no
`--model`"* is the brief's *"install's defaults"*; §17's correction separates the two kinds and
§5.1's harness-block bullet attributes the relay to the probe; the `FINDINGS.md` resume block and
release-note plan agree with the build; `FINDINGS-archive.md` §"M41-2 as built" exists and is out
of scope by the brief; the prompt's two added rules cost a few hundred cached tokens per documenter
and no call, so no budget moves; and run 4's streams are recorded as living only in the session's
scratch directory, which §18 says, so nothing claims they are re-derivable.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-30

**Summary judgment.** All seven round-3 findings are applied and each was checked against the
files: the opener's condition excludes a source with tests of its own and the scoped form names
the source's path in that case, §5.2 says *"before §18's"*, §18 carries the chunk argument and
judges the third form, README names the five file tools, §4 and the brief say *"short name"*. The
prompt's Behavior and Rules bullets clear the bar: each names what to write, what never to write
and why, and run 5 shows a Haiku documenter following the inline-case wording unprompted. The
regenerated documents survive in the shared scratchpad, so this round checked §18 against them
rather than against the brief: run 5's row is exact — 6 absences in `unescape.rs`'s, 9 in
`mod.rs`'s, each as the row says — but run 4's row is an undercount of the documents on disk,
and the figures derived from it in §18, the brief's reading of done-when 2 and `FINDINGS.md`
follow it. That is a measurement a reader can falsify by opening the document, so it is the one
thing keeping this short of APPROVED; the claims the count missed are true, so nothing in the
build moves.

### Findings

1. **[IMPROVEMENT] §18's row 4 undercounts run 4's absences, and three figures derive from it.**
   `research/m40-toy-run.md` line 693 counts 11 — 6 by path, 5 reference — for `cli_agent.rs`'s
   and `listener/mod.rs`'s run-4 documents. Those documents are on disk
   (`/tmp/claude-1000/-home-nathan-Zikaron/5e455c41-61e8-4546-b354-01b08a441868/scratchpad/m40-6/warp/code-knowledge/app/src/terminal/cli_agent.rs.md`
   and `…/cli_agent_sessions/listener/mod.rs.md`; runs 1–4 each rewrote them and run 5 did not,
   so they are run 4's). Counted by the criterion row 5 itself uses — row 5 counts `mod.rs`'s
   *"are not exercised by any test in …"* (its line 98) as one of the nine — `cli_agent.rs`'s
   Behavior holds **13** absence sentences, not 8: by path, lines 73, 76 (*"covers that longer
   form"*), 82 (`from_harness` *"is not covered by any test in"*), 88 (`skill_command_prefix`),
   89 (`icon`), 91 (`telemetry_name` *"are not checked by any test in"*), 92 (`detect` *"is not
   exercised for Hermes, Kiro or Pi in"*) and 100 — eight; by reference, lines 74, 87, 96, 98 and
   99 — five; and `listener/mod.rs`'s three `mod_tests.rs` short names at lines 39, 41 and 43.
   **16 in all, 8 by path and 8 by reference** (18 and 10 if line 76's *"none exercises `detect`
   without one"* and line 90's *"checked … only for WarpTui"* are counted, which the §17 wrong
   claim of the same shape argues for). Derived from the 11: line 699's *"6 of 11"*; line 696's
   *"one absence of 44"* (18 + 16 + 15 is 49); line 736's *"So were all 11 of run 4's"*, which
   cannot cover absences the count did not see; and `FINDINGS.md` line 94's *"1 bare absence in
   44"*. The truth clause survives: against `app/src/terminal/cli_agent_tests.rs` the uncounted
   ones are each true — `from_harness`, `telemetry_name`, `Hermes`, `Kiro` and a bare `Pi` occur
   nowhere in it; `skill_command_prefix` only at lines 314 (Grok) and 323 (Muse); `.icon(` only at
   315, 324 and 682 (Grok, Muse, WarpTui); `brand_icon_color` only at 683; and every
   `detect("aifx agent run claude", …)` (lines 512, 517, 559, 607) follows a `UserWorkspaces`
   mock (502, 529, 555, 597). Suggested fix: recount row 4 from the two documents and state the
   criterion once above the table — a sentence stating that a test in a named file does not
   cover, check, exercise or pin a behavior — then correct the four derived figures, and let line
   736 say the recounted total was checked, naming what the five absences above were checked
   against so the reader need not repeat it. Minutes of work; the conclusion — about half of run
   4's sentences carry the path, every absence is about a named file — does not change.

2. **[NITPICK] `ref_tests/mod.rs` falsifies the sentence that chose run 5's module.** §18 line
   670: *"No source of `app/src/terminal` holds its tests inside it"*.
   `app/src/terminal/ref_tests/mod.rs` holds `#[test]` functions, generated by its `ref_tests!`
   macro at lines 21–30, and is not a `*_tests.rs` file; a reader who greps as this round did
   finds it first. The choice of `crates/warp_terminal/src/shell` stands — a data-driven harness
   is not the inline-test case the brief means. One clause: *"No non-test source of
   `app/src/terminal` holds its tests inside it — `ref_tests/mod.rs`, a test harness whose
   `#[test]`s a macro writes, is the one file with one outside a `*_tests.rs`"*.

3. **[NITPICK] Run 5's third document is left out of the count without a word.** §18 lines
   686–687 count *"those of `unescape.rs`'s and `mod.rs`'s"*; done-when 2's *"each of their test
   absences"* covers `mod_tests.rs`'s document too. Its Behavior (line 39 of the document) says
   *"The file was read whole. Each behavior below is asserted by the named test in this file"*
   and states no absence, so the omission is right and unexplained. Add: *"and `mod_tests.rs`'s,
   which states none"*.

4. **[NITPICK] The file-scoped form rests, in `mod.rs`'s document, on a partial read of the file
   it names, and §18 reports the read without the consequence.** §18 line 720 quotes the
   document: it read `mod_tests.rs`'s *"test names and lines 320 to 400"* — the file is 399
   lines — and scopes nine absences to the whole file. A test whose name does not say what its
   body exercises would escape a names-only read, so a file-scoped absence can be wider than the
   read behind it at a finer grain than the project-wide one was; here every one of the nine was
   checked true. The design's answer already holds — the sentence names the one file a reader
   greps — and the fence rules out asking for more reading, so no prompt change is proposed. One
   sentence after line 725 recording that the nine rest on names for lines 1–319 and were each
   checked, so the next editor does not take the form as proof the file was read whole.

5. **[NITPICK, optional] The opener's sentence says "test file" where its condition now says
   "no test at all".** `zikaron/install/code_knowledge.py` lines 200–201: the condition is
   *"neither in a file of its own nor inside the source"*, the quoted sentence *"No test file was
   read for this file."* A reader of a document sees only the sentence, and cannot tell from it
   that inline tests were absent too; the condition makes it so, but only to someone who has read
   the prompt. *"No test was read for this file."* would say what the condition means, at the
   cost of the phrase at `tests/test_install_code_knowledge.py` line 396, the quoted forms in §4,
   §5.1 and the brief, and a snapshot re-render. The author may decline on cost: the sentence is
   true as written, and run 4's two read-none documents show the model producing it verbatim.

**Checked and not raised.** Run 5's row verified against the documents: `unescape.rs`'s six
absences at its lines 29, 30, 33, 35, 36 and 37, five scoped to its own path and the bare one true
— the source's four tests (lines 107–161) pass `$` only as an ANSI-C opener or escaped inside
double quotes (line 135); `mod.rs`'s nine at lines 90–101, all scoped to `mod_tests.rs`, and
`supports_autocd` occurs eight times in `crates/warp_completer/src/completer/suggest/test.rs` and
not in `mod_tests.rs`. The read-none premise for both run-4 sources holds: `BlockGridElement`,
`blockgrid_element`, `InlineMenuMessageBar`, `INLINE_MENU_BORDER_WIDTH` and `InlineMenuMessageArgs`
occur in no `*_tests.rs` under `app/src`. `mod.rs` declares its tests with `#[cfg(test)] #[path =
"mod_tests.rs"] mod tests;` at line 1015, so the module is the three files §18 names. The prompt's
Behavior bullet (lines 196–206) and Rules bullet (lines 247–249) name the same two absences; the
five new phrases are in `TestThePromptCarriesTheSpecsRules` and the three snapshots carry them;
`test_no_sentence_asks_for_a_test_absence_over_the_whole_project` still counts the bare form once.
§5.2 line 709 says *"before §18's"*; §18 lines 701–704 carry the chunk argument and
`chunk_max_tokens` 450 is at `design/knowledge-index.md` line 576; lines 707–714 judge the third
form as drift; `README.md` line 817–818 names the five file tools; §4 line 372–373 and the brief
line 7651 say *"short name"*. The module docstring and §5.1 lines 487–489 state the provenance
correctly; `FINDINGS.md`'s release-note plan (lines 78–80) still tells every user to re-install;
the `FINDINGS-archive.md` §"M41-2 as built" block is out of scope by the brief.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-30

**Summary judgment.** Round 4's findings 1–4 are applied and each was checked against the
documents rather than the brief: counted by §18's stated criterion over the Behavior sections on
disk, run 4's two documents hold 18 absences (15 in `cli_agent.rs`'s — lines 73, 76 twice, 82,
88–92 and 100 by path, 74, 87, 96, 98 and 99 by reference — and `listener/mod.rs`'s three
`mod_tests.rs` short names at 39, 41 and 43), run 5's 16 (`unescape.rs`'s 7 at lines 29, 30, 33
twice, 35, 36 and 37; `mod.rs`'s 9 at 90–93, 96–99 and 101), and run 3's saved copy
(`scratchpad/m40-6/round1-docs/`) 18 — 13 and 5, one of them *"No test covers that either"* — so
every figure in the table and every figure derived from it in §18, §4, the brief and `FINDINGS.md`
is what the documents say. The three `listener/mod.rs` reference forms are true of their real
referent: `listener/mod_tests.rs` never constructs `CLIAgentSessionListener`, has no
`should_panic`, and passes `true` to `try_parse` only on the Codex and Grok handlers (its lines 88
and 158). `ref_tests/mod.rs` is the one file under `app/src/terminal` outside a `*_tests.rs` with a
`#[test]` attribute. Read again with fresh eyes against the prompt bar, the Behavior bullet and the
Rules bullet name what to write, what never to write and why, with a quoted form and a condition
for each of the three cases, and the harness-block rule does the same; nothing in the build moves.
What remains is three precision fixes to the research note, none of which changes a conclusion.

### Findings

1. **[NITPICK] The stated criterion catches one sentence §18 says is not there.**
   `research/m40-toy-run.md` lines 691–692: `mod_tests.rs`'s document *"states none"*. Its
   Behavior line 54 — *"The test checks the escape count only; it does not run the escaped string
   through a shell."* — is a sentence saying a test pins a behavior only in part, the same shape as
   `unescape.rs`'s *"`test_unescape_double_quotes` checks only the escaped forms"*, which row 5
   counts as its one reference form. Either count it — row 5 becomes 17 (14, 2, 1), line 702's
   *"of 52"* and `FINDINGS.md` line 94's *"in 52"* become 53, line 705's *"14 of 16"* becomes
   *"14 of 17"* — or say in one clause why it is not an absence: it describes what a test does, in
   the test file's own document, not a behavior of a source no test pins. Either is a minute;
   the conclusion does not move.

2. **[NITPICK] The truth paragraph names one referent for eight reference forms that have two.**
   `research/m40-toy-run.md` lines 745–749: *"the eight reference forms with their referent
   resolved — against `app/src/terminal/cli_agent_tests.rs`, where …"*. Five of the eight are
   `cli_agent.rs`'s; the other three are `listener/mod.rs`'s, whose referent is
   `app/src/terminal/cli_agent_sessions/listener/mod_tests.rs`, and the evidence listed is all
   about the first file. Suggested: *"— `cli_agent.rs`'s five against
   `app/src/terminal/cli_agent_tests.rs`, where …, and `listener/mod.rs`'s three against
   `app/src/terminal/cli_agent_sessions/listener/mod_tests.rs`, which never constructs
   `CLIAgentSessionListener` and passes `true` to `try_parse` only on the Codex and Grok handlers
   —"*. Checked here; the three are true.

3. **[NITPICK] The counting method stated is not the one used.** `research/m40-toy-run.md` line
   689: *"counted by hand and classed by how it names the test file it is about"*. The brief says
   the recount was a search for the criterion's phrasings over each Behavior section with two
   matches that are not absences — *"runs only for the `Claude` entry"*, *"is false only for
   `WarpTui`"* — removed by hand. Say that, in the same sentence: a reader re-deriving the count
   from the criterion needs to know which phrasings were searched and which hits were struck, and
   *"by hand"* tells them neither.

**Checked and not raised.** Runs 4 and 5 were counted by the criterion's four verbs and *"only"*
clauses and the counts agree with the table to the sentence, false positives excluded as the brief
says; run 3's copy in `round1-docs/` carries no read-none form and the *"No test covers that
either"* row 3 cites, so it is run 3's. Of the author's spot checks, `cli_agent_tests.rs` has
`skill_command_prefix` at 314 and 323 only, `.icon(` at 315, 324 and 682, `brand_icon_color` at
683, `supports_bash_mode` for Grok, Muse, OhMyPi and WarpTui only, and no `from_harness`,
`telemetry_name`, `Hermes`, `Kiro` or `CLIAgent::Pi`; the one env-var `detect` (line 443) passes
`Some(EscapeChar::Backslash)`; `test_unescape_double_quotes` (lines 132–145) asserts a plain
string and four escaped forms, no bare `$`. The three snapshots carry the shipped text: the
Claude Code documenter's lines 105–117 and 137–175 match the module's Behavior and Rules bullets,
the SKILL.md Permissions section matches `CLAUDE_CODE_LAUNCH_BODY` lines 584–598, and the kiro
documenter's one-line prompt holds each of the five phrases. `test_install_code_knowledge.py`'s
phrase list pins each rule by a sentence a rewording would lose, and
`test_no_sentence_asks_for_a_test_absence_over_the_whole_project` still counts the bare form once.
§4 lines 368–375 and the brief line 7651 say *"at least 6 of 16"*; §5.1 lines 425–427 name the
same two absences as Rules; the module docstring and §5.1 lines 487–489 state the provenance;
`FINDINGS.md` lines 76–97 name M40-6, its plan and the re-install note; the corpus sweep for the
old form (*"no test covers"*, *"that none does"*) finds only the forbidden form, the brief's
account of what was found, and two archive blocks that record what was believed when they were
written. The brief's line 7667 says *"the last"* run used the list alone where §18 says runs 4 and
5 did; both are true of run 5, and nothing follows from it.

VERDICT: APPROVED
