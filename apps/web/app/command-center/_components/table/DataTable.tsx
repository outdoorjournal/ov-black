// Generic roster table (Wave F) — server-renderable, column-def driven.
// Rows are NOT whole-row links (a11y): the primary cell carries the Link and
// `focus-within` lights the row exactly like hover, so keyboard users get the
// same affordance. Trailing chrome (→) is aria-hidden.

import type { ReactNode } from "react";

export type ColumnDef<Row> = {
  key: string;
  header: ReactNode;
  /** Present when this column is sortable — pair with <SortHeader>. */
  headerCell?: ReactNode;
  className?: string;
  /** Hide below this breakpoint: "md" | "lg". */
  hideBelow?: "md" | "lg";
  align?: "right";
  cell: (row: Row) => ReactNode;
};

const HIDE = { md: "hidden md:table-cell", lg: "hidden lg:table-cell" } as const;

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  dense = false,
}: {
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  dense?: boolean;
}) {
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-7">
      <table className="w-full border-y border-paper/10 text-left font-sans text-sm">
        <thead>
          <tr className="border-b border-paper/10">
            {columns.map((col, i) => (
              <th
                key={col.key}
                scope="col"
                className={[
                  "py-2.5 pr-4 font-sans text-[10px] font-normal uppercase tracking-label text-paper/45",
                  i === 0 ? "pl-5 sm:pl-7" : "",
                  col.hideBelow ? HIDE[col.hideBelow] : "",
                  col.align === "right" ? "text-right" : "",
                  col.className ?? "",
                ].join(" ")}
              >
                {col.headerCell ?? col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-paper/8">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="group transition-colors focus-within:bg-paper/8 hover:bg-paper/8"
            >
              {columns.map((col, i) => (
                <td
                  key={col.key}
                  className={[
                    dense ? "py-2 pr-4" : "py-3 pr-4",
                    i === 0 ? "pl-5 sm:pl-7" : "",
                    col.hideBelow ? HIDE[col.hideBelow] : "",
                    col.align === "right" ? "text-right" : "",
                    col.className ?? "",
                  ].join(" ")}
                >
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
