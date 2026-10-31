"""
SGR, "CSI Ps ; ... m": the numbers of the graphic rendition, by name.

`sgr.py` is what a screen does with them. This names the numbers once,
so a writer says `sgr(Sgr.REVERSE)` and a reader compares against the
member.
"""

from __future__ import annotations

from enum import IntEnum

from ..escape import SGR as _SGR
from .csi import Parameter, csi

__all__ = ("Sgr", "sgr")


class Sgr(IntEnum):
    "One number of a rendition. ECMA-48 8.3.117, and what xterm and kitty added."

    RESET = 0
    BOLD = 1
    DIM = 2
    ITALIC = 3
    UNDERLINE = 4
    BLINK = 5
    RAPID_BLINK = 6
    REVERSE = 7
    HIDDEN = 8
    STRIKE = 9
    DOUBLE_UNDERLINE = 21

    #: Neither bold nor dim.
    NORMAL_INTENSITY = 22
    NOT_ITALIC = 23
    NOT_UNDERLINED = 24
    NOT_BLINKING = 25
    NOT_REVERSED = 27
    NOT_HIDDEN = 28
    NOT_STRUCK = 29

    #: A foreground colour that the next numbers give: "38 ; 5 ; n" from
    #: the palette, "38 ; 2 ; r ; g ; b" by its components.
    FOREGROUND = 38
    DEFAULT_FOREGROUND = 39
    BACKGROUND = 48
    DEFAULT_BACKGROUND = 49

    #: The colour of the underline, as FOREGROUND gives one.
    UNDERLINE_COLOR = 58
    DEFAULT_UNDERLINE_COLOR = 59

    SUPERSCRIPT = 73
    SUBSCRIPT = 74
    NEITHER_SCRIPT = 75


class ColorSpace(IntEnum):
    'What follows "38", "48" or "58": a number of the palette, or the components.'

    DIRECT = 2
    INDEXED = 5


def sgr(*params: Parameter) -> str:
    """
    "CSI Ps ; ... m". With nothing, it resets every attribute.

        >>> sgr(Sgr.REVERSE)
        '\\x1b[7m'
        >>> sgr(Sgr.FOREGROUND, ColorSpace.DIRECT, 1, 2, 3)
        '\\x1b[38;2;1;2;3m'
    """
    return csi(_SGR, *params)
