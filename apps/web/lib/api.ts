/**
 * The API client. Types come from the generated contract; nothing is redeclared.
 *
 * `packages/shared-types/api.ts` is written by `task.py openapi` from the
 * running app, and `task.py check` fails if it is stale (D-53). Importing from
 * it rather than describing the responses again here is what makes a changed
 * endpoint a TypeScript error instead of an `undefined` in a browser.
 *
 * There is no money formatting in this file, or anywhere else in the web app.
 * Every value the API serves arrives with a `display` string beside it,
 * rendered by `narrative/render.py` — the same module the grounding gate
 * byte-matches against. A second implementation here would be a second answer
 * to "what does this number look like" (D-54).
 */

import type {
  EvidenceDetail,
  EvidenceIndex,
  ExceptionPage,
  ExecutionPage,
  ExecutionSummary,
  RunAccepted,
  RunPage,
} from "@shared/api";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const MERCHANT_ID = process.env.NEXT_PUBLIC_MERCHANT_ID ?? "M123";
export const USER_ID =
  process.env.NEXT_PUBLIC_USER_ID ?? "22222222-2222-4222-8222-222222222222";

const PREFIX = "/api/v1";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // Until the JWT lands the caller identifies itself with a header, and the
      // server validates the merchant against its memberships regardless (D-52).
      "X-RazorMind-User": USER_ID,
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    // The API has one error shape everywhere: { error: { code, message } }.
    // Reading `code` rather than `message` is the contract — messages are for
    // people, codes are for branches.
    const body = (await response.json().catch(() => null)) as
      | { detail?: { error?: { code?: string; message?: string } } }
      | null;
    const error = body?.detail?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "UNEXPECTED",
      error?.message ?? `${response.status} from ${path}`,
    );
  }
  return (await response.json()) as T;
}

export function startRun(message: string, clientRequestId: string): Promise<RunAccepted> {
  return request<RunAccepted>("/agent/runs", {
    method: "POST",
    body: JSON.stringify({
      merchant_id: MERCHANT_ID,
      message,
      client_request_id: clientRequestId,
    }),
  });
}

export function readExecution(executionId: string): Promise<ExecutionSummary> {
  return request<ExecutionSummary>(`/executions/${executionId}`);
}

export function listExecutions(limit = 25): Promise<ExecutionPage> {
  return request<ExecutionPage>(
    `/executions?merchant_id=${encodeURIComponent(MERCHANT_ID)}&limit=${limit}`,
  );
}

export function listEvidence(executionId: string): Promise<EvidenceIndex> {
  return request<EvidenceIndex>(`/executions/${executionId}/evidence`);
}

export function readEvidence(
  executionId: string,
  evidenceId: string,
): Promise<EvidenceDetail> {
  // An evidence id contains slashes — it is an address, not a name — so the
  // path segment is left unencoded and the route takes the rest of the URL.
  return request<EvidenceDetail>(`/executions/${executionId}/evidence/${evidenceId}`);
}

export function listRuns(from?: string, to?: string): Promise<RunPage> {
  const window = from && to ? `&from=${from}&to=${to}` : "";
  return request<RunPage>(
    `/reconciliation/runs?merchant_id=${encodeURIComponent(MERCHANT_ID)}${window}`,
  );
}

export function listExceptions(runId: string): Promise<ExceptionPage> {
  return request<ExceptionPage>(`/reconciliation/runs/${runId}/exceptions?limit=100`);
}

export function eventStreamUrl(executionId: string): string {
  return `${API_BASE}${PREFIX}/agent/runs/${executionId}/events`;
}
