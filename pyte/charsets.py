"""
pyte.charsets
~~~~~~~~~~~~~

This module defines ``G0`` and ``G1`` charset mappings the same way
they are defined for linux terminal, see
``linux/drivers/tty/consolemap.c`` @ http://git.kernel.org

.. note:: ``VT100_MAP`` and ``IBMPC_MAP`` come from linux kernel
          source and therefore are licensed under **GPL**.

``VT100_MAP`` differs from the kernel table at one position. The
kernel draws ``h`` as U+2591 LIGHT SHADE. The DEC special graphics
set puts the newline symbol there, and Alacritty, WezTerm,
libvterm, Ghostty and xterm.js all draw U+2424 SYMBOL FOR NEWLINE.
Only kitty keeps the shade. Five emulators against one is a rule
and not a choice, so this table follows the five.

:copyright: (c) 2011-2012 by Selectel.
:copyright: (c) 2012-2017 by pyte authors and contributors,
                see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

#: Latin1.
LAT1_MAP = "".join(map(chr, range(256)))

#: VT100 graphic character set.
VT100_MAP = "".join(
    chr(c)
    for c in [
        0x0000,
        0x0001,
        0x0002,
        0x0003,
        0x0004,
        0x0005,
        0x0006,
        0x0007,
        0x0008,
        0x0009,
        0x000A,
        0x000B,
        0x000C,
        0x000D,
        0x000E,
        0x000F,
        0x0010,
        0x0011,
        0x0012,
        0x0013,
        0x0014,
        0x0015,
        0x0016,
        0x0017,
        0x0018,
        0x0019,
        0x001A,
        0x001B,
        0x001C,
        0x001D,
        0x001E,
        0x001F,
        0x0020,
        0x0021,
        0x0022,
        0x0023,
        0x0024,
        0x0025,
        0x0026,
        0x0027,
        0x0028,
        0x0029,
        0x002A,
        0x2192,
        0x2190,
        0x2191,
        0x2193,
        0x002F,
        0x2588,
        0x0031,
        0x0032,
        0x0033,
        0x0034,
        0x0035,
        0x0036,
        0x0037,
        0x0038,
        0x0039,
        0x003A,
        0x003B,
        0x003C,
        0x003D,
        0x003E,
        0x003F,
        0x0040,
        0x0041,
        0x0042,
        0x0043,
        0x0044,
        0x0045,
        0x0046,
        0x0047,
        0x0048,
        0x0049,
        0x004A,
        0x004B,
        0x004C,
        0x004D,
        0x004E,
        0x004F,
        0x0050,
        0x0051,
        0x0052,
        0x0053,
        0x0054,
        0x0055,
        0x0056,
        0x0057,
        0x0058,
        0x0059,
        0x005A,
        0x005B,
        0x005C,
        0x005D,
        0x005E,
        0x00A0,
        0x25C6,
        0x2592,
        0x2409,
        0x240C,
        0x240D,
        0x240A,
        0x00B0,
        0x00B1,
        0x2424,
        0x240B,
        0x2518,
        0x2510,
        0x250C,
        0x2514,
        0x253C,
        0x23BA,
        0x23BB,
        0x2500,
        0x23BC,
        0x23BD,
        0x251C,
        0x2524,
        0x2534,
        0x252C,
        0x2502,
        0x2264,
        0x2265,
        0x03C0,
        0x2260,
        0x00A3,
        0x00B7,
        0x007F,
        0x0080,
        0x0081,
        0x0082,
        0x0083,
        0x0084,
        0x0085,
        0x0086,
        0x0087,
        0x0088,
        0x0089,
        0x008A,
        0x008B,
        0x008C,
        0x008D,
        0x008E,
        0x008F,
        0x0090,
        0x0091,
        0x0092,
        0x0093,
        0x0094,
        0x0095,
        0x0096,
        0x0097,
        0x0098,
        0x0099,
        0x009A,
        0x009B,
        0x009C,
        0x009D,
        0x009E,
        0x009F,
        0x00A0,
        0x00A1,
        0x00A2,
        0x00A3,
        0x00A4,
        0x00A5,
        0x00A6,
        0x00A7,
        0x00A8,
        0x00A9,
        0x00AA,
        0x00AB,
        0x00AC,
        0x00AD,
        0x00AE,
        0x00AF,
        0x00B0,
        0x00B1,
        0x00B2,
        0x00B3,
        0x00B4,
        0x00B5,
        0x00B6,
        0x00B7,
        0x00B8,
        0x00B9,
        0x00BA,
        0x00BB,
        0x00BC,
        0x00BD,
        0x00BE,
        0x00BF,
        0x00C0,
        0x00C1,
        0x00C2,
        0x00C3,
        0x00C4,
        0x00C5,
        0x00C6,
        0x00C7,
        0x00C8,
        0x00C9,
        0x00CA,
        0x00CB,
        0x00CC,
        0x00CD,
        0x00CE,
        0x00CF,
        0x00D0,
        0x00D1,
        0x00D2,
        0x00D3,
        0x00D4,
        0x00D5,
        0x00D6,
        0x00D7,
        0x00D8,
        0x00D9,
        0x00DA,
        0x00DB,
        0x00DC,
        0x00DD,
        0x00DE,
        0x00DF,
        0x00E0,
        0x00E1,
        0x00E2,
        0x00E3,
        0x00E4,
        0x00E5,
        0x00E6,
        0x00E7,
        0x00E8,
        0x00E9,
        0x00EA,
        0x00EB,
        0x00EC,
        0x00ED,
        0x00EE,
        0x00EF,
        0x00F0,
        0x00F1,
        0x00F2,
        0x00F3,
        0x00F4,
        0x00F5,
        0x00F6,
        0x00F7,
        0x00F8,
        0x00F9,
        0x00FA,
        0x00FB,
        0x00FC,
        0x00FD,
        0x00FE,
        0x00FF,
    ]
)

#: IBM Codepage 437.
IBMPC_MAP = "".join(
    chr(c)
    for c in [
        0x0000,
        0x263A,
        0x263B,
        0x2665,
        0x2666,
        0x2663,
        0x2660,
        0x2022,
        0x25D8,
        0x25CB,
        0x25D9,
        0x2642,
        0x2640,
        0x266A,
        0x266B,
        0x263C,
        0x25B6,
        0x25C0,
        0x2195,
        0x203C,
        0x00B6,
        0x00A7,
        0x25AC,
        0x21A8,
        0x2191,
        0x2193,
        0x2192,
        0x2190,
        0x221F,
        0x2194,
        0x25B2,
        0x25BC,
        0x0020,
        0x0021,
        0x0022,
        0x0023,
        0x0024,
        0x0025,
        0x0026,
        0x0027,
        0x0028,
        0x0029,
        0x002A,
        0x002B,
        0x002C,
        0x002D,
        0x002E,
        0x002F,
        0x0030,
        0x0031,
        0x0032,
        0x0033,
        0x0034,
        0x0035,
        0x0036,
        0x0037,
        0x0038,
        0x0039,
        0x003A,
        0x003B,
        0x003C,
        0x003D,
        0x003E,
        0x003F,
        0x0040,
        0x0041,
        0x0042,
        0x0043,
        0x0044,
        0x0045,
        0x0046,
        0x0047,
        0x0048,
        0x0049,
        0x004A,
        0x004B,
        0x004C,
        0x004D,
        0x004E,
        0x004F,
        0x0050,
        0x0051,
        0x0052,
        0x0053,
        0x0054,
        0x0055,
        0x0056,
        0x0057,
        0x0058,
        0x0059,
        0x005A,
        0x005B,
        0x005C,
        0x005D,
        0x005E,
        0x005F,
        0x0060,
        0x0061,
        0x0062,
        0x0063,
        0x0064,
        0x0065,
        0x0066,
        0x0067,
        0x0068,
        0x0069,
        0x006A,
        0x006B,
        0x006C,
        0x006D,
        0x006E,
        0x006F,
        0x0070,
        0x0071,
        0x0072,
        0x0073,
        0x0074,
        0x0075,
        0x0076,
        0x0077,
        0x0078,
        0x0079,
        0x007A,
        0x007B,
        0x007C,
        0x007D,
        0x007E,
        0x2302,
        0x00C7,
        0x00FC,
        0x00E9,
        0x00E2,
        0x00E4,
        0x00E0,
        0x00E5,
        0x00E7,
        0x00EA,
        0x00EB,
        0x00E8,
        0x00EF,
        0x00EE,
        0x00EC,
        0x00C4,
        0x00C5,
        0x00C9,
        0x00E6,
        0x00C6,
        0x00F4,
        0x00F6,
        0x00F2,
        0x00FB,
        0x00F9,
        0x00FF,
        0x00D6,
        0x00DC,
        0x00A2,
        0x00A3,
        0x00A5,
        0x20A7,
        0x0192,
        0x00E1,
        0x00ED,
        0x00F3,
        0x00FA,
        0x00F1,
        0x00D1,
        0x00AA,
        0x00BA,
        0x00BF,
        0x2310,
        0x00AC,
        0x00BD,
        0x00BC,
        0x00A1,
        0x00AB,
        0x00BB,
        0x2591,
        0x2592,
        0x2593,
        0x2502,
        0x2524,
        0x2561,
        0x2562,
        0x2556,
        0x2555,
        0x2563,
        0x2551,
        0x2557,
        0x255D,
        0x255C,
        0x255B,
        0x2510,
        0x2514,
        0x2534,
        0x252C,
        0x251C,
        0x2500,
        0x253C,
        0x255E,
        0x255F,
        0x255A,
        0x2554,
        0x2569,
        0x2566,
        0x2560,
        0x2550,
        0x256C,
        0x2567,
        0x2568,
        0x2564,
        0x2565,
        0x2559,
        0x2558,
        0x2552,
        0x2553,
        0x256B,
        0x256A,
        0x2518,
        0x250C,
        0x2588,
        0x2584,
        0x258C,
        0x2590,
        0x2580,
        0x03B1,
        0x00DF,
        0x0393,
        0x03C0,
        0x03A3,
        0x03C3,
        0x00B5,
        0x03C4,
        0x03A6,
        0x0398,
        0x03A9,
        0x03B4,
        0x221E,
        0x03C6,
        0x03B5,
        0x2229,
        0x2261,
        0x00B1,
        0x2265,
        0x2264,
        0x2320,
        0x2321,
        0x00F7,
        0x2248,
        0x00B0,
        0x2219,
        0x00B7,
        0x221A,
        0x207F,
        0x00B2,
        0x25A0,
        0x00A0,
    ]
)


#: VAX42 character set.
VAX42_MAP = "".join(
    chr(c)
    for c in [
        0x0000,
        0x263A,
        0x263B,
        0x2665,
        0x2666,
        0x2663,
        0x2660,
        0x2022,
        0x25D8,
        0x25CB,
        0x25D9,
        0x2642,
        0x2640,
        0x266A,
        0x266B,
        0x263C,
        0x25B6,
        0x25C0,
        0x2195,
        0x203C,
        0x00B6,
        0x00A7,
        0x25AC,
        0x21A8,
        0x2191,
        0x2193,
        0x2192,
        0x2190,
        0x221F,
        0x2194,
        0x25B2,
        0x25BC,
        0x0020,
        0x043B,
        0x0022,
        0x0023,
        0x0024,
        0x0025,
        0x0026,
        0x0027,
        0x0028,
        0x0029,
        0x002A,
        0x002B,
        0x002C,
        0x002D,
        0x002E,
        0x002F,
        0x0030,
        0x0031,
        0x0032,
        0x0033,
        0x0034,
        0x0035,
        0x0036,
        0x0037,
        0x0038,
        0x0039,
        0x003A,
        0x003B,
        0x003C,
        0x003D,
        0x003E,
        0x0435,
        0x0040,
        0x0041,
        0x0042,
        0x0043,
        0x0044,
        0x0045,
        0x0046,
        0x0047,
        0x0048,
        0x0049,
        0x004A,
        0x004B,
        0x004C,
        0x004D,
        0x004E,
        0x004F,
        0x0050,
        0x0051,
        0x0052,
        0x0053,
        0x0054,
        0x0055,
        0x0056,
        0x0057,
        0x0058,
        0x0059,
        0x005A,
        0x005B,
        0x005C,
        0x005D,
        0x005E,
        0x005F,
        0x0060,
        0x0441,
        0x0062,
        0x0063,
        0x0064,
        0x0065,
        0x0066,
        0x0067,
        0x0435,
        0x0069,
        0x006A,
        0x006B,
        0x006C,
        0x006D,
        0x006E,
        0x043A,
        0x0070,
        0x0071,
        0x0442,
        0x0073,
        0x043B,
        0x0435,
        0x0076,
        0x0077,
        0x0078,
        0x0079,
        0x007A,
        0x007B,
        0x007C,
        0x007D,
        0x007E,
        0x2302,
        0x00C7,
        0x00FC,
        0x00E9,
        0x00E2,
        0x00E4,
        0x00E0,
        0x00E5,
        0x00E7,
        0x00EA,
        0x00EB,
        0x00E8,
        0x00EF,
        0x00EE,
        0x00EC,
        0x00C4,
        0x00C5,
        0x00C9,
        0x00E6,
        0x00C6,
        0x00F4,
        0x00F6,
        0x00F2,
        0x00FB,
        0x00F9,
        0x00FF,
        0x00D6,
        0x00DC,
        0x00A2,
        0x00A3,
        0x00A5,
        0x20A7,
        0x0192,
        0x00E1,
        0x00ED,
        0x00F3,
        0x00FA,
        0x00F1,
        0x00D1,
        0x00AA,
        0x00BA,
        0x00BF,
        0x2310,
        0x00AC,
        0x00BD,
        0x00BC,
        0x00A1,
        0x00AB,
        0x00BB,
        0x2591,
        0x2592,
        0x2593,
        0x2502,
        0x2524,
        0x2561,
        0x2562,
        0x2556,
        0x2555,
        0x2563,
        0x2551,
        0x2557,
        0x255D,
        0x255C,
        0x255B,
        0x2510,
        0x2514,
        0x2534,
        0x252C,
        0x251C,
        0x2500,
        0x253C,
        0x255E,
        0x255F,
        0x255A,
        0x2554,
        0x2569,
        0x2566,
        0x2560,
        0x2550,
        0x256C,
        0x2567,
        0x2568,
        0x2564,
        0x2565,
        0x2559,
        0x2558,
        0x2552,
        0x2553,
        0x256B,
        0x256A,
        0x2518,
        0x250C,
        0x2588,
        0x2584,
        0x258C,
        0x2590,
        0x2580,
        0x03B1,
        0x00DF,
        0x0393,
        0x03C0,
        0x03A3,
        0x03C3,
        0x00B5,
        0x03C4,
        0x03A6,
        0x0398,
        0x03A9,
        0x03B4,
        0x221E,
        0x03C6,
        0x03B5,
        0x2229,
        0x2261,
        0x00B1,
        0x2265,
        0x2264,
        0x2320,
        0x2321,
        0x00F7,
        0x2248,
        0x00B0,
        0x2219,
        0x00B7,
        0x221A,
        0x207F,
        0x00B2,
        0x25A0,
        0x00A0,
    ]
)


#: The national replacement sets, and the one position each of them
#: moves.
#:
#: A national set is not a character set of its own. It is ASCII with
#: a handful of positions replaced by the letters one country needs,
#: which is what a seven bit terminal did instead of having an eighth
#: bit. So each entry below is only the positions that move.
#:
#: The tables come from xterm's `charsets.h`, the `map_NRCS_*` macros,
#: read in the direction `xtermCharSetOut` reads them: the position a
#: program writes, and the character it draws. Only the sets a VT320
#: had are here -- the VT5xx sets (Greek, Hebrew, Russian,
#: Serbo-Croatian, Turkish) are not, and neither is any 96 character
#: supplemental set.
NATIONAL = {
    #: British. The one position that made "#" a pound sign.
    "A": {0x23: 0x00A3},
    #: Dutch.
    "4": {
        0x23: 0x00A3,  # POUND SIGN
        0x40: 0x00BE,  # VULGAR FRACTION THREE QUARTERS
        0x5B: 0x0133,  # LATIN SMALL LIGATURE IJ
        0x5C: 0x00BD,  # VULGAR FRACTION ONE HALF
        0x5D: 0x007C,  # VERTICAL LINE
        0x7B: 0x00A8,  # DIAERESIS
        0x7C: 0x0192,  # LATIN SMALL LETTER F WITH HOOK
        0x7D: 0x00BC,  # VULGAR FRACTION ONE QUARTER
        0x7E: 0x00B4,  # ACUTE ACCENT
    },
    #: Finnish.
    "5": {
        0x5B: 0x00C4,  # LATIN CAPITAL LETTER A WITH DIAERESIS
        0x5C: 0x00D6,  # LATIN CAPITAL LETTER O WITH DIAERESIS
        0x5D: 0x00C5,  # LATIN CAPITAL LETTER A WITH RING ABOVE
        0x5E: 0x00DC,  # LATIN CAPITAL LETTER U WITH DIAERESIS
        0x60: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x7B: 0x00E4,  # LATIN SMALL LETTER A WITH DIAERESIS
        0x7C: 0x00F6,  # LATIN SMALL LETTER O WITH DIAERESIS
        0x7D: 0x00E5,  # LATIN SMALL LETTER A WITH RING ABOVE
        0x7E: 0x00FC,  # LATIN SMALL LETTER U WITH DIAERESIS
    },
    #: French.
    "R": {
        0x23: 0x00A3,  # POUND SIGN
        0x40: 0x00E0,  # LATIN SMALL LETTER A WITH GRAVE
        0x5B: 0x00B0,  # DEGREE SIGN
        0x5C: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
        0x5D: 0x00A7,  # SECTION SIGN
        0x7B: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x7C: 0x00F9,  # LATIN SMALL LETTER U WITH GRAVE
        0x7D: 0x00E8,  # LATIN SMALL LETTER E WITH GRAVE
        0x7E: 0x00A8,  # DIAERESIS
    },
    #: French Canadian.
    "Q": {
        0x40: 0x00E0,  # LATIN SMALL LETTER A WITH GRAVE
        0x5B: 0x00E2,  # LATIN SMALL LETTER A WITH CIRCUMFLEX
        0x5C: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
        0x5D: 0x00EA,  # LATIN SMALL LETTER E WITH CIRCUMFLEX
        0x5E: 0x00EE,  # LATIN SMALL LETTER I WITH CIRCUMFLEX
        0x60: 0x00F4,  # LATIN SMALL LETTER O WITH CIRCUMFLEX
        0x7B: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x7C: 0x00F9,  # LATIN SMALL LETTER U WITH GRAVE
        0x7D: 0x00E8,  # LATIN SMALL LETTER E WITH GRAVE
        0x7E: 0x00FB,  # LATIN SMALL LETTER U WITH CIRCUMFLEX
    },
    #: German.
    "K": {
        0x40: 0x00A7,  # SECTION SIGN
        0x5B: 0x00C4,  # LATIN CAPITAL LETTER A WITH DIAERESIS
        0x5C: 0x00D6,  # LATIN CAPITAL LETTER O WITH DIAERESIS
        0x5D: 0x00DC,  # LATIN CAPITAL LETTER U WITH DIAERESIS
        0x7B: 0x00E4,  # LATIN SMALL LETTER A WITH DIAERESIS
        0x7C: 0x00F6,  # LATIN SMALL LETTER O WITH DIAERESIS
        0x7D: 0x00FC,  # LATIN SMALL LETTER U WITH DIAERESIS
        0x7E: 0x00DF,  # LATIN SMALL LETTER SHARP S
    },
    #: Italian.
    "Y": {
        0x23: 0x00A3,  # POUND SIGN
        0x40: 0x00A7,  # SECTION SIGN
        0x5B: 0x00B0,  # DEGREE SIGN
        0x5C: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
        0x5D: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x60: 0x00F9,  # LATIN SMALL LETTER U WITH GRAVE
        0x7B: 0x00E0,  # LATIN SMALL LETTER A WITH GRAVE
        0x7C: 0x00F2,  # LATIN SMALL LETTER O WITH GRAVE
        0x7D: 0x00E8,  # LATIN SMALL LETTER E WITH GRAVE
        0x7E: 0x00EC,  # LATIN SMALL LETTER I WITH GRAVE
    },
    #: Norwegian and Danish.
    "`": {
        0x40: 0x00C4,  # LATIN CAPITAL LETTER A WITH DIAERESIS
        0x5B: 0x00C6,  # LATIN CAPITAL LETTER AE
        0x5C: 0x00D8,  # LATIN CAPITAL LETTER O WITH STROKE
        0x5D: 0x00C5,  # LATIN CAPITAL LETTER A WITH RING ABOVE
        0x5E: 0x00DC,  # LATIN CAPITAL LETTER U WITH DIAERESIS
        0x60: 0x00E4,  # LATIN SMALL LETTER A WITH DIAERESIS
        0x7B: 0x00E6,  # LATIN SMALL LETTER AE
        0x7C: 0x00F8,  # LATIN SMALL LETTER O WITH STROKE
        0x7D: 0x00E5,  # LATIN SMALL LETTER A WITH RING ABOVE
        0x7E: 0x00FC,  # LATIN SMALL LETTER U WITH DIAERESIS
    },
    #: Portuguese. The only one of these whose name is two bytes.
    "%6": {
        0x5B: 0x00C3,  # LATIN CAPITAL LETTER A WITH TILDE
        0x5C: 0x00C7,  # LATIN CAPITAL LETTER C WITH CEDILLA
        0x5D: 0x00D5,  # LATIN CAPITAL LETTER O WITH TILDE
        0x7B: 0x00E3,  # LATIN SMALL LETTER A WITH TILDE
        0x7C: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
        0x7D: 0x00F5,  # LATIN SMALL LETTER O WITH TILDE
    },
    #: Spanish.
    "Z": {
        0x23: 0x00A3,  # POUND SIGN
        0x40: 0x00A7,  # SECTION SIGN
        0x5B: 0x00A1,  # INVERTED EXCLAMATION MARK
        0x5C: 0x00D1,  # LATIN CAPITAL LETTER N WITH TILDE
        0x5D: 0x00BF,  # INVERTED QUESTION MARK
        0x7B: 0x00B0,  # DEGREE SIGN
        0x7C: 0x00F1,  # LATIN SMALL LETTER N WITH TILDE
        0x7D: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
    },
    #: Swedish.
    "7": {
        0x40: 0x00C9,  # LATIN CAPITAL LETTER E WITH ACUTE
        0x5B: 0x00C4,  # LATIN CAPITAL LETTER A WITH DIAERESIS
        0x5C: 0x00D6,  # LATIN CAPITAL LETTER O WITH DIAERESIS
        0x5D: 0x00C5,  # LATIN CAPITAL LETTER A WITH RING ABOVE
        0x5E: 0x00DC,  # LATIN CAPITAL LETTER U WITH DIAERESIS
        0x60: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x7B: 0x00E4,  # LATIN SMALL LETTER A WITH DIAERESIS
        0x7C: 0x00F6,  # LATIN SMALL LETTER O WITH DIAERESIS
        0x7D: 0x00E5,  # LATIN SMALL LETTER A WITH RING ABOVE
        0x7E: 0x00FC,  # LATIN SMALL LETTER U WITH DIAERESIS
    },
    #: Swiss.
    "=": {
        0x23: 0x00F9,  # LATIN SMALL LETTER U WITH GRAVE
        0x40: 0x00E0,  # LATIN SMALL LETTER A WITH GRAVE
        0x5B: 0x00E9,  # LATIN SMALL LETTER E WITH ACUTE
        0x5C: 0x00E7,  # LATIN SMALL LETTER C WITH CEDILLA
        0x5D: 0x00EA,  # LATIN SMALL LETTER E WITH CIRCUMFLEX
        0x5E: 0x00EE,  # LATIN SMALL LETTER I WITH CIRCUMFLEX
        0x5F: 0x00E8,  # LATIN SMALL LETTER E WITH GRAVE
        0x60: 0x00F4,  # LATIN SMALL LETTER O WITH CIRCUMFLEX
        0x7B: 0x00E4,  # LATIN SMALL LETTER A WITH DIAERESIS
        0x7C: 0x00F6,  # LATIN SMALL LETTER O WITH DIAERESIS
        0x7D: 0x00FC,  # LATIN SMALL LETTER U WITH DIAERESIS
        0x7E: 0x00FB,  # LATIN SMALL LETTER U WITH CIRCUMFLEX
    },
}

#: The names a terminal answers to for the same national set.
#:
#: DEC gave several of these two or three names over the models that
#: had them, and a program written for one model uses the name it
#: knew. xterm takes all of them, so this does.
NATIONAL_ALIASES = {
    "C": "5",  # Finnish
    "f": "R",  # French
    "9": "Q",  # French Canadian
    "E": "`",  # Norwegian and Danish
    "6": "`",  # Norwegian and Danish
    "H": "7",  # Swedish
}

#: The DEC technical set, `ESC ( >`: mathematics, and the pieces a
#: terminal drew a large bracket or a large sigma out of.
#:
#: From `map_DEC_Technical` in xterm's `charsets.h`. **Thirteen
#: positions are missing on purpose.** 0x31 to 0x37 are the seven
#: pieces of a large sigma and 0x38 to 0x3B, 0x52, 0x54, 0x55, 0x6D
#: and 0x75 are undefined; Unicode has no character for a sigma piece,
#: and xterm draws them from its own private area. A position that is
#: not here draws what ASCII draws.
TECHNICAL = {
    0x21: 0x23B7,  # RADICAL SYMBOL BOTTOM
    0x22: 0x250C,  # BOX DRAWINGS LIGHT DOWN AND RIGHT
    0x23: 0x2500,  # BOX DRAWINGS LIGHT HORIZONTAL
    0x24: 0x2320,  # TOP HALF INTEGRAL
    0x25: 0x2321,  # BOTTOM HALF INTEGRAL
    0x26: 0x2502,  # BOX DRAWINGS LIGHT VERTICAL
    0x27: 0x23A1,  # LEFT SQUARE BRACKET UPPER CORNER
    0x28: 0x23A3,  # LEFT SQUARE BRACKET LOWER CORNER
    0x29: 0x23A4,  # RIGHT SQUARE BRACKET UPPER CORNER
    0x2A: 0x23A6,  # RIGHT SQUARE BRACKET LOWER CORNER
    0x2B: 0x23A7,  # LEFT CURLY BRACKET UPPER HOOK
    0x2C: 0x23A9,  # LEFT CURLY BRACKET LOWER HOOK
    0x2D: 0x23AB,  # RIGHT CURLY BRACKET UPPER HOOK
    0x2E: 0x23AD,  # RIGHT CURLY BRACKET LOWER HOOK
    0x2F: 0x23A8,  # LEFT CURLY BRACKET MIDDLE PIECE
    0x30: 0x23AC,  # RIGHT CURLY BRACKET MIDDLE PIECE
    0x3C: 0x2264,  # LESS-THAN OR EQUAL TO
    0x3D: 0x2260,  # NOT EQUAL TO
    0x3E: 0x2265,  # GREATER-THAN OR EQUAL TO
    0x3F: 0x222B,  # INTEGRAL
    0x40: 0x2234,  # THEREFORE
    0x41: 0x221D,  # PROPORTIONAL TO
    0x42: 0x221E,  # INFINITY
    0x43: 0x00F7,  # DIVISION SIGN
    0x44: 0x0394,  # GREEK CAPITAL LETTER DELTA
    0x45: 0x2207,  # NABLA
    0x46: 0x03A6,  # GREEK CAPITAL LETTER PHI
    0x47: 0x0393,  # GREEK CAPITAL LETTER GAMMA
    0x48: 0x223C,  # TILDE OPERATOR
    0x49: 0x2243,  # ASYMPTOTICALLY EQUAL TO
    0x4A: 0x0398,  # GREEK CAPITAL LETTER THETA
    0x4B: 0x00D7,  # MULTIPLICATION SIGN
    0x4C: 0x039B,  # GREEK CAPITAL LETTER LAMDA
    0x4D: 0x21D4,  # LEFT RIGHT DOUBLE ARROW
    0x4E: 0x21D2,  # RIGHTWARDS DOUBLE ARROW
    0x4F: 0x2261,  # IDENTICAL TO
    0x50: 0x03A0,  # GREEK CAPITAL LETTER PI
    0x51: 0x03A8,  # GREEK CAPITAL LETTER PSI
    0x53: 0x03A3,  # GREEK CAPITAL LETTER SIGMA
    0x56: 0x221A,  # SQUARE ROOT
    0x57: 0x03A9,  # GREEK CAPITAL LETTER OMEGA
    0x58: 0x039E,  # GREEK CAPITAL LETTER XI
    0x59: 0x03A5,  # GREEK CAPITAL LETTER UPSILON
    0x5A: 0x2282,  # SUBSET OF
    0x5B: 0x2283,  # SUPERSET OF
    0x5C: 0x2229,  # INTERSECTION
    0x5D: 0x222A,  # UNION
    0x5E: 0x2227,  # LOGICAL AND
    0x5F: 0x2228,  # LOGICAL OR
    0x60: 0x00AC,  # NOT SIGN
    0x61: 0x03B1,  # GREEK SMALL LETTER ALPHA
    0x62: 0x03B2,  # GREEK SMALL LETTER BETA
    0x63: 0x03C7,  # GREEK SMALL LETTER CHI
    0x64: 0x03B4,  # GREEK SMALL LETTER DELTA
    0x65: 0x03B5,  # GREEK SMALL LETTER EPSILON
    0x66: 0x03C6,  # GREEK SMALL LETTER PHI
    0x67: 0x03B3,  # GREEK SMALL LETTER GAMMA
    0x68: 0x03B7,  # GREEK SMALL LETTER ETA
    0x69: 0x03B9,  # GREEK SMALL LETTER IOTA
    0x6A: 0x03B8,  # GREEK SMALL LETTER THETA
    0x6B: 0x03BA,  # GREEK SMALL LETTER KAPPA
    0x6C: 0x03BB,  # GREEK SMALL LETTER LAMDA
    0x6E: 0x03BD,  # GREEK SMALL LETTER NU
    0x6F: 0x2202,  # PARTIAL DIFFERENTIAL
    0x70: 0x03C0,  # GREEK SMALL LETTER PI
    0x71: 0x03C8,  # GREEK SMALL LETTER PSI
    0x72: 0x03C1,  # GREEK SMALL LETTER RHO
    0x73: 0x03C3,  # GREEK SMALL LETTER SIGMA
    0x74: 0x03C4,  # GREEK SMALL LETTER TAU
    0x76: 0x0192,  # LATIN SMALL LETTER F WITH HOOK
    0x77: 0x03C9,  # GREEK SMALL LETTER OMEGA
    0x78: 0x03BE,  # GREEK SMALL LETTER XI
    0x79: 0x03C5,  # GREEK SMALL LETTER UPSILON
    0x7A: 0x03B6,  # GREEK SMALL LETTER ZETA
    0x7B: 0x2190,  # LEFTWARDS ARROW
    0x7C: 0x2191,  # UPWARDS ARROW
    0x7D: 0x2192,  # RIGHTWARDS ARROW
    0x7E: 0x2193,  # DOWNWARDS ARROW
}


def _latin1_with(replacements: dict) -> str:
    "Latin-1, with the positions this set moves put somewhere else."
    table = list(LAT1_MAP)
    for position, codepoint in replacements.items():
        table[position] = chr(codepoint)
    return "".join(table)


MAPS = {"B": LAT1_MAP, "0": VT100_MAP, "U": IBMPC_MAP, "V": VAX42_MAP}

MAPS.update(
    {name: _latin1_with(replacements) for name, replacements in NATIONAL.items()}
)
MAPS.update({alias: MAPS[name] for alias, name in NATIONAL_ALIASES.items()})
MAPS[">"] = _latin1_with(TECHNICAL)
