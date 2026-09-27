"use client";

import { useEffect, useState } from "react";

import { useApi, useMutation } from "@/hooks/useApi";
import { aiApi } from "@/lib/aiApi";
import { leadsApi } from "@/lib/leadsApi";

/**
 * A lead's AI results.
 *
 * Every getter returns append-only history newest-first (AIOutputMixin), so
 * "current" is always [0] and an empty array means the agents haven't run for
 * this lead yet — a normal state, not a failure.
 */
export function useLeadAI(leadId: string) {
  const research = useApi(() => aiApi.research(leadId), [leadId]);
  const score = useApi(() => aiApi.score(leadId), [leadId]);
  const icp = useApi(() => aiApi.icpScore(leadId), [leadId]);
  const signals = useApi(() => aiApi.buyingSignals(leadId), [leadId]);

  const refetchAll = () => {
    research.refetch();
    score.refetch();
    icp.refetch();
    signals.refetch();
  };

  return {
    research: research.data?.[0] ?? null,
    score: score.data?.[0] ?? null,
    icp: icp.data?.[0] ?? null,
    signals: signals.data ?? [],
    loading: research.loading || score.loading || icp.loading || signals.loading,
    error: research.error ?? score.error ?? icp.error ?? signals.error,
    refetchAll,
  };
}

const POLL_MS = 2000;

/**
 * Runs the pre-Gate-1 pipeline (research → buying signals → ICP → scoring).
 *
 * The endpoint answers 202 + job_id rather than blocking, because the agents
 * are slow — so poll GET /jobs/{id} until it settles, then let the caller
 * refresh the AI panels.
 */
export function useRunIntelligence(leadId: string, onComplete?: () => void) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const run = useMutation(leadsApi.runIntelligence, "Could not start the AI run");

  useEffect(() => {
    if (!jobId) return;
    let active = true;

    const tick = async () => {
      try {
        const job = await aiApi.getJob(jobId);
        if (!active) return;
        setStatus(job.status);
        if (job.status === "completed" || job.status === "failed") {
          setJobId(null);
          if (job.status === "completed") onComplete?.();
        }
      } catch {
        // Stop polling on a failed check rather than hammering a broken endpoint.
        if (active) {
          setJobId(null);
          setStatus("failed");
        }
      }
    };

    const handle = setInterval(tick, POLL_MS);
    void tick();
    return () => {
      active = false;
      clearInterval(handle);
    };
    // onComplete is a fresh closure each render; the job id is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const start = async () => {
    const job = await run.mutate(leadId);
    if (job) {
      setJobId(job.job_id);
      setStatus(job.status);
    }
  };

  return {
    start,
    /** pending | running | completed | failed — null when idle. */
    status,
    running: run.pending || jobId !== null,
    error: run.error,
  };
}
