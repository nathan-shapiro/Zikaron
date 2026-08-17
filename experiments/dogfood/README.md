# The dogfood arm — a memory-naive agent, in a throwaway project

`zikaron-dogfood.md` is the Claude Code port of `.kiro/agents/zikaron-dogfood.json`. It is the
**control arm** of every instrument reading in this corpus: an ordinary coding agent whose prompt
says nothing about memory, so the only memory guidance it ever receives is the shipped write policy
the `SessionStart` hook injects. If it searches, it searched because the environment persuaded it to.

## It is tracked here, deliberately not in `.claude/agents/`

Under kiro the same file sat in `.kiro/agents/` harmlessly. Under Claude Code that directory makes an
agent **spawnable as a subagent of this repository's own crew**, and a subagent is a silently broken
control:

- `UserPromptSubmit` **never fires for a subagent** (`design/harness.md` §Subagents), so it would
  receive no push at all.
- A subagent gets **no MCP registration of its own** — a frontmatter `mcpServers:` block is silently
  ignored (`design/harness.md` §"Tool gating").

Both failures are invisible from inside: the agent simply never sees a memory and never has a tool,
which is indistinguishable from an agent that chose not to use them. Keeping the file out of
`.claude/agents/` is what stops that mistake being one keystroke away.

**It must run as a top-level session:** `claude --agent zikaron-dogfood`.

## No `tools:` key, and that is a decision

The kiro config listed its tools explicitly and had to, because omitting the `@zikaron` selector
there yields an agent with **no memory tools at all** — the failure
`tests/test_install_assets.py::test_the_tracked_dogfood_config_selects_the_memory_tools` exists to
catch.

Under Claude Code the failure mode **inverts**. Omitting `tools:` grants everything, including both
MCP servers; an *explicit* list that forgets `mcp__zikaron` is what would silently strip memory. So
the safe spelling here is the absent key, and the drift test asserts the absence rather than a
member.

Granting everything also means the agent sees `mcp__zikaron-consolidator`'s four verbs alongside its
own five tools. That is not a leak in this arrangement — it is the shipped condition, and the
accepted exposure `design/harness.md` §"Tool gating" records: under Claude Code an MCP server must be
registered session-wide to be reachable by any subagent, so the primary agent necessarily sees them.

## Setup

```bash
mkdir -p ~/zk-dogfood
cd /home/nathan/Zikaron
.venv/bin/python -m zikaron.install --project ~/zk-dogfood --harness claude-code
cp experiments/dogfood/zikaron-dogfood.md ~/zk-dogfood/.claude/agents/
cd ~/zk-dogfood && claude --agent zikaron-dogfood
```

`--harness` is stated rather than left to `auto` as a habit worth keeping; here the directory is
empty so `auto` has only the environment to go on, and a habit that works by luck is not a habit.

**The throwaway depends on this repository's venv.** The installer writes absolute paths to
`/home/nathan/Zikaron/.venv/bin/zikaron-hook` and `.../zikaron-mcp`, so rebuilding the venv
mid-experiment breaks the arm. And `~/zk-dogfood/.zikaron/memory.db` **is the evidence** — copy it
somewhere durable before deleting the directory.
