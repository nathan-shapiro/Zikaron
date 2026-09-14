# M18's end-to-end run: the spill works, and the cleanup did not

Measured 2026-09-13 and 2026-09-14, Claude Code 2.1.236, in a throwaway project at `~/zk-spill-e2e` installed with
`python -m zikaron.install --harness claude-code`. Not this repository, and not a clone of it — the
crew's own wiring and a memory-saturated prompt are confounds, the same reasoning M16's checkpoint
records.

**Raw artefacts are copied to `~/zikaron-m18-evidence/`** — every session's transcript, its
consolidator subagent's, and that subagent's metadata — because Claude Code prunes
`~/.claude/projects/` on `cleanupPeriodDays`. **Five sessions:**

| session | 2026 | how run | spill files | paged |
|---|---|---|---|---|
| `88999a21…` | 09-13 18:49 | headless — consolidated the 18-entry store, 14 groups, all inline | 0 | no |
| `82adbc5b…` | 09-13 18:54 | headless, **instrumented** — the contaminated run | 4 | no |
| `c1747b90…` | 09-13 20:21 | headless, clean prompt | 3 | no |
| `6ccd7dd5…` | 09-14 00:39 | **operator-driven**, `permissionMode: auto` | 4 | **yes** |
| `ae45b47a…` | 09-14 00:49 | **operator-driven**, reaches `default` — the gate run | 5 | **yes** |

Times are session end, local (UTC−5); transcript stamps below are UTC. The two operator-driven
sessions consolidated a store **reseeded on top of an already-consolidated one**, so their groups
carry an anchor and candidates — 39- and 46-line spill files — where the headless runs' journal-only
groups did not.

Every transcript-derived line below is attributed to one of these. **One quotation is not
transcript-derived and is marked where it appears**: the permission dialog is harness UI, captured
by the operator from the terminal.

**The three headless sessions ran under `--permission-mode bypassPermissions`, which makes them
controls**: they exercise the mechanism with the gate blinded, since a headless run approves
everything (`claude-code-installer-probe.md` §8). The gate itself is measured in the two
operator-driven sessions — §"The approval gate: it prompts".

## The store

Twelve journal entries, mean 20,499 prose characters, 245,998 total, all on one topic so the
grouping's similarity function would cluster them. Two earlier seedings informed this shape and are
worth recording because they are the reason it is not smaller:

- **A first seeding of 8 entries totalling 21,408 characters could not have spilled**, by
  arithmetic rather than observation: at even the maximum measured framing overhead (1.165×) the
  whole corpus serializes to ≈24,900 bytes, under the 27,000-byte threshold for any grouping of
  it. A second pass adding ten larger entries brought the store to 18, and grouping over those 18
  came out at one or two members — 10 singletons and 4 pairs — nowhere near `group_max`'s 12, so
  no payload approached the threshold. Entry *length* drives the spill on a synthetic corpus, not group size,
  which matches the real-store finding that candidates are 70% of a payload.
- **On this store, a single-entry group cannot spill** — its content line trips the 24,000-byte
  refusal before the payload reaches 27,000, since `SPILL_MAX_LINE_BYTES` sits below
  `spill_threshold`. So the entries here are sized for a *pair* to clear the threshold. **Not a
  general fact**, and it was first written here as one: a mature store's one-member group also
  carries an anchor and up to four candidates — 70% of a real payload — and can spill whole with no
  single value near the line bound. Even bare, a gist at its own 1,024-character bound leaves a
  corner where content just under 24,000 plus framing clears 27,000. It held here only because a
  near-fresh store has no candidates to serve.
- **Consolidation compresses hard**: the first run turned 99,166 characters of journal into a
  1,767-character long-term record. It rewrites prose rather than concatenating, so merging does not
  inflate the long-term tier and cannot be used to grow a payload.

## What the instrumented run did (`82adbc5b…`)

Six groups planned. **Four arrived as pointers, two inline.**

| group | form | bytes |
|---|---|---|
| 1 | inline | — |
| 2 | **spilled** | 64,557 |
| 3 | **spilled** | 43,859 |
| 4 | **spilled** | 64,590 |
| 5 | **spilled** | 43,884 |
| 6 | inline | — |

The pointer as the consolidator received it, from its own transcript — one line there, **reflowed
here for width**:

```json
{"spilled":true,
 "path":"/run/user/1000/zikaron/d5fef33f41cf33fbbb94c7024569ecec-next_group-905053-b53af357cba68e05.json",
 "bytes":64557,
 "note":"This result was too large for this harness to deliver, so Zikaron wrote it to the file above. That file is your payload: read it, to its end, and decide from it exactly as you would have from a result delivered inline."}
```

The filename is the designed shape — store hash, wire method, pid, random — and the hash matches
`socket_hash` over that store's resolved directory. Mode `0600`.

Outcome: 1 record promoted, 11 entries merged into it, 0 discarded, 0 conflicts, every group
`group_complete`, terminal `next_group` returning `{done: true}`.

**All four reads succeeded on the first attempt**, each `Read` called with `file_path` set to the
exact path and no `offset` or `limit`, and none returned a truncation notice. So the pagination path
was not exercised end to end, which the brief accepts as a decision rather than an oversight.

**The consolidator treated the pointer as legitimate and read the file completely — but this run
cannot attribute that to the shipped guidance.** Its own task prompt contained an accounting
instruction naming the pointer's exact shape and asking *"what you did next **to obtain the group's
content**"*, which presupposes acting on it. That primed the behaviour being measured. The claim
first written here — "without being prompted to" — is **withdrawn**; M16's checkpoint kept its agent
naive for precisely this reason and this note quoted that standard three paragraphs above before
breaking it.

### A second run, with the confound removed

2026-09-14, transcript `c1747b90-a8b1-47f4-8a02-77a808c388e9` (subagent
`agent-a889596d1cbec6be2.jsonl`) in `~/zikaron-m18-evidence/`.

**The store was reseeded to the same shape, not restored byte-identically.** Seeding was a script,
preserved as `seed-zk-spill-e2e.py` in the evidence directory: it writes twelve entries, findings
0–11, from five rotated templates, through the service's real `remember` path over the socket — so
the rows carry genuine embeddings and group exactly as any other write would. Its module docstring
was **corrected after preservation**: it had described an earlier eight-entry draft that was never
run and would not have spilled, which is the same assert-what-the-code-does-not-do defect this note
records elsewhere, found in the one file kept as this control's provenance. Re-running it produces
the same *shape*, not the same bytes, and the transcripts show it: run 2's
uuids appear nowhere in run 1, same-membership groups serialize tens of bytes apart, and grouping
came out at **7 groups against run 1's 6**. Nothing below depends on the stores being identical, but
the note may not call a control something the evidence shows it was not.

**The consolidator's whole task prompt was two sentences**, and both matter:

```
Consolidate this project's memory journal. Work through every group until
mcp__zikaron-consolidator__zikaron_next_group answers {"done": true}, then report what you did.
```

**That whole prompt is the installed skill's own prompt block**, byte-identical including the line
break (`~/zk-spill-e2e/.claude/skills/zikaron-consolidate/SKILL.md` — nothing is installed into the Zikaron repository itself); the operator's entire typed message was its
first sentence. Neither sentence mentions spills, pointers, paths or files. So everything from the session through the skill to the spawn
prompt was the shipped flow — which makes this a stronger control than a hand-written prompt, not a
weaker one. Results read out of the transcript rather than from the agent's report, since asking is
what contaminated the first attempt.

- **3 of 7 groups spilled** — 64,492, 64,632 and 43,910 bytes — and the consolidator called `Read`
  on all three exact paths.
- **No `offset` or `limit` on any call**, so again a single read sufficed.
- **No prose between receiving a pointer and calling `Read`** — it did not deliberate about whether
  to trust the object. That is the strongest available form of the finding: not merely that it
  complied, but that the pointer raised no question for it.
- The agent's own summary never mentioned spills at all, because nothing asked it to.
- Outcome: 1 entry promoted, the other 11 merged into it across six merge calls, nothing unfinished.

So the no-balk result holds on the shipped guidance alone. What remains unknown is whether it holds
across models, and whether the prompt's naming sentence is load-bearing or merely harmless — an
accounting-free run *without* that sentence would separate those, and was not done.

**Release is verified in the lifecycle that defeated `atexit`; the sweep is not.** After this run the
runtime directory held no spill files for this store, and every removal is attributable to
`release_finished`: each spilled file went on the `next_group` call that followed it, and further
groups arrived **inline** after the last spill — so the terminal `{done: true}` call found nothing
left to release. All of it happened before the harness terminated the process, which is the
lifecycle that matters. (`spill.py`'s docstring describes the ideal run, where the *last* group
spills and the terminal call releases it; this run was not that shape, and an earlier version of
this paragraph transplanted the docstring's description onto it.) **`sweep_stale` did not fire in
production** — run 1's four stale files were deleted by hand during reseeding, so there was nothing
for it to find. It remains verified only in the hermetic tier. Recording the distinction because
conflating the two is how the `atexit` claim survived nine review rounds.

## And the cleanup did not work

**All four spill files were still on disk afterwards** — 217 KB of verbatim record prose in tmpfs —
with the writing process (pid 905053) gone.

The mechanism was an `atexit` handler. The harness runs **one MCP server per session and terminates
it** when the session ends; a terminated process runs no `atexit` handler, and one killed outright
cannot. So the handler never ran in the only lifecycle that occurs.

**The hermetic test passed throughout**, because it spawns a subprocess that returns from `main` —
`atexit` fires there. It asserted a lifetime the production process never has. Nine review rounds, a
green gate at 97% coverage and ten verified mutations did not catch it; running it against the real
harness did, in one attempt.

The correction is two mechanisms that need nothing from the dying process — release the previous
group's files when the next group is requested, and sweep a dead predecessor's when a consolidator
starts. Both in `design/build-plan.md` §M18 §Lifetime.

## The approval gate: it prompts

**Measured in an operator-driven session in default permission mode: Claude Code asks before
letting the consolidator `Read` the spill file.** The installed `permissions.allow` grants
`mcp__zikaron` and `mcp__zikaron-consolidator` and nothing for `Read`, so the harness gates the
call. Every earlier run missed this because it ran with the gate pre-answered — three headless under
`--permission-mode bypassPermissions` and one operator-driven under `permissionMode: auto`
(`6ccd7dd5…`) — which is why this needed a human and could not be settled headlessly (`claude-code-installer-probe.md` §8 says as much).

The prompt offers three options — **captured by the operator from the terminal, since a harness
permission dialog appears in no transcript** — and the middle one is what makes this cheap:

```
1. Yes
2. Yes, allow reading from /run/user/1000/zikaron during this session
3. No
```

**Per-directory and per-session**, so one answer covers a whole consolidation rather than one
spilled group. That is what decided it: the argument for shipping a `permissions.allow` entry was
that repeated prompts would drive operators into auto-accept mode, which grants everything — and
option 2 removes that pressure. The decision, with its reasoning, is in `design/build-plan.md`; the
installer now warns that the prompt is coming.

## Windowed reading — and what the consolidator used it for

Both operator-driven sessions read spill files in windows, and **five of the six windowed serves
never reached the file's end** — where all seven headless serves were whole-file reads. Coverage,
from each `Read` result's own `startLine`/`numLines`/`totalLines`:

Labels are fragments of each spill file's random filename segment.

`6ccd7dd5...`
```
53ee81e   whole                         1..39 of 39
7830172   whole                         1..46 of 46
a717ea6   limit=15 / offset=13 limit=10 / offset=22
                                        1..15, 13..22, 22..39 of 39    complete
59666bd   limit=11 / offset=11 limit=10
                                        1..11, 11..20 of 39            tail 21..39 unread
```

`ae45b47a...`
```
435740c   whole                         1..39 of 39
4c16b30   limit=30                      1..30 of 39                    tail 31..39 unread
a907e8d   limit=10 / offset=1 limit=1 / offset=13 limit=10
                                        1..10, 1, 13..22 of 39         lines 11-12, 23..39 unread
9558a32   limit=18                      1..18 of 39                    tail 19..39 unread
794e5d2   six windows                   1..7, 7..10, 12..17, 19..24, 24, 26..40 of 46
                                        skips 11, 18, 25; tail 41..46 unread
```

Across both: of **9 spilled serves, 3 were read whole, 1 was windowed to its end, and 5 stopped
early or skipped interior lines.** In `794e5d2` the offsets hop over exactly the three members'
`content` lines — the gists were read and the prose was not — and the group was then dispositioned.
Of the gate run's 11 spilled members, **4 were discarded with content unread.**

**This behaviour was acceptable, and the fixture is why.** These twelve entries are five paragraph
templates rotated and repeated, distinguished only by a run number; each session had already read
identical prose whole in its *first* spilled file. Recognising that the rest is duplicate content
and not re-reading it is the intelligent response to the input, and expecting a capable model *not*
to notice would be the unreasonable position. The defect is in the experiment, not the agent: the
fixture was built to be large rather than realistic, and its obvious degeneracy is what licensed —
and justified — the skimming.

**So what this measures is narrower than it first looks.** Capability is verified: `offset`/`limit`
against a real spill file works, and a file *was* windowed to its end. Compliance with the
pointer's "read it, to its end" is **not** measured either way — a degenerate corpus cannot test
it, and both headless runs on the same corpus read every file whole, so mode or context pressure
may matter too. Recorded because it is the first observation of the consolidator reducing members
to their gists, which is the design §Rejected declined to ship; two things bound it here. One is contingent on this run and
would need re-checking: the verb was `discard`, which D16 keeps recoverable, where a `merge` from a
skimmed file would be the destroy-prose-nobody-read case outright. The other is structural — the
never-lose guard requires a member's uuid and `expected_version`, which sit in its *header* above
the content line, so the floor is the header regardless of corpus.

## Not measured here

Whether the **cap-forced** continuation works through a real consolidator, per the section above.
Whether the no-balk result holds across models. Whether the prompt's "this pointer is Zikaron's
own" sentence is load-bearing — an accounting-free run with that sentence removed is what would
say.
