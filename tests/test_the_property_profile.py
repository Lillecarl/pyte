"""
The gate draws the same examples every run.

A property test with no seed is a different test every time it runs.
This suite had one: `test_a_size_change_keeps_every_line` failed about
one run in eight, and a gate that is red by luck teaches everybody to
run it again instead of to look. Lillecarl/pymux#180.

`tests/conftest.py` names the two profiles and loads one. This file
holds the promise each one makes, because the promise lives in the
order two lines run in, and nothing else here would say when that
order changed.
"""

from hypothesis import settings

#: What a run without `--hypothesis-profile` gets.
GATE = "pinned"

#: The other one. `checks.pyte-roaming` runs it and is not a gate.
HUNT = "roaming"


def test_the_conftest_registers_both_profiles():
    for name in (GATE, HUNT):
        assert settings.get_profile(name).print_blob, name


def test_the_gate_pins_the_draw_and_the_hunt_does_not():
    """
    The two differ in one setting, and it is the one this is about.

    A `derandomize` run seeds each property test from its own source,
    so the examples of one run are the examples of the next.
    """
    assert settings.get_profile(GATE).derandomize
    assert not settings.get_profile(HUNT).derandomize


def test_a_run_takes_the_gate_unless_it_was_asked_for_the_hunt():
    name = settings.get_current_profile_name()
    assert name in (GATE, HUNT), name
    assert settings.default.derandomize is (name == GATE)


def test_a_property_test_of_this_suite_inherits_the_profile():
    """
    The whole point, and the part that breaks silently.

    A `@settings(...)` decorator reads the profile that is loaded when
    the decorator runs, which is when pytest imports the test module.
    Loading the profile any later than a conftest leaves every
    property test on hypothesis's own default, and nothing says so:
    the suite still passes, and it goes back to drawing a different
    test every run.
    """
    from test_reflow_keeps_the_content import (
        test_a_size_change_keeps_every_line as it,
    )

    drawn = it._hypothesis_internal_use_settings
    assert drawn.derandomize is settings.default.derandomize
