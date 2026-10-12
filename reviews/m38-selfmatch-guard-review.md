# M38 — self-match rule: build review

## Prompt texts — 2026-10-11

Written against `design/guards.md` §9 (read whole; §9.3 for what the message must contain and in
which order, §9.2 for what is appended to it and when, §9.4 for the false denies the override
exists for), §3.4 and §3.5 for the two clauses that are appended unchanged and for the override's
syntax, §5 for the prompt-text rule, `design/build-plan.md` §M38 item 4 (the guard start text does
not change, so this message is the first the agent hears of the rule and has to carry its own
fix), the brief's facts about delivery (`PreToolUse:Bash hook error: ` or
`PreToolUse:Monitor hook error: ` before the text, as the call's tool result),
`research/m38-selfmatch-replay.md` and `research/pgrep-ancestor-exclusion.md` for every platform
fact the fix texts state, and `reviews/m37-edit-guards-review.md` §"Prompt texts — 2026-10-07" for
the properties the shipped texts hold. The builder's draft in `zikaron/guard/messages.py`
(`SELF_MATCH_TEMPLATE`, `SELF_MATCH_FIXES`) was read and carries no authority; its opening words
are kept, for the reason given under the heading below, and the rest is new.

**Properties, for the builder and the tests, continuing M37's.** All three texts are ASCII — no em
dashes, no curly quotes — and each is **one line**, with no newline anywhere, because the rendered
message is a JSON string shown inline after the harness's prefix. **Each placeholder occurs exactly
once** — `{word}`, `{excerpt}` and `{fix}` in the template, none in the fix texts — because
`tests/test_guard_selfmatch_table.py` turns the template into a regular expression with one named
group per placeholder, and `re` refuses a group name defined twice. No `{` or `}` appears other than
those three, so `str.format` is safe (so no `${…}`, no `{}`; the shell substitution is written
`$(...)`). The override syntax is shown bare, never in backticks, so a copied line carries nothing
the shell would read before the `#`. Flags are bare (`-A`, `-a`, `-l`, `-f`), as the `{form}`
labels write `-i`; command text — `{word}` and `{excerpt}` — is in backticks. **The text before the
template's first `{`** — `Zikaron's self-match rule refused this command: the ` and an opening
backtick — is the fixed prefix the live test greps and the table test uses to tell this rule's
deny from §3's, whose prefix is `Zikaron's find-replace guard refused this command: `; the two
differ from their second word, and `Zikaron's self-match rule refused this command` occurs in no
other text, so §7's count (e) can read it from a tool result too.

**Assumptions.** `{word}` is the command word as `SelfMatch.word` carries it, `pgrep` or `pkill`,
without a path prefix. `{excerpt}` is the brief's: the matched text with up to 20 characters of
its own line on either side, verbatim from `tool_input.command`, bounded by the line — so it never
contains a newline, which is what keeps the rendered message on one line, and may contain any other
character, quotes and backticks included. `{fix}` is a complete sentence or two, opening with a
capital and closing with a period, since the template sets it between two sentences; both fix texts
are written so. Character counts below are by hand and approximate.

### 1. Self-match deny (§9.3)

`permissionDecisionReason`. The model reads it as the tool result after `PreToolUse:Bash hook
error: ` or `PreToolUse:Monitor hook error: `, so it opens with a sentence that completes that
prefix. §9.3's order, kept exactly: the statement that the pattern also matches the shell running
this command, with its cause (Claude Code runs each command inside a shell whose command line
contains the command's text); the matched text with a little context; what follows (`pkill` kills
that shell, `pgrep` always finds it, so a liveness check never reports a death and a count is one
high); the fix; the override's syntax as §3.5 shows it. One paragraph.

It opens by naming Zikaron and the rule, as the find-replace deny does, so the deny is attributable
to the project's hooks even though the start text never mentions this rule; the rule's name is
explained by the clause that follows it. The excerpt is introduced as *the matched text, with a
little of its line around it*, so the agent reads the 20-character margins as context and the match
as the part in the middle — the one fact that decides between the two fixes on `linux`, since a
match outside the pattern's own spelling is exactly what the bracket does not cure. The
consequences are stated for both words whichever `{word}` is, as §9.3 does: the message is shown
only when the platform's `pgrep` can match the shell, so both halves are true when it is read. The
override sentence takes §3.5's form, with its parenthetical of legitimate exceptions folded into
the conditional as the one case this rule has — §9.4's false denies are all *a deny that is
mistaken*; there is no golden-file or bulk-edit analogue — and with §3.5's concrete reason
unchanged: §9.3 asks for the syntax *as §3.5 shows it*,
§3.4's marker clause, appended on an invalid marker, already ends with that same example, so an
invalid-marker deny shows one example rather than two that disagree, and a reason that is false by
construction for this rule is one §7's count (b) can tell from a reason an agent wrote.

```
Zikaron's self-match rule refused this command: the `{word}` pattern also matches the shell running this command, because Claude Code runs each command inside a shell whose command line contains the command's text. The matched text, with a little of its line around it: `{excerpt}`. So pkill kills this command's own shell, and pgrep always finds it: a check for a running process always finds one, a wait for it to exit never ends, and a count is one high. {fix} If the deny is mistaken and this command is right as written, run it again with a shell comment of exactly this form, giving your own reason in at least two words on that line: #ZIKARON-FORCE #Reason: regenerate golden file.
```

**`{fix}` on `linux`.** `-A` first, because it is the fix that removes every match the rule can
report — the pattern's own spelling, a match elsewhere in the command, a comment on the line — and
because it also covers the one class the replay shows agents handling by hand: a filter on `$$`.
That clause is there for the agent whose `grep -v $$` or `[ "$p" = "$$" ]` was just denied, who
otherwise reads *excludes the shell* as something its command already does and overrides; §9.2's
reason — a `$(pgrep … | …)` runs in a second shell with the same command line and its own id —
is measured (`research/m38-selfmatch-replay.md`), and `-A` drops both. Where `-A` is absent is
named by version and by the two distributions that ship 3.3.17, so the agent that knows its
distribution skips a retry; BusyBox is named because Alpine's default `pgrep` is BusyBox's. The
bracket is second, with an example, and the sentence says what it does not fix in terms of the
excerpt the agent has just read: a match outside the pattern needs that text reworded or moved to
a separate call, which is §9.3's remedy.

```
Add -A (--ignore-ancestors), which excludes the shell running this command and every other ancestor, including the second shell a $(...) substitution forks, which a filter on $$ misses; procps-ng 4.0.1 and later have it, BusyBox and procps-ng 3.3.17 (Ubuntu 22.04, RHEL 9) do not. Where -A is rejected, bracket one character of the pattern ([m]onth_monitor.py) where its text is written, in the assignment if the pattern is a variable, which only stops it matching its own spelling: where the match shown above is not the pattern's text, reword that text or run it in a separate call.
```

**`{fix}` on `darwin`.** Dropping `-a` is the whole fix there, whatever the excerpt shows, since
without it macOS's `pgrep` and `pkill` exclude every ancestor by default
(`research/pgrep-ancestor-exclusion.md` §3; §9.6's premise test pins it on CI's macOS job). The
text says what `-a` means on macOS, because the `-a` was almost certainly written for Linux's
`--list-full` and an agent told only to drop it reaches for it again when it wants the command
lines — so the last sentence gives it `-l` with `-f`, which lists the full argument list there and
leaves the ancestor exclusion in force (§9.5's `darwin` row `pgrep -lf month_monitor.py` is silent).
No bracket and no `-A`: neither is needed, and `-A` is not an option on macOS at all.

```
Drop -a: on macOS it means include the ancestors, which puts the shell running this command among the matches; without it pgrep and pkill leave out every ancestor, this shell included. To list command lines there, use -l with -f.
```

**How the placeholders render.** `{word}` as given, in the template's backticks: `` the `pkill`
pattern ``. `{excerpt}` verbatim, in the template's backticks; for `pkill -f month_monitor.py` the
match is `month_monitor.py` and the margins reach both ends of the line, so the excerpt is the whole
command — `` The matched text, with a little of its line around it: `pkill -f month_monitor.py`. ``
— while for `cd /s && until ! timeout 5 pgrep -f day_panel.py >/dev/null; do sleep 15; done` it is
`` ` timeout 5 pgrep -f day_panel.py >/dev/null; do slee` ``, leading space included, as
`zikaron/guard/selfmatch.py`'s doctest shows. For `pgrep -af '[c]heck\.sh' || echo "check.sh: gone"`
the match is the `check.sh` inside the `echo`, and the excerpt shows the agent that text rather than
its pattern — the case the `linux` fix's last clause is written for. `{fix}` is the platform's text
above, whole.

**The appended clauses** are M37's, byte for byte, after one space, in the order
`deny_message` already applies: §3.4's marker clause (`messages.MARKER_CLAUSE`, from *It carries
#ZIKARON-FORCE* to its example) on a call only this rule would deny that carries an invalid marker;
§3.5's placement clause (`messages.PLACEMENT_CLAUSE`) when the marker sits only in a heredoc body or
a quoted string. Both read correctly after this message's last sentence: each names *this command*
or *no comment in it*, so their *it* is the command, not the comment the sentence before them asks
for.

**Budget.** The template's fixed text is about 670 characters; the `linux` fix about 510 and the
`darwin` fix about 230; `{word}` adds five and `{excerpt}` at most the matched text plus 40. So a
`linux` deny is roughly 1,250 characters, about 300 tokens at four characters a token, and a
`darwin` deny roughly 970 — against the find-replace deny's roughly 560 plus its targets. It is
longer because it carries three facts that deny does not need: a platform-dependent fix, a fallback
for where that fix is absent, and what the fallback leaves unfixed. The replay puts this deny at
301 of 33,784 commands, under 1%, so the per-session cost is a few hundred tokens on the sessions
that meet it at all. If that is ever judged too much, the clauses to cut, in order of least loss,
are the two distribution names and the `$$` clause — each answers an observed class and nothing
else in the message does.

**Notes for the build.**

1. **Each placeholder once, and only the three.** `tests/test_guard_selfmatch_table.py`'s
   `_template_pattern` splits on `\{(\w+)\}` and names a group per placeholder, so a second
   `{word}` is a `re.error` at import, and any other brace is a `KeyError` in `str.format`. The
   texts above satisfy both; a later edit to them must too.
2. **What the existing tests already pin holds.** `tests/test_guard_main.py` line 269 asserts the
   reason starts with `Zikaron's self-match rule refused this command`, which the template does;
   `tests/test_guard_claude_live.py` greps the text before the first `{`, which is a fixed prefix
   ending in a backtick and fine for an `in` test. `test_guard_texts.py`'s
   `test_each_hook_message_is_one_ascii_line` lists M37's six messages; the template and both fix
   texts belong in that parametrisation, which is the builder's edit, not mine.
3. **A backtick inside `{excerpt}` closes the code span early for a reader.** The excerpt is
   verbatim command text and may carry one — `` pkill -f x; echo `date` `` — in which case the
   rendered message's backticks no longer pair. The table test is unaffected, since its non-greedy
   group is bounded by the literal text that follows, and the agent still sees the text; no
   replay pattern carried a backtick, and a pattern with one outside single quotes is not literal
   and never reaches the message, so it takes a single-quoted backtick in the pattern or one in
   the 20-character margin. Recorded, not fixed: every other delimiter has the same failure on
   its own character, and backticks are what the other texts use for command text.
4. **`{excerpt}` can contain `#ZIKARON-FORCE`** — `pkill -f month_monitor.py #ZIKARON-FORCE` puts
   the marker inside the 20-character margin. M37's note 1 already says §7's count (b) must read
   `tool_input.command` or the acknowledgement's fixed substring rather than grep tool results for
   the marker, because every deny carries the override example; the excerpt is one more way a
   deny's tool result carries it. No change; the same caution.
5. **Nothing here touches the find-replace guard.** `DENY_TEMPLATE`, `INVALID_MARKER_TEMPLATE`,
   `MARKER_CLAUSE`, `PLACEMENT_CLAUSE`, `ACKNOWLEDGEMENT_TEMPLATE`, both nudge texts and
   `GUARD_START_TEXT` are unchanged, and the two shared clauses are appended as shipped. Operator,
   2026-10-11: no scope creep into the existing edit guards, and no revisiting of their rules.

Every content requirement in §9.3 — the statement and its cause, the matched text with context,
the consequences, the per-platform fix with `-A`'s version bound and the bracket's limit on `linux`
and `-a`'s meaning and `-l` on `darwin`, and the override's syntax as §3.5 shows it — is met by the
texts above as they stand, in §9.3's order, and nothing in the design had to move to meet it.

VERDICT: APPROVED

## Round 1 — 2026-10-11

**Summary judgment.** The build implements §9 faithfully and the test surface is strong: §9.1's
platform table, its signal list and §9.2's `grep` options are held as data against the design;
every §9.5 row runs through the hook's I/O on its own platform and tool and is asserted against
the message's own template; the premise test measures the platform fact rather than asserting it,
and fails rather than skips where `pgrep` is absent; `decide` carries `platform` with the
determinism property holding over it and over warnings-as-errors; the installer writes
`Bash|Monitor` and replaces an older `Bash` group; and the rename is complete across the live
corpus, with only the brief's intentional exceptions standing. Two things keep it short of
shipping as-is, both small: the rule reads a redirect token as the pattern where §9.1 says
*operand* — a false-deny class the replay was structurally unable to surface, since the prototype
reads the same way — and `README.md` says in two places that the command hook runs before each
`Bash` call while saying forty lines later that it judges `Monitor` too. One round should close
both. Done-when 1's macOS half and done-when 4's matrix are the pull request's by construction
and are not judged here; the 26 mutations are taken as reported.

**Findings.**

1. `[IMPROVEMENT]` **A redirect written before the pattern is read as the pattern** —
   `zikaron/guard/selfmatch.py` `read_call` (lines 194–201) and `zikaron/guard/grep_filter.py`
   `read_grep` (line 127). §3.1 tokenises `pgrep -f 2>/dev/null '[m]onth_monitor.py'` as
   `pgrep`, `-f`, `2>/dev/null`, `'[m]onth_monitor.py'`; `2>/dev/null` is a word token that does
   not start with `-`, so `read_call` returns it as the pattern, `re` compiles it, it matches its
   own spelling in the command, and the call is **denied** with the excerpt `` `2>/dev/null` `` —
   a false deny on a correctly bracketed pattern, and likewise `pkill -f 2>/dev/null …`,
   `pgrep -f >/dev/null …` and a `2>&1` placed before the operand. §9.1 says *the pattern is the
   first operand, unquoted as §3.1 tokenises*, and §3.1's own reader already classifies these
   tokens (`zikaron/guard/redirects.py`: redirect tokens are never targets), so this is the build
   reading the design's word *operand* more loosely than the design's own machinery does, not a
   rule change; §7's *where the table and this document disagree, one of them is a defect, decided
   in the code review* applies, and I am deciding it is the code. **The replay's zero
   disagreements is not evidence about this shape**: `experiments/m38_selfmatch_prototype.py`
   line 109 takes the first non-option word the same way, so both judges deny it identically; the
   `--dump` deny list can be grepped for `-f [0-9]*>` to learn whether any of the 301 is one. The
   agent is not stuck — `-A` is in `never` and silences the call — which is why this is not a
   blocker. **Fix:** in `_in_pipeline`, compute `redirect = find_redirects(simple.tokens).tokens`
   once and hand `read_call` the arguments with those indices removed —
   `[t for i, t in enumerate(simple.tokens) if i > at and i not in redirect]` — which also drops
   the word after a bare `>`; apply the same filter in `drops_shell_line` before `read_grep`.
   Then add §9.5 rows stating the values: `pgrep -f 2>/dev/null '[m]onth_monitor.py'` silent;
   `pkill -f 2>/dev/null month_monitor.py` deny; `pgrep -af month_monitor.py \| grep -v
   2>/dev/null '[z]zz'` deny (the `grep`'s pattern is `[z]zz`, which does not search the text —
   today it is read as `2>/dev/null`, which does, and the call is wrongly exempt). If the operator
   prefers §7's other route — no parse change — then §9.4 gains *a redirect written before the
   pattern is read as the pattern, a stated false deny* and §9.5 the row
   `pgrep -f 2>/dev/null '[m]onth_monitor.py'` → deny. Either way the table must state the value;
   today it is silent on the shape.

2. `[IMPROVEMENT]` **`README.md` describes the command hook two ways.** Line 105 (*a single-shot
   executable the harness runs before each Bash call and after each edit*) and line 328 (*the two
   guard hooks — before each Bash call, after each edit*) predate item 3, while line 471 says
   *Both refusals judge `Bash` and `Monitor` commands alike.* Item 7 names `README.md` as owed by
   this build, so the document should agree with itself. **Fix:** line 105 → *before each `Bash`
   or `Monitor` call and after each edit*; line 328 → *before each `Bash` or `Monitor` call, after
   each edit*. The same phrase in `tests/test_hook_stdlib_only.py` line 50 (*runs on every Bash
   call and every edit*) may follow or stay, since it is commentary.

3. `[NITPICK]` **`tests/test_guard_selfmatch_table.py` line 80** asserts
   `parts["word"] in ("pgrep", "pkill")`; a `{word}` filled with the wrong one of the two passes
   on any row whose command carries both. `assert parts["word"] in case.command` is as cheap and
   ties the rendered word to the row.

4. `[NITPICK]` **`zikaron/guard/grep_filter.py` `read_grep`** keeps a bare first operand as a
   pattern after a later `-e`/`--regexp`, where `grep` demotes it to a file:
   `pgrep -af x | grep -v grep -e '[z]zz'` is exempted on the strength of `grep`, which that
   `grep` does not search for. The direction is a miss, the shape is unobserved, and §9.2's *its
   first operand or each `-e`* already states the intended reading. Either clear `grep.patterns`
   the first time `_PATTERN` is seen with none seen before, or add the row to §9.5 as a stated
   miss under §9.4's exemption edges.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-11

**Summary judgment.** All four round-1 findings are closed as described and as the files now
stand: `redirects.arguments` hands both readers the operands with the redirect tokens out, §9.1
and §9.2 say so, §9.5 states the redirect shapes, `read_grep` takes the first operand as the
pattern only when no `-e`/`-f` was given, `README.md` names `Bash` or `Monitor` in both places,
and the table test ties `{word}` to the row's command. Read whole again with fresh eyes, the build
is a faithful implementation of §9: the decision order, the override's two outcomes, the clause
appending, the platform plumbing from `sys.platform`, the `Monitor` matcher through the one seam,
the installer's replacement of an older `Bash` group, the premise test in the default tier
(`integration`, which `addopts` does not deselect), and the rename, which leaves only the brief's
intentional residue in the live corpus (`.claude/`, `.kiro/`, `.github/`, `pyproject.toml` and the
scripts carry none). Done-when 2 and 3 are met in `research/m38-selfmatch-replay.md`. One
test-strength gap keeps this from APPROVED: half of §9.1's option sentence has no test that can
fail, and I traced a mutation that the whole suite lets through. It is a one-assertion fix plus
one §9.5 row. The two nitpicks are a stated-value row and a clause in the decision table.

**Findings.**

1. `[IMPROVEMENT]` **§9.1's "consumes the rest of its cluster" has no test that can fail.**
   `zikaron/guard/selfmatch.py` `_read_cluster` (lines 216–222) returns
   `index == len(letters) - 1` — consume the next token only when the argument-taking letter ends
   the cluster, otherwise the rest of the cluster is the argument. Every attached-argument reading
   the suite exercises has the letter *last*: `tests/test_guard_selfmatch.py`
   `test_an_option_consumes_an_argument_exactly_when_the_table_says` (lines 123–137) builds
   `-{letter}` alone and `{applies}{letter}` with the letter last; `pgrep -f -int month_monitor.py`
   ends in `t`; every §9.5 cluster row (`-fu nathan`, `-F /tmp/m.pid`, `-c cls`, `-9`) is the same
   shape; the property test asserts no verdict. So the mutation `return True` in `_read_cluster`
   — consume the attached rest **and** the next token — leaves every test green while silencing
   `pgrep -d, -f month_monitor.py` and `pgrep -P1 -f month_monitor.py`, whose `-f` it swallows as
   a second argument. The brief's invariant names this form (*"in a cluster and alone"*), the
   author's branch coverage cannot see it (the clause is one `return` with no branch), and I
   reasoned the mutation through the test lists and every §9.5 row rather than running it — the
   builder should run it and see red. **Fix:** in that test add a third form,
   `attached = f"pgrep {applies} -{letter}zzz month_monitor.py"`, asserting
   `_judge(attached, platform.value) is not None` for every letter: for an argument-taking letter
   `zzz` is the attached argument and `month_monitor.py` the pattern; for any other, `-{letter}zzz`
   is four options, `z` taking no argument on either platform, and the pattern is the same — so
   the correct code denies on every letter and the mutation falls silent on the argument-taking
   ones. Add the §9.5 row `pgrep -d, -f month_monitor.py` · `pgrep -P1 -f month_monitor.py` →
   deny (an attached argument ends the option's reach; the `-f` stands), beside the
   `--delimiter=,` row that already states the long form.

2. `[NITPICK]` **The exemption's edges under `-c`, `-n` and `-o` are unstated.** By §9.2's rule as
   written and as `_in_pipeline` (lines 174–176) implements it, `pgrep -acf month_monitor.py |
   grep -v grep` is exempt, though `-c` suppresses the listing and prints a count the filter
   cannot touch, so the count stays one high; and `pgrep -naf month_monitor.py | grep -v grep` is
   exempt, though `-n` picks the newest match, which is the shell running the call, so the filter
   empties the output and a running process reads as stopped. Both are conceived — the replay note
   records neither — so under §7 they take the value the rules give and the code does not move.
   **Fix:** add both to §9.4's exemption-edges bullet as misses, and as a §9.5 row `silent (stated
   miss, §9.4)`.

3. `[NITPICK]` **D38's amendment leaves the find-replace deny reading as `Bash`-only.**
   `design/overview.md` line 212: the row opens *A `PreToolUse` hook on `Bash` denies a
   find-replace edit*, and the 2026-10-11 amendment attaches *on `Bash` and `Monitor`* to the
   self-match rule alone, while `README.md` line 471 says both refusals judge `Monitor` and
   `design/guards.md` §9.1 says that is intended. A reader of the row alone concludes otherwise.
   **Fix:** extend the amendment's sentence — after *by the platform's own `pgrep` semantics* —
   with *; the hook's matcher is `Bash|Monitor`, so the find-replace deny judges a `Monitor` command
   too*. The opening sentence stays, per the table's strike-and-correct rule.

**Declined, with the reason.** Procps-ng reads only the *first* signal-shaped token as `pkill`'s
signal and hands a second to getopt, where the rule skips every one; and the exemption ignores the
long dialect names (`--fixed-strings`, `--extended-regexp`), reading such a pattern as basic. Both
are conceived edges with no replay instance, and in both the own-spelling match makes the verdict
the same on every shape I could construct, so neither earns a row. The prompt-texts note that
`{excerpt}` never holds a newline is slightly over-stated — a pattern matching across a line break
(`\s`) yields an excerpt spanning it, since `_excerpt` bounds the margins by the line and not the
match — but the JSON stays valid and no text or test depends on it.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-11

**Summary judgment.** All three round-2 findings are closed as the files stand: the attached form
is in `tests/test_guard_selfmatch.py` lines 141–142 and asserted denied for every letter, §9.5
line 1232 states the `-d,`/`-P1` row, §9.4 lines 1192–1196 and §9.5 line 1257 state the `-acf`
and `-naf` misses, and D38's amendment in `design/overview.md` line 212 now says the hook's matcher
is `Bash|Monitor`. Read whole again, the build is a faithful implementation of §9 and the brief's
eight items, and I found no defect in it: `darwin`'s argument-taking letters are exactly the
colon-suffixed ones in the getopt string `research/pgrep-ancestor-exclusion.md` §3 records
(`FGPUcdgtu`); `grammar.parse` bounds a pipeline at `;`, `&&`, `||` and `&`, so the exemption's
`pipeline[index + 1:]` sees only a `grep` that reads the `pgrep`'s output; the premise test reads
the shell's identity from `Popen.pid` and asserts on it rather than on a count; the rename leaves
only the brief's intentional residue in the live corpus (`start_text.py`'s heading, the two
citations of `reviews/m37-edit-guards-review.md`, which is that file's name, §M37's heading, and
`FINDINGS.md`'s description of the rename itself); and `README.md`, `CLAUDE.md`,
`design/overview.md` §1–§3, `design/README.md`, `design/harness.md` and `design/architecture.md`
all now say what ships in the same terms. Done-when 1's macOS half and done-when 4's matrix remain
the pull request's. What is left is two trivial items, neither of which would change a verdict the
table states.

**Findings.**

1. `[NITPICK]` **`_as_python`'s basic and fixed branches have no exempting case that a dialect
   mutation turns red.** `zikaron/guard/grep_filter.py` lines 173–190: every basic pattern in
   `tests/test_guard_selfmatch.py`'s exempting list (lines 233–256) is either plain text or a `\|`
   alternation, and the one `-F` case, `'pgrep|'`, matches its own spelling whether `re.escape` is
   applied or not. So dropping `(` from `_BASIC_SPECIALS` — or dropping the escape of unescaped
   specials entirely — and replacing the `FIXED` branch with a fall-through both leave the suite
   green; the extended branch is already pinned by `grep -vE 'pgrep('` → deny. **Fix:** add two
   items to the exempting parametrisation — `grep -v 'grep('` (a basic `(` is literal, so the
   pattern matches its own spelling; with `(` unescaped `re` refuses it and the call is wrongly
   denied) and `grep -vF 'x$y'` (fixed, so `$` is a character and the pattern matches its own
   spelling; read as any regular expression `$` is an anchor, nothing matches, and the call is
   wrongly denied). Both fit the existing test's three assertions as written, and both could join
   §9.5's silent-filter row at line 1254 if the table is to state them.

2. `[NITPICK]` **§9.5's preamble under-describes its platform column.** `design/guards.md` line
   1221 says *under `sys.platform` `linux` unless it says `darwin`*, while the table carries a
   `win32` row (line 1287) and `tests/guard_table.py` `_platform_and_tool` (lines 371–382) reads
   any lowercase span as the platform. **Fix:** *unless it names another*.

VERDICT: APPROVED

## Round 4 — 2026-10-11

**Summary judgment.** Round 3's two nitpicks are closed as the files stand (`grep -v 'grep('` and
`grep -vF 'x$y'` in `tests/test_guard_selfmatch.py` lines 268–269 and §9.5 line 1273; §9.5's
preamble at line 1233). The amendment is implemented as §9.1 now states it and I found no defect
in the mechanism: `_bindings` reads exactly what §3.3's `bound_variables` returns — assignment-only
simple commands, so a prefix assignment and `export P=…` bind nothing, `zip(strict=True)` is safe
because a non-empty result has one pair per token — skips `in_substitution` commands so a same-line
`$(…)` binds nothing outside itself, records `None` for a non-literal value so that the *last*
binding governs rather than the last literal one, and is reset per unit so a scanned body starts
empty; `_pattern_text` tries `literal_text` first, so `'$P'` stays the literal `$P`, and
`_VARIABLE.fullmatch(token.raw)` on the raw token is what makes `"$P` and `"$P"x` unread — the
mutation to `search` or to `unquoted` would turn `test_only_a_token_that_is_one_variable_is_read_as_its_value`
red, as the author reports. **Done-when 2's one disagreement is decided here: the shipped rule is
right.** The probe's shell runs `bash -c 'P=selfmatch-guard-probe; pgrep -af "$P"; …'`, whose
command line contains `selfmatch-guard-probe`, so `pgrep -af` with that value lists it; the
prototype's silence is the pre-amendment reading, and the prototype stays as it is, being the
brief's count source. The gate and the five mutations are taken as reported. One thing keeps this
from APPROVED: the fix text and §9.3 prescribe, for a match that is not the pattern's own
spelling, *a separate call* — and for the case the amendment adds, the match *is* the pattern's
spelling, written in an assignment, so that advice splits the assignment from the `pkill` and the
next call runs `pkill -f ""`. It is a one-clause edit in two places, and the mirror in this file's
§"Prompt texts" is already made.

**Findings.**

1. `[IMPROVEMENT]` **The `linux` fix's bracket sentence, and §9.3's, misdirect the one case the
   amendment adds.** `zikaron/guard/messages.py` lines 66–68 end *bracket one character of the
   pattern ([m]onth_monitor.py), which only stops it matching its own spelling: where the match
   shown above is elsewhere in the command, reword that text or run it in a separate call*, and
   `design/guards.md` §9.3 line 1160 says *which fixes only the pattern's own spelling, so a match
   elsewhere in the command needs a separate call*. For `P=month_monitor.py; pkill -f "$P"` the
   excerpt shows the match inside `P=month_monitor.py` — not in the pattern token — so an agent
   reading either sentence classifies it as *elsewhere* and the remedy offered is to move that text
   to a separate call. Claude Code runs each call in a fresh `bash -c` (the wrapper
   `research/m38-selfmatch-replay.md` measured; only `cwd` is carried, §3.3), so the next call's
   `"$P"` is empty and `pkill -f ""` matches every process — procps-ng compiles the empty pattern
   and it matches everything — which the rule cannot see (an unbound variable is silent, §9.1).
   Improbable, since `-A` comes first and the n=1 live run took it unprompted, but the design
   states a remedy that is wrong for a case it introduces, and the correct one is that the bracket
   goes where the pattern's text is written — in the assignment — which `_search` then does not
   find (`[m]onth_monitor.py` does not match `P=[m]onth_monitor.py`). **Fix, three places that must
   move together because `tests/test_guard_texts.py::test_the_self_match_deny_and_its_fixes_are_the_reviewers`
   binds the constant to this file's §"Prompt texts" §1 block:** (a) `SELF_MATCH_FIXES[Platform.LINUX]`'s
   last sentence becomes *Where -A is rejected, bracket one character of the pattern
   ([m]onth_monitor.py) where its text is written, in the assignment if the pattern is a variable,
   which only stops it matching its own spelling: where the match shown above is not the pattern's
   text, reword that text or run it in a separate call.* — ASCII, one line, no brace, about 55
   characters longer; (b) **this file's §1 `linux` block already carries that wording, edited in
   place this round** (the previous sentence is quoted above, so the trail holds), so the gate is
   red on that test until (a) lands and green after; (c) §9.3 line 1160: *otherwise a bracketed
   character (`[m]onth_monitor.py`) — written in the assignment where the pattern is a bound
   variable (§9.1) — which fixes only the pattern's own spelling, so a match elsewhere in the
   command needs a separate call.* The `darwin` fix needs nothing: dropping `-a` is whole whatever
   the excerpt shows. No row of §9.5 moves — this is wording, not a verdict.

2. `[NITPICK]` **Two values §9.1–§9.2 state have no row that can fail.** (i) §9.2 says the `grep`
   pattern is *not* read from a binding, *which §9.1 reads for the `pgrep` pattern alone*, and
   `read_grep` (`grep_filter.py` line 131) does hand `literal_text` the token with no bindings — but
   nothing pins it, so threading `bound` into `read_grep` later would leave every test green. Add
   the §9.5 row `P=grep; pgrep -af month_monitor.py \| grep -v "$P"` → deny (the `grep`'s pattern
   is not read from a binding, §9.2; a stated false deny, §9.4), and name it in §9.4's
   exemption-edges bullet beside `grep -v -f <file>` — it is a false deny, since that `grep -v grep`
   does drop the shell's line. (ii) §9.1's *a variable the command binds* means §3.3's reading,
   under which `export P=x`, `declare`/`local`, `for P in …` and `read P` bind nothing; a reader of
   §9.1 alone expects `export` to count. Add the row `export P=month_monitor.py; pkill -f "$P"` →
   silent (not a binding by §3.3's reading; a stated miss, §9.4) and the clause to §9.4's variable
   bullet. Neither moves a rule — §3.3's reading is the existing guards' and is not reopened; both
   state a value the code already gives.

3. `[NITPICK]` **`tests/test_guard_selfmatch.py`'s module docstring enumerates the properties the
   file tests and omits the two the amendment added.** Lines 4–7 list the option, signal, platform
   and exemption properties; add *a bound variable is read as the last value bound before the
   call, and only when the token is that variable alone*. A test file's docstring that lists its
   tests is the stale-comment class `design/coding-standards.md` §5 warns of.

**Declined, with the reason.** A value with a tilde (`P=~/x`) or an appended assignment (`P+=b`)
reads differently from what the shell hands `pgrep` — conceived shapes, none in the replay, and
§7 moves nothing on a conceived edge. A `$(…)` closing on a later line is parsed as the unit's own
pipelines, so a binding made inside it is carried out where the shell would not — §3.3 reads it
the same way, and the existing guards' rules are not revisited (operator, 2026-10-11). An unbound
`"$P"` — the `pkill -f ""` hazard finding 1 guards the advice against — is silent by §9.1 as
written and would be a different rule, not this one.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-11

**Summary judgment.** Round 4's three findings are closed as the files stand:
`SELF_MATCH_FIXES[Platform.LINUX]` (`zikaron/guard/messages.py` lines 63–69) is character for
character this file's §"Prompt texts" §1 `linux` block, as the template and the `darwin` fix are
theirs; §9.3 lines 1160–1162 put the bracket in the assignment and say why; §9.5 line 1275 states
`P=grep; … | grep -v "$P"` as a deny and line 1290 `export P=…; pkill -f "$P"` as silent, with
§9.4 lines 1183–1184 and 1211–1212 naming both; and `tests/test_guard_selfmatch.py`'s docstring no
longer lists its tests. Read whole again, the amendment is implemented as §9.1 states it and its
tests can fail — I traced each mutation the author names through the rows rather than running it:
dropping `_bindings`'s `in_substitution` skip turns `x=$(P=month_monitor.py); pkill -f "$P"` red,
skipping a non-literal value instead of recording `None` turns `P=month_monitor.py; P=$1; …` red,
dropping the `braced` group turns `P=month_monitor.py && pkill -f "${P}"` red, and `fullmatch` on
`unquoted` turns `"$P` red. Done-when 2's one disagreement stands decided in round 4 and
`research/m38-selfmatch-replay.md` lines 144–159 record it with both verdicts. What keeps this from
APPROVED is one sentence of §9.1 — and the same sentence in `_bindings`'s docstring — which, read
with the rule above it, licenses a deny the code does not give on a shape that is a real self-match.
It is a wording fix and a stated-value row, not a rule change; the two nitpicks are a second
stated-value row and the D38 row.

**Findings.**

1. `[IMPROVEMENT]` **§9.1 implies a binding inside a same-line `$(…)` is read for a call inside the
   same `$(…)`; the code reads it nowhere.** `design/guards.md` line 1107–1108: *a same-line
   `$(…)`'s commands bind nothing outside the subshell they run in*; `zikaron/guard/selfmatch.py`
   lines 176–177 (`_bindings`): *A same-line `$(…)` is a subshell, so its commands bind nothing
   outside it.* Both are true as far as they go, but §9.1's general sentence — *a simple command
   made only of `NAME=value` words, earlier in the same unit* — covers the assignment inside the
   substitution too, and the *outside* qualifier reads as the one carve-out, so a reader concludes
   that inside the subshell the binding stands. `_bindings` line 180 skips every `in_substitution`
   command, so it stands nowhere. Trace `kill $(P=month_monitor.py; pgrep -f "$P")`:
   `grammar._dollar` (line 257) emits the substitution's two pipelines first, both
   `in_substitution`; after the first, `_bindings` yields nothing; in the second, `_pattern_text`
   finds `P` unbound and `_search` returns `None`; the enclosing `kill` is not read. Silent. In
   bash the substitution's shell binds `P`, `pgrep -f month_monitor.py` lists the wrapper (whose
   command line carries `P=month_monitor.py`) and the substitution's own shell, and `kill` kills
   the wrapper — a self-match of exactly the kind the rule exists for, and `for p in $(P=…; pgrep
   -f "$P"); do kill $p; done` is the same. Conceived, none in the replay, so under §7 the code does
   not move and §3.3's reading is not reopened (operator, 2026-10-11); the design must state what
   the code does. **Fix:** §9.1 line 1107–1108 → *and a same-line `$(…)`'s commands bind nothing
   that is read — not for the commands after it, which run in another shell, and not for a `pgrep`
   inside the same `$(…)`, whose bindings the rule does not track*; `_bindings`'s docstring →
   *What a same-line `$(…)` binds is not read, inside it or after it: a subshell's bindings are not
   tracked.* §9.4's variable bullet (line 1180–1184): add *nor one bound inside a same-line
   `$(…)`, for a call inside it (`kill $(P=month_monitor.py; pgrep -f "$P")`) as for one after it:
   a stated miss*. §9.5: add `kill $(P=month_monitor.py; pgrep -f "$P")` to row 1290's items, or as
   a row of its own → *silent (stated miss, §9.4)*. The row is documentary — no mutation of the
   present code turns it red that `x=$(P=month_monitor.py); pkill -f "$P"` does not already catch —
   which is what a stated-value row is for.

2. `[NITPICK]` **A binding whose simple command opens with `(` or a standalone `{` is not one, and
   nothing says so.** `(P=month_monitor.py; pkill -f "$P")` and `{ P=month_monitor.py; pkill -f
   "$P"; }`: `grammar._open_boundary` (line 215–218) puts the opener into the simple command's
   tokens as a boundary token, `bound_variables` (`position.py` line 105–109) requires every token
   to be a word, so it returns `()` and `P` is never bound; the call is silent. In bash both bind
   `P` where the `pkill` runs — the group in the calling shell, the subshell in a child whose
   parent's command line carries the text — and both kill the wrapper. §9.1's *a simple command
   made only of `NAME=value` words* is literally consistent, since a boundary is a token of that
   command (§3.1), but a reader cannot see that `(` counts as one of its words. Conceived; the code
   does not move (§7; §3.3's reading). **Fix:** in §9.4's variable bullet, after the `export` list:
   *nor one whose assignment shares its simple command with a `(` or `{` opener (`(P=…; pkill -f
   "$P")`), the opener being a token of that command (§3.1)*; §9.5: `(P=month_monitor.py; pkill -f
   "$P")` · `{ P=month_monitor.py; pkill -f "$P"; }` → *silent (stated miss, §9.4)*. Documentary,
   as finding 1's row is.

3. `[NITPICK]` **D38's row says nothing of the substitution amendment.** `design/overview.md` line
   212: the Decision cell's 2026-10-11 amendment says the hook denies a `pgrep -f`/`pkill -f`
   *whose pattern matches the command's own text*, and a `"$P"` pattern matches no text — the
   bound value does — so the row under-states what the rule reads, where its 2026-10-07 precedent
   records a comparable refinement of what the find-replace rule reads. The decision and its
   authority are in §9.1 (*operator, 2026-10-11*) and `design/build-plan.md` item 1 (the
   operator's words), so nothing is lost for a reader who gets that far; what no document states is
   the *reason*, which is the Rationale column's job. **Fix:** after *by the platform's own `pgrep`
   semantics*, add *— and, **amended again 2026-10-11 (operator: "Sure, let's do substitution")**,
   a pattern that is exactly a variable the command binds is judged on its bound value, read as
   §3.3 reads a binding for a target*; in the Rationale cell, after the per-platform sentence: ***A
   bound variable is read for the reason §3.3 reads one for a target**: the operator's probe
   `P=selfmatch-guard-probe; pgrep -af "$P"` self-matched and the rule, reading any `$` as not
   literal, said nothing; the value is in the text and the reader already exists, and a split
   literal (`P="month_mon""itor.py"`), the replay's only shape, still passes.* `FINDINGS.md`'s
   index row may follow or stay, per the brief.

**Declined, with the reason.** `P=""; pkill -f "$P"` — the bound value is the empty string, `re`
compiles it, it matches at offset 0, and the deny is *true* (`pkill -f ""` matches every process,
the wrapper included) with an excerpt that is the line's first 20 characters and a fix sentence
that fits nothing: conceived, and the deny is right. `P=month_monitor.py; unset P; pkill -f "$P"` —
`unset` is not read, the binding stands, a false deny on a command that would otherwise run
`pkill -f ""`: conceived. `P=month_monitor.py` / `bash <<EOF` / `pkill -f "$P"` / `EOF` with the
delimiter *unquoted* — the calling shell expands `$P` into the body, the inner `bash` runs the
bound value, and the wrapper dies: a real miss, but §9.1 already states that a scanned body starts
with no bindings, and row 1290's quoted form states the value for the shape. This file's
§"Prompt texts" §"Budget" puts the `linux` fix at about 510 characters, which round 4's edit
raised by about 55; it says of itself that the counts are by hand and approximate, and nothing
reads it.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-11

**Summary judgment.** Round 5's three findings are closed as the files stand: `design/guards.md`
§9.1 lines 1107–1109 say what a same-line `$(…)` binds is read neither after it nor for a `pgrep`
inside it, `_bindings`'s docstring (`zikaron/guard/selfmatch.py` lines 175–177) says the same,
§9.4 lines 1186–1189 name the `(`/`{` opener and the in-substitution binding as stated misses,
§9.5 line 1295 carries all three items, and D38's row in `design/overview.md` line 212 carries the
amendment in its Decision cell and its reason in its Rationale cell. I re-traced the three new
items rather than taking the author's verification: `grammar._open_boundary` (line 215–218) puts
the `(` or standalone `{` into the simple command's tokens, `bound_variables` (`position.py` line
105–109) requires every token to be a word and returns `()`, and `grammar._dollar` (line 257)
parses the substitution's pipelines with `in_substitution=True`, which `_bindings` skips — so `P`
is unbound at the `pkill`/`pgrep` in each and all three are silent, as the row says. §9.1's *as
§3.3 reads one* holds against §3.3's own reader: `decision.all_matches` (lines 116–132) skips
`in_substitution` commands and applies a pipeline's bindings after judging it, exactly as
`first_self_match` does, and the one difference — a non-literal value recorded as `None` rather
than as its raw text — is §9.1's own stated sentence. The research note's four bound patterns in
three commands, every one a split literal and silent (`research/m38-selfmatch-replay.md` lines
153–159), agree with §9.4's *the other 4* and D38's *the replay's only bound shape*. No code
moved and none needed to; what remains is one documentary row.

**Findings.**

1. `[NITPICK]` **Two values §9.1 gives have no row, and they are the shapes an agent writes most.**
   (i) A binding on its own line: `P=month_monitor.py` / `pkill -f "$P"` → deny. Every bound deny
   in §9.5 line 1293 joins the two with `;` or `&&`; a multi-line script separates them with a
   newline, and `parse` bounds a pipeline at a line end, so `first_self_match` carries the binding
   across — but nothing pins that for this reader (§3.3's newline case at line 999 pins its own).
   (ii) A binding made before a same-line `$(…)` and read by the `pgrep` inside it:
   `P=month_monitor.py; for p in $(pgrep -f "$P"); do kill $p; done` → deny. `_dollar` emits the
   substitution's pipeline with `in_substitution=True`, `_in_pipeline` judges it with the unit's
   `bound`, which holds `P`, and the value matches the assignment — a true deny, since the
   substitution's shell carries the same command line. §9.1 says only that what the `$(…)`'s *own*
   commands bind is not read, so (ii) follows from the general rule, but a reader who takes the
   docstring's *a subshell's bindings are not tracked* as *no binding is read inside a subshell*
   would implement the opposite and the suite would stay green: no test puts a bound variable
   inside a `$(…)`. **Fix:** add both to line 1293's items — or as a row of their own — → *deny
   (the bound value is the pattern, §9.1; a `$(…)` reads the bindings made before it)*. Optionally,
   in §9.1 after *whose bindings the rule does not track*, add *— though a `pgrep` inside it reads
   the bindings made before it, which the subshell inherits*; and the clause *not for the commands
   after it, which run in another shell* reads more plainly as *which run in the calling shell, not
   the subshell's*. Documentary: no mutation of the present code is needed to see either row
   green, which is what a stated-value row is for.

**Declined, with the reason.** `if …; then P=month_monitor.py; fi; pkill -f "$P"` — `then P=…` is
not a simple command made only of assignments, so no binding stands and the call is silent where
bash binds `P`: a miss, of the class §9.4's variable bullet already states generically (*none of
which is a binding as §3.3 reads one*), conceived, none in the replay, and the operator's red line
excludes reading control flow. A bound value beginning with `-` (`P=-x; pgrep -f "$P"`) is read as
the pattern where getopt would read it as an option: conceived, and the deny it produces is on a
command that cannot run as intended anyway. The build-plan's and D38's *301 of 33,784* against the
note's *305 of 33,842* are the brief's count and the post-amendment re-run respectively, both
dated, and neither moves a decision.

VERDICT: APPROVED
