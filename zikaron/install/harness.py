"""Everything install asks a harness binary, and nothing else talks to one.

**Mostly kiro's**, and one question that is not: `binary_is_available` answers *is this harness
installed at all* for **either** harness, which is what `HarnessTarget.refuse_absent_harness` is
built on. The rest — the model list and the config validator — exist only because kiro substitutes
an unknown model silently, and have no Claude Code counterpart.

The reason these live here rather than inline in `main.py` is that all of them are *measurements of
the local machine* — the answers differ per install, and a test can substitute these functions
without simulating a CLI.

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

from zikaron.harness.spec import KIRO

#: The harness binary every shipped entry ultimately depends on. **Read from the seam** rather than
#: spelled again: `refuse_absent_harness` checks `HarnessSpec.harness_binary` while the calls below
#: *exec* this constant, so two hand-maintained copies could refuse on one name and then run
#: another. That is round 1 finding 5's defect class, and it would have been reintroduced right
#: beside the field created to prevent it.
#:
#: Resolved through `PATH` rather than pinned to a path — that part is about the *lookup*, not the
#: name: unlike Zikaron's own console scripts, which must name the interpreter they were installed
#: into, this is the user's own kiro, and whichever one their shell finds is the one that will run
#: the hooks.
KIRO_BINARY: Final = KIRO.harness_binary

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


def binary_is_available(name: str) -> bool:
    """Whether `name` is on `PATH` at all.

    Presence only — deliberately not a `--version` call. What the installer needs to know is whether
    the harness that will *read* these artefacts exists on this machine, and that question should
    not depend on the binary being authenticated, responsive, or willing to talk. One `PATH` lookup
    also costs nothing on the common path where it succeeds.
    """
    return shutil.which(name) is not None


def harness_is_available() -> bool:
    """Whether `kiro-cli` is on `PATH` at all."""
    return binary_is_available(KIRO_BINARY)


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
    what we just wrote, while the model check above catches the one thing this command provably
    does not.
    Returning the harness's own text rather than a boolean keeps its diagnostics — which name the
    offending field — instead of replacing them with "invalid".

    **A complaint is *output*, not a non-zero exit, and getting that backwards made this function a
    no-op for three milestones.** Measured against kiro-cli 2.16.0, 2026-08-16:

    | config | exit | stdout | stderr |
    |---|---|---|---|
    | valid | 0 | empty | empty |
    | unparseable JSON | **0** | empty | `Error: Json supplied at … is invalid` |
    | wrong field type | **0** | empty | `Error: … invalid type, expected a sequence` |
    | absent file | **0** | empty | `Error: Encountered io error: No such file` |

    The original returned `None` whenever the exit code was zero, which is *always* — so every
    install reported a clean validation regardless of what it had written, and
    `architecture.md`'s claim that this "catches a schema mistake in what we just wrote" was false.
    Nothing caught it because the unit fixtures encoded the belief the real binary contradicts
    (errors ⇒ non-zero exit) and the one test against the real binary asserted `is None`, which
    passed for the wrong reason. The non-zero branch is kept anyway: an exit code this command does
    not currently produce would still mean something went wrong.

    **A false positive here is cheap, which is what makes "any output is a complaint" the right
    predicate rather than a lazy one.** If a future kiro wrote a deprecation warning to stderr on a
    perfectly good config, this would relay it — and the cost is one printed line in an install that
    still succeeds, because this is a *report* and nothing branches on it. The opposite error is the
    one that actually happened: a predicate tuned to avoid noise reported nothing at all, for three
    milestones, and no test could see it. Narrowing this to match `Error:` would trade a real
    guarantee for tidiness against a format nobody has measured.
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
    complaint = completed.stderr.strip() or completed.stdout.strip()
    if completed.returncode != 0:
        return complaint or (
            f"`{KIRO_BINARY} agent validate` exited {completed.returncode} with no output"
        )
    return complaint or None
