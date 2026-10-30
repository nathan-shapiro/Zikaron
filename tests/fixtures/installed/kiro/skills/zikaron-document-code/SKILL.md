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
is. A **zikaron-code-orchestrator** subagent does the work while you wait for its report: this
session is busy until the run ends.

## How to run it

You run nothing of it yourself: no planner, no documenter. Spawn the
**zikaron-code-orchestrator** subagent, giving it this prompt:

```
Run one documentation run with exactly these arguments, as written, and no others:
<the arguments>
```

Its first line is exactly as written. **Write its second line yourself**: the modules, `--include`,
`--exclude` and `--slice` you were asked for, as they were given and spelled as the usage line above
spells them, or nothing when none were. The orchestrator decides from that line which modules to
document. One request is one spawn, however many modules it names.

## The report

Relay each report when it arrives with its opening lines — one per module the run was asked for,
each naming the module, whether it is up to date and its knowledge base, a refused module's saying
it was refused and why — and whatever else in it the user must act on.

## Permissions

The orchestrator and each documenter may do only what this session's agent's rules allow: a spawned
agent's own rules add nothing to them. So this agent needs the `subagent` tool, to spawn the
orchestrator, and allow rules for `subagent`, `shell`, `fs_read`, and `fs_write` over the documents
directory, `code-knowledge/` by default. Its `tools` need not hold `shell` or `write`: a subagent's
call is decided by this session's rules, not by its tools. Where a rule is missing, the call it
covers asks here first, and a headless run refuses it. When a run ends with documents missing for
that reason, say so.
