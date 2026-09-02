"use client";

/**
 * A finished run, replayed.
 *
 * This page fetches the same stream endpoint the chat page does and renders the
 * result through the same `ExecutionView`. There is no history-shaped code
 * path: `execution_events` is append-only and sequenced, so replaying a run is
 * not a different rendering of it, it is the same one.
 */

import { Alert, Spinner } from "@razorpay/blade/components";
import type { ExecutionSummary } from "@shared/api";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ExecutionView } from "@/components/ExecutionView";
import { ProvenanceDrawer } from "@/components/ProvenanceDrawer";
import { Shell } from "@/components/Shell";
import { USER_ID, eventStreamUrl, readExecution } from "@/lib/api";
import { readEventStream, type TraceEvent } from "@/lib/stream";

export default function ReplayPage() {
  const params = useParams<{ id: string }>();
  const executionId = params.id;

  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [summary, setSummary] = useState<ExecutionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!executionId) return;
    const handle = readEventStream(eventStreamUrl(executionId), {
      headers: { "X-RazorMind-User": USER_ID },
      onEvent: (event) => setEvents((seen) => [...seen, event]),
      onDone: () => setLoading(false),
      onError: (failure) => {
        setError(failure instanceof Error ? failure.message : String(failure));
        setLoading(false);
      },
    });
    return () => handle.close();
  }, [executionId]);

  useEffect(() => {
    if (!executionId) return;
    let live = true;
    readExecution(executionId)
      .then((loaded) => live && setSummary(loaded))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, [executionId]);

  return (
    <Shell title="Replay" subtitle={executionId}>
      {error ? (
        <Alert isFullWidth color="negative" title="Cannot replay this run" description={error} />
      ) : null}
      {loading && events.length === 0 ? (
        <Spinner accessibilityLabel="Loading the trace" size="medium" />
      ) : (
        <ExecutionView events={events} summary={summary} onInspect={setInspecting} />
      )}
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
