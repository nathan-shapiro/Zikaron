# Which hooks reach an agent-team teammate, and what they carry

Measured 2026-11-09 on Claude Code 2.1.311, for push to teammates (`FINDINGS.md` §"Current
state"). An operator drove one interactive session per backend in a throwaway project built by
`experiments/teammate_hook_probe.py setup DIR --backend {in-process,tmux}`: a logging hook on
`SessionStart`, `UserPromptSubmit`, `SubagentStart` (twice — a fresh nonce and a fixed text),
`SubagentStop`, `PreToolUse`/`PostToolUse` matched on `Bash`, `TeammateIdle`, `TaskCompleted` and
`Stop`, each context-capable event returning a nonce in `additionalContext`. The lead (sonnet)
spawned one haiku teammate and sent it three messages: run `echo one` and reply, run `echo two`
and reply, reply only; then shut it down. A nonce counts as **delivered** when the teammate's
transcript holds it in a `hook_additional_context` attachment *and* in an `api-request-blob` row —
the harness's record of what it injected and of what it sent. Neither model was asked about its
context: a prompt asking a model to list what is in its context was refused as
`reasoning_extraction`, and once refused a session stays refused. The docs' account is in
`research/claude-code-agent-teams-hooks-docs.md`.

Re-derive: `python experiments/teammate_hook_probe.py analyze ~/ZikaronTesting/teammate-hooks-in-process`.

## In-process (`--teammate-mode in-process`)

| Event, for the teammate | Fired | Its `additionalContext` |
|---|---|---|
| `UserPromptSubmit` | **never** — once, for the operator's prompt to the lead | — |
| `SubagentStart`, at spawn | yes | **delivered** |
| `SubagentStart`, at each later message | **yes, once per message** (3 of 3) | **never delivered** — a fresh nonce each time, recorded as `hook_success` and neither attached nor sent (3 of 3). The fixed text: 4 calls, 1 attachment |
| `PreToolUse` / `PostToolUse` | yes, every call, before and after each message | **delivered**, on every call, including the first call after each later message |
| `SubagentStop`, `TeammateIdle` | once per turn | no context channel |

So the docs' re-run rule is stricter than it reads: a later `SubagentStart` delivers nothing,
not merely nothing it has already delivered.

**What the payloads carry.** `SubagentStart`: `agent_id`, `agent_type`, `cwd`,
`hook_event_name`, `prompt_id`, `scratchpad_dir`, `session_id`, `transcript_path` — no message
text. `agent_type` is the **teammate's name** (`mate-1`), not its definition (`probe-mate`); the
definition is recorded only in `subagents/agent-<agent_id>.meta.json`, as `spawnedAgentType` and
`customAgentType`, equal, beside `taskKind: "in_process_teammate"`; an ordinary subagent's meta
file carries its definition as `agentType` and neither of the other two (LeibaTrader's 400 most
recent). `prompt_id` is the lead's prompt's id on every event
of the run, so it does not tell one teammate message from another. `session_id` and
`CLAUDE_CODE_SESSION_ID` are both the lead's on every teammate event, so the hook's tripwire
does not fire. `TeammateIdle` adds `team_name` and `teammate_name`.

**Where the incoming message is when a hook runs.** At each later `SubagentStart` (3 of 3), the
last `user` record of `<transcript_path without .jsonl>/subagents/agent-<agent_id>.jsonl` is
already that message, as `<teammate-message teammate_id="team-lead" summary="…">…`. At spawn the
file does not exist yet. Both inboxes, `~/.claude/teams/<team>/inboxes/*.json`, were empty every
time: a delivered message has left the inbox.

**Tool calls per prompt**, which prices a hook on every tool call: the five most recent sessions
each in `~/Memory` and LeibaTrader made 0 to 37 tool calls per `UserPromptSubmit`, main session
and subagents together; 11.5 to 33 in the seven with more than one prompt, the team run aside
(59f9a635: 1,367 + 5,485 against 209 prompts; cfe211e5, the team run: 155 + 139 against 8).

## tmux (`--teammate-mode tmux`)

Re-derive: `python experiments/teammate_hook_probe.py analyze ~/ZikaronTesting/teammate-hooks-tmux`.

The teammate is **a session of its own**: its own `session_id`, equal to its own
`CLAUDE_CODE_SESSION_ID`, and its own transcript beside the lead's in the project's directory
under `~/.claude/projects/`, not under the lead's `subagents/`.

| Event, for the teammate | Fired | Its `additionalContext` |
|---|---|---|
| `SessionStart` (`source: startup`), at spawn | yes, with `agent_type: probe-mate` — the **definition**, where in-process gives the name | **delivered** |
| `UserPromptSubmit` | **never** — each message arrives as a `<teammate-message>` user record, as in-process | — |
| `SubagentStart` | **never** | — |
| `PreToolUse` / `PostToolUse` | yes, every call, with `agent_type` and **no `agent_id`** | **delivered**, on every call |
| `Stop`, `TeammateIdle` | once per turn | no context channel |

Nothing in the environment tells this session from an ordinary one that a hook could test
cheaply: `CLAUDE_CODE_CHILD_SESSION=1` and `CLAUDE_CODE_MESSAGING_SOCKET` are set in the lead's
hooks too, and only `CLAUDE_CODE_SESSION_ATTENDED` differs (`1` for the lead, `0` here). A
`SessionStart` carrying `agent_type` is not a mark either, since `claude --agent` starts a main
session that way. The `<teammate-message>` user record is the mark common to both backends.

**A tmux teammate whose definition has a `tools:` allowlist has no `SendMessage`.** The same
`probe-mate` definition (`tools: Bash, Read`) got `SendMessage` added in-process and did not
here: every reply failed with `No such tool available: SendMessage`, the shutdown approval too,
and the lead advanced on idle notifications alone. A definition meant for tmux teammates has to
list `SendMessage` itself.

## Across both backends

- **No hook a teammate fires per message carries a push.** In-process, `SubagentStart` fires and
  delivers nothing after spawn; under tmux nothing fires at all before the first tool call.
- **`PreToolUse` and `PostToolUse` deliver on every teammate tool call under both**, and the
  message is by then the last `<teammate-message>` record of the transcript the hook can name —
  `subagents/agent-<agent_id>.jsonl` beside `transcript_path` in-process, `transcript_path`
  itself under tmux.
- **The spawn hook delivers under both** — `SubagentStart` in-process, `SessionStart` under tmux —
  but the spawn message is not in the transcript yet when it runs (in-process, measured; tmux,
  `SessionStart` precedes the first message).
- **The lead receives teammate messages the same way**, as `<teammate-message>` user records with
  no `UserPromptSubmit`: its log shows one `UserPromptSubmit`, the operator's.

## The gate's cost per tool call (M43 done-when 3, first part)

Measured 2026-11-09 on the build in `~/Zikaron-m43`, this host, load average 1.2–1.6. Three arms
interleaved round-robin, 100 runs each, a subprocess timed with `perf_counter` on each side: the
`PreToolUse` entry's gate line with no marker pending; `sh -c true`, the floor every hook entry pays
to be spawned at all; and `zikaron-hook` run ungated on the same `PreToolUse` payload, which finds
no marker and exits — what each tool call would cost without the gate. Re-derive:
`.venv/bin/python experiments/m43_gate_cost.py 100`.

| Arm | Median | p90 | Max |
|---|---|---|---|
| gate, no marker | 0.82 ms | 0.87 | 1.16 |
| `sh -c true` | 0.65 ms | 0.72 | 0.86 |
| `zikaron-hook` ungated | 56.71 ms | 60.54 | 70.39 |

So the gate costs a tool call 0.17 ms over a bare shell, and saves it about 56 ms: at the 11.5–33
tool calls per prompt above, about 10–27 ms of shell per prompt against 0.65–1.9 s of Python.
**What the harness itself pays to run an entry at all** — its spawn of the shell, the payload's
serialization, its await — is outside this measurement, which spawns `/bin/sh` from Python; this is
the first Zikaron entry with no matcher, so it pays that per-entry cost on every tool call where the
guards' `PreToolUse` pays it on `Bash` and `Monitor` alone. That cost is unmeasured; its
multiplier, the processes each new entry started against the tool calls and turns made, is in
§"Processes per tool call and turn".

## M43 live run, in-process (done-when 2)

Run 2026-11-10 by the operator on Claude Code 2.1.311, `--teammate-mode in-process`, permission
mode `auto` on every event, in a scratch project with M43's build installed from `~/Zikaron-m43`
and a three-record seed: two teammates of one definition spawned together, the session's own
ordinary subagent resumed once, the consolidator through its skill and once by name, then a
shutdown. Kit: `experiments/m43_live_run.py`, whose `analyze` re-derives every figure here from
the run's transcripts, its logging hook's `hooks.jsonl`, the store and `hook.log`.

- **Five pushes, each on its agent's first hooked tool call after an instruction, none twice**: each
  teammate's spawn message and later message, and the ordinary subagent's first prompt — five
  `surface_call` rows of `occasion: instruction`, beside ten of `prompt` — seven typed prompts and
  three subagent reports (the last bullet). Two messages sent to an
  idle teammate in quick succession arrived as one record and were pushed as one instruction.
- **Neither consolidator was pushed**, nor given a line in `hook.log`: the skill's, an ordinary
  subagent of `agent_type: zikaron-consolidator`; the one spawned by name, a teammate whose
  `agent_type` was its name and whose record named `zikaron-consolidator` in `spawnedAgentType` and
  `customAgentType`. **The one spawned by name became a teammate and idled** (`TeammateIdle`) until
  the shutdown, as `design/harness.md` §"Agent teams" says a named spawn does. **It received the
  subagent policy at its spawn**: its record does not exist at `SubagentStart` (5 of 5 spawns) and
  does at the first tool call (5 of 5), so the start text, which can read only `agent_type`, took
  it for a teammate.
- **The resumed subagent's second prompt was not pushed, and wrote `instruction_unread`.** Its
  `SubagentStart` fired; the prompt was a `user` record flagged `isMeta`, of `origin: {kind:
  coordinator}`, reading "The coordinator sent a message while you were working:", the prompt, and
  "Address this before completing your current task.", although the subagent had stopped. The
  reader passed it over as the harness's own and met the first prompt's tool result. Served since,
  by origin and those two lines, and replayed on the run's transcript to yield the prompt.
- **At every agent `PreToolUse` the transcript ended at the `api-request` record preceding the
  current response** (26 of 26, but see the second run), the call's `tool_use` not yet written and the payload's
  `tool_use_id` present. One call was refused by the harness before any hook — "Blocked:
  standalone sleep 30" — and the next call of the same response claimed the marker and read the
  two messages, its records being written about 100 ms after the hook ran.
- **No turn of an instruction this path serves made no tool call; one made `SendMessage` its
  first** — the reply-only message, pushed with the reply. The three shutdown requests were read as
  protocol and pushed nothing, with no line.
- **Not measured**: a message sent to a teammate while it is mid-task. The lead sent both of
  alpha's later messages in one response, before alpha's turn began.
- **Out of M43's scope, on the lead**: a subagent's report back (`origin: {kind: peer}`) fires the
  lead's `UserPromptSubmit`, three times in this run, so the prompt hook pushes on a report the
  operator did not type; a teammate's message to the lead fires nothing. 43 `PreToolUse` events, 26
  of them agents', in 236 s.

### The second in-process run

Run the same day on the same build with the resume served, `time.sleep(30)` in place of the bare
`sleep`, and a gap of about eighteen minutes between two steps, the operator's connection having
dropped.

- **Six pushes, `hook.log` empty, no marker left**: each teammate's spawn and later message, and
  the ordinary subagent's first prompt and **its resumed second prompt**, the record of the same
  shape as the first run's. Neither consolidator was pushed; the one spawned by name idled and was
  again given the subagent policy at spawn, its record absent at all five spawns' `SubagentStart`.
- **The lead again sent both of alpha's later messages in one response**, so they arrived as one
  record before alpha's turn; the mid-task cell is still unmeasured, and the kit now sends the
  second message as a prompt of its own during a 90-second wait.
- **A later call of a response runs its hook after the calls before it finish**: 25 of 27 agent
  `PreToolUse` hooks found the transcript ending at the `api-request` record, and the two that did
  not were second calls of their response, run 1.3 s and 30 s after the first, which found the
  response's records written, their own `tool_use` among them.
- One reply-only message made `SendMessage` its first call, as in the first run.

## M43 live run, tmux (done-when 2)

Run 2026-11-10 by the operator, `--teammate-mode tmux`, permission mode `auto`, the same seed and
build, with the mid-task message sent by a prompt of its own during a 90-second wait: two typed
teammates, a third spawned with no type, the session's own ordinary subagent resumed once, the
consolidator spawned by name, then a shutdown. `analyze` re-derives the figures.

- **Eight pushes, `hook.log` empty**: alpha's spawn message, its later message and the one sent
  mid-task; beta's spawn message and its reply-only message, pushed with the reply; the untyped
  teammate's spawn message, served by its transcript, its events carrying no `agent_type`; the
  ordinary subagent's first prompt and its resumed second, the resume record of the in-process
  shape. Eight `surface_call` rows of `occasion: instruction`, beside ten of `prompt`, eight typed
  prompts and the ordinary subagent's two reports.
- **The mid-task message waited for alpha's turn to end**: sent during the 90-second call, it
  reached alpha's transcript 0.1 s after the turn's last record; `TeammateIdle` marked alpha, and
  its next call pushed the message as an instruction of its own.
- **The consolidator spawned by name ran as a session of its own whose events carried `agent_type:
  zikaron-consolidator`**, the definition, as the probe measured: no start text, no push, no line.
  It idled as a teammate does.
- **Three markers were left**, each a tmux session's own — both typed teammates' and the
  consolidator's — set by their last `TeammateIdle`. The teammates' shutdown replies were refused
  by the harness before any hook ("message text must not be a teammate protocol frame"), so no
  call claimed the markers, and the lead ended the three with `TaskStop`. They are swept once past
  their 86,400-second limit.
- No turn of a served instruction made no tool call; one made `SendMessage` its first.

## M43 live run, default permission mode (done-when 2)

Run 2026-11-10 by the operator, in-process with `--permission-mode default`, every event's
`permission_mode` `default`: one typed teammate given a spawn message, a 90-second wait and a
message sent during it, then a shutdown. The operator approved the teammate's filesystem access
when asked. `analyze` re-derives the figures.

- **Three pushes, `hook.log` empty, no marker left**, one per instruction: the spawn message, the
  wait, and the message sent during it.
- **A call that asks for approval still carries the push** — `design/guards.md` §2's cell. The
  hook ran and its `additionalContext` was recorded as an attachment at once, the approval came
  after (about 9 s for the first call), and the block was sent with the approved call's result in
  the next request.
- **The message sent during the wait reached the teammate 0.2 s after its turn's last record**,
  as under tmux: the turn's `SubagentStop` fired, then the new message's `SubagentStart`, 0.1 s
  later, so the marker the stop cleared was not the new message's, and the next call pushed it.
  The one such case in-process; the order is what keeps the stop from clearing the new marker.

## Processes per tool call and turn (M43 done-when 3, remaining parts)

**What the new entries started**, replayed from each run's `hooks.jsonl` by the gate's own rule —
a marker pending for the event's session starts `zikaron-hook` — since the logger runs beside
Zikaron's hook and cannot see it start. Re-derive: `.venv/bin/python
experiments/m43_process_count.py ~/ZikaronTesting/m43-live-{in-process,in-process-2,tmux,default-mode}`.

| Run | Tool calls | `PreToolUse` `zikaron-hook` | `SubagentStop` shells, `zikaron-hook` | `TeammateIdle` `zikaron-hook` | Agent turns | Pushes |
|---|---|---|---|---|---|---|
| in-process | 43 | 12 | 12, 2 | 5 | 12 | 5 |
| in-process, second | 44 | 12 | 11, 0 | 5 | 11 | 6 |
| tmux | 51 | 11 | 2, 0 | 10 | 12 | 8 |
| default mode | 19 | 6 | 4, 0 | 3 | 4 | 3 |

Every tool call pays the gate's shell; `zikaron-hook` started on 41 of the 157, against 157
ungated. The 19 starts that pushed nothing were each session's first call claiming its start
marker, the consolidators' own claims, a shutdown request's first call, read as protocol, the first
run's resumed prompt, unread then, and calls made while another agent of the same in-process
session had a marker pending, which the session-wide glob lets through. An agent turn is one
`SubagentStop` with an `agent_id` or one id-less `TeammateIdle`.

**A `TOOL_CALL`'s wall time with a marker pending** does not follow the transcript's size. Measured
2026-11-10 in the tmux run's project, its service up, load average rising from 0.3 to 3.0, 50 rounds
of four arms interleaved, the installed `PreToolUse` entry's shell line through `subprocess.run`,
each marked run printing a block, in both orders of the two marked arms. Re-derive with
`.venv/bin/python experiments/m43_tool_call_time.py ~/ZikaronTesting/m43-live-tmux <the tmux lead's
transcript> 50`, adding `short-first` for the second order.

| Arm | Median | p90 | Max |
|---|---|---|---|
| marker, the runs' largest transcript (1,037,398 bytes, the tmux lead's), first in its round | 79.67 ms | 83.12 | 97.05 |
| marker, a 4-record transcript, second | 70.90 ms | 78.91 | 92.89 |
| marker, a 4-record transcript, first | 78.73 ms | 80.54 | 82.46 |
| marker, the largest transcript, second | 71.01 ms | 75.09 | 88.26 |
| another agent's marker pending, either order | 57.4 ms in both | 61.5–65.4 | 68.1–92.0 |
| no marker | 0.91 ms | 0.98–0.99 | 1.15–1.20 |

**The 8 ms between the marked arms follows their position, not the transcript**: whichever runs
first in a round comes after about 60 ms in which the service answered nothing, and the gap moves
with it. The reader alone takes 0.11 ms on the large file and 0.04 ms on the short one, since it
stops within the last block. A tmux teammate's and every lead's first call also read forward from
the file's start, stopping at its first unflagged string-content `user` record, which was at line 5
to 8 of every tmux transcript, so that path does not follow the size either.

A session's pushes are far apart, so the first-in-round figure is the one that applies: at about
79 ms for the 22 pushes, 57.4 ms for the other 44 starts and 0.91 ms for the 143 shells that
started nothing, the new
entries cost the four runs about 4.4 s of hook time in all, 28 ms a tool call on average, where an
ungated entry would have started `zikaron-hook` 157 times, about 9 s. What the harness pays to run
an entry at all stays unmeasured.

## What the pushed agents did with it

The seed made this decidable: the scratch projects hold no Makefile, no tests and no
`scripts/ship.sh`, so the three seeded facts had one source. **Every instruction that asked for one
was answered with it**, in all four runs, most replies attributing it to memory and several saying
it was unchecked against the code — tmux alpha: "Project memory says so, but I haven't verified it
against the Makefile". **Agents fetched a pushed record 14 times after the 22 pushes**: four in each
in-process run, six under tmux, none in the default-mode run, whose teammate answered from the
headline; tmux alpha's mid-task turn opened with a fetch by an id it knew from an earlier block.
`analyze` prints each pushed agent's fetches and replies. This is uptake in the degenerate case,
where the push is the only source and the question is the seeded fact: it shows agents read and
use a block, and says nothing about benefit over reading the code.
