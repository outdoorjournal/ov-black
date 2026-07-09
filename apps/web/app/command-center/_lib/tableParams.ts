// URL-state table params (Wave F). The Command Center rosters keep their
// search / filter / sort / cursor state in the query string — back button,
// refresh, sharing, and revalidatePath all keep working, and there is no
// client cache to invalidate. This module is the single place that touches
// searchParams' awkward shape (`string | string[] | undefined`, bracket
// access only under noPropertyAccessFromIndexSignature) and the
// cursor-reset rule; everything else works with the typed TableParams.

export type SearchParamsShape = Record<string, string | string[] | undefined>;

export type TableParams = {
  q: string;
  status: string | null;
  sort: string | null;
  order: "asc" | "desc" | null;
  cursor: string | null;
};

export type TableParamsConfig = {
  /** Allowed status filter values; anything else is dropped. */
  statuses?: readonly string[];
  /** Allowed sort keys; anything else is dropped. */
  sorts?: readonly string[];
};

function first(value: string | string[] | undefined): string | null {
  if (value === undefined) return null;
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === undefined) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/** Parse a page's awaited `searchParams` into typed, validated table state. */
export function parseTableParams(
  sp: SearchParamsShape,
  config: TableParamsConfig = {},
): TableParams {
  const status = first(sp["status"]);
  const sort = first(sp["sort"]);
  const orderRaw = first(sp["order"]);
  return {
    q: first(sp["q"]) ?? "",
    status:
      status !== null && (config.statuses?.includes(status) ?? false) ? status : null,
    sort: sort !== null && (config.sorts?.includes(sort) ?? false) ? sort : null,
    order: orderRaw === "asc" || orderRaw === "desc" ? orderRaw : null,
    cursor: first(sp["cursor"]),
  };
}

/**
 * Build the query string for a state transition. Changing q / status / sort /
 * order RESETS the cursor (a filter change invalidates the page position);
 * pass `cursor` explicitly to page within the current filters. Returns "" or
 * "?...", ready to append to the route literal.
 */
export function tableQuery(
  current: TableParams,
  next: Partial<TableParams>,
): string {
  const filterChanged =
    (next.q !== undefined && next.q !== current.q) ||
    (next.status !== undefined && next.status !== current.status) ||
    (next.sort !== undefined && next.sort !== current.sort) ||
    (next.order !== undefined && next.order !== current.order);

  const merged: TableParams = {
    q: next.q ?? current.q,
    status: next.status !== undefined ? next.status : current.status,
    sort: next.sort !== undefined ? next.sort : current.sort,
    order: next.order !== undefined ? next.order : current.order,
    cursor: filterChanged ? null : (next.cursor !== undefined ? next.cursor : current.cursor),
  };

  const parts = new URLSearchParams();
  if (merged.q) parts.set("q", merged.q);
  if (merged.status) parts.set("status", merged.status);
  if (merged.sort) parts.set("sort", merged.sort);
  if (merged.order) parts.set("order", merged.order);
  if (merged.cursor) parts.set("cursor", merged.cursor);
  const qs = parts.toString();
  return qs ? `?${qs}` : "";
}

/** The next sort transition for a header click: asc → desc → asc… */
export function toggleSort(
  current: TableParams,
  sortKey: string,
  defaultOrder: "asc" | "desc" = "asc",
): Partial<TableParams> {
  if (current.sort !== sortKey) return { sort: sortKey, order: defaultOrder };
  return {
    sort: sortKey,
    order: (current.order ?? defaultOrder) === "asc" ? "desc" : "asc",
  };
}
