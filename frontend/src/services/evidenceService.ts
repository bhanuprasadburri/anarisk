import { apiRequest, qs } from './apiClient';
import { API_BASE_URL } from '../lib/constants';
import { getToken } from './apiClient';
import {
  EvidenceListItem,
  EvidenceRecord,
  EvidenceVerificationResult,
  EvidenceKind,
  PaginatedResponse,
} from '../types';

export interface EvidenceListParams {
  q?: string;
  kind?: string;
  case_id?: string;
  entity_id?: string;
  verification_status?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export const evidenceService = {
  async listEvidence(
    params: EvidenceListParams = {}
  ): Promise<PaginatedResponse<EvidenceListItem>> {
    return apiRequest<PaginatedResponse<EvidenceListItem>>(`/evidence${qs(params)}`);
  },

  async getEvidence(evidenceId: string): Promise<EvidenceListItem> {
    return apiRequest<EvidenceListItem>(`/evidence/${evidenceId}`);
  },

  async createEvidence(payload: {
    entity_id: string;
    kind: Extract<EvidenceKind, 'text' | 'url' | 'whois' | 'url_inspection' | 'other'>;
    title: string;
    description?: string;
    source_url?: string;
    text_content?: string;
    provenance?: 'manual' | 'synthetic';
    metadata?: Record<string, unknown>;
    collected_at?: string;
  }): Promise<EvidenceRecord> {
    return apiRequest<EvidenceRecord>(`/evidence`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async uploadEvidence(file: File, payload: {
    entity_id: string;
    title: string;
    kind?: 'screenshot' | 'image';
    description?: string;
    provenance?: 'manual' | 'synthetic';
  }): Promise<EvidenceRecord> {
    const form = new FormData();
    form.append('file', file);
    form.append('entity_id', payload.entity_id);
    form.append('title', payload.title);
    if (payload.kind) form.append('kind', payload.kind);
    if (payload.description) form.append('description', payload.description);
    if (payload.provenance) form.append('provenance', payload.provenance);
    return apiRequest<EvidenceRecord>(`/evidence/upload`, { method: 'POST', body: form });
  },

  async deleteEvidence(evidenceId: string): Promise<void> {
    await apiRequest(`/evidence/${evidenceId}`, { method: 'DELETE' });
  },

  async verifyEvidence(evidenceId: string): Promise<EvidenceVerificationResult> {
    return apiRequest<EvidenceVerificationResult>(`/evidence/${evidenceId}/verify`, { method: 'POST' });
  },

  async linkEvidence(
    evidenceId: string,
    payload: { case_id?: string; entity_id?: string }
  ): Promise<EvidenceRecord> {
    return apiRequest<EvidenceRecord>(`/evidence/${evidenceId}/link`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async unlinkEvidence(
    evidenceId: string,
    payload: { case_id?: string; entity_id?: string }
  ): Promise<void> {
    await apiRequest(`/evidence/${evidenceId}/link${qs(payload)}`, { method: 'DELETE' });
  },

  /** URL for <a href> download (use downloadFile for authenticated download). */
  fileUrl(evidenceId: string): string {
    return `${API_BASE_URL}/evidence/${evidenceId}/file`;
  },

  /** Authenticated download: fetches the file with the bearer token and triggers a save. */
  async downloadEvidence(evidenceId: string, fileName?: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/evidence/${evidenceId}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error(`Download failed (HTTP ${res.status})`);
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/);
    const name = fileName || match?.[1] || 'evidence-download';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  /** CSV export of evidence metadata (authenticated blob download). */
  async exportCsv(params: EvidenceListParams = {}): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/evidence/export${qs(params)}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nimbus-evidence-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
