// G1 (D1) — the per-node lock badge. A booked/confirmed card surfaces the
// server-computed lock_reason as crafted refusal copy (tooltip + accessible
// label) so a reader understands why an edit would be refused.

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { CardShell } from "@/app/_components/itinerary-graph/shared/cards/CardShell";

test("a booked node renders the lock badge with crafted refusal copy", () => {
  render(
    <CardShell kind="hotel" status="booked" lockReason="status_locked" lockLabel="hotel">
      <span>Aman</span>
    </CardShell>,
  );
  const badge = screen.getByLabelText(
    "This hotel is booked — an advisor would need to move it.",
  );
  expect(badge).toBeTruthy();
  expect(badge.getAttribute("title")).toContain("an advisor would need to move it");
});

test("a confirmed node surfaces the lock copy too", () => {
  render(
    <CardShell kind="flight" status="confirmed" lockReason="status_locked" lockLabel="flight">
      <span>DL275</span>
    </CardShell>,
  );
  expect(
    screen.getByLabelText("This flight is confirmed — an advisor would need to move it."),
  ).toBeTruthy();
});

test("an unlocked (approved) node shows no lock copy", () => {
  render(
    <CardShell kind="hotel" status="approved" lockReason={null} lockLabel="hotel">
      <span>Park Hyatt</span>
    </CardShell>,
  );
  expect(screen.queryByLabelText(/an advisor would need to move it/)).toBeNull();
  expect(screen.getByLabelText("Status: approved")).toBeTruthy();
});
