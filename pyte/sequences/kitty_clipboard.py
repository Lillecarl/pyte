"""
kitty's clipboard protocol, "OSC 5522 ; metadata ; payload ST": one
packet, either way. https://sw.kovidgoyal.net/kitty/clipboard/.
Lillecarl/pymux#893.

The metadata is "key=value" pairs joined by colons. `mime`, `name` and
`pw` travel as base64 and are held here decoded; the payload stays
base64, because the chunks of one MIME type are decoded together.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..osc import Osc
from .strings import OscString, StringReport, StringSequence

__all__ = [
    "CHUNK_BYTES",
    "LIST_TYPES",
    "MAX_ID_LENGTH",
    "ClipboardPacket",
    "Malformed",
    "PacketType",
    "Status",
    "b64",
    "data_packets",
    "sanitize_id",
    "strict_b64decode",
]


class PacketType(StrEnum):
    READ = "read"
    WRITE = "write"
    WDATA = "wdata"
    WALIAS = "walias"


class Status(StrEnum):
    OK = "OK"
    DATA = "DATA"
    DONE = "DONE"
    EIO = "EIO"
    EINVAL = "EINVAL"
    ENOSYS = "ENOSYS"
    EPERM = "EPERM"
    EBUSY = "EBUSY"
    EFBIG = "EFBIG"


#: The MIME type a read names to ask which types the clipboard holds.
LIST_TYPES: Final = "."

#: The `loc` that names the primary selection.
_PRIMARY: Final = "primary"

#: The most data one packet carries, before base64: the spec's limit.
CHUNK_BYTES: Final = 4096

#: kitty keeps this much of an id (`sanitize_id`).
MAX_ID_LENGTH: Final = 512

_NOT_IN_AN_ID = re.compile(r"[^a-zA-Z0-9\-_+.]+")

#: The keys whose values travel as base64.
_ENCODED_KEYS = frozenset(["mime", "name", "pw"])


class Malformed(ValueError):
    "A packet whose metadata does not read. `type` is the type it named."

    def __init__(self, type: str, why: str) -> None:
        super().__init__(why)
        self.type = type


def sanitize_id(text: str) -> str:
    "What the spec lets an id hold, cut to kitty's length."
    return _NOT_IN_AN_ID.sub("", text)[:MAX_ID_LENGTH]


def strict_b64decode(text: str) -> bytes:
    """
    Base64 the spec's way: only the alphabet, and padded. Raises
    ValueError, since silently dropping a character turns corrupted data
    into valid data.
    """
    return base64.b64decode(text.encode("ascii"), validate=True)


def b64(data: bytes | str) -> str:
    return base64.b64encode(data.encode("utf-8") if isinstance(data, str) else data).decode("ascii")


@dataclass(frozen=True)
class ClipboardPacket(StringReport):
    """
    One OSC 5522 packet.

        >>> str(ClipboardPacket(PacketType.WRITE, Status.DONE, id="a1"))
        '\\x1b]5522;type=write:status=DONE:id=a1\\x1b\\\\'
    """

    type: str
    status: str = ""
    mime: str = ""
    id: str = ""
    primary: bool = False
    password: str = ""
    name: str = ""
    #: Base64, as it travels.
    payload: str = ""

    def sequence(self) -> StringSequence:
        fields = ["type=" + self.type]
        if self.status:
            fields.append("status=" + self.status)
        if self.primary:
            fields.append("loc=" + _PRIMARY)
        if self.id:
            fields.append("id=" + self.id)
        if self.mime:
            fields.append("mime=" + b64(self.mime))
        if self.name:
            fields.append("name=" + b64(self.name))
        if self.password:
            fields.append("pw=" + b64(self.password))
        metadata = ":".join(fields)
        return OscString(Osc.KITTY_CLIPBOARD, metadata + ";" + self.payload if self.payload else metadata).sequence()

    @classmethod
    def decode(cls, param: str) -> ClipboardPacket:
        """
        The packet an OSC 5522 carries after its code. Raises `Malformed`
        as kitty refuses one: a record that is not "key=value", or a
        `mime`, `name` or `pw` that is not base64 of UTF-8.
        """
        metadata, _, payload = param.partition(";")
        fields: dict[str, str] = {}
        for record in metadata.split(":"):
            key, sign, value = record.partition("=")
            if not sign:
                raise Malformed("", "metadata is not key=value pairs")
            fields[key] = value
        kind = fields.get("type", "")
        for key in _ENCODED_KEYS & fields.keys():
            try:
                fields[key] = strict_b64decode(fields[key]).decode("utf-8")
            except ValueError as error:
                raise Malformed(kind, "%s is not base64: %s" % (key, error)) from None
        return cls(
            type=kind,
            status=fields.get("status", ""),
            mime=fields.get("mime", ""),
            id=sanitize_id(fields.get("id", "")),
            primary=fields.get("loc", "") == _PRIMARY,
            password=fields.get("pw", ""),
            name=fields.get("name", ""),
            payload=payload,
        )

    @classmethod
    def parse(cls, text: str) -> ClipboardPacket | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> ClipboardPacket | None:
        osc = OscString.read(sequence)
        if osc is None or osc.code != Osc.KITTY_CLIPBOARD:
            return None
        try:
            return cls.decode(osc.payload)
        except Malformed:
            return None

    def words(self) -> tuple[str, ...]:
        "The payload as the space separated list a read or an alias carries. Raises ValueError."
        return tuple(strict_b64decode(self.payload).decode("utf-8").split())


def data_packets(packet: ClipboardPacket, mime: str, data: bytes) -> Iterator[ClipboardPacket]:
    """
    `data` for one MIME type, in chunks of at most `CHUNK_BYTES` before
    base64, each one padded, as copies of `packet` with that mime.
    Empty data is one empty chunk, so that the type is still named.
    """
    for start in range(0, max(len(data), 1), CHUNK_BYTES):
        yield ClipboardPacket(
            packet.type,
            packet.status,
            mime,
            packet.id,
            packet.primary,
            packet.password,
            packet.name,
            b64(data[start : start + CHUNK_BYTES]),
        )
