"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatPrice } from "@/lib/catalog";
import { apiError } from "@/lib/errors";
import { useApi, useThread } from "@/lib/messaging";
import type { Conversation, Message } from "@/lib/types";

export default function ThreadPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { user, loading } = useAuth();
  const router = useRouter();

  const { data: conversation } = useApi<Conversation>(
    user ? `/api/v1/conversations/${id}/` : null,
  );
  const { data: messages, mutate } = useThread(id);

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=/messages/${id}`);
  }, [loading, user, router, id]);

  if (loading || !user) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-12 text-sm text-neutral-500">
        Loading…
      </main>
    );
  }

  return (
    <main className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-2xl flex-col px-4">
      <ThreadHeader conversation={conversation} />
      <MessageList messages={messages} />
      <Composer conversationId={id} onSent={() => mutate()} />
    </main>
  );
}

function ThreadHeader({ conversation }: { conversation?: Conversation }) {
  if (!conversation) {
    return <div className="border-b border-neutral-200 py-4" />;
  }
  return (
    <header className="flex items-center gap-3 border-b border-neutral-200 py-3">
      <Link href="/messages" className="text-neutral-500 hover:text-brand">
        ←
      </Link>
      <Link
        href={`/listings/${conversation.listing.id}`}
        className="h-10 w-10 flex-shrink-0 overflow-hidden rounded-lg bg-neutral-100"
      >
        {conversation.listing.thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={conversation.listing.thumbnail}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : null}
      </Link>
      <div className="min-w-0 flex-1">
        <Link
          href={`/users/${conversation.other_party.id}`}
          className="block truncate text-sm font-semibold hover:text-brand"
        >
          {conversation.other_party.name}
        </Link>
        <Link
          href={`/listings/${conversation.listing.id}`}
          className="block truncate text-xs text-neutral-500 hover:text-brand"
        >
          {conversation.listing.title} ·{" "}
          {formatPrice(conversation.listing.price, conversation.listing.currency)}
        </Link>
      </div>
      <SafetyMenu otherPartyId={conversation.other_party.id} />
    </header>
  );
}

function MessageList({ messages }: { messages?: Message[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages?.length]);

  if (!messages) {
    return <div className="flex-1 py-6 text-sm text-neutral-400">Loading…</div>;
  }
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-neutral-400">
        Say hello 👋
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-2 overflow-y-auto py-4">
      {messages.map((m) => (
        <div
          key={m.id}
          className={`flex ${m.is_mine ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[75%] rounded-2xl px-3.5 py-2 text-sm ${
              m.is_mine
                ? "rounded-br-sm bg-brand text-white"
                : "rounded-bl-sm bg-neutral-100 text-neutral-800"
            }`}
          >
            <p className="whitespace-pre-wrap break-words">{m.body}</p>
            <span
              className={`mt-0.5 block text-right text-[10px] ${
                m.is_mine ? "text-white/70" : "text-neutral-400"
              }`}
            >
              {new Date(m.created_at).toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
              {m.is_mine && m.read_at ? " · Read" : ""}
            </span>
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

function Composer({
  conversationId,
  onSent,
}: {
  conversationId: string;
  onSent: () => void;
}) {
  const { authFetch } = useAuth();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const text = body.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/v1/conversations/${conversationId}/messages/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(apiError(data, "Couldn't send that message."));
      setBody("");
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send that message.");
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="border-t border-neutral-200 py-3">
      {error ? (
        <div className="mb-2">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Write a message…"
          className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border border-neutral-300 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
        />
        <button
          onClick={send}
          disabled={busy || !body.trim()}
          className="inline-flex h-11 items-center justify-center rounded-xl bg-brand px-5 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function SafetyMenu({ otherPartyId }: { otherPartyId: number }) {
  const { authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const block = async () => {
    setOpen(false);
    if (!confirm("Block this user? They won't be able to message you.")) return;
    const res = await authFetch(`/api/v1/users/${otherPartyId}/block/`, {
      method: "POST",
    });
    setNote(res.ok ? "User blocked." : "Couldn't block this user.");
  };

  const report = async () => {
    setOpen(false);
    const reason = prompt("What's the problem with this user?");
    if (reason === null) return;
    const res = await authFetch(`/api/v1/users/${otherPartyId}/report/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    setNote(res.ok ? "Thanks — this user has been reported." : "Couldn't send the report.");
  };

  return (
    <div className="relative flex-shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="px-2 text-lg leading-none text-neutral-400 hover:text-neutral-700"
        aria-label="Conversation options"
      >
        ⋯
      </button>
      {open ? (
        <div className="absolute right-0 top-8 z-10 w-40 overflow-hidden rounded-xl border border-neutral-200 bg-white text-sm shadow-lg">
          <button
            onClick={report}
            className="block w-full px-4 py-2.5 text-left hover:bg-neutral-50"
          >
            Report user
          </button>
          <button
            onClick={block}
            className="block w-full px-4 py-2.5 text-left text-red-600 hover:bg-red-50"
          >
            Block user
          </button>
        </div>
      ) : null}
      {note ? (
        <div className="absolute right-0 top-8 z-10 w-52 rounded-xl border border-neutral-200 bg-white p-3 text-xs text-neutral-600 shadow-lg">
          {note}
          <button
            onClick={() => setNote(null)}
            className="mt-2 block font-medium text-brand"
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}
