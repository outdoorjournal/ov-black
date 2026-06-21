import type {
  EdgeResponse,
  EdgeType,
  ItineraryResponse,
  NodeMeta,
  NodeResponse,
  NodeStatus,
  NodeType,
} from "@/app/_components/itinerary-graph/model/baseTypes";

// Static pseudo-UUIDs so HMR + SSR stay stable across reloads. Real uuids
// aren't needed for a fixture; deterministic strings are easier to reason
// about in tests and logs.
let _nodeCounter = 0;
let _edgeCounter = 0;

export function resetCounters(): void {
  _nodeCounter = 0;
  _edgeCounter = 0;
}

export function nodeId(prefix: string): string {
  _nodeCounter += 1;
  return `n-${prefix}-${_nodeCounter}`;
}

export function edgeId(): string {
  _edgeCounter += 1;
  return `e-${_edgeCounter}`;
}

export interface NodeInput {
  id?: string;
  type: NodeType;
  status?: NodeStatus;
  title: string;
  source?: string;
  source_id?: string;
  parent_subgraph_id?: string;
  meta: NodeMeta;
}

export function makeNode(
  itineraryId: string,
  input: NodeInput,
): NodeResponse {
  return {
    id: input.id ?? nodeId(input.type),
    itinerary_id: itineraryId,
    parent_subgraph_id: input.parent_subgraph_id ?? null,
    type: input.type,
    status: input.status ?? "approved",
    title: input.title,
    source: input.source ?? "mock",
    source_id: input.source_id ?? null,
    metadata: input.meta as Record<string, unknown>,
  };
}

export function makeEdge(
  itineraryId: string,
  fromId: string,
  toId: string,
  type: EdgeType,
): EdgeResponse {
  return {
    id: edgeId(),
    itinerary_id: itineraryId,
    from_node_id: fromId,
    to_node_id: toId,
    type,
    metadata: {},
  };
}

export function makeItinerary(id: string, title: string): ItineraryResponse {
  return {
    id,
    title,
    client_id: null,
    created_by: null,
    status: "draft",
  };
}
