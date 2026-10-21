# Review — M40-5, a second documentation run the harness ran in the foreground

Artifact: `design/build-plan.md` §"M40-5 — A second documentation run the harness ran in the
foreground, where it could not wait" (lines 7324–7473 at review time), with
`research/m40-5-spawned-orchestrator-probe.md`.

## Round 1 — 2026-10-21

**Summary judgment.** The brief is grounded: the field run, the docs' foreground rule (§Q8(c)), the
probe's two overlapping session-spawned agents, and every code and spec citation I checked hold
(`_SKILL_BODY` already takes `.`, step 1 already names `code-knowledge` for it, the consolidation
skill's `skill_markdown` is the frontmatter shape item 1 asks for, `orchestrator_agent_markdown`
takes a prompt string). It is not yet complete enough to build from without re-deriving decisions.
The whole-project default collides with the loop's own nesting refusal in every project that was
documented module-wise — the operator's primary project included — and the brief does not mention
it. The orchestrator becomes a counted subagent, which removes the measured premise of the batch's
19 while the fence forbids touching it. And three things the brief says are unchanged or leaves
unlisted contradict what it builds: the orchestrator's description, the "names no tool" test and
§5.4 sentence, and done-when 2's sweep over §7's measurement record.

### Findings

1. **[BLOCKER] The whole-project default is refused by the loop's nesting rule wherever a module is
   already documented.** Item 1 (first bullet and the description sentence, *"create, write or
   update ... with no directory named it documents the whole project"*) and item 3 (first bullet).
   `_SKILL_BODY` step 1 (`zikaron/install/code_knowledge.py` lines 313–320; spec §5.2 step 1, §5.3):
   before the planner runs, a corpus named `code-knowledge/...` whose `root_path` *lies inside*
   `<root>/<corpus>` stops the run. With no module, `<corpus>` is `code-knowledge`, and
   `<root>/code-knowledge/sugar-leiba` lies inside it — so in `~/Trading/LeibaTrader`, in Warp's clone
   (`code-knowledge/app/src/terminal`) and in any project whose first run named a directory, the
   plain-words *"update the code documentation"* the operator gave as the motivating prompt is refused
   before anything runs, by the very path the brief adds for it. Nothing in the brief says this, and
   done-when 5's plain-words test runs in a fresh install, where it cannot show.
   **Suggested change**, prose only, the operator choosing which: (a) with no module, whoever runs the
   loop reads the `zikaron_knowledge_status` listing it already fetches for the nesting check, and when
   any `code-knowledge/...` corpus is registered the run is **one per registered module** — under
   Claude Code one orchestrator spawn each, the module being the name after `code-knowledge/`; under
   kiro the loop in turn — with `.` only when none is; or (b) keep `.` and have the refusal's report
   name the registered modules and say to invoke once per module, with the session's skill telling it
   to do exactly that on such a report. Either way: state it in item 3's first bullet and the
   description, add an invariant with its mutation (the branch dropped from the loop), and add to
   done-when 5 the plain-words ask in a project that already has one module documented.

2. **[IMPROVEMENT] The orchestrator now holds one of the 20 slots the batch's 19 was measured
   against.** "What was found", item 3's second bullet, the fence's *"nor the batch's 19"*, done-when 5.
   `research/m40-toy-run.md` §13: *"The first batch ran all 20, so the forked orchestrator is not
   counted against the limit"*; the field run agrees (two forks out, 19 documenters held, one slot
   free → 18 of 19 refused). A session-spawned orchestrator is an ordinary subagent and will, on the
   docs' own wording, count. Consequences the brief should state rather than let the build discover:
   a lone run's first batch is 1 + 19 = 20 and fits; every later batch is 1 + the straggler §13
   measured + 19 = 21, one refused per batch, so the throttling rule oscillates 19 → 18 → 19 with a
   wasted spawn each; and two runs are 2 + 19 = 21, so the second orchestrator's *own* spawn is refused
   whenever the first has a batch out — item 1's *"need not wait for one another"* is, in practice,
   serialization by refusal and retry. **Suggested change**: say in "What was found" that the fork held
   no slot and the orchestrator will; have done-when 5 record spawns and refusals per batch for the lone
   run (the probe note's table shape), so the brief's claim is measured; and decide now what one
   refusal per batch means — accepted and written into §5.2's arithmetic, or the batch moved to 18 in
   this build, with the fence saying which.

3. **[IMPROVEMENT] The orchestrator's description says the opposite of what the skill now asks.**
   Item 2: *"Its frontmatter is unchanged: name, description, tools, model and effort."*
   `ORCHESTRATOR_DESCRIPTION` (`code_knowledge.py` lines 51–55) reads *"Started by that skill, never
   directly"* — written to stop a session spawning it outside the fork. Item 1 now tells the session to
   spawn it directly, and done-when 5's plain-words path may reach it by auto-delegation on this very
   description. **Suggested change**: item 2 says the description is rewritten — e.g. *"Runs one
   documentation run in the background: Zikaron's planner in batches and a zikaron-documenter per file,
   until the module is documented. Spawned by the session when the zikaron-document-code skill says so,
   one per module, never on its own judgment"* — and lists it in the invariants (mutation: *"never
   directly"* put back). `DOCUMENTER_DESCRIPTION`'s *"Spawned by the zikaron-document-code skill"* can
   stand or say "by the agent running that skill's loop".

4. **[IMPROVEMENT] The orchestrator's prompt will name tools, and two guards say it names none.** Item 2
   renders the loop into the orchestrator's definition *"with its tool names"*; the loop names the
   knowledge verbs (`zikaron_knowledge_status`, `_list`, `_add`, `_refresh`, rendered to
   `mcp__zikaron__...`). Spec §5.4 says the prompt *"names no tool, the grant being the one place a tool
   is named"*, and `tests/test_install_code_knowledge.py::TestThePromptsNameNoTool` parametrizes four
   tests over `ORCHESTRATOR_PROMPT`. Neither is in item 6 or the invariants, and the invariant *"No
   skill or agent text names a tool its harness lacks"* is the one bullet with no mutation, against the
   section's own rule. **Suggested change**: item 2 states the orchestrator's definition names Zikaron's
   verbs in Claude Code's rendered form and no built-in by name (the spawn instruction names none, as
   now); item 6 adds §5.4's sentence; the invariant becomes two with mutations — the preamble
   (`ORCHESTRATOR_PROMPT` alone) still names no tool (the existing tests, kept on the preamble), and
   the rendered definition passes the bare-name check `test_under_claude_code_no_bare_tool_name_survives`
   makes for the skill (mutations: kiro's `subagent` spawn instruction rendered into the definition; a
   bare `zikaron_knowledge_add` left unrendered).

5. **[IMPROVEMENT] Nobody is told to resume a run that stopped on contention.** Item 1's fifth bullet
   covers a *refused orchestrator spawn*; item 3's stop rule has the run report that *"invoking the
   skill again resumes where this run stopped"* — and the session's bullets say only to relay the
   report. Under the brief's own arithmetic (finding 2) this stop is the common outcome of a second
   invocation that lands mid-batch: 19 refused, 1 refused, stop, within seconds. **Suggested change**:
   a sixth bullet in item 1 — when a run's report says it stopped because the session's subagents
   were all in use, invoke the skill again for that module once the run holding them has reported;
   when no run of this session's is out, tell the user what else holds them — with the phrase in the
   invariants (mutation: dropped).

6. **[IMPROVEMENT] Two runs on one module is the case "one run at a time" also protected, and the
   brief lifts the rule without replacing that half.** Item 6: *"runs that may overlap, sharing the
   session's subagents, the throttling rule of item 3 their arbiter"*. The throttling rule arbitrates
   slots, not the documents directory: two `--apply` planner runs over one `<corpus>`, and two
   documenters at one `Document:` path, where the documenter's rule is to write a file that holds
   nothing and report a refused write. A user re-asking for the module already running is ordinary
   (the field session re-invoked `console`). **Suggested change**: one bullet in item 1 — a module a run
   of this session is already documenting, or one nesting it, is not invoked again until that run
   reports — and item 6's §5.2 rewrite says overlapping runs are on distinct, non-nesting modules
   (mutation: the sentence dropped).

7. **[IMPROVEMENT] Done-when 2 sweeps a measurement record it should exempt.**
   `design/code-knowledge.md` §7 (lines 1146–1149) says the toy run's orchestrator total was summed
   over messages whose `parent_tool_use_id` is the fork's, `forked-command-zikaron-document-code`.
   That records how a number in `research/m40-toy-run.md` was computed on the fork; rewriting it
   falsifies the record, and leaving it fails done-when 2 as written. M40-3's done-when 2 exempted §7
   for the same reason. **Suggested change**: exempt §7's record as M40-3 did, and say in item 5 how the
   live test now finds the orchestrator's messages — the session's `tool_use` whose `input` carries
   `subagent_type: zikaron-code-orchestrator`, and the records whose `parent_tool_use_id` equals its
   id — so the two identifications are not confused and the evaluation's harness is not touched.

8. **[NITPICK] Item 4's "three texts ... from one loop"**: Claude Code's skill carries no loop; two
   texts render it (kiro's skill, the orchestrator's definition) and the third is the short launcher.

9. **[NITPICK] Item 3's "while none of the run's own documenters is running"** is vacuous at a batch
   boundary — step 3 waits for every documenter before the planner runs again — and reads as a
   condition with an unstated else. Reword: *"A batch that starts none has nothing to wait for and is
   followed at once by a batch of one."*

10. **[NITPICK] Say how the arguments reach the session.** Item 1: *"carries the invocation's
    arguments verbatim, or says there are none"*. The body needs `$ARGUMENTS`
    (`research/claude-code-background-subagents.md` §Q8(e); without it Claude Code appends
    `ARGUMENTS: ...`), and the empty case should be framed in the text, since the live test invokes
    with none and only done-when 5 exercises the argument path.

11. **[NITPICK] Two passages outside the normative list.** `README.md` §Install's table (line 363,
    *"the subagent the code-documentation skill runs as, in the background"*) — done-when 2 reaches it
    by meaning, but the list names only the code-knowledge section; and
    `tests/test_code_knowledge_claude_live.py`'s `_RUN_TIMEOUT` comment (*"Three documents"*) becomes
    four once `.mcp.json` is a source, as the fence says it is.

12. **[NITPICK] The headless shape is measured first by done-when 4.** Under `-p` the toy run's fork
    ran in the foreground (§Q8(c)); a *background* orchestrator spawning *foreground* documenters under
    `-p` has no measurement yet. Say so in item 5, so a red live test is read as a measurement of the
    harness rather than a defect in the build.

VERDICT: NEEDS_CHANGES

### Author response to round 1

All twelve accepted and applied to the brief.

- **1**: option (a), decided by the author as cheap to reverse — with no module named, the loop
  documents every registered `code-knowledge/<module>` in turn inside one run, passing no globs (the
  fence says so), and the whole project only where none is registered. Item 1's description, item 3's
  first bullet, an invariant for both branches, and done-when 5's plain-words ask in a project with
  one module documented.
- **2**: the batch moves to 18 in this build, the orchestrator's slot taken by the same reasoning
  that set 19; "What was found" says the fork held no slot; done-when 5 counts a lone run's spawns and
  refusals per batch; the fence no longer fences the batch.
- **3**–**7**, **10**–**12**: applied as suggested — the description rewritten with its invariant;
  item 2 and §5.4's "names no tool" and the split invariant; item 1's contention-stop and
  running-module bullets; §7's record exempted and the live test's identification stated; `$ARGUMENTS`;
  README §Install's row and the timeout comment; the headless shape called unmeasured.
- **8**, **9**: reworded.

## Round 2 — 2026-10-21

**Summary judgment.** All twelve round-1 findings are applied as the response says, and the brief
now stands on verified ground: `.` is a tested module and the documents directory is never a source
(`tests/test_code_knowledge_command.py` lines 222–237), dot-directories are pruned
(`zikaron/core/knowledge/walk.py` line 94) so `.mcp.json` is the toy project's third source and
nothing under `.claude/` or `.zikaron/` is one, an Agent-tool subagent's messages are parented on
the call's id (`research/nested-subagent-probe.md` line 12) so item 5's identification is right,
and nothing a session runs imports `zikaron/install/` (`zikaron/cli/main.py` line 53 imports it
lazily, under `install` alone). What remains is four cases the no-module rule and done-when 5 do not
yet decide, each a sentence to fix: a measurement that cannot discriminate at a batch of 18, a
vanished module that stops the whole-project update, globs and a slice given with no module, and a
no-module invocation against the session's overlap rule.

### Findings

1. **[IMPROVEMENT] Done-when 5's per-batch count cannot say whether the orchestrator holds a slot
   once the batch is 18.** Lines 7504–7505: *"A lone run's spawns and refusals are counted per
   batch, which says whether the orchestrator holds a slot."* It does not. A lone run's first batch
   is 18 plus the orchestrator's slot or not — 19 or 18, under 20 either way; every later batch adds
   §13's straggler — 20 or 19, still under or at 20 either way. Zero refusals in every batch,
   whichever is true. §13 discriminated only because its batch was 20. The decision this should
   force is real: 18 stands if the orchestrator counts, 19 returns if it does not, one slot in
   every batch otherwise wasted. **Suggested change**, either: (a) for the lone run alone, the
   operator edits the batch to 20 in the installed loop text — after this build,
   `.claude/agents/zikaron-code-orchestrator.md` — and reads the *first* batch: one refused means
   the orchestrator counts, none means it does not; or (b) count running subagents directly from the
   harness's records while a batch is out — the probe note's method, the subagent transcripts under
   the session that have started and not handed back. And say that `experiments/m40_run_cost.py`
   classifies an orchestrator by the fork's opening (`_SKILL_OPENING = "Base directory for this
   skill:"`, line 37), so a spawned orchestrator is listed as `other`, its per-`--apply` counts
   still printed — so whoever reads the run knows where the line is.

2. **[IMPROVEMENT] The no-module run stops at the first registered module whose directory is gone.**
   Item 3's first bullet (lines 7405–7413). `zikaron/code_knowledge/main.py` line 130 refuses
   `--module <m>: no such directory` with a non-zero exit, and the loop's step 2 (`_SKILL_BODY`
   lines 337–338) says *"A non-zero exit is a refusal … report it and stop."* The loop registers a
   corpus and never removes one (step 7; the orchestrator's *"rename or remove none"*), so a module
   renamed or deleted after it was documented leaves `code-knowledge/<old>` registered, its documents
   on disk; the no-module run reaches it in turn, the planner refuses, and the run stops with every
   module after it in the listing untouched. A rename is ordinary over a project's life, and the
   plain-words *"update the code documentation"* is exactly the invocation that meets it.
   **Suggested change**: in the no-module branch, a module the planner refuses as no directory is
   reported — its corpus named, and that removing the corpus and its documents is the user's — and
   the run goes on to the next module; the invariant *"Both harnesses' loops carry item 3's rules"*
   gains it (mutation: the skip dropped, so the refusal stops the run).

3. **[IMPROVEMENT] Globs and `--slice` with no module are undefined.** Item 1's usage line (lines
   7368–7369) makes the module optional while keeping `[--include GLOB]... [--exclude GLOB]...
   [--slice N]`, so `/zikaron-document-code --slice 20` parses — and `README.md` line 719 sells
   `--slice 20` as how to see what a run costs. Item 3 says the no-module run *"passes no globs"*
   and nothing of a slice given with none; a build cannot write the loop's text without deciding
   whether a slice counts across modules, applies to the whole-project branch only, or is refused.
   **Suggested change**, the simpler: a no-module invocation that carries a glob or a slice is
   refused before the planner first runs — reported, since nothing says which module they are for
   — on both harnesses; the invariant gains it (mutation: the refusal dropped). The alternative,
   applying them to the whole-project branch alone, needs a sentence saying what happens where
   modules are registered, which is the same refusal.

4. **[IMPROVEMENT] A no-module invocation while a run is out escapes the session's running-module
   rule.** Item 1's fifth bullet (lines 7378–7379) keys on the module a run is documenting; its
   second bullet says a no-module spawn *"leaves the choice of modules to the orchestrator"*, so the
   session has no module to compare — and the no-module run covers every documented module, so it
   always overlaps a run on any one of them: two `--apply` planner runs over one `<corpus>`, two
   documenters at one `Document:` path, the case round 1's finding 6 closed for named modules. A
   user who asks for `go`, then *"update everything"* fifteen seconds later, is the field run's
   shape. **Suggested change**: one clause in item 1's fifth bullet — a no-module invocation is not
   started while any run of this session's is out, and no run is started while a no-module run is
   out — and the invariant *"keeps a second run off a running module"* names it (mutation: the
   clause dropped).

5. **[NITPICK] Say which description changes, and cover it.** Item 1's last paragraph (lines
   7391–7393) sits under *"Under Claude Code"*, but `_SKILL_DESCRIPTION` (`code_knowledge.py` lines
   270–275) is one text for both harnesses, and kiro's loop gains the same no-module rule. Say the
   description is one text on both, and add an invariant (mutation: the *"with no directory named"*
   clause dropped) — no invariant covers the description today. Keep its present opening, per-source-
   file documents into a knowledge base, ahead of the widened *"create, write or update the code's
   documentation"*: a plain *"document this function"* must not start a whole-project run.

6. **[NITPICK] Done-when 5's two-modules leg should say what success looks like.** By item 3's own
   arithmetic the second orchestrator's first batch is refused whole — the first's 1 + 18 and its
   own slot make 20 — its batch of one too, and it stops within seconds; the session re-invokes when
   the first reports. State that in done-when 5 (lines 7501–7502), so the operator reads the second's
   stop report as the designed path and counts it: both spawned at once, the stop report, the
   re-invocation, both `up_to_date`.

7. **[NITPICK] `run_in_background: true` buys nothing where the parameter exists, and costs the
   measured shape.** Item 1 (lines 7370–7373). Interactively the parameter is absent and every spawn
   is background (§Q3), so the value matters only under `-p`, where the session has nothing else to
   do. There `true` is the shape item 5 calls unmeasured, resting on the exit-time wait and the
   ceiling variable (§Q4); `false` is the shape already measured — a foreground subagent spawning a
   foreground grandchild under `-p` (`research/nested-subagent-probe.md`), the toy run's `-p` fork
   having waited in the turn for 57 minutes (§Q8(c)). Consider `false` where offered, keeping the
   clause that an absent parameter means background and is expected; item 5's caveat then narrows
   to nothing the build has not seen.

VERDICT: NEEDS_CHANGES

### Author response to round 2

- **1**: applied as (a) — the lone run's installed batch set to 20 by hand in the test project, its
  first batch read — with the `m40_run_cost.py` note in done-when 5.
- **2**: applied, generalized: in a run of several modules a refused module — no such directory, or
  nested — is reported and the run goes on; a run of one stops as now.
- **3**: the alternative, decided by the author: globs and `--slice` need a run of one module, named
  or the whole project, so `--slice 20` in a fresh project still works; over several modules,
  refused before the planner first runs.
- **4** and **6**: answered by one change, decided by the author, which round 2's own arithmetic
  forced: a second run in a session cannot share the subagents with the first — the first holds 19
  of 20 with a batch out, so the second's batches are refused whole and it stops. So the session
  queues a request that comes while a run is out and spawns it on that run's report, and one request
  is one spawn, its orchestrator documenting every module it names in turn. That removes the overlap
  case for named and no-module runs alike, and done-when 5's two-module leg now says what success is.
  The throttling rule stays, for slots the session's other subagents hold.
- **5**: applied, with an invariant.
- **7**: declined. The operator's words are in the brief's authority line — *"instructed explicitly
  to run it in background"* — and done-when 4 measures the `-p` shape; item 5 already says a red run
  is read as a finding about the harness first.

## Round 3 — 2026-10-21

**Summary judgment.** Round 2's responses are applied as stated, and the brief's structure now
matches M40-3's (normative list, what was found, the in-tree justification, six items, invariants
with mutations, done-when, fence). Every citation I re-checked holds: the fork's foreground rule
is §Q8(c) as quoted; `$ARGUMENTS` is substituted into a skill's text and its absence makes Claude
Code append `ARGUMENTS: …` (§Q8(e)); a background subagent keeps `Read`, `Bash`, every MCP tool and
`Agent` below the depth limit (§Q2c), so the orchestrator loses no tool by being spawned rather
than forked; `_ClaudeAgent.markdown` emits exactly name, description, model, effort, tools; and the
research note supports the one decision it is cited for. What remains is four passages a build
would implement wrongly or ambiguously as written — the spawn prompt's shape, which decides whether
a glob survives the session's model; the retry trigger for a refused orchestrator spawn, which the
queue rule has made impossible; the relay line for a run of several modules; and a frontmatter line
that would make the operator's background choice the harness's rather than the model's — plus three
nitpicks.

### Findings

1. **[IMPROVEMENT] The spawn prompt is left to the session's composition, and a paraphrased glob
   is destructive.** Item 1's second bullet (lines 7373–7375): *"giving it a prompt that carries
   the invocation's arguments verbatim, the body reading them through `$ARGUMENTS`, or says there
   are none"*. Claude Code substitutes `$ARGUMENTS` into the skill's text before the model reads it
   (`research/claude-code-background-subagents.md` §Q8(e): *"always expands to the full argument
   string as typed"*), so where the text puts `$ARGUMENTS` decides whether "verbatim" is copying
   or composing. The consolidation skill — the shape the Normative paragraph names — gives the
   session a fenced prompt to hand over (`tests/fixtures/installed/claude-code/skills/zikaron-consolidate/SKILL.md`
   lines 24–31); item 1 gives it a sentence. A session model that composes may turn
   `--include 'src/**/*.py'` into *"the Python files under src"*, and the orchestrator then runs
   the planner under `--apply` with no glob, or a different one — and a narrower set makes the
   planner **remove** the documents it no longer admits (`_SKILL_BODY` lines 299–301; item 3's
   second bullet keeps that rule). **Suggested change**: item 1 says the body gives the prompt as a
   fenced block, as the consolidation skill does — e.g. *"give it this prompt:"* then a block
   reading *"Run one documentation run with these arguments, exactly as written and no other:"*
   and `$ARGUMENTS` on the line below — so an empty line is the no-arguments case and *"or says
   there are none"* becomes the orchestrator's reading of an empty line rather than the session's
   sentence; the second invariant's *"carries `$ARGUMENTS`"* becomes *"carries `$ARGUMENTS` inside
   the fenced prompt it tells the session to give"* (mutation: moved outside the block). Item 3's
   first bullet, *"the sentence on where the arguments come from names … the spawn prompt under
   Claude Code"*, then says the arguments are the line after that sentence, empty for none.

2. **[IMPROVEMENT] One frontmatter line makes the background the harness's choice instead of the
   session model's.** Item 1 (lines 7370–7373) and item 2 (line 7402, *"Its tools, model and
   effort are unchanged"*). Under `-p` the session's model chooses by the parameter (§Q3 case 4),
   and the toy run saw a model leave the parameter out once and break a run
   (`research/m40-toy-run.md` §5). The subagents page documents a definition field for exactly
   this: *"`background` | Set to `true` to keep this subagent in the background even when Claude
   asks to run it in the foreground"* (§Q3, lines 254–256). It costs nothing: interactively every
   spawn is background already, and the background tool set keeps `Read`, `Bash`, every MCP tool
   and `Agent` below the depth limit (§Q2c, lines 218–221), so the orchestrator's grant is whole
   either way. This is compatible with the intentional `run_in_background: true` — the instruction
   stays, the definition enforces it — and is the operator's *"not depending on harness' quirks"*
   applied to the one path item 5 calls unmeasured; and if done-when 4 reddens on the background
   shape, this line is also where `false` would go. **Suggested change**: item 2 says the
   orchestrator's definition carries `background: true`, the documenter's not — it is asked for the
   foreground under `-p` — so `_ClaudeAgent` gains an optional field that only the orchestrator
   sets; an invariant: *"The orchestrator's definition keeps it in the background by frontmatter,
   the documenter's does not"* (mutations: the line dropped; set on the documenter).

3. **[IMPROVEMENT] The retry trigger for a refused orchestrator spawn cannot fire.** Item 1's
   fifth bullet (lines 7381–7382): *"a spawn refused because too many subagents are running is
   made again when a running run's report arrives"*. Under the fourth bullet the session spawns
   only when no run of its own is out, so a refused orchestrator spawn means no run is out, and
   *"a running run's report"* never arrives — what holds the slots is other subagents the user
   launched, which the second half of the bullet already handles for the contention-stop case.
   **Suggested change**: *"a spawn refused because too many subagents are running is made again
   when the session's next subagent reports, or, when the session has none out, answered by telling
   the user that something else holds them"* — and the contention-stop clause then says *"is
   answered the same way"* and nothing more, since the elaboration is now above it. The third
   invariant's *"answers a contention stop"* covers both (mutation: either trigger dropped).

4. **[IMPROVEMENT] A run of several modules opens with several lines, and the session relays
   one.** Item 1's sixth bullet (lines 7386–7387): *"to relay each report when it arrives, its
   first line naming the module"*; item 3's first bullet (line 7414): *"Each module … gets its own
   opening report line"*. For the plain-words path — the motivating case — a run over three
   registered modules reports three opening lines and the session, as instructed, relays the
   first, so the user learns one module's state of three. **Suggested change**: *"its opening
   lines, one per module the run documented"* in item 1; step 8's *"Open it with one line naming
   the module"* becomes one such line per module, first in the report, which the existing
   `test_the_report_opens_with_the_module_its_state_and_its_knowledge_base` phrase follows; and
   the rules invariant names it under the modules rule.

5. **[NITPICK] "Names no built-in tool" is false by the whole-word check's own definition.** Item 2
   (line 7401) and item 6 (lines 7464–7466). `CLAUDE_CODE_PLANNER_COMMAND` opens a sentence with
   *"Read `.mcp.json` there"* (`code_knowledge.py` line 481), a whole-word match for a built-in's
   name — exactly what `test_no_claude_code_tool_name_as_a_whole_word` exists to catch, which is
   why the brief keeps it on the preamble. Either say so in item 2 — the loop names a built-in only
   as the English verb, which is why the whole-word check stays on the preamble — or reword the
   verb (*"Open `.mcp.json`"*) so the check can run on the whole definition. The §5.4 sentence item
   6 rewrites should match whichever.

6. **[NITPICK] The skill's headless needs have no invariant.** Item 1's last bullet (lines
   7388–7390) carries `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` and the `--allowedTools` list, and
   the second invariant (lines 7481–7484) does not; a build that drops the paragraph reddens
   nothing. Add *"and names what a headless run needs"* (mutation: the variable dropped).

7. **[NITPICK] Done-when 5's slot measurement needs a module that owes at least 20 documents.**
   Lines 7520–7523. A first batch of 20 exists only where the planner lists 20 items, so the lone
   run cannot be the leg's small test project or the playground; say the module's size, or name a
   project of LeibaTrader's size for that one run, so the operator does not read zero refusals from
   a batch that was never 20.

VERDICT: NEEDS_CHANGES

### Author response to round 3

All seven accepted and applied: the fenced spawn prompt with `$ARGUMENTS` on its own line, and the
invariant moved inside the block (1); `background: true` on the orchestrator's definition alone,
`_ClaudeAgent` gaining the field, with its invariant (2); the refused-spawn retry on the session's
next subagent report (3); one opening report line per module, relayed whole, in item 1, item 3 and
the rules invariant (4); the planner command's *"Read `.mcp.json`"* reworded so the whole-word check
runs on the whole definition, item 6's §5.4 sentence to match (5); the headless clause's invariant
(6); a module owing at least 20 documents for the slot measurement (7).

## Round 4 — 2026-10-21

**Summary judgment.** Round 3's seven are applied as the response says, and the brief (lines
7324–7552 at review time) now reads as one a build can be worked from: the fenced spawn prompt,
`background: true` on the orchestrator alone, the queue rule, the retry on the session's next
subagent report, one opening line per module, and the headless clause's invariant are all there,
and every citation I re-checked holds — `_SKILL_BODY` step 1 reads the status listing the no-module
rule needs, `_BATCH_SIZE` is stated in step 2 and step 6, `_ClaudeAgent.markdown` emits the five
lines item 2 names, `agent_scan.py` reads only an unindented `tools:` so a `background:` line
passes it, the consolidation skill's `SKILL.md` is the fenced shape item 1 copies, and §Q3, §Q4
and §Q8 say what the brief quotes. Two things remain that are not nitpicks: an invariant whose test
is red before its mutation, because the frontmatter grants the very names the body is checked for;
and the one documented difference between a forked and a spawned subagent other than the slot — what
it loads at start — which the brief does not mention, cost or steering. Five nitpicks beside them.

### Findings

1. **[IMPROVEMENT] The whole-word check "on the whole definition" is red before any mutation.**
   Item 2 (lines 7404–7405) and the seventh invariant (lines 7507–7508): *"It names no built-in
   tool as a whole word, the check run on the whole definition"*. The definition's frontmatter
   lists `Agent`, `Bash` and `Read` under `tools:` (`zikaron/install/entries.py` lines 518–532), so
   `re.search(r"\bRead\b", definition)` — the form `test_no_claude_code_tool_name_as_a_whole_word`
   takes — matches the grant on the unmutated build, and putting *"Read `.mcp.json`"* back then
   reddens nothing that was not red. The build will read "definition" as "body" and move on, but
   the invariant is the specification and should say so. **Suggested change**: in both places,
   *"the check run on the definition's body, everything after the frontmatter"*, with the
   existing four `TestThePromptsNameNoTool` tests parametrized over that body — preamble plus
   rendered loop — rather than over `ORCHESTRATOR_PROMPT` alone, which after this build is the
   preamble only.

2. **[IMPROVEMENT] What a spawned orchestrator loads at start, which the fork did not, is
   unstated.** "What was found" (lines 7351–7354) names one consequence of spawning over forking:
   the slot. The research corpus records a second. `research/claude-code-background-subagents.md`
   §Q8(b) line 405 quotes the skills page: a forked skill's subagent *"starts with that content
   and the agent's own system prompt, and none of your CLAUDE.md files"*; for an Agent-tool
   subagent the note says only *"What else loads follows the agent's own startup context"*, and
   `research/m40-toy-run.md` §1 lines 65–67 saw a documenter — already an Agent-tool subagent —
   cost half LeibaTrader's *"under another model and in a project with no `CLAUDE.md`; which of
   the two accounts for it is not separated"*. So the project's `CLAUDE.md` is, on the docs' own
   contrast, what a spawn may add to the orchestrator's startup context. Two consequences the
   brief should state rather than let a field run find: **cost** — that file, once per run, in
   the cached prefix of the agent §5.4 already calls *"most of a run's cost"* (this repository's,
   with its `FINDINGS.md` import, is about 70 KB; the three real projects' are unmeasured); and
   **steering** — a project's standing instructions reach an agent that holds `Bash`, whose only
   bound on writing is its prompt (§5.4, §8). Neither is a reason not to spawn; both are reasons
   to say so. **Suggested change**: one sentence in "What was found" or item 2 — a session-spawned
   subagent's startup context is the harness's, which for a fork excluded the project's
   `CLAUDE.md` (§Q8(b)) and for a spawned agent is unmeasured here — and a cheap probe in
   done-when 5 or the note: the test project's `CLAUDE.md` carries one line asking any agent that
   reads it to open its report with a given word, and the orchestrator's report says whether it
   loaded it. What it shows goes in the probe note and, if it loads, in §5.4's paragraph on what
   a subagent is handed at start (code-knowledge.md lines 743–748, beside the policy's 2,900
   characters). Not the live test, whose docstring rightly excludes what a model says.

3. **[NITPICK] The glob-and-slice predicate is stated twice and the two do not meet.** Item 3's
   second bullet (lines 7426–7428): *"need a run of one module, named or the whole project"*, then
   *"a run of several modules — named, or registered — that carries one is refused"*. A no-module
   run in a project with exactly one module registered is a run of one module that is neither
   named nor the whole project, so the first clause refuses it and the second does not. State the
   predicate once: *"a run that names two or more modules, or names none and finds any
   `code-knowledge/<module>` registered, refuses a glob or a slice before the planner first
   runs"*.

4. **[NITPICK] Step 8's body for a run of several modules is left to the build.** Item 3's first
   bullet (lines 7421–7423) places the opening lines and nothing else; the counts, the items given
   up on, `unverifiable`, `git_mode_effective`, `foreign`, `unplaceable` and `skipped` are all
   per module. One clause: *"then step 8's content for each module, in the same order"*.

5. **[NITPICK] `$ARGUMENTS` with nothing after the skill name is assumed, not measured.** Item 1
   (lines 7375–7376): *"an empty line is the no-arguments case"*. §Q8(e) says only that it
   *"always expands to the full argument string as typed"*, and `research/forked-skill-probe.md`
   substituted it with arguments given. Done-when 4 invokes with none, so it measures this; say so
   in item 5's caveat, so an orchestrator that stops on `--module $ARGUMENTS: no such directory`
   is read as that finding and not as a defect in the loop.

6. **[NITPICK] The tests that read the loop from Claude Code's skill are not named.** Item 5
   (lines 7458–7459). `tests/test_install_code_knowledge.py` parametrizes the loop's phrase tests
   over `[_CLAUDE_SKILL, _KIRO_SKILL]` — labels (lines 242–246), the batch (297), the bounded
   planner (311), the corpus (322), nesting (331), the report line (338), `over_size_cap` (365) —
   and `tests/test_code_knowledge_reminder.py` lines 151–156 render the skill with
   `fork_agent=None` to read the corpus's naming; after the build Claude Code's skill holds none
   of that. One sentence: the loop's tests run over the two loop texts, kiro's skill and the
   orchestrator's body, and the reminder test reads whichever function renders the loop. The gate
   finds it either way; the sentence saves the build a surprise.

7. **[NITPICK] Done-when 5's slot leg needs three conditions it does not state.** Lines
   7535–7538. The loop states the batch in step 2's `<n>` line and step 6's dry-run `--limit`, so
   say the hand edit is step 2's alone; say the session has no other subagent of its own out when
   the first batch goes, since one Explore agent makes 1 + 20 + 1 and a refusal whichever way the
   question falls; and say the project is re-installed after, so the 20 does not outlive the
   measurement.

VERDICT: NEEDS_CHANGES

### Author response to round 4

- **1**, **3**–**7**: applied as suggested — the whole-word check on the definition's body, and
  `TestThePromptsNameNoTool` over it; the glob-and-slice predicate stated once, in the reviewer's
  words; step 8's content per module after the opening lines; `$ARGUMENTS` with nothing after the
  name named in item 5's caveat; the loop's tests and the reminder test's read named in item 5; the
  slot leg's three conditions.
- **2**: declined on a measurement. The premise is that a fork's subagent started without the
  project's `CLAUDE.md`, so a spawn would add it. LeibaTrader's forked orchestrator of 2026-10-20
  (`agent-aa8f578d1a4d31fe1`, the run `research/m40-toy-run.md` §14 prices) carries the file in two
  of its request records, *"Contents of /home/nathan/Trading/LeibaTrader/CLAUDE.md"* — the docs'
  "none of your CLAUDE.md files" did not hold for it — so the fork already paid the cost and carried
  the steering, and spawning changes neither. The field run's project has no `CLAUDE.md`, which is
  why its fork's records quote none.

## Round 5 — 2026-10-21

**Summary judgment.** Round 4's six applied findings are in the brief as the response says (lines
7324–7561 at review time): the whole-word check on the definition's body with
`TestThePromptsNameNoTool` over it, the glob-and-slice predicate stated once, step 8's content per
module, the `$ARGUMENTS`-with-nothing caveat, the loop's tests named, and the slot leg's three
conditions; finding 2's decline rests on a measurement and stands. The rendered-loop invariants
hold on inspection — `\bzikaron_` cannot match inside `mcp__zikaron__zikaron_…` since `_` is a word
character, `GLOB` is not a whole-word `Glob`, and nothing a session runs imports
`zikaron/install/` (`zikaron/doctor/checks.py` does, as a command). One thing I should have caught
when I proposed it in round 1 is wrong in a way a build would pin into both loop texts: the
no-module rule derives the module from the corpus's *name*, and the registry lower-cases every
name on write. Beside it, five nitpicks.

### Findings

1. **[BLOCKER] The no-module rule reads the module off a name the registry has lower-cased.** Item
   3's first bullet (lines 7417–7422): *"where knowledge bases named `code-knowledge/<module>` are
   registered, the run documents each of those modules in turn"* — the module being, as round 1
   put it and the brief now implies, the name after `code-knowledge/`. KB names are *"lower-cased
   on write, and the lower-cased form is what is stored, matched and"* returned
   (`design/knowledge-index.md` §3.1 lines 70 and 99, K12; `zikaron/core/knowledge/registry.py`
   lines 86–107), while the planner lower-cases nothing — no `.lower()` under
   `zikaron/core/code_knowledge/` or `zikaron/code_knowledge/` but the reminder's path compare. So
   `Sources/App`, `Assets`, `src/Components` — ordinary in C#, Swift, Unity and React trees — is
   registered as `code-knowledge/sources/app`, and the plain-words run passes the planner
   `--module sources/app`: on Linux, D35's first platform, *no such directory*
   (`zikaron/code_knowledge/main.py` line 130), which item 3's third bullet reports and skips, so
   every such module is skipped on every *"update the code documentation"* — the motivating
   prompt — with a report that blames a rename that never happened; on macOS the directory
   resolves and the planner writes documents and `zikaron-source` lines under the lower-cased
   path, which K14's byte-exact path compare (`design/knowledge-index.md` line 224, line 444) does
   not match against git's casing. Not a conceived edge: a capital letter in a source directory
   on Linux. **Suggested change**, one clause, in the vocabulary step 1 and step 7 already use:
   the module of a registered corpus is its `root_path` — which step 1's status listing carries
   and the nesting check already reads — with `<root>/code-knowledge/` stripped, never its name;
   a `code-knowledge/…` corpus whose `root_path` does not lie under `<root>/code-knowledge/` is
   another directory's, reported as step 7 reports it, and passed over as the third bullet passes
   a refused module. Then the rules invariant's no-module phrase pins `root_path` (mutation: the
   module taken from the name), and done-when 5's one-documented-module leg runs on Linux with a
   module whose path carries a capital letter, so the leg can tell the two apart.

2. **[NITPICK] One row the build must rewrite is outside both the normative list and done-when 2's
   predicate.** `design/harness.md` §"What a Claude Code install writes", the *Code orchestrator*
   row (line 632): *"YAML frontmatter with `effort: high` and `tools:` … prompt as body"*. After
   item 2 it carries `background: true` and the loop as body; the row says nothing about forking,
   one run at a time or 19, so done-when 2's predicate does not reach it, and no test reads that
   table. Add it to the Normative paragraph beside the documentation skill's row.

3. **[NITPICK] "Another run" cannot hold this session's slots under the brief's own queue rule.**
   Item 3's throttling bullet (line 7437): *"another run, or any agent the session runs, may hold
   the slots"*. Item 1's fourth bullet keeps a second run of this session's off the subagents
   until the first reports, and the limit the field run met is the session's own — the second
   session in that project is not what refused the 18. *"any other agent the session runs"* says
   what remains.

4. **[NITPICK] A run of several modules spends one orchestrator context on all of them, and the
   brief does not say what that costs.** Item 3's first bullet; item 6's §5.2 rewrite. §5.2 step
   2 prices the orchestrator's context at about 2,000 tokens a document, 45,000 to 432,000 over
   198, and under M40 each module's run was a fork of its own; the no-module run folds every
   registered module into one. Cheap where little moved, which is the update case — but a sentence
   in item 6 should say so, and that a project whose several modules are all stale is cheaper
   asked module by module, so the cost is stated where the rule is.

5. **[NITPICK] The whole-project corpus already registered takes the right branch by accident of
   wording.** Item 3's first bullet names `code-knowledge/<module>` corpora and *"where none is,
   the whole project"*; a project documented whole has `code-knowledge` registered and no
   `code-knowledge/<module>`, so the branch is the whole project, as it should be, and the nesting
   check passes since the root corpus's `root_path` is that directory itself. One clause saying
   the root corpus means the whole project is documented, and is updated by that branch, keeps a
   build from treating it as a third case.

6. **[NITPICK] The description invariant's mutation may not redden its test.** Line 7509:
   *"The orchestrator's description lets the session spawn it (*"never directly"* put back)"* — a
   test asserting the new phrase's presence stays green with the old sentence put back beside it.
   Make the mutation *"the new description replaced by the old"*, or have the test assert both.

VERDICT: NEEDS_CHANGES

### Author response to round 5

All six accepted and applied: each registered module read from its corpus's `root_path` with
`<root>/code-knowledge/` stripped, never from the lower-cased name, a corpus rooted elsewhere
reported and passed over, the invariant pinning it and done-when 5's leg run on Linux with a capital
letter in the module's path (1); the code orchestrator's row in `design/harness.md` added to the
normative list (2); *"any other agent the session runs"* (3); the cost of one orchestrator over
several modules in item 6's §5.2 rewrite (4); a project documented whole updated by the
whole-project branch (5); the description mutation as the old put back in place of the new (6).

## Round 6 — 2026-10-21

**Summary judgment.** Round 5's six are applied as the response says (lines 7324–7574 at review
time): the module read from `root_path` with `<root>/code-knowledge/` stripped, a corpus rooted
elsewhere passed over, the harness row in the normative list, *"any other agent the session runs"*,
the several-modules cost in item 6, the root corpus on the whole-project branch, and the
description mutation as a replacement. Every claim I re-checked this round holds: the three
`design/harness.md` rows the normative paragraph names are lines 95, 632 and 633 and its
consolidation paragraph is 303–307; every passage in `zikaron/`, `tests/` and `design/` that says
"fork" is either in the normative list, in item 4's docstrings, or reached by done-when 2's
predicate; the rendered Claude Code loop's only whole-word built-in is the `Read` item 2 rewords,
and no backticked kiro name or `\bzikaron_` token survives rendering; the ten invariants' mutations
each redden a distinct assertion; the planner's refusals (`zikaron/code_knowledge/main.py` lines
130–151) include the one the refused-module rule names; and the probe note supports the one
decision it is cited for. What remains is one user-facing consequence the brief derives for the loop
text and not for the README sentence that now contradicts it, and three nitpicks.

### Findings

1. **[IMPROVEMENT] The README's standing rule on globs becomes a rule the product's own plain
   update breaks, and item 6 does not reach it.** `README.md` lines 740–741: *"**Pass the same
   `--include` and `--exclude` every time** you document a directory: they are part of what it is,
   and a narrower set makes the planner remove the documents it no longer admits."* Item 3's
   second bullet (lines 7434–7438) derives the consequence for the loop — *"a module first
   documented with `--include` or `--exclude` is documented more widely unless it is named alone
   with them"* — and item 6 (lines 7493–7496) asks the README only for *"what no module means"*;
   done-when 2's predicate (fork, one run at a time, 19) does not reach line 740. The case is the
   README's own example, line 720's `--exclude '*_generated.go'`, met by the motivating prompt:
   the plain update documents every generated file at a documenter each, and the next run naming
   the module with its `--exclude` **removes** those documents under the planner's narrower-set
   rule, so alternating the two rewrites that set each way, every time. Recording the globs is
   fenced and I do not re-open it; what the user needs is to be told. **Suggested change**: item 6
   names the passage — the README's glob rule says that a module documented with globs is updated
   by naming it with them, that the plain update passes none and documents such a module in full,
   and that the next run naming it with its globs removes what the update added — and the loop's
   report line for a no-module run says *"globs: none"* per module, so the widening is visible
   where it happens (one clause in item 3's first bullet; the rules invariant's phrase list gains
   it, mutation: dropped).

2. **[NITPICK] The refused-module rule keys on one message, and the planner prints five.** Item 3's
   third bullet (lines 7439–7442): *"one the planner refuses, as no such directory"*.
   `zikaron/code_knowledge/main.py` lines 130–151 refuse *no such directory*, *is not a
   directory*, *outside the project*, *under a pruned directory* and *documents contains module*;
   a build that matches the sentence would skip on one and stop on the rest. Say *"one the planner
   refuses, whatever its reason — a registered module renamed or removed since it was documented
   is *no such directory*"*, and that a planner that fails to run at all — no JSON, as when
   `<zikaron>` is not there — stops the run as now, so a run of several does not repeat the same
   failure per module.

3. **[NITPICK] "For what that run had left" does not say what the re-invocation carries.** Item 1's
   fifth bullet (lines 7387–7388) and item 3's throttling bullet (lines 7448–7450, *"invoking the
   skill again resumes where this run stopped"*). The session has the report's opening lines, one
   per module, and the request as given; the brief should pick: *the request repeated as given*,
   a module already up to date costing one planner run, is the simple one, and the rules
   invariant's *"answers a contention stop"* then means that.

4. **[NITPICK] §5.2's invocation line is outside both item 6 and done-when 2's predicate.**
   `design/code-knowledge.md` lines 470–477 give `/zikaron-document-code <module> …` as *"the one
   form the skill's body, `README.md` and the toy run's prompt use"*; after item 3 the module is
   optional and repeatable, and the sentence says nothing of forks, one run or 19. Add *"and its
   invocation line"* to item 6's §5.2 clause.

VERDICT: NEEDS_CHANGES

### Author response to round 6

All four accepted and applied: the README's glob rule named in item 6 with the three consequences,
and *"globs: none"* on a no-module run's opening line per module, in item 3 and the rules invariant
(1); any planner refusal skipped in a run of several, a planner that prints no JSON stopping the run
(2); the request repeated as given after a contention stop (3); §5.2's invocation line in item 6 (4).

## Round 7 — 2026-10-21

**Summary judgment.** Round 6's four are applied as the response says (lines 7324–7582 at review
time): the README's glob rule with its three consequences in item 6, *"globs: none"* in item 3 and
the rules invariant, the refused-module rule widened to any planner refusal, the request repeated as
given after a contention stop, and §5.2's invocation line in item 6. Everything else I re-checked
holds: `background` is a documented field of a subagent definition (§Q3 lines 254–256), `$ARGUMENTS`
is a general skill feature and not a fork's (§Q8(e)), the consolidation skill's fenced prompt is the
shape item 1 copies, `-p` waits at exit for background work under the ceiling (§Q4), the planner's
`_count` accepts `--limit 0`, every `fork` under `zikaron/` is in a docstring or the forking parameter
item 4 removes, `experiments/m40_run_cost.py` classifies by `"Base directory for this skill:"` as
done-when 5 says, and the probe note supports the one decision it is cited for. What remains is two
rules in item 3 whose discriminator, as the brief states it, a build would pin into the loop text
wrongly — the loop text being the product — each a clause to fix, and two nitpicks.

### Findings

1. **[IMPROVEMENT] The refused-module rule's two cases are told apart by a sign both of them
   share.** Item 3's third bullet (lines 7441–7446): a module *"the planner refuses, whatever its
   reason"* is skipped, while *"a planner that fails to run at all, printing no JSON, stops the
   run"*. `zikaron/code_knowledge/main.py` lines 201–233: a `--module` refusal prints
   `refused: --module …` on standard error, exits 1 and prints no JSON (lines 211–213) — and so
   does a store-less project's refusal (206–208), a configuration error (219–221), a `failed: …`
   from the walk (230–232), and `<zikaron>` not found, which is the shell's 127. So "no JSON" and
   "non-zero exit" each describe both cases: a loop keyed on no JSON stops on every refused module,
   which makes the rule round 6 added a no-op, and one keyed on the exit code skips a store-less
   project once per module and reports every module refused. What tells them apart is the prefix.
   **Suggested change**: *"one the planner refuses — its standard error opening `refused:`, exit 1
   and no JSON — whatever the refusal's reason …"* and *"any other non-zero exit — a `failed:`, a
   store-less project's refusal, or `<zikaron>` not found — stops the run as now"*; the rules
   invariant's *"a refused module skipped in a run of several"* pins the `refused:` prefix (mutation:
   the prefix dropped, so any non-zero exit is skipped).

2. **[IMPROVEMENT] The throttling rule's `--limit` after a batch that starts none reaches step 4's
   stop before it reaches the batch of one.** Item 3's fourth bullet (lines 7447–7454): *"runs the
   planner with `--limit` the number that started, plus the items given up on"*, then *"A batch that
   starts none … is followed at once by a batch of one"*. When none started the first sentence gives
   `--limit 0` plus the given-up items, which `_count` accepts; the planner then lists nothing, or
   only the items given up on, and step 4's rule — *"Stop when … a run lists no `work` and no
   `readme`, or lists only items you have given up on"* (`_SKILL_BODY` lines 381–382) — ends the
   run as finished, not up to date, with no contention report, so the session never repeats the
   request. That is the field run's failure class, a run that ends early on contention, which this
   rule exists to prevent; the second sentence says what is meant, but a loop text written from the
   first is what a model follows. **Suggested change**: *"`--limit` the number that started — or 1,
   when none did — plus the items given up on"*, and that a batch of one refused is reported as the
   contention stop and never as step 4's end; the rules invariant's *"the throttling rule"* names the
   *"or 1"* clause (mutation: dropped).

3. **[NITPICK] `zikaron/install/code_knowledge.py`'s module docstring makes a claim done-when 2
   does not reach.** Lines 9–11: *"Neither agent's prompt names a tool (§5.4) … which is why
   neither is rendered."* After item 2 the orchestrator's definition is rendered and names Zikaron's
   verbs. The same docstring says "forks" at line 13, so item 4's clause reaches the file, but the
   sentence is a separate claim; say in item 4 that it goes too.

4. **[NITPICK] The kiro-gaps row's closing column names a route that no longer closes anything.**
   `design/kiro-gaps.md` line 24: *"a kiro subagent that can spawn, or a kiro skill that runs in a
   context of its own"*. Once nothing forks, only the first closes the gap; item 6 should say the
   row's closing column keeps the subagent alone.

VERDICT: NEEDS_CHANGES

### Author response to round 7

All four accepted and applied. 1: checked in `zikaron/code_knowledge/main.py` — every `_layout`
refusal prints `refused: ` and, for the module, `--module …`, while the store-less, configuration
and walk failures print other text — so the skip keys on standard error opening `refused: --module`,
any other failure stopping the run, and the invariant pins the prefix. 2: *"or 1, when none did"*,
the refused batch of one reported as the contention stop and never as step 4's end, the invariant
naming the clause. 3: the module docstring's claim named in item 4. 4: the kiro-gaps row in item 6.

## Round 8 — 2026-10-21

**Summary judgment.** Round 7's four are applied as the response says (lines 7324–7588 at review
time), and the discriminator they fixed is right against the code: `zikaron/code_knowledge/main.py`
prints `refused: --module …` for every `_layout` refusal of the module (lines 130–141), `refused:
--documents …` for the documents directory, `refused: no Zikaron store in …` for a store-less
project (`zikaron/project/resolve.py` line 160), a rendered error for configuration, and `failed:
…` from the walk — so the skip on `refused: --module` and the stop on everything else are what the
planner actually prints. Everything else I re-checked holds: `$ARGUMENTS` expands to the argument
string as typed and `/skill-name` in a `-p` prompt is expanded before the run
(`research/claude-code-background-subagents.md` §Q8(c), (e)); `background: true` is a documented
definition field (§Q3); `-p` forwards subagent messages at every nesting depth (§Q8(g)), so item 5's
identification by the spawn's id has a measured basis; the hook's reminder silences the orchestrator
by `agent_type` (`zikaron/hook/reminder.py` lines 31–33), which a session-spawned subagent carries as
its `subagent_type`, so nothing a session imports moves; the batch arithmetic (1 + 18, then 1 + 1 +
18) matches `research/m40-toy-run.md` §13's straggler; and the probe note supports the one decision
it is cited for. What remains is one leg done-when 5 does not run and one clause a build would read
two ways.

### Findings

1. **[IMPROVEMENT] Done-when 5 never runs the plain-words request that names a module — the one
   path where a dropped argument now starts a whole-project run.** Lines 7562–7569 test plain words
   with nothing named, twice, and the slash form with a module. Two decisions of this brief meet on
   the untested path: the session hands the fenced prompt over *as written* (item 1, round 3's
   finding 1, which exists so that a glob is never paraphrased), and an empty argument line means
   every documented module or else the whole project (item 3). So a user who says *"document the
   code under `src/Billing`"* in plain words is served correctly only if the session's model puts
   `src/Billing` into the `Skill` tool's arguments; if it invokes the skill bare, `$ARGUMENTS` is
   empty, the launcher forbids the session to add what the user said, and the orchestrator documents
   the whole project — a documenter per file, in a repository of any size — reporting it as the
   no-module run it was asked for. Nothing in the research corpus records how a model-invoked skill
   receives arguments (§Q8(e) covers `$ARGUMENTS` for a typed invocation), so this is unmeasured on
   the brief's own terms, and the field run's two invocations were slash commands. **Suggested
   change**: one more leg in done-when 5 — the request in plain words naming one module, in the
   project that has one documented (the capital-letter leg already there can carry it: *"update the
   documentation of `Sources/App`"*), passing when the report's opening line names that module
   alone and no `code-knowledge` root corpus appears. Measure first; if the argument is dropped,
   the cheap fix is one clause in the launcher — a request that named a module, directory, glob or
   slice the line below does not carry is invoked again with them as the skill's arguments, never
   handed over as an empty line — with its invariant (mutation: the clause dropped).

2. **[NITPICK] "Where none is registered" does not say whether a passed-over corpus counts.** Item
   3's first bullet (lines 7424–7427): a `code-knowledge/…` corpus whose `root_path` lies outside
   `<root>/code-knowledge/` is *"reported … and passed over"*, then *"Where none is registered, the
   module is the whole project"*. A build can read "none" as "none at all" — the passed-over ones
   are registered, so the run reports them and documents nothing — or as "none that was not passed
   over", so it falls through to the whole project. The case is a project directory moved with its
   `.zikaron/` (`root_path` is stored absolute, `design/knowledge-index.md` line 2768), where every
   module corpus is then another directory's: the second reading documents the whole project over
   the modules' own documents directory and registers `code-knowledge` beside the stale corpora.
   State the first: *"a passed-over corpus is registered all the same, so a run that passes over
   every one documents nothing and says so"*. The rules invariant's *"both of its branches"* then
   covers it with no new mutation.

VERDICT: NEEDS_CHANGES

### Author response to round 8

- **1**: the leg added to done-when 5, without the speculative clause, on a measurement the
  premise missed: the field run's invocations were not slash commands. The user typed *"Document
  module `go`"* and *"Document module `console`"* in plain words, and the session's model called
  `Skill` with `args: "go"` and `args: "console"` — a module named in plain words reached the
  skill's arguments. The leg confirms it on the new skill, and says what the clause would be if it
  did not.
- **2**: applied — a passed-over corpus is registered all the same, so a run that passes over every
  one documents nothing and says so.

## Round 9 — 2026-10-21

**Summary judgment.** Round 8's two are applied as the response says (lines 7324–7594 at review
time): the plain-words leg naming a module is in done-when 5 with the field run's `args: "go"`
measurement beside it, and the passed-over corpus is "registered all the same". Everything I
re-checked this round holds: `$ARGUMENTS` is substituted into the skill content as typed
(`research/claude-code-background-subagents.md` §Q8(e), lines 456–459), `background: true` is a
documented definition field (§Q3, lines 254–256), `_SKILL_DESCRIPTION` is one text on both
harnesses (`zikaron/install/code_knowledge.py` lines 270–275), the consolidation skill's fenced
prompt is the shape item 1 copies, `_CLAUDE_CODE_TOOLS` (`tests/test_install_code_knowledge.py`
lines 50–65) is the whole-word list and nothing capitalized in the loop but the `Read` item 2
rewords matches it, a corpus's `root_path` is stored as `str(spec.root)` with its case
(`zikaron/core/knowledge/database.py` line 86) while only the name is lower-cased, and
`design/overview.md`'s D39 row (line 219) says "forks to", so done-when 2 reaches it by meaning.
The brief is buildable as written. What remains is one measurement that cannot fail — the leg
round 8 asked for, in the form I proposed it, which was wrong — and one tally.

### Findings

1. **[IMPROVEMENT] The plain-words-naming-a-module leg passes whether or not the argument reaches
   the skill, so it measures nothing.** Done-when 5, lines 7570–7575: *"in that project, a
   plain-words request naming that module, which passes when the report opens with that module
   alone and no `code-knowledge` root corpus appears"* — "that project" being the one *"with one
   module documented"* (line 7568). Walk both outcomes through item 3's no-module rule (lines
   7419–7428). Argument delivered: the run names the module, the report opens with it alone. Argument
   dropped: `$ARGUMENTS` is empty, the orchestrator finds one `code-knowledge/<module>` registered,
   documents *every* documented module — that same one — and the report opens with it alone, no
   root corpus created since the registered-modules branch never takes `.`. The pass condition is
   met either way, and the brief's own sentence on line 7574 — *"were the argument dropped, a bare
   invocation would document every module"* — says so once "every module" is read in a one-module
   project. This is my error from round 8, which placed the leg there. **Suggested change**: move
   the leg to where the two outcomes differ — the simplest is the two-modules project of the leg's
   first clause, once both are `up_to_date`: a plain-words request naming one of the two, passing
   when the report opens with one line, that module's, and a dropped argument would open with two
   (and run the planner twice). Or keep the Linux project and name a directory *not yet*
   documented there, passing when the report's line names it and not the documented one. Either
   way drop *"and no `code-knowledge` root corpus appears"*, which no outcome in a project with a
   module documented can produce.

2. **[NITPICK] "Three places" becomes a count the build falsifies.** Item 3's first bullet (lines
   7433–7435) adds a sentence that differs per harness — where the arguments come from — beside the
   spawn instruction and the planner command, so the loop now differs in a fourth place.
   `design/code-knowledge.md` §5.2 lines 543–547 (*"The skill's text differs per harness in three
   places"*, listing the frontmatter lines among them, which item 1 removes) and the module docstring
   (`code_knowledge.py` line 13, *"differs per harness in three places"*) both carry the tally;
   item 4 reaches the docstring through its "forks" and item 6 reaches §5.2 as a whole, but neither
   says the sentence is restated. One clause in item 6: the per-harness-differences sentence names
   the places — the spawn instruction, the planner command's file, the arguments sentence — and
   states no count (`CLAUDE.md`: the predicate, never the tally).

VERDICT: NEEDS_CHANGES

### Author response to round 9

Both accepted and applied: the leg moved to the two-module project once both are `up_to_date`,
passing on one opening line, the named module's, where a dropped argument would open with two, and
the root-corpus clause dropped (1); item 6's §5.2 clause names the places the text differs per
harness and states no count (2).

## Round 10 — 2026-10-21

**Summary judgment.** Round 9's two are applied as the response says (lines 7324–7598 at review
time): the plain-words-naming-a-module leg now runs in the two-module project and passes on one
opening line where a dropped argument would give two, and item 6's §5.2 clause names the places
and states no count. What I re-checked this round holds: the batch test asserts the literal
(`tests/test_install_code_knowledge.py` line 315, *"`<n>` is 19 plus"*), so `_BATCH_SIZE` back at
19 reddens it once the text says 18; `zikaron/hook/reminder.py` lines 28–33 hold *copies* of the
two agent names rather than importing the installer, and `zikaron/doctor/checks.py` is the only
non-install importer, so "nothing a running session imports" is true; the install writes no
`.gitignore`, so the toy project's whole-project walk has exactly the three sources item 5 counts;
step 1's nesting check is symmetric (*contains … or lies inside*), so a project documented whole
can never also hold a `code-knowledge/<module>` corpus, which makes item 3's two no-module branches
exclusive rather than a third case; the consolidation skill's fenced prompt is the shape item 1
copies; and `design/kiro-gaps.md` line 24 and `design/overview.md` line 219 both say "forks" and
are in the normative list. The brief is buildable as written. What remains is three one-sentence
gaps — a refused module that the relayed summary never shows, a contract between the loop and the
planner's stderr that nothing in the gate holds, and the harness's own *"Do not retry"* which the
loop now contradicts without saying so — and two nitpicks.

### Findings

1. **[IMPROVEMENT] A refused module gets no opening line, so the relayed summary omits the one
   thing the user must act on.** Item 1's relay bullet (lines 7390–7391): *"its opening lines, one
   per module the run documented"*; item 3's first bullet (lines 7430–7432): *"the report opens
   with one line per module … in step 8's form"*, where step 8's form names the module, whether it
   is up to date and its corpus. Item 3's third bullet (lines 7442–7448) has a refused module
   *"reported"*, its corpus and documents *"the user's to remove"* — in the body. The opening lines
   exist because *"the session that receives the report may pass on only its first line"*
   (`_SKILL_BODY` step 8), and item 1 tells the session to relay exactly those lines; a module
   that was not documented has none, so on the motivating path — *"update the code
   documentation"* over three modules, one renamed — the user is shown two lines and never learns
   the third was skipped or that a stale corpus is theirs to remove. **Suggested change**: item 1
   and item 3 both say *"one per module the run was asked for, a refused module's line saying it
   was refused and why"*, and the rules invariant's *"the report opening with a line per module"*
   (line 7546) covers the refused one (mutation: the refused module's line dropped from the loop).

2. **[IMPROVEMENT] The `refused: --module` prefix is a contract between two texts that nothing in
   the gate holds together.** Item 3's third bullet (lines 7442–7444) and the rules invariant
   (lines 7548–7549) pin the loop's side: the skip keys on standard error opening
   `refused: --module`. The planner's side is composed in two places —
   `zikaron/code_knowledge/main.py` line 212 prints `refused: ` before whatever `_RefusedError`
   carried, and lines 130–141 build the `--module …` half — and the only test of that refusal,
   `tests/test_code_knowledge_command.py` line 703, asserts *"no such directory"* alone. A later
   rewording of either half — `refused: module absent` would be an ordinary tidy — leaves the loop
   stopping every run of several on the first renamed module, green throughout. The planner is
   fenced and need not move: this is a test. **Suggested change**: item 5 adds a test that runs the
   planner against an absent module and asserts its standard error opens with the exact prefix the
   loop names — the literal taken from one constant both the loop text and the test read, or read
   out of the rendered loop — with its mutation (the planner's `refused: ` or `--module` reworded
   in memory), listed under the rules invariant's refused-module phrase.

3. **[IMPROVEMENT] The harness's refusal says *"Do not retry"*, and the loop now says to keep
   going without naming the contradiction.** Item 3's throttling bullet (lines 7449–7456). The
   refusal the orchestrator reads is, verbatim, *"Concurrent subagent limit reached. You can run 20
   subagents at once. Do not retry."* (spec §5.2 step 1; the probe note §1). The loop's rule —
   wait, re-run the planner with a smaller `--limit`, spawn the same items again — is exactly what
   that sentence forbids, read literally, and the orchestrator's prompt says only that the
   *planner's* output and the *documenters'* answers are data, not the harness's tool results.
   `research/m40-toy-run.md` §13 is evidence that one refusal per batch did not stop a run, so the
   model already weighs the loop over the harness text at n=1; whether it does at 17 of 18 — the
   field run's shape, and the operator's *"it shouldn't give up"* case — is unmeasured, since the
   field run's orchestrator was in the foreground and never reached the next batch. One sentence
   in the loop removes the model's choice. **Suggested change**: the throttling bullet adds *"the
   harness's refusal says not to retry, and nothing here retries a spawn: no spawn is made again,
   the item is listed by the next planner run as step 4 says, and is spawned in a later, smaller
   batch"*; the rules invariant's *"the throttling rule with its 'or 1'"* (line 7550) names this
   clause too (mutation: dropped). And done-when 5's slot leg (lines 7578–7583) is the one leg that
   produces a refusal: say that it also reads whether the orchestrator ran the next planner batch
   after it, so the rule's *continue* half is measured once by the same run.

4. **[NITPICK] "What was found" states the slot as fact where done-when 5 measures it.** Lines
   7352–7355: *"A spawned orchestrator holds a slot the fork did not … where a subagent the session
   spawns is one of the 20 like any other."* Item 3 acts on it (*"which a spawned orchestrator now
   holds"*) and done-when 5 decides it (*"one spawn of that batch refused says it does and 18
   stands, none says it does not and 19 returns"*), which is the right structure; the first
   sentence alone reads as measured. Reword: *"… where a subagent the session spawns is, on the
   documentation's wording, one of the 20 like any other — which done-when 5 measures"*.

5. **[NITPICK] Item 6's cost sentence prices the no-module run in an orchestrator's context, and
   under kiro there is none.** Lines 7493–7496: *"a run of several modules spends one
   orchestrator's context on all of them, about 2,000 tokens a document as §5.2 prices it"*. The
   rule is on both harnesses (item 3), and under kiro the loop runs in the user's session, whose
   context the run then spends — smaller, since §5.2 says kiro's subagent results carry none of
   the framing that made 2,000, and unmeasured. One clause: *"— the orchestrator's under Claude
   Code, the session's own under kiro, where the per-document cost is unmeasured —"*.

VERDICT: NEEDS_CHANGES

### Author response to round 10

All five accepted and applied: an opening line per module the run was asked for, a refused one's
saying it was refused and why, in items 1 and 3 and the invariant (1); a test reading the prefix
out of the rendered loop and asserting the planner's refusal opens with it, the planner untouched,
with its invariant (2); the *"Do not retry"* clause in the throttling bullet and the invariant, and
the slot leg reading whether the next batch followed a refusal (3); "What was found" says the slot
is the docs' wording, measured by done-when 5 (4); the cost sentence names kiro's session (5).

## Round 11 — 2026-10-21

**Summary judgment.** Round 10's five are applied as the response says (lines 7324–7609 at review
time): an opening line per module the run was asked for with a refused one's saying why, the
prefix test with its invariant, the *"Do not retry"* clause in the loop and the slot leg's read of
the batch after a refusal, the slot stated as the docs' wording, and kiro's session in the cost
sentence. What I re-checked this round holds: the planner's two halves of the prefix are literals
inside `main()` (`zikaron/code_knowledge/main.py` line 212, `stderr(f"refused: {refused}")`) and
`_layout()` (lines 130–141, every module refusal opening `--module `), printed through
`zikaron.project.messages.stderr`, and `tests/test_code_knowledge_command.py`'s `_refused` (lines
91–96) already drives the planner in-process under `capsys`, so the prefix test is buildable as
written; `research/nested-subagent-probe.md` lines 11–15 saw an Agent-tool subagent that *"returned
'running in the background' first"* under `-p` with its grandchild's messages carried under the
call's `parent_tool_use_id`, so item 5's identification has a headless measurement behind it;
`background` is a documented definition field (§Q3 lines 254–256) and `-p`'s idle ceiling is lifted
by the variable the live test already sets (`tests/test_code_knowledge_claude_live.py` line 190);
step 4 says what the throttling bullet attributes to it (*"the next run lists the item again"*,
`_SKILL_BODY` lines 376–378); every passage in `design/`, `README.md` and `tests/` that says fork,
one run at a time or 19 is in the normative list, in item 4 or 6, or reached by done-when 2's
predicate, and nothing in `CLAUDE.md`, `.claude/`, `.kiro/` or `experiments/` says "fork". The brief
is complete in itself and buildable; the probe note supports the one decision it is cited for.
Three one-clause nitpicks remain, none of which changes what the build does.

### Findings

1. **[NITPICK] The launcher makes a refused spawn again, against the same harness text the loop now
   defers to.** Item 1's fifth bullet (lines 7385–7387): *"a spawn refused because too many
   subagents are running is made again when the session's next subagent reports"*. Round 10's
   finding 3 gave the loop a sentence reconciling its rule with the refusal's verbatim *"Do not
   retry"*, because the model reads both; the session reads both too, and the launcher says nothing.
   Rare — it needs the session's own twenty slots held by other agents — and a model that obeys the
   harness instead falls to the bullet's second half and tells the user, so the user is served
   either way. One clause: *"— the harness's refusal says not to retry, and this is not that: no
   spawn is made again at once, only when a report of the session's has freed a slot"*. The third
   invariant's *"retries a refused spawn"* already covers the sentence it sits in.

2. **[NITPICK] A passed-over corpus gets no opening line, the class round 10's finding 1 closed for
   a refused module.** Item 3's first bullet (lines 7426–7428): a `code-knowledge/…` corpus rooted
   outside `<root>/code-knowledge/` is *"reported as step 7 reports one and passed over … a run that
   passes over every one documents nothing and says so"*. Step 7's report is body text; item 1 has
   the session relay a report *"with its opening lines"*, and step 8 warns that the session *"may
   pass on only its first line"*. In the moved-project case round 8 named, every corpus is passed
   over, the report has no opening line at all, and what the session relays is whatever it makes of
   the body. One clause beside the refused module's: *"a passed-over corpus's line saying whose
   directory it is"*, so the opening-line rule has no module on the asked-for list without one.

3. **[NITPICK] The prefix test's mutation names no attribute, where every other mutation does.**
   Line 7560–7561: *"(the planner's `refused: ` or `--module` reworded in memory)"*. Neither half is
   a module attribute — both are literals inside function bodies (lines 212 and 130–141) — so a
   plugin cannot reword either by `setattr` on a constant, as it can `_BATCH_SIZE` or
   `ORCHESTRATOR_DESCRIPTION`. Say where it reaches them: *"`zikaron.code_knowledge.main.stderr`
   wrapped to reword the line, or `_RefusedError.__str__`"*. Half a sentence, and the *seen red*
   step in done-when 1 then has a mutation it can apply without discovering this first.

VERDICT: APPROVED

### Author response to round 11

The three nitpicks applied after the approval, as for M40-4's brief: the launcher's retry squared
with *"Do not retry"* (1); a passed-over corpus's opening line (2); the prefix test's mutation
naming `zikaron.code_knowledge.main`'s `stderr` (3).
