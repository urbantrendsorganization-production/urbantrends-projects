//! E.164 phone handling (CLAUDE.md §8: normalize via `phonenumber`, region KE).
//!
//! [`Phone`] is the shared normalized phone type used by the OTP service and,
//! from Phase 3, the SMS providers (§9).

/// A validated phone number in E.164 form (e.g. `+254712345678`).
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Phone(String);

/// Default parsing region for bare local numbers (Kenya).
const DEFAULT_REGION: phonenumber::country::Id = phonenumber::country::Id::KE;

impl Phone {
    /// Parse and normalize a raw phone string to E.164, defaulting to the KE
    /// region for local formats like `0712345678`.
    ///
    /// # Errors
    /// Returns [`PhoneError`] if the input cannot be parsed or is not a valid
    /// number for its region.
    pub fn parse(raw: &str) -> Result<Self, PhoneError> {
        let number =
            phonenumber::parse(Some(DEFAULT_REGION), raw).map_err(|_| PhoneError::Invalid)?;
        if !phonenumber::is_valid(&number) {
            return Err(PhoneError::Invalid);
        }
        Ok(Self(
            number.format().mode(phonenumber::Mode::E164).to_string(),
        ))
    }

    /// The normalized E.164 string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// A log-safe rendering that reveals only the last three digits (§3: never
    /// log full phone numbers).
    #[must_use]
    pub fn masked(&self) -> String {
        let count = self.0.chars().count();
        let keep = 3;
        if count <= keep {
            return "*".repeat(count);
        }
        let tail: String = self.0.chars().skip(count - keep).collect();
        format!("{}{tail}", "*".repeat(count - keep))
    }
}

/// Why a phone number could not be normalized.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum PhoneError {
    #[error("invalid phone number")]
    Invalid,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_local_kenyan_number() {
        let phone = Phone::parse("0712345678").expect("valid");
        assert_eq!(phone.as_str(), "+254712345678");
    }

    #[test]
    fn accepts_already_e164() {
        let phone = Phone::parse("+254712345678").expect("valid");
        assert_eq!(phone.as_str(), "+254712345678");
    }

    #[test]
    fn rejects_garbage() {
        assert_eq!(Phone::parse("not-a-phone"), Err(PhoneError::Invalid));
        assert_eq!(Phone::parse("12"), Err(PhoneError::Invalid));
    }

    #[test]
    fn masks_all_but_last_three() {
        let phone = Phone::parse("+254712345678").expect("valid");
        let masked = phone.masked();
        assert!(masked.ends_with("678"));
        assert!(!masked.contains("2345"));
        assert_eq!(masked.chars().filter(|&c| c == '*').count(), 10);
    }
}
