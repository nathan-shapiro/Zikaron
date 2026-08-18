"""`HarnessSpec.store_scope_dir`: the one resolver both clients use to key a store.

**The defect this closes was two implementations of one decision (D17).** `zikaron-hook` keyed the
store on the harness-supplied payload `cwd`, which under Claude Code follows the agent's own `cd`;
`zikaron-mcp` keyed it on `Path.cwd()` of a process spawned once at session start, which never
moves. They agreed only while nobody changed directory. Measured on one live session: **39 cwd
transitions**, a store created under `Trading.local/log`, and in another session **20 pushes over
two hours returning nothing** while its MCP tools kept answering from the real store. Link coverage
could not see it — it checks that both clients agree on the *session label*, which they did, and
nothing checked that they agree on the *store*.

`test_a_project_variable_keeps_both_clients_on_one_store_when_the_cwd_moves` is that missing check,
and it is the test this module exists for; everything above it establishes the pieces it rests on.
"""

from pathlib import Path

import pytest

from zikaron.harness.spec import CLAUDE_CODE, KIRO, SPECS, HarnessSpec


@pytest.fixture(autouse=True)
def _no_inherited_project_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test states the variable it wants, so none inherits the running session's own.

    This suite may itself run inside a Claude Code session, whose `CLAUDE_PROJECT_DIR` names this
    repository — a test asserting the fallback would then silently assert the opposite.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


def test_kiro_has_no_project_variable_and_falls_back_to_the_directory_given(tmp_path: Path) -> None:
    """Kiro's rung is the fallback, and that is a measurement rather than a gap.

    The lifecycle probe captured every `KIRO_*` variable across 42 records — 17 names, none
    spatial — so there is nothing to read. Kiro also restores the working directory rather than
    persisting it across shell calls, so it does not need one. Asserting `None` here pins the
    claim: if a future kiro exports a project variable, this test is where that is noticed.
    """
    assert KIRO.project_dir_variable is None
    assert KIRO.store_scope_dir(tmp_path) == tmp_path


def test_claude_code_prefers_its_own_project_variable_over_the_directory_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: the wandering directory loses to the harness's own answer."""
    project = tmp_path / "project"
    wandered = tmp_path / "project" / "src" / "deep"
    wandered.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    assert CLAUDE_CODE.store_scope_dir(wandered) == project


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "unset-but-present is as good as absent"),
        ("/nonexistent/no/such/path", "a path that is not there must not become a store"),
        # `Path(".").is_dir()` is true, so an `is_dir()`-only resolver would return it — and each
        # client would resolve it against its *own* cwd, which is the split this exists to remove.
        (".", "a relative value that exists resolves differently per client, so it is refused"),
    ],
)
def test_an_unusable_project_variable_falls_back_rather_than_being_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, why: str
) -> None:
    """What refusal actually covers: a deleted or never-created directory, an empty value, a
    relative path, and a file where a directory was promised — that last one in its own test below,
    since it needs a file on disk rather than a bare string.

    **Not** the nesting case, and an earlier version of this docstring said otherwise. A process
    tree inheriting an enclosing session's variables inherits a directory that *exists*, so it
    passes every check here and is adopted — see `HarnessSpec.store_scope_dir`'s own paragraph on
    the regression that introduces, and `design/harness.md` §"The nesting limit"."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", value)
    assert CLAUDE_CODE.store_scope_dir(tmp_path) == tmp_path, why


def test_a_file_where_a_directory_was_promised_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`is_dir()` rather than `exists()`, so a regular file at that path cannot be adopted."""
    impostor = tmp_path / "not-a-directory"
    impostor.write_text("")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(impostor))
    assert CLAUDE_CODE.store_scope_dir(tmp_path) == tmp_path


@pytest.mark.parametrize("spec", SPECS.values(), ids=lambda s: str(s.harness.value))
def test_every_harness_resolves_to_a_directory_without_creating_one(
    spec: HarnessSpec, tmp_path: Path
) -> None:
    """Resolution is a pure read. A resolver that created its answer would put an empty store
    wherever it was asked, which is the failure being removed rather than relocated."""
    absent = tmp_path / "never-created"
    assert spec.store_scope_dir(absent) == absent
    assert not absent.exists()


_WITH_VARIABLE = [s for s in SPECS.values() if s.project_dir_variable is not None]
_WITHOUT_VARIABLE = [s for s in SPECS.values() if s.project_dir_variable is None]


@pytest.mark.parametrize("spec", _WITH_VARIABLE, ids=lambda s: str(s.harness.value))
def test_a_project_variable_keeps_both_clients_on_one_store_when_the_cwd_moves(
    spec: HarnessSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The property that had no test, and whose absence is the whole defect.**

    Both clients are reproduced at the level that differed: `zikaron-hook` passes the harness's
    live payload `cwd`, `zikaron-mcp` passes its own process cwd fixed at spawn. The hook's input
    moves and the MCP client's does not — exactly the real divergence — and after resolution the
    two must still name one store.

    Split from the harnesses *without* a variable deliberately, and the first version of this test
    did not split: it fed kiro a moved payload `cwd` too, and failed. Correctly — kiro has no
    variable, so the resolver is identity there and a moved input yields a moved store. That is not
    a kiro defect, because kiro's payload does not move; but asserting agreement-under-movement for
    a harness that never moves is a claim its own fixture invents. The kiro arm's real property is
    below.
    """
    project = tmp_path / "project"
    (project / "src" / "deep").mkdir(parents=True)
    monkeypatch.setenv(str(spec.project_dir_variable), str(project))

    mcp_side = spec.store_scope_dir(project)  # spawned at the project root, never moves
    hook_side = spec.store_scope_dir(project / "src" / "deep")  # follows the agent's `cd`

    assert hook_side == mcp_side == project, (
        f"{spec.harness.value}: the two clients would key different stores, which is the defect "
        "this resolver exists to remove — push and pull would silently answer from different data"
    )


@pytest.mark.parametrize("spec", _WITHOUT_VARIABLE, ids=lambda s: str(s.harness.value))
def test_without_a_project_variable_the_resolver_is_identity_and_says_what_that_rests_on(
    spec: HarnessSpec, tmp_path: Path
) -> None:
    """The other arm's true property, and the assumption it leaves standing.

    With no variable to read, resolution returns its argument: the two clients agree **because
    their inputs agree**, not because anything here reconciles them. So agreement under this
    harness rests entirely on a claim about the *harness* — that it does not persist a working
    directory across shell calls — which is supported by an operator observation and by twelve days
    and ~8,000 events producing no stray store, and is **not measured**. If a future kiro persists
    a cwd, it reacquires this defect and nothing above will fail. This test is where that
    dependency is written down.
    """
    moved = tmp_path / "somewhere-else"
    moved.mkdir()
    assert spec.store_scope_dir(moved) == moved
    assert spec.store_scope_dir(tmp_path) == tmp_path
