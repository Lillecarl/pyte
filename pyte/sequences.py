"""
The bytes that name a sequence, for the ones `escape.py` does not hold.

`escape.py` and `control.py` came from upstream and name what a VT100
and a VT220 send. These are the rest: what a VT400 and a VT500 added,
what xterm added after them, and what kitty added after that.

`streams.Stream` reads them all from one table, so nothing here decides
anything. A name and a byte, and that is all.
"""
from enum import StrEnum

from .escape import NEL as _NEL

__all__ = ("Escape", "Csi")


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


class Csi(StrEnum):
    """
    The final byte of a CSI sequence, with its intermediate bytes in
    front of it.

    A CSI sequence ends with one final byte and can carry intermediate
    bytes before it. The parser joins the two into one key, so " q" is
    DECSCUSR and "q" on its own is something else.

    `screen.py` holds the parameters of each sequence, in the docstring
    of the handler.
    """

    #: Cursor backward tabulation: move back over tab stops. pyte has
    #: neither this nor CHT.
    CBT = "Z"

    #: Cursor horizontal forward tabulation.
    CHT = "I"

    #: Copy rectangular area: copy a rectangle to another place.
    DECCRA = "$v"

    #: Delete column: take columns out of the scrolling region.
    DECDC = "'~"

    #: Erase rectangular area.
    DECERA = "$z"

    #: Fill rectangular area: write one character over a rectangle.
    DECFRA = "$x"

    #: Insert column, the other way round from DECDC.
    DECIC = "'}"

    #: Request checksum of a rectangular area. A conformance suite
    #: reads the screen back with it, so it is the instrument that
    #: judges the rest.
    DECRQCRA = "*y"

    #: Request mode: is this mode set?
    DECRQM = "$p"

    #: Select character protection attribute. It marks the cells a
    #: program draws next, so that a selective erase leaves them alone.
    DECSCA = '"q'

    #: Set cursor style. ptterm remembers it, so that DECRQSS can
    #: report it back.
    DECSCUSR = " q"

    #: Selective erase rectangular area: erase a rectangle, and leave
    #: the cells that DECSCA marked alone.
    DECSERA = "${"

    #: Select attribute change extent: what DECCARA and DECRARA reach.
    DECSACE = "*x"

    #: Select active status display: send the output to the status
    #: line, or to the screen.
    DECSASD = "$}"

    #: Set conformance level: which DEC terminal this one answers as.
    DECSCL = '"p'

    #: Set number of lines per screen.
    DECSNLS = "*|"

    #: Select status display type: what the status line holds.
    DECSSDT = "$~"

    #: Set left and right margin. It answers only while private mode
    #: 69 is set, because the same final byte names SCOSC otherwise.
    DECSLRM = "s"

    #: Soft terminal reset. It keeps the screen and puts the settings
    #: back.
    DECSTR = "!p"

    #: Horizontal position absolute: the column of the line. pyte gives
    #: it to the handler of CHA, and xterm moves the two alike, so
    #: ptterm keeps its own name for it and serves both the same way.
    HPA = "`"

    #: Horizontal position backward: columns to the left. It is the
    #: fourth of the position family, and the only one of the four that
    #: pyte does not name. ECMA-48 8.3.58 moves the cursor backward
    #: along the character path, which on this terminal is CUB.
    HPB = "j"

    #: Vertical position backward: rows up. ECMA-48 8.3.159, and the
    #: same relation to CUU that HPB has to CUB.
    VPB = "k"

    #: Repeat the last character that was drawn. It saves a program
    #: the bytes of a run of one character.
    REP = "b"

    #: Scroll down: move the lines of the scrolling region, without
    #: moving the cursor. pyte has neither this nor SU.
    SD = "T"

    #: Scroll up.
    SU = "S"

    #: The kitty keyboard protocol: push, pop, set or query the
    #: progressive enhancement flags. Parsing its ">", "<" and "="
    #: private markers needs the matching pyte patches.
    KITTY_KEYBOARD = "u"

    #: kitty's unscroll: bring lines back from the history. The
    #: intermediate space is part of the name, so this is not CUB.
    KITTY_UNSCROLL = " D"

    #: The name and the version of the terminal. A plain "CSI Ps q" is
    #: DECLL, which ptterm ignores.
    XTVERSION = "q"

    #: Window manipulation. Only the size and title reports are
    #: answered.
    XTWINOPS = "t"

