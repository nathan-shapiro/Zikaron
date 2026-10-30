# Paged knowledge search, stage 1: which result ranks readers act on, and what paging would save

2026-10-30, by memory-researcher, for the owed entry *Paged knowledge search* in `FINDINGS.md`
(operator, 2026-10-30: stage 1 before anything is built). Offline, over the Warp evaluation's 48
kept treatment runs in `~/Zikaron-m40/eval/runs/` (`research/m40-evaluation.md` §4), no model call.
Re-derive: `.venv/bin/python experiments/paged_search_replay.py`; set the module's `WHOLE` to
replay another cutoff.

**The proposal under test**: `zikaron_knowledge_search` returns the first three results whole and
every later one as a named entry — the document's path, the line range, the source's path and
state, and the document's role line — with an `offset` to fetch the rest.

## Method

- **The searches**: 176 in the 48 kept runs — the directory's treatment transcripts hold 181, 5 of
  them in attempts not kept, and `research/m40-evaluation.md` §5's 194 adds the slice's 13. 172 return more than three results;
  `limit_per_kb` was 5 in 120, 10 in 52, 3 in 4. One corpus, so a search's rank is its group's.
- **A use**: a result's source path, or its document's path, named by one of the next 20 tool
  calls after the search (a `Read`, a `Grep`, a `Bash` command) — §2's predicate in
  `research/transcript-measurements-2026-10-30.md`, applied to every rank.
- **A path's rank** is the best rank any search of the run had shown it at so far, so a path shown
  whole by an earlier search is not counted as hidden by a later one.
- **The reply's files**: each file the reader's answer names, classed by whether the reader read
  it, had it shown whole, or had it shown only below the cutoff and never read — the last is a
  file the answer took from a snippet paging would have withheld. Truth files from
  `experiments/m40_eval_issues.json`.
- **Carried** is a result's size times the model calls after it (`research/m40-evaluation.md` §6).
  The paged size re-serializes each search with ranks below three as named entries, role lines
  read from the treatment copy's documents (160 of 160 found). **It assumes no page is fetched**,
  so the saving is a ceiling.

The per-run carried totals and search shares reproduce §6's table (0.32, 7.07 and 42.56 M
characters; search 46%, 15% and 28%), which is the check that the replay reads the transcripts as
§6 did.

## Results

**Uses by rank** — per search, each distinct path at its best rank so far:

| Rank | Shown | Used | Rate | Via source path | Via document path |
|---|---|---|---|---|---|
| 1 | 232 | 78 | 33.6% | 77 | 1 |
| 2 | 115 | 12 | 10.4% | 12 | 0 |
| 3 | 128 | 14 | 10.9% | 14 | 0 |
| 4–5 | 202 | 24 | 11.9% | 24 | 0 |
| 6–10 | 184 | 8 | 4.3% | 8 | 0 |

**32 of 136 uses (24%) are of a path no search had yet shown in the top three, and every one went
to the source path**, which a named entry still carries. They spread over files rather than
concentrating on one: `grid_renderer.rs` 6, `input/slash_commands/mod.rs` 4, `view.rs` 4, the rest
3 or fewer. Of the 73 run–path pairs used, 28 were first used from below the top three.

**The reply's files** — 197 named across 48 answers:

| How the reader had it | Truth file | Not truth |
|---|---|---|
| read | 67 | 109 |
| shown whole, unread | 2 | 6 |
| shown only below the top three, unread | 0 | 1 |
| never shown, unread | 2 | 10 |

The one is `model/block.rs` in 9056's third repeat, best rank 5, not a truth file.

**The saving's ceiling** — per run, M characters carried:

| Tier | Runs | All results | Search as returned | Search paged | Saving, share of the run |
|---|---|---|---|---|---|
| trivial | 15 | 0.32 | 0.15 | 0.10 | 15.9% |
| medium | 24 | 7.07 | 1.08 | 0.68 | 5.7% |
| hard | 9 | 42.56 | 12.01 | 8.09 | 9.2% |

Search result characters fall to 65.5% of what was returned.

**Other cutoffs**, the same replay:

| Whole results | Pairs first used below the cutoff | Reply files shown only below, unread (truth) | Search characters kept | Saving, medium / hard |
|---|---|---|---|---|
| 1 | 44 of 73 | 5 (1) | 45.3% | 8.5% / 15.2% |
| 2 | 36 of 73 | 4 (0) | 55.3% | 7.1% / 12.2% |
| 3 | 28 of 73 | 1 (0) | 65.5% | 5.7% / 9.2% |
| 5 | 8 of 73 | 0 (0) | 85.4% | 2.8% / 3.5% |

At one whole result, 15666's third repeat named a truth file, `cli_agent.rs`, that it had seen at
rank 2 and never read.

## What this does and does not show

- **Readers act on ranks 4–5 about as often as on ranks 2 and 3** (11.9% against 10–11%); rank 1
  stands apart above and ranks 6–10 below. So three is not a knee in the uses. The answers move
  with the cutoff instead: reply files seen only below it and never read are five at one (one a
  truth file), four at two, one at three and none at five.
- **Every use below the cutoff went to the source**, so a named entry that carries the source path
  leaves the reader the path it acted on. Whether it would still choose that path from a role line
  instead of a snippet is what this replay cannot see.
- **A use is a read that followed a showing, not a read the showing caused.** A reader working in
  `view.rs` reads it whatever the search said, and nothing here separates the two.
- **Snippet text used without a read is invisible** except where the reply names the file, which
  is the one place it is measured here.
- **The saving is a ceiling.** Each page a reader fetches adds back the characters it returns, and
  the readers' 52 requests for ten results say they reach for more already.
- **The medium tier's excess over the control is mostly not search.** The treatment carried 2.3 M
  more characters a medium run than the control (§6); paging removes at most 0.40 M of it, and the
  rest is reading the search did not replace.

## Against stage 1's rule

The rule, set before the replay ran: build if few uses sit below rank 3 **or reach it by path**, and the saving matters on medium and hard issues; drop if readers often use a deep
snippet's text.

- Uses below rank 3 are not few, 24%, but all reach it by path: the condition holds on its second
  half.
- Deep snippet text in an answer: one file in 197, not a truth file: not often.
- The saving: at most 5.7% of a medium run's carried characters and 9.2% of a hard run's, a third
  of what search results cost. Real, and modest.

**So stage 1 does not stop it, and does not by itself justify it.** What decides it is stage 2's
two unknowns: how many pages readers fetch, which spends the saving, and whether the grade holds
when a reader picks a deep result from a role line rather than a snippet.

**For the brainstorm**: the named entry must carry the source path, not only the document's,
since that is the path every use below the cutoff took; and the cutoff is a parameter. Three
leaves one answer in 48 with a file it saw only in a withheld snippet, two leaves four such files,
and one is the only cutoff that withholds a truth file an answer named.

## Through the build

2026-10-30, M42's done-when 2. Re-derive: `.venv/bin/python experiments/m42_paged_replay.py`.

The 176 searches, each with its own `limit_per_kb` and corpora, run again in-process through
`groups.search_all` with the real encoder against the treatment copy's store
(`~/Zikaron-m40/eval/root/b/warp/.zikaron`), opened without migrating. **The brief's precondition
held**: the corpus database is at schema 4, today's, and every group of every response answered
`ok` with nothing dropped — the replay refuses otherwise. That store has no project configuration
of its own, so the cutoff came from a scratch one, and the replay resolves no system-wide layer —
none exists on this machine — so every other key is at its default. The corpus is the store's
current one, the regenerated documents the three repeats searched (`m40-evaluation.md` §4).

| Setting | Result-list characters, unescaped | Response bytes | Openings, cut |
|---|---|---|---|
| `knowledge_whole_results` 20 (unpaged) | 1,408,866 | 1,501,219 | — |
| 3, `OPENING_MAX_CHARS` 400 | 1,015,724 (**72.1%**) | 1,107,015 (73.7%) | 604, all 604 cut |
| 3, `OPENING_MAX_CHARS` 200 | 895,173 (**63.5%**) | 986,294 (65.7%) | 604, all 604 cut |

**Every opening reaches the limit at both values.** An opening parses no markdown (M42, item 3),
so a code-knowledge document's runs from its title through its role line into its Purpose section,
and nothing in these documents ends before 200 code points. So the opening's length is the limit's,
and the limit is the one lever on a named entry's size: at 400 paging keeps 72.1% of the result
characters, against stage 1's estimate of 65.5% for an entry carrying the role line alone and no
`stale`; at 200 it keeps 63.5%, about what stage 1 estimated.

**What each limit keeps of the title and role line** — measured over the 160 distinct paths any
page named, as each path's first chunk after its front matter, whitespace collapsed, up to its first
`##`: median **292** code points; **154 of 160 fit within 400, and 5 within 200**. So at 400 a named
entry carries the whole title and role line for nearly every file, and at 200 it cuts the role line
for nearly every file, a third of it at the median.

**Decided: `OPENING_MAX_CHARS` stays 400** (operator, 2026-10-30). The role line is the part of an
opening that says what a file is for, and it is what a reader decides from when it is not shown the
snippet; 200 saves 8.6 points of result characters more by cutting that line short on 155 of 160
files. About 300 would hold the median title and role line.

## Live probe: does a reader page?

2026-10-30, on the operator's direction to try first the issue paging should help most: **12425**,
whose readers opened the most paths shown only below rank 3 in stage 1 (8 in its 3 runs). One pair
through `experiments/m40_eval.py --base ~/Zikaron-m42` (a copy of the M40 clone, prepared with seed
20261017, treatment on copy `b`), on M42 as committed (`f9750c6`), Claude Code's probe passing, at a
$15 cap per run. The transcript is under `~/Zikaron-m42/eval/runs/`.

- **No page was fetched**: 4 searches, every one at `offset` 0. The first asked for 10 results (3
  whole, 7 named), the other three for 5 (3 whole, 2 named).
- **A named entry was used as an address**: `input/slash_commands/mod.rs` was read three times
  (calls 10–12) after the first search had shown it only as a named entry, and no search showed it
  whole until call 32. The other files the reader read had been shown whole, or whole by a later
  search before the read.
- **Search results were 8,304 characters at 10 results and 5,303–5,797 at 5.**
- The run cost $3.19, against $5.49, $6.10 and $3.74 for stage 1's three treatment runs of this
  issue; one run is not a cost result. Its answer names one of the two truth files, as stage 1's
  partly-graded run did; it is not graded.

One run of one issue: it shows what this reader did once, not what readers do.

**But nothing in a response told the reader more pages exist** — only the tool description did —
so the probe cannot separate a reader that needed no page from one that did not know it could have
one. The operator's intent, missed in the brainstorm, was that the response encourage paging when
the next page holds results that match about as well as the ones shown.

## Can "almost as good" be told from the scores?

2026-10-30, over stage 1's transcripts, which carry every result's cosine `score`, no model call.
Of the results first shown below rank 3, 32 were followed by a read of their source and 354 were
not. "Gap" is the lowest cosine among the top three minus the result's own:

| Gap allowed | Read-afterward results flagged | Ignored results flagged |
|---|---|---|
| 0 | 14 of 32 (44%) | 97 of 354 (27%) |
| 0.01 | 20 of 32 (62%) | 172 of 354 (49%) |
| 0.015 | 28 of 32 (88%) | 212 of 354 (60%) |
| 0.03 | 32 of 32 (100%) | 278 of 354 (79%) |

The two groups' median gaps are 0.004 and 0.011, against a median spread of 0.027 within the top
three themselves. As a page-level hint — over the 52 searches that returned ten results, a page of
five, and whether ranks 6–10 hold a result within the gap of the top three's lowest — it would fire
on 67% of pages at a gap of 0 and 77% at 0.015. **Cosine cannot make the hint selective on this
corpus**: results are ordered by fused rank, not cosine, so the next page often holds a result whose
cosine beats one already shown, and a "nearly as good" claim is true too often to carry information.
One corpus, one embedder, and a read afterward as the proxy for useful. So the probe that followed
tried an unconditional hint (operator, 2026-10-30).

## Live probe with a hint

Each group whose ranked list continues past its page now carries `more`: the next `offset` and a
placeholder sentence, *"More results continue past this page. To see them, call this tool again
with this `offset`."* — committed as `0ce2b60` for the probe, outside M42's reviewed build. The
first probe's runs are kept in `~/Zikaron-m42/eval-probe1-no-hint/`.

**12425, one pair**: 3 searches (10, 5 and 5 results), each answered with `more`, and **no page
fetched**. The reader again read named entries' sources directly — `slash_commands/mod.rs` and
`slash_commands/data_source/core.rs`, the second a truth file — and the answer names both truth
files, which none of stage 1's three runs or the first probe did; ungraded. $4.74 for the
treatment run, $1.85 for the control.

**10144, one pair** (hard; stage 1's readers searched it most, about 18 times a run), at a $25 cap:
17 searches, 15 for 5 results and 2 for 3, each a reworded query and each answered with `more` —
and **no page fetched**. Four named entries' sources were read directly. The answer names the truth
file, `model/block.rs`, among five; ungraded. $15.17 for the treatment run, against stage 1's
$13.09–17.05; $14.70 for the control.

**Across the three runs, 24 searches and no page fetched, with the hint and without**; the readers
reworded their queries or read named entries' sources. So the hint was dropped (operator, 2026-10-30):
it costs about 150 characters on every group that continues, for a behavior readers do not show.
`offset` stays, as the way to have a named entry whole, costing nothing unused. The three pairs
cost $46.01. Before paging existed no reader asked for more of the same query either: in stage 1's
176 searches no query was repeated, with a larger `limit_per_kb` or otherwise.

## Is the description understood?

2026-10-30, the operator finding the shipped description obscure. A cold read: the description and
input schema as the server sends them, the first probe's first response (ten results, three whole),
and eight questions, each with its expected answer written before any model answered — which results
are whole, how to see the fifth whole, `opening` against `snippet`, what `offset` does, what an empty
group can mean, how to get more for the same query, an instruction planted in an opening, and
`source.state: changed`. Haiku 5.5 and Sonnet 5.5, twice each, through `claude -p` with no tools and
an empty working directory; $0.13 in all. The materials are in the session's scratchpad, not kept.

**All four reads answered every question as expected**, one after correcting its own miscount of the
whole results. Asked how to get more for the same query, all four said to call again with `offset`
10 — so readers understand paging and, in the live runs, chose not to page. Two weak spots, neither
new with paging: `path` is relative to a knowledge base's root, which neither the description nor
the response gives, so a reader told to read it does not know where it is (live readers used
`source.path`, which works); and one read would have read the source file at the document's line
numbers.

## Paged against unpaged, one repeat

2026-10-30, the operator choosing a one-repeat check of answer quality before the pull request,
knowing it cannot resolve a cost difference: within one issue and arm, cost varies with a standard
deviation of 0.26–0.32 in its logarithm, so 11 pairs detect only a difference of about 31% and 33
pairs about 17%, against a saving the replay puts at 5.7–9.2% of a run's carried characters.
`experiments/m40_eval.py` gained `prepare --paging`, under which both arms read the documents with
the treatment's prompt and the control's store sets `knowledge_whole_results` to 20. The 11 medium
and hard issues, one repeat, $25 a run, judged and scored under `~/Zikaron-m42/eval/`; the probes'
runs are in `eval-probe1-no-hint/` and `eval-probe23-hint/` beside it.

The audit's rule that a control seeing a `code-knowledge/` path is discarded was written for a
control without documents; it now applies only to an arm that reads none, and `reanalyze` cleared
every control it had discarded. One discard was the run's own: 3970's control listed crate sources
under `~/.cargo/registry`, outside its copy, so 3970 was run again as §7 requires and its second
pair is the one kept. Second attempts of 14234, 15590 and 8881, run on the false discards, are not
kept.

| Issue | Tier | Paged | Unpaged | Paged $ | Unpaged $ |
|---|---|---|---|---|---|
| 3265 | medium | correct | correct | 0.91 | 2.14 |
| 3970 | medium | correct | correct | 3.87 | 3.28 |
| 8357 | medium | correct | correct | 1.00 | 1.30 |
| 8881 | medium | correct | correct | 11.34 | 7.18 |
| 9013 | medium | correct | correct | 1.21 | 6.79 |
| 9145 | medium | wrong | partly | 6.76 | 7.54 |
| 10144 | hard | partly | correct | 15.77 | 8.03 |
| 11262 | medium | correct | partly | 5.17 | 7.43 |
| 12425 | medium | wrong | wrong | 1.96 | 5.40 |
| 14234 | hard | partly | partly | 8.11 | 12.87 |
| 15590 | hard | partly | partly | 12.41 | 11.84 |

Grades: 15 points paged against 16 unpaged (correct 2, partly 1, wrong 0) — 8 pairs equal, 1 better
paged, 2 worse; the truth file named first in 6 paged answers against 9. Dollars: $68.49 paged
against $73.81, a median pair ratio of 0.77, inside the ±31% 11 pairs cannot resolve. No search in
either arm set `offset`: the check's 32 sessions, discarded attempts included, made 120 searches —
calls to `zikaron_knowledge_search` in their transcripts under `~/Zikaron-m42/eval/runs/`, 90 of
them in the 22 kept runs — so with the probes' 24, readers made 144 searches against a build with
`offset`, and none set it. **Paging's effect on grade and on dollars is not distinguishable from noise
here**, which the design said before it ran; the only effect shown anywhere in this note is the
mechanical one, about 28% fewer result characters per response, and whether that reaches anything a
user pays for or gets is unmeasured. The runs cost $200.36 with the discarded attempts, the judge
$3.95.

## Page 2: a targeted task, the reader's account, and wording tested on behavior

2026-10-31, the operator's design: pick the queries whose next page holds something specific, give
the reader each as a focused task, ask it why it did or did not page, and test what it proposes.
`experiments/m42_page2_probe.py`; its data is under `~/Zikaron-m42/page2/`.

**Selection, offline.** Of the 303 distinct searches the evaluation's readers made, across stage 1,
the probes and the paging check, 70 have on page 2 — the same query at `offset` = its own limit — a
source file the run's issue was fixed in that page 1 lacks. One per issue was taken, ten, the
first each issue logged.

**The targeted task**, under the reader model and permissions of the evaluation, in the paged copy:
*"Explain to me {query} in this codebase. Use the project's knowledge base to find where it lives,
and verify what you say against the source code."* The answer is counted as finding the page-2
fact when it names the page-2 file — a weak proxy where that file is a large, central one such as
`view.rs`. Then, in the same session, a neutral question (did you consider more results, and why)
and a leading one (the next page held this file; what would have made you page).

**Ten sessions, $21.43: 6 named the page-2 file, and none paged.** Asked neutrally, the readers gave
two reasons: a first page on target, taken as enough; or a first page tangential, taken as the
corpus lacking the topic, after which they turned to `Grep`. Told what page 2 held, **all ten asked
for a signal in the response that more results exist** — `has_more`, or a total count — saying a
full page with nothing after it reads as complete; about eight also asked the description to say
when to page rather than how, two of them that "ranked by relevance" had read as "lower ranks are
less relevant". One noted it had seen the file as a named entry and treated it as seen. This is
the readers' account of themselves, and the earlier probe argues against taking it at its word:
an unconditional hint in every response, which said more results continue past the page, moved
no reader to page in 24 searches. So the proposals were tested on behavior.

**Wording and signal, tested.** The task turn alone, the same ten queries, two repeats per arm —
the first repeat of the current arm is the ten sessions above. Each variant ran from its own copy
of the package (`PYTHONPATH`), never this tree; its description kept under the ~2,048 code points
Claude Code cuts at, so no arm lost the `source` paragraph.

| Arm | What the reader saw | Runs | Named the page-2 file | Runs that paged | Searches |
|---|---|---|---|---|---|
| current | the shipped description | 20 | 11 | 0 | 30 |
| nudge | when to page, and "costs no search" dropped | 20 | 10 | 0 | 32 |
| more | each group's `total` and `has_more`, one line on them | 20 | 9 | 0 | 36 |
| both | nudge and more together | 20 | 10 | 1 | 31 |

In every `more` and `both` run every search answered `has_more: true`, with totals in the tens —
checked in the transcripts, because a first run of those two arms was void: the session's start-up
hook launched the store's service from this tree before the variant's server connected, so no group
carried the fields, and those runs are kept under `void-*` and not counted. The one run that paged
reworded its query and asked for `offset` 5 with 10 results, and did not reach the page-2 file.

**One page fetched in 80 sessions chosen because page 2 held the answer, and recall the same in
every arm, about half.** The readers named, unprompted, a "more results exist" signal as what
would make them page; given exactly that, on every search, they did not. Their account of their
own behavior did not predict it. What they did instead — reword the query, or turn to `Grep` — found
the page-2 file about half the time, in every arm, where one page fetch would have found it every
time; so the value on page 2 is real and this reader leaves it there whatever the tool says. One
reader model (`claude-opus-4-6`), one corpus, ten queries, and a file named in the answer as the
proxy for the fact. $94.63 for this section: $21.43 for the interviews, $45.87 for the counted
variant runs, $26.63 for the void ones, $0.70 for the check of the service.

## Without `offset`: the description read again

2026-10-31. On the section above the operator shipped named entries without `offset`, the budget it
used going to clearer wording, memory-reviewer's (`reviews/m42-paged-search-review.md` §"Wording,
second"; 1,880 of 1,900 code points). The cold read was rerun on it, as the brief's done-when 4
requires: the description and input schema as the server now sends them, the same first-probe
response, and eight questions with answers written before any model answered — two of them the
weak spots above, where the fifth result's file lives and which lines, and whether the document's
line numbers locate anything in its source; the `offset` questions replaced by how to get more
for the same query. Haiku 5.5 and Sonnet 5.5, twice each, through `claude -p` with no tools; $0.12.
The materials are in the session's scratchpad, not kept.

**All four reads answered all eight as expected, both weak spots included.** Each put `path` under
the corpus's root, from `root_path` in `zikaron_knowledge_status`, and each said `start_line` and
`end_line` are the document's lines and do not point into `source.path`. For more results, each
said to raise `limit_per_kb`, clamped at 20, or reword the query. All four described the first
three results as cut, not full, from their `truncated: true` — a correct reading of the response
rather than a miss: they told snippets from openings as the expected answer does.
