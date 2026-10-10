//! Rust kernels for pyte's per-cell loops. `python/pyte_rs/__init__.py`
//! says how they are put in place; each one gives the answer its Python
//! original gives, decision for decision. Lillecarl/pymux#566.

mod row;
mod stream;

use pyo3::intern;
use pyo3::prelude::*;

use crate::row::{Row, RowImage};
use pyo3::types::{PyDict, PyList, PyString, PyStringData, PyTuple};

/// One run while it is built. `text` is the run's own characters for a
/// plain run, and the cell's original string for one that stands alone.
struct Run<'py> {
    start: i64,
    end: i64,
    text: RunText<'py>,
    appearance: Bound<'py, PyAny>,
    written: bool,
    plain: bool,
    blank: bool,
}

enum RunText<'py> {
    Built(String),
    Cell(Bound<'py, PyString>),
}

/// Python's `" " <= s <= "~"` on a whole string: code point order, which
/// is the byte order of UTF-8.
fn printable_ascii(s: &str) -> bool {
    (" "..="~").contains(&s)
}

/// `pyte.runs.runs_of`: the runs of one row, by column.
#[pyfunction]
fn runs_of<'py>(
    py: Python<'py>,
    row: &Bound<'py, PyAny>,
    run_class: &Bound<'py, PyAny>,
    placeholder: &str,
    new_run: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyList>> {
    let char_name = intern!(py, "char");
    let appearance_name = intern!(py, "appearance");
    let written_name = intern!(py, "written");
    let width_name = intern!(py, "width");

    // A Rust row holds its cells in column order already; a dict holds
    // them in the order they were written.
    let cells: Vec<(i64, Bound<'py, PyAny>)> = if let Ok(stored) = row.cast::<Row>() {
        stored
            .borrow()
            .columns()
            .map(|(column, cell)| (column, cell.bind(py).clone()))
            .collect()
    } else {
        let row = row.cast::<PyDict>()?;
        let mut cells = Vec::with_capacity(row.len());
        let mut sorted = true;
        let mut previous = i64::MIN;
        for (column, cell) in row.iter() {
            let column: i64 = column.extract()?;
            if column < previous {
                sorted = false;
            }
            previous = column;
            cells.push((column, cell));
        }
        if !sorted {
            cells.sort_by_key(|(column, _)| *column);
        }
        cells
    };

    let mut runs: Vec<Run<'py>> = Vec::new();
    let mut start: i64 = 0;
    let mut end: i64 = 0;
    let mut text: Option<String> = None;
    let mut appearance: Option<Bound<'py, PyAny>> = None;
    let mut written = false;
    let mut blank = true;

    for (column, cell) in cells {
        let char_object = cell.getattr(char_name)?;
        let char_string = char_object.cast::<PyString>()?;
        let ch = char_string.to_str()?;
        let cell_appearance = cell.getattr(appearance_name)?;
        let cell_written: bool = cell.getattr(written_name)?.extract()?;
        let width: i64 = cell.getattr(width_name)?.extract()?;
        let same_appearance = appearance
            .as_ref()
            .is_some_and(|open| open.is(&cell_appearance));

        // The common cell: printable ASCII, one column, beside the last
        // one and drawn the same way.
        if let Some(open) = text.as_mut()
            && column == end
            && same_appearance
            && cell_written == written
            && printable_ascii(ch)
            && width == 1
        {
            if blank && ch != " " {
                blank = false;
            }
            open.push_str(ch);
            end += 1;
            continue;
        }
        // The empty second half of a wide character.
        if ch.is_empty() {
            continue;
        }
        let char_plain = if printable_ascii(ch) {
            true
        } else if ch < " " || ch == "\x7f" {
            false
        } else {
            !ch.starts_with(placeholder)
        };
        let char_blank = ch == " ";
        if let Some(open) = text.as_mut()
            && column == end
            && same_appearance
            && cell_written == written
            && width == 1
            && char_plain
        {
            if !char_blank {
                blank = false;
            }
            open.push_str(ch);
            end = column + 1;
            continue;
        }
        if let Some(open) = text.take() {
            runs.push(Run {
                start,
                end,
                text: RunText::Built(open),
                appearance: appearance.take().unwrap(),
                written,
                plain: true,
                blank,
            });
        }
        if width == 1 && char_plain {
            start = column;
            end = column + 1;
            text = Some(ch.to_owned());
            appearance = Some(cell_appearance);
            written = cell_written;
            blank = char_blank;
        } else {
            runs.push(Run {
                start: column,
                end: column + width,
                text: RunText::Cell(char_string.clone()),
                appearance: cell_appearance,
                written: cell_written,
                plain: false,
                blank: false,
            });
        }
    }
    if let Some(open) = text.take() {
        runs.push(Run {
            start,
            end,
            text: RunText::Built(open),
            appearance: appearance.take().unwrap(),
            written,
            plain: true,
            blank,
        });
    }

    // The run at the end gives up its trailing blanks. The cut counts
    // code points, as `len` does.
    let mut tail: Option<Run<'py>> = None;
    if let Some(last) = runs.last_mut() {
        if last.plain && !last.blank {
            if let RunText::Built(whole) = &last.text {
                let stripped = whole.trim_end_matches(' ');
                if !stripped.is_empty() && stripped.len() != whole.len() {
                    let cut = stripped.chars().count() as i64;
                    let rest = whole[stripped.len()..].to_owned();
                    let kept = stripped.to_owned();
                    tail = Some(Run {
                        start: last.start + cut,
                        end: last.end,
                        text: RunText::Built(rest),
                        appearance: last.appearance.clone(),
                        written: last.written,
                        plain: true,
                        blank: true,
                    });
                    last.end = last.start + cut;
                    last.text = RunText::Built(kept);
                }
            }
        }
    }
    runs.extend(tail);

    let made = PyList::empty(py);
    for run in runs {
        let text = match run.text {
            RunText::Built(text) => PyString::new(py, &text),
            RunText::Cell(text) => text,
        };
        let fields = PyTuple::new(
            py,
            [
                run.start.into_pyobject(py)?.into_any(),
                run.end.into_pyobject(py)?.into_any(),
                text.into_any(),
                run.appearance,
                pyo3::types::PyBool::new(py, run.written)
                    .to_owned()
                    .into_any(),
                pyo3::types::PyBool::new(py, run.plain)
                    .to_owned()
                    .into_any(),
                pyo3::types::PyBool::new(py, run.blank)
                    .to_owned()
                    .into_any(),
            ],
        )?;
        made.append(new_run.call1((run_class, fields))?)?;
    }
    Ok(made)
}

/// The code point at `index` of a string's own storage, which is what
/// Python's `text[index]` reads: a lone surrogate is a code point too.
fn point_at(data: &PyStringData<'_>, index: usize) -> Option<u32> {
    match data {
        PyStringData::Ucs1(units) => units.get(index).map(|&unit| u32::from(unit)),
        PyStringData::Ucs2(units) => units.get(index).map(|&unit| u32::from(unit)),
        PyStringData::Ucs4(units) => units.get(index).copied(),
    }
}

/// `text[index]` as a key, without a call into Python unless the code
/// point is a surrogate, which no Rust `char` can hold.
fn key_at<'py>(
    py: Python<'py>,
    text: &Bound<'py, PyString>,
    index: usize,
    point: u32,
    buffer: &mut [u8; 4],
) -> PyResult<Bound<'py, PyString>> {
    match char::from_u32(point) {
        Some(character) => Ok(PyString::new(py, character.encode_utf8(buffer))),
        None => Ok(text.get_item(index)?.cast_into::<PyString>()?),
    }
}

/// `pyte.screen._draw_on_row`: draw the common run of `chars` from
/// `index` into `row` from column `x`.
#[pyfunction]
fn draw_on_row<'py>(
    py: Python<'py>,
    row: &Bound<'py, PyAny>,
    mut x: i64,
    chars: &Bound<'py, PyString>,
    mut index: usize,
    edge: i64,
    cells: &Bound<'py, PyDict>,
) -> PyResult<(i64, usize, bool)> {
    // SAFETY: `chars` is borrowed for the whole call, and a str is
    // immutable once made, so its storage stays where it is.
    let data = unsafe { chars.data()? };
    let width_name = intern!(py, "width");
    let mut changed = false;
    let mut buffer = [0u8; 4];
    while x < edge {
        let Some(point) = point_at(&data, index) else {
            break;
        };
        let key = key_at(py, chars, index, point, &mut buffer)?;
        let Some(cell) = cells.get_item(&key)? else {
            break;
        };
        let width: i64 = cell.getattr(width_name)?.extract()?;
        if width != 1 {
            break;
        }
        if let Ok(stored) = row.cast::<Row>() {
            let mut stored = stored.borrow_mut();
            if !stored
                .cell(x)
                .is_some_and(|there| there.as_ptr() == cell.as_ptr())
            {
                stored.store(x, cell.unbind());
                changed = true;
            }
        } else {
            let row = row.cast::<PyDict>()?;
            if !row.get_item(x)?.is_some_and(|there| there.is(&cell)) {
                row.set_item(x, &cell)?;
                changed = true;
            }
        }
        x += 1;
        index += 1;
    }
    Ok((x, index, changed))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Row>()?;
    module.add_class::<RowImage>()?;
    module.add_function(wrap_pyfunction!(runs_of, module)?)?;
    module.add_function(wrap_pyfunction!(draw_on_row, module)?)?;
    module.add_function(wrap_pyfunction!(stream::take_ground, module)?)?;
    Ok(())
}
