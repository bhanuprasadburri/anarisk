import { apiRequest, qs } from './apiClient';
import { InvestigationCase, PaginatedResponse, CaseUserRef, CaseNote } from '../types';

export interface CaseListParams {
  q?: string;
  status?: string[];
  severity?: string[];
  brand_id?: string;
  assignee_id?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export const caseService = {
  async listCases(params: CaseListParams = {}): Promise<PaginatedResponse<InvestigationCase>> {
    return apiRequest<PaginatedResponse<InvestigationCase>>(`/cases${qs(params)}`);
  },

  async getCase(caseId: string): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}`);
  },

  async createCase(payload: {
    brand_id: string;
    title: string;
    summary?: string;
    entity_ids: string[];
  }): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async updateCase(
    caseId: string,
    payload: { title?: string; summary?: string | null; severity?: string; version?: number }
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
    resolution_summary?: string
  ): Promise<InvestigationCase> {
    return apiRequest<InvestigationCase>(`/cases/${caseId}/status`, {
      method: 'POST',
      body: JSON.stringify({
        status: to_status,
        comment: note,
        resolution_outcome,
        resolution_summary,
      }),
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
