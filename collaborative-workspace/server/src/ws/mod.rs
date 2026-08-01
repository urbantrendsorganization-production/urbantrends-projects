//! WebSocket transport: upgrade handling and the per-connection relay loop.

mod connection;

use axum::extract::ws::WebSocketUpgrade;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

use crate::sync::Rooms;

/// Hard cap on a single inbound frame. Cheap first line of defence — a peer cannot make
/// the server buffer an arbitrarily large "update".
const MAX_FRAME_BYTES: usize = 1024 * 1024;

/// `GET /ws/{room}` — upgrade to a y-sync relay session for `room`.
pub async fn upgrade(
    ws: WebSocketUpgrade,
    Path(room): Path<String>,
    State(rooms): State<Rooms>,
) -> Response {
    // Phase 1 has no auth: room joins are anonymous. Authenticating the handshake is
    // step 1 of the lifecycle in server/CLAUDE.md and lands in a later phase — until then
    // this server must not be exposed beyond localhost.
    if !is_valid_room_name(&room) {
        return (StatusCode::BAD_REQUEST, "invalid room name").into_response();
    }

    ws.max_message_size(MAX_FRAME_BYTES)
        .on_upgrade(move |socket| async move {
            let (handle, rx) = match rooms.join(&room).await {
                Ok(joined) => joined,
                Err(err) => {
                    tracing::error!(room = %room, error = %err, "failed to join room");
                    return;
                }
            };
            tracing::info!(room = %room, "connection opened");

            if let Err(err) = connection::run(socket, handle, rx).await {
                tracing::warn!(room = %room, error = %err, "connection closed with error");
            }

            rooms.leave(&room).await;
            tracing::info!(room = %room, "connection closed");
        })
}

/// Room ids come straight off the URL, so they are validated rather than trusted.
fn is_valid_room_name(room: &str) -> bool {
    !room.is_empty()
        && room.len() <= 64
        && room
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

#[cfg(test)]
mod tests {
    use super::is_valid_room_name;

    #[test]
    fn accepts_ordinary_room_names() {
        for name in ["demo", "room-1", "a_b", "A1"] {
            assert!(is_valid_room_name(name), "{name} should be accepted");
        }
    }

    #[test]
    fn rejects_empty_oversized_and_traversing_names() {
        assert!(!is_valid_room_name(""));
        assert!(!is_valid_room_name(&"x".repeat(65)));
        assert!(!is_valid_room_name("../etc/passwd"));
        assert!(!is_valid_room_name("room/../other"));
        assert!(!is_valid_room_name("room name"));
    }
}
