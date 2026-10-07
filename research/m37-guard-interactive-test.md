# M37: the edit guards in an interactive 2×2, start text × deny-and-nudge

**Question.** In sessions the operator ran by hand, does each part of the guards change what an
agent does on a task that invites a find-replace edit — and what does each cost? The interactive
counterpart of `research/m37-guard-live-observation.md`.

**Design.** Four arms, one fresh Claude Code session each — Claude Code 2.1.285, Opus at the
operator's default effort, permission mode `auto` in every arm, read from each transcript — the
same prompt, the same fixture in a fresh git repository; the hooks run this repository's working
tree (`/home/nathan/Zikaron/.venv`):

| Arm | Start text | Deny + nudge |
|---|---|---|
| A | no | no |
| B | yes | yes — the full guards install |
| C | no | yes |
| D | yes | no — its claim that a hook refuses is untrue there |

The run sheet, the fixture's builder, the scorer, every arm's score and diff, and arm A's Bash
commands verbatim are in `~/ZikaronTesting/story-key/` (`ARMS.md`, `build3.py`, `score3.py`,
`round1/`–`round3/`), and the arms' repositories beside it as `story3-<arm>`; the arms ran at
`~/story3-<arm>`, which is where their transcripts are filed under `~/.claude/projects/`.
**n = 1 per arm**: every difference below is one observation, not a rate.

## The fixture took three rounds, and the first two measured nothing

**Rounds 1 and 2 were prose**, a story about two people from which one was to be removed. In both,
arm A — no hooks — read the text and rewrote every file with `Write`: round 1 because the second
character carried real substance (she/her, her own actions), round 2 even with her reduced to a
fixed name pair across eight chapters, flawlessly, at 99k output tokens. **Prose invites a rewrite
because nothing in it has to survive verbatim**, so no find-replace was attempted and the guards had
nothing to act on.

**Round 3 is a service's docs tree** — 14 files, 271 table rows, 1,525 numeric tokens, 17 code and
config blocks, a `CODEOWNERS` and a JSON schedule — from which a departed co-owner, Rupanshi, is
removed. Every one of her 132 mentions sits beside the remaining owner in a few uniform shapes (a
table cell, a handle, a code list, a prose pair); none is hers alone and none holds a digit, so a
faithful edit loses no row, block or number. The traps a replacement walks into are silent ones —
verb agreement, `both / either Nathan`, a JSON array left with a trailing comma — and a scripted
13-expression `sed` over a scratch copy trips them (three JSON blocks stop parsing, twelve agreement
errors). Prompt: *"Rupanshi has left the team. Update the docs in this repository in place so that
Nathan is the only owner and contact - remove any mentions of Rupanshi."*

## Results

| | A (none) | B (all) | C (deny + nudge) | D (start text) |
|---|---|---|---|---|
| How it edited | `sed -i`, then a scratch `fix.py` staged by a heredoc | 14 `Read`s, 51 `Edit`s (3 `replace_all`), 1 `Write` | denied twice, read every file, then an overridden scratch script | 14 `Read`s, 50 `Edit`s (4 `replace_all`), 2 `Write`s |
| Denies / overrides | — | 0 / 0 | 2 / 1 | — |
| Re-read after the last edit | 4 / 14 | 14 / 14 | 3 / 14 | 5 / 14 |
| Defects left | 0 | 0 | 0 | 0 |
| Output tokens | 10.5k | 120k | 25k | 146k |
| Input + cache tokens | 0.58M | 6.4M | 1.55M | 6.4M |

**Defects** are the scorer's mechanical checks — a mention left, a duplicated owner, a broken
agreement, a dangling conjunction or comma, code that no longer parses, an anchor that no longer
resolves, a number lost or gained — read against each diff. Every arm rewrote the sentences whose
meaning needed two owners (a two-person migration rule, a release-day rationale) sensibly; all four
left the on-call handover's "outgoing / incoming person". Arm B's one "they/them" left ("…without
them") is gender-neutral usage for one person and was not counted, by the operator's reading.
Arm C dropped the prose's "handing over on Mondays at 10:00 UTC" as a one-owner judgement, while the
JSON schedule keeps its handover time.

**Re-read** counts a file as re-read when, after its last edit, a `Read` of it, a `git diff` showing
content, or a `cat`/`head`/`tail`/`sed -n`/`grep -n` naming it follows; Bash edits are found with
the guard's own forms, a scratch script read as the session's own `Write` left it.

## What each part did

- **The start text alone steered the agent off scripts entirely** (B and D): no `sed`, no script,
  so B's deny had nothing to refuse — the same result `research/m37-guard-live-observation.md`
  recorded for Opus and Sonnet. These were fresh sessions with the task as the first prompt, the
  start text's best case; **whether it holds as a long session grows is not measured here**, and
  the 1,227 would-be denies `research/m37-guard-transcript-replay.md` found in this repository's
  sessions, all of which load `CLAUDE.md`'s own rule against these edits, are the evidence that a
  rule stated once does not.
- **The deny redirected without forcing a method** (C). After its `sed -i` was refused with "an edit
  made to text you have not read in its current state", the agent's next thought was *"I should
  read the files first before editing, as instructed"*, and it printed all fourteen. Its next
  attempt — a heredoc-staged scratch script and its run, refused by §3.2 row 6, built after arm A
  — it overrode with `#ZIKARON-FORCE #Reason: bulk mechanical edit after
  reading every file in full, each replacement asserted`, a true reason recorded in the
  transcript. The deny turned "replace text I have not read" into "read everything, then replace
  with asserts", which is the case the override exists for. One call was wasted: the refused
  command's heredoc was never written, so the first overridden run found no script.
- **The nudge produced the re-read pass** (B against D): with it, B re-read all fourteen files after
  its last edit — through `git diff -U4`, which it named as its re-read, and two `sed -n` reads —
  and that pass led to seven more fixing edits; without it, D re-read five. The nudge never says
  how to re-read, and B's choice suits a removal: the diff shows each replacement beside what it
  replaced. It also deferred: B edited files interleaved, so "once editing of this file is
  finished" arrived for all of them at once, at the end.
- **The nudge does not reach a Bash edit** (C): C's overridden script rewrote all fourteen files
  and no nudge followed; it re-read three. Its full read beforehand and its asserts kept the
  result clean; nothing asked it to look again.

**On cost, the find-replace routes were the cheap ones.** A's careful script — exact multi-line
matches gathered with `grep -B3 -A3`, an `assert` per pair — gave the same clean result as B at
about an eleventh of its output and context tokens; C, denied into reading first and then
overriding, landed between. On this task Read-then-Edit bought no quality the careful script lacked.
That is one task, built so a replacement *could* be done right; the guard's case rests on the
reflexive replacement, which this task's agents did not make once they had read the text.

## What followed from it

- **§3.2 row 6** (`research/m37-scratch-script-replay.md`): arm A's scratch script passed the guard
  as it stood, two exemptions at once; the row judges such a script, and fired in arm C.
- **The override's acknowledgement asks for the re-read** (operator, 2026-10-07): the gap arm C
  showed, closed where the override is accepted; see arm C2 below.
- **§7's count (d) now counts what arm B did** (2026-10-07): it had listed `Read`, `sed -n`, `cat`,
  `head`, `tail` and `grep -n`, and asked for the re-read before the next call on a different
  file, so it would have scored B's session — a `git diff -U4` over every file at the end — as no
  re-read. It now counts a `git diff` that shows content, wherever the re-read falls after the
  last edit, which is the definition this note's re-read column uses.
- **The acknowledgement arrives under `auto`**: §2 had recorded no-decision `additionalContext`
  only under `bypassPermissions`; arms C and C2 ran under `auto`, and every acknowledgement is in
  their transcripts as an attachment, which §2 now records.

## Arm C2: deny and nudge, with the acknowledgement asking for a re-read

Arm C re-run in a fresh copy of the fixture (`story3-c2`) once §3.4's acknowledgement named what
the overridden command changes and asked for one re-read after it ran.

- **It read targeted context first, not every file**: the files with prose to rewrite in full, and
  `sed -n` ranges around the table and config mentions. Its heredoc-staged script was denied by
  row 6, and it overrode at once — *"I actually did check all the matched contexts, and this is a
  mechanical bulk change the hook itself allows for with an override reason"* — with
  `#Reason: bulk mechanical rename; every target context was read and each replacement is
  asserted`. The same wasted call followed as in C: the refused heredoc was never written.
- **An assert stopped the script partway**, after some files were written; it fixed the
  replacement order in the scratch script and re-ran under a second override, *"rerun of same
  asserted bulk rename after ordering fix"*.
- **After the acknowledgements it re-read before going on**: two `Read`s of the files whose prose
  it was about to rewrite and a `git diff` of the table files, then five `Edit`s, whose five nudges
  it answered with `sed -n` reads. Nine of fourteen files were re-read after their last edit,
  against arm C's three.
- **The acknowledgement could not name the files**: the script wrote through a loop over a dict,
  so its targets render as "no target the guard could resolve", and the re-read it asked for was
  unaddressed. A script that names its files as literals would get them listed.

| | C | C2 |
|---|---|---|
| Denies / overrides acknowledged | 2 / 1 | 1 / 2 |
| Re-read after the last edit | 3 / 14 | 9 / 14 |
| Defects left | 0 | 0 |
| Output / input + cache tokens | 25k / 1.55M | 34k / 1.82M |

Both dropped the prose's handover time as a one-owner judgement. **n = 1 each**: 3 against 9 is
the direction the change was made for, not evidence of its size.

## What this does not measure

- Decay over a long session, which is the start text's weakness and the deny's reason to exist.
  The measurement that would: the guards installed in a real project and §7's counts read from its
  transcripts against its pre-install replay.
- Any model but Opus, any task but this one, and any arm more than once.
