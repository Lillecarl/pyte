"""
What SGR means for a rendition, and nothing else of a screen.

`after_sgr` is the rendition an SGR leaves, `parameters_of` writes a
rendition back as SGR parameters, and `erased_appearance` is how an
erase paints a cell under one. Each reads only the rendition it is
given, so `Screen` calls them and holds no copy.
"""

from __future__ import annotations

from .cells import (
    BASELINE_PARAMETERS,
    PLAIN,
    UNDERLINE_PARAMETERS,
    UNDERLINE_SHAPES,
    Appearance,
    Rendition,
    appearance_of,
)
from .colors import (
    COLOR_OF_A_BACKGROUND,
    COLOR_OF_A_FOREGROUND,
    DEFAULT_COLOR,
    sgr_code_of,
    sgr_color,
    sgr_color_parameters,
)
from .sequences.rendition import ColorSpace, Sgr

__all__ = ["after_sgr", "erased_appearance", "parameters_of"]

#: `after_sgr`'s answers, by the rendition before and the parameters.
#: Shared by every screen: the answer depends on nothing else.
_SGR_RESULTS: dict[tuple[Rendition, tuple[int, ...]], Rendition] = {}


def after_sgr(rendition: Rendition, attrs_tuple: tuple[int, ...]) -> Rendition:
    "The rendition an SGR with these parameters leaves, from this one."
    key = (rendition, attrs_tuple)
    try:
        return _SGR_RESULTS[key]
    except KeyError:
        if len(_SGR_RESULTS) > 4096:
            _SGR_RESULTS.clear()
        answer = _SGR_RESULTS[key] = _computed(rendition, attrs_tuple)
        return answer


def _computed(rendition: Rendition, attrs_tuple: tuple[int, ...]) -> Rendition:
    """
    The rendition an SGR with these parameters leaves, from this one.

    It reads nothing else, so `after_sgr` keeps the answers: a program
    repaints with the same few sequences.
    """
    replace: dict[str, object] = {}

    attrs = [0] if not attrs_tuple else list(attrs_tuple[::-1])

    while attrs:
        attr = attrs.pop()

        # A parameter with colons in it arrives as a tuple, and
        # holds everything the colour needs.
        if isinstance(attr, tuple):
            if attr[0] in (Sgr.FOREGROUND, Sgr.BACKGROUND):
                color = sgr_color(list(attr))
                if color is not None:
                    replace["color" if attr[0] == Sgr.FOREGROUND else "bgcolor"] = color
            elif attr[0] == Sgr.UNDERLINE_COLOR:
                replace["underline_color"] = sgr_color(list(attr))
            elif attr[0] == Sgr.UNDERLINE:
                number = attr[1] if len(attr) > 1 else 1
                shape = UNDERLINE_SHAPES.get(number)
                if shape is not None:
                    replace["underline"] = number != 0
                    replace["underline_style"] = shape
            continue

        if attr in COLOR_OF_A_FOREGROUND:
            replace["color"] = COLOR_OF_A_FOREGROUND[attr]
        elif attr in COLOR_OF_A_BACKGROUND:
            replace["bgcolor"] = COLOR_OF_A_BACKGROUND[attr]
        elif attr == Sgr.BOLD:
            replace["bold"] = True
        elif attr == Sgr.DIM:
            replace["dim"] = True
        elif attr == Sgr.ITALIC:
            replace["italic"] = True
        elif attr == Sgr.UNDERLINE:
            replace["underline"] = True
            # A plain "4" draws a single line, whatever shape came
            # before it.
            replace["underline_style"] = ""
        elif attr == Sgr.BLINK:
            replace["blink"] = True
        elif attr == Sgr.RAPID_BLINK:
            replace["blink"] = True  # Fast blink.
        elif attr == Sgr.REVERSE:
            replace["reverse"] = True
        elif attr == Sgr.HIDDEN:
            replace["hidden"] = True
        elif attr == Sgr.STRIKE:
            replace["strike"] = True
        elif attr == Sgr.NOT_STRUCK:
            replace["strike"] = False
        # Where the glyph sits. A terminal draws a raised or a
        # lowered glyph smaller, and 75 puts it back on the line.
        elif attr == Sgr.SUPERSCRIPT:
            replace["baseline"] = "superscript"
        elif attr == Sgr.SUBSCRIPT:
            replace["baseline"] = "subscript"
        elif attr == Sgr.NEITHER_SCRIPT:
            replace["baseline"] = ""
        elif attr == Sgr.NORMAL_INTENSITY:
            replace["bold"] = False
            replace["dim"] = False
        elif attr == Sgr.NOT_ITALIC:
            replace["italic"] = False
        elif attr == Sgr.DOUBLE_UNDERLINE:
            replace["underline"] = True
            replace["underline_style"] = "double"
        elif attr == Sgr.NOT_UNDERLINED:
            # The colour of the line stays: a program that turns
            # the line on again writes no colour a second time.
            replace["underline"] = False
        elif attr == Sgr.NOT_BLINKING:
            replace["blink"] = False
        elif attr == Sgr.NOT_REVERSED:
            replace["reverse"] = False
        elif not attr:
            replace = {}
            rendition = PLAIN

        elif attr == Sgr.DEFAULT_UNDERLINE_COLOR:
            replace["underline_color"] = None
        elif attr in (Sgr.FOREGROUND, Sgr.BACKGROUND):
            # The colour follows in the parameters that come next.
            parameters = [attr]
            while attrs and len(parameters) < sgr_color_parameters(parameters):
                parameters.append(attrs.pop())
            color = sgr_color(parameters)
            if color is not None:
                replace["color" if attr == Sgr.FOREGROUND else "bgcolor"] = color

        elif attr == Sgr.UNDERLINE_COLOR:
            parameters = [attr]
            while attrs and len(parameters) < sgr_color_parameters(parameters):
                parameters.append(attrs.pop())
            replace["underline_color"] = sgr_color(parameters)

    return rendition._replace(**replace)  # type:ignore


def parameters_of(rendition: Rendition) -> str:
    """
    A rendition as SGR parameters, for a DECRQSS answer.

    A colour comes back the way the program named it. A number of
    the palette is a number, and a colour of its own is its three
    components. A program that probes for 24 bit colour reads its
    own colour back, which is the answer it looks for.

    One of the first sixteen comes back as the parameter that sets
    it: "31" and not "38;5;1". That is what libvterm answers, and
    its own test file says so ("t/26state_query.test", "DECRQSS on
    SGR ANSI colours"). A pane cannot tell "CSI 31 m" from
    "CSI 38;5;1 m" afterwards, because both leave the same colour,
    and either answer sets the colour back. So the shorter one, and
    the one the references write.

    "SGR 58" has no short form, so the colour of the underline is
    always a number or three components.
    """
    parts = ["0"]

    for flag, parameter in (
        (rendition.bold, "%d" % Sgr.BOLD),
        (rendition.dim, "%d" % Sgr.DIM),
        (rendition.italic, "%d" % Sgr.ITALIC),
        (
            rendition.underline,
            UNDERLINE_PARAMETERS[rendition.underline_style or ""],
        ),
        (rendition.blink, "%d" % Sgr.BLINK),
        (rendition.reverse, "%d" % Sgr.REVERSE),
        (rendition.hidden, "%d" % Sgr.HIDDEN),
        (rendition.strike, "%d" % Sgr.STRIKE),
        (
            rendition.baseline,
            BASELINE_PARAMETERS.get(rendition.baseline or "", ""),
        ),
    ):
        if flag:
            parts.append(parameter)

    for color, code, background in (
        (rendition.color, Sgr.FOREGROUND, False),
        (rendition.bgcolor, Sgr.BACKGROUND, True),
    ):
        # The default colour has a single code of its own, 39 and
        # 49, and this does not write it: the answer opens with "0",
        # which already says the default.
        if color is None or color == DEFAULT_COLOR:
            continue
        if color.index is not None:
            short = sgr_code_of(color.index, background)
            if short is not None:
                parts.append("%i" % short)
            else:
                parts.append("%i;%i;%i" % (code, ColorSpace.INDEXED, color.index))
        elif color.rgb is not None:
            parts.append("%i;%i;%i;%i;%i" % (code, ColorSpace.DIRECT, *color.rgb))

    underline_color = rendition.underline_color
    if rendition.underline and underline_color is not None:
        if underline_color.index is not None:
            parts.append("%i:%i:%i" % (Sgr.UNDERLINE_COLOR, ColorSpace.INDEXED, underline_color.index))
        elif underline_color.rgb is not None:
            parts.append("%i:%i::%i:%i:%i" % (Sgr.UNDERLINE_COLOR, ColorSpace.DIRECT, *underline_color.rgb))

    return ";".join(parts)


def erased_appearance(rendition: Rendition) -> Appearance | None:
    """
    How an erased cell is drawn, under this rendition.

    A terminal paints an erased cell with the background that is set
    now. xterm, kitty and tmux all do this, and programs count on
    it: htop draws the header of its table with "CSI K" and expects
    the colour to reach the end of the line.

    The background carries over, and the underline does not. Five
    judges take the underline off an erased cell and only kitty
    keeps it, for both ED and EL; the background is the other way
    round, five keeping it and only Ghostty dropping it.
    `test_the_panel.py` holds both tallies.

    Reverse video is a split, so it stays. kitty and WezTerm paint
    the cell; Alacritty, Ghostty, libvterm and xterm do not. Four to
    two is a choice and not a rule, and a program that reverses and
    then erases means the block to be seen.

    DCH and ICH read this style as well, and the panel splits there
    too. Ghostty and WezTerm colour a delete with nothing at all,
    not even the background, so they take no side. Of the five that
    do colour it, kitty and ptterm paint the reverse, libvterm keeps
    the foreground without it, and Alacritty and xterm keep only the
    background. Alacritty's `delete_chars_reset` reference test is
    that difference and nothing else: twelve cells at the end of one
    row.

    `None` means that nothing paints the cell, so the cell can go
    away instead, which keeps the screen sparse.

    A hyperlink is never part of it. An erase takes the content of
    a cell away, and a link that covers nothing is not a link.
    """

    if not rendition.reverse and not rendition.bgcolor:
        return None

    return appearance_of[
        PLAIN._replace(
            reverse=rendition.reverse,
            # Reverse video paints the cell with the foreground, so
            # that colour is part of an erase only then.
            color=rendition.color if rendition.reverse else None,
            bgcolor=rendition.bgcolor,
        ),
        "",
        "",
    ]
