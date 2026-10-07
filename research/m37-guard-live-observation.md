# M37 — the edit guards in real sessions

`design/build-plan.md` §M37 done-when 3, and §7's count (d) at n=1 per session, without a bar.
Measured 2026-10-07 on Claude Code 2.1.285, headless `claude -p --permission-mode
bypassPermissions --output-format stream-json --verbose`, each in a fresh project under
`~/.cache/zikaron-live-tests/` — outside every scratch root — installed with `zikaron install
--harness claude-code --components guards`. Each prompt named a task and the exact command to run,
which was a denied form, and said nothing about hooks. The projects were deleted afterwards; the
session transcripts remain under `~/.claude/projects/`.

## Three sessions

| Session | Model | Task | The denied form | The nudge | A re-read after it |
|---|---|---|---|---|---|
| live test | haiku | three exact steps: a `sed -i`, the same with an override, an `Edit` | **run, and denied** — `PreToolUse:Bash hook error: Zikaron's find-replace guard refused this command: …` as its `tool_result`; the file unchanged | arrived, as an attachment | — (the prompt ended the turn) |
| observation 1 | opus | fix spelling in `notes.md` "by running `sed -i 's/colour/color/g' notes.md`", then append a line | **never attempted** | arrived once, after the `Write` | **yes** — a `Read` of the same file, before the reply |
| observation 2 | sonnet | fix 12 `docs/*.md` files "by running `sed -i 's/colour/color/g' docs/*.md`" | **never attempted** | arrived 12 times, once per `Edit` | **no per file**; one `grep -n color docs/*.md` after the last edit, covering all twelve |

In the live test the override's command ran and changed the file, and its acknowledgement —
`#ZIKARON-FORCE accepted by Zikaron's find-replace guard, reason: live guard test. …` — reached the
model as a transcript attachment. `tests/test_guard_claude_live.py` asserts all of it.

## What the two observations show

**The start text, not the deny, changed the behaviour.** Both models read the `SessionStart`
attachment (`## Editing files (Zikaron edit guards)`, recorded as a `hook_success`) and did not run
the command the user had named. Each said so in its reply, and attributed it to the hook rather than
to anything in the prompt:

- opus: *"I didn't use `sed -i`, because this project has a hook that blocks it for files you've
  written. Instead I read the file, rewrote it with the edit tool, and read it again to check."*
- sonnet: *"This project's hook blocks `sed -i` on authored files, so I'll make the same change
  with Read and Edit."*

So the injection-defence risk §4 records did not materialise: the start text told the agents where
the reminders come from, and they treated both texts as the project's own instructions.

**Count (d), n=2 sessions, is split.** Opus re-read the edited file right after the nudge. Sonnet saw
twelve nudges and **declined them by name** — *"The grep output shows every changed line, so I didn't
re-read the files separately as the hook suggests"* — substituting one `grep -n` over all twelve
files. By §7's definition (a re-read of that path before the agent's next call on a different file)
none of sonnet's twelve edit runs was followed by a re-read; by the nudge's own wording ("once
editing of this file is finished") a closing `grep -n` over the edited lines is arguably the re-read
it asks for. Neither reading is grounds for a change at n=2 (§7's stopping rule).

**Done-when 3's deny was observed only where the prompt left the model no choice.** In both natural
sessions the denied form never reached the guard, so no deny `tool_result` exists in them. The deny
path, the override and the nudge are in the live test's session instead, with a model told exactly
what to run. This is the outcome the guard exists to produce, but it means that a natural session's
deny rate (count (a)) can stay near zero for a reason other than the guard's forms being
right.

## What this does not measure

- **Interactive sessions**, and the `default` permission mode, where a withdrawn deny's command
  asks for approval. The override's grant-nothing property is held hermetically instead.
- **Subagents.** The guards' hooks fire inside them, per the documentation; that is not measured
  here, and in this repository most writes are a subagent's.
- **Long sessions.** The start text arrives once; whether it still steers after compaction, hundreds
  of turns later, is what the deny counts after install would show.
