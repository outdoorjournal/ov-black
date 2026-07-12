// The Journal's margin channel (traveler-journal design, phase 2). Notes are
// the one write that works everywhere — INCLUDING the official trunk (these
// fixtures are a trunk: no forked_from_id) — because they gate on
// `selectCanLeaveNote` (credentials), never on role/fork/approve. Pins down:
// attached notes render in the MARGIN (never as spine cards), free-standing
// day notes ARE spine cards (the small note card), the ✎/`+`/rail affordances
// create notes, own notes edit in place (tap → textarea, save on blur), delete
// is always available, and everything disappears without credentials.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

const createNodeMock = vi.fn();
const updateNodeMock = vi.fn();
const deleteNodeMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    createNode: (...args: unknown[]) => createNodeMock(...args),
    updateNode: (...args: unknown[]) => updateNodeMock(...args),
    deleteNode: (...args: unknown[]) => deleteNodeMock(...args),
  };
});

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";

// ── Fixtures: an official trunk (no forked_from_id) ──────────────────────────
const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Kyoto in June",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "with_traveler",
};

const HOST: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "pending",
  title: "Tea ceremony",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
};

const ATTACHED_NOTE: NodeResponse = {
  id: "note-1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "note",
  status: "pending",
  title: "why are we doing this at 9am?",
  source: null,
  source_id: null,
  metadata: {},
  attached_to_node_id: "n1",
};

const DAY_NOTE: NodeResponse = {
  id: "note-2",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "note",
  status: "pending",
  title: "a dinner somewhere quiet?",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T19:00:00+09:00" },
};

const FIXTURES = new Map<string, NodeResponse>([
  [HOST.id, HOST],
  [ATTACHED_NOTE.id, ATTACHED_NOTE],
  [DAY_NOTE.id, DAY_NOTE],
]);

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Kyoto in June",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

function renderJournal(partial: Partial<ItineraryGraphInit> = {}) {
  const nodes = [HOST, ATTACHED_NOTE, DAY_NOTE];
  const init: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "with_traveler",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  return render(
    <itineraryGraphStore.Provider initial={init}>
      <TimelineDataProvider
        value={{ timeline: timeline(nodes), baselineTitle: null }}
      >
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

let serverSeq = 0;

beforeEach(() => {
  vi.clearAllMocks();
  // Echo mocks: the server adopts whatever the optimistic write proposed, so
  // the store's tmp-node swap keeps the visible text stable.
  createNodeMock.mockImplementation(
    (_c: unknown, { itineraryId, body }: { itineraryId: string; body: Record<string, unknown> }) =>
      Promise.resolve({
        ok: true,
        node: {
          id: `srv-${++serverSeq}`,
          itinerary_id: itineraryId,
          parent_subgraph_id: null,
          type: body["type"],
          status: body["status"],
          title: body["title"],
          source: null,
          source_id: null,
          metadata:
            typeof body["starts_at"] === "string"
              ? { start_time: body["starts_at"] }
              : {},
          ...(typeof body["attached_to_node_id"] === "string"
            ? { attached_to_node_id: body["attached_to_node_id"] }
            : {}),
        },
      }),
  );
  updateNodeMock.mockImplementation(
    (_c: unknown, { nodeId, patch }: { nodeId: string; patch: { title?: string } }) => {
      const base = FIXTURES.get(nodeId) ?? ATTACHED_NOTE;
      return Promise.resolve({
        ok: true,
        node: { ...base, id: nodeId, title: patch.title ?? base.title },
      });
    },
  );
  deleteNodeMock.mockResolvedValue({ ok: true });
});

describe("margin channel · placement", () => {
  test("attached notes annotate the host's margin, never the spine; day notes ARE spine note cards", () => {
    renderJournal();

    // The attached note is not a spine entry…
    const spineIds = screen
      .getAllByTestId("journal-node")
      .map((el) => el.getAttribute("data-node-id"));
    expect(spineIds).not.toContain("note-1");
    // …it hangs in the host card's margin.
    const margin = screen.getByTestId("journal-margin");
    expect(margin).toHaveAttribute("data-host-id", "n1");
    expect(within(margin).getByTestId("journal-margin-note")).toHaveTextContent(
      "why are we doing this at 9am?",
    );

    // The free-standing day note is a node on the spine, rendered as the
    // small note card (not a full glance card).
    expect(spineIds).toContain("note-2");
    expect(screen.getByTestId("journal-note-card")).toHaveTextContent(
      "a dinner somewhere quiet?",
    );
  });
});

describe("margin channel · leaving a note on a card (trunk-safe)", () => {
  test("the quiet ✎ opens a composer; submit persists an attached note", async () => {
    renderJournal();
    fireEvent.click(screen.getByTestId("journal-margin-add"));
    const input = screen.getByTestId("journal-margin-composer-input");
    fireEvent.change(input, { target: { value: "can we do this later?" } });
    fireEvent.click(screen.getByTestId("journal-margin-composer-submit"));

    // Optimistic: the annotation appears immediately.
    expect(
      screen.getAllByTestId("journal-margin-note").map((el) => el.textContent),
    ).toEqual(expect.arrayContaining([expect.stringContaining("can we do this later?")]));

    await waitFor(() =>
      expect(createNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        body: {
          type: "note",
          title: "can we do this later?",
          status: "pending",
          attached_to_node_id: "n1",
        },
      }),
    );
  });

  test("the rail renders the notes thread + composer for the active node", async () => {
    renderJournal();
    // Activate the host card (a click pin — also what flips the rail).
    fireEvent.click(screen.getByText("Tea ceremony"));

    // The rail's notes thread hosts the NotesPanel composer (always visible —
    // no "leave a note" toggle anymore).
    const railNotes = screen.getByTestId("journal-rail-notes");
    fireEvent.change(within(railNotes).getByTestId("note-composer-input"), {
      target: { value: "note from the rail" },
    });
    fireEvent.click(within(railNotes).getByTestId("note-composer-submit"));

    await waitFor(() =>
      expect(createNodeMock).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          body: expect.objectContaining({
            type: "note",
            title: "note from the rail",
            attached_to_node_id: "n1",
          }),
        }),
      ),
    );
  });
});

describe("margin channel · edit in place + delete", () => {
  test("tap → textarea; save on blur rewrites the note text", async () => {
    renderJournal();
    const note = screen.getByTestId("journal-margin-note");
    fireEvent.click(within(note).getByTestId("journal-note-text"));
    const editor = within(note).getByTestId("journal-note-editor");
    expect(editor).toHaveValue("why are we doing this at 9am?");

    fireEvent.change(editor, { target: { value: "could this be 11am?" } });
    fireEvent.blur(editor);

    // Optimistic rewrite…
    expect(screen.getByTestId("journal-margin-note")).toHaveTextContent(
      "could this be 11am?",
    );
    // …persisted as a title patch on the note node.
    await waitFor(() =>
      expect(updateNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        nodeId: "note-1",
        patch: { title: "could this be 11am?" },
      }),
    );
  });

  test("Escape abandons the edit without a network call", () => {
    renderJournal();
    const note = screen.getByTestId("journal-margin-note");
    fireEvent.click(within(note).getByTestId("journal-note-text"));
    const editor = within(note).getByTestId("journal-note-editor");
    fireEvent.change(editor, { target: { value: "never mind" } });
    fireEvent.keyDown(editor, { key: "Escape" });
    expect(updateNodeMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("journal-margin-note")).toHaveTextContent(
      "why are we doing this at 9am?",
    );
  });

  test("delete is always available on a note (spine note card too)", async () => {
    renderJournal();
    const card = screen.getByTestId("journal-note-card");
    fireEvent.click(within(card).getByTestId("journal-note-delete"));
    // Optimistic removal from the spine.
    expect(screen.queryByTestId("journal-note-card")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(deleteNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        nodeId: "note-2",
      }),
    );
  });
});

describe("the `+`-on-the-line", () => {
  test("offers Note (the trunk's only offer) and drops the note on that day at noon", async () => {
    renderJournal();
    fireEvent.click(screen.getByTestId("journal-add-plus"));
    fireEvent.click(screen.getByTestId("journal-add-note-option"));
    fireEvent.change(screen.getByTestId("journal-day-note-composer-input"), {
      target: { value: "a market morning here?" },
    });
    fireEvent.click(screen.getByTestId("journal-day-note-composer-submit"));

    // Optimistic: the new day note lands on the spine.
    expect(
      screen.getAllByTestId("journal-note-card").map((el) => el.textContent),
    ).toEqual(expect.arrayContaining([expect.stringContaining("a market morning here?")]));

    await waitFor(() =>
      expect(createNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        body: {
          type: "note",
          title: "a market morning here?",
          status: "pending",
          starts_at: expect.stringContaining("2024-06-20T12:00:00"),
        },
      }),
    );
  });
});

describe("gating — selectCanLeaveNote (credentials), not role", () => {
  test("without credentials every note affordance disappears; notes still read", () => {
    renderJournal({ apiBaseUrl: null, accessToken: null });
    // Reading stays.
    expect(screen.getByTestId("journal-margin-note")).toHaveTextContent(
      "why are we doing this at 9am?",
    );
    expect(screen.getByTestId("journal-note-card")).toBeInTheDocument();
    // Writing affordances are gone.
    expect(screen.queryByTestId("journal-add-on-line")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-margin-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-note-delete")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-note-text")).not.toBeInTheDocument();
  });
});
