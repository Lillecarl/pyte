"""
The kitty graphics protocol on the wire: "APC G <control> ; <payload> ST".

`images.py` is what a screen does with a command. This is the
sequence itself, so a program that talks to a terminal reads the
answer by its fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..images import parse_control_data
from .strings import StringKind, StringSequence, apc

__all__ = ("GraphicsReply",)


@dataclass(frozen=True)
class GraphicsReply:
    """
    A terminal's answer to a graphics command: "APC G i=31 ; OK ST", or
    an error code and its text in place of the OK.

        >>> GraphicsReply.parse("\\x1b_Gi=31;OK\\x1b\\\\")
        GraphicsReply(image_id=31, message='OK', placement_id=None, image_number=None)

    A terminal names the image the way the command did, by id or by
    number, and may add keys of its own, so each is read by its key.
    """

    KEY: ClassVar[str] = "G"
    OK: ClassVar[str] = "OK"

    image_id: int | None
    message: str
    placement_id: int | None = None
    image_number: int | None = None

    def __str__(self) -> str:
        keys = [("i", self.image_id), ("I", self.image_number), ("p", self.placement_id)]
        control = ",".join("%s=%d" % (key, value) for key, value in keys if value is not None)
        return apc("%s%s;%s" % (self.KEY, control, self.message))

    @property
    def ok(self) -> bool:
        return self.message == self.OK

    @classmethod
    def parse(cls, text: str) -> GraphicsReply | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> GraphicsReply | None:
        if sequence is None or sequence.kind is not StringKind.APC or not sequence.payload.startswith(cls.KEY):
            return None
        keys, message = parse_control_data(sequence.payload[len(cls.KEY) :])
        return cls(_number(keys.get("i")), message, _number(keys.get("p")), _number(keys.get("I")))


def _number(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None
