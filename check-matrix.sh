#!/usr/bin/env bash
# Runs the whole check gate once per supported Python version.
#
# `./check.sh` is the per-edit gate and the definition of done for a change; this script is
# additionally required before a milestone lands. (That phrase is kept on one line on purpose: it is
# how every site stating this rule is found, and a wrap hides one from the grep.)
#
# **CI does not run this script, and is not a third thing to run.**
# `.github/workflows/check.yml` asserts *this script's* claim — every supported version green on one
# tree — against a commit, by running `check.sh` once per version. So it needs none of the tree
# fingerprinting below: a job checks out one SHA, and "every version saw the same tree" is guaranteed
# rather than sampled. The price is that the deprecation filters set here become per-job over there
# and have to be asserted rather than remembered, which `tests/test_ci_workflow.py` does.
# `design/distribution.md` §"What CI asserts" is normative.
#
# Not on every edit, because it is minutes rather than seconds and builds a virtualenv per version;
# not conditional on which files changed either, because a rule like "run it when the compatibility
# module changes" is a judgement call, and the person making it is the one who would rather not wait.
#
# Two things are only ever exercised here. The version-dependent rows in
# `zikaron/service/asyncio_compat.py` are each unexecuted on the versions that do not select them, so
# only a run under each version covers both. And erroring on deprecations belongs here rather than in
# `pyproject.toml`: a deprecation raised only on a newer version is invisible to a single-version run
# whatever the filter says, so the filter belongs where the interpreter varies.
#
# The version list lives here and nowhere else in executable form, and `minors=(...)` below is what a
# test compares against the list the coding standards state. **Nothing in the environment can touch
# it**: `ZIKARON_PYTHON_3_13=/path/to/python` and its siblings override only *where* an interpreter is
# found, never which versions exist, because an environment able to shrink the list would make that
# comparison meaningless.
#
# **Arguments narrow one invocation, not the list.** With none, it runs every version, which is the
# form a milestone needs; given versions (`./check-matrix.sh 3.13`) it runs only those, checked against
# the list first, and labels its last line `SUBSET RUN`. The declaration below is what the drift test
# reads, and it is a literal, so narrowing a run cannot narrow what this script *claims* to cover.
# Arguments originally existed because the *sequential* loop outlasted what some callers can block
# for — but a subset is not a milestone gate, and the label says so.
#
# **`--parallel` runs every version at once and is the form the instruction files name**: roughly
# 3.5 minutes on a warm tree against nine sequential, each version writing to its own
# `check-matrix.<version>.log` with its own coverage file and tool caches (`ZIKARON_CACHE_SUFFIX`,
# read by `check.sh`). Virtualenv preparation stays sequential; the reason is below, at the install.
# With it, arguments are for debugging one version rather than for fitting inside a caller's patience.
set -euo pipefail
cd "$(dirname "$0")"

minors=(3.12 3.13 3.14)

parallel=false
declare -A pids=()
declare -A prepared=()
args=()
for arg in "$@"; do
    case "$arg" in
        --parallel) parallel=true ;;
        *) args+=("$arg") ;;
    esac
done

requested=("${args[@]+"${args[@]}"}")
if [[ ${#requested[@]} -gt 0 ]]; then
    for one in "${requested[@]}"; do
        # Refused rather than silently skipped: a typo would otherwise report success for a version
        # that never ran, which is the failure the absent-interpreter check below also exists for.
        # Exact equality against each entry, not a padded-substring match on the joined list: that
        # idiom accepts the empty string, since the pattern it builds matches anything containing a
        # space, and an empty version would make `venv` the bare `.venv-matrix/` directory.
        known=false
        for candidate in "${minors[@]}"; do
            if [[ "$one" == "$candidate" ]]; then
                known=true
                break
            fi
        done
        if [[ "$known" != true ]]; then
            echo "check-matrix: ${one} is not one of the tested versions (${minors[*]})" >&2
            exit 1
        fi
    done
    minors=("${requested[@]}")
fi

# Every interpreter is resolved and checked before any version runs, so a machine missing one is told
# now rather than after the earlier versions have spent their minutes.
#
# Three sources, in order. An explicit `ZIKARON_PYTHON_3_13` always wins. Otherwise `uv` is asked for
# a **managed** interpreter, which is where `uv python install --no-bin` puts them: `--no-bin` is
# deliberate, so that installing interpreters for this script does not put a second `python3.12` on a
# developer's `PATH` ahead of the system one. `--managed-python` and `--no-project` are both required
# — without them `uv python find 3.12` answers with the *project virtualenv*, which is the one
# interpreter that must never be used here. A bare `python3.<minor>` on `PATH` is the last resort, for
# a machine that manages its interpreters some other way.
declare -A interpreters=()
for minor in "${minors[@]}"; do
    override_var="ZIKARON_PYTHON_${minor//./_}"  # `ZIKARON_PYTHON_3_13` for 3.13, and so on.
    interpreter="${!override_var:-}"
    if [[ -z "$interpreter" ]] && command -v uv >/dev/null 2>&1; then
        interpreter="$(uv python find --managed-python --no-project "$minor" 2>/dev/null || true)"
    fi
    if [[ -z "$interpreter" ]]; then
        interpreter="python${minor}"
    fi
    if ! command -v "$interpreter" >/dev/null 2>&1; then
        # A red version, never a skip. A machine carrying only one interpreter would otherwise
        # satisfy this script with one version and report success for three, which is the same
        # failure as a test suite that passes by skipping.
        echo "check-matrix: no interpreter for ${minor} (looked for '${interpreter}')." >&2
        echo "  Install the tested set once with:  uv python install --no-bin ${minors[*]}" >&2
        echo "  Or point at your own with:         ${override_var}=/path/to/python" >&2
        exit 1
    fi
    interpreters[$minor]="$interpreter"
done

# **The tree is named on the last line, and that is the point of the line.** The milestone gate is
# "every tested version green on the *same* tree", and when versions are run one per call — which
# `--parallel` makes unnecessary but arguments still allow — nothing otherwise connects them: three
# green lines from three different working trees look exactly like three from one. That has already
# happened here, a test file added between one version's run and the next, visible only as a
# one-test difference in the counts. Compare these identities across runs before calling a set of
# subset runs a gate. A `--parallel` run samples once and so has nothing to reconcile.
#
# The identity is every difference from `HEAD`, whether staged or not, plus the content of every
# untracked file git does not ignore. Each of those words was earned:
#   * not a bare "-dirty" marker, which is the same string for every uncommitted state and so carries
#     nothing in a repository whose work in progress is normally uncommitted;
#   * `git diff HEAD` rather than a list of changed paths, because a *deleted* tracked file is listed
#     by `git ls-files --modified` and then cannot be hashed — which failed the pipeline and, under
#     `set -euo pipefail`, killed the gate after every version had passed, with no last line printed;
#   * diffed against `HEAD` rather than the index, because `--modified` compares against the index
#     and `--others` excludes what is in it, so after `git add -A` the fingerprint was
#     byte-identical to a clean checkout — and staging is a thing this project's own instructions
#     permit.
tree_identity() {
    local head fingerprint
    head="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')"
    if [[ -z "$(git status --porcelain --untracked-files=all 2>/dev/null)" ]]; then
        printf '%s\n' "$head"
        return
    fi
    fingerprint="$(
        {
            git diff --binary HEAD
            git ls-files -z --others --exclude-standard | while IFS= read -r -d '' path; do
                # `-f` guards against a dangling symlink, which would fail the hash and take the
                # gate with it for a reason that has nothing to do with the code.
                if [[ -f "$path" ]]; then sha256sum -- "$path"; fi
            done
        } | sha256sum | cut -c1-12
    )"
    printf '%s+%s\n' "$head" "$fingerprint"
}

# Taken before the versions run, and again after, because an edit landing mid-run would otherwise let
# two versions print one identity while testing different code — the exact confusion this line exists
# to prevent, produced by the line itself.
tree_before="$(tree_identity)"

# **Interrupting a run has to stop the versions, because nothing else will.** With job control off —
# which it is in a script — bash starts every `&` job with SIGINT and SIGQUIT *ignored*, and an
# ignored disposition survives `exec`, so `check.sh`, `timeout` and `pytest` all inherit it and
# CPython never installs its own handler over it. A Ctrl-C therefore kills only this parent, sitting
# in `wait`, and leaves three full gates running: the next run truncates their log files while they
# are still writing to them, and `pytest-cov` combines every `${COVERAGE_FILE}.*` it finds, so an
# orphan's data — from whatever tree it was started on — lands in the next run's coverage. A floor
# computed over two runs of two trees is exactly what the per-version suffix exists to prevent, and
# the tree-identity guard cannot see it, because an orphan is a process rather than a difference
# from `HEAD`.
#
# **Processes are found by a token in their environment, not by walking parent links**, because
# ancestry is the first thing an interruption destroys. A descendant walk works only for a terminal
# Ctrl-C, where the intermediate shells ignore the signal and so survive to be walked. `TERM` and
# `HUP` keep their default disposition and arrive at the whole group — from an outer `timeout`, a
# harness kill, a hangup — so those shells die first, `timeout` and `pytest` (in a group of their
# own, which the TTY never signals) are reparented, and the walk then finds nothing. **Reproduced
# before this was written**: `timeout 120 ./check-matrix.sh --parallel` left three
# `timeout 600 … pytest` pairs running after it had exited.
#
# A token also reaches what no walk could: the integration tier spawns services with
# `start_new_session=True`, so one is reparented within milliseconds of its hook exiting and has no
# ancestry left at all. Everything that inherited pytest's environment carries the token — and
# everything able to write a coverage fragment inherited that environment, because `COV_CORE_*`
# travels the same way. That includes every subprocess the suite builds an explicit `env=` for:
# each of those spreads `os.environ` into the mapping it passes, so the token travels with them too.
# The three `zikaron.knowledge` processes the reproduction below left behind passed no `env=` at
# all and carried the token by plain inheritance — the default case, and the one every indexer and
# CLI the suite spawns exercises.
#
# **The handler kills before it speaks, and that ordering is the whole of it.** A hangup is the
# shape where it matters: the terminal closing or the ssh session dropping is what *generates*
# `SIGHUP`, so by the time the handler runs the pty is already hung up and every write to stderr
# fails. `echo` reports that failure, `set -e` applies inside a trap action, and a handler that
# announces itself first therefore exits one line in, having killed nothing. Measured on this
# script, with `/dev/full` standing in for the hung-up terminal because it fails every write
# deterministically: `./check-matrix.sh --parallel 2>/dev/full`, `SIGHUP` at 90 s, **nine surviving
# processes** — three `timeout`/`pytest` pairs, two `zikaron.knowledge.indexer` subprocesses and one
# `zikaron.knowledge` CLI, the last three spawned by tests — against **zero** once the two statements
# are in this order.
ZIKARON_MATRIX_RUN="matrix-$$-$(date +%s%N)"
export ZIKARON_MATRIX_RUN

kill_run() {
    local token="$ZIKARON_MATRIX_RUN" pid
    # The search runs with the token unset, so it cannot find itself: the `/proc/[0-9]*/environ`
    # glob is expanded in the subshell *before* `grep` execs, so `grep`'s own entry is in the list
    # and it would otherwise read its own environment back and report its own pid. Harmless — that
    # pid has exited by the time the loop reaches it — but a process list that is not quite the
    # process list is the wrong thing to debug an interrupted run with. The subshell is forked
    # rather than exec'd, so its own `/proc` entry still holds the parent's `execve`-time block,
    # which never carried the token either. That is also why nothing skips this script's own pid:
    # `/proc/$$/environ` is the block this script was exec'd with, and the export above came after.
    #
    # `-x` anchors each NUL-delimited record, so a match is the whole `NAME=value` and never a
    # substring of some longer variable that happens to contain this one.
    for pid in $(
        unset ZIKARON_MATRIX_RUN
        grep -lsxz -- "ZIKARON_MATRIX_RUN=${token}" /proc/[0-9]*/environ 2>/dev/null | cut -d/ -f3
    ); do
        kill -TERM "$pid" 2>/dev/null || true
    done
}

on_signal() {
    kill_run
    echo "check-matrix: interrupted — stopped every process this run started" >&2 || true
    wait 2>/dev/null || true
    exit 130
}

# Installed before virtualenv preparation, not after it: a `TERM` arriving during a `pip install`
# would otherwise kill this script and leave the install finishing into a venv nothing ever stamps.
trap on_signal INT TERM HUP

wanted_pyproject="$(sha256sum pyproject.toml | cut -d' ' -f1)"

for minor in "${minors[@]}"; do
    interpreter="${interpreters[$minor]}"
    venv=".venv-matrix/${minor}"
    stamp="${venv}/.zikaron-venv-stamp"

    # **The base interpreter is half of what a venv is, so it is half of the stamp.** Two 3.13
    # builds are the same version and a different machine: SQLite comes with the interpreter, so a
    # distribution build and a downloaded one can link different SQLite versions (this machine's
    # `/usr/bin/python3.12` at 3.45.1 against its downloaded 3.13 at 3.53.1), and FTS5 ranking can
    # differ between them. Without this, pointing `ZIKARON_PYTHON_3_13` at a different build keeps
    # the venv that was already there: the label check below passes, since the minor version
    # matches, and the run reports green for an interpreter it never used — the same "success
    # reported for a version that never ran" that refusal exists to prevent. Verified by doing it:
    # pointing `ZIKARON_PYTHON_3_12` at `/usr/bin/python3.12` over a uv-built venv rebuilds,
    # pointing it back rebuilds again, and an unchanged run does not.
    #
    # `realpath` buys more than path normalisation here. uv's managed directory is a *minor*-named
    # symlink into a patch-named one, so resolving it stamps `cpython-3.12.14-…` rather than
    # `cpython-3.12-…` — measured — which means a `uv python upgrade` to 3.12.15 moves the target
    # and rebuilds, without the version ever being read.
    #
    # **The limit, stated because it is the case this guard looks like it covers and does not.** A
    # standalone build links SQLite statically, so the path identifies it; a distribution interpreter
    # loads the system `libsqlite3.so`, and upgrading that package changes SQLite behind a path that
    # has not moved. Nothing here can see that. What reports it is the service's own startup line,
    # which logs the linked `sqlite3.sqlite_version` every run.
    base_interpreter="$(command -v "$interpreter")"
    base_interpreter="$(realpath -- "$base_interpreter" 2>/dev/null || printf '%s' "$base_interpreter")"
    wanted_stamp="${wanted_pyproject} ${base_interpreter}"

    # **Reuse is keyed on `pyproject.toml` and the interpreter, not on the venv merely existing.**
    # An editable install keeps the package's own source live, so reuse never serves stale *code* —
    # but it does nothing for dependencies or console-script entry points, so a deliberate pin bump
    # would otherwise be tested against the previous pins on every version, and the script would say
    # green. The venv is removed and rebuilt rather than installed over, so the stamp means "this
    # venv *is* `pyproject.toml` at that hash, on that interpreter": `pip install -e` never removes
    # a dependency that the file has stopped declaring, so installing over would leave it importable
    # and a module still importing it would pass here while failing a fresh install. Written only
    # after the install succeeds, which also repairs the interrupted case — a half-built venv has no
    # stamp, so the next run rebuilds instead of dying on a missing `ruff`.
    # The condition is "a directory that is not a finished venv, stamped for this `pyproject.toml`,
    # on the live base interpreter it was stamped with", which covers a case `-x` alone silently
    # skips: `bin/python` is a symlink into the base interpreter's directory, so if that interpreter
    # is removed the link dangles, `-x` reports false, and `-m venv` run over the directory **does
    # not replace an existing symlink** — reproduced here — leaving the link dangling and the next
    # command through it failing with a bare "No such file or directory" and no remedy. Every later
    # run repeated it, because a stamped directory was never removed.
    if [[ -d "$venv" && ( ! -x "${venv}/bin/python" || ! -f "$stamp" || "$(cat "$stamp")" != "$wanted_stamp" ) ]]; then
        echo "check-matrix: rebuilding ${venv} (pyproject.toml changed, the base interpreter changed, the last install did not finish, or that interpreter is gone)"
        rm -rf "$venv"
    fi

    if [[ ! -x "${venv}/bin/python" ]]; then
        echo "check-matrix: creating ${venv} with ${interpreter}"
        "$interpreter" -m venv "$venv"
    fi

    # **The label is checked against the interpreter, not trusted, and checked before anything is
    # spent on it.** An override pointing at the wrong binary, a `python3.14` shim that resolves
    # elsewhere, or a venv built under an earlier wrong override would all run one version under
    # another's name and finish with every version green — the same "success reported for a version
    # that never ran" the absent-interpreter refusal above exists to prevent, by a quieter door. Read
    # from the venv rather than from `$interpreter`, so a stale venv is caught too; and placed before
    # the install so a wrong one is not paid for first, and before the stamp so a refused venv is
    # never stamped into looking finished.
    actual="$("${venv}/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [[ "$actual" != "$minor" ]]; then
        echo "check-matrix: ${venv}/bin/python is Python ${actual}, not ${minor} — remove ${venv}, or fix ZIKARON_PYTHON_${minor//./_}" >&2
        exit 1
    fi

    # **Sequential even when the runs are parallel, and this is the reason:** an editable install
    # writes `zikaron.egg-info/` at the project root, one directory shared by every virtualenv, so
    # three concurrent `pip install -e` calls race on it. Preparing all of them before any of them
    # runs costs nothing on a warm tree, where every stamp already matches and this block is skipped.
    if [[ ! -f "$stamp" ]]; then
        echo "check-matrix: installing into ${venv}"
        "${venv}/bin/pip" install --quiet -e '.[dev]'
        printf '%s\n' "$wanted_stamp" > "$stamp"
    fi

    prepared[$minor]="$venv"
done

# `ZIKARON_CACHE_SUFFIX` gives each version its own coverage file and tool caches, so that versions
# can share a working tree at the same time. Set even for a sequential run, so that a serial and a
# parallel sweep produce the same artefacts and neither can pass over state the other left behind.
run_one() {
    local minor="$1" venv="$2"
    ZIKARON_VENV="$venv" \
        ZIKARON_CACHE_SUFFIX=".${minor}" \
        PYTEST_ADDOPTS="-W error::DeprecationWarning -W error::PendingDeprecationWarning" \
        PYTHONWARNINGS="error::DeprecationWarning,error::PendingDeprecationWarning" \
        ./check.sh
}

for minor in "${minors[@]}"; do
    venv="${prepared[$minor]}"
    echo "check-matrix: ${minor} ($("${venv}/bin/python" --version 2>&1))"
    # **One shared path the per-version suffix deliberately does not isolate**: the embedding model
    # cache. It is one model, correctly shared, and the integration tier loads it from the system
    # temp directory with no per-run copy. On a machine that has loaded it before, three concurrent
    # readers are fine. **The unverified case is the first parallel run on a machine that has never
    # loaded it**, where the download and extraction then happen three times at once inside the
    # tests; `huggingface_hub` locks per-file downloads, but nothing here serialises the rest. Run
    # one version alone first on such a machine, or accept that this is the case nobody has measured.
    #
    # Two filters, because one of them reaches only half of what runs. `PYTEST_ADDOPTS` is applied by
    # pytest in-process and covers the suite itself; the integration tier *spawns* real service, hook
    # and MCP processes, which inherit the environment but not pytest's filters, so a deprecation
    # raised only inside a spawned process would go to a child's stderr and the gate would stay green.
    # `PYTHONWARNINGS` is an interpreter-level default and does propagate to children. It also applies
    # to every other Python the gate runs, mypy included — measured on **3.14**, the newest version and
    # so the one most likely to object: mypy and the spawning integration tests are both clean under
    # it, which is what makes the wider net affordable. Both filters name the same two warning classes;
    # a child inheriting the narrower set would be the gap this line exists to close, reopened.
    if [[ "$parallel" == true ]]; then
        run_one "$minor" "$venv" > "check-matrix.${minor}.log" 2>&1 &
        pids[$minor]=$!
        echo "check-matrix: ${minor} started (pid ${pids[$minor]}, output in check-matrix.${minor}.log)"
    else
        run_one "$minor" "$venv"
    fi
done

if [[ "$parallel" == true ]]; then
    # Every version is waited on before any failure is reported, so one red version does not hide
    # the state of the others — the point of running them at all is to learn about each.
    failed=()
    for minor in "${minors[@]}"; do
        if wait "${pids[$minor]}"; then
            echo "check-matrix: ${minor} green"
        else
            failed+=("$minor")
            echo "check-matrix: ${minor} RED — see check-matrix.${minor}.log" >&2
        fi
    done
    if [[ ${#failed[@]} -gt 0 ]]; then
        echo "check-matrix: red on ${failed[*]}" >&2
        exit 1
    fi
fi

tree_after="$(tree_identity)"
if [[ "$tree_after" != "$tree_before" ]]; then
    echo "check-matrix: the tree changed during the run (${tree_before} → ${tree_after}); nothing above is evidence about either" >&2
    exit 1
fi

if [[ ${#requested[@]} -gt 0 ]]; then
    echo "check-matrix: ${minors[*]} green on ${tree_before} — SUBSET RUN, not a milestone gate"
else
    echo "check-matrix: all of ${minors[*]} green on ${tree_before}"
fi
