//! `pyte.sixel.decode_sixel`, for the payloads it can answer exactly: ASCII,
//! with no number past 18 digits. Anything else answers `False` and the
//! Python decodes it, because Python reads Unicode digits, keeps numbers of
//! any size, and raises on one too big for a float. It runs with the GIL
//! released. Lillecarl/pymux#574.

use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::PyBytes;

const MAX_REGISTERS: usize = 256;
const MAX_WIDTH: i64 = 16384;
const MAX_HEIGHT: i64 = 16384;
const MAX_PIXELS: i64 = 4 * 1024 * 1024;
/// Past this many digits a number may not fit an `i64`.
const MAX_DIGITS: usize = 18;

const VT340_PALETTE_PERCENT: [(i64, i64, i64); 16] = [
    (0, 0, 0),
    (20, 20, 80),
    (80, 13, 13),
    (20, 80, 20),
    (80, 20, 80),
    (20, 80, 80),
    (80, 80, 20),
    (53, 53, 53),
    (26, 26, 26),
    (33, 33, 60),
    (60, 26, 26),
    (33, 60, 33),
    (60, 33, 60),
    (33, 60, 60),
    (60, 60, 33),
    (80, 80, 80),
];

/// Python's `round` of a float: half to even.
fn round_py(value: f64) -> i64 {
    value.round_ties_even() as i64
}

/// `pyte.sixel._percent`. A value past 100 clamps, so `value * 255 / 100`
/// is exact wherever the answer depends on it.
fn percent(value: i64) -> u8 {
    round_py((value as f64 * 255.0) / 100.0).clamp(0, 255) as u8
}

/// Python's `float % float`.
fn float_mod(x: f64, y: f64) -> f64 {
    let m = x % y;
    if m != 0.0 {
        if (y < 0.0) != (m < 0.0) { m + y } else { m }
    } else {
        0.0_f64.copysign(y)
    }
}

/// `colorsys._v`.
fn hls_value(m1: f64, m2: f64, hue: f64) -> f64 {
    const ONE_SIXTH: f64 = 1.0 / 6.0;
    const TWO_THIRD: f64 = 2.0 / 3.0;
    let hue = float_mod(hue, 1.0);
    if hue < ONE_SIXTH {
        m1 + (m2 - m1) * hue * 6.0
    } else if hue < 0.5 {
        m2
    } else if hue < TWO_THIRD {
        m1 + (m2 - m1) * (TWO_THIRD - hue) * 6.0
    } else {
        m1
    }
}

/// `pyte.sixel._hls_to_rgb`, through `colorsys.hls_to_rgb`.
fn hls_to_rgb(hue: i64, lightness: i64, saturation: i64) -> (u8, u8, u8) {
    const ONE_THIRD: f64 = 1.0 / 3.0;
    let h = ((hue + 240) % 360) as f64 / 360.0;
    let l = lightness.clamp(0, 100) as f64 / 100.0;
    let s = saturation.clamp(0, 100) as f64 / 100.0;
    let (red, green, blue) = if s == 0.0 {
        (l, l, l)
    } else {
        let m2 = if l <= 0.5 {
            l * (1.0 + s)
        } else {
            l + s - (l * s)
        };
        let m1 = 2.0 * l - m2;
        (
            hls_value(m1, m2, h + ONE_THIRD),
            hls_value(m1, m2, h),
            hls_value(m1, m2, h - ONE_THIRD),
        )
    };
    (
        round_py(red * 255.0) as u8,
        round_py(green * 255.0) as u8,
        round_py(blue * 255.0) as u8,
    )
}

fn define_color(values: [i64; 4]) -> (u8, u8, u8) {
    let [system, first, second, third] = values;
    if system == 1 {
        hls_to_rgb(first, second, third)
    } else {
        (percent(first), percent(second), percent(third))
    }
}

/// The payload is not one this kernel answers exactly.
struct Unanswerable;

struct Reader<'a> {
    body: &'a [u8],
    index: usize,
}

impl Reader<'_> {
    fn peek(&self) -> Option<u8> {
        self.body.get(self.index).copied()
    }

    /// `pyte.sixel._read_int`.
    fn int(&mut self) -> Result<i64, Unanswerable> {
        let start = self.index;
        while self.peek().is_some_and(|byte| byte.is_ascii_digit()) {
            self.index += 1;
        }
        let digits = &self.body[start..self.index];
        if digits.len() > MAX_DIGITS {
            return Err(Unanswerable);
        }
        Ok(digits
            .iter()
            .fold(0, |value, digit| value * 10 + i64::from(digit - b'0')))
    }
}

/// `pyte.sixel._Canvas`: register plus one per pixel, zero for unwritten.
#[derive(Default)]
struct Canvas {
    rows: Vec<Vec<u16>>,
    width: i64,
    height: i64,
}

impl Canvas {
    fn write(&mut self, band: i64, x: i64, count: i64, bits: u8, register: usize) -> i64 {
        let count = count.min(MAX_WIDTH - x);
        if count <= 0 || band >= MAX_HEIGHT {
            return 0;
        }
        self.width = self.width.max(x + count);
        self.height = self.height.max((band + 6).min(MAX_HEIGHT));
        let value = register as u16 + 1;
        let (start, end) = (x as usize, (x + count) as usize);
        for offset in 0..6 {
            if bits & (1 << offset) != 0 {
                let y = band + offset;
                if y >= MAX_HEIGHT {
                    break;
                }
                let y = y as usize;
                if self.rows.len() <= y {
                    self.rows.resize_with(y + 1, Vec::new);
                }
                let row = &mut self.rows[y];
                if row.len() < end {
                    row.resize(end, 0);
                }
                row[start..end].fill(value);
            }
        }
        count
    }

    fn to_rgba(
        &self,
        palette: &[(u8, u8, u8)],
        width: usize,
        height: usize,
        background: Option<(u8, u8, u8)>,
    ) -> Vec<u8> {
        let empty = match background {
            None => [0, 0, 0, 0],
            Some((r, g, b)) => [r, g, b, 255],
        };
        let mut lookup = Vec::with_capacity(palette.len() + 1);
        lookup.push(empty);
        lookup.extend(palette.iter().map(|&(r, g, b)| [r, g, b, 255]));
        let mut out = Vec::with_capacity(width * height * 4);
        for _ in 0..width * height {
            out.extend_from_slice(&empty);
        }
        for (y, row) in self.rows.iter().take(height).enumerate() {
            let count = row.len().min(width);
            let base = y * width * 4;
            for (x, &value) in row[..count].iter().enumerate() {
                let at = base + x * 4;
                out[at..at + 4].copy_from_slice(&lookup[usize::from(value)]);
            }
        }
        out
    }
}

type Image = Option<(i64, i64, Vec<u8>)>;

fn decode(payload: &[u8]) -> Result<Image, Unanswerable> {
    // The head: "^([\d;]*)q".
    let head_end = payload
        .iter()
        .position(|&byte| !(byte.is_ascii_digit() || byte == b';'));
    let Some(head_end) = head_end.filter(|&at| payload[at] == b'q') else {
        return Ok(None);
    };
    let mut params = Vec::new();
    for part in payload[..head_end].split(|&byte| byte == b';') {
        if part.is_empty() {
            continue;
        }
        if part.len() > MAX_DIGITS {
            return Err(Unanswerable);
        }
        params.push(
            part.iter()
                .fold(0i64, |value, digit| value * 10 + i64::from(digit - b'0')),
        );
    }
    let transparent = params.len() >= 2 && params[1] == 1;

    let mut palette: Vec<(u8, u8, u8)> = VT340_PALETTE_PERCENT
        .iter()
        .map(|&(r, g, b)| (percent(r), percent(g), percent(b)))
        .collect();
    palette.resize(MAX_REGISTERS, (0, 0, 0));

    let mut canvas = Canvas::default();
    let mut register = 0usize;
    let mut x: i64 = 0;
    let mut band: i64 = 0;
    let mut raster_width: i64 = 0;
    let mut raster_height: i64 = 0;
    let mut reader = Reader {
        body: &payload[head_end + 1..],
        index: 0,
    };
    let data = |byte: u8| (0x3f..=0x7e).contains(&byte);

    while let Some(char) = reader.peek() {
        match char {
            _ if data(char) => {
                x += canvas.write(band, x, 1, char - 0x3f, register);
                reader.index += 1;
            }
            b'!' => {
                reader.index += 1;
                let count = reader.int()?;
                if let Some(byte) = reader.peek() {
                    reader.index += 1;
                    if data(byte) {
                        let count = if count == 0 { 1 } else { count };
                        x += canvas.write(band, x, count, byte - 0x3f, register);
                    }
                }
            }
            b'#' => {
                reader.index += 1;
                let number = reader.int()?;
                if reader.peek() == Some(b';') {
                    let mut values = Vec::with_capacity(4);
                    while reader.peek() == Some(b';') && values.len() < 4 {
                        reader.index += 1;
                        values.push(reader.int()?);
                    }
                    if let Ok(values) = <[i64; 4]>::try_from(values) {
                        palette[(number % MAX_REGISTERS as i64) as usize] = define_color(values);
                    }
                } else {
                    register = (number % MAX_REGISTERS as i64) as usize;
                }
            }
            b'$' => {
                x = 0;
                reader.index += 1;
            }
            b'-' => {
                x = 0;
                band += 6;
                reader.index += 1;
            }
            b'"' => {
                reader.index += 1;
                let mut values = Vec::with_capacity(4);
                while values.len() < 4 {
                    values.push(reader.int()?);
                    if reader.peek() == Some(b';') {
                        reader.index += 1;
                    } else {
                        break;
                    }
                }
                if values.len() == 4 {
                    raster_width = values[2];
                    raster_height = values[3];
                }
            }
            _ => reader.index += 1,
        }
    }

    let width = canvas.width.max(raster_width.clamp(0, MAX_WIDTH));
    let mut height = canvas.height.max(raster_height.clamp(0, MAX_HEIGHT));
    if 0 < raster_height && raster_height <= canvas.height && canvas.height - raster_height < 6 {
        height = raster_height;
    }
    if width <= 0 || height <= 0 || width * height > MAX_PIXELS {
        return Ok(None);
    }
    let background = (!transparent).then(|| palette[0]);
    let pixels = canvas.to_rgba(&palette[..], width as usize, height as usize, background);
    Ok(Some((width, height, pixels)))
}

/// `pyte.sixel.decode_sixel`, or `False` for a payload only the Python
/// answers exactly.
#[pyfunction]
fn decode_sixel(py: Python<'_>, payload: PyBackedStr) -> PyResult<Py<PyAny>> {
    if !payload.is_ascii() {
        return Ok(false.into_pyobject(py)?.to_owned().into_any().unbind());
    }
    match py.detach(|| decode(payload.as_bytes())) {
        Err(Unanswerable) => Ok(false.into_pyobject(py)?.to_owned().into_any().unbind()),
        Ok(None) => Ok(py.None()),
        Ok(Some((width, height, pixels))) => Ok((width, height, PyBytes::new(py, &pixels))
            .into_pyobject(py)?
            .into_any()
            .unbind()),
    }
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(decode_sixel, module)?)?;
    Ok(())
}
