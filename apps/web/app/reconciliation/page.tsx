"use client";

/**
 * The reconciliation dashboard, and why it is built on evidence rather than on
 * the reconciliation endpoint.
 *
 * The scorecard reads the *published evidence* of the most recent completed
 * execution — not `reconciliation_runs`. Both hold the same figures, but only
 * one of them carries an evidence id, and a number without one cannot be
 * clicked down to the records it came from. A dashboard where the tiles are
 * inert and the chat answer is clickable would be two different standards of
 * proof in one product.
 *
 * The exception explorer reads the reconciliation endpoint, because an
 * exception is not a metric: it is a row with a category, an amount, and — for
 * the ones that matter most — the candidate the matcher found and deliberately
 * refused.
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
import type { EvidenceLine, ExceptionItem, RunSummary } from "@shared/api";
import { useEffect, useState } from "react";

import { Clickable } from "@/components/Clickable";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { listEvidence, listExceptions, listExecutions, listRuns } from "@/lib/api";

const RECONCILIATION = "finance.reconciliation";

/** The order a reader wants them in, which is not alphabetical. */
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
  exception_count: "Exceptions",
  unresolved_exception_value_paise: "Unresolved value",
};

type Loaded = {
  executionId: string | null;
  metrics: EvidenceLine[];
  run: RunSummary | null;
  exceptions: ExceptionItem[];
};

export default function ReconciliationPage() {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);

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

  // The analysis window and the bank window are different by design (D-18), so
  // the scorecard picks the row for each metric rather than assuming one window.
  const tiles = SCORECARD.map((metricId) =>
    data.metrics.find((metric) => metric.metric_id === metricId),
  ).filter((metric): metric is EvidenceLine => metric !== undefined);

  return (
    <Shell
      title="Reconciliation"
      subtitle="Every tile is a verified metric. Click one to walk it down to the records it came from."
    >
      <Box display="flex" flexWrap="wrap" gap="spacing.4">
        {tiles.map((metric) => (
          <Clickable
            key={metric.evidence_id}
            onClick={() => setInspecting(metric.evidence_id)}
            label={`Show the evidence for ${metric.metric_id}`}
            data-testid="metric-tile"
            data-metric={metric.metric_id}
            data-evidence-id={metric.evidence_id}
          >
            <Box
              display="flex"
              flexDirection="column"
              gap="spacing.2"
              padding="spacing.5"
              borderRadius="medium"
              borderWidth="thin"
              borderColor="surface.border.gray.subtle"
              backgroundColor="surface.background.gray.intense"
              minWidth="200px"
            >
              <Text size="small" color="surface.text.gray.muted" textAlign="left">
                {LABELS[metric.metric_id] ?? metric.metric_id}
              </Text>
              <Heading size="medium">{metric.display}</Heading>
              <Text size="xsmall" color="interactive.text.primary.normal" textAlign="left">
                [{metric.period_from}, {metric.period_to})
              </Text>
            </Box>
          </Clickable>
        ))}
      </Box>

      {data.run ? <Breakdown run={data.run} /> : null}
      <Exceptions items={data.exceptions} />

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
  const rows = Object.entries(run.exception_breakdown).sort((a, b) => b[1] - a[1]);
  return (
    <Card padding="spacing.5" elevation="lowRaised">
      <CardBody>
        <Box display="flex" flexDirection="column" gap="spacing.3">
          <Heading size="small">Exception breakdown</Heading>
          {rows.map(([category, count]) => (
            <Box
              key={category}
              display="flex"
              justifyContent="space-between"
              testID={`breakdown-${category}`}
            >
              <Text size="small">{category.replaceAll("_", " ").toLowerCase()}</Text>
              <Text size="small" weight="semibold">
                {count}
              </Text>
            </Box>
          ))}
        </Box>
      </CardBody>
    </Card>
  );
}

type Candidate = {
  settlement_id?: string;
  rule?: string;
  confidence_ratio?: string;
  rejected_because?: string;
};

/**
 * The exception explorer.
 *
 * The rejected candidates are the point. "We found something close and
 * deliberately did not match it, and here is why" is a far stronger trust
 * signal than an empty result, and it is the difference between a matcher that
 * missed something and one that made a decision.
 */
function Exceptions({ items }: { items: ExceptionItem[] }) {
  if (items.length === 0) return null;
  return (
    <Card padding="spacing.5" elevation="lowRaised">
      <CardBody>
        <Box display="flex" flexDirection="column" gap="spacing.4">
          <Heading size="small">Exceptions</Heading>
          {items.map((item) => {
            const candidates = (item.detail?.candidates as Candidate[] | undefined) ?? [];
            return (
              <Box
                key={item.id}
                display="flex"
                flexDirection="column"
                gap="spacing.2"
                testID="exception"
              >
                <Box display="flex" alignItems="center" gap="spacing.3" flexWrap="wrap">
                  <Badge color={item.category === "NO_COUNTERPART" ? "negative" : "notice"}>
                    {item.category}
                  </Badge>
                  <Text size="small" weight="semibold">
                    {item.transaction_id ?? item.settlement_id}
                  </Text>
                  <Text size="small" color="surface.text.gray.muted">
                    {item.side} · {item.status}
                  </Text>
                </Box>

                {candidates.map((candidate) => (
                  <Box
                    key={candidate.settlement_id}
                    display="flex"
                    flexDirection="column"
                    paddingLeft="spacing.5"
                    testID="rejected-candidate"
                  >
                    <Text size="xsmall">
                      candidate {candidate.settlement_id} · {candidate.rule} · confidence{" "}
                      {candidate.confidence_ratio}
                    </Text>
                    <Text size="xsmall" color="feedback.text.negative.intense">
                      rejected: {candidate.rejected_because}
                    </Text>
                  </Box>
                ))}
                <Divider />
              </Box>
            );
          })}
        </Box>
      </CardBody>
    </Card>
  );
}
