/**
 * The run's internals, read out of the same event log the stepper reads.
 *
 * `lib/trace.ts` answers "which stage is it on". This answers "what is it
 * actually doing", and every answer here is a payload the API emitted rather
 * than a shape this file knows how to draw. That distinction is the whole
 * point: a pipeline diagram built from a hardcoded list of stages is an
 * illustration, and an illustration of a system that verifies things is worth
 * nothing, because it looks exactly the same when the system is broken.
 *
 * So: eleven gates because the validator reported eleven, five layers in the
 * order they finished because the verifier announced each one as it finished,
 * a graph with the edges the planner actually built. A run that stops at layer
 * two draws two layers.
 *
 * Pure, like `trace.ts`. No fetching, no clock, no randomness -- the same
 * events render the same markup, live or replayed an hour later.
 */

import type { TraceEvent } from "./stream";

/* ------------------------------------------------------------------ intent */

export type Window = { from: string; to: string };

/**
 * What the model was allowed to decide, and what it cost.
 *
 * A routing decision and two windows. There is no number in here that anybody
 * reads as money, which is the claim the whole architecture rests on, and
 * putting it on screen is how that claim stops being a sentence in a document.
 */
export type ParsedIntent = {
  intent: string;
  period: Window | null;
  comparison: Window | null;
  confidence: string;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
};

export function intentOf(events: TraceEvent[]): ParsedIntent | null {
  const parsed = events.find((event) => event.kind === "intent.parsed");
  if (!parsed) return null;
  return {
    intent: String(parsed.intent),
    period: asWindow(parsed.period),
    comparison: asWindow(parsed.comparison_period),
    confidence: String(parsed.confidence_ratio ?? ""),
    model: typeof parsed.model === "string" ? parsed.model : null,
    inputTokens: typeof parsed.input_tokens === "number" ? parsed.input_tokens : null,
    outputTokens: typeof parsed.output_tokens === "number" ? parsed.output_tokens : null,
  };
}

/** The question asked back, when the parser refused to guess. */
export type Clarification = {
  question: string;
  reason: string;
  confidence: string | null;
};

export function clarificationOf(events: TraceEvent[]): Clarification | null {
  const asked = events.find((event) => event.kind === "clarification.requested");
  if (!asked) return null;
  return {
    question: String(asked.question),
    reason: String(asked.reason),
    confidence: typeof asked.confidence_ratio === "string" ? asked.confidence_ratio : null,
  };
}

function asWindow(value: unknown): Window | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (typeof record.from !== "string" || typeof record.to !== "string") return null;
  return { from: record.from, to: record.to };
}

/* ------------------------------------------------------------------- gates */

export type GateStatus = "passed" | "refused" | "inapplicable";

export type Gate = {
  code: string;
  status: GateStatus;
};

export type Validation = {
  approved: boolean;
  gates: Gate[];
  /** How many gates had something to judge. Not always eleven. */
  applied: number;
  refused: string[];
};

export function validationOf(events: TraceEvent[]): Validation | null {
  const validated = events.find((event) => event.kind === "plan.validated");
  if (!validated || !Array.isArray(validated.gates)) return null;

  const gates = (validated.gates as Record<string, unknown>[]).map((gate) => ({
    code: String(gate.code),
    status: (!gate.passed ? "refused" : gate.applied ? "passed" : "inapplicable") as GateStatus,
  }));

  return {
    approved: validated.approved === true,
    gates,
    applied: gates.filter((gate) => gate.status !== "inapplicable").length,
    refused: Array.isArray(validated.refused) ? validated.refused.map(String) : [],
  };
}

/** The one-line reason a plan was refused, when the panel above is absent. */
export function rejectionOf(events: TraceEvent[]): string | null {
  const rejected = events.find((event) => event.kind === "plan.rejected");
  return rejected ? String(rejected.code) : null;
}

/* --------------------------------------------------------------------- dag */

export type NodeStatus = "pending" | "running" | "SUCCEEDED" | "FAILED" | "SKIPPED";

export type GraphNode = {
  id: string;
  tool: string;
  version: string | null;
  dependsOn: string[];
  required: boolean;
  /** The tier it runs in. Everything in one tier runs at once. */
  layer: number;
  status: NodeStatus;
  durationMs?: number;
  /** Metric *names*, never values: nothing here has been verified yet. */
  metrics: string[];
  evidenceRows?: number;
  code?: string;
  blockedBy: string[];
};

/**
 * The plan as a graph, with each node's live state folded in.
 *
 * Built from `plan.built` when it carries a graph, so the nodes that have not
 * started yet are on screen from the moment the plan exists -- a DAG that grows
 * a node at a time shows the shape only once it no longer matters. Falls back
 * to the nodes the tool events mention, which is what an older trace has.
 */
export function graphOf(events: TraceEvent[]): GraphNode[] {
  const nodes = new Map<string, GraphNode>();

  const plan = events.find((event) => event.kind === "plan.built");
  if (plan && Array.isArray(plan.graph)) {
    for (const entry of plan.graph as Record<string, unknown>[]) {
      const id = String(entry.id);
      nodes.set(id, {
        id,
        tool: String(entry.tool ?? id),
        version: typeof entry.version === "string" ? entry.version : null,
        dependsOn: Array.isArray(entry.depends_on) ? entry.depends_on.map(String) : [],
        required: entry.required === true,
        layer: typeof entry.layer === "number" ? entry.layer : 0,
        status: "pending",
        metrics: [],
        blockedBy: [],
      });
    }
  }

  const reach = (event: TraceEvent): GraphNode => {
    const id = String(event.node);
    const held = nodes.get(id);
    if (held) return held;
    const fresh: GraphNode = {
      id,
      tool: String(event.tool ?? id),
      version: typeof event.version === "string" ? event.version : null,
      dependsOn: Array.isArray(event.depends_on) ? event.depends_on.map(String) : [],
      required: event.required === true,
      layer: typeof event.layer === "number" ? event.layer : 0,
      status: "pending",
      metrics: [],
      blockedBy: [],
    };
    nodes.set(id, fresh);
    return fresh;
  };

  for (const event of events) {
    if (event.kind === "node.started") {
      const node = reach(event);
      nodes.set(node.id, { ...node, status: "running" });
    }
    if (event.kind === "node.finished") {
      const node = reach(event);
      nodes.set(node.id, {
        ...node,
        status: (event.status as NodeStatus) ?? "SUCCEEDED",
        durationMs: typeof event.duration_ms === "number" ? event.duration_ms : undefined,
        metrics: Array.isArray(event.metrics) ? event.metrics.map(String) : [],
        evidenceRows: typeof event.evidence_rows === "number" ? event.evidence_rows : undefined,
        code: typeof event.code === "string" ? event.code : undefined,
        blockedBy: Array.isArray(event.blocked_by) ? event.blocked_by.map(String) : [],
      });
    }
  }

  // Tier first, then the order the plan listed them. Alphabetical would be
  // just as deterministic and would scramble a reading order the planner chose
  // -- revenue before refunds before chargebacks is how the bridge is read.
  const written = [...nodes.keys()];
  return [...nodes.values()].sort(
    (a, b) => a.layer - b.layer || written.indexOf(a.id) - written.indexOf(b.id),
  );
}

/** The nodes grouped by tier, in running order. Empty tiers cannot occur. */
export function tiersOf(nodes: GraphNode[]): GraphNode[][] {
  const depth = [...new Set(nodes.map((node) => node.layer))].sort((a, b) => a - b);
  return depth.map((layer) => nodes.filter((node) => node.layer === layer));
}

/* ------------------------------------------------------------ verification */

/** The five, in the order they run. Rendered before any of them has finished. */
export const LAYERS = [
  {
    name: "TYPE",
    summary: "Every output field matches its model, and no float is anywhere near money.",
  },
  { name: "RANGE", summary: "Every published value sits inside the range its metric declares." },
  { name: "CONSISTENCY", summary: "Two tools computing one quantity agree, exactly." },
  {
    name: "FORMULA",
    summary:
      "Every derived metric is re-evaluated from its own declared expression, through a grammar that cannot call the tool that produced it.",
  },
  {
    name: "SOURCE",
    summary:
      "Every cited record exists, sits inside the period, and re-folds to the figure published from it.",
  },
] as const;

export type VerificationLayer = {
  layer: string;
  index: number;
  checks: number;
  failures: string[];
  passed: boolean;
  durationMs: number;
};

export type Verification = {
  layers: VerificationLayer[];
  /** Set once the pass is over. Absent while the layers are still arriving. */
  finished: { passed: boolean; blockedAt: string | null; checks: number } | null;
};

export function verificationOf(events: TraceEvent[]): Verification {
  const layers: VerificationLayer[] = [];
  for (const event of events) {
    if (event.kind !== "verification.layer") continue;
    layers.push({
      layer: String(event.layer),
      index: typeof event.index === "number" ? event.index : layers.length,
      checks: Number(event.checks ?? 0),
      failures: Array.isArray(event.failures) ? event.failures.map(String) : [],
      passed: event.passed === true,
      durationMs: Number(event.duration_ms ?? 0),
    });
  }

  const done = events.find((event) => event.kind === "verification.finished");
  return {
    layers,
    finished: done
      ? {
          passed: done.passed === true,
          blockedAt: typeof done.blocked_at === "string" ? done.blocked_at : null,
          checks: Number(done.checks ?? 0),
        }
      : null,
  };
}

/* --------------------------------------------------------------- grounding */

export type Grounding = {
  source: string;
  attempts: number;
  claims: number;
  checks: number;
  reason: string | null;
};

export function groundingOf(events: TraceEvent[]): Grounding | null {
  const grounded = events.find((event) => event.kind === "explanation.grounded");
  if (!grounded) return null;
  return {
    source: String(grounded.source),
    attempts: Number(grounded.attempts ?? 0),
    claims: Number(grounded.claims ?? 0),
    checks: Number(grounded.checks ?? 0),
    reason: typeof grounded.reason === "string" ? grounded.reason : null,
  };
}
