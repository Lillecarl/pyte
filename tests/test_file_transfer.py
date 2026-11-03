"""
kitty's file transfer protocol, OSC 5113: the command as kitty reads and
writes it. Lillecarl/pymux#912.
"""

from __future__ import annotations

import pytest
from a_screen import a_screen

from pyte.sequences.file_transfer import Action, Compression, FileType, Malformed, TransferCommand
from pyte.streams import Stream

OSC = "\x1b]"
ST = "\x1b\\"


def test_the_spec_example_reads_and_writes():
    "The serialized example of the spec's last section. It pads its base64, and kitty writes none."
    command = TransferCommand.decode("ac=send;id=test;n=c29tZWZpbGU=;sz=3;d=AQID")
    assert command == TransferCommand(Action.SEND, id="test", name="somefile", size=3, data=b"\x01\x02\x03")
    assert str(command) == OSC + "5113;ac=send;id=test;sz=3;n=c29tZWZpbGU;d=AQID" + ST


def test_a_field_at_its_default_is_left_out():
    assert TransferCommand(Action.STATUS, id="x", status="OK").param() == "ac=status;id=x;st=T0s"


def test_base64_is_written_without_padding():
    "The kitten decodes with Go's `RawStdEncoding`, which refuses a `=`. Lillecarl/pymux#913."
    param = TransferCommand(Action.DATA, name="ab", status="a", bypass="abcd", data=b"\x01").param()
    values = [part.partition("=")[2] for part in param.split(";")]
    assert len(values) == 5
    assert not any(value.endswith("=") for value in values)


def test_every_field_crosses():
    command = TransferCommand(
        Action.FILE,
        compression=Compression.ZLIB,
        file_type=FileType.SYMLINK,
        id="s1",
        file_id="f1",
        bypass="sha256:abc",
        quiet=1,
        mtime=1_700_000_000_000_000_000,
        permissions=0o644,
        size=0,
        name="~/a b;c.txt",
        status="EPERM:no",
        parent="f0",
        data=b"fid:f2",
    )
    assert TransferCommand.decode(command.param()) == command


def test_an_unknown_key_and_a_pair_with_no_value_are_ignored():
    assert TransferCommand.decode("ac=cancel;zz=1;junk;id=a") == TransferCommand(Action.CANCEL, id="a")


def test_base64_without_padding_reads():
    assert TransferCommand.decode("ac=data;d=AQ").data == b"\x01"


def test_a_safe_string_loses_what_kitty_strips():
    assert TransferCommand.decode("ac=send;id=a$b c").id == "abc"


@pytest.mark.parametrize("param", ["id=a", "ac=jump", "ac=send;sz=many", "ac=data;d=!!!", "ac=send;n=/w=="])
def test_what_kitty_refuses_is_malformed(param):
    with pytest.raises(Malformed):
        TransferCommand.decode(param)


def test_the_screen_hands_each_command_on_and_draws_none():
    screen = a_screen(20, 3)
    told = []
    screen.file_transfer_func = told.append
    Stream(screen).feed(OSC + "5113;ac=send;id=s" + ST + OSC + "5113;ac=nothing" + ST + "x")
    assert told == [TransferCommand(Action.SEND, id="s")]
    assert [cell.char for cell in screen.page.data_buffer[0].values()] == ["x"]
