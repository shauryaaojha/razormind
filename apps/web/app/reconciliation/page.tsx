"use client";

/**
 * The reconciliation dashboard, built on evidence and deterministic matching.
 */

import {
  Alert,
  Badge,
  Box,
  Card,
  CardBody,
  Divider,
  EmptyState,
  Heading,
  Spinner,
  Text,
} from "@razorpay/blade/components";
import { AlertCircle, ArrowUpRight, CheckCircle2, Filter, Layers, Scale, ShieldAlert } from "lucide-react";
import type { EvidenceLine, ExceptionItem, RunSummary } from "@shared/api";
import { useEffect, useState } from "react";

import { useAppTheme } from "@/app/providers";
import { Clickable } from "@/components/Clickable";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { listEvidence, listExceptions, listExecutions, listRuns } from "@/lib/api";

const RECONCILIATION = "finance.reconciliation";

const SCORECARD = [
  "ledger_count",
  "bank_count",
  "matched_pairs_count",
  "matched_clean_count",
  "clean_match_rate_ratio",
  "exception_count",
  "unresolved_exception_value_paise",
] as const;

const LABELS: Record<string, string> = {
  ledger_count: "Settlement-eligible captures",
  bank_count: "Bank settlement lines",
  matched_pairs_count: "Matched pairs",
  matched_clean_count: "Matched clean",
  clean_match_rate_ratio: "Clean match rate",
  exception_count: "Exceptions flagged",
  unresolved_exception_value_paise: "Unresolved value",
};

type Loaded = {
  executionId: string | null;
  metrics: EvidenceLine[];
  run: RunSummary | null;
  exceptions: ExceptionItem[];
};

export default function ReconciliationPage() {
  const { isDark } = useAppTheme();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("ALL");

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const history = await listExecutions(50);
        const completed = history.items.find((item) => item.status === "COMPLETED");

        let metrics: EvidenceLine[] = [];
        if (completed) {
          const index = await listEvidence(completed.execution_id);
          metrics = index.items.filter((item) => item.tool_name === RECONCILIATION);
        }

        const runs = await listRuns();
        const run = runs.items[0] ?? null;
        const exceptions = run ? (await listExceptions(run.run_id)).items : [];

        if (live) {
          setData({
            executionId: completed?.execution_id ?? null,
            metrics,
            run,
            exceptions,
          });
        }
      } catch (failure) {
        if (live) setError(failure instanceof Error ? failure.message : String(failure));
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <Shell title="Reconciliation">
        <Alert isFullWidth color="negative" title="Cannot load" description={error} />
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell title="Reconciliation">
        <Spinner accessibilityLabel="Loading reconciliation" size="medium" />
      </Shell>
    );
  }
  if (!data.executionId || data.metrics.length === 0) {
    return (
      <Shell title="Reconciliation">
        <EmptyState
          title="No verified run yet"
          description="Ask a reconciliation question first; this page shows the evidence a completed investigation published."
        />
      </Shell>
    );
  }

  const tiles = SCORECARD.map((metricId) =>
    data.metrics.find((metric) => metric.metric_id === metricId),
  ).filter((metric): metric is EvidenceLine => metric !== undefined);

  const filteredExceptions =
    activeCategory === "ALL"
      ? data.exceptions
      : data.exceptions.filter((item) => item.category === activeCategory);

  const categories = [
    { key: "ALL", label: "All Exceptions", count: data.exceptions.length },
    {
      key: "TIMING_LAG",
      label: "Timing Lag",
      count: data.exceptions.filter((e) => e.category === "TIMING_LAG").length,
    },
    {
      key: "NO_COUNTERPART",
      label: "No Counterpart",
      count: data.exceptions.filter((e) => e.category === "NO_COUNTERPART").length,
    },
    {
      key: "AMOUNT_MISMATCH",
      label: "Amount Mismatch",
      count: data.exceptions.filter((e) => e.category === "AMOUNT_MISMATCH").length,
    },
    {
      key: "FEE_DISCREPANCY",
      label: "Fee Discrepancy",
      count: data.exceptions.filter((e) => e.category === "FEE_DISCREPANCY").length,
    },
    {
      key: "POSSIBLE_DUPLICATE",
      label: "Possible Duplicate",
      count: data.exceptions.filter((e) => e.category === "POSSIBLE_DUPLICATE").length,
    },
  ];

  return (
    <Shell
      title="Reconciliation Command Center"
      subtitle="Every tile is a verified metric. Click one to walk it down to the records it came from."
    >
      {/* Top 7 Scorecard Metric Tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "14px",
        }}
      >
        {tiles.map((metric) => (
          <Clickable
            key={metric.evidence_id}
            onClick={() => setInspecting(metric.evidence_id)}
            label={`Show the evidence for ${metric.metric_id}`}
            data-testid="metric-tile"
            data-metric={metric.metric_id}
            data-evidence-id={metric.evidence_id}
          >
            <div
              style={{
                padding: "16px 18px",
                borderRadius: "10px",
                backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
                border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                textAlign: "left",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B" }}>
                {LABELS[metric.metric_id] ?? metric.metric_id}
              </div>
              <div
                style={{
                  fontSize: "20px",
                  fontWeight: 700,
                  color:
                    metric.metric_id === "clean_match_rate_ratio"
                      ? "#10B981"
                      : isDark
                        ? "#F8FAFC"
                        : "#0F172A",
                  letterSpacing: "-0.01em",
                }}
              >
                {metric.display}
              </div>
              <div
                style={{
                  fontSize: "11px",
                  color: "#0C83FF",
                  fontFamily: "JetBrains Mono, monospace",
                }}
              >
                [{metric.period_from}, {metric.period_to})
              </div>
            </div>
          </Clickable>
        ))}
      </div>

      {/* Exception Breakdown summary */}
      {data.run ? <Breakdown run={data.run} /> : null}

      {/* Exception Filter Tabs */}
      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          {categories.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              style={{
                padding: "6px 14px",
                borderRadius: "20px",
                fontSize: "12px",
                fontWeight: 600,
                border: `1px solid ${
                  activeCategory === cat.key
                    ? "#0C83FF"
                    : isDark
                      ? "#1E293B"
                      : "#E2E8F0"
                }`,
                backgroundColor:
                  activeCategory === cat.key
                    ? "rgba(12, 131, 255, 0.15)"
                    : isDark
                      ? "#0E131F"
                      : "#FFFFFF",
                color:
                  activeCategory === cat.key
                    ? "#0C83FF"
                    : isDark
                      ? "#94A3B8"
                      : "#64748B",
                cursor: "pointer",
                transition: "all 0.15s ease",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              <span>{cat.label}</span>
              <span
                style={{
                  padding: "1px 6px",
                  borderRadius: "10px",
                  fontSize: "11px",
                  backgroundColor:
                    activeCategory === cat.key
                      ? "#0C83FF"
                      : isDark
                        ? "#1E293B"
                        : "#E2E8F0",
                  color: activeCategory === cat.key ? "#FFFFFF" : isDark ? "#94A3B8" : "#64748B",
                }}
              >
                {cat.count}
              </span>
            </button>
          ))}
        </div>

        <Exceptions items={filteredExceptions} />
      </div>

      {data.executionId ? (
        <ProvenanceDrawer
          executionId={data.executionId}
          evidenceId={inspecting}
          onDismiss={() => setInspecting(null)}
        />
      ) : null}
    </Shell>
  );
}

function Breakdown({ run }: { run: RunSummary }) {
  const { isDark } = useAppTheme();
  const rows = Object.entries(run.exception_breakdown).sort((a, b) => b[1] - a[1]);
  return (
    <div
      style={{
        padding: "20px",
        borderRadius: "12px",
        backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
        border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      <div style={{ fontSize: "15px", fontWeight: 700 }}>Exception Breakdown by Category</div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "10px",
        }}
      >
        {rows.map(([category, count]) => (
          <div
            key={category}
            data-testid={`breakdown-${category}`}
            style={{
              padding: "10px 14px",
              borderRadius: "8px",
              backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: "13px",
            }}
          >
            <span style={{ textTransform: "capitalize" }}>
              {category.replaceAll("_", " ").toLowerCase()}
            </span>
            <span style={{ fontWeight: 700, color: "#F59E0B" }}>{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type Candidate = {
  settlement_id?: string;
  rule?: string;
  confidence_ratio?: string;
  rejected_because?: string;
};

function Exceptions({ items }: { items: ExceptionItem[] }) {
  const { isDark } = useAppTheme();
  if (items.length === 0) {
    return (
      <div
        style={{
          padding: "24px",
          textAlign: "center",
          borderRadius: "12px",
          backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
          border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
          color: isDark ? "#94A3B8" : "#64748B",
        }}
      >
        No exceptions match the selected filter.
      </div>
    );
  }

  return (
    <div
      style={{
        padding: "20px",
        borderRadius: "12px",
        backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
        border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
        display: "flex",
        flexDirection: "column",
        gap: "16px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>
          Reconciliation Exception Explorer ({items.length})
        </h3>
        <span style={{ fontSize: "11px", color: isDark ? "#94A3B8" : "#64748B" }}>
          Rejected Match Rationale Displayed
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        {items.map((item) => {
          const candidates = (item.detail?.candidates as Candidate[] | undefined) ?? [];
          const isNoCounterpart = item.category === "NO_COUNTERPART";
          const isFeeDiscrepancy = item.category === "FEE_DISCREPANCY";

          return (
            <div
              key={item.id}
              data-testid="exception"
              style={{
                padding: "16px",
                borderRadius: "8px",
                backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
                border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap",
                  gap: "8px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                  <Badge color={isNoCounterpart ? "negative" : "notice"}>
                    {item.category}
                  </Badge>
                  <span style={{ fontWeight: 700, fontSize: "14px", fontFamily: "JetBrains Mono, monospace" }}>
                    {item.transaction_id ?? item.settlement_id}
                  </span>
                  <span style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B" }}>
                    {item.side} · {item.status}
                  </span>
                </div>

                <div
                  style={{
                    fontSize: "13px",
                    fontWeight: 700,
                    fontFamily: "JetBrains Mono, monospace",
                    color: isDark ? "#F8FAFC" : "#0F172A",
                  }}
                >
                  ₹{(item.amount_paise / 100).toFixed(2)}
                </div>
              </div>

              {/* Rejected Candidate Box */}
              {candidates.map((candidate) => (
                <div
                  key={candidate.settlement_id}
                  data-testid="rejected-candidate"
                  style={{
                    padding: "12px 14px",
                    borderRadius: "6px",
                    backgroundColor: isDark ? "rgba(239, 68, 68, 0.08)" : "rgba(239, 68, 68, 0.05)",
                    border: "1px solid rgba(239, 68, 68, 0.2)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <div style={{ fontSize: "12px", fontWeight: 600 }}>
                    Candidate {candidate.settlement_id} · Rule: {candidate.rule} · Confidence:{" "}
                    <span style={{ color: "#F59E0B" }}>{candidate.confidence_ratio}</span> (Threshold: 0.85)
                  </div>
                  <div style={{ fontSize: "12px", color: "#EF4444", fontWeight: 500 }}>
                    Rejected rationale: {candidate.rejected_because}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
