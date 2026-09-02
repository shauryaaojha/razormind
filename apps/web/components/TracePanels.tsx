"use client";

/**
 * What each stage of a run shows while it is happening.
 *
 * One panel per stage, each rendered only from the event that stage emitted, so
 * a panel is absent exactly when the thing it describes did not happen. That is
 * why there is no "waiting" artwork anywhere below: an empty gate panel means
 * validation has not run, and drawing eleven grey gates before the validator
 * has spoken would show the reader a panel that looks identical whether the
 * gates exist or not.
 *
 * The five verification layers are the one exception, and deliberately: they
 * are a fixed, ordered contract, so the five are listed from the start and fill
 * in as each finishes. Seeing that layer 4 is *coming* is part of what the
 * sequence means -- and a run that stops at layer 2 leaves three of them
 * visibly unreached, which is the fact worth showing.
 */

import { Badge } from "@razorpay/blade/components";
import { Check, ChevronRight, Minus, X } from "lucide-react";
import { useState } from "react";

import { useTheme } from "@/app/providers";
import { Mono, Pill, Row, SectionLabel, Stack } from "@/components/ui";
import {
  LAYERS,
  type Clarification,
  type Gate,
  type Grounding,
  type ParsedIntent,
  type Validation,
  type Verification,
  type Window,
} from "@/lib/pipeline";
import { numeric, radius, space, transition } from "@/lib/theme";

/* ------------------------------------------------------------------ intent */

const INTENT_LABEL: Record<string, string> = {
  revenue_diagnosis: "Revenue diagnosis",
  reconciliation_status: "Reconciliation status",
  failure_analysis: "Failure analysis",
  refund_analysis: "Refund analysis",
  chargeback_analysis: "Chargeback analysis",
};

/**
 * The entire surface through which a model influences this run.
 *
 * Worth its own panel because the architecture's central claim is that the
 * surface is this small. A reader who is told "the model never produces a
 * number" and shown nothing has been asked to take it on faith; a reader shown
 * a routing decision and two dates can check it.
 */
export function IntentPanel({ intent }: { intent: ParsedIntent }) {
  const { t } = useTheme();
  const confidence = Number(intent.confidence);

  return (
    <Stack gap={3}>
      <Row gap={2.5}>
        <Pill tone="accent">{INTENT_LABEL[intent.intent] ?? intent.intent}</Pill>
        {Number.isFinite(confidence) ? (
          <span style={{ ...numeric, fontSize: "11.5px", color: t.textMuted }}>
            confidence {intent.confidence}
          </span>
        ) : null}
        {intent.model ? (
          <span style={{ fontSize: "11.5px", color: t.textFaint }}>
            {intent.model}
            {intent.inputTokens !== null ? (
              <span style={numeric}>
                {" "}
                · {intent.inputTokens} in / {intent.outputTokens ?? 0} out
              </span>
            ) : null}
          </span>
        ) : null}
      </Row>

      <Row gap={2.5} align="stretch">
        <WindowChip label="Analysis window" window={intent.period} />
        <WindowChip label="Compared against" window={intent.comparison} />
      </Row>

      <span style={{ fontSize: "11.5px", color: t.textFaint, lineHeight: 1.55 }}>
        This is everything the model chose. No figure below was proposed, adjusted, or
        approved by it.
      </span>
    </Stack>
  );
}

function WindowChip({ label, window }: { label: string; window: Window | null }) {
  const { t } = useTheme();
  return (
    <div
      style={{
        flex: "1 1 180px",
        padding: `${space(2)} ${space(3)}`,
        borderRadius: radius.sm,
        backgroundColor: t.sunken,
        border: `1px solid ${t.border}`,
        display: "flex",
        flexDirection: "column",
        gap: space(0.5),
      }}
    >
      <span style={{ fontSize: "10.5px", fontWeight: 600, color: t.textFaint }}>{label}</span>
      <span style={{ ...numeric, fontSize: "12.5px", fontWeight: 600, color: t.text }}>
        {window ? `[${window.from}, ${window.to})` : "none"}
      </span>
    </div>
  );
}

export function ClarificationPanel({ asked }: { asked: Clarification }) {
  const { t } = useTheme();
  return (
    <Stack gap={2}>
      <Row gap={2.5}>
        <Pill tone="warning">{asked.reason}</Pill>
        {asked.confidence ? (
          <span style={{ ...numeric, fontSize: "11.5px", color: t.textMuted }}>
            confidence {asked.confidence}
          </span>
        ) : null}
      </Row>
      <span style={{ fontSize: "13.5px", color: t.text, lineHeight: 1.6 }}>{asked.question}</span>
      <span style={{ fontSize: "11.5px", color: t.textFaint, lineHeight: 1.55 }}>
        Nothing ran. A window guessed here would have reached every node in the plan at once.
      </span>
    </Stack>
  );
}

/* ------------------------------------------------------------------- gates */

const GATE_LABEL: Record<string, string> = {
  INVALID_PLAN_SCHEMA: "The plan matches the execution-plan schema",
  UNKNOWN_TOOL: "Every tool named is registered at the version asked for",
  INVALID_DAG: "The graph resolves and has no cycle",
  INVALID_PERIOD: "Each window starts before it ends",
  OVERLAPPING_PERIODS: "The comparison window does not overlap the analysis window",
  PERIOD_OUT_OF_RANGE: "Both windows sit inside the available data",
  UNSUPPORTED_CURRENCY: "The currency is one this merchant settles in",
  MERCHANT_SCOPE_VIOLATION: "The plan names the merchant this session is scoped to",
  INSUFFICIENT_PERMISSION: "The caller's role permits every node",
  MISSING_TOOL_INPUT: "Every tool was given the inputs it declares",
  UNRESOLVED_INPUT_REFERENCE: "Every referenced value comes from a node this one waits for",
};

export function GatePanel({ validation }: { validation: Validation }) {
  const { t } = useTheme();
  return (
    <Stack gap={3}>
      <Row gap={2.5} style={{ justifyContent: "space-between" }}>
        <SectionLabel>
          {validation.gates.length} gates · {validation.applied} applied
        </SectionLabel>
        <span style={{ fontSize: "11.5px", color: t.textFaint }}>
          {validation.approved ? "Nothing had run yet, and nothing was refused" : "Nothing ran"}
        </span>
      </Row>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 300px), 1fr))",
          gap: space(1.5),
        }}
      >
        {validation.gates.map((gate, index) => (
          <GateRow key={gate.code} gate={gate} index={index} />
        ))}
      </div>
    </Stack>
  );
}

function GateRow({ gate, index }: { gate: Gate; index: number }) {
  const { t } = useTheme();
  const colour =
    gate.status === "refused" ? t.negative : gate.status === "passed" ? t.positive : t.textFaint;
  const Icon = gate.status === "refused" ? X : gate.status === "passed" ? Check : Minus;

  return (
    <div
      data-testid={`gate-${gate.code}`}
      data-status={gate.status}
      className="rm-rise"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: space(2),
        padding: `${space(1.5)} ${space(2)}`,
        borderRadius: radius.sm,
        backgroundColor: gate.status === "refused" ? t.negativeSoft : "transparent",
        // Staggered so eleven gates read as a sweep rather than a flash. The
        // delay is a function of the index, not of a timer, so a replay looks
        // the same as the live run.
        animation: `rm-rise 220ms ease-out ${index * 25}ms both`,
      }}
    >
      <Icon size={13} color={colour} style={{ flexShrink: 0, marginTop: "2px" }} />
      <div style={{ display: "flex", flexDirection: "column", gap: "1px", minWidth: 0 }}>
        <span
          style={{
            fontSize: "12px",
            lineHeight: 1.45,
            color: gate.status === "inapplicable" ? t.textFaint : t.text,
          }}
        >
          {GATE_LABEL[gate.code] ?? gate.code}
        </span>
        {gate.status === "inapplicable" ? (
          <span style={{ fontSize: "10.5px", color: t.textFaint }}>
            nothing in this plan to check
          </span>
        ) : null}
        {gate.status === "refused" ? <Mono>{gate.code}</Mono> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ verification */

/**
 * The five layers, in order, with the first failure stopping the rest.
 *
 * The order and the stopping are the contract, so both are on screen: a layer
 * that has not been reached is drawn as unreached rather than as pending-and-
 * probably-fine, and a blocked run leaves the layers below it visibly unrun.
 */
export function VerificationPanel({
  verification,
  active,
}: {
  verification: Verification;
  active: boolean;
}) {
  const { t } = useTheme();
  const arrived = new Map(verification.layers.map((layer) => [layer.layer, layer]));
  const blocked = verification.layers.find((layer) => !layer.passed);
  const total = verification.layers.reduce((sum, layer) => sum + layer.checks, 0);

  // An older trace reported only the total. Listing five layers as "waiting"
  // beside a finished verdict would describe a pass that is already over.
  const rundown = verification.layers.length > 0 || active;

  return (
    <Stack gap={2}>
      {(rundown ? LAYERS : []).map((layer, index) => {
        const result = arrived.get(layer.name);
        const stopped = blocked !== undefined && index > blocked.index;
        const running = active && !result && !stopped && arrived.size === index;
        return (
          <LayerRow
            key={layer.name}
            index={index}
            name={layer.name}
            summary={layer.summary}
            checks={result?.checks}
            durationMs={result?.durationMs}
            failures={result?.failures ?? []}
            passed={result?.passed}
            running={running}
            unreached={stopped}
          />
        );
      })}

      {verification.finished ? (
        <Row gap={2.5} style={{ paddingTop: space(1) }}>
          <Pill tone={verification.finished.passed ? "positive" : "negative"}>
            {verification.finished.passed
              ? `all ${verification.finished.checks.toLocaleString("en-IN")} checks passed`
              : `blocked at ${verification.finished.blockedAt}`}
          </Pill>
          {verification.finished.passed && total > 0 ? (
            <span style={{ fontSize: "11.5px", color: t.textFaint }}>
              Every published figure may now be phrased. Nothing before this point could be.
            </span>
          ) : null}
        </Row>
      ) : null}
    </Stack>
  );
}

function LayerRow({
  index,
  name,
  summary,
  checks,
  durationMs,
  failures,
  passed,
  running,
  unreached,
}: {
  index: number;
  name: string;
  summary: string;
  checks?: number;
  durationMs?: number;
  failures: string[];
  passed?: boolean;
  running: boolean;
  unreached: boolean;
}) {
  const { t } = useTheme();
  const [open, setOpen] = useState(false);
  const state = passed === true ? "passed" : passed === false ? "failed" : running ? "running" : "waiting";
  const colour =
    state === "passed"
      ? t.positive
      : state === "failed"
        ? t.negative
        : state === "running"
          ? t.accent
          : t.textFaint;

  return (
    <div
      data-testid={`layer-${name}`}
      data-state={unreached ? "unreached" : state}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: space(1.5),
        padding: `${space(2.5)} ${space(3)}`,
        borderRadius: radius.sm,
        border: `1px solid ${state === "failed" ? t.negative : t.border}`,
        backgroundColor: state === "failed" ? t.negativeSoft : t.sunken,
        opacity: unreached ? 0.5 : 1,
        transition: `opacity ${transition.base}, border-color ${transition.base}`,
      }}
    >
      <Row gap={2.5} style={{ justifyContent: "space-between" }}>
        <Row gap={2.5} wrap={false} style={{ minWidth: 0 }}>
          <span
            style={{
              ...numeric,
              fontSize: "11px",
              fontWeight: 700,
              color: colour,
              width: "14px",
              flexShrink: 0,
            }}
          >
            {index + 1}
          </span>
          <span style={{ fontSize: "12.5px", fontWeight: 650, color: t.text, flexShrink: 0 }}>
            {name}
          </span>
          <span
            style={{
              fontSize: "11.5px",
              color: t.textMuted,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {summary}
          </span>
        </Row>

        <Row gap={2} wrap={false}>
          {checks !== undefined ? (
            <span style={{ ...numeric, fontSize: "11.5px", color: t.textMuted }}>
              {checks.toLocaleString("en-IN")} checks
              {durationMs !== undefined ? ` · ${durationMs} ms` : ""}
            </span>
          ) : null}
          {unreached ? (
            <span style={{ fontSize: "10.5px", color: t.textFaint }}>not reached</span>
          ) : (
            <Badge
              color={
                state === "passed"
                  ? "positive"
                  : state === "failed"
                    ? "negative"
                    : state === "running"
                      ? "notice"
                      : "neutral"
              }
            >
              {state}
            </Badge>
          )}
        </Row>
      </Row>

      {failures.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setOpen((shown) => !shown)}
            style={{
              appearance: "none",
              font: "inherit",
              display: "flex",
              alignItems: "center",
              gap: space(1),
              padding: 0,
              border: "none",
              background: "none",
              color: t.negative,
              fontSize: "11.5px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <ChevronRight
              size={12}
              style={{ transform: open ? "rotate(90deg)" : "none", transition: transition.fast }}
            />
            {failures.length} failed {failures.length === 1 ? "check" : "checks"}
          </button>
          {open ? (
            <Stack gap={1} style={{ marginTop: space(2) }}>
              {failures.map((failure) => (
                <Mono key={failure}>{failure}</Mono>
              ))}
            </Stack>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------- grounding */

/**
 * Where the wording came from, and how hard it was made to earn it.
 *
 * `attempts` is the interesting number: it is how many times a model wrote a
 * sentence that did not match the verified rows and was made to write it again.
 */
export function GroundingPanel({ grounding }: { grounding: Grounding }) {
  const { t } = useTheme();
  const written = grounding.source === "LLM";

  return (
    <Stack gap={2.5}>
      <Row gap={2}>
        <Pill tone={written ? "info" : "neutral"}>
          {written ? "written by the model" : "rendered from the template"}
        </Pill>
        <Pill tone="positive">
          {grounding.claims} grounded {grounding.claims === 1 ? "claim" : "claims"}
        </Pill>
        <Pill tone="neutral">
          {grounding.checks.toLocaleString("en-IN")} grounding checks
        </Pill>
        {grounding.attempts > 0 ? (
          <Pill tone="warning">
            {grounding.attempts} {grounding.attempts === 1 ? "rewrite" : "rewrites"}
          </Pill>
        ) : null}
      </Row>

      <span style={{ fontSize: "11.5px", color: t.textFaint, lineHeight: 1.6 }}>
        {written
          ? "Every figure in the sentence below was matched back, byte for byte, to a row that passed all five layers. A figure that did not match sent the wording back to be written again."
          : grounding.reason
            ? `The model was not used: ${grounding.reason}. The template renders the same verified figures without it — degrade the prose, never the numbers.`
            : "The template rendered the verified figures directly."}
      </span>
    </Stack>
  );
}
