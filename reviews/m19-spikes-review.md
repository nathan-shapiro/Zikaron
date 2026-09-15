# M19 spikes — review

Artifacts: the M19 amendments to `design/knowledge-index.md` (§3.2, §4.1, §4.2, §4.6, §5.2, §5.5,
§5.6, §7.2, §8.4, §13, §15, §16), the three research notes (`research/knowledge-index-vec0-fts5-probe.md`,
`research/knowledge-index-git-shapes.md`, `research/knowledge-index-group-ordering.md`), their three
harnesses under `spikes/`, plus the M19 blocks in `FINDINGS.md`, `FINDINGS-archive.md` §References,
and `design/build-plan.md` §M19.

## Round 1 — 2026-09-15

**Summary judgment.** This is strong spike work: every harness actually performs the measurements its
note reports (verified against the code, including the reimplemented lexical-query construction, which
does match `query.py`'s `isalnum` runs, longest-first ordering and OR-of-quoted-terms), the notes are
unusually honest about significance and threats, and the amendments are with few exceptions faithful
to what was measured. The §8.3/§7.2 contradiction find and the saturation mechanism are genuinely
good. One amendment, however, writes a failure-classification rule that contradicts the design's own
adjacent principle and, read literally, reproduces the silent-corpus-widening defect it exists to
close — that one must be fixed before M20/M21 build against it. The rest is material-but-small
tightening plus nitpicks.

### Findings

1. **[BLOCKER] §4.1 step 3 / §5.2 — "only exit 128 is failure" is an enumeration of causes that the
   neighbouring paragraph forbids, and it leaves every other abnormal outcome classified as an
   answer.** `design/knowledge-index.md:318-322` says *"Exit 1 means 'none of these paths is ignored';
   only exit 128 is failure"*, and `:625-628` repeats *"It exits 1 to say none of these paths is
   ignored … and 128 to fail."* Three paragraphs above, `:619-620` states the section's own rule:
   *"The rule is stated over **any** git failure, not over an enumeration of causes."* The probe
   observed exits 0, 1 and 128 (and git documents exactly those three), but a `check-ignore` that dies
   on a signal, is OOM-killed, or exits 2 on a bad flag returns none of them — and under the literal
   text it is not 128, therefore not failure, therefore an empty stdout that parses as "nothing
   ignored". Under `git_mode = all` that silently skips applying `.gitignore` while
   `last_scan_git_mode_effective` still records `all` — the exact silent widening `:313-315` claims
   this rule prevents, and one specification admitting two corpora, which is the defect class §5.2
   names for itself. **Fix, one clause in both places:** classify by answers, not by the failure code —
   "exits 0 and 1 are answers; any other outcome, including any other exit status or death on a
   signal, is failure." (The note's §2 phrasing "exit 128 is failure, exit 1 is an answer" seeded
   this; the note may stand as the record of what was observed, but the design must state the rule
   over the complement.)

2. **[IMPROVEMENT] §4.6's `'delete-all'` sentence points at §8.4, but §8.4 never uses it.**
   `design/knowledge-index.md:526-527`: *"The whole-index `'delete-all'` command needs no values and is
   the right tool where the whole corpus goes (§8.4), never for one file."* §8.4's encoder-mismatch
   repair (`:1356-1362`) drops `chunks_fts` and recreates it — it does not issue `'delete-all'` — and
   no other path in the design clears a whole index either (`remove` unlinks the file; `full=true` is
   per-file transactions). The cross-reference sends an implementer to a section whose mechanism is a
   different one. Suggested edit: *"The whole-index `'delete-all'` command needs no values (measured,
   A12), but no path in this design issues it: the one whole-corpus operation, §8.4's repair, drops
   and recreates the table instead, which subsumes it. It is never correct for one file."*

3. **[IMPROVEMENT] The "lower bound" conservatism claim in §7.2 (and the note's matching bullet) is
   stronger than the arithmetic supports — the omitted §8.3 lookup provably cannot change the group
   key on this data.** `design/knowledge-index.md:959-962`: *"the arm that won had strictly less
   information than the shipped design gives it, and the gap it won by is a lower bound."*
   The group key is the max cosine over group members. A lexical-only member is by definition outside
   the dense top-`fusion_depth`, so its cosine is ≤ the KB's depth-th dense cosine, which is ≤ the
   cosine of every dense-found member of the group. Therefore §8.3's explicit lookup can alter the key
   only for a group containing **zero** dense-found chunks — and since the dense arm always returns
   `fusion_depth` candidates and dense rank 1 ties or beats every lexical contribution in fused order,
   such a group essentially cannot form (the harness would have recorded `best_cosine = -1.0`; no such
   group is reported). So the measured margins are the shipped design's margins **exactly**, not a
   lower bound on something better; the omission is immaterial to ordering and matters only to `score`
   reporting. Presenting equality as conservatism flatters the result. Fix in both
   `design/knowledge-index.md` §7.2 and `research/knowledge-index-group-ordering.md`'s threat bullet:
   state the bound argument and claim identity ("the omission cannot change the key of any group
   containing a dense-found chunk, which was every group observed"), or report the count of
   zero-dense groups if any occurred.

4. **[IMPROVEMENT] Invariant 3's oracle is measured in one direction only, and the unmeasured
   direction is half of the invariant.** Spike A measured that `integrity-check 1` catches an
   **orphaned index** (content rows gone, FTS rows present — A11). Invariant 3
   (`design/knowledge-index.md:1718-1720`) also rules out the inverse: a `chunks` row with **no**
   `chunks_fts` row (e.g. a bug that issued the FTS `'delete'` but rolled back only the content half,
   or an insert path that skipped the FTS write). Nothing measures that argument 1 sees a *missing*
   row, and if it does not, M22's invariant test will pass on half the corpus it exists to rule out —
   the exact trap-4 failure the probe itself documents. One added case in
   `spikes/spike_vec0_fts5_ddl.py` settles it (issue a valid `'delete'` for one row, keep the content
   row, run `integrity-check 1`); until then, §3.2/§13 should scope the claim to the measured
   direction rather than presenting argument 1 as *the* mechanical oracle for the invariant.

5. **[IMPROVEMENT] §16 open question 11 defers its deciding measurement to M21, and §M21's brief does
   not carry it.** `design/knowledge-index.md:1906-1912` and `design/build-plan.md:1466-1467` both
   say the directory-pruning question is decided by a number taken "with M21's throughput
   measurement" — but §M21's own brief (`design/build-plan.md:1575-1577`) enumerates wall time, peak
   RSS and the §16-item-9 binary-with-unknown-extension fraction only. A session working M21 from its
   brief, as this project requires, will not take the number item 11 needs ("how much of a real
   repository sits under a `.gitignore`d directory that step 1's fixed list does not already name").
   Add it to §M21's measured list. This is the enumeration-drift class FINDINGS warns about, committed
   the same day it was re-documented.

6. **[IMPROVEMENT] The spike C note's threats section omits the fused ordering's tie-resolution
   artifact.** `spikes/spike_group_ordering.py::rank_of` sorts with Python's stable sort, so exact
   ties at the top resolve by KB insertion order (`zikaron_code`, `amazonq_code`, `amazonq_docs`) —
   a deterministic bias that binds precisely where the note's own saturation analysis says ties are
   common, and tie counts are reported only at depth 50 (1–3 of 24 per family), not at the lower
   depths where the fused collapse (0.57 → 0.38) is measured. Balanced truths mean this should not
   manufacture the collapse in aggregate, and the `fused+cosine` row bounds its size — but that
   reasoning belongs in `research/knowledge-index-group-ordering.md` §"Threats to validity" rather
   than in a reviewer's head. One bullet.

7. **[NITPICK] §5.2's submodule paragraph attributes the `off`-mode cost to the wrong mechanism.**
   `design/knowledge-index.md:610-612`: *"Under `all` and `off` … since they have no `ls-files` entry
   in either mode, the non-NULL requirement below puts every one of them on the read-and-hash path"*.
   Under `off` git is not consulted, there is no listing, and §5.3 already puts *every* candidate on
   the read-and-hash path; the non-NULL requirement is doing the work only under `all`, which is how
   the note (§6) correctly scopes it. Scope the sentence to `all` and let `off` cite §5.3.

8. **[NITPICK] §4.6 misattributes which `integrity-check` form was run after the wrong-values
   delete.** `design/knowledge-index.md:521-523` says *"with the argument-less `integrity-check`
   reporting OK afterwards"*; the harness's A11 ran argument **0** at that point (A9 ran the bare
   form, on the A5 corpus). §3.2's own measurement makes the two equivalent, so say "argument-0
   form (equivalently the bare form, §3.2)".

9. **[NITPICK] §4.6's `'delete'` incantation omits the rowid.** `:523-525` says the transaction
   *"reads `chunks.path` and `chunks.text` before deleting … and issues `'delete'` with those
   values"* — the command also requires the row's id
   (`INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', id, path, text)`, as the
   harness's A10 issues it). Add "and its rowid" so the design's one statement of the incantation is
   the complete one.

10. **[NITPICK] §7.2's sweep-table parenthetical contradicts itself.** `:942-944`: *"(…, 72
    mechanically-generated queries over three real corpora, every parameter at its shipped
    default)"* annotates the one measurement whose point is varying `fusion_depth` away from its
    shipped default. "Every **other** parameter at its shipped default."

11. **[NITPICK] The correction count drifts between files.** `design/build-plan.md:1460-1462` says
    "fourteen corrections … **plus** one correction to §7.2's own argument that no probe found";
    `FINDINGS.md:339-341` counts "fourteen (5 + 6 + 3)" — but spike C's "What changes" item 1
    *includes* the §8.3 correction, so the 14 already contains what build-plan counts as the +1.
    Pick one accounting and state it in both.

12. **[NITPICK] FINDINGS' "the harness convicted itself of the same class twice" is half
    unattested.** `FINDINGS.md:356-359` claims spike A's *first* `integrity-check` used the blind
    form; nothing in the note or harness records that (the spike B parser self-conviction *is*
    recorded, in the note's §5). Either record it in the spike A note or drop spike A from the claim.

13. **[NITPICK] The spike C note's masking description understates what the code does.**
    `research/knowledge-index-group-ordering.md` method: *"every token unique to its KB removed"*;
    the harness masks any word **containing** a token unique to **any** KB as a substring
    (`unique_any`, `t in w` — `spike_group_ordering.py:239`). Stronger masking, conservative
    direction, but the method sentence should match the instrument.

### Not flagged, deliberately

The pre-existing tension between §4.2's bullet 1 ("an attribute-excluded path never enters `pending`
at all") and the previously-indexed-exclusion deletion path predates M19 (only the measured-framing
paragraph is new) and was approved through twelve rounds — out of this review's scope. The
case-insensitive mount's absence is handled honestly in both the note and §5.6. The `fusion_depth`
sweep is correctly framed as an approximation, not a simulation, in both the note and §7.2. §7.2 and
§15 carry the p-values inline where "not better in any family" is asserted, which is adequate
qualification. Spike A/B/C answer every question `design/build-plan.md` §M19 asks.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-15

**Summary judgment.** All thirteen Round 1 findings landed correctly, and none broke a neighbour in
the direction Round 1 warned about: the complement rule in §4.1 step 3 and §5.2 agree with each other,
with §5.2's "any git failure" paragraph and with §4.1's degradation clause; A16 constructs exactly the
state it claims (a valid `'delete'` for row 2 with correct values, content row kept, so `chunks` holds
a row with no `chunks_fts` entry) and the notes report it faithfully; the `no_dense_member` counter is
the right instrument for the identity claim and the sweep's tie columns match the threats bullet. What
remains is the residue of two fixes — each closed the named hole while asserting one cell the
measurement grid still leaves empty or contradicting a number the same round added — plus one
arithmetic inconsistency Round 1 missed. Nothing blocks; all of it is this corpus's own
name-the-quantity discipline applied to four sentences.

### Findings

1. **[IMPROVEMENT] The finding-4 fix scopes the *blind* forms one cell past the measurement, and the
   note's own table shows the empty cell.** A16 runs `integrity-check 0` and `1` only
   (`spikes/spike_vec0_fts5_ddl.py:339`); the **bare** form was measured solely on the orphan corpus
   (A9). `research/knowledge-index-vec0-fts5-probe.md`'s trap-4 table is honest about this — the
   A9/missing-row cell is "—" — but four prose statements assert the cell's value anyway:
   the note's "What changes" item 5 (*"the bare and argument-0 forms see neither"*),
   `design/knowledge-index.md:266-267` (*"A test written against the form an implementer would reach
   for first therefore sees neither"* — the first-reach form is the bare one, per trap 4's own
   self-conviction), invariant 3 at `:1743-1744` (*"the argument-less and argument-0 forms report OK
   on either"*), and `FINDINGS-archive.md:1772` (*"the bare and argument-0 forms reporting OK on
   either"*). The claim is almost certainly true — §3.2's documented bare≡0 semantics plus the
   measured orphan direction support it — but this is Round 1 finding 4's exact class reappearing one
   cell over, inside the sentences that fix it. **Cheapest fix is the measurement:** add the bare form
   to A16's detail line (the A9 loop already has the SQL), re-run, replace the "—". Otherwise scope
   all four sentences to argument 0 and state the bare form's missing-row behaviour as documented
   equivalence rather than measurement.

2. **[IMPROVEMENT] "A median of 3 of 3 groups tie at the top value" is refuted by the tie counts this
   round added.** `design/knowledge-index.md:974-975` (*"so a median of 3 of 3 groups reach the top
   value"*) and `:1871-1872` (§15: *"so a median of 3 of 3 groups tie at the top value"*). The
   measured facts (`research/knowledge-index-group-ordering.md`): an exact fused tie at the top occurs
   in **7 of 72** queries at the shipped depth (31/72 at depth 3), and the median number of *distinct*
   fused values across 3 groups is **2–3**. What is median behaviour is that all three groups' top
   chunks are found by both arms (families 2–3), compressing the keys into a narrow band — not a
   3-way tie at the top. The note states this correctly; both design compressions overstate it, and
   §15's is unambiguous. Suggested wording for both: "…produces that event in every corpus — in a
   median query every group's top chunk is found by both arms — compressing the fused keys to a median
   spread of 0.003–0.014, with an exact tie at the top in 7 of 72 queries at the shipped depth (31 of
   72 at depth 3), while cosine's margin is wider by 5–40× and never ties."

3. **[IMPROVEMENT] The "20–40× wider" multiplier is contradicted by the table beside it.** From the
   note's own saturation table (`research/knowledge-index-group-ordering.md:112-116`), the per-family
   ratios of median cosine spread to median fused spread are 0.07552/0.01404 ≈ **5.4×** (identifier
   bare), 0.05855/0.00367 ≈ **16×** (in prose), 0.10446/0.00262 ≈ **40×** (prose masked). "20–40×"
   holds for one family of three, and the harness prints no other quantity it could derive from. It
   appears in the note (`:118`), the note's tiebreak threats bullet is clean, and it propagates to
   `design/knowledge-index.md:975` (§7.2) and `:1872` (§15). State it as "5–40× across the three
   families" or give the three ratios; the conclusion survives untouched at 5×.

4. **[NITPICK] Trap-4 table row labels attribute A16's argument-0 cell to A9b.** The missing-row "OK"
   in row A9b (`research/knowledge-index-vec0-fts5-probe.md:110`) was measured by A16's
   `ic(c, 0)` on the a16 corpus; A9b ran on the orphan corpus only. Row 3 is labelled "A9c / A16" for
   exactly this dual sourcing — label row 2 "A9b / A16" for the same honesty.

5. **[NITPICK] `FINDINGS.md:283-284` says "1,912 lines after M19's amendments"; the file is 1,937
   lines** after the Round 1 fixes, which are themselves M19 amendments. This file's own M13-hash
   lesson is about confident-looking pointers falsified by ordinary edits — update the number or
   de-precision it ("~1,900 lines").

### Verified this round, so it is not re-litigated

The blocker fix is complete and consistent: the complement rule appears at
`design/knowledge-index.md:320-329` and `:640-647`, the two statements agree, neither contradicts
§5.2's "any git failure" paragraph (which now *defines* "fails" for `check-ignore` via the
complement), and `research/knowledge-index-git-shapes.md` §2 withdraws its "exit 128 is failure"
recommendation in place with the right reasoning; no "only 128" phrasing survives anywhere in the
corpus. A16's construction and both notes' descriptions of it match the code; the trap-4 prose
paragraph ("Both directions are measured deliberately…") is accurate as scoped to argument 1.
`no_dense_member` (`spike_group_ordering.py:195-209`) measures exactly the zero-dense-member shape
the bound argument requires, 0/216 at every depth matches the printed denominator (72 queries × 3
groups), and §7.2's identity claim plus the note's rewritten threats bullet state the argument
soundly with the lower-bound withdrawal in place. The sweep's tie columns match the threats bullet's
7/72 → 31/72 and 0/72 numbers, and the bullet's two bounding arguments (balanced truths; the
`fused+cosine` row) are correct. Findings 2, 5, 7, 8, 9, 10, 11, 12 and 13 all landed as described:
§4.6's `'delete-all'` sentence now matches §8.4's actual mechanism; §M21's brief carries the
directory-pruning number with the three-questions-one-walk warning and §16 item 11 names the same
number; the submodule cost is scoped to `all` with `off` citing §5.3 in both the design and note §6;
the fourteen-count accounting agrees between `design/build-plan.md` and `FINDINGS.md` with the §8.3
correction inside spike C's three; and both harness self-convictions are now attested where FINDINGS
points (note B §5, note A trap 4).

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-15

**Summary judgment.** All five Round 2 findings landed correctly and no neighbour broke: the three
sites of the multiplier claim agree at "5–40× by family" and the ratio column's arithmetic checks
(0.07552/0.01404 ≈ 5.4, 0.05855/0.00367 ≈ 16, 0.10446/0.00262 ≈ 40); no "20–40" and no "3 of 3 …
top value" phrasing survives anywhere; the compression/exact-tie distinction is stated consistently
in the note (§"Why the fused ordering fails", the new paragraph), §7.2 and §15, with the tie counts
(7/72 shipped, 31/72 at depth 3, cosine 0/72) matching the sweep table at all three sites; and A16
now measures all three `integrity-check` forms on the missing-row corpus, so the trap-4 grid is
complete, its dual-sourced row labels are honest, and the four downstream statements rest on
measurement. The spike work itself is sound and I would ship it. What remains is one piece of
bookkeeping the first two rounds should have caught and did not — a claim in two in-scope files that
this review does not exist — plus two genuine nitpicks.

### Findings

1. **[IMPROVEMENT] Two in-scope files assert "no reviewer round" while this three-round trail sits
   in `reviews/`, and nothing anywhere references it.** `FINDINGS.md:336-337` (*"and **no reviewer
   round** on operator direction, since a research spike's output is measurement plus a design
   amendment"*) and `design/build-plan.md:1458` (*"No reviewer round, on operator direction"*).
   Both were written before this review was commissioned and both survived two fix passes that
   edited their neighbouring sentences; grepping the repository for `m19-spikes-review` returns
   **zero** references, so the trail is undiscoverable from working memory. A fresh session resuming
   from FINDINGS would take the sentence at face value — and the plausible failure is re-commissioning
   a review of artifacts that have been through three rounds, or missing the corrections history this
   file carries (the lower-bound→identity withdrawal, the tie-claim overstatement). This is the
   corpus's own confidently-stale-claim class (the M15 "the installer does not" specimen), in the
   always-loaded file, in two places — fixing one and not the other would be the enumeration drift
   both prior rounds warned about. **Fix, both places, writable now without waiting for
   convergence:** "landed without a pre-landing review gate, on operator direction — a research
   spike's output is measurement plus a design amendment; the spike artifacts were then reviewed
   post-landing, trail `reviews/m19-spikes-review.md`" (add the round count and verdict when the
   loop closes). I flag my own prior rounds' miss here: the sentence was already false at Round 1.

2. **[NITPICK] §3.2's measured clause names only argument 0, then draws the bare-form conclusion
   from it.** `design/knowledge-index.md:265-267`: *"argument 1 raises on an FTS row whose content
   row is gone and on a content row whose FTS row is missing, while argument 0 reports **OK** on
   both. A test written against the form an implementer would reach for first therefore sees
   neither."* The first-reach form is the bare one (trap 4's own self-conviction), so as written the
   "therefore" still routes through documented bare≡0 equivalence — the structure Round 2 asked to
   retire — even though the bare cell is now measured on both corpora (A9, A16). The other three
   downstream statements state the measured cells directly; make this one match: *"while the bare
   and argument-0 forms report **OK** on both."* One clause; the "therefore" then rests entirely on
   stated measurement.

3. **[NITPICK] `FINDINGS.md:284` says "11 open questions"; §16 has 11 items of which item 2 is
   closed.** M19 closed question 2 (struck through, "CLOSED by M19 spike C") and opened question 11,
   so the count of *open* questions is 10 and the count of items is 11. Beside a parenthetical that
   just deleted a confident-looking number for being falsified by ordinary edits, say either "10
   open questions" or "11 §16 items, one closed by spike C".

### Verified this round, so it is not re-litigated

A16 issues the bare form via `ic(c, None)` (`spikes/spike_vec0_fts5_ddl.py:67-77, :349`), evaluated
left-to-right ahead of arguments 0 and 1, on a corpus that verifiably holds a `chunks` row with no
`chunks_fts` entry (row present = 1, FTS matches = 0); the trap-4 table's six cells each trace to a
recorded measurement with row labels "A9 / A16", "A9b / A16", "A9c / A16" naming both sources; the
"Every cell is measured" paragraph and the "Both directions" paragraph are accurate as written; and
the note's "What changes" item 5, invariant 3 (`design/knowledge-index.md:1744-1747`) and
`FINDINGS-archive.md:1770-1773` all state the measured grid correctly. The harness's 21-question
count matches the brief. Findings 2 and 3's three-site claims (§7.2 at `:973-978`, §15 at
`:1873-1877`, note `:112-128`) were grepped for the *claim* rather than the phrasing: the multiplier
appears exactly three times, all "5–40"; the median claim is scoped precisely in the note (families
2 and 3 named) and stated in the design in the wording Round 2 itself supplied, with the note's new
distinction paragraph carrying the precision; the removed line count left a rationale clause rather
than a hole. Spike B and its note were untouched since Round 2 and were not re-reviewed.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-15

**Summary judgment.** All three Round 3 findings landed correctly and consistently, and none broke a
neighbour: the three statements about this review agree with each other and with what the trail
actually records, the new archive entry's every specific claim traces to a numbered finding, and no
stale phrasing survives anywhere in the corpus. The artifact set is sound and I would ship it. One
genuine nitpick remains, adjacent to rather than inside this round's changes; it does not block.

### Findings

1. **[NITPICK] The build-plan's knowledge-index preamble now contains a fired conditional it does not
   acknowledge, and the resolution lives only in FINDINGS.** `design/build-plan.md:1438-1439` says the
   design *"is APPROVED but **not yet normative** … it becomes normative when the first of these
   milestones lands"* — and `:1454` now marks M19 **complete**, so the preamble's own trigger has
   fired while its lead assertion still reads "not yet". `FINDINGS.md:292-298` handles exactly this
   ("Whether it is now normative is an operator call that is owed … `design/overview.md` remains the
   authority"), but the build-plan never points there, so the two files resolve the same question
   differently — the always-loaded one says *owed operator call*, the brief's own preamble says, on
   the literal reading, *normative now*. Both err safe in their lead sentences and FINDINGS is always
   in context, which is why this is a nitpick rather than more. One clause in the preamble closes it:
   "M19 has landed; whether that makes it normative is an operator call still owed (FINDINGS.md
   carries the argument) — `design/overview.md` remains the authority meanwhile." Rounds 1–3 could
   have flagged this and did not.

### Verified this round, so the trail records it

**Finding 1's three sites agree with each other and with the trail.** `FINDINGS.md:341-348`,
`design/build-plan.md:1458-1461` and the new `FINDINGS-archive.md:1764-1776` entry state the same
facts at three compressions: no pre-landing gate on operator direction, post-landing review on the
operator's subsequent instruction, trail named, one blocker plus four corrected claims. The counts
reconcile — FINDINGS enumerates the four (lower-bound→identity, one-direction oracle, two withdrawn
numbers) and build-plan's "four overstated or unmeasured claims" covers the same set. Grepping for
`m19-spikes-review` returns the three files plus this one; no "no reviewer round" phrasing survives
outside this review's own quotations. FINDINGS carries the read-the-trail-first warning the fix
promised.
**The archive entry is accurate against Rounds 1–3.** The blocker description (signal death and
`exit 2` classified as answers; silent `.gitignore` skip under `git_mode = all`; the enumeration
three paragraphs from the rule forbidding it) matches Round 1 finding 1 including its geometry;
"provably identity (0 of 216)" matches finding 3 plus Round 2's verified `no_dense_member` count;
the one-direction oracle is finding 4; the tie claim and the 20–40× multiplier are Round 2 findings
2 and 3, including "refuted by numbers added in the same round" and "really 5–40×". "Three of the
findings were answerable only by extending a harness and re-running it" is fair as written: A16
(R1-4), the bare form added to A16 (R2-1) and the `no_dense_member` counter (R1-3) each had a
scope-the-claim-down fallback, but scoping down concedes the question rather than answering it, and
each was in fact answered by measurement. The entry claims no round count and no verdict, correctly,
since the loop had not closed when it was written — per Round 3's own instruction, both can be added
once this round's verdict lands. It sits as the top §References entry, and the reviewer's
self-flagged miss is recorded.
**Findings 2 and 3 landed clean.** `design/knowledge-index.md:265-269` now states the bare and
argument-0 cells as measured ("every one of those six cells measured rather than inferred from the
two forms' documented equivalence"), so the "therefore" rests on stated measurement; the six-cell
count matches the note's trap-4 grid, and the claim's other sites (§4.6 at `:530-531`, invariant 3
at `:1749`, the note's table, "Every cell is measured" paragraph and "What changes" item 5, and the
archive's spike A entry at `:1784-1785`) all still agree — the edit drifted from none of them.
`FINDINGS.md:284-285` now reads "11 §16 items of which one is closed by spike C, leaving 10 open",
which matches §16's state and build-plan's "question 2 closed, question 11 opened" at `:1471-1472`.
**Also checked:** the fourteen-correction accounting (5 + 6 + 3, §8.3 inside spike C's three) still
agrees between FINDINGS and build-plan; the spike-A self-conviction FINDINGS cites is attested at
note lines 128-132; no corrected figure was reintroduced anywhere (no "20–40", no "3 of 3 … top
value", no "lower bound" claim). The spike harnesses and notes were untouched since Round 3 except
where named above and were not re-reviewed.

VERDICT: APPROVED
