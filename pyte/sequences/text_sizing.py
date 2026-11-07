"""
kitty's text sizing protocol, "OSC 66 ; metadata ; text ST": text drawn
in a block of cells larger or smaller than one.
https://sw.kovidgoyal.net/kitty/text-sizing-protocol/.
Lillecarl/pyterm#892.

The metadata is "key=value" pairs joined by colons, each value an
unsigned integer. kitty's `parse-multicell-command.h` drops the whole
sequence on a key it does not know or a value that does not read, and
`decode` raises where it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..osc import Osc
from .strings import OscString, StringReport, StringSequence

__all__ = ["MAX_TEXT_BYTES", "Malformed", "TextSize"]

#: The longest text one sequence may carry, in bytes of UTF-8.
MAX_TEXT_BYTES: Final = 4096

#: The key of each field, and the largest value kitty keeps: it stores
#: each in a bit field and clamps to what the bits hold.
_KEYS: Final = {
    "s": ("scale", 7),
    "w": ("width", 7),
    "n": ("numerator", 15),
    "d": ("denominator", 15),
    "v": ("vertical", 3),
    "h": ("horizontal", 3),
}
_DEFAULTS: Final = {"scale": 1, "width": 0, "numerator": 0, "denominator": 0, "vertical": 0, "horizontal": 0}


class Malformed(ValueError):
    "Metadata kitty's parser refuses. kitty drops the sequence."


@dataclass(frozen=True)
class TextSize(StringReport):
    """
    One OSC 66: how big to draw `text`, and in how many cells.

        >>> str(TextSize("Hi", scale=2))
        '\\x1b]66;s=2;Hi\\x1b\\\\'

    A block is `scale * width` cells wide and `scale` cells high. A
    width of zero splits the text the way plain text splits, and each
    piece takes its own block. The fraction `numerator / denominator`
    shrinks the glyph inside its block and never the block; `vertical`
    and `horizontal` place it there.
    """

    text: str = ""
    scale: int = 1
    width: int = 0
    numerator: int = 0
    denominator: int = 0
    vertical: int = 0
    horizontal: int = 0

    def sequence(self) -> StringSequence:
        return OscString(Osc.TEXT_SIZE, self.param()).sequence()

    def param(self) -> str:
        "What the OSC carries after its code, as `decode` reads it."
        fields = [
            "%s=%d" % (key, getattr(self, name))
            for key, (name, _) in _KEYS.items()
            if getattr(self, name) != _DEFAULTS[name]
        ]
        return ":".join(fields) + ";" + self.text

    @property
    def fractional(self) -> bool:
        "Whether the glyph is drawn smaller than its block."
        return 0 < self.numerator < self.denominator

    def same_size(self, other: TextSize) -> bool:
        "Whether `other` asks for the same size, whatever its text."
        return all(getattr(self, name) == getattr(other, name) for name, _ in _KEYS.values())

    @classmethod
    def decode(cls, param: str) -> TextSize:
        """
        The sequence an OSC 66 carries after its code, with each value
        clamped to the bits kitty keeps it in and a scale of at least
        one. Raises `Malformed` where kitty reports an error.
        """
        metadata, separator, text = param.partition(";")
        if not separator:
            raise Malformed("no text")
        fields: dict[str, int] = {}
        for pair in metadata.split(":") if metadata else ():
            key, equals, value = pair.partition("=")
            if key not in _KEYS:
                raise Malformed("unknown key %r" % key)
            if not equals or not value.isdigit() or not value.isascii():
                raise Malformed("value of %r is not a number" % key)
            name, largest = _KEYS[key]
            fields[name] = min(int(value), largest)
        fields["scale"] = max(1, fields.get("scale", 1))
        return cls(text, **fields)
