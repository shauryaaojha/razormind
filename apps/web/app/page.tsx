"use client";

/**
 * Ask a question and watch it being answered.
 *
 * The stages tick because they are events, not a guess: the POST returns an id,
 * the stream replays and then follows `execution_events`, and each frame moves
 * something on screen.
 */

import { Alert } from "@razorpay/blade/components";
import type { ExecutionSummary } from "@shared/api";
import { ArrowUp, Info, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useTheme } from "@/app/providers";
import { ExecutionView } from "@/components/ExecutionView";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { Panel, Row, SectionLabel, Stack } from "@/components/ui";
import { USER_ID, eventStreamUrl, readExecution, startRun } from "@/lib/api";
import { readEventStream, type StreamHandle, type TraceEvent } from "@/lib/stream";
import { radius, space, transition } from "@/lib/theme";
import { isFinished } from "@/lib/trace";

/**
 * One question per analysis the planner knows how to route, and two that are
 * meant to be refused.
 *
 * The refusals are on the page rather than tucked into a demo script because
 * they are the half of the behaviour that is hard to believe: a system that
 * answers is ordinary, and a system that declines to answer — with nothing
 * computed and a code saying why — is the part worth being able to try. The
 * captions describe the *question*, not the outcome; what actually happens
 * shows up in the trace below, whatever it is.
 */
const GALLERY: { label: string; hint: string; items: { text: string; note: string }[] }[] = [
  {
    label: "Ask",
    hint: "Each of these routes to a different analysis.",
    items: [
      {
        text: "Why did net revenue fall in July 2026 compared with June 2026?",
        note: "the full bridge — four tools",
      },
      { text: "How is reconciliation looking for July 2026?", note: "one tool, no comparison" },
      {
        text: "What happened to our payment success rate in July 2026 against June 2026?",
        note: "decline taxonomy by method",
      },
      {
        text: "Which refund reasons drove the most value in July 2026 compared with June 2026?",
        note: "refunds by reason",
      },
      {
        text: "How did chargebacks move in July 2026 against June 2026?",
        note: "disputes and their value",
      },
    ],
  },
  {
    label: "Watch it refuse",
    hint: "Nothing runs, nothing is computed, and the run says which gate stopped it.",
    items: [
      { text: "Why did net revenue fall?", note: "no comparison window given" },
      {
        text: "How did revenue do in August 2024 compared with July 2024?",
        note: "outside the seeded data",
      },
    ],
  },
];

export default function AskPage() {
  const { t } = useTheme();
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

  const canSend = Boolean(question.trim()) && !busy;

  return (
    <Shell
      title="Ask"
      subtitle="Every figure in the answer is computed deterministically, verified across five layers, and clickable down to the source records it came from."
    >
      <Panel padding={0}>
        <Stack gap={0}>
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: space(3),
              padding: space(4),
            }}
          >
            <Search size={17} color={t.textFaint} style={{ marginBottom: space(2.5) }} />
            <textarea
              value={question}
              rows={1}
              disabled={busy}
              placeholder="Ask about revenue movement, decline causes, or reconciliation health…"
              onChange={(event) => {
                setQuestion(event.target.value);
                event.target.style.height = "auto";
                event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void ask(question);
                }
              }}
              style={{
                flex: 1,
                resize: "none",
                appearance: "none",
                border: "none",
                outline: "none",
                background: "transparent",
                color: t.text,
                font: "inherit",
                fontSize: "15px",
                lineHeight: 1.6,
                padding: `${space(2)} 0`,
                maxHeight: "160px",
              }}
            />
            <button
              type="button"
              onClick={() => void ask(question)}
              disabled={!canSend}
              aria-label="Run the investigation"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "34px",
                height: "34px",
                flexShrink: 0,
                borderRadius: radius.md,
                border: "none",
                backgroundColor: canSend ? t.accent : t.surfaceHover,
                color: canSend ? t.textOnAccent : t.textFaint,
                boxShadow: canSend ? t.shadowAccent : "none",
                cursor: canSend ? "pointer" : "not-allowed",
                transition: `background-color ${transition.fast}, box-shadow ${transition.fast}`,
              }}
            >
              <ArrowUp size={17} strokeWidth={2.5} />
            </button>
          </div>

          <div
            style={{
              borderTop: `1px solid ${t.border}`,
              padding: `${space(3)} ${space(4)}`,
              backgroundColor: t.sunken,
              borderBottomLeftRadius: radius.lg,
              borderBottomRightRadius: radius.lg,
            }}
          >
            <Stack gap={3}>
              {GALLERY.map((group) => (
                <Stack key={group.label} gap={2}>
                  <Row gap={2}>
                    <SectionLabel>{group.label}</SectionLabel>
                    <span style={{ fontSize: "11px", color: t.textFaint }}>{group.hint}</span>
                  </Row>
                  <Row gap={2}>
                    {group.items.map((item) => (
                      <button
                        key={item.text}
                        type="button"
                        disabled={busy}
                        title={item.note}
                        onClick={() => {
                          setQuestion(item.text);
                          void ask(item.text);
                        }}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "flex-start",
                          gap: space(0.5),
                          padding: `${space(2)} ${space(3)}`,
                          borderRadius: radius.md,
                          font: "inherit",
                          fontSize: "12px",
                          fontWeight: 500,
                          textAlign: "left",
                          border: `1px solid ${t.border}`,
                          backgroundColor: t.surface,
                          color: t.textMuted,
                          cursor: busy ? "not-allowed" : "pointer",
                          opacity: busy ? 0.5 : 1,
                          transition: `border-color ${transition.fast}, color ${transition.fast}`,
                        }}
                        onMouseEnter={(event) => {
                          if (busy) return;
                          event.currentTarget.style.borderColor = t.accentBorder;
                          event.currentTarget.style.color = t.text;
                        }}
                        onMouseLeave={(event) => {
                          event.currentTarget.style.borderColor = t.border;
                          event.currentTarget.style.color = t.textMuted;
                        }}
                      >
                        <span>{item.text}</span>
                        <span style={{ fontSize: "10.5px", color: t.textFaint }}>{item.note}</span>
                      </button>
                    ))}
                  </Row>
                </Stack>
              ))}
            </Stack>
          </div>
        </Stack>
      </Panel>

      <Row gap={2} align="flex-start" style={{ fontSize: "12px", color: t.textFaint }}>
        <Info size={14} style={{ flexShrink: 0, marginTop: "1px" }} />
        <span style={{ lineHeight: 1.5, maxWidth: "80ch" }}>
          The model only parses your question into an intent and phrases the result. If it is
          unavailable, or the period is ambiguous, the run says so instead of guessing — and the
          numbers are computed and verified either way.
        </span>
      </Row>

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
