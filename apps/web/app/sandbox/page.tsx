"use client";

/**
 * The eight degradation paths, and which of them you can watch happen today.
 *
 * This page previously ran a `setTimeout` and rendered a hand-written result
 * object announcing that "the Grounding Gate caught the byte-mismatch" and
 * "Invariant 4 upheld" — a simulation of proof, on the one page whose subject
 * is proof, in a product whose whole claim is that a figure on screen can be
 * walked down to a record. Nothing was injected and no backend was called.
 *
 * So it states what is real instead. Four rows are reachable right now and say
 * how to reach them; the other four need the fault-injection switches, which
 * are Phase 10. A row that cannot be demonstrated says so rather than
 * pretending.
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, FlaskConical } from "lucide-react";

import { useTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";
import { Mono, Panel, PanelHeader, Pill, Row, Stack } from "@/components/ui";
import { radius, space, type Tone } from "@/lib/theme";

type Reachability =
  /** You can cause this today, from this build. */
  | { kind: "live"; how: ReactNode }
  /** Needs the Phase 10 fault-injection switches. */
  | { kind: "phase10" };

interface Path {
  failure: string;
  response: string;
  state: string;
  tone: Tone;
  reach: Reachability;
}

const PATHS: Path[] = [
  {
    failure: "Intent confidence below 0.75",
    response: "Ask one clarifying question rather than guessing the window",
    state: "NEEDS_CLARIFICATION",
    tone: "warning",
    reach: {
      kind: "live",
      how: (
        <>
          Ask <em>“why did net revenue fall?”</em> with no comparison period.
        </>
      ),
    },
  },
  {
    failure: "Plan invalid",
    response: "Structured rejection; nothing runs",
    state: "REJECTED",
    tone: "negative",
    reach: {
      kind: "live",
      how: <>Ask about a window outside the seeded data, such as August 2024.</>,
    },
  },
  {
    failure: "No model configured at intent time",
    response: "Refuse; never invent an intent",
    state: "FAILED · PROVIDER_UNAVAILABLE",
    tone: "negative",
    reach: {
      kind: "live",
      how: (
        <>
          Set <Mono>LLM_ENABLED=false</Mono> and ask anything.
        </>
      ),
    },
  },
  {
    failure: "Model unavailable, or grounding fails twice",
    response: "Deterministic template over the verified metrics — degrade the prose, never the numbers",
    state: "COMPLETED · TEMPLATE_FALLBACK",
    tone: "info",
    reach: {
      kind: "live",
      how: (
        <>
          Point <Mono>LLM_PROVIDER</Mono> at Groq: its free tier caps at 8,000 tokens a minute and
          the evidence brief is larger, so the explainer falls back every time.
        </>
      ),
    },
  },
  {
    failure: "Reconciliation fails",
    response: "The whole run fails; no downstream number is allowed to exist",
    state: "FAILED",
    tone: "negative",
    reach: { kind: "phase10" },
  },
  {
    failure: "A non-required tool fails",
    response: "Continue, and mark that metric unavailable in the answer rather than blank or zero",
    state: "PARTIAL → COMPLETED",
    tone: "warning",
    reach: { kind: "phase10" },
  },
  {
    failure: "Verification fails",
    response: "Block the explanation entirely — the reader sees no figures at all",
    state: "BLOCKED",
    tone: "negative",
    reach: { kind: "phase10" },
  },
  {
    failure: "A tool times out",
    response: "Counted as a tool failure, not an exception; the DAG decides what still runs",
    state: "PARTIAL → COMPLETED",
    tone: "warning",
    reach: { kind: "phase10" },
  },
];

export default function SandboxPage() {
  const { t } = useTheme();
  const live = PATHS.filter((path) => path.reach.kind === "live").length;

  return (
    <Shell
      title="Failure paths"
      subtitle="What this system does when something breaks. The rule throughout is one sentence: degrade the prose, never the numbers."
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: space(3.5),
          padding: `${space(4)} ${space(5)}`,
          borderRadius: radius.lg,
          backgroundColor: t.warningSoft,
          border: `1px solid ${t.border}`,
        }}
      >
        <AlertTriangle size={18} color={t.warning} style={{ flexShrink: 0, marginTop: "2px" }} />
        <span style={{ fontSize: "13px", lineHeight: 1.6, color: t.text }}>
          <strong>Fault injection is not built yet.</strong> {live} of the {PATHS.length} paths below
          can be triggered against this build today, and each says how. The rest need the injection
          switches, which are Phase&nbsp;10. This page deliberately shows no simulated results —
          a mocked proof of verification would be worth less than none.
        </span>
      </div>

      <Panel>
        <PanelHeader
          title="The recovery matrix"
          icon={<FlaskConical size={15} />}
          hint="From docs/05-agent-runtime.md. Every row is a real branch in the runtime, not an aspiration."
        />

        <Stack gap={2.5}>
          {PATHS.map((path) => (
            <div
              key={path.failure}
              style={{
                padding: `${space(3.5)} ${space(4)}`,
                borderRadius: radius.md,
                backgroundColor: t.sunken,
                border: `1px solid ${t.border}`,
                display: "flex",
                flexDirection: "column",
                gap: space(2),
              }}
            >
              <Row gap={2.5} style={{ justifyContent: "space-between" }}>
                <span style={{ fontSize: "13.5px", fontWeight: 600, color: t.text }}>
                  {path.failure}
                </span>
                <Row gap={2} wrap={false}>
                  <Pill tone={path.tone}>{path.state}</Pill>
                  <Pill tone={path.reach.kind === "live" ? "positive" : "neutral"}>
                    {path.reach.kind === "live" ? "reachable now" : "Phase 10"}
                  </Pill>
                </Row>
              </Row>

              <span style={{ fontSize: "12.5px", color: t.textMuted, lineHeight: 1.55 }}>
                {path.response}
              </span>

              {path.reach.kind === "live" ? (
                <span
                  style={{
                    fontSize: "12px",
                    color: t.textFaint,
                    lineHeight: 1.55,
                    paddingTop: space(1),
                    borderTop: `1px solid ${t.border}`,
                  }}
                >
                  <strong style={{ color: t.textMuted }}>Try it: </strong>
                  {path.reach.how}
                </span>
              ) : null}
            </div>
          ))}
        </Stack>
      </Panel>

      <Panel>
        <PanelHeader
          title="Why the two model failures are not one case"
          hint="Losing the model at explanation time costs phrasing. Losing it at intent time costs the question."
        />
        <p style={{ margin: 0, fontSize: "13.5px", lineHeight: 1.7, color: t.textMuted, maxWidth: "78ch" }}>
          The template can render verified metrics without a model, so an explainer that dies is a
          prose problem. Nothing can render a question nobody parsed — the only thing that knows
          which analysis was asked for is the model — so an intent parser that dies is the end of
          the run. A canned intent would answer a question nobody asked, verified and cited, with
          nothing anywhere indicating that no model was consulted.
        </p>
        <div style={{ marginTop: space(4) }}>
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
            Try one of the reachable paths <ArrowRight size={14} />
          </Link>
        </div>
      </Panel>
    </Shell>
  );
}
