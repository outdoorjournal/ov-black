// D5 — traveler cross-trip invoice listing (/basecamp/invoices).
//
// Presentational component: assert rows render label + trip title + total, the
// status badge copy per status, each row links to /invoices/{id}, and the empty
// state renders.

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import type { MyInvoiceSummary } from "@ov-black/api-client";

import { InvoiceList } from "@/app/basecamp/invoices/_components/InvoiceList";

function invoice(over: Partial<MyInvoiceSummary> & { id: string }): MyInvoiceSummary {
  return {
    label: "Deposit",
    status: "issued",
    currency: "USD",
    total: "1000.00",
    due_at: null,
    itinerary_id: "itin-1",
    itinerary_title: "Kyoto in Spring",
    ...over,
  } as MyInvoiceSummary;
}

test("renders a row per invoice with label, trip title, and total", () => {
  render(
    <InvoiceList
      invoices={[
        invoice({ id: "inv-1", label: "Deposit", total: "1000.00" }),
        invoice({ id: "inv-2", label: "Balance", total: "2500.00", itinerary_title: "Patagonia" }),
      ]}
    />,
  );
  expect(screen.getByText("Deposit")).toBeTruthy();
  expect(screen.getByText("Kyoto in Spring")).toBeTruthy();
  expect(screen.getByText("Balance")).toBeTruthy();
  expect(screen.getByText("Patagonia")).toBeTruthy();
  expect(screen.getByText("1000.00 USD")).toBeTruthy();
  expect(screen.getByText("2500.00 USD")).toBeTruthy();
});

test("each row links to the /invoices/{id} pay page", () => {
  render(<InvoiceList invoices={[invoice({ id: "inv-1" })]} />);
  const link = screen.getByTestId("invoice-row-inv-1");
  expect(link.getAttribute("href")).toBe("/invoices/inv-1");
});

test("the status badge reflects the invoice status", () => {
  render(
    <InvoiceList
      invoices={[
        invoice({ id: "a", status: "paid" }),
        invoice({ id: "b", status: "draft" }),
        invoice({ id: "c", status: "void" }),
      ]}
    />,
  );
  expect(screen.getByTestId("invoice-status-paid").textContent).toContain("paid");
  expect(screen.getByTestId("invoice-status-draft").textContent).toContain("draft");
  expect(screen.getByTestId("invoice-status-void").textContent).toContain("void");
});

test("empty state renders when there are no invoices", () => {
  render(<InvoiceList invoices={[]} />);
  expect(screen.getByText("No invoices yet.")).toBeTruthy();
});
