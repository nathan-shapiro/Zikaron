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
| The find-replace guard and the self-match rule (D38) | a `PreToolUse` hook denies a find-replace edit to an authored file, and a `pgrep -f`/`pkill -f` matching its own shell (`design/guards.md` §3, §9) | not built | kiro's `preToolUse` can block, exit 2 with stderr reaching the model, but the guards were kept to Claude Code (operator, 2026-10-06; `design/guards.md` §2) | the seam: kiro's tool names and payload fields carried by `HarnessSpec`, which today carries only Claude Code's triggers and matchers (`design/guards.md` §1); kiro's hook format in the installer; a live test |
| The re-read nudge (D38) | a `PostToolUse` hook reminds the agent to re-read what it edited (`design/guards.md` §4) | harness limit | kiro's `postToolUse` has no documented path to the model (`design/guards.md` §2) | a probe of whether a `postToolUse` hook's output reaches the model; if it does, as the row above |
| A code-knowledge run that leaves the session free (D39) | the skill forks to a background `zikaron-code-orchestrator` (`design/code-knowledge.md` §5.2), whose model `--orchestrator-model` sets | harness limit | a kiro subagent has no spawn tool, so the session that invoked the skill runs the loop (`design/code-knowledge.md` §5.2) | a kiro subagent that can spawn, or a kiro skill that runs in a context of its own; then the installer's `--orchestrator-model`, refused under kiro until then (`design/harness.md` §"The flags, and what each refuses") |
| Reasoning effort per agent | the documenter at `effort: medium`, the orchestrator at `effort: high` (`design/code-knowledge.md` §5.1, §5.4) | harness limit | kiro sets effort only globally per model (`design/code-knowledge.md` §5.1) | an effort field in a kiro agent config |
| The documenter on Haiku 5.5 | `haiku` (`design/harness.md` §"The table") | harness limit | `kiro-cli chat --list-models` offered no Haiku 5.5 on 2026-10-20 | when it does, `KIRO.documenter_model` moves to it, checked against the model list as every shipped model is; until the default moves, `--documenter-model` reaches it |
| A document corrected in place | the documenter holds `Edit` (`design/code-knowledge.md` §5.1) | not built | kiro's `write` is not measured to edit in place, so the prompt asks for an edit only where a tool can make one | a probe of whether `write`'s edit command works from the documenter's config; nothing to build if it does |
| An over-large consolidator result spilled to a file | the client writes it to a file and returns a pointer, and the consolidator holds `Read` (`design/architecture.md` §"A result too large to deliver") | not built | `consolidator_can_read_files=False`: every payload is returned inline, and what kiro does with an over-large result is unmeasured (`design/harness.md` §"The table") | a probe of what kiro delivers past its limit; if it truncates, a read tool in the consolidator's config and the spill as under Claude Code |
| A live test of code knowledge | `tests/test_code_knowledge_claude_live.py` runs the installed skill through a real `claude` | not built | — | an `integration_kiro` twin running the skill in a real kiro session |
