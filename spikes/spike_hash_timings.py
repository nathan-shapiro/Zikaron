"""Timing harness behind design/knowledge-index.md §5.1.

Run from inside a git repository:  python spikes/spike_hash_timings.py
Reports the cost of every change-detection approach considered, over that repo's tracked files.
Warm-cache figures; run twice and take the second. Cold-cache both hashing arms are I/O bound
and the differences between them largely vanish.
"""
import hashlib, subprocess, sys, time

def best(fn, reps=5):
    return min((lambda s=time.perf_counter(): (fn(), time.perf_counter() - s)[1])() for _ in range(reps)) * 1000

def main() -> int:
    files = subprocess.run("git ls-files -z", shell=True, capture_output=True).stdout.split(b"\0")[:-1]
    if not files:
        print("not a git repository, or no tracked files", file=sys.stderr)
        return 1
    total = sum(len(open(f, "rb").read()) for f in files)
    nul, lines = b"\0".join(files) + b"\0", b"\n".join(files) + b"\n"
    sh = lambda c, i=None: subprocess.run(c, shell=True, input=i, capture_output=True)
    print(f"{len(files)} tracked files, {total/1048576:.1f} MB, warm cache\n")
    rows = [
        ("git ls-files -s (precomputed, no reads)", lambda: sh("git ls-files -s")),
        ("git status --porcelain", lambda: sh("git status --porcelain")),
        ("sha1sum, batched via xargs", lambda: sh("xargs -0 sha1sum", nul)),
        ("python hashlib.sha1", lambda: [hashlib.sha1(open(f, "rb").read()) for f in files]),
        ("git hash-object --stdin-paths --no-filters", lambda: sh("git hash-object --stdin-paths --no-filters", lines)),
        ("python hashlib.sha256", lambda: [hashlib.sha256(open(f, "rb").read()) for f in files]),
        ("git hash-object --stdin-paths (filters on)", lambda: sh("git hash-object --stdin-paths", lines)),
    ]
    for label, fn in rows:
        print(f"  {label:<44} {best(fn, 3):>7.1f} ms")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
