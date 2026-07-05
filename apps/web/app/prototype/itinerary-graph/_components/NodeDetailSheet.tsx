"use client";

import { AnimatePresence, motion } from "framer-motion";

import {
  type MoodId,
  type NodeResponse,
  STATUS_LABELS,
  getMeta,
} from "@/app/_components/itinerary-graph/model/baseTypes";
import { Card } from "@/app/_components/itinerary-graph/shared/ExpandedCard";

interface NodeDetailSheetProps {
  node: NodeResponse | null;
  mood: MoodId;
  subNodes: NodeResponse[];
  onClose: () => void;
}

export function NodeDetailSheet({
  node,
  mood,
  subNodes,
  onClose,
}: NodeDetailSheetProps) {
  return (
    <AnimatePresence>
      {node ? (
        <motion.div
          key="sheet"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-stretch justify-end bg-ink/30 backdrop-blur-xs"
          onClick={onClose}
        >
          <motion.aside
            initial={{ x: 40 }}
            animate={{ x: 0 }}
            exit={{ x: 40 }}
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
            onClick={(e) => e.stopPropagation()}
            className="flex h-full w-full max-w-[460px] flex-col border-l border-ink/10 bg-paper"
          >
            <header className="flex items-center justify-between border-b border-ink/10 px-5 py-3">
              <div>
                <div className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
                  {node.type} · {STATUS_LABELS[node.status]}
                </div>
                <h2 className="font-serif text-xl text-ink">{node.title}</h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-ink/15 px-2 py-0.5 text-[11px] text-ink/65"
              >
                Close
              </button>
            </header>
            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
              <DetailBody node={node} mood={mood} />
              {subNodes.length > 0 ? (
                <section>
                  <div className="mb-2 text-[10px] uppercase tracking-[0.22em] text-ink/55">
                    Sub-itinerary · {subNodes.length} cards
                  </div>
                  <div className="space-y-2">
                    {subNodes.map((c) => (
                      <Card key={c.id} node={c} mood={mood} compact />
                    ))}
                  </div>
                </section>
              ) : null}
              <RawMeta node={node} />
            </div>
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function DetailBody({ node, mood }: { node: NodeResponse; mood: MoodId }) {
  const meta = getMeta(node);
  const snap = meta.snapshot;
  return (
    <section className="space-y-3">
      {snap?.cover_image ? (
        <div
          className="h-40 w-full rounded-md bg-ink/10"
          style={{
            backgroundImage: `url(${snap.cover_image})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
      ) : null}
      {snap?.location ? (
        <div className="text-[13px] text-ink/75">
          <span className="uppercase tracking-[0.18em] text-[10px] text-ink/50">
            Where
          </span>
          <br />
          {snap.location}
        </div>
      ) : null}
      {snap?.price ? (
        <div className="text-[13px] text-ink/75">
          <span className="uppercase tracking-[0.18em] text-[10px] text-ink/50">
            Price
          </span>
          <br />
          {snap.price}
        </div>
      ) : null}
      {meta.description ? (
        <p className="font-serif text-[15px] leading-relaxed text-ink/85">
          {meta.description}
        </p>
      ) : null}
      {snap?.activities && snap.activities.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-[0.22em] text-ink/50">
            Activities
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink/80">
            {snap.activities.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {/* mood is threaded so future sections can style against it */}
      <span className="sr-only">Mood: {mood}</span>
    </section>
  );
}

function RawMeta({ node }: { node: NodeResponse }) {
  return (
    <details className="rounded-md border border-ink/10 bg-ink/2 px-3 py-2 text-[11px]">
      <summary className="cursor-pointer uppercase tracking-[0.22em] text-ink/55">
        Raw metadata
      </summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[10px] leading-relaxed text-ink/70">
        {JSON.stringify(
          {
            id: node.id,
            type: node.type,
            status: node.status,
            source: node.source,
            source_id: node.source_id,
            parent_subgraph_id: node.parent_subgraph_id,
            metadata: node.metadata,
          },
          null,
          2,
        )}
      </pre>
    </details>
  );
}
