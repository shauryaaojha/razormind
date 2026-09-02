"use client";

/**
 * The reconciliation scorecard, built on evidence, plus the exception explorer.
 *
 * The tiles read published evidence rather than `reconciliation_runs`: both
 * hold the same figures and only one carries the id that makes a tile
 * openable (D-56). The exceptions come from the reconciliation endpoint,
 * because an exception is not a metric — it is a row with a category, an
 * amount, and, for the ones that matter, the candidate the matcher found and
 * deliberately refused.
 */

import { Alert, Badge, Spinner } from "@razorpay/blade/components";
import type { EvidenceLine, ExceptionItem, RunSummary } from "@shared/api";
import { useEffect, useState } from "react";

import { useTheme } from "@/app/providers";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { EmptyState, Grid, MetricTile, Panel, PanelHeader, Pill, Row, Stack } from "@/components/ui";
import { listEvidence, listExceptions, listExecutions, listRuns } from "@/lib/api";
import { numeric, radius, space, transition } from "@/lib/theme";

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

const CATEGORY_LABEL = (key: string) =>
  key.replaceAll("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

type Loaded = {
  executionId: string | null;
  metrics: EvidenceLine[];
  run: RunSummary | null;
  exceptions: ExceptionItem[];
};

export default function ReconciliationPage() {
  const { t } = useTheme();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [category, setCategory] = useState("ALL");

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
          setData({ executionId: completed?.execution_id ?? null, metrics, run, exceptions });
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
        <Panel>
          <EmptyState
            title="No verified run yet"
            body="This page shows the evidence a completed investigation published. Ask a reconciliation question and it will fill in."
          />
        </Panel>
      </Shell>
    );
  }

  // Latest window per metric, not the first row found: reconciliation
  // publishes the settlement-lagged bank window alongside the analysis one, so
  // "the first row with this id" can be the comparison period.
  const tiles = SCORECARD.map((metricId) =>
    data.metrics
      .filter((metric) => metric.metric_id === metricId)
      .reduce<EvidenceLine | undefined>(
        (newest, metric) =>
          !newest || metric.period_from > newest.period_from ? metric : newest,
        undefined,
      ),
  ).filter((metric): metric is EvidenceLine => metric !== undefined);

  const counts = new Map<string, number>();
  for (const item of data.exceptions) {
    counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  }
  const filters = [
    { key: "ALL", label: "All", count: data.exceptions.length },
    ...[...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, label: CATEGORY_LABEL(key), count })),
  ];
  const shown =
    category === "ALL"
      ? data.exceptions
      : data.exceptions.filter((item) => item.category === category);

  return (
    <Shell
      title="Reconciliation"
      subtitle="Every tile is a verified metric. Click one to walk it down to the records it came from."
    >
      <Grid min="215px">
        {tiles.map((metric) => (
          <div key={metric.evidence_id} data-metric={metric.metric_id}>
            <MetricTile
              testID="metric-tile"
              label={LABELS[metric.metric_id] ?? metric.metric_id}
              value={metric.display}
              tone={metric.metric_id === "clean_match_rate_ratio" ? "positive" : undefined}
              caption={`[${metric.period_from}, ${metric.period_to})`}
              onOpen={() => setInspecting(metric.evidence_id)}
            />
          </div>
        ))}
      </Grid>

      {data.run ? <Breakdown run={data.run} /> : null}

      <Panel>
        <PanelHeader
          title={`Exceptions (${data.exceptions.length})`}
          hint="A near miss the matcher refused is a stronger signal than an empty result, so the rejected candidate and its reason are shown."
          action={
            <Row gap={1.5}>
              {filters.map((filter) => {
                const active = category === filter.key;
                return (
                  <button
                    key={filter.key}
                    type="button"
                    onClick={() => setCategory(filter.key)}
                    aria-pressed={active}
                    style={{
                      appearance: "none",
                      font: "inherit",
                      display: "flex",
                      alignItems: "center",
                      gap: space(1.5),
                      padding: `${space(1)} ${space(2.5)}`,
                      borderRadius: radius.pill,
                      fontSize: "11.5px",
                      fontWeight: 600,
                      border: `1px solid ${active ? t.accentBorder : t.border}`,
                      backgroundColor: active ? t.accentSoft : "transparent",
                      color: active ? t.accent : t.textMuted,
                      cursor: "pointer",
                      transition: `all ${transition.fast}`,
                    }}
                  >
                    {filter.label}
                    <span style={{ ...numeric, opacity: 0.75 }}>{filter.count}</span>
                  </button>
                );
              })}
            </Row>
          }
        />
        <Exceptions items={shown} />
      </Panel>

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
  const { t } = useTheme();
  const rows = Object.entries(run.exception_breakdown).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  if (rows.length === 0) return null;

  return (
    <Panel>
      <PanelHeader
        title="Exceptions by category"
        hint="Ledger side only — counting the bank side in the same total would count one discrepancy twice."
      />
      <Stack gap={2.5}>
        {rows.map(([name, count]) => (
          <div key={name} data-testid={`breakdown-${name}`}>
            <Row gap={3} style={{ justifyContent: "space-between", marginBottom: space(1) }}>
              <span style={{ fontSize: "12.5px", color: t.text }}>{CATEGORY_LABEL(name)}</span>
              <span style={{ ...numeric, fontSize: "12.5px", fontWeight: 600, color: t.warning }}>
                {count}
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
                  width: `${(count / total) * 100}%`,
                  backgroundColor: t.warning,
                  opacity: 0.8,
                  borderRadius: radius.pill,
                }}
              />
            </div>
          </div>
        ))}
      </Stack>
    </Panel>
  );
}

type Candidate = {
  settlement_id?: string;
  rule?: string;
  confidence_ratio?: string;
  rejected_because?: string;
};

function Exceptions({ items }: { items: ExceptionItem[] }) {
  const { t } = useTheme();
  if (items.length === 0) {
    return <EmptyState title="Nothing here" body="No exception matches the selected category." />;
  }

  return (
    <Stack gap={2.5}>
      {items.map((item) => {
        const candidates = (item.detail?.candidates as Candidate[] | undefined) ?? [];
        return (
          <div
            key={item.id}
            data-testid="exception"
            style={{
              padding: space(4),
              borderRadius: radius.md,
              backgroundColor: t.sunken,
              border: `1px solid ${t.border}`,
              display: "flex",
              flexDirection: "column",
              gap: space(2.5),
            }}
          >
            <Row gap={3} style={{ justifyContent: "space-between" }}>
              <Row gap={2.5}>
                <Badge color={item.category === "NO_COUNTERPART" ? "negative" : "notice"}>
                  {item.category}
                </Badge>
                <span style={{ ...numeric, fontSize: "13.5px", fontWeight: 650, color: t.text }}>
                  {item.transaction_id ?? item.settlement_id}
                </span>
                <span style={{ fontSize: "11.5px", color: t.textFaint }}>
                  {item.side} · {item.status}
                </span>
              </Row>
              {/* The API renders this; nothing here divides paise by 100 (D-54). */}
              <span style={{ ...numeric, fontSize: "13.5px", fontWeight: 650, color: t.text }}>
                {item.amount_display}
              </span>
            </Row>

            {candidates.map((candidate) => (
              <div
                key={candidate.settlement_id}
                data-testid="rejected-candidate"
                style={{
                  padding: `${space(2.5)} ${space(3)}`,
                  borderRadius: radius.sm,
                  backgroundColor: t.negativeSoft,
                  border: `1px solid ${t.border}`,
                  display: "flex",
                  flexDirection: "column",
                  gap: space(1),
                }}
              >
                <Row gap={2}>
                  <span style={{ fontSize: "11.5px", color: t.textMuted }}>
                    Found <strong style={{ color: t.text }}>{candidate.settlement_id}</strong> by{" "}
                    {candidate.rule}
                  </span>
                  <Pill tone="warning">confidence {candidate.confidence_ratio}</Pill>
                </Row>
                <span style={{ fontSize: "11.5px", color: t.negative, lineHeight: 1.5 }}>
                  Not matched: {candidate.rejected_because}
                </span>
              </div>
            ))}
          </div>
        );
      })}
    </Stack>
  );
}
