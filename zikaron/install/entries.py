"""The JSON Zikaron adds to a kiro configuration: hook entries, the MCP server, and the
consolidator agent config.

`architecture.md` §"Two hook formats, both inside the stable agent config" and §"The install
contract" are normative.

Dicts are the return type here and that is deliberate rather than a lapse from
`coding-standards.md` §2's types-not-dicts rule: these functions *are* the serialization boundary —
their output goes straight to `json.dump` into a file whose schema belongs to the harness, not to
us.
The typed values live on the input side (`Commands`, `HookFormat`), which is where a mistake would
otherwise be silent.
"""

import os
import shlex
import sysconfig
from enum import StrEnum
from pathlib import Path
from typing import Final, NamedTuple

from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS, MAX_OUTPUT_SIZE, TIMEOUT_MS
from zikaron.install.assets import consolidator_prompt, identity_vocabulary
from zikaron.mcp.tool_names import CONSOLIDATOR_TOOLS, PRIMARY_TOOLS

#: The `mcpServers` key, and therefore the `@zikaron` selector. One declaration, because the name
#: appears in three places that must agree — the server map, `tools`, and `allowedTools` — and a
#: mismatch in the second silently produces an agent with no memory tools at all (measured; see
#: `TOOL_SELECTOR`).
MCP_SERVER_NAME: Final = "zikaron"

#: How an agent config selects this server's tools. **Configuring `mcpServers` is not sufficient**,
#: which was measured rather than inferred: an agent carrying the server entry and a `tools` list
#: that did not name it reported its available tools as `code, dummy, execute_bash, fs_read,
#: fs_write, glob, grep, todo_list, use_subagent` — the whole memory surface absent, with no warning
#: anywhere. `tools` selects; `mcpServers` only configures.
TOOL_SELECTOR: Final = f"@{MCP_SERVER_NAME}"

#: The consolidator's own config file name, and hence its agent name (kiro derives one from the
#: other). Named in `architecture.md`'s distribution table, so it is not ours to vary.
CONSOLIDATOR_AGENT_NAME: Final = "zikaron-consolidator"

_HOOK_SCRIPT: Final = "zikaron-hook"
_MCP_SCRIPT: Final = "zikaron-mcp"

#: Kiro's two trigger names, **read from the seam rather than spelled again**. A review caught this
#: file restating them: the harness-table drift guard covers spec↔design and nothing covered
#: spec↔installer, so a trigger renamed in the spec would move the *hook* (whose tests read the
#: spec) while the *installer* kept writing the old name — an installed config naming a trigger the
#: hook does not recognise, which fails as no output and exit 0.
_AGENT_SPAWN: Final = KIRO.spawn_trigger
_USER_PROMPT_SUBMIT: Final = KIRO.prompt_trigger

#: Shared by both harnesses' consolidator definitions, which is why it is a constant rather than a
#: literal inside either builder: it is the text a harness reads to decide the agent is relevant,
#: and two copies would let one harness's install drift into describing a different agent.
_CONSOLIDATOR_DESCRIPTION: Final = (
    "Consolidates Zikaron's memory journal into long-term records. Spawned by the "
    "zikaron-consolidate skill; carries the four consolidation tools and nothing else."
)

#: Claude Code's three triggers, derived from the seam for the reason above. `SubagentStart` has no
#: kiro counterpart and is not optional: M14 built the write-policy-per-subagent path behind it, and
#: kiro reaches the same place by firing its ordinary hooks *for* a subagent session instead.
#: Registering only the first two would leave that path dead with nothing failing — no error, no log
#: line, just subagents that never see the policy. The `is not None` filter is a type narrowing and
#: not a real branch: this tuple is Claude Code's, and Claude Code has all three.
_CLAUDE_TRIGGERS: Final = tuple(
    trigger
    for trigger in (
        CLAUDE_CODE.spawn_trigger,
        CLAUDE_CODE.prompt_trigger,
        CLAUDE_CODE.subagent_start_trigger,
    )
    if trigger is not None
)


class HookFormat(StrEnum):
    """Which of the two formats the harness accepts to write.

    Not a preference: a config already using one format must be merged in that format, because the
    harness rewrites the file in whichever it read and a mixed file has no defined meaning.
    """

    OBJECT = "object"
    ARRAY = "array"


class Commands(NamedTuple):
    """The two absolute command paths every shipped entry names.

    Resolved from the running interpreter rather than accepted as strings, so an install cannot
    write a `command` pointing at an interpreter that does not have Zikaron in it — which would fail
    at hook time, in a subprocess whose stderr the harness does not surface.
    """

    hook: Path
    mcp: Path

    @classmethod
    def from_this_interpreter(cls) -> "Commands":
        """`<venv>/bin/zikaron-hook` and `<venv>/bin/zikaron-mcp` for the interpreter running this.

        `sysconfig.get_path("scripts")` is the same directory `pip install` put those two console
        scripts in, so this resolves correctly under a venv, a `--user` install or a system install
        without needing to know which of the three it is.
        """
        scripts = Path(sysconfig.get_path("scripts"))
        return cls(hook=scripts / _HOOK_SCRIPT, mcp=scripts / _MCP_SCRIPT)

    def missing(self) -> tuple[Path, ...]:
        """Whichever of the two is not an executable file, in path order.

        Checked rather than assumed because the failure is otherwise invisible until a hook fires:
        installing from a source checkout without `pip install` leaves both absent, and a hook whose
        `command` does not exist produces no output on the one channel the harness reads.

        **Executability, not merely existence.** A console script that exists without the execute
        bit
        — a file copied out of a wheel by hand, an install onto a filesystem mounted `noexec` —
        fails
        at exactly the moment this check exists to protect, and `is_file()` alone would pass it.
        """
        return tuple(
            path
            for path in (self.hook, self.mcp)
            if not (path.is_file() and os.access(path, os.X_OK))
        )


def hooks_object(commands: Commands) -> dict[str, list[dict[str, object]]]:
    """The object-format `hooks` value: one entry per trigger, keyed by trigger name.

    Both triggers point at the same executable, which dispatches on `hook_event_name` from its own
    stdin payload — kiro's hook fields carry no per-trigger argument mechanism, so the payload is
    the
    only place the trigger name is available (`zikaron/hook/main.py`).
    """
    return {
        _AGENT_SPAWN: [_object_entry(commands.hook)],
        _USER_PROMPT_SUBMIT: [_object_entry(commands.hook)],
    }


def hooks_array(commands: Commands) -> list[dict[str, object]]:
    """The array-format `hooks` value: a flat list carrying its own `trigger` per entry."""
    return [
        _array_entry(commands.hook, _AGENT_SPAWN),
        _array_entry(commands.hook, _USER_PROMPT_SUBMIT),
    ]


def hooks_value(commands: Commands, hook_format: HookFormat) -> object:
    """Whichever of the two the caller asked for, for a caller that only serializes it.

    Two typed builders and this one-line dispatcher, rather than a single function returning a
    union:
    `writer.py` merges into an existing value and needs the concrete type to do it, while the
    fragment printer only hands the result to `json.dumps` and does not care.
    """
    if hook_format is HookFormat.OBJECT:
        return hooks_object(commands)
    return hooks_array(commands)


def hook_command_string(hook_command: Path) -> str:
    """The `command` string for a hook entry: the executable path, **shell-quoted**.

    Measured, not inferred: this field is run through a shell. An unquoted
    `/home/me/My Projects/.venv/bin/zikaron-hook` produced
    `/bin/bash: line 1: /home/me/My: No such file or directory` and exit 127 from the real harness,
    with the hook contributing nothing — no write policy on spawn, no memories on a prompt — while
    the
    install itself had exited 0, because the path *is* an executable file and every preflight
    passed.
    A single-quoted path was then measured to run correctly.

    So a project or venv directory containing a space is enough to break the whole install, with no
    attacker and nothing exotic. `shlex.quote` is applied here rather than at each call site so both
    formats are quoted by construction.

    `mcpServers`' own `command` is deliberately **not** quoted: that field takes a program and a
    separate `args` array, which is exec-style rather than shell-style, and quoting it would make
    the
    harness look for a file whose name contains the quotes.
    """
    return shlex.quote(str(hook_command))


def _object_entry(hook_command: Path) -> dict[str, object]:
    """One object-format entry: the command, and both limits stated rather than inherited."""
    return {
        "command": hook_command_string(hook_command),
        "timeout_ms": TIMEOUT_MS,
        "max_output_size": MAX_OUTPUT_SIZE,
    }


def _array_entry(hook_command: Path, trigger: str) -> dict[str, object]:
    """One array-format entry.

    `max_output_size` is **absent**, and that is a fact about the format rather than an omission:
    the harness documents that field for object-format entries only. An installer that added it here
    anyway would be writing a key with no documented meaning and no way to tell whether it took
    effect — so an array-format install inherits the 10240-byte default, which is why
    `writer.py` reports that difference instead of hiding it.
    """
    return {
        "name": f"zikaron-{trigger}",
        "trigger": trigger,
        "action": {"type": "command", "command": hook_command_string(hook_command)},
        # Seconds here, milliseconds in the object entry above — the one place kiro's two formats
        # disagree about a value rather than a shape. Both read the same canonical seconds constant
        # rather than converting from each other, so neither can drift into the other's unit.
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def mcp_servers_value(commands: Commands, *, mode: str) -> dict[str, object]:
    """The `mcpServers` entry for one mode: `primary` for a user's own agent, `consolidator` for
    ours."""
    return {
        MCP_SERVER_NAME: {
            "command": str(commands.mcp),
            "args": ["--mode", mode],
        }
    }


def claude_tool_vocabulary() -> dict[str, str]:
    """Bare tool name → the `mcp__<server>__<tool>` form Claude Code serves and shows the model.

    Built from the two tool sets and the two server names rather than listed, so a tool added to
    `zikaron.mcp.tool_names` is covered here automatically and a *renamed* one fails
    `assets._guard_known_tools` loudly instead of shipping a name nothing serves.
    """
    return {
        **{name: f"mcp__{MCP_SERVER_NAME}__{name}" for name in PRIMARY_TOOLS},
        **{name: f"mcp__{CONSOLIDATOR_AGENT_NAME}__{name}" for name in CONSOLIDATOR_TOOLS},
    }


def claude_hooks_value(commands: Commands) -> dict[str, list[dict[str, object]]]:
    """The `hooks` value for `.claude/settings.local.json`: three triggers, one command each.

    The doubled nesting is the harness's own and was confirmed by running it: an event maps to a
    list of *groups*, each carrying an optional `matcher` and its own inner `hooks` list
    (`research/claude-code-installer-probe.md` §1). No `matcher` is written — `UserPromptSubmit`
    accepts none at all, and the other two must fire for every session and every subagent, which is
    what omitting it means.

    `timeout` is **seconds** here, measured rather than assumed, and `command` is *not*
    shell-quoted: unlike kiro's hook field this is not documented as passing through a shell, and
    quoting a path the harness execs directly would make it look for a file whose name contains the
    quotes — the same reasoning `mcp_servers_value` already applies to its own `command`.
    """
    entry: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": str(commands.hook),
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
        ]
    }
    return {trigger: [entry] for trigger in _CLAUDE_TRIGGERS}


def claude_mcp_servers_value(commands: Commands) -> dict[str, object]:
    """Both servers, for `.mcp.json`.

    Two entries rather than kiro's one, and not a stylistic difference: a server must be registered
    **session-wide** to be reachable by any subagent at all, so the consolidator's server cannot
    live inside the consolidator's own definition the way it does under kiro. That is the same fact
    that makes D32's other half unenforceable here, reported by the installer rather than hidden.
    """
    return {
        **mcp_servers_value(commands, mode="primary"),
        CONSOLIDATOR_AGENT_NAME: {
            "command": str(commands.mcp),
            "args": ["--mode", "consolidator"],
        },
    }


def consolidator_agent_markdown(commands: Commands, *, model: str) -> str:
    """The whole `.claude/agents/zikaron-consolidator.md` — YAML frontmatter, prompt as body.

    Three things differ from kiro's JSON and each is measured rather than translated:

    - **`tools` is a whole-server wildcard**, not the four verbs by name. An unrecognised tool name
      in frontmatter refuses the spawn outright with "would be spawned with zero tools"
      (`claude-code-harness-probe.md` §6), so an explicit list is a second declaration of a fact
      `mcp/consolidator.py` owns whose drift mode is a consolidator that will not start. The
      wildcard was measured to grant that server's tools and to **exclude** the primary server's
      `search`/`fetch` (`installer-probe` §7), which is the whole of what D7 needs.
    - **No `mcpServers` block.** A frontmatter `mcpServers:` key is silently ignored (probe §6);
      registration is session-wide in `.mcp.json` or it does not happen.
    - **The model may be an alias**, because this harness refuses an unknown id loudly at spawn
      rather than substituting its default. `harness.md` §"The consolidator's model".

    `commands` is unused and stays in the signature deliberately: it keeps this builder's shape
    identical to `consolidator_agent_config`'s, so the two targets call one interface, and the fact
    that Claude Code needs no per-agent server registration is visible as an *unused argument* here
    rather than as an asymmetry the caller has to know about.
    """
    del commands
    frontmatter = "\n".join(
        (
            "---",
            f"name: {CONSOLIDATOR_AGENT_NAME}",
            f"description: {_CONSOLIDATOR_DESCRIPTION}",
            f"model: {model}",
            "tools:",
            f"  - mcp__{CONSOLIDATOR_AGENT_NAME}",
            "---",
        )
    )
    return f"{frontmatter}\n\n{consolidator_prompt(claude_tool_vocabulary())}\n"


def consolidator_agent_config(commands: Commands, *, model: str) -> dict[str, object]:
    """The whole `zikaron-consolidator.json`.

    Every field is a decision `architecture.md` §"The install contract" states, and three are worth
    re-reading here because their absence would be invisible:

    - `tools` is `@zikaron` alone — and it has to be there at all, since `mcpServers` configures a
      server while `tools` is what selects its tools. No `read`, `write` or `shell`: the design's
      claim is that *code*
      selects the candidates, and a consolidator that can read the repository can wander outside the
      group it was handed.
    - `allowedTools` repeats it, because a subagent has no user to answer a permission prompt — an
      available-but-not-allowed tool is one that fails at the moment it is needed. (The primary
      agent's own config gets the same treatment by default, for a different reason: see
      `writer._selecting`.)
    - there is **no** `hooks` key. This session must not fire the push hook (it has no `search` to
      spend a result on) and must not print the write policy (its policy is this prompt).
    """
    return {
        "name": CONSOLIDATOR_AGENT_NAME,
        "description": _CONSOLIDATOR_DESCRIPTION,
        "model": model,
        "prompt": consolidator_prompt(identity_vocabulary()),
        "tools": [TOOL_SELECTOR],
        "allowedTools": [TOOL_SELECTOR],
        "mcpServers": mcp_servers_value(commands, mode="consolidator"),
    }
