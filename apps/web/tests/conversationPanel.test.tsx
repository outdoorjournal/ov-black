// The concierge conversation surface's proposal rendering. A proposal renders as
// the SAME card the timeline / Collection show — the shared CardShell substrate +
// type-specific CardBody (M006 harmonization) — not a bespoke stub. A flight
// reads like a boarding pass: title + route + airport-local wall clock + cabin.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import {
  ConversationPanel,
  type ConversationProposal,
} from "@/app/_components/concierge/ConversationPanel";

const FLIGHT: ConversationProposal = {
  id: "n1",
  type: "flight",
  title: "DTW → SCL · LATAM Airlines",
  metadata: {
    kind: "flight",
    iata_from: "DTW",
    iata_to: "SCL",
    cabin: "economy",
    depart_at: "2026-11-10T16:10:00-05:00",
    arrive_at: "2026-11-11T07:50:00-03:00",
    from_location: { label: "Detroit (DTW)" },
    to_location: { label: "Santiago (SCL)" },
  },
};

test("a flight proposal renders as the shared boarding-pass card", () => {
  render(
    <ConversationPanel messages={[]} onSubmit={() => {}} proposals={[FLIGHT]} />,
  );

  // The card carries its title (the real CardBody shows it — unlike the old
  // stub, which suppressed it for typed flights).
  expect(screen.getByText("DTW → SCL · LATAM Airlines")).toBeTruthy();

  // Route codes + cities read like a boarding pass.
  expect(screen.getByText("DTW")).toBeTruthy();
  expect(screen.getByText("SCL")).toBeTruthy();
  expect(screen.getByText("Detroit")).toBeTruthy();
  expect(screen.getByText("Santiago")).toBeTruthy();

  // Each end shows its OWN airport-local wall clock (embedded offset, no
  // viewer-tz conversion): depart 16:10, arrive 07:50.
  expect(screen.getByText("16:10")).toBeTruthy();
  expect(screen.getByText("07:50")).toBeTruthy();

  // Cabin chip humanized.
  expect(screen.getByText("Economy")).toBeTruthy();

  // Accept / Dismiss ride in the shell's actions slot.
  expect(screen.getByText("Accept")).toBeTruthy();
  expect(screen.getByText("Dismiss")).toBeTruthy();
});

test("a non-typed proposal falls back to the bare title", () => {
  const generic: ConversationProposal = {
    id: "n2",
    type: "experience",
    title: "Sunrise at Torres del Paine",
  };
  render(
    <ConversationPanel messages={[]} onSubmit={() => {}} proposals={[generic]} />,
  );
  expect(screen.getByText("Sunrise at Torres del Paine")).toBeTruthy();
});

test("Up/Down recall previously sent messages, then restore the draft", () => {
  const onSubmit = vi.fn();
  render(<ConversationPanel messages={[]} onSubmit={onSubmit} />);
  const box = screen.getByRole("textbox") as HTMLTextAreaElement;

  // Send two messages; the composer clears after each.
  fireEvent.change(box, { target: { value: "first message" } });
  fireEvent.keyDown(box, { key: "Enter" });
  fireEvent.change(box, { target: { value: "second message" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onSubmit).toHaveBeenCalledTimes(2);
  expect(box.value).toBe("");

  // Start a fresh draft, then walk back through history with Up.
  fireEvent.change(box, { target: { value: "half-typed" } });
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box.value).toBe("second message");
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box.value).toBe("first message");
  // Oldest entry holds — no wrap.
  fireEvent.keyDown(box, { key: "ArrowUp" });
  expect(box.value).toBe("first message");

  // Down walks forward, then restores the in-progress draft.
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(box.value).toBe("second message");
  fireEvent.keyDown(box, { key: "ArrowDown" });
  expect(box.value).toBe("half-typed");
});
