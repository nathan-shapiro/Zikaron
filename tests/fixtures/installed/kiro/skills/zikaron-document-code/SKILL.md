---
name: zikaron-document-code
description: Write per-source-file documentation of this project's code into a knowledge base per module, through Zikaron's planner and a zikaron-documenter subagent per file. Use when asked to create, write or update the code's documentation — a module's, a directory's or the project's — or to bring it up to date after the code has moved. With no directory named it updates every documented module, or documents the whole project where none is.
---

# Document this project's code

```
/zikaron-document-code [<module>]... [--include GLOB]... [--exclude GLOB]... [--slice N]
```

This writes one document per source file of each module, and a README for the module, into the
project's `code-knowledge/` directory, and makes them searchable as the module's own knowledge base.
A **planner** decides what needs writing; you spawn a **zikaron-documenter** subagent for each item
it lists and run it again, until it reports the module up to date. You write no document yourself
and you never decide what is out of date — the planner does, from hashes.

The modules, their globs and any slice are the arguments this skill was invoked with.

A module is a directory relative to the project root, written with no leading `./` and no trailing
`/`, and `.` for the root itself. **Its globs are part of what the module is**: pass the same
`--include` and `--exclude` on every run over it, because a narrower set makes the planner remove
the documents it no longer admits. `--slice N` is the skill's own word, for documenting only N
files this time; it is never passed to the planner.

## 1. Find the planner and the modules

The project root is the directory holding `.kiro/`. Open
`.kiro/agents/zikaron-consolidator.json` there, which Zikaron's install always writes, and take
`mcpServers.zikaron.command`: the path of this project's `zikaron-mcp`. The planner is the `zikaron`
in that same directory — the path with its last component `zikaron-mcp` replaced by `zikaron`.

Call that path `<zikaron>`, and the absolute path of the project root `<root>` — its real path,
symlinks resolved, as `pwd -P` prints it there, which is the form the planner's `root` prints and a
knowledge base's `root_path` is stored in. Do not use a `zikaron` found on `PATH`: it may be another
install, one without this command.

Call `zikaron_knowledge_status` with no name: its listing decides the modules and the check below.
**The modules are the ones named, in the order given. With none named**, every knowledge base whose
name begins `code-knowledge/` is a module documented already, and the run updates each in turn:
**its module is its `root_path` with `<root>/code-knowledge/` taken off — never its name**, which
the index stores lower-cased while a directory keeps its case. One whose `root_path` does not lie
under `<root>/code-knowledge/` is another directory's: pass over it, with an opening line of its own
in the report (step 8) saying whose directory it is. It stays registered, so a run that passes over
every one documents nothing, and says so. Where no knowledge base's name begins `code-knowledge/`,
the module is `.`, the whole project.

**Globs and `--slice` need a run of one module**: a run that names two or more modules, or names
none and finds any knowledge base named `code-knowledge/…` registered, given a glob or a slice
stops here, before the planner first runs, and reports it, since nothing says which module they are
for. So a run over registered modules passes no globs, and each of its opening lines says
`globs: none`.

Run steps 2 to 7 for each module in turn, and report them all in step 8. For each, call the
module's knowledge base `<corpus>`: `code-knowledge/<module>`, or `code-knowledge` when `<module>`
is `.`. Its directory, `<root>/<corpus>`, holds the module's documents. **Refuse a module that
nests** before the planner first runs for it: if a knowledge base named `code-knowledge`, or with a
name beginning `code-knowledge/`, has a `root_path` that contains `<root>/<corpus>` or lies inside
it, and is not that directory itself — containment between directories, so `…/code-knowledge/src`
does not contain `…/code-knowledge/src-extra` — refuse it: the module's documents would be indexed
by two knowledge bases, and returned twice by a search naming neither.

**In a run of several modules, a module refused is reported and the run goes on to the next**: one
refused for nesting, or one the planner refuses — its standard error opening `refused: --module`,
whatever follows. A registered module the planner finds no such directory for was renamed or
removed since it was documented; its opening line names its knowledge base and documents as the
user's to remove. Any other failure of the planner stops the run, and a run of one module stops on
any refusal: report it and stop.

## 2. Run it in batches

Run this as a shell command:

```
<zikaron> code-knowledge plan --project <root> --module <module> [--include GLOB]... \
    [--exclude GLOB]... --apply --limit <n>
```

`<n>` is 18 plus the number of items you have given up on (step 4), less after a batch
had spawns refused, as step 4 says. **Never run it
without `--limit`**: a whole module's listing is longer than a harness shows of a command's
output, and a cut-off object cannot be parsed. **Always pass `--project` with `<root>` written
out** — not `$PWD` or `.`, which the shell resolves wherever it stands: otherwise the planner
resolves the shell's working directory, which may have moved.

It prints one JSON object. A non-zero exit prints none, its reason on standard error, and is
handled as step 1 says. What you act on:

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
spawn a **zikaron-documenter** subagent, giving it this
prompt:

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

**A spawn refused because too many subagents are running is expected and never a reason to stop**:
any other agent the session runs may hold the slots. The harness's *"Do not retry"* is kept — no
refused spawn is made again; the next planner run lists the item, and a later, smaller batch spawns
it. Wait for the documenters of that batch that did start, then run step 2 with `<n>` the number
that started — or 1, when none did — plus the items given up on, and return to 18 once a
batch has none refused. A batch that starts none has nothing to wait for, so that batch of one
follows at once; if it is refused too, stop and report that the session's subagents were all in
use, and that invoking the skill again resumes where this run stopped — a stop for contention,
never the end below.

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
the same command without `--apply`, `--limit` 18 plus the items given up on — which
changes nothing, where an `--apply` run would remove the out-of-date documents of items this slice
will not write.
An offered item the dry run still lists is retried with `--apply` and `--limit` the number of such
items plus the items given up on; repeat the dry run until it lists none of them, or only items
given up on. The three attempts count across batches and retries alike. If the dry run lists a
`readme` item, go to step 5 with an `--apply` run.

## 7. Register or refresh the knowledge base

Whatever the loop's outcome: if `zikaron_knowledge_list` shows no knowledge base named `<corpus>` —
compared ignoring case, as the knowledge index compares names — create it with
`zikaron_knowledge_add` —

- `name`: `<corpus>`
- `path`: `<corpus>`
- `include`: `["*.md"]`
- `git_mode`: `"off"`
- `description`: "Per-source-file documentation of `<module>` in this project's code, written by agents: what each file is for, what it declares, its non-trivial behavior and what it depends on. A lead for where to look, checked against the code; each result says whether its source has changed since it was documented.", with `<module>` filled in

— and otherwise call `zikaron_knowledge_refresh` with that name, unless the `root_path` step 1's
status reported for it is not `<root>/<corpus>`: that knowledge base is another directory's, and you
report it rather than refresh it. Either call returns at once and builds in the background; it is
searchable once `zikaron_knowledge_status` reports it `ok`. `git_mode` is `off` so that a document
is indexed however this project keeps it, committed or not.

## 8. Report

End with the report the user reads. **Open it with one line per module the run was asked for, each
naming the module, whether it is up to date, and its knowledge base's name**, before anything else
— a refused module's saying it was refused and why, a passed-over knowledge base's saying whose
directory it is, a module the run stopped before reaching saying so, and in a run over registered
modules each saying `globs: none` — since the
session that receives the report may pass on only these lines. Then, for each module in the same
order, how many documents were written, moved and removed. If it is not up to date, name
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

This skill runs in the session that invoked it. kiro gives each documenter only what its own config
and this session's agent both allow, so where this agent has no `fs_write` rule covering the
documents directory, each documenter's write asks first, and a headless run writes no document.
When a run ends with documents missing for that reason, say so.
