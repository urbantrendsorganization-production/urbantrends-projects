//! Password hashing with argon2id (CLAUDE.md §3, §5).
//!
//! Hashes are PHC strings (`$argon2id$...`), self-describing so parameters are
//! embedded and verification never needs out-of-band config. The seed binary in
//! `onboardkit-db` hashes independently (it cannot depend on `integrations`),
//! but produces interoperable PHC strings that [`verify`] accepts.

use argon2::Argon2;
use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};

/// Errors from password hashing/verification.
#[derive(Debug, thiserror::Error)]
pub enum PasswordError {
    #[error("password hashing failed")]
    Hash,
    #[error("entropy source failed")]
    Rng,
}

/// Hash a plaintext password with argon2id and a fresh random salt.
///
/// # Errors
/// [`PasswordError::Rng`] on entropy failure, [`PasswordError::Hash`] if the
/// hasher rejects the input.
pub fn hash(password: &str) -> Result<String, PasswordError> {
    let mut salt_bytes = [0u8; 16];
    getrandom::fill(&mut salt_bytes).map_err(|_| PasswordError::Rng)?;
    let salt = SaltString::encode_b64(&salt_bytes).map_err(|_| PasswordError::Hash)?;
    let hashed = Argon2::default()
        .hash_password(password.as_bytes(), &salt)
        .map_err(|_| PasswordError::Hash)?;
    Ok(hashed.to_string())
}

/// Verify a plaintext password against a stored PHC hash. Returns `Ok(false)`
/// for a mismatch; `Err` only when the stored hash is malformed.
///
/// # Errors
/// [`PasswordError::Hash`] if `phc` cannot be parsed as a PHC hash string.
pub fn verify(password: &str, phc: &str) -> Result<bool, PasswordError> {
    let parsed = PasswordHash::new(phc).map_err(|_| PasswordError::Hash)?;
    Ok(Argon2::default()
        .verify_password(password.as_bytes(), &parsed)
        .is_ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_then_verify_roundtrips() {
        let phc = hash("correct horse battery staple").expect("hash");
        assert!(phc.starts_with("$argon2id$"));
        assert!(verify("correct horse battery staple", &phc).expect("verify"));
    }

    #[test]
    fn wrong_password_does_not_verify() {
        let phc = hash("s3cret").expect("hash");
        assert!(!verify("guess", &phc).expect("verify"));
    }

    #[test]
    fn salts_differ_between_hashes() {
        assert_ne!(hash("same").unwrap(), hash("same").unwrap());
    }

    #[test]
    fn malformed_hash_is_an_error() {
        assert!(verify("x", "not-a-phc-string").is_err());
    }
}
