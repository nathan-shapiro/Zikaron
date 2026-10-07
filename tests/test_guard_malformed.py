"""Malformed commands and scripts: what the rules give where brackets, quotes or delimiters do not
close (`design/edit-guards.md` §3.3: a write whose target yields nothing is denied naming no
target).

Each value below is what §3 gives the input, pinned so the defensive branches that produce it are
exercised; none of these inputs is valid shell or valid Python.
"""

import pytest

from zikaron.guard.decision import Deny, Silent, decide
from zikaron.guard.expression import Judge, Source
from zikaron.guard.scratch import Location

HERE = Location("/home/u/proj")


@pytest.mark.parametrize(
    ("command", "named"),
    [
        # A parenthesised `with` item not followed by `:` is read item by item, so `d` is unbound.
        (
            "python3 -c \"with (tempfile.mkdtemp()) as d, open(f'{d}/x','w') as fh: pass\"",
            ("/home/u/proj/{d}/x",),
        ),
        ("python3 -c \"(Path('f').write_text(s)\"", ("/home/u/proj/f",)),
        ("node -e \"fs.writeFileSync('f'\"", ()),
        ('python3 -c "x).write_text(s)"', ()),
        ('python3 -c ").write_text(s)"', ()),
        ("python3 -c \"p = Path('/tmp/x'; p.write_text(s)\"", ()),
        ("python3 -c \"open(f(), 'w')\"", ()),
        ("python3 -c \"open( , 'w')\"", ()),
        ('python3 -c "Path().write_text(s)"', ()),
        ("python3 -c \"open(os.path.join(), 'w')\"", ()),
        ("python3 -c \"open(p.open('w').x, 'w')\"", ()),
        ('python3 -c "(a)(b).write_text(s)"', ()),
        ("python3 -c \"open((p) .x, 'w')\"", ()),
        ("python3 -c \"open((p)[0, 'w')\"", ()),
        ("python3 -c \"open(p[0, 'w')\"", ()),
        ("python3 -c \"p = (Path('f'); p.write_text(s)\"", ()),
        ('python3 -c ".x.write_text(s)"', ()),
        ("sed -i $(\nls) f", ()),
    ],
)
def test_a_seen_write_denies_naming_what_resolved(command: str, named: tuple[str, ...]) -> None:
    decision = decide(command, HERE)
    assert isinstance(decision, Deny)
    assert decision.match.authored_paths == named


@pytest.mark.parametrize(
    "command",
    [
        "cat <<",
        "cat <<'EOF",
        "cat << ;",
        'node -e "\nfs.writeFileSync(`/tmp/${n}\nb`, s)\n"',
        "python3 -c \"open((Path('f'),'w')\"",
        "python3 -c \"open(Path('f','w')\"",
        "python3 -c \"open(x.read(, 'w')\"",
        "python3 -c \"open(p.with_suffix(.x, 'w')\"",
    ],
)
def test_an_unclosed_construct_hides_nothing_it_does_not_contain(command: str) -> None:
    assert decide(command, HERE) == Silent()


def test_a_receiver_walk_stops_at_the_start_of_the_script() -> None:
    assert Judge(Source(".x.write_text(s)")).receiver(dot=2) is None
