"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type FindingResponse,
  type ForkDiffResponse,
  type NodeChangeResponse,
  type ReconcileOutcomeResponse,
  createApiClient,
  getAnalysis,
  getForkDiff,
  reconcileFork,
  startAnalysis,
} from "@ov-black/api-client";

// Advisor diff + reconcile surface — the itinerary-aside Diff tab (M004/G3).
//
// Self-contained like PartyPanel: it takes the staff credentials the store holds
// (travelers never receive them) and calls the fork wrappers directly. Diffs this
// alternative version against its baseline by lineage, runs a feasibility check
// (Analyze on the fork), and reconciles a per-change selection into the LIVE plan —
// the per-change outcome is shown honestly (a booked node refusal reads "kept").

const ATTENTION = "#8b2a1d";

const ERROR_COPY: Record<string, string> = {
  not_found: "This alternative could not be found.",
  not_a_fork: "This itinerary is not an alternative version.",
  fork_infeasible:
    "This alternative has a blocking feasibility issue. Override to reconcile anyway.",
  advisor_only: "Reconciling is advisor-only.",
  forbidden: "You don't have access to this alternative.",
  network_error: "Could not reach the server. Try again in a moment.",
};

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

type Snapshot = Record<string, unknown> | null;

function str(snapshot: Snapshot, key: string): string | null {
  const value = snapshot?.[key];
  return typeof value === "string" ? value : null;
}

function nodeLabel(snapshot: Snapshot): string {
  return str(snapshot, "title") || "Untitled";
}

function costLabel(snapshot: Snapshot): string | null {
  const amount = str(snapshot, "cost_amount");
  const currency = str(snapshot, "cost_currency");
  return amount && currency ? `${currency} ${amount}` : null;
}

function isTerminal(status: string): boolean {
  return ["completed", "failed", "cancelled"].includes(status);
}

const SECTIONS: { key: keyof ReconcileBuckets; label: string }[] = [
  { key: "added", label: "Added" },
  { key: "removed", label: "Removed" },
  { key: "changed", label: "Changed" },
  { key: "moved", label: "Moved" },
];

type ReconcileBuckets = Pick<
  ForkDiffResponse,
  "added" | "removed" | "changed" | "moved"
>;

function allChanges(diff: ForkDiffResponse): NodeChangeResponse[] {
  return [...diff.added, ...diff.removed, ...diff.changed, ...diff.moved];
}

export function DiffPanel({
  apiBaseUrl,
  accessToken,
  forkItineraryId,
  baselineItineraryId,
  editable,
}: {
  apiBaseUrl: string | null;
  accessToken: string | null;
  forkItineraryId: string;
  baselineItineraryId: string | null;
  editable: boolean;
}) {
  const [diff, setDiff] = useState<ForkDiffResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // change_id → accept (true) | discard (false). Defaults to accept.
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [analysis, setAnalysis] = useState<{
    id: string;
    status: string;
    findings: FindingResponse[];
  } | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [overrideBlock, setOverrideBlock] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [outcomes, setOutcomes] = useState<ReconcileOutcomeResponse[] | null>(
    null,
  );
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const api =
    apiBaseUrl && accessToken
      ? createApiClient({ baseUrl: apiBaseUrl, accessToken })
      : null;

  const refresh = useCallback(async () => {
    if (!api) return;
    const result = await getForkDiff(api, forkItineraryId);
    if (!mounted.current) return;
    if (result.ok) {
      setDiff(result.diff);
      setDecisions((prev) => {
        const next: Record<string, boolean> = {};
        for (const change of allChanges(result.diff)) {
          next[change.change_id] = prev[change.change_id] ?? true;
        }
        return next;
      });
    } else {
      setError(copy(result.detail));
    }
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forkItineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = (changeId: string) =>
    setDecisions((prev) => ({ ...prev, [changeId]: !prev[changeId] }));

  const runFeasibility = useCallback(async () => {
    if (!api || analyzing) return;
    setAnalyzing(true);
    setError(null);
    try {
      const created = await startAnalysis(api, { itineraryId: forkItineraryId });
      if (!created.ok) {
        if (mounted.current) setError(copy(created.detail));
        return;
      }
      const analysisId = created.created.analysis_id;
      for (let i = 0; i < 20; i += 1) {
        const got = await getAnalysis(api, {
          itineraryId: forkItineraryId,
          analysisId,
        });
        if (!mounted.current) return;
        if (got.ok) {
          setAnalysis({
            id: got.analysis.id,
            status: got.analysis.status,
            findings: got.analysis.findings,
          });
          if (isTerminal(got.analysis.status)) return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    } finally {
      if (mounted.current) setAnalyzing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forkItineraryId, apiBaseUrl, accessToken, analyzing]);

  const hasBlock =
    analysis?.findings.some((f) => String(f.severity) === "block") ?? false;

  const reconcile = useCallback(async () => {
    if (!api || !diff || reconciling) return;
    setReconciling(true);
    setError(null);
    setOutcomes(null);
    try {
      const result = await reconcileFork(api, forkItineraryId, {
        decisions: allChanges(diff).map((c) => ({
          change_id: c.change_id,
          accept: decisions[c.change_id] ?? true,
        })),
        ...(analysis ? { analysis_id: analysis.id } : {}),
        override_block: overrideBlock,
      });
      if (!mounted.current) return;
      if (result.ok) {
        setOutcomes(result.result.outcomes);
        await refresh(); // baseline moved — re-diff to show the smaller delta
      } else {
        setError(copy(result.detail));
      }
    } finally {
      if (mounted.current) setReconciling(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diff, decisions, analysis, overrideBlock, forkItineraryId, reconciling]);

  const changeCount = diff ? allChanges(diff).length : 0;

  return (
    <div
      data-testid="diff-panel"
      className="flex h-full flex-col gap-5 overflow-y-auto bg-paper px-4 py-4 text-ink"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="font-serif text-lg tracking-tight text-ink">
          Alternative vs. agreed plan
        </h3>
        {baselineItineraryId ? (
          <a
            href={`/itinerary/${baselineItineraryId}`}
            className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/50 transition-colors hover:text-ink"
          >
            View agreed plan →
          </a>
        ) : null}
      </header>

      {!loaded ? (
        <p className="font-sans text-sm text-ink/50">Loading…</p>
      ) : changeCount === 0 ? (
        <p className="font-sans text-sm italic text-ink/50">
          This alternative matches the agreed plan — nothing to reconcile.
        </p>
      ) : (
        <>
          {/* Feasibility check */}
          <section className="flex flex-col gap-2 border-y border-ink/10 py-3">
            <div className="flex items-center justify-between">
              <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
                Feasibility
              </span>
              <button
                type="button"
                onClick={() => void runFeasibility()}
                disabled={analyzing}
                className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
              >
                {analyzing ? "Checking…" : "Run feasibility check"}
              </button>
            </div>
            {analysis && isTerminal(analysis.status) ? (
              analysis.findings.length === 0 ? (
                <p className="font-sans text-xs text-ink/55">
                  No feasibility issues found.
                </p>
              ) : (
                <ul className="flex flex-col gap-1" data-testid="diff-findings">
                  {[...analysis.findings]
                    .sort((a, b) =>
                      String(b.severity).localeCompare(String(a.severity)),
                    )
                    .map((f) => (
                      <li
                        key={f.id}
                        className="font-sans text-xs"
                        style={
                          String(f.severity) === "block"
                            ? { color: ATTENTION }
                            : undefined
                        }
                      >
                        <span className="uppercase tracking-[0.16em]">
                          {String(f.severity)}
                        </span>{" "}
                        · {f.category} — {f.message}
                      </li>
                    ))}
                </ul>
              )
            ) : null}
          </section>

          {/* Change buckets */}
          {SECTIONS.map(({ key, label }) => {
            const changes = diff ? diff[key] : [];
            if (changes.length === 0) return null;
            return (
              <section key={key} className="flex flex-col gap-2">
                <h4 className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
                  {label} · {changes.length}
                </h4>
                <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
                  {changes.map((change) => (
                    <li
                      key={change.change_id}
                      data-testid={`diff-change-${change.change_id}`}
                      className="flex items-start gap-3 py-2.5"
                    >
                      <div className="min-w-0 flex-1">
                        <ChangeBody change={change} />
                      </div>
                      <label className="flex shrink-0 cursor-pointer items-center gap-1.5 font-sans text-[10px] uppercase tracking-[0.18em] text-ink/60">
                        <input
                          type="checkbox"
                          checked={decisions[change.change_id] ?? true}
                          onChange={() => toggle(change.change_id)}
                          className="accent-ink"
                        />
                        Accept
                      </label>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}

          {/* Reconcile footer */}
          <section className="flex flex-col gap-2 border-t border-ink/10 pt-3">
            {hasBlock ? (
              <label className="flex items-center gap-2 font-sans text-xs" style={{ color: ATTENTION }}>
                <input
                  type="checkbox"
                  checked={overrideBlock}
                  onChange={() => setOverrideBlock((v) => !v)}
                />
                Override the blocking feasibility issue
              </label>
            ) : null}
            <button
              type="button"
              onClick={() => void reconcile()}
              disabled={!editable || reconciling}
              data-testid="diff-reconcile"
              className="rounded-md border border-ink/20 bg-paper px-3 py-1.5 font-sans text-[11px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              {reconciling ? "Reconciling…" : "Reconcile selected"}
            </button>
            {!editable ? (
              <p className="font-sans text-xs italic text-ink/50">
                Hold the edit lock to reconcile.
              </p>
            ) : null}
          </section>

          {outcomes ? (
            <section className="flex flex-col gap-1" data-testid="diff-outcomes">
              <h4 className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
                Result
              </h4>
              <ul className="flex flex-col gap-0.5">
                {outcomes.map((o) => (
                  <li key={o.change_id} className="font-sans text-xs text-ink/70">
                    {o.kind} — {outcomeLabel(o.result)}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      {error ? (
        <p role="alert" className="font-sans text-xs font-medium" style={{ color: ATTENTION }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function outcomeLabel(result: string): string {
  switch (result) {
    case "applied":
      return "merged into the agreed plan";
    case "discarded":
      return "kept out (discarded)";
    case "refused_booked":
      return "kept (booked — can't be changed)";
    case "skipped":
      return "skipped (already resolved)";
    default:
      return "could not be applied";
  }
}

function ChangeBody({ change }: { change: NodeChangeResponse }) {
  const before = change.before ?? null;
  const after = change.after ?? null;
  if (change.kind === "added") {
    const cost = costLabel(after);
    return (
      <p className="font-sans text-sm text-ink/90">
        <span className="font-medium">{nodeLabel(after)}</span>
        {cost ? <span className="text-ink/55"> · {cost}</span> : null}
      </p>
    );
  }
  if (change.kind === "removed") {
    return (
      <p className="font-sans text-sm text-ink/90 line-through decoration-ink/30">
        {nodeLabel(before)}
      </p>
    );
  }
  if (change.kind === "moved") {
    return (
      <p className="font-sans text-sm text-ink/90">
        {nodeLabel(after)}
        <span className="ml-2 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
          reordered
        </span>
      </p>
    );
  }
  // changed — show baseline → fork with the changed field names.
  const fields = change.fields ?? [];
  return (
    <div className="font-sans text-sm text-ink/90">
      <span className="text-ink/55">{nodeLabel(before)}</span>
      <span className="px-1 text-ink/40">→</span>
      <span className="font-medium">{nodeLabel(after)}</span>
      {fields.length ? (
        <span className="ml-2 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
          {fields.join(", ")}
        </span>
      ) : null}
    </div>
  );
}
