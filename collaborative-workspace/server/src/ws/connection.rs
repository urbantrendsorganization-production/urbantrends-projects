//! One connection = one peer's y-sync session against a room's Yrs replica.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::extract::ws::{Message as WsMessage, WebSocket};
use bytes::Bytes;
use futures_util::stream::SplitSink;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::broadcast::Receiver;
use tokio::sync::broadcast::error::RecvError;
use yrs::Origin;
use yrs::sync::protocol::Error as ProtocolError;
use yrs::updates::encoder::Encode;

use crate::sync::{RelayProtocol, Room, RoomUpdate};

/// Distinguishes connections so a peer can be told apart from its own echo. Room-agnostic
/// and process-local; it is never written into the document.
static NEXT_CONNECTION_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, thiserror::Error)]
pub enum ConnectionError {
    #[error("websocket transport failed: {0}")]
    Transport(#[from] axum::Error),

    #[error("y-sync protocol failed: {0}")]
    Protocol(#[from] ProtocolError),
}

/// Drives a single peer to completion. Returns once the socket closes.
pub async fn run(
    socket: WebSocket,
    room: Arc<Room>,
    inbox: Receiver<RoomUpdate>,
) -> Result<(), ConnectionError> {
    let origin = Origin::from(NEXT_CONNECTION_ID.fetch_add(1, Ordering::Relaxed));
    let protocol = RelayProtocol::new(origin);

    let result = relay(socket, &room, &protocol, inbox).await;

    // However the session ended — clean close, error, or the peer vanishing mid-frame —
    // this peer's presence goes with it. Runs on every exit path, which is why the loop
    // lives in its own function.
    room.forget(&protocol).await;

    result
}

async fn relay(
    socket: WebSocket,
    room: &Room,
    protocol: &RelayProtocol,
    mut inbox: Receiver<RoomUpdate>,
) -> Result<(), ConnectionError> {
    let (mut sink, mut stream) = socket.split();

    // Initial sync: the server opens with its state vector and the current presence
    // roster, the peer answers with the updates the server is missing and asks for its own.
    for frame in room.start_frames().await? {
        if !send(&mut sink, frame).await {
            return Ok(());
        }
    }

    'session: loop {
        tokio::select! {
            frame = stream.next() => {
                match frame {
                    Some(Ok(WsMessage::Binary(data))) => {
                        // Applying to the replica fires the room's observers, which is
                        // what fans this update out to the other peers.
                        let replies = room.handle(protocol, &data).await?;
                        for reply in replies {
                            if !send(&mut sink, reply.encode_v1().into()).await {
                                break 'session;
                            }
                        }
                    }
                    // Axum answers pings itself; text frames are not part of this protocol.
                    Some(Ok(_)) => {}
                    Some(Err(err)) => return Err(err.into()),
                    None => break 'session,
                }
            }

            relayed = inbox.recv() => {
                match relayed {
                    Ok(update) => {
                        // Skip our own echo — this peer already has what it just sent.
                        if update.origin.as_ref() == Some(protocol.origin()) {
                            continue;
                        }
                        if !send(&mut sink, update.payload).await {
                            break 'session;
                        }
                    }
                    // Backpressure: this peer fell far enough behind that the fan-out
                    // dropped frames for it. Rather than leaving it silently stale, restart
                    // the handshake so it re-converges from the replica.
                    Err(RecvError::Lagged(missed)) => {
                        tracing::warn!(missed, "connection lagged; forcing resync");
                        if !send(&mut sink, room.resync_payload().await).await {
                            break 'session;
                        }
                    }
                    Err(RecvError::Closed) => break 'session,
                }
            }
        }
    }

    Ok(())
}

/// Writes one frame to the peer, reporting whether the connection is still usable.
///
/// A write failure means the peer is already gone — typically a tab closing while a
/// broadcast was in flight. That is an ordinary end of connection, not a fault, so it is
/// logged at debug and ends the session quietly.
async fn send(sink: &mut SplitSink<WebSocket, WsMessage>, payload: Bytes) -> bool {
    match sink.send(WsMessage::Binary(payload)).await {
        Ok(()) => true,
        Err(err) => {
            tracing::debug!(error = %err, "peer went away mid-send");
            false
        }
    }
}
