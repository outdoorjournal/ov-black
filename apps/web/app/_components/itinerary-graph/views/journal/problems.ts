// problems — the Journal's problem-state derivation (traveler-journal design,
// phase 3). The problem SOURCE OF TRUTH is deliberately deferred (the doc's
// answered open question: a later analysis pass will populate it), so this is
// a typed adapter over whatever problem data already exists client-side:
//
//   · Analyze findings in the store (`s.findings`, advisor-run) — warn/block
//     severities mapped to their node ids.
//   · A typed optional `metadata.problem` bag on the node itself — the forward
//     socket, so the rendering lights up the moment real data arrives.
//
// Nothing here invents a backend; when neither input is present the Journal
// simply has no problem treatment.

import type { FindingResponse } from "@ov-black/api-client";

import type { NodeResponse } from "../../model/types";

export type JournalProblemSeverity = "warn" | "block";

export type JournalProblem = {
  message: string;
  severity: JournalProblemSeverity;
};

/** The typed optional `metadata.problem` input shape. */
type ProblemMeta = { message?: unknown; severity?: unknown };

function problemOfMeta(node: NodeResponse): JournalProblem | null {
  const bag = (node.metadata as { problem?: ProblemMeta }).problem;
  if (!bag || typeof bag.message !== "string" || bag.message.length === 0) {
    return null;
  }
  return {
    message: bag.message,
    severity: bag.severity === "block" ? "block" : "warn",
  };
}

const rank: Record<JournalProblemSeverity, number> = { warn: 0, block: 1 };

/**
 * node id → its problem. When both a finding and a metadata bag speak about
 * the same node, the more severe one wins (block > warn); ties keep the
 * finding (the fresher analysis).
 */
export function journalProblems(
  nodes: NodeResponse[],
  findings: FindingResponse[],
): Map<string, JournalProblem> {
  const out = new Map<string, JournalProblem>();
  for (const f of findings) {
    if (!f.node_id) continue;
    if (f.severity !== "warn" && f.severity !== "block") continue;
    const candidate: JournalProblem = {
      message: f.message,
      severity: f.severity,
    };
    const existing = out.get(f.node_id);
    if (!existing || rank[candidate.severity] > rank[existing.severity]) {
      out.set(f.node_id, candidate);
    }
  }
  for (const n of nodes) {
    const fromMeta = problemOfMeta(n);
    if (!fromMeta) continue;
    const existing = out.get(n.id);
    if (!existing || rank[fromMeta.severity] > rank[existing.severity]) {
      out.set(n.id, fromMeta);
    }
  }
  return out;
}
