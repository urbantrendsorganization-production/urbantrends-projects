"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/catalog";
import { useConversations } from "@/lib/messaging";
import type { Conversation } from "@/lib/types";

export default function MessagesPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const { data, isLoading } = useConversations();

  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=/messages");
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12 text-sm text-neutral-500">
        Loading…
      </main>
    );
  }

  const conversations = data?.results ?? [];

  return (
    <main className="mx-auto max-w-2xl space-y-5 px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Messages</h1>

      {isLoading && !data ? (
        <p className="text-sm text-neutral-500">Loading conversations…</p>
      ) : conversations.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-neutral-300 py-16 text-center">
          <p className="text-sm text-neutral-500">No conversations yet.</p>
          <Link
            href="/"
            className="mt-2 inline-block text-sm font-medium text-brand hover:underline"
          >
            Browse listings →
          </Link>
        </div>
      ) : (
        <ul className="divide-y divide-neutral-200 overflow-hidden rounded-2xl border border-neutral-200 bg-white">
          {conversations.map((c) => (
            <ConversationRow key={c.id} conversation={c} />
          ))}
        </ul>
      )}
    </main>
  );
}

function ConversationRow({ conversation: c }: { conversation: Conversation }) {
  const unread = c.unread > 0;
  return (
    <li>
      <Link
        href={`/messages/${c.id}`}
        className="flex items-center gap-3 p-3 transition hover:bg-neutral-50"
      >
        <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-xl bg-neutral-100">
          {c.listing.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={c.listing.thumbnail}
              alt=""
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[10px] text-neutral-400">
              No photo
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className={`truncate text-sm ${unread ? "font-bold" : "font-medium"}`}>
              {c.other_party.name}
            </span>
            <span className="flex-shrink-0 text-xs text-neutral-400">
              {c.last_message_at ? relativeTime(c.last_message_at) : ""}
            </span>
          </div>
          <p className="truncate text-xs text-neutral-500">{c.listing.title}</p>
          <p
            className={`truncate text-sm ${
              unread ? "font-medium text-neutral-800" : "text-neutral-500"
            }`}
          >
            {c.last_message?.body ?? (
              <span className="italic text-neutral-400">No messages yet</span>
            )}
          </p>
        </div>

        <div className="flex flex-shrink-0 flex-col items-end gap-1">
          <span className="text-xs font-semibold text-brand">
            {formatPrice(c.listing.price, c.listing.currency)}
          </span>
          {unread ? (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-brand px-1.5 text-xs font-semibold text-white">
              {c.unread}
            </span>
          ) : null}
        </div>
      </Link>
    </li>
  );
}

/** Compact "3h", "2d" style relative time. */
function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
