"""
Which module may import what.

**This package is the pure layer.** It parses bytes and holds cells. It
opens nothing, it talks to nobody, and it has no opinion about how a
cell is drawn. That is what makes it worth having on its own, and it is
the whole of Lillecarl/pymux#11.

Two front ends prove it rather than claim it. `ptterm` draws a screen
with prompt_toolkit and `txterm` draws the same screen with Textual, and
neither one may appear here.

**This file is the boundary, and grep is not.** A single
`from prompt_toolkit import ...` in `screen.py` would put the package
back where it started, with nothing to say so. The import that breaks a
layer fails here instead.

Everything that parses or holds is held to the rules. The disassembler
is not: it is a program, it writes to a file, and `TOOLS` names it.
"""
import ast
from pathlib import Path

import pytest

import pyte

#: The package as it is installed, and not as it sits beside this file.
#: A check runs the tests against what it built.
PACKAGE = Path(pyte.__file__).parent

#: The screen and everything under it. No I/O and no toolkit.
PURE = {
    "cache",
    "cells",
    "charsets",
    "colors",
    "control",
    "escape",
    "images",
    "kitty_keys",
    "modes",
    "osc",
    "page",
    "parameters",
    "placeholders",
    "png",
    "screen",
    "sequences",
    "sixel",
    "streams",
    "terminfo",
    "xcms",
}

#: The modules that are not the screen. Each one is a program or a
#: helper for one, so each one may touch a file.
#:
#: `debug.py` writes a JSON line per parsed event, so it holds a file
#: and imports `os`. `__main__.py` is the command line around it, so it
#: reads standard input. `__init__.py` wires the two together.
#:
#: `environment.py` says what a program run on this screen sees. The
#: entry that describes the screen is a file, and the answer depends on
#: whether it is there, so it looks at a directory.
TOOLS = {"__init__", "__main__", "debug", "environment"}

#: What the pure layer may take from outside: data, arithmetic and
#: tables.
#:
#: `sys` is here for `sys.maxsize` and `sys.platform`, which say nothing
#: about a file. `warnings` is a message, not a channel.
MAY_IMPORT = {
    "__future__",
    "array",
    "base64",
    "codecs",
    "collections",
    "colorsys",
    "enum",
    "functools",
    "inspect",
    "itertools",
    "math",
    "re",
    "string",
    "struct",
    "sys",
    "typing",
    "warnings",
    "zlib",
    "wcwidth",
}

#: The toolkits. This package may not draw, so it may not import one,
#: and the two front ends may never reach each other through it.
TOOLKITS = {"prompt_toolkit", "textual", "rich"}

#: The package that runs a program on a pty. A screen parses bytes;
#: where they came from is not its question. Lillecarl/pymux#85.
RUNS_A_PROGRAM = "ptyhost"

#: The two front ends. Neither may appear here at all.
FRONT_ENDS = {"ptterm", "txterm"}


def _name_of(path: Path) -> str:
    "The module name of one file, inside the package."
    relative = path.relative_to(PACKAGE).with_suffix("")
    parts = list(relative.parts)
    return ".".join(parts)


def _modules():
    "Every module of the package, by name."
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found[_name_of(path)] = path
    return found


MODULES = _modules()


def _imports(path: Path):
    """
    What one module imports: the outside packages by their first name,
    and the modules of this package by their own name.
    """
    outside = set()
    inside = set()
    tree = ast.parse(path.read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                outside.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                outside.add((node.module or "").split(".")[0])
                continue
            if node.module:
                # "from .colors import SgrColor".
                inside.add(node.module)
            else:
                # "from . import kitty_keys" names one module per alias.
                for alias in node.names:
                    inside.add(alias.name)
    return outside, inside


def test_every_module_has_a_layer():
    """
    A new module has to say which side it is on, here, before anything
    else can hold it to a rule.
    """
    unplaced = sorted(name for name in MODULES if name not in PURE | TOOLS)
    assert unplaced == [], (
        "these modules are in no layer: add each one to PURE or TOOLS "
        "in this file"
    )


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_imports_no_toolkit(name):
    "The whole point of the package. Lillecarl/pymux#11."
    outside, _inside = _imports(MODULES[name])
    assert not (outside & TOOLKITS)


@pytest.mark.parametrize("name", sorted(MODULES))
def test_no_module_reaches_a_front_end(name):
    """
    Not even the ones upstream left. A screen that imported a widget
    would be a screen that only that widget can hold.
    """
    outside, _inside = _imports(MODULES[name])
    assert not (outside & FRONT_ENDS)


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_reaches_no_pty(name):
    """
    A screen parses bytes and holds cells. Where the bytes came from is
    not its question. Lillecarl/pymux#85.
    """
    outside, _inside = _imports(MODULES[name])
    assert RUNS_A_PROGRAM not in outside


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_does_no_input_or_output(name):
    """
    This package is worth having on its own because it opens nothing and
    talks to nobody. A module that imports `os` has left that behind.
    """
    outside, _inside = _imports(MODULES[name])
    assert outside <= MAY_IMPORT, (
        "%s imports %s, which the pure layer may not"
        % (name, sorted(outside - MAY_IMPORT))
    )


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_reaches_no_tool(name):
    """
    The disassembler holds a file. A module that parses or holds may not
    reach one, which is the same rule as the one about `os`, said from
    the inside.
    """
    _outside, inside = _imports(MODULES[name])
    assert inside <= PURE, "%s imports %s" % (name, sorted(inside - PURE))


def test_the_reading_sees_an_import_where_there_is_one():
    """
    The tests above say nothing unless this one passes: a reader that
    found no import anywhere would pass every module.
    """
    outside, inside = _imports(MODULES["screen"])
    assert {"cells", "colors", "images", "kitty_keys", "page"} <= inside

    # `cells` is where the one outside import of the pure layer is:
    # `wcwidth` measures a character, and nothing else here reaches
    # outside the standard library at all.
    outside, inside = _imports(MODULES["cells"])
    assert "wcwidth" in outside
    assert {"cache", "colors"} <= inside
