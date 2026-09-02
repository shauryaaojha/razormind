/**
 * Frame parsing and stage derivation. Pure functions, so pure tests.
 *
 * Both are places where a small mistake looks like a working feature: a
 * heartbeat parsed as an event puts a blank row in the trace, and a stage that
 * never leaves "running" is a spinner with extra steps.
 */

import { describe, expect, it } from "vitest";

import { parseFrame } from "@/lib/stream";
import { isFinished, stagesOf, statusOf, toolsOf } from "@/lib/trace";

describe("SSE frames", () => {
  it("parses an event", () => {
    const frame = 'id: 4\nevent: tool\ndata: {"seq":4,"kind":"node.started","node":"revenue"}';
    expect(parseFrame(frame)).toEqual({ seq: 4, kind: "node.started", node: "revenue" });
  });

  it("ignores a heartbeat comment rather than rendering an empty row", () => {
    expect(parseFrame(": heartbeat")).toBeNull();
  });

  it("ignores a frame whose data is not JSON instead of throwing mid-stream", () => {
    expect(parseFrame("id: 1\ndata: {broken")).toBeNull();
  });
});

describe("stages", () => {
  const started = [
    { seq: 0, kind: "execution.created", question: "why?" },
    { seq: 1, kind: "state.changed", to: "PLANNING" },
  ];

  it("reports the last state the log reached", () => {
    expect(statusOf(started)).toBe("PLANNING");
    expect(statusOf([])).toBe("PENDING");
    expect(isFinished(started)).toBe(false);
  });

  it("marks a clarification as an answer, not a failure", () => {
    const asked = [
      ...started,
      { seq: 2, kind: "clarification.requested", reason: "MISSING_COMPARISON_PERIOD" },
      { seq: 3, kind: "state.changed", to: "NEEDS_CLARIFICATION" },
    ];
    expect(isFinished(asked)).toBe(true);
    const stages = stagesOf(asked);
    expect(stages[0]?.status).toBe("done");
    expect(stages[0]?.detail).toContain("MISSING_COMPARISON_PERIOD");
    // Nothing ran, so no later stage claims to have failed.
    expect(stages.slice(1).every((stage) => stage.status === "pending")).toBe(true);
  });

  it("marks the stage a rejected plan stopped at, and no stage after it", () => {
    const rejected = [
      ...started,
      { seq: 2, kind: "state.changed", to: "VALIDATING" },
      { seq: 3, kind: "plan.rejected", code: "OVERLAPPING_PERIODS" },
      { seq: 4, kind: "state.changed", to: "REJECTED" },
    ];
    const stages = stagesOf(rejected);
    expect(stages[1]?.status).toBe("failed");
    expect(stages[1]?.detail).toBe("Rejected: OVERLAPPING_PERIODS");
    expect(stages[2]?.status).toBe("pending");
  });

  it("keeps a tool that has started but not finished visible", () => {
    const running = toolsOf([
      { seq: 1, kind: "node.started", node: "revenue", tool: "finance.revenue_analysis" },
    ]);
    expect(running).toEqual([
      { node: "revenue", tool: "finance.revenue_analysis", status: "running" },
    ]);
  });

  it("does not invent a duration for a tool that never reported one", () => {
    const [tool] = toolsOf([
      { seq: 1, kind: "node.started", node: "failures", tool: "payments.failure_analysis" },
      {
        seq: 2,
        kind: "node.finished",
        node: "failures",
        tool: "payments.failure_analysis",
        status: "SKIPPED",
      },
    ]);
    expect(tool?.status).toBe("SKIPPED");
    expect(tool?.durationMs).toBeUndefined();
  });
});
