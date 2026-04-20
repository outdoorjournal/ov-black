// Mood classifier + phase-shift hook for the atmospheric frame (S06).
//
// classifyMood is a pure function over the tail of a turn list: it tokenizes
// the concatenated content, scores each mood by keyword hits, and returns
// the winner. Ties break on the token that appears latest (more recent signal
// dominates when counts are equal).
//
// usePhaseShiftMood gates re-classification: the mood only changes every Nth
// committed turn (default 3) so the frame drifts on phase shifts rather than
// strobing on every message. The counter is held in a ref and compared
// during render so React 19 StrictMode's double-invocation doesn't tick twice.

import { useMemo, useRef } from "react";

import { DEFAULT_MOOD, MOODS, type MoodId } from "./moods";

import type { AgentTurnView } from "@/app/chat/[client_id]/_components/types";

const CLASSIFIABLE_ROLES = new Set(["user", "assistant"]);

export function classifyMood(
  turns: AgentTurnView[],
  options?: { windowSize?: number },
): MoodId | null {
  const windowSize = options?.windowSize ?? 3;
  const eligible = turns.filter((t) => CLASSIFIABLE_ROLES.has(t.role));
  const window = eligible.slice(-windowSize);
  if (window.length === 0) return null;

  const text = window.map((t) => t.content).join(" ").toLowerCase();
  const tokens = text.match(/[a-z]+/g) ?? [];
  if (tokens.length === 0) return null;

  const keywordToMood = new Map<string, MoodId>();
  for (const moodId of Object.keys(MOODS) as MoodId[]) {
    for (const kw of MOODS[moodId].keywords) {
      keywordToMood.set(kw, moodId);
    }
  }

  const counts: Partial<Record<MoodId, number>> = {};
  const lastIndex: Partial<Record<MoodId, number>> = {};
  for (let i = 0; i < tokens.length; i++) {
    const mood = keywordToMood.get(tokens[i]!);
    if (!mood) continue;
    counts[mood] = (counts[mood] ?? 0) + 1;
    lastIndex[mood] = i;
  }

  let winner: MoodId | null = null;
  let winnerCount = 0;
  let winnerLastIndex = -1;
  for (const moodId of Object.keys(counts) as MoodId[]) {
    const c = counts[moodId]!;
    const li = lastIndex[moodId]!;
    if (
      c > winnerCount ||
      (c === winnerCount && li > winnerLastIndex)
    ) {
      winner = moodId;
      winnerCount = c;
      winnerLastIndex = li;
    }
  }
  return winner;
}

export function usePhaseShiftMood(
  turns: AgentTurnView[],
  options?: { phaseSize?: number; fallback?: MoodId },
): { mood: MoodId; phaseCounter: number } {
  const phaseSize = options?.phaseSize ?? 3;
  const fallback = options?.fallback ?? DEFAULT_MOOD;

  // Refs, not state: we don't want a setState to cause another re-render, and
  // we don't want StrictMode's dev-only double-invocation of the render body
  // to tick the counter twice. The counter advances at most once per unique
  // turns.length value.
  const phaseCounterRef = useRef(0);
  const lastTickAtLengthRef = useRef(-1);
  const lastMoodRef = useRef<MoodId | null>(null);

  const length = turns.length;
  // Only tick when we cross the next phase boundary AND we haven't already
  // ticked at this exact length (StrictMode guard).
  if (length >= phaseSize && length !== lastTickAtLengthRef.current) {
    const crossedBoundaries = Math.floor(length / phaseSize);
    if (crossedBoundaries > phaseCounterRef.current) {
      phaseCounterRef.current = crossedBoundaries;
      lastTickAtLengthRef.current = length;
      lastMoodRef.current = classifyMood(turns, { windowSize: phaseSize });
    }
  }

  const phaseCounter = phaseCounterRef.current;
  const resolvedMood = lastMoodRef.current ?? fallback;

  return useMemo(
    () => ({ mood: resolvedMood, phaseCounter }),
    [resolvedMood, phaseCounter],
  );
}

// Forward-compat seam for S08's approval-gate override. ChatShell wires
// `useAtmosOverride() ?? usePhaseShiftMood(state.turns).mood` so the override
// can slot in later without restructuring.
export function useAtmosOverride(): MoodId | null {
  return null;
}
