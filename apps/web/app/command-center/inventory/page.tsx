import { InventoryWorkbench } from "../_components/InventoryWorkbench";
import { parseInventoryQuery } from "../_lib/inventoryQuery";
import type { SearchParamsShape } from "../_lib/tableParams";

// The inventory workbench (Wave F follow-on): search across every registered
// provider with full control of the query params — the advisor's discovery
// surface and the developer's harness for testing a newly wired source. The
// URL is the query (same param names as GET /search-inventory), so the server
// page just snapshots it into initial form state; fetching is client-side —
// a workbench iterates on params live.
export const dynamic = "force-dynamic";

export default async function InventoryPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsShape>;
}) {
  const initial = parseInventoryQuery(await searchParams);

  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="border-b border-paper/10 pb-8">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          Command Center
        </p>
        <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Inventory
        </h1>
      </header>
      <InventoryWorkbench initial={initial} />
    </main>
  );
}
