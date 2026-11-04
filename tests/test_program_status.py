"""
"OSC 7501", the Program Status Protocol: a screen answers the feature
query and keeps the records, by the rules of spec revision 0.4.
Lillecarl/pymux#927.
"""

from __future__ import annotations

import base64

from pyte.program_status import MAX_RECORDS, BlockedKind, ProgramState, parse_report
from pyte.screen import Screen
from pyte.streams import Stream


def _screen():
    replies = []
    heard = []
    screen = Screen(
        24, 80, write_process_input=replies.append, osc_func=lambda code, param: heard.append((code, param))
    )
    return screen, Stream(screen), replies, heard


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def report(body: str) -> str:
    return "\x1b]7501;%s\x1b\\" % body


def test_the_feature_query_is_answered():
    _screen_, stream, replies, _heard = _screen()
    stream.feed(report("?"))
    assert replies == ["\x1b]7501;?:states=idle,working,done,blocked,error:kinds=permission,question,auth\x1b\\"]


def test_a_report_becomes_a_record_and_the_embedder_hears():
    screen, stream, _replies, heard = _screen()
    body = "state=blocked:kind=permission:app=terraform:msg=" + _b64("Apply?")
    stream.feed(report(body))
    record = screen.program_status.records[""]
    assert (record.state, record.kind, record.app, record.msg_text) == (
        ProgramState.BLOCKED,
        BlockedKind.PERMISSION,
        "terraform",
        "Apply?",
    )
    assert heard == [("7501", body)]


def test_a_report_replaces_its_record_whole():
    screen, stream, _replies, _heard = _screen()
    stream.feed(report("state=working:app=brew:progress=40"))
    stream.feed(report("state=done"))
    record = screen.program_status.records[""]
    assert (record.state, record.app, record.progress) == (ProgramState.DONE, None, None)


def test_a_report_that_breaks_a_rule_changes_nothing():
    screen, stream, _replies, heard = _screen()
    for body in (
        "state=sleeping",
        "app=x",
        "state=idle:id=a//b",
        "state=idle:id=" + "/".join("s" * 9),
        "state=idle:msg=" + _b64("two\nlines"),
        "state=idle:msg=a",
        "state=idle:title=" + _b64("t" * 193),
    ):
        stream.feed(report(body))
    assert screen.program_status.records == {}
    assert heard == []


def test_a_bad_pair_is_skipped_and_the_rest_counts():
    parsed = parse_report("state=blocked:kind=dance:progress=101:nonsense: app = cargo :x=a;b")
    assert parsed is not None
    assert (parsed.state, parsed.kind, parsed.progress, parsed.app) == (ProgramState.BLOCKED, None, None, "cargo")


def test_clear_takes_the_record_and_those_beneath_it():
    screen, stream, _replies, _heard = _screen()
    for id in ("build", "build/test", "builder", "deploy"):
        stream.feed(report("state=working:id=" + id))
    stream.feed(report("state=clear:id=build"))
    assert sorted(screen.program_status.records) == ["builder", "deploy"]
    stream.feed(report("state=clear"))
    assert screen.program_status.records == {}


def test_a_prompt_ends_the_work_and_leaves_what_finished():
    screen, stream, _replies, _heard = _screen()
    stream.feed(report("state=working:id=a") + report("state=blocked:id=b") + report("state=done:id=c"))
    stream.feed(report("state=idle:id=d") + report("state=error:id=e"))
    stream.feed("\x1b]133;A\x1b\\")
    assert sorted(screen.program_status.records) == ["c", "d", "e"]


def test_a_full_reset_takes_them_and_a_soft_one_does_not():
    screen, stream, _replies, heard = _screen()
    stream.feed(report("state=done"))
    stream.feed("\x1b[!p")
    assert list(screen.program_status.records) == [""]
    stream.feed("\x1bc")
    assert screen.program_status.records == {}
    assert heard[-1] == ("7501", "")


def test_the_alternate_screen_keeps_them():
    screen, stream, _replies, _heard = _screen()
    stream.feed(report("state=working") + "\x1b[?1049h")
    assert list(screen.program_status.records) == [""]


def test_the_oldest_update_goes_at_the_cap():
    screen, stream, _replies, _heard = _screen()
    for n in range(MAX_RECORDS):
        stream.feed(report("state=idle:id=r%d" % n))
    stream.feed(report("state=working:id=r0"))
    stream.feed(report("state=idle:id=new"))
    records = screen.program_status.records
    assert len(records) == MAX_RECORDS
    assert "r1" not in records and "r0" in records and "new" in records


def test_app_comes_from_the_nearest_ancestor():
    screen, stream, _replies, _heard = _screen()
    stream.feed(report("state=working:app=deploy") + report("state=working:id=eu/west"))
    assert screen.program_status.app_of("eu/west") == "deploy"
