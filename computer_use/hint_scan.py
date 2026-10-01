"""Static scan of every `hint` text the sources can put in a response (CE-FACADE-011: a hint adds the next call and is at most HINT_MAX characters).

A hint is a string constant (or the left side of a `%` format, or a conditional's branches) stored under the key 'hint' of a dict literal, passed as
hint=..., assigned to ['hint'], or a value of one of the *HINTS dicts. Pure ast: nothing is imported or run.
"""
import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
HINT_MAX = 240
# the n placeholder expanded to 2 digits (plan.hint_for's suffix is measured on the real function by the test)
FORMAT_ROOM = 2


def _texts(node):
    """Every string constant a hint expression can evaluate to (conditional branches, % formats and + concatenations included; names are skipped)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        yield ''.join(v.value if isinstance(v, ast.Constant) else 'xx' for v in node.values)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        yield from _texts(node.left)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for left in _texts(node.left):
            for right in _texts(node.right) or ['']:
                yield left + right
    elif isinstance(node, ast.IfExp):
        yield from _texts(node.body);yield from _texts(node.orelse)


def hint_texts(path):
    """[(line, text)] of every hint constant in one source file."""
    tree = ast.parse(Path(path).read_text())
    out = []
    def take(node):
        for text in _texts(node):out.append((node.lineno, text))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'hint':take(value)
        elif isinstance(node, ast.keyword) and node.arg == 'hint':take(node.value)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == 'hint' for t in node.targets):take(node.value)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith('HINTS') for t in node.targets) and isinstance(node.value, ast.Dict):
            for value in node.value.values:take(value)
    return out


def all_hints():
    """[(file, line, text)] over every non-test source of the package."""
    return [(p.name, line, text) for p in sorted(HERE.glob('*.py')) if not p.name.startswith('test_') and p.name != 'hint_scan.py' for line, text in hint_texts(p)]


def too_long():
    return [(f, line, len(text), text[:60]) for f, line, text in all_hints() if len(text) + (FORMAT_ROOM if '%(n)d' in text or '%d' in text else 0) > HINT_MAX]
