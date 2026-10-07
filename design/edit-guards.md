# Edit guards

**Normative for D38.** Two deterministic Claude Code hooks that hold an agent to two rules this
project's own `CLAUDE.md` states and an agent routinely breaks: *edit authored files with the editing
tools, never with a find-replace script*, and *re-read what you edited, with its surroundings, once
you are done editing it*. Neither hook is part of the memory store or the knowledge index: a
project may install the guards, Zikaron's memory, or both (§5).

## 1. Why a hook, and why no model

Stating a rule once (`CLAUDE.md`, the write policy) loses to what the agent sees continuously, and
stating it every turn (the push block) is disowned by its own preamble. **Evaluating behaviour and
reacting to it is the only category that has held a rule in this project** — the argument and its
evidence are the 2026-09-24 *evaluator with teeth* proposal (`FINDINGS-archive.md` §"The strongest
M32 candidate, and why"; `research/leibatrader-consolidation-2026-09-24.md`). That proposal split
rules into two disjoint classes: **deterministic synchronous predicates** for what must not happen,
and an asynchronous watcher for what is visible only in hindsight. The guards are the first class,
and nothing more.

**That argument covers the find-replace guard, which refuses. The re-read nudge is a reminder**,
closer to the "state it every turn" class than to the one that held, though it is triggered by the
behaviour rather than by the clock. What is measured for it is delivery only (§2); whether it changes
behaviour is §7's count.

- **Regular expressions over the tool call, and one file read.** No model, no network, no store,
  no service, and no filesystem query beyond the hook's own stdin except one: the text of a
  scratch script the command runs, read once and bounded (§3.2 row 6). The same payload, the same
  `$TMPDIR` (§3.3) and the same contents of that script always give the same answer.
- **Stdlib only**, held by `tests/test_hook_stdlib_only.py`, so the cost per call is one Python
  start.
- **D2 is untouched**: no model at all, and nothing on Zikaron's write path.
- **It is not a component in D31's sense.** D31's components share a store over a Unix socket; the
  guard opens no socket and touches no store, so it is a harness hook that happens to ship in the
  same wheel, and D31 is not amended.
- **It reads Claude Code's payload directly, and that is the seam's one exception.** The field names
  it reads — such as `hook_event_name`, `tool_name`, `cwd`, `scratchpad_dir`, `tool_input.command`,
  `tool_input.file_path`, `tool_input.notebook_path`, `tool_response` and `tool_output` — are not
  routed through `HarnessSpec`, because there is no second harness to carry a difference for.
  `HarnessSpec` carries only the triggers and matchers the installer writes (§5). A kiro port is
  therefore a seam change, not a new value.

The asynchronous watcher class stays unscoped.

## 2. What Claude Code lets a hook do — measured

`research/claude-code-tool-hook-probe.md` (Claude Code 2.1.285) is the evidence; every row here was
observed, not read from documentation.

| Path | Behaviour |
|---|---|
| `PreToolUse`, exit 0, `hookSpecificOutput.permissionDecision: "deny"` | The tool does not run. `permissionDecisionReason` **becomes the tool result** the model reads |
| The same under `bypassPermissions` | Still denies |
| `PreToolUse` with **no** `permissionDecision`, only `additionalContext` | Under `bypassPermissions`, the command ran and `additionalContext` reached the model. Under `default`, the harness's own flow decided as if no hook existed — the command asked for approval; whether `additionalContext` also arrived there was not recorded. Under `auto` (2.1.285, the interactive test's override sessions, 2026-10-07: `research/m37-guard-interactive-test.md`), the command ran and `additionalContext` arrived, recorded in each transcript as an attachment |
| `PreToolUse` `allow` + `additionalContext` | Reaches the model (measured under `bypassPermissions`). That `allow` skips the approval the user's policy would ask for is the documentation's statement — `allow` under `default` was not run — and is why the override does not use it (§3.4) |
| `PostToolUse` `additionalContext` after a successful edit | Reaches the model, beside an unchanged tool result |
| `PostToolUse` stdin for `Write` | `tool_response.type` is `"create"` or `"update"` |
| `PostToolUse` stdin for `Edit` | `tool_response.structuredPatch` carries the changed hunks with line numbers |
| The payload | Carries `cwd`; carries no scratchpad path |

The documentation (`research/claude-code-tool-hooks-docs.md`) agrees on every row and adds three
facts the design leans on: a hook `deny` also holds under `--dangerously-skip-permissions`; a hook
that exits non-zero other than 2, crashes or times out lets the call proceed, which is §6's
behaviour by the harness's own rule; and project settings hooks fire inside subagents too.
**The nudge is the fragile half**: GitHub issues filed in 2026 (#19432, #55889, #79616) report
`additionalContext` not reaching the model on some versions and surfaces, and each was closed
without a fix, while the deny reaches it as the tool result itself. That is why the brief requires
a live test of both.

**Kiro is out (operator decision 2026-10-06).** Its `preToolUse` can block (exit 2, stderr to the
model), but its `postToolUse` has no documented path to the model, and the guards are not offered
there at all for now. The installer refuses them for kiro (§5).

## 3. The find-replace guard — `PreToolUse`, matcher `Bash`

In every table of this document, `\|` is Markdown's escape for a `|` in a command or a pattern;
copy it as `|`.

A payload whose `tool_name` is not `Bash` is allowed silently. Otherwise the guard reads
`tool_input.command` and decides in this order: does a form in §3.2 match; if so, are all its
targets exempt (§3.3); if not, does the command carry a valid override (§3.4). It denies only when
a form matches, a target is not exempt and there is no valid override.

### 3.1 Command position

Every form names a **command word**, and the word counts only in **command position**: at the
start of a line (after optional whitespace), after `|`, `||`, `&&`, `;`, `&` or `(`, after `{` as
a standalone word (so `-I{}`, `${VAR}` and `{}` are no command position), after an unquoted `$(`,
after the shell keywords `if`, `while`, `until`, `do`, `then`, `else` and `elif`, after any unquoted `)` — which is how a
`case` arm's pattern ends, and the over-match is accepted — or after `find`'s `-exec` and
`-execdir`. The separators are matched as characters outside quotes, glued or not (`a;b`,
`cat f|sed -i … g`), except that an `&` inside a redirect (`>&`, `&>`, `2>&1`) is part of the
redirect and separates nothing, and bash's `|&` is read as `|`. Between that point and the word may stand leading `NAME=value`
assignments and any of the wrappers `sudo`, `env` (with its assignments), `xargs`, `time`,
`timeout`, `nice`, `nohup`, `command`, `exec`, `busybox`, `uv run`, `poetry run`, `pdm run`,
`pipenv run` and `npx`, each with its `-`-prefixed flags — and
one separate argument after `xargs`'s `-I`/`-n`/`-L`/`-P`/`-d`/`-s`/`-E`/`--max-args`/`--max-procs`, `nice`'s `-n`, `sudo`'s
`-u`/`-g`/`--user`/`--group`, `env`'s `-u`, `timeout`'s `-s`/`-k`/`--signal`/`--kill-after` and
its duration (the one token after its flags, consumed whatever it is), and `uv run`'s
`--with`/`--python`/`-p`. "Separate" means the flag token is bare:
`xargs -I{}` carries its argument attached and consumes nothing after it. A wrapper may carry a
path prefix (`/usr/bin/env`), and the word itself may carry a path prefix, `(?:\S*/)?`, or a
leading `\`, the alias-skipping spelling (`\sed -i …`).

**A backtick is deliberately not a command position.** In a Bash tool call it is far more often
Markdown inline code inside a heredoc body — a PR or commit message quoting `` `sed -i` `` — than a
command substitution running an in-place edit, which has no output to substitute; `$(` stays.

So `grep -rn "sed -i" tests/` matches nothing — `sed` is an argument there, not a command — while
`find . -name '*.md' -exec sed -i 's/a/b/' {} +`, `for f in *.md; do sed -i 's/a/b/' "$f"; done`,
`LC_ALL=C sed -i … f`, `timeout 60 sed -i … f` and a line starting with `sed -i` inside a body
fed to `bash` (§3.2) all match.

**The parse runs in one order.**

1. **Heredoc bodies** are delimited and each is classed scanned or data by its opener's pipeline
   (§3.2). A body begins after the opener's line *and any lines that line continues onto* — by a
   trailing `\`, or a trailing unquoted `|`, `&&` or `||` — as the shell reads it. **An opener**
   is a `<<`/`<<-` not inside a quoted string that pairs on its raw line, the opener's own quoted
   delimiter (`<<'EOF'`, `<<"EOF"`) being removed before that pairing; a quote that does not pair
   on its line quotes nothing in this step — it becomes step 2's multi-line string, and the body it
   precedes is skipped by that string. So `bash -c "$(cat <<"EOF"` opens a body, and
   `echo "x <<'EOF' y"` does not.
2. **Strings and comments**, in a single left-to-right pass where the first thing met decides: a
   quote that pairs on its line is a one-line string; a `#` at a line start or after whitespace,
   met outside any string, is the line's **comment**, and nothing after it on the line opens
   anything; an unpaired quote met before any such `#` opens a **multi-line string**, whose
   content takes the rest of the line, `#` and all, and which runs to the first unescaped quote of
   its kind on a later line (`\"` is escaped; `'` has no escape). The rest of the closing line is
   then scanned as any other text, and may itself open another string. Lines inside a multi-line
   string are string content: no comment, no marker, no line start. **Every heredoc body is a
   unit apart from the lines around it**: a string opened outside a body is not closed by a quote
   inside any body — the body's lines are skipped and the string resumes after the delimiter
   line — and a scanned body is scanned on its own, a string opened inside it closing inside it
   or running unterminated to the body's end. A data body is not scanned at all.
3. **Continuations** are joined, outside data bodies, strings and comments: a backslash ending a
   line — as its last character; `\ ` before the newline escapes the space — (a `\\` before the
   newline is an escaped backslash, not a continuation), or a line ending — with its comment
   removed — in an unquoted `|`, `&&` or `||`, whatever whitespace follows it, joins the next line
   to it, as the shell does. (Step 1 reads the same way for a body's start.) So
   `sed -i \` / `-e 's/a/b/' \` / `/tmp/x` is one simple command, `find … \` / `-exec sed -i …`
   is one line on which `-exec` keeps its place, and `cat <<'EOF' |` / `tee f` is one pipeline.
4. **Comments are removed and lines tokenised.**

A form's **simple command** runs from its command word to the next unquoted `|`, `||`, `&&`, `;`,
`&`, `)` or newline outside a string. Its tokens are split on whitespace, and a quoted string —
one-line or multi-line — is one token of the simple command that contains its opening, which
continues after the string's close on the closing line; nothing more of shell grammar is parsed
(§7). Because the comment is removed before tokenising, a trailing note, or the override's own
words, never becomes a target. The override (§3.4) is matched against the comment itself, since a
comment is where it lives.

A **sink** is an unquoted token that is `>` or `>>`, whose target is the next token, or that begins
with `>` or `>>` followed by its target. A token beginning `>&` or `>|` (bash's clobber form; a `|` straight after an unquoted `>` is
part of that token, not a pipe), or a digit followed
by `>` (`2>`, `2>>`, `2>&1`), is not treated as a sink — which also leaves `1> f` uncaught (§7). A **redirect
token** — a sink, its target, a token beginning with `<`, `>&` or `&>` or with a digit followed by
`>` or `<`, the word after a bare `&>`/`&>>`, and the word after a bare `<`, `<<`, `<<-`, `<<<`,
`>&` or digit-redirect (`2>`, `2>>`, `1>`) — is never a target of rows 1–3 nor of `tee` in row 5
(§3.3). **A `$(` whose `)` closes on the same line is, with its
contents, one token of the enclosing simple command** — so `echo $(date) > f` keeps its sink —
while the first word inside it is still in command position, and its closing `)` is no command
position. **A `$(` that does not close on its line ends no simple command**: the words after it
are in command position *and* remain tokens of the enclosing simple command, so an opener there
belongs to the enclosing command's pipeline. A `>(…)`
or `<(…)` is a process substitution: neither a sink, a redirect token, nor a target of any row; a
token beginning `>(` or `<(` whose `)` lies outside it is a redirect token and never a sink,
and so is every token up to that `)` — or to the end of the simple command, where no `)` comes;
its `(` is no command position.
The `)` closing it is part of that token — it neither ends a simple command nor is a command
position; a substitution containing whitespace is parsed as stated (its `)` ends the simple
command, a miss). **A `>`/`>>` with no target token** — the simple command ends first, or the next
token is a process substitution — **is not a sink**.

### 3.2 What is denied

| # | Command word | Matches when the simple command has | Examples that match |
|---|---|---|---|
| 1 | `g?sed` | a token `--in-place` or `--in-place=…`, or a token `-<c>*[iI]…` where every `<c>` is in sed's argument-less set `nrEsuz` (case-sensitive; `I` is BSD sed's second in-place flag; anything may follow, as the suffix) | `sed -i 's/a/b/' f`, `sed -Ei.bak … f`, `sed --in-place=.orig … f`, `sed -I '' … f` |
| 2 | `perl`, `ruby` | a token `-<c>*i…` where every `<c>` is in the argument-less set — perl's `pnlaws` or `0` with its optional octal digits, `-(?:[pnlaws]\|0[0-7]*+)*+i…` with possessive quantifiers so a run of zeros cannot backtrack; ruby's `pnlaw` — case-sensitive | `perl -pi -e 's/a/b/' f`, `perl -i.bak -pe … f`, `perl -0777pi -e … f`, `ruby -pi -e 'gsub(/a/,"b")' f` |
| 3 | `g?awk` | `-i inplace`, `-iinplace`, `--include=inplace` or `--include inplace` | `gawk -i inplace '{…}' f` |
| 4 | `(python[0-9.]*t?\|pypy[0-9]*\|node\|nodejs)`, compared with its quotes removed | a token `-c`, `-e` or `-E`, or a short-flag cluster whose last letter is `e` or `E` (`-ne`, `-lne`) or, for the python words, `c` (`-uc`, `-Bc`), bare or glued to its quoted script (`-c'…'`), or `<<` (a heredoc or a here-string) in the command word's pipeline (§3.2's sense), or stdin piped from an `echo`/`printf` simple command immediately before it in the same pipeline — **and**, within that simple command's own tokens — a multi-line string among them (§3.1), searched with each of its lines' Python-style comments dropped (a `#` at a line start or after whitespace, that line's one-line quoted strings paired first), so a commented-out write is not seen; one-line strings keep their comments — the **scanned** body opened by that `<<` — whichever simple command of the pipeline carries it — with §3.1's comments removed (a data body is not searched), or the piped `echo`/`printf`'s tokens, a write call. **The text searched is the script as the interpreter sees it**: shell quote delimiters are removed, an opening one becoming a newline and a closing one a space, and `\"` is unescaped; a body is searched raw. §3.3's statements and names are read from that same text. The write calls are listed below the table | `python3 - <<'EOF' … p.write_text(s) … EOF`, `.venv/bin/python -c "open('f','w').write(s)"`, a `python3 -c "` whose script spans lines, `echo "open('f','w').write('x')" \| python3` |
| 5 | `cat`, `echo`, `printf`, `tee` | for `echo`/`printf`: a sink (§3.1) in the simple command; for `cat`: a token beginning `<<` or carrying a heredoc opener, and a sink, in its own simple command; for `tee`: a target token or a sink, fed by literal text — a `<<` or `<<<` in its own simple command, or, walking back along the pipeline from `tee` over simple commands whose command word is neither a shell word nor a row-4 interpreter word, a simple command that carries an opener or a `<<<` or is `echo`/`printf` (filters between included; a shell or interpreter word stops the walk, since what reaches `tee` is then that program's output, which this section leaves alone; a sink's target is then a target too) | `cat > f <<'EOF'`, `printf '%s\n' x >> f`, `tee f <<'EOF'` |
| 6 | a shell word, `(ba\|z\|da\|k)?sh`, or a row-4 interpreter word | a **script operand** that is scratch (§3.3), and no inline script — for an interpreter word, none of row 4's script sources — **and**, in that script's text, judged as if the text were the scanned body of a heredoc fed to the same word: for an interpreter word, a row-4 write call; for a shell word, any row matching on a line of it. **The text** is the body of a heredoc that a row-5 `cat` or `tee` wrote to the operand's path earlier in the same unit, the latest such, or else the file at that path, read once (below) | `cat > /tmp/fix.py <<'EOF'` … `EOF` then `python3 /tmp/fix.py`, `python3 "$TMPDIR/fix.py"`, `cd /tmp/w && bash rewrite.sh` |

**Row 4's write calls.** Each pattern allows `\\?` before a quote, so an escaped `\"w\"` is seen;
`\|` is `|` (§3):

- **a bare `open(` with a write mode after a comma** —
  `(?<!\w)open\((?:[^()]\|\((?:[^()]\|\([^()]*\))*\))*,\s*(?:mode\s*=\s*)?\\?['"](w\|a\|x\|r[bt]?\+)[bt+]*(?:[:\|]\w+)?\\?['"]`.
  A read of a file named `x` or `w` is not a write; `Popen(` and `fdopen(` are not `open(`; two
  levels of nested call are seen (`open(os.path.join(os.path.dirname(__file__),'x'),'w')`), a
  third is a miss (§7), and the alternatives are disjoint on their first character, so it cannot
  backtrack badly. A module prefix (`io.`, `gzip.`, `tarfile.`, `codecs.`, node's `fs.`) changes
  nothing; `[:\|]\w+` keeps `tarfile`'s `'w:gz'`.
- **a `.open(` on a receiver with a write mode first**, positional or `mode=` —
  `(?:(?<![\w.])\w+\|\))\.open\(\s*(?:mode\s*=\s*)?\\?['"](w\|a\|x\|r[bt]?\+)[bt+]*(?:[:\|]\w+)?\\?['"]`,
  the receiver word not a module whose `open(` takes a path first (`io`, `codecs`, `gzip`, `bz2`,
  `lzma`, `tarfile`, `wave`, `aifc`, `fsspec`, `smart_open`, `fs`), so `io.open('w')` — a read of
  a file named `w` — is no write.
- **`\.write_text\(`, `\.write_bytes\(`**.
- **node's `(write\|append)File(Sync)?\(` and `createWriteStream\(`**.
- **`fileinput`'s in-place mode** —
  `(?:fileinput\.)?(?:input\|FileInput)\((?:[^()]\|\([^()]*\))*inplace\s*=\s*(?:True\|1)\b`, so
  pandas' `df.dropna(inplace=True)` is not a write.

**Row 6's script operand** is the first token after the command word that is neither an option nor
a redirect token (§3.1), §3.1's wrappers already passed: a token starting `-` is an option, and so
is one starting `+` after a shell word, and `--` ends the options, the token after it being the
operand. **Some options take the next token as their argument**: a Python word's
`--check-hash-based-pycs`; node's `-r`, `--require`, `--import`, `--loader`,
`--experimental-loader`, `--input-type`, `-C` and `--conditions`; a shell word's `-o`, `+o`, `-O`,
`+O`, `--rcfile` and `--init-file`. A Python word's short-flag cluster is read letter by letter:
`W` or `X` takes the rest of the token as its argument, or the next token when it is last
(`-Werror`, `-W ignore`, `-X utf8`) — a cluster that row 4 reads as a script flag never gets here
(§7). **Some options mean there is
no script file**: in a Python cluster, `m` (a module) or `c`; node's `-e`, `-p`, `--eval` and
`--print`; a shell word's cluster containing `c` or `s` (an inline script, or stdin); and a bare `-`
(stdin) after any of them. The operand is resolved
and tested for scratch exactly as a target is (§3.3): quotes removed, a variable bound earlier
substituted, a `cd` earlier in the same unit followed. **Only a scratch operand matches**: `python
fix.py` in the project runs one of the project's own programs, which this row leaves alone.

**Row 6's text.** A body is **staged** for a path by a row-5 `cat` with a heredoc of its own, or by
a row-5 `tee` fed by a heredoc — its own, or one earlier in its pipeline, as row 5's walk back finds
it — whose sink or `tee` target resolves to that path under the location in force at that command.
Where a body was staged for the operand's resolved path earlier in the same unit (the command's own
lines, or one scanned body), the latest such body is the text, raw: unexpanded even under an
unquoted delimiter, where the shell would first expand any `$…` in it, and untransformed by any
filter between the heredoc and the `tee`. Otherwise **the file at that path is read, once**. The
path is the operand's resolved one, except that a leading `$TMPDIR` or `${TMPDIR}` stands for the
hook's own `$TMPDIR`, and `${TMPDIR:-DEFAULT}` for it or, unset, for `DEFAULT`; any other
`${TMPDIR…}` names no file. The read takes at most 256 KiB, of a regular file and not a symlink
(opened without following one and without blocking), decoded as UTF-8 with undecodable bytes
replaced. A missing file, any other kind of file, a larger one, or any error reading it means no
text, and the row does not match (§6). A script staged in the same command by any other means is
read from the file, which then holds whatever an earlier call left there (§7).

**Row 6's judging.** An interpreter's text is searched for row 4's write calls as a scanned body fed
to it is, §3.1's comments removed, and its targets are judged by §3.3's row-4 rules. **Both start
from the directory in force at the run and no bindings**: the script's process inherits that
directory and none of the command's unexported variables. A shell's text is delimited and judged
as a scanned body is — every row, line by line, its own heredocs scanned or data by the same rule,
its own bindings and `cd`s. **Inside a
script's text row 6 reads no file**: a script that runs another scratch script is judged only by
what its own text staged with a heredoc. The match's targets are the write calls' targets for an
interpreter, and for a shell every target of every row matched in its text, a matched row with no
target contributing one that is not exempt — so the match is exempt only when everything the
script would write is scratch. The override is read from the command alone (§3.4), never from a
script's text.

**Several forms in one command** are judged each on its own targets: the command is denied if any
matched form has a target that is not exempt and there is no valid override, and the message names
the first such form.

**Heredoc bodies.** A body runs from the line after an unquoted `<<`/`<<-` opener — never `<<<`, a
here-string, which opens no body — to the line equal to its delimiter. The delimiter is the next
word after the opener, with or without whitespace between, compared with its quotes or a leading
backslash removed (`<<'EOF'`, `<<"EOF"`, `<<\EOF`), and under `<<-` with leading tabs stripped.
**Rows 1–4 scan a body only when something will execute it**: when the opener's **pipeline** — the
simple commands joined by `|` on either side of the opener, bounded by `;`, `&&`, `||` or the
line end — has a shell or interpreter word, `(ba|z|da|k)?sh` or row 4's interpreter words —
matched as the whole word, with §3.1's path prefix (`/bin/bash`) and quotes removed, so `ssh` is
not `sh` — as the command word of one of them (an opener inside an unclosed `$(` is in the pipeline
of the simple command enclosing the `$(`, so `python3 -c "$(cat <<'EOF'` and `bash -c "$(cat
<<'EOF'` are scanned while `gh pr create --body "$(cat <<'EOF'` is not), as in `bash <<'EOF'`,
`sudo bash <<'EOF'`, `cat <<'EOF' | bash`, `tee /tmp/fix.sh <<'EOF' | bash`, `python3 - <<'EOF'`
and `cat <<'EOF' | python3 -`. An opener on a line of a scanned body opens a body on the same
terms, so a script staged from inside a `bash` heredoc is still data. Bodies are delimited before
a multi-line string's close is sought (§3.1's order), so a `"` inside a body, scanned or data,
never closes a `python3 -c "$(cat <<'EOF' … EOF)"` string.
Every other body is data and is never scanned, so a scratch script staged with
`cat > /tmp/fix.sh <<'EOF'`, and a PR or commit message under `gh pr create --body "$(cat <<'EOF'
…)"`, cannot be denied for what they contain — until row 6 runs the script, when the staged body
is that row's text. In a scanned body each line outside a multi-line
string opened inside it counts as a line start
for §3.1. **Row 5 never looks inside a heredoc body for its sink** — the sink must be in its own
simple command on the opener's line, so the PR body's `>` and `->` never read as sinks — but a
row-5 line *in* a scanned body is judged as any other line start (`bash <<'EOF'` / `echo x > f`
is denied).

**Not denied**: an ordinary command's output redirected to a file (`pytest -q > log`), redirects to
file descriptors (`2>&1`), `sed -n`, an interpreter script with no write call, **a transformation's
output redirected to a file** (`sed 's/a/b/' f > g`, `awk '{…}' f > g`, `perl -pe … f > g`, with
or without an `mv g f` after), an interpreter's printed output redirected to a file
(`python3 -c 'print("…")' > f`), and running a script file outside scratch (`python fix.py`). The transformation
idiom is a find-replace edit by this document's own definition, and it is left alone because a
redirected transformation is indistinguishable by pattern from ordinary data processing into a new
file — `awk '{print $1}' data > out.csv` — which a deny would stop; §7's count (c) is what would
show agents routing around a deny through it, and `ex`/`ed` are misses on the same terms.
**A scratch script is judged and any other script file is not, and the line is drawn on
evidence.** A script under scratch is the agent's own, written for the task in hand, and staging a
bulk edit as one and running it is a reflexive route: in local transcripts 231 Bash calls ran a
`/tmp` script, 85 of them staged by a heredoc in the same command, and replayed through this row,
54 of 33,069 calls are denied by it first — 47 of them an authored file rewritten by the script,
2 golden files the override answers, and 5 the stated false deny of a script given its targets as
arguments (`research/m37-scratch-script-replay.md`). A script elsewhere is one of the project's own
programs — a generator, a formatter, a release tool — whose writes are its job, and reading it
would deny the project its own tooling. The guard is a nudge with teeth for the reflexive case, not
a security boundary.

### 3.3 Exempt targets

A target is **scratch** when, after every quote in it is removed (with the backslash escaping it, if
any) and a relative path is joined to the payload's `cwd` and normalised as a string — no
filesystem access — it is, or lies under, `/tmp`, `/var/tmp`, `/dev`, the value of `$TMPDIR`, or
the payload's `scratchpad_dir` where a version sends one (2.1.285 does not) — compared
component-wise, so `/tmp` itself counts and `/tmpfoo` does not — or is written as the literal
`$TMPDIR/…` or `${TMPDIR…}/…` (so `"$TMPDIR"/probe` and `${TMPDIR:-/tmp}/probe` count). A
`$TMPDIR` that is empty or `/` is ignored, since it would make everything scratch, and a relative
one is joined to the payload's `cwd` first; the same holds for `scratchpad_dir`. **A target that
begins with a variable the command bound is read with the variable's value in its place**: where a
target starts `$NAME` or `${NAME}` — after its quotes are removed, and ending there or followed by
`/` — and a simple command made only of `NAME=value` words, earlier in the same unit (the command's
own lines, or one scanned body), bound `NAME`, the last such value replaces it. So
`S=/tmp/x; echo y > "$S/a"` is scratch, `R=research; echo y > "$R/a"` names `<cwd>/research/a`, and
`t=$(mktemp); echo x > "$t"` stays a false deny, its value being `$(mktemp)`. A prefix assignment
(`S=/tmp/x echo y > "$S/a"`) binds nothing, as the shell expands the word before it takes effect,
and a scanned body starts with no bindings, as the shell that runs it inherits no unexported
variable. The payload's
`cwd` follows a `cd` made in an earlier call (measured), and **a `cd` inside the same command is
followed too**: a simple command that is exactly `cd DIR` makes later relative targets in the same
unit resolve against DIR, itself read as a target is (quotes removed, a bound variable substituted,
joined to the directory before it). So `cd /tmp/x && sed -i … f` is scratch and `cd design && sed
-i … x.md` names `<cwd>/design/x.md`. It is not followed in a unit that holds a `(` subshell, whose
`cd` need not outlive it, nor for `cd` alone, `cd -` or a `~` directory, which the rules cannot
know; a scanned body starts from the payload's `cwd`. **A same-line `$(…)` is a subshell too**:
what its own commands bind or move to is not carried to the commands after it, and a `(` inside
one — `$((…))` included — is not the unit's subshell. So `x=$(cd /tmp && pwd); echo y > f` names
`<cwd>/f`, and `cd /tmp/x && echo $((1+1)) > f` is scratch. On macOS the roots `/tmp`, `/var/tmp` and `$TMPDIR` are symlinks under `/private`,
and tools that canonicalise print that spelling, so — on every platform, since nothing on Linux
lives there and the table then needs no platform pin — a target under `/private` followed by any of
those roots is scratch by the same component-wise test. Nothing else is resolved through
symlinks. A matched form is exempt when **every** one of its targets is
scratch and it has at least one. The targets are, per form:

- **Rows 1–3**: the simple command's tokens after the command word that do not start with `-`, are
  not redirect tokens (§3.1), and are not the argument of a flag that takes one — `-e`, `-f`,
  `--expression`, `--file`, perl's `-E`, any short-flag cluster whose last letter is `e` or `f`
  (`-pe`, `-ne`), a perl cluster ending in `E`, and a `-e`/`-E`/`-f` glued to its argument
  (`-e's/a/b/'`, `-es/a/b/`), which counts as present and carries it — though for sed `-E` is
  argument-less, and a
  `-<c>*i<suffix>` token is never a script-carrying cluster whatever its suffix ends in — row 3's
  `-i inplace` and `--include inplace`, awk's `-v` and `-F`, GNU sed's `-l`/`--line-length`,
  perl's `-I` and `-M` and ruby's `-I` and `-r` written with a separate argument, and, after a
  `-<c>*[iI]` token that carries no suffix, an immediately following empty quoted string (`''` or
  `""`), BSD sed's suffix argument on macOS — **minus the first such token, the script, unless** one of the script-carrying flags
  (`-e`, `-f`, their long forms including `--expression=…` and `--file=…`, perl's `-E`, and a
  cluster ending in one of them) is present. So `sed -i 's|/usr|/opt|' /tmp/x` and
  `sed -i '' 's/a/b/' /tmp/x` are exempt: each has the one target `/tmp/x`.
- **Row 4**: each write call (§3.2's list) has one **target expression**, and only it is judged:
  - for a bare `open(`, `writeFile*(`/`appendFile*(`/`createWriteStream(` and `fileinput`'s call,
    the **first argument** (or a `file=`/`path=` keyword);
  - for `.write_text(`, `.write_bytes(` and a receiver `.open(`, the **receiver** — the operand
    before the method: a name, a call (`Path(…)`) or a parenthesised group, with any `.name(…)` chain
    between.

  A name or path anywhere else in the statement — the data being written, another call's
  argument — contributes nothing. A target expression that yields nothing makes the form not
  exempt: it is denied naming no target.

  **Judging a target expression: its head decides.** Its first operand is a name, a string
  literal, a `Path(…)`, a call, or a parenthesised group — its contents judged as a target expression (all six steps) — **together
  with any `.name`/`.name(…)` chain after it**; the part
  before that chain is the **head**. Step 1 looks at the whole operand, step 6 at the chain, and
  steps 2–5 at the head alone — so `Path('/tmp/report.md').stem` and `d.joinpath('x')` are step 6,
  never step 3 nor step 5's catch-all:
  1. **A scratch call**, checked on the whole operand first → a scratch target. A scratch call is a
     `tempfile.` call; a bare `mkdtemp(`, `mkstemp(`, `mktemp(`, `gettempdir(`, `TemporaryFile(`,
     `NamedTemporaryFile(`, `SpooledTemporaryFile(` or `TemporaryDirectory(`; a `tmpdir()` call
     (`\btmpdir\(\)`: node's `os.tmpdir()` or `require('os').tmpdir()`); or a read of `$TMPDIR`
     (`environ['TMPDIR']`, `environ.get('TMPDIR', …)`, `getenv('TMPDIR')`, node's
     `process.env.TMPDIR`).
  2. **A string literal** → that literal (below), joined to `cwd` when relative.
  3. **A `Path('…')`** (with or without a `pathlib.` prefix; several literal arguments joined with
     `/`), with its `/` chain's literals joined up to the first non-literal operand
     (`Path('/tmp') / n / 'x'` gives `/tmp`) → that path; `Path(<scratch call>)` → scratch.
  4. **A bound name** → its binding's target (below); an unbound name → nothing.
  5. **A path function** — `str(`, `Path(`, `os.path.join(`, `os.path.abspath(`,
     `os.path.expanduser(`, `os.path.realpath(`, `os.path.dirname(`, `os.fspath(`, node's
     `path.join(`/`path.resolve(` → its first argument, judged as a target expression (all six steps) (an `os.path.join(` or
     `path.join(` with several leading literals joins them with `/`). **Any other call → nothing.**
  6. **A chain after the head** — a name, a `Path(…)`, a path function's call or a parenthesised group (`src.with_suffix('.json')`,
     `p.parent / 'x'`, `os.path.join(d, 'x').upper()`) →
     the head's target, except that a chain **containing** a read or a name component —
     `.read_text(`, `.read_bytes(`, `.read(`, `.readlines(`, `.exists(`, `.is_file(`, `.is_dir(`,
     `.stat(`, `.iterdir(`, `.glob(`, `.rglob(`, `.stem`, `.name`, `.suffix`, `.parts`, or a
     `.open(` with no write mode — yields nothing.

  Whatever leads governs: a scratch call or scratch-bound name later in the expression changes
  nothing, so `Path('research') / src.name` names `research` whatever `src` holds.
  **Bindings.** A statement runs to a `;` or newline outside string literals and unclosed
  brackets. A name is bound by `name = <expr>` — the identifier at a statement's start, after an
  optional `const`, `let` or `var`, with an optional `: type`, before `=` — to `<expr>` judged as a
  target expression is (so a scratch head binds a scratch target, `OUT = d + '/x'` takes `d`'s
  target, and a bare alias `q = p` takes `p`'s); a later binding of the same name replaces the
  earlier. `with <expr> as name` binds `name` as a scratch target where `<expr>`'s head is a
  scratch call, and otherwise binds nothing, so `with open('CLAUDE.md') as src` never makes `src`
  a target; the `with` items may be enclosed in `(…)` and span lines, as `ruff format` writes a
  long `with`. A keyword argument (`encoding='utf-8'`) binds nothing, and a name is matched as
  `(?<![\w.])name\b`, so an attribute of the same spelling (`os.path`) is not the name.

  **Literals.** A literal may carry a prefix (`f`, `r`, `b`, `rb`, `fr`) and is compared with the
  prefix removed and any `{…}` left in place; in a node script a backtick-delimited literal is a
  literal too, with any `${…}` left in place. A `{…}` or `${…}` span **at the literal's start** is
  itself judged as a target expression (all six steps), so `f'{d}/x'` with `d` scratch-bound and `` `${os.tmpdir()}/x` `` are
  scratch — and where that head yields nothing, the literal contributes as written, relative
  (`` `${d}/x` `` with `d` unbound names `<cwd>/${d}/x`, so the misread shows) — while a span after a literal prefix (`f'research/{d}'`) is not a head and the prefix
  governs. A literal immediately followed by `+`, `%` or `.format(` contributes that literal
  alone — `'/tmp/' + n` and `'/tmp/%s.json' % n` are scratch, `'{}/x'.format(d)` and
  `'out' + str(i)` are relative and not.

  So reading or enumerating authored files — chained or through a name — and writing the result
  to `/tmp/` is exempt; `p = Path('/tmp/x'); p.write_text(…)`,
  `out = Path('/tmp/in.md').with_suffix('.json'); out.write_text(…)` and
  `Path('/tmp/x').open('w')` are exempt; `p = Path('CLAUDE.md'); p.write_text(…)` and its alias
  `q = p; q.write_text(…)` are denied naming `CLAUDE.md`.
- **Row 5**: the token after each sink, or `tee`'s tokens that do not start with `-`.
- **Row 6**: what its script's text yields, judged as §3.2's "Row 6's judging" says — never the
  operand itself, which only has to be scratch for the row to match.

The session scratchpad sits under `/tmp/` on Linux. On macOS, where `$TMPDIR` is under
`/var/folders/…`, where the scratchpad sits is unmeasured; if it is under `$TMPDIR` it is exempt by
the same rule, and if not, writes there are a false deny the override answers.

### 3.4 The override

The override is examined **only after a form has matched** with a target that is not exempt; a
marker on a command no form matches changes nothing. **A marker inside a heredoc body (§3.2) is
content, not an override** — the guard's own tests and documentation, written through a heredoc,
contain it; so is a marker inside a quoted string, including on a line of a multi-line string
(§3.1), where a Python `#ZIKARON-FORCE …` line would otherwise read as a shell comment.
A valid override is a match, on a line of the
command that is not a heredoc body, against that line's **comment** — the text from §3.1's
unquoted `#` to the end of the line — for

```
(^|\s)#ZIKARON-FORCE[ \t]+#Reason:[ \t]*\S+[ \t]+\S+
```

— the marker preceded by whitespace or a line start, so the shell reads it as a comment and not as
part of a word, and a reason of **at least two whitespace-delimited words on the marker's own line**.
Quotes inside the comment are not parsed, as the shell does not parse them, so `#Reason: 'golden
file'` has two words. **The reason — the text after `#Reason:` to the end of the line — is invalid
when fewer than two words remain after every `<…>` span is removed**, so pasting a template's
`#Reason: <few words>` is not an override, while `#Reason: fix <12> now` is. A marker inside a
quoted string precedes no unquoted `#`, so it is never in a comment.

- **On a valid override the hook returns no `permissionDecision`**: exit 0 with JSON carrying only
  `hookSpecificOutput.hookEventName` and an `additionalContext` line acknowledging the override and
  its reason (content draft: `#ZIKARON-FORCE accepted — reason: <reason>. The find-replace guard
  withdrew its deny; the usual permission flow applies.` — final wording per §5's prompt-text
  rule, and the live test greps for it). **The acknowledgement also asks for the re-read** that
  §4's nudge asks after an `Edit` or `Write` and cannot ask here, since it fires on neither a
  `Bash` call nor its result: it names what the overridden command changes — every target that is
  not exempt, of every form that matched, resolved and in command order as the deny names them
  (§3.5), each path once, or the deny's fixed clause where none resolves — and asks for one
  re-read of the changed material and its surroundings once the command has run (operator,
  2026-10-07; in the interactive test's arm C, `research/m37-guard-interactive-test.md`, an
  overridden scratch script rewrote all fourteen files, no nudge followed, and eleven were never
  re-read). The harness's own permission flow then decides exactly as if no guard were installed
  (§2, measured). **The override withdraws the deny and grants nothing**; returning `allow` would
  skip the approval the user's own policy asks for, on exactly the commands the guard exists to
  watch.
- A marker that is present but invalid — `#ZIKARON-FORCE` appears on a line that is not a heredoc
  body, outside a quoted string — one-line or multi-line — and no comment carries a
  match: bare, a one-word reason, or glued to a preceding word (`f#ZIKARON-FORCE` is in no
  comment) — is **denied** with a message saying what is missing. A marker only in a heredoc body
  or a quoted string gets the ordinary deny message.
- No separate override log. The command and its reason are in the harness transcript, which is
  where §7 counts them.
- The override exists for the legitimate exceptions — a file whose bytes a program owns (this
  repository's `.kiro/` golden files), a bulk mechanical change across many files — and for a guard
  that is wrong. **A false deny stops work outright**, so the escape hatch is not optional.

### 3.5 The deny message

`permissionDecisionReason`, in this order: which form matched, **the targets the rules found that
are not scratch — as resolved, so a misread shows (`<cwd>/~/f`) — or that none was found**, and why
the rule exists (an edit made to text you have not read in its current state); the alternative
(`Read` then `Edit`, or `Write` for a new file); and the override's exact syntax, shown with a
concrete reason (`#ZIKARON-FORCE #Reason: regenerate golden file`) rather than a placeholder. One
short paragraph — it is shown on every deny. §8's "naming `X`", "naming the authored target" and
"naming no literal" cells assert the target part. **When the command carried a marker only inside a heredoc body or a
quoted string**, the message adds that the override is a shell comment outside them — on the
heredoc opener's line, a line after the delimiter, or after a multi-line string's closing quote —
since a marker on the delimiter line stops the heredoc terminating and the shell writes it into
the file.

## 4. The re-read nudge — `PostToolUse`, matcher `Edit|MultiEdit|NotebookEdit|Write`

A payload whose `tool_name` is not one of those four gets nothing — so a file changed by a `Bash`
command is never nudged, and where the guard let such a command through on an override, its
acknowledgement asks for the re-read instead (§3.4). After each successful edit, the hook adds
`additionalContext` (content draft; final wording per §5's prompt-text rule):

> `<path>` was edited (lines `<ranges>`) and has not yet been re-read for flow and consistency with
> the rest of the file. Once editing of this file is finished, the next step is to re-read all the
> edited material and its surroundings.

- **It fires on every edit**, and it asks for the re-read **once editing of that file is done**, so
  an agent making several edits to one file can plan one re-read rather than one per edit (operator
  decision 2026-10-06). It carries the operator's content — does it flow, is it consistent, re-read
  once done — **phrased as statements about the file rather than as commands**, because the
  documentation asks for factual statements and reports that `additionalContext` framed as
  out-of-band system commands can trigger the model's injection defences and be surfaced to the user
  instead of acted on (`research/claude-code-tool-hooks-docs.md` §3.3, summarised rather than
  verbatim).
- `<path>` is `tool_input.file_path`, or `tool_input.notebook_path` for `NotebookEdit`.
- `<ranges>` comes from the result's `structuredPatch`, new-side line numbers, read from
  `tool_response` or, where a version names it so, `tool_output`. Where there is no patch —
  `NotebookEdit`, or a shape the hook does not recognise — the parenthesis is omitted, never
  guessed.
- **A `Write` whose result `type` is `"create"` gets no nudge**: a new file has no surroundings. An
  overwrite (`"update"`) does, and so does a `Write` whose result carries no `type`. §6's silence
  is for a field the decision needs, and the nudge needs only the path: a missing patch drops the
  parenthesis, a missing `type` reads as an overwrite.
- **A scratch `<path>` (§3.3's test) gets no nudge**: the rule is about authored files, and a probe
  script under `/tmp/` is not one.
- **Cost**: the template is 218 characters before the path and ranges are filled in — roughly 55
  tokens per edit at about four characters a token, plus the path — persisted in the transcript and
  replayed on resume.
- It never denies or blocks; a `PostToolUse` hook cannot undo an edit that has already happened.

**What it competes with.** The `Edit` result tells the model *"no need to Read it back"*. That is
about the harness's view of file state, not consistency, and the nudge says what it is asking for.

## 5. Installation

The installer offers **three** selections: the memory store (what an install writes today), the
guards, or both. **Guards are installed only on request**; the default is unchanged. Guards are
Claude Code only, and selecting them with `--harness kiro` is refused before anything is written.

- **One console script, `zikaron-guard`**, reading `hook_event_name` from stdin to choose the rule.
  Its hook groups sit in `.claude/settings.local.json` beside the memory hooks, for the same reason —
  the command is an absolute path into one virtualenv.
- **The start text goes through the existing `zikaron-hook`, not a new hook.** `zikaron-hook`
  already owns `SessionStart` and `SubagentStart`, where it injects the write policy (D18). The
  installer writes the selection into that entry's command, as `zikaron-hook --components
  guards|both`, and the hook builds its text from the flag alone, with no file read and no
  service query:
  - no flag (`memory`): the write policy, exactly as today, so a default install's entry is
    byte-for-byte unchanged.
  - `guards`: only the guard start text. No service connect, no warm helper, no store. So a
    guards-only install also writes the `SessionStart`/`SubagentStart` groups and needs the
    `zikaron-hook` script.
  - `both`: the write policy, then the guard start text, one blank line between.

  The consolidator gets no start text under any selection: its system prompt is its whole
  instruction, which is why the write policy already skips it, and it holds no editing tool.

  The guard start text must say: authored files are edited with `Read` then `Edit`, or `Write`
  for a new file, never with `sed -i`, an inline interpreter script, a script staged in scratch
  and run, or a heredoc redirect; scratch paths are exempt as targets; and after each edit a
  reminder from this project's hooks will ask for one re-read once that file's editing is done.
  That last part also tells the agent where the
  nudge comes from, which guards against the injection-defence risk §4 records. **It does not
  mention the override** (operator decision 2026-10-07): the deny message teaches the override
  when it is needed, and announcing it at start invites the reflexive use §7's count (c) watches
  for.
- **Every prompt text's final wording is written by memory-reviewer at build time** (operator
  decision 2026-10-07). That covers the guard start text, the deny message (§3.5), the
  invalid-marker message, the override acknowledgement (§3.4) and the nudge (§4). This document
  states what each text must contain; any wording quoted here is a content draft. The builder
  copies the reviewer's wording verbatim, and the tests assert it.
- **Each guard entry states its `timeout`: 10 s**, a constant in `zikaron/guard/` the installer
  reads, and the worst stall a wedged guard can cost one tool call. It is independent of the memory
  hook's `HOOK_TIMEOUT_SECONDS`, which is sized to that hook's internal deadlines; the guard has
  none, and 10 s is simply far above one Python start while far below Claude Code's 600 s default
  for tool events, which an unstated timeout would inherit.
- **The tool names live once**, in the spec field's matchers (§1). The guard reads its `tool_name`
  checks from that field by splitting each matcher on `|`, so widening a matcher widens what the
  guard judges. A matcher is therefore a `|`-joined list of bare tool names, never a regex, and a
  test holds that.
- **An install touches only the selection it was given.** It replaces or adds that selection's own
  hook groups, and never removes another's: installing the guards over a memory install keeps the
  memory hooks, and re-running a memory install keeps the guards. Removal is out of scope. **The
  shared start entry takes the union** of what it already carries and what is being installed:
  `guards` over a memory install writes `--components both`, and `memory` over a guards or both
  install keeps `--components both`, so neither install ever drops the other's start text.
- **The guards selection writes the guard groups and the start entry under `hooks` and nothing
  else** in `settings.local.json` — no `enabledMcpjsonServers`, no `permissions.allow` entry — writes no
  `.mcp.json`, ships neither the consolidator nor the skill, and reports none of the memory
  install's notes. A memory install removes none of the guards'.
- A guards-only install needs no store, no service and no model. `--model` names a consolidator the
  selection does not ship, so it is **refused** under `guards`, as `--agent` is refused under Claude
  Code rather than silently discarded; `--no-trust-tools` asks for nothing to be done and is
  accepted as a no-op.

## 6. Failure behaviour

**Every failure is an allow, silently.** Malformed stdin, an unknown `hook_event_name`, a missing
field, an exception: the hook exits 0 with no output, and the tool call proceeds as if no guard were
installed. A guard that blocks on its own defect stops work for a reason that is not the agent's,
which is worse than a guard that misses one edit. **A hang allows only when the harness's timeout
expires**, which §5 bounds by stating it in every entry. **Row 6's read is the one place the guard
touches the filesystem, and it fails the same way**: a script it cannot read, or will not, is a
row that does not match — and it opens without blocking, so a FIFO at the operand's path cannot
hang it.

**The guard is also silent when it does not run at all**: under `--bare`, `disableAllHooks` or
`allowManagedHooksOnly`, and a plugin may approve a call it denied
(`research/claude-code-tool-hooks-docs.md` §5). A miss in a session like that is not a regex
defect.

## 7. Known gaps, and the counts that would move them

- Every script file outside scratch, `python fix.py` included (§3.2). Inside scratch, row 6 misses
  a script larger than 256 KiB, one whose own path is a symlink, one whose path the rules cannot
  read as scratch (`python3 "$(mktemp)"`, `python3 "$t"` after `t=$(mktemp)`), one run as its own
  command word (`/tmp/fix.sh`, `uv run /tmp/fix.py`), and one after a shell flag cluster ending in
  `o`, which takes no argument here, so `bash -euxo pipefail /tmp/fix.sh` reads `pipefail` as the
  operand. **An interpreter whose pipeline also carries a row-4 source** — a heredoc or here-string
  as the script's input, an `echo`/`printf` piped into it, or a row-4 script flag among the
  interpreter's own arguments, after the operand included: Python's `-E`, a `-W`/`-X` cluster of
  letters and digits ending in `e` (`-Wignore`, `-Ximporttime`; `-Werror::Foo:mod` is not one), a
  `-c` meant for the script (`python3 /tmp/fix.py -c cfg`) — is row 4's and not row 6's, so the
  scratch script it runs is not judged (`python3 /tmp/fix.py <<'EOF'` with a file list in the
  body). A script staged in the same command other than by a
  `cat`/`tee` heredoc (`printf … > /tmp/fix.py && python3 /tmp/fix.py`, `cp`, a here-string
  `tee /tmp/fix.py <<< "…"`), or staged in one unit for a run in another — the command's own lines
  and a scanned body are units apart (§3.2), either way round — is judged on what the file held
  before the command ran, or not at all where there was none; and a body **appended**
  (`cat >> /tmp/fix.py <<'EOF'`, `tee -a`) is the whole text, what the file held before it
  unjudged. Row 6 judges a file as it stands when the hook runs.
- The git commands `CLAUDE.md` forbids on its own account (`checkout -- <path>`, `restore`, `reset
  --hard`, `stash`, `clean`, and the redirect spelling `git show HEAD:<path> > <path>`) rewrite
  authored files and match nothing here: they belong to a different rule, not this guard, and the
  miss is not a defect. `git show HEAD:<path> > /tmp/…`, the pristine copy `CLAUDE.md` prescribes,
  is silent too.
- A write form not in §3.2's table — `dd`, `install`, `cp` or `rsync` over a file, `git apply`, `patch`,
  `sd` (in-place by default), `yq -i`, `… | sponge f`, and their interpreter analogues
  `shutil.copy`/`shutil.move`/`os.replace`, `Path('f').rename(`/`.replace(`, `os.open(`/`os.write(`,
  `df.to_csv('f')`, `np.save('f')`, `File.binwrite(`, perl's `write_file(`; write routes inside
  other tools — `sort -o f`, awk's own `print > "f"` inside its program, sed's own `w` flag and
  command (`sed 's/a/b/w out' f`, `sed -n '/x/w out' f`), `fastmod`, `comby`; and
  `exec > f` and `truncate -s 0 f` beside `: > f`; a `mode=` keyword on a call that is not
  `open(` (`df.to_csv('f', mode='a')`, `logging.FileHandler('f', mode='a')`,
  `zipfile.ZipFile('f', mode='w')`, `os.fdopen(fd, mode='w')`); and a `.open(` whose receiver word
  is itself after a `.` or `]` (`p.parent.open('w')`, `paths[0].open('w')`). Adding any is a
  change to this section.
- **Shell quoting is parsed only as far as §3.1 says.** A multi-line string is one token, so
  `echo "a` / `b" > f` is denied and a commit message typed as `git commit -m "Title` / `sed -i is
  refused"` is not; but an unquoted `<<` inside one opens a data body, since bodies are delimited
  first, and what follows it is unseen. A sink glued inside a word (`echo x>f`) is missed, as is an opener glued to its command word
  (`cat<<EOF > f`); a string literal that quotes a whole write call (`print(repr("open('f','w')"))`)
  is matched as a write and denied naming nothing, as is a triple-quoted string spanning lines,
  whose inner lines are searched as code; and a `>` inside `$((…))` reads as a sink of the simple
  command inside the substitution, whose command word is the arithmetic's first operand and
  matches no form, so `echo $(( 1 > 0 )) > /tmp/x` is silent and only the enclosing command's own
  sink is judged.
- **The expected value of each remaining edge**, so a test table states it rather than a builder
  deciding it:
  - **misses**: `bash -c '…'`/`sh -c '…'` (the script is one quoted token), and a script piped
    into a shell as one string (`echo "sed -i … f" | bash`, `printf … | sh`), with no body to scan; `{ echo a; echo b; } > f`
    and `(echo a; echo b) > f`; `echo x | cat > f` and `cat <<'EOF' | grep x > f`; `&>`, `>& f`,
    `>|` and `1> f`; a `cd` or an assignment inside a `$(` that does not close on its line, read
    as the unit's own since §3.3's subshell sentence is for the same-line form (`x=$(` / `cd /tmp`
    / `)` / `echo y > f`);
    `eval "sed -i …"`;
    node's `--eval` and `-p`; `ex` and `ed`, and `vim -es -c '%s/a/b/g' -c wq f` and its
    `vi`/`nvim --headless` kin, the same deliberate class; `parallel`; `ipython -c …`, not a row-4
    word; a redirection before the command word
    (`> f cat <<'EOF'`); a `$(…)` inside a one-line or multi-line double-quoted string (`x="$(sed -i … f)"`, kept
    whole by §3.1) and a backtick substitution; a body fed to a shell whose word is quoted, absent,
    or behind a word that is no wrapper (`ssh host 'bash -s' <<'EOF'`, `ssh host bash <<'EOF'`,
    `sudo -s <<'EOF'`, `su -c`, `doas`, `docker exec -i c bash <<'EOF'`, `docker run … sed -i …
    /w/f` over a bind mount, `kubectl exec`);
    truncation by
    `: > f` or a bare `> f`; a perl or ruby program that writes through `open`/`File`, inline
    (`perl -e`, `ruby -e`, `perl <<'EOF'`) — row 2 catches `-i`, and the rest is count (c)'s; the
    Homebrew `$(brew --prefix gnu-sed)/libexec/gnubin/sed` spelling, which a person types and an
    agent writes as `gsed`; `bun -e`, `deno eval`, `php -r`, `Rscript -e`, `lua -e`, `npx tsx -e`
    and `ts-node -e`; `tee f < /tmp/x` and `cat /tmp/x | tee f`, copy route-arounds `tee` does not
    match;
    `uvx python -c …`, `flock /path cmd`, `setsid`, `stdbuf -oL`, `ionice -c 3`, `chroot /root`,
    `unshare`, `nsenter`, `strace -f`, `caffeinate`, `script -q /dev/null`, `conda run -n env`,
    `mamba run`, `hatch run`, `pipx run`, and `uv run --with-requirements r.txt`/`--with-editable .`,
    whose wrappers or argument-taking flags are not listed; `cat fix.py | python3`,
    `python3 < fix.py` and `python3 - < fix.py`, a script file by another route, missed even for a
    scratch `fix.py` since row 6 reads only an operand; a `$(…)` or backtick inside the body of a heredoc whose delimiter is unquoted, which
    the shell executes while §3.2 treats the body as data; a process substitution containing
    whitespace (`tee >(cat -n) f`); a script held in a variable or a substitution
    (`S='open("f","w").write("x")'; python3 -c "$S"`, `python3 -c "$(cat fix.py)"`,
    `python3 -c "exec(open('fix.py').read())"`) or a mode held in a name (`mode = 'w';
    open('CLAUDE.md', mode)`); a shell run from inside a row-4 script
    (`subprocess.run("sed -i …", shell=True)`, `os.system(…)`); an interpreter held in a variable
    (`$PYTHON -c …`, `"$PYTHON" -c …`); an unquoted `<<` that is an operator in a scanned body or a multi-line `-c` string
    (`x = 1 << 20`), or a shell arithmetic `<<` (`x=$((1<<3))`), which opens a data body since bodies are delimited first, so what follows it
    is unseen — nothing tells it from `<<3` by regex; `ssh host <<'EOF'`; a body under `fish`,
    `ash`, `csh` or `tcsh`,
    which `(ba|z|da|k)?sh` does not name;
    `! sed -i …`, since `!` is no command position; an `open(` nested three calls deep;
    `xargs -a /tmp/list sed -i …` and `uv run --project`/`--directory`/`--group …`, whose
    argument-taking flags are not listed; `fd -x`/`-X`/`--exec`/`--exec-batch sed -i …`, which is
    no command position; `source f` and `. f`, whose word is no shell word; and node's
    `fs.openSync('f','w')` and `fs.writeSync(fd, …)`;
  - **false denies on scratch**: `find /tmp/x -exec sed -i … {} +` (`{}` is never scratch); a
    target held in a variable after `mktemp` (`t=$(mktemp); sed -i … "$t"`, `echo x > "$t"`) or
    written inline (`echo x > "$(mktemp)"`, `echo x > $(mktemp)`); a path passed as a script
    argument (`python3 -c "open(sys.argv[1],'w').write('x')" /tmp/x`), and its row-6 form, a
    scratch script given its targets as arguments (`python3 /tmp/fix.py /tmp/x` over
    `open(sys.argv[1], 'w')`, `bash /tmp/fix.sh /tmp/x` over `sed -i … "$1"`);
    a path arriving through a function parameter, a loop variable or tuple unpacking (`a, b =
    '/tmp/a', '/tmp/b'; open(a,'w')`; `def save(p): open(p,'w')`,
    `for p in ['/tmp/a','/tmp/b']: open(p,'w')`); a loop over scratch files
    (`for f in /tmp/*.md; do sed -i … "$f"; done`) and its interpreter analogue (`for p in
    Path('/tmp').glob('*.md'): p.write_text('x')`, where `Path('/tmp')` is read by `.glob(` and the
    bare `.write_text(` contributes nothing); `ls /tmp/*.md | xargs sed -i …`, which has no target
    token at all; `perl -pi -e … $(ls /tmp/*.md)`, whose `$(…)` token is never scratch; BSD
    `sed -i .bak …` with the suffix as a separate word, which is dropped as the script; a
    backslash-escaped separator outside quotes (`\)`, `\|`, `\;`), which ends the simple command
    (`sed -i s/a\|b/c/ /tmp/x`; quoted, `'s/a\|b/c/'` is safe); a variable bound to a scratch path
    by a prefix assignment, or outside the scanned body that uses it (`S=/tmp/x echo y > "$S/a"`,
    `S=/tmp/x; bash <<'EOF'` / `echo y > "$S/a"`); old-style
    formatting with a scratch name (`'%s/x' % d`, `'{}/x'.format(d)`, where the literal alone
    contributes and is relative); a path returned by a call that is no path function
    (`out = make_path(d)`); `'/'.join([d, 'x'])`, where `'/'` contributes alone and is no scratch
    root; a subscript receiver (`paths[0].write_text(…)`); a path passed only as a keyword
    other than `file=`/`path=` (`fileinput.input(files='f', inplace=True)`), which names nothing;
    and a Claude Code background job's own `~/.claude/jobs/<id>/tmp`, which is no scratch root
    unless a version's payload names it as `scratchpad_dir` — seen in one session of the
    pre-install replay (`research/m37-guard-transcript-replay.md`);
  - **false denies**: a relative target after a `cd` the rules do not follow (§3.3) — in a unit
    holding a `(` subshell (`cd /tmp && (echo y > f)`), or `cd` alone, `cd -` or `cd ~/x` — which
    resolves against the payload's `cwd`; and one after a `cd` the rules follow to a directory
    they cannot read as scratch, since `DIR` is read as a path and the `$TMPDIR` literal rule looks
    only at a target's own text (`cd "$TMPDIR" && echo y > f`, `cd $(mktemp -d) && echo y > f`);
    `python3 tool.py <<'EOF'` whose body is data containing a
    write call, and `python3 - <<'EOF'` whose body holds a row-1 line Python will not run, since
    the opener's pipeline has an interpreter word and the over-match is accepted. A PR or commit
    body is no longer one: it is never scanned (§3.2);
  - **conservative and accepted**: `f() { sed -i 's/a/b/' "$1"; }` is denied though it only
    defines a function, since `{` is a command position;
  - **parsed as stated**: the heredoc delimiter as §3.2 defines it; `tee` with no target token
    (`echo x | tee`) does not match; a backslash-escaped double quote does not end a double-quoted string, and outside a string a backslash escapes
    nothing except as a line continuation and a quote it precedes (`\"`, `\'` open nothing, so
    `echo \"x\" > f` keeps its sink); a
    backslash-escaped space splits a token (`/tmp/my\ file` is two tokens, the second relative),
    so such a scratch target is a false deny; `~` and `$HOME` are not expanded, so `echo x > ~/f`
    is denied naming `<cwd>/~/f`; an unquoted `<<` inside a comment (`echo x > /tmp/x # see <<EOF
    below`) opens a body, since bodies are delimited before comments are found, and nothing closes
    it; with two openers on one line (`cat <<A <<B > f`) the second
    body begins after the first's delimiter line, as the shell reads it; the marker is
    case-sensitive, so `#zikaron-force` is no marker; ANSI-C quoting with an escaped quote
    (`echo $'it\'s' > f`) pairs at `\'` and opens a string that swallows the sink — a miss.
- **An edge listed nowhere here takes the value the rules above give.** The test table records each
  such edge as it is found; where the table and this document disagree, one of them is a defect,
  decided in the code review.
- **After the build, §3's rules change on an observed command** — a false deny in the pre-install
  replay or a transcript, a reflexive override or a route-around under count (c) — **never on a
  conceived edge.** A conceived edge becomes a §8 row with the value the rules already give it,
  and nothing else moves.
- That the guards fire inside subagent sessions is documented, not measured.

**The counts, without a bar** — they say whether any of the above needs acting on, and nothing is
gated on them. After some sessions with the guards installed, from the session transcripts under
`~/.claude/projects/<project>/` — **including the subagents'**, at
`<session>/subagents/agent-*.jsonl`, since in this repository most writes are made by subagents:

- **(a) denies**: tool results beginning `PreToolUse:Bash hook error`, read against the
  pre-install replay the brief's done-when runs, which is the rate of the same forms before a deny
  existed.
- **(b) overrides**: commands carrying `#ZIKARON-FORCE #Reason:` outside a heredoc body — or,
  more simply, the acknowledgement attachments the override path emits.
- **(c) reflexive overrides and routing around**: a deny answered in the next tool call by an
  override of the same command, by a redirected transformation or an interpreter's printed output
  redirected onto the same target (§3.2), or a script file outside scratch writing the
  same target, by a `cp`/`mv`/`install`/`rsync`, a `cat /tmp/x > f`, a `tee f < /tmp/x` or a
  `cat /tmp/x | tee f` from a scratch path onto it, or by
  an interpreter or shell fed through a pipe, a redirect, a variable or a script file — including a
  scratch script row 6 misses (above). **Read their reasons before acting on the
  rate**: a reflexive override of a false deny argues for tighter forms or a parser; of a true one,
  that the agent treats the deny as a formality, which argues about the reason rule — and reasons
  that read as boilerplate argue the same.
- **(d) the nudge**: of the paths a session edits, how many are re-read after their last edit —
  a `Read`, a Bash call whose simple command reads the path (`sed -n`, `cat`, `head`, `tail`,
  `grep -n`), or a `git diff` whose output shows its content (not `--stat` or `--name-only`) — in
  a project that installs the guards, its sessions before install against after. The re-read is
  counted wherever it falls after the last edit, since the nudge asks for it once that file's
  editing is finished and an agent editing several files in turn reviews them together at the end;
  and a diff counts, since for a replacement it shows each change beside what it replaced (both
  observed in the interactive test's arm B, `research/m37-guard-interactive-test.md`, whose
  re-read figures are this count). This repository does not install the guards (`design/build-plan.md`
  §M37 item 5). This is the one count that says the nudge changes behaviour rather than only
  arriving.

## 8. The test table's seed

**The one place the rule table's rows are listed.** The build's parametrised test holds every row
here and every edge §7 names with the value §7 gives it; a row found
during the build is added here in the same change as its test. *Deny* means a deny; *silent* means
no output; *ack* means no decision plus the override's acknowledgement. `/` separates lines of one
command (`\|`: §3). **Every row is judged under one payload**: `cwd` is a directory that is not
scratch (`/home/u/proj`), `$TMPDIR` is unset, the payload carries no `scratchpad_dir`, and **no
file exists for row 6 to read** — so a row-6 row is judged on what its own command stages, never on
whatever the machine running the test holds under `/tmp`; the one row saying a relative target
resolves under `/tmp/` is the exception to the first, and §8.1's rows, which do read files, to the
last. The probe's commands are
the rows marked *probe*, verbatim, judged under the same `cwd` — the probe itself ran in a
scratch directory, where these rules would exempt them.

| Command | Expected |
|---|---|
| *probe*: `sed -i 's/beta/BETA/' target.txt` | deny |
| *probe*: `sed -i 's/beta/BETA/' target.txt #ZIKARON-FORCE` | deny (invalid-marker message) |
| *probe*: `sed -i 's/beta/BETA/' t2.txt #ZIKARON-FORCE #Reason: probe test` | ack |
| `grep -rn "sed -i" tests/` | silent |
| `sed -i 's/a/b/' f` · `sed -Ei.bak 's/a/b/' f` · `sed --in-place=.orig 's/a/b/' f` | deny |
| `sed -i 's\|/usr\|/opt\|' /tmp/x` · `sed -i '' 's/a/b/' /tmp/x` · `sed -I '' 's/a/b/' /tmp/x` · `sed -Ei '' 's/a/b/' /tmp/x` | silent |
| `sed -i '' 's/a/b/' f` · `sed -Ei '' 's/a/b/' f` · `sed -I '' 's/a/b/' f` | deny |
| `sed -i --expression=s/a/b/ /tmp/x` | silent |
| `find . -name '*.md' -exec sed -i 's/a/b/' {} +` · `find . -name '*.md' \` / `-exec sed -i 's/a/b/' {} +` | deny |
| `for f in *.md; do sed -i 's/a/b/' "$f"; done` · `if grep -q x f; then sed -i 's/a/b/' f; fi` · `case $x in a) sed -i 's/a/b/' f;; esac` | deny |
| `LC_ALL=C sed -i 's/a/b/' f` · `timeout 60 sed -i 's/a/b/' f` · `timeout -s KILL 60 sed -i 's/a/b/' f` · `\sed -i 's/a/b/' f` · `xargs -I{} sed -i 's/a/b/' {}` · `busybox sed -i 's/a/b/' f` | deny |
| `sed -i \` / `-e 's/a/b/' \` / `-e 's/c/d/' \` / `/tmp/x` | silent |
| the same ending `f` | deny |
| `sed -i 's/a/b/' /tmp/x  # note` · `sed -i 's/a/b/' /tmp/x #ZIKARON-FORCE` | silent |
| `sed -i 's/a/b/' f # note` | deny |
| a relative target that `cwd` resolves under `/tmp/` · `echo x > "$TMPDIR"/probe` · `echo x > "${TMPDIR:-/tmp}/probe"` · `sed -i 's/a/b/' "/tmp/x y"` | silent |
| `perl -pi -e 's/a/b/' f` · `perl -0pi -e 's/a\nb/c/' f` · `ruby -pi -e 'gsub(/a/,"b")' f` | deny |
| `perl -0777pi -e 's/a/b/' /tmp/x` · `ruby -i.bak -pe 's' /tmp/x` | silent |
| `perl -Ilib -ne 'print' f` · `perl -Mstrict -ne 'print' f` | silent (no in-place flag) |
| `gawk -i inplace -v n=1 '{print}' /tmp/x` | silent |
| `gawk -i inplace '{print}' f` | deny |
| `sed 's/a/b/' f > g` · `python3 -c 'print("x")' > f` · `cat f \| sed -n 1,5p` | silent (not denied) |
| `python3 - <<'EOF'` / `Path('f').write_text('x')` / `EOF` · `.venv/bin/python -c "open('f','w').write(s)"` · `python3 -c'open("f","w").write("x")'` · `python3 -c "open(\"f\",\"w\").write('x')"` · `"$venv/python" -c "open('f','w').write(s)"` · `nodejs -e "require('fs').writeFileSync('f','x')"` · `node -e "fs.createWriteStream('f')"` | deny |
| `python3 -c "` / `from pathlib import Path` / `p = Path('CLAUDE.md')` / `p.write_text(p.read_text().replace('a', 'b'))` / `"` · `node -e "` / `require('fs').writeFileSync('f','x')` / `"` | deny |
| the same five-line `python3 -c "` with `Path('/tmp/x')` · `python3 -c '` / `print("x")` / `' > /tmp/out` | silent |
| `python3 -c "` / `#ZIKARON-FORCE #Reason: bulk fix` / `open('f','w').write('x')` / `"` | deny (marker is content) |
| the same with `" #ZIKARON-FORCE #Reason: bulk fix` as its closing line | ack |
| `echo "open('f','w').write('x')" \| python3` | deny |
| `printf '%s' "open('/tmp/x','w').write('x')" \| python3 -` | silent |
| `python3 -c "import json,tomllib; d=tomllib.load(open('pyproject.toml','rb')); open('/tmp/d.json','w').write(json.dumps(d))"` · `python3 -c "from pathlib import Path; Path('/tmp/l.txt').write_text('\n'.join(str(p) for p in Path('design').rglob('*.md')))"` · `python3 -c "Path('/tmp/x').open('w').write('y')"` · `python3 -c "print(Path('CLAUDE.md').resolve())"` | silent |
| `open(Path('/tmp/x'),'w')` · `open(os.path.join('/tmp','x'),'w')` · `Path('/tmp/x').with_suffix('.json').write_text(s)` · `Path('/tmp').joinpath('x').open('w')` · `zipfile.ZipFile('/tmp/x.zip', mode='w')` · `tempfile.NamedTemporaryFile(mode='w', delete=False)` · `open(f'/tmp/{n}.json','w')` — each inside `python3 -c "…"` | silent |
| `open(str(Path('design/x.md')),'w')` · `open(os.path.join('design','overview.md'),'w')` · `open(os.path.join(d,'x'),'w')` · `Path('design/x.md').with_suffix('.bak').write_text(s)` · `open(f'{d}/x','w')` — each inside `python3 -c "…"` | deny |
| `uv run --with x python -c "open('f','w').write('x')"` | deny |
| `python3 - <<'EOF'` / `# open('f','w')` / `print(1)` / `EOF` | silent |
| `cat > f <<'EOF'` · `printf '%s\n' x >> f` · `tee f <<'EOF'` · `tee --append f <<'EOF'` · `cat <<< 'line' > f` | deny |
| `cat <<< 'line' > /tmp/x` · `echo x \| tee >(cat) /tmp/x` · `foo $(echo x) > f` | silent |
| `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' "$1"` / `EOF` | silent |
| `gh pr create --body "$(cat <<'EOF'` / a line `sed -i 's/a/b/' f` / a line quoting `` `sed -i 's/a/b/' f` `` / `EOF` / `)"` | silent |
| `bash <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `cat <<'EOF' \| bash` (same body) · `cat <<'EOF' \| sudo bash` (same body) · `tee /tmp/fix.sh <<'EOF' \| bash` (same body) | deny |
| `bash <<'EOF'` / `sed -i \` / `'s/a/b/' /tmp/x` / `EOF` · `bash <<'EOF'` / `cat > /tmp/fix.sh <<'INNER'` / `sed -i 's/a/b/' "$1"` / `INNER` / `EOF` | silent |
| `python3 -c 'print(1)'` / `cat > /tmp/notes.md <<'EOF'` / `open('f','w')` / `EOF` · `python3 -c 'print(1)'; echo "open('f','w')" > /tmp/x` · `python3 fix.py && cat > /tmp/notes.md <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` | silent |
| `sed -i 's/a/b/' /tmp/x && echo y > f` | deny, naming the `echo` form |
| `cat > f <<'EOF'` / `#ZIKARON-FORCE #Reason: two words` / `EOF` · `echo 'x #ZIKARON-FORCE #Reason: two words' >> CLAUDE.md` · `bash <<'EOF'` / `sed -i 's/a/b/' f #ZIKARON-FORCE #Reason: a b` / `EOF` | deny (ordinary message, plus §3.5's placement clause) |
| `sed -i 's/a/b/' f #ZIKARON-FORCE #Reason: regenerate golden` · `… #Reason: 'golden file'` · `… #Reason: fix <12> now` | ack |
| `sed -i 's/a/b/' f #ZIKARON-FORCE` · `… #ZIKARON-FORCE #Reason: golden` · `… #Reason: <few words>` · `… #Reason: <x> regenerate` · `sed -i 's/a/b/' f#ZIKARON-FORCE #Reason: a b` | deny (invalid-marker message) |
| `ls #ZIKARON-FORCE #Reason: a b` | silent |
| `python3 -c '` / `open("f","w")` / `' #ZIKARON-FORCE #Reason: bulk fix` | ack |
| `python3 -c "` / `# open('f','w')` / `print(1)` / `"` | silent |
| `Path(tempfile.gettempdir()).joinpath('x').write_text(s)` · `open(os.path.join(tempfile.gettempdir(),'x'),'w')` — each inside `python3 -c "…"` | silent |
| `echo x \| tee >(cat) f` | deny |
| `echo x \| tee >(grep a) /tmp/x` · `echo x > >(cat)` · `echo x >\| f` · `echo x \| tee >(cat -n) f` · `echo x \| tee >(grep a) f` | silent (the last three stated misses) |
| `python3 -c "import gzip; gzip.open('/tmp/x.gz','wt').write(b)"` · `python3 -c "p=Path('/tmp/x'); p.open('w').write('y')"` · `python3 -c "s=Path('CLAUDE.md').open().read(); open('/tmp/x','w').write(s)"` | silent |
| `python3 -c "import codecs; codecs.open('f','w','utf-8').write(s)"` | deny, naming `f` |
| `git commit -m "x` / `sed -i 's/a/b/' f"` | silent (the second line is inside a string) |
| `/usr/bin/env python3 -c "open('f','w').write('x')"` | deny |
| `perl -e 'open(F, ">/tmp/x"); print F 1'` | silent |
| `cat <<'EOF' > /tmp/fix.sh && bash /tmp/fix.sh` / `sed -i 's/a/b/' f` / `EOF` | deny, naming `f` (row 6: the staged body is the script's text) |
| `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 /tmp/fix.py` · `tee /tmp/fix.py <<'EOF' > /dev/null` / `open('f', 'w').write('x')` / `EOF` / `python3 /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 -u /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 -X utf8 /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `timeout 60 python3 -- /tmp/fix.py x` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 -W ignore /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 -Werror /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 -Werror::DeprecationWarning:m /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w').write('x')` / `EOF` / `python3 /tmp/fix.py; python3 -c 'print(1)'` | deny, naming `f`, naming the `python3` form (a row-4 flag ends row 6 only among the run's own arguments) |
| `cat > /tmp/fix.js <<'EOF'` / `require('fs').writeFileSync('f', 'x')` / `EOF` / `node /tmp/fix.js` | deny, naming `f`, naming the `node` form |
| `cat > /tmp/fix.sh <<'EOF'` / `echo x > f` / `EOF` / `sh /tmp/fix.sh` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `bash -x /tmp/fix.sh` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `bash -o pipefail /tmp/fix.sh` | deny, naming `f` |
| `S=/tmp/w; cat > "$S/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 "$S/fix.py"` · `cd /tmp/w && cat > fix.py <<'EOF'` / `open('/home/u/proj/f', 'w')` / `EOF` / `python3 fix.py` | deny, naming `f` (the operand read through its binding, and through the `cd`) |
| `cd /tmp/w && cat > fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 fix.py` · `cat > /tmp/w/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `cd /tmp/w && python3 fix.py` | silent (the script's `f` resolves where it runs, `/tmp/w`) |
| `cat > /tmp/w/fix.py <<'EOF'` / `open('/home/u/proj/f', 'w')` / `EOF` / `cd /tmp/w && python3 fix.py` · `S=/tmp/w; cat > "$S/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 /tmp/w/fix.py` | deny, naming `f` (a staging and a run spelling one path differently meet through its resolved form) |
| `cat > $TMPDIR/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 "$TMPDIR/fix.py"` | deny, naming `f` (with `$TMPDIR` unset the two spellings meet through §3.3's resolved form) |
| `cat > /tmp/fix.py <<'EOF'` / `open('/tmp/out', 'w').write('x')` / `EOF` / `python3 /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `print(open('f').read())` / `EOF` / `python3 /tmp/fix.py` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' /tmp/x` / `EOF` / `bash /tmp/fix.sh` | silent (everything the script writes is scratch, or it writes nothing) |
| `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 /tmp/other.py` · `python3 /tmp/fix.py; cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 -m fix /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 - /tmp/fix.py` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `bash -c 'echo' /tmp/fix.sh` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `bash -s < /tmp/fix.sh` | silent (no staged text for the path the run names, staged after the run, or no script operand) |
| `cat > fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 fix.py` | deny, naming `fix.py` (row 5 on the staging; `fix.py` is no scratch operand, so row 6 does not match) |
| `cat > /tmp/fix.sh <<'EOF'` / `cat > /tmp/inner.py <<'PY'` / `open('f', 'w')` / `PY` / `python3 /tmp/inner.py` / `EOF` / `bash /tmp/fix.sh` | deny, naming `f` (a script's own text stages for a run inside it) |
| `S=/tmp/w; cat > /tmp/fix.py <<'EOF'` / `open('$S/x', 'w')` / `EOF` / `python3 /tmp/fix.py` | deny, naming `$S/x` (the script's process inherits no unexported variable, so `$S` is no binding there) |
| `S=/tmp/w; cat > /tmp/fix.sh <<'EOF'` / `echo y > "$S/a"` / `EOF` / `bash /tmp/fix.sh` | deny, naming `$S/a` |
| `cat <<'EOF' \| tee /tmp/fix.py` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py` | deny, naming `f`, naming the `python3` form (a `tee` fed by a heredoc earlier in its pipeline stages it) |
| `cat <<'EOF' \| sudo tee /tmp/fix.sh > /dev/null` / `sed -i 's/a/b/' f` / `EOF` / `bash /tmp/fix.sh` | deny, naming `f` |
| `bash <(echo 'sed -i s/a/b/ f')` | silent (a process substitution is no script operand, §3.1) |
| `cat > /tmp/fix.py <<'EOF' #ZIKARON-FORCE #Reason: bulk mechanical rename` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py` | ack |
| `cat > /tmp/fix.py <<'EOF'` / `# #ZIKARON-FORCE #Reason: bulk mechanical rename` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py` | deny (placement clause: the marker is in the staged body, not the command's comment) |
| `python3 tool.py <<'EOF'` / `open('f','w')` / `EOF` | deny (stated over-match) |
| `f() { sed -i 's/a/b/' "$1"; }` | deny |
| `sed -i'' 's/a/b/' /tmp/x` | silent |
| `sed -i'' 's/a/b/' f` | deny |
| `cat <<'EOF' \| python3 -` / `open('f','w').write('x')` / `EOF` · `tee /tmp/fix.py <<'EOF' \| python3 -` (same body) · `cat <<'EOF' \| python3 -c "import sys; exec(sys.stdin.read())"` / `Path('f').write_text('x')` / `EOF` | deny |
| `cat <<'EOF' \| python3 -` / `open('/tmp/x','w').write('x')` / `EOF` | silent |
| `open(os.path.join(os.path.dirname(__file__),'x'),'w')` inside `python3 -c "…"` | deny, naming no literal |
| `echo x > /private/tmp/x` · `sed -i 's/a/b/' /private/var/tmp/x` | silent |
| `python3 -c "` / `s = '# x'; open('f','w').write(s)` / `"` | deny |
| `for f in /tmp/*.md; do sed -i 's/a/b/' "$f"; done` | deny (stated false deny on scratch) |
| `python3 -c "import tempfile,os; d=tempfile.mkdtemp(); open(os.path.join(d,'x'),'w').write('y')"` · `python3 -c "out = '/tmp/x'; open(out, 'w').write(s)"` · `python3 -c "out = '/tmp/x'; Path(out).write_text(s)"` · `python3 -c "s = 'hello'; open('/tmp/x','w').write(s)"` · `python3 - <<'EOF'` / `OUT = '/tmp/out.json'` / `with open(OUT, 'w') as fh: fh.write(s)` / `EOF` | silent |
| `python3 -c "out = 'CLAUDE.md'; open(out, 'w').write(s)"` | deny, naming `CLAUDE.md` |
| `python3 -c "$(cat <<'EOF'` / `print("it's")` / `EOF` / `)" && echo y > f` · `bash <<'EOF'` / `echo "a` / `EOF` / `echo y > f` | deny, naming `f` |
| `python3 -c "$(cat <<'EOF'` / `print("it's")` / `open('f','w')` / `EOF` / `)" #ZIKARON-FORCE #Reason: bulk fix` · `echo "a` / `b" > f #ZIKARON-FORCE #Reason: x y` · `sed -i 's/a/b/' f \` / `#ZIKARON-FORCE #Reason: a b` | ack |
| `echo "a #ZIKARON-FORCE #Reason: x y` / `b" > f` | deny (ordinary message plus §3.5's placement clause: the marker is inside the string) |
| `sed -i 's/a/b/' /tmp/x # it's "fine` · `python3 -c "print(open('x').read())"` · `python3 -c "import dbm; dbm.open('cache')"` · `./check.sh 2>&1 \| tee check.log` | silent |
| `python3 -c "open('x','w')"` · `python3 - <<< "` / `open('f','w')` / `"` · `sed -i 's/a/b/' /tmp/x # note \` / `echo y > f` · `echo "a \|\|"` / `sed -i 's/a/b/' f` | deny |
| `python3 -c "Path('CLAUDE.md').open('w').write('x')"` · `python3 -c "p = Path('CLAUDE.md'); p.open('w').write('x')"` · `python3 -c "import gzip; gzip.open('x.gz','wt')"` · `bash -c "$(cat <<"EOF"` / `sed -i 's/a/b/' f` / `EOF` / `)"` · `python3 -c "p = Path('design') / 'x.md'; p.write_text(s)"` · `python3 -c "path = 'CLAUDE.md'; open(path,'w').write('x')"` · `cat <<'EOF' \| # pipe` / `bash` / `sed -i 's/a/b/' f` / `EOF` · `bash <<'EOF'` / `python3 -c "` / `open('f','w')` / `"` / `EOF` · `python3 - <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `x=$(` / `sed -i 's/a/b/' f` / `)` · `echo x \` / `> f` | deny |
| `python3 -c "import shelve; shelve.open('data', flag='r')"` | silent (no write pattern) |
| `cat <<'EOF' \| bash #ZIKARON-FORCE #Reason: bulk fix` / `sed -i 's/a/b/' f` / `EOF` | ack |
| `python3 -c "import io; io.open('x')"` · `python3 -c "Path('/tmp/x').open(mode='w')"` · `echo "x <<'EOF' y" > /tmp/x` · `python3 -c "p = Path('design') / 'x.md'; s = p.read_text(); open('/tmp/x','w').write(s)"` · `python3 -c "p = Path('/tmp') / 'x'; p.write_text(s)"` · `python3 -c "path = 'CLAUDE.md'; open(os.path.join('/tmp','x'),'w').write(path)"` · `python3 -c "import subprocess; subprocess.Popen(['tar','x','f.tar'])"` · `bash <<'EOF'` / `echo "a` / `sed -i 's/a/b/' f` / `b"` / `EOF` · `python3 -c "OUT: str = '/tmp/x'; open(OUT,'w')"` · `python3 -c "open('/tmp/x','w',encoding='utf-8')"` · `python3 -c "mode = 'w'; open('CLAUDE.md', mode)"` | silent (the last a stated miss) |
| `echo "sed -i 's/a/b/' f" \| bash` · `printf '%s\n' "sed -i 's/a/b/' f" \| sh` · `echo "$(` / `sed -i 's/a/b/' f` / `)" > /tmp/x` | silent (stated misses) |
| ``node -e 'fs.writeFileSync(`/tmp/${n}.json`, s)'`` | silent |
| ``node -e 'fs.writeFileSync(`${d}/x`, s)'`` | deny |
| `S='open("f","w").write("x")'` / `python3 -c "$S"` · `python3 -c "$(cat fix.py)"` · `python3 -c "exec(open('fix.py').read())"` · `python3 -c "import subprocess; subprocess.run(\"sed -i 's/a/b/' f\", shell=True)"` · `fish <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `! sed -i 's/a/b/' f` · `echo x >& f` | silent (stated misses) |
| `python3 -c "p = Path('CLAUDE.md'); q = p; q.write_text('x')"` | deny, naming `CLAUDE.md` (an alias takes its target) |
| `python3 -c "p = Path('/tmp/x'); q = p; q.write_text('x')"` | silent (an alias of a scratch-bound name is scratch) |
| `echo x \| tee >> f` · `echo x \| tee > f` | deny, naming `f` |
| `echo x \| tee >> /tmp/x` · `cat <<'EOF' \| python3 - > f` / `print(1)` / `EOF` · `cat <<'EOF' \| sed 's/a/b/' > f` / `x` / `EOF` · `python3 - <<'EOF' > f` / `print(1)` / `EOF` | silent |
| `cat <<'EOF' > f` / `x` / `EOF` | deny |
| `python3 -c "from pathlib import Path; p = Path('CLAUDE.md'); s = p.read_text(); Path('/tmp/x').write_text(s)"` · `python3 -c "(Path('/tmp') / 'x').write_text(s)"` · `python3 -c "p = Path('/tmp'); (p / 'x').write_text(s)"` · `python3 - <<< "open('/tmp/x','w').write('x')"` · `sed -l 80 -i 's/a/b/' /tmp/x` | silent |
| `python3 -c "(Path('design') / 'x.md').write_text(s)"` · `python3 - <<< "open('f','w').write('x')"` · `python3 -c "open('f', 'w').write('x')"` | deny |
| `#ZIKARON-FORCE #Reason: bulk fix` / `sed -i 's/a/b/' f` | ack |
| `echo x > "$(mktemp)"` · `echo x > $(mktemp)` | deny (stated false deny on scratch) |
| `python3 -c "p = Path('CLAUDE.md'); Path('/tmp/x').write_text(p.read_text())"` · `python3 -c "p = Path('CLAUDE.md'); open('/tmp/x','w').write(p.read_text())"` · `python3 -c "f = Path('CLAUDE.md'); s = f.read_text(); open('/tmp/f.txt','w').write(s)"` · `open(str(Path('/tmp/x')),'w')` inside `python3 -c "…"` · `node -e "fs.open('/tmp/x','w',cb)"` · `tee /tmp/x << EOF` / `x` / `EOF` · `echo x > /tmp/$(whoami)/x` | silent |
| `python3 -c "p = Path('CLAUDE.md'); p.write_text('x')"` · `python3 -c "p = Path('CLAUDE.md'); with open(p,'w') as fh: fh.write('x')"` · `node -e "fs.open('f','w',cb)"` · `tee f << EOF` / `x` / `EOF` · `cat << EOF > f` / `x` / `EOF` | deny, naming the authored target |
| `python3 -c "p = Path('CLAUDE.md'); json.dump(p.read_text(), open('/tmp/x','w'))"` | silent (only the write's first argument is judged) |
| `grep -rl a . \| xargs sed -i 's/a/b/'` · `find . -name '*.md' -exec sed -i 's/a/b/' {} \;` · `bash -c "$(cat <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `)"` · `bash <<'EOF'` / `python3 - <<'INNER'` / `open('f','w')` / `INNER` / `EOF` · `sed -i 's/a/b/' /tmp/a f` · `echo x \| tee /tmp/x f` · `echo "$(sed 's/a/b/' f)" > f` · `tee f <<< x` · `echo x >f` · `sed -i 's/a/b/' f #zikaron-force #Reason: a b` | deny |
| `sudo --user root sed -i 's/a/b/' f` · `env -u X sed -i 's/a/b/' f` | deny |
| `x=$(cat <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `)` · `python3 -c "import os, tempfile; OUT = os.path.join(tempfile.gettempdir(), 'r.json'); open(OUT, 'w').write(s)"` · `python3 -c "import tempfile; d = tempfile.gettempdir(); OUT = d + '/x'; open(OUT,'w').write(s)"` · `python3 -c "import tempfile; OUT = f'{tempfile.gettempdir()}/x'; open(OUT,'w').write(s)"` · `python3 -c "S = Path('/tmp/s'); OUT = S / 'x'; OUT.write_text(s)"` · `git show HEAD:design/x.md > /tmp/x.md` · `git show HEAD:design/x.md > design/x.md` · `python3 -c "open(file='/tmp/x', mode='w')"` · `python3 -c "Path('f').touch()"` | silent (the `git show … > design/x.md` a stated miss) |
| `python3 -c "OUT = os.path.join('research', 'x.md'); open(OUT,'w').write(s)"` · `python3 -c "R = Path('research'); OUT = R / 'x.md'; OUT.write_text(s)"` · `if sed -i 's/a/b/' f; then echo ok; fi` · `python3 -c "import re; s = open('CLAUDE.md').read(); open('CLAUDE.md','w').write(re.sub('a','b',s))"` · `sed -ie 's/a/b/' f` · `cat >> f <<'EOF'` / `x` / `EOF` · `python3.14t -c "open('f','w')"` | deny, naming the authored target |
| `python3 tool.py -c "open('f','w')"` | deny (stated over-match) |
| `python3 -c "print(open('README.md').read().count('>'))"` · `python3 -c "open('/tmp/x','w').write('> quote')"` · `ruby -e 'File.open("/tmp/x","w") { \|f\| f.puts ">" }'` · `bash <<'EOF'` / `echo x > /tmp/x` / `EOF` · `ruby -e 'File.open("app.rb").read'` · `ruby -e 'File.new("/tmp/archive.zip")'` · `python3 -c "src = '/tmp/in.md'; d = tempfile.mkdtemp(); OUT = os.path.join(d, 'x'); open(OUT,'w')"` · `python3 -c "d = '/tmp'; OUT = Path(d) / 'x'; OUT.write_text(s)"` · `python3 -c "d = tempfile.mkdtemp(); OUT = d / 'x'; OUT.write_text(s)"` · `python3 -c "from tempfile import mkdtemp; d = mkdtemp(); open(os.path.join(d,'x'),'w')"` · `python3 -c "out = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'x'); open(out,'w')"` · `python3 -c "out = os.path.join(os.getenv('TMPDIR'), 'x'); open(out,'w')"` · `echo x \|& tee /tmp/x` | silent |
| `python3 -c "open('f','w').write('> quote')"` · `bash <<'EOF'` / `echo x > f` / `EOF` · `bash <<'EOF'` / `cat > f <<'INNER'` / `x` / `INNER` / `EOF` · `bash <<'EOF'` / `echo x \| tee f` / `EOF` · `echo \"x\" > f` · `echo x \|& tee f` · `xargs --max-args 1 sed -i 's/a/b/'` | deny |
| `python3 -c "src = Path('/tmp/in.md'); dst = Path('research') / src.name; dst.write_text(src.read_text())"` · `python3 -c "src = Path('/tmp/in.md'); open(Path('research') / src.name, 'w')"` · `python3 -c "src = '/tmp/in.md'; open('research/' + os.path.basename(src), 'w')"` | deny, naming `research` (the literal leads) |
| `x=$((1<<3))` / `sed -i 's/a/b/' f` | silent (stated miss) |
| `python3 -c "(Path('/tmp') / 'x').with_suffix('.json').write_text(s)"` · `python3 -c "d = '/tmp'; Path(d).open('w')"` | silent |
| `python3 -c "(Path('design') / 'x.md').with_suffix('.json').write_text(s)"` | deny, naming `design/x.md` |
| `python3 -c "d = 'research'; Path(d).open('w')"` | deny, naming `research` |
| `python3 -c "src = Path('/tmp/in.md'); out = src.with_suffix('.json'); out.write_text(s)"` · `python3 -c "p = Path('/tmp/x'); out = p.parent / 'y'; out.write_text(s)"` · `python3 -c "d = Path(tempfile.mkdtemp()); d.joinpath('x').write_text(s)"` · `python3 -c "p = Path('CLAUDE.md'); p.parent.open('w')"` · `python3 -c "import pandas as pd; df.to_csv('out.csv', mode='a')"` · `python3 -c "import logging; logging.FileHandler('run.log', mode='a')"` · `python3 -c "zipfile.ZipFile(p, mode='w')"` · `python3 -c "dict(mode='w')"` | silent (the last five stated misses) |
| `python3 -c "src = Path('research/in.md'); out = src.with_suffix('.json'); out.write_text(s)"` · `python3 -c "p = Path('CLAUDE.md'); p.parent.write_text('x')"` | deny, naming the authored target |
| `python3 -c "paths = [Path('/tmp/a')]; paths[0].write_text('x')"` · `python3 -c "import fileinput; [print(l, end='') for l in fileinput.input(files='f', inplace=True)]"` | deny, naming no literal (stated) |
| `python3 -c "d = tempfile.mkdtemp(); open('/'.join([d, 'x']), 'w')"` | deny, naming `/` (stated false deny on scratch) |
| `perl -E 'open(F,">","f"); print F "x"'` · `perl -ne 'BEGIN{open(F,">","f")} print F' in` · `perl -e 'open(my $fh, ">", "f") or die; print $fh 1'` · `perl -e 'open F, ">f"; print F 1'` · `perl -e 'my $f = "research/x"; open(my $fh, ">", $f)'` · `ruby -e 'IO.write("f", s)'` · `ruby -e 'File.open("app.rb", "w")'` · `ruby -e 'File.new("f","w").write("x")'` · `python3 -c "import shelve; shelve.open('data')"` · `python3 -c "import dbm; dbm.open('cache','c')"` · `python3 -c "zipfile.ZipFile('f', 'w')"` · `$(brew --prefix gnu-sed)/libexec/gnubin/sed -i 's/a/b/' f` | silent (stated misses: inline perl/ruby writes, archive and database writers, the Homebrew sed path — cut in favour of a smaller rule set, §7) |
| `python3 -c "d = 'research'; OUT = os.path.join(d, 'x'); open(OUT,'w')"` · `perl -pie 's/a/b/' f` · `cat <<'EOF' \| sed 's/a/b/' \| tee f` / `x` / `EOF` | deny, naming the authored target |
| `python3 -c "p = Path('CLAUDE.md'); x = p.read_text(); open(x + '.bak','w')"` · `python3 -c "for p in [Path('design/a.md'), Path('design/b.md')]: p.write_text(s)"` · `python3 -c "a, b = '/tmp/a', '/tmp/b'; open(a,'w')"` | deny, naming no literal (the last a stated false deny on scratch) |
| `python3 -c "d = 'research'; OUT = '/tmp/' + d; open(OUT,'w')"` · `python3 -c "open('/tmp/x','w').write((Path('design') / 'x.md').read_text())"` · `python3 -c "Path('/tmp/l.txt').write_text('\n'.join(str(q) for d in [Path('design'), Path('docs')] for q in d.rglob('*.md')))"` · `python3 -c "Path('/tmp/x').write_text((Path('design') / 'x.md').read_text())"` · `python3 -c "with (tempfile.TemporaryDirectory() as d): open(f'{d}/x','w')"` · `python3 - <<'EOF'` / `with (` / `    tempfile.TemporaryDirectory() as d,` / `    open(os.path.join(d, 'x'), 'w') as fh,` / `):` / `    fh.write(s)` / `EOF` · `python3 -c "s = 'a;b'; open('/tmp/x','w').write(s)"` · `echo $'it\'s' > f` · `vim -es -c '%s/a/b/g' -c wq f` · `ipython -c "open('f','w')"` | silent (the last three stated misses) |
| `python3 - <<'EOF' \| tee out.txt` / `print(1)` / `EOF` · `bash <<'EOF' \| tee check.log` / `./check.sh` / `EOF` · `cat <<'EOF' \| python3 - \| tee f` / `print(1)` / `EOF` · `python3 - <<'EOF' \| tee /tmp/out.txt` / `print(1)` / `EOF` · `` node -e 'fs.writeFileSync(`${os.tmpdir()}/x.json`, s)' `` · `node -e 'const d = os.tmpdir(); fs.writeFileSync(d + "/x", s)'` · `` node -e 'fs.writeFileSync(`${require("os").tmpdir()}/x`, s)' `` · `node -e 'const out = "/tmp/x"; fs.writeFileSync(out, s)'` · `node -e 'fs.writeFileSync(process.env.TMPDIR + "/x", s)'` · `perl -e 'my $f = "/tmp/x"; open(my $fh, ">", $f)'` · `python3 -c "with tempfile.TemporaryDirectory() as d: open(f'{d}/x','w')"` · `python3 -c "with tempfile.TemporaryDirectory() as d: open(os.path.join(d,'x'),'w')"` · `python3 - <<'EOF'` / `with tempfile.TemporaryDirectory() as d:` / `    open(os.path.join(d, 'x'), 'w').write(s)` / `EOF` · `python3 -c "with open('CLAUDE.md') as src, open('/tmp/x','w') as dst: dst.write(src.read())"` · `python3 -c "with tempfile.NamedTemporaryFile('w', delete=False) as fh: fh.write('x')"` · `echo x >\|f` · `python3 -c "import wave; wave.open('/tmp/x.wav','wb')"` | silent (`>\|f` a stated miss) |
| `cat <<'EOF' \| sort \| tee f` / `x` / `EOF` · `node -e 'const out = "research/x"; fs.writeFileSync(out, s)'` · `python3 -c "ROOT = 'research'; OUT = os.path.join(ROOT, 'x'); open(OUT,'w')"` · `python3 -c "d = 'research'; open(f'{d}/x','w')"` · `python3 -c "import wave; wave.open('x.wav','wb')"` | deny, naming the authored target |
| `` node -e 'fs.writeFileSync(`${d}/x`, s)' `` · `node -e 'const d = "research"; fs.writeFileSync(d + "/x", s)'` · `python3 - <<'EOF'` / `"""` / `open('f','w')` / `"""` / `print(1)` / `EOF` · `python3 -c "def save(p): open(p,'w').write(s)` / `save('/tmp/x')"` · `python3 -c "for p in ['/tmp/a','/tmp/b']: open(p,'w')"` | deny (stated; the triple-quoted row names `f`, the `` `${d}/x` `` row names `${d}/x` — a relative literal — the `const d = "research"` row names `research`, and the others name no literal) |
| `node -e "window.open('about:blank')"` · `cat <<< x \| sort \| tee /tmp/x` | silent (the receiver pattern does not reach `'about:blank'`) |
| `cat <<< x \| sort \| tee f` | deny, naming `f` |
| `python3 -c "import pandas as pd; df = pd.read_csv('data/x.csv'); df.dropna(inplace=True); print(df.describe())"` · `python3 -c "import pandas as pd; df = pd.read_csv('data/x.csv'); df.sort_values('a', inplace=True); print(df)"` · `python3 -c "from fileinput import FileInput; [print(l, end='') for l in FileInput('/tmp/x', inplace=True)]"` · `python3 -c "import numpy as np; print(np.pad(np.arange(4), 1, mode='wrap'))"` · `python3 -c "from scipy import ndimage; out = ndimage.gaussian_filter(img, 2, mode='wrap')"` · `python3 -c "import logging; logging.FileHandler('/tmp/x.log', mode='w')"` · `python3 -c "OUT = str(Path('/tmp') / 'x'); open(OUT,'w')"` · `python3 -c "open(str(Path('/tmp') / 'x'),'w')"` · `python3 -c "open(os.path.abspath('/tmp/x'),'w')"` · `python3 -c "OUT = Path('/tmp/in.md').with_suffix('.json'); OUT.write_text(s)"` · `python3 -c "from tempfile import NamedTemporaryFile; NamedTemporaryFile(mode='w', delete=False)"` · `python3 -c "from tempfile import TemporaryFile; TemporaryFile(mode='w+')"` · `python3 -c "import zipfile; zipfile.ZipFile('a')"` | silent |
| `python3 -c "import fileinput; [print(l.replace('a','b'), end='') for l in fileinput.input('f', inplace=True)]"` · `python3 -c "import tarfile; tarfile.open('x.tar.gz', mode='w:gz')"` · `python3 -c "import tarfile; tarfile.open('x.tar.gz', 'w:gz')"` · `python3 -c "OUT = str(Path('design') / 'x'); open(OUT,'w')"` · `python3 -c "open(os.path.expanduser('~/.zikaron/x'),'w')"` · `python3 -c "OUT = Path('research/in.md').with_suffix('.json'); OUT.write_text(s)"` · `python3 -c "name = Path('/tmp/in.md').name; Path('research', name).write_text(s)"` · `python3 -c "d = tempfile.mkdtemp(); open(f'research/{d}', 'w')"` · `python3 -c "name = Path('/tmp/in.md').stem; open(f'research/{name}.md', 'w')"` | deny, naming the authored target |
| `python3 -c "s = Path('CLAUDE.md').open().read(); open(s + '.bak', 'w')"` · `python3 -c "stem = Path('/tmp/report.md').stem; open(stem + '.html', 'w')"` · `python3 -c "print(repr(\"open('f','w')\"))"` | deny, naming no literal |
| `python3 -c "from tempfile import mkdtemp; d = mkdtemp(); open(f'{d}/x','w')"` | silent (a leading `{…}` holding a scratch-bound name) |
| `python3 -c "d = '/tmp'; OUT = d + '/x'; open(OUT,'w').write(s)"` · `python3 -c "d = Path('/tmp'); OUT = d / 'x'; OUT.write_text(s)"` | silent (a name already bound to a scratch target) |
| `python3 -c "d = 'research'; OUT = d + '/x'; open(OUT,'w').write(s)"` | deny, naming `research` (a name bound to an authored path heads the expression) |
| `.venv/bin/python -c "import os;from pathlib import Path;from zikaron.service import paths as p;rd=p.runtime_dir(xdg_runtime_dir=None,uid=501);print(len(os.fsencode(p.socket_path(rd,Path('/x'),platform='darwin'))), p.sun_path_size('darwin'))"` | silent — `FINDINGS.md`'s own re-derive command |
| `sed -i 's/a/b/' /tmp/x 2> err.log` · `sed -i 's/a/b/' /tmp/x 2>err.log` · `echo x \| tee /tmp/x 2> err.log` · `sed -i -e's/a/b/' /tmp/x` · `echo x \| grep x \| tee /tmp/x` · `python -m zikaron.install --project . --harness claude-code --components guards` · `.venv/bin/pip install -e . --no-deps` | silent |
| `sed -i 's/a/b/' f 2> /dev/null` · `sed -i -e's/a/b/' f` · `echo x \| grep x \| tee f` · `python3 -c "open('f','rb+').write(b)"` | deny, naming `f` |
| `python3 - <<'EOF'` / `x = 1 << 20` / `open('f','w').write(str(x))` / `EOF` · `python3 -c "` / `x = 1 << 20` / `open('f','w').write(str(x))` / `"` · `ssh host <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `$PYTHON -c "open('f','w').write('x')"` | silent (stated misses) |
| `python3 -c "from pathlib import Path as P; P('f').write_text('x')"` | deny, naming no literal (the write is seen; nothing contributes) |
| `python3 -c "open(sys.argv[1],'w').write('x')" /tmp/x` | deny, naming no literal (stated false deny on scratch) |
| `sed -i 's/a/b/' f #ZIKARON-FORCE #reason: a b` | deny (invalid-marker message: `#Reason:` is case-sensitive) |
| `cat <<'EOF' \` / `\| bash` / `sed -i 's/a/b/' f` / `EOF` · `cat <<'EOF' \|` / `bash` / `sed -i 's/a/b/' f` / `EOF` · `cat <<'EOF' \|` / `tee f` / `x` / `EOF` | deny (the opener's line continues) |
| `echo "a` / `b" > f` · `printf '%s\n' "a` / `b" > f` · `sed -i "s/a/` / `b/" f` · `echo "$(cat <<'EOF'` / `x` / `EOF` / `)" > f` · `python3 -c '` / `print('\''x'\'')` / `open("f","w")` / `'` | deny |
| `echo "a` / `b" > /tmp/x` · `sed -i "s/a/` / `b/" /tmp/x` · `echo x > /tmp/x # don't` | silent |
| `python3 -c "open('/tmp/' + n, 'w').write(s)"` · `python3 -c "open('/tmp/%s.json' % n, 'w')"` · `node -e "fs.writeFileSync('/tmp/' + n, s)"` · `python3 -c "Path('/tmp', 'x').write_text(s)"` · `node -e "fs.writeFileSync(require('os').tmpdir() + '/x', s)"` | silent |
| `python3 -c "open('{}/x'.format(d), 'w')"` · `python3 -c "p = pathlib.Path('CLAUDE.md'); p.write_text('x')"` · `python3 -c "Path('design', 'x.md').write_text(s)"` · `x=$(python3 -c "open('f','w').write('x')")` | deny, naming the authored target |
| `python3 -c "open(d + '/x', 'w')"` | deny, naming no literal |
| `bash <<'EOF'` / `python3 -c "open('f','w').write('x')"` / `EOF` | deny |
| `cat > f <<'EOF' #ZIKARON-FORCE #Reason: bulk fix` / `x` / `EOF` · `cat > f <<'EOF'` / `x` / `EOF` / `#ZIKARON-FORCE #Reason: bulk fix` | ack |
| `sed -i -f s.sed f` · `echo x > /tmp/../etc/x` · `echo x \| sudo tee -a /etc/hosts > /dev/null` | deny |
| `sed -i -f s.sed /tmp/x` · `echo x > /dev/null` | silent |
| `python3 fix.py && cat > /tmp/notes.md <<'EOF'` / `open('f','w')` / `EOF` | silent |
| `python3 - <<'EOF' && echo done` / `open('f','w')` / `EOF` · `python3 -uc "open('f','w').write('x')"` · `python3 -c "$(cat <<'EOF'` / `open('f','w').write('x')` / `EOF` / `)"` · `/bin/bash <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` | deny |
| `echo $(date) > f` · `echo "$(date)" > f` · `echo x \| tee /tmp/x > f` · `cat <<'EOF' \| tee f` / `x` / `EOF` | deny |
| `echo $(date) > /tmp/x` · `cat <<'EOF' \| tee /tmp/x` / `x` / `EOF` · `sed -i 's/a/b/' /tmp/x &> /tmp/log` · `echo x \| tee /tmp/x >&2` · `sed -i 's/a/b/' /tmp/*.md` · `./check.sh 2>&1 \| tee /tmp/check.log` · `python3 -c "import tarfile; tarfile.open('/tmp/x.tar','w')"` | silent |
| `sed -i 's/a/b/' f #ZIKARON-FORCE` / `#Reason: bulk fix` | deny (invalid marker: the reason must be on the marker's line) |
| `python3 -c "for p in Path('/tmp').glob('*.md'): p.write_text('x')"` | deny (stated false deny on scratch) |
| `.venv/bin/ruff format .` · `.venv/bin/ruff check --fix .` · `python -c "from zikaron.install.assets import *; print(skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION))" > .kiro/skills/zikaron-consolidate/SKILL.md` | silent — the gate's formatter and the prescribed golden re-render stay override-free on purpose |
| `bash -c 'sed -i s/a/b/ f'` · `sh -c 'sed -i s/a/b/ f'` · `{ echo a; echo b; } > f` · `(echo a; echo b) > f` · `echo x \| cat > f` · `echo x &> f` · `echo x 1> f` · `eval "sed -i 's/a/b/' f"` · `node --eval "require('fs').writeFileSync('f','x')"` · `node -p "require('fs').writeFileSync('f','x')"` · `ex -sc '%s/a/b/g' -cx f` · `printf '%s\n' ',s/a/b/g' w q \| ed -s f` · `vi -es -c '%s/a/b/g' -c wq f` · `nvim --headless -c '%s/a/b/g' -c wq f` · `parallel sed -i 's/a/b/' ::: f` · `x="$(sed -i 's/a/b/' f)"` · ``x=`sed -i 's/a/b/' f` `` · `su -c "sed -i 's/a/b/' f"` · `doas sed -i 's/a/b/' f` · `docker run -v "$PWD":/w img sed -i 's/a/b/' /w/f` · `kubectl exec pod -- sed -i 's/a/b/' f` · `: > f` · `> f` | silent (stated misses, §7) |
| `bun -e "require('fs').writeFileSync('f','x')"` · `deno eval "Deno.writeTextFileSync('f','x')"` · `php -r "file_put_contents('f','x');"` · `Rscript -e "writeLines('x','f')"` · `lua -e "io.open('f','w')"` · `npx tsx -e "require('fs').writeFileSync('f','x')"` · `ts-node -e "require('fs').writeFileSync('f','x')"` · `tee f < /tmp/x` · `cat /tmp/x \| tee f` · `uvx python -c "open('f','w')"` · `cat fix.py \| python3` · `python3 < fix.py` · `python3 - < fix.py` · `python3 -c "import os; os.system('sed -i s/a/b/ f')"` · `"$PYTHON" -c "open('f','w')"` · `python3 -c "open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'x'),'w')"` · `source f` · `. f` · `node -e "fs.openSync('f','w')"` · `node -e "fs.writeSync(fd, 'x')"` · `echo x \| tee` | silent (stated misses, §7) |
| `flock /tmp/l sed -i 's/a/b/' f` · `setsid sed -i 's/a/b/' f` · `stdbuf -oL sed -i 's/a/b/' f` · `ionice -c 3 sed -i 's/a/b/' f` · `chroot /root sed -i 's/a/b/' f` · `unshare sed -i 's/a/b/' f` · `nsenter sed -i 's/a/b/' f` · `strace -f sed -i 's/a/b/' f` · `caffeinate sed -i 's/a/b/' f` · `script -q /dev/null sed -i 's/a/b/' f` · `conda run -n env sed -i 's/a/b/' f` · `mamba run sed -i 's/a/b/' f` · `hatch run sed -i 's/a/b/' f` · `pipx run sed -i 's/a/b/' f` · `uv run --with-requirements r.txt sed -i 's/a/b/' f` · `uv run --with-editable . sed -i 's/a/b/' f` · `uv run --project . sed -i 's/a/b/' f` · `uv run --directory d sed -i 's/a/b/' f` · `uv run --group dev sed -i 's/a/b/' f` · `xargs -a /tmp/list sed -i 's/a/b/'` · `fd -x sed -i 's/a/b/'` · `fd -X sed -i 's/a/b/'` · `fd --exec sed -i 's/a/b/'` · `fd --exec-batch sed -i 's/a/b/'` | silent (stated misses, §7: no wrapper, or an argument-taking flag not listed) |
| `cat <<'EOF' \| grep x > f` / `x` / `EOF` · `> f cat <<'EOF'` / `x` / `EOF` · `ssh host 'bash -s' <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `ssh host bash <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `sudo -s <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `docker exec -i c bash <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `perl <<'EOF'` / `open(F, ">f"); print F 1;` / `EOF` · `ash <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `csh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `tcsh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` · `cat <<EOF > /tmp/x` / `$(sed -i 's/a/b/' f)` / `EOF` · `echo x > /tmp/x # see <<EOF` / `sed -i 's/a/b/' f` | silent (stated misses, §7; the last parsed as stated: the comment's `<<` opens a body that swallows the line after it) |
| `find /tmp/x -exec sed -i 's/a/b/' {} +` · `t=$(mktemp); sed -i 's/a/b/' "$t"` · `t=$(mktemp); echo x > "$t"` · `ls /tmp/*.md \| xargs sed -i 's/a/b/'` · `perl -pi -e 's/a/b/' $(ls /tmp/*.md)` · `sed -i .bak 's/a/b/' /tmp/x` · `sed -i s/a\;b/c/ /tmp/x` · `S=/tmp/x echo y > "$S/a"` · `S=/tmp/x; bash <<'EOF'` / `echo y > "$S/a"` / `EOF` · `python3 -c "open('%s/x' % d,'w')"` · `python3 -c "out = make_path(d); open(out,'w')"` | deny (stated false denies on scratch, §7) |
| `cd dir && sed -i 's/a/b/' f` | deny, naming `dir/f` (a `cd` in the same command is followed) |
| `sed -i 's/a/b/' /tmp/my\ file` | deny (stated, §7: an escaped space splits a token) |
| `cd /tmp/x && sed -i 's/a/b/' f` · `S=/tmp/s; cd $S && cat > p.py <<'EOF'` / `x` / `EOF` · `cd "/tmp/a b"; echo y > f` · `cd /tmp; cd x && echo y > f` | silent (a `cd` in the same command is followed) |
| `cd /home/u/.claude/jobs/j/tmp && cat > stub.py <<'EOF'` / `x` / `EOF` · `printf 'x\n' > /home/u/.claude/jobs/j/tmp/rows.txt` | deny (stated false denies on scratch, §7: a job's tmp directory is no scratch root) |
| `(cd /tmp && ls); echo y > f` · `cd /tmp && (echo y > f)` · `cd && echo y > f` · `cd - && echo y > f` · `cd ~/x && echo y > f` | deny, naming `f` (a `cd` the rules do not follow; the second a stated false deny) |
| `echo x > ~/f` | deny, naming `~/f` (parsed as stated: `~` is not expanded) |
| `echo x > $HOME/f` | deny, naming `$HOME/f` (parsed as stated: `$HOME` is not expanded) |
| `cat <<A <<B > f` / `a` / `A` / `b` / `B` | deny, naming `f` (two openers on one line take their bodies in turn) |
| `python3 -c "d = '/tmp'; open(d[0], 'w')"` | silent (a subscript in the chain reads nothing, so the head's target stands) |
| `python3 -c "d = '/tmp'; open(d[0].stem, 'w')"` | deny, naming no literal (the chain contains `.stem`, after a subscript) |
| `sleep 1 & sed -i 's/a/b/' f` · `true \|\| sed -i 's/a/b/' f` | deny, naming `f` (`&` and `\|\|` end a simple command, §3.1) |
| `sed -i --expression s/a/b/ f` | deny, naming `f` (`--expression` takes the next word, the script) |
| `S=/tmp/x; echo y > "$S/a"` · `SP=/tmp/s && cat > $SP/p.py <<'EOF'` / `x` / `EOF` · `D=/tmp/d; sed -i 's/a/b/' "${D}/f"` · `S='/tmp/a b'; echo y > "$S"` · `S=/tmp/x; python3 -c "open('$S/f','w')"` · `bash <<'EOF'` / `S=/tmp/x` / `echo y > "$S/a"` / `EOF` | silent (a variable the command bound is read as its value) |
| `R=research; echo y > "$R/a"` · `S=/tmp/x; S=research; echo y > "$S/a"` | deny, naming `research/a` (the last binding before the target is its value) |
| `echo y > "$S/a"; S=/tmp/x` | deny, naming `$S/a` (a binding after the target binds nothing for it) |
| `R=research; python3 -c "open('$R/f','w')"` | deny, naming `research/f` (a script literal is read with the bound value too) |
| `cd "$TMPDIR" && echo y > f` | deny, naming `$TMPDIR/f` (stated false deny: `DIR` is read as a path) |
| `cd $(mktemp -d) && echo y > f` | deny, naming `$(mktemp -d)/f` (stated false deny) |
| `cat > /tmp/x <<'EOF' # staged \` / `sed -i 's/a/b/' f` / `EOF` | silent (a `\` ending a comment continues nothing, so the data body begins on the next line) |
| `bash <<'EOF' # run \` / `sed -i 's/a/b/' f` / `EOF` | deny |
| `echo $(( 1 > 0 )) > /tmp/x` | silent (the arithmetic's `>` belongs to the substitution's own command, which matches no form) |
| `echo $(( 1 > 0 )) > f` | deny, naming `f` |
| `x=$(cd /tmp && pwd); echo y > f` | deny, naming `f` (a `cd` inside a `$(…)` does not outlive it) |
| `x=$(S=/tmp; echo $S); echo y > "$S/a"` | deny, naming `$S/a` (nor does a binding) |
| `cd /tmp/x && echo $((1+1)) > f` · `cd /tmp/x && echo $(date) > f` | silent (a `(` inside a `$(…)` is not the unit's subshell) |
| `x=$(` / `cd /tmp` / `)` / `echo y > f` · `x=$(` / `S=/tmp` / `)` / `echo y > "$S/a"` | silent (stated misses: a `$(` that does not close on its line is not read as a subshell) |
| `python fix.py` · `git checkout -- design/x.md` · `git restore design/x.md` · `git reset --hard` · `git stash` · `git clean -fd` · `echo x>f` · `cat<<EOF > f` / `x` / `EOF` | silent (stated misses, §7: a script outside scratch, the git commands another rule covers, a sink or opener glued inside a word) |
| `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `/tmp/fix.sh` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `uv run /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `cat /tmp/fix.py \| python3` · `printf '%s\n' "open('f', 'w')" > /tmp/fix.py && python3 /tmp/fix.py` · `python3 "$(mktemp)"` · `tee /tmp/fix.py <<< "open('f', 'w')"; python3 /tmp/fix.py` · `cat > /tmp/fix.sh <<'EOF'` / `sed -i 's/a/b/' f` / `EOF` / `bash -euxo pipefail /tmp/fix.sh` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `bash <<'B'` / `python3 /tmp/fix.py` / `B` · `cat > /tmp/fix.py <<'PY'` / `open('f', 'w')` / `PY` / `python3 /tmp/fix.py <<'EOF'` / `a.md` / `EOF` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `echo a.md \| python3 /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py <<< a.md` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 -E /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 -Wignore /tmp/fix.py` · `cat > /tmp/fix.py <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 /tmp/fix.py -c cfg.toml` · `cat >> /tmp/fix.py <<'EOF'` / `print(1)` / `EOF` / `python3 /tmp/fix.py` · `bash <<'EOF'` / `cat > /tmp/fix.py <<'PY'` / `open('f', 'w')` / `PY` / `EOF` / `python3 /tmp/fix.py` | silent (stated misses, §7: a script run as its own command word or by another route, staged other than by a heredoc or in another unit than the run's, after a shell cluster ending in `o`, at a path the rules cannot read as scratch, run by an interpreter a row-4 source feeds — `-E`, and a cluster ending in `e` such as `-Wignore`, are row-4 script flags wherever they stand among its arguments — or appended to) |
| `dd if=/tmp/x of=f` · `install -m 644 /tmp/x f` · `cp /tmp/x f` · `rsync /tmp/x f` · `git apply /tmp/p.diff` · `patch -p1 < /tmp/p.diff` · `sd a b f` · `yq -i '.a = 1' f.yaml` · `sort f \| sponge f` · `sort -o f f` · `awk '{print > "f"}' in` · `sed 's/a/b/w out' f` · `sed -n '/x/w out' f` · `fastmod a b` · `comby 'a' 'b' -in-place` · `exec > f` · `truncate -s 0 f` | silent (stated misses, §7: write forms not in §3.2's table) |
| `python3 -c "import shutil; shutil.copy('/tmp/x', 'f')"` · `python3 -c "import shutil; shutil.move('/tmp/x', 'f')"` · `python3 -c "import os; os.replace('/tmp/x', 'f')"` · `python3 -c "Path('f').rename('g')"` · `python3 -c "Path('f').replace('g')"` · `python3 -c "import os; fd = os.open('f', os.O_WRONLY); os.write(fd, b)"` · `python3 -c "df.to_csv('f')"` · `python3 -c "np.save('f', a)"` · `ruby -e 'File.binwrite("f", s)'` · `perl -e 'write_file("f", $s)'` · `python3 -c "import os; os.fdopen(fd, mode='w')"` · `python3 -c "paths[0].open('w')"` | silent (stated misses, §7: interpreter write routes not in §3.2's list) |

### 8.1 Row 6's file reads

The rows that read a file. Each is judged under §8's payload except that `$TMPDIR` is a fresh,
empty directory, into which the test first writes the files the row lists, and in which nothing
else exists. A file is written as `` `name`: `text` `` — that text and a final newline — or as one
of: a symlink to another listed file, a FIFO, a directory, *N* bytes ending in a text (the text
preceded by `#` comment lines to make up the count), or the byte `0xFF` followed by a text.

| Files in `$TMPDIR` | Command | Expected |
|---|---|---|
| `fix.py`: `open('f', 'w').write('x')` | `python3 "$TMPDIR/fix.py"` · `python3 $TMPDIR/fix.py` · `python3 "${TMPDIR}/fix.py"` · `python3 "${TMPDIR:-/tmp}/fix.py"` | deny, naming `f` |
| `fix.py`: `open('/tmp/out', 'w').write('x')` | `python3 "$TMPDIR/fix.py"` | silent |
| `fix.sh`: `sed -i 's/a/b/' f` | `bash "$TMPDIR/fix.sh"` · `sh "$TMPDIR/fix.sh"` | deny, naming `f` |
| `fix.py`: `print(1)` | `cat > "$TMPDIR/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 "$TMPDIR/fix.py"` | deny, naming `f` (the staged body is the text, not the file) |
| `fix.py`: `open('f', 'w')` | `cat > "$TMPDIR/fix.py" <<'EOF'` / `print(1)` / `EOF` / `python3 "$TMPDIR/fix.py"` · `cat >> "$TMPDIR/fix.py" <<'EOF'` / `print(1)` / `EOF` / `python3 "$TMPDIR/fix.py"` | silent (the staged body is the text, not the file — an appended one too) |
| `fix.py`: `print(1)` | `cat > "$TMPDIR/fix.py" <<'EOF'` / `open('f', 'w')` / `EOF` / `python3 "${TMPDIR}/fix.py"` | deny, naming `f` (two spellings of `$TMPDIR` meet through the file's path) |
| `fix.sh`: `python3 "$TMPDIR/inner.py"` · `inner.py`: `open('f', 'w')` | `bash "$TMPDIR/fix.sh"` | silent (inside a script's text row 6 reads no file) |
| `fix.sh`: `python3 "$TMPDIR/inner.py"` · `inner.py`: `open('f', 'w')` | `python3 "$TMPDIR/inner.py"` | deny, naming `f` |
| `fix.py`: a symlink to `real.py` · `real.py`: `open('f', 'w')` | `python3 "$TMPDIR/fix.py"` | silent (a symlink is not followed) |
| `fix.py`: a FIFO · `dir.py`: a directory | `python3 "$TMPDIR/fix.py"` · `python3 "$TMPDIR/dir.py"` · `python3 "$TMPDIR/absent.py"` | silent (no regular file to read, and the FIFO opened without blocking) |
| `fix.py`: 262144 bytes ending in `open('f', 'w')` | `python3 "$TMPDIR/fix.py"` | deny, naming `f` (256 KiB, the most read) |
| `fix.py`: 262145 bytes ending in `open('f', 'w')` | `python3 "$TMPDIR/fix.py"` | silent (over 256 KiB, not read) |
| `fix.py`: the byte `0xFF` followed by `open('f', 'w')` | `python3 "$TMPDIR/fix.py"` | deny, naming `f` (an undecodable byte is replaced) |
| `fix.py`: `open('f', 'w')` | `cd "$TMPDIR" && python3 fix.py` | silent (stated miss, §7: §3.3 reads a `cd`'s `$TMPDIR` as a path) |
