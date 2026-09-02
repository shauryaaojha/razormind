/**
 * The trace shows the run's internals, and shows them honestly.
 *
 * Two properties are worth a test rather than a look. The first is that every
 * panel is driven by an event: a gate panel that renders eleven green ticks
 * regardless of what the validator said would look identical whether the gates
 * ran or not, and that is precisely the failure a demo cannot catch. The second
 * is the one the whole product rests on — **no figure appears before
 * verification has passed**. A tool finishing mid-run publishes rows that
 * nothing has checked yet, and the trace names them without ever writing one
 * down.
 */

import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import { render, screen, within } from "@testing-library/react";
import type { ProvenanceLevel } from "@shared/api";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { Calculation } from "@/components/Calculation";
import { ExecutionView } from "@/components/ExecutionView";
import { graphOf, validationOf, verificationOf } from "@/lib/pipeline";
import type { TraceEvent } from "@/lib/stream";

function withBlade(element: ReactElement): ReactElement {
  return (
    <BladeProvider themeTokens={bladeTheme} colorScheme="light">
      {element}
    </BladeProvider>
  );
}

const GRAPH = [
  { id: "reconcile", tool: "finance.reconciliation", version: "1.0", depends_on: [], required: true, layer: 0 },
  {
    id: "revenue",
    tool: "finance.revenue_analysis",
    version: "1.0",
    depends_on: ["reconcile"],
    required: false,
    layer: 1,
  },
  {
    id: "refunds",
    tool: "finance.refund_analysis",
    version: "1.0",
    depends_on: ["reconcile"],
    required: false,
    layer: 1,
  },
];

/** A run in flight: the plan exists, reconciliation is done, revenue is running. */
const MIDWAY: TraceEvent[] = [
  { seq: 0, kind: "execution.created", question: "Why did net revenue fall?" },
  { seq: 1, kind: "state.changed", from: "PENDING", to: "PLANNING" },
  {
    seq: 2,
    kind: "intent.parsed",
    intent: "revenue_diagnosis",
    period: { from: "2026-07-01", to: "2026-08-01" },
    comparison_period: { from: "2026-06-01", to: "2026-07-01" },
    confidence_ratio: "0.940000",
    model: "gemini-flash-lite-latest",
    input_tokens: 812,
    output_tokens: 96,
  },
  { seq: 3, kind: "plan.built", intent: "revenue_diagnosis", nodes: GRAPH.map((n) => n.id), graph: GRAPH },
  { seq: 4, kind: "state.changed", from: "PLANNING", to: "VALIDATING" },
  {
    seq: 5,
    kind: "plan.validated",
    approved: true,
    refused: [],
    gates: [
      { code: "INVALID_PLAN_SCHEMA", applied: true, passed: true },
      { code: "UNKNOWN_TOOL", applied: true, passed: true },
      { code: "OVERLAPPING_PERIODS", applied: false, passed: true },
    ],
  },
  { seq: 6, kind: "state.changed", from: "VALIDATING", to: "EXECUTING" },
  { seq: 7, kind: "node.started", node: "reconcile", tool: "finance.reconciliation", layer: 0 },
  {
    seq: 8,
    kind: "node.finished",
    node: "reconcile",
    tool: "finance.reconciliation",
    status: "SUCCEEDED",
    duration_ms: 747,
    layer: 0,
    metrics: ["clean_match_rate_ratio", "ledger_count"],
    evidence_rows: 7,
  },
  { seq: 9, kind: "node.started", node: "revenue", tool: "finance.revenue_analysis", layer: 1 },
];

describe("the trace shows what the run actually did", () => {
  it("draws every planned node before any of them has run", () => {
    // From `plan.built`, not from the tool events: a graph that grows a node at
    // a time shows the reader its shape only once it no longer matters.
    const planned = graphOf(MIDWAY.slice(0, 4));
    expect(planned.map((node) => node.id)).toEqual(["reconcile", "revenue", "refunds"]);
    expect(planned.every((node) => node.status === "pending")).toBe(true);
    expect(planned[1]?.dependsOn).toEqual(["reconcile"]);
  });

  it("reports a gate with nothing to judge as inapplicable, not as passed", () => {
    const validation = validationOf(MIDWAY);
    expect(validation?.approved).toBe(true);
    expect(validation?.applied).toBe(2);
    expect(validation?.gates.find((gate) => gate.code === "OVERLAPPING_PERIODS")?.status).toBe(
      "inapplicable",
    );
  });

  it("writes no figure at all while tools are still running", () => {
    // The rows `reconcile` just published have not been through a single
    // verification layer. The trace says how many there are and what they are
    // called, and does not say what any of them is.
    render(withBlade(<ExecutionView events={MIDWAY} summary={null} />));

    expect(screen.getByTestId("tool-reconcile")).toHaveTextContent("7 evidence rows, 2 metrics");
    expect(screen.queryByText(/₹/)).toBeNull();
    expect(screen.queryByText(/95\.6/)).toBeNull();
    expect(screen.getByTestId("tool-revenue")).toHaveAttribute("data-status", "running");
    expect(screen.getByTestId("tool-refunds")).toHaveAttribute("data-status", "pending");
  });

  it("names the dead dependency that skipped a node", () => {
    const skipped = graphOf([
      ...MIDWAY,
      {
        seq: 10,
        kind: "node.finished",
        node: "refunds",
        tool: "finance.refund_analysis",
        status: "SKIPPED",
        layer: 1,
        code: "DEPENDENCY_UNAVAILABLE",
        blocked_by: ["reconcile"],
      },
    ]);
    const node = skipped.find((held) => held.id === "refunds");
    expect(node?.status).toBe("SKIPPED");
    expect(node?.blockedBy).toEqual(["reconcile"]);
  });
});

describe("the five layers, in order, stopping", () => {
  const blocked: TraceEvent[] = [
    ...MIDWAY,
    { seq: 20, kind: "state.changed", from: "EXECUTING", to: "VERIFYING" },
    { seq: 21, kind: "verification.layer", layer: "TYPE", index: 0, checks: 42, failures: [], passed: true, duration_ms: 3 },
    {
      seq: 22,
      kind: "verification.layer",
      layer: "RANGE",
      index: 1,
      checks: 18,
      failures: ["net_revenue_paise/value_in_range: 4 is outside [0, 1]"],
      passed: false,
      duration_ms: 1,
    },
    { seq: 23, kind: "verification.finished", passed: false, blocked_at: "RANGE", checks: 60 },
    { seq: 24, kind: "state.changed", from: "VERIFYING", to: "BLOCKED" },
  ];

  it("emits only the layers that ran", () => {
    const verification = verificationOf(blocked);
    expect(verification.layers.map((layer) => layer.layer)).toEqual(["TYPE", "RANGE"]);
    expect(verification.finished?.blockedAt).toBe("RANGE");
  });

  it("shows the three layers below the failure as unreached rather than pending", () => {
    render(withBlade(<ExecutionView events={blocked} summary={null} />));
    expect(screen.getByTestId("layer-TYPE")).toHaveAttribute("data-state", "passed");
    expect(screen.getByTestId("layer-RANGE")).toHaveAttribute("data-state", "failed");
    for (const layer of ["CONSISTENCY", "FORMULA", "SOURCE"]) {
      expect(screen.getByTestId(`layer-${layer}`)).toHaveAttribute("data-state", "unreached");
      expect(within(screen.getByTestId(`layer-${layer}`)).getByText("not reached")).toBeInTheDocument();
    }
  });
});

describe("the worked calculation", () => {
  const node: ProvenanceLevel = {
    evidence_id: "t/1.0/net_revenue_change_ratio/2026-07-01_2026-08-01",
    tool_name: "finance.revenue_analysis",
    tool_version: "1.0",
    metric_id: "net_revenue_change_ratio",
    unit: "ratio",
    value: "-0.175956",
    display: "-17.5956%",
    period_from: "2026-07-01",
    period_to: "2026-08-01",
    dimension_value: null,
    support: "FORMULA",
    detail: "(current - prior) / prior",
    rules_applied: [],
    source_record_ids: [],
    operands: [
      {
        name: "current",
        reference: "t/1.0/net_revenue_paise/2026-07-01_2026-08-01",
        value: 39012295,
        display: "₹3,90,122.95",
        node: null,
      },
      {
        name: "prior",
        reference: "t/1.0/net_revenue_paise/2026-06-01_2026-07-01",
        value: 47342482,
        display: "₹4,73,424.82",
        node: null,
      },
    ],
  };

  it("substitutes the operands into the expression the tool declared", () => {
    render(withBlade(<Calculation node={node} />));
    expect(screen.getByText("(current - prior) / prior")).toBeInTheDocument();
    expect(screen.getByText("(39012295 - 47342482) / 47342482")).toBeInTheDocument();
    // The stored value, not a number this page worked out.
    expect(screen.getByText("-0.175956 ratio")).toBeInTheDocument();
  });

  it("does not half-substitute an expression whose operands it does not all have", () => {
    // A formula with a name that has no operand would otherwise render as
    // though some of its inputs were unknown.
    render(
      withBlade(
        <Calculation node={{ ...node, detail: "gross - refunds - fees - chargebacks" }} />,
      ),
    );
    expect(screen.getByText("gross - refunds - fees - chargebacks")).toBeInTheDocument();
    expect(screen.queryByText(/39012295/)).toBeNull();
  });
});
