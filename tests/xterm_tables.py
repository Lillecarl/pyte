"""
xterm's own character set tables, read out of its source.

`pyte/charsets.py` holds the national replacement sets and the DEC
technical set as tables of a hundred and thirty odd positions. Nobody
publishes those as data: Unicode's vendor mappings have no DEC
directory, no python package carries them, and the DEC manuals are
paper. **xterm's `charsets.h` is the list**, as a wall of C macros, and
every terminal that has these sets either copied it or copied the same
manuals.

So the tables are not trusted here. `test_the_national_tables.py` reads
this module and compares, the way `xlib_oracle` compares the colour
specs against the real Xlib. The two are the same idea: a port is only
right if something says so against the original.

`PYTE_XTERM_SOURCE` says where the unpacked source is, and
`nix/checks.nix` sets it from `xterm.src`.
"""

import os
import re
from pathlib import Path

#: Where the unpacked xterm source is. Empty outside the check.
SOURCE = os.environ.get("PYTE_XTERM_SOURCE", "")

#: A keysym whose line in `charsets.h` carries no "U+" comment, so the
#: name is the only thing that says what it is.
KEYSYMS = {"XK_Eacute": 0x00C9}

#: The macro that holds each set, by the name pyte gives the set.
MACROS = {
    "4": "map_NRCS_Dutch",
    "5": "map_NRCS_Finnish",
    "R": "map_NRCS_French",
    "Q": "map_NRCS_French_Canadian",
    "K": "map_NRCS_German",
    "Y": "map_NRCS_Italian",
    "`": "map_NRCS_Norwegian_Danish",
    "%6": "map_NRCS_Portuguese",
    "Z": "map_NRCS_Spanish",
    "7": "map_NRCS_Swedish",
    "=": "map_NRCS_Swiss",
    ">": "map_DEC_Technical",
}

_DEFINE = re.compile(r"#define (map_\w+)\(")
_ENTRY = re.compile(
    r"(MAP|UNI|XXX)\(0x([0-9A-Fa-f]{2}),\s*([^)]+)\)(?:\s*/\*\s*(.*?)\*/)?"
)
_CODEPOINT = re.compile(r"U\+([0-9A-Fa-f]{4})")


def xterm_is_available() -> bool:
    return bool(SOURCE) and _header().is_file()


def _header() -> Path:
    return Path(SOURCE) / "charsets.h"


def _macro_bodies() -> dict:
    "Every `#define map_...` in the header, and the lines under it."
    bodies: dict = {}
    name = None
    for line in _header().read_text(errors="replace").splitlines():
        start = _DEFINE.match(line)
        if start:
            name = start.group(1)
            bodies.setdefault(name, [])
            continue
        if name is None:
            continue
        if not line[:1].isspace():
            name = None
            continue
        bodies[name].append(line)
    return bodies


def table_of(macro: str) -> dict:
    """
    The positions one macro moves, as ``{position: codepoint}``.

    Read in the direction `xtermCharSetOut` reads it: the position a
    program writes, and the character that is drawn for it.

    An `XXX` entry has no character in Unicode -- the seven pieces a
    large sigma is drawn out of are the case -- so it is left out, and
    a position nobody names draws what ASCII draws.
    """
    lines = _macro_bodies().get(macro)
    if lines is None:
        raise KeyError("xterm's charsets.h has no %s" % (macro,))

    table = {}
    for line in lines:
        entry = _ENTRY.search(line)
        if entry is None:
            continue
        kind, position, target, comment = entry.groups()
        if kind == "XXX":
            continue
        target = target.strip()
        if target.startswith("0x"):
            table[int(position, 16)] = int(target, 16)
            continue
        codepoint = _CODEPOINT.search(comment or "")
        if codepoint is not None:
            table[int(position, 16)] = int(codepoint.group(1), 16)
        elif target in KEYSYMS:
            table[int(position, 16)] = KEYSYMS[target]
        else:
            raise AssertionError("no codepoint for %r" % (line.strip(),))
    return table
