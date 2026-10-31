"""
"ESC <final>" and the two families with an intermediate byte, "ESC #"
and "ESC SP".
"""

from __future__ import annotations

from enum import StrEnum

from ..control import ESC as _ESC
from ..escape import DECALN as _DECALN
from ..escape import NEL as _NEL

__all__ = ("Escape", "Sharp", "announce", "esc", "sharp")


class Escape(StrEnum):
    """
    The byte that follows ESC, for the sequences `escape.py` does not
    name.

    A member is a string, so the parser can look one up with the raw
    byte it read.
    """

    #: Next line. pyte gives it to the handler of LF, and the two
    #: differ: NEL always goes to the left margin.
    NEL = _NEL

    #: Back index. It moves the cursor one column to the left, and
    #: moves the scrolling region instead when the cursor stands on
    #: the left margin. pyte has neither this nor DECFI.
    DECBI = "6"

    #: Forward index, the other way round.
    DECFI = "9"

    #: Start of a protected area. It marks the cells a program draws
    #: next, so that an erase leaves them alone.
    SPA = "V"

    #: End of a protected area.
    EPA = "W"

    #: Identify terminal. It is the older way to ask what DA asks, and
    #: a terminal answers it the same way. A VT100 had it; xterm keeps
    #: it, so a program written for one still gets an answer.
    DECID = "Z"

    #: Application keypad. The keypad stops sending digits and sends
    #: SS3 forms, so a program can tell the keypad from the row of
    #: numbers above the letters. Private mode 66 (DECNKM) is the
    #: newer spelling of the same thing, and this is the one that
    #: programs send: terminfo's `smkx` is usually "\\E[?1h\\E=", which
    #: turns on the application cursor keys and this in one string.
    DECKPAM = "="

    #: Normal keypad, the other half of the pair. terminfo's `rmkx`.
    DECKPNM = ">"

    #: Locking shift 2. G2 is what the letters come from, until
    #: something says otherwise. SI and SO are the same thing for G0
    #: and G1, and they are control characters rather than escapes
    #: because a VT100 had only those two.
    LS2 = "n"

    #: Locking shift 3.
    LS3 = "o"

    #: Single shift 2. **The next character alone** comes from G2, and
    #: then the letters come from wherever they came from before. This
    #: is what a program uses to draw one character out of a set it
    #: does not want to stay in.
    SS2 = "N"

    #: Single shift 3.
    SS3 = "O"


class Sharp(StrEnum):
    """
    The byte that follows "ESC #".

    The "#" is an intermediate byte, so these are their own family:
    "ESC 8" is DECRC and "ESC # 8" is DECALN, and only the "#" says
    which.

    Four of the five draw a line at twice the width or twice the
    height on a VT100. This screen reads them and draws neither, which
    `tests/test_line_attributes.py` says why: kitty, Ghostty and
    Alacritty implement none of them and no recorded program sends
    one. What has to be true is that the bytes go away.
    Lillecarl/pymux#141.
    """

    #: Double height, top half.
    DECDHL_TOP = "3"

    #: Double height, bottom half. A double height line is two lines,
    #: and a program writes the same text twice.
    DECDHL_BOTTOM = "4"

    #: Single width, which is what a line is unless something says
    #: otherwise.
    DECSWL = "5"

    #: Double width.
    DECDWL = "6"

    #: Alignment display: fill the screen with "E". `escape.py` names
    #: it as well, because upstream put it there.
    DECALN = _DECALN


def esc(final: str) -> str:
    """
    An escape sequence with no intermediate byte: "ESC <final>".

        >>> esc(escape.RIS)
        '\\x1bc'
        >>> esc(Escape.DECID)
        '\\x1bZ'

    `escape.py` names the ones a VT100 and a VT220 send, and `Escape`
    names the rest.
    """
    return _ESC + final


def sharp(final: str) -> str:
    """
    "ESC # <final>", which is the line attributes and DECALN.

        >>> sharp(Sharp.DECDWL)
        '\\x1b#6'

    The "#" is why this is not `esc`: "ESC 8" is DECRC and
    "ESC # 8" is DECALN, and the intermediate byte is the whole
    difference.
    """
    return _ESC + "#" + final


def announce(final: str) -> str:
    """
    "ESC SP <final>", which ECMA-48 calls an announcer.

        >>> announce(escape.S7C1T)
        '\\x1b F'

    The space is an intermediate byte, so a stream that does not read
    it puts the final byte on the screen as text. `streams.py` eats
    the announcers it has no handler for, for that reason.
    """
    return _ESC + " " + final
