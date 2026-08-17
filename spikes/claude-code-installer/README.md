# Claude Code installer probe — scripts and raw logs

Evidence behind `research/claude-code-installer-probe.md`, kept in the repository for the reason
`spikes/claude-code-harness/` gives: **a grep that cannot see the evidence re-litigates it.** The
`.log` file is force-added past `.gitignore`'s `*.log`.

| File | What it was for |
|---|---|
| `sleeper.sh` | The timeout probe. Logs `START` and `END` around a sleep, so a **kill** is distinguishable from a completion, and prints a marker only on survival — which is what separates "the harness killed it" from "it ran and said nothing" |
| `timeout-ladder.log` | The run that bracketed the `UserPromptSubmit` default at **[30, 32)**: nine no-`timeout` entries sleeping 15…55 s, five of which logged `END`. Also shows all entries starting within 2 ms of each other, i.e. hooks on one event run in parallel |
| `probe-server-primary.py` / `probe-server-consolidator.py` | Two MCP servers under distinct `.mcp.json` keys, so the wildcard grant could be tested for *exclusion* rather than only for access |
| `bracketed.md` | Pinned to `model: sonnet[1m]`. It **spawned normally**, refuting the installer's own comment that a plain `[A-Za-z0-9._-]+` covers every id and alias either harness serves |
| `zk-gated.md` | The subagent granted `tools: [mcp__zikaron-consolidator]`. It reported exactly one tool and **zero** containing "search" — D7's enforcement half, measured |

**Not reproduced here:** the `settings.local.json` files each arm used. They are three lines and are
quoted in full in the research note; the scripts above are the part that would be tedious to
reconstruct.
