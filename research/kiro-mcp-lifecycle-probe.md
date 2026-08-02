# kiro MCP server lifecycle for subagents — measured 2026-08-02

**One MCP server process per agent instance.** Not per session, not per config, not shared with a
subagent. Each subagent spawn starts a **fresh** server process and that process exits when the
subagent finishes. All instances of one kiro session are children of the same `acp` process and share
the same `KIRO_SESSION_ID`; the **pid is the only thing that distinguishes them.**

This settles four premises the consolidation design rests on, and it corrects one sentence I had
written into `architecture.md` on the strength of an assumption. Raw records:
`research/kiro-mcp-lifecycle-probe.jsonl` (21 events). Harness:
`experiments/mcp-lifecycle/probe_server.py` plus two agent configs under that directory's own
`.kiro/agents/`.

## Why it was measured

Zikaron's consolidation lease is owned by a `(session_id, pid)` pair, its receipts are scoped by
`client_kind`, and its takeover path is triggered by a `plan_groups` call the consolidator's MCP client makes
before it forwards a serve — at most one **successful** such call per client process, re-attempted while it has
not yet succeeded. All three assume the consolidator's client is **its own process,
started per spawn**. This document measures the *process model*; **which moment** within a process's life that
call belongs at is a separate design choice, settled afterwards in `design/architecture.md`
§"Consolidation lifecycle" — and the eager handshake measured below is the reason it is not the moment the
process starts. Nothing had verified that. If instead one server served the whole session:

- two consolidators of one session would present the same `session_id` *and* the same `pid`, because
  they would literally be one process — collapsing ownership back to session-only, which is the hole
  the pair was introduced to close;
- `client_kind` could not be a per-process fact, since one process would serve both the primary
  agent's tool set and the consolidator's, and the server cannot see which agent's allowlist admitted
  a call;
- the per-process takeover guard would be a per-*session* guard, so the first consolidation would take
  over and every retry inside that session would reach `next_group`'s refusal again — the exact
  failure the bridge exists to prevent.

The earlier session-id probe (`research/kiro-session-id-probe.jsonl`) did not answer this. It recorded
five hook firings: payload `session_id`, `KIRO_SESSION_ID`, the `KIRO_*` key list, and ancestor chains.
No MCP server appears in any of its records. **A claim in `FINDINGS.md` that that probe showed
`KIRO_SESSION_ID` "present in … live MCP servers" was not supported by the cited file** — whatever
established it was an ad-hoc check that was never persisted. This document is that check, done properly.

## Method

A throwaway MCP server over stdio that answers `initialize`, `tools/list` and `tools/call`, and appends
one JSONL record per event — startup, every request, every tool call, and stdin close — carrying its
pid, ppid, argv, cwd, `KIRO_SESSION_ID` and every other `KIRO_*` variable. Its single tool,
`probe_ping`, returns the server's own pid to the model, so the *agent's* view and the *process's* view
can be compared rather than assumed to agree.

Two workspace agent configs, `mcp-probe-parent` and `mcp-probe-child`, each naming that server.
**The two `mcpServers` blocks are byte-identical** — same command, same args, same timeout, no `env`.
That is the control that matters: had they differed in any way, a second process might have been kiro
keying on the difference rather than on the agent boundary, and the experiment would have answered a
question nobody asked.

One fresh non-interactive session, run from the experiment directory so Zikaron's own crew was
untouched:

```
kiro-cli chat --agent mcp-probe-parent --trust-all-tools --no-interactive "<three steps>"
```

The parent called `probe_ping` itself, then spawned `mcp-probe-child` twice through the `subagent`
tool, each child calling `probe_ping` once.

## What came back

Three `startup` records, three distinct pids, one `ppid`, one session id:

| caller | server pid | ppid | `KIRO_SESSION_ID` |
|---|---|---|---|
| parent | 1355002 | 1354956 | `e6593bed-b740-4012-8add-fa249750a192` |
| child-1 | 1355020 | 1354956 | `e6593bed-…` (identical) |
| child-2 | 1355022 | 1354956 | `e6593bed-…` (identical) |

`argv` was identical across all three processes, so the separate instances are **not** an artifact of
differing config content. Each received the full handshake independently — `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`.

Lifetimes are strictly nested, and each child's server closed before the next opened:

```
parent server   :28 ─────────────────────────────────── :46    18.2 s  (the whole session)
  child-1 server      :32 ── :37                                5.4 s  (that subagent's duration)
  child-2 server                 :39 ── :45                     5.7 s
```

Event order, from the monotonic clock: `1355002 startup`, `1355020 startup`, `1355020 stdin_closed`,
`1355022 startup`, `1355022 stdin_closed`, `1355002 stdin_closed`. No process was alive afterwards.

Separately observed on the same machine, in another project that ships an MCP server: two concurrent
top-level sessions of one agent had **two** server processes, each a direct child of its own
`kiro-cli-chat acp`. And a `py-runner` subagent spawned from this repository's own session reported an
ancestor chain running through the **parent's** `acp` process, with the `acp` process set byte-identical
before and after — so a subagent gets no `acp` of its own, and its MCP servers are started by the
parent's.

## What this establishes, and what it does not

**Confirmed.**

1. **A subagent spawn starts a fresh MCP server process.** Two spawns of the same config gave two pids.
   So a per-process guard in `zikaron-mcp` is a **per-invocation** guard, which is precisely what the
   takeover bridge needs for its bound — at most one *successful* takeover per client process — to mean at
   most one per human action. The process supplies the **guard**, not a limit on RPC attempts: a failed plan
   rolls back, displaces nobody, and so must not consume it.
   Note what this does *not* license: the process boundary supplies the counter, not the moment — see the
   eager-handshake observation below, which is why the call is made on the first forwarded serve. `FINDINGS.md` open question 10's named experiment is
   this one, and its premise holds.
2. **`(session_id, pid)` ownership is sound and the pair is necessary.** One session id across three
   processes, three different pids. Session-only ownership would have made all three the same worker.
3. **`client_kind` can be a per-process fact**, because each config launches its own instance — so the
   consolidator's instance can be told, by its own config's `args` or `env`, that it is a consolidator.
4. **A consolidator's client is short-lived**, existing only for the span of its subagent. The
   long-lived component is `zikaron-service`, which is what D31 already assumes; the MCP client paying
   startup cost per spawn is acceptable because consolidation is manually invoked and off every
   latency-critical path.

**Not established, and one design sentence has to be narrowed because of it.**

`architecture.md` justified takeover partly by asserting that a cancelled model turn "leaves a
perfectly live process holding a lease it will never use again". This experiment measured **normal
completion**, not cancellation: on normal completion the subagent's server *exits*. Whether an
interrupted or cancelled turn tears the subagent down — and with it the server — is unmeasured. If it
does, a pid-liveness check would in fact detect a dead worker, which weakens that particular argument
for takeover.

What survives unconditionally is the *other* half: **a lease is a timer, so it cannot distinguish a
dead worker from a slow one**, and pid liveness carries a pid-reuse residual the corpus already names.
Takeover remains the operator's decision and does not depend on the cancellation case; the reasoning
recorded for it must not claim more than this file measured.

**Also unmeasured, and worth naming rather than assuming:** whether kiro ever restarts a server for its
own reasons mid-subagent (a crash, a timeout, a reconnect). If it does, the restarted process would carry a
fresh guard, and the next `next_group` it forwarded would consume it — a takeover with no human behind it. Nothing here saw such a restart in three instances, which is weak
evidence at that sample size.

## Cleanup

The harness is throwaway and lives under `experiments/mcp-lifecycle/`, including its own
`.kiro/agents/` so it is discoverable only from that directory and cannot alter this repository's crew.
The raw log is copied to `research/kiro-mcp-lifecycle-probe.jsonl` so no figure quoted above depends on
a file in `/tmp`.
