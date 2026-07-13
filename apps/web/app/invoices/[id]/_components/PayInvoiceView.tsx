"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import braintree, { type HostedFields } from "braintree-web";

import {
  type InvoicePayContextResponse,
  type InvoiceResponse,
  type PaymentQuote,
  createApiClient,
  createPaymentQuote,
  getInvoice,
  getPaymentToken,
  payInvoice,
} from "@ov-black/api-client";

// Traveler-facing pay surface (M005/I2). Shows an issued invoice's line-item
// breakdown (so the traveler understands *why* it's owed), a billing form
// pre-filled from their client record, and Braintree **Hosted Fields** for the
// card (SAQ A — card data stays in Braintree's iframes). On submit it tokenizes
// the card, forwards the billing identity, and pays. Once paid it shows the
// receipt. Mirrors the voyage-site checkout. Self-contained — the page passes the
// viewer's credentials (the API's owner/advisor gate is the real authority).

const ATTENTION = "#8b2a1d";
const POSITIVE = "#1d6b3a";

const ERROR_COPY: Record<string, string> = {
  not_found: "This invoice could not be found.",
  forbidden: "You don't have access to this invoice.",
  invoice_not_issued: "This invoice isn't ready for payment yet.",
  payment_declined: "The payment was declined. Please try another card.",
  payments_unconfigured: "Payments aren't available right now.",
  nothing_to_pay: "There's nothing to pay on this invoice.",
  quote_required: "The exchange rate needs to refresh — one moment.",
  quote_expired: "The exchange rate refreshed. Please review and pay again.",
  fx_unavailable: "Currency conversion is unavailable right now.",
  rate_unavailable: "Currency conversion is unavailable right now.",
  network_error: "Could not reach the server. Try again in a moment.",
};

// Braintree injects its card iframes into these mount points; the ids are the
// Hosted Fields selectors (mirrors voyage-site). The e2e drives the resulting
// `braintree-hosted-field-*` iframes.
const CARD_FIELD_STYLES = {
  input: { "font-size": "15px", color: "#1a1a1a" },
  ".invalid": { color: ATTENTION },
} as const;

/** M:SS countdown label for the pay-time FX lock. */
function fmtCountdown(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

/** A localized money string ("$13,442"), falling back to "CODE 1,234". */
function money(currency: string, amount: string): string {
  const n = Number.parseFloat(amount);
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(Number.isFinite(n) ? n : 0);
  } catch {
    return `${currency} ${Math.round(Number.isFinite(n) ? n : 0).toLocaleString()}`;
  }
}

/** A calendar date ("12 Jul 2026") or null for an absent timestamp. */
function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(d);
}

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

/** "Pay with test card ····1111" — the configured sandbox card, masked to last-4. */
function testCardLabel(card: string): string {
  const last4 = card.replace(/\D/g, "").slice(-4);
  return last4 ? `Pay with test card ····${last4}` : "Pay with test card";
}

type Billing = {
  name: string;
  address: string;
  city: string;
  region: string;
  postalCode: string;
  country: string;
};

function seedBilling(ctx: InvoicePayContextResponse | null): Billing {
  return {
    name: ctx?.full_name ?? "",
    address: ctx?.address ?? "",
    city: ctx?.city ?? "",
    region: ctx?.region ?? "",
    postalCode: ctx?.postal_code ?? "",
    country: ctx?.country_code ?? "",
  };
}

export function PayInvoiceView({
  apiBaseUrl,
  accessToken,
  invoiceId,
  payContext = null,
  demoTestCard = null,
}: {
  apiBaseUrl: string;
  accessToken: string;
  invoiceId: string;
  /** Trip title + billing identity for narration + prefill (server-fetched). */
  payContext?: InvoicePayContextResponse | null;
  /** Demo/dev only (env-gated by the page) — a sandbox card number to offer as a
   *  one-click pay; null/undefined hides it. Display only; the charge uses the nonce. */
  demoTestCard?: string | null;
}) {
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [cardReady, setCardReady] = useState(false);
  const [billing, setBilling] = useState<Billing>(() => seedBilling(payContext));
  // Settlement (pay-currency) invoices lock a fresh FX rate at pay time (0050):
  // fetch a quote, show a countdown, re-quote on expiry, and charge the locked id.
  const [quote, setQuote] = useState<PaymentQuote | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const hostedRef = useRef<HostedFields | null>(null);
  const mounted = useRef(true);

  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void hostedRef.current?.teardown().catch(() => undefined);
      hostedRef.current = null;
    };
  }, []);

  const refresh = useCallback(async () => {
    const result = await getInvoice(api, invoiceId);
    if (!mounted.current) return;
    if (result.ok) setInvoice(result.invoice);
    else setError(copy(result.detail));
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const isSettlement = Boolean(invoice?.settlement_currency);

  const fetchQuote = useCallback(async () => {
    const result = await createPaymentQuote(api, invoiceId);
    if (!mounted.current) return;
    if (result.ok) setQuote(result.quote);
    else {
      setQuote(null);
      setError(copy(result.detail));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, apiBaseUrl, accessToken]);

  // Fetch the first lock once a settlement invoice is issued.
  useEffect(() => {
    if (invoice?.status === "issued" && invoice.settlement_currency) void fetchQuote();
  }, [invoice?.status, invoice?.settlement_currency, fetchQuote]);

  // Tick the lock's countdown; re-quote at a fresher rate when it lapses.
  useEffect(() => {
    if (!quote) {
      setSecondsLeft(null);
      return;
    }
    const expiry = new Date(quote.expiresAt).getTime();
    const compute = () => Math.round((expiry - Date.now()) / 1000);
    setSecondsLeft(compute());
    const id = setInterval(() => {
      const left = compute();
      if (left <= 0) {
        clearInterval(id);
        setSecondsLeft(0);
        void fetchQuote();
      } else {
        setSecondsLeft(left);
      }
    }, 1000);
    return () => clearInterval(id);
  }, [quote, fetchQuote]);

  // Mount Braintree Hosted Fields once the invoice is issued + mount points exist.
  useEffect(() => {
    if (!invoice || invoice.status !== "issued" || hostedRef.current) return;
    let cancelled = false;
    void (async () => {
      const token = await getPaymentToken(api, invoiceId);
      if (cancelled || !mounted.current) return;
      if (!token.ok) {
        setError(copy(token.detail));
        return;
      }
      try {
        const clientInstance = await braintree.client.create({
          authorization: token.clientToken,
        });
        const hosted = await braintree.hostedFields.create({
          client: clientInstance,
          styles: CARD_FIELD_STYLES,
          fields: {
            number: { selector: "#cc-number", placeholder: "4111 1111 1111 1111" },
            expirationDate: { selector: "#cc-expiry", placeholder: "MM / YY" },
            cvv: { selector: "#cc-cvv", placeholder: "123" },
          },
        });
        if (cancelled || !mounted.current) {
          void hosted.teardown().catch(() => undefined);
          return;
        }
        hostedRef.current = hosted;
        setCardReady(true);
      } catch {
        if (mounted.current) setError("Could not load the payment form.");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoice?.status, invoiceId]);

  // Post a nonce and settle the invoice — shared by the real card flow and the
  // demo test-card flow (they differ only in where the nonce comes from).
  const submitNonce = useCallback(
    async (nonce: string) => {
      if (paying) return;
      // A settlement invoice charges the locked quote — never without one.
      if (isSettlement && !quote) {
        setError(copy("quote_required"));
        void fetchQuote();
        return;
      }
      setPaying(true);
      setError(null);
      try {
        const result = await payInvoice(api, invoiceId, {
          payment_method_nonce: nonce,
          ...(isSettlement && quote ? { quote_id: quote.id } : {}),
          billing_name: billing.name || null,
          billing_address: billing.address || null,
          billing_city: billing.city || null,
          billing_region: billing.region || null,
          billing_postal_code: billing.postalCode || null,
          billing_country: billing.country || null,
        });
        if (!mounted.current) return;
        if (result.ok) {
          await hostedRef.current?.teardown().catch(() => undefined);
          hostedRef.current = null;
          setInvoice(result.invoice);
        } else {
          setError(copy(result.detail));
          // The lock lapsed between quote and charge — grab a fresher one to retry.
          if (result.detail === "quote_expired") void fetchQuote();
        }
      } catch {
        if (mounted.current) setError("Something went wrong. Try again.");
      } finally {
        if (mounted.current) setPaying(false);
      }
    },
    // `api` is recreated each render (createApiClient) — intentionally omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [invoiceId, paying, isSettlement, quote, fetchQuote, billing],
  );

  const pay = useCallback(async () => {
    const hosted = hostedRef.current;
    if (!hosted || paying) return;
    let nonce: string;
    try {
      ({ nonce } = await hosted.tokenize());
    } catch {
      if (mounted.current) setError("Please complete the card details.");
      return;
    }
    await submitNonce(nonce);
  }, [paying, submitNonce]);

  // Demo/dev only: skip card entry, submit the Braintree sandbox nonce directly.
  const payWithTestCard = useCallback(
    () => submitNonce("fake-valid-nonce"),
    [submitNonce],
  );

  const setField = useCallback(
    (key: keyof Billing) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setBilling((b) => ({ ...b, [key]: e.target.value })),
    [],
  );

  if (!loaded) {
    return <p className="font-sans text-sm text-ink/50">Loading…</p>;
  }
  if (!invoice) {
    return (
      <p role="alert" className="font-sans text-sm" style={{ color: ATTENTION }}>
        {error ?? "This invoice could not be found."}
      </p>
    );
  }

  const succeeded = (invoice.payments ?? []).filter((p) => p.status === "succeeded");

  // For a settlement invoice the headline is the locked pay-currency figure; the
  // native subtotals sit beneath it. A native invoice shows its own currency.
  const settlementLabel =
    isSettlement && quote ? money(quote.settlementCurrency, quote.settlementAmount) : null;
  const nativeLabel = `${invoice.total} ${invoice.currency}`;
  const payAmount = isSettlement ? (settlementLabel ?? "…") : nativeLabel;
  const settlementReady = !isSettlement || Boolean(quote);
  const dueOn = fmtDate(invoice.due_at);
  const issuedOn = fmtDate(invoice.issued_at);
  const subtotalEntries = Object.entries(invoice.subtotals ?? {});

  return (
    <div
      data-testid="pay-invoice"
      className="mx-auto flex max-w-lg flex-col gap-6 px-4 py-8 text-ink"
    >
      <header className="flex flex-col gap-1">
        {payContext?.itinerary_title ? (
          <p
            data-testid="pay-trip"
            className="font-sans text-[11px] uppercase tracking-[0.2em] text-ink/45"
          >
            {payContext.itinerary_title}
          </p>
        ) : null}
        <h1 className="font-serif text-2xl tracking-tight">{invoice.label || "Invoice"}</h1>
        <p className="font-sans text-sm tabular-nums text-ink/70" data-testid="pay-amount">
          {payAmount}
          <span className="ml-2 text-[11px] uppercase tracking-[0.18em] text-ink/45">
            {invoice.status}
          </span>
          {invoice.number != null ? (
            <span className="ml-2 text-[11px] tabular-nums text-ink/40">
              INV-{String(invoice.number).padStart(6, "0")}
            </span>
          ) : null}
        </p>
        {isSettlement ? (
          <p className="font-sans text-[11px] text-ink/50" data-testid="pay-settlement-note">
            {nativeLabel}
            {invoice.status === "issued" && secondsLeft != null ? (
              <span className="ml-2 tabular-nums text-ink/45">
                · rate locked {fmtCountdown(secondsLeft)}
              </span>
            ) : null}
          </p>
        ) : null}
      </header>

      {/* Why you're paying: the line-item ledger + subtotals + dates. */}
      <section
        data-testid="pay-breakdown"
        className="flex flex-col gap-2 rounded-md border border-ink/10 p-4"
      >
        <h2 className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
          What this covers
        </h2>
        <ul className="flex flex-col gap-1.5">
          {(invoice.lines ?? []).map((line) => (
            <li
              key={line.id}
              data-testid="pay-line"
              className="flex items-baseline justify-between gap-4 font-sans text-sm"
            >
              <span className="text-ink/80">
                {line.description || line.kind}
                {line.kind !== "charge" ? (
                  <span className="ml-1.5 text-[10px] uppercase tracking-[0.14em] text-ink/40">
                    {line.kind}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0 tabular-nums text-ink/70">
                {money(line.currency, line.amount)}
              </span>
            </li>
          ))}
        </ul>
        <div className="mt-1 flex flex-col gap-0.5 border-t border-ink/10 pt-2">
          {subtotalEntries.map(([currency, amount]) => (
            <div
              key={currency}
              className="flex items-baseline justify-between font-sans text-sm font-medium"
            >
              <span className="text-ink/60">Total</span>
              <span className="tabular-nums" data-testid="pay-total">
                {money(currency, String(amount))}
              </span>
            </div>
          ))}
        </div>
        {issuedOn || dueOn ? (
          <p className="font-sans text-[11px] text-ink/45">
            {issuedOn ? `Issued ${issuedOn}` : null}
            {issuedOn && dueOn ? " · " : null}
            {dueOn ? `Due ${dueOn}` : null}
          </p>
        ) : null}
      </section>

      {invoice.status === "paid" ? (
        <section data-testid="pay-receipt" className="flex flex-col gap-2">
          <p className="font-sans text-sm" style={{ color: POSITIVE }}>
            This invoice is paid in full.
          </p>
          {succeeded.map((p) => (
            <p key={p.id} className="font-sans text-xs text-ink/60">
              {p.amount} {p.currency}
              {p.last_four ? ` · card ····${p.last_four}` : ""}
            </p>
          ))}
        </section>
      ) : invoice.status === "issued" ? (
        <section className="flex flex-col gap-5">
          {/* Billing identity — pre-filled from the client record, editable. */}
          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
              Billing details
            </legend>
            <label className="flex flex-col gap-1 font-sans text-xs text-ink/60">
              Name
              <input
                data-testid="billing-name"
                value={billing.name}
                onChange={setField("name")}
                autoComplete="name"
                className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 font-sans text-xs text-ink/60">
              Address
              <input
                data-testid="billing-address"
                value={billing.address}
                onChange={setField("address")}
                autoComplete="street-address"
                className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm text-ink"
              />
            </label>
            <div className="flex flex-wrap gap-3">
              <label className="flex flex-1 flex-col gap-1 font-sans text-xs text-ink/60">
                City
                <input
                  data-testid="billing-city"
                  value={billing.city}
                  onChange={setField("city")}
                  autoComplete="address-level2"
                  className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm text-ink"
                />
              </label>
              <label className="flex w-24 flex-col gap-1 font-sans text-xs text-ink/60">
                Region
                <input
                  data-testid="billing-region"
                  value={billing.region}
                  onChange={setField("region")}
                  autoComplete="address-level1"
                  className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm text-ink"
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-3">
              <label className="flex flex-1 flex-col gap-1 font-sans text-xs text-ink/60">
                Postal code
                <input
                  data-testid="billing-postal"
                  value={billing.postalCode}
                  onChange={setField("postalCode")}
                  autoComplete="postal-code"
                  className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm text-ink"
                />
              </label>
              <label className="flex w-24 flex-col gap-1 font-sans text-xs text-ink/60">
                Country
                <input
                  data-testid="billing-country"
                  value={billing.country}
                  onChange={setField("country")}
                  autoComplete="country"
                  maxLength={2}
                  placeholder="US"
                  className="rounded-md border border-ink/20 bg-paper px-3 py-2 text-sm uppercase text-ink"
                />
              </label>
            </div>
          </fieldset>

          {/* Card — Braintree Hosted Fields inject an iframe into each mount point. */}
          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/45">
              Card
            </legend>
            <label className="font-sans text-xs text-ink/60" htmlFor="cc-number">
              Card number
            </label>
            <div
              id="cc-number"
              data-testid="cc-number"
              className="h-11 rounded-md border border-ink/20 bg-paper px-3 py-2"
            />
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1">
                <label className="font-sans text-xs text-ink/60" htmlFor="cc-expiry">
                  Expiry
                </label>
                <div
                  id="cc-expiry"
                  data-testid="cc-expiry"
                  className="h-11 rounded-md border border-ink/20 bg-paper px-3 py-2"
                />
              </div>
              <div className="flex w-24 flex-col gap-1">
                <label className="font-sans text-xs text-ink/60" htmlFor="cc-cvv">
                  CVV
                </label>
                <div
                  id="cc-cvv"
                  data-testid="cc-cvv"
                  className="h-11 rounded-md border border-ink/20 bg-paper px-3 py-2"
                />
              </div>
            </div>
          </fieldset>

          <button
            type="button"
            onClick={() => void pay()}
            disabled={paying || !settlementReady || !cardReady}
            data-testid="pay-submit"
            className="rounded-md border border-ink/20 bg-ink px-4 py-2 font-sans text-sm uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {paying
              ? "Processing…"
              : !settlementReady
                ? "Fetching rate…"
                : !cardReady
                  ? "Loading card form…"
                  : `Pay ${payAmount}`}
          </button>
          {demoTestCard ? (
            <button
              type="button"
              onClick={() => void payWithTestCard()}
              disabled={paying}
              data-testid="pay-test-card"
              className="self-start rounded-md border border-dashed border-ink/25 px-3 py-1.5 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/60 transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              {paying ? "Processing…" : testCardLabel(demoTestCard)}
            </button>
          ) : null}
        </section>
      ) : (
        <p className="font-sans text-sm italic text-ink/50">
          This invoice is not ready for payment yet.
        </p>
      )}

      {error ? (
        <p role="alert" className="font-sans text-xs font-medium" style={{ color: ATTENTION }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
