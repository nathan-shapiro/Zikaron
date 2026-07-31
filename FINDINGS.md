# FINDINGS — Zikaron: Memory for AI Assistants and Coding Agents

> Durable project memory, maintained by the **memory-researcher** agent. Captures problem framing,
> hypotheses, design decisions, build state, open questions, and references. This hub is kept
> **lean (~4k words)** because it loads into context every session: park long-form design in
> `design/<topic>.md`, literature in `research/` (via memory-assistant), and critique trails in
> `reviews/` (via memory-reviewer). Prune and compress rather than appending forever.

## What Zikaron is
**Zikaron** (Hebrew/Yiddish זיכרון — "memory, remembrance") is a memory system for AI assistants and
coding agents: memory that persists across turns, sessions, and projects, and that measurably improves
task outcomes under real budgets for tokens, latency, and correctness.

Target capabilities, provisionally:
- Remember **user-level** facts: preferences, working style, recurring instructions.
- Remember **project-level** facts: conventions, architecture, build/test commands, gotchas.
- Remember **episodic** facts: what was attempted, what failed and why, where the work stands.
- Recall the right subset **cheaply and at the right moment**, and keep it **fresh** as code changes.

Non-goals (explicit, to prevent drift): emulating human psychology, affect, or personality for its own
sake. Mechanisms from memory science are welcome only where they buy measurable task benefit.

## Relationship to the sibling project
`~/Memory` designs a **human-like** memory/affect system for character agents, where psychological
fidelity is the goal; it has a mature harness, design corpus, and review trail. Zikaron reuses its
*crew structure* and *mechanisms where applicable*, not its goals. Treat `~/Memory` as read-only prior
art. Log here anything mined from it, so provenance stays clear.

## Repository layout
- **FINDINGS.md** — this hub.
- **design/** — design docs, one per topic (`design/<topic>.md`).
- **research/** — full literature and prior-art notes, one file per brief (written by memory-assistant).
- **reviews/** — memory-reviewer critique trails, one file per artifact (the `self-review` skill).
- **.kiro/agents/** — the crew: `memory-researcher` (driver, ctrl+shift+m), `memory-assistant` (web
  research → `research/`), `memory-reviewer` (critique → `reviews/`), `py-runner` (command execution).

## Current state — resume here
**Phase: pre-design.** The agent crew and directory scaffold exist (2026-07-31). No architecture chosen,
no code, no stack committed. Nothing has been researched or reviewed yet.

## Open questions — the first real decisions
1. **Scope**: which agent/harness does Zikaron serve first — Kiro CLI itself, an MCP server usable by
   any agent, or a standalone library? This determines every integration constraint.
2. **Memory taxonomy**: what tiers exist, what is authored by the user vs. inferred by the agent, and
   what lives in git (reviewable, diffable) vs. a private store?
3. **Write policy**: what earns a durable write, and who decides — the agent mid-task, a sleep/consolidation
   pass, or the user via explicit confirmation?
4. **Recall**: proactive injection into the prompt vs. a retrieval tool the agent chooses to call, and how
   the per-turn context budget is allocated between them.
5. **Freshness**: how a memory is bound to code that will change beneath it, and how staleness is detected
   and repaired rather than confidently recalled.
6. **Evaluation**: what benchmark or ablation would show Zikaron helps. Needed *before* building, so the
   design has a target.

## References
_(One line per research note and review, added as they land: topic — key takeaway — file path.)_
