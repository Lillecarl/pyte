"""
pyte
~~~~

A terminal emulator, without a terminal. Two halves:
:class:`~pyte.streams.Stream` parses what a program wrote and
dispatches an event for each command, and
:class:`~pyte.screen.Screen` keeps the cells that those
events draw.

**It answers as a VT520 and honours DECSCL down to a VT100.**
`ConformanceLevel` in `parameters.py` names the five, and the private
modes a later terminal brought go away when a program asks for an
earlier one: the left and right margin arrived on the VT400, and
DECNCSM on the VT500. DA2 names the VT520 family. Nothing between
VT100 and VT520 is skipped, and esctest2's `DECSCLTests` is what
says so.

**The DEC line attributes are the one exception.** "ESC # 3",
"ESC # 4", "ESC # 5" and "ESC # 6" draw a line at twice the width or
twice the height on a VT100. This screen reads each of them and
draws the line the plain way, the way kitty, Ghostty and Alacritty
do. Lillecarl/pymux#141 holds the reasons and the vote.

On top of that are the things no DEC terminal had: 256 colours,
truecolour, the kitty keyboard and graphics protocols, sixels,
hyperlinks, and the underline shapes.

**It opens nothing and draws nothing.** A cell holds an
`Appearance`, which is a model and not a spelling, so a renderer
decides how to draw one: `ptterm` does it with prompt_toolkit and
`txterm` with Rich. `tests/test_the_layers.py` holds the line.

.. warning:: From ``xterm/main.c`` "If you think you know what all
             of this code is doing, you are probably very mistaken.
             There be serious and nasty dragons here" -- nothing
             has changed.

:copyright: (c) 2011-2012 by Selectel.
:copyright: (c) 2012-2017 by pyte authors and contributors,
                see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

__version__ = "0.8.3.dev"

__all__ = ("Screen", "Stream", "ByteStream", "DebugScreen")

from .debug import DebugScreen
from .screen import Screen
from .streams import ByteStream, Stream


if __debug__:
    import io

    def dis(chars: bytes | str) -> None:
        """A :func:`dis.dis` for terminals.

        >>> dis(b"\x07")       # doctest: +NORMALIZE_WHITESPACE
        ["bell", [], {}]
        >>> dis(b"\x1b[20m")   # doctest: +NORMALIZE_WHITESPACE
        ["select_graphic_rendition", [20], {}]
        """
        if isinstance(chars, str):
            chars = chars.encode("utf-8")

        with io.StringIO() as buf:
            ByteStream(DebugScreen(to=buf)).feed(chars)
            print(buf.getvalue())
