"""
`pyte_rs.decode_sixel` decodes what `pyte.sixel.decode_sixel` decodes.

Random payloads of every command a body holds -- data, repeats, colour
selections and definitions in both systems, carriage returns, new bands,
raster attributes -- with numbers short, long and past 18 digits, and
digits Python reads that ASCII does not. Both have to give the same
image, byte for byte, or the same error. Lillecarl/pymux#574.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte_rs
from pyte import sixel

#: The reference, taken before any test could have installed a kernel.
PURE = sixel.decode_sixel

#: Mostly small: registers and colour components are, and a register a
#: body selects has to come up again for its data to show it.
numbers = st.one_of(
    st.integers(0, 16).map(str),
    st.integers(0, 16).map(str),
    st.integers(0, 16).map(str),
    st.integers(0, 400).map(str),
    st.integers(0, 10**25).map(str),
    st.just(""),
    st.sampled_from(["²", "٣", "0" * 30 + "7"]),
)

piece = st.one_of(
    st.text(alphabet="".join(chr(c) for c in range(0x3F, 0x7F)), min_size=1, max_size=8),
    st.tuples(numbers, st.sampled_from("?~@Ax!")).map(lambda p: "!" + p[0] + p[1]),
    numbers.map(lambda n: "#" + n),
    st.tuples(numbers, st.sampled_from(["1", "2", "3", ""]), numbers, numbers, numbers).map(
        lambda p: "#%s;%s;%s;%s;%s" % p
    ),
    st.tuples(numbers, numbers).map(lambda p: "#%s;%s" % p),
    st.sampled_from(["$", "-", " ", "\n", "\x07"]),
    st.lists(numbers, min_size=1, max_size=5).map(lambda values: '"' + ";".join(values)),
)

head = st.one_of(
    st.lists(st.sampled_from(["", "0", "1", "2", "7", "12345678901234567890"]), max_size=4).map(
        lambda parts: ";".join(parts) + "q"
    ),
    st.sampled_from(["", "x", "0;1", "²q"]),
)


@given(head, st.lists(piece, max_size=40))
@settings(max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_same_image_is_decoded(start, pieces):
    payload = start + "".join(pieces)
    try:
        expected = ("ok", PURE(payload))
    except Exception as error:
        expected = (type(error).__name__, str(error))
    try:
        found = ("ok", pyte_rs.decode_sixel(payload))
    except Exception as error:
        found = (type(error).__name__, str(error))
    assert found == expected


PURE_SIZE = sixel.sixel_size


def _answer(function, payload):
    try:
        return ("ok", function(payload))
    except Exception as error:
        return (type(error).__name__, str(error))


@given(head, st.lists(piece, max_size=40))
@settings(max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_size_is_the_decoded_size(start, pieces):
    "Both sizes are the decoder's: the Python's walk and the kernel's."
    payload = start + "".join(pieces)
    decoded = _answer(PURE, payload)
    if decoded[0] == "ok" and decoded[1] is not None:
        decoded = ("ok", decoded[1][:2])
    assert _answer(PURE_SIZE, payload) == decoded
    assert _answer(pyte_rs.sixel_size, payload) == decoded


def test_a_run_of_data_past_the_widest_row_is_sized_the_same():
    "The kernel sizes a run of data characters in one step; the edge is where it could slip."
    payload = "0;1q!16380~" + "~" * 10 + "-" + "~" * 20
    assert _answer(pyte_rs._native.sixel_size, payload) == _answer(PURE_SIZE, payload)


def test_an_ordinary_image_is_answered_in_rust():
    "Not handed back to the Python: the payloads programs send are ASCII."
    payload = '0;1;0q"1;1;4;6#1;2;100;0;0#1~~~~-'
    assert sixel_answer(payload) is not False
    assert pyte_rs.decode_sixel(payload) == PURE(payload)
    assert pyte_rs._native.sixel_size(payload) == (4, 6)


def sixel_answer(payload):
    return pyte_rs._native.decode_sixel(payload)
