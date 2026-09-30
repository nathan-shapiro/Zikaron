"""The only transaction control a service connection sees is the transaction primitive's.

`architecture.md` §Lifecycle is normative. The primitive is what serializes transactions on a
connection, chooses `IMMEDIATE` for a write, bounds the lock wait, and names a driver failure; a
`BEGIN` issued anywhere else has none of that, and on the service's writer it would run inside
another request's transaction. Two other functions issue one, and both run before the socket
exists: `Store._create_tables_and_meta` creating a store, and `migration.migrate` moving one
forward. The allowance is by function rather than by module, since `store.py` also holds the
writer's reopen, which runs under the socket.

Every spelling that opens or ends a transaction counts, not only `BEGIN`: a `SAVEPOINT` outside a
transaction is SQLite's `BEGIN DEFERRED`, and one nothing releases wedges the writer as an
uncommitted `BEGIN` would; a `COMMIT`, a `ROLLBACK`, or a driver `commit()`/`rollback()` issued
outside the primitive ends whichever task's transaction is open on the handle.

Read from the source rather than from a running service, so a statement on a path no test exercises
is still found. A statement is recognised as a string literal that is a whole transaction-control
statement — including an f-string's literal part and a line of an `executescript` body — which is
how it would reach a connection whatever call carried it. `END` is left out, since alone on a line
it is also the close of a formatted `CASE`.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

_PACKAGE: Final = Path(__file__).resolve().parent.parent / "zikaron"

#: Where transaction control may appear: the primitive's own functions, and the two that run
#: before the socket exists.
_ALLOWED: Final = frozenset(
    {
        ("core/store/transactions.py", "_begin_immediate_by_polling"),
        ("core/store/transactions.py", "commit_or_roll_back"),
        ("core/store/transactions.py", "finalize"),
        ("core/store/transactions.py", "in_one_transaction"),
        ("core/store/store.py", "_create_tables_and_meta"),
        ("core/store/migration.py", "migrate"),
    }
)

_TRANSACTION_CONTROL: Final = re.compile(
    r"^\s*(BEGIN(\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?(\s+TRANSACTION)?"
    r"|COMMIT(\s+TRANSACTION)?|ROLLBACK(\s+TRANSACTION)?(\s+TO(\s+SAVEPOINT)?\s+\S+)?"
    r"|SAVEPOINT\s+\S+|RELEASE(\s+SAVEPOINT)?\s+\S+)\s*;?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_DRIVER_CONTROL: Final = frozenset({"commit", "rollback"})

_FUNCTIONS: Final = (ast.FunctionDef, ast.AsyncFunctionDef)


def _is_control(node: ast.AST, docstrings: set[int]) -> bool:
    if isinstance(node, ast.Constant):
        return (
            isinstance(node.value, str)
            and id(node) not in docstrings
            and _TRANSACTION_CONTROL.search(node.value) is not None
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _DRIVER_CONTROL
    )


def _walk(node: ast.AST, function: str | None) -> Iterator[tuple[ast.AST, str | None]]:
    """Every node below `node`, with the name of the innermost function enclosing it."""
    for child in ast.iter_child_nodes(node):
        inner = child.name if isinstance(child, _FUNCTIONS) else function
        yield child, inner
        yield from _walk(child, inner)


def _control_sites(tree: ast.AST) -> list[tuple[int, str | None]]:
    """The line and enclosing function of every transaction-control statement or driver call in
    `tree`, docstrings aside.

    `ast.Constant` covers an f-string's literal parts as well as a plain string.
    """
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return sorted(
        (node.lineno, function)  # type: ignore[attr-defined]
        for node, function in _walk(tree, None)
        if _is_control(node, docstrings)
    )


def _control_lines(source: str) -> list[int]:
    return [line for line, _function in _control_sites(ast.parse(source))]


def _module_sites(path: Path) -> list[tuple[str, int, str | None]]:
    module = path.relative_to(_PACKAGE).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [(module, line, function) for line, function in _control_sites(tree)]


def test_no_function_outside_the_allowed_issues_transaction_control() -> None:
    offenders = [
        f"{module}:{line} in {function}"
        for path in sorted(_PACKAGE.rglob("*.py"))
        for module, line, function in _module_sites(path)
        if (module, function) not in _ALLOWED
    ]
    assert offenders == []


def test_every_allowed_function_still_issues_it() -> None:
    """An allowance nothing uses is a hole a later edit could fill unseen, so each one is held to a
    site that exists."""
    found = {
        (module, function)
        for path in sorted(_PACKAGE.rglob("*.py"))
        for module, _line, function in _module_sites(path)
    }
    assert found >= _ALLOWED


def test_the_guard_finds_transaction_control_in_every_form_a_call_can_carry_it() -> None:
    """The recogniser, against every shape the guard exists for, so a guard that matches nothing
    cannot pass for one that found nothing."""
    source = (
        'await db.execute("BEGIN")\n'
        'await db.execute(f"BEGIN IMMEDIATE")\n'
        'await db.executescript("SELECT 1;\\nBEGIN;\\nSELECT 2;")\n'
        'await db.execute("SAVEPOINT s")\n'
        "await db.commit()\n"
        'await db.execute("ROLLBACK TO SAVEPOINT s")\n'
        'await db.execute("RELEASE s")\n'
        "await db.rollback()\n"
    )
    assert _control_lines(source) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_a_case_expression_is_not_transaction_control() -> None:
    source = 'await db.execute("SELECT CASE\\n  WHEN x THEN 1\\nEND\\nFROM t")\n'
    assert _control_lines(source) == []


def test_a_site_is_attributed_to_its_innermost_function() -> None:
    """What the allowance is keyed on: a `BEGIN` in a function nested inside an allowed one belongs
    to the nested function, and one at module level to none."""
    source = (
        "def allowed():\n"
        "    async def nested():\n"
        '        await db.execute("BEGIN")\n'
        'MODULE = "BEGIN"\n'
    )
    assert _control_sites(ast.parse(source)) == [(3, "nested"), (4, None)]
