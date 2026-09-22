# GitHub Actions macOS runners, `timeout`, and uv — for M28's CI workflow

**Brief.** M28 adds a GitHub Actions workflow running `./check.sh` on Linux (3.12/3.13/3.14) and,
advisory-only, on arm64 macOS for 3.12. Three questions: (1) which macOS runner labels exist today
and which are arm64/free on public repos; (2) does the macOS runner image ship GNU `timeout`
(our gate wraps pytest in `timeout 600 …`, and macOS base userland is BSD with no `timeout(1)`);
(3) does `astral-sh/setup-uv` / `uv python install` work on arm64 macOS for 3.12/3.13/3.14. Date of
research: 2026-09-21. Where a fact is time-sensitive (label meanings shift), that is flagged
explicitly — this area moves on GitHub's own release cadence, not ours.

## Method

Searched GitHub's own docs (`docs.github.com`), GitHub's changelog (`github.blog/changelog`), and
the `actions/runner-images` repository directly (via `raw.githubusercontent.com` and the GitHub
blob viewer) for the current macOS image readme. Cross-checked uv's own platform-support and
Python-install documentation. All quotes below are paraphrased through a fetch tool rather than
copied verbatim in full (this project's ~30-word verbatim limit), but every claim is tied to a
specific page. No secondary blog/aggregator claim is used as the sole source for anything
load-bearing; aggregator sites (`cicdpipelinecost.com`, `dev.to`, etc.) are cited only where they
corroborate a GitHub-docs-derived figure, never in place of one.

## Q1 — Runner labels, architecture, cost

**Current label set** (confirmed by listing `actions/runner-images/images/macos/` directory
contents directly, 2026-09-21): `macos-14`, `macos-14-arm64`, `macos-15`, `macos-15-arm64`,
`macos-26`, `macos-26-arm64`, `xcode-27-arm64`. **`macos-13` readmes are gone from the directory**
— consistent with GitHub's own changelog post "[GitHub Actions: macOS 13 runner image is closing
down](https://github.blog/changelog/2025-09-19-github-actions-macos-13-runner-image-is-closing-down/)"
(2025-09-19), i.e. macOS 13 was sunset roughly a year before this research date and should not be
targeted by a new workflow.

**Per GitHub's own "Supported runners and hardware resources" reference**
(`docs.github.com/en/actions/reference/runners/github-hosted-runners`, fetched 2026-09-21):
- `macos-latest`, `macos-14`, `macos-15`, `macos-26` are **ARM64 (Apple M-series)**, 3 vCPU / 7 GB
  RAM, standard (free-tier-eligible) runners.
- `macos-15-intel`, `macos-26-intel` are **x64/Intel**, 4 vCPU / 14 GB RAM.
- `xcode-27-arm64` is listed as a **public-preview** ARM64 label.
- The page states standard GitHub-hosted runner minutes are **free and unlimited on public
  repositories** — this is the load-bearing sentence for M28, and it is corroborated independently
  by GitHub's billing docs (below) rather than resting on one page alone.
- A **separate** changelog post ([GitHub Actions: Upcoming image migrations, 2026-05-14](https://github.blog/changelog/2026-05-14-github-actions-upcoming-image-migrations/))
  gives the `macos-26` label set as `macos-26` (arm64 standard), `macos-26-intel` (x64 standard),
  `macos-26-large` (x64 large), `macos-26-xlarge` (arm64 large) — so an `-xlarge` variant exists for
  arm64 but is a **larger runner**, which GitHub's docs state explicitly are **not free for public
  repositories** even though standard runners are. Do not reach for `-xlarge` casually.

**`macos-latest` — what it resolves to, and why the label is unstable across time.** As of this
research date, `macos-latest` = **macOS 26** (arm64, 3 vCPU/7 GB). This is a *recent* change, not
a durable fact:
- [GitHub Actions: Upcoming image migrations](https://github.blog/changelog/2026-05-14-github-actions-upcoming-image-migrations/)
  (2026-05-14): the `macos-latest` label migration "will begin June 15 and take 30 days to
  complete… will point to the macOS 26 image instead of macOS 15."
- [macos-26 is now generally available for GitHub-hosted runners](https://github.blog/changelog/2026-02-26-macos-26-is-now-generally-available-for-github-hosted-runners/)
  (2026-02-26) confirms macOS 26 GA and that it runs natively on Apple Silicon.
- An open runner-images issue, "[macOS] macos-latest label will use macos-26 in June 2026" (#14167),
  corroborates the same date from the maintainers' side.
- **So: before 2026-06-15, `macos-latest` meant macOS 15. From roughly 2026-07-15 onward
  (30-day rollout complete), it means macOS 26.** Today (2026-09-21) it is macOS 26.

**So-what for our workflow**: **name `macos-15` explicitly rather than `macos-latest`.** This is
exactly the "a label whose meaning shifts under us" risk the brief called out, and it has *already*
shifted once this year on GitHub's own schedule, with no action on our part. `macos-15` (not
`-arm64` suffixed — the bare `macos-15` label is itself the arm64 standard runner; `-intel` is the
Intel variant) is the concrete, non-drifting choice for M28's advisory job. If M28 later wants to
track "whatever GitHub currently calls default," `macos-latest` is available but must be re-verified
before use, on this record, not assumed stable.

**Billing multiplier.** Per GitHub's own reference table (`docs.github.com/en/billing/reference/actions-runner-pricing`,
fetched 2026-09-21): Linux 2-core standard runner $0.006/min, Windows 2-core $0.010/min, **macOS
3-core/4-core $0.062/min** — roughly **10× Linux** per minute, consistent with the commonly-quoted
"macOS runners consume included minutes at 10× the Linux rate" framing found on GitHub's billing
docs and corroborated by third-party cost calculators (not the basis for the number, just
consistent with it).
**Public-repo exemption**: GitHub's billing docs state standard GitHub-hosted runner usage,
including macOS, is **free on public repositories on every plan** — the multiplier only bites
private-repository included-minute pools. **Larger runners (`-large`/`-xlarge`) are billed even on
public repositories** — an explicit carve-out in GitHub's own docs, and the reason M28 should stick
to the bare `macos-15` label rather than any `-large`/`-xlarge` variant.

**So-what**: since M28's repo will be public (per the M28 decision table), the macOS advisory job
costs nothing in GitHub Actions minutes, on the standard `macos-15` label, indefinitely — as long as
`-large`/`-xlarge` is never used.

## Q2 — Does the macOS runner image ship GNU `timeout`?

**No.** Directly searched the raw markdown of
`actions/runner-images/main/images/macos/macos-15-arm64-Readme.md` (fetched via
`raw.githubusercontent.com`, 2026-09-21) for the strings `coreutils`, `timeout`, `gtimeout`: **zero
matches for all three**, and the "Homebrew"-related lines that do appear are all about *other*
Homebrew-installed formulas (Clang/LLVM 18.1.8, GCC 13/14/15, GNU Fortran 13/14/15) and Homebrew
itself (`Homebrew 6.0.22`), never `coreutils`. The readme's "Utilities" section is a flat list, not
a table: `7-Zip, aria2, azcopy, bazel, bazelisk, bsdtar, Curl, Git, Git LFS, GitHub CLI, GNU Tar,
GNU Wget, gpg, jq, OpenSSL, Packer, pkgconf, Unxip, yq, zstd, Ninja` (versions omitted here per the
verbatim limit) — **GNU Tar and GNU Wget are present, `coreutils` is not.**

So `coreutils` is **not preinstalled**, and consequently neither `timeout` nor `gtimeout` is on
`PATH` by default on the current arm64 macOS image. This is a direct table read, not an inference
from "BSD userland" — confirmed absent from the actual installed-software readme.

**Canonical remedy**: install Homebrew's `coreutils` in the workflow step and prepend its `gnubin`
directory to `PATH`, e.g.:
```yaml
- run: brew install coreutils
- run: echo "$(brew --prefix coreutils)/libexec/gnubin" >> "$GITHUB_PATH"
```
After that, plain `timeout` resolves to GNU `timeout` for the rest of the job (this is the standard
gnubin convention Homebrew's `coreutils` formula documents — its `caveats` message names exactly
this path). Without the `PATH` prepend, the binary is only reachable as `gtimeout`, which is the
distinction the brief specifically asked about: **it is not simply "run `brew install coreutils`
and get `timeout`"** — the `gnubin` step is required, or the workflow must call `gtimeout`
explicitly instead of patching `check.sh`.

**Cost**: not independently benchmarked here (unverified precisely how many seconds `brew install
coreutils` costs on this runner class today — Homebrew installs on GitHub's macOS images are
generally fast because the formula's dependencies are usually already cached in the image's Homebrew
cellar, but this project has not measured it and should not assert a number it did not take).

**So-what**: M28's macOS job needs an explicit `brew install coreutils` + `gnubin` `PATH` step (or a
`gtimeout` substitution) before `check.sh` can run unmodified; do not assume `timeout` exists.

## Q3 — uv on arm64 macOS

**`astral-sh/setup-uv` / `uv python install` on arm64 macOS**: uv's own platform-support
documentation (`docs.astral.sh/uv/reference/policies/platforms/`) lists **macOS (Apple Silicon) as
a Tier 1 platform** — "guaranteed to work," with continuous building, testing and development.
uv's Python-management docs (`docs.astral.sh/uv/guides/install-python/`,
`docs.astral.sh/uv/concepts/python-versions/`) describe `uv python install` fetching prebuilt
CPython builds from the **python-build-standalone** project, naming builds in the form
`cpython-<version>-macos-aarch64-none`, and state this is independent of Homebrew/pyenv/system
Python (matches this project's own `CLAUDE.md` setup instructions, which already rely on this
mechanism on Linux). **3.14 availability specifically on macOS aarch64 was not directly confirmed
in the fetched pages** — the docs describe the general mechanism and named 3.10–3.13 examples;
python-build-standalone tracks new CPython releases closely, and this project's own `check-matrix.sh`
work (M27) already exercises `uv python install --no-bin 3.12 3.13 3.14` on Linux successfully, but
**the macOS-arm64 3.14 build was not independently checked here and should be treated as
unverified** until the workflow's own first run confirms it (which is exactly what an advisory CI
job is for).

**So-what**: `astral-sh/setup-uv` + `uv python install 3.12` is safe to use in M28's macOS job on
the evidence above; do not assume 3.14 is available on that platform without letting the workflow
itself surface the answer.

## Evidence quality and gaps

- **Solid, primary-sourced**: label list and architecture (GitHub's own runner reference doc,
  cross-checked against the `runner-images` directory listing); `macos-latest`'s current and recent
  past meaning (two independent GitHub changelog posts plus a runner-images issue, all agreeing on
  the same June–July 2026 window); the `coreutils`/`timeout` absence (direct string search of the
  actual readme file, not a snippet or a secondary summary); billing multiplier and public-repo
  exemption (GitHub's own billing/pricing reference pages).
- **Corroborated but not independently re-derived**: the exact dollar figures for private-repo
  overage billing — taken from GitHub's own pricing reference table via a fetch-tool summary, not
  quoted from a saved primary copy; if a dollar figure ever needs to be quoted precisely in a
  workflow's comments, re-fetch `docs.github.com/en/billing/reference/actions-runner-pricing`
  directly rather than trusting this note's paraphrase.
- **Unverified, flagged as such rather than guessed**: (a) exact wall-clock/dollar cost of
  `brew install coreutils` on today's macOS runner image — not measured; (b) whether
  python-build-standalone currently ships a macOS-aarch64 3.14 build — plausible given the Linux
  precedent already exercised in M27, but not confirmed from a fetched uv release table; (c)
  whether the macOS-26 readme (as opposed to macOS-15, which M28 is expected to pin) also lacks
  `coreutils` — not checked, since M28's plan is to pin `macos-15` specifically and macOS-26's
  package list is very unlikely to differ in this respect but was not read.
- **Time-sensitivity flag**: everything under Q1 about `macos-latest` is a snapshot of a rolling
  migration that GitHub explicitly documented as changing on its own schedule (already once this
  year, per the sources above). Anyone re-reading this note after another `macos-latest` migration
  should re-check rather than trust this paragraph's date-qualified claim.

## Follow-up 2026-09-22 — pinned action majors for the M28 workflow

**Brief.** The M28 workflow pins three third-party actions by major version:
`actions/checkout@v5`, `actions/cache@v4`, `astral-sh/setup-uv@v7`. Verify each major against the
action's own repository (releases/tags/README), not memory, since a wrong major fails on the first
real run and the operator cannot test locally before pushing. Also: does `astral-sh/setup-uv` have
a `python-version` input. Research date: 2026-09-22.

**Method, same standard as above.** For each action: fetched the repository's `README.md` (raw,
via `raw.githubusercontent.com`, to get the exact usage snippet rather than a rendered-page
summary), the `/releases` and `/tags` listings, and — for the two cases where the named major
turned out to be stale — the specific `/releases/tag/<name>` page to confirm what that tag
currently resolves to rather than inferring from a changelog summary.

### 1. `actions/checkout` — named `v5`, **wrong**. Current major is `v7`.

**`v5` is real but two majors behind current.** The repository's own README
(`raw.githubusercontent.com/actions/checkout/main/README.md`, fetched 2026-09-22) shows the current
basic-usage snippet as:
```yaml
- uses: actions/checkout@v7
```
`v5` exists as a documented past major (its own README section notes it moved the action onto the
Node 24 runtime, minimum Actions Runner `2.327.1`) but is not what the README tells a new user to
write today. **`v6` sits between them** and changed how `persist-credentials` stores its token (a
separate file under `$RUNNER_TEMP` rather than inside `.git/config`) — not relevant to our usage,
which does not set `persist-credentials`, but named here since a coordinator jumping straight to
`v7` should know `v6` was a real intermediate step, not a skipped number.
**`v7` itself carries a behavior change worth knowing even though M28 does not trigger it**: per
GitHub's own changelog (["Safer pull_request_target defaults for GitHub Actions
checkout"](https://github.blog/changelog/2026-06-18-safer-pull_request_target-defaults-for-github-actions-checkout/),
2026-06-18) and corroborated by the README, `v7` refuses to check out fork PR code by default when
the workflow is triggered by `pull_request_target` or `workflow_run` — a security default, opt-out
via `allow-unsafe-pr-checkout: true`. M28's workflow (a `push`/`pull_request`-triggered gate) is not
in that trigger class, so this is inert for us, but it is the kind of major-version change that
*would* silently break a differently-triggered job, which is exactly the failure shape the
coordinator is trying to pre-empt.
**Runtime note**: `v7` requires Node 24 (inherited from the `v5` bump) and, per the README,
"a minimum Actions Runner version of v2.327.1" — GitHub-hosted runner images are kept current
enough that this is not a practical constraint on `macos-15`/`ubuntu-*`, but would matter on a
self-hosted runner, which M28 does not use.
**Verdict: replace `actions/checkout@v5` with `actions/checkout@v7`.**

### 2. `actions/cache` — named `v4`, **wrong**. Current major is `v6`.

**The repository's own README** (`raw.githubusercontent.com/actions/cache/main/README.md`, fetched
2026-09-22) shows:
```yaml
uses: actions/cache@v6
```
**`v4` is not merely old, it is inside the README's own deprecation warning.** The same README
carries a standing notice: *"We are deprecating some versions of this action. We recommend
upgrading to version `v4` or `v3` as soon as possible before February 1st, 2025 … If you do not
upgrade, all workflow runs using any of the deprecated actions/cache will fail."* Read literally
this notice is about the **legacy cache-service sunset** and names `v4`/`v3` as the *safe* targets
relative to `v1`/`v2` — so `v4` itself is not the deprecated one, `v1`/`v2` are. But the notice's
own cutoff date (2025-02-01) has already passed as of this research date (2026-09-22, over a year
and a half later), and the README's *current* usage example has since moved past `v4` to `v6`
regardless — `v5` added the Node 24 runtime bump (same shape as `checkout`'s `v5`), and `v6` added
read-only cache access on top of that. **So `v4` is not scheduled to fail outright** (it is not in
the pre-2025 legacy-service class the deprecation notice targets), but it is two majors behind the
README's own current guidance and does not carry the Node 24 runtime bump — worth moving off of on
its own terms, separate from the "does the pin exist" question the coordinator asked.
**Verdict: replace `actions/cache@v4` with `actions/cache@v6`.** Not a "will fail" risk the way the
setup-uv pin below is, but a "works today, silently behind, and inside an old warning's blast
radius" one.

### 3. `astral-sh/setup-uv` — named `v7`. **This is the one to worry about, and the coordinator was right to be least sure of it.**

**The current major is `v10`** (latest patch `v10.2.0`, released 2026-09-21 per the repository's own
`/releases` page — one day before this follow-up's research date, so astral ships on a fast cadence
and any number quoted here should be re-checked before it is trusted for long). **The project's own
README does not show a bare major-version pin at all.** Its documented usage snippet
(`raw.githubusercontent.com/astral-sh/setup-uv/main/README.md`, fetched 2026-09-22) is:
```yaml
- name: Install the latest version of uv
  uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0
```
— a full commit **SHA**, with the human-readable version as a trailing comment, not `@v10`. This is
astral's documented convention (SHA-pinning for supply-chain hardening), not merely a stylistic
choice, and it is a real divergence from `actions/checkout`'s and `actions/cache`'s convention of a
GitHub-maintained, continuously-updated floating major tag.

**And that divergence is not cosmetic — it changes whether a bare major tag even resolves, and this
is the finding the coordinator specifically asked to have verified rather than assumed.** Checked
directly:
- `github.com/astral-sh/setup-uv/releases/tag/v10` → **HTTP 404.** There is no floating `v10` tag.
  The `/tags` listing (fetched 2026-09-22) shows only fully-qualified patch tags for the current
  major — `v10.2.0`, `v10.1.0`, `v10.0.1`, `v10.0.0` — with no bare `v10` alongside them.
- `github.com/astral-sh/setup-uv/releases/tag/v7` → **resolves**, but to `Release v7.6.0`, dated
  16 Mar (year not fully confirmed by the fetch, almost certainly 2026 or earlier given `v10.2.0` is
  dated 2026-09-21 and `v7.0.0` itself is dated 7 Oct — i.e. `v7` predates `v10` by roughly a year
  or more of releases). So `astral-sh/setup-uv@v7` **is a real, resolvable tag today** — it will not
  make the workflow fail outright — but it is a **frozen historical major**, last updated at
  `v7.6.0` before the project cut `v8`, not an actively-maintained tracking tag the way
  `actions/checkout@v7` or `actions/cache@v6` are for *their* current majors. Pinning `@v7` here
  means running an action roughly three majors and a year-plus of fixes and features behind current
  — including, per this project's own Q3 findings above, whatever checksum-verification and
  cache-poisoning-hardening changes landed in `v10.0.0` (astral's own release notes describe `v10`
  as "a breaking release … disables the cache by default to protect against cache poisoning for
  certain events").
**So the coordinator's instinct to flag this one as the least certain was correct, and the actual
defect is worse than "wrong major number": `@v7` would not crash the job, it would silently run a
year-old, unmaintained-since-superseded release of the action with none of the intervening security
defaults.** That is a harder failure to notice than a 404, and it is the kind this project's own
`CLAUDE.md` names — a plausible-looking pin that is wrong in a way nothing announces.
**Verdict: do not pin `astral-sh/setup-uv@v7`.** Either follow the project's own documented
convention (pin the current SHA, `bec219d24cd3e171d82865faccec33120bb574f4`, with `# v10.1.0` or the
newer `v10.2.0` as a trailing comment) or, if a floating-tag style is preferred for consistency with
the other two actions' conventions, use a full current patch tag (`@v10.2.0`) — **there is no bare
`@v10` to fall back to**, unlike `checkout`/`cache`.

**`python-version` input: yes, it exists.** Per the same README fetch: the action accepts a
`python-version` input that sets `UV_PYTHON` for the rest of the job, overriding any version found
in `pyproject.toml`, `.python-version`, or an explicit `.tool-versions` file; if neither the input
nor `UV_PYTHON` is set and a `.tool-versions` file is present, the action extracts the Python entry
from it automatically. Not evaluated here for redesign, per the brief — flagged only as existing, so
the coordinator's separate `uv python install` step is a deliberate choice to make, not something
this note is silently overriding.

### Summary table

| Action | Named | Correct? | Current major | Notes |
|---|---|---|---|---|
| `actions/checkout` | `v5` | No | **`v7`** | `v5` real but 2 majors stale; `v7` adds a `pull_request_target`/`workflow_run` fork-checkout security default, inert for M28's trigger |
| `actions/cache` | `v4` | No | **`v6`** | `v4` still resolves and is not in the (already-past) legacy-service-sunset deprecation class, but is 2 majors behind and predates the Node 24 runtime bump |
| `astral-sh/setup-uv` | `v7` | No | **`v10`** (no floating `v10` tag exists — pin a SHA or a full patch tag, e.g. `v10.2.0`) | `v7` resolves but is a **frozen** historical major (last patch `v7.6.0`), not a tracking tag; running it silently skips `v10`'s cache-poisoning-hardening default and everything since |

**None of the three named majors is a hard 404** — all three would technically start a job — which
is worth stating plainly since the brief asked for that framing: `checkout@v5` and `cache@v4` are
merely stale, and `setup-uv@v7` is the dangerous one precisely because it resolves silently to an
old, no-longer-updated release rather than erroring.

## Sources

1. [Supported runners and hardware resources](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) — GitHub Docs, fetched 2026-09-21. Runner label table, arm64/x64 split, vCPU/RAM, public-repo-free statement.
2. [GitHub Actions: Upcoming image migrations](https://github.blog/changelog/2026-05-14-github-actions-upcoming-image-migrations/) — GitHub Changelog, 2026-05-14. `macos-latest` → macOS 26 migration window (June 15–July 15, 2026); macOS-26 label set including `-large`/`-xlarge`.
3. [macos-26 is now generally available for GitHub-hosted runners](https://github.blog/changelog/2026-02-26-macos-26-is-now-generally-available-for-github-hosted-runners/) — GitHub Changelog, 2026-02-26. macOS 26 GA, native Apple Silicon support.
4. [\[macOS\] macos-latest label will use macos-26 in June 2026 · Issue #14167](https://github.com/actions/runner-images/issues/14167) — actions/runner-images, corroborates item 2's date.
5. [GitHub Actions: macOS 13 runner image is closing down](https://github.blog/changelog/2025-09-19-github-actions-macos-13-runner-image-is-closing-down/) — GitHub Changelog, 2025-09-19. macOS 13 sunset.
6. [actions/runner-images — images/macos directory listing](https://github.com/actions/runner-images/tree/main/images/macos) — fetched 2026-09-21. Confirms current readme files: `macos-14`, `macos-14-arm64`, `macos-15`, `macos-15-arm64`, `macos-26`, `macos-26-arm64`, `xcode-27-arm64`; no `macos-13-*`.
7. [macos-15-arm64-Readme.md, raw](https://raw.githubusercontent.com/actions/runner-images/main/images/macos/macos-15-arm64-Readme.md) — fetched 2026-09-21. Direct search for `coreutils`/`timeout`/`gtimeout` (all absent) and the full "Utilities" list.
8. [Actions runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing) — GitHub Docs, fetched 2026-09-21. Per-minute rates: Linux $0.006, Windows $0.010, macOS $0.062; "larger runners are not free for public repositories."
9. [About billing for GitHub Actions](https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions) — GitHub Docs, fetched 2026-09-21. Standard-runner public-repo-free statement; 10× macOS multiplier framing.
10. [uv — Platform support](https://docs.astral.sh/uv/reference/policies/platforms/) — Astral Docs. macOS (Apple Silicon) listed Tier 1.
11. [uv — Installing and managing Python](https://docs.astral.sh/uv/guides/install-python/) and [uv — Python versions](https://docs.astral.sh/uv/concepts/python-versions/) — Astral Docs. python-build-standalone mechanism, `cpython-<ver>-macos-aarch64-none` naming, isolation from system/Homebrew/pyenv Python.
12. [actions/checkout — README.md, raw](https://raw.githubusercontent.com/actions/checkout/main/README.md) — fetched 2026-09-22. Current usage snippet (`@v7`), `v5`/`v6`/`v7` change notes.
13. [actions/checkout — tags](https://github.com/actions/checkout/tags) — fetched 2026-09-22. Confirms `v4`/`v5`/`v6`/`v7` all present as maintained branches.
14. ["Safer pull_request_target defaults for GitHub Actions checkout"](https://github.blog/changelog/2026-06-18-safer-pull_request_target-defaults-for-github-actions-checkout/) — GitHub Changelog, 2026-06-18. `v7`'s fork-PR-checkout security default.
15. [actions/checkout — release v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) — fetched 2026-09-22.
16. [actions/cache — README.md, raw](https://raw.githubusercontent.com/actions/cache/main/README.md) — fetched 2026-09-22. Current usage snippet (`@v6`), deprecation-notice text and its 2025-02-01 date.
17. [actions/cache — releases](https://github.com/actions/cache/releases) — fetched 2026-09-22. `v4`/`v5`/`v6` version history, Node runtime notes per major.
18. [astral-sh/setup-uv — README.md, raw](https://raw.githubusercontent.com/astral-sh/setup-uv/main/README.md) — fetched 2026-09-22. Current usage snippet (SHA-pinned, `# v10.1.0` comment), `python-version` input documentation.
19. [astral-sh/setup-uv — releases](https://github.com/astral-sh/setup-uv/releases) and [releases/latest](https://github.com/astral-sh/setup-uv/releases/latest) — fetched 2026-09-22. Latest tag `v10.2.0`, dated 2026-09-21; `v10` breaking-release cache-poisoning-hardening note.
20. [astral-sh/setup-uv — tags](https://github.com/astral-sh/setup-uv/tags) — fetched 2026-09-22. Confirms no bare `v10` tag exists, only patch tags (`v10.2.0`, `v10.1.0`, `v10.0.1`, `v10.0.0`).
21. [astral-sh/setup-uv — release v7.0.0](https://github.com/astral-sh/setup-uv/releases/tag/v7.0.0) and [tag/v7](https://github.com/astral-sh/setup-uv/releases/tag/v7) — fetched 2026-09-22. `v7` exists, frozen at `v7.6.0`, not updated past that patch.
22. [pydevtools — "How to upgrade setup-uv in GitHub Actions" (v7→v8)](https://pydevtools.com/handbook/how-to/how-to-upgrade-setup-uv-from-v7-to-v8/) — third-party, corroboration only that `v7`→`v8` was a real past major transition, not relied on for any figure quoted above.
