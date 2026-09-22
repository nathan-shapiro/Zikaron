"""The harness itself loads what we installed, driven by a real `claude` and a real model.

**This is the test an earlier scope fence said could not exist.** That fence read: the harness's own
reading of the installed files "is not testable from here — kiro is not driven by the suite." True
of kiro, and false of Claude Code, which has a headless mode. So every other test in this repository
checks that we *wrote* the right files; this one checks that the harness *acts* on them.

What it establishes that nothing else can: that `.claude/settings.local.json` is where hooks are
actually read from, that the trigger names in `zikaron/harness/` are the ones this harness fires,
that exit-0 stdout on those triggers reaches a real model, and that a server named in `.mcp.json`
becomes a tool the model can call. A rename upstream on any of those breaks every install on every
machine, and no hermetic test can see it.

**Out of the default run, and it needs its own justification because it is a different kind of
"out".** `integration_kiro` and `integration_claude` exist because they need a third-party binary
installed *and working*. This one needs that **and a live model call**, which costs money and takes
tens of seconds, and whose output is not deterministic. `check.sh` must stay hermetic, fast and
repeatable, so this is opt-in:

    .venv/bin/pytest -m integration_claude tests/test_install_claude_live.py

**Nesting is safe in this direction, measured.** These tests may themselves run inside a Claude Code
session. `research/claude-code-harness-probe.md` §1 measured the inner direction safe: a nested
`claude` gets its own fresh `CLAUDE_CODE_SESSION_ID`, correctly overridden rather than inherited.
The exposed direction is the other one — a non-Claude-Code process tree *under* a Claude Code
session — and this file is not it.

**What is asserted, and what is deliberately not.** The first test is deterministic: a hook either
ran and reached the service or it did not, and the store's own event rows say which, whatever the
model chose to say. **The other two are not** — both ask a model to call a named tool, and a model
may decline, so both `test_an_installed_mcp_server_becomes_a_tool_the_model_can_call` and
`test_both_clients_resolve_one_session_label` sit on the model-choice side of that boundary. They
are the only places in this repository where a *model's* choice can turn the suite red, which is
stated here rather than discovered on a bad day.
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Final

import pytest

from zikaron.harness.spec import CLAUDE_CODE
from zikaron.install import harness
from zikaron.install import main as install_main
from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME, MCP_SERVER_NAME
from zikaron.service import paths

pytestmark = pytest.mark.integration_claude

#: A cold run pays for a `claude` start, a service start, and a real model turn. Generous on
#: purpose: a timeout here reports as a failure of the install, which is the wrong diagnosis.
_TURN_TIMEOUT: Final = 300.0

#: Distinctive enough that a model repeating it cannot be repeating something else.
_GIST: Final = "zikaron live install check: the installed MCP server is reachable from a real turn"


def _require_claude() -> None:
    """Fail — never skip — when the binary is absent.

    The same argument `test_install_harness.py::_require_kiro` makes: a tier that goes green on the
    one error it exists to catch is worse than no tier, and `conftest.pytest_runtest_makereport`
    converts a skip inside a harness tier into a failure anyway. The message names both causes so
    the reader does not have to guess which one they hit.
    """
    name = CLAUDE_CODE.harness_binary
    assert harness.binary_is_available(name), (
        f"{name!r} is not on PATH. Either this machine has no Claude Code — in which case do not "
        f"run `-m integration_claude` here — or `HarnessSpec.harness_binary` names the wrong "
        f"binary, in which case every Claude Code install refuses and no other test can see it."
    )


def _install(project: Path) -> None:
    status = install_main.main(["--project", str(project), "--harness", "claude-code"])
    assert status == 0, "the install refused on a directory it had just been given"


def _turn(project: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    """One headless turn in `project`, with this process's own harness variables removed.

    `conftest._no_inherited_harness_environment` has already emptied `os.environ` of them for the
    test process; passing a copy keeps that true for the child, so the `claude` we spawn exports its
    own session id rather than inheriting an outer one. That is the difference between measuring
    this install and measuring the session that happens to be running the suite.
    """
    return subprocess.run(  # noqa: S603 — the argv is this file's own constant.
        [CLAUDE_CODE.harness_binary, "-p", prompt],
        cwd=project,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=_TURN_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _events(project: Path) -> list[tuple[str, str, str]]:
    """`(session_id, client_kind, kind)` for every event, read-only.

    Read directly rather than through the service: the service may still be running, and a reader
    that has to coordinate with it would be testing the reader.
    """
    db_path = paths.store_db_path(paths.store_dir(project))
    assert db_path.is_file(), (
        "no store was created. The `SessionStart` entry did not run, or ran and could not reach "
        f"the service — check {paths.hook_log_path(paths.store_dir(project))}."
    )
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute("SELECT session_id, client_kind, kind FROM event")
        ]
    finally:
        connection.close()


class TestTheHarnessActsOnWhatWeInstalled:
    def test_the_prompt_hook_fires_and_reaches_the_service(self, tmp_path: Path) -> None:
        """The push half, end to end through the harness, and it does not depend on the model.

        `surface_call` is emitted by the **service**, on a request the **hook** made, on a trigger
        the **harness** fired, from an entry the **installer** wrote. Nothing short of all four
        being right produces this row — and a model that answers the prompt with nonsense produces
        it just the same, which is why this is the assertion the tier leans on.
        """
        _require_claude()
        project = tmp_path / "project"
        project.mkdir()
        _install(project)

        result = _turn(project, "Reply with the single word: ok")

        events = _events(project)
        hook_kinds = {kind for _, client, kind in events if client == "hook"}
        assert "surface_call" in hook_kinds, (
            f"the UserPromptSubmit entry never reached the service. The hook records its own "
            f"failures at {paths.hook_log_path(paths.store_dir(project))} — read that first. "
            f"claude exited {result.returncode}; stderr: {result.stderr[-800:]!r}"
        )

    def test_an_installed_mcp_server_becomes_a_tool_the_model_can_call(
        self, tmp_path: Path
    ) -> None:
        """The pull/write half: a server registered in `.mcp.json` becomes a tool a model can call.

        **What this cannot establish, stated because an earlier docstring claimed it.** It does
        *not* check that `enabledMcpjsonServers` and `permissions.allow` do their jobs.
        `research/claude-code-installer-probe.md` §8 measured that a **headless** run approves
        everything — so this test passes identically if the installer omits both approval keys,
        and a claim about them here would be vacuous in exactly the way the break-the-code
        discipline exists to catch. Those two keys were measured interactively instead
        (`research/claude-code-dogfood-checkpoint.md` §1), and their *contents* are pinned
        hermetically by `test_the_installed_settings_name_this_harness_own_triggers` below.

        What is left is still worth a live turn, and nothing else in the repository has it:
        registration → a tool the model can **name and call**, through the file the installer wrote.

        The prompt names the tool in the `mcp__<server>__<tool>` form because that is the form the
        model sees (`design/harness.md` §"Tool names are a substitution point"), and because the
        same measurement found these tools arrive **deferred** — a model that cannot name a tool
        exactly may not be able to load it at all.
        """
        _require_claude()
        project = tmp_path / "project"
        project.mkdir()
        _install(project)

        result = _turn(
            project,
            "Call the tool mcp__zikaron__zikaron_memory_remember exactly once, with gist "
            f"{_GIST!r} and content 'Written by the Zikaron live install test.' "
            "Then reply with the single word: done. Do not do anything else.",
        )

        events = _events(project)
        kinds = {(client, kind) for _, client, kind in events}
        assert ("mcp", "remember") in kinds, (
            "the model did not reach the installed MCP server. If the store exists and the hook "
            "fired, the install is fine and this is a model or approval failure, not a packaging "
            f"one — check `/mcp` interactively. claude exited {result.returncode}; "
            f"stderr: {result.stderr[-800:]!r}"
        )

    def test_both_clients_resolve_one_session_label(self, tmp_path: Path) -> None:
        """Link coverage 1.0, established through the harness rather than argued from a variable.

        `design/schema.md` §"Linked sessions" says the two cross-client signals are only computable
        when the hook and the MCP client agree on `session_id`, and that under Claude Code this
        holds because `CLAUDE_CODE_SESSION_ID` is exported into every spawned process. That is a
        claim about the harness, so only the harness can check it: here both clients run inside one
        real session and their rows have to carry one label.
        """
        _require_claude()
        project = tmp_path / "project"
        project.mkdir()
        _install(project)

        result = _turn(
            project,
            "Call the tool mcp__zikaron__zikaron_memory_search exactly once with the query "
            "'anything', "
            "then reply with the single word: done.",
        )

        events = _events(project)
        assert result.returncode == 0 or events, (
            f"claude exited {result.returncode} and wrote no events; "
            f"stderr: {result.stderr[-800:]!r}"
        )
        hook_sessions = {session for session, client, _ in events if client == "hook"}
        mcp_sessions = {session for session, client, _ in events if client == "mcp"}
        assert hook_sessions, "no hook events at all — see the push test for the diagnosis"
        assert mcp_sessions, "no mcp events at all — see the tool test for the diagnosis"
        assert hook_sessions == mcp_sessions, (
            "the hook and the MCP client resolved different session labels, so every cross-client "
            f"signal is uncomputable for this session. hook={sorted(hook_sessions)} "
            f"mcp={sorted(mcp_sessions)}"
        )


def test_the_installed_settings_name_this_harness_own_triggers(tmp_path: Path) -> None:
    """A cheap guard on the file itself, so a failure above can be localised.

    If the three tests above fail together, the question is whether we wrote the wrong file or the
    harness ignored the right one. This answers the first half without a model call.

    **It also pins the two approval keys, and that is the only place they can be pinned.** A live
    turn cannot check them: headless approves everything (`installer-probe` §8), so a run passes
    identically whether or not they were written. Their *effect* was measured interactively
    (`dogfood-checkpoint` §1) and cannot be re-measured from a test at all; their *presence and
    contents* are checkable here, and that is what guards against the one drift that would be
    silent in both directions — an install that quietly stops writing them.
    """
    _require_claude()
    project = tmp_path / "project"
    project.mkdir()
    _install(project)

    settings = json.loads((project / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    subagent_trigger = CLAUDE_CODE.subagent_start_trigger
    assert subagent_trigger is not None, (
        "this harness is the one that has a subagent trigger; if that ever stops being true, the "
        "write policy stops reaching subagents and this file is the wrong place to find out."
    )
    assert set(settings["hooks"]) == {
        CLAUDE_CODE.spawn_trigger,
        CLAUDE_CODE.prompt_trigger,
        subagent_trigger,
    }
    assert set(settings["enabledMcpjsonServers"]) == {MCP_SERVER_NAME, CONSOLIDATOR_AGENT_NAME}, (
        "the load-time approval key lost a server. Nothing live can catch this — a headless run "
        "approves everything — so an install that stopped writing it would look fine everywhere "
        "except on a real user's first session, where the server silently never loads."
    )
    assert set(settings["permissions"]["allow"]) == {
        f"mcp__{MCP_SERVER_NAME}",
        f"mcp__{CONSOLIDATOR_AGENT_NAME}",
    }, "the per-call approval key lost a server; every write would prompt on a real machine"
