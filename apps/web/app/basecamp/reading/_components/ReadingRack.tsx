"use client";

// Client shell for the basecamp reading rack: the server page fetches and
// dedupes the cross-trip items, this owns the one interaction — the quiet
// per-tile remove. Removal is the graph's soft-discard (status → `discarded`,
// reversible), applied optimistically: the tile disappears at once, the PATCH
// runs behind it, and the tile returns only if every underlying node refused.
// A deduped tile can stand for the same article saved on several trips, so a
// remove discards each ref — otherwise the surviving copy would resurface the
// "removed" article on the next visit.

import { useMemo, useState } from "react";

import { createApiClient, updateNodeStatus } from "@ov-black/api-client";

import { createBrowserSupabase } from "@/lib/supabase/client";
import { ReadingList } from "@/app/_components/reading/ReadingList";
import type { ReadingItem } from "@/app/_components/reading/readingItem";

export function ReadingRack({
  items,
  apiBaseUrl,
  accessToken,
}: {
  items: ReadingItem[];
  apiBaseUrl: string;
  accessToken: string;
}) {
  const [removedIds, setRemovedIds] = useState<ReadonlySet<string>>(new Set());

  // Token resolved per-request from the live browser session (falling back to
  // the SSR token), so a rack left open past the ~1h TTL still writes.
  const api = useMemo(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return createApiClient({
      baseUrl: apiBaseUrl,
      accessToken: async () => {
        if (supabase) {
          const {
            data: { session },
          } = await supabase.auth.getSession();
          if (session?.access_token) return session.access_token;
        }
        return accessToken;
      },
    });
  }, [apiBaseUrl, accessToken]);

  const visible = items.filter((item) => !removedIds.has(item.id));

  const remove = (item: ReadingItem) => {
    setRemovedIds((prev) => new Set(prev).add(item.id));
    void Promise.all(
      item.refs.map((ref) =>
        updateNodeStatus(api, {
          itineraryId: ref.itineraryId,
          nodeId: ref.nodeId,
          status: "discarded",
        }),
      ),
    ).then((results) => {
      // Any surviving copy means the article is still on the account — put the
      // tile back rather than pretend it's gone.
      if (results.some((r) => !r.ok)) {
        setRemovedIds((prev) => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
      }
    });
  };

  return <ReadingList items={visible} onRemove={remove} />;
}
