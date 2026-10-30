# kiro V3 probe round 2 — the interactive run (for the operator to drive, about 10 minutes)

Measures what headless runs cannot: a declined trust screen, a session id across compaction, and an
interactive resume, each with Zikaron's own install. Run every command from a fresh terminal with no
`CLAUDE*` variables, not one Claude Code spawned.

## Setup (done once, by the agent)

```bash
P=<an empty directory kiro has never been launched in>
mkdir -p "$P/.kiro/agents" && cd "$P" && git init -q .
VISUAL=true EDITOR=true kiro-cli agent create live -d .kiro/agents   # writes the profile before any editor
~/Zikaron/.venv/bin/python -m zikaron.install --project "$P" --harness kiro --agent "$P/.kiro/agents/live.json"
~/Zikaron/.venv/bin/zikaron init
```

`kiro-cli agent create` opens `$VISUAL` after writing the file; with `VISUAL=vim` it waits there.

## 1. A declined trust screen
1. `cd $P && kiro-cli chat --v3 --agent live`
2. On the trust screen, **decline** — whichever option does not trust the folder.
3. If a session opens, type: `List every tool you have whose name contains zikaron, or say there are none. Quote any memory instructions in your context.`
4. Note what the screen offered and what the agent answered. `/quit`.
5. Launch again exactly as in step 1. Note whether the trust screen asks again. This time **trust** it.

## 2. Compaction
In the session step 1.5 opened:
1. `Call zikaron_memory_search with the query "probe" and tell me what it returned.`
2. `/compact`
3. `Call zikaron_memory_search with the query "compaction" and tell me what it returned.`
4. `/quit`

## 3. An interactive resume
1. `cd $P && kiro-cli chat --v3 --agent live --resume`
2. `Call zikaron_memory_search with the query "resume" and tell me what it returned.`
3. `/quit`

The agent reads the rest from `$P/.zikaron/memory.db`, `hook.log`, `~/.kiro/logs/` and
`~/.kiro/workspace-roots/`.
