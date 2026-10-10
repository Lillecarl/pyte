"""
`pyte_rs.Row` answers what `pyte.page.Row` answers.

Both kinds of row take the same operations and have to give the same
answers on the way and hold the same cells at the end. Their images
have to agree on which rows are equal: two rows' images are equal
exactly when the rows hold the same cell objects in the same columns.

One difference is allowed: a Rust row iterates by column and a dict
in the order it was written, so contents are compared sorted. pyte's
whole suite runs with the Rust row in `checks.pyte-rs-unit`, which is
what says nothing reads that order. Lillecarl/pymux#570.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte_rs
from pyte.cells import _CHAR_CACHE, _ERASED_CACHE, PLAIN_APPEARANCE, UNWRITTEN
from pyte.page import Row

CELLS = [_CHAR_CACHE[c, PLAIN_APPEARANCE] for c in "ab "] + [_ERASED_CACHE[" ", PLAIN_APPEARANCE]]
COLUMNS = st.integers(-3, 12)

operations = st.lists(
    st.one_of(
        st.tuples(st.just("set"), COLUMNS, st.integers(0, len(CELLS) - 1)),
        st.tuples(st.just("del"), COLUMNS),
        st.tuples(st.just("pop"), COLUMNS),
        st.tuples(st.just("get"), COLUMNS),
        st.tuples(st.just("read"), COLUMNS),
        st.tuples(st.just("in"), COLUMNS),
        st.tuples(st.just("update"), st.dictionaries(COLUMNS, st.integers(0, len(CELLS) - 1), max_size=4)),
        st.tuples(st.just("clear")),
    ),
    max_size=30,
)


def apply(row, steps):
    answers = []
    for step in steps:
        kind = step[0]
        if kind == "set":
            row[step[1]] = CELLS[step[2]]
        elif kind == "del":
            try:
                del row[step[1]]
                answers.append("deleted")
            except KeyError:
                answers.append("KeyError")
        elif kind == "pop":
            answers.append(row.pop(step[1], "absent"))
        elif kind == "get":
            answers.append(row.get(step[1]))
        elif kind == "read":
            answers.append(row[step[1]])
        elif kind == "in":
            answers.append(step[1] in row)
        elif kind == "update":
            row.update({column: CELLS[which] for column, which in step[1].items()})
        else:
            row.clear()
        answers.append(len(row))
    return answers


@given(operations, st.booleans())
@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_same_operations_give_the_same_answers(steps, wrapped):
    pure, fast = Row(), pyte_rs.Row()
    pure.wrapped = fast.wrapped = wrapped
    assert apply(pure, steps) == apply(fast, steps)
    assert sorted(pure.items()) == sorted(fast.items())
    assert sorted(pure) == sorted(fast) == sorted(fast.keys())
    assert (pure == fast) and (fast == pure) and (fast == dict(pure))
    assert fast.wrapped is wrapped
    assert bool(pure) == bool(fast)


def test_a_column_nobody_wrote_reads_as_unwritten_and_stays_absent():
    row = pyte_rs.Row()
    assert row[5] is UNWRITTEN
    assert 5 not in row
    assert len(row) == 0


@given(operations, operations)
@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_images_agree_on_which_rows_are_equal(one, other):
    pure = [Row(), Row()]
    fast = [pyte_rs.Row(), pyte_rs.Row()]
    for steps, pure_row, fast_row in zip((one, other), pure, fast):
        apply(pure_row, steps)
        apply(fast_row, steps)
    # By identity: a written blank and an erased one are equal cells,
    # and draw differently.
    same = [(column, id(cell)) for column, cell in sorted(pure[0].items())] == [
        (column, id(cell)) for column, cell in sorted(pure[1].items())
    ]
    assert (pure[0].image() == pure[1].image()) is same
    assert (fast[0].image() == fast[1].image()) is same
    if same:
        assert hash(pure[0].image()) == hash(pure[1].image())
        assert hash(fast[0].image()) == hash(fast[1].image())


def test_an_image_does_not_follow_its_row():
    row = pyte_rs.Row()
    row[0] = CELLS[0]
    before = row.image()
    row[0] = CELLS[1]
    assert before != row.image()
    row[0] = CELLS[0]
    assert before == row.image()
