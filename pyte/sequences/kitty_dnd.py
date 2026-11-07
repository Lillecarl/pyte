"""
kitty's drag and drop protocol, "OSC 72 ; metadata ; payload ST": one
packet, either way. https://sw.kovidgoyal.net/kitty/dnd-protocol/.
Lillecarl/pyterm#894.

The metadata is "key=value" pairs joined by colons, with one letter
keys. `t` is a letter, every other value an integer. The four location
keys mean what the type makes them mean: a cell for a move, an index
into a MIME list for a request, a directory handle for `Y`. So they
keep kitty's struct names here. The payload stays as it travels: raw
text for a MIME list or an error, base64 for data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..osc import Osc
from .strings import OscString, StringReport, StringSequence

__all__ = ["CHUNK_BYTES", "MACHINE_ID", "START_OFFERING", "STOP_OFFERING", "DndPacket", "DndType", "Malformed"]


class DndType(StrEnum):
    ACCEPT = "a"
    STOP_ACCEPTING = "A"
    MOVE = "m"
    DROP = "M"
    REQUEST = "r"
    REQUEST_ERROR = "R"
    OFFER = "o"
    PRESENT = "p"
    DRAG_IMAGE = "P"
    DRAG_EVENT = "e"
    DRAG_ERROR = "E"
    REMOTE_ITEM = "k"
    QUERY = "q"


#: The most payload one packet carries, after base64: the spec's limit.
CHUNK_BYTES: Final = 4096

#: The value of `x` that makes an `ACCEPT` carry a machine id.
MACHINE_ID: Final = 1
#: The values of `x` on an `OFFER` that start and stop a program's offers.
START_OFFERING: Final = 1
STOP_OFFERING: Final = 2

_UINT_KEYS: Final = {"m": "more", "i": "client_id", "o": "operation"}
_INT_KEYS: Final = {"x": "cell_x", "y": "cell_y", "X": "pixel_x", "Y": "pixel_y"}
#: kitty reads at most this many digits of a number.
_DIGITS: Final = 10
_UINT32: Final = 1 << 32

#: The types whose packets kitty writes with every location key, zero
#: or not: a program may read the cell of a move without a default.
_LOCATED: Final = frozenset([DndType.MOVE, DndType.DROP])


class Malformed(ValueError):
    "Metadata kitty's parser refuses. kitty drops the packet."


def _int32(value: int) -> int:
    "C's cast of a 32-bit unsigned number to a signed one."
    return value - _UINT32 if value >= 1 << 31 else value


@dataclass(frozen=True)
class DndPacket(StringReport):
    """
    One OSC 72 packet.

        >>> str(DndPacket(DndType.MOVE, cell_x=3, cell_y=1))
        '\\x1b]72;t=m:x=3:y=1:X=0:Y=0:o=0\\x1b\\\\'

    `type` is empty when the packet names none. kitty ignores such a
    packet, unless it continues a chain of chunks.
    """

    type: str = ""
    more: int = 0
    client_id: int = 0
    operation: int = 0
    cell_x: int = 0
    cell_y: int = 0
    pixel_x: int = 0
    pixel_y: int = 0
    payload: str = ""

    def sequence(self) -> StringSequence:
        return OscString(Osc.KITTY_DND, self.param()).sequence()

    def param(self) -> str:
        "What the OSC carries after its code, as `decode` reads it."
        fields = ["t=" + self.type] if self.type else []
        located = self.type in _LOCATED
        for key, name in _INT_KEYS.items():
            if located or getattr(self, name):
                fields.append("%s=%d" % (key, getattr(self, name)))
        if located or self.operation:
            fields.append("o=%d" % self.operation)
        if self.client_id:
            fields.append("i=%d" % self.client_id)
        if self.more:
            fields.append("m=%d" % self.more)
        metadata = ":".join(fields)
        return metadata + ";" + self.payload if self.payload else metadata

    @classmethod
    def decode(cls, param: str) -> DndPacket:
        """
        The packet an OSC 72 carries after its code. Raises `Malformed`
        where kitty's `parse_dnd_code` reports an error: a key it does
        not know, a type it does not know, or a number that does not
        read.
        """
        metadata, _, payload = param.partition(";")
        values: dict[str, int | str] = {}
        records = metadata.split(":") if metadata else []
        # kitty's parser ends happy waiting for a key: "t=a:" reads.
        if records and not records[-1]:
            records.pop()
        for record in records:
            key, sign, value = record.partition("=")
            if len(key) != 1 or not sign:
                raise Malformed("not a key=value pair: %r" % record)
            if key == "t":
                if len(value) != 1 or value not in DndType:
                    raise Malformed("unknown type: %r" % value)
                values["type"] = value
            elif key in _UINT_KEYS:
                values[_UINT_KEYS[key]] = _number(value)
            elif key in _INT_KEYS:
                negative = value.startswith("-")
                number = _int32(_number(value[1:] if negative else value))
                values[_INT_KEYS[key]] = _int32((-number) % _UINT32) if negative else number
            else:
                raise Malformed("unknown key: %r" % key)
        return cls(payload=payload, **values)  # type: ignore[arg-type]

    @classmethod
    def parse(cls, text: str) -> DndPacket | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> DndPacket | None:
        osc = OscString.read(sequence)
        if osc is None or osc.code != Osc.KITTY_DND:
            return None
        try:
            return cls.decode(osc.payload)
        except Malformed:
            return None


def _number(text: str) -> int:
    "kitty's READ_UINT: up to ten digits, and no more than 32 bits."
    if not text or not text.isascii() or not text.isdigit() or len(text) > _DIGITS:
        raise Malformed("not a number: %r" % text)
    value = int(text)
    if value >= _UINT32:
        raise Malformed("too large: %r" % text)
    return value
