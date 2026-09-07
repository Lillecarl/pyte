"""
The values a CSI parameter can carry.

A sequence such as DECSCUSR ("CSI Ps SP q") or DECSCL ("CSI Ps ; Ps " p")
carries a number, and the number means something. This module says
what each one means, and nothing more: no sequence is read here and
none is written.

The screen holds the choice a program made — `cursor_style`,
`conformance_level`, `attribute_extent` — and acts on it. What the
numbers are is a fact about the protocol, so it lives apart from the
screen that obeys them.

`modes.py` holds the parameters of "CSI Ps h", which are a group of
their own, `terminfo.py` holds the answers a program reads back, and
`titles.py` holds the titles that `TitleMode` and `TitlePart` name.
Lillecarl/pymux#129.
"""
from enum import IntEnum

__all__ = (
    "DEFAULT_CONFORMANCE_LEVEL",
    "DEFAULT_CURSOR_STYLE",
    "FIRST_PAGE_LENGTH",
    "AttributeExtent",
    "ConformanceLevel",
    "CursorShape",
    "StatusDisplay",
    "StatusLineType",
    "TitleMode",
    "TitlePart",
    "WindowOp",
)


class CursorShape(IntEnum):
    """
    The shape of the cursor, as DECSCUSR ("CSI Ps SP q") names it.

    One number carries the shape and the blinking together. The
    blinking shapes are the odd numbers, and the steady one of a pair
    is the number after it. Private mode 12 writes the blinking alone,
    so both sequences write this one value.
    """

    BLINKING_BLOCK = 1
    STEADY_BLOCK = 2
    BLINKING_UNDERLINE = 3
    STEADY_UNDERLINE = 4
    BLINKING_BAR = 5
    STEADY_BAR = 6


#: The shape that a terminal starts with.
DEFAULT_CURSOR_STYLE = CursorShape.BLINKING_BLOCK


class AttributeExtent(IntEnum):
    """
    What DECCARA and DECRARA reach, as DECSACE ("CSI Ps * x") sets it.

    A stream runs from the first corner to the second, the way a
    program reads a page. A rectangle takes the columns between them
    on every row.

    Zero and one both name the stream. A terminal reports back the one
    it was given, so the two are kept apart here.
    """

    DEFAULT = 0
    STREAM = 1
    RECTANGLE = 2


class StatusDisplay(IntEnum):
    "Where the output goes, as DECSASD (\"CSI Ps $ }\") sets it."

    MAIN = 0
    STATUS_LINE = 1


class StatusLineType(IntEnum):
    """
    What the status line holds, as DECSSDT ("CSI Ps $ ~") sets it.

    A terminal draws the indicator itself. A host status line holds
    what the program writes to it, after DECSASD sends the output
    there.
    """

    NONE = 0
    INDICATOR = 1
    HOST_WRITABLE = 2


class ConformanceLevel(IntEnum):
    """
    The level DECSCL ("CSI Ps ; Ps " p") names.

    Each one is the level of one DEC terminal, and a higher level takes
    every sequence of the levels below it.
    """

    VT100 = 61
    VT200 = 62
    VT300 = 63
    VT400 = 64
    VT500 = 65


#: The level ptterm reports until a program names another one. It
#: answers the sequences of a VT500, so it says so.
DEFAULT_CONFORMANCE_LEVEL = ConformanceLevel.VT500


class WindowOp(IntEnum):
    "The operations of \"CSI Ps t\" that a pane can answer."

    REPORT_TEXT_AREA_PIXELS = 14

    #: "CSI 15 t": how much room there is, in pixels. For a pane that
    #: is the pane: it draws on nothing else.
    REPORT_SCREEN_SIZE_PIXELS = 15

    REPORT_CELL_SIZE_PIXELS = 16
    REPORT_TEXT_AREA_CHARS = 18

    #: "CSI 19 t": how much room there is, in cells. A program asks
    #: this to learn how large it could become.
    REPORT_SCREEN_SIZE_CHARS = 19

    REPORT_ICON_LABEL = 20
    REPORT_WINDOW_TITLE = 21
    PUSH_TITLE = 22
    POP_TITLE = 23

    #: "CSI 4 ; Ph ; Pw t": as many cells as fit the given pixels.
    RESIZE_PIXELS = 4

    #: "CSI 8 ; Ph ; Pw t": that many rows and columns.
    RESIZE_CHARS = 8


#: "CSI Ps t" with a Ps of this or more is DECSLPP, and asks for a page
#: of Ps lines. Below it, Ps names one of the `WindowOp` operations.
FIRST_PAGE_LENGTH = 24


class TitleMode(IntEnum):
    """
    A title mode, by the number that "CSI > Ps t" carries.

    xterm keeps four. Two say how a program writes a title, and two say
    how the terminal reports one back. "CSI > Ps t" sets one and
    "CSI > Ps T" takes it away.
    """

    #: A title that a program sets is hexadecimal: two digits a byte.
    SET_HEX = 0

    #: A title that the terminal reports is hexadecimal.
    QUERY_HEX = 1

    #: A title that a program sets is UTF-8 and not Latin-1.
    SET_UTF8 = 2

    #: A title that the terminal reports is UTF-8 and not Latin-1.
    QUERY_UTF8 = 3


class TitlePart(IntEnum):
    "Which title a push or a pop of \"CSI 22 t\" and \"CSI 23 t\" names."

    BOTH = 0
    ICON = 1
    WINDOW = 2
