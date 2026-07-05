//! Opaque token helpers for refresh tokens (§7).
//!
//! Refresh tokens are high-entropy opaque strings handed to the client; only
//! their sha256 hash is stored server-side.

use sha2::{Digest, Sha256};

/// Errors generating a token.
#[derive(Debug, thiserror::Error)]
pub enum TokenError {
    #[error("entropy source failed")]
    Rng,
}

/// Generate a 256-bit opaque token as lowercase hex (64 chars) from the OS
/// CSPRNG.
///
/// # Errors
/// [`TokenError::Rng`] if the OS entropy source fails.
pub fn generate_opaque() -> Result<String, TokenError> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| TokenError::Rng)?;
    Ok(hex::encode(bytes))
}

/// SHA-256 of `input`, lowercase hex — the form stored for refresh tokens.
#[must_use]
pub fn sha256_hex(input: &str) -> String {
    hex::encode(Sha256::digest(input.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opaque_tokens_are_64_hex_chars_and_unique() {
        let a = generate_opaque().unwrap();
        let b = generate_opaque().unwrap();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn sha256_is_stable() {
        assert_eq!(sha256_hex("abc"), sha256_hex("abc"));
        assert_ne!(sha256_hex("abc"), sha256_hex("abd"));
        assert_eq!(sha256_hex("abc").len(), 64);
    }
}
