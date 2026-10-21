---
name: zikaron-document-code
description: Write per-source-file documentation of this project's code into a knowledge base per module, through Zikaron's planner and a zikaron-documenter subagent per file. Use when asked to create, write or update the code's documentation — a module's, a directory's or the project's — or to bring it up to date after the code has moved. With no directory named it updates every documented module, or documents the whole project where none is.
---

# Document this project's code

```
/zikaron-document-code [<module>]... [--include GLOB]... [--exclude GLOB]... [--slice N]
```

This writes one document per source file of each module named — a directory of the project — into
the project's `code-knowledge/` directory, searchable as that module's own knowledge base. With no
module named it updates every module documented already, or documents the whole project where none
is. A **zikaron-code-orchestrator** subagent does the work in the background, so you stay free and
receive its report when it is done.

## How to run it

You run nothing of it yourself: no planner, no documenter. Spawn the
**zikaron-code-orchestrator** subagent — whichever tool this harness gives you for delegating to a
subagent, with `subagent_type: zikaron-code-orchestrator`; **if the tool offers
`run_in_background`, pass `true`**, and if it offers no such parameter, every spawn runs in the
background, which is expected — and give it this prompt, exactly as written:

```
Run one documentation run with exactly these arguments, as written, and no others:
$ARGUMENTS
```

Its second line is the arguments as they were given, empty when none were, and the orchestrator
decides from it which modules to document. One request is one spawn, however many modules it names.

**One run at a time in this session.** A request that comes while a run of yours is out is not
spawned then: say so, and spawn it when that run's report arrives. A second run would share this
session's 20 subagents with the first, which holds 19 of them while a batch is out, and could
document a module the first is documenting.

**A spawn refused because too many subagents are running** is made again when the next subagent of
this session reports, and never while a run of yours is out, since the rule above comes first —
the harness's *"Do not retry"* is kept, since nothing is spawned again at once, only once a report
has freed a slot — or, when this session has no subagent out, is answered by telling the user that
something else holds them. **A report saying the run stopped because the
session's subagents were all in use** is answered the same way, with the request repeated as it
was given; a module already up to date costs one planner run.

## The report

Relay each report when it arrives with its opening lines — one per module the run was asked for,
each naming the module, whether it is up to date and its knowledge base, a refused module's saying
it was refused and why — and whatever else in it the user must act on.

## Permissions

The planner's command and each documenter's write go through this session's permission mode, and
their prompts surface here, naming the agent asking: an interactive session is asked to approve the
planner's command when it first runs — and at later batches unless the user allows it for the
session — and the first document a documenter writes; under auto mode neither is put to the user,
the classifier deciding the command and an edit inside the project approved outright. A headless
run is asked nothing and is refused: it needs `--permission-mode bypassPermissions`, or
`--allowedTools` naming the planner command, the subagent tool, the file tools and Zikaron's own
server, and `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, without which a run that waits ten idle
minutes is stopped.
