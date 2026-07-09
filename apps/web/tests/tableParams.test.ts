import { expect, test } from "vitest";

import {
  parseTableParams,
  tableQuery,
  toggleSort,
} from "@/app/command-center/_lib/tableParams";

const CONFIG = {
  statuses: ["draft", "proposed", "approved"],
  sorts: ["updated_at", "title"],
} as const;

test("parse handles missing, array, and blank values", () => {
  const parsed = parseTableParams(
    { q: ["kyoto", "ignored"], status: "draft", sort: "  ", cursor: undefined },
    CONFIG,
  );
  expect(parsed).toEqual({
    q: "kyoto",
    status: "draft",
    sort: null,
    order: null,
    cursor: null,
  });
});

test("parse drops unknown status/sort/order values", () => {
  const parsed = parseTableParams(
    { status: "exploded", sort: "DROP TABLE", order: "sideways" },
    CONFIG,
  );
  expect(parsed.status).toBeNull();
  expect(parsed.sort).toBeNull();
  expect(parsed.order).toBeNull();
});

test("tableQuery resets the cursor when a filter changes", () => {
  const current = parseTableParams(
    { q: "old", cursor: "abc", status: "draft" },
    CONFIG,
  );
  expect(tableQuery(current, { q: "new" })).toBe("?q=new&status=draft");
});

test("tableQuery keeps the cursor when only paging", () => {
  const current = parseTableParams({ q: "kyoto" }, CONFIG);
  expect(tableQuery(current, { cursor: "page2" })).toBe("?q=kyoto&cursor=page2");
});

test("tableQuery clears removed filters and renders empty state as bare path", () => {
  const current = parseTableParams({ status: "draft" }, CONFIG);
  expect(tableQuery(current, { status: null })).toBe("");
});

test("toggleSort cycles asc/desc and adopts new columns at their default", () => {
  const none = parseTableParams({}, CONFIG);
  expect(toggleSort(none, "title")).toEqual({ sort: "title", order: "asc" });
  const titleAsc = parseTableParams({ sort: "title", order: "asc" }, CONFIG);
  expect(toggleSort(titleAsc, "title")).toEqual({ sort: "title", order: "desc" });
  expect(toggleSort(titleAsc, "updated_at", "desc")).toEqual({
    sort: "updated_at",
    order: "desc",
  });
});
