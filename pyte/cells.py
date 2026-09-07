"""
What one cell of a screen is, and how a program asked for it to be
drawn.

A cell holds a character and an `Appearance`. **The appearance is a
model and not a spelling**: it names the fields SGR names, and a front
end decides how to draw them. `ptterm/style.py` spells one for
prompt_toolkit and `txterm/style.py` spells a `rich.style.Style` from
the same object, and neither has to parse the other's words.

Nothing here reads a sequence or writes one. `screen.py` parses SGR
into a `Rendition` and `page.py` says what holds the cells.
Lillecarl/pymux#129.
"""
from enum import IntFlag
from functools import lru_cache
from typing import NamedTuple, Tuple

from wcwidth import wcwidth  # type: ignore[import-untyped]

from .cache import FastDictCache
from .colors import SgrColor

__all__ = (
    "BASELINE_PARAMETERS",
    "UNDERLINE_PARAMETERS",
    "UNDERLINE_SHAPES",
    "Appearance",
    "Cell",
    "ErasedCell",
    "PLAIN",
    "PLAIN_APPEARANCE",
    "Protection",
    "ProtectedCell",
    "Rendition",
    "WrittenCell",
    "appearance_of",
    "character_width",
    "protection_of",
)


#: The shape of the line that each sub-parameter of "SGR 4" draws.
#: Zero draws none. An empty name is the single line that a plain
#: "SGR 4" draws.
UNDERLINE_SHAPES = {
    0: "",
    1: "",
    2: "double",
    3: "curly",
    4: "dotted",
    5: "dashed",
}

#: The sub-parameter of "SGR 4" that each shape answers with.
UNDERLINE_PARAMETERS = {
    "": "4",
    "double": "4:2",
    "curly": "4:3",
    "dotted": "4:4",
    "dashed": "4:5",
}

#: The parameter that raises or lowers a glyph. "SGR 75" puts it back
#: on the line and needs no parameter of its own: a report starts with
#: a reset, which says the same thing.
BASELINE_PARAMETERS = {
    "superscript": "73",
    "subscript": "74",
}


@lru_cache(maxsize=4096)
def character_width(text: str) -> int:
    """
    How many columns the content of one cell takes.

    A combining mark measures zero and hangs on the character before
    it, so a cell that holds a base and its marks is as wide as the
    base alone. A control character measures -1 and draws nothing, so
    it counts as nothing here.
    """
    if len(text) == 1:
        return max(0, wcwidth(text))
    return sum(character_width(character) for character in text)


class Cell:
    """
    One cell of a screen: what a program wrote there, and how it asked
    for it to be drawn.

    It is immutable, and `_CHAR_CACHE` hands out one object for each
    pair, so a screen full of spaces holds one cell many times.

    **The appearance is a model and not a spelling.** A cell held a
    prompt_toolkit style string before this, so a second front end
    could only read it by parsing one toolkit's words back into the
    fields they came from. `ptterm/style.py` spells one for
    prompt_toolkit, and a Textual widget spells a `rich.style.Style`
    from the same object. Lillecarl/pymux#11 and Lillecarl/pymux#82.

    This was `prompt_toolkit.layout.screen.Char`, without that class's
    `display_mappings`. The table swaps a control character for "^A"
    and a no-break space for an underlined blank, which is right for a
    prompt that a person types into and wrong for a screen: the
    program that wrote the screen already chose what it says.
    `WrittenCell` existed to undo one entry of that table.
    """

    __slots__ = ("char", "appearance", "width")

    def __init__(self, char: str, appearance: "Appearance") -> None:
        self.char = char
        self.appearance = appearance

        # Every caller needs it, so it is a field and not a method.
        self.width = character_width(char)

    def __eq__(self, other: object) -> bool:
        return (
            self.char == other.char  # type: ignore[attr-defined]
            and self.appearance == other.appearance  # type: ignore[attr-defined]
        )

    def __ne__(self, other: object) -> bool:
        # Not `not __eq__`: this is called for every cell of every
        # frame, and one call is cheaper than two.
        return (
            self.char != other.char  # type: ignore[attr-defined]
            or self.appearance != other.appearance  # type: ignore[attr-defined]
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.char!r}, {self.appearance!r})"


class ErasedCell(Cell):
    """
    The blank that an erase leaves behind.

    It draws as a space, and it holds no character. The difference
    matters for one thing: a combining mark that arrives next has
    nothing to hang on, so the mark goes away. A space that a program
    draws is a character, and a mark does hang on that.

    kitty and WezTerm both draw the line in that place. ptterm gave two
    answers for the same program before this. An erase with no
    background drops the cell, so the mark went away. An erase with a
    background wrote a space, so the mark stayed.
    """

    __slots__ = ()


class WrittenCell(Cell):
    """
    One cell that a program wrote, as against one that an erase left.

    It adds nothing to a `Cell`. What it says is who put the character
    there, and two things read that: the renderer keeps a blank that a
    program wrote and drops one that it did not, and a selective erase
    leaves an erased cell alone.
    """

    __slots__ = ()


class Protection(IntFlag):
    """
    The marks that hold an erase away from a cell.

    A cell can carry both, because the two commands that set them are
    not the same command and neither one takes the other away.
    """

    NONE = 0

    #: SPA ("ESC V") sets it. ED, EL and ECH read it.
    ISO = 1

    #: DECSCA ("CSI 1 " q") sets it. The selective erases, DECSED and
    #: DECSEL, read it.
    DEC = 2


class ProtectedCell(WrittenCell):
    """
    One cell that an erase may have to leave alone.

    Two commands mark a cell, and each one holds a different erase
    away from it. `protection` carries both marks, because a cell can
    hold either or both.
    """

    __slots__ = ("protection",)

    def __init__(
        self, char: str, appearance: "Appearance", protection: int = 0
    ) -> None:
        super().__init__(char, appearance)
        self.protection = protection


def protection_of(cell: Cell) -> int:
    "The marks that a cell carries. A plain cell carries none."
    return getattr(cell, "protection", 0)


# Cache for Cell objects.
_CHAR_CACHE: FastDictCache[Tuple[str, "Appearance"], Cell] = FastDictCache(
    WrittenCell, size=1000 * 1000
)

#: The same for the cells that carry a mark. Nearly no program marks
#: one, so this one stays small.
_PROTECTED_CHAR_CACHE: FastDictCache[
    Tuple[str, "Appearance", int], Cell
] = FastDictCache(ProtectedCell, size=10 * 1000)


class Rendition(NamedTuple):
    """
    How a program asked for the next characters to be drawn.

    SGR sets it, "ESC 7" saves it, and every cell keeps the one that
    drew it. The fields are the ones SGR names, so nothing here is a
    decision: a terminal that draws none of them still has to hold
    them, because a program can ask for them back.

    A colour is a number: a place in the palette, or three components
    that a program named itself. `None` means that no program has asked
    for one, and `DEFAULT_COLOR` means that one asked for the colour of
    the terminal by name. DECRQSS has to tell those two apart.

    This was `prompt_toolkit.styles.Attrs`, with the two hyperlink
    fields left out. A hyperlink is not a rendition: it comes from OSC
    8 and not from SGR, and the screen already holds it apart.
    Lillecarl/pymux#11.
    """

    color: SgrColor | None = None
    bgcolor: SgrColor | None = None
    bold: bool = False
    dim: bool = False
    underline: bool = False
    strike: bool = False
    italic: bool = False
    blink: bool = False
    reverse: bool = False
    hidden: bool = False
    #: The shape of the line: "double", "curly", "dotted" or "dashed".
    #: An empty string is a single line, and it only shows when
    #: `underline` is true.
    underline_style: str = ""
    #: The colour of that line, when a program named one apart from the
    #: colour of the text.
    underline_color: SgrColor | None = None
    #: Where the glyph sits: "superscript", "subscript", or an empty
    #: string for on the line.
    baseline: str = ""


#: What a screen draws with when no program has asked for anything.
PLAIN = Rendition()


class Appearance:
    """
    Everything about how one cell looks: the rendition, and the
    hyperlink that the cell sits inside.

    The two are apart because they arrive apart. SGR sets a rendition
    and says nothing about a link; "OSC 8" opens a link and says
    nothing about a rendition. They are together because a cell has one
    of these and a front end wants both at once.

    **Every one of these is interned**, by `appearance_of`. A screen
    holds one object for each way of drawing that a program has asked
    for, so a cell keeps a reference and a comparison is nearly always
    an identity. The hash is taken once, when the object is made, and
    a screen makes one of these per SGR sequence rather than per cell.
    """

    __slots__ = ("rendition", "hyperlink", "hyperlink_id", "_hash")

    def __init__(
        self, rendition: Rendition, hyperlink: str = "", hyperlink_id: str = ""
    ) -> None:
        self.rendition = rendition
        #: The target of the link that is open ("OSC 8"), and the id
        #: that joins its pieces. Both are empty outside a link.
        self.hyperlink = hyperlink
        self.hyperlink_id = hyperlink_id
        self._hash = hash((rendition, hyperlink, hyperlink_id))

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        # Interned, so the first test answers nearly every call.
        if self is other:
            return True
        return (
            self._hash == other._hash  # type: ignore[attr-defined]
            and self.rendition == other.rendition  # type: ignore[attr-defined]
            and self.hyperlink == other.hyperlink  # type: ignore[attr-defined]
            and self.hyperlink_id == other.hyperlink_id  # type: ignore[attr-defined]
        )

    def __repr__(self) -> str:
        if not self.hyperlink:
            return "Appearance(%r)" % (self.rendition,)
        return "Appearance(%r, %r, %r)" % (
            self.rendition, self.hyperlink, self.hyperlink_id
        )


#: One `Appearance` for each way of drawing that a program has asked
#: for. A screen reaches this once per SGR sequence.
appearance_of: FastDictCache[
    Tuple[Rendition, str, str], Appearance
] = FastDictCache(Appearance, size=10 * 1000)

#: How a screen draws before any program has asked for anything, and
#: what an untouched cell carries.
PLAIN_APPEARANCE = appearance_of[PLAIN, "", ""]
