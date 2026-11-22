import createClient from "openapi-fetch";
import type { paths } from "./schema";
import type { ExportName, ReportFormat } from "./types";

// openapi-fetch keeps the fetch it is given; a late-bound wrapper lets tests (msw) patch fetch.
const lateFetch: typeof fetch = (input, init) => globalThis.fetch(input, init);

// The app always talks to the server it was loaded from. location.origin rather than "" because
// Node's fetch (tests) refuses relative URLs; in a browser the two are the same.
export const client = createClient<paths>({ baseUrl: location.origin, fetch: lateFetch });

export const NETWORK_ERROR =
  "The Corelata server could not be reached; check that it is running and try again.";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The API answered 404: what was asked for does not exist (any other failure might pass). */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };
const PLACES = new Set(["body", "query", "path"]);

/** The one line to show for a failed request: the API's `detail` (spec: errors are one line). */
export function errorText(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as ValidationItem;
    const field = (first.loc ?? []).filter((part) => !PLACES.has(String(part))).join(".");
    return field ? `${field}: ${first.msg}` : String(first.msg);
  }
  return `The server answered ${status} without an explanation.`;
}

/** A request its caller cancelled: TanStack Query aborts a query nobody watches any more, when
 * the page it was for is left. That is not a network failure (CRL-40). */
function cancelled(error: unknown): boolean {
  return (error as { name?: unknown } | null)?.name === "AbortError";
}

/** The data of an API call, or an ApiError with the message to show. A cancelled request
 * rejects with its AbortError, which TanStack Query treats as a cancellation, not an error. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch (error) {
    if (cancelled(error)) throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
  if (!result.response.ok) {
    throw new ApiError(result.response.status, errorText(result.response.status, result.error));
  }
  return result.data as T;
}

/** Text or bytes from a route the typed client types as a file: the report and the exports. */
export async function unwrapText(url: string, signal?: AbortSignal): Promise<string> {
  let response: Response;
  try {
    response = await globalThis.fetch(url, { signal });
  } catch (error) {
    if (cancelled(error)) throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw new ApiError(response.status, errorText(response.status, body));
  }
  return response.text();
}

/** URLs the browser loads itself (an EventSource, a download link, the report frame). */
export function eventsUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/events`;
}

export function reportUrl(
  runId: string,
  format: ReportFormat,
  opts: { claimIds?: boolean; download?: boolean } = {},
): string {
  const params = new URLSearchParams({ format });
  if (opts.claimIds) params.set("with_claim_ids", "true");
  if (opts.download) params.set("download", "true");
  return `/api/runs/${encodeURIComponent(runId)}/report?${params}`;
}

export function exportUrl(runId: string, name: ExportName): string {
  return `/api/runs/${encodeURIComponent(runId)}/exports/${name}`;
}
