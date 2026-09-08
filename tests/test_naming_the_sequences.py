"""
What the rewriting tool does, and what it refuses to touch.

`tools/name_the_sequences.py` moves hand-typed escape sequences over
to the builders in `pyte.sequences`. It has changed a few hundred
lines across three repositories, so what it will and will not do is
worth holding here rather than in the memory of whoever ran it.
Lillecarl/pymux#165.

The rules it must not lose are the refusals. A tool that rewrites the
expected value of an assertion turns a test into one that passes
whatever the code does, and nothing downstream would say so.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from name_the_sequences import (  # noqa: E402
    Rewrite,
    Skipped,
    an_expression_for,
    applied,
    changes_in,
    with_the_imports,
)


def rewritten(text):
    "The expression for one string, or None when there is no rule."
    answer = an_expression_for(text)
    return answer.expression if isinstance(answer, Rewrite) else None


def reason(text):
    "Why one string was left alone."
    answer = an_expression_for(text)
    return answer.reason if isinstance(answer, Skipped) else None


# ----------------------------------------------------------------------
# What it writes.


def test_a_sequence_with_parameters():
    assert rewritten("\x1b[2T") == "csi(Csi.SD, 2)"
    assert rewritten("\x1b[1;1H") == "csi(escape.CUP, 1, 1)"


def test_a_sequence_with_none():
    assert rewritten("\x1b[J") == "csi(escape.ED)"


def test_an_empty_parameter_stays_empty():
    "Which is not the same as a zero: the default of that position."
    assert rewritten("\x1b[;5H") == "csi(escape.CUP, None, 5)"


def test_the_intermediate_bytes_are_part_of_the_name():
    assert rewritten("\x1b[4 q") == "csi(Csi.DECSCUSR, 4)"
    assert rewritten("\x1b[!p") == "csi(Csi.DECSTR)"


def test_a_private_marker_is_named():
    assert rewritten("\x1b[?62;1;6c") == "csi(escape.DA, 62, 1, 6, private='?')"


def test_a_mode_is_a_mode_before_it_is_a_sequence():
    "The rules run from the most specific to the least."
    assert rewritten("\x1b[?1049h") == (
        "set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)"
    )
    assert rewritten("\x1b[?1049l") == (
        "reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)"
    )
    assert rewritten("\x1b[4h") == "set_mode(AnsiMode.INSERT_REPLACE)"


def test_a_mode_nobody_names_is_written_the_long_way():
    """
    2026 is synchronised output, which `modes.py` does not name. The
    long form says the marker out loud, so nothing is guessed.
    """
    assert rewritten("\x1b[?2026h") == "csi(escape.SM, 2026, private='?')"


def test_the_name_of_a_final_byte_is_the_csi_one():
    """
    `escape.py` names the ESC sequences and the CSI ones in one file,
    and the same byte means two things: "D" is IND after ESC and CUB
    after CSI. A rewrite that took the wrong one would write the right
    bytes under a name that means something else.
    """
    assert rewritten("\x1b[3D") == "csi(escape.CUB, 3)"
    assert rewritten("\x1b[c") == "csi(escape.DA)"


# ----------------------------------------------------------------------
# What it refuses.


def test_a_string_with_two_sequences_is_left_alone():
    "One call per sequence, and where a blob divides is a judgement."
    assert reason("\x1b[2J\x1b[H") == "not one sequence"


def test_a_sequence_that_is_not_csi_is_left_alone():
    assert reason("\x1b]0;title\x07") == "not CSI"


def test_a_piece_of_a_sequence_is_left_alone():
    "A prefix that a test strips off an answer is not a sequence."
    assert reason("\x1b[9;") == "no whole CSI sequence"


def test_a_final_byte_with_no_name_is_counted():
    assert reason("\x1b[1*{").startswith("no name")


def test_a_sequence_with_something_after_it_is_left_alone():
    """
    A newline after the sequence is not part of it, and the rewrite
    would have dropped it.

    This is the one the tool got wrong. In Python a `$` in a pattern
    matches before a trailing newline as well as at the end, so
    `"\\x1b[4;1H\\n"` read as a bare sequence. The check that every
    expression writes back the string it replaced caught it, on the
    first file outside pyte, before anything was written.
    """
    assert reason("\x1b[4;1H\n") == "no whole CSI sequence"
    assert reason("\x1b[2Jx") == "no whole CSI sequence"


def test_what_an_assertion_expects_is_left_alone():
    """
    The bytes a test compares against are the subject of the test. A
    rewrite there asks the writer to mark its own work, and the test
    passes whatever the writer does.
    """
    changes, _ = changes_in(
        'def t():\n    assert answers == ["\\x1b[0n"]\n'
    )
    assert changes == []


def test_what_a_string_method_is_asked_about_is_left_alone():
    """
    `line.endswith("\\x1b[0m")` asks a question about an answer, the
    same way `line == "\\x1b[0m"` does.

    This one matters because product code uses the builders too.
    `pymux/pymux/blocks.py` ends a line with `csi(escape.SGR, 0)`, so
    a test that expected `csi(escape.SGR, 0)` would have stopped
    asking anything at all.
    """
    changes, _ = changes_in(
        'def t():\n    assert line.endswith("\\x1b[2T")\n'
    )
    assert changes == []

    changes, _ = changes_in(
        'def t():\n    x = answer.removeprefix("\\x1b[2T")\n'
    )
    assert changes == []


def test_a_needle_is_left_alone():
    "`x in written` asks the same question as `x == written`."
    changes, _ = changes_in('def t():\n    assert "\\x1b[2T" in written\n')
    assert changes == []


def test_a_sequence_going_into_a_call_is_not_an_expectation():
    "Even when the call is one side of a comparison."
    source = 'def t():\n    assert feed("\\x1b[2T") == [1]\n'
    changes, _ = changes_in(source)
    assert [change.rewrite.expression for change in changes] == [
        "csi(Csi.SD, 2)"
    ]


def test_a_docstring_is_left_alone():
    changes, _ = changes_in('def t():\n    "\\x1b[2J is an erase."\n')
    assert changes == []


def test_a_part_of_an_f_string_is_left_alone():
    changes, _ = changes_in('def t():\n    x = f"\\x1b[2J{1}"\n')
    assert changes == []


def test_a_line_with_no_room_is_left_alone():
    """
    A name is longer than the bytes it names. Wrapping the line is a
    decision about how it should read, which is a person's.
    """
    short = 'def t():\n    feed("\\x1b[1;1H")\n'
    assert len(changes_in(short)[0]) == 1

    padded = "x" * 70
    long = 'def t():\n    feed("\\x1b[1;1H", "%s")\n' % padded
    changes, skipped = changes_in(long)
    assert changes == []
    assert [one.reason for one in skipped] == ["no room on the line"]


# ----------------------------------------------------------------------
# What it writes into the file.


def test_the_import_goes_under_the_imports_the_file_has():
    source = 'import re\n\nfrom pyte.streams import Stream\n\nfeed("\\x1b[2T")\n'
    changes, _ = changes_in(source)
    written = with_the_imports(applied(source, changes), changes)

    lines = written.splitlines()
    assert lines[2] == "from pyte.streams import Stream"
    assert lines[3] == "from pyte.sequences import Csi, csi"


def test_the_names_of_one_module_share_a_line():
    source = 'feed("\\x1b[2T")\nfeed("\\x1b[1;1H")\n'
    changes, _ = changes_in(source)
    written = with_the_imports(applied(source, changes), changes)

    assert "from pyte.sequences import Csi, csi" in written
    assert "from pyte import escape" in written


def test_an_import_the_file_has_is_not_added_again():
    source = 'from pyte import escape\n\nfeed("\\x1b[1;1H")\n'
    changes, _ = changes_in(source)
    written = with_the_imports(applied(source, changes), changes)

    assert written.count("from pyte import escape") == 1


def test_every_rewrite_writes_the_string_it_replaces():
    """
    The check that makes the whole thing trustworthy.

    A tool that changes a few hundred strings is worth having only if
    it cannot get one of them wrong quietly, so every expression is
    evaluated and compared before a file is written. This asks the
    same question of every rule above.
    """
    from pyte import escape  # noqa: F401
    from pyte.modes import AnsiMode, PrivateMode  # noqa: F401
    from pyte.sequences import Csi, csi, reset_mode, set_mode  # noqa: F401

    for text in (
        "\x1b[2T",
        "\x1b[1;1H",
        "\x1b[;5H",
        "\x1b[4 q",
        "\x1b[!p",
        "\x1b[?62;1;6c",
        "\x1b[?1049h",
        "\x1b[4h",
        "\x1b[?2026h",
        "\x1b[3D",
        "\x1b[c",
        "\x1b[J",
    ):
        expression = rewritten(text)
        assert expression is not None, text
        assert eval(expression) == text, expression


@pytest.mark.parametrize("marker", ["?", ">", "<", "="])
def test_every_marker_survives_the_round_trip(marker):
    from pyte import escape  # noqa: F401
    from pyte.sequences import Csi, csi  # noqa: F401

    text = "\x1b[%s1u" % marker
    expression = rewritten(text)
    assert expression is not None
    assert eval(expression) == text
