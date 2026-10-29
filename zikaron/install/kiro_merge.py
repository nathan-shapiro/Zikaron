"""Merging Zikaron into a user's own kiro agent profile, the one file a kiro install does not own.

`architecture.md` §"The install contract" is normative, and `design/harness.md` §"The installer's
two targets" for the profile shapes kiro's V3 engine reads. `plan_kiro_merge` reads and refuses and
writes nothing; `writer.commit_merge` writes.

**Three shapes, told apart by predicates of this module's own**, named to stay clear of `kiro-cli
agent upgrade`'s words, whose "already universal" also covers a profile with no trust field:

- *V2-only*: a V2 trust field and no `permissions`. V3 refuses such a profile, so this does, and
  converting the user's trust settings is left to the harness's own upgrader.
- *universal*: `permissions` and `allowedTools` both, which is what `kiro-cli agent create` writes.
  Both halves gain Zikaron's grant, so a rebuild of the V3 half from the V2 one keeps it.
- *V3-only*: every other profile. Only `permissions` gains the grant.
"""

import enum
import json
import shlex
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import Final, NamedTuple

from zikaron.install.assets import SKILL_NAME
from zikaron.install.code_knowledge import DOCUMENT_SKILL_NAME, DOCUMENTER_AGENT_NAME
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    TOOL_SELECTOR,
    Commands,
    hooks_array,
    mcp_servers_value,
    primary_rules,
)
from zikaron.install.harness import InstallError
from zikaron.install.ownership import ANOTHER_INSTALL, merged_server, refuse_conflicting
from zikaron.install.writer import MergePlan, Plan, Targets, guard_backup_path

#: How a skill is named in `resources`. Skills are progressively loaded, unlike `file://` entries.
_SKILL_SCHEME: Final = "skill://"

#: The `tools` entry selecting every tool, which `kiro-cli agent create` writes.
_EVERY_TOOL: Final = "*"

#: The fields whose edit makes `kiro-cli agent upgrade` call a profile carrying `kiroUpgrade` out of
#: sync.
_SYNCED_FIELDS: Final = ("tools", "permissions", "allowedTools")

#: The planner's default documents directory, which the write rule below is scoped to.
DOCUMENTS_DIRECTORY: Final = "code-knowledge"


class _ParentGrant(NamedTuple):
    """A capability the documenter uses that kiro also requires of the profile spawning it."""

    capability: str
    act: str
    rule: str


#: The read rule is the one `kiro-cli agent create` writes; the write rule, scoped to the documents
#: directory, was measured to let a spawned documenter write (`research/kiro-v3-probe.md` §28).
_DOCUMENTER_PARENT_GRANTS: Final = (
    _ParentGrant(
        "fs_read",
        "reading each source",
        '{"capability": "fs_read", "match": ["./**"], "effect": "allow"}',
    ),
    _ParentGrant(
        "fs_write",
        "writing each document",
        f'{{"capability": "fs_write", "match": ["./{DOCUMENTS_DIRECTORY}/**"], "effect": "allow"}}',
    ),
)

#: kiro's camelCase trigger names, by the V3 name each means. `kiro-cli agent upgrade` keeps the
#: camelCase spelling in the entries it converts, so ownership compares triggers through this map:
#: compared by spelling, a converted `agentSpawn` entry would sit beside a new `SessionStart` one
#: and the hook would run twice per session.
_V3_TRIGGER: Final = {
    "agentSpawn": "SessionStart",
    "AgentSpawn": "SessionStart",
    "userPromptSubmit": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "stop": "Stop",
}


class ProfileShape(enum.Enum):
    """Which engines' fields an agent profile carries, as this installer reads them."""

    V2_ONLY = "V2-only"
    UNIVERSAL = "universal"
    V3_ONLY = "V3-only"


def profile_shape(document: Mapping[str, object]) -> ProfileShape:
    """The shape of a parsed profile.

    A V2 trust field is an `allowedTools` that is set, or a `toolsSettings` that is a non-empty
    object. `kiro-cli agent create` writes `"toolsSettings": {}`, and the upgrader calls a profile
    with no trust field universal, so counting `{}` would refuse a profile nothing can convert.
    """
    has_permissions = not _is_unset(document, "permissions")
    has_allowed_tools = not _is_unset(document, "allowedTools")
    settings = document.get("toolsSettings")
    has_tools_settings = isinstance(settings, dict) and bool(settings)
    if not has_permissions and (has_allowed_tools or has_tools_settings):
        return ProfileShape.V2_ONLY
    if has_permissions and has_allowed_tools:
        return ProfileShape.UNIVERSAL
    return ProfileShape.V3_ONLY


def plan_kiro_merge(path: Path, plan: Plan, targets: Targets) -> MergePlan:
    """Check a user's agent profile and build the document a merge would write. Writes nothing.

    Raises:
        InstallError: the file is missing or not a JSON object; it is a V2-only profile; it carries
            a field in a shape this cannot merge into; its object-format `hooks` hold an entry of
            the user's; or it already carries a Zikaron entry another install owns. The last is the
            one worth refusing loudly: its paths may point at a venv that no longer has Zikaron in
            it, and replacing it silently would hide that the user has two installs.
    """
    document = _load_agent_config(path)
    _guard_mergeable_shapes(document, path=path)
    shape = profile_shape(document)
    if shape is ProfileShape.V2_ONLY:
        raise InstallError(
            f"{path} is a V2 agent profile: it carries `allowedTools` or `toolsSettings` and no "
            "`permissions` block, and kiro's V3 engine refuses such a profile and runs its default "
            "agent instead. "
            f"Convert it with `kiro-cli agent upgrade {path.parent}`, then re-run this install. "
            "Converting your trust settings is the harness's job, so this does not do it."
        )
    if shape is ProfileShape.UNIVERSAL:
        _guard_crew_shape(document, path=path)
    _guard_object_hooks(document, plan.commands, path=path)
    _guard_existing_entries(document, plan.commands, path=path, force=plan.force)
    guard_backup_path(path)

    merged = dict(document)
    merged["hooks"] = _merged_hooks(document, plan.commands)
    merged["mcpServers"], server_notes = _merged_servers(document, plan.commands, force=plan.force)
    if _EVERY_TOOL not in _string_list(document.get("tools")):
        merged["tools"] = _selecting(document, "tools")
    if plan.trust_tools:
        merged["permissions"] = _merged_permissions(document)
        if shape is ProfileShape.UNIVERSAL:
            merged["allowedTools"] = _selecting(document, "allowedTools")
    crew_notes: list[str] = []
    if shape is ProfileShape.UNIVERSAL:
        settings, crew_notes = _merged_tools_settings(document)
        if settings is not None:
            merged["toolsSettings"] = settings
    resources, resource_notes = _merged_resources(document, targets)
    if resources is not None:
        merged["resources"] = resources

    notes = _hook_notes(document, plan.commands)
    notes.extend(server_notes)
    notes.extend(crew_notes)
    notes.extend(resource_notes)
    notes.extend(_grant_notes(document, merged, path=path, trust_tools=plan.trust_tools))
    notes.extend(_out_of_sync_notes(document, merged, path=path, shape=shape))
    return MergePlan(path=path, document=merged, notes=tuple(notes), unchanged=merged == document)


def _load_agent_config(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"could not read {path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise InstallError(f"{path} is not a JSON object")
    return document


def _is_unset(document: Mapping[str, object], key: str) -> bool:
    """Whether `key` carries no value a merge could drop — absent, or explicitly `null`.

    **`null` is how kiro spells *unset*, and it writes it itself**: `kiro-cli agent create` writes
    `prompt` and `model` as `null`, and the agent it wrote runs. Treating a present-but-`null` key
    as a malformed value would refuse the harness's own default output, so the guards below ask this
    rather than `in`.

    It does **not** loosen anything else: a value of the wrong *type* is still refused, because
    that is a thing the user put there and a merge would destroy it to make room.
    """
    return document.get(key, None) is None


def _guard_mergeable_shapes(document: dict[str, object], *, path: Path) -> None:
    """Refuse any shape the merge below would silently drop.

    The merge is written defensively — it filters a hook-map value that is not a list, and treats a
    non-list `tools` as absent — and defensive filtering on a *write* path is data loss with a
    reassuring shape. A value of the wrong type is something the user put there; this cannot know
    what they meant by it, and installing over it would destroy something to make room.
    """
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        for trigger, value in hooks.items():
            if not isinstance(value, list):
                raise InstallError(
                    f"{path} has `hooks.{trigger}` as {type(value).__name__} rather than an array. "
                    "Fix or remove it before installing; this refuses rather than drop it."
                )
    elif not isinstance(hooks, list) and not _is_unset(document, "hooks"):
        raise InstallError(
            f"{path} has a `hooks` value that is neither an object nor an array "
            f"({type(hooks).__name__}). Fix or remove it before installing; this refuses rather "
            "than replace it."
        )
    for key in ("tools", "allowedTools", "resources"):
        value = document.get(key)
        if not _is_unset(document, key) and not isinstance(value, list):
            raise InstallError(
                f"{path} has a `{key}` value that is not an array ({type(value).__name__}). Fix or "
                "remove it before installing; this refuses rather than replace it."
            )
    permissions = document.get("permissions")
    if not _is_unset(document, "permissions") and not isinstance(permissions, dict):
        raise InstallError(
            f"{path} has a `permissions` value that is not an object "
            f"({type(permissions).__name__}). Fix or remove it before installing."
        )
    rules = _as_mapping(permissions).get("rules")
    if rules is not None and not isinstance(rules, list):
        raise InstallError(
            f"{path} has `permissions.rules` as {type(rules).__name__} rather than an array. Fix "
            "or remove it before installing."
        )


def _guard_crew_shape(document: dict[str, object], *, path: Path) -> None:
    """Refuse a `toolsSettings.crew` this cannot merge into rather than replacing it.

    Same rule as every other shape guard here, one level deeper: the crew block gates which agents
    may be spawned, so quietly rebuilding a malformed one could hand the user a config that spawns
    more — or less — than they had written down.
    """
    settings = document.get("toolsSettings")
    if not _is_unset(document, "toolsSettings") and not isinstance(settings, dict):
        raise InstallError(
            f"{path} has a `toolsSettings` value that is not an object "
            f"({type(settings).__name__}). Fix or remove it before installing."
        )
    if not isinstance(settings, dict):
        return
    present = [key for key in _CREW_KEYS if not _is_unset(settings, key)]
    if len(present) > 1:
        raise InstallError(
            f"{path} has both `toolsSettings.crew` and `toolsSettings.agent_crew`. The harness "
            "documents them as aliases for one block and gives no meaning to carrying both, so "
            "this refuses rather than guess which one it reads. Keep one and re-run."
        )
    for crew_key in present:
        crew = settings[crew_key]
        if not isinstance(crew, dict):
            raise InstallError(
                f"{path} has a `toolsSettings.{crew_key}` value that is not an object "
                f"({type(crew).__name__}). Fix or remove it before installing."
            )
        for list_key in ("availableAgents", "trustedAgents"):
            if not _is_unset(crew, list_key) and not isinstance(crew[list_key], list):
                raise InstallError(
                    f"{path} has `toolsSettings.{crew_key}.{list_key}` as "
                    f"{type(crew[list_key]).__name__} rather than an array. Fix or remove it "
                    "before installing."
                )


def _guard_object_hooks(document: dict[str, object], commands: Commands, *, path: Path) -> None:
    """Refuse object-format `hooks` holding an entry this install did not write.

    V3 reads that form only as compatibility input, and a key is either an object or an array, so
    Zikaron's array entries cannot sit beside an entry of the user's. The refusal shows the user's
    entries in the array form, and names the upgrader only for a profile it would convert: one with
    no `permissions`, since it leaves a profile that has them untouched.
    """
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return
    ours = {id(hook.entry) for hook in _recognised_hooks(document, commands)}
    theirs = [
        _as_array_entry(str(trigger), index, entry)
        for trigger, entries in hooks.items()
        for index, entry in enumerate(_as_list(entries))
        if id(entry) not in ours
    ]
    if not theirs:
        return
    remedy = (
        f"`kiro-cli agent upgrade {path.parent}` converts it; run that, then re-run this install."
        if _is_unset(document, "permissions")
        else "Rewrite `hooks` in that form, then re-run this install."
    )
    raise InstallError(
        f"{path} has `hooks` in the object form, holding entries this install did not write. "
        "kiro's V3 engine reads that form only as compatibility input, and Zikaron's entries are "
        "in the array form, so they cannot share the key. In the array form, yours read: "
        f"{json.dumps(theirs)}. {remedy}"
    )


def _as_array_entry(trigger: str, index: int, entry: object) -> object:
    """An object-format entry as the array form states it, for a refusal to show."""
    if not isinstance(entry, dict):
        return entry
    converted: dict[str, object] = {"name": f"{trigger}-{index}", "trigger": _v3(trigger)}
    if "matcher" in entry:
        converted["matcher"] = entry["matcher"]
    converted["action"] = {"type": "command", "command": entry.get("command")}
    timeout_ms = entry.get("timeout_ms")
    if isinstance(timeout_ms, int) and not isinstance(timeout_ms, bool):
        converted["timeout"] = -(-timeout_ms // 1000)
    return converted


def _guard_existing_entries(
    document: dict[str, object], commands: Commands, *, path: Path, force: bool
) -> None:
    """Refuse a config carrying a Zikaron entry that another install owns, unless forced.

    Both halves are checked, because they are installed together: a config carrying another
    install's hook command and no server entry is as much a second install as one carrying both.
    """
    servers = document.get("mcpServers")
    if not _is_unset(document, "mcpServers") and not isinstance(servers, dict):
        raise InstallError(
            f"{path} has an `mcpServers` value that is not an object "
            f"({type(servers).__name__}). Fix or remove it before installing."
        )
    refuse_conflicting(
        servers,
        mcp_servers_value(commands, mode="primary"),
        path=path,
        key="mcpServers",
        force=force,
    )
    if force:
        return
    conflicts = [
        f"{hook.where}: command is {_entry_command(hook.entry)!r}, "
        f"this install writes {str(commands.hook)!r}"
        for hook in _recognised_hooks(document, commands)
        if not _is_owned(hook.entry, commands)
    ]
    if conflicts:
        raise InstallError(
            f"{path} already carries Zikaron hook entries that differ from what this install "
            f"would write ({'; '.join(conflicts)}). {ANOTHER_INSTALL}"
        )


class _RecognisedHook(NamedTuple):
    """An existing entry the merge will replace, beside the entry it replaces it with."""

    where: str
    entry: object
    expected: dict[str, object]


def _recognised_hooks(document: dict[str, object], commands: Commands) -> list[_RecognisedHook]:
    """Every existing entry the merge replaces — the one list the guards and the merge read.

    Recognized by the command's file name read past a leading `exec`, on a trigger matched by
    meaning, and in the array form also by the reserved `name`, so another install's entry is found
    and not left beside this one. **Only on the triggers this install writes**: an entry elsewhere
    has nothing here to replace it with, so it is neither compared nor touched.
    """
    ours = hooks_array(commands)
    by_name: dict[object, dict[str, object]] = {entry["name"]: entry for entry in ours}
    by_trigger: dict[object, dict[str, object]] = {entry["trigger"]: entry for entry in ours}
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        return [
            _RecognisedHook(str(trigger), entry, by_trigger[_v3(trigger)])
            for trigger, entries in hooks.items()
            if _v3(trigger) in by_trigger
            for entry in _as_list(entries)
            if _is_our_command(entry, commands)
        ]
    recognised: list[_RecognisedHook] = []
    for entry in _as_list(hooks):
        if not isinstance(entry, dict):
            continue
        name, trigger = entry.get("name"), entry.get("trigger")
        if isinstance(name, str) and name in by_name:
            recognised.append(_RecognisedHook(name, entry, by_name[name]))
        elif (
            isinstance(trigger, str)
            and _v3(trigger) in by_trigger
            and _is_our_command(entry, commands)
        ):
            recognised.append(_RecognisedHook(trigger, entry, by_trigger[_v3(trigger)]))
    return recognised


def _v3(trigger: object) -> object:
    return _V3_TRIGGER.get(trigger, trigger) if isinstance(trigger, str) else trigger


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _is_owned(entry: object, commands: Commands) -> bool:
    """Whether a recognized hook entry is this install's own: its command, unquoted, is ours."""
    return _entry_command(entry) == str(commands.hook)


def _is_our_command(entry: object, commands: Commands) -> bool:
    """Whether an existing entry is a Zikaron hook, in either form's spelling.

    Matches on the command's **file name**, not the whole path, so a previous install from another
    venv is replaced rather than left beside this one — two `zikaron-hook` entries on one trigger
    would inject two blocks per message, and the stale one would point at an interpreter that may no
    longer have Zikaron installed.
    """
    command = _entry_command(entry)
    return command is not None and Path(command).name == commands.hook.name


def _entry_command(entry: object) -> str | None:
    """The executable an entry runs, in either form's spelling, **unquoted** and read past `exec`.

    Unquoted because the stored string is shell source: what we write is `shlex.quote`'d, so the raw
    value of a Zikaron entry is `exec '/path/to/zikaron-hook'`. A single-token command, once a
    leading `exec` is set aside, is reported as that token; anything else — a pipeline, several
    words, unbalanced quotes — is reported verbatim, since it is not a bare executable path and no
    caller should treat it as one.
    """
    if not isinstance(entry, dict):
        return None
    direct = entry.get("command")
    if not isinstance(direct, str):
        action = entry.get("action")
        nested = action.get("command") if isinstance(action, dict) else None
        direct = nested if isinstance(nested, str) else None
    if direct is None:
        return None
    try:
        words = shlex.split(direct)
    except ValueError:
        # Unbalanced quotes: not something to reinterpret, and the caller compares it as-is.
        return direct
    if words[:1] == ["exec"]:
        words = words[1:]
    return words[0] if len(words) == 1 else direct


def _merged_hooks(document: dict[str, object], commands: Commands) -> list[object]:
    """This install's hook entries, in the array form, folded into whatever the profile had.

    Replacement is keyed on identity rather than appended blindly — the entries
    `_recognised_hooks` finds. Appending instead would give a twice-installed project two hooks per
    trigger, and therefore two injected blocks per user message. An object-format `hooks` reaching
    here holds only Zikaron's entries, `_guard_object_hooks` having refused any other, so none of
    it is kept.
    """
    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        return list(hooks_array(commands))
    replaced = {id(hook.entry) for hook in _recognised_hooks(document, commands)}
    kept = [entry for entry in _as_list(hooks) if id(entry) not in replaced]
    return [*kept, *hooks_array(commands)]


def _hook_notes(document: dict[str, object], commands: Commands) -> list[str]:
    """What replacing this install's own hook entries cost, where they were not what it writes.

    The two readings are indistinguishable from the file — a new default upgrading itself, or a
    hand-edited timeout being reverted — so the entry is rewritten, which serves the first, and the
    fields are named, which serves the second. Another install's entry, replaced under `--force`, is
    not reported: taking it over is what the flag is for.
    """
    if isinstance(document.get("hooks"), dict):
        if not _recognised_hooks(document, commands):
            return []
        return [
            "Zikaron's hook entries were rewritten from the object form into the array form that "
            "kiro's V3 engine reads."
        ]
    notes = []
    for hook in _recognised_hooks(document, commands):
        if not _is_owned(hook.entry, commands) or hook.entry == hook.expected:
            continue
        entry = hook.entry if isinstance(hook.entry, dict) else {}
        fields = ", ".join(
            f"`{key}`"
            for key in sorted(set(entry) | set(hook.expected))
            if entry.get(key) != hook.expected.get(key)
        )
        notes.append(
            f"Zikaron's own hook on {hook.where} differed in {fields} and was replaced — if you "
            "had hand-edited it, re-apply that."
        )
    return notes


def _merged_servers(
    document: dict[str, object], commands: Commands, *, force: bool
) -> tuple[dict[str, object], list[str]]:
    """The `mcpServers` value, merged per key as `.mcp.json` is, and what the merge cost."""
    servers = document.get("mcpServers")
    merged: dict[str, object] = dict(servers) if isinstance(servers, dict) else {}
    notes: list[str] = []
    for name, entry in mcp_servers_value(commands, mode="primary").items():
        merged[name], entry_notes = merged_server(
            merged.get(name),
            entry,
            name=name,
            force=force,
            registered_for="for every session of this agent",
        )
        notes.extend(entry_notes)
    return merged, notes


def _merged_permissions(document: dict[str, object]) -> dict[str, object]:
    """The profile's `permissions`, its `rules` gaining whichever of Zikaron's two it lacks.

    **Written by default, and the reason is the write policy rather than convenience.** Without the
    `mcp` rule every `remember`, `amend` and `retire` interrupts the user for approval, and the
    design's whole write posture is "err toward recording" — the prior art's own measured failure
    was an agent that recorded too *little*. Per-write friction pushes directly against the one
    behavior the store depends on, and it trains a user to click through prompts, which is worse
    than not asking at all. Without the `skill` rule a skill asks before it loads, and headless
    neither loads at all.

    What is being trusted is narrow: tools that read and write rows in SQLite files under the
    project, with no network and no effect outside it, and the loading of two skill files. A
    mistaken write is **recoverable, not undoable** — `retire` withdraws a row from ordinary
    retrieval and leaves it auditable, while an `amend` overwrites prose that nothing restores.
    `--no-trust-tools` leaves both rules out for anyone who wants the prompts.
    """
    permissions = document.get("permissions")
    merged: dict[str, object] = dict(permissions) if isinstance(permissions, dict) else {}
    rules = list(_as_list(merged.get("rules")))
    for rule in primary_rules():
        if rule not in rules:
            rules.append(rule)
    merged["rules"] = rules
    return merged


def _grant_notes(
    document: dict[str, object], merged: dict[str, object], *, path: Path, trust_tools: bool
) -> list[str]:
    """What the merge granted, and what it left for the user to grant."""
    notes: list[str] = []
    if merged.get("tools") != document.get("tools"):
        notes.append(
            f"Added `{TOOL_SELECTOR}` to {path.name}'s `tools` — without it Zikaron's tools are "
            "simply absent, since `mcpServers` configures the server and `tools` selects from it."
        )
    existing_rules = _as_list(_as_mapping(document.get("permissions")).get("rules"))
    if not trust_tools and any(rule not in existing_rules for rule in primary_rules()):
        notes.append(
            f"--no-trust-tools withheld the two rules this install writes into {path.name}'s "
            "`permissions.rules`: `mcp` over `zikaron/*`, so every Zikaron tool call asks your "
            "permission, and `skill`, so either skill asks before it loads. A headless run "
            "refuses every such question, so there neither skill loads at all. The consolidator's "
            "and the documenter's own `mcp` rules do not make up for it: kiro gives a subagent "
            "only what its parent's rules allow as well."
        )
    unspawnable = [
        agent
        for agent, _skill in _CREW_AGENTS
        if not any(_covers(rule, agent) for rule in _allow_rules(merged, "subagent"))
    ]
    if not _selects(merged, "subagent") or len(unspawnable) == len(_CREW_AGENTS):
        notes.append(
            f"{path.name} does not grant the `subagent` tool. The {SKILL_NAME} and "
            f"{DOCUMENT_SKILL_NAME} skills spawn their agents through it, which takes `subagent` "
            'in `tools` and a `{"capability": "subagent", "effect": "allow"}` rule in '
            "`permissions.rules`: without the rule kiro asks before each spawn, and a headless run "
            "is refused. Granting a built-in tool is your decision, so this install does not do it "
            "for you."
        )
    elif unspawnable:
        names = " or ".join(f"`{agent}`" for agent in unspawnable)
        notes.append(
            f"{path.name}'s `subagent` rules do not match {names}, so kiro asks before each such "
            "spawn, and a headless run is refused. Widening a rule's `match` is your decision."
        )
    if not (_selects(merged, "shell") and _allow_rules(merged, "shell")):
        notes.append(
            f"{path.name} does not grant the `shell` tool. The {DOCUMENT_SKILL_NAME} skill runs "
            "its planner as a shell command, which takes `shell` in `tools` and, as kiro documents "
            'it, a `{"capability": "shell", "effect": "allow"}` rule — a rule not measured here, '
            "unlike the `subagent` one. Granting it is your decision."
        )
    ungranted = [
        grant for grant in _DOCUMENTER_PARENT_GRANTS if not _allow_rules(merged, grant.capability)
    ]
    if ungranted:
        capabilities = " or ".join(f"`{grant.capability}`" for grant in ungranted)
        acts = " and ".join(grant.act for grant in ungranted)
        rules = " and ".join(f"`{grant.rule}`" for grant in ungranted)
        notes.append(
            f"{path.name} has no {capabilities} allow rule, and kiro gives a subagent only what "
            f"its own rules and its parent's both allow. So `{DOCUMENTER_AGENT_NAME}` asks before "
            f"{acts}, and a headless run refuses, leaving the {DOCUMENT_SKILL_NAME} skill without "
            f"its documents. {rules} would allow it, the planner writing under "
            f"`{DOCUMENTS_DIRECTORY}` by default. Granting it is your decision."
        )
    return notes


def _selects(document: Mapping[str, object], tool: str) -> bool:
    """Whether a profile's `tools` selects `tool`."""
    return bool(_string_list(document.get("tools")) & {tool, _EVERY_TOOL})


def _allow_rules(document: Mapping[str, object], tool: str) -> list[dict[str, object]]:
    """The profile's rules allowing `tool`, whatever they match."""
    rules = _as_list(_as_mapping(document.get("permissions")).get("rules"))
    return [
        rule
        for rule in rules
        if isinstance(rule, dict)
        and rule.get("capability") == tool
        and rule.get("effect") == "allow"
    ]


def _covers(rule: Mapping[str, object], agent: str) -> bool:
    """Whether a `subagent` rule allows spawning `agent`: one with no `match` allows every agent,
    which is the rule kiro documents; `kiro-cli agent upgrade` writes one matching the agents a V2
    profile trusted. Patterns are read as globs, as the `mcp` rule's `zikaron/*` is; whether a
    `subagent` rule's `match` globs is unmeasured, and one naming the agent exactly is covered
    under either reading."""
    match = rule.get("match")
    if not isinstance(match, list) or not match:
        return True
    return any(isinstance(pattern, str) and fnmatch(agent, pattern) for pattern in match)


def _out_of_sync_notes(
    document: dict[str, object], merged: dict[str, object], *, path: Path, shape: ProfileShape
) -> list[str]:
    """What editing a profile that carries a `kiroUpgrade` block does to it.

    `kiro-cli agent upgrade` writes that block, and so does `kiro-cli agent create`. Any edit to
    such a profile's `tools`, `permissions` or `allowedTools` makes the upgrader call it out of
    sync, and kiro documents that the TUI then rebuilds its V3 fields from its V2 ones when
    the profile is selected. A universal profile carries Zikaron's grant in both halves; a V3-only
    one carries none of it in its V2 fields, which is why its note says what to do if a rebuild
    drops it.
    """
    if "kiroUpgrade" not in document:
        return []
    if all(merged.get(key) == document.get(key) for key in _SYNCED_FIELDS):
        return []
    consequence = (
        "Zikaron's grant is in both, so the rebuild should keep it."
        if shape is ProfileShape.UNIVERSAL
        else "Its V2 fields carry none of Zikaron's grant, so if Zikaron's tools start asking for "
        "permission after you select it, re-run this install."
    )
    return [
        f"{path.name} carries the `kiroUpgrade` block that `kiro-cli agent create` and `kiro-cli "
        "agent upgrade` both write, and this install edited its `tools`, `permissions` or "
        "`allowedTools`, so the upgrader now calls it out of sync. kiro documents that selecting "
        f"such a profile in the TUI rebuilds its V3 fields from its V2 ones. {consequence}"
    ]


def _merged_resources(
    document: dict[str, object], targets: Targets
) -> tuple[list[object] | None, list[str]]:
    """The agent's `resources` with both skills declared, when declaring them is what makes them
    load.

    Skills reach an agent through `resources`, and by default they *also* arrive without one: the
    harness appends inherited resources (workspace skills among them) to whatever a config declares,
    and only the `chat.disableInheritingDefaultResources` setting turns that off.

    **An entry is written whenever nothing already covers its skill, including when `resources` is
    absent.** Relying on inheritance alone leaves a *deterministically broken* install for the one
    documented configuration where it does not apply, and a warning is not a delivered skill.
    Declaring resources does not disable inheritance (the harness appends to what a config
    declares), so the entry is purely additive and cannot narrow anything; the only cost is a
    redundant declaration in the common case, against a skill that silently fails to load in the
    uncommon one.

    A `skill://.kiro/skills/**/SKILL.md` glob already covers both, so a config carrying one gains
    nothing.

    Coverage is tested with `fnmatch`, whose `*` spans separators and so treats the `**` glob above
    as matching. Both directions of error are benign: over-matching leaves the entry off a config
    that inherits it anyway, and under-matching adds one that is redundant.
    """
    declared = document.get("resources")
    listed: list[object] = list(declared) if isinstance(declared, list) else []
    added: list[object] = []
    notes: list[str] = []
    for skill_file, skill in (
        (targets.skill_file, "consolidation"),
        (targets.document_skill_file, "code documentation"),
    ):
        target = str(skill_file.relative_to(targets.project))
        covered = any(
            isinstance(entry, str)
            and entry.startswith(_SKILL_SCHEME)
            and fnmatch(target, entry.removeprefix(_SKILL_SCHEME))
            for entry in listed
        )
        if not covered:
            added.append(_SKILL_SCHEME + target)
            notes.append(
                f"Added `{_SKILL_SCHEME}{target}` to `resources`, so the {skill} skill is "
                "reachable whether or not inherited resources are switched on."
            )
    if not added:
        return None, []
    return [*listed, *added], notes


#: `toolsSettings.crew` gates which agents the V2 `subagent` tool may spawn. `agent_crew` is a
#: documented alias for the same block, so a config using it must be *updated in place* rather than
#: given a second block whose relationship to the first is undefined.
_CREW_KEYS: Final = ("crew", "agent_crew")

#: The agents Zikaron's skills spawn, each with the skill that spawns it, in the order they are
#: added to a crew.
_CREW_AGENTS: Final = (
    (CONSOLIDATOR_AGENT_NAME, SKILL_NAME),
    (DOCUMENTER_AGENT_NAME, DOCUMENT_SKILL_NAME),
)


def _merged_tools_settings(
    document: dict[str, object],
) -> tuple[dict[str, object] | None, list[str]]:
    """A universal profile's `toolsSettings` with the consolidator and the documenter added to its
    crew, and what to report.

    Fed for the reason `allowedTools` is: the upgrader converts `toolsSettings` into rules, so a
    rebuild of the V3 half reads it. Whether V3 still reads it directly is a conflict in kiro's own
    documentation.

    **`availableAgents` is a restriction, and only extended when it already lists something**: the
    harness documents an absent or empty list as every agent being available, so adding our names
    to an empty one would *narrow* the config to only ours and silently break every other subagent
    the user has. **`trustedAgents` is never written**: it grants a subagent spawn, which is wider
    than Zikaron's own tools.

    Returns `(None, notes)` when there is nothing to change, so an install does not add an empty
    `toolsSettings` block to a config that had none.
    """
    settings = document.get("toolsSettings")
    if not isinstance(settings, dict):
        return None, []
    crew_key = next((key for key in _CREW_KEYS if key in settings), "crew")
    crew = settings.get(crew_key)
    crew_dict: dict[str, object] = dict(crew) if isinstance(crew, dict) else {}
    available = crew_dict.get("availableAgents")
    if not isinstance(available, list) or not available:
        return None, []
    missing = [
        (agent, skill) for agent, skill in _CREW_AGENTS if agent not in _string_list(available)
    ]
    if not missing:
        return None, []
    crew_dict["availableAgents"] = [*available, *(agent for agent, _skill in missing)]
    merged_settings = dict(settings)
    merged_settings[crew_key] = crew_dict
    return merged_settings, [
        f"Added `{agent}` to `toolsSettings.{crew_key}.availableAgents` — the {skill} skill spawns "
        "it, and that list gates which agents may be spawned."
        for agent, skill in missing
    ]


def _selecting(document: dict[str, object], key: str) -> list[object]:
    """The agent's `tools` or `allowedTools`, with `@zikaron` added if it is not already there.

    **`tools` is not optional, and that was measured rather than assumed.** An agent carrying the
    `mcpServers` entry and a `tools` list that did not name the server reported its own tools as
    `code, dummy, execute_bash, fs_read, fs_write, glob, grep, todo_list, use_subagent` — every
    memory tool absent, no warning anywhere. `mcpServers` configures a server; `tools` selects
    from it.
    """
    existing = document.get(key)
    listed: list[object] = list(existing) if isinstance(existing, list) else []
    if TOOL_SELECTOR in _string_list(existing):
        return listed
    return [*listed, TOOL_SELECTOR]


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))
