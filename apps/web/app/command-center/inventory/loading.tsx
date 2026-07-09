import { Panel } from "../_components/panels";

export default function Loading() {
  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="border-b border-paper/10 pb-8">
        <div className="h-3 w-32 animate-pulse rounded bg-paper/6" />
        <div className="mt-4 h-10 w-48 animate-pulse rounded bg-paper/8" />
      </header>
      <Panel aria-hidden>
        <div className="h-9 w-full animate-pulse rounded bg-paper/6" />
        <div className="h-6 w-3/4 animate-pulse rounded bg-paper/6" />
        <div className="h-6 w-2/3 animate-pulse rounded bg-paper/6" />
      </Panel>
    </main>
  );
}
