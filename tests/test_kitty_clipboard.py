"""
kitty's clipboard protocol, OSC 5522: what a screen assembles, and
what it answers by itself. Lillecarl/pyterm#895.
"""

from __future__ import annotations

import base64
import json

import pytest

from pyte.freeze import Frozen, freeze, thaw
from pyte.kitty_clipboard import MAX_WRITE_BYTES, ClipboardRead, ClipboardRequest, ClipboardWrite, KittyClipboard
from pyte.screen import Screen
from pyte.sequences.kitty_clipboard import ClipboardPacket, PacketType, Status, data_packets
from pyte.streams import Stream


def b64(text: str | bytes) -> str:
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


class Pane:
    def __init__(self, serves: bool = True) -> None:
        self.replies: list[str] = []
        self.requests: list[ClipboardRequest] = []
        self.screen = Screen(5, 20, write_process_input=self.replies.append)
        if serves:
            self.screen.clipboard_func = self.requests.append
        self.stream = Stream(self.screen)

    def send(self, metadata: str, payload: str = "") -> None:
        self.stream.feed("\x1b]5522;%s%s\x1b\\" % (metadata, ";" + payload if payload else ""))

    def answers(self) -> list[ClipboardPacket | None]:
        return [ClipboardPacket.parse(reply) for reply in self.replies]


def test_a_write_arrives_whole_with_its_aliases():
    pane = Pane()
    pane.send("type=write:id=w1")
    pane.send("type=wdata:mime=%s" % b64("text/plain"), b64("hello"))
    pane.send("type=wdata:mime=%s" % b64("text/plain"), b64(" world"))
    pane.send("type=walias:mime=%s" % b64("text/plain"), b64("text/x-a text/x-b"))
    pane.send("type=wdata:mime=%s" % b64("image/png"), b64(b"\x89PNG"))
    assert pane.requests == []
    pane.send("type=wdata")
    [write] = pane.requests
    assert isinstance(write, ClipboardWrite)
    assert write.id == "w1"
    assert write.data == {"text/plain": b"hello world", "image/png": b"\x89PNG"}
    assert write.types()["text/x-b"] == b"hello world"
    assert pane.replies == []


def test_chunks_of_one_type_decode_together():
    "A chunk need not be a multiple of four; only the whole of a type is padded."
    pane = Pane()
    encoded = b64("abcdefgh")
    pane.send("type=write")
    pane.send("type=wdata:mime=%s" % b64("text/plain"), encoded[:3])
    pane.send("type=wdata:mime=%s" % b64("text/plain"), encoded[3:])
    pane.send("type=wdata")
    assert pane.requests[0].data == {"text/plain": b"abcdefgh"}


def test_bad_base64_aborts_with_einval_and_the_rest_is_ignored():
    pane = Pane()
    pane.send("type=write:id=x")
    pane.send("type=wdata:mime=%s" % b64("text/plain"), "aGk=\n")
    assert pane.answers() == [ClipboardPacket(PacketType.WRITE, Status.EINVAL, id="x")]
    pane.send("type=wdata:mime=%s" % b64("text/plain"), b64("hi"))
    pane.send("type=wdata")
    assert pane.requests == []
    assert len(pane.replies) == 1


@pytest.mark.parametrize(
    ("payloads", "status"),
    [
        # kitty_tests/clipboard.py, test_clipboard_invalid_base64.
        (["!!!"], Status.EINVAL),
        (["SGVs!!!bG8="], Status.EINVAL),
        [[b64("good"), "SGVs!!!bG8="], Status.EINVAL],
        (["\n" + b64("data with a newline in the payload")], Status.EINVAL),
        (["SGVsbG8"], Status.EINVAL),
        ([b64("good"), "SGVsbG8"], Status.EINVAL),
        ([b64("some data")[:3], b64("some data")[3:7], b64("some data")[7:]], Status.DONE),
        (list(b64("some data")), Status.DONE),
        # Padding ends a chunk's stream, as in kitty's write kitten.
        ([b64("hello"), b64(" world")], Status.DONE),
        (["aGk=aGk="], Status.EINVAL),
    ],
)
def test_base64_as_kitty_reads_it(payloads: list[str], status: Status):
    "Straight to the assembler: a newline inside an OSC is the stream's business."
    clipboard = KittyClipboard()
    clipboard.take("type=write:id=w1")
    taken = [clipboard.take("type=wdata:mime=%s;%s" % (b64("text/plain"), payload)) for payload in payloads]
    taken.append(clipboard.take("type=wdata"))
    errors = [packet for packet in taken if isinstance(packet, ClipboardPacket)]
    if status is Status.DONE:
        assert errors == [] and isinstance(taken[-1], ClipboardWrite)
    else:
        assert errors == [ClipboardPacket(PacketType.WRITE, status, id="w1")]


def test_missing_padding_aborts_at_the_end_of_its_type():
    pane = Pane()
    pane.send("type=write")
    pane.send("type=wdata:mime=%s" % b64("text/plain"), "aGk")
    pane.send("type=wdata:mime=%s" % b64("text/html"), b64("<b>"))
    assert pane.answers() == [ClipboardPacket(PacketType.WRITE, Status.EINVAL)]


def test_an_alias_without_a_type_aborts():
    pane = Pane()
    pane.send("type=write")
    pane.send("type=walias", b64("text/x-a"))
    assert pane.answers() == [ClipboardPacket(PacketType.WRITE, Status.EINVAL)]


def test_a_mime_that_is_not_base64_aborts_a_write():
    pane = Pane()
    pane.send("type=write")
    pane.send("type=wdata:mime=text/plain", b64("hi"))
    assert pane.answers() == [ClipboardPacket(PacketType.WRITE, Status.EINVAL)]


def test_too_much_data_aborts_with_efbig():
    clipboard = KittyClipboard()
    clipboard.take("type=write")
    chunk = "type=wdata:mime=%s;%s" % (b64("application/octet-stream"), "A" * (4 << 20))
    taken = [clipboard.take(chunk) for _ in range(MAX_WRITE_BYTES * 4 // 3 // (4 << 20) + 1)]
    assert taken[-1] == ClipboardPacket(PacketType.WRITE, Status.EFBIG)
    assert taken[:-1] == [None] * (len(taken) - 1)


def test_data_with_no_write_is_ignored():
    pane = Pane()
    pane.send("type=wdata:mime=%s" % b64("text/plain"), b64("hi"))
    pane.send("type=wdata")
    assert pane.requests == [] and pane.replies == []


def test_a_read_names_its_types_and_its_password():
    pane = Pane()
    pane.send(
        "type=read:loc=primary:id=a/b c:pw=%s:name=%s" % (b64("secret"), b64("nvim")),
        b64("text/plain image/png"),
    )
    assert pane.requests == [ClipboardRead(("text/plain", "image/png"), True, "abc", "secret", "nvim")]


def test_a_read_that_does_not_parse_is_ignored():
    pane = Pane()
    pane.send("type=read", "not base64!")
    pane.send("type=read:noequals", b64("."))
    assert pane.requests == [] and pane.replies == []


def test_a_screen_with_no_clipboard_refuses():
    pane = Pane(serves=False)
    pane.send("type=read:id=r", b64("."))
    pane.send("type=write:id=w")
    pane.send("type=wdata")
    assert pane.answers() == [
        ClipboardPacket(PacketType.READ, Status.EPERM, id="r"),
        ClipboardPacket(PacketType.WRITE, Status.EPERM, id="w"),
    ]


def test_decrqm_knows_paste_events_only_with_a_clipboard():
    served, alone = Pane(), Pane(serves=False)
    for pane in (served, alone):
        pane.stream.feed("\x1b[?5522h\x1b[?5522$p")
    assert served.replies == ["\x1b[?5522;1$y"]
    assert alone.replies == ["\x1b[?5522;0$y"]


def test_a_packet_reads_back_what_it_writes():
    packet = ClipboardPacket(PacketType.READ, Status.DATA, "text/plain", "i1", True, "pw", "name", b64("hi"))
    assert ClipboardPacket.parse(str(packet)) == packet


def test_data_goes_in_chunks_of_4096():
    head = ClipboardPacket(PacketType.WDATA)
    chunks = list(data_packets(head, "image/png", bytes(10000)))
    assert [len(base64.b64decode(chunk.payload)) for chunk in chunks] == [4096, 4096, 1808]
    assert all(chunk.mime == "image/png" for chunk in chunks)
    assert list(data_packets(head, "text/plain", b"")) == [ClipboardPacket(PacketType.WDATA, mime="text/plain")]


def test_a_write_in_progress_survives_a_freeze():
    pane = Pane()
    pane.send("type=write:id=w")
    pane.send("type=wdata:mime=%s" % b64("text/plain"), b64("one"))
    pane.send("type=wdata:mime=%s" % b64("text/html"), b64("<i>"))
    frozen = json.loads(json.dumps(freeze(pane.screen)))
    thawed = Pane()
    thaw(Frozen(*frozen), thawed.screen)
    thawed.send("type=wdata")
    assert thawed.requests[0].data == {"text/plain": b"one", "text/html": b"<i>"}
