"use client";

// Inline location chip. The agent references a place mid-sentence as a markdown
// link with a `place:` scheme — `[Fiskardo](place:Fiskardo)` — and ProseMessage
// swaps the anchor for this component. It renders as a restrained pill inside
// the prose. Inside ChatShell (where SurfaceContext provides an opener),
// tapping it opens the place brief in the drawer beside the chat — resolution
// happens server-side there, which handles the loose place strings the agent
// writes far better than client geocoding. Outside the chat shell (concierge
// panel, human thread) it falls back to the original inline mini-map popover.
//
// Constraints that shaped this:
//   * It lives inside a markdown <p>, so the whole subtree is inline elements
//     (span/button) — never a <div> — to avoid invalid nesting / hydration warns.
//   * Geocoding (fallback path only) is lazy: nothing hits the network until
//     the first expand; lib/chat/geocode memoises per query.
//   * No Mapbox token, or an unresolvable place, degrades to a quiet caption —
//     the chip still marks the place, it just can't draw a map.

import { MapPin } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import {
  getMapboxToken,
  loadMapbox,
  type MapboxMap,
} from "@/app/_components/itinerary-graph/model/mapbox";
import type { GeocodeResult } from "@/lib/chat/geocode";
import { resolvePlacePoint } from "@/lib/chat/placeBrief";
import { cn } from "@/lib/utils";

import { useSurfaceOpener } from "@/app/_components/concierge/surfaces/SurfaceContext";

export type PlaceChipProps = {
  // The visible label (the markdown link text).
  label: string;
  // The geocoder query (everything after `place:` in the link target).
  query: string;
};

type LookupState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "ready"; result: GeocodeResult }
  | { phase: "empty" };

export function PlaceChip({ label, query }: PlaceChipProps) {
  const opener = useSurfaceOpener();
  const [open, setOpen] = useState(false);
  const [lookup, setLookup] = useState<LookupState>({ phase: "idle" });
  const rootRef = useRef<HTMLSpanElement | null>(null);

  // Resolve coordinates the first time the popover is opened (fallback path
  // only — inside a SurfaceContext the drawer owns resolution). Server-side
  // /places/brief first; Mapbox geocoding only as a last resort.
  useEffect(() => {
    if (!open || lookup.phase !== "idle") return;
    let cancelled = false;
    setLookup({ phase: "loading" });
    void resolvePlacePoint(query).then((result) => {
      if (cancelled) return;
      setLookup(result ? { phase: "ready", result } : { phase: "empty" });
    });
    return () => {
      cancelled = true;
    };
  }, [open, lookup.phase, query]);

  // Dismiss on outside click / Escape while the popover is open.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={rootRef} className="relative inline-block align-baseline">
      <button
        type="button"
        data-testid="place-chip"
        data-place-query={query}
        aria-expanded={open}
        onClick={() => {
          if (opener) {
            opener.open({ kind: "place", label, query });
            return;
          }
          setOpen((v) => !v);
        }}
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 align-baseline",
          "font-sans text-[0.85em] leading-none text-ink transition-colors",
          "bg-ink/6 ring-1 ring-inset ring-ink/10 hover:bg-brand/10 hover:ring-brand/30",
          open && "bg-brand/10 ring-brand/40",
        )}
      >
        <MapPin className="h-3 w-3 text-brand" aria-hidden />
        <span>{label}</span>
      </button>

      <AnimatePresence>
        {open ? (
          <motion.span
            role="dialog"
            data-testid="place-chip-map"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className={cn(
              "absolute left-0 top-full z-30 mt-2 block w-72 max-w-[80vw]",
              "overflow-hidden rounded-md bg-paper shadow-float ring-1 ring-ink/10",
            )}
          >
            <ChipMap lookup={lookup} />
            <span className="block px-3 py-2 font-sans text-[11px] leading-snug text-ink/60">
              {lookup.phase === "ready"
                ? lookup.result.placeName
                : lookup.phase === "loading"
                  ? "Locating…"
                  : lookup.phase === "empty"
                    ? label
                    : label}
            </span>
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}

// The map surface. A block-display <span> is a valid Mapbox container and keeps
// us inside the inline-only subtree. When we can't draw a map (no token or the
// place didn't resolve) we show a calm compass-rose placeholder instead.
function ChipMap({ lookup }: { lookup: LookupState }) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const hasToken = Boolean(getMapboxToken());

  const result = lookup.phase === "ready" ? lookup.result : null;
  const lng = result?.lng;
  const lat = result?.lat;

  useEffect(() => {
    if (!hasToken || lng === undefined || lat === undefined) return;
    if (!containerRef.current) return;
    let cancelled = false;
    const token = getMapboxToken();
    void loadMapbox().then((mapbox) => {
      if (cancelled || !containerRef.current) return;
      const opts: Record<string, unknown> = {
        container: containerRef.current,
        style: "mapbox://styles/mapbox/light-v11",
        center: [lng, lat],
        zoom: 8,
        interactive: false,
        attributionControl: false,
      };
      if (token) opts["accessToken"] = token;
      const map = new mapbox.Map(opts as ConstructorParameters<typeof mapbox.Map>[0]);
      mapRef.current = map;
      map.on("load", () => {
        if (cancelled) return;
        new mapbox.Marker({ color: "#F5701F" }).setLngLat([lng, lat]).addTo(map);
      });
    });
    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [hasToken, lng, lat]);

  if (lng !== undefined && lat !== undefined && hasToken) {
    return <span ref={containerRef} className="block h-36 w-full bg-ink/5" />;
  }

  // Fallback: loading shimmer or a quiet "no map" state.
  return (
    <span className="flex h-36 w-full items-center justify-center bg-ink/4">
      <MapPin
        className={cn(
          "h-6 w-6 text-ink/30",
          lookup.phase === "loading" && "animate-pulse",
        )}
        aria-hidden
      />
    </span>
  );
}
