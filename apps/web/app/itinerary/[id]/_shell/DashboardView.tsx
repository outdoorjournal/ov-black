"use client";

// The per-trip Dashboard (M006/PS3) — the "you're not lost" home the itinerary
// index lands on. It gathers the trip-management surfaces the old eight-tab aside
// scattered (design §4): an editable brief/splash HERO, ONE guided next best
// action, the money ROLL-UP (total owed · issued · what-to-pay, which the PS4
// card money facet rolls up into and deep-links back down from), the travel
// PARTY, and — for an advisor — the Vault/Invoices/Booking management panels
// rehomed out of the transitional Studio (Studio keeps Build/Diff, PS6 finalises).
// Role-agnostic: both roles land here; affordances differ by `role`.

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  createApiClient,
  listInvoices,
  listItineraryParty,
  type InvoiceResponse,
  type InvoiceStatus,
  type ItineraryPartyEntry,
} from "@ov-black/api-client";

import { ItineraryIntake } from "@/app/_components/itinerary-graph/intake/ItineraryIntake";
import {
  itineraryGraphStore,
  selectCanApprove,
  selectCanPropose,
  selectCanReopen,
  selectEditable,
  selectScheduledCount,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { BookingPanel } from "@/app/_components/itinerary-graph/views/horizontal/BookingPanel";
import { InvoicePanel } from "@/app/_components/itinerary-graph/views/horizontal/InvoicePanel";
import { PartyPanel } from "@/app/_components/itinerary-graph/views/horizontal/PartyPanel";
import { VaultPanel } from "@/app/_components/itinerary-graph/views/horizontal/VaultPanel";
import { DEFAULT_MOOD, MOODS, type MoodEntry } from "@/lib/atmos/moods";

import { useConciergeControl } from "./ConciergeControl";
import {
  deriveNextAction,
  firstUnpaidIssued,
  formatTiming,
  invoiceOwed,
  isPayable,
  rollupInvoices,
  type CurrencyRollup,
  type NextAction,
} from "./dashboardModel";

type MoneyState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; invoices: InvoiceResponse[] };

export function DashboardView() {
  const router = useRouter();
  const { timeline } = useTimelineData();
  const { openConcierge } = useConciergeControl();

  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const scheduledCount = itineraryGraphStore.useStore(selectScheduledCount);
  const pendingCount = itineraryGraphStore.useStore((s) => s.pendingProposals.length);

  const isAdvisor = role === "advisor";
  const it = timeline.itinerary;
  const clientId = it.client_id;

  const [editing, setEditing] = useState(false);
  const [money, setMoney] = useState<MoneyState>({ kind: "loading" });

  useEffect(() => {
    if (!apiBaseUrl || !accessToken) {
      setMoney({ kind: "error" });
      return;
    }
    let cancelled = false;
    void (async () => {
      const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const result = await listInvoices(client, itineraryId);
      if (cancelled) return;
      setMoney(
        result.ok
          ? { kind: "ready", invoices: result.invoices }
          : { kind: "error" },
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [itineraryId, apiBaseUrl, accessToken]);

  const firstUnpaid = useMemo(
    () => (money.kind === "ready" ? firstUnpaidIssued(money.invoices) : null),
    [money],
  );
  const nextAction = useMemo(
    () =>
      deriveNextAction({
        role: isAdvisor ? "advisor" : "client",
        scheduledCount,
        pendingCount,
        firstUnpaid,
        itineraryId,
      }),
    [isAdvisor, scheduledCount, pendingCount, firstUnpaid, itineraryId],
  );

  // Editing the brief re-runs the intake prefilled; the brief/timing are a server
  // prop, so a save must refresh the route to pull the new value back down.
  if (editing && apiBaseUrl && accessToken) {
    return (
      <ItineraryIntake
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        audience={isAdvisor ? "advisor" : "traveler"}
        initial={{
          brief: it.brief ?? null,
          timingKind: it.timing_kind ?? null,
          dateStart: it.date_start ?? null,
          dateEnd: it.date_end ?? null,
          durationNights: it.duration_nights ?? null,
          timingNote: it.timing_note ?? null,
        }}
        onSaved={() => {
          setEditing(false);
          router.refresh();
        }}
        onSkip={() => setEditing(false)}
      />
    );
  }

  return (
    <div
      data-testid="dashboard"
      className="min-h-0 flex-1 overflow-y-auto bg-paper"
    >
      <Hero
        title={it.title?.trim() || "Your trip"}
        brief={it.brief ?? null}
        timing={formatTiming(it)}
        mood={timeline.mood}
        canEdit={apiBaseUrl !== null && accessToken !== null}
        onEdit={() => setEditing(true)}
      />

      <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <NextActionCard action={nextAction} onConcierge={openConcierge} />
        <ApprovalSection />
        <MoneySection state={money} role={isAdvisor ? "advisor" : "client"} itineraryId={itineraryId} />
        <PartySection
          isAdvisor={isAdvisor}
          clientId={clientId}
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
        />
        {isAdvisor ? (
          <AdvisorManagement
            itineraryId={itineraryId}
            clientId={clientId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
          />
        ) : null}
      </div>
    </div>
  );
}

// ── Hero — brief · splash · timing ───────────────────────────────────────────
function Hero({
  title,
  brief,
  timing,
  mood,
  canEdit,
  onEdit,
}: {
  title: string;
  brief: string | null;
  timing: string;
  mood: string;
  canEdit: boolean;
  onEdit: () => void;
}) {
  const entry = (MOODS as Record<string, MoodEntry>)[mood];
  const imageUrl = entry?.imageUrl ?? MOODS[DEFAULT_MOOD].imageUrl;

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
      <div className="mx-auto w-full max-w-5xl">
        <p className="font-sans text-[11px] uppercase tracking-[0.28em] text-white/70">
          {timing}
        </p>
        <h1 className="mt-2 max-w-3xl font-serif text-3xl leading-tight text-white sm:text-4xl">
          {title}
        </h1>
        {brief ? (
          <p className="mt-3 max-w-2xl font-serif text-lg italic leading-snug text-white/85">
            {brief}
          </p>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            onClick={onEdit}
            data-testid="dashboard-hero-edit"
            className="mt-4 self-start rounded-full border border-white/40 px-4 py-1.5 font-sans text-[11px] uppercase tracking-[0.18em] text-white/90 transition-colors hover:border-white hover:bg-white/10"
          >
            {brief ? "Edit the brief" : "Set the brief"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

// ── Next best action ─────────────────────────────────────────────────────────
function NextActionCard({
  action,
  onConcierge,
}: {
  action: NextAction;
  onConcierge: () => void;
}) {
  return (
    <SectionCard label="Next" testid="dashboard-next-action">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="font-serif text-xl text-ink">{action.label}</p>
          <p className="mt-0.5 font-sans text-[13px] text-ink/55">{action.detail}</p>
        </div>
        {action.target.kind === "href" ? (
          <Link
            href={action.target.href as Route}
            data-testid="dashboard-next-cta"
            className="shrink-0 self-start rounded-full bg-ink px-5 py-2 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90"
          >
            {action.cta}
          </Link>
        ) : (
          <button
            type="button"
            onClick={onConcierge}
            data-testid="dashboard-next-cta"
            className="shrink-0 self-start rounded-full bg-ink px-5 py-2 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90"
          >
            {action.cta}
          </button>
        )}
      </div>
    </SectionCard>
  );
}

// ── Money roll-up ────────────────────────────────────────────────────────────
// ── Approval — propose → approve, per-currency total (ADV-10) ────────────────
//
// The itinerary's proposed → approved arc lives here. The advisor *proposes*
// the finished plan (draft → proposed), which freezes the build for review; the
// traveler *approves* it — the all-at-once "Approve all" here, or card-by-card
// on the timeline (both derive the itinerary to `approved`). The plan's
// per-currency price (from the graph read's `totals`) shows alongside, so the
// traveler sees what they're approving. Craft-feel: no spinners/icons — a
// disabled button is the only in-flight affordance.
function ApprovalSection() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const status = itineraryGraphStore.useStore((s) => s.status);
  const totals = itineraryGraphStore.useStore((s) => s.totals);
  const canPropose = itineraryGraphStore.useStore(selectCanPropose);
  const canReopen = itineraryGraphStore.useStore(selectCanReopen);
  const canApprove = itineraryGraphStore.useStore(selectCanApprove);
  const proposePending = itineraryGraphStore.useStore((s) => s.proposePending);
  const reopenPending = itineraryGraphStore.useStore((s) => s.reopenPending);
  const approvePending = itineraryGraphStore.useStore((s) => s.approvePending);
  const propose = itineraryGraphStore.useStore((s) => s.propose);
  const reopen = itineraryGraphStore.useStore((s) => s.reopen);
  const approve = itineraryGraphStore.useStore((s) => s.approve);

  const isAdvisor = role === "advisor";
  const totalEntries = Object.entries(totals);
  const hasTotals = totalEntries.length > 0;

  // Nothing to show on a plain draft with no price and no advisor propose action
  // (e.g. a traveler looking at a draft the advisor is still building).
  if (status === "draft" && !canPropose && !hasTotals) return null;

  const primaryBtn =
    "shrink-0 self-start rounded-full bg-ink px-5 py-2 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50";
  const secondaryBtn =
    "shrink-0 self-start rounded-full border border-ink/20 bg-transparent px-5 py-2 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/80 transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50";

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
              : status === "proposed"
                ? isAdvisor
                  ? "Proposed — awaiting the traveler"
                  : "Ready for your approval"
                : "Ready to send"}
          </p>
          <p className="mt-0.5 font-sans text-[13px] text-ink/55">
            {status === "approved"
              ? "The whole plan is approved."
              : status === "proposed"
                ? isAdvisor
                  ? "The traveler can approve the plan, or firm up cards one at a time."
                  : "Approve the whole plan, or approve cards one at a time on the timeline."
                : "Send the finished plan to the traveler for approval."}
          </p>
          {hasTotals ? (
            <div
              data-testid="dashboard-trip-total"
              className="mt-3 flex flex-col gap-0.5"
            >
              <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
                Trip total
              </span>
              {totalEntries.map(([currency, amount]) => (
                <span
                  key={currency}
                  data-testid="dashboard-trip-total-row"
                  data-currency={currency}
                  className="font-serif text-lg text-ink"
                >
                  {money(currency, Number(amount))}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-2">
          {canPropose ? (
            <button
              type="button"
              onClick={propose}
              disabled={proposePending}
              data-testid="dashboard-propose"
              className={primaryBtn}
            >
              Propose to traveler
            </button>
          ) : null}
          {canReopen ? (
            <button
              type="button"
              onClick={reopen}
              disabled={reopenPending}
              data-testid="dashboard-reopen"
              className={secondaryBtn}
            >
              Reopen to edit
            </button>
          ) : null}
          {/* Traveler's one-action "Approve all" (advisor uses propose/reopen). */}
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

function MoneySection({
  state,
  role,
  itineraryId,
}: {
  state: MoneyState;
  role: "advisor" | "client";
  itineraryId: string;
}) {
  return (
    <SectionCard label="Money" testid="dashboard-money">
      {state.kind === "loading" ? (
        <p className="font-serif text-[13px] italic text-ink/45">Checking the ledger…</p>
      ) : state.kind === "error" ? (
        <p className="font-serif text-[13px] italic text-ink/45">
          The ledger isn’t available right now.
        </p>
      ) : (
        <MoneyBody invoices={state.invoices} role={role} itineraryId={itineraryId} />
      )}
    </SectionCard>
  );
}

const money = (currency: string, amount: number): string =>
  `${currency} ${amount.toFixed(2)}`;

function MoneyBody({
  invoices,
  role,
  itineraryId,
}: {
  invoices: InvoiceResponse[];
  role: "advisor" | "client";
  itineraryId: string;
}) {
  const { byCurrency, issuedCount, hasOwed } = rollupInvoices(invoices);
  // Only issued/paid invoices are the traveler-facing ledger; drafts are advisor
  // scaffolding (managed in the Invoices panel below) and never "owed" yet.
  const rows = invoices
    .filter((i) => i.status === "issued" || i.status === "paid")
    .sort((a, b) => statusRank(a.status) - statusRank(b.status));

  if (rows.length === 0) {
    return (
      <p
        data-testid="dashboard-money-empty"
        className="font-serif text-[13px] italic text-ink/45"
      >
        {role === "advisor"
          ? "No invoices issued yet."
          : "Nothing to settle right now."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* The glance: owed per currency + how many invoices are out. */}
      <div className="flex flex-col gap-1.5">
        {byCurrency.map((c) => (
          <RollupRow key={c.currency} rollup={c} />
        ))}
        <p className="pt-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
          {issuedCount === 0
            ? "All invoices settled"
            : `${issuedCount} invoice${issuedCount === 1 ? "" : "s"} issued`}
          {hasOwed ? " · balance outstanding" : ""}
        </p>
      </div>

      {/* Per-invoice rows — pay from here (the existing /invoices/[id] page); the
          per-inventory charge lines deep-link DOWN into the card money facet. */}
      <ul className="flex flex-col divide-y divide-ink/10 border-t border-ink/10">
        {rows.map((inv) => (
          <InvoiceRow key={inv.id} invoice={inv} itineraryId={itineraryId} />
        ))}
      </ul>
    </div>
  );
}

const statusRank = (s: InvoiceStatus): number =>
  s === "issued" ? 0 : s === "paid" ? 1 : 2;

function RollupRow({ rollup }: { rollup: CurrencyRollup }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/45">
        {rollup.owed > 0.005 ? "Owed" : "Settled"}
      </span>
      <span
        className={
          "font-serif tabular-nums " +
          (rollup.owed > 0.005 ? "text-base text-[#8b2a1d]" : "text-sm text-ink")
        }
      >
        {money(rollup.currency, rollup.owed > 0.005 ? rollup.owed : rollup.billed)}
      </span>
    </div>
  );
}

function InvoiceRow({
  invoice,
  itineraryId,
}: {
  invoice: InvoiceResponse;
  itineraryId: string;
}) {
  const payable = isPayable(invoice);
  const owed = invoiceOwed(invoice);
  // "What to pay" children: the charge lines carrying a node — each rolls up from
  // (and links back to) that card's own money facet.
  const nodeLines = (invoice.lines ?? []).filter(
    (l) => l.kind === "charge" && typeof l.node_id === "string" && l.node_id.length > 0,
  );

  return (
    <li data-testid="dashboard-invoice-row" className="flex flex-col gap-1.5 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-serif text-sm text-ink">{invoice.label}</p>
          <p className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
            {STATUS_LABEL[invoice.status]}
            {payable ? ` · ${money(invoice.currency, owed)} due` : ""}
          </p>
        </div>
        {payable ? (
          <Link
            href={`/invoices/${invoice.id}` as Route}
            data-testid="dashboard-invoice-pay"
            className="shrink-0 rounded-full border border-ink/25 px-4 py-1.5 font-sans text-[11px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink hover:text-paper"
          >
            View &amp; pay
          </Link>
        ) : (
          <span className="shrink-0 font-serif text-sm tabular-nums text-ink/70">
            {money(invoice.currency, Number.parseFloat(invoice.total))}
          </span>
        )}
      </div>
      {nodeLines.length > 0 ? (
        <ul className="flex flex-col gap-0.5 pl-1">
          {nodeLines.map((line) => (
            <li key={line.id}>
              <Link
                href={`/itinerary/${itineraryId}/item/${line.node_id}` as Route}
                data-testid="dashboard-invoice-line"
                className="flex items-baseline justify-between gap-3 font-sans text-[12px] text-ink/55 transition-colors hover:text-ink"
              >
                <span className="min-w-0 truncate underline-offset-2 hover:underline">
                  {line.description}
                </span>
                <span className="shrink-0 tabular-nums">
                  {money(line.currency, Number.parseFloat(line.amount))}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

const STATUS_LABEL: Record<InvoiceStatus, string> = {
  draft: "Draft",
  issued: "Issued",
  paid: "Paid",
  void: "Void",
};

// ── Travel party ─────────────────────────────────────────────────────────────
function PartySection({
  isAdvisor,
  clientId,
  itineraryId,
  apiBaseUrl,
  accessToken,
}: {
  isAdvisor: boolean;
  clientId: string | null;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  if (isAdvisor) {
    // The advisor gets the full attach/detach panel rehomed from Studio.
    return (
      <SectionCard label="Travel party" testid="dashboard-party">
        <PartyPanel
          clientId={clientId}
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
        />
      </SectionCard>
    );
  }
  return (
    <SectionCard label="Travel party" testid="dashboard-party">
      <PartyGlance
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
      />
    </SectionCard>
  );
}

// A traveler's read-only "who's coming" glance — the itinerary party is theirs to
// read (require_user), but building the household roster is self-service at
// /basecamp/party, so we point there rather than embed the advisor panel.
function PartyGlance({
  itineraryId,
  apiBaseUrl,
  accessToken,
}: {
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "error" }
    | { kind: "ready"; members: ItineraryPartyEntry[] }
  >({ kind: "loading" });

  useEffect(() => {
    if (!apiBaseUrl || !accessToken) {
      setState({ kind: "error" });
      return;
    }
    let cancelled = false;
    void (async () => {
      const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const result = await listItineraryParty(client, itineraryId);
      if (cancelled) return;
      setState(
        result.ok
          ? { kind: "ready", members: result.party.members }
          : { kind: "error" },
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [itineraryId, apiBaseUrl, accessToken]);

  return (
    <div className="flex flex-col gap-3">
      {state.kind === "loading" ? (
        <p className="font-serif text-[13px] italic text-ink/45">Gathering the party…</p>
      ) : state.kind === "error" || state.members.length === 0 ? (
        <p className="font-serif text-[13px] italic text-ink/45">
          Just you so far.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {state.members.map((m) => (
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
        href={"/basecamp/party" as Route}
        className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
      >
        Manage your household →
      </Link>
    </div>
  );
}

// ── Advisor management — Vault · Invoices · Booking (rehomed from Studio) ──────
type ManageTab = "vault" | "invoices" | "booking";
const MANAGE_LABEL: Record<ManageTab, string> = {
  vault: "Vault",
  invoices: "Invoices",
  booking: "Booking",
};

function AdvisorManagement({
  itineraryId,
  clientId,
  apiBaseUrl,
  accessToken,
}: {
  itineraryId: string;
  clientId: string | null;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  // Invoicing is advisor-only server-side and independent of the graph edit-lock
  // (it must work on an approved trip), so it gates on role, not `editable`.
  const canManageInvoices = itineraryGraphStore.useStore((s) => s.canEdit);
  const [tab, setTab] = useState<ManageTab>("invoices");

  return (
    <SectionCard label="Trip management" testid="dashboard-manage">
      <div
        role="tablist"
        aria-label="Trip management"
        className="mb-3 flex flex-wrap gap-1 border-b border-ink/10 pb-2"
      >
        {(["vault", "invoices", "booking"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            data-testid={`dashboard-manage-tab-${t}`}
            className={`h-8 rounded-md px-3 font-sans text-[11px] uppercase tracking-[0.16em] transition-colors ${
              tab === t ? "bg-ink/10 text-ink" : "text-ink/55 hover:bg-ink/5"
            }`}
          >
            {MANAGE_LABEL[t]}
          </button>
        ))}
      </div>
      <div className="relative min-h-0">
        <div className={tab === "vault" ? "" : "hidden"}>
          <VaultPanel
            clientId={clientId}
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
          />
        </div>
        <div className={tab === "invoices" ? "" : "hidden"}>
          <InvoicePanel
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
            canManage={canManageInvoices}
          />
        </div>
        <div className={tab === "booking" ? "" : "hidden"}>
          <BookingPanel
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
            editable={editable}
          />
        </div>
      </div>
    </SectionCard>
  );
}

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
