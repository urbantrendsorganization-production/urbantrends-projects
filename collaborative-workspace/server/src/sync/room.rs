//! Rooms: one server-side Yrs replica + one broadcast fan-out per document id.
//!
//! Keeping an authoritative replica per room is what makes a late-joining client work —
//! it syncs against the server's document, not against whichever peers happen to be online.

use std::collections::HashMap;
use std::sync::Arc;

use bytes::Bytes;
use tokio::sync::{RwLock, broadcast};
use yrs::sync::protocol::Error as ProtocolError;
use yrs::sync::{Awareness, Message, Protocol, SyncMessage};
use yrs::updates::encoder::Encode;
use yrs::{Doc, Origin, ReadTxn, Subscription, Transact, TransactionAcqError};

use super::protocol::{RelayProtocol, start_frames};

/// Buffered frames per connection before it is considered lagging.
const BROADCAST_CAPACITY: usize = 512;

/// A frame to relay to the room, tagged with the connection that caused it so that
/// connection can skip its own echo.
#[derive(Clone, Debug)]
pub struct RoomUpdate {
    pub origin: Option<Origin>,
    pub payload: Bytes,
}

/// A single live document: the authoritative Yrs replica plus its fan-out channel.
pub struct Room {
    awareness: RwLock<Awareness>,
    tx: broadcast::Sender<RoomUpdate>,
    /// Subscriptions must outlive the room; dropping them unregisters the observers.
    _doc_sub: Subscription,
    _awareness_sub: Subscription,
}

impl Room {
    /// Fails only if the fresh document is somehow already inside a transaction, which
    /// cannot happen here — but room construction sits on the connection path, so the
    /// error is propagated rather than unwrapped.
    fn new() -> Result<Self, TransactionAcqError> {
        let (tx, _) = broadcast::channel(BROADCAST_CAPACITY);

        let doc = Doc::new();

        // Every committed transaction on the replica — whoever caused it — is re-encoded
        // as a y-sync Update and pushed to the room.
        let doc_tx = tx.clone();
        let doc_sub = doc.observe_update_v1(move |txn, e| {
            let payload = Message::Sync(SyncMessage::Update(e.update.clone())).encode_v1();
            let _ = doc_tx.send(RoomUpdate {
                origin: txn.origin().cloned(),
                payload: Bytes::from(payload),
            });
        })?;

        let mut awareness = Awareness::new(doc);

        // Awareness is relayed, never persisted (there is no persistence in this phase at
        // all). No presence is interpreted server-side — this is pure protocol plumbing.
        let awareness_tx = tx.clone();
        let awareness_sub = awareness.on_update(move |awareness, e, origin| {
            let Ok(update) = awareness.update_with_clients(e.all_changes()) else {
                return;
            };
            let _ = awareness_tx.send(RoomUpdate {
                origin: origin.cloned(),
                payload: Bytes::from(Message::Awareness(update).encode_v1()),
            });
        });

        Ok(Self {
            awareness: RwLock::new(awareness),
            tx,
            _doc_sub: doc_sub,
            _awareness_sub: awareness_sub,
        })
    }

    /// Opening handshake for a new peer: sync-step-1 + awareness snapshot, as one frame
    /// each (see [`start_frames`] for why they must not share a frame).
    pub async fn start_frames(&self) -> Result<Vec<Bytes>, ProtocolError> {
        let awareness = self.awareness.read().await;
        Ok(start_frames(&awareness)?
            .into_iter()
            .map(Bytes::from)
            .collect())
    }

    /// Applies an inbound y-sync payload to the replica, returning any direct replies owed
    /// to the sender. Relaying to the rest of the room happens via the doc/awareness
    /// observers, so it is not this function's job.
    pub async fn handle(
        &self,
        protocol: &RelayProtocol,
        data: &[u8],
    ) -> Result<Vec<Message>, ProtocolError> {
        let mut awareness = self.awareness.write().await;
        let replies = protocol.handle(&mut awareness, data)?;
        Ok(replies.into_vec())
    }

    /// Clears the presence a departing connection published, broadcasting the removal.
    ///
    /// Presence is ephemeral and belongs to the socket that published it. Yjs clients do
    /// expire stale peers on their own, but only after a ~30s timeout, and only for peers
    /// they can still hear from — a peer that crashes rather than closing cleanly would
    /// otherwise linger in the replica and be handed to every subsequent joiner. Clearing
    /// it here is immediate and safe: a reconnecting client republishes its state.
    pub async fn forget(&self, protocol: &RelayProtocol) {
        let published = protocol.take_published();
        if published.is_empty() {
            return;
        }

        let mut awareness = self.awareness.write().await;
        for client in published {
            // Fires the awareness observer, which fans the removal out to the room.
            awareness.remove_state(client);
        }
    }

    /// A bare sync-step-1, used to re-converge a connection that fell behind the fan-out.
    pub async fn resync_payload(&self) -> Bytes {
        let awareness = self.awareness.read().await;
        let sv = awareness.doc().transact().state_vector();
        Bytes::from(Message::Sync(SyncMessage::SyncStep1(sv)).encode_v1())
    }

    fn subscriber_count(&self) -> usize {
        self.tx.receiver_count()
    }
}

/// Registry of live rooms, keyed by document id.
#[derive(Clone, Default)]
pub struct Rooms(Arc<RwLock<HashMap<String, Arc<Room>>>>);

impl Rooms {
    pub fn new() -> Self {
        Self::default()
    }

    /// Joins a room, creating it if this is the first connection.
    ///
    /// The receiver is created while the registry lock is still held. That ordering
    /// matters: it makes the room's subscriber count non-zero before another task can
    /// observe it as empty and evict it, which would otherwise strand this connection in
    /// an orphaned room that later joiners never see.
    pub async fn join(
        &self,
        name: &str,
    ) -> Result<(Arc<Room>, broadcast::Receiver<RoomUpdate>), TransactionAcqError> {
        let mut rooms = self.0.write().await;
        let room = match rooms.get(name) {
            Some(room) => room.clone(),
            None => {
                let room = Arc::new(Room::new()?);
                rooms.insert(name.to_owned(), room.clone());
                room
            }
        };
        let rx = room.tx.subscribe();
        Ok((room, rx))
    }

    /// Drops the room once its last connection is gone. Nothing is persisted, so an empty
    /// room has no state worth keeping.
    pub async fn leave(&self, name: &str) {
        let mut rooms = self.0.write().await;
        if let Some(room) = rooms.get(name)
            && room.subscriber_count() == 0
        {
            rooms.remove(name);
        }
    }

    #[cfg(test)]
    async fn len(&self) -> usize {
        self.0.read().await.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use yrs::block::ClientID;
    use yrs::sync::awareness::AwarenessUpdateEntry;
    use yrs::sync::{AwarenessUpdate, MessageReader};
    use yrs::updates::decoder::{Decode, DecoderV1};
    use yrs::{Any, Map, MapPrelim, ReadTxn, StateVector, Update};

    /// Encodes a client-side doc's full state as a steady-state y-sync Update frame.
    fn update_frame(doc: &Doc) -> Vec<u8> {
        let update = doc
            .transact()
            .encode_state_as_update_v1(&StateVector::default());
        Message::Sync(SyncMessage::Update(update)).encode_v1()
    }

    fn decode_messages(data: &[u8]) -> Vec<Message> {
        let mut decoder = DecoderV1::from(data);
        MessageReader::new(&mut decoder)
            .collect::<Result<Vec<_>, _>>()
            .expect("decodable y-sync payload")
    }

    /// Writes a shape into the `shapes` map using the real document shape: a nested
    /// Y.Map per object, keyed by object id, with per-property keys.
    fn insert_shape(doc: &Doc, id: &str, x: f64, y: f64) {
        let shapes = doc.get_or_insert_map("shapes");
        let mut txn = doc.transact_mut();
        shapes.insert(
            &mut txn,
            id,
            MapPrelim::from([
                ("x".to_string(), Any::from(x)),
                ("y".to_string(), Any::from(y)),
            ]),
        );
    }

    fn read_shape_x(doc: &Doc, id: &str) -> Option<f64> {
        let shapes = doc.get_or_insert_map("shapes");
        let txn = doc.transact();
        let shape = shapes.get(&txn, id)?.cast::<yrs::MapRef>().ok()?;
        match shape.get(&txn, "x")? {
            yrs::Out::Any(Any::Number(n)) => Some(n),
            _ => None,
        }
    }

    /// The core Phase 1 guarantee: a client that connects *after* edits already happened
    /// converges to current state off the server replica alone.
    #[tokio::test]
    async fn late_joiner_syncs_to_current_state() {
        let room = Room::new().expect("fresh room");

        // An early client makes an edit and pushes it to the room.
        let early = Doc::new();
        insert_shape(&early, "rect-1", 42.0, 7.0);
        let proto_early = RelayProtocol::new(Origin::from(1u64));
        room.handle(&proto_early, &update_frame(&early))
            .await
            .expect("server accepts the update");

        // A late client joins knowing nothing, and performs the handshake.
        let late = Doc::new();
        assert_eq!(read_shape_x(&late, "rect-1"), None);

        let proto_late = RelayProtocol::new(Origin::from(2u64));
        let start = room.start_frames().await.expect("handshake encodes");

        // The server's sync-step-1 tells the client what the server has; the client
        // answers with its own state vector.
        let mut client_replies = Vec::new();
        for frame in &start {
            for msg in decode_messages(frame) {
                if let Message::Sync(SyncMessage::SyncStep1(_)) = msg {
                    let sv = late.transact().state_vector();
                    client_replies.push(Message::Sync(SyncMessage::SyncStep1(sv)).encode_v1());
                }
            }
        }
        assert!(
            !client_replies.is_empty(),
            "server must open with sync-step-1"
        );

        // The server answers with exactly the updates the client is missing.
        for frame in client_replies {
            for reply in room
                .handle(&proto_late, &frame)
                .await
                .expect("server replies")
            {
                if let Message::Sync(SyncMessage::SyncStep2(update)) = reply {
                    let update = Update::decode_v1(&update).expect("decodable update");
                    late.transact_mut().apply_update(update).expect("applies");
                }
            }
        }

        assert_eq!(
            read_shape_x(&late, "rect-1"),
            Some(42.0),
            "late joiner must converge to the state it never saw live"
        );
    }

    /// Updates are broadcast tagged with their author so the author can skip its own echo.
    #[tokio::test]
    async fn broadcasts_carry_the_authoring_origin() {
        let rooms = Rooms::new();
        let (room, mut rx) = rooms.join("demo").await.expect("join");

        let author = Origin::from(99u64);
        let doc = Doc::new();
        insert_shape(&doc, "rect-1", 1.0, 2.0);

        room.handle(&RelayProtocol::new(author.clone()), &update_frame(&doc))
            .await
            .expect("server accepts the update");

        let relayed = rx.try_recv().expect("update is fanned out to the room");
        assert_eq!(
            relayed.origin.as_ref(),
            Some(&author),
            "fan-out must identify the authoring connection"
        );
        assert!(matches!(
            decode_messages(&relayed.payload).as_slice(),
            [Message::Sync(SyncMessage::Update(_))]
        ));
    }

    /// Two clients that never talk to each other converge through the relay.
    #[tokio::test]
    async fn two_clients_converge_through_the_relay() {
        let room = Room::new().expect("fresh room");

        let a = Doc::new();
        let b = Doc::new();
        insert_shape(&a, "rect-a", 10.0, 0.0);
        insert_shape(&b, "rect-b", 20.0, 0.0);

        let proto_a = RelayProtocol::new(Origin::from(1u64));
        let proto_b = RelayProtocol::new(Origin::from(2u64));
        room.handle(&proto_a, &update_frame(&a))
            .await
            .expect("a applies");
        room.handle(&proto_b, &update_frame(&b))
            .await
            .expect("b applies");

        // Each client pulls whatever it is missing from the server replica.
        for (doc, proto) in [(&a, &proto_a), (&b, &proto_b)] {
            let sv = doc.transact().state_vector();
            let frame = Message::Sync(SyncMessage::SyncStep1(sv)).encode_v1();
            for reply in room.handle(proto, &frame).await.expect("server replies") {
                if let Message::Sync(SyncMessage::SyncStep2(update)) = reply {
                    let update = Update::decode_v1(&update).expect("decodable update");
                    doc.transact_mut().apply_update(update).expect("applies");
                }
            }
        }

        for doc in [&a, &b] {
            assert_eq!(read_shape_x(doc, "rect-a"), Some(10.0));
            assert_eq!(read_shape_x(doc, "rect-b"), Some(20.0));
        }
    }

    /// Writes a peer's presence into the room the way a real connection does.
    fn presence_frame(client: ClientID, json: &str) -> Vec<u8> {
        let update = AwarenessUpdate {
            clients: HashMap::from([(
                client,
                AwarenessUpdateEntry {
                    clock: 1,
                    json: json.into(),
                },
            )]),
        };
        Message::Awareness(update).encode_v1()
    }

    fn presence_of(update: &AwarenessUpdate, client: ClientID) -> Option<&str> {
        Some(update.clients.get(&client)?.json.as_ref())
    }

    /// The handshake must go out as one y-sync message per WebSocket frame.
    ///
    /// `yrs` is happy to pack several messages into one buffer, but `y-websocket` reads
    /// only the first message of a frame and discards the rest — so a packed handshake
    /// silently loses the awareness snapshot and late joiners see an empty room.
    #[tokio::test]
    async fn handshake_sends_one_message_per_frame() {
        let room = Room::new().expect("fresh room");

        let peer = RelayProtocol::new(Origin::from(1u64));
        let client = ClientID::new(7);
        room.handle(&peer, &presence_frame(client, r#"{"user":{"name":"Ada"}}"#))
            .await
            .expect("server accepts presence");

        let frames = room.start_frames().await.expect("handshake encodes");

        for (i, frame) in frames.iter().enumerate() {
            assert_eq!(
                decode_messages(frame).len(),
                1,
                "frame {i} must carry exactly one message, or the JS client drops the rest"
            );
        }

        let messages: Vec<_> = frames.iter().flat_map(|f| decode_messages(f)).collect();
        assert!(
            matches!(
                messages.first(),
                Some(Message::Sync(SyncMessage::SyncStep1(_)))
            ),
            "the handshake must open with sync-step-1"
        );

        let presence = messages
            .iter()
            .find_map(|m| match m {
                Message::Awareness(update) => Some(update),
                _ => None,
            })
            .expect("the handshake must carry the presence roster");
        assert_eq!(
            presence_of(presence, client),
            Some(r#"{"user":{"name":"Ada"}}"#),
            "a late joiner must receive the peers already in the room"
        );
    }

    /// Presence belongs to the socket that published it, so a dropped connection takes its
    /// awareness entry with it rather than leaving a phantom peer in the replica.
    #[tokio::test]
    async fn dropping_a_connection_clears_the_presence_it_published() {
        let rooms = Rooms::new();
        let (room, mut rx) = rooms.join("demo").await.expect("join");

        let departing = RelayProtocol::new(Origin::from(1u64));
        let client = ClientID::new(7);
        room.handle(
            &departing,
            &presence_frame(client, r#"{"user":{"name":"Ada"}}"#),
        )
        .await
        .expect("server accepts presence");
        rx.try_recv().expect("presence is fanned out");

        room.forget(&departing).await;

        // The room announces the departure...
        let relayed = rx.try_recv().expect("removal is fanned out");
        let removal = match decode_messages(&relayed.payload).as_slice() {
            [Message::Awareness(update)] => update.clone(),
            other => panic!("expected a single awareness message, got {other:?}"),
        };
        assert_eq!(
            presence_of(&removal, client),
            Some("null"),
            "a cleared peer is announced as a null state"
        );

        // ...and a peer joining afterwards never learns about the departed one at all.
        let frames = room.start_frames().await.expect("handshake encodes");
        for frame in &frames {
            for message in decode_messages(frame) {
                if let Message::Awareness(update) = message {
                    assert!(
                        presence_of(&update, client).is_none(),
                        "a departed peer must not be handed to new joiners"
                    );
                }
            }
        }

        // Clearing twice is a no-op: the connection no longer owns anything.
        room.forget(&departing).await;
        assert!(rx.try_recv().is_err(), "nothing left to announce");
    }

    /// An empty room is evicted, but only once its last connection has actually left.
    #[tokio::test]
    async fn empty_rooms_are_evicted() {
        let rooms = Rooms::new();

        let (_room, rx) = rooms.join("demo").await.expect("join");
        assert_eq!(rooms.len().await, 1);

        // Still connected: leaving must be a no-op.
        rooms.leave("demo").await;
        assert_eq!(
            rooms.len().await,
            1,
            "a room with a live connection must survive"
        );

        drop(rx);
        rooms.leave("demo").await;
        assert_eq!(rooms.len().await, 0);
    }
}
