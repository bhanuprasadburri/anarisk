import { apiRequest, qs } from './apiClient';
import { InvestigationCase, PaginatedResponse, CaseUserRef, CaseNote, GraphResponse } from '../types';

export interface CaseListParams {
  q?: string;
  status?: string[];
  severity?: string[];
  brand_id?: string;
  assignee_id?: string;
  /** "mine" → only cases assigned to the caller. */
  mine?: boolean;
  /** true → only cases nobody has claimed yet. */
  unassigned?: boolean;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export interface TakedownReportDraft {
  generated_at: string;
  case_number: string;
  brand: { id: string; name: string };
  official_assets: Array<{ kind: string; value: string; platform?: string | null; note?: string | null }>;
  suspected_assets: Array<{
    name: string; type: string; platform?: string | null; identifier: string;
    source_url?: string | null; publisher?: string | null; observed_at?: string | null;
    assessment?: { risk_score: number | null; risk_band: string; model_version: string; signals: Array<{ type: string; status: string; value: number | null; explanation: string }> } | null;
  }>;
  case_evidence: Array<{ id: string; kind: string; title: string; description?: string | null; source_url?: string | null; collected_at: string; sha256?: string | null; provenance: string }>;
  decision: { outcome: string; reason: string; decided_at?: string | null; case_risk_score: number | null; case_risk_band: string; score_version?: string | null; score_note: string };
  investigation_history: Array<Record<string, unknown>>;
  requested_action: string;
  submission_note: string;
}

export const caseService = {
  async listCases(params: CaseListParams = {}): Promise<PaginatedResponse<InvestigationCase>> {
    return apiRequest<PaginatedResponse<InvestigationCase>>(`/cases${qs(params)}`);
  },

  async getCase(caseId: string): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}`);
  },

  async getTakedownReport(caseId: string): Promise<TakedownReportDraft> {
    return apiRequest<TakedownReportDraft>(`/cases/${caseId}/takedown-report`);
  },

  /** Server-composed sub-graph: the case's linked entities + relationships among them. */
  async getCaseGraph(caseId: string): Promise<GraphResponse> {
    return apiRequest<GraphResponse>(`/cases/${caseId}/graph`);
  },

  async createCase(payload: {
    brand_id: string;
    title: string;
    summary?: string;
    entity_ids: string[];
    platforms?: string[];
  }): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async updateCase(
    caseId: string,
    payload: { title?: string; summary?: string | null; severity?: string; platforms?: string[]; version?: number }
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async deleteCase(caseId: string): Promise<void> {
    await apiRequest(`/cases/${caseId}`, { method: 'DELETE' });
  },

  async changeStatus(
    caseId: string,
    to_status: string,
    note?: string,
    resolution_outcome?: string,
    resolution_summary?: string,
    expected_status?: string
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/status`, {
      method: 'POST',
      body: JSON.stringify({
        status: to_status,
        comment: note,
        resolution_outcome,
        resolution_summary,
        expected_status,
      }),
    });
  },

  async setResponseOutcome(
    caseId: string,
    payload: { response_outcome: string; evidence_id?: string; note?: string }
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/response-outcome`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async assign(
    caseId: string,
    assignee_id: string,
    note?: string
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/assign`, {
      method: 'POST',
      body: JSON.stringify({ assignee_id, note }),
    });
  },

  async addNote(caseId: string, body: string): Promise<CaseNote> {
    return apiRequest<CaseNote>(`/cases/${caseId}/notes`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
  },

  async escalate(
    caseId: string,
    payload: { partner_type: string; reason: string; partner_contact?: string; requested_action?: string }
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/escalate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async resolve(caseId: string, payload: { outcome: string; summary: string }): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async linkEntity(caseId: string, entity_id: string, role?: string): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/entities`, {
      method: 'POST',
      body: JSON.stringify([{ entity_id, role: role || 'related' }]),
    });
  },

  async listAssignableUsers(): Promise<CaseUserRef[]> {
    return apiRequest<CaseUserRef[]>(`/users/assignable`);
  },

  async getWorkflow(): Promise<{ transitions: Record<string, string[]> }> {
    return apiRequest<{ transitions: Record<string, string[]> }>(`/cases/workflow`);
  },
};
