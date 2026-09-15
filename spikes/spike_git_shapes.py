"""M19 spike B: git plumbing on the repository shapes the walk must handle.

Consumers: design/knowledge-index.md §4.1 (batched `check-ignore`), §4.2 (batched `check-attr`),
§5.2 (the candidate set, the skip rule, the degradation rule, `status` parsing) and §5.6 (the shapes
table). §5.2's `ls-files`/`status` behaviour was measured when the design was written; the two
`--stdin -z` batch calls are **inferred** from documentation, and this harness measures them.

    .venv/bin/python spikes/spike_git_shapes.py

Builds a throwaway fixture tree under $TMPDIR and prints one block per question. Nothing outside
that tree is touched, and no product code is imported.
"""

import os
import shutil
import subprocess
import sys
import tempfile

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "spike",
    "GIT_AUTHOR_EMAIL": "spike@example.invalid",
    "GIT_COMMITTER_NAME": "spike",
    "GIT_COMMITTER_EMAIL": "spike@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",  # no user config leaks into the fixture
    "GIT_CONFIG_SYSTEM": "/dev/null",
}
NEWLINE_NAME = "weird\nname.md"
SPACE_NAME = "a file with spaces.md"


def git(cwd: str, *args: str, stdin: bytes | None = None, env: dict | None = None):
    return subprocess.run(
        ["git", *args], cwd=cwd, input=stdin, capture_output=True, env=env or GIT_ENV
    )


def show(title: str, *lines: str) -> None:
    print(f"\n{title}")
    for line in lines:
        print(f"    {line}")


def nul_fields(blob: bytes) -> list[str]:
    """NUL-terminated records, empties dropped. Wrong for `-z -v`; see `nul_all`."""
    return [f.decode("utf-8", "replace") for f in blob.split(b"\0") if f != b""]


def nul_all(blob: bytes) -> list[str]:
    """NUL-TERMINATED fields, empties preserved: only the tail after the final NUL is dropped."""
    parts = blob.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    return [f.decode("utf-8", "replace") for f in parts]


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


# ======================================================================================
# Fixture tree
# ======================================================================================
root = tempfile.mkdtemp(prefix="zk-spike-b-")
base, sub = os.path.join(root, "base"), os.path.join(root, "sub")

git(root, "init", "-q", "sub")
write(os.path.join(sub, "submodule_file.md"), "content of the submodule\n")
git(sub, "add", "-A")
git(sub, "commit", "-qm", "sub")

git(root, "init", "-q", "base")
write(os.path.join(base, "docs/guide.md"), "the retrieval guide\n")
write(os.path.join(base, "docs/moved.md"), "this file will be renamed\n")
write(os.path.join(base, "src/app.py"), "print('hello')\n")
write(os.path.join(base, SPACE_NAME), "spaces in the name\n")
write(os.path.join(base, NEWLINE_NAME), "newline in the name\n")
write(os.path.join(base, "assets/pic.bin"), "pretend binary\n")
write(os.path.join(base, "assets/notext.dat"), "marked -text\n")
write(os.path.join(base, "assets/notes.auto"), "marked text=auto\n")
write(os.path.join(base, ".gitignore"), "build/\n*.log\n")
write(os.path.join(base, ".gitattributes"), "*.bin binary\n*.dat -text\n*.md text\n*.auto text=auto\n")
os.symlink("docs/guide.md", os.path.join(base, "link_to_guide.md"))
git(base, "add", "-A")
# Force-added despite matching `*.log`: the tracked-but-ignored case §5.2's table calls IN.
write(os.path.join(base, "tracked_but_ignored.log"), "tracked, and matched by .gitignore\n")
git(base, "add", "-f", "tracked_but_ignored.log")
git(base, "commit", "-qm", "base")
git(base, "-c", "protocol.file.allow=always", "submodule", "--quiet", "add", sub, "sub")
git(base, "commit", "-qm", "add submodule")

# Untracked, created AFTER the commit so they stay untracked.
write(os.path.join(base, "build/artifact.txt"), "untracked and ignored by `build/`\n")
write(os.path.join(base, "untracked_dir/one.md"), "untracked file one\n")
write(os.path.join(base, "untracked_dir/two.md"), "untracked file two\n")
write(os.path.join(base, "bad\nname.log"), "untracked, ignored, and newline in the name\n")

print(f"git {git(base, '--version').stdout.decode().strip().split()[-1]}   fixtures: {root}")

# ======================================================================================
print("\n" + "=" * 92)
print("B1. `git check-ignore --stdin -z` — the call §4.1 step 3 makes, inferred until now")
print("=" * 92)

walked = [
    "docs/guide.md",
    "build/artifact.txt",  # untracked, matched by `build/`
    "tracked_but_ignored.log",  # TRACKED, matched by `*.log`
    "untracked_dir/one.md",
    NEWLINE_NAME,
    SPACE_NAME,
]
payload = b"\0".join(p.encode() for p in walked) + b"\0"

r = git(base, "check-ignore", "--stdin", "-z", stdin=payload)
show(
    "B1a  default: which of 6 walked paths come back?",
    f"exit={r.returncode}  stdout={nul_fields(r.stdout)}",
    f"stderr={r.stderr.decode().strip()!r}",
    "-> only IGNORED paths are echoed; the caller subtracts them from its own list",
)

r_ni = git(base, "check-ignore", "--stdin", "-z", "--no-index", stdin=payload)
show(
    "B1b  same call with --no-index (does the DEFAULT consult the index?)",
    f"default : {nul_fields(r.stdout)}",
    f"--no-index: {nul_fields(r_ni.stdout)}",
    "-> if they differ, `check-ignore` already implements §4.1's 'never affects tracked files' rule",
)

r_none = git(base, "check-ignore", "--stdin", "-z", stdin=b"docs/guide.md\0")
show(
    "B1c  EXIT CODE when nothing is ignored (the trap)",
    f"exit={r_none.returncode}  stdout={nul_fields(r_none.stdout)!r}  stderr={r_none.stderr.decode().strip()!r}",
    "-> a non-zero exit here does NOT mean the call failed",
)

r_out = git(root, "check-ignore", "--stdin", "-z", stdin=b"anything\0")
show(
    "B1d  EXIT CODE outside a work tree (a real failure)",
    f"exit={r_out.returncode}  stderr={r_out.stderr.decode().strip()!r}",
)

r_dir = git(base, "check-ignore", "--stdin", "-z", stdin=b"build\0build/\0")
show(
    "B1e  can a DIRECTORY be tested, so the walk can prune instead of listing every file?",
    f"exit={r_dir.returncode}  stdout={nul_fields(r_dir.stdout)}",
)

r_nl = git(base, "check-ignore", "--stdin", "-z", "-v", "--non-matching", stdin=payload)
kept, all_fields = nul_fields(r_nl.stdout), nul_all(r_nl.stdout)
show(
    "B1f  -v --non-matching: every path answered, with the deciding rule",
    f"exit={r_nl.returncode}; {len(all_fields)} fields keeping empties, {len(kept)} dropping them,"
    f" for {len(walked)} paths ({len(all_fields) / len(walked):.0f} per record)",
    *[f"  {all_fields[i:i + 4]}" for i in range(0, len(all_fields), 4)],
    "-> non-matching records carry THREE EMPTY fields; a parser that drops empties misaligns",
)

ignored_newline = "bad\nname.log"
r_noz = git(base, "check-ignore", "--stdin", stdin=(ignored_newline + "\n").encode())
r_z = git(base, "check-ignore", "--stdin", "-z", stdin=(ignored_newline + "\0").encode())
show(
    "B1g  an IGNORED path containing a newline, with and without -z",
    f"without -z: exit={r_noz.returncode}  stdout={r_noz.stdout!r}  "
    f"stderr={r_noz.stderr.decode().strip()[:70]!r}",
    f"with    -z: exit={r_z.returncode}  stdout={r_z.stdout!r}",
    "-> without -z the path is split at the newline and answered WRONG, silently",
)

sub_cwd = os.path.join(base, "docs")
r_rel = git(sub_cwd, "check-ignore", "--stdin", "-z", stdin=b"../build/artifact.txt\0build/artifact.txt\0")
r_attr_rel = git(sub_cwd, "check-attr", "--stdin", "-z", "text", stdin=b"guide.md\0docs/guide.md\0")
show(
    "B1h  paths are relative to the PROCESS CWD, not the repository root",
    f"check-ignore from base/docs: {nul_fields(r_rel.stdout)}",
    f"check-attr  from base/docs: {nul_fields(r_attr_rel.stdout)}",
)

# ======================================================================================
print("\n" + "=" * 92)
print("B2. `git check-attr --stdin -z binary text` — the call §4.2 makes")
print("=" * 92)

attr_paths = [
    "assets/pic.bin",
    "assets/notext.dat",
    "assets/notes.auto",
    "docs/guide.md",
    "src/app.py",
    NEWLINE_NAME,
]
attr_payload = b"\0".join(p.encode() for p in attr_paths) + b"\0"
r = git(base, "check-attr", "--stdin", "-z", "binary", "text", stdin=attr_payload)
f = nul_fields(r.stdout)
show(
    "B2a  output framing and values",
    f"exit={r.returncode}, {len(f)} NUL fields for {len(attr_paths)} paths × 2 attrs "
    f"({len(f) / (len(attr_paths) * 2):.0f} per record: path, attr, value)",
    *[f"  {f[i:i + 3]}" for i in range(0, len(f), 3)],
)

r_all = git(base, "check-attr", "--stdin", "-z", "--all", stdin=b"assets/pic.bin\0")
show(
    "B2b  --all on a file marked `binary` (what the macro expands to)",
    f"fields={nul_fields(r_all.stdout)}",
)

r_missing = git(base, "check-attr", "--stdin", "-z", "binary", stdin=b"no/such/file.md\0")
show(
    "B2c  a path that does not exist on disk",
    f"exit={r_missing.returncode}  fields={nul_fields(r_missing.stdout)}  "
    f"stderr={r_missing.stderr.decode().strip()!r}",
)

r_outside = git(root, "check-attr", "--stdin", "-z", "binary", stdin=b"x\0")
show(
    "B2d  outside a work tree",
    f"exit={r_outside.returncode}  stderr={r_outside.stderr.decode().strip()!r}",
)

# uncommitted .gitattributes change: working tree or index?
with open(os.path.join(base, ".gitattributes"), "a") as fh:
    fh.write("*.py binary\n")
r_uncommitted = git(base, "check-attr", "--stdin", "-z", "binary", stdin=b"src/app.py\0")
show(
    "B2e  an UNCOMMITTED .gitattributes edit",
    f"fields={nul_fields(r_uncommitted.stdout)}",
    "-> working-tree .gitattributes wins; an attribute can change with no commit and no file change",
)
git(base, "checkout", "--", ".gitattributes")

# ======================================================================================
print("\n" + "=" * 92)
print("B3. `git ls-files -s` on the shapes of §5.6")
print("=" * 92)

r = git(base, "ls-files", "-s", "-z")
entries = [e.split("\t", 1) for e in nul_fields(r.stdout)]
show("B3a  every entry, mode-first", *[f"{m}  {p}" for m, p in entries])
modes = {m.split()[0] for m, _ in entries}
show(
    "B3b  modes present",
    f"{sorted(modes)}  (160000 = submodule gitlink, 120000 = symlink, 100644/100755 = regular)",
)

r_noz = git(base, "ls-files", "-s")
show(
    "B3c  WITHOUT -z: how unusual paths are rendered",
    *[line for line in r_noz.stdout.decode("utf-8", "replace").splitlines() if '"' in line],
)

# ======================================================================================
print("\n" + "=" * 92)
print("B4. `git status --porcelain -z -uall` — the parsing surface §5.2 calls a correctness surface")
print("=" * 92)

git(base, "mv", "docs/moved.md", "docs/renamed.md")
write(os.path.join(base, "docs/guide.md"), "the retrieval guide, edited\n")
os.unlink(os.path.join(base, "src/app.py"))
write(os.path.join(base, NEWLINE_NAME), "newline in the name, edited\n")
# Edit a TRACKED file inside the checked-out submodule, so the superproject sees it.
write(os.path.join(base, "sub", "submodule_file.md"), "the submodule's tracked file, edited\n")

r = git(base, "status", "--porcelain", "-z", "-uall")
show("B4a  raw NUL fields, in order", *[repr(x) for x in nul_all(r.stdout)])

r_unormal = git(base, "status", "--porcelain", "-z")
show(
    "B4b  the same, with the DEFAULT -unormal (why §5.2 requires -uall)",
    *[repr(x) for x in nul_all(r_unormal.stdout)],
)

r_noz2 = git(base, "status", "--porcelain", "-uall")
show(
    "B4c  WITHOUT -z: quoting under core.quotePath",
    *[line for line in r_noz2.stdout.decode("utf-8", "replace").splitlines() if '"' in line],
)

# ======================================================================================
print("\n" + "=" * 92)
print("B5. Linked worktree, submodule, sparse checkout")
print("=" * 92)

wt = os.path.join(root, "linked-wt")
git(base, "worktree", "add", "-q", "-b", "wtbranch", wt)
dotgit = os.path.join(wt, ".git")
show(
    "B5a  a linked worktree's .git",
    f"isfile={os.path.isfile(dotgit)}  isdir={os.path.isdir(dotgit)}",
    f"contents={open(dotgit).read().strip()!r}",
    f"ls-files works from inside: {len(nul_fields(git(wt, 'ls-files', '-z').stdout))} entries",
)

show(
    "B5b  the submodule directory, as the walk would meet it",
    f"base/sub is a directory on disk: {os.path.isdir(os.path.join(base, 'sub'))}",
    f"base/sub/.git is a file: {os.path.isfile(os.path.join(base, 'sub', '.git'))}",
    "-> §4.1's prune rule must match the NAME .git whether file or directory, in both shapes",
)

sub_listed = [e for e in nul_fields(git(base, "ls-files", "-s", "-z").stdout) if "sub" in e]
sub_status = [f for f in nul_all(git(base, "status", "--porcelain", "-z", "-uall").stdout) if "sub" in f]
show(
    "B5b2 what the SUPERPROJECT says about a file inside the submodule",
    f"ls-files entries mentioning 'sub': {sub_listed}",
    f"status fields mentioning 'sub':   {sub_status}",
    f"the file exists on disk: {os.path.isfile(os.path.join(base, 'sub', 'submodule_file.md'))}",
    "-> the edited file is invisible; only the gitlink is reported, and it names a DIRECTORY",
)

clone = os.path.join(root, "sparse")
git(root, "-c", "protocol.file.allow=always", "clone", "-q", "--no-local", base, clone)
git(clone, "sparse-checkout", "init", "--cone")
git(clone, "sparse-checkout", "set", "docs")
listed = {e.split("\t", 1)[1] for e in nul_fields(git(clone, "ls-files", "-s", "-z").stdout)}
on_disk = {
    os.path.relpath(os.path.join(dirpath, fn), clone)
    for dirpath, dirnames, filenames in os.walk(clone)
    for fn in filenames
    if ".git" not in dirpath.split(os.sep)
}
absent = sorted(listed - on_disk)
st = git(clone, "status", "--porcelain", "-z", "-uall")
show(
    "B5c  sparse checkout: listed by ls-files but ABSENT from disk",
    f"{len(listed)} listed, {len(on_disk)} on disk, {len(absent)} listed-but-absent",
    f"absent: {absent[:5]}",
    f"`git status --porcelain` reports: {nul_fields(st.stdout) or 'NOTHING'}",
)

# ======================================================================================
print("\n" + "=" * 92)
print("B6. The degradation rule of §5.2: a work tree git refuses to read")
print("=" * 92)

dubious = {**GIT_ENV, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
for name, args, stdin in (
    ("rev-parse --is-inside-work-tree", ("rev-parse", "--is-inside-work-tree"), None),
    ("ls-files -s", ("ls-files", "-s"), None),
    ("status --porcelain -z -uall", ("status", "--porcelain", "-z", "-uall"), None),
    ("check-ignore --stdin -z", ("check-ignore", "--stdin", "-z"), b"build/artifact.txt\0"),
    ("check-attr --stdin -z binary", ("check-attr", "--stdin", "-z", "binary"), b"assets/pic.bin\0"),
):
    rr = git(base, *args, stdin=stdin, env=dubious)
    first = rr.stderr.decode().strip().splitlines()[:1]
    show(f"B6  {name}", f"exit={rr.returncode}  stderr={(first[0] if first else '')!r}")

# ======================================================================================
print("\n" + "=" * 92)
print("B7. Case sensitivity (partial — no case-insensitive mount available without root)")
print("=" * 92)

for value in ("false", "true"):
    git(base, "config", "core.ignorecase", value)
    r_ci = git(base, "check-ignore", "--stdin", "-z", stdin=b"BUILD/artifact.txt\0")
    r_ls = git(base, "ls-files", "-z", "--", "DOCS/guide.md")
    show(
        f"B7  core.ignorecase={value}, on a case-SENSITIVE filesystem",
        f"check-ignore('BUILD/artifact.txt') -> exit={r_ci.returncode} {nul_fields(r_ci.stdout)}",
        f"ls-files('DOCS/guide.md')          -> {nul_fields(r_ls.stdout)}",
    )
git(base, "config", "core.ignorecase", "false")
show(
    "B7  what this probe cannot settle",
    "NOT MEASURED: a genuine case-insensitive mount (needs root to create one). §5.6's row is about",
    "OUR byte-exact path matching, a property of our code rather than of git.",
)

print(f"\nfixtures left at {root}  (rm -rf to clean up)")
if "--keep" not in sys.argv:
    shutil.rmtree(root, ignore_errors=True)
    print("removed.")
