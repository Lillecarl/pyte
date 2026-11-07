"""
kitty's drag and drop protocol (OSC 72) as a pane's program sends it:
each packet goes to the embedder, a chunk of a chain with the metadata
of its first chunk, and with no embedder nothing answers. The parser
itself is judged against kitty in ptterm. Lillecarl/pyterm#894.
"""

from __future__ import annotations

import json

from pyte.freeze import Frozen, freeze, thaw
from pyte.kitty_dnd import KittyDnd
from pyte.screen import Screen
from pyte.sequences.kitty_dnd import DndPacket, DndType
from pyte.streams import Stream


class Pane:
    def __init__(self, serves: bool = True) -> None:
        self.replies: list[str] = []
        self.packets: list[DndPacket] = []
        self.screen = Screen(5, 20, write_process_input=self.replies.append)
        if serves:
            self.screen.dnd_func = self.packets.append
        self.stream = Stream(self.screen)

    def send(self, param: str) -> None:
        self.stream.feed("\x1b]72;%s\x1b\\" % param)


def test_a_packet_goes_to_the_embedder():
    pane = Pane()
    pane.send("t=a:i=7;text/plain text/uri-list")
    assert pane.packets == [DndPacket(DndType.ACCEPT, client_id=7, payload="text/plain text/uri-list")]
    assert pane.replies == []


def test_a_chunk_carries_the_metadata_of_the_first():
    pane = Pane()
    pane.send("t=e:y=2:i=3:m=1;aGVs")
    pane.send("m=1;bG8g")
    pane.send("t=q:m=0;d29y")
    pane.send("t=m:o=1")
    first = DndPacket(DndType.DRAG_EVENT, more=1, client_id=3, cell_y=2, payload="aGVs")
    assert pane.packets == [
        first,
        DndPacket(DndType.DRAG_EVENT, more=1, client_id=3, cell_y=2, payload="bG8g"),
        DndPacket(DndType.DRAG_EVENT, client_id=3, cell_y=2, payload="d29y"),
        DndPacket(DndType.MOVE, operation=1),
    ]


def test_a_packet_kitty_refuses_is_dropped():
    pane = Pane()
    pane.send("t=z")
    pane.send("w=1")
    pane.send("i=3")
    assert pane.packets == []


def test_without_an_embedder_a_query_goes_unanswered():
    "The program sends DA1 after its query; DA1's answer alone says no support."
    pane = Pane(serves=False)
    pane.send("t=q")
    assert pane.replies == []


def test_a_move_names_every_location_key():
    assert str(DndPacket(DndType.MOVE, cell_x=-1, cell_y=-1)) == "\x1b]72;t=m:x=-1:y=-1:X=0:Y=0:o=0\x1b\\"
    assert str(DndPacket(DndType.REQUEST, cell_x=2, client_id=5, more=1, payload="aGk=")) == (
        "\x1b]72;t=r:x=2:i=5:m=1;aGk=\x1b\\"
    )
    assert str(DndPacket(DndType.STOP_ACCEPTING)) == "\x1b]72;t=A\x1b\\"


def test_a_packet_reads_back_what_it_writes():
    packet = DndPacket(DndType.PRESENT, client_id=9, operation=1024, cell_x=-1, cell_y=100, pixel_x=16, payload="aGk=")
    assert DndPacket.parse(str(packet)) == packet


def test_a_chain_in_progress_survives_a_freeze():
    pane = Pane()
    pane.send("t=p:x=1:m=1;aGVs")
    frozen = json.loads(json.dumps(freeze(pane.screen)))
    thawed = Pane()
    thaw(Frozen(*frozen), thawed.screen)
    thawed.send("m=0;bG8=")
    assert thawed.packets == [DndPacket(DndType.PRESENT, cell_x=1, payload="bG8=")]


def test_a_screen_keeps_what_its_program_registered_through_a_freeze():
    pane = Pane()
    pane.send("t=a:i=4:m=1;text/plain ")
    pane.send("m=0;text/uri-list")
    pane.send("t=a:x=1;1:abc")
    pane.send("t=o:x=1:i=9;1:def")
    frozen = json.loads(json.dumps(freeze(pane.screen)))
    thawed = Pane()
    thaw(Frozen(*frozen), thawed.screen)
    dnd = thawed.screen.kitty_dnd
    assert (dnd.accepting, dnd.accepted_mimes, dnd.drop_client_id, dnd.machine_id) == (
        True,
        "text/plain text/uri-list",
        4,
        "1:abc",
    )
    assert (dnd.offering, dnd.drag_client_id, dnd.offer_machine_id) == (True, 9, "1:def")

    thawed.send("t=A:i=4")
    thawed.send("t=o:x=2:i=9")
    assert not dnd.accepting and not dnd.offering
    assert dnd.machine_id == dnd.accepted_mimes == ""


def test_a_new_registration_forgets_the_machine_id():
    "kitty's drop_register_window clears is_remote_client: the id comes after."
    pane = Pane()
    pane.send("t=a:x=1;1:abc")
    pane.send("t=a")
    assert pane.screen.kitty_dnd.machine_id == ""


def test_a_chain_ends_with_its_last_chunk():
    chain = KittyDnd()
    assert chain.take("t=a:m=1;text/plain ") == DndPacket(DndType.ACCEPT, more=1, payload="text/plain ")
    assert chain.take(";text/html") == DndPacket(DndType.ACCEPT, payload="text/html")
    assert chain.take(";text/html") is None
