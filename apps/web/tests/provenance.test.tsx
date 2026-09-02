/**
 * The drawer is one recursive renderer with no knowledge of any metric.
 *
 * The test builds a chain by hand rather than fetching one, because what is
 * being asserted is the recursion: a node with operands renders its operands,
 * and a fold renders the records it cites. A component that happened to handle
 * the revenue bridge and nothing else would pass a fetch-based test against the
 * revenue bridge.
 */

import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import { render, screen, within } from "@testing-library/react";
import type { ProvenanceLevel } from "@shared/api";
import { describe, expect, it } from "vitest";

import { Level } from "@/components/ProvenanceDrawer";

function fold(metric: string, display: string, records: string[]): ProvenanceLevel {
  return {
    evidence_id: `t/1.0/${metric}/2026-08-01_2026-08-24`,
    tool_name: "finance.revenue_analysis",
    tool_version: "1.0",
    metric_id: metric,
    unit: "paise",
    value: 1,
    display,
    period_from: "2026-08-01",
    period_to: "2026-08-24",
    dimension_value: null,
    support: "AGGREGATION",
    detail: "the captures in the window",
    rules_applied: [],
    operands: [],
    source_record_ids: records,
  };
}

const CHAIN: ProvenanceLevel = {
  evidence_id: "t/1.0/net_revenue_paise/2026-08-01_2026-08-24",
  tool_name: "finance.revenue_analysis",
  tool_version: "1.0",
  metric_id: "net_revenue_paise",
  unit: "paise",
  value: 39012295,
  display: "₹3,90,122.95",
  period_from: "2026-08-01",
  period_to: "2026-08-24",
  dimension_value: null,
  support: "FORMULA",
  detail: "gross - refunds - fees - chargebacks",
  rules_applied: [],
  source_record_ids: [],
  operands: [
    {
      name: "gross",
      reference: "t/1.0/gross_payments_paise/2026-08-01_2026-08-24",
      value: 40626000,
      display: "₹4,06,260.00",
      node: fold("gross_payments_paise", "₹4,06,260.00", ["TXN_1", "TXN_2", "TXN_3"]),
    },
    {
      name: "hundred",
      reference: "literal",
      value: 100,
      display: "100",
      node: null,
    },
  ],
};

function withBlade(node: ProvenanceLevel) {
  return render(
    <BladeProvider themeTokens={bladeTheme} colorScheme="light">
      <Level node={node} depth={0} />
    </BladeProvider>,
  );
}

describe("the provenance drawer", () => {
  it("walks from a derived metric down to the records beneath it", () => {
    withBlade(CHAIN);
    const [outer, inner] = screen.getAllByTestId("provenance-node");
    expect(screen.getAllByTestId("provenance-node")).toHaveLength(2);

    // Containment, not an index: the operand's node is rendered *inside* the
    // node that cites it, which is what "recursive" means here.
    expect(outer).toContainElement(inner ?? null);
    expect(within(outer!).getByText("net_revenue_paise")).toBeInTheDocument();
    expect(within(inner!).getByText("gross_payments_paise")).toBeInTheDocument();
    expect(within(inner!).getByText("folds 3 records")).toBeInTheDocument();
  });

  it("writes every figure the way the server rendered it", () => {
    // No money formatting exists in the web app at all (D-54). If a display
    // string were being rebuilt here, this is where the two spellings would
    // diverge.
    withBlade(CHAIN);
    expect(screen.getByText("₹3,90,122.95")).toBeInTheDocument();
    expect(screen.getByText("gross = ₹4,06,260.00")).toBeInTheDocument();
  });

  it("renders a literal operand without pretending it has a chain", () => {
    withBlade(CHAIN);
    expect(screen.getByText("hundred = 100")).toBeInTheDocument();
    expect(screen.getAllByTestId("provenance-node")).toHaveLength(2);
  });

  it("shows the tool and window on every level, because they differ (D-18)", () => {
    withBlade(CHAIN);
    expect(
      screen.getAllByText("finance.revenue_analysis · [2026-08-01, 2026-08-24)"),
    ).toHaveLength(2);
  });
});
