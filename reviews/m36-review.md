# M36 implementation — review

Artifact: the M36 change against `design/build-plan.md` §"M36 — An upgrade the installer refused,
a stale install nothing reported, and the release" — `zikaron/install/ownership.py` (new),
`zikaron/install/{writer,targets,entries}.py`, `zikaron/doctor/{checks,main}.py`,
`zikaron/core/knowledge/counters.py`, `zikaron/mcp/primary.py`, the tests named in the brief,
`pyproject.toml`, and the prose in `README.md`, `FINDINGS.md`, `design/{architecture,harness,
distribution,knowledge-index}.md`.

## Round 1 — 2026-09-30

**Summary judgment.** The code does what the brief specifies and the design now states. Ownership
is one predicate in one module, both targets import it, kiro refuses a server entry only on
`MCP_OWNERSHIP_FIELDS` and a hook entry only on its unquoted command, one recogniser serves the
guard, the notes and the array merge, and entries on foreign triggers are neither compared nor
touched — I walked each of those paths in `writer.py` and `ownership.py` against the brief's three
bullets and found no divergence. `check_always_load` sits where the brief puts it, fails only on
the absent key, produces no row on every no-answer shape the brief enumerates, and `doctor`'s
import closure stays stdlib-plus-package as `cli/main.py` promises (`install.targets` pulls in
nothing third-party). The count guard is assembled from fragments, collapses line breaks, is
bounded to *six*–*twelve*, and no spelled count survives in its three roots. `architecture.md`,
`harness.md`, `distribution.md` and `README.md` state the ownership rule, the merge, the `doctor`
row and the version facts consistently with the code, and nothing in `zikaron/`, `design/` or
`README.md` still says kiro compares whole. What remains is working-memory prose that describes
the pre-build tree as current, one README sentence that promises more of `doctor` than the
operator allowed it to do, and a handful of nits.

### Findings

1. **[IMPROVEMENT] `FINDINGS.md`'s M36 block still carries the pre-build item list as if it were
   open, and its remedies name code that no longer exists.** Location: `FINDINGS.md:94–123`, and
   `:231–237`. Item 1's *Where* names `_differing_zikaron_hooks` (gone) and its *Fix* says to use
   "`targets.py` `_ownership`, `_differing_ownership_fields`" (both moved to `ownership.py` and
   renamed without the underscore); item 2 states *"spelled out in five places"* — the very count
   this milestone removed — and item 3 proposes the `doctor` check as future work; the block's own
   "Done when" (*"all three are in … `README.md`'s troubleshooting row points at the `doctor`
   check"*) is the superseded one, beside line 84's note that the brief supersedes it. Line 85–90's
   plan reads *"(b) … built …; now (d) below; (c) the release: `pyproject.toml` to `0.3.0` …"*, so
   (c) is listed as pending after (d) has begun, while `pyproject.toml` already says `0.3.0` and
   `README.md` is current. And §"Owed work" (`:231–237`) still proposes the `reaped` fix *"as its
   own chore commit, now that M35 has landed"* — it rode in M36 by operator decision. A fresh
   session resuming from this file would look for `_ownership` in `targets.py` and re-open the
   fixture as owed. *Fix:* delete items 1–3 and their "Done when" (the brief holds them);
   rewrite the plan as *(a) brief, (b) items 1–4, (c) the release number, `README.md` and the
   drafted release notes — done; (d) implementation review into `reviews/m36-review.md` — in
   progress; (e) `./check.sh` green, PR when asked*; delete the Owed-work fixture entry. Nothing
   here needs the code's names restated — `design/architecture.md` §"The install contract" points at
   `ownership.py`.

2. **[IMPROVEMENT] `README.md:248` promises that `doctor` says whether `.mcp.json` "is current",
   which is more than the row judges.** Location: `README.md:248`, *"`zikaron doctor` afterwards
   says whether a Claude Code project's `.mcp.json` is current."* The operator narrowed the check
   to exactly `alwaysLoad` (`build-plan.md:5536–5538`; `distribution.md:190–191`: *"nothing else
   about the file is judged"*), so the next key a release adds to the entry leaves `doctor` green on
   a stale file while this sentence tells the user it would have said so. The same paragraph's
   `README.md:463–465` states it correctly. *Fix:* *"`zikaron doctor` afterwards says whether a
   Claude Code project's Zikaron entries carry `alwaysLoad` — the one thing about `.mcp.json` it
   judges."*

3. **[NITPICK] The passing detail claims a non-object entry carries the key.** Location:
   `zikaron/doctor/checks.py:239`, `f"{', '.join(ours)} carry `{ALWAYS_LOAD_KEY}`"`. `ours` is
   every present Zikaron key, while `stale` filters to objects, so `"zikaron": null` — the shape
   `test_a_null_entry_passes_rather_than_raising` pins — prints *"zikaron carry `alwaysLoad`"*, which
   is false (and "carry" with one name is off). *Fix:* build the detail from the object entries only,
   e.g. `carrying = [name for name in ours if isinstance(servers[name], dict)]` and
   `f"`{ALWAYS_LOAD_KEY}` present on {', '.join(carrying)}"`, or when `carrying` is empty
   *"nothing to judge: {names} is not an object"*; and one assertion in the null-entry test that the
   detail does not name the key as present.

4. **[NITPICK] The remedy test does not pin the `false` clause the brief specifies.** Location:
   `tests/test_doctor.py:435–446` asserts `"--harness claude-code"` and `"`alwaysLoad` by hand"`;
   the brief (`build-plan.md:5550–5551`) requires *"`false` to keep deferral"* in the remedy, and
   `checks.py:246` carries it. One line: `assert "`false`" in finding.remedy`.

5. **[NITPICK] A test docstring names a function that moved.** Location:
   `tests/test_install_targets.py:712`, *"`_ownership` projects a non-object to `{}`"* — it is now
   `ownership.ownership`, and `targets.py` has no `_ownership`. Replace the name.

6. **[NITPICK] An unhashable `name` or `trigger` in a kiro array entry tracebacks rather than
   refuses.** Location: `zikaron/install/writer.py:646–649`, `if name in by_name` /
   `elif trigger in by_trigger`. A user's entry carrying `"name": ["x"]` raises `TypeError` from
   the dict lookup — the outcome `test_a_hook_entry_that_is_not_an_object_is_left_alone_rather_than_crashing`
   exists to rule out one shape over. Probably inherited from the code this replaced, and exotic;
   `isinstance(name, str) and name in by_name` (and the same for `trigger`) closes it.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-30

**Summary judgment.** All six round-1 findings are applied as described, and I re-walked the code
rather than the summary: `FINDINGS.md`'s M36 block now describes the tree that exists and the
`reaped` entry is gone from §"Owed work"; `README.md:248–249` claims exactly what `doctor` judges;
`checks.py:239–245` builds the passing detail from object entries and the null-entry test asserts
`"present" not in finding.detail`; the remedy test pins ``"`false` keeps deferral"``;
`test_install_targets.py:712` names `ownership.ownership`; `writer.py:647–651` guards both lookups
with `isinstance(..., str)`, and the new test at `:1127` puts an unhashable `name` *and* `trigger`
through the array merge. Beyond the applied items I checked what round 1 did not: the count guard's
pattern against each phrasing the brief lists and against the two ordinary-English forms that must
stay green; every live document for a spelled count of reasons outside the guard's three roots
(none — `build-plan.md` §M36 quotes the removed phrasings as history, which is where the brief puts
them); that no test pins a `.dev` suffix on `[project] version`; that `lifecycle._spawn_detached`
really does reap on a daemon thread (`lifecycle.py:295`), so the fixture's poll ends when the brief
says it does; and that the old refusal strings (*"not an entry this install writes"*, *"or an entry
you edited"*, *"previous install from a different interpreter"*) survive nowhere in `zikaron/`,
`tests/`, `README.md` or the three design files. The code is ready. Two prose findings remain, both
small, one of them against the brief's own normative pointer.

### Findings

1. **[IMPROVEMENT] The ownership rule is stated in `harness.md`, but under the wrong heading — the
   one the brief and `CLAUDE.md` point at does not contain it.** `build-plan.md:5473` names
   `design/harness.md` §"The installer's two targets" as normative for item 1, and `CLAUDE.md`'s
   table row for `harness.md` lists that section as covering *"the three flags and what each
   refuses"*. The paragraph that actually states the rule — *"What refuses an entry is ownership
   rather than equality, on both harnesses …"* — is at `harness.md:442–447`, inside §"MCP tools may
   arrive deferred" (headings at `:357` and `:449` bracket it). §"The installer's two targets"
   (`:563–604`) says nothing about ownership, and its one sentence on refusal, `:602–603` *"a
   clone-mate's install refuses on the differing entry rather than merging over it"*, reads as the
   whole-entry comparison this milestone removed — true for a clone-mate only because their
   `command` differs, and false the day a clone-mate's entry differs in `env` alone, which is now
   merged and reported. A reader following the brief's pointer reads 140 lines and does not find the
   predicate. *Fix:* move `:442–447` into §"The installer's two targets", directly after the
   *"Values still come from the seam."* paragraph (`:574–577`), where *what refuses* belongs beside
   *what each flag refuses*; leave a one-line pointer at `:442` (*"an install predating the key is an
   upgrade, not a conflict — §"The installer's two targets""*), since that section's point is that
   `alwaysLoad` arriving does not refuse; and change `:602–603` to *"refuses on the differing
   `command` rather than merging over it"*. Prose only; `./check.sh`'s pointer guard is the only
   test this touches.

2. **[IMPROVEMENT] `FINDINGS.md` states the release facts twice, three lines apart.** `:80–86` and
   `:91–94` both say the operator tags the merge `v0.3.0`, both say the release notes are published
   from the PR, and both end in the same bold sentence, **"The first commit after the tag sets
   `0.3.1.dev0`."** The file's own header says a fact is *"stated once"*, and this is the file that
   loads every session. The only thing `:91–94` adds is why there is no `0.2.0`, with its pointer.
   *Fix:* delete `:91–94` and append one clause to `:86`: *"… `0.3.1.dev0`. `0.1.0` shipped schema 1
   and `0.3.0` ships schema 3, each step a minor bump, so there is no `0.2.0`
   (`design/distribution.md` §3)."*

3. **[NITPICK] `FINDINGS.md:83–84` says the release notes are drafted and does not say where.**
   *"the release notes drafted for the PR description — done"* — if the draft lives only in the
   session, the file's own §"Facts that constrain" (`:159–161`) records what a compaction does to
   that. One phrase: name the scratchpad path, or say they are re-derived from `git log v0.1.0..`
   at PR time so a fresh session knows not to look for a file.

4. **[NITPICK] The `doctor` remedy prints an unquoted project path inside a command the user is
   meant to paste.** `zikaron/doctor/checks.py:251`, ``f"`zikaron install --harness claude-code
   --project {project}` there"``. A project directory with a space — the case
   `entries.hook_command_string` measured breaking a hook — yields a command that fails on paste.
   `shlex.quote(str(project))` (one import, one call); the other remedies name paths rather than
   command lines, so this is the only site.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-30

**Summary judgment.** The four round-2 items are applied as described, and I checked each against the
file rather than the summary: the ownership paragraph now sits at `harness.md:574–580` inside
§"The installer's two targets" (heading `:558`), names `zikaron/install/ownership.py`, and `:442`
keeps a one-line pointer; `:605–606` says a clone-mate's install *"refuses on the differing
`command`"*; `FINDINGS.md:80–90` states the release once, with the no-`0.2.0` reason and its pointer,
and says the notes are not in the tree and how a fresh session re-derives them; `checks.py:252`
quotes the project path and `test_doctor.py:449–458` pins it. Beyond that I re-walked what the
brief's five items require against the tree as it now stands — `refuse_conflicting` and
`merged_server` on both callers, `_recognised_hooks` in both formats including the by-name and
foreign-trigger branches, `run_all`'s order against `distribution.md:184–205`, the count guard's
pattern and line-join against every phrasing the brief names, the `reaped` poll, `pyproject.toml`
at `0.3.0`, and the `--mode` default (required, `mcp/main.py:24`, so an entry with no `args` really
is not this install's). The code is correct and the prose agrees with it. One thing the brief
specifies and the code does not do remains, on the exact path this milestone was written for; the
rest is nits.

### Findings

1. **[IMPROVEMENT] The upgrade that *adds* `alwaysLoad` — the path `doctor` sends every `0.1.0`
   user down — merges the key without naming it.** `zikaron/install/ownership.py:111–119`:
   `kept` is fields of theirs not in ours, `overwritten` is fields in *both* whose values differ; a
   field of ours absent from theirs is in neither, so the note list is empty and the install says
   only that `.mcp.json` was merged. The brief's item 1 specifies *"a value this install writes is
   set and named"* (`build-plan.md:5497`), `README.md:325–327` promises *"a value this install
   writes — `alwaysLoad` in particular — is reset to this install's and named too"*, and
   `architecture.md:2406–2407` states the principle, *"not refusing does not mean not saying"*.
   `test_install_targets.py:675–696` — the test whose docstring calls this *"the path a real upgrade
   takes"* — asserts the value and nothing about the output, which is how the gap stayed green.
   *Fix:* in `merged_server`, on the non-force path, `added = sorted(field for field in ours if
   field not in existing)` and, when non-empty, `notes.append(f"`{name}`: {fields} added — an
   earlier install wrote the entry without {it}.")` beside the `overwritten` note (the `--force`
   path replaces whole and already says so); one `capsys` assertion in
   `test_an_install_predating_always_load_is_upgraded_rather_than_refused` that `ALWAYS_LOAD_KEY`
   appears in the output, seen red first. If the operator would rather the add stay silent, then
   `README.md:326` must instead read *"is set — and named where it replaced a value of yours"*, so
   the sentence stops promising what the modal upgrade does not print.

2. **[NITPICK] The server refusal names the field and not the values, where the hook refusal
   prints both commands.** `ownership.py:49` returns `"args"`/`"command"`, so a refusal reads
   *"zikaron (args). That usually means another Zikaron install owns them, whose paths may point at
   a venv…"* — and for `(args)` the tail is wrong on the realistic case, `--agent` pointed at
   `zikaron-consolidator.json` itself or a consolidator-mode entry copied under the primary key,
   where the path is identical. `writer.py:603–604` already does the better thing for hooks
   (*"command is …, this install writes …"*). Brief accepts the shared tail, so this is optional:
   return `f"{name} is {theirs.get(name)!r}, this install writes {mine.get(name)!r}"` and loosen
   the two `match=` patterns at `test_install_writer.py:1175` and `:1232` from `\(args\)` /
   `\(command\)` to the bare field name.

3. **[NITPICK] The guard's digit alternative is unbounded while its word alternative is bounded.**
   `tests/test_knowledge_counters.py:259–263`: `_NUMBER` is *six*–*twelve* **or `\d+`**, so
   *"3 reasons"* reddens the guard while *"three reasons"* is deliberately green
   (`:321–322`). Bound the digits to the same neighbourhood — `r"|(?:[6-9]|1[0-2])"` in place of
   `r"|\d+"` — and add *"3 reasons"* to the green sentence.

4. **[NITPICK] `_LINE_BREAK` joins a wrap across a comment or prose line, not across adjacent
   Python string literals.** `:282` handles `\n` + indent + `#:`/`>`; a count split as
   `"… the eight "` / `"file reasons …"` — the form `ownership.ANOTHER_INSTALL` and the MCP tool
   descriptions outside docstrings are written in — would pass. Nothing is missed today (every site
   the brief names is a docstring or `#:` comment), so this is about the next one. One-line widening:
   `re.compile(r'"?\s*\n\s*(?:#:?|>)?\s*"?')`, and a sixth parametrised sentence built from
   fragments the way the others are, with a closing quote, newline, indent and opening quote between
   the number and the noun.

5. **[NITPICK] The brief promises a before-and-after measurement and carries only the before.**
   `build-plan.md:5606–5607`: *"**Measured**: the file's wall time before and after, from
   `--durations` — six teardowns at 10.02 s each and 76.5 s for the file, before."* The after
   figure is in no file (grep for `76.5`/`10.02 s` finds only that line). Append it to that sentence
   from the gate's `--durations` when `./check.sh` runs after this round, or say the commit message
   carries it.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-30

**Summary judgment.** The five round-3 items are applied as described, and I checked each against
the file: `ownership.py:120–133` builds `added` from the non-ownership fields of ours absent from
the entry and names it on both paths, `overwritten` and `added` both exclude `MCP_OWNERSHIP_FIELDS`
(so `test_install_writer.py:1178–1195`'s takeover prints no `args` note), `differing_ownership_fields`
prints both values per field and `:1175`/`:1233` match on them, `_NUMBER` is *six*–*twelve* or
`[6-9]|1[0-2]` with *"3 reasons; 16 reasons"* in the green sentence, `_LINE_BREAK` swallows a
closing-quote/newline/indent/opening-quote run and the sixth parametrised sentence exercises it, and
`build-plan.md:5607–5608` carries 15.8 s. Beyond that I looked where earlier rounds had not: the
`--force` help string and the umbrella's `doctor` line (no count, no stale claim), the archive's
M36 mention (a pointer, not a second record), `tests/test_distribution.py` (nothing pins a version),
the object-format refusal of another interpreter's hook (`test_install_writer.py:196–216`), and every
phrasing of the whole-entry comparison across `zikaron/`, `tests/`, `design/`, `README.md`,
`CLAUDE.md`, `FINDINGS.md` and both crew directories — it survives only in the brief's account of
what was and in one test docstring's counterfactual, both correct. I also walked the array-format
recogniser against an old install whose hook path carries a space and was written unquoted: `_entry_command`
returns the multi-word string verbatim, which equals `str(commands.hook)`, so it is owned and
rewritten with quoting rather than refused. The code is correct, the prose agrees with it, and
`FINDINGS.md:80–90` describes the tree that exists. What remains is three one-word nits. The brief's
own done-when item 4 — `./check.sh` green — is the researcher's stated next step and is not something
this review can substitute for.

### Findings

1. **[NITPICK] The brief still says the guard fails on "a digit string"; the guard now bounds digits
   to the same neighbourhood as the words.** `design/build-plan.md:5581`: *"a number word from
   *six* to *twelve* or a digit string"*. After round 3's item 3, `tests/test_knowledge_counters.py:262`
   is `[6-9]|1[0-2]` and `:325` pins *"3 reasons"* and *"16 reasons"* green, so the normative
   sentence now specifies a stricter guard than the one that exists. One clause: *"or a digit in the
   same range"*.

2. **[NITPICK] `_LINE_BREAK` joins a wrap across adjacent plain string literals but not across a
   prefixed one.** `tests/test_knowledge_counters.py:282`, `r'"?\s*\n\s*(?:#:?|>)?\s*"?'` — a
   continuation line beginning `f"` leaves the `f` in place, so *"the eight "* / `f"file reasons"`
   reads as *"eight f"file reasons"* and passes. That form is live in this tree: `targets.py:97–108`
   and `:122–132` build their note constants from `f"`-prefixed fragments. Nothing is missed today;
   this is the same "next one" class as round 3's item 4, one token wider:
   `r'"?\s*\n\s*(?:#:?|>)?\s*(?:[rfbRFB]{0,2}")?'`, and a seventh parametrised sentence with an
   `f"` on the continuation.

3. **[NITPICK] Two sentences describing the per-key merge predate the `added` note and now
   under-report it.** `zikaron/install/targets.py:465–467`, *"`ownership.merged_server` reports both
   what it kept and what it overwrote"*, and `design/architecture.md:2407–2408`, *"a user's own key
   on Zikaron's entry survives and is reported alongside anything overwritten"*. Both are true and
   both omit the case the milestone was written for — the key the entry lacked. `README.md:325–327`
   already says *"whether it was missing or different"*; match it: *"what it kept, added and
   overwrote"* in the docstring, and *"alongside anything set — added or overwritten"* in the
   contract.

VERDICT: APPROVED
