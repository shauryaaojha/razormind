/**
 * Reading an execution's event stream. One function for live and for history.
 *
 * The API replays `execution_events` from the requested sequence and then
 * follows the run, so a finished execution and a running one are the same
 * request against the same rows. Reading them with one function is how that
 * stops being a claim in a document and becomes a thing the code cannot get
 * wrong — there is no second path for history to drift down.
 *
 * `fetch` with a stream reader rather than `EventSource`, for two reasons that
 * both matter here. `EventSource` reconnects automatically when the server
 * closes the stream, so a finished run would be replayed forever. And it cannot
 * send headers, which this API needs for the caller identity.
 */

export type TraceEvent = {
  seq: number;
  kind: string;
  [key: string]: unknown;
};

export type StreamHandle = { close: () => void };

/**
 * Read every event from `fromSeq` onward, calling `onEvent` as each arrives.
 *
 * Returns a handle that aborts the request. Callers must use it: an unaborted
 * stream on an unmounted page holds a connection open for the life of the tab.
 */
export function readEventStream(
  url: string,
  options: {
    headers?: Record<string, string>;
    fromSeq?: number;
    onEvent: (event: TraceEvent) => void;
    onDone?: () => void;
    onError?: (error: unknown) => void;
  },
): StreamHandle {
  const controller = new AbortController();
  const target = options.fromSeq ? `${url}?from_seq=${options.fromSeq}` : url;

  void (async () => {
    try {
      const response = await fetch(target, {
        headers: { Accept: "text/event-stream", ...(options.headers ?? {}) },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`stream failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line. Anything after the last
        // separator is a partial frame and stays in the buffer.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const event = parseFrame(frame);
          if (event) options.onEvent(event);
        }
      }
      options.onDone?.();
    } catch (error) {
      if (controller.signal.aborted) return;
      options.onError?.(error);
    }
  })();

  return { close: () => controller.abort() };
}

/** One SSE frame into an event, or null for a heartbeat comment. */
export function parseFrame(frame: string): TraceEvent | null {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice("data: ".length))
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as TraceEvent;
  } catch {
    return null;
  }
}
