# Claude Code harness probe — measured, 2026-08-16

**Harness:** Claude Code **2.1.233**, Linux, headless `claude -p` runs in a throwaway project at
`/tmp/zk-ccprobe`. Probe scripts and raw logs: `spikes/claude-code-harness/`.

**Why this file exists.** `research/claude-code-harness-contract.md` is the documentation reading of the
same questions, produced by `claude-code-guide`. On the single most load-bearing question — *can an MCP
server learn the session id* — the documentation reading said **no documented channel**, and the
measurement says **yes, `CLAUDE_CODE_SESSION_ID`, in every process, matching the hook payload exactly**.
Same shape as `research/kiro-mcp-lifecycle-probe.md`: documentation is not measurement. Read this file
first; read the contract file for the parts nothing here measured.

---

## 1. Session identity — the two-rung ladder ports intact

`CLAUDE_CODE_SESSION_ID` is exported into **every** process Claude Code spawns, and it equals the
`session_id` in the hook payload:

| Process | `CLAUDE_CODE_SESSION_ID` | Source |
|---|---|---|
| `SessionStart` hook | `ba129a77-…7ea4dd` | env; identical to payload `session_id` |
| `UserPromptSubmit` hook | `ba129a77-…7ea4dd` | env; identical to payload `session_id` |
| **MCP stdio server** | `ba129a77-…7ea4dd` | env (measured from inside the server process) |
| A **subagent's** Bash subprocess | `ba129a77-…7ea4dd` | env — the *parent* session's id, not its own |

So `KIRO_SESSION_ID` → `CLAUDE_CODE_SESSION_ID` is a **variable rename**, not a redesign.
`architecture.md` §"Both clients resolve the same label" holds verbatim: both clients read one variable
out of their own environment and agree by construction. Linked sessions, link coverage, the two
cross-client D30 signals and the per-session recall instrument all survive the move.

**The harness marker is measured too**, and it is what harness detection turns on: `CLAUDECODE=1` is
present in every process dumped above — 4 occurrences in `spikes/claude-code-harness/hook.log` (both hook
events) and 6 in `mcp.log` (both server starts) — alongside `AI_AGENT=claude-code_<version>_<role>`, whose
role suffix distinguishes `harness` (hook processes, MCP servers) from `agent` (a subagent's subprocesses).

**Two cautions, both measured.**
- The value is **overridden, not inherited**: a nested `claude -p` launched from inside another Claude
  Code session got its *own* new session id, correctly. Good.
- **`CLAUDE_PID` is *not* overridden.** In the nested run the MCP server reported `CLAUDE_PID=2255833`
  (the *outer* session's pid) while its actual parent was `2256639`. Do not use `CLAUDE_PID` for
  anything. `os.getppid()` is trustworthy; that variable is not.

## 2. Hook payloads — richer than kiro's, and the prompt field is `prompt`

`SessionStart`:
```json
{"session_id","transcript_path","cwd","hook_event_name":"SessionStart","source":"startup"}
```
`UserPromptSubmit`:
```json
{"session_id","transcript_path","cwd","prompt_id","permission_mode",
 "hook_event_name":"UserPromptSubmit","prompt":"<the user's text>"}
```

**The field is `prompt`, exactly as under kiro.** FINDINGS' migration note claimed `user_input`;
that is **refuted** — `hook/main.py`'s `payload.get("prompt")` needs no change at all.

**[Refuted 2026-08-18 — see `claude-code-dogfood-checkpoint.md` §11b. The payload `cwd` is present,
but it *wanders* with the agent's own `cd`, which is precisely what broke D17's store scoping: the
hook followed it while `zikaron-mcp` did not. `Path.cwd()` in the MCP client was not "correct" so
much as *different*. Both clients now resolve through `HarnessSpec.store_scope_dir`. Kept as written,
per this project's withdraw-in-place rule.]**

`cwd` is present on both, so D17's store scoping is unaffected. `CLAUDE_PROJECT_DIR` is also exported,
and for the MCP server `os.getcwd()` was the project directory — so `Path.cwd()` in `zikaron-mcp`
remains correct here as it was under kiro.

New fields with no kiro analogue: **`transcript_path`**, **`prompt_id`** (a stable id per user message,
present on `UserPromptSubmit` *and* on `SubagentStart`/`SubagentStop`), **`permission_mode`**, and
`source` on `SessionStart` (`startup` observed; `resume`/`clear`/`compact` documented, unmeasured).

`CLAUDE_ENV_FILE` is exported to `SessionStart` hooks only, pointing at
`~/.claude/session-env/<session-id>/sessionstart-hook-0.sh` — an unmeasured mechanism by which a
`SessionStart` hook can apparently export environment into the rest of the session.

## 3. Subagents — `UserPromptSubmit` does not fire for them, and identity is explicit

In a run where the main agent spawned a `probe-helper` subagent, `UserPromptSubmit` fired **once**, for
the user's own message. It did **not** fire for the subagent. `SessionStart` likewise fired once.

`SubagentStart` and `SubagentStop` fired instead, and both carry **`agent_id` and `agent_type`**
(`"probe-helper"`), plus `session_id` (the parent's), `prompt_id`, and on stop
`agent_transcript_path`, `last_assistant_message`, `stop_hook_active`.

Two consequences for D32's push-suppression rule:
- **The door it guards is closed by the harness.** No push fires into a subagent context, so a
  consolidator subagent cannot receive injected gists. The kiro rule (compare env id to payload id)
  is not merely unportable — it is **unnecessary** as long as we register nothing on `SubagentStart`.
- **If we ever do want per-subagent injection, identity is available and exact.** `agent_type` names
  the subagent, so a future rule can suppress *the consolidator specifically* instead of every
  subagent — the over-breadth `architecture.md` §"Subagent sessions" accepts and regrets.

**Cost, not yet paid for:** a subagent therefore never sees the injected write policy either, while
still inheriting the session's MCP tools. Under kiro, subagent `agentSpawn` fired and was deliberately
suppressed; here there is nothing to suppress and nothing to deliver.

## 4. MCP server lifecycle — per **session**, not per agent instance

Two `zkprobe` server processes were started in one session (pids 2256657 and 2256689), both children of
the same Claude Code process, both with the project directory as cwd; the tool call was served by the
second. **No server process was spawned for the subagent** — the subagent's tool calls would be served
by the session's existing server.

This **falsifies the premise `zikaron-mcp`'s takeover bridge rests on.** `research/kiro-mcp-lifecycle-probe.md`
measured kiro running one MCP server process *per agent instance*, which is what supplies a fresh
`_PlanBridge` guard per consolidator spawn, and what makes `(session_id, pid)` consolidation ownership
discriminate two consolidators in one session. Under Claude Code both properties are gone:
- `pid` is the same for every client in the session, so `(session_id, pid)` cannot tell a consolidator
  from the primary agent, nor one consolidator from another.
- `_PlanBridge`'s "at most one successful `plan_groups` per client process" becomes *per session*, so a
  second consolidation invocation in the same session gets no fresh takeover guard.

Unmeasured: why two processes start, and whether either restarts mid-session.

## 5. Hook stdout → context: it works, it lands *after* the user message, and the cap is 10,000 chars

Plain stdout on **exit 0** reaches the model for both `SessionStart` and `UserPromptSubmit` — verified
end to end by planting a secret word in the hook output and having the model repeat it.

In the transcript, hook output appears as an `attachment` of type `hook_success`, carrying `hookName`,
`hookEvent`, `content` (what the model sees), `stdout` (the raw bytes), `stderr`, `exitCode`, `command`
and `durationMs`. Ordering: `SessionStart`'s attachment precedes the user message; **`UserPromptSubmit`'s
attachment follows it**. Under kiro the injected block was placed *before* the user message, framed
*"I have gathered this context from valuable programmatic script hooks"*. Claude Code adds no such
framing sentence, and the late placement is the one `~/Memory` recommends — open question 4's stated
tension resolves in our favour here, by the harness's choice rather than ours.

**The size cap, bisected in one run with four hooks of different sizes:**

| stdout bytes | `content` the model sees | truncated? |
|---|---|---|
| 3,005 | 3,004 | no |
| 9,503 | 9,502 | no |
| 10,502 | 2,263 | **yes** |
| 16,001 | 2,263 | **yes** |
| 70,834 | 2,226 | **yes** |

So the threshold is **10,000 characters**, fixed — Claude Code's hook schema has **no
`max_output_size` field**, so the 65536 the installer explicitly writes into every kiro object-format
entry has no analogue and no way to be raised.

**Overrun is loud, not silent** — the opposite of kiro, and it changes the risk calculus of open
question 11. The model receives:
```
<persisted-output>
Output too large (69.2KB). Full output saved to: <…>/tool-results/hook-<uuid>-stdout.txt

Preview (first 2KB):
…
...
</persisted-output>
```
i.e. an explicit notice, a 2 KB preview, and a **path to the full output the model can read**.

**What this costs us.** The shipped write policy is 2,950 bytes and fits. A five-row push block of
ordinary prose gists fits. But the margin against the unbounded-gist defect (open question 11 — tokens
do not bound bytes, one `[UNK]` can be 4,000 characters) shrinks from 65,536 to **10,000**, a 6.5×
tightening. The byte bound on `gist` stops being a deferred nicety.

## 6. Tool gating — D32's mechanical enforcement is only half reproducible

Four configurations measured against two probe MCP servers (`zkopen`, `zkgated`) and two probe
subagents, Claude Code 2.1.233:

| Configuration | Result |
|---|---|
| Subagent frontmatter `tools: Bash`, asked to call an MCP tool | **`NOT-AVAILABLE`** — frontmatter `tools:` **does** restrict MCP tools |
| `permissions.deny: ["mcp__zkgated__peek"]`, main agent calls it | `No such tool available` — deny **unregisters** the tool, it is not merely blocked |
| Same deny, plus a subagent whose frontmatter grants exactly that tool | **Spawn refused**: *"would be spawned with zero tools — refusing… unrecognized [mcp__zkgated__peek]"* |
| Subagent frontmatter declaring its own `mcpServers:` block, server absent from `.mcp.json` | **Ignored** — the key has no effect; the tool never resolved and the spawn was refused |

So, for D32:

- **The half that carries D7's enforcement survives mechanically.** A subagent's frontmatter `tools:`
  genuinely restricts it, so the consolidator can still be given the four consolidation verbs **and
  no `search` or `fetch`**. That is the claim D32 exists to make — code picks the candidates, and the
  consolidator cannot wander outside the group it was handed.
- **The other half cannot be reproduced.** An MCP server must be registered session-wide in
  `.mcp.json` to be reachable by any subagent at all, so the primary agent necessarily also sees the
  four consolidation verbs. `permissions.deny` cannot claw them back from the primary alone: deny is
  global and removes the tool from the subagent too, breaking it outright. There is no per-subagent
  MCP registration to route around it.
- **Consequence, stated rather than papered over:** under Claude Code, "the primary agent cannot fire
  the expensive path on a whim" becomes **prompt-only**, where under kiro it was mechanical. The
  failure it guards against is a wasted expensive call, not a corrupted store — the never-lose guard,
  the receipts and the lease are all untouched.

## 7. Second round — three claims a review caught me asserting without measuring

Added 2026-08-16 after `reviews/claude-code-port-plan-review.md` round 1 flagged three assertions in the
port plan that this note did not support. All three are now measured, and one of them was **wrong**.

**(a) The 10,000 cap counts *characters*, not bytes.** §5's bisection used ASCII, where the two units
coincide — the review was right that this corpus has been burned by exactly that conflation before. A
payload of `MB-HEAD ` + 9,000 × `漢` + ` MB-TAIL` is **9,016 characters / 27,016 bytes**, and **both
markers arrived**, so 27 KB passed a cap that 10,502 ASCII characters failed. The budget is characters.
Note what this does and does not fix: it makes multibyte prose cheaper than feared, and it leaves open
question 11 exactly where it was — the defect is that *tokens* bound neither, and one `[UNK]` can be
4,000 characters, so the bound `gist` needs is a **character** bound.

**(b) `SubagentStart` injects into the subagent — but only through the structured channel.** Plain
exit-0 stdout, the channel `SessionStart` and `UserPromptSubmit` both accept, reached **nobody**: the
hook fired (one payload logged) and neither the subagent nor the parent could see the planted word.
Emitting `{"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":"…"}}` instead, the
**subagent reported the word verbatim and the parent still could not see it** — which is the isolation
the write-policy delivery wants. So this harness has **two output channels and they are not
interchangeable per event**; `hook/main.py` writes plain stdout for everything today and cannot keep
doing so. Whether `additionalContext` shares the 10,000-character cap is **unmeasured**.

**(c) A subagent's transcript records the concrete model, so an alias is recoverable.** A subagent whose
frontmatter said `model: haiku` produced assistant messages carrying
`"model": "claude-haiku-4-5-20251001"`. Beside the transcript sits `agent-<id>.meta.json` with
`{"agentType","description","toolUseId","spawnDepth"}`. So the model **actually used** by a consolidation
run is readable from the harness's own record rather than the model's self-report, which is what makes
shipping the moving `sonnet` alias defensible.

**(d) An unknown model id in subagent frontmatter fails LOUDLY, before any turn runs.** A subagent pinned to
`claude-not-a-real-model-xyz` was terminated at spawn with `[claude-code:unrecognized_model]` and *"There's an
issue with the selected model… It may not exist or you may not have access to it."* No fallback, no partial
output. **This is the opposite of kiro**, whose documented behaviour is to substitute its default — and
kiro's substitution is the sole reason `architecture.md`'s install-time `--list-models` check exists. Under
Claude Code the harness enforces no-silent-fallback itself, so the consolidator's model can simply be a
**pinned concrete id** and needs neither install-time validation nor per-run recording. `claude-sonnet-5` was
verified valid as a pinned id — the same string kiro already ships, so the field is not harness-varying data.

**(e) A subagent's self-report matched the transcript, and the reason matters more than the result.** A
subagent pinned to `model: haiku` answered `claude-haiku-4-5-20251001`, exactly what its transcript records.
n=1. But Claude Code injects the model id into the system prompt, so this is the model *reading* a
harness-supplied fact, not recalling itself — which is why a self-report was rejected as a provenance source
even though it happened to be right: it carries no information the harness does not already hold, while
adding a tool parameter D27 exists to refuse and a channel a model can paraphrase or be talked out of.

**(f) `additionalContext` does not share the 10,000-character stdout cap.** A `SubagentStart` hook emitting
**12,000 characters** of `additionalContext` delivered both its head and tail markers to the subagent intact.
Not bisected further, because the requirement is settled well below it: the shipped write policy is 2,950 B.
Recorded as **≥12,000, exact ceiling unknown**.

**(g) Only one MCP server process ever serves, and it does not respawn.** Two processes start (measured again:
pids 2266561 and 2266589 under one parent), but **all three tool calls across the session went to the second**,
including calls made after two subagents had run, and no restart occurred. This tightens §4's residual
materially: the fresh-guard-per-process takeover hazard requires a process that actually *serves* a forwarded
`next_group`, and only one process does. The never-serving process costs nothing either, since
`zikaron-mcp` opens no socket and makes no RPC until a tool is called. What stays unmeasured is whether a
*serving* server is ever restarted mid-session over a longer run.

**(h) The session id survives `--resume`, and `SessionStart` fires again with `source: "resume"`.** All four
payloads across an original run and a resumed one carried the identical `session_id`. Two consequences: the
per-session recall instrument accumulates correctly across a resume rather than splitting; and the write
policy is **re-injected** on resume. Re-injection is desirable rather than a defect — a resumed session may
have lost the policy — and it points at something kiro could not do at all: if `source: "compact"` fires as
documented (**unmeasured**), the policy is restored automatically after a compaction, which is the moment it
is most likely to have been dropped. Whether `/clear` mints a new session id is also **unmeasured** and would
matter to the instrument.

## 8. Not measured here

`PreCompact`/`PostCompact` payloads and whether they can inject (no compaction occurred);
`source` values other than `startup`; session-id stability across `/compact` and `--resume`;
`PostToolUse`/`PostToolUseFailure` injection behaviour; hooks declared in subagent frontmatter;
interactive (non-`-p`) sessions — every run here was headless, and M16's checkpoint is the interactive
confirmation rather than a probe. `SessionStart` `source` values other than `startup`/`resume` — in
particular whether `compact` fires, and whether `clear` mints a new session id. The exact ceiling of
`additionalContext` (≥12,000). Whether a *serving* MCP server ever restarts mid-session over a long run.
Why the first, never-serving server process is started at all.
(`permissions.deny` versus frontmatter `tools:` is now §6; unknown model ids §7d; the `additionalContext`
cap §7f; MCP serving behaviour §7g; resume §7h.)
