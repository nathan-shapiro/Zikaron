"""Which model each agent Zikaron ships is installed with.

`design/harness.md` §"The flags, and what each refuses" is normative. `--model` sets every agent,
and an agent's own flag sets that agent alone, over it. A model id is the harness's own, so one
install takes the ids of the harness it is for.
"""

import argparse
from dataclasses import dataclass
from typing import Final

from zikaron.hook.components import Components
from zikaron.install.code_knowledge import ORCHESTRATOR_MODEL
from zikaron.install.harness import InstallError
from zikaron.install.targets import HarnessTarget
from zikaron.install.writer import Plan

_EVERY: Final = "--model"
_CONSOLIDATOR: Final = "--consolidator-model"
_DOCUMENTER: Final = "--documenter-model"
_ORCHESTRATOR: Final = "--orchestrator-model"


def add_model_options(parser: argparse.ArgumentParser) -> None:
    """Add the four model options to the installer's parser."""
    parser.add_argument(
        _EVERY,
        default=None,
        help="the model of every agent Zikaron ships whose own flag is not given (default: this "
        "harness's own for each agent). An id is the harness's own: kiro checks it against its "
        "model list, and Claude Code refuses an unknown one at spawn",
    )
    parser.add_argument(_CONSOLIDATOR, default=None, help="the consolidator's model, over --model")
    parser.add_argument(_DOCUMENTER, default=None, help="the code documenter's model, over --model")
    parser.add_argument(
        _ORCHESTRATOR,
        default=None,
        help="Claude Code only: the code orchestrator's model, over --model",
    )


@dataclass(frozen=True, slots=True)
class ModelFlags:
    """The four model options as given, each `None` where it was not."""

    every: str | None
    consolidator: str | None
    documenter: str | None
    orchestrator: str | None

    @classmethod
    def from_options(cls, options: argparse.Namespace) -> "ModelFlags":
        return cls(
            every=options.model,
            consolidator=options.consolidator_model,
            documenter=options.documenter_model,
            orchestrator=options.orchestrator_model,
        )

    def consolidator_model(self, target: HarnessTarget) -> str:
        return self._chosen(self.consolidator, target.spec.consolidator_model)

    def documenter_model(self, target: HarnessTarget) -> str:
        return self._chosen(self.documenter, target.spec.documenter_model)

    def orchestrator_model(self) -> str:
        return self._chosen(self.orchestrator, ORCHESTRATOR_MODEL)

    def given(self) -> tuple[str, ...]:
        """The options given, as spelled on the command line."""
        options = (
            (_EVERY, self.every),
            (_CONSOLIDATOR, self.consolidator),
            (_DOCUMENTER, self.documenter),
            (_ORCHESTRATOR, self.orchestrator),
        )
        return tuple(option for option, value in options if value is not None)

    def _chosen(self, own: str | None, default: str) -> str:
        # `is None`, never truthiness: an empty value is a mistake for the model check to report,
        # and `or` would replace it with a default.
        if own is not None:
            return own
        if self.every is not None:
            return self.every
        return default


def refuse_unusable_model_flags(
    flags: ModelFlags, *, components: Components, target: HarnessTarget
) -> None:
    """Refuse a model flag that would set nothing, rather than ignore it.

    Raises:
        InstallError: a model flag under a selection that ships no agent, or `--orchestrator-model`
            for a target that ships no orchestrator.
    """
    given = flags.given()
    if given and not components.memory:
        raise InstallError(
            f"--components {components.value} ships no agent, so nothing would use "
            f"{', '.join(given)}. Drop the model flags, or install --components both."
        )
    if flags.orchestrator is not None and not target.ships_orchestrator:
        raise InstallError(
            f"{_ORCHESTRATOR} has no meaning under --harness {target.name}, which ships no code "
            "orchestrator: there the session that invokes the documentation skill runs its loop "
            f"itself. Drop the flag; {_DOCUMENTER} sets the documenter."
        )


def refuse_unknown_models(target: HarnessTarget, plan: Plan) -> None:
    """Check each distinct model the install writes once against its harness.

    Raises:
        InstallError: a model the harness would not serve as asked.
    """
    shipped = [plan.consolidator_model, plan.documenter_model]
    if target.ships_orchestrator:
        shipped.append(plan.orchestrator_model)
    for model in dict.fromkeys(shipped):
        target.refuse_unknown_model(model)
