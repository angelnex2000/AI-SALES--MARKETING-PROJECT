"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Shared data-fetching primitives. Every API-backed page needs the same four
 * states (loading / error / empty / data) plus a stale-response guard, so that
 * logic lives here once instead of being re-hand-rolled per page.
 *
 * Pages never call axios directly — they call a service in lib/*Api.ts through
 * one of these hooks. See lib/leadsApi.ts + useLeads.ts for the reference chain.
 */

interface ErrorLike {
  message?: string;
  response?: { status?: number; data?: { message?: string } };
}

/**
 * Turns whatever the api client rejected with into something showable.
 *
 * Two shapes arrive here: an AxiosError (HTTP status, body = the global
 * handler's { success:false, message, error_code } envelope from
 * app/core/exceptions.py), or that envelope itself — the response interceptor
 * in lib/api.ts rejects with the raw body when a 200 carries success:false.
 *
 * NOTE on 404: the API deliberately returns 404 (never 403) for a resource the
 * caller isn't allowed to see — a Sales Exec must not learn an unassigned lead
 * exists. So 404 must read as "not found", never as a permissions hint.
 */
export function errorMessage(e: unknown, fallback: string): string {
  const err = e as ErrorLike | null;
  const status = err?.response?.status;

  if (status === 401) return "Your session has expired — please sign in again.";
  if (status === 403) return "You don't have access to this.";
  if (status === 404) return "Not found.";

  // The envelope message beats axios's own "Request failed with status code…".
  return err?.response?.data?.message ?? err?.message ?? fallback;
}

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Re-runs the fetcher — call after a mutation succeeds. */
  refetch: () => void;
}

interface UseApiOptions {
  /**
   * Set false to skip the call entirely. Use it for role-gated endpoints
   * (/analytics/revenue, /users, /billing/*, /integrations all sit behind
   * require_role) so a Sales Exec doesn't fire requests that can only 403.
   */
  enabled?: boolean;
  /** Message shown when the failure carries nothing useful. */
  fallbackError?: string;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  { enabled = true, fallbackError = "Failed to load" }: UseApiOptions = {},
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    // Guards against a slow response from an earlier render landing after a
    // newer one (or after unmount) and overwriting fresher state.
    let active = true;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e: unknown) => {
        if (active) setError(errorMessage(e, fallbackError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // fetcher is a fresh closure every render; callers declare what it depends
    // on via `deps` instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce, ...deps]);

  return { data, loading, error, refetch };
}

export interface MutationState<TArgs, TResult> {
  mutate: (args: TArgs) => Promise<TResult | null>;
  pending: boolean;
  error: string | null;
}

/**
 * For write actions (Gate 2 approve/send, notes, integrations connect).
 * Resolves to null on failure and exposes the message — callers refetch on a
 * non-null result rather than patching local state, so what's on screen is
 * always what the server actually stored.
 */
export function useMutation<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  fallbackError = "Action failed",
): MutationState<TArgs, TResult> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mutate = useCallback(
    async (args: TArgs) => {
      setPending(true);
      setError(null);
      try {
        return await fn(args);
      } catch (e: unknown) {
        setError(errorMessage(e, fallbackError));
        return null;
      } finally {
        setPending(false);
      }
    },
    // Same reasoning as above — fn is re-created each render by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fallbackError],
  );

  return { mutate, pending, error };
}
