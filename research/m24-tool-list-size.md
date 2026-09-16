# The size of the primary server's tool list, at twelve tools

**Measured 2026-09-16**, on the tree as M24 leaves it. Harness, re-runnable in one command:
`experiments/m24_tool_list_size.py`.

M24's brief asks for a probe *before* writing six more tools, on the grounds that twelve on one
server is new here and M16 measured that tools arrive **deferred** under Claude Code. **It was run
after rather than before, and that is worth saying plainly**: the code was written first and this
measures what it produced. What the brief was protecting against is a size the harness cuts, and
the number below is far enough from anything this corpus has measured as a limit that taking it
earlier would not have changed a decision — but that is a judgement made with the answer in hand,
which is not the same as the check the brief asked for.

## What was measured

Every tool each server registers, serialized as the transport serializes it — name, description and
input schema — in UTF-8 bytes.

| server | tools | description bytes | whole entries |
|---|---|---|---|
| primary | 12 | 14,971 | 18,594 |
| consolidator | 4 | 3,315 | 4,631 |

The largest single entry is `zikaron_knowledge_search` at 2,891 bytes; the smallest is
`zikaron_knowledge_rename` at 850. The primary row is skewed rather than flat — descriptions run
**457 to 2,498, mean 1,248** — so the mean describes no actual tool, and the three largest
(`knowledge_search` 2,498, `knowledge_status` 1,982, `knowledge_add` 1,891) are 43% of the budget.

**The primary row first read 14,840 / 18,461 and was re-taken at 14,971 / 18,594** after the
milestone's review rounds edited the shipped prose — a `~`-expansion clause in `add`'s description
among them. Both figures are correct for the tree they were taken on; neither is a property of the
project. **Re-run the harness rather than quoting either**, which is one command and is the whole
reason it exists.

## What it does and does not establish

**It establishes the size.** 18,594 bytes is the whole of what a harness is handed when it asks the
primary server what it serves.

**It establishes nothing about *cost*, which is the question that actually matters and is not
answerable in bytes.** What a description costs is occupancy of the context window on every turn of
every session, against a budget shared with everything else in that window. Two servers of equal
byte size can cost differently depending on what else is competing, and the reading is taken with a
context inspector against a real session. That measurement is owed and is the operator's;
`design/build-plan.md` §M25 carries the scope it feeds.

**It establishes nothing about delivery**, and the distinction matters because the two live in
different channels. The threshold this corpus has actually measured is for a **tool result** —
roughly 29,923 tokens delivered and refused past it, recorded in single-counted payload bytes
(`research/claude-code-mcp-result-truncation.md`). A tool *list* is not a tool result: it reaches a
model through the tool schema rather than through a message, and under Claude Code it arrives
deferred, which is a third behaviour again. So the tool-result figure is the nearest order of
magnitude this project holds and it bounds nothing here.

**What would establish it is a session with a real harness**, in the shape M16 and M18 used: install
into a throwaway project, start a session, and read what the model was actually given. That is an
operator-driven measurement rather than one this suite can take, and it is **not done**. Recorded as
owed rather than as satisfied.

## The one thing that is reassuring without being evidence

Nothing in the corpus reports a limit anywhere near 18 KB for this channel, and the measured
tool-result threshold — the only comparable figure there is — sits well above it. That is a reason
not to expect a problem. It is not a measurement that there is none.
