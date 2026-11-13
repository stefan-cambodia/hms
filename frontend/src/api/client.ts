/**
 * Thin fetch wrapper for the HMS API.
 *
 * - Same-origin cookie session (httpOnly); the CSRF token is kept in memory
 *   and sent on every state-changing request.
 * - Errors are normalised to ApiError with the server's stable `code`, which
 *   the UI translates (never shows raw server text to staff).
 */

export const API_BASE = '/api/v1';

export interface FieldError {
  loc: (string | number)[];
  code: string;
  ctx?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly params: Record<string, unknown>;
  readonly fields: FieldError[];

  constructor(status: number, code: string, message: string, params = {}, fields: FieldError[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.params = params;
    this.fields = fields;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

async function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal, extra?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...extra };
  // Files go as multipart: the browser sets the Content-Type with its boundary.
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;

  let response: Response;
  try {
    response = await fetch(API_BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, 'NETWORK_ERROR', 'Server unreachable');
  }

  if (response.status === 204) return undefined as T;
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const data = isJson ? await response.json() : null;

  if (!response.ok) {
    const e = data?.error ?? {};
    const error = new ApiError(
      response.status,
      e.code ?? `HTTP_${response.status}`,
      e.message ?? response.statusText,
      e.params ?? {},
      e.fields ?? [],
    );
    if (response.status === 401 && path !== '/auth/login' && onUnauthorized) onUnauthorized();
    throw error;
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) => request<T>('POST', path, body ?? {}, undefined, headers),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, form),
};

/** Build a query string, skipping empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}
