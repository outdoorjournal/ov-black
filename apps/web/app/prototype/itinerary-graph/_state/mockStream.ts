"use client";

import type { StoreApi } from "zustand";

import type { NodeResponse } from "../_lib/types";
import type { TimelineState } from "./timelineStore";

// Local mirror of the AgentNode shape from agentStream.types. Kept here so
// scenario authors can build full NodeResponse-shaped proposals without
// reaching across modules.
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
  store: StoreApi<TimelineState>;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function nextId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

// Token-by-token delta streaming for a given message.
async function streamAssistant(
  ctx: ScenarioContext,
  text: string,
  perTokenMs = 22,
): Promise<string> {
  const msgId = nextId("msg");
  ctx.store.getState().appendAssistantMessage(msgId);
  const tokens = text.match(/\S+\s*|\s+/g) ?? [text];
  for (const tok of tokens) {
    await sleep(perTokenMs);
    ctx.store.getState().appendDelta(msgId, tok);
  }
  ctx.store.getState().finishAssistant(msgId);
  return msgId;
}

// Propose-cards scenario — streams a reply, then lays down a few proposals.
async function runProposeScenario(ctx: ScenarioContext) {
  const userText = "Can you propose a couple of experiences I might love?";
  ctx.store.getState().appendUserMessage(nextId("msg"), userText);

  await sleep(300);
  await streamAssistant(
    ctx,
    "Looking at your itinerary, here are a few ideas — each lands in its day as a ghost card you can accept or dismiss.",
  );

  const state = ctx.store.getState();
  const day = state.nodes[0]
    ? ((state.nodes[0].metadata["day_index"] as number | undefined) ?? 1)
    : 1;
  const itineraryId = state.sample.itinerary.id;

  const proposals: AgentNode[] = [
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "experience",
      status: "proposed",
      title: "Private sommelier tasting",
      source: "mock",
      source_id: "prop-1",
      metadata: {
        day_index: day,
        rank: 99,
        description: "A two-hour private wine session at a boutique cellar.",
        snapshot: {
          title: "Private sommelier tasting",
          cover_image:
            "https://images.unsplash.com/photo-1474722883778-792e7990302f?q=80&w=1200",
          price: "$180 pp",
          duration_days: 1,
          location: "Local estate",
          activities: ["Tasting flight", "Cellar tour", "Paired bites"],
        },
      },
    },
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "meal",
      status: "proposed",
      title: "Chef's-table dinner",
      source: "mock",
      source_id: "prop-2",
      metadata: {
        day_index: day,
        rank: 100,
        time_of_day: "evening",
        description: "Tasting menu from a rising Michelin one-star chef.",
        snapshot: {
          title: "Chef's-table dinner",
          cover_image:
            "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?q=80&w=1200",
          price: "$240 pp",
          location: "Old town",
          activities: ["7-course menu", "Paired wines"],
        },
      },
    },
    {
      id: nextId("prop"),
      itinerary_id: itineraryId,
      type: "experience",
      status: "proposed",
      title: "Dawn balloon flight",
      source: "mock",
      source_id: "prop-3",
      metadata: {
        day_index: day + 1,
        rank: 1,
        description: "A sunrise launch with champagne on the descent.",
        snapshot: {
          title: "Dawn balloon flight",
          cover_image:
            "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?q=80&w=1200",
          price: "$420 pp",
          duration_days: 1,
          location: "Valley meadow",
          activities: ["Pilot briefing", "60-min flight", "Breakfast"],
        },
      },
    },
  ];

  for (const proposal of proposals) {
    await sleep(480);
    ctx.store.getState().proposeNode(proposal);
  }
}

// Assemble-draft scenario — creates follows edges between adjacent nodes of
// the same day and between days.
async function runAssembleScenario(ctx: ScenarioContext) {
  ctx.store
    .getState()
    .appendUserMessage(nextId("msg"), "Can you connect everything into a draft?");
  await sleep(300);
  await streamAssistant(
    ctx,
    "Connecting your days now — watch the spine stitch together.",
  );

  const state = ctx.store.getState();
  const byDay = new Map<number, NodeResponse[]>();
  for (const n of state.nodes) {
    const day = (n.metadata["day_index"] as number | undefined) ?? 0;
    const arr = byDay.get(day) ?? [];
    arr.push(n);
    byDay.set(day, arr);
  }
  const existingEdges = new Set(
    state.edges
      .filter((e) => e.type === "follows")
      .map((e) => `${e.from_node_id}::${e.to_node_id}`),
  );

  const newEdges: Array<{ fromId: string; toId: string }> = [];
  const sortedDays = Array.from(byDay.keys()).sort((a, b) => a - b);
  for (const day of sortedDays) {
    const inDay = (byDay.get(day) ?? []).slice().sort((a, b) => {
      const ra = (a.metadata["rank"] as number) ?? 0;
      const rb = (b.metadata["rank"] as number) ?? 0;
      return ra - rb;
    });
    for (let i = 0; i + 1 < inDay.length; i++) {
      const from = inDay[i];
      const to = inDay[i + 1];
      if (!from || !to) continue;
      const key = `${from.id}::${to.id}`;
      if (!existingEdges.has(key)) {
        newEdges.push({ fromId: from.id, toId: to.id });
        existingEdges.add(key);
      }
    }
  }

  ctx.store.getState().assembleDraft(newEdges);
  await sleep(600);
  await streamAssistant(
    ctx,
    `Draft assembled — ${newEdges.length} new connection${newEdges.length === 1 ? "" : "s"} drawn across your days.`,
    14,
  );
}

// Modify-node scenario — picks the first hotel and swaps its title/metadata.
async function runModifyScenario(ctx: ScenarioContext) {
  const target = ctx.store.getState().nodes.find((n) => n.type === "hotel");
  if (!target) {
    await streamAssistant(
      ctx,
      "No hotel to swap in this sample — try a different itinerary.",
    );
    return;
  }
  ctx.store
    .getState()
    .appendUserMessage(
      nextId("msg"),
      "Can you find me something more private for our stay?",
    );
  await sleep(300);
  await streamAssistant(
    ctx,
    `Looking at alternatives to ${target.title}. Swapping in a small villa option now.`,
  );
  await sleep(500);
  const updated: AgentNode = {
    id: target.id,
    itinerary_id: target.itinerary_id,
    type: target.type,
    status: target.status,
    title: `${target.title.replace(/ Villa$| Hotel$/, "")} Private Villa`,
    source: target.source,
    source_id: target.source_id,
    metadata: {
      ...target.metadata,
      nights:
        typeof target.metadata["nights"] === "number"
          ? target.metadata["nights"]
          : 2,
      snapshot: {
        ...((target.metadata["snapshot"] as object) ?? {}),
        title: `${target.title.replace(/ Villa$| Hotel$/, "")} Private Villa`,
        price: "$1,850 / night",
        location: "Private estate",
      },
    },
  };
  ctx.store.getState().applyNodeUpdate(updated);
}

// Freeform scenario — matches the user's input against keywords.
async function runFreeformScenario(ctx: ScenarioContext, userText: string) {
  const text = userText.toLowerCase();
  if (/propose|suggest|ideas?/.test(text)) {
    return runProposeScenario(ctx);
  }
  if (/assemble|connect|draft/.test(text)) {
    return runAssembleScenario(ctx);
  }
  if (/swap|change|different|another|replace/.test(text)) {
    return runModifyScenario(ctx);
  }
  ctx.store.getState().appendUserMessage(nextId("msg"), userText);
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
