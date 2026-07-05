"use client";

import { useState, useTransition } from "react";

import { startItineraryForClientAction } from "../actions";

/**
 * "New itinerary" action on the client detail page's Itineraries panel — the
 * advisor-side entry point for spinning up a trip bound to *this* client
 * (G-ITIN-FOR-CLIENT). The server action creates a `client_id`-bound itinerary
 * and redirects into its first-run intake, so on success this component simply
 * unmounts as the navigation happens; only a create failure returns here and
 * surfaces inline.
 */
export function NewItineraryButton({ clientId }: { clientId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const onClick = () => {
    setError(null);
    startTransition(async () => {
      const result = await startItineraryForClientAction(clientId);
      // Success redirects (never returns); we only land here on failure.
      if ("error" in result) setError(result.error);
    });
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={isPending}
        className="rounded-full border border-paper/25 px-3 py-1 font-sans text-[10px] uppercase tracking-label text-paper/70 transition-colors hover:border-paper hover:text-paper disabled:opacity-50"
      >
        {isPending ? "Creating…" : "New itinerary"}
      </button>
      {error ? (
        <p
          role="alert"
          className="font-sans text-[10px] uppercase tracking-label text-destructive"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
