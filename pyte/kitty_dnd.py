"""
kitty's drag and drop (OSC 72) as one side sends it: the chunks of a
chain given the metadata of its first chunk, and what a program said it
takes part in.

A chunk after the first may carry only `m` and `i`, so it names no
type. kitty's `screen_handle_dnd_command` copies the first chunk's
metadata onto each later one, and takes only `m` and the payload from
it. This does the same, for a pane's program and for a terminal.

A program registers once, at its start: as a drop target, with the MIME
types it takes, and as a drag source. kitty keeps that per window; a
pane keeps it on its screen, so that it lives through a server upgrade.
Lillecarl/pyterm#894.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

from .keep import Keep
from .sequences.kitty_dnd import MACHINE_ID, START_OFFERING, STOP_OFFERING, DndPacket, DndType, Malformed

__all__ = ["KittyDnd"]


class KittyDnd:
    "One sender's chain of chunks in progress, and what a program registered."

    KEEP: ClassVar[dict[str, Keep]] = {
        "first": Keep.SAVED,
        "accepting": Keep.SAVED,
        "accepted_mimes": Keep.SAVED,
        "_mimes_so_far": Keep.SAVED,
        "drop_client_id": Keep.SAVED,
        "machine_id": Keep.SAVED,
        "offering": Keep.SAVED,
        "drag_client_id": Keep.SAVED,
        "offer_machine_id": Keep.SAVED,
    }

    def __init__(self) -> None:
        #: The metadata of the first chunk of a chain that has not
        #: ended, as it travelled, or None.
        self.first: str | None = None
        #: Whether the program takes drops, and the MIME types it named,
        #: space separated, as it sent them.
        self.accepting = False
        self.accepted_mimes = ""
        self._mimes_so_far = ""
        #: The `i` of its registration: every packet to it carries it.
        self.drop_client_id = 0
        #: The machine id it gave for drops, "" for none. kitty takes
        #: none as the terminal's own machine.
        self.machine_id = ""
        #: Whether the program offers drags, its `i`, and its machine id.
        self.offering = False
        self.drag_client_id = 0
        self.offer_machine_id = ""

    def registration(self, machine_id: str) -> dict[str, Any]:
        "What a mirror's frame says the program registered, with `machine_id` where it named none."
        return {
            "accepting": self.accepting,
            "mimes": self.accepted_mimes,
            "machine_id": self.machine_id or machine_id,
            "offering": self.offering,
            "offer_machine_id": self.offer_machine_id or machine_id,
        }

    def register(self, data: dict[str, Any]) -> bool:
        "Take a frame's registration on a mirror. True when what the terminals register for changed."
        before = (self.accepting, self.accepted_mimes, self.offering)
        self.accepting = bool(data.get("accepting"))
        self.accepted_mimes = str(data.get("mimes") or "")
        self.machine_id = str(data.get("machine_id") or "")
        self.offering = bool(data.get("offering"))
        self.offer_machine_id = str(data.get("offer_machine_id") or "")
        return (self.accepting, self.accepted_mimes, self.offering) != before

    def take(self, param: str) -> DndPacket | None:
        "The packet an OSC 72 carries, whole; None for one kitty drops."
        try:
            packet = DndPacket.decode(param)
        except Malformed:
            return None
        if self.first is not None:
            packet = replace(DndPacket.decode(self.first), more=packet.more, payload=packet.payload)
            if not packet.more:
                self.first = None
        elif packet.more:
            self.first = param.partition(";")[0]
        if not packet.type:
            return None
        self._register(packet)
        return packet

    def _register(self, packet: DndPacket) -> None:
        "What kitty's drop_register_window and drag_start_offerring keep."
        match packet.type:
            case DndType.ACCEPT if packet.cell_x == MACHINE_ID:
                self.machine_id = packet.payload
            case DndType.ACCEPT:
                self.accepting = True
                self.drop_client_id = packet.client_id
                self.machine_id = ""
                self._mimes_so_far += packet.payload
                if not packet.more:
                    self.accepted_mimes = self._mimes_so_far
                    self._mimes_so_far = ""
            case DndType.STOP_ACCEPTING:
                self.accepting = False
                self.drop_client_id = packet.client_id
                self.accepted_mimes = self._mimes_so_far = self.machine_id = ""
            case DndType.OFFER if packet.cell_x == START_OFFERING:
                self.offering = True
                self.drag_client_id = packet.client_id
                self.offer_machine_id = packet.payload
            case DndType.OFFER if packet.cell_x == STOP_OFFERING:
                self.offering = False
                self.offer_machine_id = ""
            case DndType.OFFER:
                self.drag_client_id = packet.client_id
