"use client";

import type { Dispatch } from "react";

import { getVerticalMeta, type NodeResponse } from "../_lib/types";
import type {
  VerticalTimelineAction,
  VerticalTimelineState,
} from "./useTimelineState";

export interface AgentNode {
  id: string;
  itinerary_id: string;
  type: string;
  status: string;
  title: string;
  source: string | null;
  source_id: string | null;
  metadata: Record<string, unknown>;
}

export type ScenarioId = "propose" | "assemble" | "modify" | "freeform";

export interface ScenarioContext {
  state: VerticalTimelineState;
  dispatch: Dispatch<VerticalTimelineAction>;
  onAssembleSweep?: (nodeIds: string[]) => void;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function nextId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

async function streamAssistant(
  ctx: ScenarioContext,
  text: string,
  perTokenMs = 22,
): Promise<void> {
  const msgId = nextId("msg");
  ctx.dispatch({ type: "APPEND_ASSISTANT_MESSAGE", id: msgId });
  const tokens = text.match(/\S+\s*|\s+/g) ?? [text];
  for (const tok of tokens) {
    await sleep(perTokenMs);
    ctx.dispatch({ type: "APPEND_DELTA", id: msgId, text: tok });
  }
  ctx.dispatch({ type: "FINISH_ASSISTANT", id: msgId });
}

async function runProposeScenario(ctx: ScenarioContext) {
  ctx.dispatch({
    type: "APPEND_USER_MESSAGE",
    id: nextId("msg"),
    text: "Can you propose a couple more experiences I might love?",
  });
  await sleep(300);
  await streamAssistant(
    ctx,
    "Looking at your trip, here are a few ideas — each lands on the timeline at its proposed time. Accept or dismiss from the chat or the card.",
  );

  const itineraryId = ctx.state.sample.itinerary.id;

  const proposals: AgentNode[] = [
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "experience",
      status: "proposed",
      title: "Tea ceremony at a Kyoto machiya",
      source: "mock",
      source_id: "prop-tea",
      metadata: {
        start_time: "2024-06-25T10:00:00+09:00",
        duration_minutes: 75,
        location: { lat: 35.0116, lng: 135.7681, label: "Gion" },
        ambient_image: "/japan/day06_kinkoen_sumi_ink.jpg",
        description: "Private chado session in a restored 19th-century townhouse.",
        snapshot: {
          title: "Kyoto machiya tea ceremony",
          cover_image: "/japan/day06_kinkoen_sumi_ink.jpg",
          location: "Gion, Kyoto",
          activities: ["Matcha", "Wagashi", "Chado history"],
        },
      },
    },
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "meal",
      status: "proposed",
      title: "Chef's-table kaiseki dinner",
      source: "mock",
      source_id: "prop-kaiseki",
      metadata: {
        start_time: "2024-06-26T19:30:00+09:00",
        duration_minutes: 120,
        time_of_day: "evening",
        location: { lat: 34.3953, lng: 132.4638, label: "Hiroshima" },
        ambient_image: "/japan/day08_hiroshima_okonomiyaki.jpg",
        description: "Eight-course tasting from a rising Michelin-starred chef.",
        snapshot: {
          title: "Kaiseki chef's table",
          cover_image: "/japan/day08_hiroshima_okonomiyaki.jpg",
          price: "$240 pp",
          location: "Hiroshima",
          activities: ["8 courses", "Sake pairing"],
        },
      },
    },
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "experience",
      status: "proposed",
      title: "Dawn hot-air balloon over Mt Fuji foothills",
      source: "mock",
      source_id: "prop-balloon",
      metadata: {
        start_time: "2024-07-01T05:30:00+09:00",
        duration_minutes: 90,
        location: { lat: 35.5024, lng: 138.7528, label: "Kawaguchiko" },
        ambient_image: "/japan/day12_road_to_fuji_5th_station.jpg",
        description: "Launch at first light with champagne on the descent.",
        snapshot: {
          title: "Dawn balloon · Kawaguchiko",
          cover_image: "/japan/day12_road_to_fuji_5th_station.jpg",
          price: "$420 pp",
          location: "Kawaguchiko",
          activities: ["Pilot briefing", "60-min flight", "Breakfast"],
        },
      },
    },
  ];

  for (const proposal of proposals) {
    await sleep(480);
    ctx.dispatch({ type: "PROPOSE_NODE", node: proposal });
  }
}

async function runAssembleScenario(ctx: ScenarioContext) {
  ctx.dispatch({
    type: "APPEND_USER_MESSAGE",
    id: nextId("msg"),
    text: "Assemble my days into a confirmed draft.",
  });
  await sleep(300);
  await streamAssistant(
    ctx,
    "Cementing the order — watch your days pulse in sequence.",
  );

  // Compute a sweep order: nodes sorted by start_time.
  const ordered = ctx.state.nodes
    .slice()
    .sort((a, b) => {
      const sa = new Date(
        getVerticalMeta(a).start_time ?? ctx.state.sample.windowStart,
      ).getTime();
      const sb = new Date(
        getVerticalMeta(b).start_time ?? ctx.state.sample.windowStart,
      ).getTime();
      return sa - sb;
    })
    .map((n) => n.id);

  ctx.onAssembleSweep?.(ordered);
  ctx.dispatch({ type: "ASSEMBLE_PULSE" });
  await sleep(600);
  await streamAssistant(
    ctx,
    `Draft assembled — ${ordered.length} nodes ordered across your 15 days.`,
    14,
  );
}

async function runModifyScenario(ctx: ScenarioContext) {
  const target = ctx.state.nodes.find((n: NodeResponse) => n.type === "hotel");
  if (!target) {
    await streamAssistant(ctx, "No hotel to swap in this sample.");
    return;
  }
  ctx.dispatch({
    type: "APPEND_USER_MESSAGE",
    id: nextId("msg"),
    text: "Can you find me something more private for the Shin-Nakano stay?",
  });
  await sleep(300);
  await streamAssistant(
    ctx,
    `Looking at alternatives to ${target.title}. Swapping in a private residence now.`,
  );
  await sleep(500);
  const updated: AgentNode = {
    id: target.id,
    itinerary_id: target.itinerary_id,
    type: target.type,
    status: target.status,
    title: target.title.replace(/Apartment/i, "Private Residence"),
    source: target.source,
    source_id: target.source_id,
    metadata: {
      ...target.metadata,
      snapshot: {
        ...((target.metadata["snapshot"] as object) ?? {}),
        title: target.title.replace(/Apartment/i, "Private Residence"),
        price: "$1,850 / night",
        location: "Private estate",
      },
    },
  };
  ctx.dispatch({ type: "UPDATE_NODE", node: updated });
}

async function runFreeformScenario(ctx: ScenarioContext, userText: string) {
  const text = userText.toLowerCase();
  if (/propose|suggest|ideas?|add/.test(text)) {
    return runProposeScenario(ctx);
  }
  if (/assemble|connect|draft|confirm/.test(text)) {
    return runAssembleScenario(ctx);
  }
  if (/swap|change|different|another|replace|private/.test(text)) {
    return runModifyScenario(ctx);
  }
  ctx.dispatch({
    type: "APPEND_USER_MESSAGE",
    id: nextId("msg"),
    text: userText,
  });
  await sleep(200);
  await streamAssistant(
    ctx,
    "Try asking me to propose experiences, assemble a draft, or swap a hotel — the demo has scripted responses for those.",
  );
}

export async function runScenario(
  scenario: ScenarioId,
  ctx: ScenarioContext,
  userText?: string,
): Promise<void> {
  switch (scenario) {
    case "propose":
      return runProposeScenario(ctx);
    case "assemble":
      return runAssembleScenario(ctx);
    case "modify":
      return runModifyScenario(ctx);
    case "freeform":
      return runFreeformScenario(ctx, userText ?? "");
  }
}
