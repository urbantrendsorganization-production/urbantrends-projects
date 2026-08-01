-- Durable document state.
--
-- Two tables on purpose: a snapshot is the whole document re-serialised, which is far too
-- expensive to write every flush interval while someone is dragging a rectangle. The log
-- absorbs those frequent small writes; the snapshot bounds how much of it ever has to be
-- read back. See `Room::flush_locked` for the compaction rule that ties them together.
--
-- Only the document channel is stored here. Awareness/presence is ephemeral and has no
-- table by design.

-- One row per room: the whole document as a single yrs update, plus the log watermark it
-- already subsumes.
CREATE TABLE documents (
    room         TEXT        PRIMARY KEY,
    snapshot     BYTEA       NOT NULL,
    -- Every `document_updates.seq <= snapshot_seq` is already folded into `snapshot`.
    snapshot_seq BIGINT      NOT NULL,
    -- Encoding of `snapshot`. Versioned per row rather than globally so two server builds
    -- can coexist during a rolling deploy.
    format       SMALLINT    NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Updates written since the room's last snapshot. Each row is one flush's worth of edits,
-- already merged, not one row per keystroke.
--
-- Deliberately no foreign key to `documents`: a brand-new room appends to the log before it
-- ever has a snapshot row, and ordering the two writes to satisfy a constraint would buy
-- nothing. Compaction deletes these rows by watermark, so they cannot outlive their
-- document.
CREATE TABLE document_updates (
    room       TEXT        NOT NULL,
    seq        BIGSERIAL,
    payload    BYTEA       NOT NULL,
    format     SMALLINT    NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (room, seq)
);

-- Cold load reads the tail of one room's log: `WHERE room = $1 AND seq > $2 ORDER BY seq`.
-- The primary key already covers it; this index exists only to make the compaction delete
-- (`WHERE room = $1 AND seq <= $2`) a range scan on the same shape.
CREATE INDEX document_updates_room_seq_idx ON document_updates (room, seq);
