"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import dropin, { type Dropin } from "braintree-web-drop-in";

import {
  type InvoiceResponse,
  type PaymentQuote,
  createApiClient,
  createPaymentQuote,
  getInvoice,
  getPaymentToken,
  payInvoice,
} from "@ov-black/api-client";

// Traveler-facing pay surface (M005/I2). Shows an issued invoice's total + a
// Braintree drop-in; on submit it tokenizes the card and pays. Once paid it
// shows the payment history. Self-contained — the page passes the viewer's
// credentials (the API's owner/advisor gate is the real authority).

const ATTENTION = "#8b2a1d";

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

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

/** "Pay with test card ····1111" — the configured sandbox card, masked to last-4. */
function testCardLabel(card: string): string {
  const last4 = card.replace(/\D/g, "").slice(-4);
  return last4 ? `Pay with test card ····${last4}` : "Pay with test card";
}

export function PayInvoiceView({
  apiBaseUrl,
  accessToken,
  invoiceId,
  demoTestCard = null,
}: {
  apiBaseUrl: string;
  accessToken: string;
  invoiceId: string;
  /** Demo/dev only (env-gated by the page) — the sandbox card number to offer as a
   *  one-click pay; null/undefined hides it. Display only; the charge uses the nonce. */
  demoTestCard?: string | null;
}) {
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  // Settlement (pay-currency) invoices lock a fresh FX rate at pay time (0050):
  // fetch a quote, show a countdown, re-quote on expiry, and charge the locked id.
  const [quote, setQuote] = useState<PaymentQuote | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<Dropin | null>(null);
  const mounted = useRef(true);

  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void instanceRef.current?.teardown().catch(() => undefined);
      instanceRef.current = null;
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

  // Mount the Braintree drop-in once the invoice is issued + container exists.
  useEffect(() => {
    if (!invoice || invoice.status !== "issued" || instanceRef.current) return;
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;
    void (async () => {
      const token = await getPaymentToken(api, invoiceId);
      if (cancelled || !mounted.current) return;
      if (!token.ok) {
        setError(copy(token.detail));
        return;
      }
      try {
        const instance = await dropin.create({
          authorization: token.clientToken,
          container,
        });
        if (cancelled || !mounted.current) {
          void instance.teardown().catch(() => undefined);
          return;
        }
        instanceRef.current = instance;
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
  const submitNonce = useCallback(async (nonce: string) => {
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
      });
      if (!mounted.current) return;
      if (result.ok) {
        await instanceRef.current?.teardown().catch(() => undefined);
        instanceRef.current = null;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, paying, isSettlement, quote, fetchQuote]);

  const pay = useCallback(async () => {
    const instance = instanceRef.current;
    if (!instance || paying) return;
    let nonce: string;
    try {
      ({ nonce } = await instance.requestPaymentMethod());
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

  const succeeded = (invoice.payments ?? []).filter(
    (p) => p.status === "succeeded",
  );

  // For a settlement invoice the headline is the locked pay-currency figure; the
  // native subtotals sit beneath it. A native invoice shows its own currency.
  const settlementLabel =
    isSettlement && quote ? money(quote.settlementCurrency, quote.settlementAmount) : null;
  const nativeLabel = `${invoice.total} ${invoice.currency}`;
  const payAmount = isSettlement ? (settlementLabel ?? "…") : nativeLabel;
  const settlementReady = !isSettlement || Boolean(quote);

  return (
    <div
      data-testid="pay-invoice"
      className="mx-auto flex max-w-lg flex-col gap-5 px-4 py-8 text-ink"
    >
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-2xl tracking-tight">{invoice.label || "Invoice"}</h1>
        <p className="font-sans text-sm tabular-nums text-ink/70" data-testid="pay-amount">
          {payAmount}
          <span className="ml-2 text-[11px] uppercase tracking-[0.18em] text-ink/45">
            {invoice.status}
          </span>
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

      {invoice.status === "paid" ? (
        <section data-testid="pay-receipt" className="flex flex-col gap-2">
          <p className="font-sans text-sm text-[#1d6b3a]">This invoice is paid in full.</p>
          {succeeded.map((p) => (
            <p key={p.id} className="font-sans text-xs text-ink/60">
              {p.amount} {p.currency}
              {p.last_four ? ` · card ····${p.last_four}` : ""}
            </p>
          ))}
        </section>
      ) : invoice.status === "issued" ? (
        <section className="flex flex-col gap-3">
          <div ref={containerRef} data-testid="dropin-container" />
          <button
            type="button"
            onClick={() => void pay()}
            disabled={paying || !settlementReady}
            data-testid="pay-submit"
            className="rounded-md border border-ink/20 bg-ink px-4 py-2 font-sans text-sm uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {paying ? "Processing…" : !settlementReady ? "Fetching rate…" : `Pay ${payAmount}`}
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
