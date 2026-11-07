"""
kitty's file transfer protocol, "OSC 5113 ; key=value ; ... ST": one
command of a transfer session, either way.
https://sw.kovidgoyal.net/kitty/file-transfer-protocol/.
Lillecarl/pyterm#914.

This follows kitty's `FileTransmissionCommand` (`kitty/file_transmission.py`)
and not only the spec page: the same short keys and defaults, a field
at its default left out, and an unknown key ignored. The password hash
of `bypass` is base64 there, though the spec calls it a safe string.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final

from ..osc import Osc
from .strings import OscString, StringReport, StringSequence

__all__ = [
    "CHUNK_BYTES",
    "Action",
    "Compression",
    "FileType",
    "Malformed",
    "TransferCommand",
    "TransmissionType",
]


class Action(StrEnum):
    SEND = "send"
    FILE = "file"
    DATA = "data"
    END_DATA = "end_data"
    RECEIVE = "receive"
    CANCEL = "cancel"
    STATUS = "status"
    FINISH = "finish"


class Compression(StrEnum):
    NONE = "none"
    ZLIB = "zlib"


class FileType(StrEnum):
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    LINK = "link"


class TransmissionType(StrEnum):
    SIMPLE = "simple"
    RSYNC = "rsync"


#: The most data one command carries, before base64: the spec's limit.
CHUNK_BYTES: Final = 4096

#: What kitty strips from a safe string.
_UNSAFE: Final = re.compile(r"[^0-9a-zA-Z_:./@-]")

_ENUMS: Final[dict[str, type[StrEnum]]] = {
    "action": Action,
    "compression": Compression,
    "file_type": FileType,
    "transmission_type": TransmissionType,
}
_INTEGERS: Final = frozenset(["quiet", "mtime", "permissions", "size"])
_TEXTS: Final = frozenset(["bypass", "name", "status"])
_SAFE: Final = frozenset(["id", "file_id", "parent"])


class Malformed(ValueError):
    "A command kitty refuses: no action, or a value that does not read. kitty drops it."


@dataclass(frozen=True)
class TransferCommand(StringReport):
    """
    One OSC 5113 command.

        >>> str(TransferCommand(Action.SEND, id="test", name="somefile", size=3, data=b"\\x01\\x02\\x03"))
        '\\x1b]5113;ac=send;id=test;sz=3;n=c29tZWZpbGU;d=AQID\\x1b\\\\'
    """

    action: Action
    compression: Compression = Compression.NONE
    file_type: FileType = FileType.REGULAR
    transmission_type: TransmissionType = TransmissionType.SIMPLE
    id: str = ""
    file_id: str = ""
    bypass: str = ""
    quiet: int = 0
    mtime: int = -1
    permissions: int = -1
    size: int = -1
    name: str = ""
    status: str = ""
    parent: str = ""
    data: bytes = b""

    def sequence(self) -> StringSequence:
        return OscString(Osc.FILE_TRANSFER, self.param()).sequence()

    def param(self) -> str:
        "What the OSC carries after its code, as `decode` reads it, in kitty's order of fields."
        parts = []
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name != "action" and value == field.default:
                continue
            key = _KEY_OF[field.name]
            if field.name == "data":
                parts.append("%s=%s" % (key, _unpadded(value)))
            elif field.name in _TEXTS:
                parts.append("%s=%s" % (key, _unpadded(value.encode("utf-8"))))
            elif field.name in _SAFE:
                parts.append("%s=%s" % (key, _UNSAFE.sub("", value)))
            else:
                parts.append("%s=%s" % (key, value))
        return ";".join(parts)

    @classmethod
    def decode(cls, param: str) -> TransferCommand:
        """
        The command an OSC 5113 carries after its code. Raises
        `Malformed` where kitty's `deserialize` raises.
        """
        values: dict[str, object] = {}
        for part in param.split(";"):
            key, sign, value = part.partition("=")
            name = _NAME_OF.get(key)
            if not sign or name is None:
                continue
            try:
                if name in _ENUMS:
                    values[name] = _ENUMS[name](value)
                elif name in _INTEGERS:
                    values[name] = int(value)
                elif name == "data":
                    values[name] = _base64(value)
                elif name in _TEXTS:
                    values[name] = _base64(value).decode("utf-8")
                else:
                    values[name] = _UNSAFE.sub("", value)
            except ValueError as error:
                raise Malformed("%s=%r does not read" % (key, value)) from error
        if "action" not in values:
            raise Malformed("no action")
        return cls(**values)  # type: ignore[arg-type]


#: The serialized name of each field, as kitty's `sname` metadata has it.
_KEY_OF: Final = {
    "action": "ac",
    "compression": "zip",
    "file_type": "ft",
    "transmission_type": "tt",
    "id": "id",
    "file_id": "fid",
    "bypass": "pw",
    "quiet": "q",
    "mtime": "mod",
    "permissions": "prm",
    "size": "sz",
    "name": "n",
    "status": "st",
    "parent": "pr",
    "data": "d",
}
_NAME_OF: Final = {key: name for name, key in _KEY_OF.items()}


def _unpadded(value: bytes) -> str:
    "Standard base64 with no padding, as kitty writes it. The kitten refuses a `=`: it decodes with Go's `RawStdEncoding`."
    return base64.b64encode(value).decode("ascii").rstrip("=")


def _base64(value: str) -> bytes:
    "Standard base64, with or without its padding, which kitty's decoder does not need."
    return base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
