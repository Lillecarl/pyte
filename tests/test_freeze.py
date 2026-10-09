"""
A frozen screen thaws into one that holds the same and behaves the same.

Lillecarl/pymux#399.
"""

from __future__ import annotations

import json
import random
import time

import pytest
from a_screen import a_screen

from pyte.freeze import Freezer, Frozen, freeze, merge, thaw
from pyte.streams import Stream

ESC = "\x1b"
CSI = ESC + "["
OSC = ESC + "]"
ST = ESC + "\\"

#: A program that leaves something in every corner of the state.
BEFORE = "".join(
    [
        # History: more lines than the screen holds.
        *("line %d\r\n" % number for number in range(60)),
        # Colours, a link, wide characters and a combining mark.
        CSI + "1;38;5;196;48;2;10;20;30mred on rgb" + CSI + "0m ",
        CSI + "4:3;58;5;27mcurly" + CSI + "0m ",
        OSC + "8;id=one;https://example.com" + ST + "link" + OSC + "8;;" + ST + " ",
        "中文 é\r\n",
        # Protection, by both marks, and an erase with a background.
        ESC + "Vguarded" + ESC + "W " + CSI + '1"qdec' + CSI + '0"q\r\n',
        CSI + "41m" + CSI + "K" + CSI + "0m\r\n",
        # Titles, a palette colour, a cursor shape, a tab stop, charsets.
        OSC + "2;the window" + ST + OSC + "1;the icon" + ST + CSI + "22;0t",
        OSC + "4;1;rgb:12/34/56" + ST,
        CSI + "4 q",
        CSI + "3g" + CSI + "5G" + ESC + "H",
        ESC + ")0" + "\x0e" + "lqk" + "\x0f",
        # Keyboard settings a program reads back.
        CSI + ">1u" + CSI + ">4;2m",
        # A region, a saved cursor, and a pending wrap on the last line.
        CSI + "3;20r" + CSI + "10;5H" + ESC + "7",
        CSI + "?69h" + CSI + "2;70s",
        CSI + "24;1H" + "x" * 80,
        # The alternate screen, with its own content, left in front.
        CSI + "?1049h" + CSI + "2J" + CSI + "Halternate" + CSI + "5;5H" + ESC + "7",
    ]
)

#: What a program does next. Both screens must answer it the same way.
AFTER = "".join(
    [
        ESC + "8" + "restored",
        "\x0e" + "q" + "\x0f",
        CSI + "?1049l" + ESC + "8" + "main again",
        "\t" * 3 + "tabbed",
        CSI + "<u" + CSI + "r" + CSI + "?69l",
        OSC + "8;id=two;https://example.org" + ST + "more" + OSC + "8;;" + ST,
        "\r\n" * 30,
    ]
)


def _json(frozen: Frozen) -> Frozen:
    "The frozen screen as a file would give it back."
    return Frozen(*json.loads(json.dumps(frozen)))


def _first_difference(one, other, path="") -> str | None:
    if type(one) is not type(other):
        return "%s: %r != %r" % (path, one, other)
    if isinstance(one, dict):
        for key in sorted(one.keys() | other.keys()):
            if key not in one or key not in other:
                return "%s.%s: only on one side" % (path, key)
            found = _first_difference(one[key], other[key], "%s.%s" % (path, key))
            if found:
                return found
        return None
    if isinstance(one, list):
        if len(one) != len(other):
            return "%s: %d items != %d" % (path, len(one), len(other))
        for index, (a, b) in enumerate(zip(one, other)):
            found = _first_difference(a, b, "%s[%d]" % (path, index))
            if found:
                return found
        return None
    return None if one == other else "%s: %r != %r" % (path, one, other)


def _same(frozen: Frozen, other: Frozen) -> None:
    difference = _first_difference(json.loads(json.dumps(frozen)), json.loads(json.dumps(other)))
    assert difference is None, difference


def _cells(screen) -> list:
    "Every cell of both pages, with the kind a comparison of cells ignores."
    pages = [screen.page, screen._original_screen, screen._alternate_screen]
    return [
        [
            (number, row.wrapped, [(column, type(cell), cell.char, cell.appearance) for column, cell in row.items()])
            for number, row in sorted(page.data_buffer.items())
        ]
        for page in pages
        if page is not None
    ]


@pytest.fixture
def screens():
    screen = a_screen(80, 24)
    Stream(screen).feed(BEFORE)
    frozen = freeze(screen)
    thawed = a_screen(80, 24)
    thaw(_json(frozen), thawed)
    return screen, thawed, frozen


def test_a_thawed_screen_freezes_to_the_same_data(screens):
    screen, thawed, frozen = screens
    _same(freeze(thawed), frozen)


def test_a_thawed_screen_holds_the_same_cells(screens):
    screen, thawed, _ = screens
    assert screen._alternate_screen is not None or screen._original_screen is not None
    assert _cells(thawed) == _cells(screen)


def test_a_thawed_screen_behaves_the_same(screens):
    screen, thawed, _ = screens
    Stream(screen).feed(AFTER)
    Stream(thawed).feed(AFTER)
    _same(freeze(thawed), freeze(screen))
    assert _cells(thawed) == _cells(screen)


def test_the_parked_page_and_its_buffer_stay_one_object(screens):
    screen, thawed, _ = screens
    assert screen._original_screen_vars["data_buffer"] is screen._original_screen.data_buffer
    assert thawed._original_screen_vars["data_buffer"] is thawed._original_screen.data_buffer


#: What a program may do between two freezes. Each one moves, clears,
#: replaces or trims rows some way the screen has to report.
STEPS = [
    "plain text\r\n",
    "a line long enough to wrap past the edge of a narrow screen, and then some more of it\r\n",
    CSI + "1;31mred" + CSI + "0m\r\n",
    CSI + "?1049h",
    CSI + "?1049l",
    CSI + "?47h",
    CSI + "?47l",
    CSI + "2J",
    CSI + "3J",
    CSI + "K",
    CSI + "2L",
    CSI + "2M",
    CSI + "3S",
    CSI + "2T",
    CSI + "4;10r",
    CSI + "r",
    CSI + "5;3H",
    ESC + "c",
    ESC + "#8",
    "\r\n" * 15,
    "resize",
]


def _program(seed: int, length: int) -> list[str]:
    choose = random.Random(seed)
    return [choose.choice(STEPS) for _ in range(length)]


def _run(screen, program: list[str], seed: int) -> None:
    stream = Stream(screen)
    sizes = random.Random(seed)
    for step in program:
        if step == "resize":
            screen.resize(sizes.randint(5, 30), sizes.randint(20, 100))
        else:
            stream.feed(step)


@pytest.mark.parametrize("seed", range(40))
def test_a_later_freeze_merges_into_what_a_whole_one_says(seed):
    screen = a_screen(40, 12, history=50)
    _run(screen, _program(seed, 30), seed)
    freezer = Freezer()
    merged = _json(freezer.freeze(screen))
    for round in range(3):
        _run(screen, _program(seed * 7 + round, 12), seed + round)
        merged = merge(merged, _json(freezer.freeze(screen)))

        from_merge = a_screen(40, 12, history=50)
        thaw(merged, from_merge)
        from_whole = a_screen(40, 12, history=50)
        thaw(_json(freeze(screen)), from_whole)
        assert _cells(from_merge) == _cells(from_whole), "round %d" % round
        _same(freeze(from_merge), freeze(from_whole))


def test_a_later_freeze_of_a_deep_history_holds_only_what_changed():
    screen = a_screen(80, 24, history=10_000)
    Stream(screen).feed("".join("row %d\r\n" % number for number in range(10_024)))
    freezer = Freezer()
    freezer.freeze(screen)
    Stream(screen).feed("one more\r\n" + CSI + "1;1Htop")
    later = freezer.freeze(screen)
    assert later.whole == []
    assert sum(len(rows) for rows in later.buffers.values()) <= 3


#: Output cut inside a sequence of every kind. The cut is `|`.
CUTS = [
    "before" + CSI + "3|1;4" + "\n" + "2mred",
    "before" + CSI + "?10|49hon the alternate screen",
    OSC + "2;half a ti|tle" + ST + "after",
    OSC + "2;a title that ends with a bell|\x07after",
    ESC + "P1$|r" + ESC + "\\after",
    ESC + "(|0lqk",
    "text" + ESC + "|[1mbold",
    "text" + ESC + "|",
    CSI + "1;" + "\t" + "|" + "31mafter a tab inside",
]


@pytest.mark.parametrize("cut", CUTS)
def test_a_sequence_cut_by_a_thaw_reads_on_the_same(cut):
    head, tail = cut.split("|")
    screen = a_screen(40, 10)
    stream = Stream(screen)
    stream.feed(head)

    thawed = a_screen(40, 10)
    thawed_stream = Stream(thawed)
    thaw(_json(freeze(screen)), thawed)
    thaw(_json(freeze(stream)), thawed_stream)

    stream.feed(tail)
    thawed_stream.feed(tail)
    _same(freeze(thawed), freeze(screen))
    assert _cells(thawed) == _cells(screen)


def test_a_sequence_fed_in_pieces_is_pending_whole():
    screen = a_screen()
    stream = Stream(screen)
    for piece in ["plain", CSI, "1", ";", "\n", "3"]:
        stream.feed(piece)
    assert stream.replay() == CSI + "1;3"
    stream.feed("1m")
    assert stream.replay() == ""


@pytest.mark.parametrize("rows", [2_000, 10_000, 50_000])
def test_how_long_a_deep_history_takes(rows, capsys):
    """
    The time a freeze, its JSON and a thaw take, printed to the log.

    A hot upgrade pauses the server for the freeze, so this is the
    number Lillecarl/pymux#399 bounds. The assertion is loose, because
    a build machine is not the machine a person sits at.
    """
    screen = a_screen(80, 24, history=rows)
    line = CSI + "32m%06d" + CSI + "0m " + "the quick brown fox jumps over the lazy dog " * 2
    Stream(screen).feed("".join((line % number)[:200] + "\r\n" for number in range(rows + 24)))

    freezer = Freezer()
    started = time.perf_counter()
    frozen = freezer.freeze(screen)
    frozen_at = time.perf_counter()
    text = json.dumps(frozen)
    dumped_at = time.perf_counter()
    thaw(Frozen(*json.loads(text)), a_screen(80, 24, history=rows))
    thawed_at = time.perf_counter()
    # What the pause pays: a screenful written since the first freeze.
    Stream(screen).feed("".join((line % number)[:200] + "\r\n" for number in range(24)))
    again_at = time.perf_counter()
    freezer.freeze(screen)
    later_at = time.perf_counter()

    with capsys.disabled():
        print(
            "\nfreeze %d rows: freeze %.3fs, json %.3fs (%.1f MB), load and thaw %.3fs, a screenful later %.4fs"
            % (
                rows,
                frozen_at - started,
                dumped_at - frozen_at,
                len(text) / 1e6,
                thawed_at - dumped_at,
                later_at - again_at,
            )
        )
    assert frozen_at - started < 30


def test_what_declares_no_keep_is_refused():
    class Stranger:
        pass

    with pytest.raises(TypeError, match="declares no KEEP"):
        freeze({"one": Stranger()})


def test_a_class_outside_pyte_is_never_built():
    stranger = {"dict": [["x", {"object": "os.Popen", "id": 1, "fields": {}}]], "id": 0}
    root = {"object": "pyte.screen.Screen", "id": 9, "fields": {"saved_modes": stranger}}
    with pytest.raises(ValueError, match="not pyte's"):
        thaw(Frozen(root, {}, [], [], {}), a_screen())
