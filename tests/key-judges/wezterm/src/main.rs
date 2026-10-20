//! Ask WezTerm's key encoders what a key sends.
//!
//! WezTerm has two, and the GUI picks between them the way this does
//! (`wezterm-gui/src/termwindow/keyevent.rs`): a pane that pushed a
//! kitty flag gets `wezterm_input_types::KeyEvent::encode_kitty`, and
//! every other pane gets termwiz's `KeyCode::encode`, which is also
//! where xterm's modifyOtherKeys lives.
//!
//! One request is one line, the same for every key judge
//! (`ghostty_keys.c` says what each field is):
//!
//! ```text
//! name mods action flags cursor_keys char unshifted other_keys keypad
//! ```
//!
//! The answer is `=` and the bytes in hex, or `?` for what WezTerm
//! cannot be asked about here:
//!
//! - a repeat to a pane that asked for the event types: the encoder
//!   knows a key going down and coming up, and nothing between;
//! - a key it reads from a raw event only, which this judge has none
//!   of: a modifier or lock key, a media key, F25 and up, Menu;
//! - DECKPAM, which termwiz does not read ("TODO: also respect
//!   self.application_keypad").

use std::io::{self, BufRead, Write};

use termwiz::input::{KeyCode as LegacyKey, KeyCodeEncodeModes, KeyboardEncoding};
use wezterm_input_types::{KeyCode, KeyEvent, KeyboardLedStatus, KittyKeyboardFlags, Modifiers};

const SHIFT: u32 = 1;
const ALT: u32 = 2;
const CTRL: u32 = 4;
const SUPER: u32 = 8;
const HYPER: u32 = 16;
const META: u32 = 32;
const CAPS_LOCK: u32 = 64;
const NUM_LOCK: u32 = 128;
const REPORT_EVENT_TYPES: u32 = 2;

struct Request {
    name: String,
    mods: u32,
    action: String,
    flags: u32,
    cursor_keys: bool,
    character: Option<char>,
    other_keys: u32,
    keypad: bool,
}

fn parse(line: &str) -> Option<Request> {
    let fields: Vec<&str> = line.split_whitespace().collect();
    if fields.len() != 9 {
        return None;
    }
    let number = |i: usize| fields[i].parse::<u32>().ok();
    let code = number(5)?;
    Some(Request {
        name: fields[0].to_string(),
        mods: number(1)?,
        action: fields[2].to_string(),
        flags: number(3)?,
        cursor_keys: number(4)? != 0,
        character: if code >= 0x20 && code != 0x7f { char::from_u32(code) } else { None },
        other_keys: number(7)?,
        keypad: number(8)? != 0,
    })
}

fn modifiers_of(mods: u32) -> Modifiers {
    let mut out = Modifiers::NONE;
    if mods & SHIFT != 0 {
        out |= Modifiers::SHIFT;
    }
    if mods & ALT != 0 {
        out |= Modifiers::ALT;
    }
    if mods & CTRL != 0 {
        out |= Modifiers::CTRL;
    }
    if mods & SUPER != 0 {
        out |= Modifiers::SUPER;
    }
    out
}

/// The key as the kitty encoder takes it, or None for one it needs a
/// raw event for.
fn kitty_key(request: &Request) -> Option<KeyCode> {
    let name = request.name.as_str();
    if name == "CHAR" {
        return request.character.map(KeyCode::Char);
    }
    if let Some(n) = name.strip_prefix('F').and_then(|n| n.parse::<u8>().ok()) {
        return (n <= 24).then_some(KeyCode::Function(n));
    }
    if let Some(n) = name.strip_prefix("KP_").and_then(|n| n.parse::<u8>().ok()) {
        return Some(KeyCode::Numpad(n));
    }
    Some(match name {
        "ESCAPE" => KeyCode::Char('\x1b'),
        "ENTER" => KeyCode::Char('\r'),
        "TAB" => KeyCode::Char('\t'),
        "BACKSPACE" => KeyCode::Char('\x08'),
        "DELETE" => KeyCode::Char('\x7f'),
        "INSERT" => KeyCode::Insert,
        "LEFT" => KeyCode::LeftArrow,
        "RIGHT" => KeyCode::RightArrow,
        "UP" => KeyCode::UpArrow,
        "DOWN" => KeyCode::DownArrow,
        "PAGE_UP" => KeyCode::PageUp,
        "PAGE_DOWN" => KeyCode::PageDown,
        "HOME" => KeyCode::Home,
        "END" => KeyCode::End,
        // The keypad without num lock: the key is the digit it is on,
        // and the LED says which of its two meanings it has.
        "KP_INSERT" => KeyCode::Numpad(0),
        "KP_END" => KeyCode::Numpad(1),
        "KP_DOWN" => KeyCode::Numpad(2),
        "KP_PAGE_DOWN" => KeyCode::Numpad(3),
        "KP_LEFT" => KeyCode::Numpad(4),
        "KP_BEGIN" => KeyCode::Numpad(5),
        "KP_RIGHT" => KeyCode::Numpad(6),
        "KP_HOME" => KeyCode::Numpad(7),
        "KP_UP" => KeyCode::Numpad(8),
        "KP_PAGE_UP" => KeyCode::Numpad(9),
        "KP_DECIMAL" => KeyCode::Decimal,
        "KP_DIVIDE" => KeyCode::Divide,
        "KP_MULTIPLY" => KeyCode::Multiply,
        "KP_SUBTRACT" => KeyCode::Subtract,
        "KP_ADD" => KeyCode::Add,
        _ => return None,
    })
}

/// The key as termwiz's legacy encoder takes it.
fn legacy_key(request: &Request) -> Option<LegacyKey> {
    let name = request.name.as_str();
    if name == "CHAR" {
        return request.character.map(LegacyKey::Char);
    }
    if let Some(n) = name.strip_prefix('F').and_then(|n| n.parse::<u8>().ok()) {
        return (n <= 24).then_some(LegacyKey::Function(n));
    }
    if name.starts_with("KP_") {
        // A keypad key that writes a character is that character to a
        // legacy pane, as the GUI hands it over.
        if let Some(c) = request.character {
            return Some(LegacyKey::Char(c));
        }
    }
    Some(match name {
        "ESCAPE" => LegacyKey::Escape,
        "ENTER" | "KP_ENTER" => LegacyKey::Enter,
        "TAB" => LegacyKey::Tab,
        "BACKSPACE" => LegacyKey::Backspace,
        "DELETE" | "KP_DELETE" => LegacyKey::Delete,
        "INSERT" | "KP_INSERT" => LegacyKey::Insert,
        "LEFT" | "KP_LEFT" => LegacyKey::LeftArrow,
        "RIGHT" | "KP_RIGHT" => LegacyKey::RightArrow,
        "UP" | "KP_UP" => LegacyKey::UpArrow,
        "DOWN" | "KP_DOWN" => LegacyKey::DownArrow,
        "PAGE_UP" => LegacyKey::PageUp,
        "PAGE_DOWN" => LegacyKey::PageDown,
        "HOME" => LegacyKey::Home,
        "END" => LegacyKey::End,
        "KP_HOME" => LegacyKey::KeyPadHome,
        "KP_END" => LegacyKey::KeyPadEnd,
        "KP_PAGE_UP" => LegacyKey::KeyPadPageUp,
        "KP_PAGE_DOWN" => LegacyKey::KeyPadPageDown,
        "KP_BEGIN" => LegacyKey::KeyPadBegin,
        _ => return None,
    })
}

fn answer(request: &Request) -> Option<String> {
    if request.mods & (HYPER | META) != 0 || request.keypad {
        return None;
    }
    let down = request.action != "release";
    if request.flags != 0 {
        if request.action == "repeat" && request.flags & REPORT_EVENT_TYPES != 0 {
            return None;
        }
        let mut leds = KeyboardLedStatus::empty();
        if request.mods & CAPS_LOCK != 0 {
            leds |= KeyboardLedStatus::CAPS_LOCK;
        }
        if request.mods & NUM_LOCK != 0 {
            leds |= KeyboardLedStatus::NUM_LOCK;
        }
        let event = KeyEvent {
            key: kitty_key(request)?,
            modifiers: modifiers_of(request.mods),
            leds,
            repeat_count: 1,
            key_is_down: down,
            raw: None,
        };
        let flags = KittyKeyboardFlags::from_bits_truncate(request.flags as u16);
        return Some(event.encode_kitty(flags));
    }
    let modes = KeyCodeEncodeModes {
        encoding: KeyboardEncoding::Xterm,
        application_cursor_keys: request.cursor_keys,
        newline_mode: false,
        modify_other_keys: (request.other_keys != 0).then_some(request.other_keys as i64),
    };
    legacy_key(request)?
        .encode(modifiers_of(request.mods), modes, down)
        .ok()
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let reply = match parse(&line).as_ref().and_then(answer) {
            Some(bytes) => {
                let hex: String = bytes.bytes().map(|b| format!("{b:02x}")).collect();
                format!("={hex}")
            }
            None => "?".to_string(),
        };
        if writeln!(stdout, "{reply}").and_then(|()| stdout.flush()).is_err() {
            break;
        }
    }
}
