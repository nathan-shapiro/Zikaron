# Feedback to Anthropic on agent-team hooks — draft for the operator

Drafted 2026-11-09 for `design/build-plan.md` §M43 item 12, from `research/teammate-hook-probe.md`;
item 4 added 2026-11-10 from the M43 in-process live run.
Sending it is the operator's act (`/feedback` in Claude Code); the text below is ready to paste.

---

**Agent teams: no hook can inject context when a teammate receives a message (Claude Code 2.1.311)**

Context: we inject per-prompt memory context through `UserPromptSubmit`'s
`hookSpecificOutput.additionalContext`. With `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, teammates never
get it. Measured with a logging hook that returns a unique token in `additionalContext` on every event,
delivery read from the transcripts (`hook_additional_context` attachments and `api-request-blob` rows):

1. In-process teammates: `SubagentStart` fires once per message the teammate receives, as the hooks
   reference says, but only the spawn run's `additionalContext` is delivered. Each later run's text —
   different every time — is recorded as `hook_success` and is neither attached nor sent (3 of 3).
   The docs say a re-run injects "only when the subagent's context doesn't already hold the copy";
   in practice a new copy is not injected either.
2. tmux teammates: no hook fires between a message's arrival and the teammate's first tool call.
   `UserPromptSubmit` does not fire for teammate messages on either backend.
3. No hook payload carries the incoming message text (`SubagentStart` has `agent_id` and `agent_type`
   only), and `prompt_id` is the lead's on every event of a team run, so a hook cannot tell messages
   apart.
4. An in-process teammate's `SubagentStart` gives its name as `agent_type`, not its definition, and
   its `subagents/agent-<id>.meta.json` — which has the definition as `spawnedAgentType` — is
   written only after that hook (5 of 5 spawns). So a hook cannot tell at spawn which definition a
   named teammate runs, and context meant for every subagent but one definition reaches that one too.

Request: a hook that fires when a teammate (or a resumed subagent) receives a message, carrying the
message text and the agent's identity, whose `additionalContext` is delivered with that message — or
`UserPromptSubmit` firing for teammate messages with an `agent_id`. Today the only workaround is a
`PreToolUse` hook that reads the teammate's transcript, which depends on undocumented file formats.

Separately, a tmux/in-process asymmetry: the same agent definition with `tools: Bash, Read` gets
`SendMessage` added automatically as an in-process teammate, but not as a tmux teammate, whose every
reply and shutdown approval then fails with "No such tool available: SendMessage".
