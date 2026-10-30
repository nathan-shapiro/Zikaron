# Review — M42 brief: paged knowledge search

Artifact: `design/build-plan.md` §"M42 — Paged knowledge search: each corpus's first results whole,
the rest by name" (lines 8865–8959 at the time of each round). Reviewer: memory-reviewer.

## Round 1 — 2026-10-30

**Summary judgment.** The brief is close to buildable: the mechanism matches `search.py`'s total
order and `_capped`'s cap-before-limit, the configuration key is well bounded, the evidence is
cited honestly as a ceiling, and the scope fence is clean. Two things stop it from being built
without re-deciding: the `role` it specifies is heading extraction, which `design/knowledge-index.md`
§1.1 forbids in so many words and the brief does not amend; and the invariant it adds to §13 is
false whenever `offset + limit_per_kb` exceeds the 20 clamp. Around those, the `role` definition
differs from the experiment that produced its measurements, the description's author is not told
the tests that pin the description's wording, and several design sentences that paging falsifies
are not named as sites.

### Findings

1. **[BLOCKER] `role` contradicts §1.1, and the brief does not amend it.** `design/knowledge-index.md`
   §1.1 (lines 38–45): *"the design must not assume it — no markdown parsing and no heading
   extraction. The one structure the index reads is its own (K14, §7.7)."* Item 3 (build-plan.md
   lines 8900–8907) defines `role` by skipping front matter and headings up to "the next heading" —
   heading extraction, applied at search time to every named entry. A build from this brief leaves
   §1.1 and §8.3 contradicting each other with no guard that notices. Decide one way in the brief:
   either (a) amend §1.1 in the same change — add it to the normative-sites paragraph (line 8867)
   and state the exception: *the index reads two structures of its own choosing and nothing else:
   K14's front matter, and, for a named entry's `role`, a `---` fence and ATX `#` headings; a file
   without them yields its opening lines as its role, so nothing is assumed of a file that lacks
   them* — or (b) make `role` structure-free (the first chunk's text after any K14 front matter, cut
   on a word boundary to 400 code points), accepting that a code-knowledge document's `role` then
   opens with its `# Title` line. (a) keeps the measured 230/310 figures applicable; (b) needs them
   re-measured. Either is a one-paragraph edit; what is not acceptable is leaving §1.1 as it stands.

2. **[BLOCKER] Item 8's invariant is false past the clamp.** Build-plan.md lines 8925–8928: *"the
   results of a call with `offset` k and `limit_per_kb` L are ranks k+1 to k+L of a call with
   `offset` 0 and `limit_per_kb` k+L."* `groups.clamp_limit` (groups.py line 205) caps
   `limit_per_kb` at 20, so for k+L > 20 the reference call returns at most 20 results and ranks
   21..k+L do not exist in it, while the paged call returns up to L results from a pool that
   `fusion_depth` bounds near 100. Example: `offset 15, limit_per_kb 10` returns ranks 16–25; the
   reference call returns ranks 1–20. Fix the sentence: *"... for every k ≥ 0 and L ≥ 1 with
   k + L ≤ 20 ..."*, and say in "Invariants and properties" that the property's generator respects
   that bound. Without the clause the §13 text is wrong as normative prose and the property test
   fails on its first unlucky draw.

3. **[IMPROVEMENT] The `role` definition is not the one that was measured, and it is ambiguous.**
   `experiments/paged_search_replay.py` `_role_line` (lines 140–154), which produced the 230/310
   figures item 3 quotes: strips a `---`…`---` fence, drops non-blank lines, **drops the first
   remaining line whatever it is**, collects until a line starting `##` (a `#` line would not stop
   it), joins, applies no cap, reads the whole file. Item 3: skips "headings", stops at "the next
   heading", says nothing about blank lines, reads the first chunk, caps at 400. The two coincide on
   a code-knowledge document (`# Title`, role paragraph, `## Purpose`) and on nothing else, and the
   brief should say that is why the figures carry. Pin the definition so the implementer decides
   nothing: non-blank lines only, and a blank line neither starts nor ends the role; a heading is an
   ATX line (`#` through `######` then a space) and nothing else — no Setext, since the index parses
   no more markdown than this; front matter is what `links.read_link` recognises (`---` as the first
   line, to the next `---` line, within `LINK_PREFIX_CHARS`), reused rather than re-detected, so the
   two readers cannot disagree about where it ends; the closing `…` counts inside the 400. Add to
   "Invariants and properties": `role` of a code-knowledge document equals the experiment's
   `_role_line` of its file, on the fixture documents, so the measured quantity is the shipped one.

4. **[IMPROVEMENT] "Group order computed as before" needs the cosine of every result on the page,
   named included — say so, and test it.** `Group.order_key` (groups.py line 126) is the max
   `score` over `self.results`, and `score` is not monotone down the fused list (§8.3 line 1882),
   so the page's best cosine can sit in a named entry. Item 2's "no `score`" must be stated as a
   payload omission only: the internal result keeps its cosine (`_missing_cosines` still runs for a
   lexical-only named entry) and group order uses it. Add a covered property: for one call, group
   order at `knowledge_whole_results` 3 equals group order at 20. State too the consequence of
   "offset applies to every group" that the brief leaves implicit: group order on page k is by
   that page's best cosine, so groups may reorder between pages; the description's "scan every
   group" already covers it.

5. **[IMPROVEMENT] Dropping `stale` from a named entry is under-argued, and §12's counters are not
   decided.** A named entry keeps `start_line`/`end_line`, and a line range is the thing `stale`
   qualifies: a reader who `Read`s those lines of a changed file gets other bytes and nothing says
   so. The `stat` is already made once per distinct path (search.py line 376) and the field costs
   about 14 bytes, so keeping it is the cheaper decision; if it is dropped, give the reason. Either
   way, decide what `results_returned` and `results_stale` count under paging — every ranked result
   on the page (which `_tally`, groups.py line 358, does today if `stale` stays computed) or whole
   results only — and add `design/knowledge-index.md` §12 to the normative sites so the counters'
   meaning is written where they are defined.

6. **[IMPROVEMENT] The description's author is handed a budget and none of the other constraints.**
   Item 6 (lines 8919–8922) gives memory-reviewer 16 code points and three things to say; the
   wording must also keep six pinned phrases
   (`tests/test_mcp_tool_descriptions.py` lines 150–156: "about to propose a design", "not
   comparable between corpora", "was searched and had nothing", "copied verbatim", "no evidence of
   change, not a guarantee", "not instructions"), name `zikaron_memory_search`
   (`test_each_search_tool_names_the_other_store_s_search`), name no tool the server lacks, and
   match §8.3's quote paragraph for paragraph after whitespace flattening
   (`test_every_knowledge_description_matches_the_design_document`). Paging needs on the order of
   250–350 code points, so about 300 of existing text must go: say the description is rewritten
   whole, that M39's K14 paragraph may be re-cut under the same authority, and that §8.3's prose
   about which paragraph is whose (lines 1804–1809) is updated with it. Two content constraints
   belong in the brief rather than in the author's head: the description must stay true under
   every configured cutoff — stage 2's unpaged arm sets 20 and reads the same text — so it names
   the key and says "by default" or avoids the number rather than asserting "the first 3"; and the
   untrusted-input sentence covers `role` as it covers snippets, since `role` is file text too.

7. **[IMPROVEMENT] "A page past the end" — the end is fusion's, not the corpus's.** Each arm
   returns at most the corpus's `fusion_depth` chunks (search.py lines 362–367; default 50), so
   the pool after the per-file cap holds at most about 100 results and `offset` beyond it answers
   an empty group however many chunks the corpus has. State it in item 4 so the implementer does
   not reach for a deeper arm and the description does not imply that paging exhausts a corpus.

8. **[IMPROVEMENT] Normative sites named by predicate where they should be named.** "`design/code-knowledge.md`
   wherever it states what a search returns or costs a reader" (line 8870) resolves to three
   sentences the build must change, and two sites elsewhere are missing: `code-knowledge.md` §5.3
   lines 738–740 (a group of five is about 7,000 bytes, so about three groups fit the cap — at the
   default cutoff a group of five is three snippets and two entries, and the arithmetic moves);
   §8 lines 1416–1419 (*"A search result is the matching lines with the document's path and
   `source.state`, never its title or role line"* — false for a named entry, and the
   partial-coverage argument that follows from it changes); §8 lines 1478–1481 (the same
   "about three groups"); `design/knowledge-index.md` §7.4 lines 1292–1295 (*"`results: []` is
   reached only by a corpus that is empty, unbuilt, or unable to serve"* — false at `offset` > 0);
   and §14, which lists every K-decision and gets a row for this one (paging is presentation only;
   the cutoff is configuration; no stored field). Replace the predicate with the list.

9. **[IMPROVEMENT] Done-when 2 names a measurement without its harness, its store or its quantity.**
   Lines 8946–8949. No CLI search exists, so the replay is an in-process `groups.search_all` with
   the encoder against a store — name the file (`experiments/paged_search_replay.py` extended, or a
   new `experiments/m42_replay.py`) and the store (the treatment copy's `.zikaron` under
   `~/Zikaron-m40`, which `m40_eval.py` `_provision` built; state the precondition that it opens at
   today's schema with the corpus `ok`, and what is done if it must be rebuilt). Name the quantity:
   stage 1's 65.5% is `len(json.dumps(results))` of result lists, not `groups.response_bytes` of
   whole responses, so say which is measured and compared. Add one number the replay can give for
   free: how many named entries had their `role` cut at 400.

10. **[NITPICK] State the fetch-one idiom.** The description must say "how to fetch one whole"; the
    brief should give it so author and implementer agree: `offset: k−1, limit_per_kb: 1` returns
    rank k whole, which is exactly what item 8's invariant licenses. Say also whether the
    description points a reader at that or at reading `path` lines `start_line`–`end_line`
    directly, which K13 makes equivalent for an unchanged file and costs no search.

11. **[NITPICK] `end_line` on a named entry.** It is the chunk's own `end_line` — no snippet cut
    applies — and `_StoredChunk` does not carry it today (`cut_to_snippet` derives it from the
    text), so say it is read from `chunks.end_line`.

12. **[NITPICK] Cost of a page.** Item 4 says a page is recomputed; say that this is a whole
    search — query embedding, both arms, the `stat`s and the source hashing — so a page costs what
    the first call did, which is the figure stage 2 will be weighing the saving against.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-30

**Summary judgment.** Every round-1 finding is resolved as the brief says: `opening` parses no
markdown and the fence says §1.1 stands; the §13 invariant carries its `k + L ≤ 20` bound and the
property its generator; group order, `stale`, the fusion end, the normative sites, the replay's
harness and store, and the description's constraints are all stated. What remains is narrower and
each fix is a sentence or two: item 3 misdescribes what `opening` yields for a code-knowledge
document, and the evidence paragraph still quotes a saving measured on a smaller entry than the one
that ships; `searches_empty` is left to count a page past the end as an abstention; and item 3
leaves two small choices to the implementer. No blocker.

### Findings

1. **[IMPROVEMENT] Item 3's account of a code-knowledge opening is wrong in the common case, and the
   evidence paragraph's saving was measured on a different entry.** Build-plan.md lines 8915–8916:
   *"a code-knowledge document's opening is its `#` title line followed by §4's role line."* §4's
   role line is *"One or two sentences"* (`code-knowledge.md` line 341) and the title is `# ` plus a
   backticked path (lines 208–209) — together well under 400 code points — so with whitespace
   collapsed the 400 limit is reached inside `## Purpose`, and the opening of nearly every
   code-knowledge document is *title, role line, "## Purpose" and the start of its text*, cut at
   400. Two consequences the brief does not state. (a) Lines 8886–8888 say showing ranks below 3 by
   name *"keeps 65.5% of the search-result characters"*; `experiments/paged_search_replay.py`
   lines 171–178 measured that with a `role` field holding the role line alone (round 1 put it at
   230/310 code points) and no `stale`, where the shipped entry carries `stale` and an `opening`
   that will sit at the 400 cap, so the shipped saving is smaller than the figure quoted and the
   brief reads as if 65.5% is what ships. (b) The description's author is told the opening is a
   title and a role line, and will describe it as such. Fix item 3's sentence to what is true —
   *a code-knowledge document's opening is its title line, its role line and whatever of
   `## Purpose` fits in the 400* — and qualify the evidence paragraph: *measured with a role-line
   field and no `stale`; the shipped entry is larger, and done-when 2 re-measures it.* Then let
   done-when 2 decide the cap knowingly rather than after stage 2: have `m42_paged_replay.py`
   report the 3-against-20 ratio with the opening cap at 400 **and at 200**, so the operator sets
   the default with both numbers in hand before the live arm runs — the replay is free to run
   twice and nothing else in the brief moves.

2. **[IMPROVEMENT] A page past the end is counted as an abstention.** `counters.SearchTally`
   (counters.py line 204) sets `searches_empty` to 1 whenever a group's results are empty, and item
   8 (lines 8949–8950) says *"nothing new is counted"*. So every `offset` past fusion's end — which
   item 4 makes a legitimate, described answer — increments the counter §12 defines as *"how often
   a corpus is searched and has nothing — the abstention rate §7.4 exists to make visible"*, on a
   corpus that answered. A reader asking for `offset 10, limit_per_kb 10` on a corpus with eight
   capped results does this on an ordinary day. Decide it in item 8 and write it into §12's
   `searches_empty` row: *`searches_empty` counts a corpus whose ranked list is empty before
   `offset` is applied; a page past the end raises `searches` and no `searches_empty`* — one
   condition where the tally is built, since `search_one` knows whether its pool was empty. Say too
   that `searches` counts pages, since item 4 makes each one a whole search, so `results_returned /
   searches` is per page from this change on.

3. **[IMPROVEMENT] Item 3 leaves two choices to the implementer.** (a) *Which text the helper runs
   over.* Lines 8909–8912 say the opening is read from the first chunk and the front matter's end
   is found *"where `links.read_link` recognizes one"* — but on the search path `read_link` runs
   over `link_store.stored_prefix` (link_store.py lines 26–53), which joins chunks until it holds
   `LINK_PREFIX_CHARS` = 4,096 characters, while a chunk is about 1,800 (§4.3 line 608). A linked
   document whose block closes after chunk 0 therefore has `source` and a first chunk with no
   closing `---`. State the rule: *the helper runs over the first chunk's text alone; a block that
   does not close within it is not skipped, and the opening starts at the chunk's first character*
   — one query per group, as item 3 wants, and never a second chunk. Name the chunk by
   `part_index = 0`, the join `link_store` already uses, rather than *"the lowest `start_line`"*.
   (b) *The cut when there is no boundary.* "Cut on a word boundary" after collapsing leaves one
   boundary, a space; say *at the last space before the limit, or at the limit when there is none*,
   so a 400-character token — a URL, a minified line — yields a hard cut rather than an empty
   opening. Add both to the property list (a K14 block longer than the first chunk; a first chunk
   with no space in its first 400), and say the 400 is a named module constant beside
   `LIMIT_PER_KB_CAP`, since the fence rules out configuration and nothing else names where it
   lives. An opening with nothing after the front matter is the empty string, never absent.

4. **[NITPICK] Where `offset` skips from.** `search_one` drops a chunk with no vector after the cap
   (search.py lines 387–392); if `offset` skips from the capped pool rather than from the final
   list, the two calls in item 10's invariant can disagree by one result when a dropped chunk sits
   in the skipped prefix. Say in item 4 that `offset` skips results of the final list, after every
   exclusion. One clause; the case is one every build makes impossible, which is why this is a
   nitpick.

5. **[NITPICK] Two one-page summaries say every result is a fragment.** `knowledge-index.md` §2
   lines 79–80 (*"The agent receives fragments with line ranges … A fragment is byte-identical to
   the lines it names"*) and `README.md` lines 22 and 670 (*"fragments … quoted verbatim"*) stay
   true of whole results and silent about named entries; a reader of §2 would not learn paging
   exists. Add §2 to the sites with one clause — *past `knowledge_whole_results` a result is a
   named entry: path, line range and opening, no fragment* — and the README's two sentences if a
   user-facing mention is judged worth it.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-30

**Summary judgment.** Every round-2 finding is applied as the brief says, and I re-checked each
against the code rather than the summary: the opening's source chunk, its cut rule and its empty
form; `searches_empty` before `offset`; the skip after every exclusion; §2 and the README as sites.
The brief now matches `search.py`'s pipeline and `groups.py`'s assembly at every point I could test,
and the evidence paragraph says what the 65.5% was measured on. Three things still leave a decision
to the implementer or make a done-when unexecutable as written, each a sentence to fix: the constant's
named home creates an import cycle, done-when 2 varies a constant it gives the replay no way to set,
and the §13 invariant is scoped so that it does not cover the fetch-one idiom item 4 states and the
description will teach. No blocker.

### Findings

1. **[IMPROVEMENT] `OPENING_MAX_CHARS` "beside `LIMIT_PER_KB_CAP`" is a placement the code cannot
   take.** Build-plan.md line 8919. `LIMIT_PER_KB_CAP` is in `groups.py` (line 51), and `groups.py`
   imports `search` (line 38); `search.py` imports nothing from `groups`. The cut the constant bounds
   is the analogue of `cut_to_snippet` (search.py lines 206–240) and belongs beside it — so a constant
   in `groups.py` used from `search.py` is a cycle, and the only way to honour the sentence is to
   cut the opening in `groups.py` at payload time, which means `search_one` hands up to 1,800
   characters of raw first chunk per named entry across the module boundary for `groups` to
   trim. Round 2 suggested the location loosely and I am correcting it: write *a module constant in
   `search.py` beside `cut_to_snippet`, set to 400*, and leave `groups.py` out of it. One phrase.

2. **[IMPROVEMENT] Done-when 2 runs `groups.search_all` at `OPENING_MAX_CHARS` 400 and 200 and
   says nothing about how the replay sets a module constant.** Lines 8990–9000. `search_all`
   builds `SearchSettings` from `config` (groups.py lines 458–462) and exposes no way in; a `Final`
   module constant is settable at runtime by attribute only if the code reads it where the cut
   happens rather than binding it as a default argument. As written, the implementer must choose
   between an attribute set on a `Final` in an experiment and a parameter on `SearchSettings` that
   nothing but the replay passes — and done-when 2 does not run until one is chosen. Decide it in
   the brief, in one sentence either way: *the constant is read where the opening is cut, never
   bound as a default, and `m42_paged_replay.py` sets `search.OPENING_MAX_CHARS` for its second
   pass* (experiments are outside every sweep, so the hack lives where hacks are allowed), or
   *`SearchSettings` carries `opening_max_chars`, filled from the constant by `search_all` and by
   the replay directly*. The first is cheaper and ships nothing.

3. **[IMPROVEMENT] The §13 invariant does not license the fetch-one idiom at the default cutoff.**
   Item 10 (lines 8963–8967) holds *"with every result whole"* — cutoff 20 — while item 4 (lines
   8938–8940) promises that `offset` k−1, `limit_per_kb` 1 returns rank k whole, a promise a reader
   acts on from a page at cutoff 3, and item 2 (line 8907) asserts *"Paging changes what is shown,
   never what is ranked"*. Nothing in the invariant or the property list tests that a named entry
   at rank k on one call is the chunk the fetch returns whole; the two claims rest on the
   implementation applying the cutoff after the skip, which is exactly what a property is for.
   Extend the invariant: *at any cutoff, the same `path` and `start_line` at every rank; with every
   result whole, the same `end_line` and snippet too.* The split is forced and worth stating: a
   named entry's `end_line` is the chunk's own (item 2) and a whole result's is the snippet's, so
   they differ whenever `truncated` would be true. Run the §13 property at cutoff 3 as well as 20,
   and add the one-line check that a page's first `min(cutoff, L)` results carry `snippet` and the
   rest do not, which is item 4's sentence as a test.

4. **[NITPICK] Two more things the key's tests read.** Item 1 (lines 8900–8901) says the key is
   *"Declared in `schema.md`'s table"*; `tests/test_config_keys.py` also reads the TOML sample under
   the same heading (`test_defaults_match_the_design_sample`, schema.md lines 597–610), so the key
   goes there too or the gate is red on the first run. And `tests/test_knowledge_groups.py` lines
   112–114 tie `knowledge_max_chunks_per_file`'s maximum to `LIMIT_PER_KB_CAP`; the new key's
   maximum is the same cap for the same reason, so add that assertion to the property list beside
   the schema-agreement line. Add too: `offset` −1 answers as `offset` 0.

5. **[NITPICK] Two sentences inside named sections go false and are not in the brief's predicate.**
   `knowledge-index.md` §10 line 3030, *"the two search keys shape one response"*, becomes three;
   §8.3 line 1879, *"at most `limit_per_kb` extra vector reads per group"*, becomes at most
   `offset + limit_per_kb`, bounded by the pool, since item 4 skips after every exclusion and the
   no-vector exclusion needs the cosine. The brief names §10 as *"(the key)"* and §8.3 by four
   parts, neither of which is these; add both.

6. **[NITPICK] The evidence paragraph names one quantity wrongly and drops a verb.** Line 8886:
   *"of the 136 reads that followed a search"* — `research/paged-search-replay.md` §Method defines a
   use as a `Read`, `Grep` or `Bash` call naming the path within the next 20 tool calls, and 136 is
   the count of uses; say *uses*, or *tool calls naming a result's path*. Lines 8888–8890: *"keeps
   65.5% of the search-result characters, so at most 5.7% of a medium run's carried characters and
   9.2% of a hard run's"* — without *saves* the clause reads as search's share of the run, which is
   15% on medium (§6); write *so saves at most 5.7% …*.

7. **[NITPICK] Item 3's helper sentence overstates, and leaves one block unclassified.** Line 8916,
   *"so the two cannot disagree where it ends"* — the next clause names the case where they do (a
   block closing past chunk 0: `read_link` over `stored_prefix` says it ends, the helper over the
   chunk says it does not). Say *so the two split lines the same way*. And state which block is
   skipped: *one `read_link` answers other than `None` for* — so a malformed K14 block (one key,
   or a bad value) is skipped like a well-formed one, and a `---` block carrying neither key stays,
   as the property list already says. Without it the malformed case is the implementer's call.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-30

**Summary judgment.** Round 3's seven findings are applied as the brief says, and I re-derived
each against the code rather than the summary: `search.py` imports from `links` and nothing from
`groups`, so the constant's home is sound; the cut reads the constant at use; the §13 invariant's
split is right for every k, L and cutoff I worked through; the key's maximum and sample line, §10's
count, §8.3's bound, the quantity words and the helper's skip rule are all in. I also re-checked
the evidence paragraph against `research/paged-search-replay.md` figure by figure, the description's
free space (the shipped docstring is about 1,884 code points, so 16 is right), the store path
against `m40_eval.Layout`, and D33's startup read against item 5. The brief is buildable. What
remains is one specified behaviour with no test in the list that pins it, and four one-line
precisions; none changes what ships.

### Findings

1. **[IMPROVEMENT] The one value on which a named entry differs from its whole result has no test
   in the list.** Item 2 (build-plan.md lines 8906–8907) specifies that a named entry's `end_line`
   is the chunk's own, read from `chunks.end_line`, and item 10 (lines 8971–8972) argues the split
   from it. The property list (lines 8978–8996) never compares a named entry's `end_line` to
   anything: the §13 property at cutoff 3 compares `path` and `start_line` only, by design, and the
   payload line checks which fields are present, not their values. The implementation most likely
   to be written — the existing `search_one` loop with `cut_to_snippet` still run for every kept
   chunk and three fields dropped from the payload — ships the snippet's `end_line` on a named
   entry, contradicts item 2, and passes every listed test; `new_line_coverage.py` does not catch
   it either, since the line executes. Add one line: *a named entry's `end_line` is
   `chunks.end_line` — equal to the whole result's for a chunk within `knowledge_snippet_max_chars`
   and greater than it for a chunk over the cap* (the `TestTheSnippetCap` fixture already builds
   such a chunk). Add beside it the other field the list leaves unpinned on a named entry:
   *invariant 17 holds at every rank — a named entry carries `source` exactly where its whole result
   would* — since every existing K14 test reads results that are whole.

2. **[NITPICK] The malformed-block skip is specified and not in the property list.** Item 3 (lines
   8915–8916) says a block `read_link` answers *other than `None`* for is skipped, *malformed or
   not*; the list's `opening` line (lines 8988–8991) covers a well-formed K14 block, an unlinked
   file, another kind of front matter, and a block closing after the first chunk — not a K14 block
   with one key closing within it. Add *on a malformed K14 block within the first chunk, which is
   skipped* to that line. Round 3 asked for the rule and got it; this is the test for it.

3. **[NITPICK] "Where it closes within that chunk" is wider than the reader the brief names.** Item
   3 (line 8916–8918) finds the block's end with a helper sharing `read_link`'s line reader;
   `links._lines` (links.py lines 91–107) stops at `LINK_PREFIX_CHARS` = 4,096, so for a first
   chunk longer than that — `chunk_max_tokens` reaches 8,192 — a block closing past 4,096 is one
   `read_link` calls malformed and the helper cannot see close, while the sentence says it is
   skipped. The behaviour the shared reader gives is the right one and needs no code; write *where
   it closes within the first `LINK_PREFIX_CHARS` of that chunk*, so the implementer does not write
   a second reader to honour the sentence as it stands.

4. **[NITPICK] `searches_empty` before `offset` needs a return `_serve` does not get today.** Item
   8 (lines 8962–8963). `groups._serve` (groups.py line 348) builds `_tally` from `search_one`'s
   return alone, and if that return is the page, whether the ranked list was empty is gone. Say in
   item 8 that `search_one` returns the page together with whether the ranked list was empty — a
   two-field value — and `_serve` builds the tally from both. One clause; without it the
   implementer chooses between that and a second query.

5. **[NITPICK] Two quantities in the evidence paragraph are still named by the wrong unit.** Line
   8887: *"of the 136 tool calls that named a result's path within 20 calls of its search"* — 136
   is the `Used` column of the replay's rank table (78 + 12 + 14 + 24 + 8), each a *distinct path a
   search showed* that some call in the window named, so one tool call can account for several and
   one path for one; round 3's second suggested wording was the loose one, and this corrects it.
   Write *of the 136 paths a search showed that a tool call named within 20 calls, 32 had been shown
   only below rank 3*. And item 6 (lines 8952–8954) says the description passes *through the
   existing drift, budget and phrase tests* as if none of them moves: `test_mcp_tool_descriptions.py`
   line 189 keys the §8.3 quote comparison on the opening sentence *Search indexed project documents
   by relevance.*, so a description rewritten whole either keeps that sentence or moves the
   `_QUOTED_DESCRIPTIONS` row with it. One clause either way.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-30

**Summary judgment.** Round 4's five findings are applied as the brief says, and I re-derived each
against the code rather than the summary: the whole/named `end_line` split in the property list is
the one `cut_to_snippet` (search.py lines 206–240) forces, and `chunks.end_line` is a column
`_stored_chunks` can carry; `links._lines` (lines 91–107) stops at `LINK_PREFIX_CHARS`, so item 3's
skip rule is the shared reader's own behaviour and needs no second reader; `_serve` (groups.py
lines 325–355) builds its tally from `search_one`'s return alone today, so item 8's two-field return
is exactly what the counter rule needs; 136 is the rank table's `Used` column; and
`_QUOTED_DESCRIPTIONS` (test_mcp_tool_descriptions.py line 189) keys the §8.3 comparison on the
sentence item 6 names. I also checked what no earlier round had: `groups.search_all` has exactly one
caller in `zikaron/` (`dispatch_knowledge.knowledge_search`, line 282) and the search reminder
(`hook/reminder.py` `_searched`) reads tool *inputs*, never the response, so no internal consumer
meets a named entry where it expects a snippet; and `_capped`'s break at the limit, the no-vector
exclusion, `_missing_cosines` over the kept pool and `Group.order_key` all compose with item 4's
skip-after-every-exclusion exactly as item 10's invariant states, for k + L within and past the
clamp. The brief is buildable without a decision left to the implementer. Two trivial points remain,
and neither changes what ships.

### Findings

1. **[NITPICK] One line of the section exceeds 100 characters.** Build-plan.md line 8924 — *"opening
   with nothing in it is `""`, never absent. **No markdown is parsed** (§1.1: no heading
   extraction): a code-knowledge"* — is about 126 characters; every other line of the section wraps
   at 100, and the handoff says none exceeds it. Rewrap lines 8924–8926. Nothing in the gate reads
   line length, so this is wrapping consistency only.

2. **[NITPICK] Done-when 2 says how the replay sets the constant and not how it sets the key.**
   Lines 9008–9020 run `groups.search_all` at `knowledge_whole_results` 3 and 20. `search_all` reads
   the cutoff from `config` (groups.py lines 458–462); `EffectiveConfig` is constructible only with
   every declared key present (resolution.py lines 52–58), and its one ordinary path is
   `resolve(system_path, project_path)`; the store's own override is `<store>/.zikaron/config.toml`
   (`project_config_path`, lines 247–249) — the very file the scope fence says stage 2's unpaged arm
   sets to 20. One clause settles which the replay does: *the replay resolves a scratch copy of the
   store's `config.toml` with the key set to each cutoff, and never edits the store's own* — so a
   pass at 20 cannot leave the treatment copy at 20 when stage 2's arms are assigned. `resolve`
   takes any path, so this costs the replay two scratch files and nothing else.

VERDICT: APPROVED
