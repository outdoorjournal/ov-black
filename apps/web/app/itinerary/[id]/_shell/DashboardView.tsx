"use client";

// The per-trip Dashboard — the itinerary index lands here, and the Journal IS
// the dashboard (traveler-journal design): the edit-in-place HERO (title /
// brief / timing inline editors — see DashboardHero), then the narrative
// Journal (spine of cards + reactive right rail). The old modules relocate
// rather than vanish — next action + approve-all + balance become the rail's
// RESTING state, and the money ledger, travel party, and advisor
// Vault/Invoices/Booking panels move to a quiet footer after the journey
// ("The practical part"). Role-agnostic: both roles land here (Studio stays
// one click away as the workbench); affordances differ by `role`.

import { useEffect, useRef, useState } from "react";

import {
  createApiClient,
  listInvoices,
  listItineraryParty,
} from "@ov-black/api-client";

import {
  itineraryGraphStore,
  selectCanApprove,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { AmbientLayer } from "@/app/_components/itinerary-graph/views/journal/AmbientLayer";
import { JournalVersionChip } from "@/app/_components/itinerary-graph/views/journal/JournalVersionChip";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";

import { DashboardHero } from "./DashboardHero";
import { type MoneyState, type PartyState } from "./dashboardModel";

export function DashboardView() {
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  // Bumped when the agent changes the travel party mid-chat — re-runs the party
  // fetch below so the hero chip reflects a seat/unseat without a reload.
  const partyRevision = itineraryGraphStore.useStore((s) => s.partyRevision);

  const [money, setMoney] = useState<MoneyState>({ kind: "loading" });
  const [party, setParty] = useState<PartyState>({ kind: "loading" });
  // The dashboard's scroll container — the Journal's scroll-active center band
  // is measured against it.
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!apiBaseUrl || !accessToken) {
      setMoney({ kind: "error" });
      setParty({ kind: "error" });
      return;
    }
    let cancelled = false;
    const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
    void (async () => {
      const result = await listInvoices(client, itineraryId);
      if (cancelled) return;
      setMoney(
        result.ok
          ? { kind: "ready", invoices: result.invoices }
          : { kind: "error" },
      );
    })();
    // The travel party feeds the hero's person-icon chip (and its popover). Read
    // here — a single fetch — and hand the result down to the hero.
    void (async () => {
      const result = await listItineraryParty(client, itineraryId);
      if (cancelled) return;
      setParty(
        result.ok
          ? { kind: "ready", members: result.party.members }
          : { kind: "error" },
      );
    })();
    return () => {
      cancelled = true;
    };
    // `partyRevision` re-runs this on an agent party change: the roster feeds the
    // hero chip, and party size also expands per-person costs, so the money read
    // is worth refreshing alongside it.
  }, [itineraryId, apiBaseUrl, accessToken, partyRevision]);

  return (
    // The `relative` frame is the ambient's containing block: it pins the wash to
    // the dashboard content region (not the whole viewport), so the backdrop
    // never bleeds onto the sibling rail + concierge chrome. The scroller sits
    // ABOVE it (z-[1]) and does the scrolling; the ambient, outside the scroller,
    // stays put while the story moves.
    <div className="relative min-h-0 flex-1 overflow-hidden bg-paper">
      {/* The ambient layer (phase 5) — behind the paper: the active node's
          watermark wash (mood tint fallback), held still behind the story as it
          scrolls. */}
      <AmbientLayer />
      <div
        ref={scrollRef}
        data-testid="dashboard"
        className="relative z-[1] h-full overflow-y-auto"
      >
        {/* Edit-in-place hero (phase 2) — title/brief/timing are their own
            inline editors; the money callout (right) and travel-party chip
            (left) now live here too. The intake overlay is first-run only
            (ItineraryShell's brief gate), never the edit path. */}
        <DashboardHero money={money} party={party} />

        {/* The version chip near the hero (phase 4) — names which version this
            is and carries the *Compare with the trip* toggle (diff mode: a
            toggle over the Journal DOM below, never a route). */}
        <div className="mx-auto w-full max-w-6xl px-4 pt-4 sm:px-6">
          <JournalVersionChip />
        </div>

        {/* The Journal — the trip read as a story. Its right rail rests on the
            relocated "trip at a glance" (next action · approval). Money moved to
            the hero callout, so the rail no longer doubles the balance. */}
        <JournalView scrollRootRef={scrollRef} railIdle={<ApprovalSection />} />
      </div>
    </div>
  );
}

// ── Approval — approve-all, per-currency total ───────────────────────────────
//
// The itinerary's approval arc lives here. Once cards are with the traveler
// (`with_traveler`) they *approve* — the all-at-once "Approve all" here, or
// card-by-card on the timeline (both derive the itinerary to `approved`). The
// plan's per-currency price (from the graph read's `totals`) shows alongside,
// so the traveler sees what they're approving. Craft-feel: no spinners/icons —
// a disabled button is the only in-flight affordance.
function ApprovalSection() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const status = itineraryGraphStore.useStore((s) => s.status);
  const totals = itineraryGraphStore.useStore((s) => s.totals);
  const displayCurrency = itineraryGraphStore.useStore((s) => s.displayCurrency);
  const totalDisplay = itineraryGraphStore.useStore((s) => s.totalDisplay);
  const canApprove = itineraryGraphStore.useStore(selectCanApprove);
  const approvePending = itineraryGraphStore.useStore((s) => s.approvePending);
  const approve = itineraryGraphStore.useStore((s) => s.approve);

  const isAdvisor = role === "advisor";
  const totalEntries = Object.entries(totals);
  const hasTotals = totalEntries.length > 0;
  // 0048: when the client has a preferred currency and FX resolved, lead with
  // the converted grand total; keep the native per-currency breakdown as a
  // muted secondary line (unless the plan is already all in that currency).
  const converted =
    totalDisplay != null && displayCurrency != null
      ? { currency: displayCurrency, amount: Number(totalDisplay) }
      : null;
  const showNativeBreakdown =
    !converted ||
    totalEntries.length > 1 ||
    (totalEntries.length === 1 && totalEntries[0]?.[0] !== converted.currency);

  // Nothing to show on a plan still in the studio with no price (e.g. a
  // traveler looking at a plan the advisor is still building).
  if (status === "in_studio" && !hasTotals) return null;

  const primaryBtn =
    "shrink-0 self-start rounded-full bg-ink px-5 py-2 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50";

  return (
    <SectionCard label="Approval" testid="dashboard-approval">
      <div
        className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
        data-itinerary-status={status}
      >
        <div className="min-w-0">
          <p className="font-serif text-xl text-ink">
            {status === "approved"
              ? "Approved"
              : status === "with_traveler"
                ? isAdvisor
                  ? "With the traveler — awaiting their review"
                  : "Ready for your approval"
                : "In the studio"}
          </p>
          <p className="mt-0.5 font-sans text-[13px] text-ink/55">
            {status === "approved"
              ? "The whole plan is approved."
              : status === "with_traveler"
                ? isAdvisor
                  ? "The traveler can approve the plan, or firm up cards one at a time."
                  : "Approve the whole plan, or approve cards one at a time on the timeline."
                : "The plan is still being built."}
          </p>
          {hasTotals ? (
            <div
              data-testid="dashboard-trip-total"
              className="mt-3 flex flex-col gap-0.5"
            >
              <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
                Trip total
              </span>
              {converted ? (
                <span
                  data-testid="dashboard-trip-total-display"
                  data-currency={converted.currency}
                  className="font-serif text-lg text-ink"
                >
                  {money(converted.currency, converted.amount)}
                </span>
              ) : null}
              {showNativeBreakdown
                ? totalEntries.map(([currency, amount]) => (
                    <span
                      key={currency}
                      data-testid="dashboard-trip-total-row"
                      data-currency={currency}
                      className={
                        converted
                          ? "font-sans text-[11px] text-ink/45"
                          : "font-serif text-lg text-ink"
                      }
                    >
                      {converted ? "from " : ""}
                      {money(currency, Number(amount))}
                    </span>
                  ))
                : null}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          {/* Traveler's one-action "Approve all". */}
          {canApprove && !isAdvisor ? (
            <button
              type="button"
              onClick={approve}
              disabled={approvePending}
              data-testid="dashboard-approve-all"
              className={primaryBtn}
            >
              Approve all
            </button>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}

// Trip-total currency formatter (ApprovalSection). The money ledger itself now
// renders in the hero callout + the routed Invoices surface.
const money = (currency: string, amount: number): string =>
  `${currency} ${amount.toFixed(2)}`;

// ── Shared section chrome ────────────────────────────────────────────────────
function SectionCard({
  label,
  testid,
  children,
}: {
  label: string;
  testid: string;
  children: React.ReactNode;
}) {
  return (
    <section
      data-testid={testid}
      className="rounded-lg border border-ink/10 bg-white/60 p-4 sm:p-5"
    >
      <h2 className="mb-3 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
        {label}
      </h2>
      {children}
    </section>
  );
}
