# Review — M21: Discovery, filtering, and change detection

Artifacts: `zikaron/core/knowledge/{counters,text,git,walk,candidates,changes,files,pending,lock,scan}.py`,
`zikaron/knowledge/scope.py`, `zikaron/knowledge/indexer/main.py`, the changed modules listed in the
brief, `tests/test_knowledge_*.py`, `design/build-plan.md` §M21, the M21 amendments to
`design/knowledge-index.md`, and `research/m21-scan-throughput.md`.

## Round 1 — 2026-09-15

**Summary judgment.** This is strong work: the module boundaries match the design's own seams (the
five git invocations in one module, candidacy-versus-filtering split into `candidates.py`, the two
phases in `scan.py`), the measured traps from M19's spikes are all implemented on the correct side
(`check-ignore` exits stated over the complement, `--no-index` not passed, `-z` on every call,
`text=auto` admitting, the rename pair consumed explicitly), the test suite reaches every skip
reason and every repository shape the brief names, and the throughput note closes §16 items 9 and
11 with its own threats stated. One correctness defect blocks it: `git status --porcelain` reports
paths relative to the **repository root**, the walk's join key is relative to the **corpus root**,
and nothing reconciles the two — so for a corpus root that is a subdirectory of a repository (a
vendored dependency, a `docs/` tree: uses §8.6 endorses by name), an uncommitted edit to a tracked
file is silently cleared as unchanged forever. That is precisely the "confidently stale, and
silent" class §5.2 exists to rule out, and no test covers the configuration.

### Findings

1. **[BLOCKER] `changed_paths` and the walk disagree about what a path is relative to, and the
   fast path silently skips uncommitted edits whenever the corpus root is a subdirectory of its
   repository.** `zikaron/core/knowledge/git.py::changed_paths` runs `git status --porcelain -z
   -uall` with `cwd=root` and returns the reported paths verbatim. Porcelain (v1) output is always
   relative to the *repository root*, regardless of cwd — `status.relativePaths` is a
   human-format-only setting. Every other invocation in the module is cwd-consistent (`ls-files`
   restricts to and reports relative to cwd; `check-ignore`/`check-attr` interpret stdin paths
   against cwd and echo them back), so `status` is the one call whose keys do not join.
   Failure chain, traced in code: KB root `repo/docs`, `git_mode=tracked`, `docs/guide.md`
   committed and indexed (stored `git_blob_hash` = index blob H). User edits the file without
   staging. Next scan: `ls-files` still lists H (the index is unchanged), `status` reports the
   change as `docs/guide.md` while the candidate path is `guide.md`, so
   `files.unchanged_by_git`'s third clause (`candidate_path in reported_changed`) never fires —
   the file is cleared as unchanged and the edit is never indexed, on every scan, until the edit
   is committed. Nothing raises, nothing counts, and (come M22) a same-size edit is invisible to
   §7.5's stat check too. This configuration is endorsed: §8.6 names "a vendored dependency" — a
   tree inside a work tree — as a legitimate root, and `rev-parse --is-inside-work-tree` at such a
   root answers true, so `tracked` (the default) is the effective mode.
   Neither the design (§5.2's "Parsing `git status` is a correctness surface" list has `-z`,
   `-uall`, both columns, and the rename pair — but not path relativity), the code, the git-shapes
   probe (which measured cwd-relativity for `check-ignore`/`check-attr` *inputs* only, at repo
   root), nor any test (every fixture in `tests/test_knowledge_scan_git.py` and
   `tests/test_knowledge_git.py` uses the repo root as the corpus root) touches it.
   **Suggested fix:** in `changed_paths`, obtain the corpus root's prefix inside the same
   degradation rule — `git rev-parse --show-prefix` with `cwd=root` (empty output at the repo
   root) — then in `_parse_status` keep only records under the prefix and strip it, the rename's
   bare old-path field included. Classify a `show-prefix` failure as `GitUnavailableError` (it is
   enumeration-affecting: without it the status guard cannot be applied). Update the module
   docstring's "five invocations" count, §5.2's exhaustive invocation list, and §5.2's status
   bullet list to state the relativity fact alongside `-z` and `-uall`. **Add the failing test
   first:** repo with a committed file under `docs/`, KB rooted at `docs/` with `tracked`, build,
   edit without committing, rebuild, assert the row's `content_hash` changed — this fails against
   the current code and pins the fix the way the suite's other measured-trap tests do.

2. **[IMPROVEMENT] One degraded scan erases every stored `git_blob_hash`, so a single transient
   git failure costs a full read of the whole corpus on the *next* scan as well.**
   `zikaron/core/knowledge/changes.py::Comparison.keep` records a refresh whenever
   `listed != row.git_blob_hash`; under effective `off` (the degradation path — whose common cause
   the code itself names as dubious-ownership refusals in containers) `answers.listed` is empty,
   so every unchanged, previously-tracked file gets `blob_hash_refreshes[path] = None` and the
   fast-path state is nulled. The next healthy scan can then clear nothing and reads every file
   once to rebuild it. This conflates "git was not asked" with "git says untracked": the `None`
   refresh is needed for the became-untracked case under `all` (where git *answered*), but under
   effective `off` no observation was made and retaining the last-known hash is safe — a stale
   stored hash can only fail the equality test and route to read-and-hash, never wrongly clear
   (same content ⇒ same blob hash; changed content ⇒ reindex path writes the row afresh).
   **Suggested fix:** in `changes.compare`, record blob-hash refreshes only when
   `answers.effective is not GitMode.OFF` (one guard around the `keep` bookkeeping, or a flag on
   `Comparison`), with a comment stating the conflation this avoids; add a test that a scan under
   a monkeypatched `list_files` failure leaves a previously stored `git_blob_hash` intact.

3. **[IMPROVEMENT] The second write of `last_scan_git_mode_effective` — the half the §5.2
   amendment calls "the one that matters" — is not pinned by any test that can fail.** The two
   tests that read the persisted key (`tests/test_knowledge_scan.py:126`,
   `tests/test_knowledge_scan_git.py:230`) both cover corpora where the begin-time probe already
   wrote the final value (`off` at `_begin`, `off` again at `_close_walk_phase`), and the one test
   that exercises a walk-*discovered* degradation
   (`test_a_listing_that_does_not_answer_degrades_the_whole_scan`) asserts only
   `refreshed.result.git_mode_effective` and never reads `meta`. Deleting
   `LAST_SCAN_GIT_MODE_EFFECTIVE_KEY` from `_close_walk_phase`'s write leaves the suite green —
   the guard-that-proves-nothing class this project's rubric names. **Suggested fix:** in that
   test, also open the KB and assert the persisted key is `"off"`; since the probe wrote
   `"tracked"` at `_begin` (the repo is real and `rev-parse` succeeds), only the closing rewrite
   can satisfy the assertion. Confirm by the usual mutation: remove the key from the closing
   transaction and watch the test fail.

4. **[IMPROVEMENT] `design/build-plan.md` §M21 names "M24" four times for work that §M23 owns.**
   Lines ~1596–1602: "which belongs here rather than in M24", "Cross-host reporting and
   `--force-unlock` stay in M24, where the state machinery they report through exists", "invoked
   synchronously here, detached in M24", "M24 adds spawning and progress". §M23's own heading and
   body ("The detached indexer, progress, and the repair paths"; "Cross-host lock reporting and
   `--force-unlock` with its same-host-live refusal"; normative "§9's `--force-unlock`") carry all
   of it, and §M24's fence says `--force-unlock` *stays CLI-only* — consistent with M23 having
   built it. This is the corpus's own enumeration-drift class, in the plan document, and it has
   already propagated once: the review brief for this round repeats "detaching it is M24's".
   **Suggested fix:** change the four references in §M21 to M23, then grep the corpus for other
   claims about which milestone owns detach/`--force-unlock` (not the phrase "M24").

5. **[IMPROVEMENT] `_record_skip`'s "only when" claim is contradicted by a reachable path, and
   the same edge grazes two neighbouring statements.** `zikaron/core/knowledge/scan.py::
   _record_skip` says the was-indexed case "reaches here **only** when that earlier read *failed*
   and this one succeeded — a file whose permissions moved between the two phases." A second route
   exists: a previously indexed file whose walk-phase read succeeded (text, hash changed → into
   `pending` with `was_indexed=True`) and whose bytes were then replaced with binary before the
   index-phase read — that read sniffs `NotText` and lands in the same branch. The scan module
   docstring's and §5.5's "a file it reads for the first time this scan" carry the same
   over-precision (for this route the index-phase read is the second read of the scan).
   **Suggested fix:** reword to name both routes — "only when the walk phase could not settle it:
   its read failed there, or the file changed after that read" — in `_record_skip`, the scan.py
   module docstring, and §5.5's matching sentence, and grep for other statements of the
   which-phase-discovers-it claim rather than the phrasing.

6. **[NITPICK] §M21's normative list omits §6.3.** `design/build-plan.md:1589` reads "§6.2, §6.4"
   while the milestone amended §6.3 (`files_seen` written during the walk) and
   `scan.py::_walk_tree` implements exactly its rule. Add "§6.3" to the list so the brief's
   normative set matches what the milestone actually built against (the review brief for this
   round already lists it; the plan document does not).

7. **[NITPICK] `remove`'s lock check is check-then-act across two databases, and the docstring
   presents refusal as airtight.** `lifecycle.remove` reads `lock_held` via `_observe`, then
   deletes the registry row and unlinks; an indexer acquiring the lock in that window has its
   database unlinked underneath it (bounded harm — the racing build's work lands on an unlinked
   inode and evaporates, which is what `remove` was asked for — and unfixable in one transaction,
   since the lock lives in the KB file and the row in `memory.db`). One sentence in the docstring
   naming the window and why it is accepted would keep the "refuses while the lock is held" claim
   honest.

Everything else examined held up under attack: the walk order and filter ladder match §4.1
step-for-step including the reported-reason order; the `.gitattributes` predicate is the measured
one and `text=auto` admits; the deny-list is endings-based with the compound entries handled; the
NUL-record parser keeps interior empties and drops exactly one terminator; the skip rule cannot
admit NULL = NULL; deletions are one-transaction-per-path with the pending row; `pending` is
replaced wholesale inside the walk-close transaction and swept by nothing; the lock's
same-host-only reclaim, unreadable-pid refusal, and unconditional release are all tested; the
two-racing-scans window is closed by SQLite snapshot semantics under the explicit `BEGIN`; the
counters' corpus-versus-workload split is implemented and asserted; the crash/resume and
kill-a-real-process tests exist; and the throughput note takes all four numbers the brief demands
and withdraws its own idle-machine claim with the direction of the contamination stated.

**Verdict rationale:** finding 1 is a silent-staleness defect in a supported, endorsed
configuration, in the exact class the design's own §5.2 calls unacceptable, with no covering test.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-15

**Summary judgment.** All seven round-1 findings are genuinely fixed, and the prefix reconciliation
itself held up under every mode and shape I could attack it with (detail in the closing paragraph).
The blocker this round is not a cascade from those fixes but from the mid-round revision of the
throughput note: `design/knowledge-index.md` §6.1 and FINDINGS.md both assert measured bounds —
"at most 2.6 s", "at most 0.15 s" — that the cited note's own table refutes (2.903 s, 0.253 s), and
the note's §1 prose contradicts its table three lines above it. That is the "false in two files at
once" class this corpus documents from M19, one of the files being the always-loaded one. Two
genuine cascades from round 1's fixes were also found, both in the requested class: an enumeration
the reworded §5.5 sentence still narrows too far, and a test whose fixture cannot fail under the
mutation its own name promises to catch.

### Findings

1. **[BLOCKER] §6.1 and FINDINGS.md state "at most" bounds that the throughput note's own table
   exceeds, and the note's prose contradicts its table.** `design/knowledge-index.md` §6.1
   (~lines 967–970): a full build "costs **at most 2.6 s over 2,034 files and 11.9 MB**, and **at
   most 0.15 s** to rebuild when nothing has changed." The table in
   `research/m21-scan-throughput.md` §1 that this cites: cold builds 2.553 / 2.554 / **2.903 s**
   (the `all` row), rebuilds 0.231 / 0.147 / **0.253 s** — so both "at most" claims are refuted by
   two of three modes (rebuild) and one of three (cold) in the evidence they cite. FINDINGS.md
   (~lines 674–676) repeats both bounds verbatim ("a cold build of **at most 2.6 s** … a rebuild of
   **at most 0.15 s**"), so the false claim already sits in the always-loaded file. And the note's
   own §1 prose (~line 43, "its whole cold build is **2.6 s**") contradicts the 2.903 s row three
   lines above it; the "~9 s … under 7% of the whole" derivation inherits it (from 2.903 the scaled
   figure is ~9.8 s, which is ~7.3% of the whole — the "under 10% of the embed component" half
   survives). The 2.6/0.15 figures are the *tracked*-mode column presented as corpus-wide maxima,
   with nothing naming the mode. **Suggested fix:** restate all three places from the worst mode
   ("at most ~2.9 s cold, at most ~0.26 s to rebuild" — or name `tracked` explicitly everywhere the
   smaller numbers are kept), recompute the note's scaled comparison from the same number, and then
   grep the corpus for the *claim* (the 2.6 and 0.15 values and any "at most" attached to a build
   time), not the phrasing — FINDINGS is proof it has propagated once already. None of this
   threatens §6.1's argument, which survives at 2.9 s exactly as well as at 2.6 s; what does not
   survive is a normative document quoting a bound its own evidence file exceeds.

2. **[IMPROVEMENT] The disposal enumeration misses the index-phase size-cap refusal in five
   places, while the code implements it and one test exercises it.** The reachable route:
   a pending file grows past `max_file_bytes` after the walk's stat (never-indexed) or after the
   walk's noticing read (previously indexed), so `_dispose`'s `read_bounded` returns
   `OVER_SIZE_CAP` and `_record_skip` runs — a recorded **size** skip, plus a deletion when a row
   exists. `tests/test_knowledge_scan.py:305` covers the never-indexed half and its docstring
   states the disposal plainly. Against that, five texts enumerate three outcomes that are all
   text-shaped: `scan.py` module docstring ("exactly the three outcomes of reading one pending
   file — it is text, it is not and was indexed, it is not and never was");
   `design/knowledge-index.md` §7.5 (~line 1178, "Every disposal is one of three: a reindex, a
   deletion, or a recorded **text-detection** skip") — the never-indexed over-cap disposal is
   none of the three, and invariant 12 (~line 1977) says emptying `pending` on any other occasion
   "destroys the signal", so the shipped code violates the invariant's letter; §5.5 (~line 888,
   "The index phase's deletions are the ones only it can discover: its own read finds a file that
   is **no longer text** and was already indexed") — the round-1 rewording fixed the routes into
   the not-text branch and left this neighbouring "deletions only via not-text" narrowing in
   place, which is precisely the cascade class this round was asked to hunt; and
   `tests/test_knowledge_scan.py:326` ("Finding it no longer text *and* already indexed is **the
   one way** a deletion reaches the index phase") — falsified by the walk-read-succeeds-then-grows
   route. **Suggested fix:** widen all five to name the size-cap refusal beside text detection
   (§7.5 and invariant 12: "a recorded skip — text detection or the size cap (§5.5, §8.5)"; §5.5:
   "no longer text, or no longer takeable at the size cap"; the scan.py trichotomy and the
   line-326 docstring accordingly), and optionally add the missing race test: previously-indexed
   file, walk read answers new text, index read answers `OVER_SIZE_CAP`; assert one deletion and
   `over_size_cap: 1`.

3. **[IMPROVEMENT] The drop-above-prefix rule is pinned by no test that can fail, because both
   fixtures chose a colliding name.** Mutation: replace `_parse_status`'s guarded comprehension
   with `{path.removeprefix(prefix) for path in reported}` (strip where possible, drop nothing).
   `tests/test_knowledge_git.py:163` — `_parse_status(b" M guide.md\0 M docs/guide.md\0",
   "docs/")` — expects `{"guide.md"}`, and the mutation *also* yields `{"guide.md"}`: the sibling
   collides with the stripped corpus path, so the set is identical. The integration test
   (`tests/test_knowledge_scan_git.py:181`,
   `test_a_change_outside_the_corpus_is_not_mistaken_for_one_inside_it`) cannot catch it either:
   a false membership in `reported_changed` only vetoes the fast path, which reads the file,
   finds the hash equal, and keeps an identical row — so `rows["guide.md"] == first` passes and
   the test's name promises more than its assertions can observe. (This also bounds the severity:
   a leaked above-prefix path can only ever force a spurious read, never a wrong clear, so the
   drop rule is a cost guard rather than a correctness one — worth one sentence in the
   `_parse_status` docstring, which currently justifies the drop by collision alone.)
   **Suggested fix:** add a non-colliding above-prefix record to the unit fixture —
   `_parse_status(b" M notes.md\0 M guide.md\0 M docs/guide.md\0", "docs/") == {"guide.md"}` —
   which the mutation fails (it yields `{"notes.md", "guide.md"}`), and verify by running exactly
   that mutation. The researcher's round-2 mutation list covered "dropping the prefix strip"; the
   drop-above sub-rule was a separate behaviour and was not in it.

4. **[NITPICK] `changed_paths`'s summary line still promises the repository-wide set.**
   `zikaron/core/knowledge/git.py:261`: "Every path git reports as differing from `HEAD` or from
   the index, in either column" — since the fix, the function returns only the subset under the
   corpus root, as the next paragraph explains. Qualify the first line ("…that lies under the
   corpus root") so the sentence a caller reads first is not corrected two sentences later.

5. **[NITPICK] `git_answered` is derived independently at its two call sites.**
   `changes.py:109` computes it once in `compare`; `_classify` (line 151) re-derives
   `constants.answers.effective is not GitMode.OFF` inline. Both read the same `answers` object so
   they cannot disagree today, but the duplication is exactly how one site keeps a pre-fix
   expression when the other moves. Hoist the boolean into `_Constants` and pass it to both.

**What held up under attack, so it is not re-litigated.** The prefix reconciliation is correct in
every mode and shape checked: corpus root at the repository top (`--show-prefix` answers empty,
strip and filter are identities — every pre-existing repo-root test still exercises this); a
corpus root that is a submodule (the submodule is its own repository, so prefix, `status` and
`ls-files` all agree within it); a linked worktree (prefix and porcelain are both relative to that
worktree's top); `git_mode=all` with untracked paths in the status stream (untracked porcelain
entries are repository-relative too, stripped the same way, and a stray membership in
`reported_changed` can only force a read, never clear one); the rename pair's bare second field
(unit-tested with a prefix); and a trailing-newline-vs-`rstrip` edge that cannot misfire because a
non-empty prefix always ends in `/`. `_prefix_inside_repository` failure is classified
`GitUnavailableError` and §5.2's exhaustive list now carries both `rev-parse` uses, matching
`git.py`'s "six invocations" count exactly. `git_answered` is semantically right at both `keep`
call sites — under `all` a became-untracked file still gets its `None` refresh (git answered),
under effective `off` nothing is refreshed, and the new degraded-scan test plus the
persisted-`off` assertion in the listing-failure test both pin what round 1 asked for. §M21's four
M23 references now agree with §M23's own body and §M24's fence; §6.3 is in the normative list;
`remove`'s check-then-act window is stated with its bounded harm. The reworded which-phase
claims are mutually consistent across `_record_skip`, the scan module docstring, and §5.5 — with
the one residual narrowing recorded as finding 2.

**Verdict rationale:** finding 1 is a false measured bound in a normative design section, already
propagated into the always-loaded file, contradicted by the very table both cite — this corpus's
named dominant defect class, and the review's whole job is to stop it at two files rather than
three.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-15

**Summary judgment.** The round-2 fixes are real and almost complete: the throughput note's
recomputed arithmetic is correct from the slowest row (2.903 × 40/11.9 ≈ 9.8 s; 7.9% of the embed
component, 7.3% of the whole — both honestly "under a tenth"), the corpus carries no residual
2.6/0.15 figure outside deliberately quoted withdrawn text, the non-colliding `notes.md` fixture
genuinely fails the strip-instead-of-drop mutation, the new grows-between-the-two-reads race test
pins exactly what round 2 asked for, and `git_answered` is derived once. What remains is one
instance of the requested cascade class: the widened disposal enumeration landed in six sites and
the *same claim* survives, pre-fix, in three more — two of them in `scan.py` itself, one paragraph
away from the sentence that was widened, and one in the always-loaded file. The fix is three
sentences; the design document and the code are already right everywhere.

### Findings

1. **[IMPROVEMENT] The pre-widening enumeration survives in three places, two of them adjacent to
   round 2's own fix.** The claim — *index-phase deletions are text-detection deletions* — was
   widened in the six sites the researcher lists, and a grep for the claim (`became.binary`,
   `no longer text`, `it is text`) finds three statements still asserting the pre-fix world:
   (a) `zikaron/core/knowledge/scan.py:12–14`, module docstring ¶2: "The index phase's deletions
   are the ones only it can discover: a file its own read finds is **no longer text** and was
   indexed before…" — a definitional "are the ones", under-inclusive, and contradicted **two
   paragraphs later** by ¶3's widened "'Not indexable' is two refusals… both delete the row where
   one exists", and by `_dispose`, which routes `OVER_SIZE_CAP` through the same deleting branch.
   (b) `zikaron/core/knowledge/scan.py:71–74`, `ScanResult.files_deleted`'s docstring: "…and one
   the index phase read and found was **no longer text**." (c) `FINDINGS.md:619–625`, the second
   "decisions taken before any code" bullet: "the index phase's deletions are the **became-binary**
   ones it discovers at read time" and the trichotomy "**it is text** (reindex), it is not and was
   indexed before (deletion)…" — false for the still-text-but-over-cap file, which is not
   reindexed, and this is the file every session loads. **Suggested change:** (a) "…a file its own
   read refuses — no longer text, or past the size cap — and was indexed before"; (b) "…and one
   the index phase's own read refused"; (c) "the no-longer-indexable ones — not text, or past the
   size cap — it discovers at read time" and "it is indexable (reindex)". Verified the rest of the
   corpus is clean: §5.5, §7.5, invariant 12, the §3.2 DDL comment, `_record_skip`'s docstring,
   both test docstrings, and `knowledge-index.md:531` (which describes a *walk-phase* route and is
   correct as written) all carry or are consistent with the widened rule; `build-plan.md:1595`'s
   "one of the three disposals" is a neutral reference to §7.5.

2. **[NITPICK] §6.1's "the fastest mode is 2.55 s and 0.15 s" names no mode, and no single mode
   posts both numbers at full precision.** `design/knowledge-index.md:972–973`: fastest cold is
   `off` (2.553 s, rebuild 0.231 s); fastest rebuild is `tracked` (0.147 s, cold 2.554 s). The
   sentence is true of `tracked` only at display rounding. FINDINGS' own new corollary from this
   round's blocker is "name which row a bound comes from" — apply it to the small numbers too:
   "the fastest, `tracked`, is 2.55 s cold and 0.15 s to rebuild".

**Verified this round, so round 4 need not re-check:** the scaled derivation and both
"under a tenth" claims recompute correctly from 2.903 s; the withdrawal paragraph in the note
correctly names `tracked` as the source of the withdrawn figure; the only remaining 2.6/0.15
occurrences are quoted-as-withdrawn (note §1, FINDINGS' lesson paragraph); the `notes.md` fixture
fails the strip-everything mutation by yielding `{"notes.md", "guide.md"}`; the new race test's
two-answer `read_bounded` stub fails loudly on any third call and asserts deletion, counter and
empty `pending` together; `_parse_status`'s cost-guard-versus-correctness sentence matches the
severity analysis; `changed_paths`'s first line now states the corpus-root scope; and both `keep`
call sites read `_Constants.git_answered`.

**Verdict rationale:** finding 1 is the exact class this round was convened to hunt — a fix
landing in six sites while the same claim stands in three others, one of them two paragraphs from
the fix and one in the always-loaded file. It is three sentences to correct, the code and the
normative document are already right, and nothing else blocks.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-15

**Summary judgment.** Every round-3 correction is in place and consistent with its neighbours, the
tenth site is genuinely widened, and my own re-run of the claim grep across its phrasings found no
eleventh. What this round's fresh pass over the less-attacked surfaces turned up is four findings,
none touching behaviour: a user-facing diagnostic that misattributes the ordinary endorsed case to
a git failure, a docstring whose "purely at creation time" purpose claim is falsified by the scan
being its second caller, and two small drift instances — one of them a mirror of round 1's own fix
that the fix never reached. All four are prose; the code, the schema and the measurements stand.

### Findings

1. **[IMPROVEMENT] The indexer's git-mode caveat tells the ordinary user git failed when git in
   fact answered.** `zikaron/knowledge/indexer/main.py::_print_caveats` (~line 104): *"git-mode
   'tracked' did not take effect: **git could not answer for this root**, so the build ran as
   'off'…"*. Two distinct causes reach this branch, and the message names only the rare one:
   `roots.effective_git_mode` degrades to `off` both when git cannot answer *and* when the root is
   simply **not inside a git work tree** — which `design/knowledge-index.md` (~line 717) calls
   "ordinary rather than exotic" ("`git_mode` defaults to `tracked` while §8.6 explicitly endorses
   indexing a docs tree outside any repository"), and which is exactly the fixture in
   `tests/test_knowledge_indexer.py::test_a_git_mode_that_did_not_take_effect_is_said_out_loud`,
   whose own docstring says so. An operator indexing a plain docs tree is sent to debug git
   (`PATH`, `safe.directory`) on every build, for a condition where git answered correctly. The
   code cannot distinguish the two at reporting time — `inside_work_tree` deliberately collapses
   every cause to *no* — so the message must name both. **Suggested change:** *"git-mode 'tracked'
   did not take effect: this root is not inside a git work tree, or git could not answer for it,
   so the build ran as 'off' and no git rule was applied."* The test pins only "did not take
   effect", so no test change is forced; pinning a fragment of the corrected first clause would be
   cheap insurance.

2. **[IMPROVEMENT] `roots.effective_git_mode`'s docstring claims a purpose its second caller
   refutes, and an execution mode the code no longer has.**
   `zikaron/core/knowledge/roots.py:58–61`: *"The probe is run here, **synchronously**, **purely
   so a caller learns at creation time** that its choice will not take effect."* Two callers
   exist: `lifecycle.add` (line 280, the creation-time feedback the sentence describes) and
   `scan.run` (`scan.py:399`), where the same call is the **begin-time probe** whose answer
   `_begin` persists to `last_scan_git_mode_effective` and which decides the candidate set the
   whole build runs under — the design's own §5.2 "written twice" paragraph ("At walk start only
   the work-tree probe has run") names precisely this use. So "purely … at creation time" is
   false about the shipped system, and it is the misleading direction: a maintainer trusting it
   would conclude the scan does not re-probe, or that this function may safely grow
   creation-only side effects. "Synchronously" is also wrong on its face — the function is
   `async` and hops the subprocess onto a worker thread. **Suggested change:** *"Probed at
   creation, so the caller learns immediately that its choice will not take effect there, and
   again at the start of every build (§5.2's begin-time probe). Neither answer is the authority
   on an indexed corpus afterwards — what explains one is the effective mode the build that
   produced it recorded, which a walk-discovered degradation may weaken further."*

3. **[NITPICK] FINDINGS.md's mirror of §M21's normative list kept the enumeration round 1
   corrected in the plan.** `FINDINGS.md:591`: "Normative: `knowledge-index.md` §4.1, §4.2,
   §5.1–§5.6, **§6.2, §6.4**, §7.5's `pending` half and §8.5's skip breakdown" — while
   `design/build-plan.md:1589`, fixed per round 1 finding 6, reads "§6.2, **§6.3**, §6.4". The
   fix landed in one of the two sites that state the set; the always-loaded mirror still asserts
   the pre-fix world, ~120 lines above the new dogfooding entry describing exactly this
   mechanism. **Suggested change:** insert "§6.3," into FINDINGS.md:591.

4. **[NITPICK] `_record_skip`'s first route clause is narrower than §5.5's statement of the same
   claim, and than scan.py's own module docstring.** `zikaron/core/knowledge/scan.py:263–264`:
   "It reaches here only when the walk could not settle it: that earlier read *failed* **and this
   one succeeded**, or the file was indexable when the walk read it and had changed by the time
   this read ran…". The added conjunct excludes a reachable route: walk-phase read fails
   (`_classify` routes it to `pending` with `was_indexed=True`), the file then grows past the
   cap, and the index-phase `read_bounded` returns `OVER_SIZE_CAP` — a *refused* read, not a
   successful one — landing in exactly this branch. §5.5 states the same claim without the
   conjunct (`knowledge-index.md:890–891`: "its read there **failed**, or the file was still
   indexable when the walk read it and had changed by the time the index phase read it"), and so
   does scan.py's own ¶2 (lines 13–14: "either because the walk's read of it failed or because
   the file changed again after that read"). Three statements of one claim, one narrower — the
   conjunct entered during the round-1 fix and survived two rounds. **Suggested change:** drop
   it, mirroring §5.5: "…: its read failed there, or the file was indexable when the walk read
   it and had changed by the time this read ran — into something not text, or past the size
   cap."

**What this round checked, since it was asked to be named.** (a) All five round-3 edits verified
in place and against their neighbours: scan.py ¶2 now agrees with ¶3's trichotomy and with
`_dispose`; `ScanResult.files_deleted`'s "one the index phase's own read refused";
`pending.dispose`'s widened tenth site; FINDINGS' decisions bullet including "it is indexable
(reindex)"; §6.1's "the fastest, `tracked`, is 2.55 s cold and 0.15 s to rebuild" against the
note's table (2.554/0.147 at display rounding — correct). (b) The claim grep re-run independently
over `no longer text` / `not text` / `became-binary` / `text-detection` / `no(-| )longer(-|
)indexable` / `only it can discover` and `one of three` / `three disposals` / `three outcomes`:
every remaining site — §3.2's DDL comment, §5.5, §7.5, invariant 12, `build-plan.md:1595`,
`knowledge-index.md:531` (walk-phase, attribute-driven, correct) and `:650` (a commonness claim
about the never-indexed text case, not an enumeration of disposals) — carries or is consistent
with the widened rule; finding 4 is the one residual, and it is a narrowing of the *route*
enumeration, not of the disposal one. (c) A fresh pass over the modules rounds 1–3 had not
itemised: `counters.py` (the eight-reason/nine-key split agrees with §8.5's nine-way breakdown
and its `files_skipped` decomposition sentence at ~line 1738), `text.py` (endings-vs-suffix,
sniff order, the `text=auto`-admitting predicate), `walk.py` (prune list, `.git`-as-file, the
sorted/reversed stack, `files_seen` accounting), `candidates.py` (tracked intersection degrades,
attribute failure does not — matching §5.2/§4.4's determine-versus-filter split), `lock.py`
(same-host-only reclaim, unreadable-pid refusal, unconditional release), `meta.py` (thirteen
required keys plus seven transient ones, matching §3.x's creation contract at lines 282–295;
`parse_id`'s version-4 rule), `state.py` (three `reindex_required` causes, precedence order),
`lifecycle.py` (registry-first prose including the hard-kill third state; `refresh`'s
dangling-KB refusal matching the FINDINGS design-defect entry), `scope.py`, and both indexer
entry points. (d) Re-verified `changes.py`'s single `git_answered` derivation at both `keep`
sites, `git.py`'s six-invocation header against §5.2, `_parse_status`'s drop-versus-strip rules,
and the throughput note's arithmetic (2.903 × 40/11.9 ≈ 9.8 s; 7.9% of embed, 7.3% of whole) plus
the 2,033-indexed/2,034-walked distinction §6.1's "2,034 files" correctly takes from the walked
count. Nothing in (c) or (d) produced a finding beyond the four above.

**Verdict rationale:** no blocker and nothing touching behaviour, but the operator's standard for
this loop is bare approval, and findings 1 and 2 are genuine — one misleads the user in the
ordinary endorsed configuration, one misleads the maintainer about which code decides a build's
git mode. All four are a few sentences each; on their correction I expect the next round to be a
bare pass.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-15

**Summary judgment.** All four round-4 corrections are in place, and — tested rather than assumed,
as asked — none of them introduced a contradiction with the code it describes, the design sections
it cites, or the third sites that state the same claims. The two docstring rewrites were checked
claim by claim against `scan.py`, `candidates.py`, `changes.py`, `lifecycle.py` and §5.2, and every
claim held; the caveat's new wording was checked against what the degradation machinery can actually
produce, and its "ran as 'off'" is provably right on every path into that branch, not just the
probed one. No findings at any tag level.

### Findings

None.

**What this round checked, named so the trail shows a real final pass rather than a rubber stamp.**

(a) **The caveat, against every path that can reach it.** The branch fires on
`result.git_mode_effective is not result.git_mode`, and there are three ways in: the probe answered
a genuine *no* (root outside any work tree), the probe failed and was collapsed to *no*
(`git.py::inside_work_tree`, lines 168–179, whose docstring states the collapse the caveat's
comment cites), and a walk-*discovered* degradation (`candidates.gather`'s `GitUnavailableError`
branch) where the probe succeeded. The message's two clauses cover all three — the first names the
ordinary endorsed case, "git could not answer for it" honestly covers both the collapsed probe and
the mid-walk failure — and "so the build ran as 'off'" is correct by construction, not by luck:
`roots.effective_git_mode` returns only `{requested, OFF}` and `gather` returns only
`{probed, OFF}`, so a differing effective mode is necessarily `OFF`. The test now pins
`"not inside a git work tree"` (`tests/test_knowledge_indexer.py:99`) on the fixture that *is* the
ordinary case, and a corpus grep found no other site quoting either the old or the new message
text outside this review file.

(b) **The rewritten `roots.effective_git_mode` docstring, claim by claim.** "Probed at creation, so
the caller learns immediately" — `lifecycle.add` calls it at line 280 and returns the answer as
`Created.git_mode_effective` (line 312), so the caller genuinely learns rather than the value being
computed and dropped. "Again at the start of every build, whose opening transaction persists the
answer" — `scan.run:399` probes, and `_begin` (scan.py:128–155) writes
`LAST_SCAN_GIT_MODE_EFFECTIVE_KEY` in the same transaction that takes the lock. "A degradation
discovered later in the walk may weaken further, and … that build rewrites [the key] when it does"
— `gather` degrades to `OFF` on any candidacy-deciding failure and `_close_walk_phase`
(scan.py:207–214) rewrites the key with `answers.effective`; this is §5.2's own "written twice, and
the second write is the one that matters" paragraph (knowledge-index.md:756–759), restated
consistently. "Synchronously" is gone, correctly — the function is async and hops the subprocess to
a thread. The claim's third and fourth statements — §5.2's "`add` reports the degradation from its
own probe" paragraph (lines 764–769) and `Created`'s docstring (lifecycle.py:103–105) — agree with
the rewrite; no site still asserts "purely at creation time".

(c) **The route enumeration, at all three sites and against the mechanism.** `_record_skip`'s
clause now reads "its read **failed** there, or the file was indexable when the walk read it and
had changed by the time this read ran — into something not text, or past the size cap"
(scan.py:263–265), agreeing with scan.py ¶2 (lines 12–14) and §5.5 (knowledge-index.md:890–892).
The dropped conjunct was the right thing to drop, and the two-route enumeration is *exhaustive*,
verified against `changes.compare`: every previously-indexed path that enters `pending` passes
through `_classify` (git could not clear it), which either read-fails (`UNREADABLE` → route 1) or
reads it as indexable with a differing hash (route 2) — its other two branches (`NotText`,
over-cap) route to `no_longer_admitted` and are walk-phase deletions that never reach `pending`.
So there is no third way a previously-indexed pending row exists, and no route in which the walk
never attempted the read. The fourth statement of the claim, the test docstring at
`tests/test_knowledge_scan.py:324–327`, names both routes consistently.

(d) **The two normative-set enumerations.** `FINDINGS.md:591` and `design/build-plan.md:1589` both
read "§6.2, §6.3, §6.4"; a grep for both the corrected and the pre-fix spelling confirms exactly
two sites state the normative set and they agree, with the review file's quotations being trail
rather than assertion.

**Verdict rationale:** the four fixes are correct, their neighbours were read, the claims they
introduce were checked against the code and design they describe rather than accepted on the
researcher's report, and the independent grep sweeps found no fifth site of any of the reconciled
claims. Nothing remains at any tag level.

VERDICT: APPROVED
