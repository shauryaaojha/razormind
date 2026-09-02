/**
 * Turning an event log into something a person can watch.
 *
 * This is pure: events in, stages out, no fetching and no clock. Every screen
 * that shows a trace calls it with the same events and gets the same answer,
 * which is what makes "history and live chat render identically" a property of
 * the code rather than a thing somebody checked once.
 */

import type { TraceEvent } from "./stream";

export type StageStatus = "pending" | "running" | "done" | "failed";

export type Stage = {
  id: string;
  label: string;
  status: StageStatus;
  /** A short line under the label: the plan, the check count, the answer's origin. */
  detail?: string;
};

export type ToolRun = {
  node: string;
  tool: string;
  status: "running" | "SUCCEEDED" | "FAILED" | "SKIPPED";
  durationMs?: number;
  code?: string;
};

/** The states a run passes through, in order, with what to call each one. */
const STAGES: ReadonlyArray<{ id: string; label: string; states: string[] }> = [
  { id: "understand", label: "Understanding the question", states: ["PLANNING"] },
  { id: "validate", label: "Validating the plan", states: ["VALIDATING"] },
  { id: "execute", label: "Running the analysis", states: ["EXECUTING", "PARTIAL"] },
  { id: "verify", label: "Verifying every number", states: ["VERIFYING"] },
  { id: "explain", label: "Writing the answer", states: ["EXPLAINING", "COMPLETED"] },
];

const TERMINAL = new Set([
  "COMPLETED",
  "FAILED",
  "REJECTED",
  "BLOCKED",
  "NEEDS_CLARIFICATION",
]);

/** The last state the log reached, or `PENDING` if it has not started. */
export function statusOf(events: TraceEvent[]): string {
  const states = events.filter((event) => event.kind === "state.changed");
  const last = states[states.length - 1];
  return typeof last?.to === "string" ? last.to : "PENDING";
}

export function isFinished(events: TraceEvent[]): boolean {
  return TERMINAL.has(statusOf(events));
}

export function stagesOf(events: TraceEvent[]): Stage[] {
  const reached = new Set(
    events
      .filter((event) => event.kind === "state.changed")
      .map((event) => String(event.to)),
  );
  const status = statusOf(events);
  const stopped = status === "FAILED" || status === "REJECTED" || status === "BLOCKED";

  return STAGES.map((stage, index) => {
    const entered = stage.states.some((state) => reached.has(state));
    const later = STAGES.slice(index + 1).some((next) =>
      next.states.some((state) => reached.has(state)),
    );

    let state: StageStatus = "pending";
    if (entered && later) state = "done";
    else if (entered && TERMINAL.has(status)) state = stopped ? "failed" : "done";
    else if (entered) state = "running";
    // A run that stopped before this stage did not fail *here*; it never got
    // here. Showing it as failed would name the wrong step.

    return { id: stage.id, label: stage.label, status: state, detail: detailFor(stage.id, events) };
  });
}

function detailFor(stageId: string, events: TraceEvent[]): string | undefined {
  const find = (kind: string) => events.find((event) => event.kind === kind);

  if (stageId === "understand") {
    const clarification = find("clarification.requested");
    if (clarification) return `Asked back: ${String(clarification.reason)}`;
    return undefined;
  }
  if (stageId === "validate") {
    const rejected = find("plan.rejected");
    if (rejected) return `Rejected: ${String(rejected.code)}`;
    const plan = find("plan.built");
    if (plan && Array.isArray(plan.nodes)) return `${plan.nodes.length} tools planned`;
    return undefined;
  }
  if (stageId === "verify") {
    const verified = find("verification.finished");
    if (!verified) return undefined;
    const checks = Number(verified.checks ?? 0);
    return verified.passed
      ? `${checks.toLocaleString("en-IN")} checks passed`
      : `Blocked at ${String(verified.blocked_at)}`;
  }
  if (stageId === "explain") {
    const grounded = find("explanation.grounded");
    if (!grounded) return undefined;
    const source =
      grounded.source === "LLM" ? "written by the model" : "rendered from a template";
    return `${String(grounded.claims)} claims, ${source}`;
  }
  return undefined;
}

/** One row per tool node, in the order the log first mentions it. */
export function toolsOf(events: TraceEvent[]): ToolRun[] {
  const runs = new Map<string, ToolRun>();
  for (const event of events) {
    if (event.kind === "node.started") {
      const node = String(event.node);
      runs.set(node, { node, tool: String(event.tool ?? node), status: "running" });
    }
    if (event.kind === "node.finished") {
      const node = String(event.node);
      const existing = runs.get(node);
      runs.set(node, {
        node,
        tool: String(event.tool ?? existing?.tool ?? node),
        status: (event.status as ToolRun["status"]) ?? "SUCCEEDED",
        durationMs: typeof event.duration_ms === "number" ? event.duration_ms : undefined,
        code: typeof event.code === "string" ? event.code : undefined,
      });
    }
  }
  return [...runs.values()];
}

/** The question the run was started with, from the log itself. */
export function questionOf(events: TraceEvent[]): string | undefined {
  const created = events.find((event) => event.kind === "execution.created");
  return typeof created?.question === "string" ? created.question : undefined;
}
