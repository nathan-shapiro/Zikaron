# onnxruntime macOS wheel availability — the exact cutoff, current shape, and fastembed's exposure

**Brief.** M28's normative platform decision ("Linux + macOS arm64, Intel Macs out") justifies
itself with "`onnxruntime` stopped publishing macOS x86_64 wheels (reported at 1.23.2)" — a number
quoted from a secondary report inside our own corpus, never read from PyPI. This note verifies the
exact cutoff, the current (2026-09-21) wheel matrix, and whether Zikaron's pinned `fastembed==0.8.0`
actually forces an Intel Mac onto a post-cutoff `onnxruntime`.

**Bottom line up front**: the "1.23.2 last, then dropped" claim is **confirmed**, but "not ours to
fix" is **weaker than the brief states for Python ≤3.13**: `fastembed==0.8.0`'s own dependency range
does not exclude the last x86_64-capable release, so pip's resolver can and will fall back to it on
an Intel Mac running cp310–cp313. It only becomes unfixable at cp314, where fastembed forces
`onnxruntime>=1.24.2`, a range with no macOS x86_64 wheel at all.

## Method

Read PyPI's release history and per-version file listings for the `onnxruntime` project directly
(project page, `/#files` pages, and the JSON API at `pypi.org/pypi/onnxruntime/<version>/json`),
cross-checked against GitHub's release-notes page for the version that changed behaviour. Read
`fastembed`'s `pyproject.toml` at the `v0.8.0` tag on GitHub for its `onnxruntime` constraint.
Today's date is 2026-09-21; PyPI's history shows `onnxruntime` 1.30.0 released **2026-09-10**, eleven
days before this note, so "latest" below is current as of the brief.

One methodological caveat: WebFetch's summarizing model sometimes returned garbled or cached-looking
content on rendered `/project/<pkg>/<version>/#files` pages (one pass, since discarded, produced
release dates and version numbers inconsistent with a second pass on the same URL). Every number
quoted below was **cross-checked against the JSON API** (`pypi.org/pypi/<pkg>/<version>/json`),
which returns literal `urls[].filename` values and is not subject to that rendering flakiness. Where
only the rendered page could be reached, that is noted.

## Q1 — the exact cutoff

**Last release with a macOS x86_64 wheel: `onnxruntime` 1.23.2**, released 2025-10-22 per PyPI's
version history. Confirmed via `pypi.org/project/onnxruntime/1.23.2/#files`, which lists, for every
CPython tag 3.10–3.13:
- `onnxruntime-1.23.2-cp31{0,1,2,3}-cp31{0,1,2,3}-macosx_13_0_x86_64.whl`
- `onnxruntime-1.23.2-cp31{0,1,2,3}-cp31{0,1,2,3}-macosx_13_0_arm64.whl`
- (cp313 additionally ships a `cp313t` free-threaded variant, Linux/Windows only, no macOS)

So 1.23.2's macOS wheels are split arm64/x86_64 (not universal2), tagged `macosx_13_0` (macOS Ventura
13.0 as the deployment target), covering cp310 through cp313.

**First release that dropped it: `onnxruntime` 1.24.1`, released 2026-02-05.** There is **no 1.24.0**
on PyPI — `pypi.org/pypi/onnxruntime/1.24.0/json` returns a plain HTTP 404, so the project went
1.23.2 → 1.24.1 directly (1.24.0 appears to have been an internal/skipped tag; I could not find a
GitHub release, a yank notice, or any other record of it, and did not chase this further since it is
immaterial to the cutoff question).

**The drop was announced**, in 1.24.1's own GitHub release notes
(`github.com/microsoft/onnxruntime/releases/tag/v1.24.1`, dated 2026-02-06 per that page — one day
after the PyPI date, consistent with a PyPI upload preceding the GitHub release publish):

> "x86_64 binaries for macOS/iOS are no longer provided and minimum macOS is raised to 14.0"

The same notes record two other relevant platform moves in the same release: "Python 3.10 wheels
are no longer published" and "Python 3.14 support added" (plus free-threaded 3.13t/3.14t on Linux).
So 1.24.1 is a triple platform-matrix shift: drop macOS x86_64, drop cp310, add cp314 — all in one
release, which is why a naive "does the newest onnxruntime support X" check can look like several
unrelated regressions when it is one version bump.

Confirmed the drop is not a one-release blip: `pypi.org/pypi/onnxruntime/1.24.2/json` (2026-02-19
per history) lists only `macosx_14_0_arm64` wheels for cp311–cp314, no `x86_64` macOS entry at all.

**Universal2 wheels: existed once, long before the cutoff, and are irrelevant to it.**
`onnxruntime` 1.12.0 (2022) shipped `onnxruntime-1.12.0-cp310-cp310-macosx_10_15_universal2.whl`
alongside separate `cp37`/`cp38`/`cp39` x86_64-only wheels (verified via
`pypi.org/pypi/onnxruntime/1.12.0/json`) — a transitional single cp310 universal2 build while
Apple Silicon support was new. By the time of the cutoff (1.23.2, five years later) the project had
long since moved to separate `macosx_13_0_x86_64` / `macosx_13_0_arm64` wheels per CPython tag, and
no universal2 wheel exists in any version I checked between 1.12.0 and 1.30.0. So there is no
universal2 escape hatch for an Intel Mac on any recent release — the split-by-architecture wheel is
what got dropped, not merged.

## Q2 — the current (1.30.0) shape

`onnxruntime` 1.30.0, released 2026-09-10 (11 days before this note), is the latest release.
Verified via `pypi.org/project/onnxruntime/1.30.0/#files`:

| tag | macOS | Linux | Windows |
|---|---|---|---|
| cp311 | `macosx_14_0_arm64` only | `manylinux_2_28_{x86_64,aarch64}` | `win_amd64`, `win_arm64` |
| cp312 | `macosx_14_0_arm64` only | `manylinux_2_28_{x86_64,aarch64}` | `win_amd64`, `win_arm64` |
| cp313 (+ cp313t) | `macosx_14_0_arm64` only | `manylinux_2_28_{x86_64,aarch64}` (both regular and free-threaded `t`) | `win_amd64`, `win_arm64` |
| cp314 (+ cp314t) | `macosx_14_0_arm64` only | `manylinux_2_28_{x86_64,aarch64}` (both regular and free-threaded `t`) | `win_amd64`, `win_arm64` |

No cp310 wheel exists at all (dropped at 1.24.1, per the release notes above) — the earliest tag on
1.30.0 is cp311.

**Answering the specific question**: **cp314 macOS arm64 wheels do exist**
(`onnxruntime-1.30.0-cp314-cp314-macosx_14_0_arm64.whl`), and so does **cp314 Linux x86_64**
(`onnxruntime-1.30.0-cp314-cp314-manylinux_2_28_x86_64.whl`, plus the `cp314t` free-threaded
variant). So the stated reason for pinning the macOS CI job to 3.12 — "cp314 arm64 wheel
availability is unverified in our corpus" — is now **verified and unfounded as a reason**: the
wheel has existed since at least 1.24.1 (2026-02-05), over seven months before this note. Whatever
else may argue for pinning macOS CI to 3.12, onnxruntime wheel availability for cp314 arm64 is not
one of them, as of today.

## Q3 — does fastembed 0.8.0 actually protect Intel Macs, or expose them?

Read directly from `github.com/qdrant/fastembed`, `pyproject.toml` at tag `v0.8.0`. The
`onnxruntime` constraint is **conditioned on the installing Python version**:

| Python | `onnxruntime` constraint |
|---|---|
| 3.10 | `>=1.17.0,!=1.20.0,<1.24` |
| 3.11–3.12 | `>=1.17.0,!=1.20.0,!=1.24.0,!=1.24.1` |
| 3.13 | `>1.21.0,!=1.24.0,!=1.24.1` |
| 3.14+ | `>=1.24.2` |

**This matters a great deal, and it cuts against the brief's framing for three of Zikaron's four
supported interpreters.** None of the 3.10, 3.11–3.12, or 3.13 rows have an upper bound that
excludes 1.23.2 — they only exclude specific *broken* point releases (1.20.0, 1.24.0, 1.24.1).
**1.23.2 satisfies all three of those ranges and still ships a `macosx_13_0_x86_64` wheel.**

Pip's resolver does not simply grab the newest version satisfying a constraint and fail if that
version lacks a wheel for the target platform — it backtracks through the constraint-satisfying
versions looking for one with an installable distribution. So on Zikaron's supported cp312/cp313 on
an Intel Mac: `fastembed==0.8.0`'s constraint permits 1.23.2, 1.23.2 has an x86_64 wheel, and the
resolver will land on it (there is no *newer* x86_64-macOS wheel to prefer, so 1.23.2 is simply the
newest satisfying candidate for that platform). **An Intel Mac running Zikaron's cp312 install would
successfully `pip install fastembed==0.8.0` today**, landing on `onnxruntime` 1.23.2 rather than
failing outright.

**Where it does become unfixable**: the `3.14+` row requires `onnxruntime>=1.24.2`, and every
release in that range (verified for 1.24.2, and by construction for everything after 1.24.1 per Q1)
ships macOS arm64 only. So on cp314 specifically, fastembed 0.8.0 forces a version with no x86_64
macOS wheel, and there genuinely is no fallback — that row of the brief's justification holds.

**Consequence for the brief's justification, stated precisely.** "Intel Macs are out because
onnxruntime dropped x86_64 wheels, not ours to fix" is **too broad as written**: for the cp312/cp313
Zikaron actually plans to run, the *dependency constraint* does not force the unsupported range —
`fastembed`'s pin is loose enough that an old-but-compatible `onnxruntime` is still resolvable, and
would need to be **actively excluded** (e.g. by Zikaron's own upper-bounding, or by a stricter
`fastembed` release) to make the platform genuinely uninstallable via this path. What *is* true and
unconditional is: (a) that fallback wheel (1.23.2) is nearly a year old and receives no further
security or correctness fixes upstream, since 1.24.x+ superseded it seven months ago; (b) the
project's own stated direction is arm64-only going forward, so any fix here is temporary; and (c) at
cp314 the exclusion is real and immediate, not merely a matter of pinning older. If the operator's
intent is "no supported install path should silently resolve to a year-old, unmaintained
dependency," the platform-exclusion decision is still the right one — but the justification should
say *that*, not "there is no installable wheel," which is only true for cp314.

## Sources

1. [onnxruntime 1.23.2 — files](https://pypi.org/project/onnxruntime/1.23.2/#files) — last release with macOS x86_64 wheels (`macosx_13_0_x86_64`, cp310–cp313), released 2025-10-22 per PyPI history.
2. [onnxruntime 1.24.1 — GitHub release notes](https://github.com/microsoft/onnxruntime/releases/tag/v1.24.1) — "x86_64 binaries for macOS/iOS are no longer provided and minimum macOS is raised to 14.0"; also drops cp310, adds cp314/cp313t/cp314t. Dated 2026-02-06.
3. `pypi.org/pypi/onnxruntime/1.24.0/json` — HTTP 404; no such release exists on PyPI (project went 1.23.2 → 1.24.1 directly).
4. `pypi.org/pypi/onnxruntime/1.24.2/json` — confirms the drop persists: `macosx_14_0_arm64` only, cp311–cp314, released 2026-02-19.
5. [onnxruntime 1.30.0 — files](https://pypi.org/project/onnxruntime/1.30.0/#files) — latest release as of 2026-09-21 (released 2026-09-10); confirms cp311–cp314 all macOS-arm64-only, and confirms cp314 Linux x86_64 (`manylinux_2_28_x86_64`) wheels exist.
6. `pypi.org/pypi/onnxruntime/1.12.0/json` — historical universal2 wheel (`macosx_10_15_universal2`, cp310 only, 2022), confirming universal2 existed once but not near the cutoff and not since.
7. [fastembed `pyproject.toml` at tag v0.8.0](https://github.com/qdrant/fastembed/blob/v0.8.0/pyproject.toml) — per-Python-version `onnxruntime` constraints; the 3.10/3.11–3.12/3.13 rows all permit 1.23.2, the 3.14+ row requires `>=1.24.2` (arm64-only).
8. [onnxruntime PyPI project page — release history](https://pypi.org/project/onnxruntime/#history) — full version/date table used to establish "latest" and to cross-check GitHub release dates.
9. [microsoft/onnxruntime — Releases index](https://github.com/microsoft/onnxruntime/releases) — used to locate individual release-note pages.

## What I could not verify / flagged as open

- Why there is no `1.24.0` on PyPI (skipped tag, internal build, or something else) — immaterial to
  the cutoff question, not chased further.
- Whether the GitHub release-notes date (2026-02-06) vs. the PyPI upload date (2026-02-05) reflects
  a real one-day gap between upload and release-notes publish, or a timezone artifact — immaterial.
- I did not exhaustively check every point release between 1.24.1 and 1.30.0 for macOS x86_64
  wheels (only 1.24.2 and 1.30.0 directly); given the explicit "no longer provided" announcement and
  the confirmed absence at both the first and the latest point checked, I treat the drop as
  continuous rather than re-verifying every intermediate release.
