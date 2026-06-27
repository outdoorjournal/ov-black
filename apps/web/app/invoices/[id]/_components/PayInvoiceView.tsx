"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import dropin, { type Dropin } from "braintree-web-drop-in";

import {
  type InvoiceResponse,
  createApiClient,
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
  network_error: "Could not reach the server. Try again in a moment.",
};

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

export function PayInvoiceView({
  apiBaseUrl,
  accessToken,
  invoiceId,
}: {
  apiBaseUrl: string;
  accessToken: string;
  invoiceId: string;
}) {
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
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

  const pay = useCallback(async () => {
    const instance = instanceRef.current;
    if (!instance || paying) return;
    setPaying(true);
    setError(null);
    try {
      const { nonce } = await instance.requestPaymentMethod();
      const result = await payInvoice(api, invoiceId, {
        payment_method_nonce: nonce,
      });
      if (!mounted.current) return;
      if (result.ok) {
        await instance.teardown().catch(() => undefined);
        instanceRef.current = null;
        setInvoice(result.invoice);
      } else {
        setError(copy(result.detail));
      }
    } catch {
      if (mounted.current) setError("Please complete the card details.");
    } finally {
      if (mounted.current) setPaying(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, paying]);

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

  return (
    <div
      data-testid="pay-invoice"
      className="mx-auto flex max-w-lg flex-col gap-5 px-4 py-8 text-ink"
    >
      <header className="flex flex-col gap-1">
        <h1 className="font-serif text-2xl tracking-tight">{invoice.label || "Invoice"}</h1>
        <p className="font-sans text-sm tabular-nums text-ink/70">
          {invoice.total} {invoice.currency}
          <span className="ml-2 text-[11px] uppercase tracking-[0.18em] text-ink/45">
            {invoice.status}
          </span>
        </p>
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
            disabled={paying}
            data-testid="pay-submit"
            className="rounded-md border border-ink/20 bg-ink px-4 py-2 font-sans text-sm uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {paying ? "Processing…" : `Pay ${invoice.total} ${invoice.currency}`}
          </button>
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
