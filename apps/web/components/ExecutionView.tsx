"use client";

/**
 * One execution, rendered. The **only** component that renders one.
 *
 * Everything a number needs to be believed is here: the stages that produced
 * it, the verification that cleared it, and a claim that opens onto the
 * evidence.
 *
 * Each stage now carries the work it did rather than a label and a badge. That
 * was the gap worth closing: a five-row stepper describes a pipeline correctly
 * and shows nothing about it, so a reader watching one had to take the
 * interesting part -- the eleven gates, the concurrent DAG, the five layers in
 * order, the rewrite when a sentence did not match its rows -- entirely on
 * trust. Every panel below is drawn from an event the run emitted, so a stage
 * that did nothing renders nothing, and a run that broke shows where.
 *
 * The answer is laid out as **flowing prose with the claims inline**, not as a
 * stack of boxed figures. It was the latter, and that is a worse reading of
 * what a claim is: a claim is a span *of a sentence* that happens to be backed
 * by a row, so lifting it out of the sentence loses the argument the paragraph
 * was making. Inline, the reader sees an ordinary paragraph in which some
 * phrases are underlined and can be opened.
 */

import { Alert, Badge, Spinner } from "@razorpay/blade/components";
import type { AnswerClaim, ExecutionSummary } from "@shared/api";
import React, { type ReactNode } from "react";

import { useTheme } from "@/app/providers";
import { Motion } from "@/components/motion";
import { TraceGraph } from "@/components/TraceGraph";
import {
  ClarificationPanel,
  GatePanel,
  GroundingPanel,
  IntentPanel,
  VerificationPanel,
} from "@/components/TracePanels";
import { Panel, PanelHeader, Pill, Row, SectionLabel, Stack } from "@/components/ui";
import {
  clarificationOf,
  graphOf,
  groundingOf,
  intentOf,
  validationOf,
  verificationOf,
} from "@/lib/pipeline";
import type { TraceEvent } from "@/lib/stream";
import { numeric, radius, space, transition } from "@/lib/theme";
import { questionOf, stagesOf, statusOf, type StageStatus } from "@/lib/trace";

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

export function ExecutionView({ events, summary, onInspect }: ExecutionViewProps) {
  const { t } = useTheme();
  const stages = stagesOf(events);
  const status = statusOf(events);
  const question = questionOf(events);

  const intent = intentOf(events);
  const asked = clarificationOf(events);
  const validation = validationOf(events);
  const nodes = graphOf(events);
  const verification = verificationOf(events);
  const grounding = groundingOf(events);

  /** What to show under each stage, or nothing if that stage said nothing. */
  const detailFor = (stageId: string, stageStatus: StageStatus): ReactNode => {
    if (stageId === "understand") {
      if (asked) return <ClarificationPanel asked={asked} />;
      return intent ? <IntentPanel intent={intent} /> : null;
    }
    if (stageId === "validate") {
      return validation ? <GatePanel validation={validation} /> : null;
    }
    if (stageId === "execute") {
      return nodes.length > 0 ? <TraceGraph nodes={nodes} /> : null;
    }
    if (stageId === "verify") {
      const shown = verification.layers.length > 0 || verification.finished !== null;
      return shown ? (
        <VerificationPanel verification={verification} active={stageStatus === "running"} />
      ) : null;
    }
    if (stageId === "explain") {
      return grounding ? <GroundingPanel grounding={grounding} /> : null;
    }
    return null;
  };

  return (
    <Stack gap={5} style={{ width: "100%" }}>
      <Motion />

      {question ? (
        <Panel padding={4}>
          <Stack gap={1.5}>
            <SectionLabel>Question</SectionLabel>
            <span style={{ fontSize: "15px", fontWeight: 550, color: t.text, lineHeight: 1.5 }}>
              {question}
            </span>
          </Stack>
        </Panel>
      ) : null}

      <Panel>
        <PanelHeader
          title="Execution trace"
          hint="Each stage moves when an event arrives, not on a timer, and shows the work it actually did."
          action={<Badge color={status === "COMPLETED" ? "positive" : "neutral"}>{status}</Badge>}
        />

        <div style={{ display: "flex", flexDirection: "column" }}>
          {stages.map((stage, index) => {
            const detail = detailFor(stage.id, stage.status);
            const last = index === stages.length - 1;
            return (
              <div
                key={stage.id}
                data-testid={`stage-${stage.id}`}
                style={{ display: "flex", gap: space(3), alignItems: "flex-start" }}
              >
                {/* The rail: a dot per stage, joined by a line except at the end. */}
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    alignSelf: "stretch",
                    paddingTop: space(1),
                  }}
                >
                  <StageDot status={stage.status} />
                  {!last ? (
                    <span
                      style={{
                        flex: 1,
                        width: "1.5px",
                        minHeight: space(4),
                        backgroundColor: stage.status === "done" ? t.positiveSoft : t.border,
                      }}
                    />
                  ) : null}
                </div>

                <div
                  style={{
                    flex: 1,
                    minWidth: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: space(3),
                    paddingBottom: last ? 0 : space(5),
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: space(3),
                      flexWrap: "wrap",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column", gap: space(0.5) }}>
                      <span
                        style={{
                          fontSize: "13.5px",
                          fontWeight: stage.status === "pending" ? 450 : 600,
                          color: stage.status === "pending" ? t.textFaint : t.text,
                        }}
                      >
                        {stage.label}
                      </span>
                      {stage.detail ? (
                        <span style={{ ...numeric, fontSize: "12px", color: t.textMuted }}>
                          {stage.detail}
                        </span>
                      ) : null}
                    </div>

                    {stage.status === "running" ? (
                      <Spinner accessibilityLabel={`${stage.label} in progress`} size="medium" />
                    ) : (
                      <Badge color={BADGE[stage.status]}>{stage.status}</Badge>
                    )}
                  </div>

                  {detail ? (
                    <div
                      style={{
                        padding: space(4),
                        borderRadius: radius.md,
                        backgroundColor: t.sunken,
                        border: `1px solid ${t.border}`,
                      }}
                    >
                      {detail}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <Answer summary={summary} onInspect={onInspect} />
    </Stack>
  );
}

function StageDot({ status }: { status: StageStatus }) {
  const { t } = useTheme();
  const color =
    status === "done"
      ? t.positive
      : status === "failed"
        ? t.negative
        : status === "running"
          ? t.accent
          : t.borderStrong;
  return (
    <span
      aria-hidden
      className={status === "running" ? "rm-pulse" : undefined}
      style={{
        width: "9px",
        height: "9px",
        borderRadius: radius.pill,
        backgroundColor: status === "pending" ? "transparent" : color,
        border: `2px solid ${color}`,
        flexShrink: 0,
        ...(status === "running"
          ? { ["--rm-pulse" as string]: t.accentSoft, animation: "rm-pulse 1.6s ease-in-out infinite" }
          : {}),
      }}
    />
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
    return (
      <Alert
        isFullWidth
        color="negative"
        title="These numbers could not be verified"
        description={errorMessage(summary) ?? "Verification failed, so no figures are shown."}
      />
    );
  }

  if (summary.status === "NEEDS_CLARIFICATION" || summary.status === "REJECTED") {
    return (
      <Alert
        isFullWidth
        color="notice"
        title={summary.status === "NEEDS_CLARIFICATION" ? "One question back" : "Plan rejected"}
        description={errorMessage(summary) ?? "Nothing was run."}
      />
    );
  }

  if (!summary.answer) return null;

  const written = summary.response_source === "LLM";
  return (
    <Panel>
      <PanelHeader
        title="Answer"
        hint="Underlined figures open onto the evidence they came from."
        action={
          <Row gap={2} wrap={false}>
            <Pill tone={written ? "info" : "neutral"}>
              {written ? "written by the model" : "template"}
            </Pill>
            <Pill tone="positive">
              {summary.claims.length} grounded {summary.claims.length === 1 ? "claim" : "claims"}
            </Pill>
          </Row>
        }
      />
      <GroundedText answer={summary.answer} claims={summary.claims} onInspect={onInspect} />
    </Panel>
  );
}

export function GroundedText({
  answer,
  claims,
  onInspect,
}: {
  answer: string;
  claims: AnswerClaim[];
  onInspect?: (evidenceId: string) => void;
}) {
  const { t } = useTheme();
  const segments = splitByClaims(answer, claims);
  return (
    <p
      style={{
        margin: 0,
        fontSize: "14.5px",
        lineHeight: 1.75,
        color: t.text,
        maxWidth: "78ch",
      }}
    >
      {segments.map((segment, index) => {
        const spacer = index > 0 ? " " : "";
        if (!segment.claim) {
          return (
            <React.Fragment key={index}>
              {spacer}
              <span style={{ color: t.textMuted }}>{segment.text}</span>
            </React.Fragment>
          );
        }
        const claim = segment.claim;
        return (
          <React.Fragment key={index}>
            {spacer}
            <button
              type="button"
              data-testid="claim"
              data-evidence-id={claim.evidence_id}
              aria-label={`Show the evidence for ${claim.metric_id}`}
              title={`${claim.metric_id} — open the evidence`}
              onClick={() => onInspect?.(claim.evidence_id)}
              style={{
                appearance: "none",
                font: "inherit",
                ...numeric,
                display: "inline",
                padding: 0,
                border: "none",
                background: "none",
                color: t.text,
                fontWeight: 600,
                cursor: "pointer",
                textDecoration: "underline",
                textDecorationStyle: "dotted",
                textDecorationColor: t.accentBorder,
                textUnderlineOffset: "3px",
                transition: `color ${transition.fast}, text-decoration-color ${transition.fast}`,
              }}
              onMouseEnter={(event) => {
                event.currentTarget.style.color = t.accent;
                event.currentTarget.style.textDecorationColor = t.accent;
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.color = t.text;
                event.currentTarget.style.textDecorationColor = t.accentBorder;
              }}
            >
              {segment.text}
            </button>
          </React.Fragment>
        );
      })}
    </p>
  );
}

type Segment = { text: string; claim: AnswerClaim | null };

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
