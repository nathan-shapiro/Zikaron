# M37 — the find-replace guard replayed over this repository's transcripts

`design/build-plan.md` §M37 done-when 2: before the guards are installed anywhere, every `Bash`
`tool_input.command` in this repository's own Claude Code transcripts — `~/.claude/projects/
-home-<user>-Zikaron/**/*.jsonl`, subagents included — is judged by the shipped decision function
under the call's recorded `cwd` and this machine's `$TMPDIR` (unset). Measured 2026-10-07.

Re-run, which reads the local transcripts and so is not reproducible off this machine:

```bash
.venv/bin/python experiments/m37_guard_replay.py --dump /tmp/denies.json
```

## Counts — the denominator for `design/edit-guards.md` §7's count (a)

Against the rules as they ship, after the two §3.3 changes below:

| | |
|---|---|
| transcript files | 973 |
| `Bash` commands | 20,051 |
| a form matched | 1,520 (7.6%) |
| denied | **1,227 (6.1%)** — 988 inline scripts, 177 literal-text writes, 62 `sed -i` |
| a form matched, every target scratch | 293 |

The transcripts grew while this ran, since this session's own calls are in them, so the totals
move by a few dozen between runs.

## Every deny, read

`experiments/m37_guard_replay.py` assigns each deny a class; the classes were then checked by
reading — every command in the false classes, and two random samples of 40 and 60 from the
largest true class.

| Reading | Class | Denies | Sessions |
|---|---|---|---|
| true | an authored file of the session's project | 1,094 | 31 |
| true | a write whose target the rules cannot resolve | 111 | 12 |
| true | an authored file outside the session's project | 6 | 4 |
| false | a write call quoted in a string, testing the guard | 10 | 1 |
| false | a Claude Code job's own tmp directory | 6 | 1 |
| false | a target held in a variable bound to `$(mktemp …)` | 3 | 2 |
| false | a loop variable ranging over scratch paths | 1 | 1 |

**The true denies are the rule doing what it is for.** 99 of the 111 unresolvable targets are one
idiom: a list of `(path, old, new)` triples looped over with `p.read_text()` and
`p.write_text(t.replace(old, new))` — a bulk find-replace over `design/`, `zikaron/` and
`FINDINGS.md`, where the path arrives through a loop variable. The project-file class is the same
behaviour with literal paths, plus heredoc appends (`cat >> tests/test_x.py <<'PY'`) and `sed -i`.
The samples held no false deny. They held several writes the override exists for: re-rendering
`tests/fixtures/kiro_artefacts.json` through the installer's own functions, and deliberate mutation
tests of shipped code.

**The four false classes are each one session, or a stated §7 class**, so none is grounds for a
rule change (`design/edit-guards.md` §7's stopping rule):

- **A write call quoted in a string** (§7, "parsed as stated"): the prototype's own test runs,
  which pass §8's commands to `decide` as Python string literals. The guard reads a script's
  literals as code, by design.
- **A Claude Code job's tmp directory**, `~/.claude/jobs/<id>/tmp`: one background job staged its
  probes there. It is no scratch root, and the payload of 2.1.285 names no `scratchpad_dir`; a
  version that sends one would exempt it. Entered in §7.
- **`$(mktemp …)` bound to a variable** (§7, stated): `d=$(mktemp -d); echo '{not json' > $d/bad.json`.
- **A loop over scratch** (§7, stated): `for d in /tmp/a /tmp/b; do cat > $d/srv.py <<'EOF'`.

## Two recurring false denies, and the §3.3 changes they made

The first replay, against §3 as approved, found two false-deny shapes recurring across sessions —
the case done-when 2 says becomes a §3 change in the build. The operator took both (2026-10-07).
Each was a stated §7 false deny until then.

| Shape | Denies | Sessions | §3.3 now |
|---|---|---|---|
| `S=<scratchpad>; cat > $S/probe.py <<'EOF'` — the agent's own scratchpad, bound to a variable in the same command | 58 | 13 | a target beginning with a variable an assignment-only simple command bound earlier in the same unit is read with its value |
| `cd <scratchpad> && cat > probe.py <<'EOF'` — a relative target after a `cd` in the same command | 56 | 14 | a `cd DIR` simple command moves the directory later relative targets resolve against, except in a unit holding a `(` subshell |

Both are counted against the replay as it stood when each was found, and both classes are empty
in the counts above. The prefix-assignment, subshell, `cd -` and `~` cases stay false denies, and
§8 holds a row for each.

## What this does not measure

- **The live rate.** These are commands written with no guard installed. Once one denies, an agent
  adapts — to `Read` and `Edit`, to an override, or to a route around the guard — and §7's counts
  (a) to (c) read that adaptation against this baseline.
- **Kiro sessions.** Only Claude Code transcripts were read; the guards are not offered on kiro.
- **The full verbatim list is not published.** The transcripts are one machine's working history:
  they name other projects and private paths the publication hygiene guard keeps out of the
  package. `--dump` writes the list, with each deny's class, to a local file.
