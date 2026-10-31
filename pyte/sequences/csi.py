"""
"CSI <params> <final>": the names of the final bytes, and the writers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..control import CSI as _CSI
from ..escape import RM as _RM
from ..escape import SM as _SM
from ..modes import AnsiMode, PrivateMode

__all__ = (
    "Csi",
    "CsiReport",
    "CsiSequence",
    "Marker",
    "Mode",
    "Parameter",
    "ask_mode",
    "csi",
    "mode_named",
    "reset_mode",
    "set_mode",
)


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


#: One parameter of a sequence. `None` is an empty parameter, which is
#: how a program asks for the default of that position rather than for
#: zero. A sequence of them is a parameter with subparameters, which
#: the colons join.
Parameter = int | None | Sequence[int | None]


class Marker(StrEnum):
    """
    The private marker between the "[" and the parameters.

    The marker is the whole difference between some sequences that
    share a final byte, so it is named and never spelled into the final
    byte: "CSI ? u" asks for the keyboard flags and "CSI > 1 u" pushes
    them.
    """

    #: No marker: the sequence ECMA-48 defines.
    NONE = ""

    #: DEC's, and xterm's after it: the private modes and their reports.
    QUESTION = "?"

    #: The secondary device attributes, XTVERSION, and kitty's push.
    GREATER = ">"

    #: kitty's pop, and an SGR mouse report.
    LESS = "<"

    #: kitty's set, and the tertiary device attributes.
    EQUALS = "="


def csi(final: str, *params: Parameter, private: Marker = Marker.NONE) -> str:
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

    `private` is the `Marker` between the "[" and the parameters:

        >>> csi(Csi.KITTY_KEYBOARD, private=Marker.QUESTION)
        '\\x1b[?u'
    """
    return "%s%s%s%s" % (_CSI, private, _joined(params), final)


def _joined(params: Iterable[Parameter]) -> str:
    """
    The parameters of a sequence, with the separators between them.

    A loop and not a generator: an image's placement writes a cursor
    move every frame, and `checks.pymux-images` counts what that costs.
    """
    parts = []
    for value in params:
        if value is None:
            parts.append("")
        elif isinstance(value, int):
            # "%d" writes an `IntEnum` as its number.
            parts.append("%d" % value)
        else:
            parts.append(":".join(_one(part) for part in value))
    return ";".join(parts)


def _one(value: int | None) -> str:
    "One parameter. Nothing at all is how an empty one is written."
    return "" if value is None else str(int(value))


#: A mode, by its name. A bare number is not one, on purpose: the
#: marker says whether a mode is private, the number does not, and a
#: builder that guessed would write "CSI 1049 h" for a mode that only
#: exists as "CSI ? 1049 h". `modes.py` names the modes a pane acts on;
#: for any other number, write `csi(escape.SM, 2031, private=Marker.QUESTION)` and
#: say the marker out loud.
Mode = AnsiMode | PrivateMode


def set_mode(*modes: Mode) -> str:
    "SM: turn these modes on. `modes.py` names them."
    return csi(_SM, *modes, private=_marker_of(modes))


def reset_mode(*modes: Mode) -> str:
    "RM: turn these modes off."
    return csi(_RM, *modes, private=_marker_of(modes))


def _marker_of(modes: Sequence[Mode]) -> Marker:
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
        raise ValueError("a private mode and an ANSI mode cannot go in one sequence: %r" % (modes,))
    return Marker.QUESTION if any(private) else Marker.NONE


def ask_mode(mode: Mode) -> str:
    """
    DECRQM: is this mode set? "CSI ? Ps $ p" for a private mode.

        >>> ask_mode(PrivateMode.SYNCHRONIZED_OUTPUT)
        '\\x1b[?2026$p'

    A terminal answers with a `reports.ModeReport`.
    """
    return csi(Csi.DECRQM, mode, private=_marker_of((mode,)))


def mode_named(number: int, private: bool) -> Mode | int:
    "The member that names this mode, or the number when no member does."
    try:
        return PrivateMode(number) if private else AnsiMode(number)
    except ValueError:
        return number


# ----------------------------------------------------------------------
# Reading one.

#: One CSI sequence, ECMA-48 5.4: the introducer, in its 7-bit or its
#: 8-bit form, a marker, the parameters, the intermediate bytes and one
#: final byte.
_SEQUENCE_RE = re.compile(r"(?:\x1b\[|\x9b)([<=>?]?)([0-9;:]*)([ -/]*)([@-~])")


class CsiReport:
    """
    What a terminal answers with a CSI sequence.

    `str(report)` writes it with the 7-bit CSI. A screen writes it with
    `sequence().body()` behind the CSI that S8C1T picks, so the report
    never decides which of the two it gets.
    """

    def sequence(self) -> CsiSequence:
        raise NotImplementedError

    def __str__(self) -> str:
        return str(self.sequence())


@dataclass(frozen=True)
class CsiSequence(CsiReport):
    """
    One CSI sequence, to write or as it was read.

        >>> str(CsiSequence(Csi.SD, (2,)))
        '\\x1b[2T'
        >>> CsiSequence.parse("\\x1b[?2026;1$y")
        CsiSequence(final='$y', params=(2026, 1), private=<Marker.QUESTION: '?'>)

    `final` carries the intermediate bytes in front of the final byte,
    the way `Csi` names them, so " q" is DECSCUSR. The parameters are
    what `csi` takes: a number, `None` for an empty one, or a tuple of
    subparameters.

    A reply is read with the class that names it, in `reports.py`. This
    is what each of those reads first.
    """

    final: str
    params: tuple[Parameter, ...] = ()
    private: Marker = Marker.NONE

    def __str__(self) -> str:
        return csi(self.final, *self.params, private=self.private)

    def sequence(self) -> CsiSequence:
        return self

    def body(self) -> str:
        "The sequence without its CSI: the marker, the parameters and the final byte."
        return "%s%s%s" % (self.private, _joined(self.params), self.final)

    @classmethod
    def parse(cls, text: str) -> CsiSequence | None:
        "The sequence `text` is, whole, or None."
        match = _SEQUENCE_RE.fullmatch(text)
        if match is None:
            return None
        marker, params, intermediates, final = match.groups()
        return cls(intermediates + final, _parameters_of(params), Marker(marker))

    def numbers(self) -> tuple[int, ...] | None:
        """
        The parameters as plain numbers, an empty one as zero. None when
        one of them carries subparameters, which no report does.
        """
        numbers = []
        for param in self.params:
            if param is None:
                numbers.append(0)
            elif isinstance(param, int):
                numbers.append(int(param))
            else:
                return None
        return tuple(numbers)


def _parameters_of(text: str) -> tuple[Parameter, ...]:
    "What `csi` would take to write `text` again."
    if not text:
        return ()
    return tuple(_parameter_of(part) for part in text.split(";"))


def _parameter_of(text: str) -> Parameter:
    if ":" in text:
        return tuple(int(part) if part else None for part in text.split(":"))
    return int(text) if text else None
