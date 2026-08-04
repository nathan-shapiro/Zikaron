"""Everything install asks the installed kiro harness, and nothing else talks to it.

Two questions, and the reason they are here rather than inline in `main.py` is that both are
*measurements of the local machine* — the answers differ per install, and a test can substitute this
module's two functions without simulating a CLI.

`architecture.md` §"The install contract" is normative, including the measured reason the second
question cannot be answered by the obvious command: `kiro-cli agent validate` accepts an unknown
`model` silently, so an installer that relied on it would leave the consolidator's model — the one
variable the design asks us to hold fixed and measure — set by a silent fallback instead.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

#: The harness binary every shipped entry ultimately depends on. Resolved through `PATH` rather than
#: pinned to a path: unlike Zikaron's own console scripts — which must name the interpreter they
#: were
#: installed into — this is the user's own kiro, and whichever one their shell finds is the one that
#: will run the hooks.
KIRO_BINARY: Final = "kiro-cli"

#: Every harness call is bounded. A hung `kiro-cli` must fail the install loudly rather than leave a
#: terminal sitting on a subprocess with no output: generous enough for a cold start on a slow
#: machine, short enough that "it stopped" is distinguishable from "it is thinking".
_TIMEOUT_SECONDS: Final = 60.0


class InstallError(Exception):
    """An install could not proceed, with a message written for whoever ran the command.

    Deliberately **not** `ZikaronError`: §7 of `coding-standards.md` makes that type the carrier of
    the design's numeric *wire* codes, and every one of them describes something a client asked the
    service to do. An absent `kiro-cli`, an unknown model id or a file that already exists are none
    of those — giving them wire codes would put values on that contract that no RPC can ever return.
    """


def harness_is_available() -> bool:
    """Whether `kiro-cli` is on `PATH` at all."""
    return shutil.which(KIRO_BINARY) is not None


def available_model_ids() -> frozenset[str]:
    """Every model id this harness will accept, from `kiro-cli chat --list-models -f json`.

    The one authority for a model id, because nothing else on the machine is: the agent-config
    validator checks schema only, and the harness's own documented behaviour on an unavailable model
    is to fall back to its default — which is exactly the silent substitution
    `architecture.md`'s no-silent-fallback rule exists to prevent.

    Raises:
        InstallError: the binary is absent, failed, timed out, or answered something this function
            cannot read as a model list. Every one of those is refused rather than treated as "no
            models found", because an empty set would make the caller reject a perfectly good id
            for the wrong reason.
    """
    if not harness_is_available():
        raise InstallError(
            f"{KIRO_BINARY} is not on PATH. The hook and MCP entries this installs are read by "
            f"{KIRO_BINARY} itself, so an install cannot be verified without it."
        )
    try:
        completed = subprocess.run(  # noqa: S603 — a fixed argv, no shell, nothing interpolated.
            [KIRO_BINARY, "chat", "--list-models", "-f", "json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"could not run `{KIRO_BINARY} chat --list-models`: {exc}") from exc
    if completed.returncode != 0:
        raise InstallError(
            f"`{KIRO_BINARY} chat --list-models` exited {completed.returncode}: "
            f"{completed.stderr.strip() or '(no stderr)'}"
        )
    return _parse_model_ids(completed.stdout)


def _parse_model_ids(raw: str) -> frozenset[str]:
    """The `model_id` of every entry in a `--list-models -f json` payload.

    Reads `model_id` specifically, not `model_name`: the two are equal for every model this harness
    currently lists, which is precisely why picking either at random would work today and could stop
    working silently. `model` in an agent config is an id.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(
            f"`{KIRO_BINARY} chat --list-models -f json` was not JSON: {exc}"
        ) from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise InstallError("model list JSON has no `models` array")
    ids = {
        entry["model_id"]
        for entry in models
        if isinstance(entry, dict) and isinstance(entry.get("model_id"), str)
    }
    if not ids:
        raise InstallError("model list JSON carried no readable `model_id` values")
    return frozenset(ids)


def validate_agent_config(path: Path) -> str | None:
    """Run `kiro-cli agent validate` on a written config; return its complaint, or `None` if clean.

    A **report**, not a gate, and the distinction is the point: this catches a schema mistake in
    what
    we just wrote, while the model check above catches the one thing this command provably does not.
    Returning the harness's own text rather than a boolean keeps its diagnostics — which name the
    offending field — instead of replacing them with "invalid".
    """
    try:
        completed = subprocess.run(  # noqa: S603 — a fixed argv, no shell; only `path` varies.
            [KIRO_BINARY, "agent", "validate", "--path", str(path)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run `{KIRO_BINARY} agent validate`: {exc}"
    if completed.returncode == 0:
        return None
    return (completed.stderr.strip() or completed.stdout.strip()) or (
        f"`{KIRO_BINARY} agent validate` exited {completed.returncode} with no output"
    )
