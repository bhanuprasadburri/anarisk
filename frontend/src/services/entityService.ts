import { apiRequest, qs } from './apiClient';
import {
  DigitalEntity,
  PaginatedResponse,
  RiskAssessment,
  RelatedEntity,
  EvidenceRecord,
  InvestigationCase,
} from '../types';

export interface EntityListParams {
  q?: string;
  entity_type?: string;
  severity?: string | string[];
  brand_id?: string;
  provenance?: string;
  min_risk?: number;
  max_risk?: number;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export interface EntityDetail extends DigitalEntity {
  related_entities?: Array<RelatedEntity & { relationship_type?: string }>;
  evidence?: EvidenceRecord[];
  cases?: Array<Pick<InvestigationCase, 'id' | 'case_number' | 'title' | 'status' | 'severity'>>;
}

export const entityService = {
  async listEntities(params: EntityListParams = {}): Promise<PaginatedResponse<DigitalEntity>> {
    return apiRequest<PaginatedResponse<DigitalEntity>>(`/entities${qs({ ...params, severity: params.severity })}`);
  },

  async getEntity(entityId: string): Promise<EntityDetail> {
    return apiRequest<EntityDetail>(`/entities/${entityId}`);
  },

  async submitEntity(payload: {
    brand_id: string;
    entity_type: string;
    display_name?: string;
    platform?: string;
    source_url?: string;
    attributes: Record<string, unknown>;
    analyze?: boolean;
  }): Promise<{ entity: DigitalEntity; assessment?: RiskAssessment }> {
    return apiRequest(`/entities`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async deleteEntity(entityId: string): Promise<void> {
    await apiRequest(`/entities/${entityId}`, { method: 'DELETE' });
  },

  async analyzeEntity(entityId: string): Promise<RiskAssessment> {
    return apiRequest<RiskAssessment>(`/entities/${entityId}/analyze`, { method: 'POST' });
  },

  async getAssessments(entityId: string): Promise<PaginatedResponse<RiskAssessment>> {
    return apiRequest<PaginatedResponse<RiskAssessment>>(`/entities/${entityId}/assessments`);
  },

  async getEvidence(entityId: string): Promise<EvidenceRecord[]> {
    return apiRequest<EvidenceRecord[]>(`/entities/${entityId}/evidence`);
  },

  async getCases(entityId: string): Promise<Array<Pick<InvestigationCase, 'id' | 'case_number' | 'title' | 'status' | 'severity'>>> {
    return apiRequest(`/entities/${entityId}/cases`);
  },

  async inspectUrl(entityId: string, url: string): Promise<Record<string, unknown>> {
    return apiRequest(`/entities/${entityId}/inspect-url`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  },
};
