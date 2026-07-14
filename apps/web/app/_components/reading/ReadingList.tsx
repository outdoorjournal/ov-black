"use client";

// The reading-list surface — a rack of "little magazine" tiles, one per article
// a traveler has saved. Shared by the cross-trip basecamp rack and the per-trip
// itinerary shell page; both hand it a flat ReadingItem[].
//
// Layout is deliberately magazine-shaped: the first couple of pieces run large
// across the top (imagery-forward hero, serif headline + publication on a scrim
// at the foot), then the rest fall into a denser grid of smaller tiles. Every
// tile carries a photo — the article's own OpenGraph cover when we have one,
// else a mood image chosen from the headline — so the rack never shows a bare
// gradient. Each tile links out to the source in a new tab; a link-less save
// renders as a plain (non-navigating) tile rather than a dead link.

import { moodImageFor, type ReadingItem } from "./readingItem";

export type { ReadingItem };

export type ReadingListProps = {
  items: ReadingItem[];
  // The itinerary shell already supplies its own chrome/title; basecamp wants
  // the full masthead. Default is the standalone masthead.
  heading?: boolean;
  // Soft-remove (discard) an item. When supplied, each tile grows a quiet
  // hover-revealed × in its corner; the caller owns the optimistic update and
  // the PATCH. Absent (e.g. read-only embeds), tiles render exactly as before.
  onRemove?: (item: ReadingItem) => void;
};

export function ReadingList({ items, heading = true, onRemove }: ReadingListProps) {
  const featured = items.slice(0, 2);
  const rest = items.slice(2);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-10 sm:px-10">
      {heading ? (
        <header className="flex flex-col gap-3">
          <h2 className="font-serif text-4xl leading-[1.1] tracking-tight text-ink sm:text-5xl">
            Reading list
          </h2>
          <p className="max-w-prose font-sans text-sm leading-relaxed text-ink/60">
            The articles you&rsquo;ve saved along the way — dispatches, guides
            and longreads, kept together like a little stack of magazines.
          </p>
        </header>
      ) : null}

      {items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="flex flex-col gap-5">
          {/* Featured row runs large; ~40% smaller than before by going three-up
              on desktop rather than two. The rest fall into a denser grid. */}
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-3">
            {featured.map((item) => (
              <ReadingCard key={item.id} item={item} size="large" onRemove={onRemove} />
            ))}
          </div>
          {rest.length > 0 ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-5">
              {rest.map((item) => (
                <ReadingCard key={item.id} item={item} size="small" onRemove={onRemove} />
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function ReadingCard({
  item,
  size,
  onRemove,
}: {
  item: ReadingItem;
  size: "large" | "small";
  onRemove?: ((item: ReadingItem) => void) | undefined;
}) {
  const large = size === "large";
  // A photo, always: the article's own cover sits on top; a mood image chosen
  // from the headline sits beneath it and shows through if the cover errors.
  const mood = moodImageFor(`${item.title} ${item.publication ?? ""}`, item.id);

  const inner = (
    <>
      {/* Base layer: the mood photo (always present). */}
      {/* eslint-disable-next-line @next/next/no-img-element -- remote CDN URL; next/image loaders unneeded. */}
      <img
        src={mood}
        alt=""
        className="absolute inset-0 h-full w-full object-cover"
        aria-hidden
      />

      {/* The article's own OpenGraph cover, layered over the mood photo. On a
          load error it hides itself so the mood image shows through. */}
      {item.coverImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote OpenGraph URL; degrades to the mood image on error.
        <img
          src={item.coverImage}
          alt=""
          className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : null}

      {/* Legibility scrim — deep at the foot where the type sits, clear up top. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to top, rgba(10,10,10,0.82) 0%, rgba(10,10,10,0.35) 38%, rgba(10,10,10,0) 68%)",
        }}
      />

      {/* Title + metadata — always present, kept legible over the scrim.
          Serif throughout for the editorial, magazine feel. */}
      <div className={`relative z-10 flex flex-col ${large ? "gap-1.5 p-4" : "gap-1 p-3"}`}>
        <h3
          className={`font-serif leading-tight tracking-tight text-paper ${
            large ? "text-lg sm:text-xl" : "text-sm sm:text-[0.95rem]"
          }`}
        >
          {item.title}
        </h3>
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={`min-w-0 truncate font-serif italic text-paper/80 ${
              large ? "text-sm" : "text-xs"
            }`}
          >
            {item.publication ?? "Saved reading"}
          </span>
          {item.url ? (
            <span className="shrink-0 border-b border-transparent font-serif text-xs italic text-paper/85 transition-colors group-hover:border-brand group-hover:text-brand">
              Read →
            </span>
          ) : null}
        </div>
      </div>
    </>
  );

  const shell =
    "group relative flex flex-col justify-end overflow-hidden rounded-lg border border-ink/10 text-paper shadow-sheet transition-all duration-200 " +
    (large ? "aspect-[4/5] sm:aspect-[5/6]" : "aspect-[3/4]") +
    (item.url ? " hover:-translate-y-1 hover:shadow-sheet-lg" : "");

  // The tile is a div with a stretched link over it (rather than an anchor
  // wrapping everything) so the remove button isn't an interactive element
  // nested inside another. A link-less save simply has no overlay.
  return (
    <div className={shell}>
      {inner}
      {item.url ? (
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          aria-label={item.title}
          className="absolute inset-0 z-20"
        />
      ) : null}
      {onRemove ? (
        <button
          type="button"
          aria-label={`Remove “${item.title}” from your reading list`}
          title="Remove from reading list"
          onClick={() => onRemove(item)}
          // Quiet by design: invisible until the tile is hovered (or the
          // button is keyboard-focused); faintly present on touch screens,
          // where there is no hover to reveal it.
          className="absolute right-2 top-2 z-30 flex h-7 w-7 items-center justify-center rounded-full bg-ink/45 text-paper/90 opacity-0 backdrop-blur-sm transition-opacity duration-200 hover:bg-ink/70 hover:text-paper focus-visible:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-60"
        >
          <svg
            viewBox="0 0 12 12"
            className="h-3 w-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            aria-hidden
          >
            <path d="M2 2l8 8M10 2l-8 8" />
          </svg>
        </button>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-ink/15 bg-paper/60 p-12 text-center">
      <h3 className="font-serif text-2xl tracking-tight text-ink">
        Nothing on the rack yet
      </h3>
      <p className="max-w-sm font-sans text-sm leading-relaxed text-ink/55">
        Share a link with your concierge — a trail write-up, a chef&rsquo;s
        profile, a neighbourhood guide — and it&rsquo;ll be waiting here as part
        of your reading list.
      </p>
    </div>
  );
}
