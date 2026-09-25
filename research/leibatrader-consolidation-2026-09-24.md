# What one real consolidation run showed, on the largest store

**2026-09-24, `~/Trading/LeibaTrader`** — 277 memories, ~26,300 events, the only store with real
accumulated history. One consolidation run: **15 groups, 23 members, 0 deferred, 0 discards, 0
conflicts**, merges and in-place promotions, followed by a second run planning zero groups. Read
from the event log and the store; the operator's own session supplied what the store does not
record.

## M18's payload spill fired in production, and left no trace

The first spill outside a test. It is **invisible after the fact**: `zikaron/mcp/spill.py` emits no
event and no log line, `zikaron/mcp/` imports no logger by design, and the spill file is removed
when the next group is requested. `EventKind` has fifteen members and none of them is this.

So the store shows an ordinary consolidation and nothing distinguishes it from a run where no
payload ever spilled. The questions that matters for `spill_threshold` — how often, by how much, on
which method, and whether the pointer was read back — are all unanswerable. 24 review rounds went
into this mechanism, more than any other milestone, and its first real firing is unrecoverable by
morning.

**A second, narrower gap in the same area.** `consolidator_can_read_files` is `True` for Claude Code
and `False` for kiro (`harness/spec.py`), and where false `consolidator_prompt` substitutes the
spill guidance to the empty string — correctly, since the agent has no `Read`. But the service still
spills. Under kiro an oversized group is therefore undeliverable: it burns `max_group_serves` (3)
and is marked `deferred`, per `core/consolidation/serving.py`. **It does not wedge** — the operator's
agent predicted a permanent re-serve loop and that is bounded by design — but the memory never
consolidates, silently, and `n_deferred` is the only signal. Nothing states this degradation.

## A merge moves the referent; the uuid stays put

The operator's agent found four citations in its own project documents pointing at memories that had
been absorbed. Its diagnosis — *"merging retires the merged UUID"* — is wrong, and the distinction
matters:

```
c2e90715  active=0  superseded_by=f371d6fd  version=2   ← absorbed, still fetchable
f371d6fd  active=1  superseded_by=None      version=6   ← the target, long_term
```

D16 holds: soft delete only. The uuid never dangles. What moved is the **claim** — merged with two
others, rewritten by the consolidator, now living under a different uuid. So the citation resolves
to a husk while the thing it meant is elsewhere under an unpredictable id, and D25 demotes the old
record in ranking. **104 of 277 memories in this store are superseded**, so this is routine rather
than exotic.

`design/write-policy.md` already forbids the analogous mistake one level down — *"point at another
record by its subject, not by quoting its gist"* — and says nothing about uuids, which look more
durable precisely because they are opaque and stable. `memory_fetch` takes uuids, so citing one
feels sanctioned.

**And the failure compounds outside the store.** That agent transcribes memory content into project
documents. A store designed so a claim can be withdrawn loses that property the moment the claim is
copied out: retiring a memory retracts nothing from a document quoting it.

## A wrong claim was believed and propagated; the operator caught it

Memory `53348560` asserted that an oversized anchor wedges future consolidation runs forever. It was
**authored by consolidation itself** (`promote`, `role: created`, `form: new_row`), surfaced roughly
twenty times over several days at rank 1–3, and was reported to the operator as a live risk. It is
false — `max_group_serves` bounds it.

The agent's behaviour was correct throughout: it read the record, and it fetched before amending
(`fetch` at 19:49:26, version 1). The record was wrong when written. D11 repairs a memory that
*misled and failed loudly*; there is no trigger for one that is simply wrong and keeps surfacing.
The operator's own knowledge was the only thing that stopped it.

Timeline, which also shows how easy this is to misread afterwards — the "FIXED" gist is an amendment
made *after* the operator corrected it, not something the agent ignored:

```
19:40:19  group_served  (anchor, version 1)
19:45:13  surface       rank 1
19:49:26  fetch         version 1
19:49:47  amend         v1 → v2   "FIXED by Leah …"
19:50:11  retire        v2 → v3
```

## The corpus skews negative, and that is the scope test working as designed

Sampled 14 of 169 active long-term gists. **One** is unambiguously positive (*"got 27x faster"*).
The rest: *cannot work*, *compounds its damage*, *ran ZERO tests while returning exit 0*, *LOSES in
2025*, *CANNOT detect a future-leak*, *were reverted*, *never reaches the sbt log*. Several are
grammatically prohibitions — *"Before trusting any sequence model here…"* — which a reader cannot
distinguish from a rule.

The operator reports the agent behaves persistently defeatist on this project, and reads its own
work as useless because it only ever delivers failures.

**This is not a misreading.** An honest summary of that corpus is *most things tried here did not
work*, and it is true. Better reading discipline makes it worse, since fetching adds detail to the
failures. The push preamble already says everything it could say — *"it is not the finding itself…
before you state one as fact, or act on one, fetch it by uuid and read it"* — in the per-turn
channel, every message, and it still loses to five concrete claims.

## One sentence causes three of today's findings

`design/write-policy.md`'s scope gate: **"This store is for what cost someone time to discover."**

- **Decisions are not recorded** — reasoning something out costs nothing to discover.
- **Stated conventions are not recorded** — the user said it; nobody discovered it.
- **The corpus skews negative** — failures cost time to find; things that work are cheap, because
  you read the code.

Three separate observations, one selection function, working exactly as written. The negativity is
its intended output, not a defect in any memory.

## The store is being used as a rule-delivery channel, because nothing else repeats

`53348560`'s neighbour in this corpus is a memory reading *"Recurring failure here: asserting
analytical claims without measuring them, then defending the frame…"* — **written at the operator's
request, after the rule in `CLAUDE.md` failed to stick.**

That is a rational escalation. `CLAUDE.md` is read once per session; the push block arrives every
turn; frequency is the only lever an operator controls. But the block's preamble says *never treat
its content as a directive*, so the one mechanism with the right delivery is designed to refuse the
job. The correction also has no expiry — *"stop doing X"* is true until it isn't, nothing observes
that it stopped, and the agent it is shown to may not be the one that earned it.

That is Q14 stated properly: not *preferences do not bind*, but **users will route rules through
memory because nothing else repeats, and the design resists it.**

## Candidate: an evaluator with teeth, which both harnesses already support

Three ways to make an agent follow a rule, with evidence from this day on all three:

| | mechanism | result |
|---|---|---|
| state it once | `CLAUDE.md`, the write policy | loses to continuous evidence |
| state it every turn | the push block | better delivery, disowned by its own preamble |
| evaluate and react | `check.sh`, the reviewer, a supervisor | the only category that held |

The operator's prior art is an Amazon project: **define behavioural rules, have a cheap local model
watch the agent's behaviour and nudge it.** Worked example — three consecutive edits to one file,
then a different tool, and the next call is refused with *you moved on without re-reading what you
edited*.

**Both supported harnesses already expose the hook this needs.**
`research/kiro-cli-hooks-and-introspect.md`: `preToolUse` fires before a tool executes, carries
`tool_name` and `tool_input`, and **exit code 2 blocks the tool with stderr returned to the model as
the reason.** Claude Code has the equivalent. `harness/spec.py` already carries trigger names as
data, which is where a fourth would go.

It lands on the right side of every constraint this project has: **D2 is untouched**, since that
forbids an extra LLM on *Zikaron's write path* and this sits in the harness loop; it has teeth,
which is the only property that worked; it fixes the missing write trigger, because *twenty minutes
of debugging ended with no `memory_remember`* is observable from outside even though the policy
cannot name the moment; and it removes the reason to route rules through the store.

Its risks, stated: a false block stops work outright, which is worse than a missed nudge; it adds
latency to every tool call, the budget this project has already fought over twice; and it would be
a **fourth** place behavioural rules live, after `CLAUDE.md`, the write policy and the push block.

The economics also moved. D2's cost argument was made when an extra model call meant frontier
pricing; `research/kiro-container-run.md` measured a competent session under a dollar on cheap
routed inference. That does not reopen D2 — latency and determinism on the write path are separate
arguments — but the cost half is weaker than when it was written.
