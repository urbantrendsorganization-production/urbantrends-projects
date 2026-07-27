"use client";

// Client-side messaging data layer: SWR hooks bound to the authenticated fetch
// so tokens (and refresh-on-401) come for free from the auth context.
import useSWR, { type SWRConfiguration } from "swr";

import { useAuth } from "@/lib/auth";
import type { Conversation, Message } from "@/lib/types";

/** SWR hook that fetches an API path with the access token attached. */
export function useApi<T>(
  path: string | null,
  options?: SWRConfiguration<T>,
) {
  const { authFetch } = useAuth();
  return useSWR<T>(
    path,
    async (p: string) => {
      const res = await authFetch(p);
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      return (await res.json()) as T;
    },
    options,
  );
}

/** The signed-in user's total unread messages (navbar badge). Polls slowly. */
export function useUnreadCount(enabled: boolean) {
  const { data } = useApi<{ count: number }>(
    enabled ? "/api/v1/conversations/unread_count/" : null,
    { refreshInterval: 20000 },
  );
  return data?.count ?? 0;
}

/** The inbox: every thread, newest activity first. Polls while open. */
export function useConversations() {
  return useApi<{ results: Conversation[] }>("/api/v1/conversations/", {
    refreshInterval: 15000,
  });
}

/** A single thread's messages. Polls frequently — this is the "live" chat. */
export function useThread(id: string | number) {
  return useApi<Message[]>(`/api/v1/conversations/${id}/messages/`, {
    refreshInterval: 5000,
  });
}
