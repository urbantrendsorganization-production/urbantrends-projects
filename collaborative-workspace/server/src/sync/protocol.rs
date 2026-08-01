//! y-sync protocol binding.
//!
//! The protocol itself lives in [`yrs::sync`] (the upstreamed `y-sync` crate). All we add
//! is per-connection provenance: every update a connection sends is applied to the room's
//! replica inside a transaction tagged with that connection's [`Origin`], so the broadcast
//! fan-out can skip echoing an update back to the peer that authored it.

use std::collections::HashSet;
use std::sync::Mutex;

use yrs::block::ClientID;
use yrs::sync::protocol::Error;
use yrs::sync::{Awareness, AwarenessUpdate, Message, Protocol, SyncMessage};
use yrs::updates::encoder::Encode;
use yrs::{Origin, ReadTxn, Transact, Update};

/// The room-relay protocol: [`DefaultProtocol`](yrs::sync::DefaultProtocol) plus origin
/// tagging and presence bookkeeping.
///
/// One instance per connection. Conflict resolution is entirely Yrs's — this type only
/// decides *which transaction* an update lands in, never *how* it merges.
pub struct RelayProtocol {
    origin: Origin,
    /// Awareness client ids this connection has published, so they can be cleared when the
    /// socket drops. Presence is ephemeral: it must not outlive the connection that owns
    /// it. Interior mutability because the [`Protocol`] trait handlers take `&self`.
    published: Mutex<HashSet<ClientID>>,
}

impl RelayProtocol {
    pub fn new(origin: Origin) -> Self {
        Self {
            origin,
            published: Mutex::new(HashSet::new()),
        }
    }

    pub fn origin(&self) -> &Origin {
        &self.origin
    }

    /// Hands over the presence entries this connection owns, leaving none behind.
    ///
    /// A poisoned lock means a handler panicked mid-update. The set is a plain collection
    /// of ids with no invariant to corrupt, and dropping the presence of a dying connection
    /// is exactly the right outcome either way, so the guard is recovered rather than
    /// propagated as an error.
    pub fn take_published(&self) -> HashSet<ClientID> {
        let mut published = self
            .published
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        std::mem::take(&mut *published)
    }
}

impl Protocol for RelayProtocol {
    /// Identical to [`DefaultProtocol`](yrs::sync::DefaultProtocol) except the update is
    /// applied within a transaction carrying this connection's origin.
    ///
    /// `handle_update` (steady-state) delegates to this method in the default trait impl,
    /// so overriding it here covers both initial sync-step-2 and every later update.
    fn handle_sync_step2(
        &self,
        awareness: &mut Awareness,
        update: Update,
    ) -> Result<Option<Message>, Error> {
        let mut txn = awareness
            .doc()
            .try_transact_mut_with(self.origin.clone())
            .map_err(|e| Error::Other(Box::new(e)))?;
        txn.apply_update(update)?;
        Ok(None)
    }

    /// Applies a peer's presence, tagged with this connection's origin, and records which
    /// client ids the connection is responsible for.
    ///
    /// Tagging matters more here than on the document: cursors are the highest-frequency
    /// traffic in the room, and without an origin the fan-out would echo every one of them
    /// straight back to the peer that just sent it.
    fn handle_awareness_update(
        &self,
        awareness: &mut Awareness,
        update: AwarenessUpdate,
    ) -> Result<Option<Message>, Error> {
        let summary = awareness.apply_update_summary_with(update, self.origin.clone())?;

        if let Some(summary) = summary {
            let mut published = self
                .published
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            published.extend(summary.added.iter().copied());
            published.extend(summary.updated.iter().copied());
            // A clean disconnect: the peer withdrew its own presence, so there is nothing
            // left for us to clear on drop.
            for client in &summary.removed {
                published.remove(client);
            }
        }

        Ok(None)
    }
}

/// The opening handshake for a freshly connected peer, **one y-sync message per frame**:
/// sync-step-1 carrying the server replica's state vector, then the awareness snapshot.
///
/// [`Protocol::start`] packs both messages into a single buffer — legal in the y-sync
/// protocol, and `yrs`' own `MessageReader` drains a buffer to the end. The JavaScript
/// client does not: `y-websocket`'s `readMessage` reads exactly one message type per
/// WebSocket frame and dispatches once, silently discarding whatever follows. Packed that
/// way the awareness snapshot is dropped on arrival and a late joiner sees an empty room
/// until every peer happens to move. Splitting the handshake is the fix; every other path
/// here already emits one message per frame.
pub fn start_frames(awareness: &Awareness) -> Result<Vec<Vec<u8>>, Error> {
    let state_vector = awareness.doc().transact().state_vector();
    let presence = awareness.update()?;

    Ok(vec![
        Message::Sync(SyncMessage::SyncStep1(state_vector)).encode_v1(),
        Message::Awareness(presence).encode_v1(),
    ])
}
