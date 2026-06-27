// M004/G3 — advisor Diff + reconcile panel (itinerary-aside Diff tab).
//
// The fork wrappers are mocked so we assert the panel's own wiring:
//   - on mount it renders the four buckets (added/removed/changed/moved),
//   - toggling Accept off for a change flips its decision in the reconcile body,
//   - Reconcile calls reconcileFork and renders the per-change outcomes honestly
//     (a booked refusal reads "kept", not an error),
//   - the Reconcile button is disabled (with a notice) when the lock isn't held.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getForkDiff: vi.fn(),
  reconcileFork: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysis: vi.fn(),
}));

import {
  getForkDiff,
  reconcileFork,
  type ForkDiffResponse,
  type NodeChangeResponse,
} from "@ov-black/api-client";

import { DiffPanel } from "@/app/_components/itinerary-graph/views/horizontal/DiffPanel";

function change(over: Partial<NodeChangeResponse>): NodeChangeResponse {
  return {
    change_id: "x",
    kind: "changed",
    fork_node_id: null,
    baseline_node_id: null,
    fields: [],
    before: null,
    after: null,
    ...over,
  } as NodeChangeResponse;
}

const DIFF: ForkDiffResponse = {
  fork_id: "fork-1",
  baseline_id: "base-1",
  added: [
    change({
      change_id: "a1",
      kind: "added",
      fork_node_id: "n-a1",
      after: { title: "Tea ceremony" },
    }),
  ],
  removed: [
    change({
      change_id: "r1",
      kind: "removed",
      baseline_node_id: "n-r1",
      before: { title: "Bullet train" },
    }),
  ],
  changed: [
    change({
      change_id: "c1",
      kind: "changed",
      fork_node_id: "n-c1",
      baseline_node_id: "n-c1b",
      fields: ["title"],
      before: { title: "Osaka day" },
      after: { title: "Kyoto day" },
    }),
  ],
  moved: [
    change({
      change_id: "m1",
      kind: "moved",
      fork_node_id: "n-m1",
      baseline_node_id: "n-m1b",
      fields: ["position"],
      after: { title: "Dinner" },
    }),
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getForkDiff).mockResolvedValue({ ok: true, diff: DIFF });
});

function renderPanel(editable = true) {
  return render(
    <DiffPanel
      apiBaseUrl="http://api.test"
      accessToken="tok"
      forkItineraryId="fork-1"
      baselineItineraryId="base-1"
      editable={editable}
    />,
  );
}

test("renders the four diff buckets from getForkDiff", async () => {
  renderPanel();
  await waitFor(() => expect(getForkDiff).toHaveBeenCalledWith({}, "fork-1"));
  await screen.findByText(/Added · 1/);
  expect(screen.getByText(/Removed · 1/)).toBeTruthy();
  expect(screen.getByText(/Changed · 1/)).toBeTruthy();
  expect(screen.getByText(/Moved · 1/)).toBeTruthy();
  expect(screen.getByText("Tea ceremony")).toBeTruthy();
  expect(screen.getByText("Kyoto day")).toBeTruthy();
});

test("toggling Accept off flips the decision sent to reconcileFork", async () => {
  vi.mocked(reconcileFork).mockResolvedValue({
    ok: true,
    result: { baseline: {} as never, fork: {} as never, outcomes: [] },
  });
  renderPanel();

  await screen.findByText(/Added · 1/);
  // Uncheck the "added" change (its row's Accept checkbox).
  const addedRow = screen.getByTestId("diff-change-a1");
  const checkbox = addedRow.querySelector(
    "input[type=checkbox]",
  ) as HTMLInputElement;
  fireEvent.click(checkbox);

  fireEvent.click(screen.getByTestId("diff-reconcile"));
  await waitFor(() => expect(reconcileFork).toHaveBeenCalled());
  const [, forkId, body] = vi.mocked(reconcileFork).mock.calls[0]!;
  expect(forkId).toBe("fork-1");
  const byId = Object.fromEntries(
    (body.decisions ?? []).map((d) => [d.change_id, d.accept]),
  );
  expect(byId["a1"]).toBe(false); // toggled off
  expect(byId["c1"]).toBe(true); // still accepted
});

test("renders per-change outcomes incl. a booked 'kept' row", async () => {
  vi.mocked(reconcileFork).mockResolvedValue({
    ok: true,
    result: {
      baseline: {} as never,
      fork: {} as never,
      outcomes: [
        { change_id: "c1", kind: "changed", result: "applied", detail: null },
        {
          change_id: "r1",
          kind: "removed",
          result: "refused_booked",
          detail: "status_locked",
        },
      ],
    },
  });
  renderPanel();

  await screen.findByTestId("diff-reconcile");
  fireEvent.click(screen.getByTestId("diff-reconcile"));

  const outcomes = await screen.findByTestId("diff-outcomes");
  expect(outcomes.textContent).toMatch(/merged into the agreed plan/);
  expect(outcomes.textContent).toMatch(/kept \(booked/);
});

test("reconcile is disabled with a notice when the lock isn't held", async () => {
  renderPanel(false);
  await screen.findByText(/Added · 1/);
  expect(
    (screen.getByTestId("diff-reconcile") as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(screen.getByText(/Hold the edit lock to reconcile/)).toBeTruthy();
});

test("shows the matched-baseline empty state when there are no changes", async () => {
  vi.mocked(getForkDiff).mockResolvedValue({
    ok: true,
    diff: { ...DIFF, added: [], removed: [], changed: [], moved: [] },
  });
  renderPanel();
  await screen.findByText(/nothing to reconcile/i);
});
