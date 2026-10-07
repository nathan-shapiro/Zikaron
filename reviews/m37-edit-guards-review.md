# M37 — edit guards: build review

## Prompt texts — 2026-10-07

Written against `design/edit-guards.md` §3.4, §3.5, §4 and §5 (read whole, with §2, §7 and §8 for
what each text has to agree with), `design/build-plan.md` §M37 item 7, the brief's facts about how
each text is delivered, `research/claude-code-tool-hooks-docs.md` §3.3 (statements, not commands,
in `additionalContext`; never write a `<system-reminder>` tag) and §12, and
`zikaron/hook/write_policy.py`'s `WRITE_POLICY_PROMPT`, which the start text follows under
`--components both`. The nudge keeps §4's draft wording unchanged; the others are new. **Amended
in place 2026-10-07 for §3.2 row 6** — the start text, the deny message's scratch clause and the
`{form}` table; note 4 under §"Notes for the build" says what moved and why — **and again the same
day for §3.4's re-read ask** — the acknowledgement alone; note 5.

**Properties common to all five, for the builder and the tests.** Every text is ASCII — no em
dashes, no curly quotes — so a test asserts it as a plain literal and the live test greps it
without escaping. The four hook messages are each **one line**: no newline anywhere, because they
are JSON string values shown inline after the harness's prefix. The start text is the only
multi-line one; it is hard-wrapped under 100 columns like `WRITE_POLICY_PROMPT`, has no leading or
trailing newline, and the blank line between the policy and it under `both` is the hook's to
emit, not part of the text. Tool names (`Read`, `Edit`, `Write`) are written bare, as the write
policy writes `zikaron_memory_search`; commands and paths are in backticks. The override syntax
is shown bare, never in backticks, so a copied line carries nothing the shell would read before
the `#`. No text contains `{` or `}` other than the placeholders, so `str.format` is safe.

**Assumptions.** `{word}` is the brief's: the command word as written, without its path prefix —
rendered here in backticks, as given. The invalid-marker message takes the deny message's target
part unchanged, as the brief permits. Where I quote a character count below, it is counted by
hand; the builder's test should assert the sum against `HarnessSpec`'s budget rather than take my
figure.

### 1. Guard start text (§5)

Static. The whole start output under `--components guards`; follows `WRITE_POLICY_PROMPT` (or the
subagent policy) after one blank line under `both`. Its `## ` heading parallels the policy's own,
so under `both` the two read as sibling sections. It states the rule, says that a hook enforces
it (so a later deny is attributable), names the scratch roots an agent would actually use, says
they are exempt *as targets* and that a script run from one is judged by what it writes (§3.2
row 6: an unqualified "scratch is exempt" would tell the agent its `/tmp/fix.py` is exempt, which
is the opposite of the rule), and tells the agent where the nudge comes from and that it asks for
one re-read per file, not one per edit. It does not mention the override, by §5's operator
decision.

```
## Editing files (Zikaron edit guards)

Authored files in this project are edited with Read then Edit, or with Write for a new file, and
never with `sed -i`, an inline interpreter script, a script written to scratch and then run, or
a heredoc or other redirect of literal text into a file, each of which changes text that has not
been read in its current state. A hook in this project refuses a Bash command that does so.
A path under /tmp, /var/tmp or $TMPDIR is scratch and exempt as a target; a script run from
there is judged by what it writes, not by where it is. After each edit, a reminder from this
project's hooks notes that the file has not been re-read; it asks for one re-read of the edited
material and its surroundings once that file's editing is finished, not one re-read per edit.
```

Budget: about 800 characters, all BMP, so about 800 UTF-16 units; the longest line is 96
columns. `WRITE_POLICY_PROMPT` is about 3,500 by line count. Both together are well inside Claude
Code's 10,000-unit budget, and a test asserting `len(policy) + 1 + len(guard_text)` against
`spec.injection_budget` costs nothing.

### 2. Deny message (§3.5)

`permissionDecisionReason`. The model reads it as the tool result after `PreToolUse:Bash hook
error: `, so it opens with a sentence that completes that prefix. §3.5's order: form, targets,
why, alternative, override syntax with a concrete reason. One paragraph. It also names the scratch
roots, because a misread target (`/home/u/proj/~/f`) and an unresolvable one (`$(mktemp)`) are the
two cases where the agent has to decide between fixing the path and overriding, and the message is
the only thing in front of it at that moment. The scratch clause says *a target* under those
roots is exempt, not *a path*: in a row-6 deny the `{word}` has just run a script that is under
one of them, and an unqualified clause would read as the message conceding the deny is mistaken —
the override reason it offers two sentences later. The override example closes the message and
ends with a period; a copied reason that includes the period is still two words and valid.

```
Zikaron's find-replace guard refused this command: `{word}` {form}; it names {targets}. That is an edit made to text you have not read in its current state. Authored files are edited with Read then Edit, or with Write for a new file; a target under /tmp, /var/tmp or $TMPDIR is scratch and exempt. If this command is nonetheless the right tool here (a file whose bytes a program owns, a bulk mechanical change, or a deny that is mistaken), run it again with a shell comment of exactly this form, giving your own reason in at least two words on that line: #ZIKARON-FORCE #Reason: regenerate golden file.
```

**The target part** is the clause `it names {targets}`, in two forms:

- one or more resolved paths — `it names {targets}`, where `{targets}` renders each non-scratch
  target as resolved, absolute, in backticks, joined by `, ` in command order:
  `` it names `/home/u/proj/CLAUDE.md` `` · `` it names `/home/u/proj/a.md`, `/home/u/proj/b.md` ``
  · `` it names `/home/u/proj/~/f` `` (the misread shows, as §3.5 asks). When some targets
  resolved and some did not, only the resolved ones appear, in this form.
- none found — a form with no target token, a row-4 target expression yielding nothing, or a
  row-6 script whose matched rows name nothing the rules can resolve — renders as the fixed
  clause:

```
it names no target the guard could resolve
```

So §8's "naming `X`" cells assert `` it names `<cwd>/X` `` and its "naming no literal" cells
assert `it names no target the guard could resolve`.

**`{form}`** — one label per §3.2 row, a verb phrase that follows `` `{word}` ``:

| Row | `{form}` |
|---|---|
| 1 | `edits a file in place (-i or --in-place)` |
| 2 | `edits a file in place (-i)` |
| 3 | `edits a file in place (-i inplace)` |
| 4 | `runs an inline script that writes a file` |
| 5 | `writes literal text to a file` |
| 6 | `runs a scratch script that writes a file` |

Rendered: `` `gsed` edits a file in place (-i or --in-place); it names `/home/u/proj/CLAUDE.md`. ``
· `` `python3.12` runs an inline script that writes a file; it names no target the guard could
resolve. `` · `` `tee` writes literal text to a file; it names `/home/u/proj/f`. ``
· `` `python3` runs a scratch script that writes a file; it names `/home/u/proj/f`. ``
· `` `bash` runs a scratch script that writes a file; it names `/home/u/proj/f`. `` When several
forms match, §3.2 says the message names the first with a non-exempt target; `{word}` and
`{form}` are that form's. Row 6's `{word}` is the shell or interpreter word that ran the script
(`python3`, `node`, `bash`, `sh`), never the script's path, and its targets are what the script
would write (§3.3's row-6 bullet), so the row-6 message is the row-4 one with *scratch* in place
of *inline* — the one word that tells the agent the deny is about what the script writes, not
about where it sits.

**The placement clause** — appended, after one space, when the command carried `#ZIKARON-FORCE`
only inside a heredoc body or a quoted string:

```
The #ZIKARON-FORCE in this command is inside a heredoc body or a quoted string, where it is content rather than a comment. The override is a shell comment outside both: on the heredoc opener's line, on a line after its delimiter, or after a multi-line string's closing quote; on the delimiter line it would stop the heredoc terminating and be written into the file.
```

### 3. Invalid-marker message (§3.4)

`permissionDecisionReason`, for a marker present outside every body and string with no comment
carrying a valid override. One text for all six shapes, so it states the whole valid form rather
than diagnosing one defect; each clause answers one shape — "at the start of a line or after
whitespace" the glued marker, "#Reason: follows it" the bare marker, "with that spelling and
capital R" the lower-case `#reason:`, "on the marker's line" the reason on the next line, "at
least two words" the one-word reason, "outside angle brackets" the `<few words>` template. Same
placeholders and the same target part as the deny message.

```
Zikaron's find-replace guard refused this command: `{word}` {form}; it names {targets}. It carries #ZIKARON-FORCE, but no comment in it is a valid override. A valid override is one shell comment in which the marker stands at the start of a line or after whitespace, #Reason: follows it with that spelling and capital R, and your own reason follows on the marker's line, at least two words outside angle brackets: #ZIKARON-FORCE #Reason: regenerate golden file.
```

No placement clause here: §3.4 gives a marker that is only inside a body or a string the
*ordinary* deny message, and this message is for a marker that is outside them.

### 4. Override acknowledgement (§3.4)

`additionalContext` with no `permissionDecision`; the model sees `PreToolUse:Bash hook additional
context: ` and then this. Statements only, since it travels as context. It names the reason, says
the deny is withdrawn for this command only (an override is not sticky), says the harness's own
permission flow still decides, and says the override and reason are in the transcript, which is
where §7 counts them. **Amended in place 2026-10-07 for §3.4's re-read ask** (note 5 under
§"Notes for the build"): it then names what the command changes and asks for the re-read that
§4's nudge cannot, since no hook fires after a `Bash` call with anything to say about the files
the command wrote. The two added sentences are the nudge's two in shape — a statement about the
material, *this command changes X* beside the nudge's *X was edited*, then *once …, the next step
is to re-read all the … material and its surroundings* — with the command's run in place of the
file's editing as the moment and *changed* in place of *edited*, so the agent meets one shape of
ask whichever tool changed the file. The clause between them says why the ask arrives before the
run rather than after it, as a statement rather than an instruction (§4's injection-defence
reason).

```
#ZIKARON-FORCE accepted by Zikaron's find-replace guard, reason: {reason}. The guard's deny is withdrawn for this command only; the usual permission flow applies to it, and the override and its reason are recorded in the transcript. This command changes {targets}. No re-read reminder follows a Bash call, so once it has run, the next step is to re-read all the changed material and its surroundings.
```

`{reason}` renders verbatim: the text after `#Reason:` to the end of its line,
whitespace-trimmed, no quotes added, nothing truncated. **`{targets}` renders as the deny's target
part renders** (subsection 2): each path resolved, absolute, in backticks, joined by `, ` in
command order — `` This command changes `/home/u/proj/a.md`, `/home/u/proj/b.md`. `` — or, where
none resolves, the same fixed clause, so the sentence reads
`This command changes no target the guard could resolve.` **The set is wider than the deny's**:
§3.4 asks for every target that is not exempt of *every* form that matched, where the deny names
the first such form's (§3.2), so an override of a command that matched twice names what both
forms would write; a path two forms reach appears once, at its first position. A misread shows
here exactly as it shows in the deny (`/home/u/proj/~/f`), and the agent that overrode a deny as
mistaken has already judged it. **The fixed substring for the live test and for §7's count (b)**
is `#ZIKARON-FORCE accepted by Zikaron's find-replace guard`, unchanged by the amendment — it
occurs in no other text, and it does not contain `#ZIKARON-FORCE #Reason:`, so a grep for the
command form and a grep for the acknowledgement count different things.

### 5. Re-read nudge (§4)

`PostToolUse` `additionalContext`. §4's draft is kept word for word: it is the operator's
content, it is already two factual statements about the file rather than an instruction (the
docs note's injection-defence guidance), it carries the once-per-file semantics, and its fixed
characters count to exactly the 218 §4 states — the backticks around `{ranges}` are part of that
count — so §4's cost figure stays true and no document moves.

With a patch:

```
`{path}` was edited (lines `{ranges}`) and has not yet been re-read for flow and consistency with the rest of the file. Once editing of this file is finished, the next step is to re-read all the edited material and its surroundings.
```

Without one (`NotebookEdit`, or a result shape the hook does not recognise):

```
`{path}` was edited and has not yet been re-read for flow and consistency with the rest of the file. Once editing of this file is finished, the next step is to re-read all the edited material and its surroundings.
```

`{path}` renders as given — `tool_input.file_path` or `notebook_path`, absolute — inside the
backticks. `{ranges}` renders each hunk's new-side inclusive range as `start-end` with an ASCII
hyphen, a one-line hunk as `start` alone, hunks joined by `, ` in patch order: `` lines `12-18` ``
· `` lines `12-18, 40` `` · `` lines `1-120` `` for a `Write` overwrite's full hunk.

### Notes for the build

1. **[IMPROVEMENT] Count (b) in `research/` must not be a transcript-wide grep for
   `#ZIKARON-FORCE #Reason:`** — both deny messages carry that literal as the override example,
   so every deny's `tool_result` would count as an override. Read `tool_input.command` fields, or
   grep the acknowledgement's fixed substring above, which §7 already names as the simpler route.
   No design change; a note for whoever writes the count.
2. **[NITPICK] The `{form}` labels are mine and the tests pin them**, so a §3.2 row added later
   needs a label added here in the same change; §8's own rule (the table and this file disagree →
   decided in code review) covers it.
3. **[NITPICK] The start text names three scratch roots and §3.3 names five** (`/dev` and
   `scratchpad_dir` omitted as roots no agent edits by hand). It says those three are exempt, not
   that only they are, so it is true as written; if §3.3's list ever changes, this is the one
   second copy of it in a prompt.
4. **Amended 2026-10-07 for §3.2 row 6** — a shell or row-4 interpreter whose script operand is
   scratch has that script judged by its text — on the operator's direction to make the change
   before the arms re-run, the pattern having proved common. What moved, and why:
   - **The start text** (subsection 1). Its list of refused means gains *a script written to
     scratch and then run*, and its scratch sentence now says a scratch path is exempt *as a
     target* and that a script run from there is judged by what it writes, not by where it is —
     §5's amended content requirement, and because the old sentence ("a path under /tmp … is
     scratch and exempt") told the agent its `/tmp/fix.py` is exempt, which under row 6 is
     exactly what the operand is not. The heading, the hook-attribution sentence and the nudge
     sentence are unchanged.
   - **The `{form}` table** gains row 6, `runs a scratch script that writes a file` — parallel
     to row 4's label, so the two denies differ in the one word that matters.
   - **The deny message's scratch clause** reads *a target under* rather than *a path under*:
     one word, for the same reason as the start text — in a row-6 deny the script *is* under
     `/tmp`, and the unqualified clause would read as the message conceding the deny is mistaken,
     the override reason it offers two sentences later. That moves `DENY_TEMPLATE`; the
     invalid-marker message, the placement clause, the acknowledgement and both nudge texts are
     unchanged, and no test asserts the moved substring (`tests/test_guard_claude_live.py` greps
     the opening sentence, which does not move).
   - **The "none found" clause's** list of cases gains the row-6 one. The fixed clause itself is
     unchanged.
   Every property the section's opening paragraph lists still holds: ASCII throughout, each hook
   message one line, the start text hard-wrapped under 100 columns with no leading or trailing
   newline, no `{` or `}` but the placeholders, and neither the override syntax nor the word
   *Reason* in the start text. The start text and either policy together stay inside the
   10,000-unit budget. For the build: `Form` gains a member valued 6 and `FORM_LABELS` its entry,
   which `tests/test_guard_texts.py` reads from the table above through its single-digit pattern;
   `GUARD_START_TEXT` and `DENY_TEMPLATE` are copied verbatim from their blocks.
5. **Amended 2026-10-07 for §3.4's re-read ask** — the acknowledgement names what the overridden
   command changes and asks for one re-read of it once the command has run — on the operator's
   direction (*"Can we first implement re-read after FORCE, then re-read C, then consider work
   done?"*), because in the interactive live test an agent overrode a row-6 deny with a true
   reason, its scratch script then rewrote fourteen files, and no re-read was asked of any of them:
   the nudge fires only after `Edit`/`Write`, and the override is the one path by which a guarded
   edit reaches a file through `Bash`. What moved, and why:
   - **The acknowledgement** (subsection 4) gains two sentences after its last: *This command
     changes {targets}.* and *No re-read reminder follows a Bash call, so once it has run, the
     next step is to re-read all the changed material and its surroundings.* They are the nudge's
     two sentences with the command's run as the moment, so one shape of ask reaches the agent
     whichever tool changed the file. The middle clause is there because the ask arrives before
     the run, the opposite of the nudge's timing, and a statement of why reads as context rather
     than as a system command. The no-target case asks for the same re-read of whatever the
     command changed, which the agent that wrote the command knows and the guard does not — the
     fourteen-file script would have been that case.
   - **`{targets}`**, a new placeholder, rendered as subsection 2's target part — the same
     backticks, `, ` and fixed clause — over §3.4's wider set, each path once.
   - Nothing else moves: the first three sentences, the fixed substring and `{reason}`'s rendering
     are as they were; the deny, the invalid-marker message, the placement clause, the start text
     and both nudge texts are unchanged.
   Every property the section's opening paragraph lists still holds: ASCII, one line, `Bash`
   written bare as the other tool names are, and no `{` or `}` but the two placeholders. For the
   build: `ACKNOWLEDGEMENT_TEMPLATE` is copied verbatim from the block; `acknowledgement(reason,
   targets)` — the signature `main.py` and `Acknowledge.targets` already carry — renders `targets`
   through the one join `deny_message` builds its `targets` from, factored into a helper both
   call so the two cannot render differently; `tests/test_guard_texts.py` line 78 and
   `tests/test_guard_main.py` line 56 pass it a tuple. A test should assert what §8's `ack` rows
   do not: a two-form command's acknowledgement names both forms' targets in command order, and a
   no-target one (`python3 -c "P('f').write_text('x')" #ZIKARON-FORCE #Reason: a b`) renders the
   fixed clause.

Every content requirement in §3.4, §3.5, §4 and §5 — §5 as amended for row 6, §3.4 as amended for
the re-read ask — is met by the texts above as they stand, and nothing in the design had to move
to meet it.

VERDICT: APPROVED

## Round 1 — 2026-10-07

**Summary judgment.** The build is close to shippable. The guard package implements §3 as written:
I hand-traced the parse for the rows most likely to diverge (unclosed `$(` inside a multi-line
string, the continued-opener heredocs, the comment-swallowed `<<`, the process-substitution misses,
the bound-variable and `cd` rows, the row-4 head/chain cases) and found the code giving §8's value
in each; `tests/edit_guard_table.py` reads §8 from the document fail-closed, so the table cannot
drift silently; the installer's union-and-ownership logic is right on the normal-run plane and the
perturbation test walks that plane whole; every document item 6 owes is present, `CLAUDE.md`'s
`harness.md` row has lost its flag count, and `FINDINGS.md` on disk is current. One defect blocks:
the `--print-only` preview contradicts the install in exactly the prior-state × selection cell §5
makes a point of, and that cell of the brief's perturbation table was never walked. The rest is
small.

**Findings.**

1. **[BLOCKER] `--print-only` previews a start entry the install would not write.**
   `zikaron/install/targets.py`, `ClaudeCodeTarget.fragment`, builds
   `claude_hooks_value(plan.commands, plan.components)` with no `start=`, while `_plan_settings`
   passes `start=_start_selection(by_trigger, plan)`. So `--print-only --components guards` over a
   memory install prints `SessionStart`/`SubagentStart` commands ending `--components guards`, and
   the real run writes `--components both`; the reverse (`memory` over `guards`) prints a bare
   `zikaron-hook` where the run writes `--components both`. A user applying the preview by hand —
   the path `--print-only` exists for — would drop the write policy from the start hooks. The
   method's own docstring sets the standard it fails ("the preview is a preview of *this*
   install"), and `design/build-plan.md` §M37's perturbation table names the mode as an axis;
   `test_print_only_writes_nothing_and_shows_the_selections_groups` walks it only over an empty
   project. **Fix:** in `fragment`, compute the start selection from the existing file read-only —
   `by_trigger = _hook_groups_by_trigger(_load_json_object_or_empty(path), path)` inside a
   `try`/`except InstallError` that falls back to `plan.components` (a preview refuses nothing it
   does not have to, as the print-only path already says) — and pass it as `start=`. Add to
   `tests/test_install_components.py`: install memory, then `--print-only --components guards`,
   assert the printed start command ends `--components both` and the tree is unchanged; and the
   mirror cell, guards then `--print-only` with no flag.

2. **[IMPROVEMENT] A row-4 target with a bound variable is judged substituted but named
   unsubstituted.** `zikaron/guard/forms.py` `_script_target` builds the displayed path with bare
   `normalise(judged.path, location.cwd)` while `_word_target` uses `location.resolve(raw)`, which
   applies `_substituted`. `is_scratch` does substitute on both paths, so for
   `R=research; python3 -c "open('$R/f','w')"` the verdict follows `research/f` (not scratch) and
   the message says `` it names `/home/u/proj/$R/f` ``. §3.3 says such a target "is read with the
   variable's value in its place" and §3.5 that the message shows targets "as resolved", and §8's
   `S=/tmp/x; python3 -c "open('$S/f','w')"` → silent row already establishes that the rule reaches
   row-4 literals. **Fix:** add `Location.resolve_text(text)` =
   `normalise(self._substituted(text), self.cwd)` — no `unquote`, since a script literal's
   delimiters are already gone and its content may hold a quote — use it in `_script_target`, and
   add the §8 row `R=research; python3 -c "open('$R/f','w')"` → deny, naming `research/f`. This is
   the code meeting §3.3's existing sentence, not a rule change.

3. **[IMPROVEMENT] `test_the_form_labels_are_the_reviewers` reads the whole review file.**
   `tests/test_guard_texts.py` line 84–86 runs `re.findall(r"^\| (\d) \| `([^`]+)` \|$", …)` over
   the entire file, not the `## Prompt texts` section the other tests scope to. This file accrues
   review rounds — this one included — so any later round that writes a table row with a
   single-digit first cell and a backticked second cell either reddens the gate or silently joins
   `labels`. **Fix:** slice to the section first, e.g.
   `section = text.split("## Prompt texts", 1)[1].split("\n## ", 1)[0]`, or reuse
   `_prompt_texts`'s section tracking to collect the table lines.

4. **[IMPROVEMENT] A false deny the new `cd` rule creates is listed nowhere in §7/§8.**
   `Location.moved_to` reads `DIR` as a path, so `cd "$TMPDIR" && echo y > f` (and
   `cd $TMPDIR && sed -i 's/a/b/' f`) resolves `f` to `<cwd>/$TMPDIR/f`: the `$TMPDIR`-literal
   exemption looks only at the target's own text and never sees it, and no root matches. Verified
   by hand against `scratch.py`. Likewise `cd $(mktemp -d) && echo y > f` → deny naming
   `$(mktemp -d)/f`, the stated `$(mktemp)` class by a new route. Under §7's own rule these are
   conceived edges — no rule change — but §7 says a conceived edge "becomes a §8 row with the value
   the rules already give it", and §7's false-deny list names `cd -` and `cd ~/x` without these.
   **Fix:** add `cd "$TMPDIR" && echo y > f` → deny, naming `$TMPDIR/f` (parsed as stated) and
   `cd $(mktemp -d) && echo y > f` → deny, naming `$(mktemp -d)/f` to §8, and the `$TMPDIR` case to
   §7's "false denies" bullet beside `cd ~/x`. On macOS, where `$TMPDIR` is the scratch root an
   agent is most likely to `cd` into, this is the one the override will be answering.

5. **[NITPICK] `FINDINGS.md` §"Current state" lead and one sweep line.** Line 88 still opens
   "**Next: build M37, edit guards**" while the block beneath marks every step done and names the
   review as next; reword to "**M37, edit guards, is built and in review (operator, 2026-10-06)**".
   Line 119's "the mutation pass: 45 mutations, each red against the test it names" is what a sweep
   covered, which `CLAUDE.md` §"Project memory" sends nowhere; delete the clause and keep the gate
   result.

6. **[NITPICK] `interpreter._as_interpreted` mis-collapses a run of escapes.** After collapsing
   `\\` or `\"`, `previous` is set to the escaped character rather than cleared, so a third
   backslash is read as escaped by the one that was itself consumed: `"a\\\"b"` yields `a"b` where
   the shell yields `a\"b`. The write patterns allow `\\?` before a quote, so detection is
   unaffected; only the text handed to `expression` differs. Fix: set `previous = ""` after the
   `text[-1] = char.text` branch.

7. **[NITPICK] `design/harness.md` §"What a Claude Code install writes" counts the start entries
   twice.** The "Hook entries | memory | three entries" row includes the two start groups that the
   next row lists for every selection, so a reader summing the table gets five groups for `memory`
   where the file has three. Say "the prompt trigger, `UserPromptSubmit`" in the first row (and
   drop the tally, which `CLAUDE.md` asks for anyway), or fold the two rows into one.

**Checked and not raised.** The hook's import of `zikaron.guard.start_text` pulls an empty package
`__init__` and `typing` only, so the memory hook's per-call cost does not move. The two §3.3 rule
changes are implemented as the operator took them (assignment-only simple commands; `cd DIR`
outside a `(` unit; a scanned body starting clean), and `experiments/m37_guard_prototype.py`'s
subscript-chain disagreement is the product following §3.3's text. The research notes support the
decision they carry — two rule changes and nothing else — and nothing in them would move that.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-07

**Summary judgment.** All seven round-1 findings are applied as described, and each fix is the
right shape: `fragment` now previews the union the install would write and falls back on an
unreadable file; `resolve_literal` carries a bound variable into a row-4 literal and §8 holds the
row; the texts test is scoped to the section; §7 and §8 carry the `cd "$TMPDIR"`/`cd $(mktemp -d)`
cases; `_as_interpreted` spends an escaping backslash; the harness table counts the start entries
once; `FINDINGS.md`'s lead is current. I re-traced the parse for the classes most likely to hide a
defect — the step-1 reading of an unpaired `"` before `$(cat <<`, the comment-swallowed opener,
`$((…))`, continued opener lines, the `tee` walk-back, bound-variable and `cd` resolution, and
every row-4 head step against §8's rows — and found the code giving §8's value everywhere except
one conceived edge where `heredoc._continues` reads a line differently from `lexer` and from
§3.1. That, plus a §7 sentence that states a false deny the rules do not produce (and whose
missing §8 row is why nobody noticed), is what stands between this and APPROVED; both are small
and bounded. **Assumption:** this session has no shell, so the gate, coverage and mutation claims
in the brief are taken as reported, and every trace here is by hand.

**Findings.**

1. **[IMPROVEMENT] `heredoc._continues` treats a backslash that ends a *comment* as a line
   continuation, which `lexer._join_continuations` and §3.1 do not.**
   `zikaron/guard/heredoc.py` `_continues` counts trailing backslashes on the **raw** line before
   it strips the comment, while the `|`/`&&` test on the next line is made on the comment-stripped
   `code`. §3.1 step 3 says continuations are joined "outside data bodies, strings and
   **comments**", and step 1 says it "reads the same way for a body's start … as the shell reads
   it". The two readers therefore disagree on where a body begins when the opener's line ends in
   a comment ending in `\`. Hand trace of
   `cat > /tmp/x <<'EOF' # staged \` / `sed -i 's/a/b/' f` / `EOF` under §8's payload:
   `_continues(line 0)` → raw trailing `\` → group `[0, 1]` → the body is sought from line 2,
   which is `EOF`, so the body is **empty** and `sed -i 's/a/b/' f` becomes one of the unit's
   own lines; `lexer` then (correctly) does not join it, so `parse` yields a second pipeline and
   the result is **deny naming `/home/u/proj/f`**. By the design the body is `sed -i …`, under
   `cat` it is data, and the command is **silent**. A false deny the design does not predict, on
   exactly the shape — a staged scratch script — the data-body rule exists for. **Fix:** make
   `_continues` test the comment-stripped text on both branches:
   `code = _code_before_comment(line)[0]; trailing = len(code) - len(code.rstrip("\\")); if
   trailing % 2 == 1: return True; return code.rstrip().endswith(("|", "&&"))`. I checked the
   §8 rows that end a line with `\` after a comment (775's `# note \`, 772's and 834's
   continuations outside a comment): none moves. Add to §8:
   `cat > /tmp/x <<'EOF' # staged \` / `sed -i 's/a/b/' f` / `EOF` → silent (a `\` ending a
   comment continues nothing, so the body begins on the next line), and its control
   `bash <<'EOF' # run \` / `sed -i 's/a/b/' f` / `EOF` → deny. The first row is red on the tree
   as it stands and green after the one-line change; no rule moves, the code meets the stated
   one.

2. **[IMPROVEMENT] §7 states a false deny the rules do not give, and the edge has no §8 row.**
   `design/edit-guards.md` §7 line 557–559: *"a `>` inside `((…))` is arithmetic but reads as a
   sink, so `echo $(( 1 > 0 )) > /tmp/x` is a false deny on scratch."* Trace: `_dollar` reads
   `$((` as `$(` + `(`, `same_line_close` finds the last `)`, and the inner text `( 1 > 0 )` is
   parsed as its own pipeline — `(` is a subshell boundary, so the inner simple command's command
   word is `1`, and its `> 0` is a sink of a command that matches **no row**. The enclosing
   `echo … > /tmp/x` keeps its sink, which is scratch. The product is **silent**, which is also
   what §3.1's own text gives ("the first word inside it is still in command position"). The §7
   sentence is therefore a false claim in a normative document, and it survived because the brief's
   invariant — "the test table holds … every edge §7 names with the value §7 gives it" — is not
   met for it: there is no `$((` row in §8. The same bullet and the "write form not in §3.2's
   table" bullet name several more edges with no row (`echo x>f`, `cat<<EOF > f`, `exec > f`,
   `truncate -s 0 f`, `paths[0].open('w')`, and the `dd`/`install`/`cp`/`rsync`/`git apply`/
   `patch`/`sd`/`yq -i`/`sponge`/`shutil.copy`/`os.replace`/`os.fdopen(fd, mode='w')` list); I
   traced each and all are silent, so only the `$((` value is wrong — but `FINDINGS.md` line 105
   ("§8 … now also holds every §7 edge as a row") is a universal the table does not satisfy.
   **Fix:** reword the §7 sentence to what the rules give — *"a `>` inside `$((…))` is read as a
   sink of the simple command inside the substitution, whose command word is the arithmetic's
   first operand and matches no form, so `echo $(( 1 > 0 )) > /tmp/x` is silent"* — and add §8
   rows `echo $(( 1 > 0 )) > /tmp/x` → silent and `echo $(( 1 > 0 )) > f` → deny, naming `f`;
   add the other named edges as silent rows (one row, `·`-separated, "stated misses, §7"); and
   either make `FINDINGS.md` line 105 true by that addition or state the predicate rather than
   the universal ("every §7 edge the build walked"). No rule changes.

3. **[NITPICK] `README.md` §"Edit guards" line 465–467 tells the user to see the guard work by
   asking the agent to run `sed -i 's/a/b/' README.md`.** `research/m37-guard-live-observation.md`
   records that an agent given the start text declines to run it in both natural sessions, so
   the user most likely sees prose, not the deny. The demonstration that does not depend on the
   model's choice is the hook itself:
   `printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"'"$PWD"'","tool_input":{"command":"sed -i s/a/b/ README.md"}}' | .venv/bin/zikaron-guard`
   prints the deny JSON. Either substitute that, or say "tell it to run the command character
   for character, as the live test does".

**Checked and not raised.** The installer's union-and-ownership logic survives the perturbation
cells the new tests add, and `_rewritten_hook_notes` correctly does not report a selection change
as a reverted hand-edit (`_without_arguments` reduces both sides to the program). `main.py` and
every guard module import stdlib only, and `start_text` imports `typing` alone, so the memory
hook's per-call cost does not move. The override is examined only after a match, withdraws and
grants nothing, and its reason and the deny's resolved paths are the agent's own text, so no new
injection surface opens. The two §3.3 rule changes are implemented as taken (assignment-only
simple commands; `cd DIR` outside a `(` unit; a scanned body starting clean). The replay note
supports exactly the decision it carries and nothing in it would move it; the live note's n=2
split on count (d) is reported without a bar, as §7 asks. The §8 reader unescapes `\|`
(`design_tables._split_row`), so the rows run with real pipes. The three generic script tests
read `[project.scripts]` rather than a list. Every §8 row I traced that the brief's changes touch
(856–873) gives the stated value.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-07

**Summary judgment.** The three round-2 findings are applied as described and each lands: `_continues`
now reads the comment-stripped line on both branches (I traced §8's 775, 776, 835 and 873 and the
two new rows 875–876 against it — none moves, and the staged-script row is silent as the design
says); the `$((…))` sentence in §7 now states what the rules give and both new rows (877–878) trace
to it; and `README.md` §"Edit guards" demonstrates the deny through the hook rather than through
a model's choice. I walked every §7 edge against §8 and found one unlisted (`ed`), re-traced the
override reader, the row-5 walk-back, the `cd`/binding resolution and the row-4 head steps on the
rows the last two rounds added, and read the installer's union logic and the hook's `--components`
dispatch again end to end. One parse inconsistency remains that neither §7 nor §8 names, in the
allow direction, on a conceived edge; it is bounded and cheap. The rest is nits. **Assumption:** no
shell in this session, so the gate, coverage, mutation and replay claims are taken as reported and
every trace is by hand.

**Findings.**

1. **[IMPROVEMENT] A same-line `$(…)` leaks its `cd` and its assignments into the enclosing unit,
   while a `(` inside one switches `cd`-following off for the whole unit — two readings of one
   construct, and neither is a §7 or §8 value.** `zikaron/guard/grammar.py` `_dollar` parses a
   closed `$(…)`'s contents as pipelines of the unit's own (`self.pipelines.extend(parse(…))`), and
   `zikaron/guard/decision.py` `all_matches` then treats every pipeline alike: it follows a
   `cd DIR` and takes a `NAME=value` from any of them, and computes `follows_cd` over every token
   of every one. Traces, `cwd` `/home/u/proj`:
   - `x=$(cd /tmp && pwd); echo y > f` → the inner `[cd /tmp]` comes first in `parse`'s order,
     no `SUBSHELL` token exists, so `here` moves to `/tmp` and `f` resolves to `/tmp/f` →
     **silent**. The shell runs that `cd` in a subshell and writes `<cwd>/f`: a miss. The same
     route carries a binding out: `x=$(S=/tmp; echo $S); echo y > "$S/a"` → silent.
   - `cd /tmp/x && echo $((1+1)) > f` → `$((` is read as `$(` + `(`, the inner `(1+1)` yields a
     `SUBSHELL` token, `follows_cd` is `False` for the unit, and `f` resolves to `<cwd>/f` →
     **deny naming `/home/u/proj/f`**: a false deny on scratch that the `cd` rule was added to
     remove, produced by arithmetic in an unrelated word.
   §3.3 says a `cd` is not followed "in a unit that holds a `(` subshell, whose `cd` need not
   outlive it" — exactly the property of `$(…)` — and §3.1 makes a closed `$(…)` "one token of the
   enclosing simple command"; neither sentence decides this case, and the code decides it one way
   for `$(` and the other for `$((`. Both edges are conceived, not observed, so §7's stopping rule
   governs: **the minimum is to pin the values the code gives** — add to §8
   `x=$(cd /tmp && pwd); echo y > f` → silent and `cd /tmp/x && echo $((1+1)) > f` → deny, naming
   `f`, and to §7's "misses" the clause *"a `cd` or an assignment inside a closed `$(…)` is read as
   the unit's own, though the shell runs it in a subshell"* and to its "false denies" *"a `(`
   inside `$((…))` or `$( (…) )` counts as the unit's subshell, so a `cd` before it is not
   followed"*. **The better fix is the code meeting §3.3's subshell sentence, which is not a rule
   change:** give `SimpleCommand` a `nested: bool = False`, set it on the commands `_dollar`'s
   recursive `parse` produces (pass a flag through `_Parser`/`_end`), and in `all_matches` skip
   nested commands for `bound_variables`, `changed_directory` and the `follows_cd` scan. Form
   matches inside a `$(…)` are unaffected either way (row 839's
   `x=$(python3 -c "open('f','w').write('x')")` still denies). With that change the two rows above
   read deny naming `f` and silent respectively, and the §7 clauses are not needed.

2. **[NITPICK] §7 names `ed` and §8 has no row for it.** `design/edit-guards.md` §7 "misses"
   lists "`ex` and `ed`"; row 852 carries `ex -sc '%s/a/b/g' -cx f` and nothing for `ed`. Every
   other §7 edge I checked has a row. Add `printf '%s\n' ',s/a/b/g' w q \| ed -s f` (or any `ed`
   spelling) to row 852's silent list; `FINDINGS.md` line 105–106 ("now also holds every §7 edge
   as a row") is then true rather than nearly.

3. **[NITPICK] `tests/test_check_gate.py` line 146 hand-lists the four console scripts** in a test
   whose own docstring says it checks "by shape rather than by contents", beside a `len(…) == 5`
   on dependencies. The brief had the two generic script tests read `[project.scripts]` so no
   list is maintained by hand; this is a third copy of that enumeration, in the test the gate
   runs first. Replace with `assert "scripts" in project` (the inserted-table property the test
   exists for), or add `"scripts"` to the `for key in (…)` loop above it.

4. **[NITPICK] `README.md` line 468–470's demonstration is silent when run from a scratch
   directory**, since `"cwd":"'"$PWD"'"` is what the guard exempts on. The surrounding prose
   implies the project directory but does not say it; add "from the project directory" to the
   sentence introducing the command, so a reader who tries it from `/tmp` does not conclude the
   guard is inert.

**Checked and not raised.** The `_continues` change: a comment's trailing `\` continues nothing,
`\ ` before a comment is an escaped space, `|` or `&&` before a comment still continues, and an
odd run of code backslashes still does; `_is_executed` and `lexer._join_continuations` read the
same groups as a result. The override reader examines only the top unit's comments, so a marker in
a scanned body's comment is content (row 745) while one on a continuation line after `\` is a
comment (row 773). `cd "$TMPDIR"` and `cd $(mktemp -d)` name what rows 873–874 say. The row-5
`cat<<EOF` and `echo x>f` misses (row 879) fall out of the tokeniser as stated. `os.open(`,
`os.fdopen(` and `paths[0].open(` (row 881) do not reach the write patterns, for the reasons the
patterns' own anchors give. The installer's `_start_selection` unions under `--force` too, and
`_previewed_start_selection` falls back only on `InstallError`. `CLAUDE.md`'s `harness.md` row on
disk carries no flag count; `design/harness.md` §"The flags, and what each refuses" matches. The
replay harness judges with the shipped `decide` under the recorded `cwd` and the machine's
`$TMPDIR`, and `all_matches` for the matched count, so its numbers are the product's. The live
note reports count (d) at n=2 without a bar, as §7 asks. Nothing in either note would move what
the milestone ships or decides.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-07

**Summary judgment.** All four round-3 findings are applied, and the one that mattered is applied
the better way: `SimpleCommand.in_substitution` is set by `grammar._dollar`'s recursive parse and
read in `decision.all_matches` in exactly the three places it has to be — the binding, the `cd`,
and the `(`-subshell scan — while `match_pipeline` still judges every pipeline, so a form inside a
`$(…)` is still seen. I traced rows 882–884 by hand through `_dollar` → `same_line_close` →
`parse(…, in_substitution=True)` → `all_matches` and each gives its stated value; §3.3's new
sentence and §3.1's existing one agree; `read_override`, `heredoc._is_executed` and the row-4
script search are untouched by the flag. §8 now carries a row for every edge §7 names (I walked
§7's four bullets again, `ed` included), `tests/test_check_gate.py` reads `scripts` with the other
`[project]` keys, and `README.md` says where the demonstration runs and why. I re-read the whole
guard package, the hook's `--components` dispatch, the installer's union-and-ownership path and the
owed documents with fresh eyes and found nothing that changes a decision. Two nitpicks remain,
neither of which I would hold the build for. **Assumption:** no shell here, so the gate, coverage
and mutation claims are taken as reported and every trace is by hand.

**Findings.**

1. **[NITPICK] The other `$(` shape — one that does not close on its line — carries a `cd` or a
   binding out of the substitution, and neither §7 nor §8 says so.** §3.3's new sentence is for a
   *same-line* `$(…)`; §3.1 makes an unclosed `$(` a boundary whose following words are simple
   commands of the unit, so `changed_directory` and `bound_variables` read them as the unit's own.
   Trace, `cwd` `/home/u/proj`: `x=$(` / `cd /tmp` / `)` / `echo y > f` → line 1 is `[x=,
   SUBSTITUTION]` (binds nothing, moves nothing), line 2 `cd /tmp` is followed, line 3 `)` ends an
   empty command, line 4's `f` resolves to `/tmp/f` → **silent**, where the shell writes
   `<cwd>/f`. Likewise `x=$(` / `S=/tmp` / `)` / `echo y > "$S/a"` → silent. Both are conceived,
   so §7's stopping rule governs and the value is the one the rules give. **Fix:** add the two rows
   to §8 as *silent (stated miss: a `$(` that does not close on its line is not read as a
   subshell)*, and to §7's "misses" the clause *"a `cd` or an assignment inside a `$(` that does
   not close on its line is read as the unit's own, since §3.3's subshell sentence is for the
   same-line form"*. No rule moves; row 780's `x=$(` / `sed -i 's/a/b/' f` / `)` → deny is
   unaffected either way.

2. **[NITPICK] `FINDINGS.md` lines 245–250, the new owed-work entry, carries the story of how it
   was found.** *"failed once at 147 ms with a review agent running beside the gate on a host at
   load 6–7; alone it passed five times and in the next gate"* is what a sweep covered, which
   `CLAUDE.md` §"Project memory" sends nowhere; the measured fact and the fix are what the pool
   wants. **Fix:** keep "measured 147 ms once on a host at load 6–7 against a 125 ms bound" and the
   `0.5 × budget` proposal, and drop the rest of that sentence.

**Checked and not raised.** The `in_substitution` flag is set only by `_dollar`'s recursive
`parse` and inherited by any `$(…)` nested inside one, so a binding two substitutions deep is still
not carried out. `follows_cd` is computed over `own` and a `(` inside `$((…))`, `$( (…) )` or a
`>(…)` word never counts as the unit's subshell, while a `(` on a line inside an *unclosed* `$(`
still does (`x=$(` / `(cd /tmp; ls)` / `)` / `echo y > f` → deny naming `f`, correctly). The
inner pipelines come before their enclosing command in `parse`'s order, so a `$(…)` in command
*N* is judged under the bindings and directory of commands 1 to *N* − 1, which is what the shell
does. `heredoc._is_executed` parses the opener's group without the flag and does not need it; the
probe is found on the same token either way. `read_override` reads `annotate(top)`, the top unit
only, so a marker in a scanned body's comment is still content (row 748) and one on a continuation
line is still a comment (row 776). `_as_interpreted` spends an escaping backslash (round 1, 6) and
`_continues` reads the comment-stripped line on both branches (round 2, 1) — both re-traced on the
rows they own. The hook's `_dispatch` gives the consolidator nothing under every selection, the
guard start text and the policy together fit the 10,000-unit budget, and `start_text` imports
`typing` alone, so the memory hook's per-call cost does not move. The installer's `_start_selection`
unions over every `zikaron-hook` start group including another install's, `_previewed_start_selection`
falls back only on `InstallError`, and a `guards` install over an older unquoted memory path is
replaced rather than duplicated. `design/overview.md`'s D38 row, `design/harness.md` §"The table"
row and §"What a Claude Code install writes", `design/architecture.md`'s two deltas,
`design/distribution.md`'s console-script sentence and `README.md`'s install, options, guard and
uninstall sections are present and agree with the code. `FINDINGS.md`'s lead is current and names
the review as the open step. The replay note supports the two §3.3 changes and nothing else; the
live note reports count (d) at n=2 without a bar; neither would move what the milestone ships.

VERDICT: APPROVED

## Round 5 — 2026-10-07

**Summary judgment.** Row 6 is built the way §3.2 states it, and the hard parts are right: the
operand walk reads every option shape §3.2 lists (I traced `-u -X utf8`, `-Wignore`, `-um`, `-ec`,
`--`, a bare `-`, `-o pipefail`, `--require r`, and a `+o` after a shell word); staging and running
meet through one key (`_key` → `file_path`, falling back to `resolve` so `$TMPDIR/x` still meets
itself on a machine with no `$TMPDIR`); the judged script starts from the run's directory with the
bindings dropped, reads no file of its own, and never supplies the override; the one read is
`O_NOFOLLOW | O_NONBLOCK`, size-checked before and after, and wired at `main` alone, which
`TestTheRealProcess` proves by running the process. Every §8 and §8.1 row I traced (832–843, 968,
and all thirteen of §8.1) gives its stated value, and the texts, labels, D38, the README's two
places, `FINDINGS.md`, the archive row and the research note agree with the code. One gap stands
between the code and §3.2's own sentence about what counts as a staging — a real shell idiom that
the row's purpose covers and the code does not — and it is small. The rest is nits.
**Assumption:** no shell here, so the gate, coverage and replay claims are taken as reported and
every trace is by hand.

**Findings.**

1. **[IMPROVEMENT] A `tee` fed by a heredoc *earlier in its pipeline* stages nothing, so
   `cat <<'EOF' | tee /tmp/fix.py` … `python3 /tmp/fix.py` is silent.**
   `zikaron/guard/script_file.py` `staged_texts` collects `bodies` from
   `simple.tokens` — the `tee`'s *own* tokens — and `continue`s when that is empty, before it ever
   asks `literal_targets`. For `cat <<'EOF' \| tee /tmp/fix.py` / `open('f','w')` / `EOF` /
   `python3 /tmp/fix.py`: the body hangs on the `cat`'s `<<` token; the `tee` simple command has no
   heredoc token, so `bodies == []` and nothing is staged; the run then falls to the file read, and
   at `PreToolUse` the file does not exist — **silent**, on exactly the half of the case row 6 was
   added for (`research/m37-scratch-script-replay.md`: "at `PreToolUse` the file does not exist
   yet"). §3.2 says the text is *"the body of a heredoc that a row-5 `cat` or `tee` wrote to the
   operand's path"*, and row 5's own definition of `tee` is the walk-back — `tee` fed by a heredoc
   anywhere before it over filters — so the row-5 `tee` match here (target `/tmp/fix.py`, fed by
   the `cat`'s opener) is a `tee` that "wrote a heredoc's body to the path" by the document's
   words, and the code does not record it. The same shape with `sudo tee` is the common spelling of
   this idiom. **Fix (the code meeting the design, no rule change):** for a `tee` word, take the
   bodies from every simple command of the pipeline up to and including it:

   ```python
   for index, simple in enumerate(pipeline):
       for word in command_words(simple):
           name = command_name(simple.tokens[word])
           if name not in ("cat", "tee"):
               continue
           fed = pipeline[: index + 1] if name == "tee" else (simple,)
           bodies = [t for each in fed for token in each.tokens for t in token.heredoc_texts]
           if not bodies:
               continue
           for raw in literal_targets(pipeline, index, word):
               staged[_key(raw, location)] = bodies[-1]
   ```

   `literal_targets` already answers `[]` for a `tee` behind a shell or interpreter word, so a body
   before such a word is never keyed. Add to §8: `cat <<'EOF' \| tee /tmp/fix.py` / `open('f','w')`
   / `EOF` / `python3 /tmp/fix.py` → deny, naming `f`, naming the `python3` form; and
   `cat <<'EOF' \| sudo tee /tmp/fix.sh > /dev/null` / `sed -i 's/a/b/' f` / `EOF` /
   `bash /tmp/fix.sh` → deny, naming `f`. (A filter between — `cat <<'EOF' | sed … | tee /tmp/x`
   — stages the body raw rather than transformed, the same accepted imprecision as "unexpanded even
   under an unquoted delimiter"; one clause in the "Row 6's text" paragraph covers it.) **If the
   operator would rather not move code before arms B–D run**, the alternative that also closes
   this is to state in that paragraph that the heredoc must be in the `cat`/`tee`'s *own* simple
   command and add the first row above as *silent (stated: staged by a `tee` fed through a pipe)*
   with a §7 clause — but the fix is one function and the §8 row would then record a miss on the
   idiom the row exists for.

2. **[NITPICK] `script_operand` can return a token that is no word.** `zikaron/guard/script_file.py`
   line 86–89: `find_redirects(...).tokens` excludes boundary and process-substitution tokens from
   the *redirect* set, so a `(`, an unclosed `$(` or a `<(…)` token after the command word is
   iterated, is not an option (`starts_unquoted` is false for a boundary) and is returned as the
   operand. `bash <(curl …)` then has operand `<(curl …)`; harmless under an authored `cwd`
   (never scratch), and under a scratch `cwd` it tries `file_path` on a path that cannot exist and
   reads nothing. §3.1 says a process substitution is "never a target of any row"; the operand
   should be held to the same. **Fix:** `if index not in redirects and token.is_word` in the
   generator, and pin `bash <(echo 'sed -i s/a/b/ f')` → silent in §8 (a process substitution is no
   operand, §3.1).

3. **[NITPICK] Three conceived row-6 edges the rules decide have no §8 row.** Under §7's stopping
   rule each takes the value the rules give; none moves a rule:
   - `bash -euxo pipefail /tmp/fix.sh` → silent. `_shell_option("-euxo")` is `ALONE` (only the bare
     `-o` is in `_SHELL_TAKES_NEXT`), so `pipefail` is read as the operand and is not scratch. Add
     the row, and *"a shell cluster ending in `o` does not take the next word"* to §7's first bullet.
   - `tee /tmp/fix.py <<< "open('f','w')"; python3 /tmp/fix.py` → silent. A here-string opens no
     body, so `heredoc_texts` is empty and the file (absent) is read — §7's "staged … other than by
     a `cat`/`tee` heredoc" class, with no row naming the `<<<` spelling.
   - `cat > /tmp/fix.py <<'EOF'` / `open('f','w')` / `EOF` / `bash <<'B'` / `python3 /tmp/fix.py`
     / `B` → silent under §8's payload. `all_matches` builds a fresh `staged` per unit, so a staging
     on the command's own lines is not seen by a run inside a scanned body; the run reads the file,
     which does not exist yet. §3.2's "the same unit (the command's own lines, or one scanned body)"
     already decides it; a row makes it visible.

4. **[NITPICK] Two sentences row 6 made stale.** `zikaron/guard/heredoc.py` line 9–10: *"never
   looked inside, so a PR body or a staged script cannot be denied for what it says"* — the design's
   matching sentence now ends *"until row 6 runs the script, when the staged body is that row's
   text"* (§3.2); add that clause, or drop "or a staged script". `design/build-plan.md` §M37
   "Invariants and properties" line 5755: *"the same payload and `$TMPDIR` always yield the same
   output"* — §1 and `tests/test_guard_properties.py` now add the scratch script's contents; add
   "and the same contents of any scratch script the command runs".

**Checked and not raised.** The judged text is read as a scanned body is — `delimit`, then
`executed_text` for an interpreter and `all_matches` for a shell — so every §7 miss stated for a
scanned body (`x = 1 << 20`, a triple-quoted string's inner lines, `\'` inside `'…'`) holds for a
read file on the same terms, which is what "judged as if the text were the scanned body" promises.
A staging inside a same-line `$(…)` is carried out (`staged.update` runs before the
`in_substitution` skip), which is right — a subshell's file write persists. The override is read
from `annotate(top)` only, so a marker in a staged body (row 843) and one in a read file both leave
the ordinary deny; the file-read case has no §8.1 row and needs none, since nothing in that path
can reach `read_override`. `in_child` keeps `tmpdir` and `scratchpad` and drops only `bindings`.
`_shell_targets` folds a target-less row into one non-exempt target, so a shell script's match is
exempt only when everything it writes is scratch (row 838, third item). On macOS `/tmp` and `/var`
are directory symlinks on a non-final component, which `O_NOFOLLOW` does not refuse, so the read
works there; `/dev/stdin` is refused by it, correctly. **Safety:** the brief's earlier claim that
the deny's paths are "the agent's own text" is now weaker — a string literal in a `/tmp` file
another process wrote can reach the message as a resolved path — but the agent was about to
execute that file, which is the larger exposure, and the guard's deny is what stops it; no
finding. **Cost:** a command with no scratch operand reads nothing, so the per-call cost of the
common case does not move; the 256 KiB bound's worst case runs four character-level passes and the
write-call regexes over 262,144 characters, which §8.1's sized row exercises in the suite; I cannot
time it here, and it is plausibly around a second in CPython against a 10 s timeout that allows on
expiry. §1's "one file read" is one read per scratch operand, not per command — "one place" (§6) is
the accurate claim and is the one the design leans on. The replay harness resets `written` per
transcript file, so a `Write` in a parent session is invisible to a subagent's Bash, which the
note's "108 of the 146 … could not be reconstructed" already prices in; its figures are the
product's own `decide` and `all_matches` under the recorded `cwd`, and nothing in the note would
move the decision it supports. `README.md`'s pieces table (line 104) and §"Edit guards", D38's
row with its struck clause, `FINDINGS.md`'s D38 line and steps 8–9, and the archive's evidence row
all state row 6 as built. The start text, the row-6 label and the "a target under" wording are
this file's and are not re-examined.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-07

**Summary judgment.** The four round-5 findings are applied as described and each lands: a `tee`
now takes its body from every simple command of its pipeline up to it, while `literal_targets`
still answers `[]` behind a shell or interpreter word, so a body before such a word is never keyed
(I traced rows 848 and 849, the `sudo tee … > /dev/null` spelling, a filter between, `cat <<A
<<B | tee`, and `cat <<A | tee /tmp/x <<B`, and `bodies[-1]` is what the shell writes in each);
`script_operand` skips every non-word token (row 850 and the `bash <(x)` doctest); §7's first
bullet and §8's stated-misses row carry the three conceived edges; the two prose sentences are
current; and rows 846–847 kill the `in_child()` mutation that nothing caught before. Row 6 is
built the way §3.2 states it, and design, code, texts and the five documents agree. What remains
is in the table rather than the code: §8 never makes a staging and a run meet through *different*
spellings of one path with a deny as the value, so the resolution of the key — the property the
same-command half of row 6 rests on, and the one the brief says a mutation verified — is pinned by
nothing I can find; and one plausible shape of the idiom the row exists for is a miss that §7 does
not name. Both are rows and a sentence, no rule moves. **Assumption:** no shell here, so the gate,
coverage and mutation claims are taken as reported and every trace is by hand.

**Findings.**

1. **[IMPROVEMENT] The staging key's resolution is unpinned: no §8 or §8.1 row makes a staging and
   a run meet through different spellings of the same path with a deny as the value.**
   `zikaron/guard/script_file.py` `_key` (line 235–238) resolves both sides through `file_path`,
   falling back to `resolve`, and §3.2 says a body is staged for a path "whose sink or `tee`
   target *resolves* to that path" and is used "where a body was staged for the operand's
   *resolved* path". I walked every row in which a staging and a run both appear (836–849, 977,
   §8.1's 994–995): in each the two spell the path identically (`/tmp/fix.py` both; `"$S/fix.py"`
   both; `fix.py` both after one `cd`; `"$TMPDIR/fix.py"` both), or the expected value is silent
   either way (841's second item: staged as `/tmp/w/fix.py`, run as `fix.py` after `cd /tmp/w`,
   silent because the script's `f` is scratch where it runs — and silent under a raw key too,
   since the file is then read and absent). So a `_key` that returned `raw` unchanged passes the
   table, and so does one that returned `location.resolve(raw)` without `file_path` — which is
   why I cannot find the test the brief's "staging key computed without `file_path`" mutation
   fails. **Fix:** add to §8, beside row 841:
   `cat > /tmp/w/fix.py <<'EOF'` / `open('/home/u/proj/f', 'w')` / `EOF` / `cd /tmp/w && python3
   fix.py` → deny, naming `f` (the staging's absolute spelling and the run's relative one meet
   through the resolved path) — traced: staged under `/tmp/w/fix.py`, the run's `fix.py` resolves
   to it under the moved `cwd`, the literal is absolute and not scratch; and
   `S=/tmp/w; cat > "$S/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 /tmp/w/fix.py` →
   deny, naming `f`. And to §8.1, the row that pins `file_path` in the key:
   `fix.py`: `print(1)` | `cat > "$TMPDIR/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3
   "${TMPDIR}/fix.py"` → deny, naming `f` (two spellings of `$TMPDIR` meet through the file's
   path) — under a `resolve`-only key the two differ, the file is read, and `print(1)` is silent.
   Re-run the mutation against these; nothing in the code moves.

2. **[IMPROVEMENT] A scratch script fed on stdin by a heredoc, a here-string or an `echo`/`printf`
   pipe is not judged, and §7 does not say so.** `zikaron/guard/forms.py` `_may_run_a_file` (line
   142–147) lets row 6 judge an interpreter word only when `inline_script` is `None`, and
   `zikaron/guard/interpreter.py` `inline_script` (line 42–57) answers a script for a `<<`
   anywhere in the pipeline or a printer feeding the command — §3.2 row 4's sources, which row 6's
   cell excludes by "none of row 4's script sources". Trace, `cwd` `/home/u/proj`:
   `cat > /tmp/fix.py <<'PY'` / `open('f', 'w')` / `PY` / `python3 /tmp/fix.py <<'EOF'` / `a.md`
   / `EOF` → the first body is staged for `/tmp/fix.py`; the second is scanned (its opener's
   pipeline has `python3`) and row 4 searches `/tmp/fix.py`, the `<<'EOF'` token and `a.md` for a
   write call, finds none, and `_match` answers `None`; `_may_run_a_file` answers `False` because
   `inline_script` was not `None`; the staged text is never looked at — **silent**, though the
   script rewrites `f`. The same for `echo a.md \| python3 /tmp/fix.py` and `python3 /tmp/fix.py
   <<< a.md` after the staging. This is the design's own value — a row-4 source ends row 6 — and
   the shape is a plausible one for the idiom row 6 was added for: a staged script given its file
   list on stdin. Under §7's stopping rule it becomes rows and a clause, not a rule change.
   **Fix:** add to §7's first bullet, after the `bash -euxo` clause: *"and an interpreter whose
   pipeline also carries a row-4 source — a heredoc or here-string as the script's input, or an
   `echo`/`printf` piped into it — is row 4's and not row 6's, so the scratch script it runs is not
   judged (`python3 /tmp/fix.py <<'EOF'` with data in the body)"*; add to §8's stated-misses row
   977 the three items above, each silent; and no change to §7's count (c), whose "a scratch
   script row 6 misses (above)" then covers it.

3. **[NITPICK] `python3 -E /tmp/fix.py` is silent for the same reason and has no row.** Row 4's
   cell names `-E` as a script flag for every interpreter word, so `_is_script_flag` matches
   Python's `-E` (ignore `PYTHON*` variables) and `_may_run_a_file` is `False`. Conceived and
   rare; pin it: add `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 -E
   /tmp/fix.py` → silent to row 977, with "`-E`, a row-4 script flag for every interpreter word"
   in its parenthesis.

4. **[NITPICK] An appended staging makes the appended body alone the text, and what the file
   already held is unjudged.** `cat >> /tmp/fix.py <<'EOF'` and `tee -a /tmp/fix.py <<'EOF'` are
   row-5 matches whose sink or target resolves to the path, so by §3.2's "Row 6's text" the body
   is staged and the file is not read — `staged_texts` keys `bodies[-1]` on every sink, `>>`
   included. A script created by an earlier `Write` with the write call, then appended to and
   run in one command, is judged on the appended lines only. Conceived; pin it: §8 `cat >>
   /tmp/fix.py <<'EOF'` / `print(1)` / `EOF` / `python3 /tmp/fix.py` → silent, and §8.1 `fix.py`:
   `open('f', 'w')` | `cat >> "$TMPDIR/fix.py" <<'EOF'` / `print(1)` / `EOF` / `python3
   "$TMPDIR/fix.py"` → silent (an appended body is the whole text), with one clause in §7's first
   bullet beside the here-string spelling.

**Checked and not raised.** The `tee` walk-back in `staged_texts` collects bodies from every
simple command up to the `tee` without stopping at a shell word, but `literal_targets` answers
`[]` for a `tee` whose walk back meets one, so `cat <<'A' | python3 - | tee /tmp/x` stages nothing
and `cat <<'A' | bash | cat <<'B' | tee /tmp/x` stages `B`, which is what `tee` receives. A
`cat`'s own here-string (`cat <<< … > /tmp/fix.py`) passes `literal_targets` but opens no body,
so `bodies` is empty and the file is read — the stated here-string class under another word. Row
850's `bash <(echo …)` is silent through `find_redirects` marking the open substitution's tail,
so the `is_word` filter is exercised by the doctest's `bash <(x)` rather than by §8; that is
enough. Rows 846 and 847 trace to `in_child()` dropping `bindings` and keeping `cwd`, and row 841
pins that the script starts from the run's directory rather than the payload's. A script whose
staged text stages and runs itself terminates: each level strips one heredoc, and a read file
cannot recurse because `read` is withheld inside a script. The override is still read from the
top unit only, so a marker in a staged shell script's comment is content. `messages.py` and
`start_text.py` carry the §"Prompt texts" blocks verbatim, `FORM_LABELS[SCRATCH_SCRIPT]` is the
table's row 6, and `test_guard_texts.py` scopes its label regex to the section's prose, so this
round's text cannot join it. D38's row with its struck clause, `README.md`'s pieces table and
§"Edit guards", `FINDINGS.md` step 9 (its "123 recoverable scripts" is the note's 85 + 38), the
archive's evidence row, `design/build-plan.md`'s determinism line and `heredoc.py`'s data-body
sentence all state row 6 as built. The replay harness judges with the shipped `decide` and reads a
scratch script as the session's own `Write` left it; its 54/47/2/5 are the product's figures and
nothing in the note would move the decision it carries. **Cost:** a shell script of 256 KiB made
of `<<` openers that never close costs one `_delimiter_line` scan per opener, quadratic in lines,
and the hook's timeout then allows — the §6 behaviour, and not row 6's: the top-level command has
the same shape with no size bound at all. **Safety** is as round 5 left it.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-10-07

**Summary judgment.** Round 6's four findings are applied as rows and clauses, and each lands: I
traced both items of row 847 and §8.1's row 1002 through `staged_texts` → `_key` → `file_path`
and the run's lookup, and the key is now pinned in both directions (a `resolve`-only key and a raw
key each fail row 1002, as the brief says); the three row-4-source items, the `-E` item and the
appended-staging items of row 983 and §8.1's row 1001 each give the stated value, and §7's first
bullet states the class. Row 6 is built the way §3.2 states it, and the code, the texts, D38, the
README's two places, `FINDINGS.md` step 9, the archive row, the brief's determinism line and the
research note agree. One disagreement of the same class as round 6's finding 2 remains, between
§3.2's own text and the code — on a spelling §3.2 row 6 names as one the operand walk reads, where
in fact row 4 claims the word first — and it is rows and a sentence, or one clause of row 4 if the
operator would rather the example stay true. The rest is nits. **Assumption:** no shell here, so
the gate, coverage and mutation claims are taken as reported and every trace is by hand.

**Findings.**

1. **[IMPROVEMENT] `python3 -Wignore /tmp/fix.py` is row 4's and not row 6's, and §3.2 row 6 names
   `-Wignore` as an example of the operand walk — a path that token never reaches.**
   `zikaron/guard/interpreter.py` `_is_script_flag` fullmatches `-[A-Za-z0-9]*[ceE](['\"].*)?`
   against every argument token, and `-Wignore` ends in `e`, so `inline_script` answers a script
   (`-Wignore` / `/tmp/fix.py`, no write call), `forms._match` answers `None`, and
   `_may_run_a_file` is `False` because `inline_script` was not `None` — the staged body is never
   looked at. Trace, §8's payload: `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` /
   `python3 -Wignore /tmp/fix.py` → **silent**. The same for `-We`, `-Wonce`, `-Wmodule` and
   `-Ximporttime` (every `-W`/`-X` cluster whose argument ends in `e`), and — because the flag test
   reads *every* argument token, the operand's own arguments included — for a `-c`, `-e` or `-E`
   *after* the operand: `python3 /tmp/fix.py -c cfg.toml` → silent. Yet `design/edit-guards.md`
   §3.2 line 213 says *"`W` or `X` takes the rest of the token as its argument, or the next token
   when it is last (`-Wignore`, `-X utf8`)"*, and `script_file.py` line 76's doctest shows
   `operand("python3 -Wignore f.py")` → `'f.py'` — true of `script_operand` in isolation, and a
   path row 6 never takes for that token. Row 842 pins `-u`, `-X utf8` and `--`; nothing pins a
   `-W` spelling either way. This is the brief's own intent clause — design and code agreeing —
   failing on an example the design chose. **Fix, the minimum under §7's stopping rule (no rule
   moves):** in §3.2's operand paragraph replace `-Wignore` with `-Werror` (ends in `r`, so it
   reaches the walk) or `-W ignore` (the bare `-W` takes the next token), and the doctest
   likewise; add to §7's first bullet, in the `-E` parenthesis, *"or a `-W`/`-X` cluster whose
   argument ends in `e` (`-Wignore`, `-Ximporttime`), or such a flag anywhere in the command, after
   the operand included (`python3 /tmp/fix.py -c cfg`)"*; add to row 983 the two silent items above;
   and add the positive controls to row 842: `… / python3 -W ignore /tmp/fix.py` and `… / python3
   -Werror /tmp/fix.py` → deny, naming `f` — traced: `-W` alone fails the cluster regex (nothing
   is left for `[ceE]`) and `_python_option("-W")` is `TAKES_NEXT`; `-Werror` fails it and is
   `ALONE`. **The alternative that keeps §3.2's example true is a row-4 change, the operator's to
   take:** for the python words, a cluster beginning `-W` or `-X` is never a script flag —
   `_is_script_flag`: `if letters == "ceE" and token.unquoted[1:2] in "WX": return False` — safe,
   since no such cluster carries a script, but a clause in row 4's cell. The after-the-operand case
   stays a stated miss either way.

2. **[NITPICK] §7's same-unit clause names one direction and the reverse has no row.** §7 line
   606–608: *"staged on the command's own lines for a run inside a scanned body, which is a unit
   of its own"*. The reverse — staged inside a scanned body, run on the command's own lines — is
   the same rule and is also silent: `bash <<'EOF'` / `cat > /tmp/fix.py <<'PY'` / `open('f','w')`
   / `PY` / `EOF` / `python3 /tmp/fix.py` → the body's `staged` is the body unit's (and `_units`
   judges the top unit's pipelines before the body's anyway), so the top unit's run reads the file,
   absent under §8 → **silent**. Add the row to 983 and "or the reverse" to the clause.

3. **[NITPICK] The gate.** The brief says `./check.sh` was green before round 5's edits and has not
   run since; round 5 moved code (`staged_texts`, `script_operand`) and three rounds have edited
   `design/edit-guards.md`, which `tests/test_markdown_renders_as_written.py`,
   `tests/test_design_pointers_resolve.py` and `tests/test_quoted_design_prose_is_verbatim.py`
   parse — the last through `rglob("*.md")`, so this file's own rounds are in its input. Run the
   six-file prose subset after applying this round, and the full gate before the PR; `CLAUDE.md`
   makes the latter the definition of done, and nothing in the brief's reported checks covers it.

**Checked and not raised.** Row 847's two items: the absolute staging keys `/tmp/w/fix.py` and
the relative run after `cd /tmp/w` resolves `fix.py` through the moved `cwd` to the same key; the
`$S`-bound staging keys through `_substituted` and the absolute run meets it; each names
`/home/u/proj/f`, the first because the script's literal is absolute, the second because
`in_child()` keeps the run's `cwd` `/home/u/proj`. Row 1002: `file_path` reads both `$TMPDIR` and
`${TMPDIR}` to the fixture's directory, and under a `resolve`-only key the two spell differently,
the file is read, and `print(1)` is silent — the mutation the brief ran. Row 983's three row-4-source
items each end at `_may_run_a_file`; its `-E` item through `_SCRIPT_FLAGS`; its appended item
through `find_redirects` treating `>>` as a sink, so `bodies[-1]` is keyed and the file is not
read, which §8.1's row 1001 second item pins against a file that would have denied. The `tee`
walk-back and the `is_word` operand filter are as round 6 left them. `TestTheRealProcess`'s file
read runs under `tmp_path`, which on the macOS job is under `$TMPDIR` and reaches `roots` through
`/private` and the inherited environment, so that test is not Linux-only. Two conceived edges I
decided not to pin: a scratch *directory* that is itself a symlink into the project (`/tmp/w →
<project>`) is read, since `O_NOFOLLOW` refuses only a final-component symlink — the agent made
that link, and the deny then names what the project's file writes; and `bash -n /tmp/fix.sh` and
`node --check /tmp/fix.js`, syntax checks that run nothing, are judged as runs — both rare, and
each the value the rules give. `pushd` is not `cd` and is not followed; §7's `cd` list does not
name it and nothing in the transcripts suggests an agent uses it. The research note's 54/47/2/5 are
the product's `decide` under the recorded `cwd`; whether they were re-run after round 5's
`staged_texts` change I cannot tell from here, and a `tee`-piped staging it would add moves the
count up by a few at most and moves no decision. D38's row with its struck clause, `README.md`'s
pieces table and §"Edit guards", `FINDINGS.md` step 9 (85 + 38 = 123), the archive's evidence row,
`design/build-plan.md`'s determinism line, `heredoc.py`'s data-body sentence and `script_file.py`'s
docstring all state row 6 as built. **Safety and cost** are as rounds 5 and 6 left them. The start
text, the row-6 label and the "a target under" wording are this file's and are not re-examined.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-10-07

**Summary judgment.** Round 7's findings are applied by the minimum the operator chose, and each
lands on the code as it stands: §3.2's operand examples (`-Werror`, `-W ignore`, `-X utf8`) are
each a spelling the walk actually reaches — I traced `-W ignore` through `_is_script_flag` (the
bare `-W` has nothing left for `[ceE]`) and `_python_option` (`TAKES_NEXT`, consuming `ignore`), and
`-Werror` through both (`ALONE`) — and row 846's two new positive controls deny naming `f` under
the `python3` form; row 987's `-Wignore` and `/tmp/fix.py -c cfg.toml` items each end at
`_may_run_a_file` with `inline_script` not `None`, so row 6 is never asked; the reverse-unit item
(`bash <<'EOF'` staging, top-unit run) is silent because `all_matches` builds `staged` per unit and
`_units` judges the top unit before the body's; §7's clause now states both directions; and the
`script_operand` doctest's `-Werror` gives `'f.py'`. Row 6 is built the way §3.2 states it, and the
design, the code, the texts, D38, the brief's determinism line, the README's two places,
`FINDINGS.md` step 9 and the archive row agree. What remains is two wording-and-pinning nits in
the clause this round added, neither of which moves a rule or a decision. **Assumption:** no shell
here, so the prose-subset, doctest and replay claims are taken as reported and every trace is by
hand; the full gate the brief says follows this round is the project's definition of done and is
not a review condition.

**Findings.**

1. **[NITPICK] §7's new clause overstates where a row-4 flag counts, and understates what a
   row-4 cluster is.** `design/edit-guards.md` §7 line 604–606: *"a row-4 script flag anywhere in
   the command, after the operand included"*, and row 987's parenthesis *"row-4 script flags
   wherever they stand"*. `zikaron/guard/interpreter.py` line 46–48 tests `simple.tokens[word + 1:]`
   — the interpreter's **own** arguments — so a `-c` in a *later* simple command does not end row
   6: `cat > /tmp/fix.py <<'EOF'` / `open('f','w')` / `EOF` / `python3 /tmp/fix.py; python3 -c
   'print(1)'` is **deny naming `f`**, not the miss "anywhere in the command" promises. And
   *"a `-W`/`-X` cluster whose argument ends in `e`"* is wider than the regex `-[A-Za-z0-9]*[ceE]`,
   which admits letters and digits only: `python3 -Werror::DeprecationWarning:mymodule
   /tmp/fix.py` ends in `e`, holds `:`, is no script flag, and `_python_option` reads its `W` at
   index 1 as `ALONE` — so it reaches the walk and row 6 judges it (deny naming `f` under §8's
   staging). **Fix:** *"a row-4 script flag among the interpreter's own arguments, after the
   operand included: Python's `-E`, a `-W`/`-X` cluster of letters and digits ending in `e`
   (`-Wignore`, `-Ximporttime`; `-Werror::Foo:mod` is not one), a `-c` meant for the script …"*,
   and in row 987's parenthesis *"wherever they stand among its arguments"*. Optionally pin the
   two values: `… / python3 -Werror::DeprecationWarning:m /tmp/fix.py` → deny, naming `f` beside
   row 846's controls, and the two-interpreter command above as a deny row. Conceived edges, no
   rule moves.

2. **[NITPICK] The `resolve` half of `_key` is pinned by nothing under §8's payload.**
   `zikaron/guard/script_file.py` `_key` is `location.file_path(raw) or location.resolve(raw)`.
   Rows 851 and 1006 pin `file_path` (round 7 confirmed a `resolve`-only key fails 1006), but every
   staging-and-run pair in §8 either spells the path so that `file_path` resolves it or runs under
   §8.1's set `$TMPDIR`; with `$TMPDIR` unset no row stages and runs through `$TMPDIR` in
   *different* quotings, so a `file_path(raw) or raw` key passes the whole table. §3.2 says the
   two meet through "the operand's resolved path", which with `$TMPDIR` unset is §3.3's
   `<cwd>/$TMPDIR/fix.py` on both sides. **Fix:** add to §8 beside row 851: `cat > $TMPDIR/fix.py
   <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 "$TMPDIR/fix.py"` → deny, naming `f` (with
   `$TMPDIR` unset the two spellings meet through §3.3's resolved form). Traced:
   `is_scratch('"$TMPDIR/fix.py"')` is true by the literal rule; `file_path` matches the
   `$TMPDIR` prefix, finds no `tmpdir` and no default, and answers `None`; `resolve` gives
   `/home/u/proj/$TMPDIR/fix.py` for the sink and the operand alike; the script's `f` resolves to
   `/home/u/proj/f`. Under a raw key the quoted and unquoted spellings differ, the file is sought
   (`file_path` is `None`, so nothing is read) and the row is silent.

**Checked and not raised.** The row-4 flag test and row 6's operand walk disagree only on the
clusters §7 now names, and the operator's decision to leave row 4's test alone is recorded in
the brief; nothing here re-proposes it. Row 846's seven items all carry `python3` as the word
(`command_name` strips `timeout 60`'s prefix walk to the interpreter), so the `naming the
python3 form` assertion holds for each. The reverse-unit item of row 987 cannot be rescued by
`_units`'s order either way: even if the body were judged first, each unit's `staged` is its own,
which is the §3.2 sentence the brief cites. `experiments/m37_guard_replay.py` reads a script as
`written.get`, never the disk, and the note's 54/47/2/5 are the product's own `decide` under the
recorded `cwd`; the brief's re-run giving 54 unchanged is consistent with round 7's expectation
that the `tee`-piped staging moves the count by at most a few, and nothing in the note would move
the decision it carries. `FINDINGS.md` on disk carries row 6 as step 9 with its own gate and
review in sub-step (d), so step 7's "APPROVED … green on `93615a0+3fb5dbc5c7e3`" reads as the
pre-row-6 record it is. D38's row, `README.md` line 104 and §"Edit guards" (its "a script under
`/tmp` or `$TMPDIR`" is an illustrative list beside the full one two lines down, not a second
copy of §3.3), the archive's evidence row, `design/build-plan.md`'s determinism line,
`heredoc.py`'s and `script_file.py`'s docstrings and `decision.py`'s "reads nothing unless it
says so" all state row 6 as built. The `read_script` path is reached only after `is_scratch`
passes, so an operand holding an unbound `$VAR` or `~` never reaches `os.open`; `O_NOFOLLOW`
refuses `/dev/stdin` and `/dev/fd/N` on both platforms. `tests/test_guard_texts.py` scopes its
label regex to §"Prompt texts" and `tests/test_quoted_design_prose_is_verbatim.py` searches
Python files for attributions, so this round's text joins neither. **Safety and cost** are as
rounds 5 and 6 left them. The start text, the row-6 label and the "a target under" wording are
this file's and are not re-examined.

VERDICT: APPROVED

## Round 9 — 2026-10-07

**Summary judgment.** The re-read ask is built the way §3.4 now states it: `decide` collects the
`authored_paths` of every non-exempt match in `all_matches` order and folds them through
`dict.fromkeys`, so a path two forms reach stands once at its first position; `acknowledgement`
renders them through the `_targets` helper `deny_message` uses, so the two cannot differ;
`ACKNOWLEDGEMENT_TEMPLATE` is the §"Prompt texts" block character for character; `main` passes
`decision.targets`; the live test's fixed substring is unchanged; and §3.4, §4's opening, D38 and
the README's §"Edit guards" each say the same thing as the code. The research note's figures are
internally consistent and support the one decision they are cited for, with its own n=1 caveat.
What stops this round is not the guard: `FINDINGS.md`'s resume steps contradict the note that
this round ships beside them, and the test the brief offers for "every form's targets" cannot
tell every form from the first. The rest is one citation, one unstated condition and nits.
**Assumption:** no shell here, so the manual `~/story3-c2` run, the coverage and the prose-subset
claims are taken as reported, and the templates were compared by eye.

**Findings.**

1. **[BLOCKER] `FINDINGS.md` §"Current state" steps 8 and 10 describe a state the research note
   says has passed, and step 8 still freezes the tree.** `FINDINGS.md` line 124–138: step 8 is
   *"in progress"*, ends *"**Arm A is done; B–D are next**, their hooks now running step 9's row
   6"*, and carries *"**The arms' hooks run this working tree, so the tree must not change until
   the operator says the sessions are done.**"* — while `research/m37-guard-interactive-test.md`
   reports arms A–D scored and C2 run, and the brief says the tree has since moved (the
   acknowledgement, the version). Step 10 (line 152–164) lists (a) the §3.4 change, (b) the
   amended text, (d) the `~/story3-c2` arm and (e) the four-arm note with no *done* mark, though
   each is on disk. A fresh session resuming from this file would hold the tree still for
   sessions that have finished and re-run an arm that is written up. **Fix:** step 8 → *"**done
   (2026-10-07)** — the interactive 2×2, `research/m37-guard-interactive-test.md`: the start text
   alone kept B and D off scripts; the deny redirected C into reading first and was then
   overridden with a true reason; the nudge gave B its 14/14 re-read pass; C's overridden script
   rewrote eleven files no nudge reached, which is step 10"*, dropping the run-sheet detail and
   the tree-freeze sentence (the note holds both); step 10 → mark (a), (b), (d) and (e) *done*,
   leave (c) *in progress* until `./check.sh` is green, and keep (f)–(i) as they stand. The
   version paragraph at line 82–84 is current and needs nothing.

2. **[IMPROVEMENT] The two-form test cannot tell "every form that matched" from "the first form":
   the second form's only target is already the first form's.** `tests/test_guard_main.py` line
   68: `sed -i 's/a/b/' f g /tmp/x && echo y > f …` — the `sed` match's `authored_paths` is
   already `(f, g)`, and the `echo` adds `f` again, so `denying[0].authored_paths` alone passes
   the assertion at line 73 exactly as the shipped `(path for match in denying …)` does. The
   dedup half is pinned (an undeduplicated tuple gives `f, g, f`); the "every form" half, which
   is the property §3.4 added and the one the brief says the test holds, is pinned by nothing.
   **Fix:** make the later form contribute a path of its own and keep a repeat for the dedup:
   `two_forms = "sed -i 's/a/b/' f g /tmp/x && echo y > h && echo z > f #ZIKARON-FORCE #Reason:
   bulk rename"` and assert `"This command changes `/home/u/proj/f`, `/home/u/proj/g`,
   `/home/u/proj/h`. " in context` — the first-form mutation then yields `f, g`, the no-dedup
   mutation `f, g, h, f`, and command order is pinned by `h` before the repeated `f`. Optionally,
   since the brief's only evidence that a row-6 override names the *script's* targets is the
   manual `~/story3-c2` run: `cat > /tmp/fix.py <<'EOF' #ZIKARON-FORCE #Reason: bulk mechanical
   rename` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py` → `"This command changes
   `/home/u/proj/f`. "`, which also pins that the exempt row-5 staging does not appear.

3. **[IMPROVEMENT] The acknowledgement now carries the only re-read ask an overridden Bash edit
   gets, on a channel §2 records as unmeasured under `default` — and the research note that is
   the evidence does not say which mode its arms ran under.** `design/edit-guards.md` §2 line 53:
   the no-decision `additionalContext` row says *"Under `default` … whether `additionalContext`
   also arrived there was not recorded"*; the live test runs under `bypassPermissions`.
   `research/m37-guard-interactive-test.md` §Design names the model and effort and no permission
   mode, yet its C2 table counts *"overrides acknowledged"* — the acknowledgement attachments in
   the transcript — and its 9/14 is the decision's evidence. If the operator's interactive arms
   ran under `default` with approvals given by hand, they are the measurement §2 lacks and the
   row should say so; if they ran with approvals skipped, the ask the operator directed rides a
   channel no session in the users' mode has been seen to deliver. **Fix:** one clause in the
   note's §Design naming the mode (and, for C and C2, that the acknowledgement appeared in the
   transcript as an attachment); then either amend §2's third row — *"recorded 2026-10-07 in two
   interactive sessions under `default`: it arrived (`research/m37-guard-interactive-test.md`)"* —
   or, if the mode was not `default`, add to §3.4's re-read sentence *"on the channel §2 records
   as unmeasured under `default`"*. The code does not move either way.

4. **[IMPROVEMENT] §3.4 cites "the live test" for evidence that is the interactive test's.**
   `design/edit-guards.md` line 458: *"the live test's overridden script rewrote eleven files that
   no nudge reached"*. In this document *the live test* is `tests/test_guard_claude_live.py` —
   §2 line 67 (*"the brief requires a live test of both"*) and the same bullet's own line 452
   (*"the live test greps for it"*) — whose overridden command is a one-file `sed -i`; the eleven
   files are arm C of the operator's interactive 2×2. **Fix:** *"(operator, 2026-10-07; in the
   interactive test's arm C, `research/m37-guard-interactive-test.md`, an overridden scratch
   script rewrote eleven files that no nudge reached)"*.

5. **[IMPROVEMENT] The note's one proposal — a `git diff` in count (d) — lives only in the
   research note, which `FINDINGS.md` says is not where an owed item goes.**
   `research/m37-guard-interactive-test.md` line 106–108: *"§7's count (d) misses a `git diff`
   re-read … **Proposed:** add a `git diff` that shows content to count (d)'s list"*; and the
   note's own re-read column (line 61–63) is already counted on that wider definition, so by §7
   (d) as written (`design/edit-guards.md` line 774–776) arm B's 14/14 is 0/14 and the figure
   the decision cites is not §7's count. `FINDINGS.md` §"Owed work": *"An owed item goes here
   the moment it is identified"*; `CLAUDE.md`: research notes are *"read as a record rather than
   as instruction"*. The §7 stopping rule binds §3's *rules*, not the counts' definitions, and
   this one is observed (arm B, and B's own naming of the diff as its re-read), not conceived.
   **Fix, either:** apply it — §7 (d): *"a `Read`, or a Bash call whose simple command reads it
   (`sed -n`, `cat`, `head`, `tail`, `grep -n`, or a `git diff` whose output shows the path's
   content)"* — and let the note's bullet stand as the record of why; **or** add one line to
   §"Owed work" naming the clause and the note, and leave §7 as it is. Not both places.

6. **[NITPICK] `Acknowledge.targets` defaults to `()`, and nothing constructs it without one.**
   `zikaron/guard/decision.py` line 65. `decide` is the only constructor and always fills it; the
   default lets a future caller omit the targets and emit an acknowledgement that asks a re-read
   of *"no target the guard could resolve"* for a command whose targets were known. Drop the
   default; the doctest at line 25 is unchanged.

7. **[NITPICK] The brief's override invariant does not list the property §3.4 added.**
   `design/build-plan.md` §M37 "Invariants and properties to cover", the override bullet (line
   5769–5772): *"a valid one returns no `permissionDecision`, only the acknowledging
   `additionalContext`"*. Add: *"which names every authored target of every form that matched,
   each once, in command order, or the fixed clause where none resolves"*, so the list a later
   reader checks the suite against carries what `test_guard_main.py` now holds.

**Checked and not raised.** `ACKNOWLEDGEMENT_TEMPLATE` is the §4 block verbatim, ASCII, one
line, and `{reason}` and `{targets}` are its only braces; `test_guard_texts.py` holds it to the
block and `startswith(ACKNOWLEDGED)` to the fixed substring, which `test_guard_claude_live.py`
line 126 greps unchanged. `_targets` is the one renderer, so the deny's `it names …` and the
acknowledgement's `This command changes …` cannot drift apart. `denying` is `all_matches` order —
the top unit's pipelines, then each scanned body's — so "command order" is unit order, and a
body's match follows every top-unit match even when it stands earlier in the text; that is the
same order the deny's "first" is taken from, so the two agree, and I did not pin it. A mixed set
(one form resolved, one not) renders only the resolved paths, as subsection 2 of §"Prompt texts"
states for the deny and note 5 for the acknowledgement; the eleven-file C2 case renders the fixed
clause, which the note reports and which is the texts' own decision. A target from a `/tmp`
script's literal reaching the message is the round-5 exposure, no wider here. §8's nine `ack`
rows assert the prefix only (`test_guard_rule_table.py` line 83), which is why finding 2 sits in
`test_guard_main.py`. `README.md` line 453–462 and D38's row say what §3.4 says — the README's
*"asks for that re-read instead"* is the §4 opening's own clause. The version is `0.4.0` by the
operator's direction and `FINDINGS.md` line 82–84 and `design/build-plan.md` line 5746–5752
record it consistently, with `0.4.1.dev0` as the next tree; nothing in `tests/` reads the suffix.
Row 4's script-flag test is left as the operator decided. The note's arithmetic holds — B is
11.4× A's output and 11.0× its context, "about an eleventh"; C's 2 denies / 1 acknowledgement
and C2's 1 / 2 are consistent with each narrative, the silent bare run of an unwritten script
being the "wasted call" — and its *"unaddressed"* (line 130), which reads as *ignored* where the
next bullet says the agent re-read, is wording on a note and is declined under the operator's
2026-09-29 rule. **Safety and cost** are as rounds 5 and 6 left them: the acknowledgement adds
the targets' characters to one `additionalContext` per accepted override, no file read and no
call. The start text, the row-6 label, the "a target under" wording and the acknowledgement's
own wording are this file's and are not re-examined.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-10-07

**Summary judgment.** Round 9's seven findings are each applied as the brief describes and as the
files show. `FINDINGS.md` steps 8–10 now say what the note and the tree say; the acknowledgement
test's later forms contribute `h` and repeat `f`, so a first-form-only build yields `f, g` and an
undeduplicated one `f, g, h, f`, and each fails the `f, g, h` assertion; the staged row-6 item names
the script's `f` alone, which an exempt staging could not satisfy; `Acknowledge.targets` has no
default; the brief's override invariant names the targets; §3.4 cites arm C; §7 (d) counts a
content-showing `git diff` wherever it falls after the last edit. The note's new facts hold against
the records: all five arms' transcripts carry `permissionMode` as `auto` and nothing else (61
values, none `default` or `bypassPermissions`), C2's carries `version` 2.1.285, both quoted agent
thoughts are verbatim, and every figure in the note's two tables reproduces from the saved scores —
B's 14/14 is twelve by `git diff -U4` and two by `sed -n` on the two files edited after it, which is
the narrative. One number in a normative document and its two copies is wrong by the transcript's
own `git diff --stat`, and that is the only thing between this build and approval. **Assumption:**
no shell, so the mutation runs, the gate subset and the scorer re-run are taken as reported; the
transcripts, diffs and score files under `~/ZikaronTesting/story-key/round3/` and
`~/.claude/projects/-home-nathan-story3-*/` were read directly.

**Findings.**

1. **[IMPROVEMENT] "Eleven files" is the count of files never re-read, not the count the script
   rewrote — arm C's script rewrote all fourteen.** `design/edit-guards.md` §3.4 line 458–459: *"an
   overridden scratch script rewrote eleven files that no nudge reached"*;
   `research/m37-guard-interactive-test.md` line 92–93: *"C's overridden script rewrote eleven files
   that no nudge followed, and it re-read three"*; `FINDINGS.md` line 128–129: *"C's overridden
   script rewrote eleven files no nudge reached"*. Arm C's transcript
   (`~/.claude/projects/-home-nathan-story3-c/46661ca2-….jsonl` line 96) holds the overridden run's
   own tool result — the `git diff --stat` the command ends with — as `14 files changed, 144
   insertions(+), 158 deletions(-)`, taken before the two `Edit`s to `docs/oncall.md` (lines 117
   and 120); `round3/story3-c.diff` has fourteen `diff --git` headers; and `score-c.txt`'s re-read
   line is `3 / 14 … not: [eleven paths]`. So fourteen were rewritten, no nudge followed any of
   them, and eleven were never re-read; "rewrote eleven" is the last of those numbers attached to
   the wrong verb, and a reader of §3.4 takes it as the script's reach. It moves no decision — the
   ask was directed on the gap, not its size — but it is the one figure the normative document
   gives for that gap, and `FINDINGS.md` repeats it to every fresh session. **Fix, one clause in
   each:** §3.4 *"an overridden scratch script rewrote all fourteen files, no nudge followed, and
   eleven were never re-read"*; the note *"C's overridden script rewrote all fourteen files and no
   nudge followed; it re-read three"*; `FINDINGS.md` step 8 *"C's overridden script rewrote all
   fourteen files and no nudge reached any, which is step 10"*. This file's §"Prompt texts" note 5
   carried the same number from the brief that reported it and is this file's own record of why
   the text moved, so I have corrected it in place — two words, lines 251 and 262, outside every
   fenced block and the label table `tests/test_guard_texts.py` reads. Round 9's references to
   "eleven" are a dated record and stand.

**Checked and not raised.** `decide` folds `authored_paths` of every non-exempt match through
`dict.fromkeys` in `all_matches` order, and `is_exempt` keeps an exempt staging out of `denying`
altogether, so the staged item in `test_guard_main.py` pins the script's targets without a second
assertion; the `Acknowledge` doctest repr is the dataclass's own; `ACKNOWLEDGEMENT_TEMPLATE` is the
§4 block character for character and `_targets` is the one renderer. §2's third row records `auto`
beside `bypassPermissions` and leaves `default` as unrecorded as it was, which is the honest state:
the ask rides a channel seen to deliver under the two modes the operator's sessions ran, and the
users' `default` is still the open cell, stated where §2 states every other. The scorer's one
mechanical hit the note does not mention — C's "split pair left" of 1 — is
`docs/runbooks/backlog-growth.md:55–56`, *"page Nathan / and attach the output …"*, legitimate
prose and a scorer false positive, so the note's "Defects left 0" for C is right; its table's "14
`Read`s" for B against the scorer's 15 moves nothing and is declined under the operator's
2026-09-29 rule. C's 2 denies / 1 acknowledgement and C2's 1 / 2 are consistent with the
transcripts' shape — the refused heredoc never written, the scratch script then written with
`Write`, the first bare run finding no file (line 79) and so matching no form — and C2's first
overridden run reporting `12 files changed` before the assert stopped it is the note's "after some
files were written". The `auto` row, the note's §Design clause and the version paragraph agree;
`pyproject.toml` is `0.4.0` by the operator's direction and `FINDINGS.md` line 82–84 and
`design/build-plan.md` line 5746–5752 say so consistently; D38, the README's §"Edit guards", the
archive's evidence row and the dogfood recipe's `~/ZikaronTesting/` paths each state what the code
does. **Safety and cost** are as rounds 5, 6 and 9 left them. The texts' wording, row 4's
script-flag test, and the records that still name the old locations are not re-examined, per the
brief.

VERDICT: NEEDS_CHANGES
