# M33 — the two tool-description paragraphs, authored text

**Authoring, not review** (operator decision 2026-09-25, `design/build-plan.md` §M33 §"Two prose
changes this milestone carries"). The drafts in that brief are the specification; this file is the
wording to ship. `zikaron/mcp/primary.py` is untouched by me — the researcher applies both.

## Round 1 — 2026-09-28

### (1) `zikaron_memory_amend` — a record may get shorter

**Placement.** A new **second paragraph** of the docstring: after the opening paragraph that ends
*"…and to fold a near-duplicate's additions into the older row."* and before the paragraph that
begins *"Requires `version` to be the value you most recently read…"*. The opening paragraph has just
named folding-in as an occasion, which read alone is an invitation to append; the licence to cut has
to be the next thing said, before the mechanics of `version`.

**Text, wrapped to the file's width at the docstring's 8-space indent** (re-wrap freely; the pin is
matched flattened):

```
        **The rewrite is the whole record, and it may be shorter than the one it replaces.** A
        record that has gathered confirmations, corrections and scope notes across sessions is an
        archive, and an archive is cited rather than read: cut it back to the finding and what a
        reader should re-check, and give each separable lesson its own row with
        `zikaron_memory_remember`. Nothing is lost by the split — a lesson in its own row is found
        by its own headline; buried in an archive it has none.
```

Three sentences, 86 words.

**Pin phrase:** `may be shorter than the one it replaces` — zero occurrences anywhere in the corpus
today (`rg -n 'shorter than'` finds only unrelated fusion and chunking prose). It sits inside the
bold opening sentence, which is the sentence a well-meant tightening would most plausibly cut to
*"The rewrite is the whole record"* — the replacement fact the docstring's first word already
carries — and lose the licence that is the whole point. Match it with the description flattened
(`" ".join(description.split())`), as `test_zikaron_memory_retire_describes_the_supersession_graph_rules`
does, since it can wrap.

**What each clause carries, against the spec:**

| Spec item | Where it lands |
|---|---|
| Amending replaces; not an append | *"The rewrite is the whole record"* — stated as what `content` *is*, beside the docstring's own *"Fully rewrite"*, rather than as a prohibition on appending |
| Accumulated confirmations/corrections/scope notes → cut back to the finding and its instruction | *"gathered confirmations, corrections and scope notes across sessions is an archive … cut it back to the finding and what a reader should re-check"* |
| Separable lessons become their own memories; nothing is lost | *"give each separable lesson its own row with `zikaron_memory_remember`. Nothing is lost by the split"* |
| Too long to hold in working memory → cited rather than read | *"an archive is cited rather than read"* |

**Choices made, so they are not re-derived:**

- **"its instruction" is rendered as "what a reader should re-check".** The paragraph immediately
  above says *"observations rather than orders"*; a record's *instruction* in the next paragraph
  would read as a contradiction. `zikaron_memory_search` already defines what a record does for a
  reader — *"it tells you what to re-check, not which option to drop"* — so that is the corpus's own
  word for the actionable half, and it does not collide.
- **"too long to hold in working memory" is folded into "archive".** The word already means a body
  you consult rather than read, and the sentence pays for that meaning once, in *"is an archive, and
  an archive is cited rather than read"*. Spelling out working memory costs eight tokens per context
  window per turn for a gloss on a word the model has.
- **"Nothing is lost" is given a mechanism, not asserted.** D16 makes cutting feel like deletion, so
  the sentence says *why* a split loses nothing: a lesson in its own row has a headline to be found
  by, and buried in an archive it has none. That is true on the read path as built — push shows
  gists only, and Q12 measured a convention buried under a bug-shaped gist as reachable only on
  queries shaped like the bug — and it is information the agent lacks rather than reassurance.
- **"across sessions"** stays: it names the shape the failure takes — no one session writes an
  archive, each appends a little — so the agent that meets one in that state knows it is looking at
  the accumulation and not at one author's deliberate length.
- **No history claim.** The store keeps no readable version history, so the paragraph does not say
  "the old text is still there" or anything like it. What it says is that the *lessons* survive, in
  rows of their own.

### (2) `zikaron_memory_remember` — a uuid is not a citation

**Placement.** A new paragraph **directly after** the one that ends *"…never by quoting its
headline, which is rewritten on every amend."* and before *"Returns `{uuid, version,
near_duplicates: …`"*. That paragraph has just told the reader to cite by subject and given one
reason (the headline moves); this one gives the second prohibited form and its reason (the id
stays while the claim moves), so the reader gets the whole citation rule in one place — and sees
that neither the headline nor the id survives an amend, only the subject does. The alternative,
after the `Returns` paragraph where the uuid is handed over, was considered and rejected: it
separates the two halves of one rule by a paragraph of mechanics, and the uuid an agent cites in a
document usually came from a push or a search rather than from this return value, so "here is
where you get it" is not the moment anyway.

**Text, wrapped to the file's width at the docstring's 8-space indent:**

```
        **A uuid is a handle for this session's tool calls, not a reference for anything durable to
        hold.** It looks like a stable identifier and is not: an amend rewrites the record under
        it, and consolidation moves the claim to another row and leaves this one fetchable but
        demoted — so an id copied into a document keeps resolving long after the finding has left
        it. A document points at a memory the way another record does: by its subject.
```

Three sentences, 79 words.

**Pin phrase:** `keeps resolving long after the finding has left it` — zero occurrences in the
corpus (`keeps resolving` appears once, in `tests/test_indexing_acquisition.py`, about blob
pointers). It pins the reconciliation the brief calls the actual finding — *a uuid that ever
existed always resolves, to the row, never to the claim* — which is the clause a future edit would
most plausibly flatten to "uuids can go stale" and lose. Match flattened, as above. If a second pin
is wanted for the instruction itself, `the way another record does` is also unused anywhere.

**What each clause carries, against the spec:**

| Spec item | Where it lands |
|---|---|
| A handle for this session's tool calls, not a reference anything durable may hold | *"A uuid is a handle for this session's tool calls, not a reference for anything durable to hold."* |
| Looks like a stable identifier and is not; an internal handle consolidation moves the claim away from; meaningful only inside the session that read it | *"It looks like a stable identifier and is not: … consolidation moves the claim to another row and leaves this one fetchable but demoted"* — the session scope is carried by the first sentence's *"this session's tool calls"* |
| Cite by subject, in a document as in another record | *"A document points at a memory the way another record does: by its subject."* |

**Choices made:**

- **The amend clause is there for accuracy, not emphasis.** Of the six dead citations measured, four
  resolved to superseded rows and two of those to records *amended the same day* — so a live uuid
  can point at text that has moved under it, and a sentence naming only consolidation would license
  the inference that an id is safe until the next consolidation run, which D10 makes rare. The
  previous paragraph says the *headline* is rewritten on every amend; this one says the *record
  under the id* is, which is the fact that makes the id worthless as a citation.
- **"fetchable but demoted"** is the corpus's own description of an absorbed row (D16, D25), and
  `zikaron_memory_search` has already taught the reader *demoted* (*"a demoted row is visible for
  what it is"*). The brief's *husk* was considered and dropped: vivid, but a word the model has to
  decode, where *demoted* is one it has just been given.
- **Mechanics verified before asserting them.** `zikaron_memory_merge` rewrites the target uuid and
  supersedes the absorbed rows; `zikaron_memory_promote` mints a new row unless it flips exactly one
  journal row in place (`zikaron/mcp/consolidator.py`). So "consolidation moves the claim to another
  row and leaves this one fetchable but demoted" is true of every absorbed row, and the merge target
  — same uuid, rewritten content — is covered by the amend clause.
- **"anything durable" is kept over a list.** A concrete list (*a document, a comment, a commit
  message, another agent's memory*) would invite the reading that whatever is not listed is fine;
  the general noun covers Q14's fourth case — a fact mirrored into the harness's own memory — which
  no short list would name. The last sentence grounds it in *a document*, the measured case.
- **No mention of hallucinated ids** (two of the six resolved to nothing). It is true and it is
  information the agent lacks about its own copying, but it is not in the spec, it is a different
  claim from the one being made, and the paragraph does its job without it.

### Constraints checked on both

- No *always*, *be sure*, *remember to*, *never* (the existing paragraph's *never* is left as is; neither addition adds one). No hedging, no self-narration, nothing that explains that it is explaining.
- Register: bold on the load-bearing sentence, a colon-led mechanism, the claim stated as what the thing *is* rather than what the reader must do — the shape of *"A headline straining toward either is carrying content that belongs in `content`"* and *"A record phrased as a command is obeyed by an agent with less context than you have."*
- Every tool name each paragraph mentions (`zikaron_memory_remember`) is registered on the primary server, so `test_no_description_names_a_tool_its_own_server_does_not_have` stays green.
- `architecture.md` does not quote either description verbatim (grep for the opening sentences finds only `primary.py` and review files), so no design-side mirror needs the same edit. `test_quoted_design_prose_is_verbatim.py`'s stated scope is `zikaron/` and `tests/`, so this file's own quotations are not in its reach.
- Cost: 86 + 79 words, on two descriptions loaded into every primary-agent context. Both were cut to the clauses that carry a spec item; nothing in either restates the docstring above it.

### One observation, not a finding

The uuid an agent writes into `STATE.md` most often arrived through the push block or a
`zikaron_memory_search` result, and neither of those surfaces will carry this sentence. The operator
has already decided that a write-side description is where it lands, and why the read arm stays
untouched while M32's A/B accumulates (`design/build-plan.md` §M33 §"Why it is admissible here
despite the fence below"); this notes only that if the citation rate does not move, the first
suspect is the surface rather than the wording.
