"""
The colours one screen paints a cell with, as `#rrggbb`.

A cell names colours as the program asked: a number of the palette, a
colour of its own, or nothing, which is the terminal's. What shows is
that against the screen's theme, with reverse applied. A reader that
gets no stylesheet -- `compact_html` -- and one that draws pixels --
pymux's PNG capture -- both need that answer, so it is here once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .colors import DEFAULT_COLORS, PALETTE, SgrColor
from .html import THEMED

if TYPE_CHECKING:
    from .cells import Appearance
    from .osc import ColorOverrides

__all__ = ("Paint",)


class Paint(NamedTuple):
    "The two colours a screen draws with, and its sixteen themed ones."

    foreground: str
    background: str
    themed: tuple[str, ...]

    @classmethod
    def of(cls, colors: ColorOverrides | None) -> Paint:
        "A screen's own colours, or the palette this package holds without them."
        if colors is None:
            return cls(
                DEFAULT_COLORS["foreground"].hex,
                DEFAULT_COLORS["background"].hex,
                tuple(PALETTE[index].hex for index in range(THEMED)),
            )
        themed = tuple((colors.color_of(index) or PALETTE[index]).hex for index in range(THEMED))
        return cls(colors.named("foreground").hex, colors.named("background").hex, themed)

    def value(self, color: SgrColor) -> str:
        "The colour a cell asked for, or empty for the screen's own."
        if color.rgb is not None:
            return color.rgb.hex
        if color.index is None:
            return ""
        if color.index < THEMED:
            return self.themed[color.index]
        return PALETTE[color.index].hex

    def asked(self, appearance: Appearance, reverse_video: bool = False) -> tuple[str, str]:
        """
        The foreground and the background a cell shows, empty where it
        is the screen's own.

        Reverse swaps them, and a colour left to the terminal becomes
        the other one's by name. A screen in reverse video (DECSCNM)
        reverses every cell, and a cell that asked for reverse inside it
        comes back the right way round.
        """
        rendition = appearance.rendition
        color = self.value(rendition.color or SgrColor())
        background = self.value(rendition.bgcolor or SgrColor())
        if rendition.reverse != reverse_video:
            return background or self.background, color or self.foreground
        return color, background

    def shown(self, appearance: Appearance, reverse_video: bool = False) -> tuple[str, str]:
        "The foreground and the background a cell shows, each as a colour."
        color, background = self.asked(appearance, reverse_video)
        if reverse_video:
            return color or self.background, background or self.foreground
        return color or self.foreground, background or self.background
