# Claude Code tool hooks: what reaches the model — probe

Measured 2026-10-06 on Claude Code 2.1.285, `claude -p --model haiku --permission-mode
bypassPermissions --output-format stream-json --verbose`, in a throwaway project under the session
scratchpad. Each hook message carried a nonce the model could not otherwise know; a message counts as
delivered when the model quoted its nonce back.

It settles two cells `research/claude-code-harness-contract.md` left open (PreToolUse visibility "unknown") or stated
from documentation (PostToolUse "cannot inject context on success").

## Hooks

- `PreToolUse`, matcher `Bash`: a Python script reading stdin JSON. On `sed -i` without the marker
  `#ZIKARON-FORCE` it printed `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"NONCE-DENY-JSON-7731: …"}}`.
  With the marker it printed `permissionDecision: "allow"`, a reason, and `additionalContext:
  "NONCE-PRE-CTX-5519: …"`.
- `PostToolUse`, matcher `Edit|Write|MultiEdit`: printed `additionalContext: "NONCE-POST-CTX-4412: …"`.

## Results

| Path | Delivered to the model? | How it appeared |
|---|---|---|
| PreToolUse `deny` + `permissionDecisionReason` | **Yes** | As the tool result itself: `PreToolUse:Bash hook error: NONCE-DENY-JSON-7731: …`. The command did not run |
| `deny` under `bypassPermissions` | **Still blocks** | The hook received `permission_mode: "bypassPermissions"` and its deny held |
| PreToolUse `allow` + `additionalContext` | **Yes** | Not in the tool result text (`(Bash completed with no output)`), but quoted verbatim by the model, so it arrived beside it |
| PreToolUse `allow` + `permissionDecisionReason` | **Not quoted** | `NONCE-ALLOW-REASON-2210` never appeared in the model's reply |
| The in-command marker `#ZIKARON-FORCE` | **Works** | A trailing shell comment; `sed` ran and the file changed |
| PostToolUse `additionalContext` after a successful `Edit` | **Yes** | Quoted verbatim; the edit's own result text was unchanged |

## The override without a decision — second probe, same day

A `PreToolUse` hook that, on the marker, prints **only** `{"hookSpecificOutput":{"hookEventName":
"PreToolUse","additionalContext":"NONCE-NODEC-6603: …"}}` — no `permissionDecision` — run once per
mode with the same command:

| Mode | Outcome |
|---|---|
| `bypassPermissions` | The command ran; the model quoted `PreToolUse:Bash hook additional context: NONCE-NODEC-6603: …` |
| `default` | The harness's own flow took over: the tool result was *"sed in '…/t2.txt' needs approval"*, as with no hook at all |

So returning no decision leaves the user's permission policy exactly as it was, while
`additionalContext` still reaches the model. Returning `allow` would have skipped that approval.
The `PreToolUse` payload's keys, both modes: `cwd`, `hook_event_name`, `permission_mode`,
`prompt_id`, `session_id`, `tool_input`, `tool_name`, `tool_use_id`, `transcript_path` — **no
scratchpad path**.

## Does the payload's `cwd` follow a `cd`? — third probe, same day

Three separate Bash calls, `cd sub`, `pwd`, `pwd`, with a `PreToolUse` hook logging `cwd`: the
first payload carried the project directory, the second and third carried `…/sub`. **The payload's
`cwd` follows a `cd` made in an earlier call**, so a relative path in a later call resolves against
the directory the shell is actually in. Only a `cd` inside the same command can mislead it.

## Facts a design will need

- **`additionalContext` is absent from the `stream-json` output.** It is recorded only in the
  session's transcript under `~/.claude/projects/<project>/<session>.jsonl`, as an `attachment`
  entry whose `rendered` content is `<system-reminder>\nPostToolUse:Edit hook additional context:
  …` — so a test of the nudge reads that file, not the stream. The deny reason, by contrast, is the
  `tool_result` in the stream. Re-derive: `grep -o '.\{200\}NONCE-POST-CTX' <transcript>`.
- The Edit tool's own result now reads *"file state is current in your context — no need to Read it
  back"*. A nudge to re-read surroundings competes with that sentence in the same turn.
- PostToolUse stdin for `Edit` carries `tool_response` with `filePath`, `oldString`, `newString`,
  `originalFile`, `structuredPatch`, `userModified`, `replaceAll` — so the edited line range is
  computable deterministically, without reading the file.
- **`Write` says whether it created or overwrote**: its `tool_response.type` is `"create"` for a new
  file (empty `structuredPatch`) and `"update"` for an overwrite (a full hunk). Measured with a second
  run of the same setup, a `PostToolUse` hook dumping the payload.
- The documentation, read the same day (`research/claude-code-tool-hooks-docs.md`), agrees with
  every row above, and so refutes both of the contract note's cells this probe measured. It names `additionalContext` on
  `PostToolUse` explicitly; only plain exit-0 stdout is debug-log-only.
- Not measured here: the exit-2/stderr path, subagent sessions, `MultiEdit`/`Write`/`NotebookEdit`, and
  a model that was not told to report hook messages.
