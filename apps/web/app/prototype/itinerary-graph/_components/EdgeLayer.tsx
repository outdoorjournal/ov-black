"use client";

import { motion } from "framer-motion";

import { EDGE_TYPE_COLORS, type EdgeResponse } from "@/app/_components/itinerary-graph/model/baseTypes";
import { type LayoutResult, bezierPath, edgeAnchor } from "../_state/layout";

interface EdgeLayerProps {
  edges: EdgeResponse[];
  layout: LayoutResult;
  pulse: number;
}

export function EdgeLayer({ edges, layout, pulse }: EdgeLayerProps) {
  return (
    <svg
      className="pointer-events-none absolute inset-0"
      width={layout.width}
      height={layout.height}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      aria-hidden
    >
      <defs>
        <marker
          id="arrowhead"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(10,10,10,0.45)" />
        </marker>
        <marker
          id="diamond"
          viewBox="0 0 10 10"
          refX="5"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 5 0 L 10 5 L 5 10 L 0 5 z" fill="#8b2a1d" />
        </marker>
      </defs>

      {edges.map((edge) => {
        const from = layout.positions.get(edge.from_node_id);
        const to = layout.positions.get(edge.to_node_id);
        if (!from || !to) return null;

        if (edge.type === "grouped_with") {
          const minX = Math.min(from.x, to.x);
          const maxX = Math.max(from.x + from.w, to.x + to.w);
          const minY = Math.min(from.y, to.y);
          const maxY = Math.max(from.y + from.h, to.y + to.h);
          return (
            <rect
              key={edge.id}
              x={minX - 6}
              y={minY - 6}
              width={maxX - minX + 12}
              height={maxY - minY + 12}
              rx={12}
              fill={EDGE_TYPE_COLORS.grouped_with}
              opacity={0.5}
            />
          );
        }

        const { fromPoint, toPoint } = edgeAnchor(from, to);
        const d = bezierPath(fromPoint, toPoint);
        const color = EDGE_TYPE_COLORS[edge.type];
        const strokeWidth = edge.type === "follows" ? 1.5 : 1;
        const isAssembled =
          pulse > 0 && edge.id.startsWith("e-assembled-");

        const pathProps: Record<string, unknown> = {
          d,
          fill: "none",
          stroke: color,
          strokeWidth,
        };
        if (edge.type === "alternative_to") pathProps["strokeDasharray"] = "4 4";
        if (edge.type === "follows") pathProps["markerEnd"] = "url(#arrowhead)";
        if (edge.type === "requires") pathProps["markerEnd"] = "url(#diamond)";
        if (isAssembled) {
          pathProps["initial"] = { pathLength: 0, opacity: 0.2 };
          pathProps["animate"] = { pathLength: 1, opacity: 1 };
          pathProps["transition"] = { duration: 0.6, ease: "easeOut" };
        }

        return (
          <g key={edge.id}>
            <motion.path {...pathProps} />
            {edge.type === "alternative_to"
              ? (() => {
                  const midX = (fromPoint[0] + toPoint[0]) / 2;
                  const midY = (fromPoint[1] + toPoint[1]) / 2;
                  return (
                    <text
                      x={midX}
                      y={midY - 4}
                      textAnchor="middle"
                      className="font-serif italic"
                      fontSize="11"
                      fill="rgba(10,10,10,0.55)"
                    >
                      or
                    </text>
                  );
                })()
              : null}
          </g>
        );
      })}
    </svg>
  );
}
