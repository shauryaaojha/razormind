"use client";

/**
 * The scorecard for the most recent completed investigation.
 *
 * Every figure is an evidence row published by that run, and every figure
 * opens. The page held hardcoded literals before — figures that looked exactly
 * like the verified ones and were typed by hand, in a product whose entire
 * claim is that a number on screen can be walked down to the records it came
 * from (D-56). A tile with no evidence id is not rendered rather than rendered
 * inert, because the only honest thing to show for a metric this run did not
 * publish is nothing.
 */

import { Alert, Spinner } from "@razorpay/blade/components";
import type { EvidenceLine } from "@shared/api";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useTheme } from "@/app/providers";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { RevenueWaterfall } from "@/components/RevenueWaterfall";
import { Shell } from "@/components/Shell";
import { EmptyState, Grid, MetricTile, Panel, PanelHeader, Row, Stack } from "@/components/ui";
import { listEvidence, listExecutions } from "@/lib/api";
import { numeric, radius, space, type Tone } from "@/lib/theme";

const REVENUE = "finance.revenue_analysis";
const FAILURES = "payments.failure_analysis";
const RECONCILIATION = "finance.reconciliation";

/** The headline metrics, in reading order. */
const SCORECARD: { tool: string; metric: string; label: string; tone?: Tone }[] = [
  { tool: REVENUE, metric: "net_revenue_paise", label: "Net revenue" },
  { tool: REVENUE, metric: "net_revenue_change_ratio", label: "Change on prior window" },
  { tool: REVENUE, metric: "gross_payments_paise", label: "Gross payments" },
  { tool: FAILURES, metric: "success_rate_ratio", label: "Payment success rate" },
  { tool: FAILURES, metric: "success_rate_pp_change", label: "Success rate change" },
  { tool: RECONCILIATION, metric: "clean_match_rate_ratio", label: "Clean match rate" },
];

type Loaded = { executionId: string; metrics: EvidenceLine[] };

export default function DashboardPage() {
  const { t } = useTheme();
  const [data, setData] = useState<Loaded | null>(null);
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const history = await listExecutions(50);
        const completed = history.items.find((item) => item.status === "COMPLETED");
        if (!completed) {
          if (live) setEmpty(true);
          return;
        }
        const index = await listEvidence(completed.execution_id);
        if (live) setData({ executionId: completed.execution_id, metrics: index.items });
      } catch (failure) {
        if (live) setError(failure instanceof Error ? failure.message : String(failure));
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  /**
   * A run publishes each metric for more than one window -- the analysis window
   * and the one it is compared against -- so "the figure" means the latest
   * window **that metric** was computed for.
   *
   * Deliberately not one window for the whole execution. Reconciliation runs on
   * a settlement-lagged window that ends after the analysis window does, so the
   * newest `period_from` in the evidence set belongs to `bank_count` and every
   * revenue metric matched against it comes back empty. Grouping per metric is
   * the only rule that does not assume the tools agree on a calendar.
   */
  const latest = useMemo(() => {
    const newest = new Map<string, EvidenceLine>();
    for (const row of data?.metrics ?? []) {
      const key = `${row.tool_name}|${row.metric_id}|${row.dimension_value ?? ""}`;
      const held = newest.get(key);
      if (!held || row.period_from > held.period_from) newest.set(key, row);
    }
    return [...newest.values()];
  }, [data]);

  const pick = (tool: string, metric: string): EvidenceLine | null =>
    latest.find(
      (item) =>
        item.tool_name === tool && item.metric_id === metric && item.dimension_value === null,
    ) ?? null;

  const attribution = latest
    .filter((item) => item.metric_id.startsWith("attribution."))
    .sort((a, b) => Math.abs(Number(b.value)) - Math.abs(Number(a.value)));

  const methods = latest.filter(
    (item) => item.tool_name === FAILURES && item.metric_id === "by_method.success_rate_ratio",
  );

  if (error) {
    return (
      <Shell title="Dashboard">
        <Alert isFullWidth color="negative" title="Cannot load" description={error} />
      </Shell>
    );
  }

  if (empty) {
    return (
      <Shell title="Dashboard">
        <Panel>
          <EmptyState
            title="No verified run yet"
            body="This page shows the evidence a completed investigation published. Ask a question and it will fill in."
            action={
              <Link
                href="/"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: space(1.5),
                  padding: `${space(2)} ${space(4)}`,
                  borderRadius: radius.md,
                  backgroundColor: t.accent,
                  color: t.textOnAccent,
                  fontSize: "13px",
                  fontWeight: 600,
                  textDecoration: "none",
                  boxShadow: t.shadowAccent,
                }}
              >
                Ask a question <ArrowRight size={14} />
              </Link>
            }
          />
        </Panel>
      </Shell>
    );
  }

  if (!data) {
    return (
      <Shell title="Dashboard">
        <Spinner accessibilityLabel="Loading the scorecard" size="medium" />
      </Shell>
    );
  }

  const window = pick(REVENUE, "net_revenue_paise") ?? latest[0];

  return (
    <Shell
      title="Dashboard"
      subtitle={
        window
          ? `Published evidence from the most recent completed run, for [${window.period_from}, ${window.period_to}). Every tile opens onto its source records.`
          : "Published evidence from the most recent completed run."
      }
    >
      <Grid min="230px">
        {SCORECARD.map((entry) => {
          const row = pick(entry.tool, entry.metric);
          if (!row) return null;
          const amount = Number(row.value);
          const signed =
            row.metric_id.includes("change") && Number.isFinite(amount) && amount !== 0;
          return (
            <MetricTile
              key={row.evidence_id}
              label={entry.label}
              value={row.display}
              tone={signed ? (amount < 0 ? "negative" : "positive") : entry.tone}
              caption={row.metric_id}
              onOpen={() => setInspecting(row.evidence_id)}
            />
          );
        })}
      </Grid>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))",
          gap: space(6),
          alignItems: "start",
        }}
      >
        <RevenueWaterfall
          terms={attribution}
          total={pick(REVENUE, "net_revenue_change_paise")}
          onInspect={setInspecting}
        />

        {methods.length > 0 ? (
          <Panel>
            <PanelHeader
              title="Success rate by method"
              hint="Each rail is its own verified metric, not a share of one."
            />
            <Stack gap={2}>
              {[...methods]
                .sort((a, b) => Number(b.value) - Number(a.value))
                .map((method) => {
                  const rate = Number(method.value);
                  return (
                    <button
                      key={method.evidence_id}
                      type="button"
                      onClick={() => setInspecting(method.evidence_id)}
                      style={{
                        appearance: "none",
                        font: "inherit",
                        width: "100%",
                        textAlign: "left",
                        display: "flex",
                        flexDirection: "column",
                        gap: space(1.5),
                        padding: `${space(2)} ${space(2.5)}`,
                        borderRadius: radius.sm,
                        border: "1px solid transparent",
                        background: "none",
                        cursor: "pointer",
                      }}
                      onMouseEnter={(event) => {
                        event.currentTarget.style.backgroundColor = t.surfaceHover;
                        event.currentTarget.style.borderColor = t.border;
                      }}
                      onMouseLeave={(event) => {
                        event.currentTarget.style.backgroundColor = "transparent";
                        event.currentTarget.style.borderColor = "transparent";
                      }}
                    >
                      <Row gap={3} style={{ justifyContent: "space-between" }}>
                        <span style={{ fontSize: "13px", fontWeight: 500, color: t.text }}>
                          {method.dimension_value}
                        </span>
                        <span style={{ ...numeric, fontSize: "13px", fontWeight: 600, color: t.text }}>
                          {method.display}
                        </span>
                      </Row>
                      <div
                        style={{
                          height: "6px",
                          borderRadius: radius.pill,
                          backgroundColor: t.sunken,
                          overflow: "hidden",
                        }}
                      >
                        <span
                          style={{
                            display: "block",
                            height: "100%",
                            // A success rate lives in the top few percent, so a
                            // 0-100 axis renders every rail as a full bar.
                            // The floor is 90%, and the caption says so.
                            width: `${Math.max(Math.min((rate - 0.9) / 0.1, 1), 0.02) * 100}%`,
                            backgroundColor: t.accent,
                            borderRadius: radius.pill,
                          }}
                        />
                      </div>
                    </button>
                  );
                })}
              <span style={{ fontSize: "11px", color: t.textFaint, marginTop: space(1) }}>
                Bars are scaled from 90% to 100%, where the differences are.
              </span>
            </Stack>
          </Panel>
        ) : null}
      </div>

      <ProvenanceDrawer
        executionId={data.executionId}
        evidenceId={inspecting}
        onDismiss={() => setInspecting(null)}
      />
    </Shell>
  );
}
