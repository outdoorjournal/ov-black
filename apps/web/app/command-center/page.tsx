import {
  getAdvisorActivity,
  getAdvisorOverview,
  getAwareness,
  listAdvisorItineraries,
} from "@ov-black/api-client";

import { ErrorBanner } from "./_components/panels";
import { ActivityFeed } from "./_components/ops/ActivityFeed";
import { AttentionQueue } from "./_components/ops/AttentionQueue";
import { PipelineStrip } from "./_components/ops/PipelineStrip";
import { StatsBand } from "./_components/ops/StatsBand";
import { advisorApi } from "./_lib/api";

// Ops — mission control (Wave F). One screen answers the advisor's morning
// question: what is waiting on me, what happened while I was away, what's
// moving right now. Four server reads in parallel (all cheap aggregates);
// the live SSE feed prepends activity client-side and nudges a throttled
// router.refresh() so the queue and stats stay honest without a reload.
export const dynamic = "force-dynamic";

export default async function OpsPage() {
  const api = await advisorApi();

  const [overviewResult, awarenessResult, activityResult, tripsResult] =
    await Promise.all([
      getAdvisorOverview(api),
      getAwareness(api),
      getAdvisorActivity(api, { limit: 30 }),
      listAdvisorItineraries(api, { limit: 6 }),
    ]);

  const attention = awarenessResult.ok ? awarenessResult.clients : [];
  const clientNames: Record<string, string> = {};
  for (const c of attention) {
    if (c.full_name) clientNames[c.client_id] = c.full_name;
  }

  const today = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date());

  return (
    <main className="flex w-full flex-1 flex-col gap-8 px-6 py-10 sm:px-10 sm:py-12">
      <header className="flex flex-col gap-2 border-b border-paper/10 pb-8">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          Ops · {today}
        </p>
        <h1 className="font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Mission Control
        </h1>
      </header>

      {!overviewResult.ok && !awarenessResult.ok ? (
        <ErrorBanner>
          Could not reach the API — the numbers below may be stale or missing.
        </ErrorBanner>
      ) : null}

      {overviewResult.ok ? <StatsBand overview={overviewResult.overview} /> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-6">
          <AttentionQueue clients={attention} />
          <PipelineStrip trips={tripsResult.ok ? tripsResult.itineraries : []} />
        </div>
        <div className="min-w-0 lg:sticky lg:top-4 lg:self-start">
          <ActivityFeed
            initialEvents={activityResult.ok ? activityResult.events : []}
            clientNames={clientNames}
          />
        </div>
      </div>
    </main>
  );
}
