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
import ast
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


def test_an_escape_sequence_with_no_intermediate_byte():
    assert rewritten("\x1bc") == "esc(escape.RIS)"
    assert rewritten("\x1bM") == "esc(escape.RI)"
    assert rewritten("\x1bZ") == "esc(Escape.DECID)"


def test_the_sharp_and_the_announcer_families():
    assert rewritten("\x1b#6") == "sharp(Sharp.DECDWL)"
    assert rewritten("\x1b F") == "announce(escape.S7C1T)"


def test_the_intermediate_byte_picks_the_family():
    "'ESC 8' is DECRC and 'ESC # 8' is DECALN."
    assert rewritten("\x1b8") == "esc(escape.DECRC)"
    assert rewritten("\x1b#8") == "sharp(Sharp.DECALN)"


def test_an_operating_system_command():
    assert rewritten("\x1b]4;3;#aabbcc\x1b\\") == (
        'osc(Osc.PALETTE_COLOR, "3", "#aabbcc")'
    )
    assert rewritten("\x1b]104\x1b\\") == "osc(Osc.RESET_PALETTE_COLOR)"
    assert rewritten("\x1b]8;;\x1b\\") == 'osc(Osc.HYPERLINK, "", "")'


def test_a_code_that_osc_py_does_not_name_stays_a_string():
    "The dynamic colours are 10 to 19, and a member each gains nothing."
    assert rewritten("\x1b]10;?\x1b\\") == 'osc("10", "?")'


def test_the_terminator_is_named():
    assert rewritten("\x1b]11;?\x07") == (
        'osc("11", "?", end=Terminator.BEL)'
    )


def test_a_device_control_string_and_an_application_one():
    assert rewritten("\x1bP1$r0m\x1b\\") == 'dcs("1$r0m")'
    assert rewritten("\x1b_Gi=31;OK\x1b\\") == 'apc("Gi=31;OK")'


def test_a_dcs_that_asks_a_setting_back_says_which():
    """
    "$q" asks a setting back and what follows names the sequence that
    would set it, so it takes the name `csi` gives that sequence.
    """
    assert rewritten("\x1bP$qm\x1b\\") == "decrqss(escape.SGR)"
    assert rewritten("\x1bP$q q\x1b\\") == "decrqss(Csi.DECSCUSR)"
    assert rewritten('\x1bP$q"p\x1b\\') == "decrqss(Csi.DECSCL)"


def test_a_dcs_that_is_an_answer_is_carried_across_whole():
    "'$r' answers and '+q' reads a capability. Neither is a setting."
    assert rewritten("\x1bP+qzzzz\x1b\\") == 'dcs("+qzzzz")'


def test_a_string_sequence_with_no_terminator_is_left_alone():
    """
    A prefix and not a sequence. A test that feeds one is checking
    what the parser does with an unfinished sequence, so it has to
    stay unfinished.
    """
    assert reason("\x1bP") == "no terminator"
    assert reason("\x1b]11;?") == "no terminator"


def test_a_payload_that_is_a_template_is_left_alone():
    assert reason("\x1b]22;%s\x1b\\") == "a format template"


def test_a_prefix_is_not_an_escape_sequence():
    """
    "ESC O" starts an SS3 form, and a byte no family names is left
    alone. A bare ESC is a key and not a sequence at all.
    """
    assert reason("\x1bO") == "not CSI"
    assert reason("\x1b") == "not CSI"
    assert reason("\x1b(0") == "not CSI"


# ----------------------------------------------------------------------
# What it refuses.


def test_a_string_with_two_sequences_becomes_two_calls():
    assert rewritten("\x1b[2J\x1b[H") == "csi(escape.ED, 2) + csi(escape.CUP)"


def test_the_text_between_two_sequences_stays_text():
    assert rewritten("\x1b[42mhi\x1b[K") == (
        'csi(escape.SGR, 42) + "hi" + csi(escape.EL)'
    )


def test_the_text_around_a_sequence_stays_text():
    assert rewritten("a\r\nb\x1b[0S") == '"a\\r\\nb" + csi(Csi.SU, 0)'
    assert rewritten("ab\x1b#8X") == '"ab" + sharp(Sharp.DECALN) + "X"'


def test_a_quote_in_the_text_is_left_to_repr():
    """
    Double quotes are what this codebase writes, so the swap happens
    where it needs no other change. Getting the escaping right by hand
    is how a rewrite writes bytes nobody meant.
    """
    assert rewritten("a'b\x1b[2J") == '"a\'b" + csi(escape.ED, 2)'
    assert rewritten('a"b\x1b[2J') == '\'a"b\' + csi(escape.ED, 2)'


def test_a_string_is_named_whole_or_not_at_all():
    """
    A string this tool half understands is worse than one it leaves
    alone: a reader cannot tell which of the pieces was checked. So
    the first ESC with no rule gives up on all of it, even the parts
    that had one.
    """
    assert rewritten("\x1b[2J\x1b(0") is None
    assert reason("\x1b[2J\x1b(0") == "not CSI"


def test_a_charset_designation_is_left_alone():
    """
    "ESC ( 0" picks the line drawing set. It is a family of its own,
    with the set in the byte after the "(", and nothing names it yet.
    """
    assert reason("\x1b(0") == "not CSI"
    assert reason("\x1b(B") == "not CSI"


def test_a_piece_of_a_sequence_is_left_alone():
    "A prefix that a test strips off an answer is not a sequence."
    assert reason("\x1b[9;") == "no whole CSI sequence"


def test_a_final_byte_with_no_name_is_counted():
    assert reason("\x1b[1*{").startswith("no name")


def test_what_follows_a_sequence_survives():
    """
    A newline after the sequence is not part of it, and a rewrite that
    dropped it would change what the test feeds.

    This is the one the tool got wrong. In Python a `$` in a pattern
    matches before a trailing newline as well as at the end, so
    `"\\x1b[4;1H\\n"` read as a bare sequence and the newline went
    away. The check that every expression writes back the string it
    replaced caught it, on the first file outside pyte, before
    anything was written.
    """
    assert rewritten("\x1b[4;1H\n") == 'csi(escape.CUP, 4, 1) + "\\n"'
    assert rewritten("\x1b[2Jx") == 'csi(escape.ED, 2) + "x"'


def test_a_format_template_is_not_a_sequence():
    """
    `"\\x1b[%dm"` reads as a sequence whose intermediate byte is "%",
    and no name has a "%" in it, so nothing would be rewritten
    anyway. That is luck rather than a rule, and a template rewritten
    as the bytes it looks like would be silent and unreadable.
    """
    assert reason("\x1b[%dm") == "a format template"
    assert reason("\x1b[1;%dH") == "a format template"


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


def test_a_long_line_is_wrapped_and_not_left_alone():
    """
    A name is longer than the bytes it names, and that is the trade.

    The point of the rewrite is that a person, or an agent reading the
    code, sees what a sequence is without decoding it. Length is not a
    reason to leave one as bytes, so a line that grows past the room
    on it goes onto several lines, the way somebody writing it by hand
    would do.
    """
    source = (
        'def t():\n'
        '    feed("\\x1b[5;7r\\x1b[?69h\\x1b[5;7s\\x1b[?6h")\n'
    )
    changes, skipped = changes_in(source)
    assert len(changes) == 1
    assert skipped == []

    written = applied(source, changes)
    assert written == (
        "def t():\n"
        "    feed(\n"
        "        csi(escape.DECSTBM, 5, 7)\n"
        "        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)\n"
        "        + csi(Csi.DECSLRM, 5, 7)\n"
        "        + set_mode(PrivateMode.ORIGIN)\n"
        "    )\n"
    )
    ast.parse(written)


def test_a_line_that_fits_stays_on_one_line():
    source = 'def t():\n    feed("\\x1b[1;1H")\n'
    written = applied(source, changes_in(source)[0])

    assert written == "def t():\n    feed(csi(escape.CUP, 1, 1))\n"


def test_a_wrap_reuses_the_brackets_that_are_there():
    """
    `feed("...")` already has parentheses around the expression, and a
    second pair inside them says nothing. Where there is no bracket,
    the wrap brings its own, because the expression has to stay one
    expression.
    """
    inside = 'def t():\n    feed("\\x1b[5;7r\\x1b[?69h\\x1b[5;7s\\x1b[?6h")\n'
    assert "((" not in applied(inside, changes_in(inside)[0])

    bare = 'WHAT = "\\x1b[5;7r\\x1b[?69h\\x1b[5;7s\\x1b[?6h"\n'
    written = applied(bare, changes_in(bare)[0])
    assert written.startswith("WHAT = (\n")
    ast.parse(written)


def test_two_rewrites_on_one_line_are_not_wrapped():
    """
    One wrap to a line. Two would have to be laid out around each
    other, and that is a judgement about the whole line rather than
    about one string in it.
    """
    source = (
        'def t():\n'
        '    feed("\\x1b[5;7r\\x1b[?69h\\x1b[5;7s", "\\x1b[5;7r\\x1b[?69h")\n'
    )
    written = applied(source, changes_in(source)[0])

    assert "\n" not in written.splitlines()[1]
    ast.parse(written)


# ----------------------------------------------------------------------
# What it writes into the file.


def test_a_character_outside_ascii_does_not_move_the_splice():
    """
    `ast` reports a column in UTF-8 bytes and not in characters, so a
    line that holds anything outside ASCII puts every column after it
    too far along.

    It ate the comma after the rewrite on this very line and left a
    file that does not parse. Nothing but the parser would have said
    so: the check that every expression writes back its own string
    reads the string and not the line it sits on.
    """
    source = 'def t():\n    assert not differences("\\x1b[3Gá", lines=3)\n'
    changes, _ = changes_in(source)
    written = applied(source, changes)

    assert 'differences(csi(escape.CHA, 3) + "á", lines=3)' in written
    ast.parse(written)


def test_two_rewrites_on_one_line_both_land():
    "The splice runs backwards, so one never moves the other."
    source = 'def t():\n    feed("\\x1b[2T", "\\x1b[3T")\n'
    changes, _ = changes_in(source)
    written = applied(source, changes)

    assert "feed(csi(Csi.SD, 2), csi(Csi.SD, 3))" in written
    ast.parse(written)


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
    from pyte.osc import Osc  # noqa: F401
    from pyte.sequences import (  # noqa: F401
        Csi,
        Escape,
        Sharp,
        Terminator,
        announce,
        apc,
        csi,
        dcs,
        decrqss,
        esc,
        osc,
        reset_mode,
        set_mode,
        sharp,
    )

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
        "\x1bc",
        "\x1b#6",
        "\x1b F",
        "\x1b]4;3;#aabbcc\x1b\\",
        "\x1b]104\x1b\\",
        "\x1b]11;?\x07",
        "\x1b]8;;\x1b\\",
        "\x1bP$qm\x1b\\",
        "\x1bP1$r0m\x1b\\",
        "\x1b_Gi=31;OK\x1b\\",
        "\x1b[2J\x1b[H",
        "\x1b[42mhi\x1b[K",
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
