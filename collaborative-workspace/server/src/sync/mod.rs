//! CRDT sync: the y-sync protocol binding and the per-room Yrs replicas.

pub mod protocol;
pub mod room;

pub use protocol::RelayProtocol;
pub use room::{Room, RoomUpdate, Rooms};
