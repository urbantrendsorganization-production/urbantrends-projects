//! Image processing for the `process_image` job (CLAUDE.md §10).
//!
//! Re-encodes uploaded photos to JPEG under a size budget and produces a
//! thumbnail. Re-encoding inherently drops EXIF/metadata (no orientation or GPS
//! survives), satisfying the "strip EXIF" requirement without a separate pass.

use std::io::Cursor;

use image::{DynamicImage, ExtendedColorType, ImageEncoder};

/// The output of [`process_photo`]: a size-bounded JPEG plus a thumbnail.
#[derive(Debug, Clone)]
pub struct ProcessedImage {
    pub jpeg: Vec<u8>,
    pub thumbnail: Vec<u8>,
}

/// Errors from image processing.
#[derive(Debug, thiserror::Error)]
pub enum ImageError {
    #[error("could not decode image")]
    Decode,
    #[error("could not encode image")]
    Encode,
}

/// Decode `input`, re-encode as a JPEG no larger than `max_bytes`, and build a
/// square-bounded thumbnail with edge `thumb_edge`.
///
/// # Errors
/// [`ImageError::Decode`] if the bytes are not a supported image,
/// [`ImageError::Encode`] if JPEG encoding fails.
pub fn process_photo(
    input: &[u8],
    max_bytes: usize,
    thumb_edge: u32,
) -> Result<ProcessedImage, ImageError> {
    let img = image::ImageReader::new(Cursor::new(input))
        .with_guessed_format()
        .map_err(|_| ImageError::Decode)?
        .decode()
        .map_err(|_| ImageError::Decode)?;

    let jpeg = encode_under_limit(&img, max_bytes)?;
    let thumb = img.thumbnail(thumb_edge, thumb_edge);
    let thumbnail = encode_jpeg(&thumb, 80)?;

    Ok(ProcessedImage { jpeg, thumbnail })
}

/// Encode as JPEG, lowering quality then downscaling until the result fits under
/// `max_bytes` (best effort at the floor).
fn encode_under_limit(img: &DynamicImage, max_bytes: usize) -> Result<Vec<u8>, ImageError> {
    let mut current = img.clone();
    loop {
        for quality in [85u8, 75, 65, 55, 45, 35] {
            let buf = encode_jpeg(&current, quality)?;
            if buf.len() <= max_bytes {
                return Ok(buf);
            }
        }
        let (w, h) = (current.width(), current.height());
        if w < 400 || h < 400 {
            // Can't shrink further sensibly; return the smallest we managed.
            return encode_jpeg(&current, 35);
        }
        let (nw, nh) = (w * 3 / 4, h * 3 / 4);
        current = current.resize(nw, nh, image::imageops::FilterType::Triangle);
    }
}

fn encode_jpeg(img: &DynamicImage, quality: u8) -> Result<Vec<u8>, ImageError> {
    let rgb = img.to_rgb8();
    let mut buf = Vec::new();
    let encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, quality);
    encoder
        .write_image(
            rgb.as_raw(),
            rgb.width(),
            rgb.height(),
            ExtendedColorType::Rgb8,
        )
        .map_err(|_| ImageError::Encode)?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a synthetic PNG so tests need no fixtures.
    #[allow(clippy::cast_possible_truncation)]
    fn sample_png(w: u32, h: u32) -> Vec<u8> {
        let mut img = image::RgbImage::new(w, h);
        for (x, y, px) in img.enumerate_pixels_mut() {
            *px = image::Rgb([(x % 256) as u8, (y % 256) as u8, 128u8]);
        }
        let dynimg = DynamicImage::ImageRgb8(img);
        let mut buf = Vec::new();
        dynimg
            .write_to(&mut Cursor::new(&mut buf), image::ImageFormat::Png)
            .unwrap();
        buf
    }

    #[test]
    fn produces_jpeg_under_the_limit_and_a_thumbnail() {
        let png = sample_png(1200, 900);
        let out = process_photo(&png, 300 * 1024, 256).expect("process");
        assert!(out.jpeg.len() <= 300 * 1024);
        // JPEG magic bytes.
        assert_eq!(&out.jpeg[0..2], &[0xFF, 0xD8]);
        assert!(!out.thumbnail.is_empty());
        assert!(out.thumbnail.len() < out.jpeg.len());
    }

    #[test]
    fn rejects_non_image_bytes() {
        assert!(matches!(
            process_photo(b"this is not an image", 300 * 1024, 256),
            Err(ImageError::Decode)
        ));
    }
}
