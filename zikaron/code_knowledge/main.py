"""`zikaron code-knowledge plan` — which of a module's documents to write, and what to remove.

`design/code-knowledge.md` §3 is normative. One run covers a whole module and prints one JSON
object; a refusal is a non-zero exit and a sentence on standard error. It never connects to the
service — like `install`, it needs neither the service nor a store open — but it refuses a project
with no store, by the predicate every `knowledge` verb uses, since its documents could not be
indexed there.
"""

import argparse
import asyncio
import json
import os
import posixpath
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from zikaron.code_knowledge.apply import apply
from zikaron.code_knowledge.output import rendered
from zikaron.code_knowledge.survey import hashes, module_documents, module_sources
from zikaron.core.code_knowledge.layout import Layout
from zikaron.core.code_knowledge.plan import Survey, plan
from zikaron.core.config.resolution import (
    default_system_config_path,
    project_config_path,
)
from zikaron.core.config.resolution import (
    resolve as resolve_configuration,
)
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge import walk
from zikaron.project.messages import render, stderr
from zikaron.project.resolve import initialize_command, refusal, resolve

_MODULE_INVOCATION: Final = "python -m zikaron.code_knowledge"

DEFAULT_DOCUMENTS: Final = "code-knowledge"
ROLES_DIRECTORY: Final = "code-knowledge"
ROLES_NAME: Final = "roles.md"


class _RefusedError(Exception):
    """An argument names something the planner cannot document."""


def _count(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"{value} is below 0")
    return number


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Plan per-source-file documentation of a module, for the skill that writes it.",
    )
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="VERB")
    planning = verbs.add_parser(
        "plan",
        help="list the documents a module needs written, and remove or move what that implies",
        description=(
            "Judge every document under the module's documents directory against the module's "
            "sources and print one JSON object: the work to write, and the removals and moves "
            "made under --apply or reported without it."
        ),
    )
    planning.add_argument(
        "--module",
        type=Path,
        required=True,
        help="the directory to document, relative to the project root and inside it",
    )
    planning.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project root, holding .zikaron/; default the working directory",
    )
    planning.add_argument(
        "--documents",
        default=DEFAULT_DOCUMENTS,
        help=f"where documents live, relative to the project root; default {DEFAULT_DOCUMENTS}",
    )
    planning.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="admit only sources matching, by path relative to the module; repeatable",
    )
    planning.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="refuse sources matching, by path relative to the module; repeatable",
    )
    planning.add_argument(
        "--limit",
        type=_count,
        default=None,
        metavar="N",
        help="list at most N work items, the first in path order",
    )
    planning.add_argument(
        "--apply",
        action="store_true",
        help=(
            "make the removals and moves, create the listed documents' directories, and write a "
            "listed README's role list under .zikaron/"
        ),
    )
    return parser


def _layout(root: Path, module: Path, documents: str) -> Layout:
    """The module and the documents directory as root-relative paths, or the reason they are not.

    Raises:
        _RefusedError: the module is not a directory inside the root, or lies under a directory
            the corpus walk prunes; or the documents directory is absolute, is or contains the
            root, or contains the module.
    """
    try:
        directory = (root / module).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _RefusedError(f"--module {module}: no such directory in {root}") from error
    if not directory.is_dir():
        raise _RefusedError(f"--module {module} is not a directory")
    if not directory.is_relative_to(root):
        raise _RefusedError(f"--module {module} is outside the project {root}")
    relative = directory.relative_to(root)
    pruned = next((part for part in relative.parts if walk.is_pruned_directory(part)), None)
    if pruned is not None:
        raise _RefusedError(
            f"--module {module} lies under {pruned!r}, a directory the corpus walk prunes, "
            "so its documents could not be indexed"
        )
    if Path(documents).is_absolute():
        raise _RefusedError(f"--documents {documents} must be relative to the project root")
    normalized = posixpath.normpath(documents)
    if normalized == ".":
        raise _RefusedError("--documents may not be the project root itself")
    if root.is_relative_to((root / normalized).resolve()):
        raise _RefusedError(f"--documents {documents} contains the project root")
    layout = Layout(documents=normalized, module=relative.as_posix() if relative.parts else "")
    if layout.documents_contain_module:
        raise _RefusedError(f"--documents {documents} contains --module {module}")
    return layout


def roles_path(store_dir: Path, layout: Layout) -> Path:
    """Where `--apply` writes the role list a listed README is written from: in the store
    directory, which no corpus indexes and git is told to ignore."""
    return store_dir / ROLES_DIRECTORY / layout.module / ROLES_NAME


async def _run(
    root: Path, layout: Layout, rules: walk.WalkRules, limit: int | None, store_dir: Path | None
) -> dict[str, object]:
    """One run, under `--apply` where `store_dir` is given, the role list's home."""
    sources = await module_sources(root, layout, rules)
    hashed = await hashes(root, sources.paths)
    found = await asyncio.to_thread(module_documents, root, layout)
    planned = plan(
        Survey(
            layout=layout,
            sources=hashed,
            documents=found.texts,
            readme=found.readme,
            readme_present=found.readme_present,
        ),
        limit=limit,
    )
    if store_dir is None:
        return rendered(root, sources, planned, None, None)
    roles = roles_path(store_dir, layout)
    applied = await asyncio.to_thread(apply, root, planned, roles, store_dir / ROLES_DIRECTORY)
    return rendered(root, sources, planned, applied, posixpath.relpath(roles, root))


def _print(report: dict[str, object]) -> None:
    """Print the report on one line, paths as they are — escaped only where standard output cannot
    encode them, as an undecodable file name's surrogate escapes cannot be."""
    try:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    except UnicodeEncodeError:
        print(json.dumps(report, separators=(",", ":")))


def main(argv: Sequence[str] | None = None, *, prog: str = _MODULE_INVOCATION) -> int:
    """Run one verb. Returns a process exit status.

    Returns rather than exiting, so a test drives the whole command in-process; `__main__` and the
    `zikaron` front door turn the status into an exit.
    """
    args = _parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    try:
        project = resolve(args.project)
    except ZikaronError as error:
        render(error)
        return 1
    if not project.has_store:
        stderr(refusal(project, initialize=initialize_command(prog)))
        return 1
    try:
        layout = _layout(project.directory, args.module, args.documents)
    except _RefusedError as refused:
        stderr(f"refused: {refused}")
        return 1
    try:
        configuration = resolve_configuration(
            default_system_config_path(os.environ.get("XDG_CONFIG_HOME"), Path.home()),
            project_config_path(project.store_dir),
        )
    except ZikaronError as error:
        render(error)
        return 1
    rules = walk.WalkRules(
        include_globs=tuple(args.include),
        exclude_globs=tuple(args.exclude),
        max_file_bytes=configuration.get_int("knowledge_max_file_bytes"),
    )
    try:
        store_dir = project.store_dir if args.apply else None
        report = asyncio.run(_run(project.directory, layout, rules, args.limit, store_dir))
    except (OSError, ValueError) as error:
        stderr(f"failed: {error}")
        return 1
    _print(report)
    return 0
