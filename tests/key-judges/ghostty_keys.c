/*
 * Ask Ghostty's key encoder what a key sends, through libghostty-vt.
 *
 * One process answers one request after another. A request is one
 * line of whitespace-separated fields, the same for every key judge
 * (`tests/key_panel.py` writes them):
 *
 *     name mods action flags cursor_keys char unshifted other_keys keypad
 *
 * - name: the key as kitty names it ("LEFT", "KP_0", "F13"), or "CHAR"
 *   for a key that writes a character;
 * - mods: kitty's modifier bits, shift 1 to num lock 128;
 * - action: "press", "repeat" or "release";
 * - flags: the kitty keyboard flags the pane pushed;
 * - cursor_keys, keypad: DECCKM and DECKPAM, 0 or 1;
 * - char: the code point the key types before ctrl or alt, or 0;
 * - unshifted: the code point of the key without shift, or 0;
 * - other_keys: the level of xterm's modifyOtherKeys, 0 to 3.
 *
 * The answer is "=" and the bytes in hex, or "?" for a key or a mode
 * Ghostty has no way to be asked about. That is an abstention, and
 * the panel counts it as one.
 *
 * Every option the request does not set comes from a fresh terminal
 * (`ghostty_key_encoder_setopt_from_terminal`), so the encoder runs
 * with Ghostty's own defaults and not with ones written here.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ghostty/vt.h>

/* kitty's modifier bits, which every request uses. */
enum {
  K_SHIFT = 1,
  K_ALT = 2,
  K_CTRL = 4,
  K_SUPER = 8,
  K_HYPER = 16,
  K_META = 32,
  K_CAPS = 64,
  K_NUM = 128,
};

typedef struct {
  const char *name;
  GhosttyKey key;
} Name;

/* kitty's names for the keys that write no character. A name that is
 * missing here is a key Ghostty does not have, such as F26 or hyper. */
static const Name NAMES[] = {
    {"ESCAPE", GHOSTTY_KEY_ESCAPE},
    {"ENTER", GHOSTTY_KEY_ENTER},
    {"TAB", GHOSTTY_KEY_TAB},
    {"BACKSPACE", GHOSTTY_KEY_BACKSPACE},
    {"INSERT", GHOSTTY_KEY_INSERT},
    {"DELETE", GHOSTTY_KEY_DELETE},
    {"LEFT", GHOSTTY_KEY_ARROW_LEFT},
    {"RIGHT", GHOSTTY_KEY_ARROW_RIGHT},
    {"UP", GHOSTTY_KEY_ARROW_UP},
    {"DOWN", GHOSTTY_KEY_ARROW_DOWN},
    {"PAGE_UP", GHOSTTY_KEY_PAGE_UP},
    {"PAGE_DOWN", GHOSTTY_KEY_PAGE_DOWN},
    {"HOME", GHOSTTY_KEY_HOME},
    {"END", GHOSTTY_KEY_END},
    {"CAPS_LOCK", GHOSTTY_KEY_CAPS_LOCK},
    {"SCROLL_LOCK", GHOSTTY_KEY_SCROLL_LOCK},
    {"NUM_LOCK", GHOSTTY_KEY_NUM_LOCK},
    {"PRINT_SCREEN", GHOSTTY_KEY_PRINT_SCREEN},
    {"PAUSE", GHOSTTY_KEY_PAUSE},
    {"MENU", GHOSTTY_KEY_CONTEXT_MENU},
    {"F1", GHOSTTY_KEY_F1},
    {"F2", GHOSTTY_KEY_F2},
    {"F3", GHOSTTY_KEY_F3},
    {"F4", GHOSTTY_KEY_F4},
    {"F5", GHOSTTY_KEY_F5},
    {"F6", GHOSTTY_KEY_F6},
    {"F7", GHOSTTY_KEY_F7},
    {"F8", GHOSTTY_KEY_F8},
    {"F9", GHOSTTY_KEY_F9},
    {"F10", GHOSTTY_KEY_F10},
    {"F11", GHOSTTY_KEY_F11},
    {"F12", GHOSTTY_KEY_F12},
    {"F13", GHOSTTY_KEY_F13},
    {"F14", GHOSTTY_KEY_F14},
    {"F15", GHOSTTY_KEY_F15},
    {"F16", GHOSTTY_KEY_F16},
    {"F17", GHOSTTY_KEY_F17},
    {"F18", GHOSTTY_KEY_F18},
    {"F19", GHOSTTY_KEY_F19},
    {"F20", GHOSTTY_KEY_F20},
    {"F21", GHOSTTY_KEY_F21},
    {"F22", GHOSTTY_KEY_F22},
    {"F23", GHOSTTY_KEY_F23},
    {"F24", GHOSTTY_KEY_F24},
    {"F25", GHOSTTY_KEY_F25},
    {"KP_0", GHOSTTY_KEY_NUMPAD_0},
    {"KP_1", GHOSTTY_KEY_NUMPAD_1},
    {"KP_2", GHOSTTY_KEY_NUMPAD_2},
    {"KP_3", GHOSTTY_KEY_NUMPAD_3},
    {"KP_4", GHOSTTY_KEY_NUMPAD_4},
    {"KP_5", GHOSTTY_KEY_NUMPAD_5},
    {"KP_6", GHOSTTY_KEY_NUMPAD_6},
    {"KP_7", GHOSTTY_KEY_NUMPAD_7},
    {"KP_8", GHOSTTY_KEY_NUMPAD_8},
    {"KP_9", GHOSTTY_KEY_NUMPAD_9},
    {"KP_DECIMAL", GHOSTTY_KEY_NUMPAD_DECIMAL},
    {"KP_DIVIDE", GHOSTTY_KEY_NUMPAD_DIVIDE},
    {"KP_MULTIPLY", GHOSTTY_KEY_NUMPAD_MULTIPLY},
    {"KP_SUBTRACT", GHOSTTY_KEY_NUMPAD_SUBTRACT},
    {"KP_ADD", GHOSTTY_KEY_NUMPAD_ADD},
    {"KP_ENTER", GHOSTTY_KEY_NUMPAD_ENTER},
    {"KP_EQUAL", GHOSTTY_KEY_NUMPAD_EQUAL},
    {"KP_SEPARATOR", GHOSTTY_KEY_NUMPAD_SEPARATOR},
    {"KP_LEFT", GHOSTTY_KEY_NUMPAD_LEFT},
    {"KP_RIGHT", GHOSTTY_KEY_NUMPAD_RIGHT},
    {"KP_UP", GHOSTTY_KEY_NUMPAD_UP},
    {"KP_DOWN", GHOSTTY_KEY_NUMPAD_DOWN},
    {"KP_PAGE_UP", GHOSTTY_KEY_NUMPAD_PAGE_UP},
    {"KP_PAGE_DOWN", GHOSTTY_KEY_NUMPAD_PAGE_DOWN},
    {"KP_HOME", GHOSTTY_KEY_NUMPAD_HOME},
    {"KP_END", GHOSTTY_KEY_NUMPAD_END},
    {"KP_INSERT", GHOSTTY_KEY_NUMPAD_INSERT},
    {"KP_DELETE", GHOSTTY_KEY_NUMPAD_DELETE},
    {"KP_BEGIN", GHOSTTY_KEY_NUMPAD_BEGIN},
    {"MEDIA_PLAY_PAUSE", GHOSTTY_KEY_MEDIA_PLAY_PAUSE},
    {"MEDIA_STOP", GHOSTTY_KEY_MEDIA_STOP},
    {"MEDIA_TRACK_NEXT", GHOSTTY_KEY_MEDIA_TRACK_NEXT},
    {"MEDIA_TRACK_PREVIOUS", GHOSTTY_KEY_MEDIA_TRACK_PREVIOUS},
    {"LOWER_VOLUME", GHOSTTY_KEY_AUDIO_VOLUME_DOWN},
    {"RAISE_VOLUME", GHOSTTY_KEY_AUDIO_VOLUME_UP},
    {"MUTE_VOLUME", GHOSTTY_KEY_AUDIO_VOLUME_MUTE},
    {"LEFT_SHIFT", GHOSTTY_KEY_SHIFT_LEFT},
    {"LEFT_CONTROL", GHOSTTY_KEY_CONTROL_LEFT},
    {"LEFT_ALT", GHOSTTY_KEY_ALT_LEFT},
    /* W3C's "Meta" is the key with the logo on it, which kitty calls
     * super. kitty's meta and hyper have no W3C code at all. */
    {"LEFT_SUPER", GHOSTTY_KEY_META_LEFT},
    {"RIGHT_SHIFT", GHOSTTY_KEY_SHIFT_RIGHT},
    {"RIGHT_CONTROL", GHOSTTY_KEY_CONTROL_RIGHT},
    {"RIGHT_ALT", GHOSTTY_KEY_ALT_RIGHT},
    {"RIGHT_SUPER", GHOSTTY_KEY_META_RIGHT},
};

/* The physical key that writes this character on a US layout. */
static GhosttyKey key_of_char(uint32_t c) {
  if (c >= 'a' && c <= 'z') return (GhosttyKey)(GHOSTTY_KEY_A + (c - 'a'));
  if (c >= '0' && c <= '9') return (GhosttyKey)(GHOSTTY_KEY_DIGIT_0 + (c - '0'));
  switch (c) {
    case ' ': return GHOSTTY_KEY_SPACE;
    case '[': return GHOSTTY_KEY_BRACKET_LEFT;
    case ']': return GHOSTTY_KEY_BRACKET_RIGHT;
    case '/': return GHOSTTY_KEY_SLASH;
    case '-': return GHOSTTY_KEY_MINUS;
    case '=': return GHOSTTY_KEY_EQUAL;
    case '\\': return GHOSTTY_KEY_BACKSLASH;
    case '`': return GHOSTTY_KEY_BACKQUOTE;
    case ',': return GHOSTTY_KEY_COMMA;
    case '.': return GHOSTTY_KEY_PERIOD;
    case ';': return GHOSTTY_KEY_SEMICOLON;
    case '\'': return GHOSTTY_KEY_QUOTE;
    default: return GHOSTTY_KEY_UNIDENTIFIED;
  }
}

static GhosttyKey key_of_name(const char *name) {
  for (size_t i = 0; i < sizeof(NAMES) / sizeof(NAMES[0]); i++) {
    if (strcmp(NAMES[i].name, name) == 0) return NAMES[i].key;
  }
  return GHOSTTY_KEY_UNIDENTIFIED;
}

/* Ghostty numbers the modifiers in an order of its own: ctrl is 2 and
 * alt is 4, where kitty has them the other way round. */
static GhosttyMods mods_of(unsigned kitty) {
  GhosttyMods mods = 0;
  if (kitty & K_SHIFT) mods |= GHOSTTY_MODS_SHIFT;
  if (kitty & K_CTRL) mods |= GHOSTTY_MODS_CTRL;
  if (kitty & K_ALT) mods |= GHOSTTY_MODS_ALT;
  if (kitty & K_SUPER) mods |= GHOSTTY_MODS_SUPER;
  if (kitty & K_CAPS) mods |= GHOSTTY_MODS_CAPS_LOCK;
  if (kitty & K_NUM) mods |= GHOSTTY_MODS_NUM_LOCK;
  return mods;
}

static size_t utf8_of(uint32_t c, char *out) {
  if (c < 0x80) {
    out[0] = (char)c;
    return 1;
  }
  if (c < 0x800) {
    out[0] = (char)(0xC0 | (c >> 6));
    out[1] = (char)(0x80 | (c & 0x3F));
    return 2;
  }
  if (c < 0x10000) {
    out[0] = (char)(0xE0 | (c >> 12));
    out[1] = (char)(0x80 | ((c >> 6) & 0x3F));
    out[2] = (char)(0x80 | (c & 0x3F));
    return 3;
  }
  out[0] = (char)(0xF0 | (c >> 18));
  out[1] = (char)(0x80 | ((c >> 12) & 0x3F));
  out[2] = (char)(0x80 | ((c >> 6) & 0x3F));
  out[3] = (char)(0x80 | (c & 0x3F));
  return 4;
}

static void answer(GhosttyKeyEncoder encoder, GhosttyTerminal terminal, const char *line) {
  char name[64], action[16];
  unsigned mods, flags, cursor_keys, character, unshifted, other_keys, keypad;
  if (sscanf(line, "%63s %u %15s %u %u %u %u %u %u", name, &mods, action, &flags, &cursor_keys, &character,
             &unshifted, &other_keys, &keypad)
      != 9) {
    printf("?\n");
    return;
  }
  GhosttyKey key = strcmp(name, "CHAR") == 0 ? key_of_char(unshifted ? unshifted : character) : key_of_name(name);
  /* Ghostty has one level of modifyOtherKeys, the second. */
  bool other_keys_level_known = other_keys == 0 || other_keys == 2;
  if (key == GHOSTTY_KEY_UNIDENTIFIED || mods & (K_HYPER | K_META) || !other_keys_level_known) {
    printf("?\n");
    return;
  }

  ghostty_key_encoder_setopt_from_terminal(encoder, terminal);
  bool cursor = cursor_keys != 0, pad = keypad != 0, state_2 = other_keys == 2;
  GhosttyKittyKeyFlags kitty_flags = (GhosttyKittyKeyFlags)flags;
  ghostty_key_encoder_setopt(encoder, GHOSTTY_KEY_ENCODER_OPT_CURSOR_KEY_APPLICATION, &cursor);
  ghostty_key_encoder_setopt(encoder, GHOSTTY_KEY_ENCODER_OPT_KEYPAD_KEY_APPLICATION, &pad);
  ghostty_key_encoder_setopt(encoder, GHOSTTY_KEY_ENCODER_OPT_MODIFY_OTHER_KEYS_STATE_2, &state_2);
  ghostty_key_encoder_setopt(encoder, GHOSTTY_KEY_ENCODER_OPT_KITTY_FLAGS, &kitty_flags);

  GhosttyKeyEvent event;
  if (ghostty_key_event_new(NULL, &event) != GHOSTTY_SUCCESS) {
    printf("?\n");
    return;
  }
  GhosttyKeyAction kind = GHOSTTY_KEY_ACTION_PRESS;
  if (strcmp(action, "repeat") == 0) kind = GHOSTTY_KEY_ACTION_REPEAT;
  if (strcmp(action, "release") == 0) kind = GHOSTTY_KEY_ACTION_RELEASE;
  ghostty_key_event_set_action(event, kind);
  ghostty_key_event_set_key(event, key);
  ghostty_key_event_set_mods(event, mods_of(mods));

  char text[8];
  if (character >= 0x20 && character != 0x7f) {
    size_t length = utf8_of(character, text);
    ghostty_key_event_set_utf8(event, text, length);
    ghostty_key_event_set_unshifted_codepoint(event, unshifted ? unshifted : character);
    /* Shift made the character when the character is not the key's own. */
    if (unshifted && unshifted != character && mods & K_SHIFT) {
      ghostty_key_event_set_consumed_mods(event, GHOSTTY_MODS_SHIFT);
    }
  }

  char out[128];
  size_t length = 0;
  GhosttyResult result = ghostty_key_encoder_encode(encoder, event, out, sizeof(out), &length);
  ghostty_key_event_free(event);
  if (result != GHOSTTY_SUCCESS) {
    printf("?\n");
    return;
  }
  putchar('=');
  for (size_t i = 0; i < length; i++) printf("%02x", (unsigned char)out[i]);
  putchar('\n');
}

int main(void) {
  GhosttyKeyEncoder encoder;
  GhosttyTerminal terminal;
  if (ghostty_key_encoder_new(NULL, &encoder) != GHOSTTY_SUCCESS
      || ghostty_terminal_new(NULL, &terminal, 80, 24) != GHOSTTY_SUCCESS) {
    fprintf(stderr, "ghostty-keys: cannot make an encoder\n");
    return 1;
  }
  char line[512];
  while (fgets(line, sizeof(line), stdin)) {
    answer(encoder, terminal, line);
    fflush(stdout);
  }
  ghostty_key_encoder_free(encoder);
  ghostty_terminal_free(terminal);
  return 0;
}
