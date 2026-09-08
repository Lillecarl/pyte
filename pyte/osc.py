"""
The payloads of the OSC sequences that a pane reads and answers.

A pane is not the outer terminal: it has no window, no clipboard of its
own and no palette that the user picked. What it does have is a set of
answers that keep a program from waiting forever for a reply. This
module holds the shape of each payload: which code names which colour,
how a hyperlink is written, how a pointer shape is named.

Colour queries come in two shapes. The xterm one names the colour in
the code itself ("OSC 10" is the foreground, "OSC 11" the background,
"OSC 4 ; index" a palette entry), and the kitty one names it with a key
("OSC 21 ; foreground=?"). Both are answered here.

What a colour *is* lives in `colors.py`, and the arithmetic behind it
in `xcms.py`. Nothing about a colour space belongs here.

The state a pane keeps for an OSC lives here as well: `PointerShapes`
holds the stack of "OSC 22" and `ColorOverrides` holds what "OSC 4",
"OSC 5" and "OSC 10" set. That is where `GraphicsState` sits for the
graphics protocol, in `images.py`. Neither one writes a sequence: each
returns the payload to answer with, and the screen sends it.
Lillecarl/pymux#129.
"""

from enum import StrEnum
from typing import Dict, List, NamedTuple, Tuple

from .colors import DEFAULT_COLORS, PALETTE, Color, parse_color

__all__ = [
    "DYNAMIC_COLOR_CODES",
    "DYNAMIC_COLOR_RESET_OFFSET",
    "FIRST_SPECIAL_COLOR",
    "FORWARDED_OSC",
    "MAX_HYPERLINK_ID_LENGTH",
    "MAX_HYPERLINK_LENGTH",
    "MAX_POINTER_SHAPES",
    "POINTER_SHAPES",
    "POINTER_SHAPE_ALIASES",
    "QUERY",
    "SPECIAL_COLOR_NAMES",
    "ColorOverrides",
    "Osc",
    "PointerShapeRead",
    "PointerShapes",
    "asks_for_the_clipboard",
    "parse_hyperlink",
    "parse_kitty_color_query",
    "pointer_shape_name",
]


class Osc(StrEnum):
    """
    The OSC codes that a pane reads.

    An OSC names its code in text, not in a parameter, so the code is
    a string here as well.
    """

    #: "OSC 8": the hyperlink that the cells after it carry.
    HYPERLINK = "8"
    #: "OSC 4": one entry of the palette, by index.
    PALETTE_COLOR = "4"
    #: "OSC 5": one colour that a rendition asks for by name.
    SPECIAL_COLOR = "5"
    #: "OSC 21": the colours, in the form that kitty reads.
    KITTY_COLORS = "21"
    #: "OSC 22": the shape of the pointer over the pane.
    POINTER_SHAPE = "22"
    #: "OSC 52": the clipboard of the user.
    CLIPBOARD = "52"
    #: "OSC 99": a desktop notification.
    NOTIFICATION = "99"
    #: "OSC 104": put palette entries back to their defaults.
    RESET_PALETTE_COLOR = "104"
    #: "OSC 105": put special colours back to their defaults.
    RESET_SPECIAL_COLOR = "105"


#: The OSC sequences that a pane cannot answer by itself. They ask the
#: terminal of the user for the shape of the pointer (22), the
#: clipboard (52) or a desktop notification (99). `Screen.osc_func`
#: receives them, and a pane without such a function consumes them.
FORWARDED_OSC = frozenset(
    [
        Osc.POINTER_SHAPE,
        Osc.CLIPBOARD,
        Osc.NOTIFICATION,
    ]
)


def asks_for_the_clipboard(payload: str) -> bool:
    """
    True for a clipboard query, e.g. "OSC 52 ; c ; ?".

    The payload of OSC 52 names a selection and then the data. A
    question mark asks for the content instead of setting it.
    """
    _selection, _semicolon, data = payload.partition(";")
    return data.strip() == "?"


#: The codes of the dynamic colours, and the colour that each one
#: names. "OSC 10" is the first of them, and a payload with several
#: values walks up the codes from the one it was sent with.
#:
#: xterm numbers ten of these. The five that are here are the five
#: that a pane holds; the rest name a pointer or a Tektronix window,
#: which a pane does not have.
DYNAMIC_COLOR_CODES: Dict[str, str] = {
    "10": "foreground",
    "11": "background",
    "12": "cursor",
    "17": "selection_background",
    "19": "selection_foreground",
}

#: The colours that a rendition asks for by name, in the order that
#: xterm numbers them. "OSC 5 ; 0" is the first.
SPECIAL_COLOR_NAMES = ["bold", "underline", "blink", "reverse", "italic"]

#: The index that the first special colour takes in an "OSC 4"
#: payload. The special colours sit after the palette, so a program
#: reads the size of the palette first and adds it.
FIRST_SPECIAL_COLOR = len(PALETTE)

#: What separates the code that puts a dynamic colour back from the
#: code that sets it. "OSC 10" sets the foreground and "OSC 110" puts
#: it back.
DYNAMIC_COLOR_RESET_OFFSET = 100


def parse_kitty_color_query(param: str) -> List[Tuple[str, bool]] | None:
    """
    Split the payload of an "OSC 21" sequence into its keys.

    Returns one (key, is_query) pair per part, or None when the payload
    holds nothing to answer. A part with a "?" value is a query; every
    other part sets a colour, which a pane cannot do.
    """
    parts = [part for part in param.split(";") if part != ""]
    if not parts:
        return None

    result = []
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result.append((key, value == "?"))
        else:
            result.append((part, False))
    return result


#: The longest hyperlink target that a pane may open. A URL longer than
#: this is not a link that anybody follows; it is a way to fill memory.
MAX_HYPERLINK_LENGTH = 2083

#: The longest id that a hyperlink may carry. The specification of the
#: sequence gives this number.
MAX_HYPERLINK_ID_LENGTH = 250

#: The characters that an id may not hold. Three of them separate the
#: parts of the sequence, and a control character ends it early. The id
#: goes back out on the wire, so an id with one of these in it would
#: change what the sequence means there.
_UNSAFE_IN_HYPERLINK_ID = frozenset(";:=\x1b\x07")


def _hyperlink_id(params: str) -> str:
    """
    The id that the parameter field of an "OSC 8" names, or "".

    The field is "key=value : key=value", and the specification gives
    one key: "id". A pane keeps the id, because it joins the pieces of
    one link, so a link that a line break cuts in two stays one link.
    """
    for part in params.split(":"):
        key, _, value = part.partition("=")
        if key != "id":
            continue
        if not value or len(value) > MAX_HYPERLINK_ID_LENGTH:
            return ""
        if any(
            character < " "
            or character == "\x7f"
            or character in _UNSAFE_IN_HYPERLINK_ID
            for character in value
        ):
            return ""
        return value
    return ""


def parse_hyperlink(param: str) -> tuple[str, str] | None:
    """
    The id and the target of an "OSC 8", or `None` when there is none.

    The payload is "params ; target". An empty target closes the link
    that is open, and it comes back as a pair of empty strings.

    A control character would end the sequence early on the terminal of
    the user, and what follows would run as a command of its own, so a
    target that holds one is no target at all.
    """
    if ";" not in param:
        return None
    params, target = param.split(";", 1)
    if not target:
        return "", ""  # Close the link that is open.
    if len(target) > MAX_HYPERLINK_LENGTH:
        return None
    if any(character < " " or character == "\x7f" for character in target):
        return None
    return _hyperlink_id(params), target


#: The stack of pointer shapes that a terminal keeps. kitty asks for a
#: minimum of sixteen, and uses sixteen itself.
MAX_POINTER_SHAPES = 16

#: The shapes that a terminal must know, named after the cursor
#: property of CSS.
POINTER_SHAPES = frozenset(
    [
        "alias",
        "cell",
        "copy",
        "crosshair",
        "default",
        "e-resize",
        "ew-resize",
        "grab",
        "grabbing",
        "help",
        "move",
        "n-resize",
        "ne-resize",
        "nesw-resize",
        "no-drop",
        "not-allowed",
        "ns-resize",
        "nw-resize",
        "nwse-resize",
        "pointer",
        "progress",
        "s-resize",
        "se-resize",
        "sw-resize",
        "text",
        "vertical-text",
        "w-resize",
        "wait",
        "zoom-in",
        "zoom-out",
    ]
)

#: The names that xterm used, which kitty takes as well. A set takes
#: them; kitty leaves "arrow" and "beam" out of the set that its own
#: "OSC 22" reads, so those are not here either.
POINTER_SHAPE_ALIASES = {
    "bottom_left_corner": "sw-resize",
    "bottom_right_corner": "se-resize",
    "bottom_side": "s-resize",
    "clock": "wait",
    "closedhand": "grabbing",
    "cross": "cell",
    "crossed_circle": "not-allowed",
    "dnd-copy": "copy",
    "dnd-link": "alias",
    "dnd-no-drop": "no-drop",
    "dnd-none": "grabbing",
    "fleur": "move",
    "forbidden": "not-allowed",
    "half-busy": "progress",
    "hand": "pointer",
    "hand1": "grab",
    "hand2": "pointer",
    "ibeam": "text",
    "left_ptr": "default",
    "left_ptr_watch": "progress",
    "left_side": "w-resize",
    "openhand": "grab",
    "plus": "cell",
    "pointer-move": "move",
    "pointing_hand": "pointer",
    "question_arrow": "help",
    "right_side": "e-resize",
    "sb_h_double_arrow": "ew-resize",
    "sb_v_double_arrow": "ns-resize",
    "size-bdiag": "nesw-resize",
    "size-fdiag": "nwse-resize",
    "size_bdiag": "nesw-resize",
    "size_fdiag": "nwse-resize",
    "split_h": "ew-resize",
    "split_v": "ns-resize",
    "tcross": "crosshair",
    "top_left_corner": "nw-resize",
    "top_right_corner": "ne-resize",
    "top_side": "n-resize",
    "watch": "wait",
    "whats_this": "help",
    "xterm": "text",
    "zoom_in": "zoom-in",
    "zoom_out": "zoom-out",
}


def pointer_shape_name(name: str) -> str | None:
    """
    The shape that a name stands for, or `None` for a name that no
    terminal knows.

    An empty name is the shape of nobody: it takes the shape away.
    """
    if not name:
        return ""
    if name in POINTER_SHAPES:
        return name
    return POINTER_SHAPE_ALIASES.get(name)


class PointerShapeRead(NamedTuple):
    'What one "OSC 22" payload asks the screen to do.'

    #: The payload to answer with, or `None` when the sequence asked
    #: no question.
    answer: str | None

    #: Did the shape change? Then the embedder has to look again.
    changed: bool


class PointerShapes:
    """
    The stack of pointer shapes that "OSC 22" keeps.

    The main and the alternate screen each have their own, so this
    rides in `Screen.swap_variables` the way `GraphicsState` does.

    A pane has no pointer of its own. It holds the stack so that it
    can tell an embedder what the program asked for, and so that it
    can answer a program that asks what it holds.
    """

    __slots__ = ("stack",)

    def __init__(self) -> None:
        self.stack: List[str] = []

    @property
    def shape(self) -> str:
        """
        The shape now.

        An empty string means that no program asked for one, and that
        whoever draws the pointer picks it.
        """
        return self.stack[-1] if self.stack else ""

    def read(self, param: str) -> PointerShapeRead:
        """
        Read one "OSC 22" payload.

        A bare name or "=name" replaces the shape now, ">a,b" pushes,
        "<" pops one, and an empty payload takes the shape away.
        "?names" asks a question, which this answers.
        """
        operation = "="
        if param and param[0] in "><=?":
            operation, param = param[0], param[1:]

        if operation == "?":
            return PointerShapeRead(self._answer(param), False)

        if operation == "<":
            if not self.stack:
                return PointerShapeRead(None, False)
            self.stack.pop()
            return PointerShapeRead(None, True)

        changed = False
        for name in param.split(","):
            if not name and operation != "=":
                continue  # A push of nothing pushes nothing.
            shape = pointer_shape_name(name)
            if shape is None:
                continue  # Not a shape that a terminal knows.
            if operation == "=":
                if self.stack:
                    self.stack[-1] = shape
                else:
                    self.stack.append(shape)
            else:
                if len(self.stack) >= MAX_POINTER_SHAPES:
                    del self.stack[0]  # The oldest goes.
                self.stack.append(shape)
            changed = True
        return PointerShapeRead(None, changed)

    def _answer(self, param: str) -> str:
        """
        The payload of the answer to "OSC 22 ; ? names".

        A name that this takes answers one, a name that nobody knows
        answers zero, and "__current__" answers the shape now, or zero
        when there is none. A pane has no pointer of its own, so the
        default and the grabbed shape are both the plain default.

        kitty answers for the table of CSS names, and takes a few more
        names than it calls valid. This answers for the names it really
        takes, which is what a program asking the question wants to
        know.
        """
        answers = []
        for query in param.split(","):
            if query and pointer_shape_name(query) is not None:
                answers.append("1")
            elif query == "__current__":
                answers.append(self.shape or "0")
            elif query in ("__default__", "__grabbed__"):
                answers.append("default")
            else:
                answers.append("0")
        return "22;%s" % ",".join(answers)


#: The value that asks for a colour instead of setting one.
QUERY = "?"


class ColorOverrides:
    """
    The colours that a program set, over the ones a pane starts with.

    Two tables, because a program names a colour two ways. "OSC 4" and
    "OSC 5" number one, and "OSC 10" and the codes after it name one.
    The two arrive apart and go back apart, so they are kept apart, and
    they are together here because one question reads both: what colour
    does this pane draw for that?

    Every method that answers a program returns the payloads to send
    and writes nothing. A pane has one screen of these, and a reset
    takes them all away.
    """

    __slots__ = ("by_index", "by_code")

    def __init__(self) -> None:
        #: What "OSC 4" and "OSC 5" set, by the index into the palette
        #: and the special colours after it.
        self.by_index: Dict[int, Color] = {}

        #: What "OSC 10" and the codes after it set, by the code that
        #: set it.
        self.by_code: Dict[str, Color] = {}

    def color_of(self, index: int) -> Color | None:
        """
        The colour that "OSC 4" reports for an index.

        The palette comes first and the special colours follow it. The
        answer is what a program set, or the default when it set
        nothing. `None` is an index that this pane does not hold.
        """
        held = self.by_index.get(index)
        if held is not None:
            return held
        if index < len(PALETTE):
            return PALETTE[index]
        # A special colour that nobody set draws in the colour of the
        # text. xterm leaves such a colour unset and paints the text
        # colour, so that is the honest answer.
        #
        # It is the foreground this pane holds now, and not the default
        # one. A program can set the foreground with "OSC 10", and the
        # bold text of that program then draws in the colour it set.
        if index - FIRST_SPECIAL_COLOR < len(SPECIAL_COLOR_NAMES):
            return self.named("foreground")
        return None

    def named(self, name: str) -> Color:
        """
        The colour that a name stands for, as this pane holds it now.

        A dynamic colour that a program set wins over the default. Both
        "OSC 10" and the kitty query read the same colour, so both read
        this.
        """
        for code, named in DYNAMIC_COLOR_CODES.items():
            if named == name and code in self.by_code:
                return self.by_code[code]
        return DEFAULT_COLORS[name]

    def read_indexed(self, code: str, param: str, offset: int) -> List[str]:
        """
        Read "OSC 4" or "OSC 5": the palette and the special colours.

        The payload holds index and value pairs. A value of "?" asks
        for the colour and the others set it. `offset` is what the
        written index needs to reach the table, because "OSC 5"
        numbers the special colours from zero and "OSC 4" numbers them
        after the palette.

        Each query gets a payload of its own. A program reads one
        answer for each question it asked, so two questions may not
        come back as one.
        """
        answers = []
        parts = param.split(";")
        for index in range(0, len(parts) - 1, 2):
            number, value = parts[index], parts[index + 1]
            if not number.isdigit():
                continue
            entry = int(number) + offset
            if value.strip() == QUERY:
                color = self.color_of(entry)
                if color is not None:
                    answers.append("%s;%s;%s" % (code, number, color.spec))
            else:
                color = parse_color(value)
                if color is not None and self.color_of(entry) is not None:
                    self.by_index[entry] = color
        return answers

    def reset_indexed(self, param: str, offset: int, count: int) -> None:
        """
        Read "OSC 104" or "OSC 105": put colours back to the defaults.

        The payload names the indexes to put back. An empty payload
        puts back every colour that the sequence covers, which is the
        palette for one code and the special colours for the other.
        """
        if not param.strip():
            for entry in range(offset, offset + count):
                self.by_index.pop(entry, None)
            return
        for number in param.split(";"):
            if number.isdigit():
                self.by_index.pop(int(number) + offset, None)

    def read_dynamic(self, code: str, param: str) -> List[str]:
        """
        Read "OSC 10" and the codes after it: the colours that a
        terminal names rather than numbers.

        One payload may carry several values, and each one moves on to
        the next code. "OSC 10 ; spec1 ; spec2" sets the foreground and
        then the background. A code that a pane does not hold is
        counted and skipped, so the ones after it still land right.
        """
        answers = []
        for step, value in enumerate(param.split(";")):
            number = str(int(code) + step)
            if number not in DYNAMIC_COLOR_CODES:
                continue
            if value.strip() == QUERY:
                color = self.by_code.get(
                    number, DEFAULT_COLORS[DYNAMIC_COLOR_CODES[number]]
                )
                answers.append("%s;%s" % (number, color.spec))
            else:
                color = parse_color(value)
                if color is not None:
                    self.by_code[number] = color
        return answers

    def reset_dynamic(self, code: str) -> None:
        'Read "OSC 110" and the codes after it: put one colour back.'
        self.by_code.pop(code, None)

    def answer_kitty(self, param: str) -> str | None:
        """
        The payload that answers a kitty colour query, e.g.
        "OSC 21 ; background=?", or `None` when there is nothing to
        answer.

        kitty joins its answers into one sequence, which is what its
        own protocol says. The xterm queries answer one at a time.
        """
        keys = parse_kitty_color_query(param)
        if keys is None:
            return None

        answers = []
        for key, is_query in keys:
            if not is_query:
                continue
            if key.isdigit() and int(key) < len(PALETTE):
                color = self.color_of(int(key))
                answers.append("%s=%s" % (key, color.spec))
            elif key in DEFAULT_COLORS:
                answers.append("%s=%s" % (key, self.named(key).spec))
            else:
                answers.append("%s=" % key)  # Not a colour that we hold.
        if not answers:
            return None
        return "21;%s" % ";".join(answers)
