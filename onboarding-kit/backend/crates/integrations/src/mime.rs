//! Magic-byte MIME sniffing for upload validation (CLAUDE.md §11: sniff by
//! content, never by extension).

/// Sniff the MIME type from the leading bytes, or `None` if unrecognized.
#[must_use]
pub fn sniff(bytes: &[u8]) -> Option<&'static str> {
    infer::get(bytes).map(|kind| kind.mime_type())
}

/// Whether a sniffed MIME type is acceptable for a given `doc_type`.
///
/// Photo document types must be images; `address_proof` additionally allows PDF
/// (§11).
#[must_use]
pub fn is_allowed_for(doc_type: &str, mime: &str) -> bool {
    let is_image = matches!(mime, "image/jpeg" | "image/png" | "image/webp");
    match doc_type {
        "id_front" | "id_back" | "selfie" => is_image,
        "address_proof" => is_image || mime == "application/pdf",
        _ => false,
    }
}

/// The canonical file extension for a sniffed MIME type.
#[must_use]
pub fn extension_for(mime: &str) -> &'static str {
    match mime {
        "image/jpeg" => "jpg",
        "image/png" => "png",
        "image/webp" => "webp",
        "application/pdf" => "pdf",
        _ => "bin",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sniffs_png_magic_bytes() {
        let png = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 0];
        assert_eq!(sniff(&png), Some("image/png"));
    }

    #[test]
    fn unknown_bytes_sniff_to_none() {
        assert_eq!(sniff(b"plain text not a known format"), None);
    }

    #[test]
    fn photo_types_require_images() {
        assert!(is_allowed_for("selfie", "image/jpeg"));
        assert!(!is_allowed_for("selfie", "application/pdf"));
    }

    #[test]
    fn address_proof_allows_pdf_and_images() {
        assert!(is_allowed_for("address_proof", "application/pdf"));
        assert!(is_allowed_for("address_proof", "image/png"));
        assert!(!is_allowed_for("address_proof", "text/plain"));
    }

    #[test]
    fn unknown_doc_type_allows_nothing() {
        assert!(!is_allowed_for("passport", "image/jpeg"));
    }
}
