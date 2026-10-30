# Kiro gaps

> **What Zikaron does under Claude Code and not under kiro-cli.** Standing rule (operator,
> 2026-10-20): a feature built for Claude Code alone gets a row here **in the same change that
> builds it**, and a row leaves in the change that closes its gap. The gaps are closed together
> when that time is set aside, so this list is the whole of that work, not a selection from it.
>
> It carries what is missing, why, and what closing it takes. **What kiro was measured or
> documented to do is `design/harness.md`'s** — every *why* below points there or at the spec that
> states it, and is not restated here.

A row is one of two kinds, kept apart because they close differently:

- **Not built** — kiro offers what the feature needs, or nothing says it does not; closing it is
  Zikaron's work.
- **Harness limit** — kiro was measured or documented not to offer what the feature needs; closing it
  waits on kiro, and the row names what to re-check first.

| Feature | Under Claude Code | Kind | Why it is not under kiro | Closing it takes |
|---|---|---|---|---|
| The re-read nudge (D38) | a `PostToolUse` hook reminds the agent to re-read what it edited (`design/guards.md` §4) | harness limit | no post-tool output reaches the model under V3, on any exit code — `PostToolUse` after a shell, write, search or MCP call, nor `PostFileCreate` or `PostFileSave` — so every documented route is measured shut (`research/kiro-v3-probe.md` §6, §35, §36; `design/harness.md` §"The table") | re-checked when a kiro release names post-tool output reaching the model; then a re-read hook in `KIRO.guards` and its entry in the installer |
| The search reminder (D39) | a `PostToolUse` hook names the knowledge bases documenting what a search reached (`design/code-knowledge.md` §6) | harness limit | the re-read nudge's reason: no post-tool output reaches the model (`research/kiro-v3-probe.md` §6, §35, §36), so `KIRO.search_reminder` is `None` | re-checked with the re-read nudge; then kiro's search tools and their payload fields in `KIRO.search_reminder`, and kiro's hook entries in the installer |
| A code-knowledge run that leaves the session free (D39) | the skill has the session spawn `zikaron-code-orchestrator` in the background (`design/code-knowledge.md` §5.2) | harness limit | the orchestrator is built under kiro too, and the session spawns it, but kiro runs a subagent in the foreground and the parent waits, and runs one in the background only as a Workflow, which stays out (`design/code-knowledge.md` §5.2; `research/kiro-cli-v3-migration.md` §4) | Workflows taken in, or a kiro release that runs a subagent in the background |
| The write policy reaches a subagent of the user's own | `SubagentStart` delivers the subagent variant of the policy to every subagent but the consolidator (`design/harness.md` §"Subagents") | harness limit | kiro has no subagent trigger, and a subagent's own hooks never fire (`research/kiro-v3-probe.md` §12, §38); Zikaron's documenter and orchestrator carry the policy in their prompts, but a user's agent that declares the `zikaron` server holds the memory verbs and meets no policy (`design/code-knowledge.md` §5.4) | re-checked when kiro gains a subagent trigger |
| A project's own subagent-policy override | `write_policy.resolved_policy_text` reads the project's `.zikaron/write-policy.md` override at each `SubagentStart` (`design/write-policy.md`) | not built | the install fixes the shipped `SUBAGENT_WRITE_POLICY_PROMPT` at the end of the documenter's and the orchestrator's prompts (`design/build-plan.md` §M41-2 item 4), so an override reaches neither | the install rendering the override into both prompts, and re-running when it changes |
| The override's acknowledgement (D38) | an accepted `#ZIKARON-FORCE` override is acknowledged through `additionalContext`, which asks for the re-read of what the command changes (`design/guards.md` §3.4) | harness limit | nothing a pre-tool hook prints on exit 0 reaches the model (`research/kiro-v3-probe.md` §34), so the command runs and is not acknowledged; the find-replace denies carry the re-read ask instead (`design/guards.md` §3.5) | re-checked when a kiro release names exit-0 output reaching the model from a pre-tool hook |
| The guard start text reaches a subagent (D38) | the start text's group sits on `SessionStart` and `SubagentStart` (`design/guards.md` §5) | harness limit | kiro has no subagent trigger (`research/kiro-v3-probe.md` §12, §38), so a kiro subagent meets the rule first as a deny, which reaches it (§57) and teaches the override | re-checked when kiro gains a subagent trigger |
