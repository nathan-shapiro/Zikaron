# Review — M40-4 build: the search reminder

Artifact: the M40-4 build in `/home/nathan/Zikaron-m40-4` (branch `m40-4-grep-reminder`, uncommitted
over `ac1a285`). Brief: `design/build-plan.md` §"M40-4 — A grep through a documented module, by an
agent that forgot its documents". The brief's own review is `reviews/m40-4-grep-reminder-review.md`
(APPROVED, round 7).

## Round 1 — 2026-10-21

**Summary judgment.** The build does what the brief says, and it does it cleanly: the seam field,
the hook's connect-only path, the parser extension, the service method with its receipt-time clear
and synchronous throttle, and the membership rule for a trigger two selections write are each where
the brief put them, and the normative sections state what the code does. I found no correctness
defect in the code; the live session, the mutation sweep and the invariant tests cover the brief's
list with one exception noted below. What keeps it from shipping as-is is a handful of
brief-alignment misses in the prose — a count written as the next number, an index row the brief
names left unamended — one filter asymmetry the documents do not admit, and the line's wording,
which the brief makes this review's to set.

**Findings.**

1. **[IMPROVEMENT] `README.md:365` writes the count the brief forbids.** The settings row now reads
   *"four hooks — session start, per-message, per-subagent, and after each search"*. Brief item 8
   names this exact sentence among the counts to be *"restated as its predicate, not as the next
   number"*, and the next change to the hook set will falsify "four" the same way M40-4 falsified
   "three". Edit: *"hooks for session start, each message, each subagent start and each search
   ([Code knowledge](#code-knowledge)) — plus both approval keys, `enabledMcpjsonServers` and
   `permissions.allow`"*.

2. **[IMPROVEMENT] `FINDINGS.md`'s D39 row carries no 2026-10-20 amendment.** Brief item 8:
   *"D39's amendment in `design/overview.md` and `FINDINGS.md`"*. `design/overview.md` D39 now
   has it; the worktree's `FINDINGS.md:72` and the main tree's row both end at the 2026-10-16
   amendment, so the index a fresh session resumes from does not know the reminder exists. If the
   edit is being held for the cherry-pick into the main tree, say so in the handback; otherwise
   append to the row: *"— **amended 2026-10-20**: under Claude Code a search of a documented
   module is followed by one line naming its knowledge bases, at most once per agent each
   `retrieval.knowledge_reminder_interval`"*.

3. **[IMPROVEMENT] The `rg` filter has no leading wildcard, and nothing says what that misses.**
   `zikaron/harness/spec.py:352` ships `("Bash(*grep *)", "Bash(rg *)")`. The probes measured that
   `LC_ALL=C grep …` and `cd src && grep …` start `Bash(*grep *)`
   (`research/m40-4-hook-probes.md` §Probe 2), and the brief's item 3 says the parser reads them;
   the same shapes with `rg` — `LC_ALL=C rg needle`, `cd src && rg needle .`, `ls; rg needle` —
   match neither handler, so the hook never starts, although `shell_search.searched_paths` would
   read each of them correctly. `design/code-knowledge.md` §6 says a search is *"a `Bash` command
   running `grep`, `egrep`, `fgrep`, `rg` or `git grep`"*, and §8's miss list names `timeout`,
   `bash -c`, `xargs` and `find -exec` but not this, which is a miss of the pattern's shape rather
   than of the filter's parsing. Two ways to close it; the second is the minimum. (a) Widen to
   `Bash(*rg *)` after one probe run — the cost is one start (~100 ms, no connect) on any simple
   command whose text carries `rg ` (`jq --arg …`, a commit message with `org `), the class item 4
   already prices for `grep `. (b) Enter the miss in §8 and in brief item 3's known-misses
   sentence: *"an `rg` that is not the command's first word — after an assignment, a `cd … &&` or
   a `;` — since `Bash(rg *)` carries no leading wildcard where `Bash(*grep *)` does"*.

4. **[IMPROVEMENT] One listed invariant has no test.** The brief's invariants include *"a payload
   `session_id` differing from the environment's is neither suppressed nor logged"*, and done-when
   1 says every new test was seen red. `tests/test_hook_reminder.py` never sends a `session_id`
   at all (`_run` adds only `cwd`), so the property holds by the code's silence rather than by a
   test that would go red if someone later copied `push.py`'s tripwire compare into `run`. Add to
   `TestWhatIsAsked`: `_run(_grep("src", session_id="not-the-env-label"), project) == _LINE`, the
   request's `client["session_id"] == _SESSION`, and `_hook_log(project) == ""`. The mutation that
   must redden it: a `return None` in `run` when `payload.get("session_id") != label`.

5. **[IMPROVEMENT] The line — final wording, per brief item 6.** `reminder_text`
   (`zikaron/core/code_knowledge/reminder.py:68–72`) currently reads *"Zikaron hook: the files this
   search covered are documented in the knowledge base X. zikaron_knowledge_search there finds
   what a file is for and what it depends on — a lead to check against the code."* Two things to
   fix. *"The files this search covered are documented"* asserts every covered file has a
   document, which is false for the commonest search, one from the project's root, and a reader
   who greps for an undocumented file and is told it is documented learns to discount the line.
   And the em-dash clause attaches to *"what it depends on"* rather than to what the tool gives,
   so *"a lead"* reads as describing the dependency. Set the text to:

   ```python
   f"Zikaron hook: code this search covered is documented in the {noun} {listed}. "
   "zikaron_knowledge_search there finds what a file is for and what it depends on, "
   "as a lead to check against the code."
   ```

   It stays a statement that names its source, keeps the tool's bare name, and both substrings
   `tests/test_code_knowledge_reminder.py` pins (`"the knowledge base X."`, `" and 1 more."`) still
   hold. Leave `research/m40-4-live-session.md` §1's quoted line as it is: it records what that
   session was shown.

6. **[IMPROVEMENT] A main session started as a named agent is unmeasured, and it is how the real
   stores run.** Brief item 4 and `design/code-knowledge.md` §6 rest on Probe 1's *"the main
   session's carries neither"* `agent_type` nor `agent_id`, measured on a plain `claude -p`
   (`research/m40-4-hook-probes.md` §Probe 1). The projects that run this tree start their main
   sessions as named agents — `claude --agent …` (`CLAUDE.md` §The crew; LeibaTrader's
   `leiba-engineer`). If such a session's tool events carry both fields, `_agent_id`
   (`zikaron/hook/reminder.py:104`) keys it as a subagent, `_open_the_turn`
   (`zikaron/service/dispatch.py`) never reaches its entry, and the per-prompt reminder silently
   becomes once per interval in every session of the primary store — not a failure, but not what
   §6 says either. One headless run with the probes' logging hook, `claude --agent <name> -p`,
   decides it. If both fields are present, no mechanism: the hook cannot tell that session from
   a subagent (its payload `session_id` equals the environment's in both), so the outcome is one
   sentence in §6 "How often" and in `research/m40-4-hook-probes.md` saying so. If absent, one
   sentence in the probes note saying it was checked.

7. **[NITPICK] "many-to-one" says the opposite of what it means.** `design/harness.md:96` and
   `zikaron/harness/spec.py:34`: *"Trigger names normalize many-to-one internally, onto
   `HookEvent`'s members"* reads as every name collapsing onto one event. The predicate wanted is
   *"Trigger names normalize onto `HookEvent`'s members, each name to the one member it means"*.

8. **[NITPICK] `zikaron/service/dispatch_knowledge.py`'s docstring predates the method it now
   registers.** Line 1 names *"search, and the management verbs"*, and the paragraph at 35–38
   presents `knowledge_unlock` as the method deliberately not a tool, while `dispatch_reminder.py`
   says it is registered *"in `dispatch_knowledge.py`'s table beside the knowledge index's other
   methods"*. One clause in that paragraph: *"`knowledge_remind` is served here on the same terms,
   and `dispatch_reminder.py` says why it has no tool"*.

9. **[NITPICK] `reminder_text`'s one-line guarantee holds only for names without a newline.**
   `registry.normalize_name` preserves whitespace (`zikaron/core/knowledge/registry.py:97–100`),
   so a corpus registered with a newline in its name would break `additionalContext` into two
   lines. The registering agent and the reminded one are the same trust domain, so this is the
   agent's own doing; if it is worth a line, `" ".join(name.split())` per name in
   `reminder_text`, with `test_it_is_one_line` given such a name.

10. **[NITPICK] §6 cites the earlier figure where the brief's own measurement now exists.**
    `design/code-knowledge.md` §6 "What it costs" quotes *"about 95 ms where it was measured
    (`research/m40-4-search-tool-use.md`)"*; done-when 2's measurement is 101–104 ms with and
    without a corpus (`research/m40-4-live-session.md` §3), and the second note is the one that
    says the connect and request add about 3 ms to the start. Cite both, or the later one.

VERDICT: NEEDS_CHANGES

### Author's responses to round 1

1. **Accepted.** `README.md`'s row reads *"hooks for session start, each message, each subagent
   start and each search ([Code knowledge](#code-knowledge)), plus both approval keys, …"*.
2. **Declined — already done.** The main tree's `FINDINGS.md` D39 row (line 72) carries
   *"amended 2026-10-20 (M40-4): under Claude Code a search of a documented module is followed by
   one line naming its knowledge bases, at most once per agent each
   `retrieval.knowledge_reminder_interval`"*. The worktree's `FINDINGS.md` is the committed copy
   and is never edited there; FINDINGS lands from the main tree.
3. **Declined on measurement; a different miss entered instead.** The premise is refuted:
   `research/m40-4-hook-probes.md` §Probe 6 (runs 6 and 7, `Bash(rg *)` beside `Bash(*rg *)`)
   shows `Bash(rg *)` starting for `cd src && rg …`, `ls; rg …`, `LC_ALL=C rg …` and `FOO=1 rg …`
   — the filter is matched per subcommand with its assignments stripped — while `Bash(*rg *)` adds
   only a false start on `jq -n --arg …`. So the shipped filter stays. The same probe found what
   is missed: an assignment-prefixed search **that finds nothing** comes back as an error (exit 1
   read as failure, since the harness reads exit 1 as "no matches" only when the command is the
   search), fires `PostToolUseFailure`, and runs no handler. Entered in `design/code-knowledge.md`
   §8 and brief item 3, which now also says why `Bash(rg *)` needs no leading wildcard.
4. **Accepted.** `test_a_payload_session_id_differing_from_the_label_is_asked_under_the_label`:
   the line is returned, the request's `client.session_id` is the label, `hook.log` is empty;
   seen red under the mutation named (a `return None` on a differing `session_id`).
5. **Accepted, as the brief gives you the wording.** `reminder_text` reads *"Zikaron hook: code
   this search covered is documented in the {noun} {listed}. zikaron_knowledge_search there finds
   what a file is for and what it depends on, as a lead to check against the code."*
   `experiments/m40_4_reminder_followon.py` now recognizes the line by its `Zikaron hook:` opening,
   so a transcript under either wording counts. The live-session quote is left as recorded.
6. **Measured; no mechanism needed.** §Probe 5: `claude --agent probe-main -p …` gives the main
   session's `PostToolUse` payload `agent_type: "probe-main"` and **no** `agent_id`. The hook sends
   an `agent_id` only beside an `agent_type`, so such a session is keyed as the session and the
   per-prompt clear reaches it. One sentence in §6 "How often", the probe in the note, and
   `test_a_main_session_run_as_a_named_agent_is_keyed_as_the_session`, seen red under a mutation
   that keys by `agent_type` when no `agent_id` is sent.
7. **Accepted.** `design/harness.md` and `HookEvent`'s docstring: *"normalize … onto
   `HookEvent`'s members, each name to the one member it means"*.
8. **Accepted.** `dispatch_knowledge.py`'s first line names `knowledge_remind`, and the
   `knowledge_unlock` paragraph ends *"`knowledge_remind` is served here on the same terms, and
   `dispatch_reminder.py` says why it has no tool."*
9. **Accepted** (a cheap fix): each named corpus has its whitespace runs folded to one space, with
   a docstring sentence saying why; `test_it_is_one_line` gives a name carrying a newline and
   checks it is folded; seen red with the fold removed.
10. **Accepted.** §6 "What it costs" cites `research/m40-4-live-session.md` §3: about 100 ms, nearly
    all of it the interpreter's start and imports, the request about 3 ms more.

Also changed since round 1, outside the findings: `research/m40-4-live-session.md` §3 gained the
breakdown of the ~100 ms (interpreter 36 ms, imports ~65 ms, per-event imports saving ~2 ms) and the
comparison with the push's service-side time, and `FINDINGS.md` §"Owed work" an entry for a native
hook client (operator).

## Round 2 — 2026-10-21

**Summary judgment.** Round 1's ten responses are each in the tree as described, and the two that
were declined were declined on measurement that holds up: Probe 5 settles the named-agent main
session, Probe 6 settles `Bash(rg *)`, and the miss they found instead is now in §8 and brief item
3. The code is correct on every path I traced, the normative sections state what it does with one
exception, and the brief's invariant list is covered with one exception — both cheap. Verified
rather than assumed this round: the MCP server's label is the hook's under Claude Code, since
`CLAUDE_CODE_SESSION_ID` is exported into every process the harness starts (`design/harness.md:112`),
so `knowledge_search`'s stamp lands on the key the hook reads; `tests/test_hook_stdlib_only.py`
discovers `zikaron/hook/*.py` by glob, so `reminder.py` and `shell_search.py` are enforced without
being listed; and a sweep for brief item 8's retired phrasings finds them only in earlier
milestones' briefs, `FINDINGS-archive.md`, `research/` and `reviews/`.

**Findings.**

1. **[IMPROVEMENT] `find … -exec grep … {} +` is not the miss §8 says it is; it is a false reach.**
   `design/code-knowledge.md` §8 and brief item 3 say it "name[s] no path". The parser disagrees:
   `zikaron/guard/position.py:82–91` puts the word after `-exec` in command position — its own
   doctest, `words("find . -exec sed -i x {} +")` → `['find', 'sed']` — `zikaron/guard/grammar.py:241–248`
   keeps `{}` a literal word by design, and `read_grep` (`grep_filter.py:151–164`) keeps every
   non-option word as an operand, so for `find src -exec grep -l needle {} +` `Grep.paths` is
   `["{}", "+"]` and `shell_search._paths` (`shell_search.py:135–140`) makes them `<cwd>/{}` and
   `<cwd>/+`. Both lie under the cwd, so `corpora_reached` reports every module the cwd reaches —
   from the project root, every module — whatever directory `find` was given, and
   `find /somewhere/else -exec grep … {} +` run from the root reminds falsely. The hook does start
   for it: `Bash(*grep *)`'s leading wildcard matched `pgrep` mid-command (probes, run 4), so it
   matches `-exec grep ` too. `… | xargs -I{} grep needle {}` has the same shape (`xargs` is a
   wrapper `command_word_at` skips, `-I{}` an attached flag), and `grep needle -` yields `<cwd>/-`
   the same way. Fix, in `shell_search` and not in `read_grep`, so the guard's reading of a
   `grep` is untouched: before `_paths`, drop each operand that is a placeholder or a terminator
   rather than a path — `{}` or any operand containing it, `+`, `;` and a lone `-` — so such a
   command yields nothing and §8's sentence becomes true as written. Add to
   `test_hook_shell_search.py::test_a_command_that_searches_nothing`: `find src -exec grep -l
   needle {} +`, `find src -exec grep -l needle {} \;`, `find src | xargs -I{} grep needle {}` and
   `grep needle -`; the mutation is the filter removed.

2. **[IMPROVEMENT] The "reads no result" invariant has no test.** Brief invariants: *"The hook
   reads no result: a search that found nothing is reminded as one that found something."*
   `tests/test_hook_reminder.py` never sends a `tool_response`, so the property holds by the code's
   silence — the same class as round 1's finding 4, which was accepted on the same reasoning. Add
   to `TestWhatIsAsked` two payloads carrying Probe 3's recorded shapes and assert each returns
   `_LINE`: `_grep("src", tool_response={"numFiles": 0, "filenames": []})`, and a `Bash` `grep -rn
   needle src` with `tool_response={"stdout": "", "stderr": "", "interrupted": False,
   "returnCodeInterpretation": "No matches found"}`. The mutation that must redden them: in `run`,
   `return None` when `payload.get("tool_response")` is a dict whose `numFiles` is 0 or whose
   `returnCodeInterpretation` is `"No matches found"`.

3. **[NITPICK] Alternating selections reorder `PostToolUse` and rewrite the file with a `.bak` and
   no note.** `settings_hooks.merge` (`settings_hooks.py:55–68`) appends this selection's groups
   after the kept ones, so `both` followed by `memory` turns `[reminder, nudge]` into
   `[nudge, reminder]`; `MergePlan.unchanged` (`writer.py:463`) compares documents whole, so that
   run writes the file and a backup, and the next `both` flips it back. Before M40-4 a `memory`
   run over `both` touched nothing, because the triggers were disjoint. Fix: splice `groups` in at
   the index of the first group `slots[trigger].holds`, and at the end when none does; extend
   `test_a_rerun_that_changes_nothing_writes_nothing` with the pair `("both", "memory")`.

4. **[NITPICK] `reminder.run`'s "Never raises" is not quite true, though fail-open holds.**
   `Path(written).expanduser()` (`reminder.py:84`, `shell_search.py:144`) raises `RuntimeError` for
   `~nosuchuser/…`, and nothing in `run` catches it; `main()`'s `contextlib.suppress(Exception)`
   turns it into a silent exit 0, which is the brief's behaviour for a malformed payload, so only
   the sentence is wrong. Either wrap `_searched` (`except Exception: return ()`) or restate the
   docstring: *"Raises nothing it anticipates; `main` suppresses the rest, so the exit is 0 either
   way."*

5. **[NITPICK, optional] Earlier briefs name symbols this change moved.** `design/build-plan.md`
   lines 3027 and 5410 (`_classify_failure`) and 5159 and 5303 (`push._REJECTION_KINDS`) now point
   at `failure.classify` and `failure.REJECTION_KINDS`. A past brief is a record, so leaving them is
   defensible; if touched, a parenthetical *"(since M40-4, `failure.classify`)"* is enough.

VERDICT: NEEDS_CHANGES

### Author's responses to round 2

1. **Accepted, and widened to the class.** `shell_search._paths` yields nothing when any operand
   stands in for paths named elsewhere — one containing `{}`, or a lone `+`, `;` or `-` — so a
   recursive `grep` under `find -exec … {} +` is not read as the cwd either; and a search run by
   `xargs`, which the parser passes over as a wrapper, is read as no search
   (`_run_by_a_supplier`), since `… | xargs grep -rn needle` names no path and would otherwise
   read as a recursive search of the cwd. `read_grep` is untouched. `test_a_command_that_searches_nothing`
   gained `find src -exec grep -l needle {} +`, the same with `';'`, with `grep -rl`, `find src |
   xargs -I{} grep needle {}`, `find src -name '*.py' | xargs grep -rn needle` and `grep -r needle
   -`; each seen red with its rule removed (`sh_stand_ins_read`, `sh_xargs_ignored`). §8, brief
   item 3 and the module's docstring now say a search whose paths come from elsewhere is read as
   no search.
2. **Accepted.** `test_the_result_is_not_read`, with Probe 3's two recorded shapes; seen red under
   the mutation named.
3. **Accepted.** `settings_hooks._spliced` puts this selection's groups where the first of them
   stood, and after the rest when none did; `test_a_rerun_that_changes_nothing_writes_nothing` now
   runs `(memory, memory)`, `(both, both)`, `(both, memory)` and `(both, guards)`, and the
   `(both, memory)` case is red with the old append.
4. **Accepted, as the docstring.** `run`: *"Raises nothing it anticipates; `main` suppresses the
   rest, so the exit is 0 either way."*
5. **Declined.** A past milestone's brief records what was built then; a parenthetical pointing
   forward is prose explaining prose, and the symbols' current homes are in the code.

## Round 3 — 2026-10-21

**Summary judgment.** Round 2's four accepted fixes are in the tree as described and each closes
its finding: `_paths` yields nothing on a stand-in or terminator, `_run_by_a_supplier` reads a
search behind `xargs` as none (I confirmed `xargs` is in `position.WRAPPERS`, so `command_words`
does reach the `grep` and the supplier check is what stops it), `_spliced` keeps a trigger's
order under one selection over `both`, and the result-not-read test carries Probe 3's shapes.
I traced every path again against the brief's items 2–8 and its invariant list, and against
`code-knowledge.md` §6/§8, `architecture.md` §"Degraded modes" and §"Service RPC surface",
`harness.md` and `schema.md`: the code does what those sections say, the throttle's
no-`await` window holds (`lease_deadline` is synchronous), and every invariant has a test that
would redden under a plausible mutation. The main tree's `FINDINGS.md` D39 row and the owed
native-hook-client entry are present as round 1's response said. One sentence of the brief's
item 3 states a consequence the matching rule does not deliver; the rest is nitpicks.

**Findings.**

1. **[IMPROVEMENT] A `git grep` revision does not "reach what the `cwd` reaches" — it reaches only
   the modules above the `cwd`, so `git grep needle HEAD` from the root reminds of nothing below
   it.** Brief item 3 (`design/build-plan.md:7105`): *"a revision among the operands is read as a
   path, which lies under the `cwd` and reaches what the `cwd` reaches."* By `corpora_reached`'s
   rule (`zikaron/core/code_knowledge/reminder.py:50`), a path P reaches M when P is under M or M
   is under P; `<cwd>/HEAD` is under no module below the `cwd`, and no module is under it, so for
   `cwd` = project root and corpora `code-knowledge/src/a`, `git grep needle HEAD` yields paths
   `(<root>/HEAD,)` and reaches nothing — where `git grep needle` yields `(<root>,)` and reaches
   every module. `test_hook_shell_search.py:80` pins the paths and no test takes them through
   `corpora_reached`, which is why the sentence survived. Two fixes; the first is the minimum.
   (a) Correct the sentence and enter the miss: *"a revision among the operands is read as a path
   under the `cwd`, so such a search reaches only the modules at or above the `cwd` — a known
   miss (§8), since without `--` nothing lexical tells a revision from a path"*, and add the clause
   to `design/code-knowledge.md` §8's miss list. (b) Better, and exact where `git`'s own grammar
   is: `git grep [opts] <pattern> [<rev>…] [--] [<pathspec>…]`, so when `--` is present every
   operand between the pattern and `--` is a revision. In `_git_grep`
   (`zikaron/hook/shell_search.py:142`), after reading the subcommand: `rest = given[index + 1:]`;
   `dash = next((i for i, t in enumerate(rest) if t.unquoted == "--"), None)`; take
   `[t.unquoted for t in rest[dash + 1:]]` as the written pathspecs when `dash is not None`, else
   `grep.paths` as today. Then `test_git_grep`'s row becomes
   `("git grep needle HEAD -- src", (f"{CWD}/src",))`, add `("git grep needle HEAD", (f"{CWD}/HEAD",))`
   for the `--`-less case the sentence under (a) still describes, and the mutation is the `dash`
   branch removed. Either way the brief's sentence changes.

2. **[NITPICK] `rg --files <dir>` reads `<dir>` as the pattern and reminds for the `cwd`.**
   `shell_search._searched` (`shell_search.py:121–123`) hands `rg`'s operands to `read_grep`,
   whose first operand is the pattern; under `--files` (and `--type-list`) `rg` takes none, so
   `rg --files src/a` from the root yields `(<root>,)` and names every module rather than `src/a`'s.
   `rg --files` is a common agent idiom. If worth closing: in the `rg` branch, when any token in
   `given` has `unquoted == "--files"`, use `rg.operands` as the written paths; add
   `("rg --files src", (f"{CWD}/src",))` to `test_ripgrep`. Over-reach rather than a false reach,
   so optional.

3. **[NITPICK] The order `guards` → `memory` → `both` still rewrites `PostToolUse` once, with a
   `.bak` and no note.** After `guards` then `memory` the trigger holds `[nudge, reminder]`;
   `both` writes `[reminder, nudge]`, and `_spliced` (`settings_hooks.py:65–77`) places *all* of
   `ours` at the first held group's slot, so the file flips and `MergePlan.unchanged` is false.
   Round 2's fix covers one selection over `both`; this is `both` over the two selections installed
   separately, and it happens once, so it is cosmetic. If closing it: in `_spliced`, map each of
   `ours` by its script (`_zikaron_script` of its first command) and, at each held existing group,
   emit the one of ours with that script if not yet placed, appending the rest at the end; add the
   triple to the rerun test as a three-step case.

4. **[NITPICK] `_spliced`'s `slot: "_Slot"` is a string annotation because `_Slot` is defined
   below it** (`settings_hooks.py:65`, `80`). Move the dataclass above `merge` and drop the quotes.

VERDICT: NEEDS_CHANGES

### Author's responses to round 3

1. **Accepted, both halves.** (b): `shell_search._after_revisions` takes a `git grep`'s written
   pathspecs as the operands after a `--` when one is present, so every operand before it but the
   pattern is a revision and dropped; `test_git_grep` now has `git grep needle HEAD main -- src` →
   `src`, `git grep -e needle HEAD -- src lib` → both, `git grep needle HEAD --` → the cwd, and
   `git grep needle HEAD` → `<cwd>/HEAD`; the first three are red with the branch removed
   (`sh_revisions_kept`). (a): brief item 3's sentence now says a revision is told from a path only
   by a `--`, and that without one it is read as a path reaching only the modules at or above the
   cwd — a known miss, entered in §8.
2. **Accepted** (a cheap fix for a common idiom): under `--files`, every `rg` operand is a path
   (`_RG_LISTS_FILES`); `test_ripgrep` gained `rg --files src`, `rg --files -g '*.rs' src lib` and
   `rg --files`, the first two red with the rule removed. Brief item 3 says so in one sentence.
3. **Declined.** The flip needs three installs in that particular order — `guards`, then `memory`,
   then `both` — and happens once: the write leaves the order `both` writes, so every later run
   of any selection over it is unchanged. Placing each of ours by its script is more machinery
   than a one-time `.bak` with the same hooks in it is worth.
4. **Accepted.** `_Slot` moved above `merge`; `_spliced` takes `_Slot` unquoted, and `_Slot.of`
   returns `Self`.

## Round 4 — 2026-10-21

**Summary judgment.** Round 3's two accepted fixes are in the tree as described: `_after_revisions`
takes a `git grep`'s pathspecs from after a `--` and leaves the `--`-less case as the brief now
states it, and `_RG_LISTS_FILES` reads every `rg --files` operand as a path; the new test rows pin
both, and §8 and brief item 3 say what is missed. I re-traced the hook, the parser, the service
method, the throttle and the settings merge against items 2–8 and the invariant list, and
confirmed from the grammar that `&&` and `;` end a pipeline, so `cd src && rg needle` and
`ls; rg needle` — the shapes Probe 6 measured — are read as searches of the cwd rather than as
`rg` after a pipe. One defect remains, found by asking what the registry does to a corpus name
before `corpora_reached` ever sees it: every name is stored lower-cased, the comparison is
case-sensitive, and so a search *inside* any module whose path carries an upper-case letter never
names that module's corpus. It is silent, it falsifies a normative sentence, and the fix is one
line; everything else is a pin or a clause.

**Findings.**

1. **[BLOCKER] A module with an upper-case letter in its path is reached from above and never from
   inside.** `registry.normalize_name` (`zikaron/core/knowledge/registry.py:85–107`) stores every
   name lower-cased, and `lifecycle.add` applies it (`lifecycle.py:194`), so a module
   `src/Components` is registered as `code-knowledge/src/components`. `module_of`
   (`zikaron/core/code_knowledge/reminder.py:25–32`) reads `src/components` back, `corpora_reached`
   (`:49–50`) builds `root = <project>/src/components`, and the hook's paths carry the directory's
   real case — `grep -rn x src/Components` → `<project>/src/Components`, and the `Grep` tool's
   `path` likewise. `PurePosixPath.is_relative_to` compares components exactly
   (`test_a_sibling_sharing_a_prefix_is_beside_not_under` relies on that), so neither direction
   holds: the search inside the module reaches nothing, while one from `src` or the root still
   names it, because `<project>/src/components` *is* under `<project>/src`. So the most specific
   case — the agent is in the module, grepping it — is exactly the one that stays silent, and
   nothing says so: the brief's item 3 (`design/build-plan.md:7112–7113`) and
   `design/code-knowledge.md` §6's *"a search reaches module M when a path it searched is M or
   under it"* are false for every such module. Lower-case module paths (`app/src/terminal`,
   LeibaTrader's) do not show it, which is why the live session and the toy runs passed; `src/
   Components`, `Sources/`, `Source/<Game>/` (the Unreal project in
   `research/m30-docker-end-to-end.md`) and most C#/Swift/TypeScript trees would. **Fix, one line,
   in `_normalized` (`reminder.py:76–77`)**: `return PurePosixPath(os.path.normpath(path).lower())`
   — both `root` and every searched path go through it, so the comparison folds case on both sides.
   This is the registry's own rule applied to the comparison, not a new conflation: `normalize_name`
   already makes `Docs` and `docs` one corpus, so two directories differing only by case already
   share a corpus name, and the module they would both reach is the one that corpus documents. The
   module docstring's *"Paths are compared lexically, normalized and absolute"* gains *"and
   without regard to case, since a registered name is lower-cased"*; the same clause goes in brief
   item 3's *"Paths are compared lexically, normalized and absolute, touching no file"* sentence
   and in §6's *"paths are compared lexically"*. Test, in `TestTheMatchingTable`
   (`tests/test_code_knowledge_reminder.py`):
   `assert _reached(f"{PROJECT}/src/Components/x.tsx", corpora=("code-knowledge/src/components",)) == ("code-knowledge/src/components",)`,
   with a docstring saying the registry lower-cases the name and the hook sends the path as
   written; the mutation is the `.lower()` removed. `experiments/m40_4_reminder_followon.py` and
   the service inherit the fix through `corpora_reached`; `dispatch_knowledge._reaches_code_knowledge`
   already lower-cases its names and needs nothing.

2. **[NITPICK] Pin that `&&` and `;` do not make an `rg` "after a pipe".** `shell_search._searched`
   (`zikaron/hook/shell_search.py:131`) reads an `rg` with no path as its input when
   `after_pipe=index > 0`, where `index` is the simple command's place in its pipeline — correct
   today because `grammar.py` ends a pipeline at `&&`, `;`, `||` and `&` and continues it only at
   `|` (`grammar.py:3–5`, `:111`). `test_hook_shell_search.py` never exercises a path-less `rg`
   after either operator: `test_a_cd_earlier_in_the_command_is_not_followed` and
   `test_every_search_in_a_compound_command_counts` both name a path, so a grammar change that
   folded `&&` lists into one pipeline would silently turn `cd src && rg needle` — the very shape
   Probe 6 measured as the reason `Bash(rg *)` needs no leading wildcard — into no search, with
   nothing red. Add to `test_ripgrep`: `("cd src && rg needle", (CWD,))` and
   `("ls; rg needle", (CWD,))`. The mutation: `after_pipe` computed from the pipeline's index in the
   command rather than the simple command's in the pipeline.

3. **[NITPICK] The Components row now says the hook starts the service only for a push.**
   `design/architecture.md:65`: *"Starts the service if absent for a push; the reminder only
   connects to one already serving."* The spawn trigger also starts it — through the detached
   warm helper, which runs `connect_start_if_absent` (`zikaron/hook/warm_helper.py:103–107`;
   §Warming) — so a reader of the row now believes the spawn path leaves an absent service absent.
   Edit: *"Starts the service if absent — directly for a push, through the detached warm helper on
   spawn (§Warming) — while the reminder only connects to one already serving (§"Degraded
   modes")."*

VERDICT: NEEDS_CHANGES

### Author's responses to round 4

1. **Accepted — confirmed before fixing.** `corpora_reached(['/p/src/Components/x.tsx'],
   project='/p', corpora=['code-knowledge/src/components'])` returned `()`, while the same corpus
   was reached from `/p/src`. `_normalized` now lower-cases after `normpath`, so both sides fold as
   the registry's `normalize_name` does (`str.lower()`, the registry's own choice over
   `casefold`). `test_a_module_s_case_is_not_compared` checks a search inside `src/Components` and
   one from a mixed-case project path; red with the `.lower()` removed (`ck_case_kept`). The
   clause is in the module docstring, brief item 3 and §6.
2. **Accepted.** `test_ripgrep` gained `cd src && rg needle` and `ls; rg needle`, each the cwd; both
   red under the mutation named (`sh_pipe_from_pipeline_index`), with the existing `an rg after a
   pipe` case.
3. **Accepted**, as worded.

## Round 5 — 2026-10-21

**Summary judgment.** Round 4's three fixes are in the tree as described: `_normalized` lower-cases
after `normpath`, `test_a_module_s_case_is_not_compared` pins a search inside `src/Components` and
one from a mixed-case project path, the two `test_ripgrep` rows pin `&&` and `;` as not-a-pipe, and
the brief, §6 and the Components row carry the case clause. Fresh checks this round, all holding:
the connect path is bounded as item 4 says (`_try_connect` and `_health` get 0.3 s each, and
`remind_once` re-arms from the 1 s deadline taken before the connect, so a wedged service costs at
most the second); `orphan_candidates` answers `()` for an absent `knowledge/`, so a store with no
corpus never reaches the socket; `zikaron doctor` enumerates no triggers, so no install check went
stale; and `test_hook_stdlib_only.py` globs the hook package, so `shell_search.py`'s import of the
guard's parser is enforced stdlib-only. What remains is one reading `git grep`'s own manual example
defeats, one confound in the instrument done-when 2 ships, and three clauses.

**Findings.**

1. **[IMPROVEMENT] A `git grep` pathspec with a wildcard reaches nothing below the `cwd`, and that
   is git's own documented idiom.** `git grep 'time_t' -- '*.[ch]'` is the manual's example and the
   common agent form for restricting by extension; git's pathspec globs cross directories, so it
   searches every `.c` and `.h` file below the `cwd`. `_git_grep` (`zikaron/hook/shell_search.py:152–159`)
   makes it `<cwd>/*.[ch]`, and under `corpora_reached`'s rule that path is neither under
   `<cwd>/src/a` nor above it, so from the project root the search reaches the root module alone
   and every `code-knowledge/<module>` corpus stays silent — where the same command with no
   pathspec reaches all of them. The brief's item 3 sentence *"a glob operand such as `src/*.py`
   lies under `src`"* is right for `grep`, whose shell expands the glob in one directory, and wrong
   for a `git grep` pathspec, which git expands across the tree. Fix, in `_git_grep` only: read
   each pathspec up to its first component carrying `*`, `?` or `[`, and as `.` when that is the
   first component —

   ```python
   _GLOB_CHARS: Final = frozenset("*?[")

   def _literal_prefix(pathspec: str) -> str:
       """A pathspec up to its first component carrying a wildcard, since git's globs cross
       directories: `*.c` searches every directory below, `src/*.rs` every one below `src`."""
       parts = PurePosixPath(pathspec).parts
       literal = list(takewhile(lambda part: not _GLOB_CHARS & set(part), parts))
       return str(PurePosixPath(*literal)) if literal else "."
   ```

   applied to each path in the `pathspecs` comprehension after the `:/` substitution (an absolute
   result keeps its `/` as its first part). Rows for `test_git_grep`:
   `("git grep needle -- '*.py'", (CWD,))`, `("git grep needle -- 'src/*.rs'", (f"{CWD}/src",))`,
   `("git grep needle -- ':/**/*.py'", (TOP,))`; the mutation is `_literal_prefix` returning its
   argument. One sentence in brief item 3 after the glob-operand clause, and in
   `design/code-knowledge.md` §6's "What counts as a search": *"a `git grep` pathspec is read up to
   its first component with a wildcard, since git's globs cross directories"*.

2. **[IMPROVEMENT] The follow-on instrument's control arm counts the documenter's own searches.**
   `experiments/m40_4_reminder_followon.py` classifies every search in every transcript, subagents
   included, as reminded or not by the transcript's attachment, and the hook is silent for the
   documenter by `agent_type` — so every documenter `Grep` of the module it is documenting lands in
   the *unreminded* class, and the documenter then searches its own corpus by instruction (34 of
   41 reached it, `design/code-knowledge.md` §5.1). In any project that has a corpus the documenter
   wrote it, so the control arm is dominated by searches no throttle left alone, followed by
   knowledge searches no line could have prompted, and the rate it reports says the documents are
   used without the reminder whatever the line does. This is the number done-when 2 names as the
   one that later decides whether the line earns its place, which is why it counts under the
   operator's rule for notes. Fix: exclude the documenter's transcripts, which are the only ones
   that write into a corpus — read each code-knowledge corpus's root from the registry beside its
   name, and in `outcomes` skip a transcript holding a `Write` or `Edit` whose `file_path` lies
   under any such root; or, if a subagent transcript records its agent type, skip by
   `DOCUMENTER_AGENT_TYPE` and `ORCHESTRATOR_AGENT_TYPE` from `zikaron.hook.reminder`, which is
   the hook's own rule. Either way, one sentence in `research/m40-4-live-session.md` §4 saying
   the documenter's searches are left out and why.

3. **[NITPICK] `git grep -- -pattern` reads the pattern as a pathspec.** git skips a `--` that
   precedes any pattern (`git-grep.c`: *"skip a -- separator; we know it cannot be separating
   revisions from pathnames if we haven't even had any patterns yet"*), so `git grep -- -foo src`
   has pattern `-foo` and pathspec `src`. `_after_revisions` (`shell_search.py:162–170`) takes the
   first `--` as the separator and yields `[-foo, src]`, so `git grep -- -foo` with no path yields
   `<cwd>/-foo` instead of the `cwd`. Rare — the form exists for patterns that begin with `-` — and
   cheap: when no `-e`/`-f` was given (`len(grep.paths) < len(grep.operands)`) and every operand
   stands after the first `--` (`words[dash + 1:] == grep.operands`), the dash preceded the
   pattern: take `grep.operands[1:]`, and if a literal `--` is among them, what follows it. Rows:
   `("git grep -- -needle", (CWD,))`, `("git grep -- -needle src", (f"{CWD}/src",))`.

4. **[NITPICK] `design/guards.md` §9.2 enumerates the filter `grep`'s reading and does not say `--`
   ends its options, which the shared `read_grep` now does.** §9.2 lists what `-A -B -C -m -d -D`
   and the long options consume and how `-e`/`-f` are read; the brief's item 3 adds *"`--` ends
   the options"* to `read_grep`, and the guard inherits it: `pgrep -af X | grep -v -- -e` was read
   as a `grep` with no pattern (deny) and is now read as the pattern `-e` (exempt). The verdict
   moved toward correctness on a conceived edge, which §9.4 says §9 does not do without an observed
   command, so the honest fix is the clause rather than a revert: after *"unless written with
   `=value`"*, add *"; `--` ends its options, every token after it an operand"*.

5. **[NITPICK] `design/knowledge-index.md` §10's table is no longer every `knowledge_` key.** The
   restated `design/schema.md` sentence makes membership by prefix — *"the `knowledge_`-prefixed
   keys, whichever section they sit in, belong to the knowledge index"* — and §10 presents its
   five-row table as the index's keys, with *"the first four are declared keys in `schema.md`'s own
   configuration table"*. `knowledge_reminder_interval` carries the prefix, is declared, and is in
   neither. Add a row — `knowledge_reminder_interval` | 300 s | the search reminder's, for code
   knowledge (`code-knowledge.md` §6) — and make the sentence *"every row but
   `knowledge_scan_on_session_start` is a declared key"*.

VERDICT: NEEDS_CHANGES

### Author's responses to round 5

1. **Accepted.** `shell_search._literal_prefix` reads a `git grep` pathspec up to its first
   component carrying `*`, `?` or `[`, as `.` when that is the first, after the `:/` substitution;
   `test_git_grep` gained `-- '*.py'` → the cwd, `-- 'src/*.rs'` → `src`, `-- 'src/a/**/[ab].py'`
   → `src/a` and `-- ':/**/*.py'` → the top, all four red with it returning its argument
   (`sh_globs_kept`). Brief item 3 and §6 say so in one sentence each.
2. **Accepted.** The counter skips a transcript whose `.meta.json` names `agentType` as either of
   `zikaron.hook.reminder`'s two silent types — the hook's own rule — and its docstring and
   `research/m40-4-live-session.md` §4 say why. Run on `~/Trading/LeibaTrader`, where M40-4 is not
   installed, it gives the pre-reminder baseline, now in §4: 1,358 unreminded searches of a
   documented module, 4 followed by a knowledge search within 5 calls (0.3%).
3. **Accepted** (rare, and a few lines). When the first `--` stands before every operand and no
   `-e`/`-f` named the pattern, it only ended the options: the pattern is the first operand after
   it, and a second `--` separates revisions from pathspecs. Rows `git grep -- -needle` → the cwd,
   `git grep -- -needle src` → `src`, `git grep -n -- -needle HEAD -- src` → `src`; red with the
   first `--` always taken as the separator (`sh_leading_dash_as_separator`). Brief item 3 says so.
4. **Accepted**, as worded.
5. **Accepted.** §10's table has the row, *"Every row but `knowledge_scan_on_session_start` is a
   declared key"*, and the paragraph after it, which said *"The other three"*, now reads *"The
   others"* and names what the reminder's key paces.

## Round 6 — 2026-10-21

**Summary judgment.** Round 5's five fixes are in the tree as described, and each holds up on a
re-trace: `_literal_prefix` reads `*.py` as `.`, `src/*.rs` as `src` and `:/**/*.py` as the top
after the `:/` substitution; `_after_revisions` takes a leading `--` as the options' end exactly
when it precedes every operand and no `-e`/`-f` named the pattern, which I walked for the three new
rows and for `-e needle -- -weird`, `-- needle` and a `--` given as a `-e` pattern, each right; the
counter skips by the `agentType` a subagent's `.meta.json` carries, which I confirmed on a
LeibaTrader transcript's own; and the four documents say what the code does. Checked fresh this
round rather than taken from earlier rounds: `tests/test_hook_stdlib_only.py` discovers
`zikaron/hook/*.py` and measures each module's imports transitively in a subprocess, so
`reminder.py`'s new import of `zikaron.core.knowledge.paths` (pure stdlib) and `shell_search.py`'s
of the guard are enforced; the main tree's `FINDINGS.md` carries the D39 amendment (line 72) and
the owed native-hook-client entry (line 549); and the grammar parses a same-line `$(…)` into
pipelines of its own, so `echo $(grep -rn x src)` is read as a search of `src` rather than missed.
One false reach remains, on a command agents do run; the rest is two pins.

**Findings.**

1. **[IMPROVEMENT] An `rg` or `git grep` with no pattern is read as a search of the `cwd`, so
   `rg --version` from the project root reminds of every module.** `shell_search._searched`
   (`zikaron/hook/shell_search.py:129–133`) hands `rg`'s tokens to `read_grep`, and for
   `rg --version`, `rg --help`, `rg --type-list` or `rg --pcre2-version` — the forms an agent runs
   to check the tool is there or to learn its type names, and `rg --help | grep -i glob` is a
   natural one — `_read_long` returns nothing for the unknown long option, `operands` is empty,
   `paths` is empty, and `_paths([], default=cwd)` yields the `cwd`. `Bash(rg *)` starts the hook
   for each. So a command that searches nothing earns a reminder naming every module the `cwd`
   reaches and, worse, **spends the turn's one reminder on it**, so the real search that follows
   is throttled. `_git_grep` has the same hole for `git grep --help` (`grep.paths` empty,
   `default=base`), and plain `grep` is protected only by its recursion rule. The brief's
   invariant list names *"a `Bash` command that is no search"*, and `pgrep` and `echo grep …` are
   pinned for it; this is the same invariant on the command the parser does read. Fix, a property
   on the reading both hooks share, with the predicate `paths` already branches on:

   ```python
   # zikaron/guard/grep_filter.py, in `Grep`
   @property
   def names_a_pattern(self) -> bool:
       """Whether anything was given to search for: an operand, or an `-e` or `-f`. Without one
       the command prints usage or a version and searches nothing."""
       return bool(self.operands) or bool(self.letters & {_PATTERN, _PATTERN_FILE})
   ```

   and in `shell_search`: the `grep` branch yields only when `grep.names_a_pattern`; the `rg`
   branch only when `listing or rg.names_a_pattern`; `_git_grep` returns after `read_grep` when
   `not grep.names_a_pattern`. Rows for `test_a_command_that_searches_nothing`: `rg --version`,
   `rg --help`, `rg --type-list`, `git grep --help`; and, so the predicate does not over-correct,
   for `test_ripgrep`: `("rg -e needle", (CWD,))` and `("rg -f pats.txt", (CWD,))`, where the
   second holds `f` in `letters` and nothing in `patterns`. The mutation: the property returning
   `True`. One clause in brief item 3 after *"an `rg` after a `|`, reads its input"* and in
   `design/code-knowledge.md` §6's "What counts as a search": *"and one given no pattern —
   `rg --version`, `rg --help` — searches nothing"*.

2. **[NITPICK] The forced cross-selection installs are not pinned to produce no note.** The
   invariant reads *"with and without `--force`, whose note names only the groups it replaced"*;
   `test_each_selection_keeps_the_other_s_group[forced]`
   (`tests/test_install_components.py`) asserts the two scripts survive and reads nothing of the
   output, so a `_notes` that reported the other selection's group as a `--force` loss would pass.
   The predicate holds today (`replaced` is built from `slot.holds`, which the other selection's
   group fails), so this is a pin: take `capsys` in that test and add
   `assert "replaced" not in capsys.readouterr().out` after the second install. The mutation:
   `replaced` built from `_commands_in(group)` being non-empty rather than from `holds`.

3. **[NITPICK, optional] A shell glob under a recursive `grep` under-reaches, and §8 does not say
   so.** `grep -rn needle src/*` from the root is, after the shell expands it, a search of every
   entry in `src` and so of every module under it; the parser reads the one token `src/*` as
   `<root>/src/*`, which under `corpora_reached`'s rule is under `src` and above nothing, so the
   modules under `src` stay silent. Brief item 3's *"a glob operand such as `src/*.py` lies under
   `src`"* is true and is the right reading for `*.py`, whose expansion stays in one directory; it
   is the wrong one for a bare `*` or `*/` under `-r`, which is how an agent sometimes spells "all
   of src". Applying `_literal_prefix` to `grep` operands would fix `src/*` and over-reach `*.py`,
   so no rule is right for both and I would not change the code; the cheap honest fix is one
   clause in `design/code-knowledge.md` §8's miss list: *"a shell glob under a recursive `grep`,
   such as `src/*`, read as lying under `src` rather than as the directories it expands to"*.
   Declining is reasonable.

VERDICT: NEEDS_CHANGES

### Author's responses to round 6

1. **Accepted.** `Grep.names_a_pattern` in `zikaron/guard/grep_filter.py` — an operand, or an
   `-e`/`-f` — and `shell_search` yields a `grep` only when it holds, an `rg` only under `--files`
   or when it holds, and a `git grep` returns before its pathspecs when it does not. The guard's
   own reading is untouched (`tests/test_guard_rule_table.py` and `tests/test_guard_main.py`
   green). `test_a_command_that_searches_nothing` gained `rg --version`, `rg --help`,
   `rg --type-list`, `git grep --help` and `grep -r --help`, all red with the property `True`
   (`sh_always_a_pattern`); `test_ripgrep` gained `rg -e needle` and `rg -f patterns.txt` → the
   cwd, so it does not over-correct. Brief item 3 and §6 carry the clause.
2. **Accepted, with the markers the notes carry.** The installer prints `replaced  <path>` for
   every file it rewrites, so the bare word is in every such run's output; the test now asserts
   neither hook note — *"--force replaced Zikaron's hook"* nor *"differed from what this install
   writes"* — appears, and is red on both forced cross-selection cases under a `_notes` that
   reports the other selection's group (`in_notes_any_group`).
3. **Accepted** as the clause in §8.

## Round 7 — 2026-10-21

**Summary judgment.** Round 6's three fixes are in the tree as described and hold up on a re-trace:
`Grep.names_a_pattern` is the operand-or-`-e`/`-f` predicate, `_read_cluster` puts `e` in `letters`
whether or not its pattern is attached (so `rg -efoo src` still keys `paths` off the flag), the
`grep`, `rg` and `git grep` branches each gate on it with `--files` the one exception, and the
forced cross-selection installs are pinned to produce neither note. Checked fresh this round rather
than carried from earlier ones: `server._invoke` runs `on_receipt` before the deadline is read and
the connection obtained, so a `bounds`-refused push opens the turn as the test says;
`connect_if_serving` answers `None` on exactly the absent-server errnos and lets anything else
reach the log; `orphan_candidates` is a suffix listing that opens nothing; the follow-on counter
skips by the `.meta.json`'s `agentType` against the hook's own two names; and the main tree's
`FINDINGS.md` carries the D39 amendment (line 72) and the owed native-hook-client entry (line 549).
Every invariant in the brief's list has a test I can name, and done-when 2's note carries the
ordered observations, the timing without a bar, the transcript evidence and the instrument with its
LeibaTrader baseline. What remains is two sentences the build makes false — one of them the last
requirement of brief item 8, in the document the brief names — and two clauses.

**Findings.**

1. **[IMPROVEMENT] The main tree's `FINDINGS.md` still records a narrow-the-check proposal that
   M40-4 falsifies, and brief item 8 says this sentence must change.** Brief item 8's last
   paragraph: *"this change moves `zikaron/hook` and `zikaron/service`, which §7's package check
   covers, so the choice `FINDINGS.md` records before the repeats — narrow the check or
   re-`prepare` — must cover those two packages too."* `/home/nathan/Zikaron/FINDINGS.md:229–236`
   still reads *"narrow that check to what a run executes — leave `zikaron/code_knowledge`,
   `zikaron/core/code_knowledge` and `zikaron/install` out of both the porcelain and the diff, one
   sentence in §7 — which keeps the slice, run under an unchanged server, service, hook and
   index"*. Once this PR lands, *unchanged service, hook* is false — the service gains
   `knowledge_remind` and `memory_surface`'s receipt, the hook gains an event and the
   `failure.classify`/`HookDeadline` relocation, `zikaron/guard/grep_filter.py` and
   `zikaron/harness/spec.py` move too — and the narrowing predicate *what a run executes* cannot
   leave `zikaron/hook` or `zikaron/service` out, since the Warp copies' pushes and MCP calls run
   both. So the proposal a fresh session resumes from would, applied as written, leave §7's check
   red and the slice no more re-runnable than today. Edit, in the main tree after *"(about
   $49)"*: *"**M40-4 moves `zikaron/hook`, `zikaron/service`, `zikaron/guard/grep_filter.py` and
   `zikaron/harness/spec.py` as well, and a run does execute the first two**, so the narrowed
   check cannot exempt them by that predicate. What holds instead: the copies are not
   re-installed, so no `PostToolUse` entry exists there, the hook's new event never fires and
   `knowledge_remind` is never called; the push path's change is a relocation with no behavioural
   difference; and `memory_surface`'s receipt touches only an in-memory table nobody reads. The
   §7 sentence would exempt those packages on that stated ground, or the re-`prepare` is taken —
   the operator's call before repeat 1."*

2. **[IMPROVEMENT] `design/retrieval.md:27–32` says the channel this build ships does not exist.**
   *"The moment a memory is most needed … arrives twenty tool calls later, when no injectable hook
   fires. … `postToolUse` fires per tool call and does receive `tool_response`, but has **no
   documented stdout→context path**. Unresolved"* — stated harness-generally, in a normative
   document. Under Claude Code it has been false since D38's nudge, and the artifact under review
   is a `PostToolUse` hook whose `additionalContext` was measured reaching the main session and a
   subagent (`research/m40-4-hook-probes.md`), carrying a knowledge reminder mid-turn. A reader of
   `retrieval.md` now concludes a mid-turn injection is impossible, where the true state is that it
   is possible and the push does not ride it — a design choice M40-4's fence makes explicit, not a
   harness limit. The limitation itself stands and should stay. Edit, the paragraph's last two
   sentences: *"Symptom-triggered recall must therefore come from pull, which means the agent has
   to remember to pull. Under kiro `postToolUse` fires per tool call and receives `tool_response`
   but has no documented path to the model; under Claude Code `PostToolUse`'s `additionalContext`
   does reach it — the channel D38's nudge and the search reminder use (`design/code-knowledge.md`
   §6) — and the push does not ride it, so this is open as a design question rather than closed
   by the harness; see `FINDINGS.md` open question 1."* And the one clause in the main tree's Q1
   that carries the same premise: *"when no injectable hook fires"* → *"when no hook the push
   rides fires — under Claude Code `PostToolUse` could carry one (D38, M40-4), untried"*. The
   staleness predates this build; the build is what makes it conspicuous, and the minimum is the
   one clause in each place.

3. **[NITPICK] `design/schema.md` §Bounds, the `paths` row: "one that names no module asks
   nothing" says something the hook cannot know.** The hook never sees a module — it asks whenever
   the store holds a corpus database and the command parsed as a search; what asks nothing is a
   command the parser reads as no search. Edit: *"Never empty, because a search with no path
   covered its working directory and a command that runs no search asks nothing"*. Brief item 4
   has the same phrase and can stand as a record; the normative table should be exact.

4. **[NITPICK, optional] `design/harness.md`'s table enumerates output channels by trigger kind
   (rows 64–65: spawn/prompt → stdout, subagent → `additionalContext`) and leaves the tool event's
   unstated there.** It is stated in prose at line 650 and pinned by `CHANNELS` and
   `test_the_search_reminder_goes_out_on_the_tool_events_structured_channel`, so nothing drifts;
   but the table is where a reader looks a channel up. Add after row 65: *"| Output channel, tool
   event | n/a | `hookSpecificOutput.additionalContext` — plain stdout goes to the debug log alone
   (`tool-hook-probe`), measured reaching the main session and a subagent alike
   (`m40-4-hook-probes`) |"*.

VERDICT: NEEDS_CHANGES

### Author's responses to round 7

1. **Accepted, with the recommendation the entry owes.** The main tree's `FINDINGS.md` now says
   M40-4 also moves `zikaron/hook` and `zikaron/service`, which a run executes, so narrowing the
   check by that predicate can no longer keep the slice, and that exempting them would rest on an
   argument the check cannot verify (the three grounds named); it proposes re-`prepare` at the
   PR's merge commit and re-running the slice, about $49, so every cell runs one build. The
   choice stays the operator's.
2. **Accepted.** `design/retrieval.md`'s paragraph and Q1's clause, as worded.
3. **Accepted**, as worded.
4. **Accepted.** The row is in `design/harness.md`'s table, and
   `test_the_search_reminder_goes_out_on_the_tool_events_structured_channel` now reads it — kiro's
   cell carries an absence marker, Claude Code's names `additionalContext` — beside `CHANNELS`.

## Round 8 — 2026-10-21

**Summary judgment.** Round 7's four fixes are in the tree as described: the main tree's
`FINDINGS.md` now says M40-4 moves `zikaron/hook` and `zikaron/service`, which a run executes, and
proposes the re-`prepare` (lines 232–237); Q1 reads *"when no hook the push rides fires — under
Claude Code `PostToolUse` could carry one (D38, M40-4), untried"* (671–674); `design/retrieval.md:27–32`
states the kiro/Claude Code split and keeps the limitation; `design/schema.md`'s `paths` row says a
command that runs no search asks nothing; and `design/harness.md`'s table carries the tool-event
channel row, which the renamed test parses. Read fresh this round rather than carried from earlier
ones: the six new modules whole, the four new test files whole, the full diff, the brief's items 2–8,
invariants, done-when and fence, and the normative sections it names. I traced every item 3 reading
against `read_grep`'s `--`/`-e`/`-f` handling and `_after_revisions` for the leading-`--` form, the
`on_receipt` ordering in `server._invoke` against the two refused-push tests, `_spliced` and
`_Slot.holds`/`owns` against each of the invariant list's install cases, and the follow-on counter's
documenter exclusion against the `.meta.json` it reads. A sweep of the worktree's prose outside the
evidence trails for the retired counts and phrasings (`three hooks`, `three triggers`,
`many-to-three`, `eighth RPC`, `only knowledge method`, `Nothing tells your agent`, `no documented
stdout`, `no injectable hook`) finds them only where the brief quotes them, in `FINDINGS-archive.md`,
and in D32's own struck text. The code does what the brief and the normative sections say, every
invariant has a test, and done-when 2's note carries the ordered observations, the timing without a
bar, the transcript evidence and the instrument with its baseline. What remains is two nitpicks,
neither of which I would hold the build for.

**Findings.**

1. **[NITPICK] `design/code-knowledge.md` §6 "What it costs" (line 793) prices a matched call and
   not the unmatched starts the brief budgets.** Brief item 4: *"A `Bash` command the filter cannot
   read — any heredoc, measured — starts both `Bash` handlers together, about one start's wall time
   in every memory install; … So does any simple command whose text carries `grep ` beyond a search
   — `pgrep`, an `echo`, a commit message — at one start and no connect."* §6 says *"a hook process
   for each `Grep` and `Glob` and each matched `Bash` call"*, so a reader budgeting from the
   normative section counts one process per search and none for a heredoc, where every heredoc in
   every memory install starts two. One clause closes it, after *"each matched `Bash` call"*: *"— a
   match being the `if` filter's, so a `pgrep`, an `echo … grep …` or a commit message carrying
   `grep ` starts one too, and a command the filter cannot read, any heredoc, starts both `Bash`
   handlers together at about one start's wall time (`research/m40-4-hook-probes.md`) —"*.

2. **[NITPICK, optional] A non-literal operand — a `$(…)` or a `$VAR` — is read as a path under the
   `cwd` rather than as a path named elsewhere.** `grammar.py:9` keeps a same-line `$(…)` as one
   token of the enclosing command, so for `grep -rn needle $(git ls-files '*.py')` `read_grep`'s
   `paths` is `["$(git ls-files '*.py')"]` and `shell_search._paths` (`shell_search.py:198–207`)
   makes it `<cwd>/$(git ls-files '*.py')`; `git -C "$DIR" grep needle` gives `<cwd>/$DIR` the same
   way. From the project root that reaches the root module alone and none below it, where the
   command searched every tracked file. It is the class §8 already names — *"a search whose paths
   come from elsewhere"* — in a spelling the stand-in rule (`:202`) does not cover, and it is benign:
   the bogus path lies under the `cwd`, so it reaches only the modules the `cwd` is inside, which
   the search did cover, never a module it did not. If closing it: extend the check at `:202` with
   `"$" in path or "`" in path`, add `grep -rn needle $(git ls-files)` and `grep -rn needle "$SRC"`
   to `test_a_command_that_searches_nothing` (`tests/test_hook_shell_search.py:104–154`) with the
   rule removed as the mutation, and one clause in §8's miss list beside the `{}` sentence: *"or a
   `$(…)` or variable among them"*. Declining is reasonable; an under-reach costs a reminder, not a
   false one.

VERDICT: APPROVED

### Author's responses to round 8

1. **Accepted**, as worded, in §6 "What it costs".
2. **Declined**, on the round's own reading: the bogus path lies under the cwd, so it reaches only
   modules the search did cover, and the cost is a reminder not given, never a false one; a code
   change after approval would also stand unreviewed.
