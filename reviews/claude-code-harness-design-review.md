# Review — M13 design delta: `design/harness.md` and the D34 amendments

Artifacts: `design/harness.md` (new, normative); `design/overview.md` D34 row + D32 amendment;
`design/architecture.md` five "Harness delta (D34)" blockquotes; `design/schema.md` §"Linked sessions"
blockquote. Ground truth: `research/claude-code-harness-probe.md` §§1–8. Spec: `design/build-plan.md` §M13.

## Round 1 — 2026-08-16

**Summary judgment.** This is a strong artifact: nearly every Claude-Code claim traces cleanly to a numbered
probe section, the D32/D34 rows state the weakened guarantees honestly and at their measured size, the five
architecture blockquotes are accurate about what their sections describe, and the alias-versus-pin argument is
the right kind of deletion. It is not shippable yet for three reasons: the nesting tripwire is specified with
the same predicate as kiro's subagent-suppression rule and the document does not say how the two compose (as
written it logs a false positive on every kiro subagent turn, and the suppression rule silently eats the push
in the very nested case the tripwire exists to catch); the nesting section itself violates the document's own
evidence rule (a symmetric direction claim §1 partly contradicts, and a "hit accidentally" sentence the probe
does not support); and three table rows carry uncited, unmarked claims in a document whose core promise is
that every claim is traceable or marked.

### Findings

1. **[BLOCKER] The tripwire and the kiro subagent-suppression rule share one predicate, and the document
   never says how they compose — as specified, the tripwire is mostly false positives and the suppression
   rule defeats it in the target case.** `design/harness.md` lines 93–96 specify: "when the payload's
   `session_id` differs from the resolved environment value, write one `hook.log` line." That is *exactly*
   the comparison `zikaron/hook/envelope.py::is_subagent_session` already makes, and under kiro that
   divergence is the **routine, expected** subagent case (measured 2/2 in the kiro hook probe;
   `architecture.md` lines 777–784) — so an implementer following this text logs a tripwire line on every
   `py-runner` turn, drowning the nesting signal in noise and polluting `hook.log`, which `push.py`
   deliberately keeps to a closed vocabulary. Worse, in the actual nested case (kiro running under an
   inherited `CLAUDECODE` — see finding 2), the shared suppression code compares the kiro payload's id to the
   stale `CLAUDE_CODE_SESSION_ID`, finds them different, and **prints nothing** — the nested session silently
   loses all pushes, and depending on ordering the tripwire may never be reached. This directly contradicts
   lines 107–109 ("the kiro suppression rule stays in the code and is inert here"): in the nesting scenario
   this same document describes, the comparison *is* reached, on a top-level user message, and misfires.
   M14's done-when repeats the tripwire unscoped, so this will be built as written. **Concrete fix, three
   sentences in §"The nesting limit":** (a) the tripwire fires **only when the detected harness is Claude
   Code**, where payload-equals-environment is measured invariant (§1) and any divergence is an anomaly;
   under kiro the same divergence is the subagent case and stays unlogged. (b) State explicitly what the hook
   *prints* on a detected-Claude-Code divergence — the suppression comparison must not run there (recommend:
   log the tripwire, print nothing, and say why: a push resolved under the stale label would be injected into
   the wrong session's instrument stream; either decision is defensible, but it must be a decision, not an
   implementation accident). (c) Name the log-line kind (e.g. `session_env_mismatch`) so `hook.log` keeps its
   closed vocabulary.

2. **[BLOCKER] The nesting section states an unmeasured mechanism as symmetric fact and cites an accident
   the probe does not record — against the document's own evidence rule.** `design/harness.md` lines 85–99.
   Three defects: (a) "A session of one harness launched from a shell inside the other inherits a stale
   session variable" is stated symmetrically, but §1 measured the Claude-Code-inner direction **safe**: "the
   value is overridden, not inherited: a nested `claude -p` … got its own new session id, correctly." The
   vulnerable direction is only kiro (or any process) running under an **inherited `CLAUDECODE` marker** —
   and the root failure there is *misdetection of the harness*, of which the stale session variable is one
   consequence (the misdetected hook also applies the 10,000-character budget and Claude Code's channel
   table; harmless today, but the mechanism should be named). (b) "It was hit accidentally during the probe
   itself, which is how it was found at all" traces to nothing: what §1's nested run actually caught was a
   stale **`CLAUDE_PID`** while the session variable was correctly fresh. As written the sentence implies the
   stale-session-variable scenario was observed; it was not. (c) The whole stale-inheritance mechanism is
   by-construction reasoning, which is fine — but the document's preamble promises every claim is probe-
   traceable **or explicitly marked unmeasured**, and this section carries no marker. **Concrete fix:**
   restate the limit as directional ("the exposed case is a kiro session — or any non-Claude process tree —
   inheriting `CLAUDECODE` and `CLAUDE_CODE_SESSION_ID` from an enclosing Claude Code session; the reverse
   direction is measured safe, §1: Claude Code overrides its own variables at spawn"), mark the mechanism
   **unmeasured, by construction from environment inheritance**, and replace the "hit accidentally" sentence
   with what §1 actually shows (the nested run surfaced stale `CLAUDE_PID`, which is the measured evidence
   that outer-session values do leak into nested process trees).

3. **[BLOCKER] Three Claude-Code table rows are neither probe-traceable nor marked, and the preamble's
   "every claim below" is false of the whole kiro column.** `design/harness.md` lines 7–12 (the rule) versus
   lines 55, 57, 58: "Hook config lives in `.claude/settings.local.json`" cites nothing and is marked
   nothing — the probe note never mentions settings files, and this is in fact a *decision* whose rationale
   lives only in M15's brief (machine-local venv paths must not enter the checked-in `settings.json` layer);
   a document claiming to be "the single normative source for every harness-coupled fact" must carry both the
   fact and its provenance. Same for the consolidator-agent row (`.claude/agents/…md`, YAML frontmatter —
   partially evidenced by §6/§7c's use of frontmatter, but uncited) and the skill row (documentation-only;
   the probe never exercised a skill). The `.mcp.json` row shows the document knows how to mark these
   ("*documented, unmeasured*") — the unmarked rows stand out against it. And the kiro column (array-format
   `SessionStart` alias, 65536, silent model fallback, one-process-per-agent-instance) traces to kiro
   sources, not the probe, so the preamble's "every claim below" overclaims. **Concrete fix:** scope the
   evidence rule ("every **Claude Code** claim below is traceable to the probe or marked; kiro claims trace
   to `research/kiro-mcp-lifecycle-probe.md`, `architecture.md` §'Two hook formats' and
   §'The consolidator's model…'"); annotate the hook-config row "(decision, M15: absolute venv paths are
   machine-local, so the uncommitted layer — `settings.json` would break every other clone)"; mark the
   consolidator-agent and skill rows *documented/decided, unmeasured* as appropriate.

4. **[IMPROVEMENT] The table's MCP-scope row re-flattens "two observed, one serves" into "one per
   session" — the exact flattening the port-plan review's round 1 flagged as a BLOCKER and M13's brief warns
   against.** `design/harness.md` line 53 says "one per **session**, shared by subagents (§4, §7g)" while the
   document's own §"Consolidation ownership" correctly says "one or more … two observed starting, of which
   only the second ever served." The table is the quick-reference future sessions will read, and the
   difference is load-bearing: the spurious-takeover residual exists *because* the count is not one.
   **Concrete fix:** row text "one or more per session (two observed; only one ever served), shared by
   subagents (§4, §7g)".

5. **[IMPROVEMENT] The document never states how kiro's two `--mode` registrations map onto Claude Code,
   though its tool-gating and ownership sections silently presuppose the answer.**
   `zikaron/install/entries.py` ships `zikaron-mcp --mode primary` in the user's agent config and
   `--mode consolidator` inside the consolidator's config; under Claude Code, M15's brief says "two servers
   in `.mcp.json`" — but that fact appears nowhere in `design/harness.md`, whose table row (line 56) answers
   only *where* the config lives. An implementer reading the normative document alone must guess between one
   combined-mode server and two mode-split registrations, and the guess changes which server process owns the
   consolidation lease and which tools the primary agent sees. **Concrete fix:** one sentence in §"Tool
   gating" (or a table cell): "Both modes register session-wide in `.mcp.json` — two entries, `--mode
   primary` and `--mode consolidator` — so the consolidator subagent's frontmatter `tools:` selects among
   session-visible tools rather than getting its own registration; the exposure below follows directly."

6. **[IMPROVEMENT] "The shipped default is the `sonnet` alias" is unscoped, and it quietly makes the model
   field harness-varying — which §7d concluded it was not.** `design/harness.md` lines 193–199. Kiro cannot
   ship `sonnet`: its `--list-models` check would refuse it, and `architecture.md`'s table (line 1771)
   still — correctly — says kiro's v0 default is the pinned `claude-sonnet-5`. So the shipped default is
   per-harness: pinned-and-validated under kiro, alias under Claude Code. The section reads as a global rule,
   and probe §7d's own closing inference ("the field is not harness-varying data") is now superseded by this
   decision without either document saying so. **Concrete fix:** scope the sentence ("Under Claude Code the
   shipped default is the `sonnet` alias; kiro keeps the pinned `claude-sonnet-5` and its install-time
   check") and add one clause noting §7d's pin-everywhere inference was a probe-note conclusion the design
   deliberately did not adopt for Claude Code, and why (rot-at-spawn breaks the product).

7. **[IMPROVEMENT] Two harness-coupled facts the codebase consumes are absent from the table: the hook
   timeout, and push-block placement/framing.** (a) `zikaron/hook/limits.py` states `timeout_ms: 10000` and
   `zikaron/hook/push.py` sizes its 2 s internal deadline against it ("our failure path always fires before
   the harness's kill"). Claude Code's hook timeout — its default, its unit, and whether the installer can or
   should state it in `settings.local.json` — appears nowhere, so M15 cannot know whether the ~2 s deadline's
   fires-before-the-kill property survives the port. Add a row, marked *documented, unmeasured* if that is
   its standing. (b) Probe §5 measured placement and framing (kiro: before the user message, inside a
   follow-any-requests wrapper; Claude Code: after it, no framing) — a fact with a named consumer
   (`retrieval.md`'s untrusted-reference-data preamble was argued against kiro's wrapper) that resolves open
   question 4's stated tension. It belongs in the table with its §5 citation rather than only in the probe
   note.

8. **[IMPROVEMENT] `architecture.md`'s consolidation-ownership prose still teaches `(session_id, pid)` and
   the per-client-process plan-bridge bound with no delta note in sight.** §"What the shared label affects"
   (lines 809–819: "this is now mechanized on `pid`… Ownership is therefore `(session_id, pid)`") and
   §"Consolidation lifecycle" / the `plan_groups` description (lines 1264, 1283, 1300, 1314–1320, 1704–1713:
   "at most once successfully per client process", "a per-process guard is a per-invocation guard") are the
   sections harness.md §"Consolidation ownership under a shared MCP process" most directly weakens, and
   neither carries a blockquote — the nearest one (line 760) covers push suppression, two subsections and
   a thousand lines away respectively. The brief's five insertion points missed the sixth that matters most.
   **Concrete fix:** one more blockquote at the head of the `plan_groups` bullet or §"Consolidation
   lifecycle": "Harness delta (D34). `pid` discriminates consolidators only under kiro's
   process-per-agent-instance model. Under Claude Code one shared server process serves the session, so the
   per-process bound is per-session and a restarted serving process is a spurious self-takeover — accepted,
   `design/harness.md` §'Consolidation ownership under a shared MCP process'."

9. **[NITPICK] "Four artefacts in three formats" counts loosely.** `design/harness.md` line 21 /
   `architecture.md` line 1807: the two JSON files share a serialization and the two Markdown files share
   one; "three formats" is defensible only by counting schemas. Say "four artefacts — two JSON, two
   YAML-frontmatter Markdown" and drop the arithmetic.

10. **[NITPICK] The supremacy rule names only `architecture.md`.** `design/harness.md` lines 3–5: deltas
    were also placed in `schema.md`, and future drift is as likely there or in `retrieval.md` (whose push
    section still describes kiro trigger names and placement). Widen to "an older section of another design
    document".

11. **[NITPICK] Kiro's array format also accepts PascalCase trigger names generally, not only the
    `SessionStart` alias.** `architecture.md` line 1739 versus the table's spawn row (line 44). Harmless
    under many-to-two normalization, but this table is that normalization's declared source of truth, so
    carry the full alias set.

### What was checked and is clean

Traceability of the session-identity, subagent, tool-gating, ownership, model and budget sections to probe
§§1–7 is exact, including the character-versus-byte pinning and the honest ≥12,000 marker; the D34 row states
measured versus decided correctly and names both accepted limits; the D32 amendment claims only the surviving
half and cites §6; the five architecture blockquotes and the schema blockquote are accurate about their
sections being kiro-specific; link-coverage-cannot-detect-nesting is correct as argued (agreement by
construction attributes the nested session's events to the outer id, so no unlinked session ever appears);
the ×4 UTF-8 derivation is sound and correctly distinguished from the withdrawn tokens×4 guess; FINDINGS'
refuted migration claims are withdrawn in place per the done-when.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-16

**Summary judgment.** All eleven round-1 findings are genuinely fixed, not merely gestured at: the tripwire
is now scoped, named, and composes cleanly with the kiro suppression rule (one predicate, print-nothing on
divergence under both harnesses, log only under Claude Code — implementable from `harness.md` plus M14's
done-when without guessing); the nesting section is directional, marked, and withdraws the false "hit
accidentally" sentence in place; the evidence rule is scoped and the table rows carry provenance; the sixth
blockquote sits at `architecture.md` §"Consolidation lifecycle" and says the right thing. What remains is
residue in two sibling artifacts that still carry the *pre-fix* versions of two corrected claims — the
overview D34 row's unscoped model-alias sentence (the exact spot the researcher's brief asked to be checked,
and it does still imply the wrong thing) and the schema blockquote's symmetric nesting sentence, which
`harness.md` now explicitly calls wrong. Both fixes are one or two sentences; nothing else blocks.

### Fix verification, item by item

1. **Fixed and correct.** `design/harness.md` lines 113–134: tripwire scoped to detected-Claude-Code, where
   payload-equals-environment is measured invariant (§1, and §7h for resume); kind `session_env_mismatch`
   named; print-nothing stated as a decision with the instrument-corruption-vs-recoverable-pull asymmetry as
   its rationale, correctly the same asymmetry §"Subagent sessions" uses; consequence ("loses push entirely")
   stated; detect-by-agreement recorded without adoption. The composition is now well-defined: divergence
   prints nothing under both harnesses, and only the Claude-Code case logs. I walked the misdetected
   nested-kiro case through it (top-level kiro payload id ≠ stale `CLAUDE_CODE_SESSION_ID` → log + silence;
   kiro subagent turns inside that session take the same path) and it behaves as the text says. M14's
   done-when (`build-plan.md` lines 548–552) matches exactly, including the kiro-subagent-writes-nothing
   assertion and the drowning rationale. Implementable without further guessing.
2. **Fixed and correct.** Lines 94–106: directional, with §1's override finding quoted accurately; root
   failure named as harness misdetection with the budget/channel-table consequences; mechanism marked
   *unmeasured, by construction*; the "hit accidentally" sentence withdrawn in place and replaced with the
   stale-`CLAUDE_PID` observation, which is what §1 actually records. Faithful to the probe.
3. **Fixed.** Preamble lines 9–16 scope the rule to Claude Code claims and name kiro's sources; the
   hook-config row carries the M15 decision and its rationale, the consolidator-agent row separates what
   §6/§7c/§7d exercised from the *documented* file layout, the skill row is marked. One small gap in the
   kiro source list — finding 4 below.
4. **Fixed.** Row 57 reads "one or more per session — two observed starting, only one ever served".
5. **Fixed.** §"Tool gating" lines 186–191 name both `.mcp.json` entries and their `--mode` flags and derive
   the exposure from session-wide registration. Consistent with M15's brief.
6. **Fixed.** §"The consolidator's model" line 235 scopes the default per-harness, the table gained row 59,
   and §7d's "not harness-varying" inference is explicitly noted as a probe-note conclusion not adopted.
   `architecture.md`'s blockquote (lines 1767–1773) agrees. The residue is in `overview.md` — finding 1.
7. **Fixed.** Timeout row (line 60) marked *documented, unmeasured* with the `push.py` ~2 s deadline named as
   the unverified consumer; placement/framing row (line 61) added with §5.
8. **Fixed.** Sixth blockquote at `architecture.md` line 1204, heading §"Consolidation lifecycle", correctly
   states per-session bound, spurious self-takeover, both accepted limits and the untouched cross-session
   case. `harness.md`'s delta inventory ("architecture.md (six) and schema.md (one)") is accurate.
9/10/11. **Fixed** in `harness.md` (line 26 "two JSON, two YAML-frontmatter Markdown"; preamble supremacy
   rule widened and `retrieval.md` named as un-annotated; row 48 carries "PascalCase trigger names
   generally"). Finding 9's *second* cited location was not fixed — finding 3 below.

Also re-verified: FINDINGS' migration claims are withdrawn in place on disk (struck-through original at line
152, refutation block at 114–122) — the copy loaded into my context at spawn was a stale snapshot, and round
1's clean-list claim holds against the file.

### Findings

1. **[IMPROVEMENT] The overview D34 row still states the model-alias decision unscoped, exactly where the
   brief suspected — a reader of the decision table alone concludes the shipped `model` is an alias on both
   harnesses.** `design/overview.md`, D34 rationale (line 138): "…an unknown model id is **refused at
   spawn** rather than silently substituted, which removes the need for kiro's install-time `--list-models`
   check and lets the shipped `model` stay an alias." Two defects: "removes the need for kiro's … check" is
   readable as *kiro's check is no longer needed* (it is kept — `harness.md` line 235, table row 59), and
   "lets the shipped `model` stay an alias" carries no harness qualifier, while `harness.md` now makes the
   field explicitly harness-varying (kiro pinned + validated, Claude Code alias). CLAUDE.md sends every
   session to this table's rationale before touching a decision, so this is the highest-traffic place for
   the wrong reading to take root, supremacy rule notwithstanding. **Concrete fix, one clause:** "…which
   removes the need for an install-time `--list-models` check *there* and makes the `model` field
   harness-varying: Claude Code ships the `sonnet` alias, kiro keeps its pinned `claude-sonnet-5` and its
   check (`design/harness.md`, table)."
2. **[IMPROVEMENT] The schema blockquote still asserts the symmetric nesting claim that `harness.md` now
   withdraws as wrong.** `design/schema.md` lines 646–649: "a session of one harness launched from a shell
   inside the other inherits a *stale* session variable…" — the exact sentence shape `harness.md` line 94
   corrects ("an earlier draft of this section stated it symmetrically — wrongly"; §1 measured the
   Claude-Code-inner direction safe). The blockquote's instrument-invisibility point survives unchanged in
   the exposed direction, but as written the corpus simultaneously asserts the symmetric claim and calls it
   wrong. **Concrete fix, one clause:** "a non-Claude-Code process tree (a kiro session, for instance)
   launched inside a Claude Code session inherits `CLAUDECODE` and a stale `CLAUDE_CODE_SESSION_ID` — the
   reverse direction is measured safe (probe §1) — both clients read the same stale value, they **agree**…"
3. **[NITPICK] Round-1 finding 9's second location was not fixed.** `architecture.md` line 1817 ("Claude
   Code writes four artefacts in three formats") and, same counting, `build-plan.md` M15 line 565. Apply the
   `harness.md` line 26 phrasing: "four artefacts — two JSON, two YAML-frontmatter Markdown".
4. **[NITPICK] The preamble's kiro source list omits §"Subagent sessions".** `harness.md` line 12 names
   `kiro-mcp-lifecycle-probe.md`, §"Two hook formats" and §"The consolidator's model…", but the subagent-
   triggers kiro cell (row 51, "hooks fire *for* subagent sessions instead") traces to `architecture.md`
   §"Subagent sessions" (the 2026-08-01 measurement), which is in none of the three. Add it. While there:
   row 59's parenthetical "an alias would fail the `--list-models` check" is an inference, not a
   measurement — a "(inferred)" marker would keep the column honest at zero cost.
5. **[NITPICK] M13's completed brief still carries both pre-fix claims** — the symmetric nesting sentence
   and the unscoped tripwire (`build-plan.md` lines 366–375). M14's done-when is the corrected, binding
   text, so no implementer is misled, but a one-line "superseded by `design/harness.md` §'The nesting
   limit'" annotation would keep the record from contradicting the artifact it produced, in the same style
   as `architecture.md`'s existing "Superseded, 2026-08-03" notes. Optional — the brief is historical.

### What was checked and is clean

The tripwire/suppression composition under all four cases (kiro top-level, kiro subagent, Claude Code
top-level and resume, misdetected nested kiro); the minted-rung edge (variable absent ⇒ no comparison to
diverge, consistent with the ladder); table-versus-prose agreement across all 21 rows including budgets,
channels, MCP scope and model; the six architecture blockquotes plus the schema blockquote against their
sections; the D32 row's split text against `harness.md` §"Tool gating" (consistent, including the
served-as-the-owner consequence); M14's and M15's briefs against the table (settings.local.json rationale,
two `.mcp.json` entries, approval-step reporting, the `permissions.deny` scope fence); and the kiro column's
traceability to its named sources (complete except finding 4).

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-16

**Summary judgment.** All five round-2 findings are correctly and completely applied, and none of them
introduced a new error. The overview D34 sentence now reads unambiguously in its full row context — "*there*"
scopes to Claude Code by its subject and the closing kiro clause removes any residual misreading; the schema
blockquote's directional rewrite preserves the instrument-invisibility argument intact (the "both clients
then read the same stale value → agree → coverage ~1.0" chain now binds only to the exposed direction, and
its closing pointer to the tripwire matches `harness.md`'s scoped version, which does fire in that case since
the misdetected harness is Claude Code); the old "three formats" phrasing has zero occurrences left in
`design/`; the preamble's kiro source list carries §"Subagent sessions" and row 61's parenthetical is marked
*inferred*; and M13's superseded note names both corrections and points at §"The nesting limit" as normative,
with M14's done-when as the binding text. I re-checked every delta location against `design/harness.md` —
the six architecture blockquotes, the schema blockquote, D32/D34, and the M13–M16 briefs including M15's
tail and M16 — and found no contradiction with the supremacy document. Only trivial wording residue remains.

### Fix verification

1. **Correct.** `design/overview.md` D34 rationale now reads "…removes the need for an install-time
   `--list-models` check *there* and makes the `model` field **harness-varying**: Claude Code ships the
   `sonnet` alias, while kiro keeps its pinned `claude-sonnet-5` and its check (`design/harness.md`, table)."
   In the full row context the antecedent of "there" is the refused-at-spawn behaviour, which is Claude
   Code's, and the kiro clause states the check is kept — both round-2 defects gone. Consistent with
   `harness.md` table row 61, §"The consolidator's model", and `architecture.md`'s blockquote at 1767–1773.
2. **Correct.** `design/schema.md` lines 646–651: the blockquote is now directional ("a non-Claude-Code
   process tree — a kiro session, for instance — launched inside a Claude Code session inherits `CLAUDECODE`
   and a *stale* `CLAUDE_CODE_SESSION_ID`, while the reverse direction is measured **safe** (probe §1)").
   The invisibility argument that follows survives the rewrite: "Both clients **then** read the same stale
   value" correctly binds to the exposed case only, "that session's events are silently attributed to the
   outer session" remains true under the tripwire's print-nothing decision (the MCP events are attributed;
   suppressed pushes simply never exist), and the closing sentence correctly names the `harness.md` tripwire
   as the only evidence — which is accurate, since in this scenario the detected harness is Claude Code and
   the scoped tripwire fires.
3. **Correct.** Zero occurrences of "three formats" remain anywhere in `design/`; `architecture.md` 1817 and
   `build-plan.md` 569 both carry "four artefacts — two JSON, two YAML-frontmatter Markdown". (One wording
   wart introduced at the architecture location — finding 1 below.)
4. **Correct.** `harness.md` preamble (lines 12–15) names §"Subagent sessions" with the 2026-08-01
   measurement identified; table row 61's parenthetical reads "an alias would fail the `--list-models`
   check — *inferred*, not measured".
5. **Correct.** `build-plan.md` lines 368–371: the italic supersession note names the artifact, the date,
   both corrections (the symmetry, with the Claude-Code-inner direction marked measured safe per probe §1;
   the tripwire's shared-predicate scoping), and points at M14's done-when as the corrected binding text —
   matching the style of `architecture.md`'s existing "Superseded" notes.

### Findings

1. **[NITPICK] The architecture install-contract blockquote repeats its own phrase.** `architecture.md`
   lines 1817–1818: "four artefacts — two JSON, two YAML-frontmatter Markdown (`.claude/settings.local.json`,
   `.mcp.json`, and two YAML-frontmatter Markdown files)" — the fix's phrasing collided with the existing
   parenthetical enumeration, so "two YAML-frontmatter Markdown" appears twice in one sentence. Drop the
   parenthetical's tail: "(… and two YAML-frontmatter Markdown files)" → "(the two JSON being
   `.claude/settings.local.json` and `.mcp.json`)", or delete the parenthetical entirely — `harness.md` and
   M15 both enumerate the files.
2. **[NITPICK] One sentence in `harness.md` §"Link coverage cannot detect it" still enumerates "pushes" as
   attributed, which the tripwire decision three paragraphs later reverses.** Line 112: "the inner session's
   pushes, writes and searches are silently attributed to the outer, live session's instruments" — under the
   round-2 print-nothing decision (line 125) and the stated consequence (line 131, "loses push entirely"),
   pushes are dropped, not attributed; only the MCP-side writes and searches land on the outer label. The
   sentence is describing the un-tripwired baseline the paragraph argues from, so no implementer is misled,
   but one qualifier squares it: "…its writes and searches are silently attributed to the outer session's
   instruments (its pushes are suppressed by the tripwire below)". While in that section, "prints nothing"
   at line 125 could gain three words — "prints nothing and makes no RPC" — since the instrument-corruption
   rationale it states (no `surface_call` may be counted against the outer session's stream) is only
   delivered by not calling the service, and the kiro suppression path it shares a predicate with is
   specified elsewhere as "prints nothing **and calls nothing**". The shared-predicate framing plus the
   rationale make the right implementation the obvious one, which is why this is a nitpick and not more.
3. **[NITPICK] The label-resolution blockquote's residual pointer still uses the compressed symmetric
   phrasing.** `architecture.md` line 161: "a nested session of one harness inside the other inheriting a
   stale id" — as a deferring pointer to `harness.md` this is harmless (it names a case, not a mechanism),
   but the one-word directional form would end the phrasing's last appearance: "a non-Claude-Code session
   nested inside a Claude Code session inheriting a stale id".
4. **[NITPICK] A duplicated clause in M14's brief.** `build-plan.md` lines 512–513: "M13's measurement (the
   harness refuses an unknown id at spawn, so the id can simply be trusted, because the harness refuses an
   unknown one at spawn)" — the justification is stated twice inside one parenthetical; delete the trailing
   "because the harness refuses an unknown one at spawn". Pre-existing editing artifact, not introduced by
   the round-2 fixes.

### What was checked and is clean

The overview D34 row read end to end against `harness.md`'s table and §"The consolidator's model" (the
three-measurements sentence structure survives the insertion; budgets, subagent, and suppression clauses all
still match); the D32 row's split paragraph (unchanged, still consistent); the schema blockquote against both
the directional limit and the scoped tripwire, including the coverage-reads-~1.0 chain; all six architecture
blockquotes against their `harness.md` counterparts (155, 760, 1204, 1735, 1767, 1817 — the model blockquote's
"removes the need … there" matches the overview fix's scoping); the M13 supersession note against §"The
nesting limit" and M14's done-when; M15's tail (settings.local.json rationale, approval-step reporting,
`permissions.deny` scope fence) and M16 (baseline reset, the `~/Memory` fence) against `harness.md`; and the
`design/`-wide absence of the corrected phrasings ("three formats": zero hits; symmetric nesting: only the
compressed pointer in finding 3 and the annotated-as-superseded M13 paragraph remain).

VERDICT: APPROVED
