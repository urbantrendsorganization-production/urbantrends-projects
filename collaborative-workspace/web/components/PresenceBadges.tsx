"use client";

import { initials, type RosterEntry } from "@/lib/collab/presence";

import styles from "./PresenceBadges.module.css";

const MAX_VISIBLE = 5;

/**
 * Who is in the room, derived from awareness membership.
 *
 * Purely a projection of the presence channel — a peer appears when its awareness entry
 * does and disappears when the entry is withdrawn or times out. There is no roster stored
 * anywhere.
 */
export function PresenceBadges({ roster }: { roster: readonly RosterEntry[] }) {
  const visible = roster.slice(0, MAX_VISIBLE);
  const overflow = roster.length - visible.length;

  return (
    <div className={styles.badges} aria-label={`${roster.length} connected`}>
      {visible.map((entry) => (
        <span
          key={entry.clientId}
          className={styles.badge}
          style={{ background: entry.user.color }}
          title={entry.isLocal ? `${entry.user.name} (you)` : entry.user.name}
          data-local={entry.isLocal || undefined}
        >
          {initials(entry.user.name)}
        </span>
      ))}

      {overflow > 0 && (
        <span className={`${styles.badge} ${styles.overflow}`} title={`${overflow} more`}>
          +{overflow}
        </span>
      )}
    </div>
  );
}
