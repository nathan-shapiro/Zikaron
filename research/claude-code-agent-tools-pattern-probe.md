# Does a subagent's `tools:` line honor `Bash(ls:*)`? — probe

2026-10-21, Claude Code 2.1.304, headless (`claude -p --model haiku`), in a scratch `git init`
holding `a.txt` and `b.txt`. Three subagents, identical but for `tools:` — `Read, Bash(ls:*),
Bash(test:*)`, `Read, Bash(ls *), Bash(test *)`, and the control `Read, Bash` — each spawned by the
main session and told to run nine commands, one call each: `ls` with a missing operand, `test -e`
twice, `cat a.txt`, `touch made1.txt`, `ls a.txt && touch made2.txt`, `ls $(touch made3.txt)`,
`ls a.txt > made4.txt` and `ls a.txt; touch made5.txt`. Every command ran inside the subagent, by
its transcript, and what each did was read from its tool results and the files left behind.

| Permission mode | Control `Bash` | `Bash(ls:*)` | `Bash(ls *)` |
|---|---|---|---|
| `bypassPermissions` | all nine ran | all nine ran | all nine ran |
| `default` | `ls`, `test`, `cat` ran; all five writes refused | the same | the same |
| `auto` (the operator's `defaultMode`) | all nine ran | all nine ran | all nine ran |

**A `Bash(...)` pattern on an agent's `tools:` line grants the whole `Bash` tool.** In every mode
the two pattern agents behaved exactly as the control did: `cat` ran, and `touch`, a redirection,
`&&`, `;` and `$(…)` either all ran or were all refused. Where something was refused, the control
was refused too, so the refusal is the permission mode's — `default` auto-approves read-only
commands and refuses the rest headless, with *"A nested command in this command can't be checked
before it runs"* for `$(…)` and *"Output redirection to …"* for `>` — and never the `tools:` line's.
Nothing reported the pattern as ignored.

**So the line cannot give the documenter a shell limited to `ls` and `test`**: granting one gives
it every command its session's mode allows, which under `auto` is anything the classifier passes.
No agent this repository ships or runs carries such a pattern.
