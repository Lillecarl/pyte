"""
A screen as HTML for a reader that never draws it: an agent.

`html.py` writes for a browser, which a stylesheet themes and a viewer
polls, so it names colours by custom property and renditions by class.
A reader that only reads cannot fetch the stylesheet, and every byte
it reads is a token. So this writes what the eye would see, in the
fewest tags a model already knows:

- A colour is the colour this screen paints, as `#rrggbb`. The screen's
  own colours go once on the `pre`, and a run that draws in them says
  nothing.
- Bold, italic, underline and strike are `b`, `i`, `u` and `s`. Dim is
  `opacity:.5`. A hidden glyph is a blank. Blink and the shapes of an
  underline are left out: they change nothing a reader acts on.
- **A blank takes the spelling of the run before it** when the two
  paint the same background and draw the same lines through it. A
  blank cell carries a foreground nobody sees, and without this every
  space between two coloured words opened a span of its own. Measured
  on a Claude Code pane: 12 KB of `html.py` against 1.1 KB of text.
  asciinema's player merges its spaces the same way; it paints the
  background on a layer of its own and so can ignore it, which one
  layer of HTML cannot.
- Only `&` and `<` are escaped, which is all a `pre` needs.

A hyperlink stays a link: it passes `href_of`, like every other way a
program's "OSC 8" reaches a document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .colors import DEFAULT_COLORS, PALETTE, SgrColor
from .html import THEMED, href_of, runs_of_row

if TYPE_CHECKING:
    from .cells import Appearance
    from .osc import ColorOverrides
    from .page import Page, Row

__all__ = ("compact_html_of_page", "compact_html_of_row")


class _Spelling(NamedTuple):
    "How one run reads: each field empty or false where the screen's own default holds."

    href: str
    color: str
    background: str
    bold: bool
    italic: bool
    underline: bool
    strike: bool
    dim: bool


class _Palette(NamedTuple):
    foreground: str
    background: str
    themed: tuple[str, ...]

    @classmethod
    def of(cls, colors: ColorOverrides | None) -> _Palette:
        if colors is None:
            return cls(
                DEFAULT_COLORS["foreground"].hex,
                DEFAULT_COLORS["background"].hex,
                tuple(PALETTE[index].hex for index in range(THEMED)),
            )
        themed = []
        for index in range(THEMED):
            held = colors.color_of(index)
            themed.append((held or PALETTE[index]).hex)
        return cls(colors.named("foreground").hex, colors.named("background").hex, tuple(themed))

    def value(self, color: SgrColor) -> str:
        "The colour a cell asked for, or empty for the screen's own."
        if color.rgb is not None:
            return color.rgb.hex
        if color.index is None:
            return ""
        if color.index < THEMED:
            return self.themed[color.index]
        return PALETTE[color.index].hex


def _spelled(appearance: Appearance, palette: _Palette, reverse_video: bool) -> _Spelling:
    rendition = appearance.rendition
    color = palette.value(rendition.color or SgrColor())
    background = palette.value(rendition.bgcolor or SgrColor())
    if rendition.reverse != reverse_video:
        color, background = background or palette.background, color or palette.foreground
    return _Spelling(
        href=href_of(appearance.hyperlink),
        color=color,
        background=background,
        bold=bool(rendition.bold),
        italic=bool(rendition.italic),
        underline=bool(rendition.underline),
        strike=bool(rendition.strike),
        dim=bool(rendition.dim),
    )


def _escaped(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;")


#: The tag for each rendition that has one, outermost first.
_TAGS = (("bold", "b"), ("italic", "i"), ("underline", "u"), ("strike", "s"))


def _wrapped(opened: list[str], inner: str) -> str:
    closed = "".join("</%s>" % (tag.partition(" ")[0],) for tag in reversed(opened))
    return "".join("<%s>" % (tag,) for tag in opened) + inner + closed


def _outer(spelling: _Spelling) -> list[str]:
    "The link and the span: what several runs in a row share when only a rendition changes."
    opened = []
    style = []
    if spelling.color:
        style.append("color:" + spelling.color)
    if spelling.background:
        style.append("background:" + spelling.background)
    if spelling.dim:
        style.append("opacity:.5")
    if spelling.href:
        opened.append('a href="%s"' % (spelling.href,))
    if style:
        opened.append('span style="%s"' % (";".join(style),))
    return opened


def _written(pieces: list[tuple[_Spelling, str]]) -> str:
    "Runs, with one span around each stretch that shares it, so a bold word does not reopen its colour."
    written: list[str] = []
    index = 0
    while index < len(pieces):
        outer = _outer(pieces[index][0])
        inner: list[str] = []
        while index < len(pieces) and _outer(pieces[index][0]) == outer:
            spelling, text = pieces[index]
            inner.append(_wrapped([tag for field, tag in _TAGS if getattr(spelling, field)], _escaped(text)))
            index += 1
        written.append(_wrapped(outer, "".join(inner)))
    return "".join(written)


def _lines_of(spelling: _Spelling) -> tuple[str, str, bool, bool]:
    "What a blank shows of its spelling: the background, the link, and the lines through it."
    return (spelling.background, spelling.href, spelling.underline, spelling.strike)


def _row(row: Row, columns: int, palette: _Palette, reverse_video: bool) -> str:
    pieces: list[tuple[_Spelling, str]] = []
    for appearance, text in runs_of_row(row, columns, reverse_video):
        spelling = _spelled(appearance, palette, reverse_video)
        if appearance.rendition.hidden:
            text = " " * len(text)
        if pieces and not text.strip(" "):
            before = pieces[-1][0]
            if _lines_of(spelling) == _lines_of(before):
                spelling = before
        if pieces and pieces[-1][0] == spelling:
            pieces[-1] = (spelling, pieces[-1][1] + text)
        else:
            pieces.append((spelling, text))
    # `runs_of_row` keeps a trailing blank that names a colour, and one
    # that names the screen's own background still draws nothing.
    while pieces and not (pieces[-1][0].background or pieces[-1][0].underline or pieces[-1][0].strike):
        spelling, text = pieces[-1]
        trimmed = text.rstrip(" ")
        if trimmed:
            pieces[-1] = (spelling, trimmed)
            break
        pieces.pop()
    return _written(pieces)


def compact_html_of_row(
    row: Row, columns: int, colors: ColorOverrides | None = None, reverse_video: bool = False
) -> str:
    "One row of a screen, spelled as the module docstring says."
    return _row(row, columns, _Palette.of(colors), reverse_video)


def compact_html_of_page(
    page: Page,
    first: int,
    last: int,
    columns: int,
    colors: ColorOverrides | None = None,
    reverse_video: bool = False,
) -> str:
    """
    The rows between `first` and `last` as one `pre`, a row to a line.

    `colors` are the screen's own, which the `pre` paints with; without
    them, the palette this package holds. Like `html_of_page`, a row the
    buffer does not hold is an empty line, and nothing here makes one.
    """
    palette = _Palette.of(colors)
    if reverse_video:
        foreground, background = palette.background, palette.foreground
    else:
        foreground, background = palette.foreground, palette.background
    rows = []
    for number in range(first, last + 1):
        row = page.data_buffer.get(number)
        rows.append("" if row is None else _row(row, columns, palette, reverse_video))
    return '<pre style="color:%s;background:%s">%s</pre>' % (foreground, background, "\n".join(rows))
