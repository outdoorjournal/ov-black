// Traveler reading list (/basecamp/reading).
//
// A dedicated magazine rack for the "article" nodes a traveler has saved to
// their itinerary Collections (via the agent's save_link_to_collection, kind
// "article"). Self-scoped like the rest of basecamp: we resolve every trip from
// /me/itineraries, then read each trip's graph and lift out its article nodes,
// so the page spans the whole account rather than a single itinerary. The tiles
// echo the imagery-forward "little magazine" look of the home ItineraryGrid,
// but each one links out to the source article rather than into a trip.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  getItinerary,
  listMyItineraries,
  type MyItinerarySummary,
  type NodeResponse,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { BasecampChrome } from "../_components/BasecampChrome";
import { ReadingList, type ReadingItem } from "./_components/ReadingList";

export const dynamic = "force-dynamic";

export default async function ReadingPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/");
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    redirect("/");
  }

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    notFound();
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const itinerariesResult = await listMyItineraries(api);
  const itineraries: MyItinerarySummary[] = itinerariesResult.ok
    ? itinerariesResult.itineraries
    : [];

  // Read every trip's graph in parallel and lift out its article nodes. A
  // traveler has a handful of trips, so the fan-out is cheap; a failed graph
  // read just contributes nothing rather than sinking the page.
  const perTrip = await Promise.all(
    itineraries.map(async (it) => {
      const graph = await getItinerary(api, it.id);
      if (!graph.ok) return [] as ReadingItem[];
      return graph.nodes
        .filter((n) => n.type === "article" && n.status !== "discarded")
        .map((n) => toReadingItem(n, it));
    }),
  );

  // Flatten in trip order, then drop exact-duplicate links (the same article
  // saved to two trips shows once) while keeping the first occurrence.
  const seen = new Set<string>();
  const items: ReadingItem[] = [];
  for (const item of perTrip.flat()) {
    const key = item.url ?? item.id;
    if (seen.has(key)) continue;
    seen.add(key);
    items.push(item);
  }

  return (
    <BasecampChrome user={headerUserFromSupabase(user)}>
      <ReadingList items={items} />
    </BasecampChrome>
  );
}

// True when a string reads as an http(s) URL — an article's node.title (and,
// when the OpenGraph fetch failed, its snapshot title) is often the raw link,
// so we prefer human-friendly metadata over showing a URL as a headline.
function looksLikeUrl(s: string | undefined | null): boolean {
  if (!s) return false;
  return /^https?:\/\//i.test(s.trim());
}

// The host without the www. prefix — a last-resort label / subline when nothing
// friendlier exists (e.g. "https://www.backpacker.com/…" → "backpacker.com").
function hostLabel(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "") || null;
  } catch {
    return null;
  }
}

function metaString(meta: Record<string, unknown>, key: string): string | undefined {
  const v = meta[key];
  return typeof v === "string" && v.trim() ? v : undefined;
}

// Collapse a raw article node + its owning trip into the flat shape the tiles
// render. Mirrors the card's ArticleBody label precedence:
// note → non-URL snapshot title → publication → host → title.
function toReadingItem(node: NodeResponse, trip: MyItinerarySummary): ReadingItem {
  const meta = node.metadata ?? {};
  const rawSnapshot = meta["snapshot"];
  const snapshot: Record<string, unknown> =
    rawSnapshot && typeof rawSnapshot === "object"
      ? (rawSnapshot as Record<string, unknown>)
      : {};

  const url = metaString(meta, "url") ?? (looksLikeUrl(node.title) ? node.title : null);
  const publication = metaString(meta, "publication") ?? null;
  const note = metaString(meta, "note");
  const snapTitleRaw = typeof snapshot["title"] === "string" ? snapshot["title"] : undefined;
  const snapTitle = looksLikeUrl(snapTitleRaw) ? undefined : snapTitleRaw;
  const coverImage =
    typeof snapshot["cover_image"] === "string" ? snapshot["cover_image"] : null;

  const title = note ?? snapTitle ?? publication ?? hostLabel(url) ?? node.title;
  const subline = publication && publication !== title ? publication : hostLabel(url);

  return {
    id: node.id,
    title,
    publication: subline,
    url: url ?? null,
    coverImage,
    tripId: trip.id,
    tripTitle: trip.title || "Your itinerary",
  };
}
