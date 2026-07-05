// Traveler invoice listing (/basecamp/invoices).
//
// Self-scoped like the rest of basecamp — invoices come from /me/invoices,
// resolved from the Supabase JWT, spanning every trip. Each row links to the
// existing /invoices/{id} pay page (the single-invoice Braintree drop-in).

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  listMyInvoices,
  type MyInvoiceSummary,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { BasecampChrome } from "../_components/BasecampChrome";
import { InvoiceList } from "./_components/InvoiceList";

export const dynamic = "force-dynamic";

export default async function InvoicesPage() {
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

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    notFound();
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const result = await listMyInvoices(api);
  const invoices: MyInvoiceSummary[] = result.ok ? result.invoices : [];

  return (
    <BasecampChrome user={headerUserFromSupabase(user)}>
      <InvoiceList invoices={invoices} />
    </BasecampChrome>
  );
}
