import { API_BASE_URL } from '../lib/constants';
import { supabase, supabaseAuthEnabled } from '../lib/supabase';

export class ApiError extends Error {
  code: string;
  details?: unknown;
  status: number;

  constructor(message: string, code = 'unknown_error', status = 500, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function getToken(): Promise<string | null> {
  if (supabaseAuthEnabled && supabase) {
    const { data, error } = await supabase.auth.getSession();
    if (error) return null;
    return data.session?.access_token || null;
  }
  return localStorage.getItem('nimbus_auth_token');
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(4000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err: any) {
    throw new ApiError(
      err?.message || 'Network connection failed. The backend service may be unreachable.',
      'NETWORK_FAILURE',
      0
    );
  }

  if (response.status === 401) {
    // session expired / invalid token
    localStorage.removeItem('nimbus_auth_token');
    if (supabaseAuthEnabled && supabase) void supabase.auth.signOut();
    if (!endpoint.startsWith('/auth/')) {
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
    }
  }

  if (!response.ok) {
    let errorBody: any = {};
    try {
      errorBody = await response.json();
    } catch {
      // non-JSON error body
    }
    const message = errorBody?.error?.message || errorBody?.detail || `HTTP Error ${response.status}`;
    const code = errorBody?.error?.code || `HTTP_${response.status}`;
    throw new ApiError(message, code, response.status, errorBody?.error?.details);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return (await response.json()) as T;
}

/** Build a query string, skipping empty values. */
export function qs(params: object): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
    if (v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)) continue;
    if (Array.isArray(v)) {
      for (const item of v) q.append(k, String(item));
    } else {
      q.set(k, String(v));
    }
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}
