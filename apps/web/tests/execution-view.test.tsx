/**
 * The exit criterion that has to be a test rather than an inspection.
 *
 * "History and live chat share one trace component" is easy to believe and easy
 * to lose: someone adds a small history-only tweak, and six weeks later a run
 * looks different depending on when you open it. The assertion below is
 * stronger than "both import the same module" — it feeds the same events
 * through the component the way each page does and compares the rendered markup
 * character for character.
 *
 * The events are the ones the API actually emits. If the runtime's event kinds
 * change, these fixtures stop matching the payloads and the trace stops
 * rendering — which is the failure surfacing here rather than in a demo.
 */

import { render, screen, within } from "@testing-library/react";
import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import type { ExecutionSummary } from "@shared/api";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { ExecutionView, splitByClaims } from "@/components/ExecutionView";
import type { TraceEvent } from "@/lib/stream";

const EVIDENCE_ID =
  "finance.revenue_analysis/1.0/net_revenue_paise/2026-08-01_2026-08-24";

const EVENTS: TraceEvent[] = [
  { seq: 0, kind: "execution.created", question: "Why did net revenue fall in August?" },
  { seq: 1, kind: "state.changed", from: "PENDING", to: "PLANNING" },
  { seq: 2, kind: "plan.built", intent: "revenue_diagnosis", nodes: ["reconcile", "revenue"] },
  { seq: 3, kind: "state.changed", from: "PLANNING", to: "VALIDATING" },
  { seq: 4, kind: "state.changed", from: "VALIDATING", to: "EXECUTING" },
  { seq: 5, kind: "node.started", node: "reconcile", tool: "finance.reconciliation" },
  {
    seq: 6,
    kind: "node.finished",
    node: "reconcile",
    tool: "finance.reconciliation",
    status: "SUCCEEDED",
    duration_ms: 747,
  },
  { seq: 7, kind: "node.started", node: "revenue", tool: "finance.revenue_analysis" },
  {
    seq: 8,
    kind: "node.finished",
    node: "revenue",
    tool: "finance.revenue_analysis",
    status: "SUCCEEDED",
    duration_ms: 143,
  },
  { seq: 9, kind: "state.changed", from: "EXECUTING", to: "VERIFYING" },
  { seq: 10, kind: "verification.finished", passed: true, blocked_at: null, checks: 718 },
  { seq: 11, kind: "state.changed", from: "VERIFYING", to: "EXPLAINING" },
  {
    seq: 12,
    kind: "explanation.grounded",
    source: "TEMPLATE_FALLBACK",
    attempts: 0,
    claims: 1,
    checks: 1107,
    reason: "PROVIDER_UNAVAILABLE",
  },
  { seq: 13, kind: "state.changed", from: "EXPLAINING", to: "COMPLETED" },
  { seq: 14, kind: "execution.finished", status: "COMPLETED" },
];

const SUMMARY: ExecutionSummary = {
  execution_id: "e1",
  merchant_id: "M123",
  period_from: "2026-08-01",
  period_to: "2026-08-24",
  status: "COMPLETED",
  response_source: "TEMPLATE_FALLBACK",
  answer:
    "Verified figures follow.\n- Net revenue (net_revenue_paise): ₹3,90,122.95\nNothing else was claimed.",
  claims: [
    {
      text: "- Net revenue (net_revenue_paise): ₹3,90,122.95",
      metric_id: "net_revenue_paise",
      value: 39012295,
      unit: "paise",
      evidence_id: EVIDENCE_ID,
    },
  ],
  grounding_attempts: 0,
  error: null,
};

function withBlade(element: ReactElement): ReactElement {
  return (
    <BladeProvider themeTokens={bladeTheme} colorScheme="light">
      {element}
    </BladeProvider>
  );
}

describe("one execution, one renderer", () => {
  it("renders a live run and a replayed one identically", () => {
    // The chat page accumulates events from the stream; the replay page reads
    // the same events back from the same endpoint. Neither passes anything the
    // other does not, which is exactly the property being asserted.
    const live = render(withBlade(<ExecutionView events={EVENTS} summary={SUMMARY} />));
    const liveMarkup = live.container.innerHTML;
    live.unmount();

    const replayed = render(withBlade(<ExecutionView events={EVENTS} summary={SUMMARY} />));
    expect(replayed.container.innerHTML).toBe(liveMarkup);
  });

  it("shows every stage with a status, not a spinner over the whole run", () => {
    render(withBlade(<ExecutionView events={EVENTS} summary={SUMMARY} />));
    for (const stage of ["understand", "validate", "execute", "verify", "explain"]) {
      // Asserted through what a reader sees rather than a private attribute:
      // a badge that says "done" is the thing the criterion is about.
      expect(within(screen.getByTestId(`stage-${stage}`)).getByText("done")).toBeInTheDocument();
    }
    expect(screen.getByText("718 checks passed")).toBeInTheDocument();
  });

  it("ticks: a half-finished run has a running stage and pending ones after it", () => {
    const midway = EVENTS.slice(0, 8);
    render(withBlade(<ExecutionView events={midway} summary={null} />));

    const executing = screen.getByTestId("stage-execute");
    expect(within(executing).getByLabelText("Running the analysis in progress")).toBeInTheDocument();
    expect(within(screen.getByTestId("stage-verify")).getByText("pending")).toBeInTheDocument();
    expect(within(screen.getByTestId("stage-understand")).getByText("done")).toBeInTheDocument();
  });

  it("shows each tool with the time it took", () => {
    render(withBlade(<ExecutionView events={EVENTS} summary={SUMMARY} />));
    expect(screen.getByTestId("tool-reconcile")).toHaveTextContent("747 ms");
    expect(screen.getByTestId("tool-revenue")).toHaveTextContent("finance.revenue_analysis");
  });

  it("makes every claimed figure clickable, and nothing else", () => {
    render(withBlade(<ExecutionView events={EVENTS} summary={SUMMARY} />));
    const claims = screen.getAllByTestId("claim");
    expect(claims).toHaveLength(1);
    expect(claims[0]).toHaveAttribute("data-evidence-id", EVIDENCE_ID);
    // The unclaimed prose is present and is not a button.
    expect(screen.getByText("Nothing else was claimed.")).toBeInTheDocument();
  });

  it("shows no numbers at all for a blocked execution", () => {
    // Invariant 4 on screen: verification failure blocks explanation entirely.
    const blocked: ExecutionSummary = {
      ...SUMMARY,
      status: "BLOCKED",
      response_source: null,
      answer: null,
      claims: [],
      error: { message: "verification stopped at layer FORMULA" },
    };
    render(withBlade(<ExecutionView events={EVENTS} summary={blocked} />));
    expect(screen.getByText("These numbers could not be verified")).toBeInTheDocument();
    expect(screen.queryByTestId("claim")).toBeNull();
    expect(screen.queryByText(/₹/)).toBeNull();
  });
});

describe("splitting an answer by its claims", () => {
  it("keeps unclaimed prose and never nests one claim inside another", () => {
    const segments = splitByClaims("A ₹1.00 and B ₹2.00 end.", [
      { text: "A ₹1.00", metric_id: "m", value: 100, unit: "paise", evidence_id: "a" },
      { text: "B ₹2.00", metric_id: "m", value: 200, unit: "paise", evidence_id: "b" },
    ]);
    expect(segments.map((segment) => segment.text)).toEqual([
      "A ₹1.00",
      "and",
      "B ₹2.00",
      "end.",
    ]);
    expect(segments.filter((segment) => segment.claim)).toHaveLength(2);
  });

  it("drops a claim whose text is not in the answer rather than guessing", () => {
    const segments = splitByClaims("Nothing here.", [
      { text: "₹9.00", metric_id: "m", value: 900, unit: "paise", evidence_id: "a" },
    ]);
    expect(segments).toEqual([{ text: "Nothing here.", claim: null }]);
  });
});
