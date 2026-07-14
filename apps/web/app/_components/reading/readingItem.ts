// Shared shape + extraction for the reading list — the "article" nodes a
// traveler has saved to their itinerary Collection(s). Kept framework-free so
// both the server-rendered basecamp rack (cross-trip) and the client-side
// itinerary shell page (this trip's store) produce items the same way.

import type { NodeResponse } from "@ov-black/api-client";

import { MOODS, type MoodId } from "@/lib/atmos/moods";

export type ReadingItem = {
  id: string;
  title: string;
  publication: string | null;
  url: string | null;
  coverImage: string | null;
  // Every graph node this tile stands for — usually one, but the basecamp
  // rack dedupes the same article saved across trips into a single tile, so
  // removing it must soft-discard each underlying node.
  refs: ReadingItemRef[];
};

export type ReadingItemRef = {
  itineraryId: string;
  nodeId: string;
};

// True when a string reads as an http(s) URL — an article's node.title (and,
// when the OpenGraph fetch failed, its snapshot title) is often the raw link,
// so we prefer human-friendly metadata over showing a URL as a headline.
export function looksLikeUrl(s: string | undefined | null): boolean {
  if (!s) return false;
  return /^https?:\/\//i.test(s.trim());
}

// The host without the www. prefix — a last-resort label / subline when nothing
// friendlier exists (e.g. "https://www.backpacker.com/…" → "backpacker.com").
export function hostLabel(url: string | null): string | null {
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

// True when a node is a reading-list article worth showing (not discarded).
export function isReadingArticle(node: NodeResponse): boolean {
  return node.type === "article" && node.status !== "discarded";
}

// Collapse a raw article node into the flat shape the tiles render. Mirrors the
// card's ArticleBody label precedence:
// note → non-URL snapshot title → publication → host → title.
export function toReadingItem(node: NodeResponse): ReadingItem {
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
    refs: [{ itineraryId: node.itinerary_id, nodeId: node.id }],
  };
}

// Deduped by link (the same article saved to two trips shows once), keeping
// the first occurrence but merging every duplicate's node refs into it — so a
// remove from the cross-trip basecamp rack discards all copies, not just the
// one that happened to render.
export function dedupeReadingItems(items: ReadingItem[]): ReadingItem[] {
  const byKey = new Map<string, ReadingItem>();
  const out: ReadingItem[] = [];
  for (const item of items) {
    const key = item.url ?? item.id;
    const kept = byKey.get(key);
    if (kept) {
      kept.refs.push(...item.refs);
      continue;
    }
    const copy = { ...item, refs: [...item.refs] };
    byKey.set(key, copy);
    out.push(copy);
  }
  return out;
}

// Photographic fallback for a tile with no OpenGraph cover — a considered
// editorial image rather than a flat gradient. We first try to match the
// headline/publication against the shared mood keywords (a "patagonia" longread
// gets the glacial hero); failing that we pick a stable one by hashing the id so
// a given article always wears the same photo.
const FALLBACK_MOODS: MoodId[] = [
  "alpine",
  "amber",
  "tidal",
  "verdant",
  "onyx",
  "ember",
  "glacial",
  "riviera",
];

function sized(url: string): string {
  // Tiles don't need the 2400px full-bleed hero; ask the CDN for a lighter frame
  // (no-op for the non-Unsplash olympus URL, which has no width param).
  return url.replace(/w=\d+/, "w=1200");
}

export function moodImageFor(text: string, seed: string): string {
  const hay = text.toLowerCase();
  for (const entry of Object.values(MOODS)) {
    if (entry.keywords.some((k) => hay.includes(k))) return sized(entry.imageUrl);
  }
  let sum = 0;
  for (let i = 0; i < seed.length; i += 1) sum += seed.charCodeAt(i);
  const pick = FALLBACK_MOODS[sum % FALLBACK_MOODS.length]!;
  return sized(MOODS[pick].imageUrl);
}
