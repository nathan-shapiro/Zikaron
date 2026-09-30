# M34 prose — the shipped text for both surfaces

Authored by `memory-reviewer` on the operator's instruction (as in M32 and M33). The wording below
is the deliverable; the researcher pastes it, re-renders the golden files, and measures the wire.
Brief: `design/build-plan.md` §"M34 — A headline carries no verdict"; problem statement
`FINDINGS.md` Q22.

## Round 1 — 2026-09-29

### What both surfaces carry, and why it is worded as information rather than pressure

The rule has to pass M33's admission test — prose binds where the agent lacks information, not
where it knows and does not act. The writer already knows *lead with the symptom* and obeys it. What
it does not know is two facts this corpus measured: **the line is usually all a later agent acts
on** (the record is almost never fetched; the gist is the payload), and **a verdict in the line is
repeated as the finding while the record goes unread** (`3e1f6c7a`: the headline's absolute
repeated across turns, the 5.4 KB record opened only when the operator said so). Both texts state
those two facts and the rule that follows from them — keep the symptom, stop before the conclusion,
put the conclusion in `content` — and give one example that shows the cut as a literal `so` clause.
Neither text asks for effort, brevity or care; each says what the headline is for and what a verdict
does to it.

Two boundaries had to be drawn or the rule licenses the wrong deletion: **a condition is not a
verdict** (it stays in the line — the measured `rrf_k` failure is the reason), and **taking the
verdict out of the line softens nothing** (severity is the finding; `content` states the conclusion
at full strength). Both are stated on the consolidator, which rewrites other agents' records; the
first alone on `remember`, where the budget allows one sentence and the writer is not rewriting
anyone's severity.

---

## Surface 1 — the consolidator prompt, `zikaron/install/assets.py` §"## Authoring gists and content"

Full replacement of the section, from its heading to the line before `## Details that will come
up`. Paragraphs marked *unchanged* below are byte-identical to the current source, including their
existing wrapping, so the diff is exactly the three new paragraphs plus one clause removed from the
first.

```
## Authoring gists and content

The **gist** is one line, and its only job is to let a future agent decide whether to read further.
Lead with the observable symptom or situation: "integration tests flake on CI unless PGHOST is set"
beats "notes on test configuration".

**A gist carries no verdict.** Keep the symptom and drop the conclusion drawn from it — the clause
after "so", "therefore" or "which means", or a bare ruling such as "is wrong", "cannot work" or
"must". "The deploy script exits 0 when its health check times out" is a gist; "…, so its exit code
proves nothing" is the record's conclusion, and it goes in the content. A future agent that reads
the verdict in the line repeats it as the finding and leaves the record unread, where the reasons,
limits and exceptions are; a line that names the situation gets the record read when it looks
relevant. The boundary is what was observed against what the writer made of it: the first is the
gist, the second is the verdict.

**Every gist you write passes through this rule, and nothing else applies it.** The agents who wrote
these entries were asked for the same form, and many entries still arrive as verdicts; the gist you
write is the one that lasts. That covers the gist you give a promoted record and the gist you give a
merge target, whose existing gist may itself be a verdict whether or not the entries changed what it
says. It also means a verdict gist is never repeated byte-for-byte to promote an entry in place:
rewrite it, and accept that the entry becomes a new record. That is the intended outcome, not a cost
to avoid.

**Taking the verdict out of the gist softens nothing.** The content states the conclusion in full,
at the strength the entries gave it: "silently corrupts the store" stays "silently corrupts the
store" and does not become "may affect". Severity is the finding, and a record that lost it while
gaining a better gist is worse than the entries it replaced. A condition is not a verdict either:
"unless PGHOST is set" and "until the migration lands" stay in the gist, as the rule below requires.

**Length: aim for one sentence of about 20 to 25 words.** Two bounds apply and the first you cross rejects the write: 64 tokens by default
and a fixed 1,024 characters, which only binds if the gist carries a long
unbroken string. The token bound is the project's to configure and may be lower here; the
rejection names the limit it applied. A write over either is **rejected outright**, so you lose
the call and have to author it again. A gist straining toward the limit is carrying content rather
than a cue.

**If you cannot lead with one observable symptom or situation, the entries are probably not one
finding.** A merged gist that becomes a list — "three findings: this, that, the other" — cannot be
triaged at all: a future agent sees gists only, so a record that just names its own contents is
invisible to the judgment the gist exists for, however good its content is. Prefer two records with
sharp gists over one with a table of contents. Splitting costs one extra record; a table of
contents costs the retrievability of everything under it.

The **content** carries the detail, written as an observation of what was learned here — not as an
instruction. So is the gist: "Deploying without --force left the old worker running" is right;
"always deploy with --force" is not, in either field. Records phrased as orders get obeyed by agents
with far less context than whoever wrote them, and the gist is the half every future agent is shown.

**A condition that limits a claim must survive into the gist you write.** If an entry is only true
during a migration, until a fix lands, or for one version of a dependency, that condition has to
appear in the gist itself — not only in the content you carry over. A future agent almost always
sees the
gist alone, so a qualifier you leave behind turns a temporary finding into a permanent rule nobody
intended. If the condition will not fit, do not fold that entry into a record whose gist cannot
carry it: promote it on its own instead.

**Never record a secret or personal data.** If an entry contains a token, password, key or
credential-bearing connection string, do not carry the value into a long-term record: name what is
needed and how to obtain it instead. If it contains a person's private details, leave them out of
what you write. This store is plaintext on disk, and retiring a record does not erase it.
```

**Exactly what changed.**

1. **First paragraph**: the clause *"rather than the conclusion"* is removed from *"Lead with the
   observable symptom or situation rather than the conclusion:"*. It was the ordering rule the brief
   says is being obeyed, and leaving it there beside a presence rule would let a reader satisfy both
   by putting the symptom first and the verdict second — which is the measured shape. The topic-label
   contrast (*"notes on test configuration"*) is kept here, where there is no budget; it guards a
   different failure (summary-shaped gists) than the new paragraph does.
2. **New paragraph "A gist carries no verdict."** The rule, the shapes a verdict clause takes so the
   consolidator can recognise one in an *existing* gist, one example showing the cut as a literal
   `so` clause, the two measured consequences, and the boundary test — observed versus made-of-it —
   which is what keeps *"integration tests flake on CI unless PGHOST is set"* and *"deploying without
   --force left the old worker running"* on the right side of the rule. The example is generic
   rather than the operator's tick example because the prompt's other examples are generic dev-ops;
   the verdict in it is a pure conclusion, neither an order nor a condition, so it cannot be read as
   restating either neighbouring rule.
3. **New paragraph "Every gist you write passes through this rule…"** The gatekeeper framing, stated
   as fact rather than as a design rationale: nothing else applies the rule, and many entries arrive
   as verdicts (58 of 169 is *many*, not *most*). It names the three places a gist passes through
   the consolidator — promote, merge target (whose own gist may be a pre-rule verdict even when the
   entries add nothing to it), and the byte-for-byte promote-in-place path — and says in words that
   losing in-place promotion is the intended outcome, per the brief.
4. **New paragraph "Taking the verdict out of the gist softens nothing."** The severity boundary with
   the brief's own example pair, tied to the never-lose posture the surrounding prompt already
   holds (*"Preserve the specifics"*: a record that lost severity while gaining a better gist is
   worse than what it replaced). The last sentence draws the condition boundary and points at the
   existing condition paragraph rather than restating it.
5. Everything from **"Length:"** to the end of the section is **unchanged**, byte for byte.

**Pins.** Every phrase `tests/test_install_assets.py` asserts on `CONSOLIDATOR_PROMPT` survives,
flattened: `whether to read further`, `Lead with the observable symptom`, `20 to 25 words`,
`64 tokens`, `less context than`, `--force`, `Never record a secret`, `plaintext on disk`,
`permanent rule`, `until a fix lands`, `probably not one finding`, `table of contents`,
`one observable symptom or situation`, `one at a time`, `not guaranteed to run in the order`,
`four tools and no`. No tool name is added or removed, so `test_every_tool_the_prompt_instructs…`
(set equality against the registered consolidator tools) is unaffected; `zikaron_memory_search` and
`zikaron_memory_fetch` are still absent; `Look things up` is still absent.

**What this changes downstream, for the researcher.** `CONSOLIDATOR_PROMPT` is embedded in two
golden artefacts that must be **re-rendered, not hand-edited**: `.kiro/agents/zikaron-consolidator.json`
(`tests/test_install_assets.py::TestTheTrackedArtefactsInThisRepository`, byte-for-byte) and
`tests/fixtures/kiro_artefacts.json` keys `consolidator_agent_config` and `consolidator_config_bytes`
(`tests/test_install_targets.py::TestKiroArtefactsAreUnchanged`). The fixture's `skill_markdown` key
and the tracked `SKILL.md` are **not** affected: `_SKILL_BODY` is untouched.

---

## Surface 2 — `zikaron_memory_remember`'s description, `zikaron/mcp/primary.py`

Full replacement docstring, in source form (eight-space indent as it sits in the function; the wire
text is the dedented docstring). Longest source line is 99 columns.

```python
        """Record a new memory; it is live at once.

        `gist` is the **headline**: all a later agent sees before deciding whether to read further,
        and usually all it acts on. Lead with the observable symptom and stop before the
        conclusion: "integration tests flake on CI unless PGHOST is set", not "…, so the suite is
        fine". A verdict in the line is repeated as the finding and the record goes unread; put
        the verdict in `content`. A condition is not a verdict: **if a claim expires, the headline
        has to say so** ("until a fix lands"), or the claim is recalled as a permanent rule. About
        20 to 25 words; refused over 64 tokens.

        **Write observations, not orders**: "deploying without --force left the old worker
        running", never "always deploy with --force", which an agent with less context than you
        obeys. **Never record a secret or personal data** — no tokens, passwords, keys,
        credentialed connection strings or `.env` contents; name the credential and where to
        obtain it, never its value. The store is plaintext on disk and retiring does not erase it.

        Cite another memory by its subject ("the record about the deploy rollback"), in a document
        as in `content` — never by headline or uuid. An amend rewrites the headline and the record
        behind the id, and consolidation moves the claim to another row, so an id copied into a
        document keeps resolving long after the finding has left it; a uuid is a handle for this
        session's tool calls only.

        Returns `{uuid, version, near_duplicates: [{uuid, gist, cosine, rank}]}`. `near_duplicates`
        are existing rows worth comparing, not a claim that they are duplicates: read both. For a
        genuine duplicate, `zikaron_memory_amend` the older row with anything this one adds, then
        `zikaron_memory_retire` this one with `superseded_by` set to the older uuid; until then
        both stay live. An own-write receipt lets this session amend or retire the new row without
        fetching it.
        """
```

**My count of the dedented text: 1,894 code points** (budget 1,900; today 1,895). Method: sum of
dedented line lengths plus one per newline, no trailing newline (`cleandoc` strips the closing
line). The same method reproduces today's 1,895 exactly, so it is calibrated, but a hand count with
six characters of margin is not a measurement — **run the command in `design/harness.md` §"Tool
descriptions are capped" before anything else.** If the wire comes out over, the first cut is
*"and the record goes unread"* (26 code points; *"repeated as the finding"* already implies it),
which brings the text to 1,868 with no pin touched. Every character is in the BMP.

**What it carries that it did not.** The two facts and the rule, in the order of consequence
`harness.md` asks for: what the line is (all a later agent sees — *and usually all it acts on*),
the rule with the cut shown on the house example, the consequence of a verdict (repeated as the
finding, record unread), where the verdict goes (`content`), and the boundary that stops the rule
eating the expiry rule (*a condition is not a verdict*), which now leads straight into the expiry
sentence so the two read as one rule with two halves.

**What it displaced, and why each was the weakest text.**

- *"Writes unconditionally; the row is live at once."* → *"it is live at once."* (−29). "Writes
  unconditionally" restated what the write policy already says (*"write without checking first"*)
  and what the `Returns` block already says (*"until then both stay live"*).
- *"not "notes on test configuration""* → *"not "…, so the suite is fine""* (+14 net for the pair
  but the topic-label contrast is gone). The negative example is the only place the rule is shown
  rather than stated, and the verdict contrast is the measured failure; the topic-label contrast
  guards a failure this corpus has not measured on this surface, and the consolidator keeps it.
- *"One sentence of 20 to 25 words; refused over 64 tokens (default) or 1,024 characters."* →
  *"About 20 to 25 words; refused over 64 tokens."* (−42). The brief's candidate, but **compressed
  rather than deleted**: `20 to 25 words` and `64 tokens` are both pinned on this surface by
  `test_it_bounds_a_headline_with_a_number_an_agent_can_act_on`, whose reason — an agent lost a
  call discovering the bound — is a measured cost, and the bound is the number an agent can act on.
  What went is the part that was genuinely weak: `(default)` (the refusal names the limit it
  applied) and `1,024 characters` (unreachable at 25 words unless one word is nine hundred
  characters long).
- *", for one dependency version"* (−28). The pin is `until a fix lands`; the second illustration
  of the same condition is the one thing here that carried no new information. The consolidator
  keeps both.
- *"a condition left in `content` reaches only those who fetch, so the claim is recalled…"* →
  *"or the claim is recalled…"* (−52). The mechanism moved to the top as *"and usually all it acts
  on"*, where it now explains both rules (why the condition must be in the line, why the verdict
  must not) instead of one.
- *"API keys, private keys"* → *"keys"* (−18). `keys` covers both; `.env` contents, the measured
  trap, stays.

**Kept verbatim, as the brief requires**: the citation paragraph (pin `keeps resolving long after
the finding has left it` intact) and the whole `Returns` block.

**Pinned phrases removed: none.** Verified present, flattened, on this surface: `whether to read
further`, `Lead with the observable symptom`, `20 to 25 words`, `64 tokens`, `less context than`,
`--force`, `Never record a secret`, `plaintext on disk`, `permanent rule`, `until a fix lands`,
`keeps resolving long after the finding has left it`. No tool name added, so
`test_no_description_names_a_tool_its_own_server_does_not_have` is unaffected. The word `abstract`
does not appear (that guard reads `search`, not `remember`, but the reason it exists applies here).

---

## Surface 2b — `zikaron_memory_amend`'s description, `zikaron/mcp/primary.py`

Yes, the summary clause needs the matching word: it lists the headline rules an amend inherits, and
a list that names symptom-first and expiry but not the verdict rule reads as the complete set. Amend
is also the surface that was in front of the agent when `3e1f6c7a` was repaired into another
verdict — the repair fixed what the line claimed and left its form — so it earns one sentence of
its own, which is information a repairing agent lacks: correcting a verdict is not the same as
removing it. Only the first paragraph changes; the other two are byte-identical.

```python
        """Fully rewrite an existing record's `gist` and `content`. Both follow the rules in
        `zikaron_memory_remember`: a headline leading with the symptom, stopping before the
        conclusion and carrying its own expiry condition, observations rather than orders, no
        secrets. Use it to correct a record that misled you, once you have established the
        current truth, and to fold a near-duplicate's additions into the older row. If the
        headline you replace states a verdict, correct it in `content` and leave it out of the
        line: a corrected verdict is still a verdict.

        **The rewrite is the whole record, and it may be shorter than the one it replaces.** A
        record that has gathered confirmations, corrections and scope notes across sessions is an
        archive, and an archive is cited rather than read: cut it back to the finding and what a
        reader should re-check, and give each separable lesson its own row with
        `zikaron_memory_remember`. Nothing is lost by the split — a lesson in its own row is found
        by its own headline; buried in an archive it has none.

        Requires `version` to be the value you most recently read for this exact uuid — from
        `zikaron_memory_fetch`, from `zikaron_memory_remember`'s own return for a row you just
        created, or from an earlier conflict payload for this uuid — never a version merely seen in
        a `zikaron_memory_search` row, which carries none. Returns `{uuid, version}` on success, or
        `{conflict: true, current: {...}}`
        if `version` is no longer current: `current` is the record as it now stands, with a fresh
        receipt already minted at its version, so you can re-decide and retry in one more call
        rather than fetching again first.
        """
```

**My count of the dedented text: 1,638 code points** (today 1,466; +172). Pin `may be shorter than
the one it replaces` intact; no tool name added.

---

## Things the researcher should check that I could not

- **Measure both wire descriptions** with the `harness.md` command; my counts are hand-derived.
- **Re-render** `.kiro/agents/zikaron-consolidator.json` and regenerate the two prompt-bearing keys
  of `tests/fixtures/kiro_artefacts.json` through the installer's own functions.
- The done-when asks `design/write-policy.md` §1 to state the rule beside the symptom-first
  paragraph (*"Gists must be cue-shaped, not summary-shaped."*). The sentence that belongs there is
  the one both surfaces now rest on: the line is usually all a later agent acts on, so a verdict in
  it is repeated as the finding and the record goes unread — keep the symptom, stop before the
  conclusion, and the conclusion lives in `content` at full strength. That document is the
  researcher's to edit; I have not touched it.
- `design/retrieval.md` line 724–725 (*"consolidation cannot lead a merged record with one observable
  symptom"*) is a paraphrase of the split rule, not of anything changed here; no drift.
- The replay's *"Triage kept"* bar is what guards the one way this wording could over-fire — a
  consolidator that reads *"drop the conclusion"* as *"drop everything after the subject"*. The
  boundary sentence (*observed versus made of it*) and the two positive examples that survive the
  rule are the text's defence; the bar is the measurement.

VERDICT: DRAFTED

---

## Round 2 — 2026-09-29: the in-place promote leak

### What the replay showed and why the Round 1 sentence did not bind

`research/m34-gist-form-replay.md`: where the consolidator wrote a gist, the rule held (2 of 64
residual); where it chose in-place promotion it could not, because that form keeps the gist
byte-identical by construction — 41 in-place promotes, 14 with a marked gist, about seven real
verdicts and one order. Round 1's sentence *"a verdict gist is never repeated byte-for-byte to promote
an entry in place"* sat in the authoring section, as a prohibition, three sections away from the
decision. The two texts the consolidator actually consults when it builds the call — the tool
description and the skill's verb paragraph — describe in-place promotion as a mechanism and put no
condition on it: *"Pass exactly one entry to absorb and repeat its gist and content byte-for-byte,
and that entry is promoted in place rather than copied"*. Read beside *Never invent* and *Preserve
the specifics*, the verbatim form is the faithful-looking choice for a single entry the consolidator
judges sound, and nothing at that point says what it costs.

What the consolidator lacks at the decision is one fact: **in-place promotion writes no prose, so
none of the authoring rules reaches the gist it promotes** — it is the one path through consolidation
where the gatekeeper does not author the gist. Stated there, the condition follows without being an
order: the form fits an entry whose gist and content already satisfy every rule, and any other entry
takes the ordinary form at no loss. Both texts below say that and point at the rules rather than
restating them. The mechanism is untouched, which keeps this inside §M34's fence (*"Not a change to
promote-in-place"*): byte-identical arguments still flip the row, exactly as `architecture.md`'s
ladder says; what changes is what the caller knows when it decides whether to pass them.

### Text 1 — `zikaron_memory_promote`'s description, `zikaron/mcp/consolidator.py`

Full replacement docstring, in source form (eight-space indent as it sits in the function; the wire
text is the dedented docstring). Longest source line is 97 columns. The ordinary form is stated first
and the in-place form second, so the default is the default and the exception carries its condition.

```python
        """Create a long-term record from part or all of this group. `absorb` is a list of
        `{uuid, expected_version}` naming journal entries delivered in this group and not yet
        dispositioned. Two forms, decided by what you pass. Ordinarily a new record is created
        from `gist`/`content` and every absorbed entry is retired against it, pointing at the new
        uuid. If `absorb` names exactly one entry and `gist`/`content` are byte-identical to it,
        that entry's own tier is flipped in place instead: no prose is written, so its gist and
        content go to long-term exactly as the entry's author wrote them, and none of the
        authoring rules in your instructions reaches them. The in-place form therefore fits only
        an entry whose gist and content already satisfy every one of those rules — a symptom with
        no verdict in the line, an observation rather than an order, its condition present. Any
        change to either, however small, takes the ordinary form, and nothing is lost by it: the
        entry is retired pointing at the record that carries its corrected text. Returns
        `{uuid, version, remaining_uuids, group_complete}` on success, or
        `{conflict: true, current: [...], remaining_uuids}` on the same stale-version terms as
        `zikaron_memory_merge`.
        """
```

**My count of the dedented text: 1,215 code points** (today's is 525; `DESCRIPTION_BUDGET` 1,900).
Same method as Round 1 — dedented line lengths plus one per newline, no trailing newline. Every
character is in the BMP (the one em dash is U+2014, which today's text already uses). The `harness.md`
command registers primary tools only; the consolidator-mode equivalent, using the helper the tests
already use:

```
.venv/bin/python -c "
import asyncio, tempfile
from pathlib import Path
from zikaron.mcp.server import build_server
mcp = build_server('consolidator', scope_dir=Path(tempfile.mkdtemp()))
for t in asyncio.run(mcp._list_tools()): print(len(t.description or ''), t.name)"
```

`test_no_wire_description_reaches_the_truncation_point[consolidator]` is the authoritative check
either way.

**What it says that the current text does not**, in order of consequence: the ordinary form and what
it does to the absorbed entries (today's text leads with the exception); that the in-place form
*writes no prose* and so applies no rule, with the three-item pointer at the rules the prompt states
in full (verdict, order, condition — the brief's three) rather than a second copy of the rule; and
that a change of any size takes the ordinary form at no loss, which removes the only reason to keep
a gist verbatim that the current text leaves standing. Nothing is phrased as a prohibition. The
`absorb` shape, the `Returns` block and the conflict terms are carried over verbatim, in the same
words; `zikaron_memory_merge` stays the only tool the description names, and it is registered on the
consolidator server, so `test_no_description_names_a_tool_its_own_server_does_not_have` is unaffected.
No primary tool is named — that test would fail on one.

### Text 2 — the verb paragraph, `zikaron/install/assets.py` `CONSOLIDATOR_PROMPT` §"## The three verbs"

Full replacement of the `zikaron_memory_promote` paragraph (today lines 100–103). The first line is
byte-identical to today's; the paragraph before (`merge`) and after (`discard`) are untouched.

```
**`zikaron_memory_promote(group_id, gist, content, absorb)`** — make a long-term record out of entries with
no good home. Ordinarily a new record is created from the gist and content you pass, and every
absorbed entry is retired against it, pointing at the record. One case differs: absorb exactly one
entry and repeat its gist and content byte-for-byte, and that entry is promoted in place — its tier
flips, no prose is written, and its gist reaches long-term as its author wrote it, so nothing under
"Authoring gists and content" below reaches it. That form fits an entry whose gist and content
already satisfy every rule there. An entry whose gist needed any change, however small, is promoted
as a new record, and nothing is lost by that: it is retired pointing at the record that carries the
corrected text.
```

It points at the section by its heading rather than naming any rule, so the prompt carries the
verdict rule's text once, where Round 1 put it. The retained clause *"repeat its gist and content
byte-for-byte"* is now the description of a case rather than an instruction for the call.

### Text 3 — the sentence that did not bind, `CONSOLIDATOR_PROMPT` §"## Authoring gists and content"

Small and, I judge, necessary: with the condition now stated at the decision point, the Round 1
sentences (*"It also means a verdict gist is never repeated byte-for-byte to promote an entry in
place: rewrite it, and accept that the entry becomes a new record. That is the intended outcome, not
a cost to avoid."*) are a second statement of the same condition, in the prohibition register this
round is replacing, and two copies of one condition in two registers drift. But the paragraph cannot
simply lose them: it opens *"Every gist you write passes through this rule"*, and in-place promotion
is the one gist the consolidator does *not* write, so without an acknowledgement the paragraph
overstates its own reach. Replace the last two sentences of that paragraph with one that names the
gap and points at the verb paragraph. The paragraph becomes:

```
**Every gist you write passes through this rule, and nothing else applies it.** The agents who wrote
these entries were asked for the same form, and many entries still arrive as verdicts; the gist you
write is the one that lasts. That covers the gist you give a promoted record and the gist you give a
merge target, whose existing gist may itself be a verdict whether or not the entries changed what it
says. The one gist you do not write is an entry's own, promoted in place: that form changes no
prose, and `zikaron_memory_promote` above says which entries it fits.
```

The first four sentences are byte-identical to today's. `zikaron_memory_promote` is already named in
the prompt, so the tool-name set `test_every_tool_the_prompt_instructs…` compares is unchanged.

### What else in the prompt was checked, and left alone

- **§"## Judgment"**: nothing names in-place promotion or prefers a verbatim gist. *"When in doubt,
  keep"* is keep-versus-discard; *"Never invent"* is about adding claims, and the cut this rule asks
  for removes a clause from the line while `content` keeps it, so it adds nothing; *"Preserve the
  specifics"* is answered by Round 1's *"softens nothing"* paragraph. No change.
- **§"## Details that will come up"**, *"That is the ordinary first run: promote."* — consistent with
  Text 2's *"Ordinarily a new record is created"*. No change.
- **§"## Reporting"**, *"how many records you merged into, created, and promoted in place"* — a
  count in a report, not a preference, and after this change it is a free per-run signal of how often
  the in-place form is chosen. No change.
- The `merge` and `discard` paragraphs and descriptions: untouched; neither has an in-place form.

### Pins

Grepped `tests/test_install_assets.py` and `tests/test_mcp_tool_descriptions.py` for every phrase in
the three replaced texts — `no good home`, `byte-for-byte`, `in place`, `promoted in place`, `flip
that row`, `byte-identical to it`, `not yet dispositioned`, `stale-version terms`, `part or all of
this group`, `writing a new one`, `rather than copied`, `intended outcome`: **no pin touches any of
them**. The only hit in `tests/` is a comment in `test_install_e2e.py:356–357` describing behaviour,
not asserting text. Every pin that sits *near* the changed text survives verbatim: `A gist carries no
verdict`, `condition is not a verdict`, `softens nothing`, `does not become`, `one observable symptom
or situation`, `four tools and no`, and the Round 1 list. `zikaron_memory_search` and
`zikaron_memory_fetch` are still absent from the prompt. No promote-description phrase is pinned on
the consolidator server at all — `test_mcp_tool_descriptions.py` pins only `zikaron_memory_next_group`
there — so the budget test is the one guard this text meets.

### Downstream, for the researcher

- **Re-render, do not hand-edit**: `.kiro/agents/zikaron-consolidator.json` and the
  `consolidator_agent_config` / `consolidator_config_bytes` keys of `tests/fixtures/kiro_artefacts.json`
  carry `CONSOLIDATOR_PROMPT` byte-for-byte. `SKILL.md` and the fixture's `skill_markdown` key are
  unaffected; `_SKILL_BODY` is untouched.
- `design/architecture.md` §"Consolidator tool surface" (the `zikaron_memory_promote` ladder entry)
  and `design/build-plan.md` §M34 *"Promote-in-place is unchanged"* both stay true as written; no
  design document quotes either replaced paragraph, so nothing there needs to move.
- **The second replay the research note proposes has a two-sided prediction, and both sides matter.**
  Seed the 14 marked in-place rows into a fresh store and consolidate. Prediction: the ~8 real
  verdicts and the order are promoted as *new* records with the verdict moved to `content`; the ~6
  whose markers are causal-mechanism `so` clauses or measurement dashes are **still promoted in
  place**, since their gists already satisfy the rules. If in-place drops to zero across all 14, the
  text over-fired — the condition was read as *never* — and the cost is a spent uuid per clean entry
  rather than a lost record, but the wording goes back. If a real verdict is still promoted in place
  with this text in front of the call, the remaining lever is not prose: the mechanism is fenced, and
  a code gate on *verdict* is not implementable without a model, so that outcome is an operator
  question rather than a Round 3.

VERDICT: DRAFTED

---

## Round 3 — 2026-09-29: the symptom that follows 'so'

### Why the Round 1 wording cut a symptom

The paragraph lists *"the clause after "so""* as a shape of verdict, unconditionally, and then gives
one example in which the clause after "so" is a conclusion. Read as a recogniser, that is a rule on a
word, and the boundary sentence two lines later (*observed against what the writer made of it*) never
says it applies to that word. So a gist written *mechanism, so symptom* — *"…shows in ps as `java
@/tmp/sbt-args*.tmp`, so pgrep -f on the main class finds nothing and a live job looks dead"* — lost
the clause that was the observation, and the three other causal rows were rewritten for the same
reason without losing anything. The fix is to condition the word on the boundary and show the
boundary on "so" as a minimal pair: same antecedent, one "so" clause that was seen, one that was
concluded. The pair uses the prompt's own deploy example rather than the pgrep row, because the
pgrep row is in the replay set, and a wording that quotes its test item would measure recognition
rather than the rule.

### The replacement paragraph, `CONSOLIDATOR_PROMPT` §"## Authoring gists and content"

Full replacement of the paragraph that begins `**A gist carries no verdict.**`; the paragraphs
before and after it are untouched. The diff is one clause added to the first sentence and one
clause plus one sentence added at the end; every other sentence is byte-identical.

```
**A gist carries no verdict.** Keep the symptom and drop the conclusion drawn from it — the clause
after "so", "therefore" or "which means" when it states what the writer concluded rather than what
was seen, or a bare ruling such as "is wrong", "cannot work" or "must". "The deploy script exits 0
when its health check times out" is a gist; "…, so its exit code proves nothing" is the record's
conclusion, and it goes in the content. A future agent that reads the verdict in the line repeats
it as the finding and leaves the record unread, where the reasons, limits and exceptions are; a
line that names the situation gets the record read when it looks relevant. The boundary is what
was observed against what the writer made of it: the first is the gist, the second is the verdict,
and "so" introduces either. "…, so CI shows it green while the old worker keeps serving" is a
second thing that was seen — the words a later agent will recognise, and the line is all it is
shown — and it stays; "…, so its exit code proves nothing" is what the writer made of it, and it
goes.
```

**Exactly what changed.**

1. First sentence: *"when it states what the writer concluded rather than what was seen"* is added
   after the three trigger words, so the words are a place to look and the boundary is the test. The
   bare-ruling list is unconditional as before; *"is wrong"* and *"cannot work"* are never
   observations.
2. Last sentence: *", and "so" introduces either"* is appended to the boundary sentence, then one
   sentence gives the minimal pair with the reason the observed side stays — it is the phrase a later
   agent recognises, and the line is what push shows. Nothing is phrased as an instruction to keep or
   rewrite; the consolidator that reads the pgrep gist now has the fact that its "so" clause is on
   the observed side, and no rule fires on it.

**Pins.** `A gist carries no verdict` is the paragraph's first words, unchanged. `condition is not a
verdict`, `softens nothing`, `does not become`, `no prose is written`, `The one gist you do not
write` live in other paragraphs, untouched. No tool name is added. `Lead with the observable
symptom` is in the paragraph above, untouched.

**Downstream.** Re-render `.kiro/agents/zikaron-consolidator.json` and the two prompt-bearing keys of
`tests/fixtures/kiro_artefacts.json`, as in Rounds 1–2. Prediction for a third targeted re-run on the
same 20 rows: the pgrep row and the three causal rows stay in place, or if rewritten keep their "so"
clause; the four verdicts and the order still leave in-place. If a "so" *verdict* row now also stays
in place, the conditional over-licensed, and the pair's second half is the sentence to strengthen.

### Surface 2 — `zikaron_memory_remember`'s description: leave it

It does not need the clause, and the reason is not the budget. The description names no trigger
word: its rule is *"stop before the conclusion"*, which is already the content test, and its one
example cuts a "so" clause that is a conclusion (*"so the suite is fine"*). The consolidator's
failure was a classifier's — reading another agent's line and deciding which side of the boundary a
clause sits on — whereas the writer of a fresh record is the observer and knows what it saw. No
write-side replay has shown the cut, and this surface has six code points of margin, so adding a
clause on an unmeasured risk would displace a measured fact to guard against a hypothetical one.

If a write-side replay does show it, the smallest form is replacing *"A verdict in the line is
repeated as the finding and the record goes unread; put the verdict in `content`."* with *"A verdict
in the line is repeated as the finding; put it in `content`, and what was seen stays whatever word
joins it."* — hand count +12 net, 1,906, six over — and the further cut is *"credentialed "* (−13,
to 1,893), the weakest word on the surface, since a connection string worth naming as a secret is
one that carries a credential. Not proposed now; recorded so the arithmetic is not redone.

VERDICT: DRAFTED
