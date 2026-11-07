"""
What a pane's program asks of kitty's clipboard (OSC 5522), assembled.

A write arrives in packets: "type=write", then "wdata" chunks per MIME
type and "walias" packets, then a "wdata" with no type to end it. This
holds the write in progress and hands the embedder a finished one, or
a read request. A screen does not own a clipboard, so the embedder
decides both, and answers the program. Lillecarl/pyterm#895.

kitty's `ClipboardRequestManager.parse_osc_5522` is the reference: an
error aborts the write, and every packet after it is ignored until the
next "type=write".
"""

from __future__ import annotations

from typing import ClassVar, Final, NamedTuple

from .keep import Keep
from .sequences.kitty_clipboard import ClipboardPacket, Malformed, PacketType, Status, strict_b64decode

__all__ = [
    "MAX_WRITE_BYTES",
    "ClipboardRead",
    "ClipboardRequest",
    "ClipboardWrite",
    "KittyClipboard",
    "WriteInProgress",
    "answer_to",
]

#: The most one write may hold, decoded. The spec asks a terminal to
#: take at least 64 MB; past it the write ends with EFBIG.
MAX_WRITE_BYTES: Final = 64 << 20

#: The characters a chunk of base64 may hold. The padding is checked
#: when the chunks of a type are decoded together.
_ALPHABET: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


class ClipboardWrite(NamedTuple):
    "A finished write: the data of each MIME type, and the aliases of them."

    data: dict[str, bytes]
    #: alias -> the MIME type whose data it shares.
    aliases: dict[str, str]
    primary: bool = False
    id: str = ""
    password: str = ""
    name: str = ""

    def types(self) -> dict[str, bytes]:
        "Every MIME type the write makes available, aliases included."
        found = dict(self.data)
        for alias, target in self.aliases.items():
            if target in self.data:
                found.setdefault(alias, self.data[target])
        return found


class ClipboardRead(NamedTuple):
    "A read request. `mimes` is `(LIST_TYPES,)` to ask which types there are."

    mimes: tuple[str, ...]
    primary: bool = False
    id: str = ""
    password: str = ""
    name: str = ""


ClipboardRequest = ClipboardWrite | ClipboardRead


def answer_to(request: ClipboardRequest, status: Status) -> ClipboardPacket:
    "The one-packet answer to `request`: DONE for a write, or an error."
    kind = PacketType.WRITE if isinstance(request, ClipboardWrite) else PacketType.READ
    return ClipboardPacket(kind, status, id=request.id)


class WriteInProgress:
    "One write between its 'type=write' and its last packet."

    KEEP: ClassVar[dict[str, Keep]] = {
        "primary": Keep.SAVED,
        "id": Keep.SAVED,
        "password": Keep.SAVED,
        "name": Keep.SAVED,
        "done": Keep.SAVED,
        "current": Keep.SAVED,
        "parts": Keep.SAVED,
        "carry": Keep.SAVED,
        "aliases": Keep.SAVED,
        "size": Keep.SAVED,
    }

    def __init__(self, packet: ClipboardPacket) -> None:
        self.primary = packet.primary
        self.id = packet.id
        self.password = packet.password
        self.name = packet.name
        #: The types whose chunks have all arrived.
        self.done: dict[str, bytes] = {}
        #: The type whose chunks are arriving, what of it is decoded, and
        #: the characters short of a group of four.
        self.current = ""
        self.parts: list[bytes] = []
        self.carry = ""
        self.aliases: dict[str, str] = {}
        #: The bytes decoded so far, of every type.
        self.size = 0

    def add(self, mime: str, payload: str) -> None:
        """
        One chunk of `mime`. Raises ValueError on base64 that cannot be
        right.

        Decoded as a stream, as kitty's `StreamingBase64Decoder` does: a
        chunk need not end on a group of four, and padding ends the
        stream, so the next chunk starts a new one. kitty's own write
        kitten pads every chunk.
        """
        if not _ALPHABET.issuperset(payload):
            raise ValueError("a character outside the base64 alphabet")
        if mime != self.current:
            self.flush()
            self.current = mime
        text = self.carry + payload
        whole = len(text) - len(text) % 4
        if "=" in text[:whole] and whole < len(text):
            raise ValueError("data after the padding")
        data = strict_b64decode(text[:whole])
        self.carry = text[whole:]
        self.parts.append(data)
        self.size += len(data)

    def flush(self) -> None:
        "End the type in progress. Raises ValueError when its last group is short."
        if not self.current:
            return
        if self.carry:
            raise ValueError("base64 without its padding")
        self.size -= len(self.done.get(self.current, b""))
        self.done[self.current] = b"".join(self.parts)
        self.current = ""
        self.parts = []

    def finished(self) -> ClipboardWrite:
        self.flush()
        return ClipboardWrite(self.done, self.aliases, self.primary, self.id, self.password, self.name)


class KittyClipboard:
    "A screen's half of OSC 5522: the write in progress."

    KEEP: ClassVar[dict[str, Keep]] = {"writing": Keep.SAVED}

    def __init__(self) -> None:
        self.writing: WriteInProgress | None = None

    def take(self, param: str) -> ClipboardRequest | ClipboardPacket | None:
        """
        Read one packet. The result is a request for the embedder, an
        error to answer the program with now, or None.
        """
        try:
            packet = ClipboardPacket.decode(param)
        except Malformed as bad:
            if bad.type in (PacketType.WDATA, PacketType.WALIAS) and self.writing is not None:
                return self._abort(Status.EINVAL)
            return None

        if packet.type == PacketType.READ:
            try:
                mimes = packet.words()
            except ValueError:
                # A read has no error status: the spec says to ignore it.
                return None
            return ClipboardRead(mimes, packet.primary, packet.id, packet.password, packet.name)

        if packet.type == PacketType.WRITE:
            self.writing = WriteInProgress(packet)
            return None

        writing = self.writing
        if writing is None:
            return None

        if packet.type == PacketType.WALIAS:
            if not packet.mime:
                return self._abort(Status.EINVAL)
            try:
                aliases = packet.words()
            except ValueError:
                return self._abort(Status.EINVAL)
            for alias in aliases:
                writing.aliases[alias] = packet.mime
            return None

        if packet.type == PacketType.WDATA:
            try:
                if not packet.mime:
                    finished = writing.finished()
                    self.writing = None
                    return finished
                writing.add(packet.mime, packet.payload)
            except ValueError:
                return self._abort(Status.EINVAL)
            if writing.size > MAX_WRITE_BYTES:
                return self._abort(Status.EFBIG)
        return None

    def _abort(self, status: Status) -> ClipboardPacket:
        writing = self.writing
        assert writing is not None
        self.writing = None
        return ClipboardPacket(PacketType.WRITE, status, id=writing.id)
