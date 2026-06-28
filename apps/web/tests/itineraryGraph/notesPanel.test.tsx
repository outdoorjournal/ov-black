// NotesPanel — the attached-notes list + inline composer shown in a host card's
// expanded detail sheet.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { NotesPanel } from "@/app/_components/itinerary-graph/shared/NotesPanel";

function note(id: string, title: string): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "note",
    status: "proposed",
    title,
    source: null,
    source_id: null,
    metadata: {},
    attached_to_node_id: "host",
  };
}

describe("NotesPanel", () => {
  test("renders nothing when there are no notes and no composer", () => {
    const { container } = render(<NotesPanel notes={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  test("lists existing notes", () => {
    render(<NotesPanel notes={[note("n1", "why are we doing this at 1:30?")]} />);
    expect(screen.getByText("why are we doing this at 1:30?")).toBeInTheDocument();
  });

  test("composer submits trimmed text and clears", () => {
    const onAddNote = vi.fn();
    render(<NotesPanel notes={[]} canAdd onAddNote={onAddNote} />);
    const input = screen.getByTestId("note-composer-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "  move dinner later  " } });
    fireEvent.click(screen.getByTestId("note-composer-submit"));
    expect(onAddNote).toHaveBeenCalledWith("move dinner later");
    expect(input.value).toBe("");
  });

  test("composer does not appear without canAdd", () => {
    render(<NotesPanel notes={[note("n1", "x")]} onAddNote={vi.fn()} />);
    expect(screen.queryByTestId("note-composer-input")).toBeNull();
  });
});
