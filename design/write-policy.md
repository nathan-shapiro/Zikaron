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

## 1. Why this text is shaped the way it is

**One rule is here because of a measured production failure rather than an argument, and it is the
newest.** "If a claim expires, the gist has to say so" was added 2026-08-03, in the first hour of real
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
without its claim.** The content cannot rescue a gist that has already been believed.

**The dominant failure mode is under-writing, and we have evidence, not a hunch.** `~/Memory`'s first live
run found `REMEMBER` **under-triggered**: the model funnelled durable facts — even improvised self-details —
into its scratchpad and never called the memory verb at all, which forced a per-turn `LTM_NUDGE` to be added.
So the prompt deliberately biases toward recording, and leans on D15's write-time dedup to absorb the
redundancy that bias produces. Flooding is the cheaper error: a duplicate is one row and the dedup path
offers it back, whereas an unrecorded lesson is re-learned at full cost.

**The scope line needs a test, not a definition.** D1 says tribal knowledge, not codebase knowledge, but an
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

```
## Project memory (Zikaron)

This directory has a memory store holding **tribal knowledge**: what has been learned by working
here that the source code does not tell you. It persists across sessions, and other agents will
read what you write.

**Look things up before you spend time.** A few relevant gists are injected ahead of each message
you receive, but they are only what matched *that message* — the store holds more, and nothing else
arrives unasked. Search it whenever you are about to spend real effort: a step failed in a way you
did not expect, something behaves differently from how it reads, or you are planning, brainstorming
or weighing options. Planning is the case most often skipped and often the most valuable, because
this is where "we tried that already, and here is how it failed" lives — one query costs a fraction
of rediscovering it. What you find is evidence about what happened then, not a ruling about what
must happen now. A recorded failure tells you what to re-check, not which option to drop: confirm
its conditions still hold before letting it rule anything out.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out — a separate system covers code structure, symbols and layout. This store is for what cost
someone time to discover.

Worth recording:
- How to build, test, run and deploy — especially the step that is not in the README
- Failures and their causes, above all silent ones: the symptom, what it actually was, what fixed it
- Environment requirements: which env vars and services must be set up, which versions matter, and
  **which** credentials are needed and how to obtain them
- Constraints and prohibitions *with their reason*: "do not use X yet, because Y"
- Approaches already tried that did not work, so nobody spends that afternoon twice
- Conventions and preferences that are settled but written down nowhere

**Never record a secret.** No tokens, passwords, API keys, private keys, connection strings with
credentials in them, or copied `.env` contents — and no personal data. Names and procedures, never
values: "needs GITHUB_TOKEN with repo scope, mint one at <settings page>" is right;
"GITHUB_TOKEN=ghp_..." is not. This store is plaintext on disk, it is read by every future
session, and retiring a memory does not erase it.

Not worth recording: where code lives or what a function does, or anything else derivable from the
source; transient state ("currently on branch fix-123"); facts about a language or tool in general
rather than about this project.

**Write observations, not orders.** Record what was learned and what happened — "deploying without
--force left the old worker running" — rather than standing instructions to future agents. Other
agents read these as reference material, and a memory phrased as a command will be obeyed by
someone with less context than you have.

**If a claim expires, the gist has to say so.** Some things are true only for now — during a
migration, until a fix lands, for one version of a dependency. A future agent sees the gist first
and often sees nothing else, so a condition you leave in the content is a condition that gets
dropped: "do not use the new API" recalled without "until the 2.0 release" becomes a permanent rule
nobody intended. Put the condition in the gist itself, or do not record the claim. If it will not
fit in one line, that is a sign the observation is about a passing situation rather than about this
project, and the right move is to leave it out.

**Err toward writing.** The common failure is recording nothing, not recording too much. If you just
spent real time discovering something, record it — near-duplicates are detected and handed back to
you, so you do not need to check first.

**Gists are for triage.** A future agent sees only gists and must judge from them alone whether to
read further. Lead with the observable symptom or situation rather than the conclusion:
"integration tests flake on CI unless PGHOST is set" beats "notes on test configuration".

**Keep a gist to one sentence of about 20 to 25 words.** The limit is 64 tokens — roughly 50 words
of ordinary prose — and a write over it is rejected outright, costing you the call. If a gist
strains toward that limit it is usually carrying content that belongs in `content`.

**Repair what misled you.** If a memory surfaces, you act on it, and it turns out to be wrong or
stale, correcting it is your job: establish the current truth and amend the memory. Fetch it first
— you need its version to write. Retire a memory only when it is simply no longer true and has no
replacement.
```

Mechanics deliberately left to the MCP tool descriptions rather than duplicated here: the version
precondition and its read receipt (D26), what the dedup response contains and how to resolve a duplicate
(D15), and the retire-versus-supersede distinction (D16, D25). Tool descriptions are always in context at the
point of decision, which is the better place for them.

### Inspection, deletion, and the one thing D16 cannot do
The store is a plain SQLite file at `<cwd>/.zikaron/memory.db`, mode 0600, never committed (D19). A user can
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
`memory_vec` has no foreign key, so deleting chunks first orphans vectors. And three `ON DELETE RESTRICT`
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

#### What this still does not guarantee
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

## 3. How we find out which way it errs

We cannot judge this from the prompt text, so v0 ships instrumentation instead of confidence. All cheap,
all deterministic, none requiring an extra LLM:

| Signal | What it tells us |
|---|---|
| writes per session, and sessions with **zero** writes — `remember` and `amend` counted separately as well as together, over a denominator of sessions the service actually saw | the under-writing rate (`~/Memory`'s observed failure), and separately whether repair ever happens |
| dedup near-miss offered → **fully resolved / amended-but-duplicate-left-live / duplicate-discarded-without-amend / ignored**, classified against a **deadline** of `offer.at + signal_horizon_days`, where `A` = a bounded `amend` on the offered row and `R` = a bounded `retire` of the row just created. **`A ∧ R` closes early as *fully resolved*** (it cannot be improved on); **every other offer stays *pending*, and excluded from the rate, until the deadline passes** — so an amend-only offer is never published as a failure while an in-deadline `retire` could still complete it. At maturity all four combinations are named: `A ∧ ¬R` = amended-but-duplicate-left-live, `¬A ∧ R` = duplicate-discarded-without-amend, `¬A ∧ ¬R` = ignored. Five reported numbers, rate over the four matured classes only | whether the D15 escape hatch is used, and whether agents finish the job by retiring the row they just created |
| amend following a surface, counted once per **(session, memory) pair** that was surfaced — the pair is the unit on both sides, "following" is `event.id` order, and the amend must fall within `surface.at + signal_horizon_days`; past that deadline with none the pair is *not amended* permanently, before it it is *pending* and excluded | whether D11's repair loop ever fires at all. Its `amend` arm only: a surfaced row the agent repaired by `retire` is counted by the retire signal below, so this is a floor on repair |
| retire calls, split by superseded versus outright, agent retirements only | whether the agent will ever retire, or only accretes |
| `token_count` **per write**, from the `remember`/`amend`/`merge`/`promote` events rather than from the current row | over-long memories with poor boundaries (D28), and the real length distribution open question 3 wants |
| version-conflict rate over every **observable receipt-gated** mutation call — one of `amend` / `retire` / `merge` / `promote` / `discard` that committed, or was rejected as a conflict or for a missing receipt — the consolidator's included, with `no_receipt` reported beside it | concurrency reality, and separately whether agents try to write from a gist they never read. Two exclusions, both stated where the denominator is defined in `schema.md`: rejections of other kinds write no event, so they are outside the rate; and `remember` is outside it because it names no prior version and so can never conflict — putting it in would divide contention by write volume, which the first signal measures on purpose |

Exact numerators, denominators and event shapes: `design/schema.md` §"The `event` log, per kind" and
§"D30's six signals, as queries". They are specified there rather than here because three of the six were not
reproducible from an untyped `detail` column, and because a rate needs a stated denominator to be a rate.

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
- The "err toward writing" bias is asserted from `~/Memory`'s evidence on a *character* agent. Whether
  coding agents share that bias is untested.
- The prompt is now longer than the draft it replaced, and every line of it is injected once per session.
  Nothing measures whether the secrets and observations-not-orders paragraphs earn their tokens; they are
  there because the failure they prevent is durable and unrecoverable, which is a different argument from
  measured benefit and should not be mistaken for one.
- No mechanism enforces the secret prohibition. It is prompt text, and prompt text is a request. A
  deterministic pre-write scan for high-entropy strings and known key prefixes is the obvious follow-up and
  costs no LLM call — it is not in v0 because a false positive would refuse a legitimate write, and D15's
  never-lose reasoning says a refusal is the expensive error.
