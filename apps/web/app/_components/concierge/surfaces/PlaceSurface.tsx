"use client";

// The place brief — what a tapped PlaceChip opens.
//
// Everything here is server-composed by POST /places/brief: Google resolves
// the loose place string (far more forgiving than client-side geocoding),
// photos arrive as signed proxy tokens, and the texture blocks (CIA World
// Factbook, Wikipedia) are best-effort nullables the layout simply omits.
// The chip's old Mapbox-geocode path survives only as the popover fallback
// outside ChatShell.

import { useEffect, useState } from "react";

import { placePhotoUrl } from "@/app/_components/itinerary-graph/model/placePhoto";
import { fetchPlaceBrief } from "@/lib/chat/placeBrief";
import type { PlaceBrief } from "@ov-black/api-client";

import { SurfaceMap } from "./SurfaceMap";

export type PlaceSurfaceProps = {
  label: string;
  query: string;
};

type BriefState =
  | { phase: "loading" }
  | { phase: "ready"; brief: PlaceBrief }
  | { phase: "missing" };

export function PlaceSurface({ label, query }: PlaceSurfaceProps) {
  const [state, setState] = useState<BriefState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    void fetchPlaceBrief(query).then((brief) => {
      if (cancelled) return;
      setState(brief ? { phase: "ready", brief } : { phase: "missing" });
    });
    return () => {
      cancelled = true;
    };
  }, [query]);

  if (state.phase === "loading") {
    return (
      <p className="px-6 py-8 font-sans text-[13px] text-ink/50" data-testid="place-surface-loading">
        Composing the brief for {label}…
      </p>
    );
  }

  if (state.phase === "missing") {
    return (
      <p className="px-6 py-8 font-sans text-[13px] text-ink/50" data-testid="place-surface-missing">
        {label} resisted the atlas — we couldn&apos;t pin it down just now.
      </p>
    );
  }

  const { resolved, factbook, wikipedia } = state.brief;
  const photos = (resolved.photo_tokens ?? [])
    .map((token) => placePhotoUrl(token))
    .filter((url): url is string => Boolean(url));
  const summary = resolved.editorial_summary ?? wikipedia?.extract ?? null;

  return (
    <div data-testid="place-surface">
      <SurfaceMap markers={[[resolved.lng, resolved.lat]]} />

      <div className="px-6 py-5">
        <h2 className="font-serif text-2xl leading-snug text-ink">{resolved.name}</h2>
        {resolved.formatted_address ? (
          <p className="mt-1 font-sans text-[12px] text-ink/50">{resolved.formatted_address}</p>
        ) : null}

        {summary ? (
          <p className="mt-4 font-serif text-[15px] leading-relaxed text-ink/80">{summary}</p>
        ) : null}

        {photos.length > 0 ? (
          <div className="mt-4 grid grid-cols-3 gap-2" data-testid="place-surface-photos">
            {photos.map((url) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={url}
                src={url}
                alt={resolved.name}
                className="h-20 w-full rounded-sm object-cover ring-1 ring-ink/10"
              />
            ))}
          </div>
        ) : null}

        {wikipedia && wikipedia.extract !== summary ? (
          <p className="mt-4 font-sans text-[13px] leading-relaxed text-ink/65">
            {wikipedia.extract}
          </p>
        ) : null}

        {factbook ? <FactbookBlock factbook={factbook} /> : null}

        <div className="mt-5 flex flex-wrap gap-x-5 gap-y-1">
          <a
            href={resolved.maps_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-sans text-[12px] text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand"
          >
            Open in Google Maps
          </a>
          {wikipedia?.url ? (
            <a
              href={wikipedia.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-sans text-[12px] text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand"
            >
              Read more on Wikipedia
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function FactbookBlock({
  factbook,
}: {
  factbook: NonNullable<PlaceBrief["factbook"]>;
}) {
  const rows: Array<[string, string]> = [];
  if (factbook.climate) rows.push(["Climate", factbook.climate]);
  if (factbook.terrain) rows.push(["Terrain", factbook.terrain]);
  if (factbook.languages) rows.push(["Languages", factbook.languages]);
  if (factbook.population) rows.push(["Population", factbook.population]);
  if (factbook.capital) rows.push(["Capital", factbook.capital]);
  if (rows.length === 0 && !factbook.background) return null;

  return (
    <section className="mt-6" data-testid="place-surface-factbook">
      <h3 className="font-sans text-[10px] uppercase tracking-[0.22em] text-ink/45">
        {factbook.country_name} — from the CIA World Factbook
      </h3>
      {factbook.background ? (
        <p className="mt-2 font-sans text-[13px] leading-relaxed text-ink/65">
          {factbook.background}
        </p>
      ) : null}
      {rows.length > 0 ? (
        <dl className="mt-3 space-y-1.5">
          {rows.map(([term, detail]) => (
            <div key={term} className="grid grid-cols-[86px_1fr] gap-x-3">
              <dt className="font-sans text-[11px] uppercase tracking-[0.14em] text-ink/40">
                {term}
              </dt>
              <dd className="font-sans text-[13px] leading-snug text-ink/70">{detail}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}
