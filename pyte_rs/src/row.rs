//! `pyte_rs.Row`: one row of a page, stored by column in one contiguous
//! vector. It answers the mapping protocol `pyte.page.Row` answers, with
//! the same cell objects, so nothing that reads a row can tell the two
//! apart but by speed. Lillecarl/pymux#570.

use std::collections::BTreeMap;

use pyo3::exceptions::{PyKeyError, PyTypeError};
use pyo3::prelude::*;
use pyo3::pyclass::CompareOp;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyIterator, PyList, PyTuple};

/// `pyte.cells.UNWRITTEN`: what a column nobody wrote reads as.
static UNWRITTEN: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

fn unwritten(py: Python<'_>) -> PyResult<&Py<PyAny>> {
    UNWRITTEN.get_or_try_init(py, || {
        Ok(py.import("pyte.cells")?.getattr("UNWRITTEN")?.unbind())
    })
}

#[pyclass(module = "pyte_rs", mapping)]
pub struct Row {
    /// The cells of columns 0 and up; `None` is a column nobody wrote.
    /// It never ends in `None`, so its length is one past the last
    /// column written.
    cells: Vec<Option<Py<PyAny>>>,
    /// Columns left of 0. Nothing writes one today; a dict took any
    /// column, and so does this.
    outside: BTreeMap<i64, Py<PyAny>>,
    /// How many columns hold a cell.
    count: usize,
    /// Did a wrap bring this row into being?
    #[pyo3(get, set)]
    wrapped: bool,
}

impl Row {
    pub(crate) fn cell(&self, column: i64) -> Option<&Py<PyAny>> {
        match usize::try_from(column) {
            Ok(index) => self.cells.get(index).and_then(Option::as_ref),
            Err(_) => self.outside.get(&column),
        }
    }

    pub(crate) fn store(&mut self, column: i64, cell: Py<PyAny>) {
        let replaced = match usize::try_from(column) {
            Ok(index) => {
                if index >= self.cells.len() {
                    self.cells.resize_with(index + 1, || None);
                }
                self.cells[index].replace(cell)
            }
            Err(_) => self.outside.insert(column, cell),
        };
        if replaced.is_none() {
            self.count += 1;
        }
    }

    fn remove(&mut self, column: i64) -> Option<Py<PyAny>> {
        let removed = match usize::try_from(column) {
            Ok(index) => {
                let removed = self.cells.get_mut(index).and_then(Option::take);
                while matches!(self.cells.last(), Some(None)) {
                    self.cells.pop();
                }
                removed
            }
            Err(_) => self.outside.remove(&column),
        };
        if removed.is_some() {
            self.count -= 1;
        }
        removed
    }

    /// Every cell with its column, left to right.
    pub(crate) fn columns(&self) -> impl Iterator<Item = (i64, &Py<PyAny>)> {
        self.outside
            .iter()
            .map(|(&column, cell)| (column, cell))
            .chain(
                self.cells
                    .iter()
                    .enumerate()
                    .filter_map(|(index, cell)| cell.as_ref().map(|cell| (index as i64, cell))),
            )
    }

    fn keys_list<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, self.columns().map(|(column, _)| column))
    }
}

#[pymethods]
impl Row {
    #[new]
    fn new() -> Self {
        Self {
            cells: Vec::new(),
            outside: BTreeMap::new(),
            count: 0,
            wrapped: false,
        }
    }

    fn __getitem__(&self, py: Python<'_>, column: i64) -> PyResult<Py<PyAny>> {
        match self.cell(column) {
            Some(cell) => Ok(cell.clone_ref(py)),
            None => Ok(unwritten(py)?.clone_ref(py)),
        }
    }

    fn __setitem__(&mut self, column: i64, cell: Py<PyAny>) {
        self.store(column, cell);
    }

    fn __delitem__(&mut self, column: i64) -> PyResult<()> {
        match self.remove(column) {
            Some(_) => Ok(()),
            None => Err(PyKeyError::new_err(column)),
        }
    }

    fn __contains__(&self, column: &Bound<'_, PyAny>) -> bool {
        column
            .extract::<i64>()
            .is_ok_and(|column| self.cell(column).is_some())
    }

    fn __len__(&self) -> usize {
        self.count
    }

    fn __iter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyIterator>> {
        self.keys_list(py)?.try_iter()
    }

    fn keys<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        self.keys_list(py)
    }

    fn values<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, self.columns().map(|(_, cell)| cell.clone_ref(py)))
    }

    fn items<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        PyList::new(
            py,
            self.columns()
                .map(|(column, cell)| (column, cell.clone_ref(py))),
        )
    }

    #[pyo3(signature = (column, default = None))]
    fn get(
        &self,
        py: Python<'_>,
        column: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> Py<PyAny> {
        let found = column
            .extract::<i64>()
            .ok()
            .and_then(|column| self.cell(column));
        match (found, default) {
            (Some(cell), _) => cell.clone_ref(py),
            (None, Some(default)) => default,
            (None, None) => py.None(),
        }
    }

    #[pyo3(signature = (column, *default))]
    fn pop(&mut self, column: i64, default: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        if let Some(cell) = self.remove(column) {
            return Ok(cell);
        }
        match default.len() {
            0 => Err(PyKeyError::new_err(column)),
            1 => Ok(default.get_item(0)?.unbind()),
            given => Err(PyTypeError::new_err(format!(
                "pop expected at most 2 arguments, got {}",
                given + 1
            ))),
        }
    }

    /// Take the cells of a mapping, or of an iterable of pairs.
    fn update(&mut self, other: &Bound<'_, PyAny>) -> PyResult<()> {
        let pairs = if other.hasattr("items")? {
            other.call_method0("items")?
        } else {
            other.clone()
        };
        for pair in pairs.try_iter()? {
            let (column, cell): (i64, Py<PyAny>) = pair?.extract()?;
            self.store(column, cell);
        }
        Ok(())
    }

    fn clear(&mut self) {
        self.cells.clear();
        self.outside.clear();
        self.count = 0;
    }

    /// Equal to any mapping that holds the same columns and equal cells,
    /// as a dict is.
    fn __richcmp__(
        &self,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
    ) -> PyResult<Py<PyAny>> {
        let equal = match op {
            CompareOp::Eq | CompareOp::Ne => {
                if !other.hasattr("items")? || other.len()? != self.count {
                    false
                } else {
                    let mut all = true;
                    for (column, cell) in self.columns() {
                        let theirs = other.call_method1("get", (column,))?;
                        if theirs.is_none() || !cell.bind(py).eq(&theirs)? {
                            all = false;
                            break;
                        }
                    }
                    all
                }
            }
            _ => return Ok(py.NotImplemented()),
        };
        let answer = if matches!(op, CompareOp::Eq) {
            equal
        } else {
            !equal
        };
        Ok(answer.into_pyobject(py)?.to_owned().into_any().unbind())
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let mut parts = Vec::with_capacity(self.count);
        for (column, cell) in self.columns() {
            parts.push(format!("{column}: {}", cell.bind(py).repr()?));
        }
        Ok(format!("Row({{{}}})", parts.join(", ")))
    }
}
