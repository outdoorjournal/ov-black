"use client";

// First-run intake for the itinerary builder (0033). Before a timeline exists,
// we capture the trip's first-class BRIEF (the goal) and WHEN — the same step
// whether an advisor or a traveler is starting it. Timing spans exact dates →
// a fuzzy-but-bounded window (~a week in summer) → fully flexible, plus a
// free-text constraints note the structured fields can't hold ("not August",
// "back by a Sunday"). Saving PATCHes /itinerary/{id} and hands control back to
// the parent, which reveals the builder.

import { useCallback, useMemo, useState } from "react";

import {
  createApiClient,
  updateItinerary,
  type ItineraryTimingKind,
  type UpdateItineraryRequest,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { createBrowserSupabase } from "@/lib/supabase/client";

export type ItineraryIntakeInitial = {
  brief?: string | null;
  timingKind?: ItineraryTimingKind | null;
  dateStart?: string | null;
  dateEnd?: string | null;
  durationNights?: number | null;
  timingNote?: string | null;
};

export type ItineraryIntakeProps = {
  itineraryId: string;
  apiBaseUrl: string;
  accessToken: string;
  /** Wording only — advisor phrasing vs. self-serve traveler phrasing. */
  audience?: "advisor" | "traveler";
  initial?: ItineraryIntakeInitial | undefined;
  onSaved: () => void;
  onSkip?: () => void;
};

const TIMING_MODES: ReadonlyArray<{ id: ItineraryTimingKind; label: string; hint: string }> = [
  { id: "exact", label: "Exact dates", hint: "You know the days." },
  { id: "window", label: "A rough window", hint: "Roughly when, for about so long." },
  { id: "flexible", label: "Flexible", hint: "No dates yet — just constraints." },
];

export function ItineraryIntake({
  itineraryId,
  apiBaseUrl,
  accessToken,
  audience = "advisor",
  initial,
  onSaved,
  onSkip,
}: ItineraryIntakeProps) {
  const [brief, setBrief] = useState(initial?.brief ?? "");
  const [mode, setMode] = useState<ItineraryTimingKind>(
    initial?.timingKind ?? "window",
  );
  const [dateStart, setDateStart] = useState(initial?.dateStart ?? "");
  const [dateEnd, setDateEnd] = useState(initial?.dateEnd ?? "");
  const [durationNights, setDurationNights] = useState(
    initial?.durationNights != null ? String(initial.durationNights) : "",
  );
  const [note, setNote] = useState(initial?.timingNote ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fresh token on submit (mirrors SinglePromptCard): the SSR token may have
  // expired by the time the traveler finishes typing; the browser client holds
  // an auto-refreshed one.
  const getAccessToken = useMemo<() => Promise<string | null>>(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return async () => {
      if (supabase) {
        const {
          data: { session },
        } = await supabase.auth.getSession();
        if (session?.access_token) return session.access_token;
      }
      return accessToken ?? null;
    };
  }, [accessToken]);

  const briefValid = brief.trim().length > 0;
  const datesReversed =
    mode !== "flexible" &&
    dateStart !== "" &&
    dateEnd !== "" &&
    dateEnd < dateStart;
  const canSave = briefValid && !datesReversed && !saving;

  const save = useCallback(async () => {
    if (!briefValid || datesReversed || saving) return;
    setSaving(true);
    setError(null);

    // Build a partial payload: send only the fields this mode owns, and send
    // explicit nulls to clear the others (so re-running the intake in a
    // different mode doesn't leave stale dates behind).
    const body: UpdateItineraryRequest = {
      brief: brief.trim(),
      timing_kind: mode,
      timing_note: note.trim() === "" ? null : note.trim(),
      date_start: mode === "flexible" ? null : dateStart === "" ? null : dateStart,
      date_end: mode === "flexible" ? null : dateEnd === "" ? null : dateEnd,
      duration_nights:
        mode === "window" && durationNights.trim() !== ""
          ? Number(durationNights)
          : null,
    };

    const token = await getAccessToken();
    if (!token) {
      setError("We couldn't reach the concierge. Please try again.");
      setSaving(false);
      return;
    }
    const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
    const result = await updateItinerary(api, itineraryId, body);
    if (!result.ok) {
      setError(
        result.detail === "forbidden"
          ? "You don't have permission to set this trip's brief."
          : "Something went wrong saving your brief. Please try again.",
      );
      setSaving(false);
      return;
    }
    onSaved();
  }, [
    apiBaseUrl,
    brief,
    briefValid,
    dateEnd,
    dateStart,
    datesReversed,
    durationNights,
    getAccessToken,
    itineraryId,
    mode,
    note,
    onSaved,
    saving,
  ]);

  const heading =
    audience === "traveler" ? "Where shall we take you?" : "What are we planning?";

  return (
    <div className="flex min-h-0 flex-1 items-start justify-center overflow-y-auto bg-paper px-6 py-12 text-ink sm:py-16">
      <div className="w-full max-w-2xl">
        <p className="font-sans text-[11px] uppercase tracking-label text-ink/50">
          New itinerary
        </p>
        <h1 className="mt-2 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
          {heading}
        </h1>
        <p className="mt-3 max-w-xl font-sans text-sm leading-relaxed text-ink/60">
          Start with the shape of the trip. The concierge builds the details out
          from here — you can refine any of this later.
        </p>

        <div className="mt-10 space-y-8">
          {/* Brief */}
          <div className="space-y-2">
            <label
              htmlFor="intake-brief"
              className="font-sans text-xs uppercase tracking-[0.22em] text-ink/55"
            >
              The trip, in a sentence
            </label>
            <textarea
              id="intake-brief"
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              rows={2}
              autoFocus
              placeholder="Sailing in Greece with my family…"
              className="w-full resize-none rounded-sm border border-ink/15 bg-white px-4 py-3 font-serif text-xl leading-snug text-ink transition placeholder:text-ink/30 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
            />
          </div>

          {/* When */}
          <div className="space-y-3">
            <span className="font-sans text-xs uppercase tracking-[0.22em] text-ink/55">
              When?
            </span>
            <div className="flex flex-wrap gap-2">
              {TIMING_MODES.map((m) => {
                const active = mode === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMode(m.id)}
                    aria-pressed={active}
                    className={
                      "rounded-full border px-4 py-1.5 font-sans text-sm transition " +
                      (active
                        ? "border-brand bg-brand/10 text-ink"
                        : "border-ink/15 text-ink/60 hover:border-ink/40 hover:text-ink")
                    }
                  >
                    {m.label}
                  </button>
                );
              })}
            </div>
            <p className="font-sans text-xs text-ink/45">
              {TIMING_MODES.find((m) => m.id === mode)?.hint}
            </p>

            {mode !== "flexible" ? (
              <div className="flex flex-wrap items-end gap-4 pt-1">
                <label className="flex flex-col gap-1">
                  <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
                    {mode === "window" ? "No earlier than" : "Start"}
                  </span>
                  <input
                    type="date"
                    value={dateStart}
                    onChange={(e) => setDateStart(e.target.value)}
                    className="rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
                    {mode === "window" ? "No later than" : "End"}
                  </span>
                  <input
                    type="date"
                    value={dateEnd}
                    onChange={(e) => setDateEnd(e.target.value)}
                    className="rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
                  />
                </label>
                {mode === "window" ? (
                  <label className="flex flex-col gap-1">
                    <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
                      About how many nights
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={365}
                      value={durationNights}
                      onChange={(e) => setDurationNights(e.target.value)}
                      placeholder="7"
                      className="w-28 rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink placeholder:text-ink/30 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
                    />
                  </label>
                ) : null}
              </div>
            ) : null}
            {datesReversed ? (
              <p className="font-sans text-xs text-brand">
                The end can’t be before the start.
              </p>
            ) : null}
          </div>

          {/* Constraints note */}
          <div className="space-y-2">
            <label
              htmlFor="intake-note"
              className="font-sans text-xs uppercase tracking-[0.22em] text-ink/55"
            >
              Anything to work around? <span className="text-ink/35">(optional)</span>
            </label>
            <textarea
              id="intake-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="Can't travel in August · need to be back by a Sunday · school-term only…"
              className="w-full resize-none rounded-sm border border-ink/15 bg-white px-4 py-3 font-sans text-sm leading-relaxed text-ink transition placeholder:text-ink/30 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
            />
          </div>

          {error ? <p className="font-sans text-sm text-brand">{error}</p> : null}

          <div className="flex items-center gap-5 pt-2">
            <Button
              type="button"
              variant="brand"
              disabled={!canSave}
              onClick={() => void save()}
              className="uppercase tracking-label"
            >
              {saving ? "Saving…" : "Start building"}
            </Button>
            {onSkip ? (
              <button
                type="button"
                onClick={onSkip}
                disabled={saving}
                className="font-sans text-[11px] uppercase tracking-eyebrow text-ink/45 transition hover:text-ink/80 disabled:opacity-40"
              >
                Skip for now
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
