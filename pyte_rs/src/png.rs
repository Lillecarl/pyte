//! `pyte.png`'s per-byte loops: `_unfilter` and `_rgba_of`. Each gives the
//! bytes its Python original gives, and runs with the GIL released, so a
//! worker thread decodes beside the event loop. Lillecarl/pymux#574.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedBytes;
use pyo3::types::PyBytes;

fn paeth(left: i32, up: i32, up_left: i32) -> i32 {
    let estimate = left + up - up_left;
    let distance_left = (estimate - left).abs();
    let distance_up = (estimate - up).abs();
    let distance_up_left = (estimate - up_left).abs();
    if distance_left <= distance_up && distance_left <= distance_up_left {
        left
    } else if distance_up <= distance_up_left {
        up
    } else {
        up_left
    }
}

enum Unfiltered {
    Samples(Vec<u8>),
    Truncated,
    UnknownFilter(u8),
}

fn unfilter_rows(raw: &[u8], height: usize, stride: usize, bytes_per_pixel: usize) -> Unfiltered {
    let mut out = vec![0u8; height * stride];
    let mut position = 0;
    for row in 0..height {
        if position + 1 + stride > raw.len() {
            return Unfiltered::Truncated;
        }
        let filter_type = raw[position];
        let (done, rest) = out.split_at_mut(row * stride);
        let previous: &[u8] = if row == 0 {
            &[]
        } else {
            &done[(row - 1) * stride..]
        };
        let line = &mut rest[..stride];
        line.copy_from_slice(&raw[position + 1..position + 1 + stride]);
        position += 1 + stride;
        let up = |i: usize| previous.get(i).copied().unwrap_or(0);
        match filter_type {
            0 => {}
            1 => {
                for i in bytes_per_pixel..stride {
                    line[i] = line[i].wrapping_add(line[i - bytes_per_pixel]);
                }
            }
            2 => {
                for (i, value) in line.iter_mut().enumerate() {
                    *value = value.wrapping_add(up(i));
                }
            }
            3 => {
                for i in 0..stride {
                    let left = if i >= bytes_per_pixel {
                        u32::from(line[i - bytes_per_pixel])
                    } else {
                        0
                    };
                    line[i] = line[i].wrapping_add(((left + u32::from(up(i))) >> 1) as u8);
                }
            }
            4 => {
                for i in 0..stride {
                    let (left, up_left) = if i >= bytes_per_pixel {
                        (
                            i32::from(line[i - bytes_per_pixel]),
                            i32::from(up(i - bytes_per_pixel)),
                        )
                    } else {
                        (0, 0)
                    };
                    let predicted = paeth(left, i32::from(up(i)), up_left);
                    line[i] = line[i].wrapping_add(predicted as u8);
                }
            }
            other => return Unfiltered::UnknownFilter(other),
        }
    }
    Unfiltered::Samples(out)
}

/// `pyte.png._unfilter`: undo the filter of every scanline.
#[pyfunction]
fn unfilter<'py>(
    py: Python<'py>,
    raw: PyBackedBytes,
    height: usize,
    stride: usize,
    bytes_per_pixel: usize,
) -> PyResult<Bound<'py, PyBytes>> {
    match py.detach(|| unfilter_rows(&raw, height, stride, bytes_per_pixel)) {
        Unfiltered::Samples(samples) => Ok(PyBytes::new(py, &samples)),
        Unfiltered::Truncated => Err(PyValueError::new_err("truncated image data")),
        Unfiltered::UnknownFilter(kind) => {
            Err(PyValueError::new_err(format!("unknown filter type {kind}")))
        }
    }
}

/// One scanline's samples, scaled to bytes: `pyte.png._samples`.
fn samples_of(line: &[u8], count: usize, depth: u32, out: &mut Vec<u32>) {
    out.clear();
    match depth {
        8 => out.extend(line[..count].iter().map(|&value| u32::from(value))),
        16 => out.extend(
            line.iter()
                .step_by(2)
                .take(count)
                .map(|&value| u32::from(value)),
        ),
        _ => {
            let maximum = (1u32 << depth) - 1;
            let per_byte = (8 / depth) as usize;
            for index in 0..count {
                let byte = u32::from(line[index / per_byte]);
                let shift = 8 - depth * (index % per_byte + 1) as u32;
                out.push((byte >> shift) & maximum);
            }
        }
    }
}

struct Picture<'a> {
    samples: &'a [u8],
    width: usize,
    height: usize,
    stride: usize,
    depth: u32,
    colour_type: u8,
    palette: &'a [(u8, u8, u8)],
    transparency: &'a [u8],
}

fn rgba_rows(picture: &Picture<'_>) -> Vec<u8> {
    let Picture {
        samples,
        width,
        height,
        stride,
        depth,
        colour_type,
        palette,
        transparency,
    } = *picture;
    let channels: usize = match colour_type {
        0 | 3 => 1,
        2 => 3,
        4 => 2,
        _ => 4,
    };
    let scale: u32 = if depth < 8 {
        255 / ((1 << depth) - 1)
    } else {
        1
    };
    let key = |at: usize| u32::from(u16::from_be_bytes([transparency[at], transparency[at + 1]]));
    let grey_key = (transparency.len() >= 2).then(|| key(0));
    let colour_keys = (transparency.len() >= 6).then(|| [key(0), key(2), key(4)]);
    // A 16-bit sample keeps only its high byte, and is still compared
    // with the whole key. That is what the Python does.
    let narrowed = |value: u32| if depth == 16 { value } else { value & 0xff };

    let mut out = vec![0u8; width * height * 4];
    let mut line = Vec::with_capacity(width * channels);
    for row in 0..height {
        samples_of(
            &samples[row * stride..(row + 1) * stride],
            width * channels,
            depth,
            &mut line,
        );
        for column in 0..width {
            let offset = (row * width + column) * 4;
            let index = column * channels;
            let pixel: [u32; 4] = match colour_type {
                0 => {
                    let grey = line[index] * scale;
                    let alpha = if grey_key.is_some_and(|value| line[index] == narrowed(value)) {
                        0
                    } else {
                        255
                    };
                    [grey, grey, grey, alpha]
                }
                2 => {
                    let rgb = [line[index], line[index + 1], line[index + 2]];
                    let alpha = if colour_keys.is_some_and(|keys| rgb == keys.map(narrowed)) {
                        0
                    } else {
                        255
                    };
                    [rgb[0], rgb[1], rgb[2], alpha]
                }
                3 => {
                    let entry = line[index] as usize;
                    let (red, green, blue) = palette.get(entry).copied().unwrap_or((0, 0, 0));
                    let alpha = transparency.get(entry).copied().unwrap_or(255);
                    [
                        u32::from(red),
                        u32::from(green),
                        u32::from(blue),
                        u32::from(alpha),
                    ]
                }
                4 => {
                    let grey = line[index] * scale;
                    [grey, grey, grey, line[index + 1] * scale]
                }
                _ => [
                    line[index],
                    line[index + 1],
                    line[index + 2],
                    line[index + 3],
                ],
            };
            for (slot, value) in out[offset..offset + 4].iter_mut().zip(pixel) {
                *slot = value as u8;
            }
        }
    }
    out
}

/// `pyte.png._rgba_of`: the RGBA bytes of unfiltered scanlines.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn rgba_of<'py>(
    py: Python<'py>,
    samples: PyBackedBytes,
    width: usize,
    height: usize,
    stride: usize,
    depth: u32,
    colour_type: u8,
    palette: Vec<(u8, u8, u8)>,
    transparency: PyBackedBytes,
) -> Bound<'py, PyBytes> {
    let picture = Picture {
        samples: &samples,
        width,
        height,
        stride,
        depth,
        colour_type,
        palette: &palette,
        transparency: &transparency,
    };
    let out = py.detach(|| rgba_rows(&picture));
    PyBytes::new(py, &out)
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(unfilter, module)?)?;
    module.add_function(wrap_pyfunction!(rgba_of, module)?)?;
    Ok(())
}
