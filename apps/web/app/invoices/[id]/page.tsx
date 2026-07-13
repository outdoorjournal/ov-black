// Traveler-facing invoice payment route (M005/I2).
//
// Any authenticated viewer the API admits (the owning client or an advisor) may
// pay. Unlike the read-only itinerary view, the pay surface NEEDS credentials —
// the traveler tokenizes a card and posts the nonce — so we pass apiBaseUrl +
// accessToken to the client component. The API's owner/advisor access gate on
// GET/pay is the real authority; a non-entitled viewer collapses to notFound().

import { notFound, redirect } from "next/navigation";

import { createApiClient, getInvoice, getPayContext } from "@ov-black/api-client";

import { demoTestCard, publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

import { PayInvoiceView } from "./_components/PayInvoiceView";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function InvoicePage({ params }: PageProps) {
  const { id: invoiceId } = await params;

  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/");
  }
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    redirect("/");
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  // Existence + entitlement check on the server so a non-entitled viewer can't
  // tell a real invoice from a missing one.
  const result = await getInvoice(api, invoiceId);
  if (!result.ok) {
    notFound();
  }

  // Best-effort prefill/narration context — the invoice gate above is the real
  // authority, so a context miss just renders an empty billing form.
  const ctx = await getPayContext(api, invoiceId);

  return (
    <PayInvoiceView
      apiBaseUrl={apiBaseUrl}
      accessToken={accessToken}
      invoiceId={invoiceId}
      payContext={ctx.ok ? ctx.context : null}
      demoTestCard={demoTestCard()}
    />
  );
}
