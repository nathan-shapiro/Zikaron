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
| The find-replace guard and the self-match rule (D38) | a `PreToolUse` hook denies a find-replace edit to an authored file, and a `pgrep -f`/`pkill -f` matching its own shell (`design/guards.md` §3, §9) | not built | under V3 a `PreToolUse` hook's exit 2 blocks the call, its stderr reaching the model (`research/kiro-v3-probe.md` §6), but the guards were kept to Claude Code (operator, 2026-10-06; `design/guards.md` §2) | the seam: kiro's tool names and payload fields carried by `HarnessSpec`, which today carries only Claude Code's triggers and matchers (`design/guards.md` §1); kiro's array hook entries in the installer; a live test |
| The re-read nudge (D38) | a `PostToolUse` hook reminds the agent to re-read what it edited (`design/guards.md` §4) | harness limit | under V3 a `PostToolUse` hook's exit-0 stdout reaches neither the model nor the event stream (`design/harness.md` §"The table") | a probe of the one documented route, a `PostToolUse` hook's stderr on a non-zero exit; if it reaches the model, as the row above |
| The search reminder (D39) | a `PostToolUse` hook names the knowledge bases documenting what a search reached (`design/code-knowledge.md` §6) | harness limit | under V3 a `PostToolUse` hook's exit-0 stdout reaches neither the model nor the event stream (`design/harness.md` §"The table"), so `KIRO.search_reminder` is `None` | the re-read nudge's probe; if it passes, kiro's search tools and their payload fields in `KIRO.search_reminder`, and kiro's hook entries in the installer |
| A code-knowledge run that leaves the session free (D39) | the skill has the session spawn a background `zikaron-code-orchestrator` (`design/code-knowledge.md` §5.2), whose model `--orchestrator-model` sets | harness limit | V3 runs a subagent in the background only as a workflow, and whether one subagent can spawn another is unmeasured, so the session that invoked the skill runs the loop (`design/code-knowledge.md` §5.2; `research/kiro-cli-v3-migration.md` §4) | a probe of nested spawning; if a subagent can spawn, the installer's `--orchestrator-model`, refused under kiro until then (`design/harness.md` §"The flags, and what each refuses") |
| Reasoning effort per agent | the documenter at `effort: medium`, the orchestrator at `effort: high` (`design/code-knowledge.md` §5.1, §5.4) | harness limit | kiro sets effort only globally per model (`design/code-knowledge.md` §5.1); it logs `effortOverride: false` beside a subagent's effort, a field no profile is documented to set (`research/kiro-v3-probe.md` §11) | a probe of what sets `effortOverride`; an effort field in a kiro agent config |
| The documenter on Haiku 5.5 | `haiku` (`design/harness.md` §"The table") | not built | `kiro-cli chat --list-models` lists `claude-haiku-5.5` (`research/kiro-v3-probe.md` §10), and the documenter has run on it there only headless, on one file (§17; `tests/test_install_kiro_live.py`), never on a module | a module-sized run on it; then `KIRO.documenter_model` moves to it, checked against the model list as every shipped model is |
| A document corrected in place | the documenter holds `Edit` (`design/code-knowledge.md` §5.1) | not built | under V3 `write` grants `str_replace`, which a hand-written documenter profile used to edit a file in place, headless (`research/kiro-v3-probe.md` §7, §17); the prompt still asks for an edit only where a tool can make one | the documenter prompt's edit clause made true for kiro, and a live run of it |
| The write policy reaches a subagent | `SubagentStart` delivers the subagent variant of the policy to every subagent but the consolidator, the documenter included, which holds the memory verbs (`design/harness.md` §"Subagents") | not built | no hook fires for a kiro subagent, and kiro has no subagent trigger (`research/kiro-v3-probe.md` §12) | the policy in the documenter's own prompt under kiro |
| An over-large consolidator result spilled to a file | the client writes it to a file and returns a pointer, and the consolidator holds `Read` (`design/architecture.md` §"A result too large to deliver") | not built | `consolidator_can_read_files=False`: every payload is returned inline, and what kiro does with an over-large result is unmeasured (`design/harness.md` §"The table") | a probe of what kiro delivers past its limit; if it truncates, a read tool in the consolidator's config and the spill as under Claude Code |
| A live test of code knowledge | `tests/test_code_knowledge_claude_live.py` runs the installed skill through a real `claude` | not built | — | an `integration_kiro` twin running the skill in a real kiro session |
