# Python distribution and portability for Zikaron

**Status:** research note, not a decision record. Written 2026-09-20 for memory-researcher.

## The brief

Zikaron ships as a Python application installed onto end users' machines (source checkout + `python3.12
-m venv .venv && pip install -e .`, `requires-python = "==3.12.*"`). This note asks: how do comparable
local-first Python developer tools solve the "which Python does the user have" problem, and what
actually breaks in each approach, given Zikaron's specific constraints — a loadable SQLite extension
(`sqlite-vec`) loaded through stdlib `sqlite3.Connection.enable_load_extension`, FTS5 via stdlib
`sqlite3`, a ~200 MB onnxruntime/fastembed dependency, two console-script entry points whose *absolute
paths* get written into a coding agent's config files, latency-sensitive process spawns (~50 ms per
hook invocation), and a first-use model download via `huggingface_hub`.

## Method

Five rounds of web search plus targeted `WebFetch` on primary sources: CPython bug tracker and
`bugs.python.org`/GitHub issues, `python-build-standalone`'s own repo and PRs, `pyenv`/Arch/Fedora/
Debian bug trackers, `uv`'s own docs, `aider`'s own install docs and Paul Gauthier's blog post about
uv, `iscinumpy.dev` (Henry Schreiner, a CPython/packaging authority) on `requires-python` capping, and
vendor docs for `llm`, `marimo`, `harlequin`, `datasette`, MCP/Claude Desktop docs. Where only secondary
sources turned up (some GitHub issue summaries, some blog aggregation), that is flagged. I did not
independently execute any builds or installers; the below is read, not reproduced.

---

## 1. The `enable_load_extension` question

**The mechanism, from CPython's own docs and bug tracker.** The stdlib `sqlite3` module's
`enable_load_extension`/`load_extension` methods only exist if CPython was built with
`--enable-loadable-sqlite-extensions` passed to `configure` — this is a *compile-time* Python-level
gate, layered on top of SQLite's own `SQLITE_ENABLE_LOAD_EXTENSION` compile flag
([docs.python.org/3/library/sqlite3.html](https://docs.python.org/3/library/sqlite3.html);
[bugs.python.org/issue10268](https://bugs.python.org/issue10268), which added the flag in the first
place). If the Python-level gate was never turned on, the *attribute itself* is absent:
`AttributeError: 'sqlite3.Connection' object has no attribute 'enable_load_extension'`. This is a hard
failure with no runtime workaround short of a different interpreter — you cannot `pip install` your way
out of it, because the capability is baked into the `_sqlite3` C extension at Python's own build time.

**Per-distribution answer, each checked against a primary or near-primary source:**

| Distribution | `enable_load_extension` present? | Source / caveat |
|---|---|---|
| **python.org macOS installer** | **Off** historically. python.org's own bug tracker discussion states the flag is not enabled by default "because some platforms (notably macOS) have SQLite libraries which are compiled without this feature" — [bugs.python.org/issue10268](https://bugs.python.org/issue10268). Confirmed independently by [Simon Willison's TIL](https://til.simonwillison.net/sqlite/sqlite-extensions-python-macos), which documents the exact `AttributeError` and recommends switching to Homebrew Python as the fix. |
| **python.org Windows installer** | **Off through at least 2022**, tracked in [python/cpython#95656](https://github.com/python/cpython/issues/95656) ("Enable sqlite extensions in the Windows build"), closed via PR #95662. The issue argued Windows has no reason to withhold it since python.org ships and controls its own bundled SQLite DLL there. **I could not confirm from the issue text alone which CPython release first shipped the fix** — treat as *unconfirmed* which 3.x minor first has it enabled on Windows; verify against a current `python.org` Windows build before relying on it. |
| **Homebrew Python (macOS)** | **On.** Multiple independent sources (Willison's TIL; [pythontutorials.net](https://www.pythontutorials.net/blog/symbol-not-found-sqlite3-enable-load-extension-sqlite-installed-via-homebrew/)) confirm Homebrew's Python is linked against Homebrew's own SQLite build, which has the capability, and is the standard workaround macOS users are pointed to. Caveat, also from Willison: "there is a good chance that when you type `python` that's not the version you will get" — PATH precedence between system Python, pyenv shims, and Homebrew's `python3` is not guaranteed. |
| **Debian/Ubuntu `python3` (APT)** | **On.** No single authoritative changelog entry was found in search, but this is corroborated indirectly: Debian and Ubuntu are the base for the official Docker `python` images (see below), which *are* documented as building with the flag, and no open Debian/Ubuntu bug tracks this as broken the way the Arch and Red Hat trackers below do (which suggests it was resolved long ago, pre-dating most currently searchable bug history). **Treat this row as inferred rather than directly sourced** — I found no Debian changelog entry to cite directly. |
| **Fedora / RHEL** | **On**, and it was a deliberate packaging patch. Red Hat Bugzilla [#1066708](https://bugzilla.redhat.com/show_bug.cgi?id=1066708) (filed Feb 2014, "Python sqlite3 module does not allow the loading of extensions (should be enabled)") and Fedora's own patch file `00193-enable-loading-sqlite-extensions.patch` in [fedora-python/python2-spec](https://github.com/fedora-python/python2-spec/blob/master/00193-enable-loading-sqlite-extensions.patch) show Fedora carries this as an explicit downstream patch against upstream CPython's `setup.py`/build config. |
| **Arch Linux** | **On since Python 3.4.2-2.** Arch bug [FS#43372](https://bugs.archlinux.org/task/43372) shows Python 2 already had it (since 2.7.1-3) and Python 3 was fixed and closed "Implemented" 2015-01-12 in package version 3.4.2-2. |
| **pyenv (source builds)** | **Depends on the host's SQLite dev headers and whether the flag is passed.** [pyenv/pyenv#1702](https://github.com/pyenv/pyenv/issues/1702) is an open feature request asking pyenv to compile with `--enable-loadable-sqlite-extensions` by default; as of that issue it does not automatically pass it, so a `pyenv install` is only as capable as (a) whether pyenv's build definitions add the flag (unconfirmed either way, would need to check `python-build`'s current definitions directly) and (b) whether the host has a SQLite dev package with `SQLITE_ENABLE_LOAD_EXTENSION` available to link against. This is the least predictable path of the ones checked. |
| **conda / conda-forge (Anaconda)** | **Off, historically and apparently still.** [conda/conda#3644](https://github.com/conda/conda/issues/3644) ("sqlite3 in Python 3 should have enable_load_extension") and [ContinuumIO/anaconda-issues#1287](https://github.com/ContinuumIO/anaconda-issues/issues/1287) both report it disabled; one search result additionally reports a **segfault**, not just an `AttributeError`, when `enable_load_extension(True)` is called against some Anaconda builds ([ContinuumIO/anaconda-issues#8606](https://github.com/ContinuumIO/anaconda-issues/issues/8606)) — a sharper failure mode than the clean `AttributeError` elsewhere. **Unconfirmed whether this remains true of current conda-forge `python` feedstock builds**; the issues found are multi-year-old and I did not find a conda-forge feedstock changelog entry confirming a fix or its absence today.
| **python-build-standalone (what `uv python install` downloads)** | **FTS5: yes, confirmed from source.** [astral-sh/python-build-standalone PR #800](https://github.com/astral-sh/python-build-standalone/pull/800) shows the project defines `SQLITE_ENABLE_FTS3`, `SQLITE_ENABLE_FTS4`, `SQLITE_ENABLE_FTS5`, `SQLITE_ENABLE_RTREE`, `SQLITE_ENABLE_GEOPOLY`, `SQLITE_ENABLE_DBSTAT_VTAB` for both its Unix and (as of that PR) Windows builds — this is a source-code confirmation, not a secondary report. **`enable_load_extension` specifically: not directly confirmed either way in what I could fetch.** FTS5-as-a-compiled-in-extension and *loadable* extension support (`--enable-loadable-sqlite-extensions` at the CPython `configure` level) are two different toggles, and I found evidence for the former but not a source-verified statement about the latter for this project. **Mark this unconfirmed** — it is the single most important unresolved fact in this note, since `uv python install` is the path most likely to become Zikaron's actual answer to this whole question, and it needs a direct empirical check (`python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.enable_load_extension"` against a `uv`-downloaded 3.12) before being relied on. |
| **Docker official `python` images** | **On, and this is source-confirmed via the build template**, not just search summary: `docker-library/python`'s [`Dockerfile-linux.template`](https://github.com/docker-library/python/blob/master/Dockerfile-linux.template) passes `--enable-loadable-sqlite-extensions` to CPython's `configure` when building the images from source (these images build CPython themselves against the Debian/apt-installed SQLite dev libs in the build stage, then copy the built interpreter into the runtime layer). |

**FTS5 and SQLite version, where found.** python-build-standalone compiles FTS5 in on all platforms per
PR #800 above. Docker's official images build CPython against whatever `libsqlite3-dev` Debian ships at
build time, which tracks Debian's SQLite version, itself often somewhat behind SQLite upstream compared
to a fresh `python-build-standalone` or Homebrew build. I did **not** find a clean side-by-side table of
"SQLite version linked" across all rows above and did not chase it further — flag as an open gap if the
exact SQLite version turns out to matter (e.g. for a specific FTS5 or `sqlite-vec` compatibility floor).

**Bottom line for section 1.** The failure mode is binary and silent-at-import-time: the attribute is
simply missing, so Zikaron's code needs either (a) a documented hard dependency on an interpreter known
to have the capability (Homebrew on macOS, apt/dnf/pacman on Linux, `uv python install`/Docker
everywhere) with a clear error message rather than a bare `AttributeError` when it's absent, or (b) to
control the interpreter itself (embedding python-build-standalone, per §2g) so this stops being the
user's problem. **The python.org installers (both macOS and, historically, Windows) and conda-forge are
the distributions most likely to fail**; Debian/Ubuntu, Fedora, Arch, Homebrew, and Docker's official
images are the distributions confirmed or plausibly fine.

---

## 2. The approaches

### (a) `uv` — `uv tool install`, `uvx`, `uv python install`, `requires-python`-driven download

**How it works, from uv's own docs
([docs.astral.sh/uv/concepts/python-versions/](https://docs.astral.sh/uv/concepts/python-versions/),
[docs.astral.sh/uv/guides/install-python/](https://docs.astral.sh/uv/guides/install-python/)).** uv
maintains its own registry of Python interpreters, preferring ones it manages itself over system
interpreters. When a project's `requires-python` (or a tool's own declared requirement) isn't satisfied
by any interpreter uv can find on the system, uv **automatically downloads** a matching build from
Astral's `python-build-standalone` project and uses that — this is confirmed in uv's docs language that
it will use "the first Python version that is compatible with the requirement" and falls through to a
managed download when nothing on-system qualifies. `uv tool install` and `uvx` (an alias for `uv tool
run`) both go through this same resolution, so `uvx some-tool` on a machine with no matching Python at
all will silently fetch one first.

**Where they live and relocation.** Downloaded interpreters land in `~/.local/share/uv/python/` on
Linux/macOS or `%LOCALAPPDATA%\uv\python` on Windows by default, overridable via
`UV_PYTHON_INSTALL_DIR`. Because these are `python-build-standalone` builds, they are designed to be
relocatable: uv patches `sysconfig` data (`_sysconfigdata_*.py`) after extraction so the install's
recorded paths match wherever it actually landed, rather than the build machine's original path
(secondary reporting, from a pydevtools/Medium summary rather than uv's own docs — **treat the exact
mechanism as unconfirmed** even though the general relocatability claim is consistent with
python-build-standalone's own stated design goal of being redistributable).

**What the user has to install first.** Just `uv` itself — a single static binary (Rust), typically via
a curl-pipe-sh installer or a package manager. Nothing Python-related is a prerequisite.

**Artefact size / what breaks.** `uv` itself is small (~tens of MB). The downloaded interpreter is a
full CPython build (tens of MB more). Zikaron's actual dependencies (onnxruntime etc.) still install
normally into a venv uv manages — uv changes *interpreter acquisition*, not packaging format, so
`onnxruntime`'s wheel size (~150-200 MB) is unaffected either way. Concrete precedent for this exact
approach: `aider-chat` — see §3.

### (b) `pipx`

**How it works and why it still needs a host Python.** `pipx` installs each CLI tool into its own
isolated venv under `~/.local/pipx/venvs/<tool>`, with a shim placed on `PATH`. Unlike `uv python
install`, **pipx has no interpreter-acquisition step of its own** — it uses whatever Python interpreter
it itself was installed with (or one explicitly passed via `--python`) to create those venvs. So `pipx`
solves *dependency isolation between tools* but does nothing for "the user's system has no Python 3.12
at all" — it inherits exactly the host-Python problem this note is about. This is corroborated by
aider's own docs describing pipx as usable "with python versions 3.9-3.12" (i.e. constrained by whatever
the user already has), contrasted with `uv tool install --python python3.12 aider-chat`, which can fetch
3.12 itself if absent.

### (c) PyInstaller / Nuitka single-file binaries

**PyInstaller + onnxruntime.** PyInstaller's own troubleshooting docs
([pyinstaller.org/en/stable/when-things-go-wrong.html](https://pyinstaller.org/en/stable/when-things-go-wrong.html))
describe the general "hidden import" failure class: PyInstaller's static analysis can't see imports done
via `__import__`, `importlib`, or an extension module's own C-API-level imports — exactly onnxruntime's
shape, since `onnxruntime_pybind11_state` is a compiled extension loading its own further native
dependencies. Concretely reported: [microsoft/onnxruntime#25193](https://github.com/microsoft/onnxruntime/issues/25193),
"DLL Load Failed When Importing onnxruntime_pybind11_state in PyInstaller Packaged Application" — the
standard mitigations found (`--collect-all onnxruntime`, `--hidden-import`, custom hook files) are
workarounds *per onnxruntime release*, not a solved problem; a shape that recurs across onnxruntime
version bumps because the internal module layout isn't guaranteed stable.

**A loadable native SQLite extension inside a PyInstaller/Nuitka bundle is a second, compounding
problem**, not covered directly in what I fetched but following from how both tools work: PyInstaller
bundles a Python interpreter plus your dependencies into an archive that gets unpacked to a temp
directory at runtime (`onefile` mode) or shipped as a directory tree (`onedir` mode); `sqlite-vec`'s
`.so`/`.dylib` would need to be an explicit `--add-binary`/`--add-data` entry with a resolvable runtime
path passed to `load_extension()`, since PyInstaller's import-graph analysis has no way to discover a
path string handed to `sqlite3.Connection.load_extension()` at runtime — that call is invisible to
static analysis the same way a dynamic `importlib` call is. And the **bundled interpreter itself** still
needs to have been built with `--enable-loadable-sqlite-extensions` in the first place (§1) — PyInstaller
bundles *your* interpreter, it doesn't grant new C-API surface to one that lacks it.

**Runtime model download inside a frozen bundle.** No specific problem was found in search beyond the
general PyInstaller caveat that any code path relying on package metadata / `importlib.resources`
lookups at runtime can break inside a frozen bundle if the relevant package's data files weren't
explicitly collected — `huggingface_hub`'s first-use download path is ordinary network I/O plus a
filesystem cache directory, which should work unmodified inside a frozen app as long as the cache
directory resolution itself doesn't depend on something PyInstaller's environment faking breaks (e.g.
`__file__`-relative paths). Not independently verified against `huggingface_hub` specifically —
**unconfirmed**, flagged as a real risk to test rather than assumed fine.

**Nuitka.** Less searched-for material turned up. Nuitka's own release notes mention adding DLL
dependency handling for onnxruntime in its "standalone" mode, and [Nuitka/Nuitka#1740](https://github.com/Nuitka/Nuitka/issues/1740)
documents a user hitting onnxruntime+numpy standalone-build friction. Nuitka's user manual states
standalone-mode extension modules are tied to the exact CPython version/ABI they were built against and
compile only your own code to C — third-party binary wheels containing precompiled native extensions
(onnxruntime, `sqlite-vec`) are *copied in*, not recompiled, so the interpreter-capability question (§1)
and the DLL-discovery question above both still apply.

**Verdict for (c):** feasible in principle for both concerns individually (onnxruntime bundling has a
documented, if fragile, workaround path; native extensions can be shipped as data files with explicit
runtime paths), but the combination — one frozen interpreter that must (i) have loadable-extension
support baked in at its own build time, (ii) correctly resolve onnxruntime's hidden imports across
onnxruntime version bumps, and (iii) find `sqlite-vec`'s `.so`/`.dylib` and `huggingface_hub`'s cache dir
correctly inside a relocated/unpacked bundle — is exactly the kind of interacting-constraints situation
that produces per-release breakage, not a one-time integration cost. No comparable local-first Python
dev tool with a loadable SQLite extension dependency was found shipping via PyInstaller/Nuitka in the
precedent search (§3) — that absence is itself a data point.

### (d) `shiv` / `zipapp`

**Plain `zipapp` (stdlib):** cannot include native C extensions at all — a zipapp is a zip archive
imported via `zipimport`, and CPython cannot `dlopen` a `.so`/`.dylib` from inside a zip. Immediately
disqualified for onnxruntime, `sqlite-vec`, and every other compiled dependency Zikaron has.

**`shiv`:** works around this specifically — per [shiv's own docs](https://shiv.readthedocs.io/) and
corroborating write-ups ([Graham Dumpleton](https://grahamdumpleton.me/posts/2018/10/packaging-modwsgi-into-zipapp-using-shiv/),
a [Python Discourse thread on the general problem](https://discuss.python.org/t/native-extensions-in-zipapps/27321)),
shiv's bootstrap code unpacks the archive's native-extension-bearing packages to a `~/.shiv/` cache
directory on first run and adds that to `sys.path`, so the OS loader can actually `dlopen` them from a
real filesystem path rather than from inside the zip. This solves the *bundling* problem the same way
PyInstaller's `onefile` mode does (extract-then-load), but **shiv still requires a compatible host
Python to execute the zipapp shebang** — it does not bundle an interpreter the way PyInstaller does, so
it does nothing for §1's "does the host Python have loadable-extension support" question, and does
nothing for "does the host have any 3.12 at all." It solves dependency-bundling, not
interpreter-acquisition; the two problems this note treats as orthogonal really are orthogonal in every
approach checked, and shiv is the cleanest illustration of that.

### (e) conda / pixi

**conda-forge:** per §1, historically ships `enable_load_extension` **off**
([conda/conda#3644](https://github.com/conda/conda/issues/3644)), which alone is close to disqualifying
for Zikaron without further mitigation (e.g. installing a separately-built `sqlite` conda package and
forcing `python` to link against it, which is itself the kind of user-side yak-shave this note is trying
to avoid causing). Conda environments are large by construction and typically presented as `environment.yml`
+ `conda`/`mamba install`, which is a heavier ask than a single install command for a CLI dev tool.

**pixi:** per [prefix-dev/pixi](https://github.com/prefix-dev/pixi/) and its docs, pixi is a Rust-based,
project-local wrapper over the conda-forge + PyPI ecosystem with its own global-tool-install mode
("pixi can install global tools... replacing apt, homebrew, and winget," per search summary of pixi's
own materials) explicitly compared to `pipx`/`condax`. It inherits conda-forge's package builds unless
it's pulling a given dependency from PyPI wheels instead — **whether pixi's Python (or the conda-forge
Python it depends on) has loadable-extension support was not independently re-checked and should not be
assumed different from the conda-forge answer above** without verification. Neither conda nor pixi turned
up as the shipping mechanism for any precedent tool checked in §3.

### (f) Docker / container

**How it removes the host-Python dependency:** entirely, for users willing to run Docker. The official
`python` images are confirmed (§1) to have loadable-extension support built in via
`docker-library/python`'s own Dockerfile template, and FTS5 comes along with whatever SQLite version
Debian's `libsqlite3-dev` provides at image-build time. This is the only option in this list that
sidesteps *every* host-OS variable at once (interpreter build flags, package manager quirks, PATH
ambiguity) by construction.

**What breaks / what it costs.** (i) Zikaron's specific integration surface — writing *absolute host
paths* into Claude Code's `settings.local.json` hooks and `.mcp.json` MCP server entries, and spawning a
background service the hook talks to over a Unix domain socket — becomes materially harder across a
container boundary: the coding agent (running on the host) needs a host-visible executable path to
invoke, and a Unix socket used for hook↔service IPC needs to be bind-mounted through consistently, or
the whole IPC design needs to move to a TCP port instead. This is a design-level obstacle, not a
packaging inconvenience — it cuts against three of Zikaron's own architectural decisions (D9's MCP
server + hook delivery, the socket-based RPC choice in `design/architecture.md`, and the requirement for
stable absolute paths in agent config). (ii) requires Docker itself as a prerequisite, which is a much
heavier ask for a "local-first coding-agent tool" than any of the other options — none of the precedent
tools in §3 ship primarily as a container for this reason, as far as this search found. (iii) startup
latency: a container per hook invocation would almost certainly blow the ~50 ms budget; a long-running
container for the background service is more plausible but adds its own lifecycle-management surface
Zikaron doesn't currently have. Docker is the strongest *portability* answer and the weakest fit to
Zikaron's actual integration shape.

### (g) Embedding python-build-standalone directly in your own installer

**What this means concretely:** Zikaron's own installer downloads a `python-build-standalone` release
for the user's platform (the same artefact `uv python install` fetches) into a Zikaron-owned directory,
unpacks it, and uses *that* interpreter's absolute path for both console-script entry points and the
background service's `sys.executable -m ...` spawn — rather than relying on `uv` or any system package
manager being present. This is functionally "control the interpreter yourself" rather than "hope the
user's interpreter qualifies," and is the same mechanism `uv` itself relies on, minus `uv` as an
intermediary.

**Removes the host-Python dependency:** yes, completely, for the interpreter question — the user needs
no pre-existing Python at all, only enough to run Zikaron's installer script itself (which could be a
tiny bootstrap using only the stdlib of *whatever* Python happens to be on the host, or a shell/PowerShell
script with no Python dependency at all).

**What the user has to install first:** nothing, if the installer is a shell/PowerShell/single-binary
bootstrapper. This is the same UX shape `uv`, `rustup`, and `ruff`'s own installers use (§3).

**Artefact size:** a full `python-build-standalone` CPython build (tens of MB) plus Zikaron's own
dependency wheels (onnxruntime-dominated, ~150-200 MB) — comparable to any other approach that installs
a real venv, since none of the approaches here shrink onnxruntime's own wheel size.

**What breaks:** this is the option requiring the most from Zikaron itself — an installer that knows how
to select and verify the right `python-build-standalone` release per platform/arch, keep it updated,
and (per §1's open gap) still needs to **verify, not assume**, that the specific `python-build-standalone`
release in use actually has `enable_load_extension` available, since FTS5-compiled-in and
loadable-extension-support are two separate toggles and only the former was source-confirmed above.
This option converts a distribution-availability problem into an interpreter-selection-and-pinning
problem Zikaron would own outright — more work, but the most control, and the most consistent with
Zikaron's existing shape (it already ships an installer, `zikaron/install/`, per `design/harness.md`).

---

## 3. Precedent — how comparable tools actually ship

| Tool | What it does, from its own docs | Source |
|---|---|---|
| **aider-chat** | Explicitly recommends **`uv tool install`** or a bootstrapper package (`aider-install`, itself thin wrapper that `pip install`s then invokes `uv` under the hood) over plain `pip install`. Its own blog post states install failures/dependency conflicts dropped sharply after switching to this recommendation, and that `uv tool install --force --python python3.12 aider-chat` is "extremely fast... even when uv is also installing python 3.12" — i.e. aider leans on uv's auto-download-a-matching-interpreter behavior as the *primary* fix for "user doesn't have the right Python." pipx is offered as a documented fallback (Python 3.9-3.12 supported that way), constrained by whatever the user already has. Sources: [aider.chat/docs/install.html](https://aider.chat/docs/install.html), [aider.chat/2025/01/15/uv.html](https://aider.chat/2025/01/15/uv.html), [pypi.org/project/aider-install](https://pypi.org/project/aider-install/). |
| **`llm` (Simon Willison)** | Ships three parallel install paths with no single canonical one pushed hardest: `brew install llm` (Homebrew formula), `pipx install llm`, `uv tool install llm`, plus `uvx llm ...` for ephemeral no-install runs. A real caveat is documented: the **Homebrew formula pins to Python 3.12** and some PyTorch-dependent plugins (`llm-sentence-transformers`) may not install cleanly against it because PyTorch's stable-release cadence lags new CPython minors — i.e. even a packaged, "just works" path (Homebrew) inherits interpreter-version friction from a *third* dependency, not just from `llm` itself. Source: [github.com/simonw/llm](https://github.com/simonw/llm), [llm.datasette.io/en/stable/setup.html](https://llm.datasette.io/en/stable/setup.html). |
| **marimo** | Docs describe pip/uv/conda as parallel install paths, with `uv run marimo edit` treated as a first-class flow that manages a `pyproject.toml`-declared project environment automatically. No special native-dependency guidance found (marimo's own native-extension surface is much lighter than Zikaron's). Source: [docs.marimo.io/getting_started/installation/](https://docs.marimo.io/getting_started/installation/), [docs.marimo.io/guides/package_management/using_uv/](https://docs.marimo.io/guides/package_management/using_uv/). |
| **harlequin** | Ships via plain `pip`/`pipx`/`poetry` *and* a Homebrew formula — i.e. it takes the "meet the user where they are" approach rather than standardizing on uv, per its own PyPI page. Source: [pypi.org/project/harlequin/2.13.0](https://pypi.org/project/harlequin/2.13.0/). |
| **datasette** | Long-established multi-path installer story (pip, pipx, Homebrew, Docker) predating uv's rise; its docs are the oldest of the set searched and don't reflect the uv-first pattern the newer tools (aider, llm) have since converged on. Source: [docs.datasette.io/en/stable/installation.html](https://docs.datasette.io/en/stable/installation.html). |
| **`ruff` / `uv` themselves (Rust)** | Not Python-dependency-bearing at all — distributed as single static binaries via a curl\|sh installer, `pip install` (as a wrapper that just fetches the platform binary), Homebrew, and various package managers. Relevant precedent for the **installer UX**, not for the interpreter question: a one-command, no-prerequisite install script is the pattern every one of the Python-based tools above is now converging toward reproducing (via `uv tool install` as the intermediary), even though `ruff`/`uv` sidestep the whole problem by not being Python programs. |
| **MCP servers generally / Claude Desktop** | The documented, ecosystem-standard pattern for shipping a Python-based MCP server to non-Python end users is `uvx <package>` invoked from the client's config file with an **absolute path to `uvx`** (GUI apps like Claude Desktop don't inherit shell `PATH`, so a bare `uvx` in config commonly fails silently) — directly analogous to Zikaron's own need for absolute paths in `.mcp.json`. Sources found describing this pattern: [modelcontextprotocol.io/docs/develop/build-server](https://modelcontextprotocol.io/docs/develop/build-server), a RapidDev tutorial and a BSWEN blog post (both secondary, describing the same `uvx`-in-config convention). **This is the closest precedent found to Zikaron's own console-script-absolute-path constraint**, and it resolves the same way aider does: let `uv`/`uvx` own interpreter acquisition, and point the agent config at `uvx`'s (or `uv tool install`'s installed shim's) absolute path rather than at a bare venv `python`. |

**Overall pattern across precedent:** the tools launched or updated most recently (aider, llm) have
converged on **`uv`-mediated installation as the primary recommendation**, with pipx/Homebrew/pip kept
as fallbacks for users who already have working environments. No precedent tool found ships primarily
via PyInstaller/Nuitka/conda/Docker for this class of CLI dev tool, and no precedent tool found has
Zikaron's specific combination of a loadable native SQLite extension plus a large ML runtime plus an
absolute-path integration contract — Zikaron's constraint set is somewhat more demanding than any single
precedent checked.

---

## 4. The `requires-python` upper-bound question

**Current, fairly settled community position:** cap `requires-python` with a floor (`>=3.12`), not a
ceiling. The most-cited authoritative treatment found is Henry Schreiner's
[iscinumpy.dev post](https://iscinumpy.dev/post/bound-version-constraints/) ("Should You Use Upper Bound
Version Constraints?"), whose stated position on `requires-python` specifically is blunt: **"Never
provide an upper cap to your Python version."**

**The argument against a cap, from that source:**
- `requires-python` is a metadata field consumed by resolvers to decide which package release to select
  for a given interpreter; it was, per Schreiner, "not designed to support upper caps" — its intended use
  is expressing a *floor* below which a package definitely won't work syntactically, not an *opinion*
  about future compatibility.
- If a project caps below the user's actual interpreter (e.g. releasing with `<3.13` before 3.13 exists,
  then never revisiting it once 3.13 ships), the practical effect isn't "fail cleanly" — since **you
  cannot downgrade your own interpreter to satisfy the cap**, a resolver (pip, Poetry, PDM) instead
  **backsolves to older releases of the package** that claim wider compatibility, frequently pulling in
  a genuinely broken or unmaintained old version rather than surfacing the real problem.
- This **masks real incompatibility errors**: instead of an honest `ImportError` or `SyntaxError` telling
  a user (or the project's own maintainers) exactly what broke on the new interpreter, they get an
  opaque "no compatible version found"/resolver failure that gives no actionable signal.
- It **cascades**: Poetry and PDM compute a project's supported-Python-version envelope from its
  dependency tree, so one capped dependency forces every consumer's own advertised range down to match,
  "even if maintainers oppose the practice" — a single project's defensive cap becomes ecosystem-wide
  friction.
- Documented real breakage from exactly this pattern: cibuildwheel and pybind11 CI pipelines broke when
  Python was upgraded, purely from an unrevisited upper cap, despite the actual code working fine on the
  newer interpreter.

**The argument for a cap (the exception case Schreiner and others concede):** a genuinely *known*,
specific incompatibility — e.g. "version 2 of dependency X is known to break under Python's version N" —
can justify a narrow, well-reasoned upper bound, analogous to how a floor is justified by a known
minimum. This is a different thing from a blanket `==3.12.*` chosen reflexively at project creation.

**What pip/uv resolvers actually do when a cap excludes the only available interpreter:** the resolver
does not fail with "your Python is unsupported, please downgrade or find another interpreter" in a
friendly way — it filters out every release whose `Requires-Python` metadata doesn't include the running
interpreter and then reports a generic "no versions of `<package>` satisfy the requirement" / resolver
failure, which reads to a user as if the package doesn't exist at the version they expected, not as a
Python-version problem specifically (general behavior corroborated by multiple secondary
troubleshooting pages found, e.g. a RepoFlow error-explainer page and various project-specific GitHub
issues — no single canonical pip source doc was fetched directly for this exact error-message wording,
so **treat the precise wording of the failure mode as approximately but not verbatim confirmed**). Note
this describes *installing Zikaron as a dependency of something else* or *installing it against an
interpreter that doesn't match its cap* — it does not directly describe uv's own separate behavior of
auto-downloading a matching interpreter when `requires-python` names one that isn't present, which (per
§2a) is a different code path uv added specifically to blunt this exact class of failure for its own
users.

**Implication for Zikaron's `requires-python = "==3.12.*"`:** this is exactly the pattern the community
consensus argues against, for exactly the reasons above — it will force a hard resolver failure (rather
than a graceful one) on any interpreter that isn't literally 3.x.y where x=12, including future 3.13+
interpreters that might work fine, and does nothing to *fix* the actual binding constraint (which per
this whole note is not language-syntax compatibility but §1's build-flag and native-dependency-wheel
availability question). A floor (`>=3.12`) paired with **uv-driven interpreter acquisition** (§2a) that
guarantees a *known-good* 3.12 build regardless of what the host has is the combination precedent (§3)
converges on, rather than a cap that merely blocks incompatible interpreters from ever being tried.

---

## 5. macOS specifics

**Unix domain socket `sun_path` length.** Confirmed from multiple independent, mutually consistent
sources: **macOS limits `sun_path` to 104 bytes**, **Linux to 108 bytes**
([blog.8-p.info](https://blog.8-p.info/en/2020/06/11/unix-domain-socket-length/),
[linuxvox.com](https://linuxvox.com/blog/why-is-the-maximal-path-length-allowed-for-unix-sockets-on-linux-108/),
corroborated by an Apple Developer Forums thread on the same topic). Both figures include the
terminating null byte, so usable path length is one byte less than the stated maximum in each case. This
directly bears on Zikaron's socket-based hook↔service RPC (`design/architecture.md`): **any socket path
construction that assumes the Linux 108-byte budget will silently truncate or fail to bind on macOS at
104**, and the tighter macOS number is the one to design against if Zikaron wants one code path for both
platforms — the existing scope-key-under-`.zikaron/`-per-project design (D8, D17) should be checked
against this bound for deeply-nested project directories, since the socket path is presumably derived
from the project path.

**`$XDG_RUNTIME_DIR` absence.** Confirmed: this is a Linux-only convention formalized by the
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/), and
**macOS has no equivalent variable set by the OS at all** — there is no `/run/user/<uid>/` analogue.
A common convention found in the wild (not an Apple-documented standard) is falling back to
`"$TMPDIR/runtime-$UID"` on macOS, since `$TMPDIR` *is* set by the OS to a per-user, per-session
temporary directory under `/var/folders/...`
([leebyron.com/til/mac-xdg](https://leebyron.com/til/mac-xdg/)). Whatever directory is used for the
socket needs 0700 permissions and to be on a filesystem that supports Unix sockets — both satisfied by
`$TMPDIR` on macOS in the ordinary case, but this means **Zikaron cannot assume `$XDG_RUNTIME_DIR` is
set on macOS and needs an explicit fallback path**, distinct from whatever project-scoped path (D8/D17)
governs socket placement day to day.

**Gatekeeper/notarization for a pip-installed `.dylib`/`.so`.** The picture found is nuanced and **not
fully confirmed for the specific pip-install case**. What is confirmed: macOS attaches a
`com.apple.quarantine` extended attribute to files downloaded by a quarantine-aware application (browser
downloads, `curl` in some configurations, anything using the relevant Apple APIs), and Gatekeeper
inspects quarantined executables/libraries when they're first *executed or loaded*, potentially blocking
unsigned, unnotarized ones — sourced from Apple's own Gatekeeper documentation trail and
[hacktricks.wiki's Gatekeeper writeup](https://hacktricks.wiki/en/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-gatekeeper.html).
**What is genuinely unconfirmed**: whether `pip`'s own file-write path (as opposed to a browser download
or a `curl` invocation) sets the quarantine attribute on files it extracts from a wheel — `pip` writing
files via ordinary Python file I/O during wheel extraction is a different code path from a
quarantine-aware download, and several of the search results specifically distinguish "apps that write
files themselves" (sandboxed apps quarantine their own writes) from "ordinary CLI tools" (which
generally do not). **This needs a direct empirical check** — `xattr -l` on a freshly `pip install`ed
`sqlite-vec` `.dylib` on a clean macOS machine — before assuming either way; the risk if quarantined and
unsigned is that `sqlite3.Connection.load_extension()` (which ultimately calls `dlopen`) could be blocked
by Gatekeeper at first load, which would be a confusing, install-time-invisible failure exactly in the
spirit of the failures this note is trying to get ahead of.

**onnxruntime macOS Intel (x86_64) wheel availability.** Confirmed via direct evidence: **onnxruntime
has dropped macOS x86_64 wheels as of recent releases.** Search evidence indicates **1.23.2 is the last
onnxruntime release to publish an x86_64 macOS wheel**, and **1.27.0 on PyPI ships only an
`macosx_14_0_arm64` wheel**, with a live GitHub issue
([NousResearch/hermes-agent#81560](https://github.com/NousResearch/hermes-agent/issues/81560)) reporting
exactly this failure ("onnxruntime==1.27.0 has no x86_64 wheel") as an install-breaking problem for a
downstream project. **This is corroborating evidence, not a primary onnxruntime release-notes citation**
— I did not fetch onnxruntime's own PyPI release history/changelog directly to pin the exact version
boundary; treat "1.23.2 is the last x86_64 build" as reported-and-plausible rather than fully verified,
and re-check against `pypi.org/project/onnxruntime/#history` before depending on a specific version
number. **Practical implication for Zikaron regardless of the exact cutoff version**: pinning a specific
recent `onnxruntime` version (directly or transitively through `fastembed`) risks silently losing Intel
Mac support the moment that pin crosses whatever the current cutoff is, independent of anything else in
this note — this is worth a standing check in Zikaron's own dependency-update process, not a one-time
fact to record.

---

## Evidence quality summary

- **High confidence, primary-sourced:** the `--enable-loadable-sqlite-extensions` compile-time gate
  mechanism itself; Arch and Fedora/RHEL both explicitly patching it on; Docker's official images
  building it on (source-read from the actual Dockerfile template); python-build-standalone compiling
  FTS5 in (source-read from an actual merged PR); uv's auto-download-on-`requires-python`-mismatch
  behavior and its downloaded-interpreter storage location (from uv's own docs); the
  `iscinumpy.dev`/Schreiner argument against `requires-python` upper bounds; the macOS 104 / Linux 108
  `sun_path` byte limits; `$XDG_RUNTIME_DIR` being Linux-only per the XDG spec itself; aider's and llm's
  own documented install recommendations.
- **Medium confidence, corroborated but not primary-sourced or somewhat dated:** conda-forge's
  loadable-extension status (multi-year-old GitHub issues, not re-checked against current feedstock);
  Debian/Ubuntu's status (inferred from Docker's image build process rather than a Debian changelog
  entry); PyInstaller+onnxruntime's exact failure shape (a live but single GitHub issue plus general
  PyInstaller docs, not a systematic survey); the macOS pip-quarantine question (general Gatekeeper
  mechanics confirmed, the specific pip-writes-files-itself case not directly confirmed).
- **Explicitly unconfirmed, flagged in-line above and worth a direct empirical check before relying on
  it:** whether current `python-build-standalone` builds (the ones `uv python install` fetches) actually
  have `enable_load_extension` available — this is the single highest-priority thing to verify directly,
  since it decides whether §2a (uv) or §2g (embed python-build-standalone directly) is even viable
  without extra work; which CPython/Windows-installer release first shipped the loadable-extensions fix
  from cpython#95656; the exact onnxruntime version boundary where macOS x86_64 wheels stopped shipping;
  whether pip-extracted `.dylib`/`.so` files get quarantined on macOS.

## Open questions / next steps for memory-researcher

1. **Run the empirical check**: on a machine (or CI image) using a `uv python install`-fetched 3.12,
   confirm `sqlite3.Connection.enable_load_extension` exists. This one fact plausibly decides the whole
   distribution strategy.
2. Check `xattr` on a freshly `pip install`ed `sqlite-vec` wheel's `.dylib` on real macOS hardware to
   settle the Gatekeeper/quarantine question directly rather than by inference.
3. Pin down the exact onnxruntime version where macOS x86_64 wheels were dropped, from
   `pypi.org/project/onnxruntime/#history` directly, and decide whether Zikaron needs an
   `onnxruntime`-version ceiling *specifically to preserve Intel Mac support*, which would itself be an
   informed exception to the general "don't cap" advice in §4.
4. If §2g (embedding python-build-standalone) is the direction chosen, read
   python-build-standalone's own release documentation on its versioning/support policy and on
   `SQLITE_ENABLE_LOAD_EXTENSION` explicitly, rather than relying on inference from the FTS5 PR found
   here.
