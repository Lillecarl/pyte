"""
What a legacy pane reads where the terminals split, profile by profile.

`test_keys_against_the_key_panel.py` holds each answer to the terminal
it copies. Lillecarl/pymux#706.
"""

from __future__ import annotations

import pytest

from pyte.keys import (
    DEFAULT_KEY_PROFILE,
    KEY_PROFILES,
    FunctionalKey,
    KeyboardFlag,
    ModifyOtherKeys,
    key_profile_of,
    translate_key_data,
)

KITTY, GHOSTTY, WEZTERM, XTERM = (KEY_PROFILES[name] for name in ("kitty", "ghostty", "wezterm", "xterm"))


def sent(data: str, profile, flags: int = 0, **modes) -> str:
    return translate_key_data(data, flags=flags, profile=profile, **modes)


@pytest.mark.parametrize(
    ("version", "term", "name"),
    [
        ("kitty(0.49.2)", "xterm-256color", "kitty"),
        ("ghostty 1.2.0", "", "ghostty"),
        ("WezTerm 20240203-110809-5046fc22", "", "wezterm"),
        ("XTerm(390)", "xterm", "xterm"),
        ("", "xterm-kitty", "kitty"),
        ("", "wezterm", "wezterm"),
        ("", "xterm-256color", None),
        ("foot(1.20.2)", "foot", None),
    ],
)
def test_a_terminal_is_named_by_its_answer_and_then_by_its_term(version, term, name):
    assert key_profile_of(version, term) == name


def test_kitty_is_the_default():
    assert DEFAULT_KEY_PROFILE is KITTY
    assert translate_key_data("\x1b[57363u", flags=0) == "\x1b[29~"


@pytest.mark.parametrize(("profile", "delete"), [(KITTY, "\x1b[3;9~"), (WEZTERM, "\x1b[3~"), (XTERM, "\x1b[3~")])
def test_super_in_a_csi_form(profile, delete):
    assert sent("\x1b[3;9~", profile) == delete
    assert sent("\x1b[1;13D", profile) == ("\x1b[1;13D" if profile.writes_super else "\x1b[1;5D")


def test_super_on_a_key_that_types_text_is_dropped_by_every_profile():
    for profile in KEY_PROFILES.values():
        assert sent("\x1b[97;9u", profile) == "a"


@pytest.mark.parametrize(
    ("profile", "menu", "ctrl_menu"),
    [(KITTY, "\x1b[29~", "\x1b[29;5~"), (XTERM, "\x1b[29~", "\x1b[29;5~"), (GHOSTTY, "", ""), (WEZTERM, "", "")],
)
def test_menu(profile, menu, ctrl_menu):
    assert sent("\x1b[%du" % FunctionalKey.MENU, profile) == menu
    assert sent("\x1b[%d;5u" % FunctionalKey.MENU, profile) == ctrl_menu


@pytest.mark.parametrize(
    ("key", "rxvt"),
    [(FunctionalKey.F13, "\x1b[25~"), (FunctionalKey.F13 + 7, "\x1b[34;2~"), (FunctionalKey.F24, "\x1b[45~")],
)
def test_wezterm_writes_f13_to_f24_as_rxvt_does(key, rxvt):
    data = "\x1b[%d%su" % (key, ";2" if rxvt.endswith(";2~") else "")
    assert sent(data, WEZTERM) == rxvt
    assert sent(data, KITTY) == ""


def test_f25_has_no_legacy_form_anywhere():
    for profile in KEY_PROFILES.values():
        assert sent("\x1b[%du" % (FunctionalKey.F24 + 1), profile) == ""


def test_a_modified_f3_is_what_the_terminfo_of_the_pane_names():
    "Not kitty's CSI 13 ; 2 ~, which is what xterm-kitty names."
    for profile in KEY_PROFILES.values():
        assert sent("\x1b[13;2~", profile) == "\x1b[1;2R"


@pytest.mark.parametrize(("profile", "bracket"), [(KITTY, "{"), (GHOSTTY, "{"), (WEZTERM, "\x1b"), (XTERM, "\x1b")])
def test_ctrl_and_shift_on_a_bracket(profile, bracket):
    "ctrl+shift+[, which the terminal of the person sends with its shifted key."
    assert sent("\x1b[91:123;6u", profile) == bracket
    assert sent("\x1b[91:123;8u", profile) == "\x1b" + bracket


def test_ctrl_and_shift_keep_the_shifted_key_where_the_key_has_no_control_code():
    for profile in KEY_PROFILES.values():
        assert sent("\x1b[59:58;6u", profile) == ":"
        assert sent("\x1b[45:95;6u", profile) == "\x1f"


def test_modify_other_keys_is_xterms_whatever_the_profile():
    """
    It is xterm's own mode, so xterm answers under it: super is gone
    from Delete, as xterm and WezTerm send it. Lillecarl/pymux#693.
    """
    for level in (ModifyOtherKeys.ALT_AND_META, ModifyOtherKeys.EVERY_MODIFIER):
        assert sent("\x1b[3;9~", KITTY, modify_other_keys=level) == "\x1b[3~"


def test_a_pane_that_reads_the_number_of_a_key_reads_it_in_every_profile():
    for profile in KEY_PROFILES.values():
        assert sent("\x1b[%du" % FunctionalKey.F13, profile, flags=KeyboardFlag.DISAMBIGUATE) == "\x1b[57376u"
