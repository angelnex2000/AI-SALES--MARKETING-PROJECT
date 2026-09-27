import api from "@/lib/api";
import type { DealStage } from "@/lib/dealStage";

/**
 * Deals + Pipeline service (app/routers/deals.py, mounted at the API root so it
 * owns both /deals and /pipeline).
 *
 * A Deal is a revenue opportunity against a Lead (1 Lead → N Deal). Amount,
 * currency, and expected close date live here, not on the lead.
 */

export interface DealDTO {
  id: string;
  lead_id: string;
  name: string;
  stage: DealStage;
  amount: number | null;
  currency: string;
  expected_close_date: string | null;
  created_at: string;
}

/** One kanban column — the server groups and totals so the page doesn't. */
export interface PipelineColumnDTO {
  stage: DealStage;
  count: number;
  total_amount: number;
  deals: DealDTO[];
}

export const dealsApi = {
  board: async (): Promise<PipelineColumnDTO[]> =>
    (await api.get<PipelineColumnDTO[]>("/pipeline/board")).data,

  list: async (): Promise<DealDTO[]> => (await api.get<DealDTO[]>("/deals")).data,

  /**
   * Moving to closed_lost requires a structured enum reason — feedback learning
   * can't retrain on free text, so the backend rejects the move without one.
   */
  changeStage: async ({
    dealId,
    stage,
    lossReason,
  }: {
    dealId: string;
    stage: DealStage;
    lossReason?: string;
  }): Promise<DealDTO> =>
    (await api.patch<DealDTO>(`/deals/${dealId}/stage`, { stage, loss_reason: lossReason ?? null })).data,
};
