"use client";

import { useCallback, useMemo, useState } from "react";

import { getMeta, type NodeResponse, type SampleTimeline } from "@/app/_components/itinerary-graph/model/baseTypes";
import { runScenario } from "../_state/mockStream";
import { timelineStore } from "../_state/timelineStore";
import { AIDemoController } from "./AIDemoController";
import { ConversationPanel } from "./ConversationPanel";
import { MobileTimeline } from "./MobileTimeline";
import { NodeDetailSheet } from "./NodeDetailSheet";
import { TimelineCanvas } from "./TimelineCanvas";
import { TimelineSwitcher } from "./TimelineSwitcher";
import { type Viewport, ViewportToggle } from "./ViewportToggle";

interface PrototypeShellProps {
  samples: SampleTimeline[];
}

export function PrototypeShell({ samples }: PrototypeShellProps) {
  const initial = samples[0];
  if (!initial) {
    return <div className="p-6">No sample timelines available.</div>;
  }
  return (
    <timelineStore.Provider initial={{ sample: initial }}>
      <InnerShell samples={samples} />
    </timelineStore.Provider>
  );
}

function InnerShell({ samples }: { samples: SampleTimeline[] }) {
  const sample = timelineStore.useStore((s) => s.sample);
  const nodes = timelineStore.useStore((s) => s.nodes);
  const messages = timelineStore.useStore((s) => s.messages);
  const pendingProposals = timelineStore.useStore((s) => s.pendingProposals);
  const storeApi = timelineStore.useStoreApi();

  const [viewport, setViewport] = useState<Viewport>("desktop");
  const [selectedNode, setSelectedNode] = useState<NodeResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const childrenOfSelected = useMemo(() => {
    if (!selectedNode) return [];
    return nodes.filter((n) => n.parent_subgraph_id === selectedNode.id);
  }, [selectedNode, nodes]);

  const handleMoveNode = useCallback(
    (id: string, dayIndex: number) => {
      const state = storeApi.getState();
      const node = state.nodes.find((n) => n.id === id);
      const currentRank = node
        ? ((getMeta(node).rank as number | undefined) ?? 0)
        : 0;
      state.moveNode(id, dayIndex, currentRank);
    },
    [storeApi],
  );

  const handleAcceptProposal = useCallback(
    (id: string) => {
      storeApi.getState().acceptProposal(id);
      window.setTimeout(
        () => storeApi.getState().flashNode(null),
        1600,
      );
    },
    [storeApi],
  );

  const handleDismissProposal = useCallback(
    (id: string) => storeApi.getState().dismissProposal(id),
    [storeApi],
  );

  const runDemo = useCallback(
    async (scenario: "propose" | "assemble" | "modify") => {
      setBusy(true);
      try {
        await runScenario(scenario, { store: storeApi });
      } finally {
        setBusy(false);
      }
    },
    [storeApi],
  );

  const handleChatSubmit = useCallback(
    async (text: string) => {
      setBusy(true);
      try {
        await runScenario("freeform", { store: storeApi }, text);
      } finally {
        setBusy(false);
      }
    },
    [storeApi],
  );

  return (
    <div className="flex h-screen flex-col bg-paper">
      <header className="flex flex-wrap items-center gap-3 border-b border-ink/10 px-5 py-3">
        <div className="mr-2">
          <div className="text-[10px] uppercase tracking-[0.28em] text-ink/55">
            Prototype
          </div>
          <div className="font-serif text-lg text-ink">Itinerary graph</div>
        </div>
        <div className="flex-1">
          <TimelineSwitcher
            samples={samples}
            activeId={sample.id}
            onChange={(s) => {
              storeApi.getState().loadSample(s);
              setSelectedNode(null);
            }}
          />
        </div>
        <ViewportToggle viewport={viewport} onChange={setViewport} />
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-3 border-b border-ink/10 bg-paper px-5 py-2">
            <AIDemoController onRun={runDemo} disabled={busy} />
          </div>
          <div className="flex-1 overflow-auto bg-[linear-gradient(180deg,#f7f4ee_0%,#f1ece2_100%)]">
            {viewport === "desktop" ? (
              <div className="px-5 py-5">
                <TimelineCanvas
                  mood={sample.mood}
                  onCardClick={setSelectedNode}
                  onMoveNode={handleMoveNode}
                  onAcceptProposal={handleAcceptProposal}
                  onDismissProposal={handleDismissProposal}
                />
              </div>
            ) : (
              <div className="px-4 py-5">
                <MobileTimeline
                  mood={sample.mood}
                  onCardClick={setSelectedNode}
                  onMoveNode={handleMoveNode}
                  onAcceptProposal={handleAcceptProposal}
                  onDismissProposal={handleDismissProposal}
                />
              </div>
            )}
          </div>
        </main>
        <aside className="hidden w-[360px] shrink-0 md:block">
          <ConversationPanel
            mood={sample.mood}
            messages={messages}
            pendingProposals={pendingProposals}
            onAccept={handleAcceptProposal}
            onDismiss={handleDismissProposal}
            onSubmit={handleChatSubmit}
            disabled={busy}
          />
        </aside>
      </div>

      <NodeDetailSheet
        node={selectedNode}
        mood={sample.mood}
        subNodes={childrenOfSelected}
        onClose={() => setSelectedNode(null)}
      />
    </div>
  );
}
