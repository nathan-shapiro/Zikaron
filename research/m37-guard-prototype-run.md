# M37 guard prototype — §3 transcribed literally, run against §8

A throwaway spike, not the product: `experiments/m37_guard_prototype.py` implements
`design/edit-guards.md` §3 (§3.1 parse order and command position, §3.2 forms, §3.3 targets, §3.4
override) from the text, stdlib only. It then extracts every item of §8's table and judges each
one under §8's payload: `cwd=/home/u/proj`, `$TMPDIR` unset, no `scratchpad_dir`. The question
it answers is where the spec is ambiguous or self-contradictory, and where §8's expected value
does not follow from §3.

Reproduce:

```bash
.venv/bin/python experiments/m37_guard_prototype.py
```

## Counts (against the spec as it stands after review round 24)

| | |
|---|---|
| table rows | 149 |
| items (commands) | 458 |
| passed | 458 |
| failed | 0 |
| skipped | 0 |

**Round 24, implemented.**

- **A parenthesised group can head an operand.** It is judged by its contents, with step 6 on
  any chain after it. Before this, `target()` unwrapped a group only when it was the whole
  expression. So `(Path('/tmp') / 'x').with_suffix('.json').write_text(s)` is silent, and its
  `design/` twin denies naming `design/x.md`. A probe checks the other side:
  `open((Path('design') / 'x.md').stem, 'w')` names nothing, because `.stem` is a name
  component.
- **The receiver `.open(` pattern is now `(?:(?<![\w.])\w+|\))\.open\(…`**, with the lookbehind
  on the word alternative only. So `d = 'research'; Path(d).open('w')` matches and names
  `research`, and `io.open('w')` stays a read.
- **Step 5's descent and the literals' leading span are judged as a full target expression.**
  The code already recursed through `target()`, so no change was needed.

**Round 23, implemented.**

- **The standalone `mode=` write pattern is cut.** It is gone from the pattern table, the call
  table and the target logic. The four items it used to deny are now §7 misses and pass silent:
  `df.to_csv('out.csv', mode='a')`, `logging.FileHandler('run.log', mode='a')`,
  `zipfile.ZipFile(p, mode='w')` and `dict(mode='w')`.
- **The bare and receiver `open(` patterns keep their own optional `mode=`.** So
  `open('f', mode='w')` still denies, naming `f`.
- **The head rule splits the first operand into a head and its `.name`/`.name(…)` chain.** Step 1
  looks at the whole operand, steps 2 to 5 at the head alone, and step 6 at the chain. Two
  probes check it:
  - `d = Path('/tmp'); d.joinpath('x').write_text(s)` is silent: head `d`, chain `.joinpath(…)`;
  - `open(Path(d).joinpath('x'),'w')` with `d` unbound names nothing: head `Path(d)` is a path
    function with an unbound argument.
- **A leading `{…}`/`${…}` whose head yields nothing leaves the literal as written.** The
  prototype already did this: `` `${d}/x` `` with `d` unbound names `<cwd>/${d}/x`.

Row 4's analyser was **rewritten** to the new §3.3, not patched. The rules the spec dropped were
deleted from the code: perl/ruby as row-4 words, the perl/`IO.write`/`File.*`/`ZipFile`/
`shelve`/`dbm` patterns, the name rule's position test, the `Path(…)`-anywhere loop, and the
`$(…)` command-word prefix. Every write call now has one target expression, judged by the
head rule in its stated order.

**A pass now asserts the named target, not only the decision.** The previous two runs each had
a defect that only the named target showed: the decision was right and the target was wrong.
So the harness now checks every naming claim an Expected cell makes, and a mismatch counts as a
failure:

| Cell says | Checked as | Items |
|---|---|---|
| "naming `X`" | the first denying form names `X`, joined to `cwd` when relative | 17 |
| "naming the authored target" | at least one non-scratch path target is named, and every one of its components appears in the command's text | 34 |
| "naming no literal" / "naming nothing" | the first denying form names no path, only `<nothing:…>` markers or nothing | 15 |
| a per-item cell, "the triple-quoted row names `f`, the `` `${d}/x` `` row names `${d}/x` …, and the others name no literal" | each item matched to its clause by the selector text | included above |

It also checks the invalid-marker vs ordinary deny, §3.5's placement clause, and "naming the
`echo` form", as before.

**Mutation-verified.** I fed `check()` the wrong targets the previous runs actually produced, and
each was reported as a failure:

- `<expr:out>` for `const out = "research/x"` → "expected an authored target";
- `research` for `const d = "research"; …(d + "/x")` → "expected no literal" (that cell has
  since changed to naming `research`);
- `<expr:OUT>` for `OUT = str(Path('design') / 'x')` → "expected an authored target".

**The authored check is weaker than "naming `X`".** It accepts any non-scratch target built from
the command's own text, so it would not catch a deny naming the *wrong* authored file from the
same command. A cell that names the path is the stronger form.

**How much the passes are worth.** The prototype was written with §8 in view, by one reader. A
pass shows that the spec's text, as one reader implemented it, produces §8's value. It is not an
independent second implementation.

## Failures

None.

The run before §8's update failed 18 items. In each, the round-22 spec text gave what the
prototype got. §8 has since been updated for all 18:

- the perl, ruby and archive items now share one stated-miss row;
- the alias names `CLAUDE.md`;
- `json.dump(…)` and `shelve.open(…, flag='r')` are silent.

For the three `tempfile` items, round 22's follow-up took the proposed clause instead: a `mode=`
keyword's call that is a scratch call is a scratch target. **Round 23 then cut the standalone
`mode=` pattern altogether**, and the clause went with it, so the prototype no longer has it.
Those three items now match no write call at all, and pass silent for that reason.

The diagnosis of each of the 18, as it stood against the unchanged §8, is kept below for the
record. Line numbers are `design/edit-guards.md`'s at that time.

**Row 4 is now python/pypy/node/nodejs only**, so a `perl -e`/`ruby -e` script matches no
form: expected deny, got silent. Eight items:

| Line | Item |
|---|---|
| 655 | `perl -E 'open(F,">","f"); print F "x"'` |
| 655 | `ruby -e 'IO.write("f", s)'` |
| 688 | `perl -ne 'BEGIN{open(F,">","f")} print F' in` |
| 733 | `perl -e 'open(my $fh, ">", "f") or die; print $fh 1'` |
| 733 | `ruby -e 'File.open("app.rb", "w")'` |
| 736 | `perl -e 'my $f = "research/x"; open(my $fh, ">", $f)'` |
| 750 | `perl -e 'open F, ">f"; print F 1'` |
| 753 | `ruby -e 'File.new("f","w").write("x")'` |

Fix: drop these from §8, or move them to §7's misses.

**Write-call patterns no longer in §3.2's list**: expected deny, got silent.

| Line | Item | The pattern that is gone |
|---|---|---|
| 707 | `shelve.open('data')` | `shelve.open(` |
| 707 | `dbm.open('cache','c')` | `dbm.open(` |
| 708 | `shelve.open('data', flag='r')` | `shelve.open(` |
| 762 | `zipfile.ZipFile('f', 'w')` | `ZipFile(` |

Fix: move them to §7's misses.

**A `mode=` callee's target is its first argument, or a `file=`/`path=` keyword.** These calls
have neither, so the target expression yields nothing, and §3.3 says it is "denied naming no
target". Expected silent, got deny:

| Line | Item |
|---|---|
| 663 | `tempfile.NamedTemporaryFile(mode='w', delete=False)` |
| 744 | `from tempfile import NamedTemporaryFile; NamedTemporaryFile(mode='w', delete=False)` |
| 744 | `from tempfile import TemporaryFile; TemporaryFile(mode='w+')` |

Here the spec is the likelier thing to change: these write to scratch by construction. Proposed
clause: *"a `mode=` callee that is itself a scratch call is scratch"*, the rule the spec had
before round 22. Otherwise make the three items deny, as stated false denies on scratch.

**An alias now takes its target.** Line 715,
`p = Path('CLAUDE.md'); q = p; q.write_text('x')`, expects "naming no literal (an alias of an
authored path leaves no target)" and got `CLAUDE.md`. §3.3 now says, in its closing example,
that the alias `q = p; q.write_text(…)` is "denied naming `CLAUDE.md`". So §8's cell
contradicts §3.3. Fix: the cell should read *deny, naming `CLAUDE.md`*.

**Only the target expression is judged.** Line 726,
`p = Path('CLAUDE.md'); json.dump(p.read_text(), open('/tmp/x','w'))`, expects "deny (stated
false deny on scratch)" and got silent. The position test that made `p` contribute is gone; the
one target expression is `'/tmp/x'`. The false deny no longer exists. Fix: the cell should read
silent, and §7's matching false-deny entry should go.

**The command-word prefix is back to `(?:\S*/)?`.** Line 730,
`$(brew --prefix gnu-sed)/libexec/gnubin/sed -i 's/a/b/' f`, expects "deny, naming the
authored target" and got silent. The token holds spaces inside its `$(…)`, so `\S*/` cannot
reach `sed`. Fix: make it silent as a stated miss in §7, or restore the `$(…)`-aware prefix if
the case still matters.

## Open ambiguities

None. Both of the rewrite's ambiguities are closed:

- **One call matched by two patterns** no longer arises. The standalone `mode=` pattern is cut,
  so only the bare and receiver `open(` patterns can match a call.
- **A chain after a path function's call** is judged as step 6, which round 23's head/chain
  split now states for every head. `open(str(Path('design')).stem, 'w')` yields nothing, and
  `open(os.path.join('design','x').upper(), 'w')` names `design/x`.

## Resolved

**Read this section as history.** Round 22 rewrote §3.3 row 4 and narrowed row 4's command words.
Every entry below about perl or ruby as row-4 words, the `IO.write`/`File.*`/`ZipFile`/
`shelve`/`dbm` patterns, the module list, the name rule's position test, the
exactly-a-bound-name clause, or the `$(…)` command-word prefix records an earlier state of the
spec, not the current one.

The earlier runs' failures, and every reading they picked, were settled by the spec text of their
day:

- **First run's failures.**
  - `tee >(grep a) /tmp/x` — fixed by §3.1's redirect-token run.
  - `mode = 'w'` — fixed by row 4's anchored `mode=` pattern.
  - `Path as P` — now "deny, naming no literal" in §8.
- **The `$(brew --prefix gnu-sed)/…/sed` prefix** is now `(?:(?:\$\([^()]*\)|\S)*/)?` in §3.1.
- **Aliases.** An alias of a scratch-bound name is scratch, and an alias of an authored path
  leaves no target (§3.3). §8 pins both.
- **Command position and redirects (§3.1).**
  - `{` counts only as a standalone word; only an unquoted `$(` counts.
  - A `$(` that does not close on its line ends no simple command, and its words stay tokens of
    the enclosing command.
  - An unclosed `>(` makes every token up to its `)`, or to the end of the simple command, a
    redirect token, and its `(` is no command position.
  - timeout's duration is the one token after its flags, whatever it is.
- **Row 4 (§3.2).** It searches the script as the interpreter sees it. One-line strings keep
  their comments, only scanned bodies are searched, and echo/printf must immediately precede
  the interpreter.
- **Row 5 cat (§3.2):** a token beginning `<<` or carrying an opener, plus a sink, in its own
  simple command.
- **Targets (§3.3).**
  - A non-literal `mode=` callee argument contributes nothing.
  - A Path chain counts when it *includes* a write method.
  - An unassigned `/` chain joins its literals up to the first non-literal operand.
  - `name2 / '…'` with `name2` bound to a scratch marker is scratch.
- **Backslash (§7):** outside a string, a backslash escapes nothing except as a continuation and
  a quote it precedes.

**Rules added in round 18, now implemented:**

- §3.1:
  - `|&` is read as `|`.
  - xargs `-E`, `--max-args` and `--max-procs` take an argument.
- §3.2 row 4:
  - perl's open requires a filehandle first argument.
  - Ruby's `File.open(`/`File.new(` need a `, 'w'|'a'|'r+'` mode.
- §3.3:
  - "is, or contains" is replaced by the expression's **head**. A scratch call is
    `tempfile.`, a bare `mkdtemp(`/`mkstemp(`/`gettempdir(`/`NamedTemporaryFile(`/
    `TemporaryDirectory(`, `tmpdir()`, or a `$TMPDIR` read.
  - A leading literal or `Path('…')` governs, and a later scratch name changes nothing.
  - `/private` roots are scratch on every platform; the code already did this.
- §7: outside a string, `\"` and `\'` open nothing.

**Rules added in round 19, now implemented:**

- §3.2 row 4, patterns:
  - fileinput is `(?:fileinput\.)?(?:input|FileInput)\(…inplace\s*=\s*(?:True|1)\b`, so
    pandas' `inplace=True` is no write. `FileInput(` contributes its first argument too.
  - The `mode=`, bare-open and receiver-open patterns now close their quote and accept a
    `[:|]\w+` suffix. So `mode='wrap'` is no mode, and `tarfile`'s `'w:gz'` is a write mode.
  - `ZipFile(` requires a comma before the mode.
- §3.3, scratch calls and heads:
  - The scratch calls add a bare `mktemp(`, `TemporaryFile(` and `SpooledTemporaryFile(`.
  - A bare scratch call as a `mode=` callee is scratch.
  - Descent reaches a `{…}` span only at the literal's start; a span after a prefix
    (`f'research/{d}'`) is not a head.
  - A literal or Path chain reached by descent governs as if it led: `str(Path('/tmp') / 'x')`
    is `/tmp/x`, and `abspath('/tmp/x')` is `/tmp/x`.
- §3.3, name bullet: a `Path(…)` with a call chain binds its literal, except a chain ending in a
  read or a name component, which binds nothing.

The two ambiguities left open by round 18 are now settled by the spec, in the readings the
prototype had picked. The whole operand is checked as a scratch call before descending, and only
a `{…}` span at the literal's start can be a head. The `.read(` question is settled too: the
name bullet now lists `.read(` and `.readlines(`, and a chain holding a read-mode `.open(`
anywhere binds nothing.

**Rules added in round 20, now implemented:**

- §3.2 row 5: tee is fed only by literal text. That means a `<<`/`<<<` in its own simple
  command, or a walk back over filters to a simple command that carries an opener or is
  echo/printf; a shell or interpreter word stops the walk.
- §3.1: a token beginning `>|` is not a sink.
- §3.3, the head rule:
  - a template literal's leading `${…}` is judged like an f-string's leading `{…}`;
  - a name reached by descent and bound to an authored path contributes that path;
  - the scratch calls add `process.env.TMPDIR` and perl's `$ENV{TMPDIR}`.
- §3.3, name binding:
  - binding skips an optional `const`/`let`/`var`, and perl's `my`/`our` with `$` as part of
    the name;
  - `with <expr> as name` binds the name as scratch when the head of `<expr>` is a scratch call,
    and otherwise binds nothing.
- §3.3, open: the module list is gone. An `open(` matched by the bare pattern contributes its
  first argument whatever its receiver. One matched by the receiver pattern contributes nothing,
  and that pattern excludes the path-first modules (`io` … `fs`, now with `wave`, `aifc`,
  `fsspec` and `smart_open`).

**Settled in the round-20 follow-up, now implemented or confirmed:**

- §3.3 lead: a write call's first argument that is *exactly* a bound name contributes that
  name's target, scratch or authored, whatever the position test says.
  `const out = "research/x"; fs.writeFileSync(out, s)` now names `research/x`.
- §3.1: a `|` straight after an unquoted `>` is part of that token. The prototype already read
  it this way.
- §3.2 row 5: in the tee walk, a simple command carrying a `<<<` counts as literal text. Also
  already read this way, and now pinned by §8: `cat <<< x | sort | tee f` is a deny naming `f`,
  and `… tee /tmp/x` is silent.
- §8: the `window.open('about:blank')` row is now silent, which is what §3 gives.

**Settled in round 21, now implemented:**

- **§3.3 statements.** A statement runs to a `;` or newline outside string literals and outside
  unclosed brackets. `with` items may be enclosed in `(…)` and span lines. Both multi-line
  `with (…):` items now bind `d` as scratch before the write is judged.
- **§3.3, an unassigned `/` operand.** It contributes only where its parenthesised chain is
  followed by `.write_text(`, `.write_bytes(` or a write-mode `.open(`, or is a write call's first
  argument. Followed by a read, or anything else, it contributes nothing, and so does a list
  element. Two new, unpinned probes check the implementation:
  - `open((Path('design') / 'x.md'), 'w')` names `design/x.md`, the parenthesised chain seen as
    a first argument;
  - `(Path('design') / 'x.md').read_text()` inside a write to `/tmp` contributes nothing.
- **§3.3 name bullet.** A head reached by descent that is an authored-bound name binds its path
  (`ROOT = 'research'; OUT = os.path.join(ROOT, 'x')`), and a name followed by `.` is no such
  head (`x = p.read_text()` binds nothing). The code already behaved this way.
- **Perl.** The three-argument path argument is judged as a first argument is. The code already
  did this.
