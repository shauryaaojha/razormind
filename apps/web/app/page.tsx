"use client";

/**
 * Ask a question and watch it being answered.
 *
 * The stages tick because they are events, not a guess: the POST returns an id,
 * the stream replays and then follows `execution_events`, and each frame moves
 * something on screen. There is no spinner standing in for "something is
 * happening" — a spinner over a ninety-second reconciliation is a promise the
 * page cannot keep.
 */

import { Alert, Box, Button, Card, CardBody, Text, TextInput } from "@razorpay/blade/components";
import type { ExecutionSummary } from "@shared/api";
import { useCallback, useEffect, useRef, useState } from "react";

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
];

export default function AskPage() {
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
        // A fresh idempotency key per submission. Retrying the *same* question
        // is a new investigation; a retried *request* is not.
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

  // The record is read once the log says the run is over. Reading it earlier
  // would show an answer field that is still null and invite a second render
  // that looks like a correction.
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
      title="Ask"
      subtitle="Every figure in the answer is computed deterministically, verified in five layers, and clickable down to source records."
    >
      <Card padding="spacing.5" elevation="lowRaised">
        <CardBody>
          <Box display="flex" flexDirection="column" gap="spacing.4">
            <TextInput
              label="Your question"
              placeholder="Why did net revenue fall in August?"
              value={question}
              onChange={({ value }) => setQuestion(value ?? "")}
              isDisabled={busy}
            />
            <Box display="flex" gap="spacing.3" flexWrap="wrap" alignItems="center">
              <Button isLoading={busy} onClick={() => void ask(question)}>
                Investigate
              </Button>
              {SUGGESTIONS.map((suggestion) => (
                <Button
                  key={suggestion}
                  variant="tertiary"
                  size="xsmall"
                  isDisabled={busy}
                  onClick={() => {
                    setQuestion(suggestion);
                    void ask(suggestion);
                  }}
                >
                  {suggestion}
                </Button>
              ))}
            </Box>
            <Text size="xsmall" color="surface.text.gray.muted">
              With no model configured the intent cannot be parsed and the run fails with
              PROVIDER_UNAVAILABLE — deliberately, rather than guessing which analysis you meant.
            </Text>
          </Box>
        </CardBody>
      </Card>

      {error ? <Alert isFullWidth color="negative" title="Request failed" description={error} /> : null}

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
