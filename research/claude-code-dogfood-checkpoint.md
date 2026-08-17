# Claude Code dogfooding checkpoint — measured, 2026-08-16

**Every clock time in this note is UTC**, which is why they read `2026-08-17T01:28` while the working
day was 2026-08-16 local. A reader diffing this note against commit dates should not conclude one of
them is wrong.

M16's evidence. A throwaway project at `~/zk-dogfood`, a **memory-naive** agent, and an operator who
gave **no memory nudges at any point** — the condition the pre-migration recall numbers never had.

**Arrangement.** `python -m zikaron.install --project ~/zk-dogfood --harness claude-code` into an
empty directory, then `claude --agent zikaron-dogfood` as a **top-level** session. The agent
definition is tracked at `experiments/dogfood/zikaron-dogfood.md`; its prompt says nothing about
memory on purpose, so the only guidance it ever received is the shipped write policy.

**Why not this repository.** The kiro arrangement put hooks inside `zikaron-dogfood.json`, which is
what made dogfooding a *controlled* experiment. Claude Code's settings are directory-scoped, so
installing here would have wired the crew — including a researcher agent whose own prompt is
saturated with memory instructions — and destroyed the control. `FINDINGS-archive.md` flagged this
before the port and it was still open.

**Evidence, all of it, in `~/zikaron-m16-evidence/`:** `store.db`, both session transcripts, and the
consolidator's subagent transcript — four files, no others. Deliberately not `/tmp`, which is where
the previous consolidation A/B's snapshots were left. **Frozen**: the store is out of WAL mode
(`journal_mode=delete`, no `-wal`/`-shm` sidecars) and every file is read-only, so the directory
cannot acquire the very defect described below while sitting there being cited.

**Two lessons about preserving that evidence, both learned the hard way *in* this checkpoint.**

*A `cp` of a SQLite store in WAL mode silently truncates it.* The first snapshot taken here held **27
events and 2 memories** against the live store's **38 and 4** — session 2's entire contribution was
missing, because `memory.db` was copied without its 4 MB uncheckpointed `-wal`, and the copy opens
cleanly and answers queries, so nothing announces the loss. It was caught only because a review
finding forced a recount against the live store. Use `sqlite3.Connection.backup()` or `VACUUM INTO`,
which are consistent by construction. (The two older `/tmp` snapshots were checked for the same
defect and are **intact** — 31/0 and 29/15 — so no earlier conclusion rests on a truncated copy.)

*Transcripts are the other half of the evidence and they expire.* Claude Code prunes
`~/.claude/projects/` on `cleanupPeriodDays`, default ~30. This machine happens to set 3650, but that
is machine-local, not a property of the harness — so the transcripts are copied above rather than
cited in place.

---

## 1. There are three approval gates, not two

The installer's own output names two — `enabledMcpjsonServers` for whether a project-scoped
`.mcp.json` server **loads**, and `permissions.allow` for whether each tool **call** prompts. Both
were *documented, unmeasured*: a headless run approves everything (`claude-code-installer-probe.md`
§8).

Measured interactively, in order:

| Gate | What fired | Verdict |
|---|---|---|
| 1. Folder trust | Claude Code's first-entry dialog, **which reads `permissions.allow` and surfaces it as a warning** | new — not in the corpus |
| 2. MCP load | nothing | `enabledMcpjsonServers` works |
| 3. Per-call | nothing, across **6 writes and 8 reads** (4 `remember`, 2 `amend`; 5 `search`, 3 `fetch`) | `permissions.allow` works |

Gate 1's text: *"⚠ This folder pre-approves 2 tool permissions in `.claude/settings.local.json`:
`mcp__zikaron` and `mcp__zikaron-consolidator`. These will apply without asking. Only proceed if you
trust this configuration."*

**So installing Zikaron makes a folder look less trustworthy on first entry.** The default trade —
trust the tools, because per-write prompts push against the write policy and D30 says under-writing
already dominates — is still right, but its cost was never named.

**Inferred, not measured — and its converse is the more consequential half.** Gate 1 is a first-entry
dialog, so it presumably does not fire in an already-trusted directory; that inference is a second
reason the throwaway was the right vehicle. But if it holds, then **installing Zikaron into an
already-trusted directory pre-approves two tool servers with no warning shown to anyone, ever** — the
trust dialog is the only disclosure point in the whole flow, and it is skipped precisely where installs
will normally happen, in a developer's own existing projects. Worth measuring, and worth weighing
against `--no-trust-tools` before calling the default settled.

## 2. MCP tools arrive **deferred**, and the policy's name substitution is what saves discovery

`/mcp` showed both servers `✔ connected`, with **5 tools** on `zikaron` and **4** on
`zikaron-consolidator` — D32's split, live, from the installed config.

But the tools were **not in the agent's initial tool list**. Its first action of the session was:

```
ToolSearch {"query": "select:mcp__zikaron__zikaron_search,mcp__zikaron__zikaron_fetch,mcp__zikaron__zikaron_remember"}
```

It had to load their schemas *by exact name* before it could call anything. It knew the names because
the injected write policy names them, and it got them **right** because `install/entries.py` rewrites
bare `zikaron_search` to `mcp__zikaron__zikaron_search` per harness. That substitution was built so
the spawn instruction would be correct; it turns out to be load-bearing for **tool discovery**. Had
the policy carried bare names, the `select:` would **likely** have missed and the agent would have
concluded there were no memory tools — silently. *Likely* rather than *would*: `ToolSearch`'s matching
behaviour on a bare `zikaron_search` (exact versus substring or fuzzy) was never probed, and one
headless turn would settle it. The mechanism is credited here on the observed call, not on its
counterfactual.

**This is a better explanation for `installer-probe` §9's n=1 observation** that both servers were
*"still connecting"* and could not be named. A model cannot name tools that are not in its context.
Neither reading is refuted (n=1 each, different conditions), but connection state was *inferred from*
the naming failure, and deferral explains the naming failure directly. Under interactive conditions
the servers were connected and named on demand. **Name the assumption this rests on**: deferral was
observed *interactively*, and the competing explanation requires it to hold under headless `claude -p`
too, which was not observed. That single assumption is the whole load the alternative carries.

## 3. The injection budget counts **UTF-16 code units** — measured, not assumed

`harness.md` reserved this experiment for M16: the ASCII bisection could not separate the candidate
units, and `漢` is a BMP character, so it is one code point *and* one UTF-16 unit. An **astral**
character separates all three at once. Probe: a `UserPromptSubmit` hook emitting *N* × U+1F9FF
between markers, loaded through `claude -p --settings`.

| Content | code points | UTF-16 units | UTF-8 bytes | Result |
|---|---|---|---|---|
| ASCII (M13) | 9,503 | 9,503 | 9,503 | intact |
| ASCII (M13) | 10,502 | 10,502 | 10,502 | truncated |
| `漢` (M13) | 9,016 | 9,016 | 27,016 | intact |
| **U+1F9FF** | **6,000** | **12,000** | **24,000** | **truncated** |
| **U+1F9FF** | **4,600** | **9,200** | **18,400** | **intact** |


**What each row counts, because the rows do not agree and the corpus's own rule is to say so.**
The astral rows are **content only** — 6,000 and 4,600 characters exactly, hence the exact
multiples of 2 and 4. The `漢` row is quoted as M13 reported it, and 9,016 code points of pure
`漢` would be 27,048 UTF-8 bytes rather than 27,016, so that row evidently counts ~9,000 `漢`
**plus its marker characters**. No conclusion moves — every margin here is in the hundreds or
thousands of units and the discrepancy is 32 bytes — but a table whose rows measure different
things should say which.

- **Bytes: refuted.** 27,016 B and 18,400 B arrive intact while 10,502 B truncates.
- **Code points: refuted.** 6,000 code points truncates.
- **UTF-16 code units: survives all five.** Cap ∈ **[9,503, 10,502)** — intact at 9,503 puts the cap
  at or above it, truncated at 10,502 puts it strictly below. 10,000 sits inside.

`HarnessSpec.exceeds_injection_budget` already counts UTF-16 units, chosen in M14 as the conservative
reading that upper-bounds every candidate. It is now the **measured** reading rather than a hedge, and
M14's `GIST_MAX_CHARACTERS = 1024` and the five-row-block arithmetic stand on measurement.

## 4. Session 1 — recall fired on the occasion the policy names

Session `2ec96274`. Task: *"write a script which takes two directories as input and tells me how
they're different."* Nothing about memory, ever.

Its first thinking block, **before any tool call**:

> *"Since I'm about to **propose a script design**, it's worth doing a quick memory search for
> relevant conventions…"*

That is occasion (b) of the four added to the policy on 2026-08-14 — *"you are about to propose a
design, mechanism or plan."* Zero nudging, turn 1, and it **named the trigger in its own reasoning
before acting on it**. Two searches followed, 26 ms apart, both empty against an empty store; it
adapted rather than stalling.

**The proposal gate fired, twice, unprompted**, in user-facing text: *"I searched project memory for
shell-script conventions and for directory-comparison work, both returned nothing"* and later *"Only
my own gist from last turn came back."* That gate was added on operator decision over the
researcher's objection. **Fired as designed, twice, unprompted** — deliberately not "it earns its
sentence", because the keep-or-wind-down decision has its own named criterion (searches per turn rising
while the share followed by a `fetch` falls below 32%) and two firings do not settle it.

**What it chose to record**, explicitly triaged:

- *"the correct project directory path seems like a **minor, transient mistake** rather than
  something worth persisting"* — rejected
- *"The `[[ -f ]]` symlink gotcha is general tool knowledge, **not project-specific**, so I'll skip
  that too"* — rejected (**see §9.1 — this is the wrong test**)
- *"the design decision … **isn't obvious from the code alone**, so that's worth recording"* —
  accepted
- *"I'll write the gist as a single sentence **around 20-25 words, leading with the symptom**"* — the
  policy's own phrasing, quoted back

## 5. The repair loop, triggered by a reframing

Prompt 2 changed the constraint: BSD boxes, no bash. The push hook surfaced the record the agent had
written 90 seconds earlier, and its first user-facing line was:

> *"Good — that reframes things significantly, and **it collides with what I recorded last turn**."*

Then, before trusting either the memory or itself:

> *"The key constraint I need to verify is whether POSIX shell variables can actually hold NUL bytes
> — **I should test this directly rather than rely on memory**."*

It measured (`dash -c 'v=$(printf "a\0b"); echo ${#v}'` → 2), **fetched** (the read receipt D26
requires), then **amended** with `version: 1`. The amended content keeps the GNU approach labelled
*"the rejected alternative"* — this corpus's own withdraw-in-place discipline, reached independently.

**D11 staleness repair, D26 optimistic concurrency and D6's amend-if-read-first branch all fired
correctly, in one sequence, unprompted.**

## 6. A mild heads-up became a durable preference record

Prompt 3 was a passing remark — *"I also wanted to give a heads-up that all scripts you write should
by default be compatible with both Linux and BSD systems"* — with no instruction to remember. 26
seconds later it wrote a second record.

Three mechanisms fired:

- **D30's prohibition on instruction-shaped memories.** *"I should phrase it as an observation about
  settled preference rather than a directive to future agents … **attributing the fact rather than
  issuing an order**."* First time that prohibition has been watched binding.
- **D15's write-time dedup, resolved against the offer.** `remember` returned the dirdiff record at
  **cosine 0.876**; the agent kept both, because *"one is a general project-wide convention while the
  other is the specific design record … they complement rather than overlap."* This is the **eighth**
  dedup offer in the corpus and the eighth judged a false positive — and at 0.876 it is the highest
  cosine among them. **Session 2 produced a ninth**, unmentioned in an earlier draft though its count
  sat in §10's table: the new `stat`/mtime portability record against the same dirdiff record, cosine
  **0.8246**, also kept separate. So the series is **9 offers, 9 false positives, 0.80–0.876**, and
  "highest" is now asserted against a complete series rather than a truncated one.
- **It read the untrusted-reference framing and drew the right conclusion** — see §9.3.

## 7. Consolidation — the skill path, and a split with a concordant second judgment

First exercise of the shipped skill under Claude Code (`harness.md` had it *documented, unmeasured*).

- Spawned `zikaron-consolidator`, `spawnDepth: 1`, prompt from the skill body.
- Called only `zikaron_next_group` and `zikaron_promote`. **No `search`, no `fetch`** — D32's
  enforcing half is mechanical here as under kiro.
- **Model:** frontmatter `model: sonnet` (the alias); the harness's own subagent transcript records
  `claude-sonnet-5` ×8. This measures `harness.md`'s escape hatch **true** — the concrete id behind
  the alias is recoverable from disk, so no schema column is needed. Read from the harness's record,
  not from a model's self-report, which the design rejects as a provenance source.
- **Outcome:** one group of two members (grouping found them adjacent at 0.876); the consolidator
  **split** them, promoting both in place. Gists byte-identical; no index-shaped gist manufactured.

Its reasoning: *"different scopes even though related … following the principle of **preferring sharp
distinct records over one combined summary**"* — the 2026-08-04 prompt change quoted back.

**This is the first split verdict in the corpus with a concordant second judgment**: the writing agent
rejected the same pair as a dedup offer, and the consolidator reached the same verdict with the same
reasoning, on a pair retrieval called adjacent. Both previous runs had nothing at all to score against.

**Concordance is not independence, and neither is ground truth.** An earlier draft of this section said
"independent ground truth" and that was wrong on both words. The writing agent runs `opus` and the
consolidator `sonnet` — **the same model family**, so a shared blind spot is plausible rather than
excluded. And both prompts were revised **in the same anti-merge direction on 2026-08-04**; the
consolidator quoted its half back verbatim, as recorded above. So this is two correlated judgments
agreeing, not two votes. **No human ever labelled this pair**, which is what ground truth would mean.

**Caveat, stated:** this is the **second consecutive zero-merge outcome** (`~/Memory` run 2: 0 of 31;
here 0 of 2 — run 1's 11 merges preceded the prompt change). Refusing was correct here, so the result
is consistent with both *"correctly refuses bad merges"* and *"refuses every merge."* It does not break
that tie. FINDINGS priority 1 still needs a journal containing a genuine repeat.

### Two runs per skill invocation is normal, and the store makes it look like a double takeover

The store shows runs `3123f762` (1 group) and `aa03e70c` (0 groups) seconds apart, **same pid**, which
reads as a violation of `_PlanBridge`'s "at most one successful `plan_groups` per client process."
It is not. `serving.next_group` calls `planning.plan_within_transaction` when `runs.stored_active`
returns `None`, and `serving.py` says why: *"this path never displaces a live worker, and that
asymmetry with `plan_groups` is the point."* The bridge fired exactly once. Recorded because chasing
it cost six tool calls.

## 7b. The write policy reaches subagents, and is correctly withheld from the consolidator

M16's brief names this done-when: *"a subagent is observed to have actually **received** the write
policy, rather than only our side being observed to emit it."* An earlier draft of this note simply did
not mention it, which against a named clause reads as "done" to anyone skimming. Both halves, stated:

- **Received: closed early, in M15, and not re-run here.** `research/claude-code-installer-probe.md` §9
  drove a headless `claude -p` in a freshly-installed throwaway and asked a canary subagent to report
  any memory-related instruction it had been given beyond its own prompt. It returned the shipped
  policy **verbatim**, and summarised the rest of the block correctly. That is receipt, from the
  *installed* config, through `SubagentStart`'s `additionalContext`.
- **Withheld: verified here, free, from a transcript already open for the model id.** `harness.md`
  §Subagents requires the policy on `SubagentStart` for every `agent_type` **except**
  `zikaron-consolidator`, whose policy is its own system prompt. Counting the policy's opening line —
  the greppable literal is `memory store holding **tribal knowledge**`, markdown emphasis included —
  across the frozen transcripts: **2 occurrences in each main session** and **0 in the consolidator's
  subagent transcript**. The suppression is real, not merely specified.

  **And the two occurrences are the interesting part**, because they sit in *different fields of one
  JSONL record*: one in `stdout` and one in `content`. The transcript separately records what our
  hook **emitted** and what the model **received** — which is exactly the emit-versus-receive
  distinction the done-when clause draws, available for free in the harness's own log.

  *Counted twice, wrongly, first.* An earlier revision of this section reported "1", because
  `grep -c` counts **lines** and JSONL puts both occurrences on one line; and it quoted the phrase
  without its markdown emphasis, which matches nothing at all. Recorded because the load-bearing
  half — 0 in the consolidator's — survived every phrasing, so the error was invisible to the
  conclusion and only a recount against the file could find it.

The consolidator is the only subagent this checkpoint spawned, so it could never have satisfied the
first half — it is the one subagent that must *not* receive the policy. Worth saying plainly, because
"a subagent ran and the policy was not in it" is the correct outcome here and the wrong one anywhere
else.

## 8. Session 2 — cross-session recall, carried by **push**

Session `998d776e`, restarted, no conversational memory. Task: *"a shell script which finds
recursively top N most recently modified files"* — nothing about shells, portability or BSD.

The hook surfaced both records at 01:54:29 (ranks 1 and 2). The agent's first thought, **four seconds
before it called any tool**:

> *"I need a shell script … **keeping it POSIX-compliant for Linux and BSD portability**. **I recall**
> dirdiff.sh handles filenames with newlines by refusing them…"*

**The convention arrived by push, at zero tool cost, and the agent treated the injected gist as its
own recall.** It then pulled — `search`, then `fetch` on both uuids — for the substitution table.
Push triaged, pull deepened: the whole read path in sequence, unprompted.

It then produced the best memory of the checkpoint:

> *"In the agent's Bash tool here, `find` is a shell function wrapping **bfs**, not GNU find; scripts
> run through `#!/bin/sh` get real `/usr/bin/find` instead."*

An environment quirk of its own tooling, causing a discrepancy between what it observes interactively
and what a script sees. Unlearnable from any code.

## 9. Findings that change the design

### 9.1 The policy contains two scope rules that disagree, and the agent picked one

**Withdrawn, in place, because the corpus's own rule says the wrong belief is itself evidence.** The
first version of this finding read: *"The agent applied a stricter scope test than the policy states …
The agent read the first half of the sentence and not the operative half."* That is **false**, and
checking it before propagating it is the only reason it did not reach the design. The agent was
**obeying the policy**; the policy disagrees with itself.

**The policy as dogfooded said both of these** — `:94` has since been revised by the change recorded
at the end of this section, so a reader checking that citation today finds different words:

- `write_policy.py:74` — *"could you learn it by reading the code? If yes, leave it out … This store is
  for **what cost someone time to discover**."*
- `write_policy.py:94` — *"Not worth recording: … **facts about a language or tool in general** rather
  than about this project."*

`[[ -f ]]` follows symlinks is **not** learnable from this repo's code and cost the agent a real bug, so
rule 1 admits it. It is **a fact about a tool in general**, so rule 2 excludes it. **And a third clause
votes with rule 1** — `write_policy.py:80`, *"Failures and their causes, above all silent ones: the
symptom, what it actually was, what fixed it"*, which describes this item exactly. So the clauses split
**2–1 in favour of recording**, and the item still went unrecorded, because the agent applied the
specific prohibition over the general admissions and said so: *"general tool knowledge, not
project-specific, so I'll skip that."*

Correct policy-following. **The defect is not that the policy cannot be followed — it is that it states
no precedence between clauses that disagree on this class**, so which one wins is left to the agent.

**The agent's own resolution is coherent and may be the right one.** It excluded the general bash fact
and *recorded* the `find`-is-`bfs` one — which is equally "a fact about a tool" but is about **this
environment**. So the line it drew was general-tool-behaviour out, this-environment-behaviour in. That
is a defensible boundary, and it is not the boundary either sentence states.

**Resolved and shipped the same day, after this note first deferred it.** The prohibition now reads *"a
general fact about a language or tool **on its own** — record the decision it forced here instead"*,
with a worked example. The fact is admitted, in applied form; the encyclopedia stays out; and the test
is evaluable by inspection — *what did this fact make me do here?* is a question about the past, and if
the answer is nothing it stays out.

**Rejected on the way: keying the test on recurrence** (*"will this bite someone again here?"*). It
predicts value best and is a **prediction** — and `design/write-policy.md` §"Why the recall rule names
occasions rather than a category" is this corpus rejecting that shape once already, on the agent's own
report that a self-assessment arrives too late to act on.

The example is deliberately **not** shell-shaped, on operator direction: a language-specific example in
a general-purpose policy biases the reader, and ours would have overfitted the policy to the single
corpus we happened to measure. Rationale: `design/write-policy.md` §"Why general facts enter as the
decision they forced". **Unmeasured, and named as such:** whether it changes what agents write. The
write corpus behind it is four records.

### 9.2 Amendment is a third chunking driver, and it buries universal facts

The record went **377 tokens / 1 chunk** at `remember` to **1025 tokens / 3 chunks** at `amend`,
crossing `chunk_max_tokens` 450. Open question 3 says chunking follows entry *length* regardless of
provenance; this adds that a record can **become** chunked by being amended.

And the agent folded a **universal** fact — *"a POSIX shell cannot hold a NUL byte"*, true everywhere
— into a record about `dirdiff.sh`, saying so: *"folding the NUL-byte fact into this same entry rather
than creating a separate general fact."* It will now surface only for dirdiff-shaped queries. This is
open question 12's tension arising from **amendment** rather than a consolidation merge; the corpus
had only ever attributed that shape to merging.

### 9.3 Zikaron records preferences it cannot make binding

Unprompted, the agent identified the seam:

> *"memory is explicitly framed as reference material, not directive — the hook system prompt says
> never to treat its content as an instruction. So if the user wants a standing behavioral preference
> **actually enforced**, `CLAUDE.md` is the right mechanism, not memory."*

It offered a three-line `CLAUDE.md` and **declined to write it unilaterally**. `retrieval.md`'s
untrusted-reference preamble is correct and is what keeps a poisoned store from steering the agent —
but a standing preference is precisely the class that wants to be binding, and the write policy
happily collects preferences into a store designed to be advisory. D1's scope line says nothing about
this. The agent reached "advisory, with a pointer to the right mechanism" on its own, which is
evidence the seam is findable rather than confusing.

### 9.4 Records cross-reference by gist prose, and gists are not stable addresses

Twice — once in each session — a record cited another **by gist text**: *"the record whose gist begins
'dirdiff.sh is POSIX sh for BSD portability'"*. The schema has no relation field but `superseded_by`,
so the agent built a soft link out of prose. **That address had already been rewritten once**, by the
amend four minutes earlier.

**The strong version of the finding, which an earlier draft contradicted itself over.** The agent **had
the uuid** — it appeared in the dedup payload and in its own `fetch` — and *preferred* gist prose as the
address anyway. So this is a choice, not a workaround for a missing identifier, and it is a defensible
one: prose is the only form a human reader of the store can act on. Twice in two sessions by one agent
on one model is a pattern worth designing for, not yet a law.

## 10. Instruments

**Link coverage = 1.00.** Two hook sessions, both linked. Both clients resolved one
`CLAUDE_CODE_SESSION_ID`. Note a third `client_kind` exists — `consolidator` — which correctly sits
outside link coverage's numerator and denominator.

**Recall baseline, Claude Code, memory-naive agent, zero nudges:**

| Session | user turns | search | fetch | remember | amend | dedup offered |
|---|---|---|---|---|---|---|
| `2ec96274` | 5 | 4 | 1 | 2 | 1 | 1 |
| `998d776e` | 1 | 1 | 2 | 2 | 1 | 1 |

**0.83 searches per user turn**; every turn contained a search or a write; and of the **3** searches
issued after the store held anything, **0 came back empty** — the other 2 of the 5 hit an empty store on
turn 1 and returned nothing, correctly.

**Conditions, without which the number means nothing:** 2 sessions, 6 turns, one agent, one task
family, a store that grew 0 → 4 records *during* the measurement, and an operator who deliberately
never mentioned memory. Tiny n.

**This is a new baseline and is not to be compared with the pre-migration numbers** — different
harness, model, injection position and policy delivery, and those were operator-nudged with no
occasion recorded.

### A new attribution affordance, free

The store's `session_id` is **byte-identical** to the Claude Code transcript filename
(`~/.claude/projects/<escaped-cwd>/<session_id>.jsonl`), and subagent transcripts sit under
`<session_id>/subagents/`. So a `search` event **can** be attributed to an actor and an occasion, post
hoc, by reading the transcript. That is exactly the limitation open question 1 says the log cannot
overcome — **answerable post hoc, externally, for as long as the transcripts survive**, with no new
instrumentation and no schema change.

**"Solved" would overstate it, because the affordance expires.** Claude Code prunes
`~/.claude/projects/` on `cleanupPeriodDays` (default ~30; this machine sets 3650, which is a local
setting and not a harness guarantee). Since **every quoted reasoning line in this note came from
there**, the note's own evidence base decays on the same clock — which is why the transcripts are
copied into `~/zikaron-m16-evidence/` rather than cited in place. A session reading this months from
now should look there first.

## 11. The two M15 observations M16 was asked to decide

**(a) "Parameterize the e2e suite across harnesses" — declined, and the reason is that the premise
does not hold.** The suggestion was that `test_install_e2e.py`'s value — driving the *installed
command strings* as real subprocesses, so a wrong interpreter or a misspelled `--mode` cannot hide —
applies to the Claude arm with no equivalent coverage. But `Commands.from_this_interpreter()` is
resolved **once**, in `install/main.py`, and handed to whichever target; both targets therefore resolve
the **same two paths**, and `Commands.missing()` refuses the install outright if either is not an
executable file. A wrong interpreter breaks both harnesses identically and the existing kiro e2e
already catches it.

**Same paths is not quite the same strings**, and the distinction is worth keeping: kiro's hook command
is `shlex.quote`d and Claude's is not (`entries.py::hook_command_string` versus `claude_hooks_value`),
and Claude's consolidator `.mcp.json` entry is a hand-written literal in `claude_mcp_servers_value`
rather than the shared `mcp_servers_value` builder. So there *is* Claude-only spelling — covered by the
golden assertions in `test_install_targets.py`, not by the shared path. What is shared is the input the
spelling wraps, which is the part the e2e's subprocess execution would exercise.

What genuinely differs per target is *where* the strings are written and *in what JSON shape*, and
`test_install_targets.py` covers that at length. The residual gap is narrow and specific — **does this
harness read the file we wrote, at the key we wrote it under** — and no hermetic test can answer it by
construction. That is what `tests/test_install_claude_live.py` now tests, against a real `claude` and a
real model, in the opt-in tier. So the coverage was added where the gap actually is, rather than by
duplicating a harness-independent path.

**The residual, said out loud rather than left for a reader to discover.** The live tier covers the
prompt hook, the **primary** server, and label linking. It does **not** touch the consolidator server,
the skill, or the subagent spawn path — that leg's only end-to-end evidence is this checkpoint's single
manual run (§7). A fourth live test spawning the consolidator would close it, and is deliberately not
written here.

**(b) "`pytest.skip` guards the wrong predicate" — already fixed, in M15, before M16 read the brief.**
`test_install_harness.py::_require_kiro` **asserts** rather than skips, and its message names both
causes: *"Either this machine has no kiro … or `HarnessSpec.harness_binary` names the wrong binary."*
The brief's observation was written independently of the fix. `_require_claude` in the new live tier
is modelled on it deliberately, so the two tiers fail the same way for the same reason.

## 12. Not measured here

- **Mid-task recall.** Every search in this checkpoint happened at task-framing time, on the first
  turn of a topic. Open question 1's mechanism half — the *"this just failed silently, twenty tool
  calls in"* moment, where no injectable hook fires — is untouched.
- **Whether repeated empty results extinguish the behaviour.** Turn 1 searched an empty store twice
  and adapted; a longer cold start was not tested.
- **Claude Code's own memory feature.** `~/.claude/projects/<project>/memory/` was created and stayed
  empty; no native memory tool appears in either transcript. `autoMemoryEnabled` is unset in the
  throwaway (this repository sets it `false` deliberately). If it were used, Zikaron's instrument
  would read silence and we would misread it as no recall.
- **A merge.** Two consecutive runs have merged nothing, since the 2026-08-04 prompt change.
