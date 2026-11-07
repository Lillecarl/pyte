"""
What the embedder tells a screen about where it is drawn.

None of it comes from the program's bytes. The thing that draws the
screen knows how big a cell is, which colours the terminal paints, and
what its keyboard can report, and it says so through the setters on
`Screen`. A freeze leaves these out, because an embedder pushes them
again after a load.

A mirror of the screen has no embedder of its own to ask: the screen it
mirrors is drawn somewhere else, by somebody else's terminal. So these
travel to it as one value, beside the reads. Lillecarl/pyterm#761.
"""

from __future__ import annotations

from typing import NamedTuple

from .osc import ColorBase

__all__ = ["Surroundings"]


class Surroundings(NamedTuple):
    "Everything a screen is told by its embedder, as one value."

    #: The size of one cell, in pixels (`Screen.set_cell_size`).
    cell_width: int
    cell_height: int
    #: The colours a pane starts with (`Screen.set_color_base`).
    color_base: ColorBase
    #: What the keyboard in front of the screen can report, whether to
    #: make up what it cannot, and whether anything but the legacy
    #: encoding is allowed (`Screen.set_keyboard_source`).
    keyboard_source_flags: int
    synthesize_key_events: bool
    extended_keys_allowed: bool
