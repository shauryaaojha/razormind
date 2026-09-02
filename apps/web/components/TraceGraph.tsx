"use client";

/**
 * The plan, drawn as the graph it is, running.
 *
 * The execution trace used to be a flat list of tool rows, which is a true but
 * uninteresting description of a DAG: it cannot show that four analyses start
 * on the same event and run at once, and it cannot show that a skipped node was
 * skipped *by an edge* rather than by bad luck. Both are the reason the plan is
 * a graph in the first place, so the graph is what is drawn.
 *
 * Three things are worth knowing about what is on screen:
 *
 * * **Every node exists before it runs.** They come from `plan.built`, so the
 *   shape is visible from the moment the plan is built rather than assembling
 *   itself one node at a time, which would show the reader the structure only
 *   once it no longer mattered.
 * * **A finished node names its metrics and never shows their values.** At this
 *   point in the run nothing has been verified. Numbers appear after the five
 *   layers have passed, and not one moment earlier.
 * * **Layout is computed, not measured.** Positions are arithmetic on the tier
 *   and row index, with no refs and no `useLayoutEffect`, so the same events
 *   produce the same markup whether the run is live or replayed from history.
 */

import type { CSSProperties } from "react";

import { useTheme } from "@/app/providers";
import { Mono, SectionLabel } from "@/components/ui";
import type { GraphNode, NodeStatus } from "@/lib/pipeline";
import { tiersOf } from "@/lib/pipeline";
import { numeric, radius, space, transition, type Palette } from "@/lib/theme";

const NODE_W = 232;
const NODE_H = 122;
const COL_GAP = 84;
const ROW_GAP = 20;

export function TraceGraph({ nodes }: { nodes: GraphNode[] }) {
  const { t } = useTheme();
  if (nodes.length === 0) return null;

  const tiers = tiersOf(nodes);
  const rows = Math.max(...tiers.map((tier) => tier.length));
  const width = tiers.length * NODE_W + (tiers.length - 1) * COL_GAP;
  const height = rows * NODE_H + (rows - 1) * ROW_GAP;

  /** Where a node's box sits. Centred in its column against the tallest one. */
  const place = (node: GraphNode): { x: number; y: number } => {
    const column = tiers.findIndex((tier) => tier.some((held) => held.id === node.id));
    const tier = tiers[column] ?? [];
    const row = tier.findIndex((held) => held.id === node.id);
    const span = tier.length * NODE_H + (tier.length - 1) * ROW_GAP;
    return {
      x: column * (NODE_W + COL_GAP),
      y: (height - span) / 2 + row * (NODE_H + ROW_GAP),
    };
  };

  const at = new Map(nodes.map((node) => [node.id, place(node)]));
  const byId = new Map(nodes.map((node) => [node.id, node]));

  const edges = nodes.flatMap((node) =>
    node.dependsOn
      .filter((parent) => at.has(parent))
      .map((parent) => ({ from: byId.get(parent) as GraphNode, to: node })),
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space(3) }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <SectionLabel>
          The plan — {nodes.length} {nodes.length === 1 ? "tool" : "tools"} in {tiers.length}{" "}
          {tiers.length === 1 ? "tier" : "tiers"}
        </SectionLabel>
        <span style={{ fontSize: "11.5px", color: t.textFaint }}>
          Everything in a tier runs at once
        </span>
      </div>

      {/* Wide graphs scroll inside their own box; the page never does. */}
      <div style={{ overflowX: "auto", paddingBottom: space(1) }}>
        <div style={{ position: "relative", width, height, minWidth: width }}>
          <svg
            width={width}
            height={height}
            aria-hidden
            style={{ position: "absolute", inset: 0, overflow: "visible" }}
          >
            {edges.map(({ from, to }) => {
              const start = at.get(from.id);
              const end = at.get(to.id);
              if (!start || !end) return null;
              const x1 = start.x + NODE_W;
              const y1 = start.y + NODE_H / 2;
              const x2 = end.x;
              const y2 = end.y + NODE_H / 2;
              const bend = COL_GAP * 0.55;
              const edge = edgeStyle(t, from, to);
              return (
                <path
                  key={`${from.id}->${to.id}`}
                  className={edge.moving ? "rm-flow" : undefined}
                  d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke={edge.stroke}
                  strokeWidth={1.5}
                  strokeDasharray={edge.dash}
                  style={edge.moving ? { animation: "rm-flow 700ms linear infinite" } : undefined}
                />
              );
            })}
          </svg>

          {nodes.map((node) => {
            const position = at.get(node.id);
            if (!position) return null;
            return (
              <NodeCard
                key={node.id}
                node={node}
                style={{
                  position: "absolute",
                  left: position.x,
                  top: position.y,
                  width: NODE_W,
                  height: NODE_H,
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * One tool call.
 *
 * Keeps `tool-<node>` as its test id: this card replaced the row that used to
 * carry it, and the criterion it is pinned by -- that a trace names each tool
 * and the time it took -- is about the information, not the shape.
 */
function NodeCard({ node, style }: { node: GraphNode; style: CSSProperties }) {
  const { t } = useTheme();
  const colour = statusColour(t, node.status);
  const running = node.status === "running";

  return (
    <div
      data-testid={`tool-${node.id}`}
      data-status={node.status}
      className={running ? "rm-pulse" : undefined}
      style={{
        ...style,
        display: "flex",
        flexDirection: "column",
        gap: space(1.5),
        padding: space(3),
        borderRadius: radius.md,
        backgroundColor: node.status === "pending" ? "transparent" : t.surface,
        border: `1px solid ${node.status === "pending" ? t.border : colour.edge}`,
        borderStyle: node.status === "pending" ? "dashed" : "solid",
        opacity: node.status === "SKIPPED" ? 0.72 : 1,
        boxSizing: "border-box",
        overflow: "hidden",
        transition: `border-color ${transition.base}, background-color ${transition.base}`,
        ...(running
          ? ({
              ["--rm-pulse" as string]: colour.soft,
              animation: "rm-pulse 1.6s ease-in-out infinite",
            } as CSSProperties)
          : {}),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: space(2) }}>
        <span
          aria-hidden
          style={{
            width: "7px",
            height: "7px",
            flexShrink: 0,
            borderRadius: radius.pill,
            backgroundColor: node.status === "pending" ? "transparent" : colour.fg,
            border: `1.5px solid ${colour.fg}`,
          }}
        />
        <span
          style={{
            fontSize: "13px",
            fontWeight: 650,
            color: node.status === "pending" ? t.textFaint : t.text,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {node.id}
        </span>
        {node.required ? (
          <span
            title="The run cannot continue without this one"
            style={{ fontSize: "10px", fontWeight: 700, color: t.warning, letterSpacing: "0.04em" }}
          >
            REQUIRED
          </span>
        ) : null}
      </div>

      <span
        style={{
          fontSize: "11.5px",
          color: t.textMuted,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {node.tool}
        {node.version ? <span style={{ color: t.textFaint }}> v{node.version}</span> : null}
      </span>

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: space(1) }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: space(2),
          }}
        >
          <span style={{ fontSize: "10.5px", fontWeight: 700, color: colour.fg }}>
            {node.status === "running" ? "RUNNING" : node.status.toUpperCase()}
          </span>
          <span style={{ ...numeric, fontSize: "11px", color: t.textFaint }}>
            {node.durationMs === undefined ? "" : `${node.durationMs} ms`}
          </span>
        </div>

        {/* Names, never values. Nothing here has been through the layers yet. */}
        {node.status === "SUCCEEDED" && node.evidenceRows !== undefined ? (
          <span
            className="rm-rise"
            title={node.metrics.join(", ")}
            style={{
              ...numeric,
              fontSize: "11px",
              color: t.textMuted,
              animation: "rm-rise 240ms ease-out",
            }}
          >
            {node.evidenceRows} evidence {node.evidenceRows === 1 ? "row" : "rows"},{" "}
            {node.metrics.length} {node.metrics.length === 1 ? "metric" : "metrics"}
          </span>
        ) : null}

        {node.status === "SKIPPED" && node.blockedBy.length > 0 ? (
          <span style={{ fontSize: "10.5px", color: t.textFaint, lineHeight: 1.4 }}>
            blocked by {node.blockedBy.join(", ")}
          </span>
        ) : null}

        {node.status === "FAILED" && node.code ? (
          <Mono>{node.code}</Mono>
        ) : null}

        {node.status === "running" ? (
          <span
            aria-hidden
            style={{
              display: "block",
              height: "2px",
              borderRadius: radius.pill,
              backgroundColor: t.sunken,
              overflow: "hidden",
            }}
          >
            <span
              className="rm-sweep"
              style={{
                display: "block",
                width: "33%",
                height: "100%",
                borderRadius: radius.pill,
                backgroundColor: colour.fg,
                animation: "rm-sweep 1.1s ease-in-out infinite",
              }}
            />
          </span>
        ) : null}
      </div>
    </div>
  );
}

function statusColour(t: Palette, status: NodeStatus): { fg: string; edge: string; soft: string } {
  switch (status) {
    case "SUCCEEDED":
      return { fg: t.positive, edge: t.border, soft: t.positiveSoft };
    case "FAILED":
      return { fg: t.negative, edge: t.negative, soft: t.negativeSoft };
    case "SKIPPED":
      return { fg: t.textFaint, edge: t.border, soft: t.surfaceHover };
    case "running":
      return { fg: t.accent, edge: t.accentBorder, soft: t.accentSoft };
    case "pending":
      return { fg: t.borderStrong, edge: t.border, soft: t.surfaceHover };
  }
}

/**
 * What an edge looks like given what happened at both ends.
 *
 * An edge carries the reconciliation run id, so its appearance is the honest
 * summary of one fact: whether the value it exists to carry ever arrived.
 */
function edgeStyle(
  t: Palette,
  from: GraphNode,
  to: GraphNode,
): { stroke: string; dash?: string; moving: boolean } {
  if (to.status === "SKIPPED") return { stroke: t.negative, dash: "3 4", moving: false };
  if (to.status === "running") return { stroke: t.accent, dash: "5 4", moving: true };
  if (from.status === "SUCCEEDED" && to.status === "SUCCEEDED") {
    return { stroke: t.positive, moving: false };
  }
  if (from.status === "running") return { stroke: t.border, dash: "5 4", moving: true };
  return { stroke: t.border, dash: "3 4", moving: false };
}
