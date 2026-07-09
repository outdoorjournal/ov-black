import Link from "next/link";
import { notFound } from "next/navigation";

import {
  type AgentTurnSummary,
  getClient,
  listTurns,
} from "@ov-black/api-client";

import { SetClientCrumb } from "@/app/command-center/_components/CommandCenterCrumb";
import { EmptyNote } from "@/app/command-center/_components/panels";
import { advisorApi } from "@/app/command-center/_lib/api";
import {
  formatMs,
  summarizeTurns,
} from "@/app/command-center/_lib/summarizeTurns";

// Read-only session replay (Wave F): the full transcript with per-turn
// telemetry chips and a summary strip. Diagnostic surface, not an urgent one —
// latency is mono, retries are amber, errors are destructive; no orange here.
// "Open live" jumps to the same /chat surface the traveler sees.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 100;

export default async function SessionReplayPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; sessionId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, sessionId } = await params;
  const sp = await searchParams;
  const beforeRaw = sp["before"];
  const before = Number.parseInt(
    (Array.isArray(beforeRaw) ? beforeRaw[0] : beforeRaw) ?? "",
    10,
  );
  const beforeIndex = Number.isFinite(before) && before > 0 ? before : undefined;

  const api = await advisorApi();
  const [clientResult, turnsResult] = await Promise.all([
    getClient(api, id),
    listTurns(api, sessionId, {
      limit: PAGE_SIZE,
      ...(beforeIndex !== undefined ? { beforeIndex } : {}),
    }),
  ]);

  if (!clientResult.ok) notFound();
  if (!turnsResult.ok) {
    if (turnsResult.detail === "session_not_found") notFound();
    return (
      <main className="flex w-full flex-1 flex-col gap-6 px-6 py-12 sm:px-10 sm:py-16">
        <p role="alert" className="font-sans text-sm text-destructive">
          Could not load the session. Try again in a moment.
        </p>
      </main>
    );
  }

  const client = clientResult.client;
  const turns = turnsResult.turns;
  const summary = summarizeTurns(turns);
  const firstIndex = turns[0]?.turn_index;
  const hasOlder =
    turns.length === PAGE_SIZE && firstIndex !== undefined && firstIndex > 0;

  return (
    <main className="flex w-full flex-1 flex-col gap-8 px-6 py-10 sm:px-10 sm:py-12">
      <SetClientCrumb name={client.full_name} />

      <header className="flex flex-col gap-6 border-b border-paper/10 pb-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
            Session replay
          </p>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper">
            {client.full_name}
          </h1>
          <div className="mt-3 flex items-center gap-4">
            <Link
              href={`/command-center/clients/${client.id}`}
              className="font-sans text-xs text-paper/55 transition-colors hover:text-paper"
            >
              ← Workspace
            </Link>
            <Link
              href={`/chat/${client.id}`}
              className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55 transition-colors hover:text-paper"
            >
              Open live
            </Link>
          </div>
        </div>
        <TelemetryStrip summary={summary} />
      </header>

      {turns.length === 0 ? (
        <EmptyNote>No turns in this session yet.</EmptyNote>
      ) : (
        <>
          {beforeIndex !== undefined || hasOlder ? (
            <nav className="flex items-center gap-4" aria-label="Transcript pages">
              {hasOlder ? (
                <Link
                  href={`/command-center/clients/${client.id}/sessions/${sessionId}?before=${firstIndex}`}
                  className="font-sans text-xs text-paper/55 transition-colors hover:text-paper"
                >
                  ← Older turns
                </Link>
              ) : null}
              {beforeIndex !== undefined ? (
                <Link
                  href={`/command-center/clients/${client.id}/sessions/${sessionId}`}
                  className="font-sans text-xs text-paper/55 transition-colors hover:text-paper"
                >
                  Latest →
                </Link>
              ) : null}
            </nav>
          ) : null}

          <ol className="flex max-w-3xl flex-col gap-6" data-testid="replay-transcript">
            {turns.map((turn) => (
              <TurnRow key={turn.id} turn={turn} />
            ))}
          </ol>
        </>
      )}
    </main>
  );
}

function TelemetryStrip({
  summary,
}: {
  summary: ReturnType<typeof summarizeTurns>;
}) {
  return (
    <dl
      className="flex shrink-0 flex-wrap gap-x-8 gap-y-4"
      data-testid="replay-telemetry"
    >
      <Metric label="Turns" value={`${summary.turnCount}`} />
      <Metric
        label="Span"
        value={summary.spanMs > 0 ? formatMs(summary.spanMs) : "—"}
      />
      <Metric
        label="Avg latency"
        value={summary.avgLatencyMs != null ? formatMs(summary.avgLatencyMs) : "—"}
      />
      <Metric
        label="First token p50"
        value={
          summary.firstTokenP50Ms != null ? formatMs(summary.firstTokenP50Ms) : "—"
        }
      />
      <Metric
        label="Retries"
        value={`${summary.retries}`}
        tone={summary.retries > 0 ? "amber" : "default"}
      />
      <Metric
        label="Errors"
        value={`${summary.errors}`}
        tone={summary.errors > 0 ? "destructive" : "default"}
      />
    </dl>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "amber" | "destructive";
}) {
  const valueCls =
    tone === "amber"
      ? "text-amber-300"
      : tone === "destructive"
        ? "text-destructive"
        : "text-paper";
  return (
    <div className="text-right">
      <dd className={`font-mono text-xl tabular-nums ${valueCls}`}>{value}</dd>
      <dt className="font-sans text-[10px] uppercase tracking-label text-paper/45">
        {label}
      </dt>
    </div>
  );
}

function TurnRow({ turn }: { turn: AgentTurnSummary }) {
  if (turn.role === "system" || turn.role === "tool") {
    return (
      <li
        className="font-mono text-[11px] text-paper/40"
        data-testid="replay-turn"
      >
        [{turn.role}] {turn.content.slice(0, 200)}
      </li>
    );
  }

  const isTraveler = turn.role === "user";
  const isError = turn.role === "error" || turn.error_reason != null;

  return (
    <li
      className={`flex flex-col gap-2 ${isTraveler ? "items-end" : "items-start"}`}
      data-testid="replay-turn"
    >
      <div
        className={`max-w-[85%] rounded-md border px-4 py-3 ${
          isError
            ? "border-destructive/40 bg-destructive/10"
            : isTraveler
              ? "border-paper/15 bg-paper/10"
              : "border-paper/10 bg-paper/5"
        }`}
      >
        <p className="font-sans text-[10px] uppercase tracking-label text-paper/45">
          {isTraveler ? "Traveler" : "Concierge"} · #{turn.turn_index}
        </p>
        <p className="mt-1 whitespace-pre-wrap font-sans text-sm text-paper/90">
          {turn.content}
        </p>
      </div>
      <TurnChips turn={turn} />
    </li>
  );
}

function TurnChips({ turn }: { turn: AgentTurnSummary }) {
  const chips: React.ReactNode[] = [];
  if (turn.latency_ms != null) {
    chips.push(
      <span key="latency" className="font-mono text-[10px] text-paper/45">
        {formatMs(turn.latency_ms)}
        {turn.first_token_ms != null
          ? ` · first ${formatMs(turn.first_token_ms)}`
          : ""}
      </span>,
    );
  }
  if (turn.retried > 0) {
    chips.push(
      <span key="retried" className="font-mono text-[10px] text-amber-300">
        retried ×{turn.retried}
      </span>,
    );
  }
  if (turn.error_reason) {
    chips.push(
      <span key="error" className="font-mono text-[10px] text-destructive">
        error: {turn.error_reason}
      </span>,
    );
  }
  if (chips.length === 0) return null;
  return <p className="flex items-center gap-3 px-1">{chips}</p>;
}
