//! Durable document storage.
//!
//! Only the document channel is persisted. Awareness never reaches this module — the room's
//! persistence hook is attached to `Doc::observe_update_v1`, and the awareness observer has
//! no reference to a [`Store`] at all. That is structural rather than a convention, which is
//! the point.

pub mod postgres;

#[cfg(test)]
pub mod memory;

use async_trait::async_trait;
use yrs::updates::decoder::Decode;
use yrs::{Doc, Transact, Update};

pub use postgres::PgStore;

/// Encoding of a stored blob: lib0 v1, as produced by `encode_state_as_update_v1` and
/// `merge_updates_v1`.
///
/// Written alongside every blob so a future yrs encoding change can be recognised rather
/// than silently misread. An unknown value is a load *error*, never an empty document.
pub const FORMAT_LIB0_V1: i16 = 1;

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    /// The database could not be reached or the query failed. Transient; retryable.
    #[error("document storage is unavailable: {0}")]
    Unavailable(String),

    /// A stored blob exists but cannot be decoded. Not retryable, and emphatically not an
    /// empty document.
    #[error("stored document for room {room} is unreadable: {detail}")]
    Corrupt { room: String, detail: String },

    /// Written by a newer server than this one.
    #[error("stored document for room {room} uses unsupported format {format}")]
    UnsupportedFormat { room: String, format: i16 },
}

/// A room's snapshot row.
pub struct StoredSnapshot {
    pub bytes: Vec<u8>,
    pub seq: i64,
    pub format: i16,
}

/// One row of a room's update log.
pub struct StoredUpdate {
    pub bytes: Vec<u8>,
    pub seq: i64,
    pub format: i16,
}

/// A document that was **successfully** loaded.
///
/// This type is the load-failure guarantee. There is no `empty()`, no `Default`, and no
/// public constructor — the only way to obtain one is [`LoadedDoc::decode`], which returns
/// `Result`. Since `Room` can only be built from a `LoadedDoc`, a storage error cannot
/// reach room construction, so it cannot present as an empty document that a later flush
/// would then write back over good state.
///
/// A genuinely new room *is* representable, and correctly so: no snapshot and no updates
/// decode to an empty document on the success path.
pub struct LoadedDoc {
    doc: Doc,
    /// Highest log sequence folded into `doc`. The compaction watermark.
    seq: i64,
    /// Un-snapshotted log rows behind `doc`, for compaction accounting.
    log_len: u32,
}

impl LoadedDoc {
    /// Rebuilds a document from its stored parts.
    ///
    /// Update order is irrelevant to the result — Yjs updates commute and yrs buffers any
    /// whose dependencies have not arrived yet. `seq` is tracked for the compaction
    /// watermark, not for correctness.
    pub fn decode(
        room: &str,
        snapshot: Option<StoredSnapshot>,
        updates: Vec<StoredUpdate>,
    ) -> Result<Self, StoreError> {
        let doc = Doc::new();
        let mut seq = 0;

        {
            let mut txn = doc
                .try_transact_mut()
                .map_err(|e| StoreError::Corrupt { room: room.to_owned(), detail: e.to_string() })?;

            if let Some(snapshot) = snapshot {
                check_format(room, snapshot.format)?;
                apply(room, &mut txn, &snapshot.bytes)?;
                seq = snapshot.seq;
            }

            for update in &updates {
                check_format(room, update.format)?;
                apply(room, &mut txn, &update.bytes)?;
                seq = seq.max(update.seq);
            }
        }

        Ok(Self { doc, seq, log_len: updates.len() as u32 })
    }

    pub fn seq(&self) -> i64 {
        self.seq
    }

    pub fn log_len(&self) -> u32 {
        self.log_len
    }

    /// Consumes the load, handing over the populated document.
    pub fn into_doc(self) -> Doc {
        self.doc
    }
}

fn check_format(room: &str, format: i16) -> Result<(), StoreError> {
    if format == FORMAT_LIB0_V1 {
        return Ok(());
    }
    Err(StoreError::UnsupportedFormat { room: room.to_owned(), format })
}

fn apply(room: &str, txn: &mut yrs::TransactionMut, bytes: &[u8]) -> Result<(), StoreError> {
    let corrupt = |detail: String| StoreError::Corrupt { room: room.to_owned(), detail };

    let update = Update::decode_v1(bytes).map_err(|e| corrupt(e.to_string()))?;
    txn.apply_update(update).map_err(|e| corrupt(e.to_string()))?;
    Ok(())
}

#[async_trait]
pub trait Store: Send + Sync + 'static {
    /// Reads a room back.
    ///
    /// A room with nothing stored is `Ok` with an empty document — that is a new room, and
    /// it is correct. Anything that goes wrong is `Err`, which fails the join.
    async fn load(&self, room: &str) -> Result<LoadedDoc, StoreError>;

    /// Appends one flush's worth of merged updates. Returns the row's sequence number.
    async fn append(&self, room: &str, update: &[u8]) -> Result<i64, StoreError>;

    /// Replaces the snapshot and drops every log row it subsumes, atomically.
    async fn snapshot(&self, room: &str, state: &[u8], through: i64) -> Result<(), StoreError>;
}

#[cfg(test)]
mod tests {
    use super::*;
    use yrs::{Map, MapPrelim, ReadTxn, StateVector};

    fn doc_with_shape(id: &str, x: f64) -> Vec<u8> {
        let doc = Doc::new();
        let shapes = doc.get_or_insert_map("shapes");
        {
            let mut txn = doc.transact_mut();
            shapes.insert(&mut txn, id, MapPrelim::from([("x".to_string(), yrs::Any::from(x))]));
        }
        doc.transact().encode_state_as_update_v1(&StateVector::default())
    }

    fn shape_x(doc: &Doc, id: &str) -> Option<f64> {
        let shapes = doc.get_or_insert_map("shapes");
        let txn = doc.transact();
        let shape = shapes.get(&txn, id)?.cast::<yrs::MapRef>().ok()?;
        match shape.get(&txn, "x")? {
            yrs::Out::Any(yrs::Any::Number(n)) => Some(n),
            _ => None,
        }
    }

    /// A room nobody has ever opened is empty, and that is a *success*.
    #[test]
    fn nothing_stored_decodes_to_a_new_empty_document() {
        let loaded = LoadedDoc::decode("demo", None, Vec::new()).expect("a new room is not an error");

        assert_eq!(loaded.seq(), 0);
        assert_eq!(loaded.log_len(), 0);
        assert_eq!(loaded.into_doc().transact().state_vector().len(), 0);
    }

    #[test]
    fn a_snapshot_and_its_log_tail_recombine() {
        let loaded = LoadedDoc::decode(
            "demo",
            Some(StoredSnapshot { bytes: doc_with_shape("rect-a", 10.0), seq: 7, format: FORMAT_LIB0_V1 }),
            vec![StoredUpdate { bytes: doc_with_shape("rect-b", 20.0), seq: 9, format: FORMAT_LIB0_V1 }],
        )
        .expect("decodes");

        assert_eq!(loaded.seq(), 9, "the watermark follows the newest row");
        assert_eq!(loaded.log_len(), 1);

        let doc = loaded.into_doc();
        assert_eq!(shape_x(&doc, "rect-a"), Some(10.0));
        assert_eq!(shape_x(&doc, "rect-b"), Some(20.0));
    }

    /// The whole point of the type: damage must not be able to look like emptiness.
    #[test]
    fn a_corrupt_blob_is_an_error_not_an_empty_document() {
        let err = LoadedDoc::decode(
            "demo",
            Some(StoredSnapshot { bytes: vec![0xff; 32], seq: 1, format: FORMAT_LIB0_V1 }),
            Vec::new(),
        )
        .expect_err("garbage must not decode");

        assert!(matches!(err, StoreError::Corrupt { .. }), "got {err:?}");
    }

    #[test]
    fn an_unknown_format_is_an_error_not_an_empty_document() {
        let err = LoadedDoc::decode(
            "demo",
            Some(StoredSnapshot { bytes: doc_with_shape("rect-a", 1.0), seq: 1, format: 99 }),
            Vec::new(),
        )
        .expect_err("a future encoding must not be silently ignored");

        assert!(matches!(err, StoreError::UnsupportedFormat { format: 99, .. }), "got {err:?}");
    }

    #[test]
    fn a_corrupt_log_row_fails_even_when_the_snapshot_is_fine() {
        let err = LoadedDoc::decode(
            "demo",
            Some(StoredSnapshot { bytes: doc_with_shape("rect-a", 1.0), seq: 1, format: FORMAT_LIB0_V1 }),
            vec![StoredUpdate { bytes: vec![0xff; 16], seq: 2, format: FORMAT_LIB0_V1 }],
        )
        .expect_err("a bad tail must not silently truncate history");

        assert!(matches!(err, StoreError::Corrupt { .. }), "got {err:?}");
    }
}
