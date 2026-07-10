"use client";

import type {
  EdgeResponse,
  DisplayStatus,
  NodeResponse,
  NodeType,
} from "@ov-black/api-client";

import { buildDayChains } from "./dayChains";

export type FinalItineraryViewProps = {
  status: DisplayStatus;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  title: string | null;
};

const TYPE_ORDER: readonly NodeType[] = [
  "destination",
  "experience",
  "hotel",
  "meal",
  "transit",
  "note",
];

const TYPE_LABEL: Record<NodeType, string> = {
  destination: "Destinations",
  experience: "Experiences",
  hotel: "Stays",
  meal: "Meals",
  transit: "Transit",
  note: "Notes",
  flight: "Flights",
  free_time: "Free time",
  subway: "Subway",
  train: "Trains",
  drive: "Drives",
  walk: "Walks",
  boat: "Boats",
  waiting: "Waiting",
};

function groupNodesByType(
  nodes: NodeResponse[],
): Array<{ type: NodeType; nodes: NodeResponse[] }> {
  const byType = new Map<NodeType, NodeResponse[]>();
  for (const node of nodes) {
    const bucket = byType.get(node.type) ?? [];
    bucket.push(node);
    byType.set(node.type, bucket);
  }
  const ordered: NodeType[] = [...TYPE_ORDER];
  for (const node of nodes) {
    if (!ordered.includes(node.type)) ordered.push(node.type);
  }
  return ordered
    .map((type) => ({ type, nodes: byType.get(type) ?? [] }))
    .filter((g) => g.nodes.length > 0);
}

export function FinalItineraryView({
  status,
  nodes,
  edges,
  title,
}: FinalItineraryViewProps) {
  const chains = buildDayChains(nodes, edges);

  return (
    <main
      data-testid="final-itinerary-view"
      data-itinerary-status={status}
      className="mx-auto flex min-h-screen max-w-2xl flex-col gap-10 px-6 py-12"
    >
      <header className="flex flex-col gap-2">
        <p className="font-sans text-xs uppercase tracking-label text-ink/60">
          Your itinerary
        </p>
        <h1 className="font-serif text-4xl tracking-tight text-ink">
          {title || "Your itinerary"}
        </h1>
      </header>

      <div className="flex flex-col gap-10">
        {chains.map((chain) => (
          <section
            key={chain.dayIndex}
            data-testid="final-itinerary-day"
            data-day-index={chain.dayIndex}
            className="flex flex-col gap-6"
          >
            <h2 className="font-serif text-2xl tracking-tight text-ink">
              {`Day ${chain.dayIndex + 1}`}
            </h2>
            <div className="flex flex-col gap-6">
              {groupNodesByType(chain.nodes).map((group) => (
                <div key={group.type} className="flex flex-col gap-2">
                  <p className="font-sans text-xs uppercase tracking-[0.2em] text-ink/60">
                    {TYPE_LABEL[group.type]}
                  </p>
                  <ul className="flex flex-col gap-2">
                    {group.nodes.map((node) => (
                      <li
                        key={node.id}
                        data-testid="final-itinerary-node"
                        data-node-id={node.id}
                        data-node-type={node.type}
                        data-source={node.source ?? ""}
                        className="flex flex-col gap-1 font-serif text-lg text-ink"
                      >
                        <span>{node.title}</span>
                        {node.source === "ov" ? (
                          <span
                            data-testid="final-itinerary-attribution"
                            className="font-sans text-xs uppercase tracking-[0.2em] text-ink/60"
                          >
                            via Outdoor Voyage
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}
