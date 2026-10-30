# Two transcript measurements: turns that end on a promise, and readers checking a document's source

2026-10-30, by memory-researcher, over the Claude Code transcripts of the four guarded projects —
`~/Trading/LeibaTrader`, `~/Memory`, `~/PythonPlayground` and `~/Dividends` — under
`~/.claude/projects/`, read only. LeibaTrader's are most of it: 42 main transcripts and 936
subagent transcripts, 323 MB, from 2026-08-18. Each section names the owed entry in `FINDINGS.md` it
answers.

## 1. Turns that end on a promise

**Question** (the owed stop guard): how often does a turn end with the agent announcing an action it
then does not take, so that the user has to say *"do it"*?

**Method.** In each main transcript, a turn ends at the last assistant message before the next
message the user sent — a prompt or a task notification, never a tool result. A turn whose last
message carries a tool call is skipped, as interrupted. The last message's text is screened two
ways.

| Screen | Turn endings | Flagged | Reading |
|---|---|---|---|
| **Broad**: *I'll*, *I will*, *Let me*, *I'm going to* in the last two sentences, an offer (*if you*, *want me to*, *say the word*) or a wait (*I'll report when …*) set aside | 5,658 | 538 promise, 172 offer, 132 wait | 30 of the 538, read at random: one ends on an immediate action not taken (*"Then I'll arm the monitor against D-1, synced+wait, class-flip and base."*); the rest wait on a run a monitor is watching (*"I'll report each month as it lands"*), offer (*"Say go and I'll run it"*), or state a standing practice (*"From now on I'll quote both totals over the same days only"*) |
| **Narrow**: the last sentence opens on an immediate action — *Let me*, *Now I'll*, *Then I'll*, *I'll now* — with no wait or offer word in it | 5,608 | **8** | Read whole, with the user's next message: **7 are the case**, all LeibaTrader's — *"Let me record all of this properly and take it back to the reviewer."* answered *"Makes sense - please do it"*, *"Let me record the ledger and take both back to the reviewer."* answered *"Yes please do it"*. The eighth waited on a background task, whose notification came next |

The two screens count turns slightly differently — the narrow one needs the user's next message —
hence 5,658 against 5,608.

**Result.** Between 7 and about 25 turns of 5,608 end on a promise not kept — 0.1% to 0.5%, the
upper end extrapolated from one hit in a sample of 30 — all in LeibaTrader, and almost all of the
same shape: the agent announcing it will record its findings, then stopping.

**By model**, from each turn's last message's `model` field: all 8 of the narrow screen's hits are
`claude-opus-5`'s, which ended 4,456 turns between 2026-08-17 and 2026-09-29, the last hit on
2026-09-17; `claude-opus-5-5` ended 1,143 turns since 2026-09-29, with none. At Opus 5's rate about
two would be expected in 1,143 turns, so none is what an improvement looks like — as the operator
observed (2026-10-30) — though by itself it is weak evidence: none would be seen about one time in
eight at the old rate.

**Implication.** A deterministic `Stop` guard would fire about once in several hundred turns, and
the narrow screen's one wrong hit in eight shows what it would cost: blocking a turn that is
legitimately waiting on background work. What the user pays per miss is one short message. Not
worth a guard; if it is worth anything, it is one line in the project's own agent prompt — not to
end a turn by announcing an action, but to take it — which is LeibaTrader's to write, not
Zikaron's.

## 2. A reader checking a code-knowledge result's source

**Question** (the owed reader's-verification measurement): where a session crosses unfamiliar code,
how often is a code-knowledge search followed by a read of the top result's source, and does it
decay late in a long session?

**Method.** Every `zikaron_knowledge_search` whose result holds a code-knowledge group, in main and
subagent transcripts. Its top code-knowledge result's `source.path`, resolved against the project
root, is counted as checked if one of the agent's next 20 tool calls reads it (`Read` of that file,
a `Grep` naming it, a `Bash` command naming its file).

| Who searched | Searches | Top source checked within 20 calls |
|---|---|---|
| `zikaron-documenter` subagents, all on 2026-10-20 | 92 | 2 |
| main sessions, LeibaTrader and `~/PythonPlayground` | 27 | 4 |

**The documenters' 92 are not readers.** They are the run of 2026-10-20 in which Haiku 5.5
documenters searched the corpus they were rewriting — the evidence for the documenter prompt's
*"Search no code-knowledge base"*, added that day (`design/code-knowledge.md` §5.1). No documenter
has searched code knowledge since.

**Result.** Readers searched code knowledge 27 times in all the transcripts there are, in five
sessions: 22 of them between 2026-10-16 and 2026-10-19, two on 2026-10-20, one on 2026-10-28, and
two undated. That is too few to say whether checking decays late in a session: a decay needs
searches spread across session lengths, and these are 27 in five sessions.

**Implication.** The measurement waits on reader traffic. The two live arms already owed — paged
knowledge search, and the closed-issue stage of the evaluation — would each produce hundreds of
reader searches under a fixed task, which is also where a decay would be measured against a
control; the same script applies to their transcripts.
