"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import {
  type InvoiceResponse,
  type NodeResponse,
  createApiClient,
  getItinerary,
  listInvoices,
} from "@ov-black/api-client";

import {
  type FinanceRow,
  deriveFinanceRows,
} from "@/app/itinerary/[id]/_shell/dashboardModel";
import { TYPE_TOKENS, type CardKind } from "../../shared/cards/tokens";

// The per-item Finances table (doc/thoughts.md §3) — every itinerary item that
// carries a cost, with what's been invoiced / paid / remaining and the deposit
// due, deposit-captured inferred from paid ≥ deposit-due. Grouped by native
// currency (an item bills in its own currency; the invoice settles to one).

const money = (currency: string, amount: number): string => {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${Math.round(amount).toLocaleString()}`;
  }
};

const tokenFor = (type: string) =>
  TYPE_TOKENS[(type in TYPE_TOKENS ? type : "experience") as CardKind];

function ItemIdentity({
  node,
  itineraryId,
}: {
  node: NodeResponse | undefined;
  itineraryId: string;
  fallbackTitle?: string | undefined;
}) {
  if (!node) return null;
  const token = tokenFor(node.type);
  const Icon = token.Icon;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Icon size={13} strokeWidth={1.6} aria-hidden className="shrink-0 text-ink/55" />
      <Link
        href={`/itinerary/${itineraryId}/item/${node.id}`}
        className="min-w-0 truncate font-sans text-sm text-ink/90 underline-offset-2 hover:underline"
      >
        {node.title}
      </Link>
    </span>
  );
}

function Amount({
  currency,
  value,
  tone,
}: {
  currency: string;
  value: number;
  tone?: string | undefined;
}) {
  return (
    <span
      className="font-sans text-sm tabular-nums text-ink/85"
      style={tone ? { color: tone } : undefined}
    >
      {money(currency, value)}
    </span>
  );
}

const ATTENTION = "#8b2a1d";
const OWED = "#8a5a1d";
const PAID = "#1d6b3a";

export function FinancesTable({
  apiBaseUrl,
  accessToken,
  itineraryId,
}: {
  apiBaseUrl: string | null;
  accessToken: string | null;
  itineraryId: string;
}) {
  const [invoices, setInvoices] = useState<InvoiceResponse[]>([]);
  const [nodes, setNodes] = useState<NodeResponse[]>([]);
  const [partySize, setPartySize] = useState(1);
  const [loaded, setLoaded] = useState(false);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const api =
    apiBaseUrl && accessToken ? createApiClient({ baseUrl: apiBaseUrl, accessToken }) : null;

  const refresh = useCallback(async () => {
    if (!api) return;
    const [inv, graph] = await Promise.all([
      listInvoices(api, itineraryId),
      getItinerary(api, itineraryId),
    ]);
    if (!mounted.current) return;
    if (inv.ok) setInvoices(inv.invoices);
    if (graph.ok) {
      setNodes(graph.nodes);
      setPartySize(graph.party_size ?? 1);
    }
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const rows: FinanceRow[] = useMemo(
    () => deriveFinanceRows({ invoices, nodes, partySize }),
    [invoices, nodes, partySize],
  );

  if (!loaded) {
    return <p className="font-sans text-sm text-ink/50">Loading…</p>;
  }
  if (rows.length === 0) {
    return (
      <p className="font-sans text-sm italic text-ink/50">
        No priced items yet. Costs appear here once items are approved.
      </p>
    );
  }

  return (
    <section data-testid="finances-table" className="flex flex-col gap-2">
      <header className="flex items-baseline justify-between">
        <h3 className="font-serif text-lg tracking-tight text-ink">Trip items</h3>
        <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/40">
          {rows.length} priced
        </span>
      </header>
      <div className="overflow-x-auto rounded-lg border border-ink/10">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-ink/10 text-left">
              <th className="px-3 py-2 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
                Item
              </th>
              {(["Cost", "Invoiced", "Paid", "Remaining", "Deposit due"] as const).map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 text-right font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.nodeId}
                data-testid={`finance-row-${row.nodeId}`}
                className="border-b border-ink/5 last:border-b-0"
              >
                <td className="max-w-[16rem] px-3 py-2">
                  <ItemIdentity
                    node={nodeById.get(row.nodeId)}
                    itineraryId={itineraryId}
                    fallbackTitle={row.title}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <Amount currency={row.currency} value={row.cost} />
                </td>
                <td className="px-3 py-2 text-right">
                  <Amount currency={row.currency} value={row.invoiced} />
                </td>
                <td className="px-3 py-2 text-right">
                  <Amount
                    currency={row.currency}
                    value={row.paid}
                    tone={row.paid > 0.005 ? PAID : undefined}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <Amount
                    currency={row.currency}
                    value={row.remaining}
                    tone={row.remaining > 0.005 ? ATTENTION : undefined}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <span className="inline-flex items-center gap-1.5">
                    <Amount currency={row.currency} value={row.depositDue} tone={OWED} />
                    {row.depositPaid ? (
                      <span
                        data-testid={`deposit-paid-${row.nodeId}`}
                        className="rounded-full bg-[#1d6b3a]/10 px-1.5 py-0.5 font-sans text-[9px] uppercase tracking-[0.1em] text-[#1d6b3a]"
                      >
                        Paid
                      </span>
                    ) : null}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
