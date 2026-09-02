"use client";

/**
 * Ask a question and watch it being answered.
 *
 * The stages tick because they are events, not a guess: the POST returns an id,
 * the stream replays and then follows `execution_events`, and each frame moves
 * something on screen.
 */

import { Alert, Badge, Box, Button, Card, CardBody, Text, TextInput } from "@razorpay/blade/components";
import { ArrowRight, HelpCircle, Info, MessageSquare, Search, Sparkles, Zap } from "lucide-react";
import type { ExecutionSummary } from "@shared/api";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppTheme } from "@/app/providers";
import { ExecutionView } from "@/components/ExecutionView";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { USER_ID, eventStreamUrl, readExecution, startRun } from "@/lib/api";
import { readEventStream, type StreamHandle, type TraceEvent } from "@/lib/stream";
import { isFinished } from "@/lib/trace";

const SUGGESTIONS = [
  "Why did net revenue fall in August?",
  "How is reconciliation looking for August?",
  "What happened to our payment success rate?",
  "Check fee discrepancies on zero-MDR transactions",
];

export default function AskPage() {
  const { isDark } = useAppTheme();
  const [question, setQuestion] = useState("");
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [summary, setSummary] = useState<ExecutionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stream = useRef<StreamHandle | null>(null);

  const ask = useCallback(
    async (text: string) => {
      if (!text.trim() || busy) return;
      stream.current?.close();
      setBusy(true);
      setError(null);
      setEvents([]);
      setSummary(null);
      try {
        const accepted = await startRun(text.trim(), crypto.randomUUID());
        setExecutionId(accepted.execution_id);
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : String(failure));
        setBusy(false);
      }
    },
    [busy],
  );

  useEffect(() => {
    if (!executionId) return;
    const handle = readEventStream(eventStreamUrl(executionId), {
      headers: { "X-RazorMind-User": USER_ID },
      onEvent: (event) => setEvents((seen) => [...seen, event]),
      onDone: () => setBusy(false),
      onError: (failure) => {
        setError(failure instanceof Error ? failure.message : String(failure));
        setBusy(false);
      },
    });
    stream.current = handle;
    return () => handle.close();
  }, [executionId]);

  useEffect(() => {
    if (!executionId || !isFinished(events)) return;
    let live = true;
    readExecution(executionId)
      .then((loaded) => live && setSummary(loaded))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [executionId, events]);

  return (
    <Shell
      title="AI Financial Investigation Studio"
      subtitle="Every figure in the answer is computed deterministically, verified across 5 layers, and clickable down to source records."
    >
      {/* Query Card */}
      <div
        style={{
          padding: "24px",
          borderRadius: "14px",
          backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
          border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
          display: "flex",
          flexDirection: "column",
          gap: "16px",
          boxShadow: isDark ? "0 4px 24px rgba(0,0,0,0.3)" : "0 4px 20px rgba(0,0,0,0.04)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <label
            style={{
              fontSize: "13px",
              fontWeight: 600,
              color: isDark ? "#F8FAFC" : "#0F172A",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <Search size={15} color="#0C83FF" />
            <span>Investigate Financial Query</span>
          </label>

          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: "280px" }}>
              <TextInput
                label=""
                placeholder="Ask about revenue movement, decline causes, or reconciliation health..."
                value={question}
                onChange={({ value }) => setQuestion(value ?? "")}
                isDisabled={busy}
              />
            </div>
            <button
              onClick={() => void ask(question)}
              disabled={busy || !question.trim()}
              style={{
                padding: "10px 24px",
                borderRadius: "8px",
                backgroundColor: "#0C83FF",
                color: "#FFFFFF",
                fontWeight: 600,
                fontSize: "14px",
                border: "none",
                cursor: busy || !question.trim() ? "not-allowed" : "pointer",
                opacity: busy || !question.trim() ? 0.6 : 1,
                boxShadow: "0 2px 10px rgba(12, 131, 255, 0.35)",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                transition: "all 0.15s ease",
              }}
            >
              <Zap size={16} />
              <span>{busy ? "Investigating..." : "Investigate"}</span>
            </button>
          </div>
        </div>

        {/* Suggestion Pills */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <span style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B", fontWeight: 500 }}>
            Suggested:
          </span>
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              disabled={busy}
              onClick={() => {
                setQuestion(suggestion);
                void ask(suggestion);
              }}
              style={{
                padding: "5px 12px",
                borderRadius: "20px",
                fontSize: "12px",
                fontWeight: 500,
                border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
                color: isDark ? "#CBD5E1" : "#334155",
                cursor: busy ? "not-allowed" : "pointer",
                transition: "all 0.15s ease",
              }}
            >
              {suggestion}
            </button>
          ))}
        </div>

        <div
          style={{
            fontSize: "11px",
            color: isDark ? "#64748B" : "#94A3B8",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <Info size={13} />
          <span>
            With no model configured, the intent cannot be parsed and fails with PROVIDER_UNAVAILABLE
            deliberately, rather than guessing which analysis you meant.
          </span>
        </div>
      </div>

      {error ? (
        <Alert isFullWidth color="negative" title="Request failed" description={error} />
      ) : null}

      {events.length > 0 ? (
        <ExecutionView events={events} summary={summary} onInspect={setInspecting} />
      ) : null}

      {executionId ? (
        <ProvenanceDrawer
          executionId={executionId}
          evidenceId={inspecting}
          onDismiss={() => setInspecting(null)}
        />
      ) : null}
    </Shell>
  );
}
