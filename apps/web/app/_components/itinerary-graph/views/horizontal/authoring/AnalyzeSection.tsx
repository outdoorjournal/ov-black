"use client";

// Analyze feasibility (B5), extracted from the old AuthoringPanel. Runs the
// analysis, polls until terminal, and lists findings (severity / category /
// message). Findings are validation rows, NOT cards — the common Card model
// doesn't apply here. Reads only need `canEdit`, so no lock gate.

import { useEffect, useMemo } from "react";

import type { FindingResponse } from "@ov-black/api-client";

import { itineraryGraphStore } from "../../../store/itineraryGraphStore";

import {
  SEVERITY_LABEL,
  SEVERITY_WEIGHT,
  btn,
  sectionTitle,
  severityClass,
} from "./shared";

/** `heading` prints the section's own "Analyze feasibility" label (the prototype
 *  aside); hosts that already title the surface (the Analyze modal) pass false —
 *  the Analyze run button stays either way. */
export function AnalyzeSection({ heading = true }: { heading?: boolean }) {
  const storeApi = itineraryGraphStore.useStoreApi();
  const analyzeStatus = itineraryGraphStore.useStore((s) => s.analyzeStatus);
  const analyzePending = itineraryGraphStore.useStore((s) => s.analyzePending);
  const findings = itineraryGraphStore.useStore((s) => s.findings);
  const analyzeSummary = itineraryGraphStore.useStore((s) => s.analyzeSummary);

  // Poll the analysis while it's in flight; stop as soon as it's terminal.
  useEffect(() => {
    if (analyzeStatus !== "queued" && analyzeStatus !== "running") return;
    const id = setInterval(() => storeApi.getState().refreshAnalysis(), 1500);
    return () => clearInterval(id);
  }, [analyzeStatus, storeApi]);

  const sortedFindings = useMemo(
    () =>
      [...findings].sort(
        (a, b) => SEVERITY_WEIGHT[a.severity] - SEVERITY_WEIGHT[b.severity],
      ),
    [findings],
  );

  const analyzing = analyzeStatus === "queued" || analyzeStatus === "running";

  return (
    <section data-testid="itinerary-graph-analyze">
      <div className="flex items-center justify-between gap-2">
        {heading ? <span className={sectionTitle}>Analyze feasibility</span> : <span />}
        <button
          type="button"
          onClick={() => storeApi.getState().startAnalyze()}
          disabled={analyzePending || analyzing}
          data-testid="itinerary-graph-analyze-run"
          className={btn}
        >
          {analyzing ? "Analyzing" : "Analyze"}
        </button>
      </div>

      {analyzeStatus === "failed" ? (
        <p className="mt-2 font-sans text-[11px] text-[#8b2a1d]">
          The analysis didn’t complete. Try running it again.
        </p>
      ) : null}

      {analyzeStatus === "completed" ? (
        <p
          data-testid="itinerary-graph-analyze-summary"
          className="mt-2 font-sans text-[11px] leading-relaxed text-ink/60"
        >
          {analyzeSummary ?? "No issues found."}
        </p>
      ) : null}

      <ul className="mt-2 flex flex-col gap-2" data-testid="itinerary-graph-findings">
        {sortedFindings.map((f: FindingResponse) => (
          <li
            key={f.id}
            data-testid="itinerary-graph-finding"
            data-severity={f.severity}
            className="rounded-lg border border-ink/10 bg-paper px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <span
                className={`font-sans text-[10px] uppercase tracking-[0.18em] ${severityClass(
                  f.severity,
                )}`}
              >
                {SEVERITY_LABEL[f.severity]}
              </span>
              <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/40">
                {f.category}
              </span>
            </div>
            <p className="mt-1 font-serif text-[14px] leading-snug text-ink">
              {f.message}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
