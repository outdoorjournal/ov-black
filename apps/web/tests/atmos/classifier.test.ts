// Unit tests for the S06 mood classifier and its phase-shift hook.
//
// The slice suite (T04) covers integration via the rendered frame; here we
// pin the pure-function contract and the hook's tick gating so regressions
// localize to one file.

import { StrictMode } from "react";
import { renderHook } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { classifyMood, usePhaseShiftMood, useAtmosOverride } from "@/lib/atmos/classifier";
import type { AgentTurnView } from "@/app/chat/[client_id]/_components/types";

function turn(
  role: AgentTurnView["role"],
  content: string,
  index = 0,
): AgentTurnView {
  return { id: `t-${index}-${role}`, turn_index: index, role, content };
}

describe("classifyMood", () => {
  test("returns 'glacial' for turns mentioning Patagonia", () => {
    const turns: AgentTurnView[] = [
      turn("user", "I've always dreamed of trekking through Patagonia.", 0),
    ];
    expect(classifyMood(turns)).toBe("glacial");
  });

  test("returns 'amber' for turns mentioning Tuscany", () => {
    const turns: AgentTurnView[] = [
      turn("user", "A slow week in Tuscany sipping Chianti sounds perfect.", 0),
    ];
    expect(classifyMood(turns)).toBe("amber");
  });

  test("returns null for empty turns", () => {
    expect(classifyMood([])).toBeNull();
  });

  test("ignores error/system/tool turns", () => {
    const turns: AgentTurnView[] = [
      turn("system", "Patagonia system prompt bootstrap", 0),
      turn("tool", "tool call result mentioning Tuscany", 1),
      turn("error", "connection reset while discussing Marrakech", 2),
    ];
    expect(classifyMood(turns)).toBeNull();
  });

  test("with windowSize=3 only reads the last 3 eligible turns", () => {
    const turns: AgentTurnView[] = [
      turn("user", "Patagonia glacier fjord arctic", 0),
      turn("assistant", "tokyo shibuya skyline metro", 1),
      turn("user", "tokyo manhattan brooklyn", 2),
      turn("assistant", "shanghai skyline", 3),
    ];
    // Last 3: assistant(tokyo...) + user(tokyo...) + assistant(shanghai...)
    // → onyx dominates; the older glacial-heavy turn is ignored.
    expect(classifyMood(turns)).toBe("onyx");
  });

  test("tie-breaker: later keyword appearance wins", () => {
    // One hit for each mood; the order means 'amber' (tuscany) appears last.
    const turns: AgentTurnView[] = [
      turn("user", "patagonia then tuscany", 0),
    ];
    expect(classifyMood(turns)).toBe("amber");
  });
});

describe("usePhaseShiftMood", () => {
  test("ticks every phaseSize turns, not every turn", () => {
    const t1 = turn("user", "Patagonia fjord glacier", 0);
    const t2 = turn("assistant", "Iceland arctic", 1);
    const t3 = turn("user", "antarctica norway", 2);
    const t4 = turn("assistant", "more glacial content fjord", 3);

    const { result, rerender } = renderHook(
      ({ turns }: { turns: AgentTurnView[] }) => usePhaseShiftMood(turns),
      { initialProps: { turns: [] as AgentTurnView[] } },
    );

    // turns=0 → fallback, counter=0
    expect(result.current.phaseCounter).toBe(0);
    expect(result.current.mood).toBe("alpine");

    // turns=1 → still fallback, counter=0
    rerender({ turns: [t1] });
    expect(result.current.phaseCounter).toBe(0);
    expect(result.current.mood).toBe("alpine");

    // turns=3 → tick, counter=1, classified
    rerender({ turns: [t1, t2, t3] });
    expect(result.current.phaseCounter).toBe(1);
    expect(result.current.mood).toBe("glacial");

    // turns=4 → no tick, mood unchanged
    rerender({ turns: [t1, t2, t3, t4] });
    expect(result.current.phaseCounter).toBe(1);
    expect(result.current.mood).toBe("glacial");
  });

  test("counter survives StrictMode double-render (counter=1 after 3 turns)", () => {
    const t1 = turn("user", "Patagonia fjord glacier", 0);
    const t2 = turn("assistant", "Iceland arctic", 1);
    const t3 = turn("user", "antarctica norway", 2);

    const { result, rerender } = renderHook(
      ({ turns }: { turns: AgentTurnView[] }) => usePhaseShiftMood(turns),
      {
        wrapper: StrictMode,
        initialProps: { turns: [] as AgentTurnView[] },
      },
    );

    rerender({ turns: [t1, t2, t3] });
    // StrictMode double-invokes render; the tick must still happen exactly
    // once for this length, so counter is 1 (not 2).
    expect(result.current.phaseCounter).toBe(1);
    expect(result.current.mood).toBe("glacial");
  });
});

describe("useAtmosOverride", () => {
  test("returns null in M001 (forward-compat seam for S08)", () => {
    const { result } = renderHook(() => useAtmosOverride());
    expect(result.current).toBeNull();
  });
});
