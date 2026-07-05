"use client";

// Inventory search (B1–B3), extracted from the old AuthoringPanel so it can host
// inside the unified Add composer's "Find" mode, the prototype "Build" aside, and
// anywhere else. Reads only need `canEdit`; the Add write needs the lock, so its
// button gates on `editable` (selectEditable). Each result renders through the
// common Card model (`CardShell` + `CardBody`) — no bespoke card markup.

import { useState } from "react";

import { CardBody, inferCardKind } from "../../../shared/cards/CardBody";
import { CardShell } from "../../../shared/cards/CardShell";
import {
  itineraryGraphStore,
  selectEditable,
} from "../../../store/itineraryGraphStore";

import { KIND_CHIPS, btn, formatPrice, inventoryItemToNode, sectionTitle } from "./shared";

/** `heading` prints the section's own "Search inventory" label (the prototype
 *  aside); hosts that already title the surface (composer Find mode) pass false. */
export function SearchSection({ heading = true }: { heading?: boolean }) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  const storeApi = itineraryGraphStore.useStoreApi();

  const inventoryResults = itineraryGraphStore.useStore((s) => s.inventoryResults);
  const inventoryPending = itineraryGraphStore.useStore((s) => s.inventoryPending);
  const inventoryError = itineraryGraphStore.useStore((s) => s.inventoryError);
  const addingInventoryId = itineraryGraphStore.useStore((s) => s.addingInventoryId);

  const [keyword, setKeyword] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);

  const toggleKind = (value: string) =>
    setKinds((cur) =>
      cur.includes(value) ? cur.filter((k) => k !== value) : [...cur, value],
    );

  const onSearch = () => {
    storeApi.getState().runInventorySearch({
      ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
      ...(kinds.length > 0 ? { kinds } : {}),
      limit: 20,
    });
  };

  return (
    <section data-testid="itinerary-graph-search">
      {heading ? <div className={`${sectionTitle} mb-2`}>Search inventory</div> : null}
      <div className="flex gap-2">
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSearch();
          }}
          placeholder="ramen in Kyoto, a private guide…"
          data-testid="itinerary-graph-search-input"
          className="h-8 min-w-0 flex-1 rounded-md border border-ink/15 bg-paper px-3 font-sans text-sm text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden"
        />
        <button
          type="button"
          onClick={onSearch}
          disabled={inventoryPending}
          data-testid="itinerary-graph-search-run"
          className={btn}
        >
          {inventoryPending ? "Searching" : "Search"}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {KIND_CHIPS.map((chip) => {
          const on = kinds.includes(chip.value);
          return (
            <button
              key={chip.value}
              type="button"
              onClick={() => toggleKind(chip.value)}
              className={`rounded-full border px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.14em] transition-colors ${
                on
                  ? "border-ink/40 bg-ink/10 text-ink"
                  : "border-ink/15 text-ink/55 hover:bg-ink/5"
              }`}
            >
              {chip.label}
            </button>
          );
        })}
      </div>

      {inventoryError ? (
        <p className="mt-3 font-sans text-[11px] text-[#8b2a1d]">
          That search didn’t come back. Try again in a moment.
        </p>
      ) : null}

      <ul
        className="mt-3 flex flex-wrap gap-3"
        data-testid="itinerary-graph-search-results"
      >
        {inventoryResults.map((item) => {
          const node = inventoryItemToNode(item);
          const price = formatPrice(item.price);
          const adding = addingInventoryId === item.source_id;
          return (
            <li
              key={`${item.source}:${item.source_id}`}
              data-testid="itinerary-graph-search-result"
              className="flex w-[260px] flex-col gap-2"
            >
              <CardShell
                kind={inferCardKind(node)}
                status="proposed"
                width="glance"
                lockLabel={node.type}
              >
                <CardBody node={node} kind={inferCardKind(node)} tzOffsetHours={0} />
              </CardShell>
              <div className="flex items-center justify-between gap-2 px-0.5">
                <span className="min-w-0 truncate font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
                  {item.source}
                  {price ? <span className="text-ink/70"> · {price}</span> : null}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    storeApi
                      .getState()
                      .addNodeFromInventory(item.source, item.source_id)
                  }
                  disabled={!editable || adding}
                  data-testid="itinerary-graph-search-add"
                  className="h-7 shrink-0 rounded-md border border-ink/20 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40"
                >
                  {adding ? "Adding" : "Add"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
