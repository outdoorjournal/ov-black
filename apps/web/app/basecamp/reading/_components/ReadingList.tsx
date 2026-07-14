"use client";

// The reading-list surface for /basecamp/reading — a rack of "little magazine"
// tiles, one per article a traveler has saved across their trips.
//
// The tile shape is deliberately the home ItineraryGrid card: an imagery-forward
// hero, a serif headline and its publication resting on a scrim at the foot, a
// small trip tag up top so an article always remembers which journey it belongs
// to. When an article has no cover the hero falls back to a stable per-item
// gradient so the rack never shows a floating, image-less card. Each tile links
// out to the source article in a new tab; a link-less save renders as a plain
// (non-navigating) tile rather than a dead link.

export type ReadingItem = {
  id: string;
  title: string;
  publication: string | null;
  url: string | null;
  coverImage: string | null;
  tripId: string;
  tripTitle: string;
};

export type ReadingListProps = {
  items: ReadingItem[];
};

// Muted, editorial placeholder gradients — a stable pick per item so an
// image-less tile still reads as a considered object, not an empty frame.
// Same palette as the home ItineraryGrid so the two racks feel of a piece.
const PLACEHOLDER_GRADIENTS = [
  "linear-gradient(150deg, #2f3a34 0%, #55655c 55%, #cdbfa6 100%)", // pine → sand
  "linear-gradient(150deg, #3a3340 0%, #6a5f74 55%, #d3c4b4 100%)", // plum → linen
  "linear-gradient(150deg, #2c3a45 0%, #566d78 55%, #c9c1ad 100%)", // slate → stone
  "linear-gradient(150deg, #45362c 0%, #7a5f49 55%, #d8c6a8 100%)", // umber → wheat
  "linear-gradient(150deg, #2f4038 0%, #5c7061 55%, #c6c8b0 100%)", // moss → sage
];

function placeholderFor(id: string): string {
  let sum = 0;
  for (let i = 0; i < id.length; i += 1) sum += id.charCodeAt(i);
  return PLACEHOLDER_GRADIENTS[sum % PLACEHOLDER_GRADIENTS.length]!;
}

export function ReadingList({ items }: ReadingListProps) {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-10 sm:px-10">
      <header className="flex flex-col gap-3">
        <h2 className="font-serif text-4xl leading-[1.1] tracking-tight text-ink sm:text-5xl">
          Reading list
        </h2>
        <p className="max-w-prose font-sans text-sm leading-relaxed text-ink/60">
          The articles you&rsquo;ve saved along the way — dispatches, guides and
          longreads gathered from every trip, kept together like a little stack
          of magazines.
        </p>
      </header>

      {items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <ReadingCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReadingCard({ item }: { item: ReadingItem }) {
  const cover = item.coverImage ?? undefined;

  const inner = (
    <>
      {/* The cover art, layered over the gradient. On a load error it hides
          itself so the gradient shows through rather than a broken frame. */}
      {cover ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote OpenGraph URL; next/image loaders unneeded, degrades to the gradient on error.
        <img
          src={cover}
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

      {/* Trip tag, top-left — which journey this dispatch belongs to. */}
      <span className="absolute left-4 top-4 z-10 max-w-[calc(100%-2rem)] truncate rounded-full bg-paper/90 px-2.5 py-1 font-sans text-[10px] uppercase tracking-label text-ink/80 backdrop-blur-sm">
        {item.tripTitle}
      </span>

      <div className="relative z-10 flex flex-col gap-1.5 p-5">
        <h3 className="font-serif text-2xl leading-tight tracking-tight text-paper sm:text-[1.7rem]">
          {item.title}
        </h3>
        <div className="flex items-center justify-between gap-3">
          <span className="min-w-0 truncate text-[11px] uppercase tracking-label text-paper/75">
            {item.publication ?? "Saved reading"}
          </span>
          {item.url ? (
            <span className="shrink-0 border-b border-transparent text-[11px] uppercase tracking-label text-paper/85 transition-colors group-hover:border-brand group-hover:text-brand">
              Read →
            </span>
          ) : null}
        </div>
      </div>
    </>
  );

  const shell =
    "group relative flex aspect-[4/5] flex-col justify-end overflow-hidden rounded-lg border border-ink/10 text-paper shadow-sheet transition-all duration-200 sm:aspect-[5/6]";
  const style = { backgroundImage: placeholderFor(item.id), backgroundSize: "cover" };

  // A saved link opens its source in a new tab; a link-less save is inert.
  if (item.url) {
    return (
      <a
        href={item.url}
        target="_blank"
        rel="noreferrer"
        className={`${shell} hover:-translate-y-1 hover:shadow-sheet-lg`}
        style={style}
      >
        {inner}
      </a>
    );
  }

  return (
    <div className={shell} style={style}>
      {inner}
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
