"""Throwaway spike: design/edit-guards.md §3 implemented from its text, checked against §8.

Not the product. It exists to find where §3 is ambiguous or self-contradictory, and where §8's
expected value does not follow from §3. Run: .venv/bin/python experiments/m37_guard_prototype.py
"""

# A throwaway transcription of prose rules, kept one function per clause so it can be read against
# the text: complexity and magic-number rules are waived. S108: the /tmp literals are the spec's
# scratch roots, compared as strings, never opened.
# ruff: noqa: PLR0911, PLR0912, PLR0913, PLR0915, PLR0917, PLR2004, S108

from __future__ import annotations

import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "design" / "edit-guards.md"
CWD = "/home/u/proj"

# Readings the spec leaves open; research/m37-guard-prototype-run.md has the resolved ones.
AMBIGUITIES: list[str] = []


# ---------------------------------------------------------------- characters, units, bodies


@dataclass
class C:
    c: str
    k: str  # code | str | q (quote delimiter) | cmt | join
    qt: str = ""
    oid: object = None


@dataclass
class Body:
    delim: str
    dash: bool
    lines: list[str]
    scanned: bool = False
    unit: Unit | None = None


@dataclass
class Unit:
    lines: list[str] = field(default_factory=list)
    openers: list[list[tuple[int, object]]] = field(default_factory=list)
    bodies: list[Body] = field(default_factory=list)
    chars: list[C] = field(default_factory=list)
    pipelines: list[list[Seg]] = field(default_factory=list)


@dataclass
class Tok:
    chars: list[C]
    marker: str = ""
    procsub: str = ""  # whole | open

    @property
    def raw(self) -> str:
        return self.marker or "".join(c.c for c in self.chars)

    @property
    def unq(self) -> str:
        return self.marker or "".join(c.c for c in self.chars if c.k != "q")

    @property
    def code_first(self) -> bool:
        return bool(self.chars) and self.chars[0].k == "code"


@dataclass
class Seg:
    toks: list[Tok]
    cps: set[int]
    ender: str


def find_close(s: str, start: int, q: str) -> int | None:
    i = start
    while i < len(s):
        if q == '"' and s[i] == "\\":
            i += 2
            continue
        if s[i] == q:
            return i
        i += 1
    return None


def paired_ranges(line: str) -> list[tuple[int, int]]:
    spans = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and line[i + 1 : i + 2] in ("'", '"'):
            i += 2  # §7: outside a string, \" and \' open nothing
            continue
        if line[i] in "'\"":
            j = find_close(line, i + 1, line[i])
            if j is not None:
                spans.append((i, j))
                i = j + 1
                continue
        i += 1
    return spans


def inside(spans: list[tuple[int, int]], i: int) -> bool:
    return any(a <= i <= b for a, b in spans)


OPENER_RE = re.compile(r"(?<!<)<<(-?)(?!<)")


def find_openers(line: str) -> tuple[list[tuple[int, bool, str]], str]:
    """§3.1 step 1: openers on a raw line, after removing each opener's own quoted delimiter."""
    found = []
    neutral = list(line)
    for m in OPENER_RE.finditer(line):
        p = m.end()
        while p < len(line) and line[p] in " \t":
            p += 1
        if p >= len(line):
            continue
        if line[p] in "'\"":
            j = line.find(line[p], p + 1)
            if j < 0:
                continue
            delim = line[p + 1 : j]
            neutral[p] = neutral[j] = "_"
        else:
            mm = re.match(r"\\?([^\s;|&()<>'\"]+)", line[p:])
            if not mm:
                continue
            delim = mm.group(1)
        found.append((m.start(), m.group(1) == "-", delim))
    nl = "".join(neutral)
    spans = paired_ranges(nl)
    return [f for f in found if not inside(spans, f[0])], nl


def raw_comment_start(line: str, spans: list[tuple[int, int]]) -> int | None:
    for i, c in enumerate(line):
        if c == "#" and (i == 0 or line[i - 1] in " \t") and not inside(spans, i):
            return i
    return None


def continues(line: str) -> bool:
    m = re.search(r"(\\+)$", line)
    if m and len(m.group(1)) % 2 == 1:
        return True
    _, nl = find_openers(line)
    spans = paired_ranges(nl)
    cut = raw_comment_start(nl, spans)
    s = (nl if cut is None else nl[:cut]).rstrip()
    return s.endswith(("|", "&&"))


SHELL_RE = re.compile(r"(ba|z|da|k)?sh")
INTERP_RE = re.compile(r"python[0-9.]*t?|pypy[0-9]*|node|nodejs")
PY_RE = re.compile(r"python[0-9.]*t?|pypy[0-9]*")


def is_scanned(lines: list[str], group: list[int], gi: int, col: int) -> bool:
    """§3.2: the opener's pipeline has a shell or interpreter word as a command word."""
    sentinel = object()
    chars: list[C] = []
    for n, g in enumerate(group):
        _, nl = find_openers(lines[g])
        spans = paired_ranges(nl)
        cut = raw_comment_start(nl, spans)
        for i, ch in enumerate(nl):
            if cut is not None and i >= cut:
                break
            if any(i in (a, b) for a, b in spans):
                kind = "q"
            elif inside(spans, i):
                kind = "str"
            else:
                kind = "code"
            cc = C(ch, kind)
            if n == gi and i == col:
                cc.oid = sentinel
            chars.append(cc)
        if n < len(group) - 1:
            if chars and chars[-1].c == "\\" and chars[-1].k == "code":
                chars[-1].k = "join"
            chars.append(C("\n", "join"))
    pipes: list[list[Seg]] = []
    parse_seq(chars, pipes)
    for pipe in pipes:
        if any(c.oid is sentinel for s in pipe for t in s.toks for c in t.chars):
            for seg in pipe:
                for k in command_words(seg):
                    w = cmd_name(seg.toks[k])
                    if SHELL_RE.fullmatch(w) or INTERP_RE.fullmatch(w):
                        return True
    return False


def delimit(lines: list[str]) -> Unit:
    unit = Unit()
    i = 0
    while i < len(lines):
        group = [i]
        while continues(lines[group[-1]]) and group[-1] + 1 < len(lines):
            group.append(group[-1] + 1)
        pos = group[-1] + 1
        here: dict[int, list[tuple[int, object]]] = {}
        for gi, g in enumerate(group):
            ops, _ = find_openers(lines[g])
            for col, dash, delim in ops:
                k = pos
                while k < len(lines) and (lines[k].lstrip("\t") if dash else lines[k]) != delim:
                    k += 1
                body = Body(delim, dash, lines[pos:k])
                body.scanned = is_scanned(lines, group, gi, col)
                if body.scanned:
                    body.unit = delimit(body.lines)
                unit.bodies.append(body)
                here.setdefault(gi, []).append((col, body))
                pos = k + 1
        for gi, g in enumerate(group):
            unit.lines.append(lines[g])
            unit.openers.append(here.get(gi, []))
        i = pos
    return unit


def annotate(unit: Unit) -> list[C]:
    """§3.1 step 2, then step 3's joins."""
    out: list[C] = []
    ml = ""
    for li, text in enumerate(unit.lines):
        row: list[C] = []
        p = 0
        n = len(text)
        if ml:
            j = find_close(text, 0, ml)
            if j is None:
                row += [C(ch, "str", ml) for ch in text]
                p = n
            else:
                row += [C(ch, "str", ml) for ch in text[:j]]
                row.append(C(text[j], "q", ml))
                p = j + 1
                ml = ""
        while p < n:
            c = text[p]
            if c == "\\" and text[p + 1 : p + 2] in ("'", '"'):
                row += [C(c, "code"), C(text[p + 1], "code")]
                p += 2
            elif c in "'\"":
                j = find_close(text, p + 1, c)
                row.append(C(c, "q", c))
                if j is not None:
                    row += [C(ch, "str", c) for ch in text[p + 1 : j]]
                    row.append(C(text[j], "q", c))
                    p = j + 1
                else:
                    row += [C(ch, "str", c) for ch in text[p + 1 :]]
                    ml = c
                    p = n
            elif c == "#" and (p == 0 or text[p - 1] in " \t"):
                row += [C(ch, "cmt") for ch in text[p:]]
                p = n
            else:
                row.append(C(c, "code"))
                p += 1
        for col, body in unit.openers[li]:
            row[col].oid = body
        out += row
        if li < len(unit.lines) - 1:
            out.append(C("\n", "str", ml) if ml else C("\n", "code"))
    # step 3: continuations
    for i, ch in enumerate(out):
        if ch.c != "\n" or ch.k != "code":
            continue
        j = i - 1
        bs = 0
        while j >= 0 and out[j].c == "\\" and out[j].k == "code":
            bs += 1
            j -= 1
        if bs % 2 == 1:
            out[i - 1].k = "join"
            ch.k = "join"
            continue
        j = i - 1
        while j >= 0 and out[j].c != "\n" and (out[j].k == "cmt" or out[j].c in " \t"):
            j -= 1
        pipe_end = j >= 0 and out[j].k == "code" and out[j].c == "|"
        and_end = j >= 1 and out[j].c == "&" and out[j - 1].c == "&" and out[j].k == "code"
        if pipe_end or and_end:
            ch.k = "join"
    return out


def same_line_close(chars: list[C], start: int, stop_ws: bool = False) -> int | None:
    depth = 1
    for j in range(start, len(chars)):
        ch = chars[j]
        if ch.c == "\n":
            return None
        if ch.k != "code":
            continue
        if stop_ws and ch.c in " \t":
            return None
        if ch.c == "(":
            depth += 1
        elif ch.c == ")":
            depth -= 1
            if depth == 0:
                return j
    return None


def parse_seq(chars: list[C], out: list[list[Seg]]) -> None:
    """Simple commands and pipelines, §3.1. Same-line `$(…)` contents become their own pipelines."""
    pipe: list[Seg] = []
    toks: list[Tok] = []
    cps: set[int] = {0}
    cur: list[C] = []
    cur_ps = ""

    def flush() -> None:
        nonlocal cur, cur_ps
        if cur:
            toks.append(Tok(cur, procsub=cur_ps))
        cur = []
        cur_ps = ""

    def end(ender: str) -> None:
        nonlocal toks, cps, pipe
        flush()
        pipe.append(Seg(toks, cps, ender))
        toks = []
        cps = {0}
        if ender != "|":
            out.append(pipe)
            pipe = []

    n = len(chars)

    def code(j: int, c: str) -> bool:
        return 0 <= j < n and chars[j].k == "code" and chars[j].c == c

    i = 0
    while i < n:
        ch = chars[i]
        if ch.k in ("str", "q"):
            cur.append(ch)
            i += 1
            continue
        if ch.k == "cmt":
            i += 1
            continue
        if ch.k == "join":
            flush()
            i += 1
            continue
        c = ch.c
        if c == "\n":
            end("\n")
            i += 1
        elif c in " \t":
            flush()
            i += 1
        elif c == "$" and code(i + 1, "("):
            j = same_line_close(chars, i + 2)
            if j is not None:
                parse_seq(chars[i + 2 : j], out)
                cur.extend(chars[i : j + 1])
                i = j + 1
            else:
                flush()
                toks.append(Tok([], marker="$("))
                cps.add(len(toks))
                i += 2
        elif c in "<>" and not cur and code(i + 1, "("):
            j = same_line_close(chars, i + 2, stop_ws=True)
            if j is not None:
                cur.extend(chars[i : j + 1])
                cur_ps = "whole"
                i = j + 1
            else:
                cur.extend(chars[i : i + 2])
                cur_ps = "open"
                i += 2
        elif c == "|" and code(i - 1, ">") and cur:
            cur.append(ch)  # bash's clobber `>|` is one redirect token, not a pipe
            i += 1
        elif c == "|":
            if code(i + 1, "|"):
                end("||")
                i += 2
            elif code(i + 1, "&"):  # bash's |& is read as |
                end("|")
                i += 2
            else:
                end("|")
                i += 1
        elif c == "&":
            if code(i + 1, "&"):
                end("&&")
                i += 2
            elif code(i - 1, ">") or code(i + 1, ">"):
                cur.append(ch)
                i += 1
            else:
                end("&")
                i += 1
        elif c == ";":
            end(";")
            i += 1
        elif c == ")":
            end(")")
            i += 1
        elif c == "(":
            flush()
            toks.append(Tok([], marker="("))
            cps.add(len(toks))
            i += 1
        elif c == "{" and not cur and (i + 1 >= n or chars[i + 1].c in " \t\n"):
            toks.append(Tok([], marker="{"))
            cps.add(len(toks))
            i += 1
        else:
            cur.append(ch)
            i += 1
    end("EOF")


# ---------------------------------------------------------------- command position

KEYWORDS = {"if", "while", "until", "do", "then", "else", "elif"}
WRAPPERS = {"sudo", "env", "xargs", "time", "timeout", "nice", "nohup", "command", "exec"}
WRAPPERS |= {"busybox", "npx"}
RUNNERS = {"uv", "poetry", "pdm", "pipenv"}
ARGFLAGS = {
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-s", "-E", "--max-args", "--max-procs"},
    "nice": {"-n"},
    "sudo": {"-u", "-g", "--user", "--group"},
    "env": {"-u"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "uv run": {"--with", "--python", "-p"},
}


def base(w: str) -> str:
    return re.sub(r"^(?:\S*/)?", "", w.lstrip("\\"))


def cmd_name(t: Tok) -> str:
    return base(t.unq)


def skip_prefix(toks: list[Tok], k: int) -> int | None:
    while k < len(toks):
        t = toks[k]
        if t.marker:
            return None
        w = t.unq
        if re.fullmatch(r"[A-Za-z_]\w*=.*", w, re.S):
            k += 1
            continue
        b = base(w)
        if b in KEYWORDS:
            k += 1
            continue
        two = b in RUNNERS and k + 1 < len(toks) and toks[k + 1].unq == "run"
        if two or b in WRAPPERS:
            key = b + " run" if two else b
            k += 2 if two else 1
            argf = ARGFLAGS.get(key, set())
            while k < len(toks) and not toks[k].marker and toks[k].unq.startswith("-"):
                k += 2 if toks[k].unq in argf else 1
            if key == "timeout" and k < len(toks):
                k += 1
            continue
        return k
    return None


def command_words(seg: Seg) -> list[int]:
    starts = set(seg.cps)
    for idx, t in enumerate(seg.toks):
        if not t.marker and t.unq in ("-exec", "-execdir"):
            starts.add(idx + 1)
    res = []
    for s in sorted(starts):
        k = skip_prefix(seg.toks, s)
        if k is not None and k < len(seg.toks):
            res.append(k)
    return sorted(set(res))


# ---------------------------------------------------------------- targets and scratch

SCRATCH_ROOTS = ["/tmp", "/var/tmp", "/dev"]


def strip_quotes(t: str) -> str:
    return re.sub(r"\\?['\"]", "", t)


def under(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def is_scratch(t: str, cwd: str, tmpdir: str | None) -> bool:
    s = strip_quotes(t)
    if re.match(r"\$TMPDIR(/|$)", s) or re.match(r"\$\{TMPDIR[^}]*\}(/|$)", s):
        return True
    p = normalise(s, cwd)
    roots = list(SCRATCH_ROOTS)
    if tmpdir and tmpdir != "/":
        roots.append(normalise(tmpdir, cwd))
    roots += ["/private" + r for r in roots if r != "/dev"]
    return any(under(p, r) for r in roots)


def normalise(s: str, cwd: str) -> str:
    p = s if s.startswith("/") else cwd + "/" + s
    p = posixpath.normpath(p)
    return "/" + p.lstrip("/")


def redirects(toks: list[Tok]) -> tuple[list[str], set[int]]:
    """Sinks' targets and the indices of redirect tokens (§3.1)."""
    sinks: list[str] = []
    red: set[int] = set()
    for i, t in enumerate(toks):
        if t.marker or not t.code_first:
            continue
        r = t.raw
        if t.procsub:
            if t.procsub == "open":
                # the `)` that closes it ends this simple command, so "every token up to that
                # `)`" is the rest of the list
                red.update(range(i, len(toks)))
            continue
        if r in (">", ">>"):
            red.add(i)
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is not None and not nxt.marker and not nxt.procsub:
                sinks.append(nxt.raw)
                red.add(i + 1)
        elif re.match(r">>?[^>&(|]", r):
            sinks.append(r.lstrip(">"))
            red.add(i)
        elif r.startswith(("<", ">&", "&>")) or re.match(r"\d+[<>]", r):
            red.add(i)
            if r in ("&>", "&>>", "<", "<<", "<<-", "<<<", ">&") or re.fullmatch(
                r"\d+(>>?|<|>&)", r
            ):
                red.add(i + 1)
    return sinks, red


SED_INPLACE = re.compile(r"-[nrEsuz]*[iI]")
PERL_INPLACE = re.compile(r"-(?:[pnlaws]|0[0-7]*+)*+i")
RUBY_INPLACE = re.compile(r"-[pnlaw]*i")


def inplace_token(family: str, u: str) -> bool:
    if family == "sed":
        return bool(SED_INPLACE.match(u)) or u == "--in-place" or u.startswith("--in-place=")
    if family == "perl":
        return bool(PERL_INPLACE.match(u))
    if family == "ruby":
        return bool(RUBY_INPLACE.match(u))
    return False


def rows123_targets(family: str, toks: list[Tok]) -> list[str]:
    _, red = redirects(toks)
    cands: list[str] = []
    script_flag = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if i in red or t.marker or t.procsub:
            i += 1
            continue
        u = t.unq
        if t.code_first and u.startswith("-"):
            if inplace_token(family, u):
                bare = re.fullmatch(r"-[nrEsuz]*[iI]|-(?:[pnlaws]|0[0-7]*+)*+i", u)
                if bare and i + 1 < len(toks) and toks[i + 1].raw in ("''", '""'):
                    i += 2
                    continue
                i += 1
                continue
            consume = False
            letters = "ef" + ("E" if family == "perl" else "")
            if u in ("--expression", "--file"):
                consume, script_flag = True, True
            elif u.startswith(("--expression=", "--file=")):
                script_flag = True
            elif len(u) > 2 and u[1] in letters and not u.startswith("--"):
                script_flag = True  # glued -e's/a/b/'
            elif re.fullmatch(r"-[A-Za-z0-9]*[" + letters + "]", u):
                consume, script_flag = True, True
            elif (
                (family == "awk" and u in ("-i", "--include", "-v", "-F"))
                or (family == "sed" and u in ("-l", "--line-length"))
                or (family == "perl" and u in ("-I", "-M"))
                or (family == "ruby" and u in ("-I", "-r"))
            ):
                consume = True
            i += 2 if consume else 1
            continue
        cands.append(t.raw)
        i += 1
    if not script_flag and cands:
        cands = cands[1:]
    return cands


# ---------------------------------------------------------------- row 4

# §3.2's list of write calls. Each allows `\\?` before a quote.
Q = r"\\?['\"]"
MODE = r"(w|a|x|r[bt]?\+)[bt+]*(?:[:|]\w+)?"
WRITE_RX = [
    (
        "open",
        re.compile(
            r"(?<!\w)open\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*,\s*(?:mode\s*=\s*)?" + Q + MODE + Q
        ),
    ),
    (
        "dotopen",
        re.compile(r"(?:(?<![\w.])\w+|\))\.open\(\s*(?:mode\s*=\s*)?" + Q + MODE + Q),
    ),
    ("write_text", re.compile(r"\.write_text\(")),
    ("write_bytes", re.compile(r"\.write_bytes\(")),
    ("writeFile", re.compile(r"(?:write|append)File(?:Sync)?\(|createWriteStream\(")),
    (
        "fileinput",
        re.compile(
            r"(?:fileinput\.)?(?:input|FileInput)\((?:[^()]|\([^()]*\))*inplace\s*=\s*(?:True|1)\b"
        ),
    ),
]
# the receiver words whose `open(` takes a path first, excluded from the receiver pattern
PATH_FIRST_MODULES = {
    "io",
    "codecs",
    "gzip",
    "bz2",
    "lzma",
    "tarfile",
    "wave",
    "aifc",
    "fsspec",
    "smart_open",
    "fs",
}
# §3.3's path functions (head rule 5): their first argument is judged as a head
PATH_FUNCS = {
    "str",
    "Path",
    "pathlib.Path",
    "os.path.join",
    "os.path.abspath",
    "os.path.expanduser",
    "os.path.realpath",
    "os.path.dirname",
    "os.fspath",
    "path.join",
    "path.resolve",
}
JOINERS = {"os.path.join", "path.join"}
# head rule 6: a chain containing one of these yields nothing
CHAIN_STOPS = {
    "read_text",
    "read_bytes",
    "read",
    "readlines",
    "exists",
    "is_file",
    "is_dir",
    "stat",
    "iterdir",
    "glob",
    "rglob",
    "stem",
    "name",
    "suffix",
    "parts",
}
SCRATCH_CALL_RE = re.compile(
    r"(?:\w+\.)*tempfile\."
    r"|(?:mkdtemp|mkstemp|mktemp|gettempdir|TemporaryFile|NamedTemporaryFile"
    r"|SpooledTemporaryFile|TemporaryDirectory)\("
    r"|(?:[\w.]*\.)?(?:environ\[\s*['\"]TMPDIR['\"]\s*\]"
    r"|environ\.get\(\s*['\"]TMPDIR['\"]|getenv\(\s*['\"]TMPDIR['\"])"
    r"|process\.env\.TMPDIR\b"
)
WRITE_MODE_RE = re.compile(r"\(\s*(?:mode\s*=\s*)?['\"](w|a|x|r[bt]?\+)")
BIND_RE = re.compile(r"\s*(?:(?:const|let|var)\s+)?([A-Za-z_]\w*)\s*(?::[^=]*)?=(?!=)\s*")
NAME = r"[A-Za-z_]\w*"
LIT_START = re.compile(r"(?<![\w])([rRbBfFuU]{0,2})(['\"`])")


def is_scratch_call(op: str) -> bool:
    """§3.3 head rule 1, judged on an operand's text."""
    op = op.strip()
    return bool(SCRATCH_CALL_RE.match(op)) or bool(re.search(r"\btmpdir\(\)$", op))


@dataclass
class Lit:
    start: int
    end: int
    content: str


Contribution = tuple[str, str]  # (lit|scratch, text)


class Script:
    """A row-4 script as the interpreter sees it, judged by §3.3's target-expression rules."""

    def __init__(
        self,
        s: str,
        cwd: str,
        tmpdir: str | None,
        bind: dict[str, Contribution] | None = None,
    ) -> None:
        self.s = s
        self.cwd = cwd
        self.tmpdir = tmpdir
        self.bind: dict[str, Contribution] = bind if bind is not None else {}
        self.lits: list[Lit] = []
        i = 0
        while True:
            m = LIT_START.search(s, i)
            if not m:
                break
            q = m.group(2)
            j = m.end()
            ok = False
            while j < len(s):
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == q:
                    ok = True
                    break
                if s[j] == "\n" and q != "`":
                    break
                j += 1
            if not ok:
                i = m.end()
                continue
            self.lits.append(Lit(m.start(), j + 1, s[m.end() : j]))
            i = j + 1
        b = list(s)
        for lit in self.lits:
            for k in range(lit.start, lit.end):
                if b[k] != "\n":
                    b[k] = "_"
        self.b = "".join(b)

    # -- text helpers

    def lit_at(self, pos: int) -> Lit | None:
        return next((lit for lit in self.lits if lit.start == pos), None)

    def close_of(self, i: int) -> int | None:
        depth = 0
        for j in range(i, len(self.b)):
            if self.b[j] in "([{":
                depth += 1
            elif self.b[j] in ")]}":
                depth -= 1
                if depth == 0:
                    return j
        return None

    def open_of(self, j: int) -> int | None:
        """The bracket opening the one that closes at `j`."""
        depth = 0
        for i in range(j, -1, -1):
            if self.b[i] in ")]}":
                depth += 1
            elif self.b[i] in "([{":
                depth -= 1
                if depth == 0:
                    return i
        return None

    def args(self, o: int) -> list[tuple[int, int]]:
        c = self.close_of(o)
        if c is None:
            return []
        res = []
        depth = 0
        a = o + 1
        for j in range(o + 1, c):
            ch = self.b[j]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                res.append((a, j))
                a = j + 1
        if self.s[a:c].strip() or res:
            res.append((a, c))
        return res

    def trim(self, a: int, b: int) -> tuple[int, int]:
        while a < b and self.s[a].isspace():
            a += 1
        while b > a and self.s[b - 1].isspace():
            b -= 1
        return a, b

    def whole_lit(self, a: int, b: int) -> Lit | None:
        a, b = self.trim(a, b)
        lit = self.lit_at(a)
        return lit if lit and lit.end == b else None

    def operand_end(self, a: int, b: int) -> int:
        """End of the operand starting at `a`: a name, call or parenthesised group, with its
        `.name`/`.name(…)` chain."""
        if self.b[a : a + 1] == "(":
            c = self.close_of(a)
            if c is None or c >= b:
                return a
            i = c + 1
        else:
            m = re.match(NAME, self.b[a:b])
            if not m:
                return a
            i = a + m.end()
        while i < b:
            if self.b[i] in "([":
                c = self.close_of(i)
                if c is None or c >= b:
                    break
                i = c + 1
                continue
            mm = re.match(r"\." + NAME, self.b[i:b])
            if mm:
                i += mm.end()
                continue
            break
        return i

    def slash_literals(self, start: int, end: int) -> tuple[list[str], int]:
        """The literals of a `/ '…' / '…'` chain from `start`, up to the first non-literal."""
        extra: list[str] = []
        rest = start
        while True:
            mm = re.match(r"\s*/\s*", self.s[rest:end])
            if not mm:
                break
            lit = self.lit_at(rest + mm.end())
            if not lit:
                break
            extra.append(lit.content)
            rest = lit.end
        return extra, rest

    def chain_yields(self, start: int, end: int) -> bool:
        """Head rule 6: False when the `.name(…)` chain in start..end contains a read, a name
        component, or a `.open(` with no write mode."""
        pos = start
        while pos < end:
            mm = re.match(r"\.(" + NAME + r")", self.b[pos:end])
            if not mm:
                break
            name = mm.group(1)
            pos += mm.end()
            if name in CHAIN_STOPS:
                return False
            if pos < end and self.b[pos] == "(":
                if name == "open" and not WRITE_MODE_RE.match(self.s, pos):
                    return False
                c = self.close_of(pos)
                if c is None:
                    break
                pos = c + 1
        return True

    # -- the head rule

    def lit_value(self, lit: Lit) -> list[Contribution]:
        """§3.3 Literals: a `{…}`/`${…}` span at the literal's start is judged as a head."""
        m = re.match(r"\$?\{([^}]*)\}", lit.content)
        if m:
            sub = Script(m.group(1), self.cwd, self.tmpdir, self.bind)
            h = sub.target(0, len(m.group(1)))
            if h:
                return h
        return [("lit", lit.content)]

    def target(self, a: int, b: int) -> list[Contribution]:
        """§3.3: judge a target expression by its head; [] is 'nothing'."""
        a, b = self.trim(a, b)
        if a >= b:
            return []
        e = self.operand_end(a, b)
        if self.b[a] == "(":
            # a parenthesised group heads the operand: judged by its contents, then step 6 on
            # any chain after it
            c = self.close_of(a)
            if c is None:
                return []
            value = self.target(a + 1, c)
            if not value or not self.chain_yields(c + 1, e):
                return []
            return value
        op = self.s[a:e]
        # 1. a scratch call, on the whole operand (head and chain)
        if op and is_scratch_call(op):
            return [("scratch", "scratch call")]
        # 2. a string literal (a chain after it is not one step 6 names)
        lit = self.lit_at(a)
        if lit:
            return self.lit_value(lit)
        head_end, value = self.head(a, b, e)
        if not value:
            return []
        # 6. a chain after the head: the head's target, unless it holds a read or name component
        if not self.chain_yields(head_end, e):
            return []
        return value

    def head(self, a: int, b: int, e: int) -> tuple[int, list[Contribution]]:
        """Steps 3 to 5, on the head alone: the operand before its `.name`/`.name(…)` chain.
        Returns where the head ends (the chain starts there) and what it yields."""
        # a call head: `Path(…)`, a path function, or any other call
        cm = re.match(r"(" + NAME + r"(?:\." + NAME + r")*)\(", self.b[a:e])
        callee = cm.group(1) if cm else ""
        is_path = bool(re.fullmatch(r"(?:pathlib\.)?Path", callee))
        if cm and (is_path or callee in PATH_FUNCS or "." not in callee):
            o = a + cm.end() - 1
            c = self.close_of(o)
            if c is None:
                return e, []
            args = self.args(o)
            # 3. Path('…'), with its / chain
            if is_path and args:
                if is_scratch_call(self.s[slice(*self.trim(*args[0]))]):
                    return c + 1, [("scratch", "Path(scratch call)")]
                parts = [self.whole_lit(x, y) for x, y in args]
                if all(parts):
                    extra, _ = self.slash_literals(e, b) if e == c + 1 else ([], 0)
                    return c + 1, [("lit", "/".join([*(p.content for p in parts if p), *extra]))]
            # 5. a path function: its first argument as a head
            if callee in PATH_FUNCS and args:
                if callee in JOINERS:
                    lits = []
                    for x, y in args:
                        lt = self.whole_lit(x, y)
                        if not lt:
                            break
                        lits.append(lt.content)
                    if len(lits) > 1:
                        return c + 1, [("lit", "/".join(lits))]
                return c + 1, self.target(*args[0])
            return c + 1, []  # any other call
        # 4. a name head (a dotted callee that is no path function is a name and its chain)
        nm = re.match(NAME, self.b[a:e])
        if not nm:
            return e, []
        name = nm.group(0)
        return a + nm.end(), ([self.bind[name]] if name in self.bind else [])

    def first_argument(self, o: int) -> list[Contribution]:
        """A write call's first argument, or a `file=`/`path=` keyword."""
        args = self.args(o)
        for x, y in args:
            km = re.match(r"\s*(?:file|path)\s*=(?!=)\s*", self.s[x:y])
            if km:
                return self.target(x + km.end(), y)
        if not args or re.match(r"\s*" + NAME + r"\s*=(?!=)", self.s[args[0][0] : args[0][1]]):
            return []
        return self.target(*args[0])

    def receiver(self, dot: int) -> list[Contribution]:
        """The receiver before the method whose `.` is at `dot`: a name, a `Path(…)` or a
        parenthesised group, with any `.name(…)` chain between."""
        j = dot
        while j > 0:
            if self.b[j - 1] == ")":
                o = self.open_of(j - 1)
                if o is None:
                    break
                j = o
                m = re.search(NAME + r"$", self.b[:j])
                if not m:
                    break  # a parenthesised group
                j = m.start()
            else:
                m = re.search(NAME + r"$", self.b[:j])
                if not m:
                    break
                j = m.start()
            if j > 0 and self.b[j - 1] == ".":
                j -= 1
                continue
            break
        return self.target(j, dot)

    # -- bindings

    def with_bindings(self, s0: int, s1: int) -> None:
        """`with <expr> as name` binds scratch where <expr>'s head is a scratch call."""
        m = re.match(r"\s*with\s+", self.b[s0:s1])
        if not m:
            return
        start = s0 + m.end()
        end = s1
        if self.b[start : start + 1] == "(":
            c = self.close_of(start)
            if c is not None and re.match(r"\s*:", self.b[c + 1 : s1]):
                start, end = start + 1, c
        depth = 0
        items = []
        j = start
        while j < end:
            ch = self.b[j]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif depth == 0 and ch in ",:":
                items.append((start, j))
                start = j + 1
                if ch == ":":
                    break
            j += 1
        if end != s1:
            items.append((start, end))
        for x, y in items:
            am = re.match(r"(.*)\s+as\s+(" + NAME + r")\s*$", self.s[x:y], re.S)
            if not am:
                continue
            ea, eb = self.trim(x, x + am.end(1))
            if is_scratch_call(self.s[ea : self.operand_end(ea, eb)]):
                self.bind[am.group(2)] = ("scratch", "with … as")
            else:
                self.bind.pop(am.group(2), None)

    # -- the statement walk

    def write_calls(self) -> dict[int, tuple[str, int]]:
        """Each write call, keyed by its opening paren: (kind, where its target expression is)."""
        calls: dict[int, tuple[str, int]] = {}
        s = self.s
        for kind, rx in WRITE_RX:
            for m in rx.finditer(s):
                if kind == "open":
                    calls.setdefault(m.start() + 4, ("first", m.start() + 4))
                elif kind == "dotopen":
                    rm = re.match(r"(\w+)\.open", s[m.start() :])
                    if rm and rm.group(1) in PATH_FIRST_MODULES:
                        continue
                    dot = s.index(".open(", m.start())
                    calls.setdefault(dot + 5, ("receiver", dot))
                elif kind in ("write_text", "write_bytes"):
                    calls.setdefault(m.end() - 1, ("receiver", m.start()))
                else:  # writeFile, fileinput
                    o = s.index("(", m.start())
                    calls.setdefault(o, ("first", o))
        return calls

    def analyse(self) -> tuple[bool, list[tuple[str, str]]]:
        calls = self.write_calls()
        if not calls:
            return False, []
        stmts = []
        a = 0
        depth = 0
        for j, ch in enumerate(self.b):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch in ";\n" and depth == 0:
                stmts.append((a, j))
                a = j + 1
        stmts.append((a, len(self.b)))
        out: list[tuple[str, str]] = []
        for s0, s1 in stmts:
            self.with_bindings(s0, s1)
            for o in sorted(k for k in calls if s0 <= k < s1):
                kind, where = calls[o]
                got = self.first_argument(where) if kind == "first" else self.receiver(where)
                out += got or [("nothing", self.s[max(s0, o - 40) : o + 1].strip())]
            bm = BIND_RE.match(self.s[s0:s1])
            if bm:
                v = self.target(s0 + bm.end(), s1)
                if v:
                    self.bind[bm.group(1)] = v[0]
                else:
                    self.bind.pop(bm.group(1), None)
        return True, out


def deshell(t: Tok) -> str:
    out = []
    open_q = False
    prev = ""
    for c in t.chars:
        if c.k == "q":
            out.append(" " if open_q else "\n")
            open_q = not open_q
        elif c.k == "str" and c.qt == '"' and prev == "\\" and c.c in '"\\$`':
            out[-1] = c.c
        else:
            out.append(c.c)
        prev = c.c if c.k == "str" else ""
    return "".join(out)


def py_drop_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        spans = paired_ranges(line)
        cut = raw_comment_start(line, spans)
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def tok_script(t: Tok) -> str:
    d = deshell(t)
    if any(c.k == "str" and c.c == "\n" for c in t.chars):
        d = py_drop_comments(d)
    return d


def has_lt2(t: Tok) -> bool:
    return any(c.oid for c in t.chars) or (t.code_first and t.raw.startswith("<<"))


# ---------------------------------------------------------------- forms


@dataclass
class Hit:
    form: str
    targets: list[tuple[str, bool]]

    @property
    def exempt(self) -> bool:
        return bool(self.targets) and all(s for _, s in self.targets)


def path_targets(raws: list[str], cwd: str, tmpdir: str | None) -> list[tuple[str, bool]]:
    return [(normalise(strip_quotes(r), cwd), is_scratch(r, cwd, tmpdir)) for r in raws]


def eval_pipeline(pipe: list[Seg], cwd: str, tmpdir: str | None) -> list[Hit]:
    hits: list[Hit] = []
    pipe_lt2 = any(has_lt2(t) for s in pipe for t in s.toks)
    bodies = [
        c.oid
        for s in pipe
        for t in s.toks
        for c in t.chars
        if isinstance(c.oid, Body) and c.oid.scanned
    ]
    seg_words = [[cmd_name(s.toks[k]) for k in command_words(s)] for s in pipe]
    for si, seg in enumerate(pipe):
        for k in command_words(seg):
            name = cmd_name(seg.toks[k])
            toks = seg.toks[k + 1 :]
            uq = [t.unq for t in toks]
            if re.fullmatch(r"g?sed", name) and any(
                SED_INPLACE.match(u) or re.fullmatch(r"--in-place(=.*)?", u) for u in uq
            ):
                tg = rows123_targets("sed", toks)
                hits.append(Hit("sed (row 1)", path_targets(tg, cwd, tmpdir)))
            if name in ("perl", "ruby"):
                rx = PERL_INPLACE if name == "perl" else RUBY_INPLACE
                if any(rx.match(u) for u in uq):
                    tg = rows123_targets(name, toks)
                    hits.append(Hit(f"{name} (row 2)", path_targets(tg, cwd, tmpdir)))
            if re.fullmatch(r"g?awk", name):
                ok = any(
                    (u in ("-i", "--include") and j + 1 < len(uq) and uq[j + 1] == "inplace")
                    or u in ("-iinplace", "--include=inplace")
                    for j, u in enumerate(uq)
                )
                if ok:
                    tg = rows123_targets("awk", toks)
                    hits.append(Hit("awk (row 3)", path_targets(tg, cwd, tmpdir)))
            if INTERP_RE.fullmatch(name):
                hit = row4(name, toks, si, pipe, seg_words, pipe_lt2, bodies, cwd, tmpdir)
                if hit:
                    hits.append(hit)
            if name in ("cat", "echo", "printf", "tee"):
                sinks, red = redirects(toks)
                tg: list[str] = []
                if name in ("echo", "printf"):
                    tg = sinks
                elif name == "cat":
                    tg = sinks if sinks and any(has_lt2(t) for t in toks) else []
                elif tee_fed(pipe, si, toks, seg_words):
                    own = [
                        t.raw
                        for j, t in enumerate(toks)
                        if j not in red
                        and not t.marker
                        and not t.procsub
                        and not (t.code_first and t.unq.startswith("-"))
                    ]
                    tg = own + sinks
                if tg:
                    hits.append(Hit(f"{name} (row 5)", path_targets(tg, cwd, tmpdir)))
    return hits


def is_program_word(w: str) -> bool:
    return bool(SHELL_RE.fullmatch(w) or INTERP_RE.fullmatch(w))


def tee_fed(pipe: list[Seg], si: int, toks: list[Tok], seg_words: list[list[str]]) -> bool:
    """§3.2 row 5: tee fed by literal text — a `<<`/`<<<` in its own simple command, or, walking
    back over filters, a simple command carrying an opener or that is echo/printf. A shell or
    interpreter word stops the walk."""
    if any(has_lt2(t) for t in toks):
        return True
    for j in range(si - 1, -1, -1):
        words = seg_words[j]
        if any(is_program_word(w) for w in words):
            return False
        if any(w in ("echo", "printf") for w in words) or any(has_lt2(t) for t in pipe[j].toks):
            return True
    return False


def row4(
    name: str,
    toks: list[Tok],
    si: int,
    pipe: list[Seg],
    seg_words: list[list[str]],
    pipe_lt2: bool,
    bodies: list[Body],
    cwd: str,
    tmpdir: str | None,
) -> Hit | None:
    letters = "ceE" if PY_RE.fullmatch(name) else "eE"
    flag = any(
        t.code_first
        and (
            t.unq in ("-c", "-e", "-E")
            or re.fullmatch(r"-[A-Za-z0-9]*[" + letters + r"](['\"].*)?", t.raw, re.S)
        )
        for t in toks
    )
    echo_fed = si > 0 and any(w in ("echo", "printf") for w in seg_words[si - 1])
    if not (flag or pipe_lt2 or echo_fed):
        return None
    parts = [tok_script(t) for t in toks if not t.marker]
    for body in bodies:
        if body.unit is not None:
            parts.append("".join(c.c for c in body.unit.chars if c.k != "cmt"))
    if echo_fed:
        prev = pipe[si - 1]
        ks = command_words(prev)
        if ks:
            parts += [tok_script(t) for t in prev.toks[ks[0] + 1 :] if not t.marker]
    matched, contribs = Script("\n".join(parts), cwd, tmpdir).analyse()
    if not matched:
        return None
    targets: list[tuple[str, bool]] = []
    for kind, text in contribs:
        if kind == "lit":
            targets.append((normalise(text, cwd), is_scratch(text, cwd, tmpdir)))
        elif kind == "scratch":
            targets.append(("<scratch:" + text + ">", True))
        else:  # a target expression that yields nothing: not exempt, names no target
            targets.append(("<nothing:" + text + ">", False))
    return Hit(f"{name} (row 4)", targets)


# ---------------------------------------------------------------- decision

MARKER = "#ZIKARON-FORCE"
OVERRIDE_RE = re.compile(r"(^|\s)#ZIKARON-FORCE[ \t]+#Reason:[ \t]*\S+[ \t]+\S+")


def collect(unit: Unit, units: list[Unit]) -> None:
    unit.chars = annotate(unit)
    parse_seq(unit.chars, unit.pipelines)
    units.append(unit)
    for body in unit.bodies:
        if body.scanned and body.unit is not None:
            collect(body.unit, units)


def override_state(top: Unit, command: str) -> tuple[str, bool]:
    """('valid'|'invalid'|'none', marker-only-in-content)."""
    comments: list[str] = []
    cur: list[str] = []
    visible: list[str] = []
    for c in top.chars:
        visible.append("\0" if c.k in ("str", "q") else c.c)
        if c.k == "cmt":
            cur.append(c.c)
        elif c.c == "\n":
            if cur:
                comments.append("".join(cur))
            cur = []
    if cur:
        comments.append("".join(cur))
    for cm in comments:
        for m in OVERRIDE_RE.finditer(cm):
            reason = cm[cm.index("#Reason:", m.start()) + len("#Reason:") :]
            if len(re.sub(r"<[^>]*>", " ", reason).split()) >= 2:
                return "valid", False
    if MARKER in "".join(visible):
        return "invalid", False
    return "none", MARKER in command


def decide(command: str, cwd: str = CWD, tmpdir: str | None = None) -> dict:
    top = delimit(command.split("\n"))
    units: list[Unit] = []
    collect(top, units)
    hits = [h for u in units for p in u.pipelines for h in eval_pipeline(p, cwd, tmpdir)]
    denying = [h for h in hits if not h.exempt]
    base_out = {"forms": [(h.form, h.targets) for h in hits]}
    if not denying:
        return {"decision": "silent", **base_out}
    state, placement = override_state(top, command)
    if state == "valid":
        return {"decision": "ack", **base_out}
    first = denying[0]
    return {
        "decision": "deny",
        "invalid_marker": state == "invalid",
        "placement": placement,
        "form": first.form,
        "targets": [t for t, s in first.targets if not s],
        "all_denying": [(h.form, [t for t, s in h.targets if not s]) for h in denying],
        **base_out,
    }


# ---------------------------------------------------------------- §8 extraction

SPAN_RE = re.compile(r"``\s?(.+?)\s?``|`([^`]*)`")


def pieces(item: str) -> list[tuple[str, str]]:
    out = []
    pos = 0
    for m in SPAN_RE.finditer(item):
        if m.start() > pos:
            out.append(("prose", item[pos : m.start()]))
        out.append(("span", (m.group(1) if m.group(1) is not None else m.group(2))))
        pos = m.end()
    if pos < len(item):
        out.append(("prose", item[pos:]))
    return out


def split_outside_ticks(s: str, sep: str) -> list[str]:
    res = []
    cur = []
    i = 0
    tick = False
    while i < len(s):
        if s[i] == "`":
            tick = not tick
        if not tick and s.startswith(sep, i):
            res.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(s[i])
        i += 1
    res.append("".join(cur))
    return res


def wrap_py(snippet: str) -> str:
    return f"python3 -c '{snippet}'" if '"' in snippet else f'python3 -c "{snippet}"'


@dataclass
class Case:
    row: int
    item: str
    command: str | None
    expected: str
    cwd: str = CWD
    skip: str = ""


def extract() -> list[Case]:
    text = DOC.read_text().split("\n")
    start = next(i for i, ln in enumerate(text) if ln.startswith("## 8."))
    cases: list[Case] = []
    prev_row_cmds: list[str] = []
    for lineno in range(start, len(text)):
        ln = text[lineno]
        if not ln.startswith("| ") or ln.startswith(("| Command", "|---")):
            continue
        cells = re.split(r"(?<!\\)\|", ln)
        cell1, expected = cells[1].strip(), cells[2].strip()
        each_inside = False
        tail = ' — each inside `python3 -c "…"`'
        if cell1.endswith(tail):
            cell1 = cell1[: -len(tail)]
            each_inside = True
        row_cmds: list[str] = []
        for raw_item in split_outside_ticks(cell1, " · "):
            item = raw_item.strip().replace("\\|", "|")
            case = Case(lineno + 1, item, None, expected)
            cmd = build(item, row_cmds, prev_row_cmds, case)
            if cmd is not None and each_inside:
                cmd = wrap_py(cmd)
            case.command = cmd
            if cmd is None and not case.skip:
                case.skip = "could not turn the item's prose into a literal command"
            cases.append(case)
            if cmd is not None:
                row_cmds.append(cmd)
        prev_row_cmds = row_cmds
    return cases


def build(item: str, row_cmds: list[str], prev_row: list[str], case: Case) -> str | None:
    ps = pieces(item)
    spans = [p for k, p in ps if k == "span"]
    prose = " ".join(p.strip() for k, p in ps if k == "prose").strip()
    if item.startswith("a relative target that"):
        case.cwd = "/tmp/w"
        return "sed -i 's/a/b/' x"
    if item.startswith("the same ending"):
        lines = prev_row[-1].split("\n")
        lines[-1] = "f"
        return "\n".join(lines)
    if item.startswith("the same five-line"):
        return prev_row[0].replace("Path('CLAUDE.md')", "Path('/tmp/x')")
    if item.startswith("the same with"):
        lines = prev_row[0].split("\n")
        lines[-1] = spans[0]
        return "\n".join(lines)
    if prose.endswith("(same body)"):
        body = row_cmds[-1].split("\n")[1:] if row_cmds else []
        return "\n".join([spans[0], *body])
    m = re.search(r"inside$", ps[-2][1].strip()) if len(ps) >= 2 and ps[-2][0] == "prose" else None
    if m and ps[-1] == ("span", 'python3 -c "…"'):
        return wrap_py(spans[0])
    if spans and spans[0].startswith("… #ZIKARON-FORCE"):
        return "sed -i 's/a/b/' f" + spans[0][1:]
    if spans and spans[0].startswith("… #Reason:"):
        return "sed -i 's/a/b/' f #ZIKARON-FORCE" + spans[0][1:]
    leftover = prose.replace("*probe*:", "")
    leftover = re.sub(r"/|\ba line quoting\b|\ba line\b", " ", leftover).strip()
    if leftover:
        case.skip = f"unrecognised prose: {leftover!r}"
        return None
    return "\n".join(spans)


def per_item_naming(exp: str, command: str) -> tuple[list[str], bool] | None:
    """A cell like "the triple-quoted row names `f`, the `` `${d}/x` `` row names `{d}/x` …
    and the others name no literal": what this item must name, or that it names no literal."""
    if "the others name no literal" not in exp:
        return None
    for selector, name in re.findall(r"the (.+?) row names `([^`]+)`", exp):
        sel = selector.strip()
        hit = '"""' in command if sel == "triple-quoted" else sel.strip("` ") in command
        if hit:
            return [name], False
    return [], True


def expected_of(exp: str, command: str = "") -> dict:
    word = re.match(r"\*?(\w+)", exp)
    naming = re.findall(r"naming `([^`]+)`", exp)
    no_literal = "naming no literal" in exp or "naming nothing" in exp
    per_item = per_item_naming(exp, command)
    if per_item is not None:
        naming, no_literal = per_item
    return {
        "decision": word.group(1).lower() if word else "?",
        "invalid": "invalid" in exp,
        "placement": "placement" in exp,
        "naming": naming,
        "naming_form": re.findall(r"naming the `(\w+)` form", exp),
        "no_literal": no_literal,
        "authored": "naming the authored target" in exp,
    }


def named_from_literals(target: str, command: str, cwd: str) -> bool:
    """A non-scratch path target whose components all appear in the command's text."""
    if target.startswith("<"):
        return False
    rel = target[len(cwd) + 1 :] if target.startswith(cwd + "/") else target
    return all(part in command for part in rel.strip("/").split("/") if part)


def check(case: Case, got: dict) -> list[str]:
    ex = expected_of(case.expected, case.command or "")
    probs = []
    if got["decision"] != ex["decision"]:
        return [f"decision: expected {ex['decision']}, got {got['decision']}"]
    if got["decision"] != "deny":
        return []
    if ex["invalid"] != got["invalid_marker"]:
        probs.append(f"invalid-marker: expected {ex['invalid']}, got {got['invalid_marker']}")
    if ex["placement"] and not got["placement"]:
        probs.append("placement clause expected, not produced")
    for n in ex["naming"]:
        want = normalise(n, case.cwd)
        if want not in got["targets"]:
            probs.append(f"expected first denying form to name {want}, got {got['targets']}")
    for fname in ex["naming_form"]:
        if not got["form"].startswith(fname):
            probs.append(f"expected the {fname} form named, got {got['form']}")
    if ex["no_literal"] and any(not t.startswith("<") for t in got["targets"]):
        probs.append(f"expected no literal named, got {got['targets']}")
    if ex["authored"] and not any(
        named_from_literals(t, case.command or "", case.cwd) for t in got["targets"]
    ):
        probs.append(
            f"expected an authored target from the command's literals, got {got['targets']}"
        )
    return probs


def main() -> int:
    cases = extract()
    rows = {c.row for c in cases}
    passed, failed, skipped = [], [], []
    for case in cases:
        if case.command is None:
            skipped.append(case)
            continue
        got = decide(case.command, cwd=case.cwd)
        probs = check(case, got)
        (failed if probs else passed).append((case, got, probs))
    print(
        f"rows {len(rows)}  items {len(cases)}  passed {len(passed)}  failed {len(failed)}  ",
        end="",
    )
    print(f"skipped {len(skipped)}")
    for case, got, probs in failed:
        print(f"\nFAIL line {case.row}: {case.command!r}")
        print(f"  expected: {case.expected}")
        for p in probs:
            print(f"  - {p}")
        print(f"  got: {got['decision']} forms={got['forms']}")
    for case in skipped:
        print(f"\nSKIP line {case.row}: {case.item!r}: {case.skip}")
    print("\nAMBIGUITIES (reading picked):")
    for a in AMBIGUITIES:
        print(f"  - {a}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
