// Reading-list removal: the quiet per-tile soft-delete.
//
// Covers the two pieces this feature added: (1) dedupe now merges every
// duplicate's node refs into the kept tile, so a cross-trip remove can discard
// all copies; (2) the rack's tiles grow a remove button only when a handler is
// supplied, and clicking it hands back the item (link navigation untouched).

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { ReadingList } from "@/app/_components/reading/ReadingList";
import {
  dedupeReadingItems,
  type ReadingItem,
} from "@/app/_components/reading/readingItem";

function item(overrides: Partial<ReadingItem> & { id: string }): ReadingItem {
  return {
    title: `Article ${overrides.id}`,
    publication: null,
    url: `https://example.com/${overrides.id}`,
    coverImage: null,
    refs: [{ itineraryId: `trip-${overrides.id}`, nodeId: overrides.id }],
    ...overrides,
  };
}

describe("dedupeReadingItems", () => {
  test("merges duplicate saves' refs into the kept tile", () => {
    const url = "https://example.com/shared";
    const first = item({ id: "n1", url });
    const second = item({ id: "n2", url });
    const other = item({ id: "n3" });

    const out = dedupeReadingItems([first, second, other]);

    expect(out.map((i) => i.id)).toEqual(["n1", "n3"]);
    expect(out[0]!.refs).toEqual([
      { itineraryId: "trip-n1", nodeId: "n1" },
      { itineraryId: "trip-n2", nodeId: "n2" },
    ]);
    // The input item is left untouched — merging happens on a copy.
    expect(first.refs).toHaveLength(1);
  });
});

describe("ReadingList remove affordance", () => {
  test("no onRemove → no remove buttons", () => {
    render(<ReadingList items={[item({ id: "n1" })]} />);
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
  });

  test("clicking the × hands the item back without navigating", () => {
    const onRemove = vi.fn();
    const target = item({ id: "n1" });
    render(<ReadingList items={[target]} onRemove={onRemove} />);

    fireEvent.click(screen.getByRole("button", { name: /remove/i }));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(target);
  });
});
