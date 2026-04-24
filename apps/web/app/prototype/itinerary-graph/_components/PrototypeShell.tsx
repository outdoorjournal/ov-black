"use client";

import { useCallback, useMemo, useState } from "react";

import { getMeta, type NodeResponse, type SampleTimeline } from "../_lib/types";
import { runScenario } from "../_state/mockStream";
import { useTimelineState } from "../_state/useTimelineState";
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
  return <InnerShell samples={samples} initial={initial} />;
}

function InnerShell({
  samples,
  initial,
}: {
  samples: SampleTimeline[];
  initial: SampleTimeline;
}) {
  const { state, dispatch, loadSample } = useTimelineState(initial);
  const [viewport, setViewport] = useState<Viewport>("desktop");
  const [selectedNode, setSelectedNode] = useState<NodeResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const childrenOfSelected = useMemo(() => {
    if (!selectedNode) return [];
    return state.nodes.filter(
      (n) => n.parent_subgraph_id === selectedNode.id,
    );
  }, [selectedNode, state.nodes]);

  const handleMoveNode = useCallback(
    (id: string, dayIndex: number) => {
      const node = state.nodes.find((n) => n.id === id);
      const currentRank = node ? (getMeta(node).rank as number | undefined) ?? 0 : 0;
      dispatch({ type: "MOVE_NODE", id, dayIndex, rank: currentRank });
    },
    [dispatch, state.nodes],
  );

  const handleAcceptProposal = useCallback(
    (id: string) => {
      dispatch({ type: "ACCEPT_PROPOSAL", id });
      window.setTimeout(
        () => dispatch({ type: "FLASH_NODE", id: null }),
        1600,
      );
    },
    [dispatch],
  );

  const handleDismissProposal = useCallback(
    (id: string) => dispatch({ type: "DISMISS_PROPOSAL", id }),
    [dispatch],
  );

  const runDemo = useCallback(
    async (scenario: "propose" | "assemble" | "modify") => {
      setBusy(true);
      try {
        await runScenario(scenario, { state, dispatch });
      } finally {
        setBusy(false);
      }
    },
    [state, dispatch],
  );

  const handleChatSubmit = useCallback(
    async (text: string) => {
      setBusy(true);
      try {
        await runScenario("freeform", { state, dispatch }, text);
      } finally {
        setBusy(false);
      }
    },
    [state, dispatch],
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
            activeId={state.sample.id}
            onChange={(s) => {
              loadSample(s);
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
                  state={state}
                  mood={state.sample.mood}
                  onCardClick={setSelectedNode}
                  onMoveNode={handleMoveNode}
                  onAcceptProposal={handleAcceptProposal}
                  onDismissProposal={handleDismissProposal}
                />
              </div>
            ) : (
              <div className="px-4 py-5">
                <MobileTimeline
                  state={state}
                  mood={state.sample.mood}
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
            mood={state.sample.mood}
            messages={state.messages}
            pendingProposals={state.pendingProposals}
            onAccept={handleAcceptProposal}
            onDismiss={handleDismissProposal}
            onSubmit={handleChatSubmit}
            disabled={busy}
          />
        </aside>
      </div>

      <NodeDetailSheet
        node={selectedNode}
        mood={state.sample.mood}
        subNodes={childrenOfSelected}
        onClose={() => setSelectedNode(null)}
      />
    </div>
  );
}
