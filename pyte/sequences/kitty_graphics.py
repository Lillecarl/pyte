"""
The kitty graphics protocol on the wire: "APC G <control> ; <payload> ST".

`images.py` is what a screen does with a command. This is the
sequence itself: the keys and the values the protocol names, a
command that writes itself, and the terminal's answer.
https://sw.kovidgoyal.net/kitty/graphics-protocol/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import ClassVar

from ..control import ESC as _ESC
from .strings import StringKind, StringSequence, apc

__all__ = (
    "GRAPHICS_START",
    "Action",
    "Compression",
    "Delete",
    "GraphicsCommand",
    "GraphicsKey",
    "GraphicsReply",
    "Medium",
    "Quiet",
    "Value",
    "parse_control_data",
)


class GraphicsKey(StrEnum):
    "One key of a command's control data. Case matters: i is an id, I a number."

    ACTION = "a"
    QUIET = "q"
    FORMAT = "f"
    MEDIUM = "t"
    COMPRESSION = "o"
    MORE = "m"

    #: The size of the image, in pixels.
    WIDTH = "s"
    HEIGHT = "v"

    #: How many bytes to read from a file or shared memory, and from where.
    SIZE = "S"
    OFFSET = "O"

    IMAGE_ID = "i"
    IMAGE_NUMBER = "I"
    PLACEMENT_ID = "p"

    #: The rectangle of the image to show, in pixels.
    SOURCE_X = "x"
    SOURCE_Y = "y"
    SOURCE_WIDTH = "w"
    SOURCE_HEIGHT = "h"

    #: Where in the first cell the image starts, in pixels.
    CELL_X = "X"
    CELL_Y = "Y"

    #: How many cells the image covers.
    COLUMNS = "c"
    ROWS = "r"

    #: A frame edit (`a=f`) gives two letters other meanings: `r` is the
    #: frame to edit, and `X` how the new pixels combine with the old,
    #: 1 for replacing them.
    EDIT_FRAME = "r"
    COMPOSITION = "X"

    #: 1: the cursor stays where it was.
    CURSOR = "C"
    #: 1: a virtual placement, shown through placeholder characters.
    VIRTUAL = "U"
    Z_INDEX = "z"
    DELETE = "d"


class Action(StrEnum):
    "The `a` key: what the command does."

    TRANSMIT = "t"
    TRANSMIT_AND_PUT = "T"
    QUERY = "q"
    PUT = "p"
    DELETE = "d"
    FRAME = "f"
    ANIMATE = "a"
    COMPOSE = "c"


class Medium(StrEnum):
    "The `t` key: where the pixels are."

    DIRECT = "d"
    FILE = "f"
    TEMPORARY_FILE = "t"
    SHARED_MEMORY = "s"


class Compression(StrEnum):
    "The `o` key."

    ZLIB = "z"


class Quiet(IntEnum):
    "The `q` key: which answers the terminal keeps to itself."

    ANSWER = 0
    #: No OK, but an error still comes back.
    ERRORS_ONLY = 1
    #: Nothing comes back at all.
    NOTHING = 2


class Delete(StrEnum):
    """
    The `d` key of a delete. A lower-case target takes the placements
    off the screen and keeps the image; the upper-case one frees the
    image as well.
    """

    ALL = "a"
    ALL_AND_FREE = "A"
    BY_ID = "i"
    BY_ID_AND_FREE = "I"
    BY_NUMBER = "n"
    BY_NUMBER_AND_FREE = "N"
    AT_CURSOR = "c"
    AT_CURSOR_AND_FREE = "C"
    FRAMES = "f"
    FRAMES_AND_FREE = "F"
    AT_CELL = "p"
    AT_CELL_AND_FREE = "P"
    AT_CELL_AND_Z = "q"
    AT_CELL_AND_Z_AND_FREE = "Q"
    IN_RANGE = "r"
    IN_RANGE_AND_FREE = "R"
    IN_COLUMN = "x"
    IN_COLUMN_AND_FREE = "X"
    IN_ROW = "y"
    IN_ROW_AND_FREE = "Y"
    AT_Z = "z"
    AT_Z_AND_FREE = "Z"


#: The value of one key: a member, a number, or text the caller has.
Value = StrEnum | int | str

#: How every graphics command starts, which a reader of output looks for.
GRAPHICS_START = _ESC + StringKind.APC + "G"


@dataclass(frozen=True)
class GraphicsCommand:
    """
    One command, "APC G key=value,... ; payload ST".

        >>> str(GraphicsCommand({GraphicsKey.ACTION: Action.DELETE, GraphicsKey.DELETE: Delete.ALL_AND_FREE}))
        '\\x1b_Ga=d,d=A\\x1b\\\\'

    The keys go out in the order they were given. A terminal does not
    care, and a test that holds the bytes keeps holding them.

    A payload of `None` writes no ";" at all, and an empty one writes
    the ";" with nothing after it: the last chunk of an empty image.
    """

    KEY: ClassVar[str] = "G"

    keys: dict[GraphicsKey, Value] = field(default_factory=dict)
    payload: str | None = None

    def __str__(self) -> str:
        control = ",".join("%s=%s" % (key, _written(value)) for key, value in self.keys.items())
        if self.payload is None:
            return apc(self.KEY + control)
        return apc("%s%s;%s" % (self.KEY, control, self.payload))


def _written(value: Value) -> str:
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, int):
        return str(int(value))
    return value


def parse_control_data(data: str) -> tuple[dict[str, str], str]:
    """
    Split a graphics command into its control data keys and the base64
    payload. ("a=T,f=24;<payload>".)
    """
    if ";" in data:
        control, payload = data.split(";", 1)
    else:
        control, payload = data, ""

    keys: dict[str, str] = {}
    for part in control.split(","):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        else:
            key, value = part, ""
        keys[key] = value
    return keys, payload


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
        keys = {
            GraphicsKey.IMAGE_ID: self.image_id,
            GraphicsKey.IMAGE_NUMBER: self.image_number,
            GraphicsKey.PLACEMENT_ID: self.placement_id,
        }
        control = ",".join("%s=%d" % (key, value) for key, value in keys.items() if value is not None)
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
        return cls(
            _number(keys.get(GraphicsKey.IMAGE_ID)),
            message,
            _number(keys.get(GraphicsKey.PLACEMENT_ID)),
            _number(keys.get(GraphicsKey.IMAGE_NUMBER)),
        )


def _number(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None
