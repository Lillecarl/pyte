"""
A screen painted from `repaint` holds what the screen it came from holds.

A mirror of another build seeds its copy of a pane from these bytes.
Lillecarl/pymux#759.

The oracle compares every field a screen saves for a hot upgrade
(`Screen.KEEP`), each one by what it means and not by how it is
numbered: a fresh screen numbers its rows from nought, so a row is
compared by where it stands on the page, and the history line by line.
A field that is neither compared nor in `NOT_CARRIED` fails
`test_every_saved_field_is_judged`, so a field added to the screen
cannot be forgotten here.
"""

from __future__ import annotations

import json
import random

import pytest
from a_screen import a_screen
from test_freeze import AFTER, BEFORE, CSI, CUTS, ESC, OSC, ST, STEPS

from pyte import charsets as cs
from pyte.cells import UNWRITTEN
from pyte.freeze import freeze_value, saved_fields
from pyte.images import PixelFormat
from pyte.modes import PrivateMode
from pyte.page import RowMark
from pyte.repaint import mark, marks_of, paint, repaint
from pyte.screen import Screen
from pyte.streams import Stream

#: The saved fields the bytes do not carry, and why.
NOT_CARRIED = {
    # A mirror trims its history on its own count, under the same limit.
    "_history_cleanup_counter": "trims on its own count",
    # Only grows; a reader compares it to its own last look.
    "frames_drawn": "a reader's counter",
    # REP repeats what the program drew just before it, in the same
    # write: a seed between the two is a seed inside one sequence.
    "last_character": "REP follows its character",
    # The alternate page a program left, while the first page is in
    # front. "?1049h" clears it on the way back; only "?47h" and
    # "?1047h" would find it.
    "_alternate_screen": "the parked alternate page",
    "_alternate_screen_vars": "the parked alternate page",
}

#: The modes that take the alternate page.
PAGE_MODES = {
    PrivateMode.ALTERNATE_SCREEN.flag,
    PrivateMode.ALTERNATE_SCREEN_AGAIN.flag,
    PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag,
}

#: The fields `Screen.swap_variables` holds per page, which `_page`
#: compares, and the fields that only number the rows.
PAGE_FIELDS = {
    "page",
    "_original_screen",
    "_original_screen_vars",
    "max_y",
    "history_floor",
    "reflow_floor",
    "pt_cursor_position",
    "pending_wrap",
    "savepoints",
    "tabstops",
    "mode",
    "gl",
    "g_charsets",
    "pointer_shapes",
    "kitty_flags_stack",
    "graphics",
}

_DESIGNATIONS = {id(table): code for code, table in cs.MAPS.items()}


def _charsets(tables) -> list:
    return [_DESIGNATIONS.get(id(table), "?") for table in tables]


def _cell(column, cell) -> tuple:
    appearance = cell.appearance
    return (
        column,
        type(cell).__name__,
        cell.char,
        appearance.rendition,
        appearance.hyperlink,
        appearance.hyperlink_id,
        getattr(cell, "protection", 0),
    )


def _row(row, above, columns: int) -> tuple | None:
    if row is None:
        return None
    cells = tuple(_cell(column, cell) for column, cell in sorted(row.items()) if cell is not UNWRITTEN)
    # Only a character drawn in the last column wraps, so that is the
    # one wrap mark bytes can make. An erase that reaches the edge, or
    # a wrap inside left and right margins, marks a row no write can.
    last = above.get(columns - 1) if above is not None else None
    wrapped = row.wrapped and last is not None and last.written
    if not cells and not wrapped and not row.marks:
        return None
    return (wrapped, int(row.marks), cells)


def _page(screen: Screen, page, state: dict, front: bool) -> dict:
    lines = screen.lines
    max_y = state["max_y"]
    top = max(0, max_y - lines + 1)
    rows = {}
    buffer = page.data_buffer
    for number in range(top, top + lines):
        held = _row(buffer.get(number), buffer.get(number - 1), screen.columns)
        if held is not None:
            rows[number - top] = held
    history, _found = page.unwrap(min(state["history_floor"], top), top - 1)
    graphics = state["graphics"]
    images = {
        image_id: (image.format, image.width, image.height, image.data)
        for image_id, image in graphics.images_by_id.items()
        if image.format != PixelFormat.SIXEL
    }
    placements = sorted(
        (p.image_id, p.placement_id, p.x, p.y - top, p.columns, p.rows, p.z, p.virtual, p.asked_for_the_box)
        for p in graphics.placements
        if p.image_id in images and p.crop is None
    )
    cursor = state["pt_cursor_position"]
    seen = {
        "rows": rows,
        "history": [
            (int(line.marks), [_cell(column, cell) for column, cell in enumerate(line.cells)]) for line in history
        ],
        # How far down the page anything reached. `max_y` alone counts
        # only the rows the cursor wrote on, and a painted row is one;
        # DECALN and a scroll down write rows the cursor never reached.
        "reach": max([max_y, *(top + row for row in rows)]) - top,
        "show_cursor": page.show_cursor,
        "savepoints": [
            (*savepoint[:2], _charsets(savepoint.g_charsets), *savepoint[3:]) for savepoint in state["savepoints"]
        ],
        "tabstops": sorted(state["tabstops"]),
        # A page mode left in the first page's set says nothing: the
        # page in front is `_original_screen`'s to say. Lillecarl/pymux#856.
        "mode": sorted(state["mode"] - PAGE_MODES),
        "gl": state["gl"],
        "g_charsets": _charsets(state["g_charsets"]),
        "pointer_shapes": list(state["pointer_shapes"].stack),
        "kitty_flags_stack": state["kitty_flags_stack"],
        "images": images,
        "placements": placements,
    }
    if front:
        # A page given back takes the cursor its save holds, or the
        # one the page in front leaves: never its own.
        seen["cursor"] = (cursor.x, cursor.y - top)
        seen["pending_wrap"] = state["pending_wrap"]
    return seen


def view(screen: Screen) -> dict:
    "Every saved field of `screen`, as the oracle compares it."
    front = {name: getattr(screen, name) for name in screen.swap_variables}
    seen = {"page": _page(screen, screen.page, front, front=True)}
    if screen._original_screen is not None:
        seen["_original_screen"] = _page(screen, screen._original_screen, screen._original_screen_vars, front=False)
    for field in saved_fields(Screen):
        if field not in PAGE_FIELDS and field not in NOT_CARRIED:
            seen[field] = freeze_value(getattr(screen, field))
    return seen


def _difference(one: dict, other: dict) -> str | None:
    for key in sorted(one.keys() | other.keys()):
        if one.get(key) != other.get(key):
            if isinstance(one.get(key), dict) and isinstance(other.get(key), dict):
                inner = _difference(one[key], other[key])
                return "%s.%s" % (key, inner)
            return "%s: %r != %r" % (key, one.get(key), other.get(key))
    return None


def _same(screen: Screen, other: Screen) -> None:
    difference = _difference(view(other), view(screen))
    assert difference is None, difference


def _copied(screen: Screen, stream: Stream | None = None, history: int | None = None) -> tuple[Screen, Stream]:
    copy = a_screen(screen.columns, screen.lines, history=history)
    copy_stream = Stream(copy)
    paint(copy_stream, repaint(screen, stream.replay() if stream else ""))
    mark(copy, json.loads(json.dumps(marks_of(screen))))
    return copy, copy_stream


def test_every_saved_field_is_judged():
    judged = PAGE_FIELDS | set(NOT_CARRIED) | set(view(a_screen()))
    assert sorted(set(saved_fields(Screen)) - judged) == []


def test_a_blank_screen_paints_blank():
    screen = a_screen(40, 10)
    copy, _ = _copied(screen)
    _same(screen, copy)


def test_the_screen_of_every_corner_paints_the_same():
    screen = a_screen(80, 24)
    stream = Stream(screen)
    stream.feed(BEFORE)
    assert screen.in_alternate_screen
    copy, copy_stream = _copied(screen, stream)
    _same(screen, copy)

    stream.feed(AFTER)
    copy_stream.feed(AFTER)
    _same(screen, copy)


def test_the_first_page_paints_the_same():
    screen = a_screen(80, 24)
    stream = Stream(screen)
    stream.feed(BEFORE + CSI + "?1049l")
    copy, copy_stream = _copied(screen, stream)
    _same(screen, copy)
    stream.feed(AFTER)
    copy_stream.feed(AFTER)
    _same(screen, copy)


@pytest.mark.parametrize("seed", range(60))
def test_what_a_program_leaves_paints_the_same(seed):
    choose = random.Random(seed)
    screen = a_screen(40, 12, history=500)
    stream = Stream(screen)
    for _ in range(30):
        step = choose.choice(STEPS)
        if step == "resize":
            screen.resize(choose.randint(5, 30), choose.randint(20, 100))
        else:
            stream.feed(step)
    copy, copy_stream = _copied(screen, stream, history=500)
    _same(screen, copy)

    after = "".join(choose.choice(STEPS[:-1]) for _ in range(10))
    stream.feed(after)
    copy_stream.feed(after)
    _same(screen, copy)


@pytest.mark.parametrize("cut", CUTS)
def test_a_sequence_cut_by_a_repaint_reads_on_the_same(cut):
    head, tail = cut.split("|")
    screen = a_screen(40, 10)
    stream = Stream(screen)
    stream.feed(head)
    copy, copy_stream = _copied(screen, stream)
    stream.feed(tail)
    copy_stream.feed(tail)
    _same(screen, copy)


#: One thing a program leaves each, so a failure names it.
CORNERS = {
    "colours": CSI + "1;38;5;196;48;2;10;20;30mred" + CSI + "0m plain",
    "a link": OSC + "8;id=one;https://example.com" + ST + "link" + OSC + "8;;" + ST,
    "an open link": OSC + "8;;https://example.com" + ST + "open",
    "wide": "中文 é",
    "protection": ESC + "Vguarded" + ESC + "W " + CSI + '1"qdec' + CSI + '0"q',
    "a coloured erase": CSI + "41m" + CSI + "K" + CSI + "0m",
    "an erase": "abc" + CSI + "2D" + CSI + "X",
    "gaps": "a" + CSI + "5Cb" + CSI + "10Cc",
    "titles": OSC + "2;the window" + ST + OSC + "1;the icon" + ST + CSI + "22;0t" + OSC + "2;second" + ST,
    "hex titles": CSI + ">0;1t",
    "palette": OSC + "4;1;rgb:12/34/56" + ST + OSC + "11;rgb:01/02/03" + ST,
    "tab colour": OSC + "6;1;bg;red;brightness;200" + ST,
    "cursor shape": CSI + "4 q",
    "tab stops": CSI + "3g" + CSI + "5G" + ESC + "H",
    "a tab stop gone": CSI + "9G" + CSI + "g",
    "charsets": ESC + ")0" + "\x0e" + "lqk",
    "a single shift": ESC + "*0" + ESC + "N",
    "an image": ESC + "_Ga=T,f=24,s=1,v=1,i=7;/wAA" + ST,
    "keyboard": CSI + ">1u" + CSI + ">5u" + CSI + ">4;2m" + CSI + ">4;1f",
    "a region": CSI + "3;20r" + CSI + "10;5H",
    "left and right": CSI + "?69h" + CSI + "2;70s",
    "a saved cursor": CSI + "10;5H" + CSI + "1;31m" + ESC + "(0" + ESC + "7" + CSI + "0m" + ESC + "(B" + CSI + "H",
    "origin": CSI + "5;10r" + CSI + "?6h" + CSI + "2;3H",
    "a pending wrap": CSI + "24;1H" + "x" * 80,
    "a waiting save": CSI + "24;1H" + "y" * 80 + ESC + "7" + CSI + "H",
    "insert": CSI + "4h",
    "modes": CSI + "?1h" + CSI + "?2004h" + CSI + "?1000;1006h" + CSI + "?7l" + CSI + "?25l",
    "saved modes": CSI + "?2004h" + CSI + "?2004s" + CSI + "?2004l",
    "1048": CSI + "5;5H" + CSI + "?1048h" + CSI + "H",
    "pointer": OSC + "22;>wait,text" + ST,
    "levels": CSI + '62;1"p',
    "eight bit": ESC + " G",
    "settings": CSI + "2*x" + CSI + "1$~" + CSI + "48*|",
    "history": "".join("line %d\r\n" % number for number in range(60)),
    "a wrapped line": "w" * 100 + "\r\n" + "z" * 30,
    "the alternate page": "first\r\n" + CSI + "?1049h" + "second" + CSI + "3;3H",
    "the old alternate page": "first\r\n" + CSI + "?47h" + "second",
    "a save on both pages": CSI + "4;4H" + ESC + "7" + CSI + "?1049h" + CSI + "6;6H" + ESC + "7" + CSI + "H",
}


@pytest.mark.parametrize("name", CORNERS)
def test_each_corner_paints_the_same(name):
    screen = a_screen(80, 24)
    stream = Stream(screen)
    stream.feed(CORNERS[name])
    copy, copy_stream = _copied(screen, stream)
    _same(screen, copy)
    stream.feed(AFTER)
    copy_stream.feed(AFTER)
    _same(screen, copy)


def test_history_laid_out_at_another_width_arrives_as_its_lines():
    screen = a_screen(40, 10)
    stream = Stream(screen)
    stream.feed("".join("a line of thirty characters %02d\r\n" % number for number in range(30)))
    screen.resize(10, 20)
    assert screen.reflow_floor > screen.history_floor
    copy, _ = _copied(screen, stream)
    _same(screen, copy)


def test_the_marks_a_shell_left_arrive_on_their_rows():
    screen = a_screen(40, 10)
    stream = Stream(screen)
    for number in range(30):
        screen.mark_row(RowMark.PROMPT)
        stream.feed("$ command %d\r\n" % number)
        screen.mark_row(RowMark.OUTPUT)
        stream.feed("output\r\n")
    stream.feed(CSI + "?1049h")
    screen.mark_row(RowMark.PROMPT)
    copy, _ = _copied(screen, stream)
    _same(screen, copy)
    assert any(row.marks for row in copy._original_screen.data_buffer.values())


def test_a_repaint_answers_nothing():
    screen = a_screen(80, 24)
    Stream(screen).feed(BEFORE + CSI + "?2048h")
    answers: list[str] = []
    copy = Screen(24, 80, write_process_input=answers.append)
    stream = Stream(copy)
    paint(stream, repaint(screen))
    assert answers == []
    stream.feed(CSI + "6n")
    assert answers
