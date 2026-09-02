"use client";

/**
 * One execution, rendered. The **only** component that renders one.
 *
 * The chat page passes events arriving over the stream; the history page
 * passes events replayed from the same endpoint. Neither knows which it is,
 * because there is nothing to know: `execution_events` is append-only and
 * sequenced, so a run watched live and the same run read an hour later are the
 * same list of rows. `tests/execution-view.test.tsx` asserts the two produce
 * byte-identical markup — which is a property to hold rather than a
 * coincidence to notice.
 *
 * Everything a number needs to be believed is here: the stages that produced
 * it, the verification that cleared it, and a claim that opens onto the
 * evidence. Nothing here formats money; every figure arrives already written
 * by `narrative/render.py` (D-54).
 */

import {
  Alert,
  Badge,
  Box,
  Card,
  CardBody,
  Divider,
  Heading,
  Spinner,
  Text,
} from "@razorpay/blade/components";
import type { AnswerClaim, ExecutionSummary } from "@shared/api";

import { Clickable } from "@/components/Clickable";
import type { TraceEvent } from "@/lib/stream";
import { questionOf, stagesOf, statusOf, toolsOf, type StageStatus } from "@/lib/trace";

export type ExecutionViewProps = {
  events: TraceEvent[];
  summary: ExecutionSummary | null;
  /** Opens the provenance drawer on an evidence id. */
  onInspect?: (evidenceId: string) => void;
};

const BADGE: Record<StageStatus, "positive" | "negative" | "notice" | "neutral"> = {
  done: "positive",
  failed: "negative",
  running: "notice",
  pending: "neutral",
};

const TOOL_BADGE: Record<string, "positive" | "negative" | "notice" | "neutral"> = {
  SUCCEEDED: "positive",
  FAILED: "negative",
  SKIPPED: "neutral",
  running: "notice",
};

export function ExecutionView({ events, summary, onInspect }: ExecutionViewProps) {
  const stages = stagesOf(events);
  const tools = toolsOf(events);
  const status = statusOf(events);
  const question = questionOf(events);

  return (
    <Box display="flex" flexDirection="column" gap="spacing.5" testID="execution-view">
      {question ? (
        <Card padding="spacing.5" elevation="lowRaised">
          <CardBody>
            <Text size="small" color="surface.text.gray.muted">
              Question
            </Text>
            <Text weight="semibold">{question}</Text>
          </CardBody>
        </Card>
      ) : null}

      <Card padding="spacing.5" elevation="lowRaised">
        <CardBody>
          <Box display="flex" flexDirection="column" gap="spacing.4">
            <Box display="flex" alignItems="center" gap="spacing.3">
              <Heading size="small">Trace</Heading>
              <Badge color={status === "COMPLETED" ? "positive" : "neutral"}>{status}</Badge>
            </Box>

            {stages.map((stage) => (
              <Box
                key={stage.id}
                display="flex"
                alignItems="center"
                gap="spacing.3"
                testID={`stage-${stage.id}`}
              >
                {stage.status === "running" ? (
                  <Spinner accessibilityLabel={`${stage.label} in progress`} size="medium" />
                ) : (
                  <Badge color={BADGE[stage.status]}>{stage.status}</Badge>
                )}
                <Box display="flex" flexDirection="column">
                  <Text weight={stage.status === "pending" ? "regular" : "semibold"}>
                    {stage.label}
                  </Text>
                  {stage.detail ? (
                    <Text size="small" color="surface.text.gray.muted">
                      {stage.detail}
                    </Text>
                  ) : null}
                </Box>
              </Box>
            ))}

            {tools.length > 0 ? (
              <>
                <Divider />
                <Box display="flex" flexDirection="column" gap="spacing.2">
                  {tools.map((tool) => (
                    <Box
                      key={tool.node}
                      display="flex"
                      alignItems="center"
                      justifyContent="space-between"
                      gap="spacing.3"
                      testID={`tool-${tool.node}`}
                    >
                      <Box display="flex" alignItems="center" gap="spacing.3">
                        <Badge color={TOOL_BADGE[tool.status] ?? "neutral"}>{tool.status}</Badge>
                        <Text size="small">{tool.tool}</Text>
                      </Box>
                      <Text size="small" color="surface.text.gray.muted">
                        {tool.durationMs === undefined ? "…" : `${tool.durationMs} ms`}
                      </Text>
                    </Box>
                  ))}
                </Box>
              </>
            ) : null}
          </Box>
        </CardBody>
      </Card>

      <Answer summary={summary} onInspect={onInspect} />
    </Box>
  );
}

function Answer({
  summary,
  onInspect,
}: {
  summary: ExecutionSummary | null;
  onInspect?: (evidenceId: string) => void;
}) {
  if (!summary) return null;

  if (summary.status === "BLOCKED") {
    // Invariant 4, on screen: a verification failure carries no numbers at all.
    // A partial figure with a warning beside it is what this exists to prevent.
    return (
      <Alert
        isFullWidth
        color="negative"
        title="These numbers could not be verified"
        description={
          errorMessage(summary) ?? "Verification failed, so no figures are shown."
        }
      />
    );
  }

  if (summary.status === "NEEDS_CLARIFICATION" || summary.status === "REJECTED") {
    return (
      <Alert
        isFullWidth
        color="notice"
        title={
          summary.status === "NEEDS_CLARIFICATION" ? "One question back" : "Plan rejected"
        }
        description={errorMessage(summary) ?? "Nothing was run."}
      />
    );
  }

  if (!summary.answer) return null;

  return (
    <Card padding="spacing.5" elevation="lowRaised">
      <CardBody>
        <Box display="flex" flexDirection="column" gap="spacing.4">
          <Box display="flex" alignItems="center" gap="spacing.3">
            <Heading size="small">Answer</Heading>
            <Badge color={summary.response_source === "LLM" ? "information" : "neutral"}>
              {summary.response_source === "LLM" ? "written by the model" : "template"}
            </Badge>
            <Badge color="positive">{summary.claims.length} grounded claims</Badge>
          </Box>

          <GroundedText answer={summary.answer} claims={summary.claims} onInspect={onInspect} />
        </Box>
      </CardBody>
    </Card>
  );
}

/**
 * The answer, with every claimed span made clickable.
 *
 * The spans are the ones the grounding gate matched — the client does not scan
 * the prose for anything that looks like a number. A figure is clickable
 * because it was proved, not because it was recognised.
 */
export function GroundedText({
  answer,
  claims,
  onInspect,
}: {
  answer: string;
  claims: AnswerClaim[];
  onInspect?: (evidenceId: string) => void;
}) {
  const segments = splitByClaims(answer, claims);
  return (
    <Box display="flex" flexDirection="column" gap="spacing.2">
      {segments.map((segment, index) =>
        segment.claim ? (
          <Clickable
            key={index}
            onClick={() => onInspect?.(segment.claim!.evidence_id)}
            label={`Show the evidence for ${segment.claim.metric_id}`}
            data-testid="claim"
            data-evidence-id={segment.claim.evidence_id}
          >
            <Box
              display="flex"
              alignItems="center"
              justifyContent="space-between"
              gap="spacing.3"
              padding={["spacing.2", "spacing.3"]}
              borderRadius="medium"
              borderWidth="thin"
              borderColor="surface.border.gray.subtle"
              backgroundColor="surface.background.gray.subtle"
            >
              <Text size="small" textAlign="left">
                {segment.text}
              </Text>
              <Text size="xsmall" color="interactive.text.primary.normal">
                evidence
              </Text>
            </Box>
          </Clickable>
        ) : (
          <Text key={index} size="small" color="surface.text.gray.subtle">
            {segment.text}
          </Text>
        ),
      )}
    </Box>
  );
}

type Segment = { text: string; claim: AnswerClaim | null };

/**
 * Split the answer into claimed and unclaimed runs.
 *
 * Claims are located by searching for their own text, the same way the server
 * does when it checks them. Overlaps are resolved by taking the earliest, then
 * the longest — a span inside another span is the same figure twice, and
 * rendering it twice would put a button inside a button.
 */
export function splitByClaims(answer: string, claims: AnswerClaim[]): Segment[] {
  const found = claims
    .map((claim) => ({ claim, at: answer.indexOf(claim.text) }))
    .filter((hit) => hit.at >= 0)
    .sort((a, b) => a.at - b.at || b.claim.text.length - a.claim.text.length);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const hit of found) {
    if (hit.at < cursor) continue;
    if (hit.at > cursor) {
      const between = answer.slice(cursor, hit.at).trim();
      if (between) segments.push({ text: between, claim: null });
    }
    segments.push({ text: hit.claim.text, claim: hit.claim });
    cursor = hit.at + hit.claim.text.length;
  }
  const tail = answer.slice(cursor).trim();
  if (tail) segments.push({ text: tail, claim: null });
  return segments;
}

function errorMessage(summary: ExecutionSummary): string | undefined {
  const error = summary.error as { message?: string } | null;
  return typeof error?.message === "string" ? error.message : undefined;
}
