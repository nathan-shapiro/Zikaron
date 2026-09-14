# M18 — payload spill brief review

Artifact: `design/build-plan.md` §M18 ("A group too big to deliver, and a file the consolidator can
actually read"), lines ~1126–1231. Evidence read: `research/claude-code-mcp-result-truncation.md`;
code read: `zikaron/core/consolidation/{candidates,groups,verbs}.py`, `zikaron/mcp/{main,server,
consolidator,connection}.py`, `zikaron/harness/spec.py`; design read: `design/harness.md` (D34
table and §"Everything harness-varying is a HarnessSpec field"), `design/architecture.md`
§"Filesystem security".

## Round 1 — 2026-09-13

**Summary judgment.** The mechanism is the right one — client-side spill to a line-paginable file,
harness-gated, service untouched — and the rejected-alternatives section is genuinely good: each
rejection carries a reason a fresh session can check. But the brief's two load-bearing claims are
both unproven as written. "Indented JSON is thousands of short lines" is false for a payload
dominated by string values, and the store this milestone was measured against holds records whose
JSON-escaped `content` is far past any plausible per-line read cap — so the design as specified can
reproduce the defect in a quieter, worse form (silently truncated prose informing a merge). And the
"safely low" threshold argument is denominated in characters against a cap the brief itself says is
in tokens, which is the exact unit-mismatch bug class this project has now caught twice (M14, twice
in one milestone). Both are fixable inside the brief without changing the design's shape.

### Findings

1. **[BLOCKER] Pretty-printing does not bound line length, and line length — not line count — is
   what `Read` paginates by. The design's load-bearing claim is false for this payload.**
   §"The design", "The spill file is pretty-printed, and that is the load-bearing detail":
   *"Compact JSON is one enormous line … indented JSON is thousands of short ones."* Indentation
   splits JSON *structure*, not *strings*. A record's `content` JSON-escapes to exactly one line
   (raw newlines become `\n`), and a consolidation payload is mostly `content` fields. The observed
   store holds records to ~1,877 tokens — roughly 7,000–12,000 characters at the corpus's measured
   3.89–6.55 chars/token — so a pretty-printed spill of a real group contains individual lines in
   the five-digit range. The evidence file's successful three-call read
   (`claude-code-mcp-result-truncation.md` §"The dead end is the file's *shape*") was against
   ~103-character filler lines; nothing in the corpus measures what `Read` does with a
   multi-thousand-character line inside a multi-line file, and Claude Code's own `Read` description
   states that over-long lines are truncated. If that holds, every invariant in the brief passes
   (the file is valid, line count scales with payload, round-trip comparison of *file* against
   *payload* is exact) while the consolidator reads truncated prose and merges from it — precisely
   the "destroy prose nobody read" hazard the gist-only option was rejected for, now silent instead
   of loud. Concrete edits:
   - Replace the pretty-printing paragraph's claim with the real requirement: **the writer must
     bound the maximum line length** to a named constant, chosen against a *measured* per-line
     `Read` cap (one probe run: a multi-line file containing one 8,000-character line; the
     truncation note is the natural place for the result). The obvious encoding that round-trips:
     serialize `content` (and any other potentially long string) as a JSON array of ≤N-character
     segments whose concatenation is the original.
   - Change invariant 1 from "line count against payload size" to "**no line in the spill file
     exceeds N characters**, and a compact-JSON or unsegmented-string regression must fail this".
   - Add to done-when: the end-to-end store must contain **at least one record whose JSON-escaped
     content exceeds N**, and the consolidator's read-back of it must be shown verbatim-complete —
     otherwise "readable to its end" passes on short-lined fixtures while every real store fails.

2. **[BLOCKER] The "safely low" argument is stated in characters against a cap the brief says is in
   tokens, and the brief names neither the key, nor its default, nor its unit.** §"The threshold is
   a config key". The brief's own defect paragraph says the cap "is in *tokens*" and "is
   content-dependent", and the evidence note brackets it at 40,000–52,095 characters *of one filler
   measuring ~1.47 chars/token* — close to the densest ASCII content there is. A character
   threshold T guarantees no inline refusal only while T ÷ (chars per token) stays under the
   ~27,000-token floor; at T = 40,000 that requires ≥1.48 chars/token, i.e. the measured filler sits
   *exactly at* the boundary, and content that tokenizes denser than the filler — emoji runs, and
   plausibly some non-Latin prose — breaks the guarantee outright. So "the number does not need to
   be right — only safely low" is not unconditionally true in the unit the key is denominated in,
   and that conditionality is the brief's central future-proofing claim (its heading says the fix
   "does not need revisiting"). This is the exact failure M14 caught twice and FINDINGS enshrines as
   "name the quantity before quoting a number about it". Concrete edits:
   - Name the config key (and which `schema.md` config-table section it lands in), its **default**,
     and its **unit including how it is counted** (`len()` is fine for a margin, but say so — this
     corpus has been burned by "characters" twice).
   - State the ratio assumption the default rests on, explicitly: e.g. "the default of 30,000
     characters is refused inline only by content averaging under ~1.1 chars/token; the measured
     filler (1.47) and all observed store prose (3.89–6.55) clear it; a store that does not clear
     it hits the *original loud stall, never silent loss*, and the operator's remedy is lowering
     the key." That last clause matters: it is what keeps the failure mode honest and downgrades
     "never needs revisiting" to a claim the brief can actually defend.
   - Bound "conservative" from below as well: the median observed group is 27,218 characters, so a
     default under ~28k makes the *ordinary* group pay the spill's extra `Read` round-trips. One
     sentence anchoring the default between the median and the ratio-derived ceiling closes it.

3. **[BLOCKER] The store-scale measurements the brief depends on are recorded nowhere, and the
   brief's own evidence line claims otherwise.** The header says the truncation note "carries every
   measurement below"; it does not carry "18 of 20 oversized groups … fit once low-ranked
   candidates are dropped" (§Rejected, trimming) or "the two groups in the observed store whose
   anchor and members alone exceed the threshold" (scope fence). Grep confirms 116 groups / 69,265
   / 27,218 / 20-of-116 appear in no file in the repository. Consequences: the scope fence excludes
   two groups a fresh session cannot identify; the trimming rejection cites a number nobody can
   check; and the project's evidence-separation rule (measured results live in `research/`) is
   violated by a brief that is otherwise scrupulous about it. Concrete edit: record the group-size
   distribution against the operator's store — 116 groups, max 69,265 chars, median 27,218,
   candidates a median 70% and max 94% of a group, 20 of 116 over 40,000 chars, 2 over on
   anchor-plus-members alone, with store identity and date — either as a section of the truncation
   note or a sibling `research/` note, identify the two out-of-scope groups at least by size, and
   cite it from the brief's evidence line and from both places the numbers are used.

4. **[IMPROVEMENT] The brief does not say where the spill sits or which results it covers, and the
   harness gate as described invites the branch the seam rule forbids.** Three related gaps, one
   edit. (a) `next_group` is the observed offender, but a `merge`/`promote`/`discard` **conflict**
   response carries `current: [...]` with the full prose of every conflicting row
   (`verbs.py`/`consolidator.py`) — a dozen large rows is plausibly over any conservative
   threshold. Cleanest is spilling at the client's shared result-translation seam so *every* tool
   result is covered uniformly; if the brief means `next_group` only, it should say so and say why
   the conflict shape is safe. (b) "kiro gets none of this" is currently only prose; a fresh session
   can implement it as `if harness is KIRO:` downstream of detection, which CLAUDE.md forbids — the
   brief should state that spill eligibility is **`HarnessSpec` data** (it half-does this for
   `Read`; say it for the spill gate too), and add the assertable invariant "under a kiro-detected
   client an over-threshold payload is returned inline". (c) `design/harness.md` states that every
   harness-varying value is a `HarnessSpec` field **with a D34 table row**, and the table's drift
   test enforces it — so the brief should name the rows M18 adds (MCP-result cap and overrun
   behaviour, which the table currently lacks entirely; the `Read` capability; spill
   applicability), or the implementer discovers the obligation only when the drift test goes red.

5. **[IMPROVEMENT] The spill file's lifetime is unspecified, and the erasure procedure now has an
   unnamed fourth surface.** §Location says the runtime directory clears on reboot; between reboots
   it is tmpfs — RAM — accumulating up to ~100 KB of full record prose per spilled serve, with
   re-serves and repeated runs multiplying files. And `write-policy.md`'s operator erasure
   procedure enumerates where captured secrets can persist; a spill file is a verbatim copy of
   record prose outside the store and outside the log rules, so a secret erased from the store can
   survive in `$XDG_RUNTIME_DIR/zikaron/` until reboot. Concrete edit: state a cleanup rule (e.g.
   the client unlinks its previous spill when writing the next, plus unlink-at-exit; filenames
   unique per serve so a re-serve cannot overwrite a file mid-`Read`), and add one line to the
   erasure procedure naming the runtime directory. Cheap, and exactly the kind of thing nobody adds
   after the milestone ships.

6. **[IMPROVEMENT] The brief is silent on whether the Claude Code consolidator prompt changes, and
   the pointer is injection-shaped by the evidence's own measurement.** The truncation note records
   that *both* models treated the harness's spill notice — text in tool output directing the reader
   to act — as data to be flagged, not followed. Zikaron's pointer is the same shape: tool output
   saying "go read this file". A consolidator that correctly applies the untrusted-tool-output
   stance may balk, or improvise; a consolidator that doesn't is the poisoning surface working as
   feared. One truthful sentence in the shipped Claude consolidator prompt ("an over-large group
   arrives as `{spilled…}` naming a file in Zikaron's own runtime directory; that file is the
   payload; read it to its end before deciding anything") makes the behaviour specified rather than
   inferred — and unlike the reverted attempt's text, it would be *true*. The invariant list should
   then also pin the pointer's shape as unmistakable for a served group (e.g. it contains no
   `journal_entries` key), since "must not be mistakable" is currently prose with no assertion
   behind it.

7. **[IMPROVEMENT] Whether `Read` of the runtime path is permission-gated is unaddressed.** The
   spill path lives outside the project tree, and M16 measured Claude Code's three approval gates —
   the per-call gate answered by `permissions.allow`, which the installer writes. If a subagent's
   `Read` of `$XDG_RUNTIME_DIR/zikaron/…` prompts, the fix stalls mid-consolidation on exactly the
   turn it exists to unblock (recoverable, since D10 makes consolidation operator-invoked, but it
   should be a decision rather than a surprise). Concrete edit: one line in the design section
   naming the question and the candidate answer — whether the installer's `settings.local.json`
   `permissions.allow` needs a `Read(<runtime-dir>/**)` entry, settled by the done-when's
   end-to-end run and recorded in `harness.md` with the other gate measurements.

8. **[NITPICK] The scope-fence sentence about the two largest groups reads as if M18 leaves them
   broken; it doesn't.** Under the spill, a group whose anchor and members alone exceed the
   threshold still spills and is still fully readable — what is deferred is only whether such a
   group *ought* to be split for the consolidator's benefit. One clause ("the spill delivers them;
   whether they should be sharded instead is deferred") stops a fresh session from either
   special-casing them or believing the defect survives for them.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-13

**Summary judgment.** Every round-1 fix landed, and the ones I checked against reality hold: the
result-translation seam exists and is genuinely shared (`response_to_tool_result` in
`zikaron/mcp/errors.py`, called from both clients' `_call`), a served group really does carry a
`journal_entries` key so the pointer invariant discriminates, the D34 table really lacks the three
rows the brief says M18 adds, and the trimming/anchor figures now cited all appear in
`research/consolidation-payload-sizes.md`. On the direct question asked: **I agree string
segmentation is unnecessary** — the measurement refutes my round-1 premise (lines under the
per-read cap are never clipped; a ~20k-token line came back intact via targeted offset; the one
unrecoverable shape, a single line over the cap, was separately measured on the harness's own spill
file), and segmentation would have complicated the round-trip invariant for a case no observed
record is within an order of magnitude of. The loud write-time refusal is the right guard — but it
is currently a guard against an unnamed number, which is the one remaining blocker: the brief
polices the threshold's name/default/unit/ratio meticulously and then leaves the *line* bound, the
quantity the whole recovery guarantee rests on, as "the stated maximum" with nothing stated.

### Findings

1. **[BLOCKER] The line-length maximum is load-bearing, and it has no name, no number, and no
   unit — the invariant that cites "the stated maximum" is self-referential.** §"The design",
   "What the file must satisfy" (lines ~1176–1184) says "no single line may exceed the per-read
   cap"; invariant 1 (~1277) asserts "no line … exceeds the stated maximum"; the second invariant
   refuses records "too long to serialize within that maximum"; the done-when requires a record
   "whose serialized line is long". No sentence states the maximum. And the cap it derives from is
   **25,000 tokens** (measured, `Read`'s own notice), while a writer can only cheaply measure
   characters — the exact tokens-versus-characters conditionality the brief just resolved for the
   threshold, unresolved for this second quantity. Without a number the invariant cannot be
   asserted, the refusal cannot be implemented consistently, and "long" in the done-when is
   unquantified. Concrete edits, parallel to the threshold's own treatment:
   - Name a constant (e.g. `SPILL_MAX_LINE_CHARACTERS`), its default, and its unit (`len()` of the
     JSON-escaped line, stated as such). Same ratio argument: a line of L characters stays under
     the 25,000-token per-read cap only while L ÷ (chars/token) < 25,000; at the same ~1.19
     floor the threshold already uses, L ≤ ~29,000, so a default around 25,000 characters is
     defensible and clears the largest observed record (~1,877 tokens, roughly 7,000–12,000
     escaped characters) by 2× or better.
   - Disambiguate **"write time"**: it must mean *when the client serializes the spill file*, not
     `remember` time — the scope fence forbids bounding `content`, and the current phrasing
     ("`content` has no length bound at all, so a sufficiently long record … must fail loudly at
     write time") invites exactly the remember-time reading the fence prohibits.
   - State the refusal's surface and remedy: a loud tool error naming the offending record's uuid
     and its escaped line length, because unlike the threshold there is **no key the operator can
     lower** to make a single over-long record deliverable — the remedy is amending or retiring
     the record, and the error is the only thing that can say which one.

2. **[IMPROVEMENT] "Every tool result is covered" covers more than the brief specifies: the seam
   is shared with the *primary* client, and nothing tells a primary agent what a pointer is.**
   §"Spill at the client's shared result-translation seam" (~1165). `response_to_tool_result` is
   called from `primary.py:45` as well as from the consolidator's `_call` — so spill-at-that-seam,
   as written, spills a primary-mode `fetch` of several long records too. Everything downstream is
   consolidator-only: the prompt sentence, the `Read` grant, and the pointer-shape invariant (no
   `journal_entries` key discriminates against a served group, not against a `fetch` result). A
   primary agent handed a pointer has been told nothing, anywhere, about what it means. Concrete
   edit: one sentence scoping the spill to the **consolidator client mode** (mode is already a
   `build_server` parameter; every measured and every plausible over-threshold shape is
   consolidator-side), with the primary client's exposure named as unmeasured and out of scope —
   or, if both modes are meant, name where the primary learns the pointer's meaning and give the
   pointer a discriminator valid against `fetch`'s shape too.

3. **[IMPROVEMENT] The default's lower bound is still stated in a different unit than the key, and
   at plausible serialization overhead the "ordinary group pays nothing" claim may not hold.**
   §"The threshold is a config key" (~1202–1215). The upper (safety) bound now holds in the key's
   own unit — 32,000 ÷ 27,000 ≈ 1.19, floor argument correct, densest-measured 1.47 anchored on
   the harness side. But the lower bound compares the 32,000 **serialized**-character default
   against a **27,218 prose**-character median, and the brief itself says serialized is strictly
   larger by an unquantified margin. At 10–20% framing-plus-escaping overhead (uuids, keys,
   receipts, `\n` doubling, backslashes in code-bearing records) the median group serializes to
   roughly 30,000–33,000 — i.e. possibly *over* the default, in which case the ordinary group
   spills and the anchoring sentence is inverted. Concrete edit: one measured number — run
   `len(json.dumps(payload))` over the same 116 groups (the payload-sizes note already has the
   rows) and either state "serialized median N < 32,000, so the bound holds in the key's unit" or
   move the default; add the overhead factor to `research/consolidation-payload-sizes.md` so both
   bounds are commensurable with the key.

4. **[IMPROVEMENT] The done-when's "read to its end" is satisfiable in one `Read` call for every
   group in the observed store, so the end-to-end run never exercises the pagination the design
   rests on.** §Done-when (~1294–1301). The largest observed group is 69,265 prose characters —
   at observed prose ratios that is well under `Read`'s 25,000-token per-read cap, so the whole
   spill file arrives in a single call and the targeted-`offset` continuation path (the thing the
   206k-char probe measured, and the thing recovery actually depends on for a genuinely large
   corpus) runs only in the probe and the unit tier, never end to end. Concrete edit: either
   require the run's store to force a spill file over the per-read cap (so the transcript shows a
   capped first read followed by an offset continuation reaching the end sentinel), or state
   explicitly that the end-to-end run demonstrates one-call spill-and-read and multi-call
   pagination is accepted on the probe's evidence — a decision, not an accident of fixture size.

5. **[NITPICK] "12–33% of all candidates" silently excludes the note's 40,000-budget row (8%).**
   §Rejected, trimming (~1260–1265) versus the note's table (67/80/88/92% kept). The range matches
   budgets 25,000–35,000 only; the implicit reason — 40,000 prose characters plus framing
   approaches the measured 40,000–52,095 spill bracket, so that budget does not "fit reliably" —
   is sound but unstated, and a reader checking the citation finds 8–33%. One clause closes it.

6. **[NITPICK] "observed store prose runs 3.89–6.55" relabels an M14 measurement and leaves its
   tokenizer unnamed.** §Threshold (~1213–1214). The 3.89–6.55 range was measured in M14 for the
   gist-budget arithmetic, per style rather than over store prose, and (per FINDINGS item 3)
   against the deployed embedding tokenizer — while the cap's tokens are the harness model's. Not
   load-bearing (the 1.19 floor rests on the harness-side 1.47 measurement, and prose clears it
   under any plausible tokenizer), but this corpus names its quantities: cite the range as "prose
   measured in M14 at 3.89–6.55 chars per token (embedding tokenizer)" or drop the word "store".

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-13

**Summary judgment.** All six round-2 findings landed as described, and the two measurements were
worth insisting on: the threshold's two bounds now genuinely hold in the key's own unit (recomputed:
serialized median 29,258 < 32,000 above; 32,000 ÷ 27,000 ≈ 1.185 floor against 1.47 densest measured
below; and the 40,000 rejection is arithmetically right, 40,000 ÷ 27,000 ≈ 1.481 > 1.47), the 43/116
cost is stated plainly rather than hidden, and finding 4's trade is **accepted** — manufacturing a
store that forces multi-call pagination would test the fixture, the continuation path is
probe-measured and unit-covered, and the revisit clause is named. The line bound's arithmetic also
verifies (25,000 × 1.19 ≈ 29,750; 25,000 ÷ 17,275 ≈ 1.45), and the refusal's surface and remedy are
correctly specified. What remains is one real gap the derivation check surfaced — the line bound's
unit is ambiguous by up to 6× on non-ASCII content, and which reading is meant decides whether the
below-floor failure is loud or silent — plus two smaller commensurability residues. No blocker, but
the ambiguity sits in the milestone's central new constant, in the defect class (unit ambiguity
between the two halves of one argument) this project has already been burned by twice.

### Findings

1. **[IMPROVEMENT] "`len()` of the JSON-escaped line" does not pin the escaping, the two candidate
   escapings differ by 6–12× on non-ASCII content, and only one of them makes the floor argument
   hold — under the other, the below-floor failure is the silent loss this milestone exists to
   kill.** §"The design", line-bound paragraph (~1192–1198). `json.dumps` with `ensure_ascii=True`
   (the Python default) renders every non-ASCII character as a six-character `\uXXXX` escape —
   twelve for an astral character's surrogate pair — while such a character tokenizes at roughly
   1–4 tokens, so `len()` *over-counts* dense content and the floor holds for all non-ASCII by
   construction; and pure ASCII cannot fall below ~1.0 chars/token (a token spans at least one
   byte), so 25,000 characters sits at-or-under the 25,000-token cap for any content at all. Under
   `ensure_ascii=False`, `len()` counts code points: 10,000 emoji pass the refusal at 10,000 while
   tokenizing to roughly 20,000–40,000 tokens — a line **written rather than refused**, over
   `Read`'s cap, with an unreachable tail, on any CJK- or emoji-bearing store. The brief's "~1.19
   floor" sentence is true under the first reading and false under the second, and the note's
   17,275 measurement inherits the same ambiguity. This codebase already treats the mode as a
   measured decision (`zikaron/hook/main.py:109` records exactly this inflation against a harness
   budget), so the brief citing neither reading is an accident, not a policy. Concrete edits:
   - Pin the spill serialization's escaping in the line-bound paragraph — `ensure_ascii=True` is
     the reading under which every stated number is safe — and state it as load-bearing for the
     floor, not a formatting choice.
   - Add the honest-failure sentence this bound currently lacks and the threshold has: under
     `True`, dense non-ASCII content hits the **loud refusal** at much shorter prose (≈4,100 CJK
     characters of `content` reach 25,000 escaped), which is the acceptable failure; name that
     trade so it is a decision. If `False` is ever preferred for the consolidator's readability,
     the floor argument must be restated, because below it the failure is silent.
   - State in `research/consolidation-payload-sizes.md` which escaping produced 17,275, so the
     brief's 1.45× margin is denominated in the same escaping as the constant it defends.

2. **[IMPROVEMENT] The scope fence's "two groups" is counted against 40,000 prose characters, not
   against the 32,000-serialized threshold the sentence names.** §Scope fence (~1348–1351) says
   "the two groups … whose anchor and members alone exceed **the threshold**"; the note's 2-of-116
   figure (47,406 and 45,013) is measured at **>40,000 prose**. At the actual default — 32,000
   serialized, ≈29,800 prose at the measured 1.074× — the count is *at least* 2 and possibly more:
   the note reports nothing between the 7,515 median and the 40,000 bracket. Nothing functional
   depends on the count — every such group spills whole — but it is a number cited against a bound
   it was not measured at, the exact class round 2 cleared out of the threshold section. Concrete
   edit: either re-run the existing serialized pass for anchor+members against 32,000 and state
   that count, or re-denominate the sentence ("the groups whose anchor and members alone exceed
   40,000 prose characters — two in the observed store — …").

3. **[IMPROVEMENT] The consolidator-mode scoping is called load-bearing and is prose-only — give
   it the invariant the kiro rule got for the same reason.** §"Scoped to the consolidator client
   mode" (~1171–1178) versus §Invariants (~1310–1327). Round 1 flagged "kiro gets none of this" as
   implementable-as-a-branch prose and it gained an assertable invariant; the mode qualifier sits
   in the identical position — an implementer spilling at `response_to_tool_result` unqualified
   satisfies every listed invariant while handing primary-mode `fetch` results to an agent that
   has been told nothing about pointers. Concrete edit: add one invariant, "under the **primary**
   client mode an over-threshold payload is returned inline and unchanged — spilling is a property
   of the consolidator mode, asserted against `build_server`'s mode parameter."

4. **[NITPICK] Three wording residues in the assertable sections, each one line.** (a) ~1192:
   "default 25,000" — the refusal paragraph's own argument is that there is *no key* here, so
   "default" is the wrong word; say "a fixed constant, value 25,000" (the `GIST_MAX_CHARACTERS`
   parallel). (b) Invariant 2 (~1315) still says "refused loudly **at write time**" — the exact
   phrase the design section just disambiguated; say "at client serialization time" so the
   ambiguity cannot re-enter through a test name. (c) Done-when (~1332–1333): "approaches
   `SPILL_MAX_LINE_CHARACTERS`" is unquantified — pin a floor, e.g. "at least 17,275 characters,
   the longest observed in a real store". Also (d), cosmetic: the trimming bullet's continuation
   lines (~1297–1298) have lost their hanging indent.

5. **[NITPICK] Two evidence loose ends.** (a) `research/consolidation-payload-sizes.md` now
   carries two prose medians for the same 116 groups — 27,218 (§Per-group totals) and 27,206
   (§Serialized size) — with no sentence saying why the passes differ; reconcile or explain, since
   the note exists to be checked against. (b) The brief's "no group in the observed store produces
   a spill file over `Read`'s per-read cap" (~1337–1339) is stated without its arithmetic; one
   clause backs it: max serialized 73,331 characters at the store's own prose densities (≥3.89
   chars/token) is ≈18,900 tokens, under 25,000.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-13

**Summary judgment.** The byte re-denomination is the right call and I concede it beats my round-3
suggestion outright: it removes the ratio from both bounds instead of pinning an escaping to make
one ratio hold, it buys `ensure_ascii=False` readability for free, and the ratio-based 32,000
alternative genuinely fails a real user class (see finding 1). Round-3 findings 3, 4(a–c) and 5
all landed and verify — the mode invariant is word-for-word assertable, invariant 2 names
`SPILL_MAX_LINE_BYTES` at serialization time, the done-when floor is 17,275 bytes, the medians are
reconciled with the correction recorded, and the one-call arithmetic is stated. What keeps this
round from APPROVED: the proof's numeric floor is quoted at a precision no recorded measurement
supports and rounded in the anti-conservative direction; the "bytes bound tokens" premise is a
property of the harness's counter presented as arithmetic; round-3 finding 2 (the scope fence's
count at the wrong bound) is claimed applied but did not land; and the re-denomination made one
invariant's rationale clause false on the brief's own numbers. All are one-sentence-to-two-line
edits — this is convergence-close.

### Findings

1. **[IMPROVEMENT] The attack, answered: "a token spans at least one byte" is a property of the
   harness's token counter, not arithmetic over content — one sentence naming it as the assumption
   turns an overclaim into the proof it wants to be.** §"Bytes need no ratio" (~1199–1206) says
   "tokens are therefore bounded by bytes for any content whatsoever" and §default (~1242–1243)
   says "no content can break it … bounded by construction". Verdict on the substance: **the
   premise holds for every counting scheme this corpus has observed or that is plausible for this
   harness.** Byte-level BPE — Claude's tokenizer family — partitions the input's bytes into
   non-empty spans, so tokens ≤ bytes by construction; both measured pairs satisfy it (70,848
   tokens over 104,179 ASCII chars = bytes; 31,183 over 94,328); a chars÷4 estimator satisfies it
   4× over; even M16's UTF-16-code-unit counting satisfies it (a unit is never more than… every
   UTF-8 character carries at least as many bytes as UTF-16 units: 1≥1, 2–3≥1, 4≥2). **The one
   violating class that exists:** counters that Unicode-normalize before counting.
   NFKC-normalizing tokenizers (SentencePiece-style, e.g. T5's) expand compatibility characters —
   U+FDFD is 3 UTF-8 bytes and normalizes to a phrase of dozens of tokens — and there byte-bounds-
   tokens fails outright. No evidence suggests Claude Code's counter normalizes, and byte-BPE does
   not; but the brief currently rests a "proof … no content can break it" on an unstated empirical
   property of an unobserved counter. And the failure directions differ by bound, which is worth
   stating because one of them is already covered: on the **threshold**, a violated premise
   presents as the original loud inline refusal, remedied by lowering the key — the existing
   honest-failure paragraph (~1252–1256) covers it if its trigger is widened from "if the harness
   ever lowers its cap below 27,000 tokens" to "…or its counter ever assigns a payload more tokens
   than bytes"; on the **line bound**, it presents as a spill file with a line `Read` cannot
   deliver, where the nearest measurement (the single-line spill file, `offset=1, limit=1`)
   **refused loudly** rather than clipping silently. Concrete edit: one sentence after "for any
   content whatsoever": "— for any counter that does not expand the input before counting, which
   byte-level BPE cannot and no observed measurement contradicts; a counter that violated this
   would present as the loud inline refusal below, never silent loss" — plus the one-clause
   widening of the honest-failure sentence. **On the direct questions asked:** the 58% price is
   acceptable but see finding 3 for what it is actually paying for; and **no, ratio-based 32,000
   is not the better engineering call** — at `ensure_ascii=False` a CJK- or emoji-heavy store
   serializes at ~1.0 chars/token, genuinely below the 1.185 floor, so the ratio default fails an
   entire user class (non-Latin-prose stores) recoverably-but-confusingly, and the operator asked
   for a number that does not need revisiting. The deviation is right.

2. **[IMPROVEMENT] The proof's floor — ">27,211 tokens (delivered)" — is a derived number quoted
   as a measurement, rounded in the anti-conservative direction, and recorded in no evidence
   file.** §default (~1238–1240). The truncation note carries only "~27,000–35,000 tokens"
   (§"Not measured here") and "above ~27,000 tokens"; 27,211 and 35,438 appear nowhere outside the
   brief. They derive from dividing 40,000 and 52,095 chars by the *rounded* ratio 1.47; the
   measured ratio is 70,848/104,179 = 0.68006 tokens/char, giving **≈27,202** and **≈35,428** —
   so the quoted floor overstates the derived one by 9 tokens, in the direction that flatters the
   proof, and the true margin over the 27,000-byte default is ≈202 tokens (0.75%), which is thin
   enough to deserve being a recorded fact rather than an accident of rounding. The derivation
   also silently assumes the MCP-result cap counts the way `Read`'s notice does — the only token
   accounting the harness exposes, and the same assumption the note itself makes, but currently
   stated by neither document. This is the round-1-finding-3 class again: the brief's evidence
   line says the truncation note "carries every harness measurement", and these two numbers are
   not in it. Concrete edits: add two lines to the note's §"structural" deriving the token bracket
   explicitly (40,000 × 70,848/104,179 ≈ 27,202; 52,095 × same ≈ 35,428; assumption: the MCP cap
   and `Read`'s notice share one accounting, framing overhead constant and cancelling); cite
   "≈27,200, derived" in the brief rather than ">27,211, measured"; and state the ≈200-token
   margin in the sentence that claims the proof, so the closeness is on the record.

3. **[IMPROVEMENT] The 58% is paying for the bracket's looseness, not for the byte denomination —
   say so, or a future session re-litigates the unit to fix a spill rate one probe session
   fixes.** §cost (~1245–1250). Nothing was probed between 40,000 and 52,095 chars — the bracket
   is one bisection away from tighter, with the probe harness already described in the note. A
   delivered point at ~47,000 chars of the same filler would raise the proven floor to ≈32,000
   tokens and carry the **identical proof** at a 32,000-byte default — 43/116 (37%) — buying back
   nearly all 21 points at zero assumption cost. There is a real counterargument (a bisected floor
   hugs a cap the harness can change per version, where 27,000 sits robustly under any plausible
   value, and the key is operator-raisable), so shipping 27,000 is defensible; but the brief
   currently reads as though 58% is the intrinsic price of proof-over-ratio, and it is not — it is
   the price of an unmeasured bracket. One sentence recording that, with the bisection named as
   the future remedy alongside "raise the key", closes it. Related and concrete: **invariant 3's
   rationale clause "the ordinary case pays nothing" (~1319–1320) is now false at the default on
   the brief's own numbers** — the median group serializes to 29,150 bytes > 27,000, so on the
   observed store the *majority* case spills. Re-word to "an under-threshold payload pays
   nothing", and note somewhere that spill being the majority path on the observed store is an
   argument *for* the done-when exercising it end to end, not a defect.

4. **[IMPROVEMENT] Round-3 finding 2 is claimed applied and did not land: the scope fence still
   counts "two groups" against "the threshold", a bound they were never measured at — and the byte
   re-denomination widened the gap.** §Scope fence (~1356–1360): "The two groups in the observed
   store whose anchor and members alone exceed the threshold". The note's 2-of-116 (47,406 and
   45,013) is measured at **>40,000 prose characters**; the threshold is now **27,000 serialized
   bytes** (≈25,100 prose at the measured 1.074×), at which the anchor+members count is unknown
   and at least 2 — the note reports nothing between the 7,515 median and 40,000. Dropping the
   parenthetical sizes removed the numbers but kept the count-at-wrong-bound claim. The fix is
   still the one-line re-denomination: "the groups whose anchor and members alone exceed 40,000
   prose characters — two in the observed store; sizes in `research/consolidation-payload-sizes.md`
   — need no special handling here, and neither does any smaller group the lower threshold now
   also spills whole".

5. **[NITPICK] Residues of the re-denomination and one unapplied round-3 item, each a line.**
   (a) ~1233–1235: "the group-size figures in `research/consolidation-payload-sizes.md` are
   prose-only floors" — no longer true of the note, which now carries the serialized-byte pass the
   brief itself quotes 67/116 from; say "the *prose* figures there are floors; the byte pass is
   what the 58% below reads from". (b) ~1201–1203: the two consistency pairs are ASCII filler, so
   characters and bytes coincide — add the parenthetical, since the sentence is offered as
   evidence for a claim about bytes. (c) ~1344: "serializes to 73,331 **bytes**" mislabels the
   note's *character* figure (the byte figure is 73,184), and the spill file's on-disk size is
   larger than either (pretty-printing adds indentation — cheap in tokens, not in bytes); also
   "at that store's own prose density (≥3.89 characters per token)" re-attaches M14's per-style
   embedding-tokenizer measurement to the store, the exact relabel round-2 nitpick 6 removed —
   "at prose densities measured in M14 (≥3.89 chars/token)" fixes both. (d) Invariant 1 (~1314)
   still says "the stated maximum" from the era when nothing stated it; name
   `SPILL_MAX_LINE_BYTES` and the unit. (e) Round-3 4(d) unapplied: the trimming bullet's
   continuation lines (~1298–1300, "characters plus framing…", "candidates, and") still lack
   their hanging indent.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-13

**Summary judgment.** The round-4 substance landed and the arithmetic that was asked to be checked
is almost entirely right: 44,000 × 0.68006 = 29,922.6 ≈ 29,923 and 50,012 × 0.68006 = 34,011.2 ≈
34,011 (and 70,848 ÷ 104,179 = 0.680060, so the ratio itself is honest); the margin is 29,923 −
27,000 = 2,923 ≈ 2,900 tokens and 2,923 ÷ 29,923 = 9.77% ≈ 9.8%; 67/116 = 57.8% ≈ 58%; the median
sits (29,923 − 29,150) ÷ 29,923 = 2.58% under the proven floor, so "within 3%" holds; 24,000 ÷
17,275 = 1.389 ≈ 1.39×; 73,184 ÷ 3.89 ≈ 18,813 ≈ 18,800. The counter-assumption sentence, the
widened honest-failure trigger, the ASCII parentheticals, the scope-fence re-denomination, the
invariant-3 rewording, the prose-floors correction and the 73,184-byte figure all verify against
the files. And the bisection refuting my round-4 premise is exactly the right kind of answer — the
measurement is better than my argument was, and the brief records it so it is not re-run. What
blocks this round is one number the refutation itself introduced: **51% cannot be reconciled with
the note's own median**, and neither the count nor the threshold behind it is recorded anywhere a
reader could check. Beyond that, the second bisection left a trail of now-superseded brackets in
the truncation note and one in the brief, and three round-4 nitpick residues did not land.

### Findings

1. **[BLOCKER] The 51% is arithmetically impossible against the note's own median, and its
   underlying count and threshold are recorded nowhere.** Brief ~1257–1259 ("the spill rate moved
   only 58% → 51%"); note lines 70–73 (same claim, plus "lifts a provable byte threshold by
   ~2,700"). The problem is order statistics, not rounding: 51% of 116 is 59 groups, and for 59
   groups to *exceed* a threshold, that threshold must lie **below the 58th-smallest value, i.e.
   below the median**. The note's own byte pass puts the median at **29,150 bytes** — so at any
   threshold at or above 29,150, at most 58 groups (50.0%) can spill. The lifted provable
   threshold the sentence describes is ~29,700–29,923 bytes (27,000 + ~2,700; the floor itself is
   29,923), which is *above* the median, so the count there is ≤58 and the rate ≤50%. Both files
   therefore assert a pair (51%, ~29,700) that cannot both be true alongside the recorded 29,150
   median. Possible innocent causes, each of which changes the fix: an off-by-one or ≥-versus->
   slip in the recount; the recount run against a **different pass of a live store** than the one
   the median was measured from (`~/Trading/LeibaTrader` is a working store and can have grown
   between the byte pass and the bisection); or the recount done against the character pass
   (median 29,258 — same impossibility). Concrete edits: recount at the exact threshold the
   sentence means, and **add the row to the note's byte-threshold table** (currently 27,000 /
   32,000 / 36,000 only) with the threshold, the count out of 116, and — if the store was
   re-measured — the pass date, per the note's own "recorded rather than quietly fixed" practice;
   then correct "51%" in both files to the verified figure. Note the conclusion is untouched
   either way: if the true count is ≤58, the bisection bought *even less* than claimed and the
   stay-at-27,000 decision gets stronger.

2. **[IMPROVEMENT] The second bisection superseded three statements inside the truncation note
   itself, so the note now gives two different brackets depending on which line a reader lands
   on.** This is the sweep the round was asked for, and these are the hits: (a) line 26–27, "the
   threshold sits between 40,000 and 52,095 characters of this filler" — directly beneath a table
   showing 44,000 delivered and 50,012 spilled; still true as a superset but it understates the
   note's own data, and it is the sentence a skimming reader takes as the bracket. Say "between
   44,000 and 50,012 characters". (b) lines 53–54, "40,000 chars … delivered intact … so the MCP
   result cap is **above ~27,000 tokens**" — the stale floor, derived by the rounded-1.47 method
   that §"The cap in tokens, derived" was written to replace. Update to the 44,000 point and
   ≈29,900, or reduce the bullet to the structural claim it exists for (cap > `Read`'s 25,000)
   with a pointer to the derivation section. (c) line 138, "bracketed to ~27,000–35,000 tokens" in
   §"Not measured here" — should read ≈29,900–34,000, the derived bracket the note itself now
   computes. A fresh session reading (b) or (c) would re-derive 27,202 and "correct" the brief's
   29,923; that is the exact both-things-said defect this corpus has been burned by.

3. **[IMPROVEMENT] The brief's trimming rejection still cites the superseded bracket as "the
   measured 40,000–52,095 spill bracket", and the tightened bracket weakens its arithmetic.**
   Brief ~1310–1312: "a budget low enough to fit reliably — 35,000 or below, since 40,000 prose
   characters plus framing runs into the measured 40,000–52,095 spill bracket". Two problems.
   First, the bracket is now 44,000–50,012; this is the one place the brief still quotes the old
   one as current (the researcher's own round-5 request — "nothing still cites the superseded
   bracket" — fails here). Second, under the new bracket the sentence's arithmetic no longer
   quite closes: 40,000 prose × the measured median framing (1.074×) is ≈42,960 serialized
   characters, which is *below* the 44,000-delivered point — only max framing (1.165× → ≈46,600)
   lands inside the bracket. The conclusion survives, because "fit reliably" fails on max-framed
   groups, but the stated reason should say that: e.g. "35,000 or below, since 40,000 prose
   characters at the measured framing (1.074× median, 1.165× max) serializes to ≈43,000–46,600
   characters against a 44,000-delivered / 50,012-refused bracket — inside it at the high end, so
   that budget does not fit reliably". Same edit restores the hanging indent finding 5(c) below
   re-flags.

4. **[IMPROVEMENT] "No provable threshold moves this far, a third bisection is not the remedy"
   overreaches the recorded evidence — the true reason is the margin trade, and the paragraph
   should carry it.** Brief ~1259–1261. What the evidence establishes: the *second* bisection
   bought ~7 points, and the median cluster sits just under the current proven floor. What it
   does not establish: that a third probe is worthless. The unprobed residue is 44,000–50,012
   characters ≈ 29,923–34,011 tokens; if a probe at ~47,000 delivered — which nothing recorded
   rules out, roughly a coin flip — the provable threshold reaches ~32,000 bytes, where the
   note's own table says **43/116 = 37%** spill, i.e. a further ~13 points. The argument that
   actually kills the third bisection is the one the researcher's own summary makes and the brief
   omits: any threshold hugging the measured floor trades the 9.8% protection against the harness
   changing its cap per version, which is the property the default was chosen for — at a 0.1%
   margin the key stops being future-proof, and future-proof is this section's heading claim.
   Concrete edit: replace "So no provable threshold moves this far, a third bisection is not the
   remedy" with "A tighter bracket could still buy points — the note's table shows 37% at a
   32,000-byte threshold, provable if ~47,000 characters delivers — but only by hugging the
   measured floor, trading the 9.8% margin that makes the default future-proof for spill points;
   that trade, not the bracket, is why a third bisection is not the remedy."

5. **[NITPICK] Three round-4 residues claimed in the aggregate as applied but absent from the
   file, plus one new wording slip.** (a) Invariant 1 (~1326) still opens "No line in the spill
   file exceeds **the stated maximum**" — round-4 5(d); now that the constant exists, write "No
   line in the spill file exceeds `SPILL_MAX_LINE_BYTES`, counted in UTF-8 bytes of the
   serialized line". (b) ~1357–1358 still says "at **that store's own** prose density (≥3.89
   characters per token)" — round-4 5(c)'s relabel half; the 3.89–6.55 range is M14's per-style
   measurement under the embedding tokenizer, never measured on that store; write "at prose
   densities measured in M14 (≥3.89 chars/token, embedding tokenizer)". (c) Third flag (rounds 3
   and 4): the trimming bullet's continuation lines ~1311–1312 ("characters plus framing…",
   "candidates, and") still lack their two-space hanging indent — the finding-3 rewrite above is
   the occasion to fix it, since the sentence is being retyped anyway. (d) New, from the
   re-denomination edit: the scope fence (~1369–1370) now says "The **two groups** … whose anchor
   and members alone exceed 40,000 prose characters — **two of them**, sizes in …" — the count
   stated twice in one sentence; drop the leading "two": "The groups in the observed store whose
   anchor and members alone exceed 40,000 prose characters — two of them, sizes in …".

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-13

**Summary judgment.** The round-5 blocker is resolved and the researcher's own diagnosis of it is
the correct one: the measurement was right, the prose paired a rate with the wrong threshold, and
the fix — tabulating the full ladder so every rate carries its threshold — is the durable kind. I
recounted everything the round asked me to weight, and it all holds (detail below): the ladder is
internally consistent as order statistics, consistent with the median's two straddling values,
consistent across the character and byte passes, and every percentage and margin in both files now
recomputes from the table. Findings 2–5 all landed and verify against the files, including the
corrected arithmetic. The sweep found three wording residues in the evidence notes, all trivial;
nothing remaining would change a number, a decision, or a reader's action.

**The verification record, so the next session need not re-run it.**
- Median: (29,025 + 29,276) ÷ 2 = 29,150.5 ✓. At 29,000 — below the 58th value 29,025 — ranks
  58–116 exceed, = 59 groups, 59/116 = 50.9% ≈ 51% ✓. All five ladder rows: 67/116 = 57.8% ≈ 58%;
  54/116 = 46.6% ≈ 47%; 43/116 = 37.1% ≈ 37%; 29/116 = 25.0% ✓; and the ladder is monotone
  (67 ≥ 59 ≥ 54 ≥ 43 ≥ 29) ✓.
- Cross-pass consistency, which the round did not ask for but which would have caught a recount
  run against the wrong pass: at every threshold the two tables share, the byte count is ≤ the
  character count, as it must be (`ensure_ascii=True` characters ≥ UTF-8 bytes for any content):
  43 ≤ 43, 29 ≤ 29; byte median 29,150.5 ≤ char median 29,258, within the stated 0.4%; byte max
  73,184 ≤ char max 73,331 ✓.
- Margins and derivations: 70,848 ÷ 104,179 = 0.68006 ✓; 44,000 × 0.68006 ≈ 29,923 ✓; 50,012 ×
  0.68006 ≈ 34,011 ✓; 40,000 × 0.68006 ≈ 27,202 ✓. Margins over the 29,923-token floor: 29,900 →
  0.08% ≈ 0.1%, 29,000 → 3.08% ≈ 3.1%, 27,000 → 9.77% ≈ 9.8% ✓; median 2.58% under the floor, so
  "within 3%" holds ✓; 58% − 47% = the brief's "eleven points" ✓.
- Findings 2–5 landed: the bracket sentence reads 44,000–50,012; the structural bullet cites
  44,000 and ≈29,900 with a pointer to the derivation section; §"Not measured here" reads
  ≈29,900–34,000; the trimming rejection reaches the bracket via maximum framing (40,000 × 1.165
  = 46,600, inside 44,000–50,012) with its hanging indent restored; invariant 1 names
  `SPILL_MAX_LINE_BYTES` and its unit; the density is attributed to M14 with its tokenizer named;
  the scope fence states the count once, at the bound it was measured at. All ✓. The finding-4
  rewrite is faithful: the brief now concedes the points a tighter bracket buys — 47% at 29,900,
  37% at 32,000 if ~47,000 delivers — and rests the rejection on the 9.8% margin, which is the
  defensible argument. No superseded bracket or stale floor survives outside this review file's
  own audit trail.

### Findings

1. **[NITPICK] "a threshold below 29,025 is exceeded by 59 groups" is falsified by the same
   table's own 27,000 row.** `research/consolidation-payload-sizes.md` line 87. Any threshold
   below 29,025 is exceeded by *at least* 59 groups — at 27,000 the table itself says 67. The
   sentence means thresholds just under the 58th value but quantifies over all of them, and this
   note's stated purpose is to be checkable. One word: "is exceeded by at least 59 groups".

2. **[NITPICK] A duplicated agent left by the finding-2(c) edit.**
   `research/claude-code-mcp-result-truncation.md` lines 139–140: "never stated numerically by
   the harness by the notice" — the edit inserted "by the harness" without removing the original
   "by the notice". Drop one of the two phrases.

3. **[NITPICK] The payload-sizes note's header still says "Sizes are prose characters … so every
   figure here is a floor", which the serialized sections added since contradict.**
   `research/consolidation-payload-sizes.md` lines 5–6. The byte table is not a floor — it is the
   exact unit the threshold is compared against, which is its whole point. Scope the sentence:
   "Sizes in the first two sections are prose characters … and are floors; §'Serialized size'
   makes them commensurable with the threshold's own unit."

VERDICT: APPROVED

## Round 7 — 2026-09-13 — the artifact changes: this round reviews the implementation, not the brief

Rounds 1–6 reviewed and approved `design/build-plan.md` §M18. This round checks the shipped code
against that brief as its specification. Read: `zikaron/mcp/{spill,consolidator,server,connection,
errors,main}.py`, `zikaron/harness/spec.py`, `zikaron/install/{assets,entries}.py`,
`zikaron/core/config/keys.py`, `zikaron/service/paths.py`, `tests/test_mcp_spill.py`,
`tests/test_harness_table.py`, the appended `tests/test_install_assets.py` class, the rewritten
grant test in `tests/test_install_targets.py`, the `bytes` arm in `tests/test_config_keys.py`, and
the design additions in `architecture.md`, `harness.md`, `schema.md`, `write-policy.md`.

**Summary judgment.** The core mechanism is faithful to the brief and the parts I checked hardest
hold: the line refusal runs against the *rendered* document (the right quantity — an escape
expansion is visible to it), `ensure_ascii=False` plus the byte bound is exactly the round-4
argument implemented, the pointer discriminates (`journal_entries` absent, asserted), round-trip is
compared as parsed objects, the mode scoping is structural (`register_primary_tools` takes no
policy, asserted by signature), kiro's config and prompt are unchanged (empty fills, golden-bytes
test), `O_EXCL` with the mode supplied closes the umask window the filesystem-security row
describes, and both design-record additions I could check against code are accurate. What blocks
approval: the brief's Lifetime paragraph is silently unimplemented while a docstring asserts a
*different* lifetime policy as though decided, and the milestone's kiro invariant is covered only at
the `SpillPolicy`-object level — `server._spill_policy`, the one function that turns `HarnessSpec`
data into the gate, has no test at all, so the mutations that matter most pass the suite.

### Findings

1. **[BLOCKER] The brief's Lifetime paragraph is not implemented, and `_write`'s docstring asserts
   the opposite policy as decided.** Brief ~1228–1233: "the client unlinks its previous spill when
   writing the next and unlinks on exit." Grep over `zikaron/mcp/` finds no `unlink` and no
   `atexit`; nothing tracks a previous spill and nothing runs at exit. Meanwhile
   `spill._write`'s docstring (~159–161) says "the cost of a stale file is one tmpfs page until
   reboot" — presenting no-cleanup as the design, and understating it: the largest observed group
   serializes to ~73 KB (≈18 pages), and at the note's own 58%-of-116 spill rate one consolidation
   run leaves several MB of verbatim record prose in RAM until reboot. This is the exact
   priority-4 class (a docstring asserting what the code does not do — here, what the *brief* says
   it does), and the standing note applies: where code and design disagree, one of them is a bug.
   Two acceptable resolutions, either explicitly:
   - **Implement unlink-on-exit** (an `atexit` hook in the consolidator path unlinking what this
     process wrote — the pid is already in every filename, so a `*-{pid}-*.json` glob scoped to
     this process is cheap and safe), and **amend the brief's unlink-previous clause with the
     reason it should not be built as written**: a `merge`/`promote`/`discard` **conflict**
     response can itself spill, and unlink-on-next-spill would then delete the *group's* file
     while the consolidator is mid-way through dispositioning that same group from it. The
     unique-name rule the code does implement protects overwrite; unlink-previous would
     reintroduce deletion. That hazard is real and is a good reason — but it must be recorded in
     the brief (withdraw-in-place), not silently substituted in a docstring.
   - Or amend the brief to state no-cleanup-until-reboot as the decision, with the erasure
     procedure named as the manual remedy — and fix the "one tmpfs page" claim either way.

2. **[BLOCKER] `server._spill_policy` is untested, so the brief's kiro invariant is proven only
   against a hand-built `SpillPolicy`, not against the wiring that produces one.** Brief
   invariant: "Under a kiro-detected client an over-threshold payload is returned inline, **and
   this follows from `HarnessSpec` data**." `tests/test_mcp_spill.py` covers `enabled=False →
   inline` (and the researcher's mutation confirmed `spill.apply` honours the flag), and the
   installer tests pin the *field values* transitively — but nothing anywhere calls
   `_spill_policy` (grep: `SpillPolicy` appears in tests only in `test_mcp_spill.py`, and
   `consolidator_can_read_files` appears in no test at all). Consequently all three of these
   mutations leave the 1755-test suite green: `enabled=True` unconditionally (kiro consolidator
   handed a pointer it has no tool to open — the original stall, rebuilt), `threshold_bytes=10**9`
   (spill never fires anywhere), `directory=connection.location.store_dir` (spill lands inside the
   project tree, which the brief's Location paragraph exists to prevent). Concrete edit: a test
   (in `test_mcp_spill.py` or a small `test_mcp_server.py` addition) that builds a
   `ServiceConnection` on a tmp scope dir and calls `server._spill_policy` under monkeypatched
   detection — kiro (marker unset) asserting `enabled is False`, Claude Code (`CLAUDECODE=1`)
   asserting `enabled is True`, and in both: `threshold_bytes == 27_000` (the shipped default,
   from a store with no override) and `directory == connection.location.runtime_dir`. Then break
   each of the three wires to confirm it fails.

3. **[IMPROVEMENT] The two new D34 rows have no drift test, making `consolidator_can_read_files`
   the only `HarnessSpec` field the table guard does not cover.** The brief cites `harness.md`'s
   rule — every harness-varying value is a field "**with a D34 table row**, and a drift test
   enforces it" — and the rows landed (`harness.md` lines 70–71, both accurate). But
   `tests/test_harness_table.py`'s `TestTheCodeTableMatchesTheDesignTable` has a `test_<field>`
   method for every other spec field and none for this one, so the design can flip kiro's cell to
   "yes" (or Claude Code's to "no") while the code stays put, and the gate stays green — the
   precise drift the fail-closed extractors exist to prevent. Concrete edit: add
   `test_consolidator_reads_files` reading the "Consolidator reads files" row and asserting the
   cell's leading `**no**`/`**yes**` against `spec.consolidator_can_read_files`, with the same
   raise-on-unparseable posture as `_identifier`.

4. **[IMPROVEMENT] The threshold is compared against a different serialization than the one it was
   calibrated on and the one it is documented as measuring.** `spill.apply` line 102–103 measures
   `json.dumps(result, ensure_ascii=False, indent=2)` in UTF-8 bytes. The brief (~1235–1239) and
   `schema.md`'s key row say the unit is bytes of "the serialized result — the bytes the client
   would otherwise return", and the 58%/29,150-median table it was calibrated against
   (`research/consolidation-payload-sizes.md` §"Serialized in UTF-8 bytes") was measured on
   *compact* `json.dumps`. Pretty-printing adds indentation and newlines the inline path never
   sends — the note itself records that indentation is "cheap in tokens, not in bytes" — so the
   deployed decision quantity sits a few percent above the calibrated one, and the effective spill
   rate is correspondingly above the stated 58%. Direction is safe (over-spilling costs one
   `Read`, never correctness, and the 27,000-token proof still holds because compact ≤ indented),
   but this is the name-the-quantity class this corpus polices. Concrete edit, either: compare
   `len(json.dumps(result, ensure_ascii=False).encode("utf-8"))` (the note's own pass) for the
   threshold decision and render the indented document only on the spill path — same dumps count
   per call; or keep the code and re-denominate the three design sentences as "UTF-8 bytes of the
   pretty-printed spill document, an upper bound on the inline result", with one clause noting the
   note's table under-counts the deployed quantity by the indentation overhead.

5. **[IMPROVEMENT] The refusal and the write failure both leave the ToolError channel the codebase
   itself declares is the only guaranteed one — and the refusal's stated remedy is addressed to an
   actor who cannot perform it.** `zikaron/mcp/errors.py` routes every model-facing failure
   through `ToolError`, quoting its contract ("shown regardless of `mask_error_details`").
   `PayloadLineTooLongError` subclasses plain `Exception`, and `_write`'s `OSError` (ENOSPC on a
   RAM-backed tmpfs is a real event) propagates raw — both escape `_call` outside its
   `try`/`except`, so whether the uuid-naming message the brief requires ("the error is the only
   thing that can say which one") actually reaches the model depends on FastMCP's masking default
   staying off. Also: the message says "Amend or retire that record", but its recipient is the
   consolidator, which has neither verb (D32); the run self-limits via `max_group_serves`, but the
   model is given an instruction it cannot execute and no instruction it can. Concrete edits: in
   `consolidator._call`, wrap the spill step —
   `except spill.PayloadLineTooLongError as error: raise ToolError(str(error)) from error` and
   `except OSError as error: raise ToolError(f"could not write the spill file: {error}") from
   error` (keeps `spill.py` fastmcp-free); reword the refusal's tail to name the right actor,
   e.g. "…this payload cannot be delivered whole. Report the uuid — amending or retiring it needs
   the primary agent or the operator — and continue with the run."; and have `_write` unlink its
   partial file on a failed write, since a half-written spill on a full tmpfs otherwise compounds
   the very ENOSPC that created it.

6. **[IMPROVEMENT] `_write`'s `mkdir(parents=True, exist_ok=True)` blind-creates the runtime
   directory with no mode, against the filesystem-security section's own rule.**
   `spill.py` line 162. `architecture.md` §"Filesystem security" states the `/tmp/zikaron-<uid>`
   fallback is "**validated before use**, not merely created" and calls blind `mkdir` of a
   predictable `/tmp` path the classic symlink attack; `connection.py`'s comment on `runtime_dir`
   says "already vetted for the socket" — which is true only of whichever process spawned the
   service, and the vetting is not re-run here. In practice the directory exists whenever
   `apply` runs (the socket the result just arrived over lives in it), so the `mkdir` is
   effectively test convenience — but as written it is a second creation path that skips the vet
   and would create at umask default. Concrete edit: `directory.mkdir(mode=0o700, parents=True,
   exist_ok=True)` at minimum, plus one comment sentence stating why full vetting is not repeated
   here (the file itself is `0600`, `O_EXCL`, unpredictable name, and the directory provably
   existed moments ago as the socket's home) — or drop the `mkdir` and have the tests create the
   directory, making the dependency explicit.

7. **[IMPROVEMENT] The erasure procedure promises store-scoped deletion the filenames cannot
   deliver.** `write-policy.md` lines 230–235: "delete **this store's** spill files from the
   runtime directory". The runtime directory is shared by every store of the user
   (`paths.runtime_dir` has no store component; sockets disambiguate by hash), and a spill file is
   named `{tool}-{pid}-{random}.json` — nothing identifies which store it came from, so the
   instruction as written cannot be followed. Concrete edit, either: prefix the filename with the
   store's existing socket hash (`{socket_hash}-{tool}-{pid}-{random}.json` — `StoreLocation`
   already computes it), which makes "this store's" literally globbable and gives finding 1's
   unlink-at-exit a second safe scope; or reword the procedure to "delete every `*.json` file
   there — all are transient spill copies and deleting a live one costs at most one re-serve."
   While editing: the row's `<verb>-` pattern reads as `merge-…` but the actual names are the wire
   methods (`next_group-…`, `apply_merge-…`); spell one example literally so an operator's glob
   matches.

8. **[NITPICK] `_uuid_of_longest_value` measures raw string bytes while the refusal measures
   rendered-line bytes, so escape-heavy content can name the wrong record.** `spill.py` lines
   132–153 versus 119–129. A `content` heavy in backslashes, quotes or newlines renders up to 2×
   its raw length, so with two records near the bound the attribution can point at the one that is
   *not* over. Best-effort is documented, but the docstring frames it as "may name none", not "may
   name the wrong one". Two-line fix: rank values by
   `len(json.dumps(value, ensure_ascii=False).encode("utf-8"))` so the walker and the refusal
   measure the same quantity.

9. **[NITPICK] Round 6's nitpick 2 is still unapplied:** `research/claude-code-mcp-result-
   truncation.md` lines 139–140 still read "never stated numerically by the harness by the
   notice". One of the two phrases must go.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-13

**Summary judgment.** All nine round-7 findings landed, and I verified each against the current
code rather than against the researcher's summary — the two blockers are genuinely fixed, the
withdrawal is recorded in the brief where a docstring had been quietly substituting for it, and
the filename and compact-encoding changes left nothing stale that I could find across the code,
the tests, or the four design documents. What keeps this from APPROVED is one gap in the new
wiring tests, found by asking this round's own question ("would each fail if its subject were
wrong?") of the one test whose docstring answers differently than its assertion does: the
threshold test stays green if the config wire is replaced by a hard-coded 27,000 — the exact
mutation its docstring says it exists to catch — and the whole wiring class is the suite's first
default-tier dependency on a file in the developer's home directory. Both halves are a few lines.

**The verification record, per round-7 finding, so the next session need not re-run it.**
- *Finding 1 (blocker):* `zikaron/mcp/spill.py` 204–225 — `_written` appended on successful write
  only (after the partial-file cleanup path), `_unlink_written` swallows per-file `OSError`
  without stranding the rest, `atexit.register` at import. The misleading "one tmpfs page"
  docstring is gone; `_write`'s docstring (174–189) now states the unique-name-plus-unlink-at-exit
  policy and the conflict-response reason unlink-previous would be wrong. The brief records the
  withdrawal in place (`build-plan.md` 1233–1243), with the Lifetime paragraph (1228–1231) now
  claiming only what ships. `write-policy.md` 236 correctly scopes the manual remedy to "what a
  killed one leaves" — honest about `atexit` not surviving SIGKILL/SIGTERM-without-handler. ✓
- *Finding 2 (blocker):* `TestTheWiringThatProducesAPolicy` (`tests/test_mcp_spill.py` 179–221)
  targets `server._spill_policy` on a real `ServiceConnection`. I re-derived all three round-7
  mutations against the assertions: `enabled=True` unconditionally fails `test_kiro_gets_no_spilling`
  (conftest's autouse harness-env scrub plus the explicit `delenv` makes detection fall through to
  the unmarked spec — verified `_fallback_harness` derives kiro); `threshold_bytes=10**9` fails the
  threshold test; `directory=store_dir` fails both assertions of the directory test. The
  fourth-mutation test (223–252) is the right shape: a real subprocess, `check=True` so the
  script's own asserts cannot pass vacuously, filename format pinned (`k-next_group-` prefix), and
  removing `atexit.register` demonstrably leaves the file behind. ✓
- *Finding 3:* `tests/test_harness_table.py` 78–89 and 160–176 — `_leading_bold` raises on a cell
  with no bolded word, the test additionally rejects any answer outside `{yes, no}`, and the D34
  row (`harness.md` 71) opens `**no**`/`**yes**` exactly where the extractor looks. Flipping
  kiro's cell fails it. ✓
- *Finding 4:* `spill.apply` 106–122 — threshold decided on `json.dumps(result, ensure_ascii=False)`
  compact bytes, the indented document rendered only after the decision, pointer `bytes` reporting
  the compact size, and the comment states why. This is the note's own calibration quantity, so
  the 58%/29,150 table is now commensurable with the deployed decision. The four design documents
  agree: `build-plan.md` 1245–1246 ("the bytes the client would otherwise return"), `schema.md`
  507, `architecture.md` 1049, and nothing anywhere claims the indented form is measured. ✓
- *Finding 5:* `consolidator.py` 186–194 wraps both `PayloadLineTooLongError` and `OSError` in
  `ToolError` at `_call`, `spill.py` stays stdlib-only, the refusal's tail (spill.py 62–64) now
  addresses an actor with the right verbs, and `_write` unlinks its partial file under
  `BaseException` (199–203). ✓
- *Finding 6:* `mkdir(mode=0o700, parents=True, exist_ok=True)` at spill.py 191, docstring
  186–189 stating why vetting is not repeated and that the file's own `0600`/`O_EXCL`/unpredictable
  name is what the contents rest on. ✓
- *Finding 7:* filename is `{store_key}-{tool}-{pid}-{random}.json` (spill.py 192), `store_key` is
  the socket's own hash (`server.py` 76, asserted against `sock_path` in the wiring class);
  `write-policy.md` 233–235 carries the literal `rm "$XDG_RUNTIME_DIR"/zikaron/<store-hash>-*.json`
  glob, which reaches exactly one store regardless of the `<method>` component; `architecture.md`
  556 carries the corrected row. ✓
- *Findings 8, 9:* `_uuid_of_longest_value` ranks by rendered bytes (spill.py 159–166), with the
  comment naming why; the truncation note's line 139 reads "never stated numerically by the
  harness", duplicate gone. ✓
- *Also checked:* `SPILL_GUIDANCE` (`install/assets.py` 201–214) names the pointer's actual keys
  (`{spilled: true, path, bytes, note}` — matches `apply`'s dict exactly) and correctly
  distinguishes Zikaron's pointer from the harness's own notices; the invariant list's eight
  clauses each map to a test I could name; no stale "unlink previous" text survives outside the
  withdrawal; `spill_threshold` in `keys.py` 309–315 matches `schema.md`'s row (section, bounds,
  default, unit).

### Findings

1. **[IMPROVEMENT] `test_the_threshold_is_the_shipped_default` is green under the one mutation its
   own docstring says it exists to catch, and the whole wiring class reads the developer's real
   `~/.config` — the suite's first default-tier dependency on out-of-repo state.** Two halves,
   one class. (a) The docstring (`tests/test_mcp_spill.py` 198–200) says "Read from config rather
   than hard-coded, so an operator override reaches the client" — but the assertion
   (`threshold_bytes == 27_000`) cannot distinguish `config.get_int("spill_threshold")` from a
   literal `27_000`, because the shipped default and the hard-coded constant are the same number.
   Replacing `server.py` line 72 with `threshold_bytes=27_000` leaves all 1763 tests green while
   silently severing the operator's knob — the more insidious sibling of the `10**9` mutation the
   researcher did run. This is the M14 class: a test asserting less than its docstring claims.
   Fix: one more test in the class that writes a project-layer override —
   `(tmp_path / ".zikaron").mkdir()` then `config.toml` containing
   `[consolidation]\nspill_threshold = 30000` — and asserts `threshold_bytes == 30_000`;
   mutation-verify by hard-coding 27,000 and watching it fail. (b) `_spill_policy` reaches
   `resolve_effective_config` (`connection.py` 136–144), which reads
   `${XDG_CONFIG_HOME:-~/.config}/zikaron/config.toml` from the real environment; conftest's
   autouse fixture scrubs harness variables only. Today `/home/nathan/.config/zikaron/config.toml`
   does not exist (checked), so the class passes — but a system-wide config is a *supported,
   documented layer* (D33), and the day the operator writes one with a `spill_threshold`, this
   test goes red with no code change; one with any out-of-bounds key anywhere would break all five.
   That contradicts CLAUDE.md's "hermetic, and deliberately so" property of the default suite.
   Fix: a class-scoped autouse fixture, `monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path /
   "xdg"))`, so the system layer is provably empty; the project-layer override test from (a) then
   pins the wire hermetically.

2. **[NITPICK] The store-key test's `startswith` is satisfiable by an empty `store_key`.**
   `tests/test_mcp_spill.py` 220: `sock_path.name.startswith(policy.store_key)` — `startswith("")`
   is unconditionally true, so `store_key=""` (or any prefix-truncation of the hash) passes.
   `socket_path` is exactly `f"{socket_hash(...)}.sock"` (`paths.py` 75–77), so strict equality
   costs the same line: `assert connection.location.sock_path.name == f"{policy.store_key}.sock"`.

3. **[NITPICK] The refusal message dangles when no uuid was found.** `spill.py` 58–64: with
   `uuid=None` the message opens "a value in this payload serializes to…" and then still says
   "Report that uuid and carry on" — an instruction referencing a uuid the message never named.
   Either condition the tail on `uuid` or make it uuid-neutral: "Report this refusal and carry on
   with the run: …".

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-13

**Summary judgment.** Verification round, as asked, and everything asked for verifies. All three
round-8 findings landed as described, both new mutation claims are true of the code as written —
I re-derived each against the actual assertions rather than accepting the researcher's summary —
and the autouse fixture changes no sibling test's behaviour: it only replaces an out-of-repo read
(the developer's real `~/.config`, which happens to be empty today) with a provably empty layer,
which is precisely the hermeticity round 8 asked for. The final sweep found nothing stale and
nothing new. This is ready.

**The verification record, per round-8 finding.**
- *Finding 1(a):* `test_an_operator_override_reaches_the_client` (`tests/test_mcp_spill.py`
  215–227) writes `[consolidation]\nspill_threshold = 30000` to `tmp_path/.zikaron/config.toml`
  and asserts 30,000. The wire is genuine end to end, checked at every link: `paths.store_dir`
  returns `scope_dir / ".zikaron"` (paths.py 30–39), `project_config_path` returns
  `store_dir / "config.toml"` (resolution.py 247–249) — so the file the test writes is exactly
  the project layer `_spill_policy`'s `resolve_effective_config(connection.location.store_dir)`
  reads; the key's declaration (`keys.py` 309–315: section CONSOLIDATION, bounds 4,096–1,048,576,
  default 27,000) admits 30,000. Mutation claim (a) is therefore true by construction: a
  hard-coded `threshold_bytes=27_000` in `server.py` returns 27,000 against an assertion of
  30,000. The docstring (216–220) states exactly why the sibling default test cannot catch this
  and why the key exists. ✓
- *Finding 1(b):* `_an_empty_system_config_layer` (185–198), autouse across the class, sets
  `XDG_CONFIG_HOME` to `tmp_path / "xdg"`. Checked that this actually neutralizes the layer it
  claims to: `resolve_effective_config` builds the system path via
  `default_system_config_path(os.environ.get("XDG_CONFIG_HOME"), Path.home())` (connection.py
  141–144), which honours a non-empty env value (resolution.py 237–244), and `_read_layer` treats
  the absent file as an empty, contributing-nothing layer (106–116). So the fixture is not a
  no-op, and the system layer is provably empty for all six tests. ✓
- *Finding 2:* `tests/test_mcp_spill.py` 249 asserts
  `connection.location.sock_path.name == f"{policy.store_key}.sock"`, with the comment carrying
  the round-8 reasoning. Mutation claim (b) is true: `socket_path` is exactly
  `f"{socket_hash(resolved_store_dir)}.sock"` (paths.py 75–77) and `_spill_policy` computes
  `store_key` from the same `socket_hash` over the same resolved directory (server.py 76), so
  equality holds for the real wiring and `store_key=""` yields `".sock"` against a hash-named
  socket — fails, where `startswith("")` was unconditionally green. ✓
- *Finding 3:* the refusal's tail (spill.py 62–67) is uuid-neutral — "Report this refusal and
  carry on with the run: shortening the record needs the primary agent or the operator, and
  neither verb for it is yours" — with the comment (60–61) recording why. Reads correctly under
  both `uuid="u0"` and `uuid=None`; the D32 actor framing from round 7 survives. ✓

**On the direct question — does the fixture change any sibling test's behaviour?** No, and I
checked each dependency rather than reasoning from the fixture alone. The two detection tests
read harness state through `detect.current_spec()`, which looks at harness markers
(`CLAUDECODE`), not `XDG_CONFIG_HOME`; conftest's autouse harness scrub plus the explicit
`delenv`/`setenv` still govern them. The directory and store-key tests depend on
`StoreLocation.resolve`, which reads `XDG_RUNTIME_DIR` (connection.py 82–84) — a different
variable the fixture does not touch, and both of those tests compare two values derived from the
same `StoreLocation`, so they hold regardless of that variable's real value. All six tests do
run `resolve_effective_config`, so all six previously read the developer's real config path; the
fixture changes *that* for all of them, which is the fix working, not a behaviour change — with
an empty system layer and (except in the override test) no project layer, they resolve to shipped
defaults, which is what they always got on this machine and now get everywhere.

**Final sweep.** The old refusal tail ("Report the uuid…") survives nowhere outside this review
file — the only match for the message text in the repository is spill.py itself, so no design
document quotes a message the code no longer raises. The test count is consistent (13 module
functions + 6 in the wiring class = the 19 reported). The subprocess lifetime test's
`startswith("k-next_group-")` is not the finding-2 shape — its prefix is an explicit literal with
the trailing hyphen pinned, not a policy-derived value that can be empty. No stale docstring, no
claim asserting more than its test, nothing measured in the wrong unit that I could find.

### Findings

None. The intentional items (the `Read` grant and D32 widening, kiro getting nothing, the 27,000
default and its spill rate, sharding deferred, the end-to-end run outstanding) stand as recorded
in earlier rounds and are not re-raised.

VERDICT: APPROVED

## Round 10 — 2026-09-13 — a correction found by the end-to-end run, after round 9's approval

Round 9 approved the implementation, including a lifetime mechanism (`atexit`) the end-to-end run
then measured as never firing in production — the harness terminates its MCP server, so the exit
handler asserted by `test_a_process_that_exits_takes_its_spill_files_with_it` runs only in the test.
This round reviews the replacement as new work: `spill.release_finished` /`spill.sweep_stale`, their
call sites in `consolidator.zikaron_next_group` and `server.build_server`, the ten new tests, and
the corrected design record (`build-plan.md` §M18 Lifetime, `architecture.md` filesystem row,
`write-policy.md` erasure paragraph).

**Summary judgment.** The two-mechanism design is sound and correctly placed, and I verified its
load-bearing premise against the service rather than accepting it: `groups.next_candidate` re-serves
the earliest served-but-incomplete group before advancing ("Re-serving before advancing is the
point"), and a serve rewrites that group's authorization and receipts — so any path back to a
released group passes through a fresh serve that re-spills a fresh payload, which is what actually
makes releasing at `next_group` safe. The call-site tests are non-vacuous and pin exactly the
placement bug the researcher found (monkeypatched `request` fails `ensure_planned`, so a release
moved after the bridge demonstrably fails the test). What keeps this from APPROVED is one gap in the
project's own evidence discipline — the measurement the entire correction rests on, and the
milestone's done-when evidence, is recorded nowhere durable — plus two places where the corrected
record's stated justification asserts more than the service guarantees, which is the docstring class
this corpus polices by name.

**Direct answers to the four questions asked.**
- *Is the two-mechanism design sound?* Yes. Release bounds the live set to one group during a run;
  sweep needs nothing from the dead process; neither depends on exit; both are scoped (store key,
  liveness) in the deleting function itself.
- *Is `next_group` genuinely the only safe release point?* It is the right one, but "only" and the
  stated reason both overstate — see findings 2 and 3. A disposition response carrying
  `group_complete: true` is also a safe release point (the group is `COMPLETE` and no longer
  actionable), and it is the shape a third mechanism would take; it was rightly not built, because
  it requires inspecting payload semantics at the translation seam for a residue the sweep already
  bounds.
- *Can the sweep delete a file another process is reading?* Yes, in one window — finding 5. The
  failure is loud (ENOENT on the next `Read`) and self-healing (re-request re-serves), never silent
  truncation, which is the direction that matters.
- *Is the remaining residue acceptable?* Yes, and it is smaller than the record claims: a run that
  ends properly issues one more `next_group` and receives `{done: true}`, and **that call's release
  covers the last group** — so a completed run's steady-state residue is zero, and the sweep's real
  constituency is abandoned and killed runs, which leave at most one group's files (~73 KB observed
  max per spill, plus that group's conflict spills) in RAM-backed tmpfs at `0600`, reachable by the
  erasure glob, removed at the next consolidator start or reboot. No third mechanism is warranted.

### Findings

1. **[BLOCKER] The measurement the whole correction rests on — and the milestone's own done-when
   evidence — is recorded nowhere in `research/`, and the only transcript showing it expires on
   `cleanupPeriodDays`.** Grep: `zk-spill-e2e`, `43,859`, `64,590` and `217 KB` appear in no
   research note; the sole trace is one sentence in `build-plan.md` ~1243. The run established
   five things the record now cites as fact: 4 of 6 groups spilled at 43,859–64,590 bytes; all
   four `Read`s succeeded first try with no truncation; the consolidator **did not balk at the
   pointer** — the answer to round 1 finding 6's injection-shaped-pointer worry, and the largest
   open question the done-when existed to settle; the dispositions (1 promoted, 11 merged, 0
   conflicts); and `atexit` never firing (4 files, 217 KB left). The done-when's own phrase is
   "the consolidator **shown** reading the spill file to its end" — the showing lives only in
   `~/.claude/projects/`, which the harness prunes in ~30 days, the exact expiry M16 already
   worked around by copying to `~/zikaron-m16-evidence/`. This is round 1 finding 3's class
   (blocker then, for less): a brief citing measurements nobody can check. Concrete edit: a
   `research/` note (new, or a section of the truncation note) recording the store shape (12
   entries × ~20,500 prose characters), the six groups with spilled/inline and byte sizes, the
   read-back behaviour including the no-balk observation and what the pointer's `note` text was
   when it worked, the run outcome, and the `atexit` failure with the termination diagnosis; copy
   the session and consolidator transcripts somewhere durable per the M16 practice; cite the note
   from `build-plan.md`'s "Corrected after the end-to-end run" paragraph, which currently cites
   nothing.

2. **[IMPROVEMENT] "A consolidator cannot return to it, since merge authorization is recomputed
   and rewritten on every serve — and that is true whether or not this call goes on to succeed"
   asserts two things the service does not guarantee; the accurate argument is re-servability,
   and none of the three places carrying the claim states it.** `consolidator.py` ~231–236,
   `spill.release_finished`'s docstring (~221–227), `build-plan.md` Lifetime bullet 1 (~1233–1235).
   Checked against the service: (a) `groups.replace_authorization` is keyed by `group_id` — it
   replaces *that group's* previous serve's rows, so serving group B deauthorizes nothing of group
   A (`authorization.py` ~146: "a record a *previous* serve showed" means a previous serve *of
   this group*); a served-incomplete group A in a live run passes the whole validation ladder
   after B is served. (b) On a **failed** `next_group` (transport, `store_busy`) nothing is
   rewritten at all, so "whether or not this call goes on to succeed" is exactly the half that is
   false — the previous group remains fully actionable with its file gone. (c) Even on success,
   `next_candidate` re-serves the earliest served-but-incomplete group before advancing, so the
   consolidator does return to it — with a fresh payload. The release is still safe, for a reason
   none of the texts give: **every path back to a released group passes through a fresh serve,
   which re-spills a fresh copy, so the released file is never the last copy of anything still
   reachable** — and a failed call's loss is bounded and loud (the model re-requests, the group
   re-serves). This is the docstring-asserting-more-than-holds class this project has named twice
   (the M17 deferral docstring; M14's vacuous agreement test), sitting in the exact comment a
   future session will trust when adding or moving a release point. Concrete edit: rewrite the
   sentence in all three places to the re-servability argument, e.g. "Safe not because the
   previous group is unreachable — a failed call leaves it actionable, and an unfinished one is
   re-served — but because every route back to it delivers a freshly spilled payload, so no
   released file is ever the only copy of something still needed."

3. **[IMPROVEMENT] "It cannot cover the *last* group of a run, because no further request follows
   it" is wrong for the run that ends properly, and correcting it improves the residue story the
   design record tells.** `spill.release_finished` docstring ~229–231; `build-plan.md` bullet 2
   ("This is what reaches the *last* group of a run"). A consolidator that runs to completion
   learns the run is over by calling `next_group` once more and receiving `{done: true}` — the
   docstring for `remaining_groups` is explicit that reaching 0 does not mean none remain — and
   that final call's release removes the last group's files. So: completed run, zero residue;
   the sweep's constituency is the *abandoned or killed* run, which leaves its current group.
   Concrete edit: in both places, "the last group of a run that stops without asking again — a
   killed process, or a consolidator that quits after `group_complete` — is what `sweep_stale`
   reaches; a run that ends on `{done: true}` releases its own last group." The e2e run's four
   leftover files are consistent with this: that run predates `release_finished` entirely, so it
   is evidence for the atexit failure, not for a last-group gap.

4. **[IMPROVEMENT] Pid 999999 is not provably dead, and both deletion tests go red the day it is
   alive.** `tests/test_mcp_spill.py` ~326 and `tests/test_mcp_server.py` ~182 both name
   `-999999-` as the dead pid. systemd on 64-bit Linux sets `kernel.pid_max` to 4,194,304, so on
   exactly this machine class a long-uptime system wraps pids past 999,999 and `_is_running`
   answers true — the file survives the sweep and the assert fails, a red gate for reasons
   unrelated to the change under test, which is the flap class FINDINGS already tracks around
   `fail_under`. Concrete edit: derive a genuinely dead pid by reaping one —
   `probe = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)`
   then `dead_pid = int(probe.stdout)` — the module already spawns a subprocess for the atexit
   test, and immediate pid reuse is ruled out by Linux's cyclic allocation. (The third 999999 use,
   the foreign-store test, is safe either way: it asserts the file is *kept*.)

5. **[IMPROVEMENT] The sweep can delete a file a live *session* is mid-read of — the dead-writer/
   live-reader window — and no text names it.** The pid in the filename is the MCP server's; the
   reader is the harness session's `Read` tool. If a consolidator's MCP server dies mid-session
   and the harness restarts it (crash, `/mcp` reconnect), the restarted process's `build_server`
   sweeps its predecessor's files — which may include the group the session is at that moment
   partway through reading. `sweep_stale`'s docstring (~248–250) covers only the live-pid half
   ("it may be being read right now"). The failure is the acceptable kind — the continuation
   `Read` fails loudly with file-not-found and the recovery is one `next_group` re-serve — and the
   window needs a mid-session MCP crash, so this wants a sentence, not a mechanism. Concrete
   edit: one sentence in the sweep docstring and in `build-plan.md`'s sweep bullet naming the
   window, its loud failure, and its recovery, so the next session does not discover it as a bug —
   and note it is also the real reason the primary client must not sweep (the docstring of
   `test_building_a_primary_client_sweeps_nothing` gestures at this but liveness alone would
   protect a live consolidator's files; it is the dead-writer window that primary sweeping at
   every session start would widen).

6. **[NITPICK] "— or everything, if no consolidation has run since" does not parse.**
   `write-policy.md` ~236. Since *when*? And "everything" cannot exceed one group's files, because
   release bounds the live set during any run that has the new code. Suggested restatement: "so
   what remains here is at most one group's files — the current group of a live run, or the last
   group a killed one was holding — until the next consolidator start sweeps them; the `rm` glob
   above is the remedy that waits for neither."

7. **[NITPICK] The cleanup tests share the module-global `_written` with every other test in the
   session, uncontrolled.** No fixture resets `spill._written`, so
   `test_releasing_does_not_touch_a_file_written_after_it`'s opening `release_finished` unlinks
   whatever earlier tests left there (harmless today, order-coupled forever), and the release half
   of `test_neither_mechanism_touches_anything_where_spilling_is_off` is vacuous — its file was
   never in `_written`, so `release_finished` would leave it alone even with `enabled=True`. An
   autouse fixture in the class snapshotting and clearing `_written` closes both; the vacuous half
   could instead assert against a file appended to `_written`, which would make the enabled-gate
   mutation (`release_finished` ignoring `policy.enabled`) fail a test, which today it does not.

VERDICT: NEEDS_CHANGES

## Round 11 — 2026-09-13

**Summary judgment.** The verification the round asked for passes, and findings 2 and 3 were checked
against the service, not the summary: the corrected argument's three premises are each true of the
code (`replace_authorization` is keyed by `group_id` and "replacing any previous serve's rows" means
previous serves *of this group*; the serve-side rewrites all sit inside the successful-serve path in
`serving.py` 318–325, so a failed request rewrites nothing; `next_candidate` re-serves the earliest
served-but-incomplete group before advancing, its docstring saying so in terms), and the conclusion
— every route back passes through a fresh serve, which spills a fresh copy — follows, with the
"new group, not new file" distinction present in all three texts. Finding 3's correction is true *by
the call site's own placement*: `release_finished` runs first in `zikaron_next_group`, so the
terminal `{done: true}` call has already released the last group. Findings 4–7 all landed and
verify (detail below). But checking the research note against the transcripts it cites found one
thing the note misstates in the direction that flatters the result: the no-balk observation — which
the note itself calls "the finding the done-when most needed" — was taken under a driving prompt
that named the pointer's exact shape and presupposed the consolidator would act on it, and the
note says "without being prompted to". The transcript refutes that sentence at its own line 1.

**The verification record, per round-10 finding.**
- *Finding 1:* `research/m18-spill-end-to-end.md` exists and carries everything asked: store shape
  (245,998 ÷ 12 = 20,499.8 ✓), both failed seedings with reasons, all six groups with form and byte
  size (2+3+3+2 spilled members + 2 inline singletons = 12 ✓; pair ≈ 43.9k and triple ≈ 64.6k are
  consistent with 20.5k-character entries at the measured ~1.07 framing ✓), the pointer, the run
  outcome (1 promoted + 11 merged = 12 ✓), the `atexit` failure (64,557 + 43,859 + 64,590 + 43,884
  = 216,890 B ≈ 217 KB ✓), and the bypassPermissions caveat. Checked against the transcripts
  rather than taken on trust: the pointer's path, `bytes: 64557` and note text appear verbatim in
  `agent-ab44a9f1537e8cf5a.jsonl`; **all four `Read` calls are in that transcript with `file_path`
  only — no `offset`, no `limit`** — matching the note's sentence exactly; all four filenames carry
  pid 905053 and distinct 16-hex suffixes; the evidence directory holds the six files. The brief's
  correction paragraph cites the note (build-plan.md ~1256–1257). ✓ except finding 1 below.
- *Finding 2:* the re-servability argument is in `spill.release_finished`'s docstring (~221–232),
  `consolidator.py`'s call-site comment (~231–236), and the brief's Lifetime bullet 1 (~1233–1239),
  each stating what is *not* the reason before the reason, with the group-not-file distinction. All
  three "becomes unreachable" survivals in the repo are the negated form. ✓
- *Finding 3:* both the docstring (~234–238) and the sweep bullet (~1241–1244) now say a proper run
  releases its own last group on the `{done: true}` call and the sweep's constituency is the run
  that stops without asking again. True of the implementation because release precedes the bridge
  and the request. ✓
- *Finding 4:* `_a_dead_pid()` (test_mcp_spill.py 27–41) reaps a subprocess and takes its pid, with
  the pid_max and cyclic-allocation reasoning in the docstring; used by both deletion tests
  (test_mcp_spill.py 358, test_mcp_server.py 183) and by the primary-sweeps-nothing test (196,
  which is fine — it asserts kept for a mode reason, and a dead pid makes it stronger); the
  foreign-store test keeps its literal (test_mcp_spill.py 381), correctly, since it asserts kept. ✓
- *Finding 5:* the dead-writer/live-reader window is named in `sweep_stale`'s docstring (~259–266)
  and the brief's sweep bullet, with the loud failure, the one-re-serve recovery, and the
  primary-must-not-sweep consequence. ✓
- *Finding 6:* `write-policy.md` 236–239 carries the suggested restatement, bounded to one group's
  files, with "The `rm` above waits for neither." ✓
- *Finding 7:* `_an_isolated_written_list` (test_mcp_spill.py 316–328) snapshots, clears, and
  restores `_written` for the class; the disabled-mechanisms test appends its file first (410), so
  the enabled-gate mutation on `release_finished` now fails it — and the same append makes the
  disabled *sweep* mutation catchable too, since the file's pid is dead and its key matches. The
  call-site test in test_mcp_server.py (203–226) pins the release-before-bridge placement: the
  monkeypatched `request` fails, so a release moved after `ensure_planned` leaves the file and
  fails the assert. ✓

### Findings

1. **[BLOCKER] "The consolidator read it without hesitation and without being prompted to" is
   refuted by the driving prompt in the note's own cited transcript, and the no-balk finding's
   stated uncertainty omits the confound that most directly explains it.**
   `research/m18-spill-end-to-end.md` §"What the run did" (~67–72). Line 1 of
   `~/zikaron-m18-evidence/82adbc5b…/subagents/agent-ab44a9f1537e8cf5a.jsonl` — the consolidator's
   own task prompt — contains an instrumentation section: *"In addition to your normal report, I
   need a precise mechanical accounting of the tool results themselves … did the
   zikaron_next_group tool result arrive as a normal inline group, or as a pointer object of the
   form {spilled: true, path, bytes, note}? — If any result arrived as a spilled pointer, quote
   the exact `path` string verbatim, the `bytes` value, and the `note` text, then state exactly
   what you did next **to obtain the group's content** (which tool, which arguments) and whether
   that succeeded."* That names the pointer's exact shape as an expected outcome and presupposes
   the consolidator will act on it to obtain the content — priming precisely the behaviour the
   observation claims arose unprompted. The earlier seeding run's prompt
   (`agent-a3b82e1a8626c92bc.jsonl` line 1) is more explicit still: *"…and exactly what you did
   about it (e.g. **whether you read the spill file at the given path**…)"*. So the note's
   dichotomy — "the prompt's sentence is doing its job, or the reflex is weaker than the probe
   suggested" — is missing its third and arguably strongest arm: the run's own accounting
   instructions legitimized the pointer over and above the shipped guidance. M16's checkpoint kept
   its dogfood agent memory-naive for exactly this reason, and this note inherits that standard by
   its own opening paragraph. The mechanism half is untouched: the spill, the four complete reads,
   the round-trip, and the run's completion are all clean. Concrete edit, all in the note: quote
   the accounting instruction; withdraw "without being prompted to" in place per the project's
   rule; restate the finding as "the consolidator treated the pointer as legitimate and read the
   file completely, under a run whose driving prompt had already named the pointer shape and asked
   what was done to obtain the content — so this run cannot attribute the no-balk to the shipped
   guidance"; and add to §"Not measured here": whether a consolidator balks when the shipped
   guidance is the *only* mention of the pointer, i.e. an accounting-free run. Propagate the
   softening to any other file that quotes the no-balk result as clean.

2. **[IMPROVEMENT] "A single record can never spill" is stated as a general lemma and is true only
   of this corpus.** `research/m18-spill-end-to-end.md` §"The store", second bullet. Two ways it
   fails in general. (a) A served group's payload is not just its journal entries: it carries an
   anchor and up to four candidate long-term records, and the adjacent bullet's own citation says
   candidates run ~70% of a real payload — so on a mature store a one-*member* group can clear
   27,000 bytes with no single value near the 24,000-byte line refusal. It held here because a
   near-fresh store has no candidates to serve. (b) Even a bare-record payload has a ~400-byte
   corner: the line bound caps `content`'s rendered line at 24,000, but a gist at the 1,024-character
   bound can render to ~3 KB, so content ≈ 23.9k + a maximal gist + framing exceeds the threshold
   without tripping the refusal. Concrete edit: scope the sentence — "On this store — journal-only
   groups with ordinary gists — a single-entry group cannot spill: its content line trips the
   24,000-byte refusal before the payload reaches 27,000. Not a general fact: a mature store's
   one-member group also carries an anchor and candidates and can spill whole." The bullet's
   conclusion (the corpus needed pairs) is unaffected.

3. **[NITPICK] The first-seeding bullet's two entry counts disagree.** Same section: "21,408
   characters across 8 entries produced no spill at all. Groups came out at one or two members
   (10 singletons, 4 pairs **from 18 entries**)" — 8 and 18 cannot both describe one seeding
   (10 + 4×2 = 18, so the grouping figures are internally consistent; it is the 8 that belongs to
   something else, presumably the first seeding before the second added ten more). One clause
   attributing each number to its seeding reconciles it; the note exists to be checked.

4. **[NITPICK] `release_finished`'s summary line asserts the precondition its own body refutes.**
   `spill.py` ~219: "Call when the previous group is finished." The call site calls it on every
   `next_group`, finished or not, and the docstring's whole point is that finished-ness is not the
   safety condition — re-servability is. Say "Call when the next group is requested." (The
   function's *name* has the same shading, but renaming is churn; the summary line is one word.)

5. **[NITPICK] The note's "verbatim" pointer quote is not verbatim.** The code block at ~51–57
   wraps the `note` string across lines with raw newlines inside a JSON string literal — invalid
   as displayed, and different from the transcript's single-line form. Either quote the one line
   as it appears or keep the wrapping and say "reflowed for width"; "verbatim" should mean it.

VERDICT: NEEDS_CHANGES

## Round 12 — 2026-09-13

**Summary judgment.** Re-running the experiment instead of softening the prose was the right
response to round 11, and the second run is genuine: I verified every central claim of the new
section against the transcript rather than against the researcher's account, and the mechanism
half is clean — the pointers, the exact-path `Read`s, the absence of deliberation, the silent
summary, and the empty runtime directory all check out (record below). The withdrawal is recorded
per the project's rule, findings 2–5 all landed, and §"Not measured here" is the right residual
(its quoted sentence matches `SPILL_GUIDANCE` verbatim). What keeps this from closing: the new
section misdescribes its own experimental setup in the two places that make it a control — the
consolidator's "whole prompt" was not the quoted sentence, and "identically reseeded" is refuted
by the transcripts — which is the exact claim-refuted-by-line-1 class round 11 blocked on,
recurring in the section written to fix it. Every conclusion survives the corrections, and both
fixes are sentences, so round 13 should be short.

**The verification record, against `~/zikaron-m18-evidence/c1747b90-…/subagents/
agent-a889596d1cbec6be2.jsonl` (the second run's consolidator).**
- *Prompt:* line 1 contains no mention of spills, pointers, paths or files — the confound-removal
  claim holds. (But see finding 1a: it is two sentences, not the one the note quotes.)
- *Spills and reads:* pointers at lines 11, 25, 34; `Read` at 12, 27, 35; each `input` is
  `{"file_path": …}` only — no `offset`, no `limit` — and each path is byte-identical to its
  pointer's (`…-925988-f7dee238a663fb61/…-1a4b6dfd89c58e02/…-5304cd08d457b641.json`, hash
  `d5fef33f…` matching the store). All three Read results contain the payload tail
  (`remaining_groups`), and the transcript contains no truncation notice, so one read genuinely
  sufficed. ✓
- *No prose between pointer and `Read`:* 11→12 and 34→35 are adjacent; the only event between 25
  and 27 is line 26, an assistant message whose sole content block is an **empty** thinking block
  (`"thinking":""`) — no prose, no deliberation. ✓
- *The summary:* the only occurrence of "spill" on line 52 is the `cwd` field's
  `/home/nathan/zk-spill-e2e`; the summary text itself never mentions spills, files, or `Read`. ✓
- *Completeness of the run:* findings 0–11 (all 12 entries) appear across seven group payloads —
  {0}, {1,2,4}, {3}, {5,6,7}, {8,9}, {10}, {11} — and the absorb arrays at lines 16/22/30/38/43/48
  absorb 3+1+3+2+1+1 = 11 entries into `8025fb18…` (versions 1→7), plus 1 promoted = 12. Nothing
  unfinished. ✓
- *Cleanup:* `/run/user/1000/zikaron/` holds no `*.json` today. ✓ (Attribution: finding 2.)
- *Round-11 findings 2–5:* the never-spill claim is scoped with both counterexamples (note ~29–36);
  the 8/18 seeding counts are attributed and reconcile (10 + 4×2 = 18 = 8 + 10); `spill.py` 220
  reads "Call when the next group is requested."; the pointer quote is labelled "one line there,
  reflowed here for width". All ✓.
- *Withdrawal:* the withdrawn phrase is quoted with the refutation beside it and the accounting
  instruction quoted (note ~71–77) — in place, per the rule. No stale propagation: "balk /
  without being prompted" appears nowhere else in the repo outside this review file, and
  `build-plan.md` 1336 is the prompt rationale, consistent with the note. §"Not measured here"'s
  "this pointer is Zikaron's own" matches `install/assets.py` 209 verbatim, and the
  sentence-ablation run is the correct next residual now that the accounting-free run — round 11's
  requested residual — has been done. ✓

### Findings

1. **[BLOCKER] §"A second run" misdescribes its own setup twice, and both misdescriptions are
   refuted by the transcripts the section rests on.**
   (a) *"the entire prompt being 'Consolidate this project's memory journal.'"* — the
   consolidator's actual task prompt (transcript line 1) is two sentences: that one **plus**
   *"Work through every group until mcp__zikaron-consolidator__zikaron_next_group answers
   {\"done\": true}, then report what you did."* The second sentence is the **shipped skill's own
   spawn text** (`install/assets.py` 304; installed at
   `~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` 27–28), and it mentions no spills,
   pointers, paths or files — so the confound-removal claim survives, and quoting it in full
   actually *strengthens* the run: the operator typed one sentence and everything else was the
   shipped flow end to end (session → skill → spawn prompt → consolidator). Concrete edit: quote
   both sentences, identify the second as the skill's shipped spawn text, and keep the "no mention
   of spills…" claim, which is then true of the whole prompt.
   (b) *"an identically reseeded store"* — refuted three ways: none of run 2's entry uuids appear
   in run 1's transcript (fresh writes, not a restore); the same-membership groups serialize to
   different sizes ({5,6,7}: 64,632 vs 64,590 bytes; {8,9}: 43,910 vs 43,884); and grouping came
   out differently — **7 groups against 6**, finding 11 moving from {1,2,11} to a singleton and
   finding 4 from {3,4} into {1,2,4} — which byte-identical text cannot produce through the
   deterministic grouping pipeline. Concrete edit: state how the store was actually reseeded (a
   script? a session? if a session, its transcript is not in the evidence directory — see finding
   3), and re-describe: "reseeded to the same shape — 12 entries, findings 0–11, same templates,
   same sizes to within tens of bytes — not byte-identical, and grouping accordingly shifted to 7
   groups". While there, give the section its denominator and sizes: "**3 of 7** groups spilled
   (64,492 / 64,632 / 43,910 bytes)" — "3 of the run's groups" currently invites a reader to
   assume the first run's 6. No conclusion depends on identity — the no-balk attribution and the
   cleanup result are untouched — which is why this is a wording-plus-two-numbers fix; but a
   research note may not describe its control as something the transcripts show it was not, least
   of all in the section that exists because round 11 caught exactly that.

2. **[IMPROVEMENT] "The cleanup fix is verified" conflates the two mechanisms, and only one of
   them is verified by the stated evidence.** Note ~96–98. Zero files after run 2 verifies
   **release**: each spilled file was released on the following `next_group`, the last on the
   terminal `{done: true}` call, all before the harness terminated the process — genuinely the
   lifecycle that defeated `atexit`. Whether **`sweep_stale`** fired in production depends on
   whether run 1's four pid-905053 files were still present at run 2's consolidator start, and the
   note does not say; the closing sentence ("Release on `next_group` plus the start-of-process
   sweep reach the case…") reads as both-verified. Concrete edit: one sentence stating the
   runtime directory's contents at run 2's start and attributing the removals — if the four stale
   files were there and are gone, that is the sweep's first production firing and worth recording
   as such; if they were removed manually during reseeding, say the sweep remains verified only in
   the hermetic tier, which is the exact distinction the `atexit` failure just taught.

3. **[IMPROVEMENT] The note's evidence inventory is stale, and the second run cannot be joined to
   its transcript from the note's own text.** Header ~8–11 still says "both session transcripts
   and both consolidator-subagent transcripts … Six files"; the directory now holds **nine** files
   across **three** sessions. And §"A second run" — whose method is "read out of the transcript" —
   never names which transcript: a reader must diff timestamps across three sessions to find it,
   and after `cleanupPeriodDays` the note is the only durable record, which is the entire reason
   the directory exists. Concrete edit: update the inventory (three sessions' transcripts plus
   subagent transcripts and metadata, nine files), and cite in the section: session
   `c1747b90-a8b1-47f4-8a02-77a808c388e9`, consolidator `agent-a889596d1cbec6be2`,
   2026-09-14T01:17–01:20Z. If the run-2 reseeding happened in a session, copy that transcript in
   too (finding 1b needs it named either way).

4. **[IMPROVEMENT] "The second run promoted 1 and merged 6" is wrong in the unit the adjacent
   sentence establishes.** Note ~100–102. The transcript shows 1 entry promoted and **11 entries
   absorbed across 6 merge calls** (absorb arrays of 3, 1, 3, 2, 1, 1 at lines 16/22/30/38/43/48,
   all into `8025fb18…`, versions 1→7). The preceding sentence counts the first run in entries
   ("11 entries merged into it"), so the parallel reading of "merged 6" is six *entries* — false.
   Concrete edit: "promoted 1 entry and merged the other 11 into it across six merge calls, also
   with nothing unfinished." (For the record: the agent's own prose at line 29 says "two more
   journal entries" of a group whose payload and merge call both carry three — the miscount is in
   its commentary only; the tool call absorbed all three, which is one more reason the note is
   right to read outcomes from tool calls rather than from anyone's prose.)

5. **[NITPICK] Two header-level residues of the second run.** (a) "Measured 2026-09-13" — the
   second run's transcript timestamps are 2026-09-14T01:17Z; say "2026-09-13/14" or date the
   section. (b) The "Outcome of the first run: …" paragraph now sits *inside* §"A second run",
   after the second run's cleanup paragraph — move it up under §"What the run did" (the finding-4
   rewrite touches its last sentence anyway).

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-09-13

**Summary judgment.** All five round-12 findings landed, and I re-verified each against the primary
evidence rather than against the note or the researcher's account: the two-sentence prompt, the
3-of-7 denominator and all three byte sizes, the exact-path `Read`s, the nine-file inventory, the
disposition counts, and the sweep-versus-release separation all check out (record below). What
keeps this from closing is one clause in the rewritten release-attribution paragraph — the
paragraph the brief asked to have checked hardest, and the one recorded "because conflating the
two is how the `atexit` claim survived nine rounds": the note says the last spilled file was
released "on the terminal `{done: true}` call", and the transcript's serve order refutes it — the
last spill was serve five of seven, its file released two `next_group` calls before the terminal
one, which found nothing left to release. The conclusion (all removals attributable to
`release_finished`, all before termination) survives; the mechanism narrative does not, and this
is the third consecutive round in which a sentence of this note is refuted by its own cited
evidence. One-clause fix; everything else is nitpick-grade.

**The verification record, against
`~/zikaron-m18-evidence/c1747b90-…/subagents/agent-a889596d1cbec6be2.jsonl` and the code.**
- *Prompt:* transcript line 1 is exactly the note's two sentences (the line break falls mid-second
  sentence, where the installed skill wraps). The parent session's line 1 enqueues precisely
  "Consolidate this project's memory journal." — the operator-typed-sentence-1 claim holds. The
  installed `~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` 26–29 prompt block matches
  the spawn prompt **byte-for-byte including the line break** — the `assets.py` 304–306 source
  shows the bare tool name and the installed artefact the `mcp__zikaron-consolidator__`-prefixed
  one, which is the installer's tool-name substitution (M16's deferred-tools finding), not a
  deviation from the shipped flow. But see finding 4: the block is **both** sentences. ✓
- *Spills:* pointers at lines 11/25/34, `bytes` 64,492 / 64,632 / 43,910 — matches the note. `Read`
  at 12/27/35, each `input` exactly `{"file_path": …}`, each path byte-identical to its pointer's
  (pid 925988). Line 26, the only event between pointer 25 and Read 27, is an assistant message
  whose sole block is `"thinking":""` — no deliberation. "spilled" appears nowhere on line 52, so
  the summary is clean. ✓
- *Serve order,* from the eight `zikaron_next_group` calls (lines 3/10/19/24/33/40/45/50) and
  their results (4/11/20/25/34/41/46/51): inline, **spill A**, inline, **spill B**, **spill C**,
  inline, inline, `{done: true}`. Dispositions: `zikaron_promote` at 7, `zikaron_merge` at
  16/22/30/38/43/48 — 1 promoted, 11 merged across six calls, as the note now says. Seven groups
  plus the terminal call. ✓
- *Cleanup mechanics, from the code:* `release_finished` is called unconditionally at the top of
  **every** `next_group` (`zikaron/mcp/consolidator.py` 237); `sweep_stale` runs once, at
  consolidator-server start (`zikaron/mcp/server.py` 58), before any of this run's files exist,
  and skips its own pid — so no run-2 removal can be the sweep's, and the attribution of all three
  removals to `release_finished` is structurally forced, not merely asserted. `/run/user/1000/
  zikaron/` holds no `*.json` today. The sweep/release separation, and "the sweep remains verified
  only in the hermetic tier", both hold; the by-hand deletion of run 1's four files is researcher
  testimony from outside any transcript (the parent session contains no `rm` of the runtime
  directory — its `rm` matches are substrings of "confirm"/"perform"), recorded against interest,
  which is the acceptable kind. ✓ — except the one clause in finding 1.
- *Inventory:* nine files across three sessions, session ids as the note names them. ✓ (But see
  finding 3.)

### Findings

1. **[BLOCKER] "the last on the terminal `{done: true}` call" is refuted by the serve order in the
   cited transcript.** Note ~119–122: *"each spilled file went on the following `next_group`, the
   last on the terminal `{done: true}` call, all before the harness terminated the process."* The
   first clause is true of all three files — file A (serve 2) released by the call at line 19,
   file B (serve 4) by the call at line 33, file C (serve 5) by the call at line 40. But serves
   six and seven arrived **inline**, so the last spilled file was released on the call that served
   the **sixth group**, two `next_group` calls before the terminal one — the terminal call (line
   50) ran `release_finished` and found nothing to remove. The sentence transplants `spill.py`'s
   ideal-run docstring ("a run that ends properly … that call releases the last group first",
   lines 233–238, written for a run whose *last* group spilled) onto a run whose transcript shows
   a different shape — the same class of error as rounds 11 and 12, in the paragraph added to fix
   round 12's finding 2. Concrete edit: *"each spilled file went on the `next_group` that followed
   it — the third and last on the call that served the sixth group, since the final two groups
   arrived inline — all before the harness terminated the process; the terminal `{done: true}`
   call found nothing left to release."* The conclusion is untouched; the claim about *when* must
   match the run that happened, in the one paragraph whose job is exact attribution.

2. **[IMPROVEMENT] "the same script" has no antecedent, and the script itself survives nowhere.**
   Note ~88: *"the same script wrote twelve fresh entries"* — but "script" appears nowhere earlier
   in the note (§"The store" describes the seedings without naming a method), and no seeding
   script exists in `~/zk-spill-e2e` (checked: only the install artefacts and the store) or in
   `~/zikaron-m18-evidence/`. So the sentence answering round 12's "state how the store was
   actually reseeded" cites an artefact a reader cannot find, and the control's provenance — "same
   templates, same shape" — rests on it. Concrete edit: give the reference its antecedent and make
   the script durable — name where it ran from and what interface it wrote through (the entries
   carry embeddings, so presumably the real `remember` path — say so), and copy it into
   `~/zikaron-m18-evidence/`; if it was ephemeral and is already gone, say that outright and
   describe what it did, which is the same honesty the sweep paragraph just practised.

3. **[NITPICK] The inventory counts nine files but enumerates six.** Note ~8–9: "each one's own
   transcript plus its consolidator subagent's" accounts for six of the nine; the three
   `*.meta.json` subagent metadata files are unnamed. Add "and its subagent's metadata file".

4. **[NITPICK] Both sentences are the installed skill's prompt block; the note attributes only the
   second to it.** Note ~99: a reader who follows the citation to `SKILL.md` 26–29 finds **both**
   sentences there, verbatim to the line break, and will read the note's operator/skill split as
   an error. The operator did type sentence 1 (session line 1), so nothing is false — but the
   sharper and stronger statement is: *"the whole prompt is the installed skill's own prompt
   block, byte-identical including the line break; the operator's entire typed message was its
   first sentence."* That is also the strongest available form of the shipped-flow claim.

VERDICT: NEEDS_CHANGES

## Round 14 — 2026-09-13

**Summary judgment.** The rewritten release paragraph is true under my reading of the transcript as
well as the researcher's, and I re-verified it with a fresh parse rather than restating round 13.
The researcher's "ten serve-events" is parse noise with an identifiable source (record below), and
the decision to assert only what both readings agree on was the right one — **I do not ask for the
serve numbers**; the weaker form is robust to exactly the noise that produced three rounds of
transplanted descriptions, and the exact order is now verified twice in this file with the
transcript durable. The seeding-provenance paragraph is true of the preserved script's code in
every particular I checked. What keeps this one edit from closing: the script's own module
docstring describes a corpus that neither the code below it nor either recorded seeding produced —
the project's most-relapsed defect class, planted inside the one durable provenance artefact the
paragraph now rests on.

**The verification record, against
`~/zikaron-m18-evidence/c1747b90-…/subagents/agent-a889596d1cbec6be2.jsonl` and the evidence
directory.**
- *Serve order, clean parse:* anchoring on the tool_use `"name"` field — which matches only genuine
  calls — gives exactly **eight** `next_group` calls (lines 3/10/19/24/33/40/45/50): seven group
  results plus the terminal `{"result":{"done":true}}` at line 51. Spilled pointers at 11/25/34;
  inline groups at 4/20/41/46 (`journal_entries` hits at 13/28/36 are the three `Read` results, not
  serves). So: spills were the second, fourth and fifth of seven serves; each file was released by
  the `next_group` that followed it (calls at 19, 33, 40); the final two groups arrived inline; the
  terminal call found nothing left to release. **Every clause of the rewritten paragraph holds under
  this reading**, and the paragraph asserts nothing the reading does not support. ✓
- *Why the researcher counted ten:* the tool's name also occurs in the task prompt (line 1) and in
  the envelope's `attributionMcpTool` fields, which **lag the actual call** — line 50's envelope
  says `zikaron_merge` while its content block calls `next_group`, and line 52's says
  `zikaron_next_group` on a plain-text summary. Any grep not anchored on
  `"name":"mcp__zikaron-consolidator__zikaron_next_group"` inherits that noise. If the numbers are
  ever wanted in the note, the sentence that is true is the one in the bullet above; adopting it is
  optional and I do not recommend holding anything on it.
- *The paragraph's remaining clauses:* dispositions confirmed (`promote` at 7, merges at
  16/22/30/38/43/48, summary at 52 mentioning no spills, files or `Read`); and the parenthetical
  fairly characterizes `spill.py` — its docstring (lines 234–238: "a run that ends properly …
  receiving `{done: true}`, and that call releases the last group first") is exactly the shape that
  has content only when the *last* group spills, which this run's did not. ✓
- *Seeding provenance:* `seed-zk-spill-e2e.py` is in `~/zikaron-m18-evidence/` and its code matches
  the note clause for clause — `range(12)`; gists "finding {index} about …" for 0–11; five
  `PARAGRAPHS` rotated by `(index + offset) % 5`; one raw JSON-RPC `remember` per entry over the
  store's own Unix socket with start-if-absent first, so the service embeds each row; printed
  totals are the note's numbers (245,998 ÷ 12 = 20,499.8). "Same *shape*, not the same bytes" is
  right and precisely so: the prose is deterministic, and the divergence the transcripts show
  (fresh uuids, payloads tens of bytes apart, 7 groups against 6) comes from identity and timing,
  not text. ✓ except finding 1.
- *Inventory:* globbed — nine session artefacts across three sessions, exactly the note's
  enumeration (each session's transcript, its consolidator subagent's `.jsonl`, that subagent's
  `.meta.json`, 3×3), plus the seed script as the tenth file, named separately by the provenance
  paragraph. ✓
- *The prompt:* transcript line 1 is byte-identical to the installed
  `~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` prompt block (lines 27–28), line
  break after "until", no backticks in either; the parent session's typed message is sentence 1
  alone. The note's claims all hold. (Finding 2 is about the note's own rendering, not the claim.)

### Findings

1. **[IMPROVEMENT] The preserved seed script's module docstring describes a corpus that neither its
   own code nor either recorded seeding produced — a false self-description inside the control's
   only durable provenance artefact.** `~/zikaron-m18-evidence/seed-zk-spill-e2e.py` lines 1–5:
   *"Eight mutually-similar entries of about 4,500 characters each puts the members alone well past
   that, so the group spills…"* The code below writes **twelve** entries of ~20,500 characters; the
   note's first seeding was 8 entries totalling 21,408 (≈2,676 each); and eight 4,500-character
   entries would not spill at all — a pair is ~9,000 plus framing against a 27,000 threshold — so
   the docstring's arithmetic describes no corpus that ever existed, presumably an earlier draft.
   The note's provenance paragraph is true *of the code*, which is what this round was asked to
   check — but this project treats a docstring asserting what the code does not do as a bug by name
   (the `atexit` test, the M17 deferral docstring, `spill.py`'s "one tmpfs page"), and the next
   session that opens this script will trust its docstring exactly the way this milestone trusted
   the `atexit` test. Concrete edit, either: correct the docstring in the evidence copy — it is a
   preserved *tool*, not a transcript, so correcting it is legitimate; add a clause to the note
   saying it was corrected after preservation — or leave the file untouched and add one clause to
   the note's provenance sentence: "its module docstring still describes an earlier eight-entry
   draft; the code — twelve entries, five rotated templates — is what ran, and the description here
   follows the code."

2. **[NITPICK] The note's blockquote of the prompt adds backticks that exist in neither the
   transcript nor `SKILL.md`, three lines above a "byte-identical" claim.** Note ~99–100: the
   blockquote wraps `mcp__zikaron-consolidator__zikaron_next_group` and `{"done": true}` in
   backticks; the transcript prompt and the skill block are plain text. Nothing false — the
   byte-identical claim is about transcript ↔ skill block, and that holds — but a reader diffing
   the quote against `SKILL.md` finds characters in neither source, which is the round-11
   "verbatim should mean it" class. Drop the backticks, or quote the block as a fenced block
   copied from `SKILL.md`.

3. **[NITPICK] Three consecutive blank lines (133–135) left where the outcome paragraph moved
   out.** Collapse to one.

VERDICT: NEEDS_CHANGES

## Round 15 — 2026-09-13

**Summary judgment.** All three round-14 findings landed and verify against the primary artifacts,
not the researcher's summary: the note's fenced prompt block is character-identical to the installed
`~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` lines 27–28 including the line break
after "until" and with no backticks (compared directly); the note contains no run of three or more
blank lines (checked mechanically); and the preserved docstring now describes the twelve-entry code,
carries the "Corrected after preservation" paragraph with correct arithmetic (2 × 4,500 ≈ 9,000 <
27,000), and is cited from the note's provenance sentence exactly as round 14 asked. The note itself
I can no longer refute anywhere: every descriptive claim I re-checked is transcript-anchored or
verified in rounds 11–14. What remains is one paragraph of the *corrected docstring* — the sentence
stating the two sizing measurements re-commits, in generic present tense, two claims this
milestone's own evidence bounds or refutes, one of them the exact lemma the note beside it withdrew
in place as "first written here as one". A few words of scoping close it; nothing else is open.

**The verification record.**
- *Finding 1:* `~/zikaron-m18-evidence/seed-zk-spill-e2e.py` lines 1–19. The description matches the
  code clause for clause (`range(12)`; five `PARAGRAPHS` rotated `(index + offset) % 5`, 40
  paragraphs ≈ 20,400 chars + gist ≈ the note's 20,499 mean; raw JSON-RPC `remember` over the
  store's socket with start-if-absent, so rows embed genuinely). The correction paragraph names the
  eight-entry, 4,500-character draft, says it never ran and would not have spilled, and its
  arithmetic is right. The note's provenance sentence (lines 92–95) records the correction and names
  the defect class. ✓ except finding 1 below.
- *Finding 2:* note lines 102–105 against `SKILL.md` lines 27–28 — byte-identical text, line break
  in the same place, no added backticks. The surrounding claims (operator typed sentence 1; the
  whole prompt is the skill's block) are unchanged from their round-13/14 verification. ✓
- *Finding 3:* multiline grep for three-plus consecutive blank lines over the note: zero matches. ✓
- *Sweep for the recurring class:* the release-attribution paragraph (lines 127–137), the sweep
  distinction ("verified only in the hermetic tier", by-hand deletion of run 1's files), the 3-of-7
  denominator and byte sizes, the no-prose-before-`Read` claim, the 1-promoted/11-merged count, the
  nine-file inventory, and both withdrawals-in-place all match what rounds 11–14 verified against
  the transcripts; nothing newly asserts a shape the evidence does not show.

### Findings

1. **[IMPROVEMENT] The corrected docstring's "two things measured on the way" sentence states both
   measurements as generic present-tense facts, and both are refuted outside their original scope by
   this milestone's own evidence — one of them is the exact lemma the note withdrew in place one
   correction ago.** `~/zikaron-m18-evidence/seed-zk-spill-e2e.py` lines 7–11. (a) *"a single entry
   cannot spill on its own, since a record whose content approaches the payload threshold trips the
   24,000-byte per-line refusal first"* — this is the unscoped form of the claim the note (lines
   30–37) explicitly flags: "**Not a general fact**, and it was first written here as one", with two
   counterexamples (a mature store's one-member group carries an anchor and candidates — 70% of a
   real payload — and spills whole with no value near the line bound; and even bare, a maximal gist
   plus content just under 24,000 clears 27,000). The two named artifacts now contradict each other
   on this claim's generality, and the unscoped copy sits in the durable tool a future session would
   adapt for a different store — where sizing by this lemma is exactly wrong. (b) *"grouping over a
   synthetic corpus yields groups of one or two members"* — both recorded runs of this script's own
   corpus produced **three**-member groups ({1,2,4} and {5,6,7} in run 2; run 1's spilled groups
   were 2+3+3+2 members). The measurement was of the earlier 18-entry seeding (10 singletons, 4
   pairs); the inference (size for a pair) survives, since triples only spill more easily, but the
   present-tense generic is false of the corpus the file writes. Concrete edit, both clauses
   restated as the past-tense scoped measurements they were: *"grouping over an earlier 18-entry
   seeding came out at one or two members, nowhere near `group_max`, so the spill had to be
   reachable by a pair (the final corpus later produced triples, which only spill more easily); and
   on this near-fresh store — no candidates to serve, ordinary short gists — a single entry could
   not spill on its own, since its content line trips the 24,000-byte per-line refusal before the
   payload reaches 27,000; the note records why that is not a general fact."* On the researcher's
   stated intent: the delete-the-narrative policy does not apply here — this is a tool's docstring,
   not run narrative, and the remedy is scope words, not deletion.

2. **[NITPICK] The note cites the skill by a bare relative path that resolves nowhere a reader of
   this repository would look.** Note line 108: "(`.claude/skills/zikaron-consolidate/SKILL.md`)".
   This repository has no such file (checked — nothing is installed here, per CLAUDE.md); the
   artefact is `~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md`. Prefix the path so the
   byte-identical claim is checkable from the citation.

**On the delete-rather-than-repair intent.** For *descriptive* claims about what a run did, I agree,
and rounds 11–14 are the argument: every relapse was a narrative sentence outrunning its transcript.
But do not extend the deletion to the analytical passages that survived verification — the
release-attribution paragraph (the transcripts alone cannot attribute removals; the argument needs
the call-site structure, which the note supplies), the confound analysis of run 1, and the
sweep/release distinction. Those are exactly the claims a transcript cannot carry by itself, each is
now verified twice in this file, and deleting them would leave the evidence without its reading. The
one instance this round found is in neither category: it is a docstring wanting a scope qualifier.

VERDICT: NEEDS_CHANGES

## Round 16 — 2026-09-13

**Summary judgment.** Both round-15 findings landed as described, and the two artifacts now agree on
the claim's generality: the docstring states both sizing measurements as scoped past-tense
observations, each with its own limit named, and the skill citation is absolute with the
nothing-installed-here clause. I re-verified the docstring's new clauses against the run evidence
this file already parsed rather than taking either account on faith, and the concordance is exact
(record below). Nothing material remains; the one item below is optional and must not reopen the
round.

**The verification record.**
- *Finding 1, the docstring:* `~/zikaron-m18-evidence/seed-zk-spill-e2e.py` lines 7–20. Bullet 1 is
  scoped to "an **earlier 18-entry seeding**", past tense, with the successor observation ("the
  final corpus later produced triples, which only spill more easily, so the inference held even
  though the observation did not generalise") stated rather than implied. Bullet 2 is scoped to
  "**this near-fresh store** — no long-term records to serve as candidates, ordinary short gists",
  carries "**That is not a general fact**" verbatim, the mature-store counterexample (anchor plus up
  to four candidates, ~70% of a real payload), the explicit warning ("Sizing a different store by
  this lemma would be exactly wrong"), and the pointer to the note. That matches — and slightly
  exceeds — round 15's concrete edit. The preamble ("both stated as the scoped past-tense
  observations they were, since neither is a general rule") makes the scoping self-announcing, so a
  future adapter is warned twice. ✓
- *The triples, checked independently of both accounts:* the researcher's absorb array
  `[1,3,1,3,2,1,1]` sums to 12 and is fully concordant with round 13/14's transcript parse — the
  serve order was inline, **spill A (64,492)**, inline, **spill B (64,632)**, **spill C (43,910)**,
  inline, inline, and the array puts member counts 3, 3, 2 at exactly the three spilled serves and 1
  at all four inline ones. Byte sizes rank with member counts (3 × ~20,600 prose + framing ≈ 64K;
  2 × ~20,600 + framing ≈ 44K), and run 1's four spills (64,557 / 43,859 / 64,590 / 43,884) show the
  same two-cluster structure, matching round 15's 2+3+3+2. So "the final corpus later produced
  triples" is transcript-anchored, not testimony. ✓
- *Bullet 2 against the same run:* every single-member group in run 2 arrived inline — a singleton
  payload here is ~20,600 prose + framing ≈ 22–23K serialized, under 27,000, with its content line
  (~20,560 escaped bytes) under the 24,000 refusal — so the scoped could-not-spill claim is not only
  stated correctly but visible in the run: on this store no singleton spilled and none was refused.
  ✓
- *The correction paragraph:* still accurate after the edit — names the eight-entry, 4,500-character
  draft, says it never ran and would not have spilled, arithmetic right (2 × 4,500 ≈ 9,000 <
  27,000), and the note's provenance sentence (lines 92–95) still describes it truthfully. The
  round-15 scoping edit is recorded in this file, which is where review-driven edits to a tool's
  prose belong; it does not need its own correction-log entry in the docstring. ✓
- *Finding 2, the citation:* note line 108 now reads
  "(`~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` — nothing is installed into the
  Zikaron repository itself)", which makes the byte-identical claim checkable from the citation and
  forecloses the reading that this repository carries the skill. ✓
- *Agreement sweep:* note lines 27–37 against docstring lines 11–20 — same 18-entry scoping, same
  pair-sizing inference, same "not a general fact" boundary with the same mature-store
  counterexample, same near-fresh-store explanation. The docstring omits the note's second
  (bare-maximal-gist) counterexample but names the gists in its scope clause and defers to the note
  for the full argument, which is the right division for a docstring. No sentence in either artifact
  now asserts the other's withdrawn form. ✓

**On delete-versus-repair, so the resolution is on the record here too:** the distinction stands as
round 15 stated it and the researcher has adopted — descriptive run-narrative gets deleted on
relapse; the analytical passages (release attribution, run 1's confound analysis, the sweep/release
distinction) are the reading the transcripts cannot carry alone and are repaired in place. Nothing
further to do.

### Findings

1. **[NITPICK] The docstring's pointer to the note is repo-relative from a file that lives outside
   the repository.** `~/zikaron-m18-evidence/seed-zk-spill-e2e.py` line 20 cites
   "`research/m18-spill-end-to-end.md`" — the same class as round 15's finding 2, in miniature. It
   is resolvable (line 37's `sys.path.insert` names `/home/nathan/Zikaron`, and the project has one
   `research/`), so this is genuinely optional: if the file is ever touched again, write
   `/home/nathan/Zikaron/research/m18-spill-end-to-end.md`. Do not reopen the round for it.

VERDICT: APPROVED

## Round 17 — 2026-09-14 — the post-approval gate decision, four changes

Reviewed after round 16's approval: `zikaron/install/targets.py` (`_SPILL_READ_NOTE` and its
comment), `design/build-plan.md` §M18's gate paragraphs (~1326–1339 and the done-when),
`design/harness.md`'s new "Reading a spilled payload" row (line 71) and its neighbours, and
`research/m18-spill-end-to-end.md` §"The approval gate: it prompts" plus §"Not measured here".
Checked against: `tests/test_harness_table.py` (the drift guard), `zikaron/service/paths.py`
(`runtime_dir`), `_merged_permissions`, and the shipped consolidator frontmatter (no
`permissionMode:` set, so the prompt genuinely fires in production — verified, not assumed).

**Summary judgment.** The decision itself is right and I will not argue for the rejected
`permissions.allow` entry — detail under finding 7. The D34 row is safe under the drift guard
(verified structurally: the fixture keys rows by `Fact` and refuses duplicates; every extractor is
applied only to named facts, so a prose-only row is exactly as parseable as the "Over-large MCP
tool result" row it imitates) and its content matches the code, which has no field behind it. But
the round's stated question — is each text true of what the code and the evidence support — comes
back **no** in four places: the installer note promises the prompt at a moment it will often not
occur and implies a once-ever grant that is per-session; the research note now says "measured" and
"not measured" about pagination in one section, under the heading that loses; the two new
measurements rest on a session cited nowhere and preserved nowhere, under a header that claims
every quoted line is durable; and the brief's own done-when still instructs the exact
`permissions.allow` entry the paragraph above it rejects. All are sentence-sized fixes.

### Findings

1. **[BLOCKER] `_SPILL_READ_NOTE` misstates when the prompt arrives, in both directions.**
   `zikaron/install/targets.py` ~117–124: *"so the **first consolidation** will ask"*. Two
   inaccuracies, each producing exactly the operator surprise the note exists to prevent. (a) The
   prompt fires only when a group actually **spills**; on the fresh store an operator has just
   installed into, the first consolidation plausibly never prompts — this milestone's own evidence
   is the e2e's first seeding, 8 entries, **zero spills** — so the promised prompt fails to arrive
   and "expected" reads as "something is broken". (b) Option 2 is **session-scoped**, so the prompt
   returns on the first spilled `Read` of *every new session*; "the first consolidation will ask"
   reads as once-ever, and an operator later re-prompted has been told, by us, to be suspicious of
   unexpected permission requests. On a mature store spilling is the majority path (the brief's own
   threshold section: median payload within 3% of the proven floor), so (b) is the *normal* case,
   not an edge. Concrete rewrite of the first sentence and a half: *"…given its path, so the first
   time a consolidation meets such a group — routine on a mature store, possibly never on a small
   one — Claude Code will ask whether it may read from `$XDG_RUNTIME_DIR/zikaron`. That prompt is
   expected, recurs in each new session because the grant below is session-scoped, and is not
   answered by this install: choose the option allowing that directory for the session."*

2. **[BLOCKER] The research note's §"Not measured here" now asserts both states of the pagination
   question, and the leftover sentence contradicts the paragraph above it.**
   `research/m18-spill-end-to-end.md` 180–191. The measured paragraph was prepended but the
   original entry's first sentence was never deleted, so the section reads "now measured, and it
   does … The brief's clause … can be closed. / Whether the multi-call pagination path works
   through a real consolidator, since no group in this corpus produced a spill file over `Read`'s
   per-read cap." — the exact both-closed-and-open defect FINDINGS records M14 being burned by,
   inside a section whose heading ("Not measured here") the new paragraph also contradicts. (The
   researcher's own summary says the entry "moved out of §Not measured here"; the file shows it did
   not move — it was duplicated.) Concrete edits: move the measured paragraph out into its own
   subsection (it belongs beside §"The approval gate", same run); delete the stale sentence; leave
   §"Not measured here" holding only the cross-model question and the naming-sentence ablation.
   While moving it, state the half that is genuinely closed: the run paged **by choice**, so the
   `offset`/`limit` mechanics against a real spill file are production-verified, but the
   **cap-forced** continuation — a truncation notice mid-file driving the next call — still never
   fired, because no file exceeded the cap. "The brief's clause can be closed" without that
   distinction overcloses it.

3. **[BLOCKER] Both new measurements are quoted from a session that is cited nowhere and preserved
   nowhere, under a header whose durability claim they now falsify.** The note's header (~8–10)
   says the evidence directory holds "nine files across three sessions … and every quoted line
   below came from there." The three-option prompt text (§"The approval gate") and the pagination
   call sequences (`limit=15`, `offset=13, limit=10`, `offset=22`) came from a **fourth** session
   — no session id, no date, no store, no transcript in `~/zikaron-m18-evidence/` — and the review
   brief's second file (`limit=11`, then `offset=11, limit=10`) is not in the note at all, though
   the note says "two spill files across several calls **each**" while quoting one. This is round
   10 finding 1's class, which was a blocker then for less: the transcript that could verify the
   pagination claims expires on `cleanupPeriodDays`. Concrete edits: name the session, date, and
   store in both new sections; copy its transcript (and consolidator subagent transcript) into the
   evidence directory and update the header inventory; quote both files' call sequences; and for
   the prompt dialog specifically — harness UI, plausibly absent from any transcript — say
   outright that the quote is the operator's own capture, the same
   recorded-testimony honesty the sweep paragraph already practises. Also identify which run "one
   under `permissionMode: auto`" (~163) refers to; nothing else in the note or evidence directory
   names such a run.

4. **[BLOCKER] The brief's done-when still instructs the install to do the thing the decision
   paragraph above it rejects.** `design/build-plan.md` ~1415–1417: "The run also settles whether
   `Read` of the runtime directory prompts for approval; the answer goes into `harness.md` beside
   the other gate measurements, **with a `permissions.allow` entry added if it does**." It does
   prompt, and ~1331 says the entry "was considered and rejected". A fresh session executing the
   done-when adds the rejected entry; this is the design record saying both things, ninety lines
   apart, in the normative brief. Concrete rewrite: "…prompts for approval — it does, and the
   answer is in `harness.md`'s 'Reading a spilled payload' row; the `permissions.allow` entry this
   clause originally promised was considered and rejected, above." (Withdraw-in-place shape, since
   the original clause was a commitment the measurement then argued out of.)

5. **[IMPROVEMENT] "The only point at which that grant is visible" overclaims in two of the three
   places the argument appears; the build-plan's own phrasing is the correct one.**
   `targets.py` ~122–123 ("this prompt is the only point at which that grant is visible") and the
   D34 row ("the one place D32's widening is visible to an operator") versus build-plan ~1335–1336
   ("the single point at which D32's widening becomes a **check** an operator sees rather than
   prose"). The grant *is* visible elsewhere: the shipped consolidator frontmatter carries `Read`
   in its `tools:` line on disk, and M16's own third-gate measurement is that a `permissions.allow`
   entry would have been read back at the user by the folder-trust dialog. What is unique to the
   prompt is that it is a *question* — the operator must answer it, not happen to read a file.
   Concrete edits: in the installer note, "…so this prompt is the only point at which that grant
   is put to you as a question"; in the D34 row, "…so this is the one place D32's widening is a
   check an operator answers rather than prose". Cheap, and it keeps the strongest form of the
   argument from resting on a word ("visible") the project's own measurements refute.

6. **[IMPROVEMENT] `harness.md` now measures a fourth operator-facing approval while its gate
   inventory still says three, and the section a reader is pointed at never mentions the new
   one.** Row 77 ("Approval gates | none | **three**, in order: folder trust, MCP load, per-call")
   and §"Three approval gates" (~296–320) both enumerate a world in which every gate is either the
   user's own or pre-answered by the install; the new row six lines below measures a prompting
   gate that is deliberately left live. A fresh session reading §"Three approval gates" — the
   named home of gate measurements, and where build-plan's done-when says the answer goes —
   concludes no interactive approval survives a default install, which is now false. Concrete
   edit, minimal churn: one sentence at the end of that section's intro ("A fourth interaction —
   the consolidator's first `Read` of a spilled payload — prompts by design and is deliberately
   not pre-answered; see the 'Reading a spilled payload' row"), and append to row 77's Claude cell
   "…plus the spill-`Read` prompt, deliberately left live (row below)". Verified safe against the
   drift guard: neither `_quantity` nor `_leading_bold` is applied to the "Approval gates" row.

7. **On the question asked directly: the rejected `permissions.allow` entry is not the better
   call, and I would add one argument the paragraph omits.** The decision's three stated reasons
   hold (the frontmatter really is unscopable per the probe's own schema; session-scoped really is
   inexpressible in a settings file; D10 really does put a human at the keyboard). The omitted
   argument: on a mature store spilling is the **majority** path, so a permanent entry would have
   the widened `Read` grant exercised silently on essentially every consolidation forever, while
   the prompt costs one answer per session — and the per-session recurrence finding 1 makes the
   note admit is therefore a *feature*, periodic re-visibility of the one D32 widening, not a
   friction to apologise for. Worth a clause in build-plan ~1334 when finding 4's edit is made
   nearby. No change of verdict rides on this item.

8. **[NITPICK] "a checked-in file" is the wrong phrase on the project's own architecture, twice.**
   build-plan ~1337 and `targets.py` ~114: the candidate entry would live in
   `.claude/settings.local.json`, which the installer targets *because* it is machine-local and
   never committed (`ClaudeCodeTarget._settings`'s own docstring). Say "an installed settings
   entry" or "anything a settings file could express".

9. **[NITPICK] Two citation residues.** (a) `_SPILL_READ_NOTE` names `$XDG_RUNTIME_DIR/zikaron`
   unconditionally; `paths.runtime_dir` falls back to `/tmp/zikaron-<uid>` when the variable is
   unset, so the prompt would then name a directory the note did not. One parenthetical. (b) The
   new D34 row says "measured in an operator-driven session" with no evidence pointer, while its
   neighbours cite their notes (`mcp-result-truncation`, `installer-probe` §4); cite
   `m18-spill-end-to-end` — which finding 3's edits will have made a citation actually worth
   following.

VERDICT: NEEDS_CHANGES

## Round 18 — 2026-09-14

Verified against `~/zikaron-m18-evidence/` directly, not the researcher's summary: all five
transcripts' timestamps, spill counts, permission modes, Read-call inputs, and — via the
`numLines`/`startLine`/`totalLines` triple every Read result records — exactly which lines of each
spill file the consolidators actually saw. Artifacts re-read: `research/m18-spill-end-to-end.md`,
`zikaron/install/targets.py` (`_SPILL_READ_NOTE` and both comments), `design/build-plan.md` §M18,
`design/harness.md` rows 71–72/77 and §"Three approval gates".

**Summary judgment.** The evidence table is real: every cell I could check against the transcripts
holds — spill counts 0/4/3/4/5, modes `bypassPermissions`×3 / `auto` / `auto`-then-`default`
("reaches `default`" is exactly right: the main transcript shows `permissionMode":"auto"` at lines
3 and 21, `"default"` at 39 and 46), both quoted call sequences byte-accurate, zero truncation
notices, and the closed/open split on pagination is stated correctly. But the verification the
round asked for found the thing summaries could not: **the windowed sessions did not walk the
files to the end.** The gate run's offsets hop *exactly over the members' content lines* — it read
gists, skipped prose, and discarded four members whose content no one ever read — and the note
currently records the opposite. Plus one stale paragraph at the top of the note still asserts the
gate is "not measured here", and two round-17 edits claimed applied did not land in the brief.

**The verification record.**
- Spill counts by distinct pointer path: 82adbc5b 4, c1747b90 3, 6ccd7dd5 4, ae45b47a 5,
  88999a21 0 ✓. Headless subagents' Reads carry no `offset`/`limit` (4 and 3 whole-file calls) ✓.
- 6ccd7dd5 quote block vs `agent-acf0b8b8683ed8655.jsonl` lines 31/34/37/52/58: `limit=15`;
  `offset=13,limit=10`; `offset=22`; `limit=11`; `offset=11,limit=10` — byte-accurate ✓.
  ae45b47a summary vs `agent-a1a96782eaa36bf20.jsonl` lines 49–63: `limit=7`, then offsets
  7/12/19/24/26 — accurate ✓; "another in three" = a1f279's three calls ✓.
- `truncat` matches in either interactive subagent transcript: zero ✓.
- Decode note for whoever re-checks: each Read result line holds the file text twice (rendered
  result plus `file.content`), so raw pattern counts halve; a 39-line spill file holds 3 records,
  a 46-line one 4, and member accounting for ae45b47a (2+2+2+2+3 spilled + 1 inline promoted = 12,
  the seeded corpus exactly) identifies the uuid recurring across three of its files (8b9bc789) as
  the long-term candidate/anchor, not a member.
- Round-17 findings 1, 2, 4, 5, 6, 9 landed and verify in the files (6 with the caveat in finding
  4 below); findings 7 and 8 landed in `targets.py` only — see finding 3.

### Findings

1. **[BLOCKER] "Walking forward by offset to the end" is refuted by the transcripts it cites, and
   the section omits what the windows were actually doing: skipping the prose, then dispositioning
   the group.** Note §"Windowed reading" (~191–213). Per-file coverage, from the
   `numLines/startLine/totalLines` triples:
   - 6ccd7dd5 (`agent-acf0b8b8683ed8655.jsonl`): 53ee81ed **39/39 whole** (line 13); 78301729
     **46/46 whole** (23); e38eb0e0 windowed **and completed** — 1–15, 13–22, 22–39 of 39
     (32/35/38), the *only* windowed file in either session that reached its end; 76af39be
     **stopped at line 20 of 39** (53/59) — both members' prose was read, the unread tail being
     the candidate record plus framing, and the group completed across **two** `discard` calls
     (line 55 naming only `da2daf29` after reading lines 1–11; line 61 naming `9028f649` after
     lines 11–20).
   - ae45b47a (`agent-a1a96782eaa36bf20.jsonl`): a1a084e **39/39 whole** (12); b75db87 **stopped
     at 30/39** (20) — all three records' prose sits inside 1–30, tail framing only; a1f279 read
     1–10, 1, 13–22 of 39 (28/31/34) — member **e6d8a7fe's content line (~11) was never read**,
     and the one-call discard at line 36 absorbs it anyway; aa1d5cb **18/39** (42), both members'
     prose read, tail framing; 23391efa read 1–7, 7–10, 12–17, 19–24, 24, 26–40 of 46
     (50–64) — the offsets hop **exactly over lines 11, 18 and 25, the three members' content
     lines**, gists all read, and the discard at line 66 absorbs all three.
   Tally: of 9 spilled serves across the two sessions, 3 were whole reads, **1** was windowed to
   the end, 5 stopped early or skipped interior lines; of the gate run's 11 spilled members,
   **4 were discarded with prose nobody ever read**. So the section's opening sentence is false in
   both directions ("rather than whole" — a third were whole; "to the end" — one of six windowed
   files got there), and the true finding goes unrecorded: given pagination, this consolidator
   **chose** to reduce members to their gists — §Rejected's "a gist is never sufficient to decide
   from", resurrected by the agent's own behaviour, against the pointer's own "read it, to its
   end" instruction, in precisely the two sessions run under real permission modes. State the
   mitigations with it: the verb was `discard`, which D16 keeps recoverable (a `merge` from a
   skimmed file would have been the destroy-prose-nobody-read case outright); this corpus is five
   rotated templates and each session had already read identical prose whole in its first spilled
   file, so skimming was economically defensible *here*; and both headless runs read every file
   whole, so what flips the behaviour (mode, context pressure, mid-session habituation) is
   unmeasured. Two design-relevant observations worth one sentence each: the never-lose guard
   forces reading a member's *header* (uuid + `expected_version` sit above the content line), not
   its prose — 76af39be's two-step discard versus a1f279's one-step shows exactly where that
   floor is; and compliance with "read it, to its end" is now a measured 5-of-9, so the
   capability half of the spill design is verified while the compliance half has its first
   counter-evidence. Concrete edits: rewrite the opening sentence to what the transcripts show;
   add the coverage tally; record the skim-and-discard finding with its mitigations; and either
   carry it to FINDINGS or say in the note why not. The brief's done-when ("shown reading the
   spill file to its end") is satisfied by run 2's whole-file reads and needs no change.

2. **[BLOCKER] The note's fourth paragraph still asserts the gate is "not measured here", forty
   lines above the section that measures it.** Note ~24–27: "Run under `--permission-mode
   bypassPermissions`, which makes it a control … so whether `Read` of the runtime directory
   prompts is **not measured here** and needs an interactive session." Written when the note
   covered one headless run; now it sits directly beneath a table listing two operator-driven
   sessions and contradicts §"The approval gate: it prompts" — the same both-states defect as
   round 17's finding 2, one section higher. Concrete rewrite, scoped: "The three headless
   sessions ran under `--permission-mode bypassPermissions`, which makes them controls: they
   exercise the mechanism with the gate blinded, since a headless run approves everything
   (`claude-code-installer-probe.md` §8). The gate itself is measured in the two operator-driven
   sessions — §'The approval gate: it prompts'."

3. **[IMPROVEMENT] Two round-17 edits are claimed applied and landed in `targets.py` only — the
   brief still carries both originals.** (a) Round-17 finding 8: `design/build-plan.md` ~1337
   still reads "narrower than anything a **checked-in file** could express"; the candidate entry
   would live in `.claude/settings.local.json`, which the installer targets *because* it is never
   committed. Say "an installed settings entry". (b) Round-17 finding 7: the decision paragraph
   (~1331–1339) still lacks the majority-path argument that the `targets.py` comment now carries
   ("on a mature store spilling is the majority path, so a permanent entry would have the widened
   grant exercised silently on essentially every consolidation forever — while the prompt's
   per-session recurrence is periodic re-visibility of the one D32 widening"). One clause where
   the paragraph lists its "Against an entry" reasons.

4. **[IMPROVEMENT] harness.md now says the install answers the folder-trust gate, twice, and its
   own gate table says the opposite.** Row 77: "**three** answered by the install, in order:
   folder trust, MCP load, per-call"; §"Three approval gates" closing sentence: "So a default
   install answers three gates and leaves one." The section's own table, one screen below, has
   gate 1 "Answered by: **nothing we write — it is the *user's* decision**", and M16's measurement
   is that the install makes that gate *worse* (our `permissions.allow` is read back as a
   warning). The accurate accounting: the install **pre-answers two** (MCP load, per-call); the
   user answers folder trust once per directory; the spill-`Read` prompt recurs per consolidating
   session. Concrete edits — row 77: "**three**, in order: folder trust (the user's own — the
   install's entries are read back at them there), MCP load, per-call; the install pre-answers
   the last two — measured, see §'Three approval gates' — **plus the spill-`Read` prompt,
   deliberately left live** (row below)"; section: "So a default install pre-answers two gates
   and leaves two questions for a human: folder trust, once per directory, and the spill-`Read`
   prompt, once per consolidating session." Drift-guard safe per round 17's structural check
   (prose cell, no extractor).

5. **[IMPROVEMENT] The header promises "every transcript-derived line below is attributed to one
   of these", and the note's largest section, plus the interactive runs' store lineage, plus one
   table label, fall short of it.** (a) §"What the run did" never names `82adbc5b…` — its only
   key is pid 905053 in a filename; open the section with the session id. (b) Neither new
   section says what store the interactive runs consolidated. The transcripts show it was
   *reseeded on top of a consolidated store*: a long-term record recurs as candidate/anchor
   across three of ae45b47a's five spill files (8b9bc789…) and across 6ccd7dd5's (8e9369eb…), so
   groups carry 3–4 records and 39/46-line files rather than run 2's shape — one sentence of
   lineage makes the group arithmetic checkable. (c) The 88999a21 row's label "headless, first
   seeding" points a checker at the wrong corpus: its consolidator transcript shows **15
   `next_group` calls — the 14-group consolidation of the 18-entry store** (10 singletons + 4
   pairs, all inline), not the 8-entry first seeding. Relabel (e.g. "headless, seeding-phase —
   consolidated the 18-entry store, 14 groups, all inline"), and say where the 8-entry no-spill
   observation lives if it has a transcript at all.

6. **[NITPICK] The same session carries two dates because the table and the prose use different
   clocks.** The table stamps sessions in what is evidently local session-end time (UTC−5:
   ae45b47a's first event is 05:40:21Z, table 00:49) while §"A second run" dates c1747b90
   "2026-09-14" from its UTC transcript stamps and the table says 09-13 20:21. One parenthetical
   under the table — "times are session end, local (UTC−5); transcript stamps are UTC" — or
   re-date the section heading to match the table.

VERDICT: NEEDS_CHANGES

## Round 19 — 2026-09-14

Verification round, as briefed. I did not take round 18's tally or the researcher's re-check on
trust: every `Read` call input and every `numLines`/`startLine`/`totalLines` triple in both
operator-driven subagent transcripts, and every call input in both headless ones, was re-extracted
from `~/zikaron-m18-evidence/` for this round. Artifacts re-read in full or at the changed
sections: `research/m18-spill-end-to-end.md`, `design/build-plan.md` §M18, `design/harness.md`
rows 71–72/77 and §"Three approval gates", `zikaron/install/targets.py` (`_SPILL_READ_NOTE` and
both comments). Also read against the round-18 findings: `FINDINGS.md`'s M18 item.

**Summary judgment.** The rewritten windowed-reading section survives the hard check: the coverage
table, the 3/1/5-of-9 tally, the 4-of-11 unread-discard count, and the capability-verified /
compliance-not-measured-either-way split all reproduce exactly from the transcripts, and the
narrowed conclusion is no wider than the evidence — with one residue, which is the section's own
bolded opening sentence contradicting its tally three paragraphs down. Round-18 findings 2–6 all
landed and verify in the files. What blocks this round is outside the four artifacts but inside
round 18's findings: `FINDINGS.md`'s always-loaded M18 item still describes the gate question as
open and instructs the rejected `permissions.allow` entry, and the carry-to-FINDINGS clause of
round 18's finding 1 was the one piece of that blocker that did not land.

**The verification record.**
- ae45b47a (`agent-a1a96782eaa36bf20.jsonl`), call inputs and result triples: `…435740c`
  (a1a084e92435740c) whole, 1..39 of 39 ✓; `…4c16b30` limit=30 → 1..30 of 39 ✓; `…a907e8d`
  limit=10 / offset=1,limit=1 / offset=13,limit=10 → 1..10, 1, 13..22 of 39, unread 11–12 and
  23–39 ✓; `…9558a32` limit=18 → 1..18 of 39 ✓; `…794e5d2` limit=7 / offset=7,limit=4 /
  offset=12,limit=6 / offset=19,limit=6 / offset=24,limit=1 / offset=26,limit=15 → 1..7, 7..10,
  12..17, 19..24, 24, 26..40 **of 46** — skips 11, 18, 25 ✓ (and leaves 41..46 unread, see
  finding 4).
- 6ccd7dd5 (`agent-acf0b8b8683ed8655.jsonl`): `…54a693b` whole 39/39; `…bb420ae` whole 46/46;
  `…38eb0e0` limit=15 / offset=13,limit=10 / **offset=22 with no limit** → 1..15, 13..22, 22..39
  of 39, complete — the one windowed-to-end serve; `…6af39be` limit=11 / offset=11,limit=10 →
  1..11, 11..20 of 39, tail unread ✓.
- Tally across both sessions: whole = 3 (435740c, 54a693b, bb420ae); windowed to end = 1
  (38eb0e0); stopped early or skipped = 5 (4c16b30, a907e8d, 9558a32, 794e5d2, 6af39be); total 9 ✓.
  Unread-content discards: 1 member in a907e8d + 3 in 794e5d2 = 4 of 11 ✓.
- Headless: 82adbc5b's subagent made 4 `Read` calls and c1747b90's 3, none carrying `offset` or
  `limit` — "both headless runs on the same corpus read every file whole" ✓.
- Round-18 findings landed: (2) note lines 29–32, scoped to the three headless sessions with the
  pointer ✓; (3a) build-plan ~1337 "an installed settings entry" ✓; (3b) build-plan ~1338–1342
  majority-path argument with the per-session-recurrence-as-re-visibility clause ✓; (4)
  harness.md row 77 and §"Three approval gates" both read "pre-answers two … leaves two questions
  for a human" with folder trust named as the user's own ✓; (5a) §"What the instrumented run did
  (`82adbc5b…`)" ✓; (5b) reseeded-store lineage sentence under the table ✓; (5c) 88999a21
  relabelled to the 18-entry, 14-group consolidation ✓; (6) the clocks parenthetical ✓.

### Findings

1. **[BLOCKER] `FINDINGS.md`'s M18 item instructs the rejected `permissions.allow` entry and
   calls the gate question open — the always-loaded file now contradicts all four artifacts, and
   round 18 finding 1's carry-to-FINDINGS clause never landed.** `FINDINGS.md` ~181–184: *"What
   is still left is one question a headless run cannot answer: whether `Read` of the runtime
   directory trips the per-call approval gate. If it does, the installer needs a
   `permissions.allow` entry, which is a code change."* The question is answered (it prompts,
   measured), and the entry was considered and **rejected** — build-plan ~1331, harness.md row 71,
   `_SPILL_READ_NOTE`, the research note. A fresh session resuming from FINDINGS sets out to add
   the rejected entry, which is round 17 finding 4's defect relocated into the one file every
   session loads. Same entry, same class: the phase header (~57) says the e2e run "is the one
   thing outstanding" while the body (~172) says "The end-to-end run is done" — both states,
   ninety lines apart. And the item knows nothing of the two operator-driven sessions, the gate
   decision, or the windowed-reading observation, so the round-18 ask ("either carry it to
   FINDINGS or say in the note why not") remains unanswered in both files. Concrete edits:
   replace ~181–184 with the resolved state ("the gate question is answered: `Read` of the
   runtime directory **prompts**; the harness's own option grants the directory per session, and
   a `permissions.allow` entry was considered and rejected — reasoning in `design/build-plan.md`
   §M18; the installer's third note warns the prompt is coming"); reconcile the phase header with
   the body; and either add one sentence carrying the skim observation ("given pagination on a
   degenerate corpus the consolidator reduced members to gists before dispositioning — discards
   only; compliance with 'read it, to its end' is unmeasured either way —
   `research/m18-spill-end-to-end.md` §'Windowed reading'") or record in the note why it is not
   carried.

2. **[IMPROVEMENT] The answer to the question the round asked: the section is still wider than
   the evidence in exactly one sentence — its own bolded opener.** Note ~198: *"Both
   operator-driven sessions read spill files in windows. **They did not read them to the end.**"*
   The second sentence is falsified by the section's own tally two paragraphs down: 1 of the 6
   windowed serves was carried to its end (`38eb0e0`, third call `offset=22` with no limit,
   landing 22..39 of 39), and 4 of 9 serves in total reached the end. This is the residue of the
   round-18 blocker's "false in both directions" sentence — the "rather than whole" half was
   fixed, the "to the end" half survives as an absolute. It is also the bolded line a future
   session will quote while not re-deriving the table. Concrete rewrite: *"Both operator-driven
   sessions read spill files in windows, and five of the six windowed serves never reached the
   file's end — where all seven headless serves were whole-file reads."* Everything after it
   stands as written.

3. **[IMPROVEMENT] The tally spans both sessions but the coverage table shows only `ae45b47a…`,
   so "3 read whole, 1 windowed to its end" cannot be derived from the note — and the one
   windowed-to-end serve, the existence proof for "a file *was* windowed to its end", is in the
   session the table omits.** Note ~199–209: the block is introduced as coverage "in `ae45b47a…`"
   and its five rows yield 1 whole, 0 windowed-to-end, 4 stopped/skipped; the other 2 wholes, the
   1 complete windowed read, and the fifth stopped serve are all in `6ccd7dd5…`, unshown. A
   checker gets exactly as far as I did in round 18 only by opening the transcript. Four rows
   close it, in the note's own format:
   ```
   …54a693b   whole                       lines 1..39 of 39
   …bb420ae   whole                       lines 1..46 of 46
   …38eb0e0   limit=15 / offset=13 limit=10 / offset=22
                                          1..15, 13..22, 22..39  complete
   …6af39be   limit=11 / offset=11 limit=10
                                          1..11, 11..20 of 39    tail unread
   ```

4. **[NITPICK] Two precision residues in the same section.** (a) The `794e5d2` row says only
   "skips lines 11, 18, 25", but its final window stopped at line 40 of 46 — lines 41..46 are
   also unread; every other partial row carries its "tail unread" annotation, so add "tail
   41..46 unread" (the tail is framing, which is why the tally still counts it once). (b) "two
   things bound it here, and both would need re-checking on real prose" — the second bound does
   not: the never-lose guard's header floor is structural (a disposition needs the uuid and
   `expected_version`, which only the header carries), and it is the *first* bound — that the
   verb happened to be `discard` rather than `merge` — that is contingent on this run. Scope the
   clause to the first.

5. **[NITPICK] harness.md row 77 points the wrong way: "(row below)".** The "Reading a spilled
   payload" row is line 71, six rows *above* the Approval-gates row. Say "(row above)". For the
   record, the error is mine — round 17's suggested wording contained it and was applied
   faithfully.

6. **[NITPICK] The 8-entry no-spill claim is the one observation left unattributed under a header
   that promises attribution.** Note ~40: "A first seeding of 8 entries totalling 21,408
   characters produced no spill at all" names no session, and 88999a21 is now correctly labelled
   as the 18-entry consolidation — round 18 finding 5's last clause ("say where the 8-entry
   no-spill observation lives if it has a transcript at all") did not land. One parenthetical
   either names the unpreserved session, or replaces observation with arithmetic, which is
   stronger anyway: 21,408 characters of ASCII prose at even the maximum measured framing
   (1.165×) serializes to ≈24,900 bytes, under the 27,000-byte threshold for any possible
   grouping.

VERDICT: NEEDS_CHANGES

## Round 20 — 2026-09-14

Verification round, per the brief, with `FINDINGS.md` read end to end (all 895 lines) and the
rebuilt coverage block re-extracted from both subagent transcripts rather than checked against
round 19's figures. Also re-read: `research/m18-spill-end-to-end.md` in full,
`design/build-plan.md` §M18 gate paragraphs and done-when, `design/harness.md` rows 71/77 and
§"Three approval gates", and `zikaron/install/assets.py` (to confirm the "this pointer is
Zikaron's own" sentence §"Not measured here" quotes actually exists in the shipped guidance — it
does, `SPILL_GUIDANCE`, line 209).

**Summary judgment.** All six round-19 findings landed and verify, and the rebuilt coverage block
is exact: every call input and every `numLines`/`startLine`/`totalLines` triple in both blocks
reproduces from the transcripts, every abbreviated file label resolves as a substring of a real
spill filename, the 3/1/5-of-9 tally, the 7 whole-file headless serves, and the new bolded opener
are all derivable and true. The corpus audit also holds where I probed it: seventeen-phrase spot
checks find superseded phrasings only in `researcher.json`, which is untracked session state, not
an artifact. What blocks the round is one sentence the new grep-based verification is structurally
unable to catch: `FINDINGS.md`'s M18 item still opens with "the end-to-end run is what remains" —
the same claim round 19's blocker quoted from line 57, surviving in different words in the item's
own bolded first line, nine lines above "The end-to-end run is done."

**The verification record.**
- 6ccd7dd5 (`agent-acf0b8b8683ed8655.jsonl`): `53ee81ed154a693b` whole 1..39/39 ✓;
  `78301729fbb420ae` whole 1..46/46 ✓; `a717ea6de38eb0e0` limit=15 / offset=13,limit=10 /
  offset=22 (no limit) → 1..15, 13..22, 22..39 of 39, complete ✓; `59666bdb76af39be` limit=11 /
  offset=11,limit=10 → 1..11, 11..20 of 39, tail unread ✓. The note's labels are the first 7 hex
  of each filename's random segment ✓.
- ae45b47a (`agent-a1a96782eaa36bf20.jsonl`): `a1a084e92435740c` whole 1..39/39 ✓;
  `b75db87cc4c16b30` limit=30 → 1..30/39 ✓; `a1f279203a907e8d` limit=10 / offset=1,limit=1 /
  offset=13,limit=10 → 1..10, 1, 13..22 of 39, 11–12 and 23..39 unread ✓; `aa1d5cb669558a32`
  limit=18 → 1..18/39 ✓; `23391efac794e5d2` six windows → 1..7, 7..10, 12..17, 19..24, 24,
  26..40 of 46, skips 11/18/25, tail 41..46 unread ✓. Labels are the last 7 hex ✓ (see finding 4).
- Headless serve count: 82adbc5b 4 `Read` calls, c1747b90 3, zero carrying `offset`/`limit` —
  "all seven headless serves were whole-file reads" ✓. Opener arithmetic: 6 windowed serves, 5
  short of the end, 1 complete ✓.
- Round-19 findings landed: (1) gate paragraph replaced with the resolved state incl. the
  rejection pointer and the installer's third note ✓, phase header line 57 now "built, measured
  end to end, and uncommitted" ✓, skim observation carried with the degenerate-fixture reading,
  the `discard`/D16 mitigation, and the unmeasured-on-real-prose caveat ✓; (2) opener rewritten
  as suggested ✓; (3) both sessions' coverage shown ✓; (4a) `794e5d2` carries "tail 41..46
  unread" ✓; (4b) contingent/structural bounds split correctly, only the verb flagged for
  re-checking ✓; (5) row 77 "(row above)" ✓; (6) 8-entry claim now arithmetic — 21,408 × 1.165 ≈
  24,900 < 27,000, sound, and needs no attribution ✓.
- Also checked: FINDINGS' one-clause compression of the gate rejection ("`Read` is unscopable in
  subagent frontmatter, so this is the one place D32's widening is a check an operator answers")
  is a fair reading of build-plan ~1335–1336's first "Against an entry" reason, with the pointer
  carrying the rest ✓; harness.md §"Three approval gates" and the done-when rewrite from rounds
  17–18 are stable ✓.

### Findings

1. **[BLOCKER] `FINDINGS.md`'s M18 item still opens with "the end-to-end run is what remains" —
   round 19's both-states blocker, surviving in words the grep audit never enumerated.**
   `FINDINGS.md` ~164–165: *"**M18 — a group too big for the harness to deliver. Built, APPROVED
   after nine rounds, and \*uncommitted\*; the end-to-end run is what remains.** "* versus line 57
   ("built, measured end to end") and line 173 ("**The end-to-end run is done and it changed the
   milestone.**"). The phase header was fixed; the item's own bolded first line — the
   highest-salience sentence of the entry, the one a resuming session reads first — was not, and
   a fresh session obeying it sets out to re-run a two-operator-session experiment that is
   finished. The same sentence carries a second stale claim: "APPROVED after nine rounds"
   describes round 9's approval as if it stood, when the end-to-end run reopened the milestone at
   round 10 and every round since has been its corrections — the review file this review sits in
   is the falsifying evidence. Concrete edit: *"**M18 — a group too big for the harness to
   deliver. Built, measured end to end, and uncommitted; in review**
   (`reviews/m18-payload-spill-review.md` — round 9 approved the implementation, the e2e run
   reopened it, and the round count is settled only at convergence)."* On the method, since the
   researcher changed it this round: the global-replace-plus-grep discipline is real progress and
   the audit's cleanliness verifies, but it finds the *phrasings* the reviewer quoted, not the
   *claim* — this instance survived precisely because it states the superseded claim in words
   nobody listed. The check that catches this class is one end-to-end read of the changed item
   after the edits land, which is also how this round found it.

2. **[IMPROVEMENT] The methodological paragraph's two counts are stale, inside the entry whose
   subject is prose going stale against evidence.** `FINDINGS.md` ~196–202: "**Seven times in
   this milestone**, prose asserted what the adjacent code or transcript contradicted … Sixteen
   review rounds; rounds 10-16 were all that single defect recurring." The review file holds 19
   rounds (20 with this one), and rounds 17–19 each added instances of exactly that defect class
   — the installer note's prompt-timing misstatement, the note asserting both states of the
   pagination question, "walking forward by offset to the end" refuted by the transcripts it
   cited, and round 19's FINDINGS blocker itself. So both numbers undercount the phenomenon the
   paragraph exists to record. Either update both at convergence (when the final round count is
   known) or drop the precision: "across more than a dozen instances … every round from 10 on
   was that single defect recurring somewhere new." Do not leave a wrong count in a paragraph
   about wrong prose.

3. **[NITPICK] The finding-6 edit left a sentence splice in the research note.**
   `research/m18-spill-end-to-end.md` ~40–44: "…under the 27,000-byte threshold for any grouping
   of it. and a second pass adding ten larger ones brought the store to 18." The replacement of
   the first clause orphaned the old sentence's continuation. Fix: "…for any grouping of it. A
   second pass adding ten larger entries brought the store to 18."

4. **[NITPICK] The coverage block's file labels use two different abbreviation schemes with no
   legend.** The 6ccd7dd5 block's labels are the *first* 7 hex of each filename's random segment
   (`53ee81e` ← `53ee81ed154a693b`), the ae45b47a block's are the *last* 7 (`435740c` ←
   `a1a084e92435740c`). Both resolve by grep, so nothing is wrong — but a checker comparing
   against round 18's 8-char prefixes has to discover the scheme change themselves. One
   parenthetical under the block ("labels are fragments of each spill file's random filename
   segment") closes it; unifying the scheme is optional.

VERDICT: NEEDS_CHANGES

## Round 21 — 2026-09-14

Per the brief: the `FINDINGS.md` M18 item (lines 164–213) and its phase header (57–59) read end to
end as one passage, then checked against the four artifacts; round-20 findings 2–4 verified in
place. Also re-read: round 19 and 20 in this file (for the recorded geometry of the instance the
methodological paragraph now cites), `research/m18-spill-end-to-end.md` §"The store" and
§"Windowed reading", `design/build-plan.md` §M18 done-when (~1404–1424),
`research/claude-code-mcp-result-truncation.md` (the ≈29,923 derivation), and
`research/consolidation-payload-sizes.md` (both tables).

**Summary judgment.** All four round-20 findings landed: the opening is the suggested resolved
form with no doubled `**` and no splice, a corpus grep finds no residue of "what remains" /
"APPROVED after nine rounds" / "one thing outstanding" anywhere in `FINDINGS.md`, the research
note's spliced sentence now reads cleanly with the arithmetic intact, and the label legend sits
above the coverage blocks. The end-to-end read of the item verifies almost everywhere I probed it:
opening vs. this file's round 9/10 history, ≈29,923 tokens (44,000 × 0.68006, truncation note line
66), 67/116 at 27,000 bytes (payload-sizes line 82), 217 KB in tmpfs (e2e note line 158), the
release/sweep verification split (note lines 144–154), the gate paragraph vs. build-plan
~1420–1423, the skim paragraph vs. §"Windowed reading", and the done-when's every clause including
"read to its end" (three whole serves plus the one windowed-to-end serve). What keeps the round
open is one clause: the edit that removed round 20's two stale counts introduced a new ordinal
that verifies against nothing — so the read-back check demonstrably narrows this defect class (it
caught two introduced errors this round, per the researcher's own account) without closing it,
which is itself consistent with the paragraph's thesis.

**The verification record.**
- Round-20 finding 1: `FINDINGS.md` 164–167 now reads "Built, measured end to end, uncommitted,
  and in review (`reviews/m18-payload-spill-review.md` — round 9 approved the implementation, the
  end-to-end run then reopened it, and every round since has been that run's corrections)." ✓ —
  consistent with this file's round headers, bold balanced, and grep finds no superseded phrasing
  anywhere in `FINDINGS.md` ✓.
- Round-20 finding 2: both counts gone from ~198–209; the paragraph points at this file, records
  that the tally kept growing after every round that claimed to end it, names both mechanical
  causes (replace-once + assert that cannot fail on a partial fix; phrasing-enumerating audits),
  and adds round 20's instance ✓ — with one residue, finding 1 below.
- Round-20 finding 3: e2e note ~42–44 now "…under the 27,000-byte threshold for any grouping of
  it. A second pass adding ten larger entries brought the store to 18, and grouping over those 18
  came out at one or two members — 10 singletons and 4 pairs…" ✓; the 21,408 × 1.165 ≈ 24,900
  arithmetic is intact ✓.
- Round-20 finding 4: "Labels are fragments of each spill file's random filename segment." at note
  line 204, above both coverage blocks ✓.
- Passage-level checks that found nothing: "read every file on the exact path" is consistent with
  both coverage tables (all 9 files served across the two operator sessions, all 7 headless
  whole); "five templates rotated twelve times" matches the note's "twelve entries … from five
  rotated templates"; the 12–33% trimming loss is consistent with the candidates-kept column
  (306/459 = 67% kept at 25,000); the phase header's "every question its done-when asked is now
  answered by measurement" holds against build-plan 1404–1424 — the ≥17,275-byte-line requirement
  is satisfied by the 20,499-character-mean corpus, the gate answer and the rejected
  `permissions.allow` entry are recorded in the done-when itself, and the pagination-acceptance
  clause covers the unexercised continuation — noting `./check.sh`'s exit 0 was still running per
  the researcher's state note, with this round's edits confined to files no test parses.

### Findings

1. **[IMPROVEMENT] The methodological paragraph's new instance description carries an ordinal that
   verifies against nothing — a fresh wrong count in the paragraph round 20 said must not hold
   one.** `FINDINGS.md` ~203–204: *"and this very entry opening with a claim its own fourth line
   refutes."* The recorded geometry of that instance is this file's round 20: the claim lived in
   the entry's bolded **first** line and "The end-to-end run is done" stood **nine** lines below
   (today it is the twelfth line of the entry, line 175). No counting of lines, sentences, or
   paragraphs in either state yields "fourth", so a future verifier — and every round of this
   review has been a verifier — fails on it and burns time deciding whether they have the wrong
   revision. The present tense "refutes" compounds it for this item specifically, because the
   reader is *inside* the entry and can see no such contradiction — the defect was fixed this
   round. Concrete edit, keeping the list's shape: replace the clause with *"and this very entry
   opening with a claim its own body refuted nine lines down"* (or drop the geometry entirely:
   *"and this very entry having opened with a claim a later line of it refuted"*). This is the
   round's only open item; everything else verified.

2. **[NITPICK] "the review file has the running tally" promises a number the file does not
   contain.** `FINDINGS.md` ~199: this file holds the running *record* — the instances are
   scattered across 21 rounds and a reader must derive any count themselves; no tally exists as a
   thing to look up. One word closes it: "the review file has the running record". Optional.

VERDICT: NEEDS_CHANGES

## Round 22 — 2026-09-14

Per the brief: round-21 findings verified in place; then the `FINDINGS.md` M17 item (216–265) and
M16 item (266–323) read end to end, each claim checked against its named evidence —
`reviews/m17-cold-start-review.md` (round structure and verdicts), `research/m17-cold-start-ab.md`
(every number the item quotes), `zikaron/core/store/store.py` 472–475,
`research/claude-code-dogfood-checkpoint.md` (the "what it settled" list),
`FINDINGS-archive.md` ~870–873, and `reviews/m16-dogfood-checkpoint-review.md` (exists). Because
the M17 item points into them ("Priority item 6 below carries the numbers"), priority item 6's
tail and the two un-numbered paragraphs after it (`FINDINGS.md` 415–460) were read as part of the
passage. The resume block (57–110) was re-read to adjudicate the structural question the brief
asks.

**Summary judgment.** Round 21's two findings landed exactly as specified, and the researcher's
own three self-caught corrections verify. The two named items are quantitatively sound — every
number I checked reproduces from its source, including the full A/B table, the seven-round review
structure, and a line-exact `store.py:472-475` citation — but reading them *end to end with what
they point at* finds the both-states defect twice more, in its largest instances yet: the file
says M17's production defect is fixed and measured, then 170 lines later presents it as live,
unfixed, and awaiting a milestone; and the resume block still instructs "M16's first act" for a
milestone that landed APPROVED a month ago — and instructs the very act M16's own record says the
operator corrected as wrong. Round 20's end-to-end read of all 895 lines missed both, which is
itself the methodological paragraph's thesis: that audit verified the M18 claim set and saw
nothing outside it.

**The verification record.**
- Round-21 finding 1: `FINDINGS.md` 203–204 now "and this very entry having opened with a claim a
  later line of it refuted" — geometry-free, past tense, no ordinal ✓. Finding 2: line 199 "the
  review file has the running record" ✓.
- The researcher's three self-caught M17-item corrections: line 222's "What is not done is the
  A/B" clause is gone and grep finds no residue; "Four mutations" is now countless; both
  paragraphs wrap under 100 characters ✓.
- M17 item vs evidence: seven rounds, round 4 APPROVED (brief), round 5 reopened for the
  implementation, round 7 APPROVED (code) — matching "four on the brief and three on the code" ✓;
  operator decision after round 2, dated 2026-08-19 ✓; A/B numbers 805→242 idle, 1157→395 load,
  0/5 vs 5/5, 241 B relay vs 1513 B block, 827→809 idle end-to-end, load-arm `surface` slower
  (1348 vs 1215), idle old-arm 3/3, three caveats — all line-for-line in
  `research/m17-cold-start-ab.md` ✓; `store.py:472-475` is exactly the config-vs-store comparison,
  still at those lines ✓.
- M16 item vs evidence: UTF-16 bisection (checkpoint §3, cap ∈ [9,503, 10,502)) ✓; link coverage
  1.00 (note line 402) ✓; `claude-sonnet-5` in the transcript (line 218) ✓; archive ~871 is the
  hook-placement/controlled-experiment warning as described ✓; open questions 13–15 exist ✓;
  `reviews/m16-dogfood-checkpoint-review.md` exists ✓.

### Findings

1. **[BLOCKER] `FINDINGS.md` holds both states of the M17 defect: fixed and measured at 216–243,
   live and awaiting a milestone at 415–460 — unmarked, in the always-loaded file.** The M17 item
   says the fix landed 2026-08-25 with 5/5 clean pushes under load. Then: item 6's tail (415–417)
   still says the question is *open* — "What this does leave open … a cold start-if-absent loses
   the race on a loaded machine … a user message that races it silently loses push" — when M17's
   A/B answered it; the paragraph at 419–437 presents the production loss in the present tense
   ("it is one push per idle gap, every day", "what makes the fix cheap to argue"); and the
   paragraph at 439–460 says "The obvious fix was built, measured, and does not work — reverted"
   and ends "Two paths, neither taken here … belong in a milestone with a brief, not in a
   session's tail" — the milestone happened, as a third path, option (d). The M17 item even names
   the contradiction without resolving it: "Correction to the entry this replaces, which said
   deferral 'does not work'" — but the entry it claims to replace still stands below, no marker on
   it. A fresh session reading bottom-up, or landing on 419–460 by search, believes a daily
   production defect is live and a fix milestone is still owed. The file's own house pattern is
   the fix (cf. "Original text, superseded 2026-08-16 by M15" in §Harness). Concrete edits:
   (a) append to item 6's tail: "— closed by M17, which moved the encoder load to the other side
   of the bind; the shipped hook delivered 5/5 under load (`research/m17-cold-start-ab.md`). The
   warm-helper observation stands."; (b) prepend to 419: "**Superseded 2026-08-25 by M17 (the
   item above): the loss described below is fixed and measured. Kept as the production diagnosis
   that motivated it.**"; (c) prepend to 439: "**Superseded 2026-08-25 by M17, which took a third
   path — option (d), the wrapper answering identity from expectation with the measured check in
   the loader thread. Neither path below was taken, as predicted. Kept for the measurements.**";
   (d) the M17 item's "Priority item 6 below carries the numbers" should then say where the
   numbers actually sit — item 6 carries the 1184–1235 ms bind, but the 1059 ms load breakdown is
   in the superseded diagnosis paragraph at ~430, which is not item 6: "priority item 6 and the
   superseded diagnosis paragraphs after it carry the numbers."

2. **[BLOCKER] The resume block still runs M16's opening play, for a milestone that landed a
   month ago — and the play is the one M16's own record says the operator corrected as wrong.**
   `FINDINGS.md` 74–76: "the memory tools and the push hook are **not live in this session**, and
   M16's first act is to change that:" followed by the install-into-this-repo command — while
   line 60 says "Every milestone **M0–M17 is built and reviewed**" and the M16 item (288–290)
   records that installing into this repo was "what this session first proposed and the operator
   corrected"; M16 ran on a throwaway at `~/zk-dogfood` precisely to avoid it. And line 110:
   "**M16's measurement half is done** and it is in review — see item 0 below" — false twice
   (M16 landed, APPROVED after five rounds, per line 61) and dangling once (item 0 is now M18;
   three items carry that number). A fresh session obeying 74–76 installs hooks and `.mcp.json`
   into this repository believing it is the sanctioned next step, or concludes M16 is unfinished
   and reopens it — the M15-rebuilt-twice scenario this file's own §Harness paragraph exists to
   prevent. Concrete edits: (a) 74–76 → "the memory tools and the push hook are **not live in
   this session**. M16 chose a throwaway over installing here (see its item below); installing
   into this repo remains available, and unexercised, as:"; (b) delete line 110's sentence
   outright — line 61 already states the landed fact, and nothing else in that paragraph refers
   to M16.

3. **[IMPROVEMENT] Both finished-milestone items still speak in the present and future tense
   about states that ended.** Three cheap edits, worth making even if finding 4's pass follows:
   (a) M16 item opening (266) carries no completion state at all — a reader learns only that one
   *half* is "DONE" at 273 and must find the landed fact in the phase header. Open with it:
   "**M16 — the dogfooding checkpoint under Claude Code. Landed 2026-08-16, APPROVED after five
   rounds (`reviews/m16-dogfood-checkpoint-review.md`), the last milestone of the port.**";
   (b) 267: "It **gates items 1 and 2**" → "It **gated items 1 and 2**; item 2 closed with it,
   item 1 remains open."; (c) M17 item 220: "`./check.sh` exits 0 (1738 passed" → "exited 0 at
   landing (1738 passed" — the suite now holds 1774 tests per the round-22 state note, so the
   present tense is already false.

4. **[IMPROVEMENT] The structural question: move M17 and M16 to the archive as their own pass,
   after M18 commits — not in this milestone — and move the cold-start diagnosis paragraphs with
   M17 when it goes.** The brief asks whether three landed-milestone items sitting under "What to
   do next, in priority order", all numbered `0.`, should be fixed now. Recommendation: not now.
   The move is a multi-passage reconciliation with its own end-to-end reads — exactly the work
   this review's last six rounds prove cannot ride along inside another milestone's convergence —
   and with findings 1–3 landed, nothing left in the two items is *wrong*, only misfiled. The
   pass has a concrete inventory, recorded here so it is not re-derived: the M17 item's "Priority
   item 6 below carries the numbers" (breaks southbound on archive); the superseded diagnosis
   paragraphs at 415–460, which should travel *with* the M17 item as one unit so the
   cross-reference stays internal; the M16 item's "open questions 13–15 below" and "items 1
   and 2" (both break); resume-block line 110 (deleted by finding 2); and the redundant stratum
   at 106–110, which line 60's "M0–M17" sentence already subsumes. One warning for the pass: the
   archive move is the same append-then-reconcile operation that produced every instance in the
   methodological paragraph — the moved text will need its tenses turned and its "below"s
   repointed, and the check is the same end-to-end read.

5. **[NITPICK] Line 276 is unwrapped — the append fingerprint, inside a passage the brief named.**
   `FINDINGS.md` 276 runs ~150 characters ("…came from there.** Every done-when clause is met and
   five findings arrived"). The researcher's own round-22 note identifies non-wrapping as the
   fingerprint of an unreconciled append; this one sits mid-item where the DONE paragraph was
   spliced in. Rewrap the paragraph programmatically, as was done for the M18 item.

6. **[NITPICK] "The mutations verified — A, B, and C —" still asserts the count the numeral's
   removal meant to stop asserting.** `FINDINGS.md` 223–224: the definite construction reads the
   three-element list as exhaustive, so if the original "Four" was right, the sentence is wrong
   the same way, just less checkably — and the review file names further mutations (the
   reverted-trap, the synchronous `failure()`, drop-`release()`) without settling which were the
   landing set. "The mutations verified **included** an eager artifact read in `assemble`,
   deleting the width check, and gutting the self-stop teardown; the exercise found one of the
   *new tests* vacuous…" is true at any count. Optional.

VERDICT: NEEDS_CHANGES

## Round 23 — 2026-09-14

Per the brief: the six round-22 findings verified in place; then the two questions the brief asks —
do the new supersession markers create an inconsistency anywhere they are read *from*, and does the
resume block read coherently with M18 as the only open milestone. Read for that: `FINDINGS.md` end
to end (all 921 lines), `design/build-plan.md` §M17 (764–1121) and the head of §M18, and a
corpus-wide grep for the defect's live phrasings (`loses push`, `idle gap`, `cold start`,
`HEALTH_POLL_DEADLINE`), which is what turned up `design/architecture.md:644-650` for adjudication.

**Summary judgment.** All six findings landed, one with a deviation that is a correction of my own
text: round 22's marker (b) said "the item above", which resolves to item 6, not the M17 item — the
researcher's "the M17 priority item above" is right and mine was wrong. The resume block now reads
coherently end to end: one open milestone, no instruction to run a landed one, no dangling "item 0".
The hunt the brief asked for found one surviving instance of the class — a present-tense factual
claim about pre-M17 code behaviour, with quotable numbers, sitting *before* the closure sentence
inside item 6 — plus three cross-references missing from the archive-pass inventory, two of them
external to the file. Everything else the markers are read from checks clean.

**The verification record — all six landed.**
- Finding 1(a): item 6's tail (427–429) closes with "**Closed by M17** … 5/5 clean pushes …
  The warm-helper observation stands." ✓ (but see finding 4 below on that last sentence — my
  wording, now ambiguous in its new home).
- Finding 1(b): marker at 431–432, house form, "the M17 priority item above" — the deviation is
  correct; the paragraph immediately above the marker is item 6, so my "the item above" would have
  pointed the reader at the wrong antecedent ✓.
- Finding 1(c): marker at 454–456, third-path/option (d), "Kept for the measurements" ✓.
- Finding 1(d): 255–256 "Priority item 6 below and the superseded diagnosis paragraphs after it
  carry the numbers" ✓ — and the pointer now resolves truthfully: the 1059 ms breakdown is at 446,
  under the marker.
- Finding 2(a): 74–77 "M16 chose a throwaway over installing here (see its item below); installing
  into this repo remains available, and unexercised, as:" ✓. 2(b): the line-110 sentence is deleted;
  107–111 now ends at the M14 citation and hands off cleanly to the commit-subject paragraph ✓.
- Finding 3: M16 item opens with landed/APPROVED/five rounds and the review path (273–274) ✓;
  "gated items 1 and 2; item 2 closed with it, item 1 remains open" (275–276) ✓ — and item 2 is
  indeed the struck-through done one, item 1 the live consolidation item; "exited 0 at landing
  (1738 passed" (226–227) ✓. The self-caught fourth instance: 252–254 "*lost* … took … was" ✓.
- Finding 4: the italic note at 165–169 records the misfiling, the travel-together constraint, and
  points at round 22 finding 4 ✓ (see finding 2 below — the inventory it points at is now short).
- Finding 5: the ~150-character line is gone; no line in any passage this round touched exceeds
  100 ✓ (one new ragged *short* line — finding 3 below).
- Finding 6: "The mutations verified **included** …" (229–231) ✓.

**Checked and clean — recorded so the archive pass does not re-derive it.**
- `design/build-plan.md` §M17 does *not* present the loss as live: the brief states its problem in
  the present tense by the file's own convention (§M18 does the same for its defect), and the
  section carries **DONE 2026-08-25** at line 1088 with the reproduced-and-removed numbers.
- `design/architecture.md` §"The model loads behind the socket" (642–685) is problem→design
  framing: 644–650 state the pre-fix behaviour as "The measured problem" and the very next
  paragraph states the shipped mechanism that removes it. No edit needed.
- `design/harness.md:167` "loses push entirely, silently" is the nesting-misdetection case, a
  different and still-live limitation — correctly untouched.
- `FINDINGS-archive.md` carries only review-history references to M17 (≈1748–1774), no live
  presentation of the defect.
- The resume block (57–111): phase header, M0–M17 sentence, install-remains-available framing,
  hermetic-gate paragraph and the M13/M14 stratum are mutually consistent; the only residue is the
  redundancy already inventoried for the archive pass.

### Findings

1. **[IMPROVEMENT] One instance of the hunted class survives: `FINDINGS.md` 415–418 states pre-M17
   code behaviour in the present tense, with the quotable number attached, ahead of the closure
   sentence.** "whether it holds depends on the machine: a real service takes **1184-1235 ms merely
   to bind its socket**, because `main.py` assembles the store and loads the encoder first,
   deliberately, so it never advertises a store it could not open." Post-M17 every clause of that
   is false of the shipped code — the bind is 242–395 ms and the encoder load is behind it — and
   this is the always-loaded file's most greppable cold-start figure: a session searching "bind"
   lands here and quotes 1184-1235 ms as current, exactly the confidently-stale-claim failure the
   §Harness paragraph documents. The closure sentence ten lines later corrects the *outcome* and
   the load ordering, but not this sentence's tense. Concrete edit, four verbs and one clause:
   "whether it held depended on the machine: a real service then took **1184-1235 ms merely to
   bind its socket**, because `main.py` assembled the store and loaded the encoder first,
   deliberately, so it never advertised a store it could not open — the store half of that
   ordering survives M17; the encoder half is what it moved." Keep "1184-1235 ms" verbatim:
   `design/build-plan.md:839-840` cites item 6 as recording exactly that figure, and the citation
   must go on resolving.

2. **[IMPROVEMENT] The archive-pass inventory the italic note points at is missing three
   cross-references, two of them external to `FINDINGS.md` — and one was created by round 22's own
   fix.** (a) `design/build-plan.md:766-768` — "Evidence: `FINDINGS.md` priority item 6, which
   carries the negative result and most of the numbers below" — the negative result actually lives
   in the superseded diagnosis paragraphs (458–479), which are slated to travel to the archive
   with the M17 item, so this pointer half-breaks on the move and is already imprecise today.
   (b) `design/build-plan.md:839-840` — pins item 6's "1184-1235 ms"; survives the move only if
   item 6 stays, which the plan says it does — record it so the mover checks. (c) `FINDINGS.md:76`
   — "(see its item below)", introduced by round 22 finding 2's edit, breaks when the M16 item
   moves. Concrete edit to the italic note, which also removes an asserted count of exactly the
   kind finding 6 just retired: "…and four \"below\"s break on the move" → "…and its
   cross-references break on the move — including two from `design/build-plan.md` §M17 into item 6
   and the diagnosis paragraphs, and the resume block's own \"see its item below\". Inventory and
   warning: `reviews/m18-payload-spill-review.md` round 22 finding 4 and round 23 finding 2."

3. **[NITPICK] `FINDINGS.md` 255 is a thirteen-character line — "that. Priority" — mid-paragraph:
   the splice fingerprint in the other direction.** The rewrapper's check catches only lines over
   100; an under-filled line mid-paragraph is the same evidence of an unreconciled edit that
   round 22 finding 5 named. Refill the paragraph (252–256), and consider teaching the rewrapper a
   floor as well as a ceiling for mid-paragraph lines.

4. **[NITPICK] "The warm-helper observation stands" (428–429) now has the wrong nearest
   antecedent — my round-22 wording, flagged against myself.** In its new position the phrase
   binds to "the warm helper is load-bearing rather than an optimisation" (425–426), which is
   precisely the claim M17's 5/5-under-load weakens: the cold path now wins the race without the
   helper under every tested load. The observation that genuinely stands unchanged is the
   structural one — `SessionStart`-only, never covered mid-session idle-out. Concrete edit:
   "The warm helper's structural limit — it fires on `SessionStart` only, so it never covered a
   mid-session idle-out — stands; whether the helper is still load-bearing after M17's margin is
   unmeasured." Optional, since the superseded paragraph below states the structural version in
   full.

VERDICT: NEEDS_CHANGES

## Round 24 — 2026-09-14

Per the brief: the four round-23 findings verified in place in `FINDINGS.md` (415–432, 165–171,
252–257, 430–432); the changed passages read end to end with their surroundings; both
`design/build-plan.md` citations the italic note now names re-resolved against the file
(766–768, 839–844); and a corpus grep for the retired phrasings ("M16's first act",
"measurement half is done", "takes ~1.2 s", "whether it holds depends") plus an over-100-character
scan of `FINDINGS.md`.

**Summary judgment.** All four landed. The retired phrasings survive only inside review files —
the audit trail, where they belong — and under `FINDINGS.md`'s own supersession markers, which is
the house pattern; the over-100 lines are all pre-existing and outside the passages rounds 21–24
touched. The load-bearing verbatim-keep worked: `design/build-plan.md:839-840` still resolves —
item 6 records "1184-1235 ms", now in past tense, and the citation's "one range differs" note
still describes exactly what it describes. The hunt for the both-states class in the changed
passages found nothing new; the one residue is a one-word overstatement in the italic note that my
own round-23 suggested wording introduced, and its correction is already on file one hop away.

**The verification record — all four landed.**
- Finding 1: `FINDINGS.md` 415–420 now "whether it held depended on the machine: a real service
  then took **1184-1235 ms merely to bind its socket**, because `main.py` assembled the store and
  loaded the encoder first, deliberately, so it never advertised a store it could not open — the
  store half of that ordering survives M17; the encoder half is what it moved." ✓ — figure
  verbatim, `build-plan.md:839-840` goes on resolving ✓, and the store-half clause is true of the
  shipped code (open still precedes the bind; only the encoder moved, per the M17 item's own
  wrapper description) ✓.
- Finding 2: the italic note (165–171) carries the travel-together constraint, the two build-plan
  pointers, the resume block's "see its item below", and the inventory citation to rounds 22/23;
  the echo is gone and no asserted total remains beyond the checkable "two from build-plan" ✓
  (one residue — finding 1 below). The researcher's read-back catch was right: my suggested text's
  "its cross-reference stays internal, and its cross-references break" was self-contradictory as
  written.
- Finding 3: the thirteen-character line is gone; 252–257 wraps cleanly with no line over 100 and
  no short mid-paragraph line, and the pointer sentence resolves truthfully (item 6 carries the
  bind range; the superseded diagnosis paragraphs carry the 1059 ms breakdown at 449 and the
  reverted-fix numbers at 461–482) ✓. The rewrapper gaining a floor and block-derived indent
  closes the tooling half.
- Finding 4: 430–432 is the suggested sentence exactly — structural limit stands, load-bearing
  status unmeasured ✓, and it now binds to the right antecedent.
- Hunt results, clean: "does not work — reverted" survives only at 461 under the 457–459 marker
  (withdraw-in-place, correct); all other retired phrasings live only in `reviews/` files; the
  supersession markers at 434–435 and 457–459 are bold-balanced across their line breaks; item 6
  read end to end is coherent — past-tense diagnosis, calibration history, fixture fix, "shipped
  constant unchanged" (still true post-M17, which moved the load rather than the deadline), then
  the round-22 closure sentence and the corrected warm-helper sentence.

**The closure question, answered plainly.** The milestone's artifacts — code, tests, both research
notes, `design/build-plan.md` §M18, the installer note — have been stable since round 21, and the
done-when was verified clause by clause in round 21 against build-plan 1404–1424. Rounds 21–24
were `FINDINGS.md` consistency, and the file now holds one state per fact everywhere these rounds
probed. **Nothing remaining blocks the commit.** What remains is archive-pass work by round 22
finding 4's own recommendation — post-commit, its inventory recorded in the italic note and in
rounds 22–23 — plus the single optional nitpick below, which can ride that pass.

**On the method note.** The `expected 1, got 0` abort is the right trade and worth keeping: an
edit that cannot silently half-land is the mechanical fix for the replace-once cause the
methodological paragraph names, and "assertion fails → re-read → retry" is the loop that paragraph
says prose edits need. Recorded here so the practice survives the milestone.

### Findings

1. **[NITPICK] The italic note says both build-plan pointers "break on the move"; round 23
   finding 2 — which the note cites as its inventory — established that one of them survives.**
   `FINDINGS.md` 168–170: "The rest break on the move — including two from `design/build-plan.md`
   §M17 into item 6 and the diagnosis paragraphs". `build-plan.md:839-840` pins item 6's
   "1184-1235 ms", and item 6 stays in `FINDINGS.md` under the recorded plan, so that pointer
   needs re-checking on the move rather than repair; only 766–768 (whose "negative result"
   travels with the diagnosis paragraphs) actually breaks. The wording is my own round-23
   suggested text, flagged against myself; the note's citation to round 23 finding 2 already
   carries the precise version, so a mover gets the truth one hop away. One-clause fix if
   touched at all: "— including two from `design/build-plan.md` §M17 into item 6 and the
   diagnosis paragraphs, one of which merely needs re-checking rather than repair, and the resume
   block's own \"see its item below\"." Archive-pass work; does not block the commit.

VERDICT: APPROVED
