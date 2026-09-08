"""
The bytes that name a sequence, for the ones `escape.py` does not hold.

`escape.py` and `control.py` came from upstream and name what a VT100
and a VT220 send. These are the rest: what a VT400 and a VT500 added,
what xterm added after them, and what kitty added after that.

`streams.Stream` reads them all from one table, so nothing here decides
anything. A name and a byte, and that is all.

`csi` is the other direction: a byte from a name. It builds the
sequence that these names describe, so that a caller writes what it
means instead of a hand-typed string. Lillecarl/pymux#165.

**It is not an encoder.** `Screen.encode_key` writes the keys of a
pane and `Screen` answers the queries; those are the writers, there is
one of each, and a test that judges one has to hold the bytes it
expects as a literal. This is for the other side: the sequences a test
feeds a parser, and the replies a test makes a terminal give. Getting
one of those wrong is a passing test that asserts the wrong thing.
"""
from enum import StrEnum
from typing import Iterable, Sequence, Union

from .control import CSI as _CSI
from .control import ESC as _ESC
from .escape import DECALN as _DECALN
from .escape import NEL as _NEL
from .escape import RM as _RM
from .escape import SM as _SM
from .modes import AnsiMode, PrivateMode

__all__ = (
    "Escape",
    "Csi",
    "Sharp",
    "announce",
    "csi",
    "esc",
    "reset_mode",
    "set_mode",
    "sharp",
)


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


# ----------------------------------------------------------------------
# Writing one. Lillecarl/pymux#165.


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

#: One parameter of a sequence. `None` is an empty parameter, which is
#: how a program asks for the default of that position rather than for
#: zero. A sequence of them is a parameter with subparameters, which
#: the colons join.
Parameter = Union[int, None, Sequence[Union[int, None]]]

#: The markers that go between the "[" and the parameters. The marker
#: is the whole difference between some sequences that share a final
#: byte, so it is named and never spelled into the final byte.
MARKERS = ("?", ">", "<", "=")


def csi(final: str, *params: Parameter, private: str = "") -> str:
    """
    A CSI sequence, from the name of its final byte.

    `final` is a member of `Csi`, or one of the plain names in
    `escape.py`. Both are strings, and both carry their intermediate
    bytes, which go after the parameters:

        >>> csi(Csi.SD, 2)
        '\\x1b[2T'
        >>> csi(Csi.DECSCUSR, 4)
        '\\x1b[4 q'

    A parameter of `None` is written as nothing at all, which is how a
    program asks for the default of that position rather than for
    zero:

        >>> csi(escape.CUP, None, 5)
        '\\x1b[;5H'

    A parameter that is a sequence carries subparameters, joined by
    colons the way the kitty keyboard protocol and the colon form of
    SGR write them:

        >>> csi(escape.SGR, 38, (2, 1, 2, 3))
        '\\x1b[38;2:1:2:3m'

    `private` is the marker between the "[" and the parameters: "?",
    ">", "<" or "=". The marker is the whole difference between some
    sequences that share a final byte, so it is named and not spelled
    into `final`.
    """
    return "%s%s%s%s" % (_CSI, private, _joined(params), final)


def _joined(params: Iterable[Parameter]) -> str:
    "The parameters of a sequence, with the separators between them."
    return ";".join(
        # An `IntEnum` is an `int`, so only a real sequence of
        # subparameters reaches the colons.
        _one(value)
        if isinstance(value, (int, type(None)))
        else ":".join(_one(part) for part in value)
        for value in params
    )


def _one(value: Union[int, None]) -> str:
    "One parameter. Nothing at all is how an empty one is written."
    return "" if value is None else str(int(value))


#: A mode, by its name. A bare number is not one, on purpose: the
#: marker says whether a mode is private, the number does not, and a
#: builder that guessed would write "CSI 1049 h" for a mode that only
#: exists as "CSI ? 1049 h". `modes.py` names the modes a pane acts on;
#: for any other number, write `csi(escape.SM, 2026, private="?")` and
#: say the marker out loud.
Mode = Union[AnsiMode, PrivateMode]


def set_mode(*modes: Mode) -> str:
    "SM: turn these modes on. `modes.py` names them."
    return csi(_SM, *modes, private=_marker_of(modes))


def reset_mode(*modes: Mode) -> str:
    "RM: turn these modes off."
    return csi(_RM, *modes, private=_marker_of(modes))


def _marker_of(modes: Sequence[Mode]) -> str:
    """
    The marker that these modes are written with.

    A private mode carries "?" and a mode of the ANSI standard carries
    nothing, and one sequence cannot hold both: the marker belongs to
    the sequence and not to the parameter. A caller that mixes them is
    asking for a sequence no terminal reads.

    A bare number is refused for the same reason. It says nothing
    about the marker, so a builder that took one would have to guess,
    and guessing wrong writes a sequence that reads as another mode
    entirely.
    """
    unnamed = [mode for mode in modes if not isinstance(mode, (AnsiMode, PrivateMode))]
    if unnamed or not modes:
        raise ValueError(
            "name each mode with AnsiMode or PrivateMode, because the "
            "number does not say which marker it takes: %r" % (modes,)
        )

    private = [isinstance(mode, PrivateMode) for mode in modes]
    if any(private) and not all(private):
        raise ValueError(
            "a private mode and an ANSI mode cannot go in one sequence: %r"
            % (modes,)
        )
    return "?" if any(private) else ""
