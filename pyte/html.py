"""
How a browser spells what a cell carries.

A screen holds an `Appearance`: the rendition that SGR set, and the
hyperlink that "OSC 8" opened. Both are a model, and neither is a
spelling. What a renderer writes for them is the renderer's own answer,
and this file is CSS's.

**Why this one lives with the screen, when the other two do not.**
`ptterm/style.py` spells a prompt_toolkit style string and
`txterm/style.py` spells a `rich.style.Style`; each belongs with the
package that holds the library it speaks for. CSS has no library. It is
a standard a string is written in, like the sixel `sixel.py` writes and
the sequences `sequences.py` builds, so it asks nothing of this package
that the screen does not already do. Lillecarl/pymux#452.

**CSS carries more of a rendition than either of the others.** Rich
drops the shape of an underline, its colour and the baseline; a browser
draws all three. What no spelling here can do exactly is dim: a
terminal halves the intensity of the colour, and `color-mix` is the
nearest thing CSS has.

The output is meant for a `pre`::

    <style>{CSS}</style>
    <pre class="pyte-screen">{html_of_page(page, 0, 23, 80)}</pre>

`pre` and not a block for each row, because that is what makes a blank
row take a line and a copy of the screen come out as lines. A caller
that wants each row to be an element of its own -- to replace one row
and not the screen -- wraps `html_of_row` itself, and then the newlines
this puts between rows have to go.
"""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from typing import TYPE_CHECKING, NamedTuple

from .cells import PLAIN_APPEARANCE, appearance_of
from .colors import DEFAULT_COLORS, PALETTE, SgrColor
from .placeholders import PLACEHOLDER

if TYPE_CHECKING:
    from .cells import Appearance, Cell
    from .osc import ColorOverrides
    from .page import Page, Row

__all__ = (
    "CSS",
    "Drawn",
    "SAFE_SCHEMES",
    "SCREEN_CLASS",
    "THEMED",
    "color_value",
    "href_of",
    "html_of_page",
    "html_of_row",
    "runs_of_row",
    "style_of",
    "theme_css",
    "visible_char",
)

#: The class on the element that holds a page.
#:
#: Every rule of `CSS` is written under it and `theme_css` redefines the
#: properties there, so a caller that builds the element writes this and
#: not a copy of it.
SCREEN_CLASS = "pyte-screen"

#: How many colours of the palette a theme is asked about.
#:
#: The first sixteen, and no more. A program that names one of those
#: asks the terminal of the user to paint it, and that terminal has a
#: theme, so each one becomes a custom property that a stylesheet can
#: answer. The 6x6x6 cube and the grey ramp above them are the same
#: numbers in every terminal, so those are written out as they are:
#: two hundred and forty custom properties nobody redefines would
#: travel with every page for nothing.
THEMED = 16

#: The custom property that each themed colour reads.
_PROPERTY = "--pyte-%d"

#: The two the terminal itself decides: what it draws with, and what it
#: draws on. "SGR 39" and "SGR 49" ask for these by name, and a
#: reversed cell swaps them, so both need a value a stylesheet can set.
_FOREGROUND = "--pyte-fg"
_BACKGROUND = "--pyte-bg"

#: The URL schemes that a hyperlink may carry.
#:
#: **A pane writes "OSC 8", so a program in a pane chooses this URL.**
#: In a terminal that costs little: the terminal opens what the person
#: clicks. In a document it is a script that runs in the page, so
#: `javascript:` and `data:` are refused, and so is a URL with no
#: scheme at all -- a relative URL would point at whatever is serving
#: the page, which is nothing a program in a pane may name. The link
#: goes away and the text stays. Lillecarl/pymux#452.
SAFE_SCHEMES = frozenset(["http", "https", "mailto", "ftp", "ftps", "file", "tel"])

#: What each shape of underline draws, in the words CSS uses.
_UNDERLINE_STYLES = {
    "": "solid",
    "double": "double",
    "curly": "wavy",
    "dotted": "dotted",
    "dashed": "dashed",
}

#: Where a raised or lowered glyph sits.
_BASELINES = {
    "superscript": "super",
    "subscript": "sub",
}

#: How much of the background is mixed into the colour of a dim cell.
#:
#: A terminal draws dim by halving the intensity of the colour it was
#: given, which needs the colour itself; a themed colour here is a
#: custom property and arithmetic cannot reach inside one. `color-mix`
#: can, and mixing towards the background is the same idea: the glyph
#: comes closer to what it sits on. It is the one part of a rendition
#: that is near and not exact.
_DIM = 50


def color_value(color: SgrColor, background: bool = False) -> str:
    """
    The CSS colour for one colour of a cell.

    A number of the palette under `THEMED` stays a number, as a custom
    property, so the stylesheet of the page decides what it looks like
    the way the theme of a terminal does. A number above that is a
    place in the cube every terminal agrees about, and a colour a
    program named itself has no theme to ask, so both are written out.

    `SgrColor()` with neither is the colour of the terminal by name
    ("SGR 39" and "SGR 49"), and `background` says which of the two.
    """
    if color.rgb is not None:
        return color.rgb.hex
    if color.index is None:
        return "var(%s)" % (_BACKGROUND if background else _FOREGROUND)
    if color.index < THEMED:
        return "var(%s)" % (_PROPERTY % color.index)
    return PALETTE[color.index].hex


class Drawn(NamedTuple):
    """
    How one cell is drawn: the classes it takes, and what is left over.

    **Most of a rendition has no value in it.** Bold, italic, blink,
    hidden, the two baselines, the two lines and the five underline
    shapes are each one fixed declaration, so each is a rule in `CSS`
    and a word here instead of forty characters on every span that has
    it. Measured on a real pane: 134 styled spans in one frame, polled
    twice a second for each viewer. Lillecarl/pymux#460.

    What is left in `style` is what carries a value: a colour past the
    themed sixteen, a colour a program named itself, and the mix that
    draws a dim cell.

    A page can then allow `style-src-attr 'unsafe-inline'` for that
    last case alone, or drop it and lose truecolour.
    """

    classes: str
    style: str

    def __bool__(self) -> bool:
        return bool(self.classes or self.style)


#: What every class of a cell begins with.
_CLASS = "pyte-"

#: The class for the lines through a cell.
#:
#: **Three of them and not two.** One property carries both lines, so
#: two rules that each set `text-decoration-line` do not add up -- the
#: later one wins and the other line is lost. The pair has a class of
#: its own for that reason.
_LINE_CLASSES = {
    (True, False): _CLASS + "underline",
    (False, True): _CLASS + "strike",
    (True, True): _CLASS + "underline-strike",
}

#: What the classes of the themed sixteen begin with, on each side of a
#: cell. A colour above them and a colour a program named itself carry a
#: value, so those stay in the attribute.
_FOREGROUND_CLASS = _CLASS + "fg"
_BACKGROUND_CLASS = _CLASS + "bg"


def _color_class(color: SgrColor, paints_background: bool) -> str:
    """
    The class that paints one of the themed sixteen, or nothing.

    `paints_background` says which side of the cell this colour ends up
    on, which a reverse cell has already swapped. It is not the
    question `color_value` asks: that one is about which colour the
    terminal's own means here.
    """
    if color.rgb is not None or color.index is None or color.index >= THEMED:
        return ""
    under = _BACKGROUND_CLASS if paints_background else _FOREGROUND_CLASS
    return "%s-%d" % (under, color.index)


def _spelled(appearance: Appearance, reverse_video: bool) -> Drawn:
    """
    How one cell is drawn.

    `style_of` is this function with the answers remembered. Nothing
    calls this one directly.
    """
    rendition = appearance.rendition
    declarations: list[str] = []
    classes: list[str] = []

    # **Reverse is a swap and not a property.** CSS has nothing that
    # exchanges the two colours, so the exchange happens here, and a
    # colour the program left to the terminal becomes the property of
    # the other one. A screen in reverse video (DECSCNM) reverses every
    # cell, and a cell that asked for reverse inside it comes back the
    # right way round, which is why this is an inequality and not an
    # "or".
    color = rendition.color or SgrColor()
    bgcolor = rendition.bgcolor or SgrColor()
    if rendition.reverse != reverse_video:
        color, bgcolor = bgcolor, color
        foreground = color_value(color, background=True)
        background = color_value(bgcolor, background=False)
    else:
        foreground = color_value(color)
        background = color_value(bgcolor, background=True)

    if rendition.hidden:
        # **Nothing paints the glyph of a hidden cell**, so no colour is
        # written for it at all. It used to be painted and then covered
        # by a `color:transparent` written last, which a class cannot
        # do: an attribute beats every class, and two classes are
        # settled by the order of the stylesheet. Saying nothing is
        # exact and needs no order. "SGR 8" hides the character and not
        # the space it sits in, so the background below still goes.
        classes.append(_CLASS + "hidden")
    elif rendition.dim:
        # Mixed here rather than left to the cascade: the mix needs both
        # colours, and the cell is the only place that knows them.
        declarations.append("color:color-mix(in srgb, %s %d%%, %s)" % (foreground, _DIM, background))
    elif rendition.color or rendition.reverse != reverse_video:
        painted = _color_class(color, paints_background=False)
        if painted:
            classes.append(painted)
        else:
            declarations.append("color:" + foreground)

    if rendition.bgcolor or rendition.reverse != reverse_video:
        painted = _color_class(bgcolor, paints_background=True)
        if painted:
            classes.append(painted)
        else:
            declarations.append("background-color:" + background)

    if rendition.bold:
        classes.append(_CLASS + "bold")
    if rendition.italic:
        classes.append(_CLASS + "italic")

    if rendition.underline or rendition.strike:
        classes.append(_LINE_CLASSES[(bool(rendition.underline), bool(rendition.strike))])
    if rendition.underline:
        # The class is the CSS keyword, so the rule and the word cannot
        # drift. A solid line is what CSS draws without being told.
        shape = _UNDERLINE_STYLES[rendition.underline_style]
        if shape != "solid":
            classes.append(_CLASS + shape)
        # The colour of a line that nobody draws would travel with every
        # cell for nothing.
        if rendition.underline_color:
            declarations.append("text-decoration-color:" + color_value(rendition.underline_color))

    if rendition.blink:
        classes.append(_CLASS + "blink")

    if rendition.baseline:
        classes.append(_CLASS + rendition.baseline)

    return Drawn(" ".join(classes), ";".join(declarations))


#: The CSS declarations that draw one cell, answered once for each way
#: of drawing rather than once for each cell.
#:
#: The key is an `Appearance`, which `pyte.cells` interns, so the size
#: is read off the cache that hands them out. `reverse_video` belongs
#: to the screen and not to the cell, so it is the same value for every
#: cell of a frame and costs no room worth counting.
style_of = lru_cache(maxsize=appearance_of.size)(_spelled)


def visible_char(char: str) -> str:
    """
    What to draw for the content of one cell.

    A cell that holds nothing is the second half of a double width
    character. The character beside it is two columns wide in the font
    already, so this one draws nothing at all -- a space here would
    move the rest of the row along by one.

    A unicode placeholder stands for a cell of an image, and whatever
    embeds this draws the image itself. It must not be drawn: the
    placeholder is a character no font has, and the marks that carry
    the row and the column pile up on top of it.

    A control character draws as a space. One should never be in a cell
    -- the parser eats them -- and one that is must not reach the
    document: a browser drops most of them and renders the rest as
    nothing a program asked for.
    """
    if not char:
        return ""
    if char.startswith(PLACEHOLDER):
        return " "
    first = ord(char[0])
    if first < 0x20 or first == 0x7F or 0x80 <= first <= 0x9F:
        return " "
    return char


#: What a URL scheme may hold: a letter, and then letters, digits and
#: three marks (RFC 3986).
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")


def href_of(hyperlink: str) -> str:
    """
    The `href` for a link a program opened, or empty for one to refuse.

    **Everything that puts a program's "OSC 8" into a document goes
    through this**, and not only the markup here. A caller that sends a
    cell to a browser another way owes its reader the same refusal, so
    the allowlist lives in one function rather than in each of them.

    **It refuses everything it does not recognise**, which is why the
    whole of the part before the colon has to match. A browser drops a
    tab and a newline inside a scheme before it reads one, so
    `java<tab>script:` runs a script there; here it matches no scheme at
    all and the link goes away. Anything this reads wrongly is a link
    that is not made, never one that is made and should not be.
    """
    head, colon, _rest = hyperlink.partition(":")
    if not colon or not _SCHEME.fullmatch(head):
        return ""
    if head.lower() not in SAFE_SCHEMES:
        return ""
    return escape(hyperlink, quote=True)


def _draws(cell: Cell, reverse_video: bool) -> bool:
    """
    Whether a cell puts anything on the screen at all.

    A row is as wide as the screen and a program writes part of it, so
    the rest is this. It is asked from the right, to find where the row
    stops. A screen in reverse video draws every cell, including the
    ones nobody wrote.
    """
    if reverse_video:
        return True
    if cell.appearance is not PLAIN_APPEARANCE:
        return True
    return visible_char(cell.char) not in ("", " ")


def runs_of_row(row: Row, columns: int, reverse_video: bool = False) -> list[tuple[Appearance, str]]:
    """
    One row, as the stretches of it that draw the same way.

    Cells that draw the same way are one run, because a screen is mostly
    runs of one appearance: a run for each cell of a wide screen is
    sixty thousand of whatever the caller makes per frame.

    **The blanks at the end of a row are left out.** Nothing draws them,
    so they would only put trailing spaces into anything copied out. A
    blank a program wrote stays if it carries a background, and in
    reverse video every cell draws.

    This is where a row ends and what a blank is worth, and it is one
    function because more than one thing asks: the markup below, and a
    caller that sends the cells somewhere else. Lillecarl/pymux#461.
    """
    last = columns - 1
    while last >= 0 and not _draws(row[last], reverse_video):
        last -= 1
    if last < 0:
        return []

    runs: list[tuple[Appearance, str]] = []
    text: list[str] = []
    appearance = row[0].appearance

    for column in range(last + 1):
        cell = row[column]
        # Identity, not equality: `pyte.cells` hands out one
        # `Appearance` for each way of drawing, so a run is a pointer
        # comparison.
        if cell.appearance is not appearance:
            if text:
                runs.append((appearance, "".join(text)))
                text.clear()
            appearance = cell.appearance
        text.append(visible_char(cell.char))

    if text:
        runs.append((appearance, "".join(text)))
    return runs


def html_of_row(row: Row, columns: int, reverse_video: bool = False) -> str:
    "One row of a screen, as the spans that draw it."
    pieces: list[str] = []

    for appearance, run in runs_of_row(row, columns, reverse_video):
        content = escape(run)
        drawn = style_of(appearance, reverse_video)
        link = href_of(appearance.hyperlink)
        if not link and not drawn:
            pieces.append(content)
            continue

        attributes = ""
        if link:
            attributes += ' href="%s"' % (link,)
        if drawn.classes:
            attributes += ' class="%s"' % (drawn.classes,)
        if drawn.style:
            attributes += ' style="%s"' % (drawn.style,)
        tag = "a" if link else "span"
        pieces.append("<%s%s>%s</%s>" % (tag, attributes, content, tag))

    return "".join(pieces)


def html_of_page(
    page: Page,
    first: int,
    last: int,
    columns: int,
    reverse_video: bool = False,
) -> str:
    """
    The rows of a screen between `first` and `last`, for a `pre`.

    The rows are joined by a newline, which is what makes a blank row
    take a line and a copy of the page come out as lines. The module
    docstring has the element to put it in.

    Nothing here writes to the page. A row the buffer does not hold is
    an empty line, and asking the buffer for it would make one --
    `page.data_buffer` is a defaultdict, and a row made below the floor
    of the history is a row that came back from the dead.
    """
    rows = []
    for number in range(first, last + 1):
        row = page.data_buffer.get(number)
        if row is None:
            rows.append("")
        else:
            rows.append(html_of_row(row, columns, reverse_video))
    return "\n".join(rows)


def _theme() -> str:
    "The custom properties, with the palette's own colours as the answer."
    lines = [
        "  %s: %s;" % (_FOREGROUND, DEFAULT_COLORS["foreground"].hex),
        "  %s: %s;" % (_BACKGROUND, DEFAULT_COLORS["background"].hex),
    ]
    for index in range(THEMED):
        lines.append("  %s: %s;" % (_PROPERTY % index, PALETTE[index].hex))
    return "\n".join(lines)


#: The stylesheet that the spans of `html_of_page` are written against.
#:
#: Three things in it are not decoration. `white-space: pre` is what
#: makes the columns of a row land where the screen put them. The
#: anchor rule is what stops a browser drawing a link its own way: a
#: cell that a program underlined is underlined, and one it did not is
#: not. And the keyframes are the blink, which cannot be written inline.
#:
def _renditions() -> str:
    """
    One rule for each part of a rendition that carries no value.

    Every one of these was a declaration on the span that had it, and
    each span that had one carried the whole spelling. `Drawn` says
    what that cost. Lillecarl/pymux#460.

    The rules are written from the same tables the classes are, so a
    name here and a name there cannot drift.
    """
    rules = [
        ("bold", "font-weight: bold;"),
        ("italic", "font-style: italic;"),
        ("blink", "animation: pyte-blink 1s step-end infinite;"),
        # The glyph goes and the cell keeps its background, which is
        # what "SGR 8" means. No colour is written for such a cell, so
        # nothing here has to win over one.
        ("hidden", "color: transparent;"),
    ]
    for (underline, strike), name in _LINE_CLASSES.items():
        lines = " ".join(["underline"] * underline + ["line-through"] * strike)
        rules.append((name[len(_CLASS) :], "text-decoration-line: %s;" % (lines,)))
    for shape in set(_UNDERLINE_STYLES.values()) - {"solid"}:
        rules.append((shape, "text-decoration-style: %s;" % (shape,)))
    for baseline, where in _BASELINES.items():
        rules.append((baseline, "vertical-align: %s;\n  font-size: smaller;" % (where,)))
    for index in range(THEMED):
        value = "var(%s)" % (_PROPERTY % index,)
        rules.append(("fg-%d" % index, "color: %s;" % (value,)))
        rules.append(("bg-%d" % index, "background-color: %s;" % (value,)))

    # A descendant of the screen, so that a colour here beats the one
    # the screen itself sets.
    return "\n".join(".%s .%s%s { %s }" % (SCREEN_CLASS, _CLASS, name, body) for name, body in rules)


#: The custom properties are the theme, and a page that wants another
#: one redefines them on `.pyte-screen`. The values here are the
#: palette this package already holds, so there is one copy of them.
#:
#: The rules under it answer the classes a span takes. `Drawn` says why
#: a span takes one rather than carrying the declaration itself.
CSS = """.%s {
%s
  white-space: pre;
  font-family: monospace;
  color: var(%s);
  background-color: var(%s);
}

.%s a {
  color: inherit;
  text-decoration: inherit;
}

@keyframes pyte-blink {
  50%% { visibility: hidden; }
}

%s
""" % (
    SCREEN_CLASS,
    _theme(),
    _FOREGROUND,
    _BACKGROUND,
    SCREEN_CLASS,
    _renditions(),
)


def theme_css(colors: ColorOverrides) -> str:
    """
    The rule that makes a page draw in one screen's own colours.

    `CSS` answers the sixteen properties and the two defaults with the
    palette this package holds. A screen holds its own: the theme its
    embedder set with `set_color_base`, and whatever the program on it
    changed with "OSC 4" or "OSC 10". This writes those over the top,
    so it goes after `CSS` and under the same selector, where the later
    rule wins.

    The cube past `THEMED` is not in it, for the reason `THEMED` gives.
    A program that sets one of those with "OSC 4" does not reach a
    browser, and Lillecarl/pymux#452 holds that.
    """
    lines = [
        "  %s: %s;" % (_FOREGROUND, colors.named("foreground").hex),
        "  %s: %s;" % (_BACKGROUND, colors.named("background").hex),
    ]
    for index in range(THEMED):
        color = colors.color_of(index)
        if color is not None:
            lines.append("  %s: %s;" % (_PROPERTY % index, color.hex))
    return ".%s {\n%s\n}\n" % (SCREEN_CLASS, "\n".join(lines))
