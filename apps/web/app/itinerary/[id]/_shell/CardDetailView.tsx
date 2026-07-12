"use client";

// Card detail as a full-bleed destination (M006/PS4). Clicking any card routes
// here (/itinerary/[id]/item/[nodeId]) and it takes over the planning space —
// the rail + persistent concierge stay beside it — promoting the old cramped
// max-w-4xl modal to a real surface with room for six facets:
//   (a) actions        — open in Maps / driving directions
//   (b) type detail    — the data-driven NodeZoomCard (subway stops, flight legs…)
//   (c) notes          — NotesPanel (graph-node notes, visible to advisor + party)
//   (d) ask about this — scopes the persistent concierge with a "Re: …" chip
//   (e) scheduling      — reschedule / unschedule via the store's own actions
//   (f) money          — this item's charge line, invoice status, paid/owed, booking
//   (g) edit           — post-creation details (ADV-13): description, price,
//                        the operator's confirmation number
// Role-agnostic: a traveler opens + asks too; the edit affordances gate on role.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  createApiClient,
  getNodeCharges,
  type CostKind,
  type NodeChargesResponse,
} from "@ov-black/api-client";

import {
  getHMeta,
  type NodeResponse,
} from "@/app/_components/itinerary-graph/model/horizontalTypes";
import { attachedNotesByHost } from "@/app/_components/itinerary-graph/shared/attachedNotes";
import { NodeZoomCard } from "@/app/_components/itinerary-graph/shared/cards/NodeZoomCard";
import { PartOfJourney } from "@/app/_components/itinerary-graph/shared/PartOfJourney";
import { NotesPanel } from "@/app/_components/itinerary-graph/shared/NotesPanel";
import {
  itineraryGraphStore,
  selectCanApprove,
  selectCanLeaveNote,
  selectEditable,
  selectTravelerEditable,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

import { useConciergeControl } from "./ConciergeControl";

// ── ISO ↔ day/minute helpers (mirror the store's rebaseStartToDay, in tz) ──────
const pad = (n: number): string => String(n).padStart(2, "0");

function isoToDayMinute(iso: string, tz: number): { dayKey: string; minute: number } {
  const d = new Date(new Date(iso).getTime() + tz * 3_600_000);
  return {
    dayKey: `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`,
    minute: d.getUTCHours() * 60 + d.getUTCMinutes(),
  };
}
const minuteToHHMM = (m: number): string => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
const hhmmToMinute = (s: string): number => {
  const [h, m] = s.split(":").map((v) => Number.parseInt(v, 10));
  return (Number.isFinite(h) ? (h as number) : 0) * 60 + (Number.isFinite(m) ? (m as number) : 0);
};

export function CardDetailView({ nodeId }: { nodeId: string }) {
  const { openConcierge } = useConciergeControl();
  const { timeline } = useTimelineData();
  const router = useRouter();
  const tz = timeline.timezoneOffsetHours;

  const node = itineraryGraphStore.useStore(
    (s): NodeResponse | null =>
      s.nodes.find((n) => n.id === nodeId) ??
      s.pendingProposals.find((n) => n.id === nodeId) ??
      null,
  );
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const canLeaveNote = itineraryGraphStore.useStore(selectCanLeaveNote);
  const editable = itineraryGraphStore.useStore(
    (s) => selectEditable(s) || selectTravelerEditable(s),
  );
  // Node-by-node approve: the traveler firms up this single pending card.
  const canApprove = itineraryGraphStore.useStore(selectCanApprove);
  const canEdit = itineraryGraphStore.useStore((s) => s.canEdit);
  const approvingNodeId = itineraryGraphStore.useStore((s) => s.approvingNodeId);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const setAskContext = itineraryGraphStore.useStore((s) => s.setAskContext);
  const storeApi = itineraryGraphStore.useStoreApi();

  const attachedNotes = useMemo(() => attachedNotesByHost(nodes), [nodes]);
  const backHref = `/itinerary/${itineraryId}/timeline` as const;

  const onAsk = useCallback(() => {
    if (!node) return;
    setAskContext({ nodeId: node.id, title: node.title || "this card" });
    openConcierge(); // ≥1100px the concierge is already in-flow; this is inert there.
  }, [node, setAskContext, openConcierge]);

  if (!node) {
    return (
      <div
        data-testid="card-detail-missing"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-8 text-center"
      >
        <p className="font-serif text-lg text-ink/70">This card is no longer here.</p>
        <Link
          href={backHref}
          className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/55 underline-offset-4 hover:underline"
        >
          Back to the timeline
        </Link>
      </div>
    );
  }

  const notes = attachedNotes.get(node.id) ?? [];
  // A journey beat (subgraph child) carries its parent package above its own
  // detail; opening it navigates to the parent's detail destination.
  const journeyParent = node.parent_subgraph_id
    ? (nodes.find((n) => n.id === node.parent_subgraph_id) ?? null)
    : null;
  const journeySiblingCount = journeyParent
    ? nodes.filter(
        (n) =>
          n.parent_subgraph_id === journeyParent.id &&
          n.status !== "discarded",
      ).length
    : 0;

  return (
    <div data-testid="card-detail" data-node-id={node.id} className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 items-center gap-3 border-b border-ink/10 px-4 py-3">
        <Link
          href={backHref}
          data-testid="card-detail-back"
          className="flex h-8 items-center gap-1 rounded-md px-2 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/60 transition-colors hover:bg-ink/5 hover:text-ink"
        >
          <span aria-hidden>‹</span> Back
        </Link>
        <h1 className="min-w-0 flex-1 truncate font-serif text-lg text-ink">{node.title}</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-6 lg:flex-row">
          {/* (b) The rich, data-driven type detail. */}
          <div className="flex min-w-0 flex-col gap-4 lg:flex-1">
            {journeyParent ? (
              <PartOfJourney
                parent={journeyParent}
                child={node}
                siblingCount={journeySiblingCount}
                tzOffsetHours={tz}
                onOpenParent={() =>
                  router.push(
                    `/itinerary/${itineraryId}/item/${journeyParent.id}`,
                  )
                }
              />
            ) : null}
            <NodeZoomCard node={node} tzOffsetHours={tz} />
          </div>

          {/* The facet rail: aside on desktop, stacked below on mobile. */}
          <aside className="flex w-full shrink-0 flex-col gap-4 lg:w-[320px]">
            {/* Traveler: firm up this one pending card (pending → approved);
                clearing the last pending card derives the plan to approved. An
                advisor never approves per-card here. */}
            {canApprove && !canEdit && node.status === "pending" ? (
              <ApprovalFacet
                pending={approvingNodeId === node.id}
                onApprove={() => storeApi.getState().approveNode(node.id)}
              />
            ) : null}
            <ActionsFacet node={node} />
            <AskFacet onAsk={onAsk} />
            {node.type !== "note" ? (
              <NotesPanel
                notes={notes}
                canAdd={canLeaveNote}
                viewerActorKind={canEdit ? "advisor" : "client"}
                onAddNote={(text) => storeApi.getState().addAttachedNote(node.id, text)}
                onDeleteNote={
                  canLeaveNote
                    ? (noteId) => storeApi.getState().removeNode(noteId)
                    : undefined
                }
              />
            ) : null}
            {editable ? (
              <ScheduleFacet
                node={node}
                days={timeline.days}
                tz={tz}
                onMove={(dayKey, minute) => storeApi.getState().moveNode(node.id, dayKey, minute)}
                onUnschedule={() => storeApi.getState().unscheduleNode(node.id)}
                onEditTitle={(value) => storeApi.getState().editNodeField(node.id, "title", value)}
              />
            ) : null}
            {/* (ADV-13) post-creation details. A note's text IS its title, and
                cost/confirmation don't apply to it — notes skip the facet. */}
            {editable && node.type !== "note" ? (
              <EditFacet
                node={node}
                canEditPrice={canEdit}
                onSave={(input) =>
                  storeApi.getState().updateCardDetails(node.id, input)
                }
              />
            ) : null}
            <MoneyFacet
              nodeId={node.id}
              itineraryId={itineraryId}
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              nodeCost={
                node.cost_amount != null && node.cost_currency != null
                  ? {
                      amount: node.cost_amount,
                      currency: node.cost_currency,
                      kind: node.cost_kind ?? "total",
                    }
                  : null
              }
            />
            {/* Remove (soft delete). A note is feedback and always removable; any
                other card only while pre-firmed (a firmed booking must be demoted
                first — the store guard + backend enforce this, so we simply hide
                the control). Available to anyone who can write. */}
            {canLeaveNote && (node.type === "note" || !node.lock_reason) ? (
              <RemoveFacet
                isNote={node.type === "note"}
                onRemove={() => {
                  storeApi.getState().removeNode(node.id);
                  router.push(backHref);
                }}
              />
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}

// ── Approval — node-by-node "Approve this" (ADV-10) ─────────────────────────────
function ApprovalFacet({
  pending,
  onApprove,
}: {
  pending: boolean;
  onApprove: () => void;
}) {
  return (
    <FacetCard label="Approval" testid="card-detail-approval">
      <p className="font-serif text-[13px] text-ink/70">
        Happy with this one? Approve it now, or approve the whole plan at once
        from the dashboard.
      </p>
      <button
        type="button"
        onClick={onApprove}
        disabled={pending}
        data-testid="card-detail-approve-node"
        className="mt-2 h-9 rounded-full bg-ink px-5 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
      >
        Approve this
      </button>
    </FacetCard>
  );
}

// ── Remove — soft-delete this item (notes always; else pre-firmed only) ─────────
function RemoveFacet({
  isNote,
  onRemove,
}: {
  isNote: boolean;
  onRemove: () => void;
}) {
  return (
    <FacetCard label={isNote ? "Note" : "Remove"} testid="card-detail-remove">
      <p className="font-serif text-[13px] text-ink/70">
        {isNote
          ? "Done with this note? Delete it — it disappears from the plan."
          : "Remove this item from the itinerary — it disappears from the plan."}
      </p>
      <button
        type="button"
        onClick={onRemove}
        data-testid="card-detail-remove-node"
        className="mt-2 h-9 rounded-md border border-[#8b2a1d]/40 px-4 font-sans text-[11px] uppercase tracking-[0.16em] text-[#8b2a1d] transition-colors hover:bg-[#8b2a1d]/5"
      >
        {isNote ? "Delete note" : "Remove from itinerary"}
      </button>
    </FacetCard>
  );
}

// ── (a) Actions ───────────────────────────────────────────────────────────────
function ActionsFacet({ node }: { node: NodeResponse }) {
  const loc = getHMeta(node).location;
  if (!loc) return null;
  // Lat,lng are URL-safe; Google Maps takes the bare pair as query/destination.
  const q = `${loc.lat},${loc.lng}`;
  const search = `https://www.google.com/maps/search/?api=1&query=${q}`;
  const directions = `https://www.google.com/maps/dir/?api=1&destination=${q}`;
  return (
    <FacetCard label="Getting there" testid="card-detail-actions">
      {loc.label ? <p className="font-serif text-[13px] text-ink/70">{loc.label}</p> : null}
      <div className="mt-2 flex flex-col gap-2">
        <ActionLink href={search}>Open in Google Maps</ActionLink>
        <ActionLink href={directions}>Driving directions</ActionLink>
      </div>
    </FacetCard>
  );
}

function ActionLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="flex h-9 items-center justify-center rounded-md border border-ink/15 bg-paper font-sans text-[11px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5 hover:text-ink"
    >
      {children}
    </a>
  );
}

// ── (d) Ask Artemis about this ──────────────────────────────────────────────────
function AskFacet({ onAsk }: { onAsk: () => void }) {
  return (
    <FacetCard label="Concierge" testid="card-detail-ask-facet">
      <button
        type="button"
        onClick={onAsk}
        data-testid="card-detail-ask"
        className="flex h-9 w-full items-center justify-center rounded-md border border-[#F5701F]/40 bg-[rgba(245,112,31,0.06)] font-sans text-[11px] uppercase tracking-[0.16em] text-[#8a3d12] transition-colors hover:bg-[rgba(245,112,31,0.12)]"
      >
        Ask Artemis about this
      </button>
    </FacetCard>
  );
}

// ── (e) Manual scheduling ───────────────────────────────────────────────────────
function ScheduleFacet({
  node,
  days,
  tz,
  onMove,
  onUnschedule,
  onEditTitle,
}: {
  node: NodeResponse;
  days: Array<{ date: string; label: string }>;
  tz: number;
  onMove: (dayKey: string, minute: number) => void;
  onUnschedule: () => void;
  onEditTitle: (value: string) => void;
}) {
  const meta = getHMeta(node);
  const scheduled =
    meta.start_synthesized !== true &&
    typeof meta.start_time === "string" &&
    meta.start_time.length > 0;
  const current = scheduled && meta.start_time ? isoToDayMinute(meta.start_time, tz) : null;

  const firstDay = days[0]?.date ?? "";
  const [dayKey, setDayKey] = useState(current?.dayKey ?? firstDay);
  const [hhmm, setHhmm] = useState(minuteToHHMM(current?.minute ?? 12 * 60));

  return (
    <FacetCard label="Scheduling" testid="card-detail-schedule">
      <label className="block">
        <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">Title</span>
        <input
          type="text"
          defaultValue={node.title}
          onBlur={(e) => onEditTitle(e.target.value)}
          data-testid="card-detail-title"
          className="mt-1 w-full border-0 border-b border-ink/15 bg-transparent font-serif text-base text-ink focus:border-ink/40 focus:outline-hidden"
        />
      </label>

      {days.length > 0 ? (
        <div className="mt-3 flex items-end gap-2">
          <label className="min-w-0 flex-1">
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">Day</span>
            <select
              value={dayKey}
              onChange={(e) => setDayKey(e.target.value)}
              data-testid="card-detail-day"
              className="mt-1 h-9 w-full rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
            >
              {days.map((d) => (
                <option key={d.date} value={d.date}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">Time</span>
            <input
              type="time"
              value={hhmm}
              onChange={(e) => setHhmm(e.target.value)}
              data-testid="card-detail-time"
              className="mt-1 h-9 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
            />
          </label>
        </div>
      ) : null}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => onMove(dayKey, hhmmToMinute(hhmm))}
          disabled={!dayKey}
          data-testid="card-detail-apply-schedule"
          className="h-9 flex-1 rounded-md border border-ink/20 bg-paper font-sans text-[11px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5 disabled:opacity-40"
        >
          {scheduled ? "Update time" : "Schedule"}
        </button>
        {scheduled ? (
          <button
            type="button"
            onClick={onUnschedule}
            data-testid="card-detail-unschedule"
            className="h-9 rounded-md border border-ink/20 px-3 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/60 transition-colors hover:bg-ink/5"
          >
            Unschedule
          </button>
        ) : null}
      </div>
    </FacetCard>
  );
}

// ── (g) Edit — post-creation card details (ADV-13) ──────────────────────────────
// Cards were write-once after the composer: title + schedule only. This facet
// closes the rest — description (renders in every zoom body), first-class price
// (feeds totals + billing; also how a pasted-link card finally gets priced), and
// the operator's confirmation number (renders as the booked/confirmed footer
// serial — the "manually booked off-inventory" reminder in doc/qa/advisor.md).

const COST_KIND_OPTIONS: ReadonlyArray<{ value: CostKind; label: string }> = [
  { value: "total", label: "Total" },
  { value: "per_person", label: "Per person" },
];

function EditFacet({
  node,
  canEditPrice,
  onSave,
}: {
  node: NodeResponse;
  // Price is advisor-only, even on a traveler's own fork: a traveler may reshape
  // and annotate their version but never re-quote it. Description + confirmation
  // stay editable by whoever holds the fork.
  canEditPrice: boolean;
  onSave: (input: {
    description?: string;
    confirmationNumber?: string;
    cost?: { amount: string; currency: string; kind: CostKind } | null;
  }) => void;
}) {
  const meta = (node.metadata ?? {}) as {
    description?: unknown;
    confirmation_number?: unknown;
  };
  const seedDescription =
    typeof meta.description === "string" ? meta.description : "";
  const seedConfirmation =
    typeof meta.confirmation_number === "string" ? meta.confirmation_number : "";
  const seedAmount = node.cost_amount ?? "";
  const seedCurrency = node.cost_currency ?? "USD";
  const seedKind: CostKind = node.cost_kind ?? "total";

  const [description, setDescription] = useState(seedDescription);
  const [confirmation, setConfirmation] = useState(seedConfirmation);
  const [amount, setAmount] = useState(seedAmount);
  const [currency, setCurrency] = useState(seedCurrency);
  const [kind, setKind] = useState<CostKind>(seedKind);

  const amountTrim = amount.trim();
  const amountValid =
    amountTrim === "" || Number.isFinite(Number.parseFloat(amountTrim));
  const costChanged =
    canEditPrice &&
    (amountTrim !== seedAmount ||
      (amountTrim !== "" &&
        (currency.trim().toUpperCase() !== seedCurrency || kind !== seedKind)));
  const dirty =
    description !== seedDescription ||
    confirmation !== seedConfirmation ||
    costChanged;

  const save = () => {
    if (!dirty || !amountValid) return;
    const input: Parameters<typeof onSave>[0] = {};
    if (description !== seedDescription) input.description = description;
    if (confirmation !== seedConfirmation) input.confirmationNumber = confirmation;
    if (costChanged) {
      input.cost = amountTrim
        ? {
            amount: amountTrim,
            currency: currency.trim().toUpperCase() || "USD",
            kind,
          }
        : null;
    }
    onSave(input);
  };

  const fieldClass =
    "rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-sm text-ink";

  return (
    <FacetCard label="Edit details" testid="card-detail-edit">
      <div className="flex flex-col gap-2.5">
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
            Description
          </span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            data-testid="card-edit-description"
            className={`${fieldClass} resize-y leading-relaxed`}
            placeholder="What makes this one special…"
          />
        </label>

        {canEditPrice ? (
          <label className="flex flex-col gap-1">
            <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
              Price
            </span>
            <span className="flex items-center gap-1.5">
              <input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="decimal"
                placeholder="1200.00"
                data-testid="card-edit-amount"
                className={`${fieldClass} w-28 text-right tabular-nums`}
              />
              <input
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                maxLength={3}
                aria-label="Price currency"
                data-testid="card-edit-currency"
                className={`${fieldClass} w-16 uppercase`}
              />
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as CostKind)}
                aria-label="Price kind"
                data-testid="card-edit-kind"
                className={fieldClass}
              >
                {COST_KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </span>
            <span className="font-serif text-[12px] italic text-ink/45">
              Clear the amount to remove the price.
            </span>
          </label>
        ) : null}

        <label className="flex flex-col gap-1">
          <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
            Confirmation # / PNR
          </span>
          <input
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder="e.g. HX7KQ2"
            data-testid="card-edit-confirmation"
            className={`${fieldClass} font-mono`}
          />
          <span className="font-serif text-[12px] italic text-ink/45">
            Shown on the card once this is booked or confirmed.
          </span>
        </label>

        <button
          type="button"
          onClick={save}
          disabled={!dirty || !amountValid}
          data-testid="card-edit-save"
          className="h-9 self-start rounded-full bg-ink px-5 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-40"
        >
          Save details
        </button>
      </div>
    </FacetCard>
  );
}

// ── (f) Money — the per-inventory line ──────────────────────────────────────────
function MoneyFacet({
  nodeId,
  itineraryId,
  apiBaseUrl,
  accessToken,
  nodeCost,
}: {
  nodeId: string;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
  nodeCost: { amount: string; currency: string; kind: CostKind } | null;
}) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "error" }
    | { kind: "ready"; charges: NodeChargesResponse }
  >({ kind: "loading" });

  useEffect(() => {
    if (!apiBaseUrl || !accessToken) {
      setState({ kind: "error" });
      return;
    }
    let cancelled = false;
    void (async () => {
      const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const result = await getNodeCharges(client, itineraryId, nodeId);
      if (cancelled) return;
      setState(result.ok ? { kind: "ready", charges: result.charges } : { kind: "error" });
    })();
    return () => {
      cancelled = true;
    };
  }, [nodeId, itineraryId, apiBaseUrl, accessToken]);

  return (
    <FacetCard label="This item · money" testid="card-detail-money">
      <div className="flex flex-col gap-1.5">
        {/* The item's own quoted price — read-only, shown to everyone (a traveler
            sees what a thing costs even before it's ever invoiced). Editing it is
            advisor-only, gated in the separate Edit facet. */}
        {nodeCost ? (
          <MoneyRow
            label="Price"
            value={priceLabel(nodeCost)}
            testid="card-detail-money-price"
          />
        ) : null}
        {state.kind === "loading" ? (
          <p className="font-serif text-[13px] italic text-ink/45">Checking the ledger…</p>
        ) : state.kind === "error" ? (
          <p className="font-serif text-[13px] italic text-ink/45">
            Costs aren&rsquo;t available right now.
          </p>
        ) : (
          <MoneyBody charges={state.charges} hasNodePrice={nodeCost !== null} />
        )}
      </div>
    </FacetCard>
  );
}

// A node's own quoted price ("USD 1000.00", or "… / person" when per-traveler).
function priceLabel(cost: { amount: string; currency: string; kind: CostKind }): string {
  const base = `${cost.currency} ${cost.amount}`;
  return cost.kind === "per_person" ? `${base} / person` : base;
}

const NODE_STATUS_LABEL: Record<string, string> = {
  booked: "Booked",
  confirmed: "Confirmed",
  discarded: "Cancelled",
};

function MoneyBody({
  charges,
  hasNodePrice,
}: {
  charges: NodeChargesResponse;
  hasNodePrice: boolean;
}) {
  const cur = charges.currency;
  const money = (v: string): string => (cur ? `${cur} ${v}` : v);
  const owed = Number.parseFloat(charges.owed_amount);
  const nothingBilled = !cur && charges.booking === null;

  if (nothingBilled) {
    // The price (if any) is already shown above as its own row. What's left here
    // is billing state: a priced-but-unbilled item is an advisor to-do ("bill
    // it"); a truly costless item is just informational.
    return hasNodePrice ? (
      <p
        data-testid="card-detail-money-uninvoiced"
        className="font-serif text-[13px] italic text-[#8a5a1d]"
      >
        Not yet on an invoice.
      </p>
    ) : (
      <p data-testid="card-detail-money-empty" className="font-serif text-[13px] italic text-ink/45">
        Nothing has been charged for this item yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {cur ? (
        <>
          <MoneyRow label="Charge" value={money(charges.billed_amount)} />
          <MoneyRow label="Paid" value={money(charges.paid_amount)} />
          <MoneyRow
            label="Owed"
            value={money(charges.owed_amount)}
            emphasize={owed > 0}
          />
        </>
      ) : null}
      {charges.invoice_status ? (
        charges.invoice_id ? (
          <a
            href={`/invoices/${charges.invoice_id}`}
            data-testid="card-detail-money-invoice-link"
            className="pt-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55 underline decoration-ink/20 underline-offset-2 hover:text-ink"
          >
            On invoice · {charges.invoice_status}
          </a>
        ) : (
          <p className="pt-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
            Invoice · {charges.invoice_status}
          </p>
        )
      ) : null}
      {charges.booking ? (
        <p
          data-testid="card-detail-booking"
          className="pt-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55"
        >
          {NODE_STATUS_LABEL[charges.booking.node_status] ?? charges.booking.node_status}
          {charges.booking.supplier_ref ? ` · ${charges.booking.supplier_ref}` : ""}
        </p>
      ) : null}
    </div>
  );
}

function MoneyRow({
  label,
  value,
  emphasize = false,
  testid,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
  testid?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3" data-testid={testid}>
      <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/45">{label}</span>
      <span
        className={
          "font-serif tabular-nums " + (emphasize ? "text-base text-[#8b2a1d]" : "text-sm text-ink")
        }
      >
        {value}
      </span>
    </div>
  );
}

// ── Shared facet chrome ─────────────────────────────────────────────────────────
function FacetCard({
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
      className="rounded-lg border border-ink/12 bg-paper/95 px-4 py-3"
    >
      <div className="mb-2 font-sans text-[10px] uppercase tracking-[0.22em] text-ink/50">
        {label}
      </div>
      {children}
    </section>
  );
}
