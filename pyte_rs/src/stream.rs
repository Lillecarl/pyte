//! `pyte.streams._take_ground` in Rust: what the parser reads from its
//! ground state, read without the parser. It dispatches what the parser
//! would dispatch, through the same tables and in the same order, and it
//! hands back where it stopped wherever the parser has something to
//! decide: any other escape, a string sequence, a C1 control, a sequence
//! the data ends inside, a control inside a CSI sequence, a parameter that
//! is not ASCII or not small. It stops before such a sequence starts, so
//! the parser reads all of it and nothing is dispatched twice.
//! Lillecarl/pymux#570.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PySlice, PyString, PyStringData, PyTuple};

const ESC: u32 = 0x1b;
const CSI_C1: u32 = 0x9b;
const OSC_C1: u32 = 0x9d;
const NUL: u32 = 0x00;
const DEL: u32 = 0x7f;

/// The controls `Stream.basic` names: BEL, BS, HT, LF, VT, FF, CR, SO, SI.
fn is_basic(point: u32) -> bool {
    (0x07..=0x0f).contains(&point)
}

/// What the plain text pattern stops at.
fn is_special(point: u32) -> bool {
    is_basic(point) || matches!(point, ESC | CSI_C1 | NUL | DEL | OSC_C1)
}

fn point_at(data: &PyStringData<'_>, index: usize) -> Option<u32> {
    match data {
        PyStringData::Ucs1(units) => units.get(index).map(|&unit| u32::from(unit)),
        PyStringData::Ucs2(units) => units.get(index).map(|&unit| u32::from(unit)),
        PyStringData::Ucs4(units) => units.get(index).copied(),
    }
}

fn slice<'py>(
    text: &Bound<'py, PyString>,
    start: usize,
    end: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let py = text.py();
    text.as_any()
        .get_item(PySlice::new(py, start as isize, end as isize, 1))
}

/// A private marker as the parser keeps it: none, "?" (`True`), or the
/// markers it read, as a string.
enum Private {
    No,
    Question,
    Markers(String),
}

/// A parameter, as the parser hands it on.
enum Parameter {
    Empty,
    Number(i64),
    Sub(Vec<i64>),
}

/// The digits read so far, as the parser's `int(current)` reads them, or
/// `None` when there are too many for an `i64`: the parser takes those.
fn number(digits: &str) -> Option<i64> {
    if digits.len() > 18 {
        return None;
    }
    Some(digits.parse().unwrap_or(0))
}

/// One whole CSI sequence from `start`, the byte after "ESC [": its
/// parameters, its marker, its key and where it ends; `None` when the
/// parser has to read it.
fn csi_sequence(
    data: &PyStringData<'_>,
    start: usize,
) -> Option<(Vec<Parameter>, Private, String, usize)> {
    let mut params = Vec::new();
    let mut current = String::new();
    let mut subparams: Option<Vec<i64>> = None;
    let mut private = Private::No;
    let mut interm = String::new();
    let mut index = start;
    loop {
        let point = point_at(data, index)?;
        let character = char::from_u32(point).filter(char::is_ascii)?;
        match character {
            '?' => private = Private::Question,
            '<' | '=' | '>' => {
                private = match private {
                    Private::No => Private::Markers(character.to_string()),
                    Private::Question => Private::Markers(format!("?{character}")),
                    Private::Markers(mut markers) => {
                        markers.push(character);
                        Private::Markers(markers)
                    }
                }
            }
            '\u{20}'..='\u{2f}' => interm.push(character),
            '0'..='9' => current.push(character),
            ':' => {
                subparams
                    .get_or_insert_with(Vec::new)
                    .push(number(if current.is_empty() { "0" } else { &current })?);
                current.clear();
            }
            ';' => {
                match subparams.take() {
                    None if current.is_empty() => params.push(Parameter::Empty),
                    None => params.push(Parameter::Number(number(&current)?)),
                    Some(mut sub) => {
                        sub.push(number(if current.is_empty() { "0" } else { &current })?);
                        params.push(Parameter::Sub(sub));
                    }
                }
                current.clear();
            }
            '\u{40}'..='\u{7e}' => {
                match subparams.take() {
                    Some(mut sub) => {
                        sub.push(number(if current.is_empty() { "0" } else { &current })?);
                        params.push(Parameter::Sub(sub));
                    }
                    None if !current.is_empty() => {
                        params.push(Parameter::Number(number(&current)?))
                    }
                    None if !params.is_empty() => params.push(Parameter::Empty),
                    None => {}
                }
                interm.push(character);
                return Some((params, private, interm, index + 1));
            }
            // A control runs inside the sequence, CAN and SUB abort it,
            // and anything else ends it in a way only the parser knows.
            _ => return None,
        }
        index += 1;
    }
}

#[pyfunction]
pub fn take_ground<'py>(
    py: Python<'py>,
    text: &Bound<'py, PyString>,
    offset: usize,
    draw: &Bound<'py, PyAny>,
    basic: &Bound<'py, PyAny>,
    csi: &Bound<'py, PyAny>,
    define_charset: &Bound<'py, PyAny>,
) -> PyResult<usize> {
    // SAFETY: `text` is borrowed for the whole call, and a str is
    // immutable once made, so its storage stays where it is.
    let data = unsafe { text.data()? };
    let mut index = offset;
    while let Some(point) = point_at(&data, index) {
        if !is_special(point) {
            let mut end = index + 1;
            while point_at(&data, end).is_some_and(|point| !is_special(point)) {
                end += 1;
            }
            draw.call1((slice(text, index, end)?,))?;
            index = end;
        } else if is_basic(point) {
            let key = char::from_u32(point).map(String::from).unwrap_or_default();
            basic.get_item(key)?.call0()?;
            index += 1;
        } else if point == NUL || point == DEL {
            index += 1;
        } else if point == ESC {
            match point_at(&data, index + 1) {
                Some(0x5b) => {
                    let Some((params, private, key, end)) = csi_sequence(&data, index + 2) else {
                        return Ok(index);
                    };
                    let arguments = PyList::empty(py);
                    for param in params {
                        match param {
                            Parameter::Empty => arguments.append(py.None())?,
                            Parameter::Number(value) => arguments.append(value)?,
                            Parameter::Sub(values) => {
                                arguments.append(PyTuple::new(py, values)?)?
                            }
                        }
                    }
                    let arguments = arguments.to_tuple();
                    let handler = csi.get_item(key)?;
                    match private {
                        Private::No => handler.call1(arguments)?,
                        Private::Question => {
                            let keywords = PyDict::new(py);
                            keywords.set_item("private", true)?;
                            handler.call(arguments, Some(&keywords))?
                        }
                        Private::Markers(markers) => {
                            let keywords = PyDict::new(py);
                            keywords.set_item("private", markers)?;
                            handler.call(arguments, Some(&keywords))?
                        }
                    };
                    index = end;
                }
                // "ESC ( B" and its kin: G0 to G3. A name of two bytes
                // starts with "%", and the parser reads those.
                Some(0x28..=0x2b) => {
                    if define_charset.is_none() {
                        return Ok(index);
                    }
                    match point_at(&data, index + 2) {
                        Some(code) if code != 0x25 => {
                            let keywords = PyDict::new(py);
                            keywords.set_item("mode", slice(text, index + 1, index + 2)?)?;
                            define_charset
                                .call((slice(text, index + 2, index + 3)?,), Some(&keywords))?;
                            index += 3;
                        }
                        _ => return Ok(index),
                    }
                }
                _ => return Ok(index),
            }
        } else {
            return Ok(index);
        }
    }
    Ok(index)
}
