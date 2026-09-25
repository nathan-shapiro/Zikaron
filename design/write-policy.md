# Write policy — v0 draft

> Drafted 2026-08-01, summarized as **D30** in `FINDINGS.md`. Delivered by the `agentSpawn` hook (D18), so
> it is injected once per session, sits early, and does not churn the prompt cache. **Explicitly a starting
> point to experiment against, not a settled answer** — Open question 7 remains open, and §3 below is the
> instrumentation that makes the experiment possible.
>
> **Delivery scope, narrowed 2026-08-01.** The hook prints nothing in a **subagent** session — it cannot
> identify the agent, so it suppresses all of them (`architecture.md` §"Subagent sessions"). So this text
> reaches top-level sessions only. That is the intended reach: the consolidator must not receive it (its verbs
> and its judgment are different, and D32 keeps its context narrow on purpose), and any other subagent that
> writes should carry its own policy in its own agent config, which is where per-agent instructions belong. The
> accepted cost is that a *general-purpose* subagent writing through MCP does so without this guidance;
> §3's signals will show it if it matters, since `client.kind` is `mcp` either way and the write attributes to
> the top-level session.
>
> **Harness delta (D34): the paragraph above is kiro's reach, and it is not Claude Code's.** Claude Code
> fires `SubagentStart` carrying `agent_type`, which makes the per-agent rule expressible — so
> `hook/subagent_policy.run` delivers the subagent variant of this text (§2) to **every subagent
> except `zikaron-consolidator`**,
> an unknown `agent_type` included, deliberately. Three consequences for the paragraph above, on that
> harness: it does not reach top-level sessions only; a general-purpose subagent writing through MCP
> **does** get this guidance, so the "accepted cost" is kiro's alone; and carrying a policy in the
> agent's own config is no longer the only route. §"Delivery" above says "injected once per session":
> under Claude Code it is once per session **plus** once per non-consolidator subagent.
> `harness.md` §"Subagents" is normative.
> *This was the scope header of the document that owns the injected text, stating a reach that had been
> half-false since M14 — and `harness.md`'s own inventory of kiro-stale prose did not name it. A delta
> note is cheap; the reason this one was missing is that nobody re-reads a section headed "narrowed",
> which reads as already having been thought about.*

## 1. Why this text is shaped the way it is

**Two rules are here because of a production failure rather than an argument — one observed, one
reported.** The older is
below; the newer is the read side's fetch cue, added 2026-09-20 after an agent in real use reported
taking gists as findings and answering from them
(`FINDINGS-archive.md` §"The gist-as-abstract fix, and M27" records the report and both records). It
first lived in this prompt as *fetch before you state one as fact*; M32 moved it to the two surfaces
that hand back a headline — the injected block and `zikaron_memory_search`'s description — and
changed its trigger to read-time task relevance (`retrieval.md` §"Push output format").
"If a claim expires, the gist has to say so" was added 2026-08-03, in the first hour of real
dogfooding. An agent asked to record project knowledge wrote the gist *"do not tune rrf_k/fusion_depth/arm
weighting during retrieval work — it's a deliberate standing instruction"*, with the condition that makes
it true ("during M5") left in the `content`. A later session with no other context was asked "should I tune
rrf_k?", answered from the gist alone — correctly, as retrieval triage — and told the operator **not to**,
which by then was wrong: the build was complete and that work was precisely what had been parked. It then
fetched the content, read "during M5", and *still* concluded the current phase was M5, because nothing in
the memory said otherwise and the gist had already framed the prohibition as live.

Two prohibitions were already in this text and neither caught it. "Write observations, not orders" names
the imperative but not the expiry; nothing named the expiry at all. The structural point is what makes the
new rule a rule rather than an emphasis: **every memory has a gist/content boundary, the gist is the half
that gets injected, and a qualifier on the far side of that boundary is a qualifier that will be recalled
without its claim.** The content cannot rescue a gist that has already been believed. The read side now names the fetch
occasion (`retrieval.md` §"Push output format"): it is the second half of this rule rather than a
replacement for it, for the reason this paragraph gives — a qualifier in the line reaches every
agent, and one in the content reaches only an agent that fetches.

**The dominant failure mode is under-writing, and we have evidence, not a hunch.** `~/Memory`'s first live
run found `REMEMBER` **under-triggered**: the model funnelled durable facts — even improvised self-details —
into its scratchpad and never called the memory verb at all, which forced a per-turn `LTM_NUDGE` to be added.
So the prompt deliberately biases toward recording, and leans on D15's write-time dedup to absorb the
redundancy that bias produces. Flooding is the cheaper error: a duplicate is one row and the dedup path
offers it back, whereas an unrecorded lesson is re-learned at full cost.

**The scope line needs a test, not a definition.** D1 ~~says~~ **said** tribal knowledge, not codebase
knowledge — and since its 2026-09-15 amendment the test is a **routing rule rather than a refusal**:
codebase and document knowledge now has a home in Zikaron's knowledge index rather than nowhere, which
is a stronger argument for the same test, not a weaker one. But an
agent will happily record "the auth module lives in `src/auth/`". The operational test — *could you learn
this by reading the code?* — draws the line in a way an agent can actually apply in the moment.

**Gists must be cue-shaped, not summary-shaped.** D13 makes the gist's job relevance triage, and retrieval is
triggered by symptoms: the query arriving at the moment of need is the error text or the task, not the
conclusion. So the instruction is to lead with the observable situation.

**Repair has to be named as a duty.** D11 is the entire staleness mechanism and it only works if the agent
that gets burned understands that fixing the memory is part of the job rather than a favour.

**Two things must be prohibited, not merely omitted.** A memory is durable, unencrypted, local prose, and its
gist is injected into a future model's context. That makes two failure modes worth explicit prompt text:

- **Secret capture.** The draft's "Environment requirements: env vars, versions, credentials" invited an
  agent to record the credential *value* it had just found in a shell history or a `.env` file. Recording
  which credentials are needed and how to obtain them is exactly the tribal knowledge we want; recording the
  token is a durable plaintext leak that D16 makes *harder to remove*, since retire keeps the row, the FTS
  index and the vectors. The prompt now names the boundary.
- **Instruction-shaped memories.** A memory can be written from material the agent did not author — a README,
  a tool output, a web page, or an earlier poisoned memory. If an agent writes "always deploy with --force"
  as a gist, every future session sees it in the injected block, where it is indistinguishable from policy.
  Two mitigations, and neither is complete: the write side asks for observations rather than directives, and
  the read side frames the whole block as untrusted reference data
  (`design/retrieval.md` §"Push output format"). v0 has no detection and no provenance beyond
  `session_id`; this is a bounded, stated risk, not a solved problem.

## 2. The prompt

Two variants, differing only in their second paragraph. The main-agent text describes the block
pushed with each user message; the subagent text says nothing is pushed, because nothing is —
and a subagent told *"nothing is injected for you"* **as an injection** has been handed a false
sentence as its first context. `zikaron/hook/subagent_policy.py` selects the second.

### Main agent

```
## Project memory (Zikaron)

This project has a memory store of what was learned by working here and is not in the source
code. It persists across sessions, and other agents read what you write.

**Look things up before you spend time.** A block of headlines is injected with each user message,
chosen for the words in that message, not for the problem as you understand it now. Each headline
names a record; the record holds the finding, its conditions and its exceptions. The block does
not follow the task once you reframe it, and nothing new arrives until the user speaks again.

Search with zikaron_memory_search when one of these happens, not when the effort ahead feels big
enough to deserve it:
- **Something surprised you.** A step failed in a way you did not predict, or code behaves
  differently from how it reads.
- **You are about to propose** a design, a mechanism or a plan.
- **You are about to say an approach will not work.**
- **You are about to rename, move or delete** something other work depends on.

When you propose a design or a plan, or call an approach a dead end, say what you searched for and
what came back, including "searched X, found nothing relevant". A hit is evidence about what
happened then, not a ruling about what must happen now: it tells you what to re-check, not which
option to drop.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out. This store is for what cost someone time to discover.

Worth recording with zikaron_memory_remember:
- How to build, test, run and deploy, above all the step the README omits
- Failures and their causes, especially silent ones: the symptom, the actual cause, the fix
- Environment requirements: env vars, services and versions that matter, and which credentials
  are needed and where to obtain them
- Constraints and prohibitions with their reason: "do not use X yet, because Y"
- Approaches already tried that did not work, and how they failed
- Conventions and preferences that are settled and written down nowhere

Not worth recording: what the source already says; transient state ("currently on branch
fix-123"); a general fact about a language or tool on its own. Record the decision a general fact
forced here: not "the test runner parallelizes by default" but "tests here run serially, because
the fixtures share one database".

**Never record a secret or personal data.** The store is plaintext on disk, and retiring a record
does not erase it. Headline and content rules are in zikaron_memory_remember's description.

**Err toward writing.** The common failure is recording nothing. Near-duplicates are detected and
handed back, so write without checking first.

**Repair what misled you.** If a record you acted on turns out wrong or stale, establish the
current truth and amend it with zikaron_memory_amend. Retire a record only when it is no longer
true and has no replacement.
```

### Subagent

```
## Project memory (Zikaron)

This project has a memory store of what was learned by working here and is not in the source
code. It persists across sessions, and other agents read what you write.

**Look things up before you spend time.** Nothing is pushed to you: no headlines arrive with a
message. Memory reaches you when you call zikaron_memory_search, or zikaron_memory_fetch with ids
you were handed. Each result is a headline naming a record; the record holds the finding, its
conditions and its exceptions.

Search with zikaron_memory_search when one of these happens, not when the effort ahead feels big
enough to deserve it:
- **Something surprised you.** A step failed in a way you did not predict, or code behaves
  differently from how it reads.
- **You are about to propose** a design, a mechanism or a plan.
- **You are about to say an approach will not work.**
- **You are about to rename, move or delete** something other work depends on.

When you propose a design or a plan, or call an approach a dead end, say what you searched for and
what came back, including "searched X, found nothing relevant". A hit is evidence about what
happened then, not a ruling about what must happen now: it tells you what to re-check, not which
option to drop.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out. This store is for what cost someone time to discover.

Worth recording with zikaron_memory_remember:
- How to build, test, run and deploy, above all the step the README omits
- Failures and their causes, especially silent ones: the symptom, the actual cause, the fix
- Environment requirements: env vars, services and versions that matter, and which credentials
  are needed and where to obtain them
- Constraints and prohibitions with their reason: "do not use X yet, because Y"
- Approaches already tried that did not work, and how they failed
- Conventions and preferences that are settled and written down nowhere

Not worth recording: what the source already says; transient state ("currently on branch
fix-123"); a general fact about a language or tool on its own. Record the decision a general fact
forced here: not "the test runner parallelizes by default" but "tests here run serially, because
the fixtures share one database".

**Never record a secret or personal data.** The store is plaintext on disk, and retiring a record
does not erase it. Headline and content rules are in zikaron_memory_remember's description.

**Err toward writing.** The common failure is recording nothing. Near-duplicates are detected and
handed back, so write without checking first.

**Repair what misled you.** If a record you acted on turns out wrong or stale, establish the
current truth and amend it with zikaron_memory_amend. Retire a record only when it is no longer
true and has no replacement.
```

Left to the MCP tool descriptions rather than duplicated here: the mechanics — the version precondition
and its read receipt (D26), what the dedup response contains and how to resolve a duplicate (D15), the
retire-versus-supersede distinction (D16, D25) — and, since M32, the rules for the text of a write: the
headline's form and bound, expiry-in-headline, observations-not-orders, the secrets boundary and
subject-not-quote, all in `zikaron_memory_remember`'s description and referenced from
`zikaron_memory_amend`'s. A description is in context at the instant the argument it governs is being
filled, and costs no injection budget; the prompt above keeps one line on secrets and points at the
rest. What stays here is what no description can prompt: the write trigger, the scope test and the
recall occasions.

### Inspection, deletion, and the one thing D16 cannot do
The store is a plain SQLite file at `<scope>/.zikaron/memory.db`, mode 0600, never committed (D19). A user can
read every memory with `sqlite3` and no tooling from us.

`retire` is the only removal verb **agents** get, and it is deliberately soft (D16) — one bad session must not
be able to destroy accumulated lore. D16's "never hard `DELETE`" is a constraint on the **agent-facing API**,
not a claim that the bytes cannot be removed; an operator with `sqlite3` is outside that boundary by design,
which is the same trust boundary §"Filesystem security" draws for the file itself. The consequence has to be
said out loud: **retire is not erasure.** The row, its FTS index and its vectors all remain, and a superseded
row stays *retrievable* by design (D25). So if a secret does get recorded despite the prohibition above,
retiring it is not the fix.

#### The emergency erasure procedure, exactly
An earlier draft said "delete the row and its chunks directly". **That does not erase the secret**, and it was
verified locally that it does not: `memory_fts` is an **external-content** FTS5 table, so deleting the `memory`
row leaves every one of its terms matchable — a `MATCH` on the secret still returns the deleted rowid.
**Re-verified in M0 (spike 2), and the failure is worse than "the term stays findable": it degrades rather
than fails cleanly.** Deleting only the content-table row commits with no error. The next `MATCH` query does
not raise either — it returns a phantom result that matches nothing real, since the term it appears to match
no longer exists anywhere. A second, identical query then raises `database disk image is malformed`. So the
naive form is not merely insufficient, it is a path to database corruption, and the corruption does not
announce itself on first contact — an operator who ran one query after a bad delete and saw a plausible-looking
answer would have no signal anything was wrong until the next touch. This is why the sequence below maintains
`memory_fts` explicitly with the `'delete'` command rather than relying on the content-table delete alone.
Detail: `research/spike-results.md` §"Spike 2".
`memory_vec` has no foreign key, so deleting chunks first orphans vectors. And **four** `ON DELETE RESTRICT`
references will refuse the delete outright. The supported sequence, with the service **stopped** (find its pid
in `service.log`, `SIGTERM` it; it unlinks its socket on exit — do not do this against a live service, whose
in-memory state would rewrite what you just removed):

```sql
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
-- 1. Remove the lexical entries FIRST, using the row's CURRENT values. External-content FTS5
--    cannot derive them once the row is gone; this is the only supported deletion form.
INSERT INTO memory_fts(memory_fts, rowid, gist, content)
  SELECT 'delete', rowid, gist, content FROM memory WHERE uuid = :u;
-- 2. Vectors before chunks (schema.md invariant 2: memory_vec has no FK).
DELETE FROM memory_vec
  WHERE rowid IN (SELECT chunk_id FROM memory_chunk WHERE memory_uuid = :u);
DELETE FROM memory_chunk WHERE memory_uuid = :u;
-- 3. Clear the RESTRICT references, or the delete fails. Rows that pointed at this one become
--    terminal (retired outright) — see schema.md invariants 6–7.
UPDATE memory SET superseded_by = NULL WHERE superseded_by = :u;
DELETE FROM consolidation_run WHERE run_id IN (
  SELECT run_id FROM consolidation_group
   WHERE anchor_uuid = :u
      OR group_id IN (SELECT group_id FROM consolidation_group_member  WHERE memory_uuid = :u)
      OR group_id IN (SELECT group_id FROM consolidation_group_candidate WHERE memory_uuid = :u));
-- Dropping a run loses nothing: undispositioned members stay tier='journal' AND active=1
-- and the next plan_groups() picks them up (schema.md invariant 16).
-- 4. The row itself. read_receipt cascades.
DELETE FROM memory WHERE uuid = :u;
COMMIT;
-- 5. Verify, then reclaim the pages the prose was on.
INSERT INTO memory_fts(memory_fts) VALUES('integrity-check');
PRAGMA wal_checkpoint(TRUNCATE);
VACUUM;
```

Then, outside SQLite: **truncate `service.log`**, which quotes prompts and error text and may therefore hold
the same string. `warmup.log` and `hook.log` do not need the same treatment: neither ever echoes prompt text,
memory content, or anything beyond a fixed failure-kind label and an error code (`architecture.md` §"Paths",
§"Degraded modes"), so neither can hold a secret by construction.

**And delete this store's spill files from the runtime directory**, `$XDG_RUNTIME_DIR/zikaron/` (or its
per-uid `/tmp` fallback — `architecture.md` §Paths). A consolidator group too large for a harness to deliver
is written there verbatim, so a record erased from the store can survive in one of those files until the next
reboot clears the directory. They are `0600`, and each is named for the store it came from: `<store-hash>-<method>-<pid>-<random>.json`,
where the hash is the one that names this store's socket in the same directory — so
`rm "$XDG_RUNTIME_DIR"/zikaron/<store-hash>-*.json` reaches exactly this store's files and no other's.
A consolidator removes the previous group's files as it advances and sweeps a dead
predecessor's when it starts, so what remains here is at most one group's files — the current group of
a live run, or the last group a killed one was holding — until the next consolidator start sweeps them.
The `rm` above waits for neither. This is the one copy of
record prose that lives outside the store and outside the log rules, and it is listed here because nothing
else in this procedure would reach it.

#### What this still does not guarantee
- **A knowledge base is a separate plaintext copy, and this procedure does not touch it.** Added
  2026-09-22, and it is the largest gap this section had: a corpus holds the **verbatim text of every
  file indexed into it**, in its own database, its own FTS5 index and its own vectors
  (`design/knowledge-index.md`). So a secret that reaches Zikaron inside an indexed *file* was never
  written by an agent, is not in `memory.db`, and nothing above reaches it. **`zikaron_knowledge_remove`
  destroys that corpus's index**; the file itself is yours to fix, and rotating the value remains the
  only real remedy. *(This section was written as a complete account of where a leaked string can
  survive, and `README.md` sends a user here for exactly that. It stayed complete-sounding through the
  six milestones that added a second plaintext store.)*
- **`event.detail` is not covered, and one field of it is prose.** Event details store counts, not memory
  text — with one exception, `discard.detail.reason`, which is model-authored. If the secret could be in a
  discard reason, `DELETE FROM event WHERE memory_uuid = :u` as well.
- **A copy elsewhere is a separate row.** If the value was pasted into a second memory's `content`, this
  erases one of them.
- **`VACUUM` is not secure deletion.** It reclaims pages inside the database file; it does not overwrite the
  old bytes on disk, and on a copy-on-write filesystem, an SSD with wear levelling, or any backup or snapshot,
  the original blocks may survive regardless of what SQLite does.

**So the recommended emergency procedure is the blunt one: stop the service and delete the whole `.zikaron/`
directory.** It is one command, it has no ordering hazards, and it is complete up to the filesystem caveat
above. The cost is every memory in the store — which is the right trade against a leaked credential, and is
the reason the prompt's prohibition is the actual control. v0 ships no agent-facing hard delete, and that
remains correct; a user who needs one needs to know it is a `sqlite3` command, not a tool call.

#### Pruning the event log, if it is ever necessary

**`event` is not pruned on a schedule** — the reasoning is in `design/schema.md` §"Retention: `event` is not
pruned", and it is not primarily about size. Age-pruning would cut D30's two cross-session joins
asymmetrically, and the specific artifact — a session whose `remember` rows are gone while its `surface_call`
survives reads as a *zero-write session* — inflates the under-writing rate in exactly the direction we already
expect to find. And `event.detail` is the input to the fusion-tuning pass (`FINDINGS.md` open question 2), so
discarding it destroys evidence we want.

Measured cost for context: 454 bytes per full `surface_call` row including both indexes, so ~200 MB/year for a
heavy project at ~1,000 events/day and under 20 MB/year for a normal one. Per-directory, gitignored, and off
every hot path.

If disk does become a problem on some store, this is documented as **SQL, not a tool and not a command** —
the same posture as the erasure procedure above, and for the same reasons: it is rare, operator-driven, and
actively dangerous to automate. v0 ships no CLI, and adding a fifth executable for something that may never be
run would be worse than a documented statement. Run it with the service **stopped**.

```sql
BEGIN IMMEDIATE;
-- Whole sessions only: a session is removable exactly when ALL of its activity
-- predates the cutoff. This is what makes a manual prune structurally incapable
-- of producing the zero-write artifact described above.
DELETE FROM event
 WHERE session_id IS NOT NULL
   AND session_id IN (SELECT session_id
                        FROM event
                       WHERE session_id IS NOT NULL
                       GROUP BY session_id
                      HAVING max(at) < :cutoff);
-- Sessionless rows (consolidation runs, service-level events) age out individually;
-- they participate in no cross-session join.
DELETE FROM event WHERE session_id IS NULL AND at < :cutoff;
COMMIT;

-- Record what any later signal query must disclose as its true window.
SELECT min(at) AS earliest_surviving_event FROM event;
PRAGMA wal_checkpoint(TRUNCATE);
VACUUM;
```

Sessions are the unit because every signal is either session-scoped or a pair joined within or across whole
sessions, so a whole session is the smallest safely-removable thing. **`read_receipt` is untouched** — the
statements name only `event` — which is required, not merely tidy: it is load-bearing for D26 and bounded
logically by invariant 9.

Any rate computed over a window straddling the cutoff is wrong, which is why `earliest_surviving_event` is
worth recording: it is what a later signal query needs in order to state the window it is actually reporting
on.

### Why the recall rule names occasions rather than a category

The first version told the agent to search "whenever you are about to spend real effort", and the
agent that uses this store reported back why that fails: it requires noticing that effort is coming,
and *effort feels like progress*, so the judgement arrives after the work it was meant to precede.
The rule is now four things an agent can observe itself doing — a surprise, a proposal, a rejection,
a destructive edit — because a trigger conditioned on an observable event does not depend on
correctly appraising your own state. The rejection case is the one the store is most directly for:
"we tried that already, and here is how it failed" is the memory a confident dead-end claim would
otherwise waste.

Two supports sit beside it, both from the same account. The **sufficiency illusion** — five on-point
headlines make memory feel already consulted, while they matched the *user's words* and stop covering
the problem as soon as it is reframed, and nothing arrives to say so — is stated here and in
`zikaron_memory_search`'s description, and deliberately **not** in the injected block: the moment it
has to be read is mid-task, once the framing has moved, which the block, printed at the top of a
message, has already passed, so saying it there would spend uncached characters on every message to
reach a reader who is no longer looking. The block spends its room on the fetch instead
(`retrieval.md` §"Push output format"), and every figure for what it costs is computed from
`block.FRAMING` rather than written here. And a
**gate** — a design, plan or dead-end claim must state what was searched for and what came back,
including that nothing relevant did — because it is the only lever with a checking mechanism, and
the agent ranked it first on the evidence that everything it did reliably was gated. The scope
objection to putting it here is real and was overruled deliberately: a memory system is shaping the
form of the agent's proposals, which is broader than memory. It is one sentence so that winding it
down is one deletion, and the signal that it is overfiring is searches rising while the share
followed by a `fetch` falls — against a share re-read after 2026-09-20, since the same change told
`zikaron_memory_search`'s caller to fetch before using a result.

### Why general facts enter as the decision they forced, and not at all on their own

**This clause replaced a contradiction, found by dogfooding on 2026-08-16**
(`research/claude-code-dogfood-checkpoint.md` §9.1). The text carried two scope tests that carve
different sets: *"could you learn it by reading the code? … This store is for what cost someone time to
discover"* keys on **code-learnability**, and the old *"facts about a language or tool in general rather
than about this project"* keyed on **project-specificity**. They disagree on exactly one quadrant —
general facts that are not learnable from this code and cost time here — and that quadrant is
**plausibly the largest** one, since much of what bites a coding agent is general tool behaviour.
*Plausibly*: this is an argument from experience, not a measurement, and one session cannot supply one.

The cost of leaving it was not theoretical. Two agents obeying one policy make different calls on the
same fact, which is a correctness problem for a store several agents write to; whichever rule wins
governs the highest-volume category; and consolidation inherits the ambiguity, since it cannot judge
"is this one finding?" consistently against an inconsistent scope. A memory-naive agent hit the
quadrant on its first session and resolved it toward the prohibition, correctly and unhelpfully.

**One residual conflict survives, and it is an accepted loss rather than an oversight.** A general fact
that **cost real time but has forced nothing here yet** — learned incidentally, or mid-investigation
before any code exists — is admitted by *"Err toward writing … if you just spent real time discovering
something, record it"* and excluded by this clause. **The exclusion wins**, for the plain reason that
there is no decision to record yet; the fact enters the store the first time it forces something, and
until then the next agent may re-pay it. That deferral is the cost. It is preferred to the alternative
failure the wider reading invites, which is an agent **manufacturing a decision** to justify a record
it has already decided to write — a costume that is worse than the omission, because it fabricates a
project fact rather than merely lacking one.

**The resolution narrows the *form* rather than the scope**: the fact is admitted, when an applied form
exists, as the decision it forced here. That keeps the encyclopedia out — nobody wants a store that reimplements a manual page —
while the thing that actually cost time is recorded in the shape a later agent can act on. The applied
form is also the better record: it says where the workaround lives and why not to remove it, and it is
more cue-shaped, which serves the gist's triage job.

**Rejected: keying the test on recurrence** — *"will this bite someone again here?"* That predicts value
best and is a **prediction**, and §"Why the recall rule names occasions rather than a category" above is
this document rejecting exactly that shape once already: the agent's own report was that a self-assessment
arrives too late to act on. "What did this fact make me do here?" is a question about the past, settled by
inspection.

**The example is deliberately not language-specific.** The dogfooding corpus was shell scripting and the
first draft used a shell example; that biases the reader and overfits this policy to the one corpus we
happened to measure. A test runner parallelizing by default is a fact every ecosystem has a version of.

**Unmeasured, and stated here because this is where a future policy-tuner reads.** Whether any of this
changes what agents actually write is unknown. The write corpus behind the change is **four records**,
from one agent on one model over two sessions. It removes a contradiction that was observed; it is not
evidence that the resulting store is better.

### Why a record points at another by subject rather than by gist — or by uuid

Observed twice in one day, once per session — twice in two sessions by one agent on one model is a
pattern worth designing for, not yet a law: an agent citing another record as *"the
record whose gist begins …"*, quoting a gist that an `amend` had already rewritten four minutes earlier.

**The first proposed fix was "cite the uuid", and it is wrong.** A uuid is opaque to a human, and this
store is meant to be auditable and user-editable; it cannot be re-found semantically when it does fail;
and a hallucinated uuid is undetectable where a hallucinated description is obviously wrong to a reader
— which matters, because the agent authors the citation from what it just read. The worry that prompted
it does not even hold: `fetch` resolves a uuid with no `active` filter, so D16's never-`DELETE` rule makes
a retired record still resolvable.

**The defect is narrower than it first looked**: not prose instead of a uuid, but quoting a *mutable
field* verbatim as though it were an identifier. A reference to the subject is resolved by searching, so
it degrades gracefully where an exact key does not. And it is robust to the one actor most likely to
invalidate it — **consolidation rewrites gists**, and a subject-shaped reference survives that by
construction, with nothing needing to be added to the consolidator's own prompt.

## 3. How we find out which way it errs

We cannot judge this from the prompt text, so v0 ships instrumentation instead of confidence. All cheap,
all deterministic, none requiring an extra LLM:

| Signal | What it tells us |
|---|---|
| writes per session, and sessions with **zero** writes — `remember` and `amend` counted separately as well as together, over a denominator of sessions the service actually saw | the under-writing rate (`~/Memory`'s observed failure), and separately whether repair ever happens |
| dedup near-miss offered → **fully resolved / amended-but-duplicate-left-live / duplicate-discarded-without-amend / ignored**, classified against a **deadline** of `offer.at + signal_horizon_days`, where `A` = a bounded `amend` on the offered row and `R` = a bounded `retire` of the row just created. **`A ∧ R` closes early as *fully resolved*** (it cannot be improved on); **every other offer stays *pending*, and excluded from the rate, until the deadline passes** — so an amend-only offer is never published as a failure while an in-deadline `retire` could still complete it. At maturity all four combinations are named: `A ∧ ¬R` = amended-but-duplicate-left-live, `¬A ∧ R` = duplicate-discarded-without-amend, `¬A ∧ ¬R` = ignored. Five reported numbers, rate over the four matured classes only | whether the D15 escape hatch is used, and whether agents finish the job by retiring the row they just created |
| amend following a surface, counted once per **(session, memory) pair** that was surfaced — the pair is the unit on both sides, "following" is `event.id` order, and the amend must fall within `surface.at + signal_horizon_days`; past that deadline with none the pair is *not amended* permanently; before it, the pair is *pending* and excluded | whether D11's repair loop ever fires at all. Its `amend` arm only: a surfaced row the agent repaired by `retire` is counted by the retire signal below, so this is a floor on repair |
| retire calls, split by superseded versus outright, agent retirements only | whether the agent will ever retire, or only accretes |
| `token_count` **per write**, from the `remember`/`amend`/`merge`/`promote` events rather than from the current row | over-long memories with poor boundaries (D28), and the real length distribution open question 3 wants |
| version-conflict rate over every **observable receipt-gated** mutation call — one of `amend` / `retire` / `merge` / `promote` / `discard` that committed, or was rejected as a conflict or for a missing receipt — the consolidator's included, with `no_receipt` reported beside it | concurrency reality, and separately whether agents try to write from a gist they never read. Two exclusions, both stated where the denominator is defined in `schema.md`: rejections of other kinds write no event, so they are outside the rate; and `remember` is outside it because it names no prior version and so can never conflict — putting it in would divide contention by write volume, which the first signal measures on purpose |

Exact numerators, denominators and event shapes: `design/schema.md` §"The `event` log, per kind" and
§"D30's six signals, as queries". They are specified there rather than here because three of the six were not
reproducible from an untyped `detail` column, and because a rate needs a stated denominator to be a rate.

**They ship as SQL and stop there — no reporting UI, no formatting, no export format.** A signal is a
question about the store, and the shape an answer should take differs per caller: a CLI table, a test
assertion, a one-off analysis. Fixing a presentation in the layer that computes them would fix it for
callers that have not been written.

**Two honest limits on the session-denominated signals**, both stated because both bias the same signal in the
same direction:

1. Sessions are counted from a `surface_call` event, which exists even when a push returns nothing — but a
   session whose every push failed emits no `surface_call` event at all, because the hook never reaches the
   service on a failure and therefore never emits the event the service would have written. This holds
   uniformly across every failure kind — transport, `bad_config`, `reindexing`, contention, identity — because
   the hook's response to all of them is now identical: one line to its own `hook.log` plus a model-facing
   relay on stdout, never a read (`architecture.md` §"Degraded modes"). So the rate is conditional on the
   service having been reachable **and healthy**. Making the hook write would mean handing it a writable
   store handle, which is a worse trade than a stated caveat.
2. Pushes come from `zikaron-hook` and writes come from `zikaron-mcp`, so **two of these six signals are
   cross-process joins** and only work when both clients resolved the same session label. Since 2026-08-01 they
   do so *by construction under kiro* — both read the same `KIRO_SESSION_ID` out of their own environment
   (`architecture.md` §"Both clients resolve the same label") — but linkage is still measured, because the
   guarantee is conditional on the harness exporting that variable: `schema.md` §"Linked sessions" restricts
   those two signals to sessions where both clients appear and reports **link coverage** beside them. Coverage
   should now read ~1.0, and a shortfall means the variable was missing rather than that a derivation failed.
   An unlinked writing session would otherwise be counted as a zero-write
   session — inflating exactly the under-writing rate this section exists to test, in the direction that would
   confirm its prior. Being wrong in the direction of your own hypothesis is the failure worth engineering
   against, which is why coverage is reported every time rather than checked once.

The genuinely honest measure is end-task benefit, which needs D14's evaluation and therefore a real store.
Until then these six signals tell us the *direction* of the error, which is enough to iterate the prompt.

## 4. Known gaps in this draft
- It says nothing about how much detail to put in `content` versus `gist`, beyond the triage instruction.
- It gives no guidance on writing a memory that supersedes another versus amending in place — that
  interacts with D25 and may need a line once we see what agents actually do.
- The "err toward writing" bias was asserted from `~/Memory`'s evidence on a *character* agent.
  **First evidence from a coding agent, 2026-09-24** (`research/kiro-container-run.md`): given
  material that genuinely cost time to debug, it wrote unprompted and said why. Given three settled
  design *decisions*, with this store as its only persistence channel, it wrote nothing and
  justified that from the scope gate below — which is the gap in the next bullet rather than a
  failure of the bias.
- **The scope gate and the sixth "worth recording" bullet disagree.** *"This store is for what cost
  someone time to discover"* excludes a convention somebody simply stated, while *"conventions and
  preferences that are settled but written down nowhere"* invites it. An agent reading both took
  the gate. Whether a decision taken in conversation is in scope is a D1 question, open in
  `FINDINGS.md` Q7: widening invites every passing preference in, leaving it makes the next
  argument happen twice.
- **The 64-token gist bound has a measured cost and no instrumentation.** Two of three `remember`
  calls in one observed session were refused on it (71 tokens, then 67, then 58). A refused write
  emits no event, so the store cannot report this; `FINDINGS.md` Q18 is what would close it.
- The prompt is about half the length of the draft it replaced — the write-time rules moved to
  `zikaron_memory_remember`'s description at M32 — and every line of it is still injected once per
  session. Nothing measures whether the recall occasions or the gate earn their tokens, and nothing
  measures whether the rules now in the description are read at the call: a refused write emits no
  event (Q18), so the bound's two-of-three losses are the only signal and they were counted by hand.
- No mechanism enforces the secret prohibition. It is prompt text, and prompt text is a request. A
  deterministic pre-write scan for high-entropy strings and known key prefixes is the obvious follow-up and
  costs no LLM call — it is not in v0 because a false positive would refuse a legitimate write, and D15's
  never-lose reasoning says a refusal is the expensive error.
