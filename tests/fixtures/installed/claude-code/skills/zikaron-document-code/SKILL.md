---
name: zikaron-document-code
description: Write per-source-file documentation of one module of this project's code into a knowledge base of that module's own, by running Zikaron's planner and spawning a zikaron-documenter subagent per file. Use when asked to document a module or directory of the code, or to bring that documentation up to date after the code has moved.
context: fork
agent: zikaron-code-orchestrator
---

# Document this project's code

```
/zikaron-document-code <module> [--include GLOB]... [--exclude GLOB]... [--slice N]
```

This writes one document per source file under `<module>`, and a README for the module, into the
project's `code-knowledge/` directory, and makes them searchable as the module's own knowledge base.
A **planner** decides what needs writing; you spawn a **zikaron-documenter** subagent for each item
it lists and run it again, until it reports the module up to date. You write no document yourself
and you never decide what is out of date — the planner does, from hashes.

The module, its globs and any slice are the arguments this skill was invoked with. `<module>` is a
directory relative to the project root, written with no leading `./` and no trailing `/`, and `.`
for the root itself. **Its globs are part of what the module is**: pass the same `--include` and
`--exclude` on every run over it, because a narrower set makes the planner remove the documents it
no longer admits. `--slice N` is this skill's own word, for documenting only N files this time; it
is never passed to the planner.

## 1. Find the planner

The project root is the directory holding `.mcp.json` — the
directory you were started in. Read `.mcp.json` there and take `mcpServers.zikaron.command`: the
path of this project's `zikaron-mcp`. The planner is the `zikaron` in that same directory — the path
with its last component `zikaron-mcp` replaced by `zikaron`.

Call that path `<zikaron>`, and the absolute path of the project root `<root>` — its real path,
symlinks resolved, as `pwd -P` prints it there, which is the form the planner's `root` prints and a
knowledge base's `root_path` is stored in. Do not use a `zikaron` found on `PATH`: it may be another
install, one without this command.

Call the module's knowledge base `<corpus>`: `code-knowledge/<module>`, or `code-knowledge` when
`<module>` is `.`. Its directory, `<root>/<corpus>`, holds the module's documents. **Refuse a module
that nests** before the planner first runs: call `mcp__zikaron__zikaron_knowledge_status` with no name, and if a
knowledge base named `code-knowledge`, or with a name beginning `code-knowledge/`, has a
`root_path` that contains `<root>/<corpus>` or lies inside it, and is not that directory itself —
containment between directories, so `…/code-knowledge/src` does not contain
`…/code-knowledge/src-extra` — stop and report it: the module's documents would be indexed by two
knowledge bases, and returned twice by a search naming neither.

## 2. Run it in batches

Run this as a shell command:

```
<zikaron> code-knowledge plan --project <root> --module <module> [--include GLOB]... \
    [--exclude GLOB]... --apply --limit <n>
```

`<n>` is 19 plus the number of items you have given up on (step 4). **Never run it
without `--limit`**: a whole module's listing is longer than a harness shows of a command's
output, and a cut-off object cannot be parsed. **Always pass `--project` with `<root>` written
out** — not `$PWD` or `.`, which the shell resolves wherever it stands: otherwise the planner
resolves the shell's working directory, which may have moved.

It prints one JSON object. A non-zero exit is a refusal, its reason on standard error: report it
and stop. What you act on:

- `work` — the documents to write, each with its `kind`, `source`, `document` and `front_matter`;
- `readme` — the module README to write, or `null`; under `--apply` its `roles` names the file the
  planner wrote its documented files' role lines to, and from a dry run it is `null`;
- `up_to_date` — true once nothing is owed;
- `unverifiable` — sources whose hash could not be computed, which hold `up_to_date` false and
  which no documenter can fix;
- `git_mode_effective` — `all` when git was consulted and `.gitignore` applied, `off` when git
  could not be consulted, so `.gitignore` was not applied.

`removed`, `moved`, `foreign`, `unplaceable`, `skipped` and `remaining` are for your report;
nothing in them is yours to act on.

## 3. Spawn a documenter per item

For every item in `work`, yourself — never ask a documenter to spawn another —
spawn a **zikaron-documenter** subagent — whichever
tool this harness gives you for delegating to a subagent, with `subagent_type: zikaron-documenter`;
**if the tool offers `run_in_background`, pass `false`, and if it offers no such parameter, every
spawn runs in the background, which is expected** — giving it this prompt (a spawn that answers
that it is running in the background has not returned yet: its result arrives later as a message
of its own, and the harness keeps you running until every spawn of yours has reported, so wait by
issuing nothing — no polling the documents directory, no sleeping, no command or spawn to pass the
time):

```
Root: <root>
Source: <root>/<source>
Document: <root>/<document>
Front matter:
<front_matter, exactly as the item gives it>
```

Issue every spawn of a batch together, and **wait for every documenter to return** before running
the planner again. Each answers with one line: `written: <document path>`, or `not written:` and
what stopped it.

## 4. Repeat until it is up to date

Run step 2 again. The planner checks every document afresh — one never written is listed again as
`missing`, one cut off as `invalid` — so a documenter that failed needs nothing from you but the
next run, which lists its item first.

Count, for each item — by its `source`, with the README as one item too — how many times you have
spawned a documenter for it. **A spawn the harness refused, or that failed to start, because too
many subagents were running is not an attempt**: no documenter ran, and the next run lists the
item again. **An item listed after three attempts is given up on**: spawn nothing more for it, and
count it into `<n>`, since it still leads every listing.

Stop when `up_to_date` is true, or when a run lists no `work` and no `readme`, or lists only items
you have given up on.

## 5. The README

When an `--apply` run lists a `readme` item — which it does only once no file work is left — spawn
one documenter for it in the same way, giving it `Root: <root>` and the `readme` item relayed whole,
as the JSON the planner printed. Then run the planner again. The README is retried and given up on
like any other item. **Never spawn for a `readme` item from a dry run** (step 6): nothing removed
the old README, and the write would overwrite it.

## 6. A slice

With `--slice N`, stop offering items once N distinct items have been offered; the last batch's
`--limit` is what the slice has left, plus the items given up on. Then check with a **dry run** —
the same command without `--apply`, `--limit` 19 plus the items given up on — which
changes nothing, where an `--apply` run would remove the out-of-date documents of items this slice
will not write.
An offered item the dry run still lists is retried with `--apply` and `--limit` the number of such
items plus the items given up on; repeat the dry run until it lists none of them, or only items
given up on. The three attempts count across batches and retries alike. If the dry run lists a
`readme` item, go to step 5 with an `--apply` run.

## 7. Register or refresh the knowledge base

Whatever the loop's outcome: if `mcp__zikaron__zikaron_knowledge_list` shows no knowledge base named `<corpus>` —
compared ignoring case, as the knowledge index compares names — create it with
`mcp__zikaron__zikaron_knowledge_add` —

- `name`: `<corpus>`
- `path`: `<corpus>`
- `include`: `["*.md"]`
- `git_mode`: `"off"`
- `description`: "Per-source-file documentation of `<module>` in this project's code, written by agents: what each file is for, what it declares, its non-trivial behavior and what it depends on. A lead for where to look, checked against the code; each result says whether its source has changed since it was documented.", with `<module>` filled in

— and otherwise call `mcp__zikaron__zikaron_knowledge_refresh` with that name, unless the `root_path` step 1's
status reported for it is not `<root>/<corpus>`: that knowledge base is another directory's, and you
report it rather than refresh it. Either call returns at once and builds in the background; it is
searchable once `mcp__zikaron__zikaron_knowledge_status` reports it `ok`. `git_mode` is `off` so that a document
is indexed however this project keeps it, committed or not.

## 8. Report

End with the report the user reads. **Open it with one line naming the module, whether it is up to
date, and its knowledge base's name** — the session that receives the report may pass on only its
first line. Then how many documents were written, moved and removed. If it is not up to date, name
each item given up on and why, and each `unverifiable` source, and say that the README was
therefore not written, since it waits for every file. Say so when `git_mode_effective` is `off`,
and only then. After a slice, report what it left — the last dry run's `work` items plus its
`remaining`, which counts only the items past those listed — not as a failure. Name each `foreign`
entry whose `source` is not null — that source has no document and gets none until the file at its
path is moved aside — and each `unplaceable` source, which can have none. Neither holds
`up_to_date` false, so nothing else will say it. **When `skipped` counts any `over_size_cap`, say
how many sources were too large to document** — they have no document, however up to date the
rest is — and that raising `knowledge_max_file_bytes` in the project's `.zikaron/config.toml`
would document them.

## Permissions

Under Claude Code this skill runs in a background subagent of its own, `zikaron-code-orchestrator`,
so the session that invoked it stays free and receives the report when the run ends; one run at a
time, since a second invocation holds that session until the first is done. The planner's command
and each documenter's write go through the session's permission mode, and their prompts surface in
the session, naming the agent asking: an interactive session is asked to approve the planner's
command when it first runs — and at later batches unless the user allows it for the session — and
the first document a documenter writes; under auto mode neither is put to the user, the classifier
deciding the command and an edit inside the project approved outright. A headless run is asked
nothing and is refused: it needs `--permission-mode bypassPermissions`, or
`--allowedTools` naming the planner command, the subagent tool, the file tools and Zikaron's own
server, and `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, without which a run that waits ten idle
minutes is stopped. Under kiro this skill runs in the session that invoked it, and the documenter's
own config already allows its tools.
