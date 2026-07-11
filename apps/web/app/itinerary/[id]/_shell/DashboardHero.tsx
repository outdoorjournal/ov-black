"use client";

// The Journal's hero, edit-in-place (traveler-journal design, phase 2). Each
// text element — title, brief, timing — is its own inline editor styled
// identically to its display state; a quiet ✎ appears on hover/focus as the
// only affordance (light-editorial: no chrome, no bar under the hero). The old
// full-page "What are we planning?" intake overlay is fully retired — this
// edit-in-place hero is the only way an advisor or traveler sets the brief.
//
//   title   click → an input in the same serif, save on blur/Enter
//   brief   click → an auto-growing textarea over the image, save on blur
//   timing  click → a POPOVER with the shared timing-kind/date controls
//           (TimingFields — the same ones the intake renders), not a page
//           takeover
//
// Persistence is the same PATCH /itinerary/{id} the intake uses, then
// router.refresh() — the hero's fields are a server prop, so a save must pull
// the fresh value back down (the established pattern). A small optimistic
// override keeps the just-saved text on screen until the refresh lands.
// Editing is offered to any credentialed viewer (traveler or advisor — the
// backend's owner/advisor authorization is the real authority).

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  createApiClient,
  updateItinerary,
  type ItineraryTimingKind,
  type UpdateItineraryRequest,
} from "@ov-black/api-client";

import {
  TimingFields,
  timingDatesReversed,
  timingPatch,
  timingValueFrom,
  type TimingValue,
} from "@/app/_components/itinerary-graph/intake/TimingFields";
import { CinemaPlayButton } from "@/app/_components/itinerary-graph/views/journal/Cinema";
import { PartyPanel } from "@/app/_components/itinerary-graph/views/horizontal/PartyPanel";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { DEFAULT_MOOD, MOODS, type MoodEntry } from "@/lib/atmos/moods";

import {
  firstUnpaidIssued,
  formatTiming,
  rollupInvoices,
  type MoneyState,
  type PartyState,
} from "./dashboardModel";
import { DownloadMenu } from "./DownloadMenu";

/** The quiet pencil — visible on hover/focus only, punctuation not paint. */
function Pencil() {
  return (
    <span
      aria-hidden
      className="ml-2 inline-block text-[0.6em] text-white/0 transition-colors duration-150 group-hover/hero-field:text-white/60 group-focus-visible/hero-field:text-white/60"
    >
      ✎
    </span>
  );
}

export function DashboardHero({
  money,
  party,
}: {
  // The money ledger + travel party are read once in DashboardView and handed
  // down — the hero owns their DISPLAY (a right-hand callout, a left-hand chip),
  // not their fetch. Optional so the hero renders standalone (tests, isolation).
  money?: MoneyState;
  party?: PartyState;
} = {}) {
  const router = useRouter();
  const { timeline } = useTimelineData();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  const it = timeline.itinerary;
  const canEdit = apiBaseUrl !== null && accessToken !== null;

  const entry = (MOODS as Record<string, MoodEntry>)[timeline.mood];
  const imageUrl = entry?.imageUrl ?? MOODS[DEFAULT_MOOD].imageUrl;

  const [error, setError] = useState(false);

  // One save path for every field: PATCH the partial body, refresh on success.
  const save = useCallback(
    async (body: UpdateItineraryRequest): Promise<boolean> => {
      if (!apiBaseUrl || !accessToken) return false;
      setError(false);
      const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const result = await updateItinerary(client, itineraryId, body);
      if (result.ok) {
        router.refresh();
        return true;
      }
      setError(true);
      return false;
    },
    [apiBaseUrl, accessToken, itineraryId, router],
  );

  return (
    <section
      data-testid="dashboard-hero"
      className="relative isolate flex min-h-[240px] flex-col justify-end overflow-hidden border-b border-ink/10 px-4 py-8 sm:min-h-[300px] sm:px-6 sm:py-10"
    >
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-cover bg-center"
        style={{ backgroundImage: `url(${imageUrl})` }}
      />
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-linear-to-t from-black/75 via-black/35 to-black/15"
      />
      {/* Cinema's entry (phase 5) — a small quiet Play in the hero's corner.
          It hides itself in diff mode, under reduced motion, and while
          already playing. */}
      <div className="pointer-events-none absolute bottom-4 right-4 sm:bottom-6 sm:right-6">
        <CinemaPlayButton />
      </div>
      {/* Download (PDF / Excel), top-left — export the version being viewed.
          Both roles; mirrors the money callout's chip styling. */}
      <DownloadMenu />
      {/* Money, called out in the hero's top-right space — the trip's balance is
          the one number worth surfacing above the story (the full ledger lives
          behind the tap, on the invoices surface). */}
      <HeroMoney money={money} itineraryId={itineraryId} />
      <div className="mx-auto w-full max-w-5xl">
        <TimingInline itinerary={it} canEdit={canEdit} onSave={save} />
        <TitleInline
          title={it.title ?? ""}
          canEdit={canEdit}
          onSave={save}
        />
        <BriefInline brief={it.brief ?? null} canEdit={canEdit} onSave={save} />
        {/* Travel party — a person-icon (count) chip among the trip's details,
            opening a popover (traveler: who's coming + manage; advisor: the
            full attach/detach panel rehomed from the old footer). */}
        <HeroParty party={party} />
        {error ? (
          <p
            data-testid="hero-save-error"
            className="mt-3 font-sans text-[11px] uppercase tracking-[0.16em] text-white/70"
          >
            That didn’t save — please try again.
          </p>
        ) : null}
      </div>
    </section>
  );
}

type SaveFn = (body: UpdateItineraryRequest) => Promise<boolean>;

// ── Money — the top-right balance callout ────────────────────────────────────
// The trip's balance, surfaced over the hero image so it "calls attention"
// without an owning section. Owed → the pay deep-link (the first unpaid invoice,
// matching the next-best-action); otherwise a quiet tap through to the ledger.
function HeroMoney({
  money,
  itineraryId,
}: {
  money?: MoneyState | undefined;
  itineraryId: string;
}) {
  if (!money || money.kind !== "ready") return null;
  const { byCurrency, hasOwed } = rollupInvoices(money.invoices);
  if (byCurrency.length === 0) return null; // nothing issued/paid → no callout

  const owedRows = byCurrency.filter((c) => c.owed > 0.005);
  const unpaid = firstUnpaidIssued(money.invoices);
  const href = (
    unpaid ? `/invoices/${unpaid.id}` : `/itinerary/${itineraryId}/invoices`
  ) as Route;

  const lead = owedRows[0] ?? byCurrency[0]!;
  const value = hasOwed
    ? `${lead.currency} ${lead.owed.toFixed(2)}`
    : "All settled";

  return (
    <div className="absolute right-4 top-4 z-10 sm:right-6 sm:top-6">
      <Link
        href={href}
        data-testid="hero-money"
        className="block rounded-lg border border-white/25 bg-black/25 px-4 py-2.5 text-right backdrop-blur-sm transition-colors hover:bg-black/40"
      >
        <span className="block font-sans text-[10px] uppercase tracking-[0.18em] text-white/60">
          {hasOwed ? "Balance due" : "Money"}
        </span>
        <span className="mt-0.5 block font-serif text-lg leading-none text-white">
          {value}
        </span>
        {hasOwed && owedRows.length > 1 ? (
          <span className="mt-1 block font-sans text-[10px] text-white/55">
            +{owedRows.length - 1} more
          </span>
        ) : null}
        <span className="mt-1 block font-sans text-[10px] uppercase tracking-[0.16em] text-white/70">
          {hasOwed ? "View & pay →" : "View ledger →"}
        </span>
      </Link>
    </div>
  );
}

// ── Travel party — a person-icon (count) chip that opens a popover ────────────
function PeopleIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="7.5" cy="7" r="2.6" />
      <path d="M2.5 16a5 5 0 0 1 10 0" />
      <path d="M13.5 5.4a2.6 2.6 0 0 1 0 5.1" />
      <path d="M14.2 12.2A5 5 0 0 1 17.5 16" />
    </svg>
  );
}

function HeroParty({ party }: { party?: PartyState | undefined }) {
  const { timeline } = useTimelineData();
  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  const isAdvisor = role === "advisor";
  const clientId = timeline.itinerary.client_id ?? null;

  const [open, setOpen] = useState(false);
  // Portals need a browser; gate on mount so SSR/hydration render nothing.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);
  // The popover is portalled to <body> so it escapes the hero's `isolate`
  // stacking context and `overflow-hidden` clip — anchored to the chip via a
  // viewport-fixed box (recomputed on scroll/resize), not absolute positioning.
  const [box, setBox] = useState<{ top: number; left: number; width: number } | null>(null);

  const members = party?.kind === "ready" ? party.members : [];
  const count = members.length;

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const btn = btnRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      const width = Math.min(window.innerWidth * 0.88, 352); // 22rem cap
      const left = Math.max(16, Math.min(rect.left, window.innerWidth - 16 - width));
      setBox({ top: rect.bottom + 12, left, width });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open]);

  // A popover, not a page: Escape + click-outside dismiss (mirrors the timing
  // editor's dismissal). The popover lives in a portal, so "outside" must spare
  // both the trigger and the portalled panel.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target;
      if (
        t instanceof Node &&
        (btnRef.current?.contains(t) || popRef.current?.contains(t))
      ) {
        return;
      }
      setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="mt-4">
      <button
        ref={btnRef}
        type="button"
        data-testid="hero-party"
        aria-expanded={open}
        aria-label="Travel party"
        onClick={() => setOpen((v) => !v)}
        className="group/hero-field inline-flex items-center gap-2 rounded-full border border-white/25 bg-black/25 px-3 py-1.5 font-sans text-[12px] text-white/85 backdrop-blur-sm transition-colors hover:bg-black/40"
      >
        <PeopleIcon />
        <span className="tabular-nums">
          {count > 0 ? `Travel party (${count})` : "Just you"}
        </span>
      </button>

      {mounted && open && box
        ? createPortal(
            <div
              ref={popRef}
              data-testid="hero-party-popover"
              style={{ top: box.top, left: box.left, width: box.width }}
              className="fixed z-50 rounded-lg border border-ink/10 bg-paper p-4 text-ink shadow-xl"
            >
              <p className="mb-3 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
                Travel party
              </p>
              {isAdvisor ? (
                <PartyPanel
                  clientId={clientId}
                  itineraryId={itineraryId}
                  apiBaseUrl={apiBaseUrl}
                  accessToken={accessToken}
                />
              ) : (
                <div className="flex flex-col gap-3">
                  {count === 0 ? (
                    <p className="font-serif text-[13px] italic text-ink/45">
                      Just you so far.
                    </p>
                  ) : (
                    <ul className="flex flex-wrap gap-2">
                      {members.map((m) => (
                        <li
                          key={m.traveler_id}
                          className="rounded-full border border-ink/15 px-3 py-1 font-sans text-[12px] text-ink/70"
                        >
                          {m.name}
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link
                    href={`/itinerary/${itineraryId}/party` as Route}
                    className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
                  >
                    Open the travel party →
                  </Link>
                </div>
              )}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

// ── Title — click → an input wearing the display serif ───────────────────────
function TitleInline({
  title,
  canEdit,
  onSave,
}: {
  title: string;
  canEdit: boolean;
  onSave: SaveFn;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  // Optimistic: keep the just-saved text on screen until router.refresh lands.
  const [override, setOverride] = useState<string | null>(null);

  const shown = override ?? (title.trim() || "Your trip");

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (!next || next === title.trim()) return; // empty = keep what was there
    setOverride(next);
    void onSave({ title: next }).then((ok) => {
      if (!ok) setOverride(null);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      e.currentTarget.blur(); // blur commits — one save path
    } else if (e.key === "Escape") {
      setDraft(title); // discard, then let blur exit without a diff
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        aria-label="Trip title"
        data-testid="hero-title-input"
        className="mt-2 block w-full max-w-3xl border-0 border-b border-white/40 bg-transparent p-0 font-serif text-3xl leading-tight text-white outline-none placeholder:text-white/40 focus:border-white/70 focus:ring-0 sm:text-4xl"
        placeholder="Name this trip…"
      />
    );
  }

  return (
    <h1 className="mt-2 max-w-3xl font-serif text-3xl leading-tight text-white sm:text-4xl">
      {canEdit ? (
        <button
          type="button"
          data-testid="hero-title"
          aria-label="Edit the trip title"
          onClick={() => {
            setDraft(shown === "Your trip" ? title : shown);
            setEditing(true);
          }}
          className="group/hero-field cursor-text text-left"
        >
          {shown}
          <Pencil />
        </button>
      ) : (
        shown
      )}
    </h1>
  );
}

// ── Brief — click → an auto-growing textarea over the image ──────────────────
function BriefInline({
  brief,
  canEdit,
  onSave,
}: {
  brief: string | null;
  canEdit: boolean;
  onSave: SaveFn;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [override, setOverride] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement | null>(null);

  const shown = override ?? brief;

  // Auto-grow: the textarea tracks its content so the editor never scrolls —
  // it reads exactly like the display paragraph it replaces.
  const autogrow = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight}px`;
  }, []);
  useEffect(() => {
    if (editing) autogrow();
  }, [editing, autogrow]);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (!next || next === (brief ?? "").trim()) return;
    setOverride(next);
    void onSave({ brief: next }).then((ok) => {
      if (!ok) setOverride(null);
    });
  };

  if (editing) {
    return (
      <textarea
        ref={ref}
        autoFocus
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          autogrow();
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setDraft(brief ?? "");
            setEditing(false);
          }
        }}
        rows={1}
        aria-label="Trip brief"
        data-testid="hero-brief-input"
        className="mt-3 block w-full max-w-2xl resize-none overflow-hidden border-0 border-b border-white/40 bg-transparent p-0 font-serif text-lg italic leading-snug text-white/85 outline-none placeholder:text-white/40 focus:border-white/70 focus:ring-0"
        placeholder="The trip, in a sentence…"
      />
    );
  }

  if (!canEdit) {
    return shown ? (
      <p className="mt-3 max-w-2xl font-serif text-lg italic leading-snug text-white/85">
        {shown}
      </p>
    ) : null;
  }

  return (
    <p
      className={[
        "mt-3 max-w-2xl font-serif text-lg italic leading-snug",
        shown ? "text-white/85" : "text-white/45",
      ].join(" ")}
    >
      <button
        type="button"
        data-testid="hero-brief"
        aria-label="Edit the trip brief"
        onClick={() => {
          setDraft(shown ?? "");
          setEditing(true);
        }}
        className="group/hero-field cursor-text text-left"
      >
        {shown ?? "A line about this trip…"}
        <Pencil />
      </button>
    </p>
  );
}

// ── Timing — click → a popover with the shared timing controls ───────────────
function TimingInline({
  itinerary,
  canEdit,
  onSave,
}: {
  itinerary: {
    timing_kind?: ItineraryTimingKind | null;
    date_start?: string | null;
    date_end?: string | null;
    duration_nights?: number | null;
    timing_note?: string | null;
  };
  canEdit: boolean;
  onSave: SaveFn;
}) {
  const [open, setOpen] = useState(false);
  const [timing, setTiming] = useState<TimingValue>(() => timingValueFrom());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const label = formatTiming(itinerary);

  const openEditor = () => {
    setTiming(
      timingValueFrom({
        timingKind: itinerary.timing_kind ?? null,
        dateStart: itinerary.date_start ?? null,
        dateEnd: itinerary.date_end ?? null,
        durationNights: itinerary.duration_nights ?? null,
      }),
    );
    setNote(itinerary.timing_note ?? "");
    setOpen(true);
  };

  // A popover, not a page takeover: Escape and click-outside dismiss.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (
        popoverRef.current &&
        e.target instanceof Node &&
        !popoverRef.current.contains(e.target)
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const commit = () => {
    if (saving || timingDatesReversed(timing)) return;
    setSaving(true);
    void onSave(timingPatch(timing, note)).then((ok) => {
      setSaving(false);
      if (ok) setOpen(false);
    });
  };

  if (!canEdit) {
    return (
      <p className="font-sans text-[11px] uppercase tracking-[0.28em] text-white/70">
        {label}
      </p>
    );
  }

  return (
    <div className="relative" ref={popoverRef}>
      <p className="font-sans text-[11px] uppercase tracking-[0.28em] text-white/70">
        <button
          type="button"
          data-testid="hero-timing"
          aria-label="Edit the trip timing"
          aria-expanded={open}
          onClick={() => (open ? setOpen(false) : openEditor())}
          className="group/hero-field text-left uppercase"
        >
          {label}
          <Pencil />
        </button>
      </p>

      {open ? (
        <div
          data-testid="hero-timing-popover"
          className="absolute left-0 top-full z-30 mt-3 w-[min(88vw,26rem)] rounded-lg border border-ink/10 bg-paper p-4 text-ink shadow-xl"
        >
          <p className="mb-3 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
            When?
          </p>
          <TimingFields value={timing} onChange={setTiming} />
          <label className="mt-3 block space-y-1">
            <span className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
              Anything to work around? <span className="text-ink/30">(optional)</span>
            </span>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Can’t travel in August · back by a Sunday…"
              data-testid="hero-timing-note"
              className="w-full rounded-sm border border-ink/15 bg-white px-3 py-2 font-sans text-sm text-ink placeholder:text-ink/30 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
            />
          </label>
          <div className="mt-4 flex items-center justify-end gap-4">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/45 transition-colors hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={commit}
              disabled={saving || timingDatesReversed(timing)}
              data-testid="hero-timing-save"
              className="rounded-full bg-ink px-4 py-1.5 font-sans text-[11px] uppercase tracking-[0.16em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
