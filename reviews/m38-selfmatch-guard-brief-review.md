# Review — M38 brief: the self-match rule for `pgrep -f`/`pkill -f`

Artifact: `design/build-plan.md` §M38, `design/edit-guards.md` §9 and its edits to §1, §3, §3.1, §7, §8,
D38's amendment in `design/overview.md` §4. Evidence read: `research/m38-selfmatch-replay.md`,
`research/pgrep-ancestor-exclusion.md`, `experiments/m38_selfmatch_replay.py`, and the local verdicts
TSV (1,054 judged occurrences; cited below by row number and generic shape only, never by its text).

## Round 1 — 2026-10-11

**Summary judgment.** The mechanism is right and well evidenced: the predicate *is* `pgrep`'s own
search run over the string the wrapper shell carries, the platform split is real, and the replay's
38-of-38 on signalled harm is a strong result. The brief is not yet implementable without the builder
deciding things, and two of them matter: the corpus holds nine commands that handle the self-match
correctly by comparing `pgrep`'s output with `$$`, and §9.2 denies every one of them on a sentence
that is false; and §9.1 never says how a `pkill` signal is told from an uppercase option, where the
obvious reading — the prototype's — denies `pkill -A -f …`, the very fix the deny message names, and the
corpus cannot reveal it. The rest is table completeness and a brief-versus-FINDINGS disagreement
about `!`.

### Findings

1. **[BLOCKER] §9.2 denies the correct remedy the corpus shows agents using, on a false sentence.**
   `design/edit-guards.md` §9.2, second bullet: *"Without `-a` a `pgrep` prints process ids, which no
   such filter removes."* One filter does: `$$` is the wrapper shell's pid — `eval` runs in that shell,
   and the probes read `/proc/$$/cmdline` to prove the mechanism — so dropping `$$` from pid-only
   output removes exactly the self-match. The TSV holds **nine denied commands** doing this, none
   signalled, all read by the prototype as `deny`: rows 3, 200, 244 are `pgrep -f X | grep -v $$ …`;
   rows 10, 106, 146, 207, 212 are `for p in $(pgrep -f X …); do [ "$p" = "$$" ] && continue; …`;
   row 210 is `case "$c" in *pgrep*|*"$$"*) continue;; esac` over each pid's cmdline. (Row 991 is the
   same loop with an escaped pattern and is already silent.) The agents who wrote these knew about the
   self-match and fixed it; the guard would send them to `-A` for a command that already works. Note
   also that with `-a` the spelling `| grep -v $$` is *already* exempt — by accident, since
   `re.search("$$", …)` matches the end of any string — so the prototype's verdict on that pair of
   commands is right for the wrong reason, and a test on `pgrep -af X | grep -v $$` would pass while
   proving nothing.
   **Edit.** Replace the sentence with a rule, and record both the count and the one cost:
   *"Without `-a` a `pgrep` prints process ids, and one filter removes the shell's: a comparison with
   `$$`, its own pid, which `eval` does not change. A `pgrep` is therefore also silent when `$$` stands
   outside single quotes later in the command than its pattern — `| grep -v $$`,
   `[ "$p" = "$$" ] && continue`, `case … *"$$"*)` — on either platform, since this is about the
   output and not the match. Nine replay commands, every one handling its own shell by hand; no
   replay command carries `$$` after a self-matching `pgrep` for another purpose (the one `$$` inside a
   `sed` script is single-quoted). `pkill` has no output to filter, so `$$` exempts nothing there. The
   cost is a `pgrep` followed by an unrelated `$$` — `mktemp /tmp/x.$$` — which is a stated miss."*
   Rows for §9.5: `pgrep -f month_monitor.py \| grep -v $$ >/dev/null && echo RUNNING \|\| echo
   FINISHED` → silent; `for p in $(pgrep -f month_monitor.py); do [ "$p" = "$$" ] && continue; kill
   $p; done` → silent; `pkill -f month_monitor.py; echo $$` → deny; `pgrep -af month_monitor.py \|
   grep -v $$` → silent (and say which exemption, so the accidental one is not the reason);
   `pgrep -f month_monitor.py; mktemp /tmp/x.$$` → silent (stated miss). If the author prefers the
   narrow form — exempt only a `grep -v` whose pattern token is `$$`, three commands — then the six
   loop guards go into §9.4 as a stated false deny with their count; either is a decision, and the
   text now makes neither. The replay counts in `research/m38-selfmatch-replay.md` and in §M38's
   first paragraph move by these nine commands; item 6's re-run covers that, but the brief's
   "304 of 33,789" should not be quoted as settled until it has.

2. **[BLOCKER] §9.1 does not say how a `pkill` signal is told from an option, and the natural reading
   denies the fix the message names.** `design/edit-guards.md` §9.1, third bullet: *"`pkill`'s signal
   (`-9`, `-TERM`, `-SIGKILL`) is skipped"* — three examples, no rule. The prototype's rule
   (`experiments/m38_selfmatch_replay.py` line 42, `_SIGNAL = r"-(?:\d+|(?:SIG)?[A-Z][A-Z0-9+-]*)$"`)
   treats every `-<Uppercase…>` as a signal, so for `pkill` it swallows `-A`, `-F`, `-G`, `-P`, `-U`,
   `-O`, `-L`, `-H`: `pkill -A -f month_monitor.py` is **denied** by the prototype though §9.1's table
   says *never*, and `pkill -F /tmp/m.pid -f '[m]onth_monitor.py'` is denied because `/tmp/m.pid`
   becomes the pattern. The corpus has no `pkill` with an uppercase option (grep over the TSV), so the
   replay agrees with the table only because the case never arose, and done-when 2 ("the re-run replay
   agrees with the brief's counts") would pass with the defect intact. §9.3 tells the agent on linux to
   add `-A`; for `pkill` that retry would be denied again, which is the loop §7's count (e) calls "a
   repeat". procps-ng's own reading: `signal_option()` removes, before getopt, the first `-X` argument
   whose `X` is a number or a signal name with or without `SIG`; everything else is an option — so
   `-A` is the option and `-ABRT` the signal.
   **Edit.** In §9.1: *"`pkill`'s signal is one token `-<digits>` or `-[SIG]<NAME>`, `NAME` from a
   fixed list the module carries for both platforms — HUP INT QUIT ILL TRAP ABRT IOT EMT BUS FPE KILL
   USR1 SEGV USR2 PIPE ALRM TERM STKFLT CHLD CONT STOP TSTP TTIN TTOU URG XCPU XFSZ VTALRM PROF
   WINCH IO POLL INFO PWR SYS, RTMIN, RTMAX, and RTMIN+n/RTMAX-n — and is skipped wherever it
   stands; `-A -F -G -P -U -O` are options, as the table says."* Rows for §9.5: `pkill -A -f
   month_monitor.py` → silent; `pkill -ABRT -f month_monitor.py` · `pkill -SIGABRT -f
   month_monitor.py` · `pkill -KILL -f month_monitor.py` → deny; `pkill -F /tmp/m.pid -f
   '[m]onth_monitor.py'` → silent (`-F` takes an argument). Add to §M38 item 6 that this class is
   absent from the corpus, so the re-run's agreement is not evidence about it and the rows are.

3. **[IMPROVEMENT] The brief and `FINDINGS.md` disagree about `!`, and §9.1 is complete under only one
   of them.** `design/build-plan.md` §M38 item 2 makes `!` a §3.1 wrapper "for both rules";
   `design/edit-guards.md` §3.1 (line 97), §8 row 914, §9.1 (*"§3.1's `!` wrapper was added for this
   rule"*) and §9.5 row 1159 are written to that. `FINDINGS.md` §"Current state" step 5 records the
   operator's pushback and says that after round 1 `!` becomes a prefix of §9's rule alone and the
   §3.1/§7/§8 edits are reverted. Whichever lands, the documents must say one thing. If §9-only, §9.1
   must define the prefix — the prototype's `judge` (lines 115–117) skips only a bare `!` directly
   before the word, so `! timeout 30 pgrep -f X` and `until ! sudo pkill -f X` are misses there.
   **Edit (for the §9-only outcome).** In §9.1's second bullet: *"A standalone `!` at a command
   position is skipped by this rule alone, and §3.1's wrappers after it are skipped as they are before
   any command word (`! timeout 30 pgrep -f …`, `until ! sudo pkill -f …`); §3's rule does not read
   `!`."* Then item 2 of §M38 becomes that sentence's implementation, the §8 row and §3.1's `!`
   clause go, and §9.5 row 1159's note reads "(`!` is skipped, §9.1)". Add a row `until ! timeout 5
   pgrep -f day_panel.py >/dev/null; do sleep 15; done` → deny, which the prototype would miss.

4. **[IMPROVEMENT] Hand-filtered loops over `$(pgrep -f X)` are an observed false-deny class §9.4 does
   not state.** TSV rows 2, 8, 131, 145, 175, 179, 184, 298: the agent iterates every match and
   filters by `/proc/$p/comm`, `/proc/$p/cmdline` or `ps -o`. Rows 175 and 179 (`comm` is `python3`)
   are correct and denied; row 184 (`grep -q python` on the cmdline) and row 298 (`case
   *python3*month_monitor.py*)`) matched the wrapper *through the filter's own text* — 298 killed its
   shell, exit 144 — so the class is genuinely mixed and `deny` is the right value, but it is a
   decision the brief should make visibly rather than by omission, since count (e) will show these as
   denies answered by `-A`.
   **Edit.** §9.4, new bullet: *"A loop over `$(pgrep -f …)` that inspects each pid by hand — eight in
   the replay; two filter by `comm` and are correct, two matched the shell through the filter's own
   words and one of those killed it. Denied: the rule cannot read the filter, and `-A` fixes all
   eight."* §9.5 row: `for p in $(pgrep -f month_monitor.py); do [ "$(cat /proc/$p/comm)" = python3 ]
   && kill $p; done` → deny (stated false deny).

5. **[IMPROVEMENT] Anchors are a third divergence from the real search, not a dialect one, and the
   wrapper's own quoting offers a free fix.** §9.4's bullet *"Python's `re` stands in for POSIX ERE,
   and the command is searched as written, not as the wrapper rewrites a `'`"* names dialect and the
   quote rewrite. A `^`/`$` anchor is neither: the wrapper's argv begins `/bin/bash -c source …` and
   ends `pwd -P >| /tmp/claude-<id>-cwd` (`research/m38-selfmatch-replay.md`), so `pattern$` can
   never self-match and `^pattern` only if it matches `/bin/bash`, while `re.search` over the bare
   `tool_input.command` matches at the text's own ends: `pgrep -f 'month_monitor.py$'; echo
   month_monitor.py` → deny, no self-match in fact. Two anchored patterns in the replay (rows 879,
   880), both bracketed and silent, so this is conceived and §7's rule applies: a row with the value
   the rules give.
   **Edit, either of:** (a) record it — §9.4 bullet *"An anchored pattern is searched over the command
   text, whose ends are not the argv's; `…$` and `^…` can be denied without a self-match. Two in the
   replay, both bracketed and silent."*, and the row above → deny (stated false deny); or (b) since
   the argv is measured to carry the command as `eval '<command>'`, search `"'" + command + "'"` —
   the quotes `eval` wraps it in — which costs nothing, tracks the measured string more closely than
   the bare text does, and makes an anchor unable to match the command's own ends; then the row is
   silent and the §9.4 sentence says why. (b) is the better rule; (a) is the one §7's discipline
   licenses without an observed command, and the author should pick.

6. **[IMPROVEMENT] §9.5 does not carry rows for mechanics §9.1 and §9.2 state, several of them
   observed.** §8's own standard is that the table is "the one place the rule table's rows are
   listed"; the invariants bullet delegates some of these to a property test, which is not the same
   thing. Missing, with values the rules give: `pgrep --full month_monitor.py` → deny;
   `pgrep --ignore-ancestors --full month_monitor.py` · `pgrep --exact --full month_monitor.py` →
   silent; `pgrep --delimiter=, -f month_monitor.py` → deny (`=value` consumes nothing);
   `pgrep --delimiter , -f month_monitor.py` → deny; `pgrep -f -- month_monitor.py` → deny (`--`
   ends options); `pgrep -fa month_monitor.py \| grep -v grep` → silent (the cluster order the corpus
   writes, rows 251 and 292, beside the table's `-af`); `pgrep -af month_monitor.py \| grep -v
   "pgrep\|grep"` → silent (BRE alternation, observed row 191); `pgrep -af month_monitor.py \| grep
   -vE 'pgrep|grep'` · `… \| grep -v -e pgrep -e grep` · `… \| grep -vF pgrep` → silent;
   `pgrep -af month_monitor.py \| grep -v pgrep \| head -3` → silent (the filter is not the pipeline's
   last command, observed rows 321/411); `pgrep -af month_monitor.py \| grep -c pytest` → deny (no
   `-v`, observed row 303); `if ! pgrep -f day_panel.py >/dev/null 2>&1; then break; fi` → deny (the
   other exit-143 loop, row 282); `pgrep -cf month_monitor.py \|\| echo stopped` → deny (the shape of
   rows 157–171, which could only ever answer *running*); `pgrep -f month_monitor.py \| wc -l` →
   deny. Add them.

7. **[IMPROVEMENT] Options after the operand, and a pattern from stdin, are gaps §9.4 does not list.**
   GNU getopt permutes, so `pgrep month_monitor.py -f` is a real self-match the rule misses — §9.1
   reads the first operand as the pattern and stops — and `pgrep -f month_monitor.py -A` is safe and
   denied. `echo month_monitor.py | xargs pkill -f` has no pattern token and is silent while the shell
   carries the text. None observed (grep over the TSV). **Edit.** §9.4, new bullet: *"An option written
   after the pattern (`pgrep month_monitor.py -f`, a miss; `pgrep -f month_monitor.py -A`, a false
   deny), which getopt honours and this rule does not read; and a pattern arriving on stdin
   (`… | xargs pkill -f`), a miss. None in the replay."* Three §9.5 rows with those values.

8. **[IMPROVEMENT] The invalid-marker deny on a §9-only match cannot be §3.4's message as it stands.**
   `design/build-plan.md` §M38 item 4 ("§3.4's invalid-marker message reused on a call only this rule
   matched"), §9.2's last bullet, and §9.5 row `pkill -f month_monitor.py #ZIKARON-FORCE` → "deny, the
   invalid-marker message". `INVALID_MARKER_TEMPLATE` (`zikaron/guard/messages.py` lines 32–39) opens
   *"Zikaron's find-replace guard refused this command: `{word}` {form}; it names {targets}."* — none
   of which is true of a `pkill`, and `{form}` has no value for it. **Edit.** In §9.2 and item 4: *"the
   deny carries §9.3's content, with §3.4's marker clause — from 'It carries #ZIKARON-FORCE' to the
   example — appended; only the clause is shared."* The row's expected cell then reads "deny, §9.3's
   message with the marker clause".

9. **[IMPROVEMENT] §9.6 leaves two behaviours to the builder and could pin a third premise for free.**
   (i) A machine with no `pgrep`: `python:*-slim` images carry no procps, and this project has run its
   suite in Docker (`research/m30-docker-end-to-end.md`). Say whether the test skips with the reason or
   fails — I would skip, since a box without `pgrep` cannot self-match either, and say so. (ii) "Where
   `pgrep` accepts `-A`": say how that is decided — `pgrep -A -f <nonce>` exiting 2 with *invalid
   option* on 3.3.17 and BusyBox skips that half; any other non-zero is a failure of the premise.
   (iii) The `-a` exemption rests on a second platform fact nothing pins: that `pgrep -a` prints the
   wrapper on **one** line when the command spans lines — true if procps escapes control characters
   as `?` in `CMDLINE`, which I believe it does but did not run. One more call in the same test, a
   two-line `bash -c` whose `pgrep -af <nonce>` output is asserted to be one line, would make the 65
   exempt calls rest on a measurement.

10. **[NITPICK] §9.2 "acknowledged only when §3's rule matched"** — §3.4 reads no override when every
    target of a matched form is exempt, so "matched" here must mean "would have denied". Say that.
    Optional: when a valid override withdraws both rules, one clause in the acknowledgement that the
    self-match was withdrawn too would cost a sentence and would tell the agent what it just accepted.

11. **[NITPICK] §9.3's darwin fix.** "Drop `-a`" is right; add that `-l` is the listing flag there,
    since an `-a` on macOS was almost certainly written for Linux's `--list-full`, and an agent told
    only to drop it will reach for `-a` again when it wants the command lines.

12. **[NITPICK] §9.4's darwin bullet.** The exemption is linux-only, yet `pgrep -alf X | grep -v grep`
    would be correct on darwin (`-l` with `-f` lists the full argument list). State that the exemption
    is withheld there for want of a Mac transcript, not because the filter fails there — otherwise a
    reader takes "no exemption on `darwin`" (§9.5) as a platform fact.

13. **[NITPICK] §9.1's linux "options taking an argument" omits `--env`** (procps-ng 4.0.5+), which the
    prototype's `_LONG_WITH_ARG` includes. Immaterial on 4.0.4, but item 6 compares the two, so they
    should agree or the difference should be named.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-11

Artifact re-read in full: `design/build-plan.md` §M38, `design/edit-guards.md` §§1, 3, 7, 9 (and §8 for
the rows §9 leans on), D38 in `design/overview.md` §4 and `FINDINGS.md`; `research/m38-selfmatch-replay.md`,
`research/pgrep-ancestor-exclusion.md`, `experiments/m38_selfmatch_replay.py`; the local all-verdicts TSV
(1,054 judged occurrences, cited by row number and generic shape only). No shell in this session, so
every claim below about a program's behaviour is from its source as I know it and is labelled so.

**Summary judgment.** Round 1's blockers are resolved as the brief says: the signal list, the `$$`
decision, the `!` placement and the per-platform option tables each state a value, §9.5 carries the rows,
and every `linux` row I walked by hand through the prototype's `read_call`/`_verdict` gives the value the
table states (the `-F /tmp/m.pid` row genuinely tests the argument — without it the pattern would be
`/tmp/m.pid`, which the command contains). One observed idiom is still outside every table: a `pgrep -f`
inside a double-quoted `$(…)` — `[ -z "$(pgrep -f <app>)" ] && echo none`, the canonical liveness check
— which §3.1 keeps whole, so §9 never sees it and the replay never counts it. The rest is a signal-case
divergence from procps that flips a verdict, a premise-test discriminator that fails on BusyBox instead of
skipping, and a replay comparison that cannot attribute its own differences.

### Findings

1. **[BLOCKER] A `pgrep -f`/`pkill -f` inside a double-quoted `$(…)` is observed, unseen, unstated and
   uncounted.** §3.1 makes an unquoted `$(` a command position and keeps a double-quoted `"$(…)"` whole
   (§7's stated miss; §8's row `x="$(sed -i 's/a/b/' f)"` → silent). §9.1 reuses that grammar unchanged,
   so `[ -z "$(pgrep -f <app>)" ] && echo none`, `kill "$(pgrep -f <app>)"` and `PIDS="$(pgrep -f
   <app>)"` reach neither rule. The dump holds one — row 21, a liveness check of exactly that shape, judged
   at all only because the same command also ran an unquoted `for p in $(pgrep -f …)` — and it is the shape
   §9 itself calls always wrong: on Linux it never prints *none*. The replay cannot count the class: a
   command carrying only that form has no `pgrep` in command position and yields no verdict, so "301 of
   33,784" is a floor, and nothing in `research/m38-selfmatch-replay.md` says it is one. Neither §9.4 nor
   §9.5 mentions the form. **Edit, two parts.** (i) Count it: the replay gains a counter over
   `tool_input.command` for `"$(`, optional §3.1 wrappers, then `pgrep`/`pkill` with an `-f` cluster before
   the `)`; the research note reports it beside the 301, and §M38 item 6 names it. (ii) Decide it on that
   count, in §9.1 or §9.4 — either *"a `$(…)` inside a double-quoted string is one token (§3.1) and is not
   judged — N in the replay, every one a status check; a stated miss"*, with §9.5 rows `[ -z "$(pgrep -f
   month_monitor.py)" ] && echo none` · `kill "$(pgrep -f month_monitor.py)"` · `PIDS="$(pgrep -f
   month_monitor.py)"` → silent (stated miss, §9.4); or, exactly as `!` already is, a position **this rule
   alone** reads — *"the text of a `$(…)` inside a double-quoted token is parsed as a command for this
   rule alone, since the calling shell carries it too; §3.1 is unchanged"* — with those rows → deny.
   Neither option touches §3.1 or §3's forms, and the operator's rule licenses either since the command is
   observed; the count is what decides between them.

2. **[IMPROVEMENT] The signal list is matched case-sensitively and procps-ng is not — a lowercase signal
   flips a verdict.** §9.1: *"`-[SIG]<NAME>` … `NAME` from a fixed list … as procps-ng reads them."*
   procps-ng's `signal_name_to_number` (`lib/signals.c`; `proc/sig.c` in 3.3.17) compares with
   `strcasecmp`, and BSD `pkill.c` with `strcasecmp(sys_signame[i], p)` — so `pkill -int`, `-term`, `-hup`,
   `-sigkill` are signals on both platforms, and `pkill -io` is SIGIO rather than `-i -o` (source reading,
   not run). Under the rule as written `-int` is the options `-i -n -t`; `-t` takes an argument and ends
   the cluster, so it consumes `-f`, `full` is never set, and `pkill -int -f month_monitor.py` is
   **silent** on a real self-kill. The same for `-cont`, `-chld`, `-sys`, `-bus`, `-ttou`, `-urg`, `-pwr`,
   `-emt` (an argument-taking letter last) and `-xcpu`, `-xfsz`, `-vtalrm` (an exempting letter first);
   `-term`, `-hup`, `-stop`, `-sigkill` happen to come out right because the argument-taking letter eats
   the rest of its own cluster. None in the corpus (0 by grep over the dump), so §7's rule would allow a
   stated miss — but then *"as procps-ng reads them"* is false and must go. **Edit, preferred:** in §9.1,
   *"matched without regard to case, as both platforms' `pkill` compare it"*; rows `pkill -int -f
   month_monitor.py` · `pkill -cont -f month_monitor.py` · `pkill -xcpu -f month_monitor.py` → deny;
   `_SIGNAL` in `experiments/m38_selfmatch_replay.py` gains `re.IGNORECASE` so item 6's re-run tests the
   same rule. One clause for truth besides: BSD `pkill` reads the signal only as its first argument, so
   *"wherever it stands"* is procps-ng's reading, and on `darwin` a later `-TERM` is a usage error —
   immaterial to the verdicts, which need `-a` there.

3. **[IMPROVEMENT] §9.6's "`-A` absent" discriminator is wrong for BusyBox, so on Alpine the test fails
   the half it means to skip.** *"unless `pgrep -A -f <nonce>` exits 2 saying *invalid option*, as
   procps-ng 3.3.17 and BusyBox do."* BusyBox's usage error goes through `bb_show_usage()` → `xfunc_die()`,
   which exits `xfunc_error_retval` = `EXIT_FAILURE` (1), and under musl's `getopt` the text is
   *unrecognized option*, not *invalid option* (sources, not run). `research/pgrep-ancestor-exclusion.md`
   claims neither a code nor a message — its BusyBox and 3.3.17 facts are labelled code-reading — so §9.6
   asserts past its evidence. Exit 1 is also what an accepted `-A` returns when nothing matches, so the exit
   code alone cannot discriminate. D35 supports Linux without naming a libc, so an Alpine developer's gate
   goes red for a reason that is not a defect. **Edit:** *"`pgrep` lacks `-A` when `pgrep -A -f <nonce>`
   exits non-zero **and writes to stderr** — a usage error under any `getopt`; a silent exit 1 is the
   accepted-and-nothing-found this half asserts, and exit 0 is the failure."* Drop the exit-2 and BusyBox
   clauses, or mark them unmeasured.

4. **[IMPROVEMENT] Item 6 and done-when 2 compare counts across a corpus that moves, so a difference
   cannot be attributed.** §M38 item 6: *"the build replaces its rule with the shipped one and reports any
   difference … A difference is a defect in one of them"*; done-when 2: *"agrees with the brief's counts,
   or the difference is explained"*; the research note: *"a re-run on another day moves the counts."* Once
   the prototype is replaced, the comparison is the new rule on today's corpus against the old rule on
   2026-10-11's, and "explained by new transcripts" is always available, so the gate cannot fail. **Edit:**
   keep the prototype's `judge` in the experiment under another name, judge every command with both in one
   pass, and report the commands on which they disagree — none, or each with its two verdicts — as the
   comparison; re-quote the aggregate counts from that same pass. Done-when 2 becomes *"the per-command
   comparison lists no disagreement, or each is decided in the code review"*.

5. **[IMPROVEMENT] The `-a`/`grep -v` exemption has four conceived edges §9.4 does not value.** (i) An
   intervening transformer — `pgrep -af X \| awk '{print $1}' \| grep -v grep`: the `grep` is *"a later
   simple command of its pipeline"*, but the shell's line reaching it no longer carries the command text, so
   its pid survives — exempt as written (the prototype's `_filtered` scans every later command), a miss.
   (ii) `grep -vx grep` (whole-line) and `grep -v -f pats` (the rule reads `pats` as the pattern, which the
   command text contains): exempt as written, misses. (iii) `pgrep -lf X \| grep -v grep` on `linux`: `-l`
   prints the process *name* (`bash`), not the command line, so the filter removes nothing — deny is the
   right value and worth a row, since `-l` is what §9.3's darwin sentence teaches. (iv) `rg -v`,
   `egrep -v`, `awk '!/pgrep/'`: deny, a stated false deny. None observed (0 by grep over the dump, each).
   **Edit:** either tighten §9.2 — *"the `grep` is the next simple command, or only `grep`, `head`, `tail`,
   `sort`, `uniq` stand between"*, which closes (i) at no cost — or state (i) and (ii) as misses; either
   way add rows: `pgrep -af month_monitor.py \| awk '{print $1}' \| grep -v grep` · `pgrep -af
   month_monitor.py \| grep -vx grep` · `pgrep -af month_monitor.py \| grep -v -f /tmp/pats` → silent
   (stated misses; the first → deny under the tightened wording); `pgrep -lf month_monitor.py \| grep -v
   grep` → deny (`-l` lists names); `pgrep -af month_monitor.py \| rg -v pgrep` → deny (stated false deny).

6. **[NITPICK] A `pgrep`/`pkill` in a data body that row 6 then runs is a miss nothing states.**
   `cat > /tmp/k.sh <<'EOF'` / `pkill -f month_monitor.py` / `EOF` / `bash /tmp/k.sh`: the calling shell's
   command line carries the body, the script's `pkill` kills it, and §9.1 reads scanned bodies only. None
   observed. Add the row → silent (stated miss: a data body is not scanned, §9.1) and a clause to §9.4's
   quoted-script bullet.

7. **[NITPICK] §9.2's *"the rule cannot tell that form from the ones where the filter is complete"*
   overstates it.** §3.1's grammar does distinguish a `$(` holding a pipeline from one holding a simple
   command and from a top-level pipeline; the decision is not to read the shape. Write "does not read", so
   a later reader is not told the exemption is impossible.

8. **[NITPICK] §7 count (a) calls the `PreToolUse:Monitor hook error` prefix "measured"**, citing
   `research/m38-selfmatch-replay.md`, whose `Monitor` section records that the nonce came back as the tool
   result — not the result's prefix. Record the literal prefix in the note or drop "measured" for it; count
   (a)'s grep would undercount silently if the prefix differs.

9. **[NITPICK] The patch proposal sits against `design/distribution.md` §3's own rationale.** The shape
   rule exists because *"those paths are written into harness configuration an upgrade must refresh and a
   patch bump says nothing needs refreshing"*; the brief's release note says to re-run `install` to refresh
   the matcher. "Stale rather than wrong" reads the letter; name the tension in that paragraph so the
   operator decides with it in view.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-11

Artifact re-read in full: `design/build-plan.md` §M38; `design/edit-guards.md` §1, §3 (heading and
first paragraph), §7 (the observed-command rule, counts (a) and (e)), §8 where §9 leans on it, §9
entire; D38 in `design/overview.md` §4 and `FINDINGS.md`; `research/m38-selfmatch-replay.md`,
`research/pgrep-ancestor-exclusion.md`, `experiments/m38_selfmatch_replay.py`; the regenerated
all-verdicts TSV (1,065 rows, 21 `not judged`; cited by shape only); and, because item 1 puts the new
rule inside `decide`, `zikaron/guard/main.py` and `decide`'s signature. No shell, so program behaviour
below is from source and labelled.

**Summary judgment.** Round 2's nine findings are resolved as the brief says, and I re-walked the 14
new `linux` rows by hand against `read_call`/`_verdict`: each gives the stated value. Two replay
claims I tested by grep hold — no option after a `pkill`/`pgrep` pattern (my two hits are quoted
multi-word patterns), and the 55 `pgrep -…x` rows are `pgrep -x <name>` without `-f`. One thing
remains that the documents leave to the builder and the build's own tests could not catch: the hook
returns before `decide` when the payload has no usable `cwd`, the new rule needs none, and the one
measured `Monitor` payload is quoted without one. Beyond that: the `grep` grammar the exemption
rests on is underspecified in three places, and five option rows in §9.5 pass under either reading
of the option they are there to pin.

### Findings

1. **[BLOCKER] A payload without a usable `cwd` silences the whole hook before §9 runs, nothing says
   §9 needs no `cwd`, and the measured `Monitor` payload is quoted without one.**
   `zikaron/guard/main.py` `_find_replace` (lines 74–78): `location = _location(payload, tmpdir)`,
   then `if … location is None: return None` — *before* `decide`. `_location` returns `None` unless
   `payload["cwd"]` is an absolute path. §M38 item 1 puts the self-match rule inside `decide`, so as
   the dispatch stands it inherits that gate. `research/m38-selfmatch-replay.md` §"`PreToolUse` on
   `Monitor`" quotes the hook's stdin as `{"hook_event_name": "PreToolUse", "tool_name": "Monitor",
   "tool_input": {…}}` — three top-level keys, no `cwd`. If that is the whole payload, every live
   `Monitor` call is §6's silence for both rules; the invariants' tests ("`Monitor` is judged by both
   rules") run on a synthetic payload that carries `cwd` and pass regardless; and done-when 3's live
   session tests `pkill -f` through `Bash` only. The Monitor probe itself proves deny *delivery*, not
   that the guard's own gate lets a Monitor payload through — its script denied every call
   unconditionally. If the quote merely elided the common fields, the cost of this finding is one
   clause. **Edit, three parts.** (i) In the research note, state from the logged stdin — no new run —
   whether the `Monitor` payload carried `cwd` (and `session_id`, `permission_mode`), and if the quote
   is complete, say so. (ii) In §9.1's first bullet: *"This rule reads `tool_name` and
   `tool_input.command` and nothing else of the payload; a payload with no usable `cwd` is still judged
   by it, where §3's rule is §6's silence."* — and in §M38 item 1, that `decide`'s `location` becomes
   optional (or the self-match judgement sits beside the `cwd` gate rather than behind it). This is a
   decision the documents currently leave to the builder, whatever the log says. (iii) Done-when 3
   gains *"and the same self-matching `pgrep -f` through `Monitor`, denied with this rule's message"*,
   which is the one check that would have caught the failure live. §9.5 row: `Monitor` · `pkill -f
   month_monitor.py`, *judged under a payload carrying no `cwd`* → deny (§8's payload rule is
   otherwise unchanged).

2. **[IMPROVEMENT] §9.2's `grep` grammar leaves three decisions to the builder.** The exemption's
   soundness is *"whenever that `grep`'s own pattern searches the command text"*, so which token is the
   pattern matters. (a) **`grep`'s argument-taking options** (`-A -B -C -m -d -D -f`, and `-e`, which is
   stated) are not listed; the prototype's `_read_grep` (lines 205–239) reads none of them, so in
   `grep -v -m 1 grep` the first operand is `1`. Because such an argument is always in the command
   text, the misread *always* exempts — a miss whenever the real pattern would not have filtered
   (`… | grep -v -m 1 '[z]zz'`), never a false deny. (b) **A `grep` pattern `re` cannot compile** — a
   POSIX class `[[:alpha:]]`, which Python's `re` rejects — is `except re.error: continue` in the
   prototype, i.e. exempts nothing and the call is denied; §9.2 says only what a `pgrep` pattern
   that fails to compile does. (c) **`-P`** is read as basic by the prototype, so `grep -vP
   'pgrep|grep'` becomes a literal `|` and does not exempt — a false deny with no stated value. None
   observed (0 by grep over the dump for `grep -v…` followed by `-A/-B/-C/-m/-d/-D/-f` with an
   argument), so §7 gives rows, not a rule move — but which token a `grep` option consumes is the
   unspecified half of a rule already stated, not a new rule. **Edit.** §9.2, after *"each
   `-e`/`--regexp`"*: *"`grep`'s `-A -B -C -m -d -D -f` consume the next token as `-e` does; `-P` is
   read as `-E`; a `grep` pattern `re` cannot compile exempts nothing."* Rows: `pgrep -af
   month_monitor.py \| grep -v -m 1 grep` → silent; `pgrep -af month_monitor.py \| grep -v -m 1
   '[z]zz'` → deny (the pattern does not search the text); `pgrep -af month_monitor.py \| grep -v
   '[[:alpha:]]grep'` → deny (does not compile, exempts nothing); `pgrep -af month_monitor.py \| grep
   -vP 'pgrep\|grep'` → silent. If the author prefers the prototype's reading for (a), the second row
   is silent (stated miss) and §9.4's exemption-edges bullet gains the clause.

3. **[IMPROVEMENT] Five §9.5 option rows pass under either reading of the option they pin.** A row
   that says *"(`-F` takes an argument)"* must come out differently if it did not; the `-F /tmp/m.pid`
   row does (the unconsumed `/tmp/m.pid` would match), but these do not, because the argument the
   option would fail to consume is itself in the command text, so the wrong reading denies too:
   `pgrep -f -- month_monitor.py` (an unskipped `--` is in the text); `pgrep --delimiter , -f
   month_monitor.py` (`,`); `pgrep -fu nathan month_monitor.py` (`nathan`); `pkill --signal TERM -f
   month_monitor.py` (`TERM`); `darwin` · `pgrep -c cls -af month_monitor.py` (`cls`). The
   invariants' property test will exercise the grammar anyway, but §8 makes the seed table *"the one
   place the rule table's rows are listed"*, and a seed row that passes for the wrong reason is what
   round 1 flagged in `grep -v $$`. **Edit.** Give each a bracketed-pattern twin whose value turns on
   the consumption: `pgrep -f -- '[m]onth_monitor.py'` · `pgrep --delimiter , -f
   '[m]onth_monitor.py'` · `pgrep -fu nathan '[m]onth_monitor.py'` · `pkill --signal TERM -f
   '[m]onth_monitor.py'` → silent (the option's argument is consumed; unconsumed, it would be the
   pattern and match); `darwin` · `pgrep -c cls -af '[m]onth_monitor.py'` → silent. The existing
   five can stay as plain deny rows without their parenthetical claims. (`pgrep -u nathan -f
   month_monitor.py` and `pgrep --delimiter=, -f month_monitor.py` already discriminate, in the deny
   direction.)

4. **[IMPROVEMENT] The message for a marker inside content on a §9-only deny is unspecified.** §9.2
   decides the *invalid*-marker case (§3.4's clause appended) but not the *marker-in-content* case,
   for which §3.4's second bullet gives the ordinary deny and §3.5 appends its placement clause. For
   `bash <<'EOF'` / `pkill -f month_monitor.py #ZIKARON-FORCE #Reason: a b` / `EOF`, the marker is
   content, §9 denies, and whether §9.3's message carries the placement clause is the builder's call.
   **Edit.** §9.2, order bullet: *"a marker only in a heredoc body or a quoted string gets §9.3's
   message with §3.5's placement clause, on §3.5's condition."* Rows: the command above → deny,
   §9.3's message with the placement clause; `echo 'x #ZIKARON-FORCE #Reason: a b'; pkill -f
   month_monitor.py` → the same.

5. **[IMPROVEMENT] The cost of compiling an agent-authored regular expression is not stated.** §9.2
   runs `re.search` with the call's own pattern — and §9.2's exemption with each `grep -v` pattern —
   over the whole command text, heredoc bodies included. Python's `re` backtracks, so a pattern such
   as `(.*)*x` over a multi-kilobyte command can run for seconds; §5's 10 s `timeout` then allows
   (§6). §1 lists what the guard reads and §9.4 lists what it misses, and neither names this: a
   slow pattern is a stall and then a miss. No replay pattern is of that shape, so §7 gives a stated
   gap, not a bound. **Edit.** §9.4, new bullet: *"A pattern whose search is slow in Python's `re`
   (`(.*)*x`) costs up to §5's timeout and then allows (§6); the same for a `grep -v` pattern read by
   the exemption. None in the replay."*

6. **[NITPICK] `-x` exempts a pattern that still matches the whole line.** `pgrep -xf
   '.*month_monitor.*'` is an exact match of a regex against the full command line, which the
   wrapper's line satisfies. One `-x -f` in the replay, silent and not of this shape; 55 `pgrep -x
   <name>` carry no `-f`. Row → silent (stated miss, §9.4), one clause in §9.4's exemption-edges or
   `-x` text.

7. **[NITPICK] Two rows for what the deny teaches and claims.** `darwin` · `pgrep -lf
   month_monitor.py` → silent — §9.3 sends a Mac agent to `-l`, and no row shows the fix is silent
   (the `linux` fixes `-A` and the bracket both have rows). And `Monitor` · `sed -i 's/a/b/' f` →
   deny, §3's message — §9.5 is the only table with a tool column, and the invariants' *"judged by
   both rules"* has no row for the second rule.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-11

Artifact re-read in full: `design/build-plan.md` §M38; `design/edit-guards.md` §1, §3 (heading and
first paragraph), §7 (the observed-command rule, counts (a) and (e)), §8 where §9 leans on it, §9
entire; D38 in `design/overview.md` §4 and `FINDINGS.md` (its D38 row and the in-progress block);
`research/m38-selfmatch-replay.md`, `research/pgrep-ancestor-exclusion.md`,
`experiments/m38_selfmatch_replay.py`; `zikaron/guard/main.py`, `position.py` and `grammar.py`'s
`Token` for the grammar the rule reuses; the regenerated dump (1,065 rows, cited by shape only). No
shell, so program behaviour below is from source and labelled.

**Summary judgment.** Round 3's seven findings are resolved as the brief says, and the rule set is
settled: I re-walked every `linux` row touched this round through `read_call`/`_read_grep`/`_verdict`
by hand and each gives the stated value — the `-m 1` pair discriminates on consumption, `grep -vE
'pgrep('` fails to compile and exempts nothing, `[[:alpha:]]grep` compiles to a class that matches
nothing in the text and so denies. The dump agrees with the note's aggregates — 343 `deny`, 65
exempt, 7 `Monitor` occurrences of which 5 deny, 1,065 rows — and every signalled occurrence the
prototype leaves silent belongs to a command whose other occurrence it denies (checked for each of
the eight), so 38 of 38 holds. The corpus has no `pkill` carrying a multi-letter option or signal,
no `pgrep -l…f`, no `xargs … pkill` and no `grep -v` with a long argument-taking option, so the
brief's "rests on §9.5's rows alone" is accurate. Nothing below moves a verdict or leaves a builder
deciding anything; one sentence in §9.4 is false about `darwin` and should be corrected before the
build — the correction is fully specified in finding 1 and needs no further round.

### Findings

1. **[IMPROVEMENT] §9.4's darwin bullet is false for the row it explains, and my own round-1
   nitpick is where the over-generalisation came from.** §9.4, last bullet: *"The exemption is
   withheld on `darwin` for want of a Mac transcript, not because the filter fails there"*; §9.5 row
   `darwin` · `pgrep -af month_monitor | grep -v grep` → deny *"(no exemption on `darwin`)"*. On
   darwin `-a` means *include ancestors* and changes nothing about the output, which is ids only;
   the full argument list comes from `-l` with `-f` (`research/pgrep-ancestor-exclusion.md` §2, §3,
   man page read twice). So that row's filter removes nothing, the shell's id is in the output,
   and the deny stands on the merits — it is not a withheld exemption. The form the exemption
   *would* be sound for on darwin is `pgrep -laf X | grep -v grep` — `-a` includes the shell and
   the `$(…)` subshell, `-l` prints their lines, both carry `grep` — and that is the one withheld
   for want of a transcript. Round 1's nitpick 12 named `-alf`; the sentence was applied to `-af`.
   No verdict moves; the sentence does, and it matters because §9.3 sends a Mac agent to `-l`, and
   the next thing it writes is `pgrep -laf … | grep -v grep`, which this bullet currently says is
   denied only for want of evidence while saying the `-af` form would have been fine.
   **Edit.** §9.4's bullet → *"`darwin`'s rows are read from its man page and source, not run: no
   transcript in the replay is from a Mac. §9.6's premise test is what checks them. **The exemption
   is `linux`-only.** On `darwin` `-a` prints ids, so `pgrep -af X | grep -v grep` removes nothing
   and its deny stands on the merits; with `-l` the filter would work (`pgrep -laf X | grep -v
   grep`), and that form is withheld for want of a Mac transcript — a stated false deny."* Row 1262's
   parenthetical → *"(`-a` prints ids only there; the filter removes nothing)"*. New row: `darwin` ·
   `pgrep -laf month_monitor | grep -v grep` → deny (stated false deny: the exemption is
   `linux`-only). §9.3's darwin sentence is correct and unchanged.

2. **[NITPICK] §9.2's `grep` option sentence says less than the prototype reads, and omits the
   long forms.** *"`-A -B -C -m -d -D` consume the next token"* — a glued argument (`-m1`, `-A2`)
   consumes nothing further, as `_read_grep_cluster` reads (`return (None if rest else letter)`),
   so write it as §9.1 does for `pgrep`: *"the rest of their cluster or, when last, the next
   token"*. The long forms with a separate argument — `--max-count 1`, `--context 2`,
   `--after-context`, `--before-context`, `--include`, `--exclude`, `--exclude-dir`, `--label`,
   `--devices`, `--directories`, `--binary-files` — are not listed, and the prototype's `_read_grep`
   reads an unknown `--option` as consuming nothing, so the argument becomes the pattern (`1`, in
   the text → exempts: a miss, never a false deny). None in the dump. Either add them beside the
   short forms or state the miss with a row: `pgrep -af month_monitor.py | grep -v --max-count 1
   '[z]zz'` → silent (stated miss), or deny if listed.

3. **[NITPICK] §9.6 does not say how `pgrep`'s exit code and stderr are read past the trailing
   `true`.** `bash -c '<call>; true'` exits 0 whatever `pgrep` did, and the `-A` discriminator
   turns on `pgrep`'s own non-zero exit *and* stderr. One clause — the call is run as
   `pgrep … 2>"$err"; echo "rc=$?"; true`, or the test reads stdout for ids and the captured
   stderr — closes it; otherwise the builder decides, which the brief's intent says it should not.

4. **[NITPICK] Rows for mechanics §9.1–§9.2 state without a discriminating row.**
   `pkill -f -int month_monitor.py` → deny (the signal *wherever it stands*: read as options, `t`
   would consume the pattern and the call would be silent — row 1223 pins only the signal-first
   order); `pgrep --list-full --full month_monitor | grep -v grep` · `pgrep -af month_monitor.py |
   grep -vi GREP` · `pgrep -af month_monitor.py | grep --invert-match --regexp=grep` → silent (the
   exemption's long forms and `-i`, which the invariants bullet names and the table does not);
   `python3 - <<'EOF'` / `subprocess.run(["pkill", "-f", "month_monitor.py"])` / `EOF` → silent
   (stated miss: a `pkill` inside an interpreter body stands at no command position though the
   calling shell carries its text — 0 in the dump by grep for `subprocess`/`os.system`/`Popen`
   beside `pkill`; one clause for §9.4's quoted-script bullet); `echo month_monitor.py | xargs -I{}
   pkill -f {}` → deny (parsed as stated: `{}` is a literal pattern and matches its own spelling —
   and here also a true self-match, since the input is in the text; row 1225's bare-`xargs` twin).

5. **[NITPICK] §M38's first paragraph quotes a floor as the count of the phenomenon.** *"301 of
   33,784 commands do so"* — 301 is what the rule denies; `research/m38-selfmatch-replay.md` says
   it is a floor, 21 more self-matching only inside a double-quoted `$(…)`. *"the rule catches 301
   of 33,784 doing so"* keeps the brief from being read as the incidence. D38's rationale already
   says *"it denies 301"*.

VERDICT: APPROVED
