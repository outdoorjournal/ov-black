import { Panel } from "../_components/panels";
import { TableSkeleton } from "../_components/table/EmptyState";

export default function Loading() {
  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="border-b border-paper/10 pb-8">
        <div className="h-3 w-32 animate-pulse rounded bg-paper/6" />
        <div className="mt-4 h-10 w-48 animate-pulse rounded bg-paper/8" />
      </header>
      <Panel aria-hidden>
        <TableSkeleton />
      </Panel>
    </main>
  );
}
