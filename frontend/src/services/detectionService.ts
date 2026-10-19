import { apiRequest, qs } from './apiClient';
import { DetectionItem, DetectionModelInfo, PaginatedResponse, RiskAssessment } from '../types';

export interface DetectionListParams {
  q?: string;
  severity?: string;
  entity_type?: string;
  brand_id?: string;
  status?: string;
  provenance?: string;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export const detectionService = {
  /** Flattened latest assessment per entity with filters + pagination. */
  async listDetections(
    params: DetectionListParams = {}
  ): Promise<PaginatedResponse<DetectionItem>> {
    return apiRequest<PaginatedResponse<DetectionItem>>(`/detections${qs(params)}`);
  },

  async getAssessment(assessmentId: string): Promise<RiskAssessment> {
    return apiRequest<RiskAssessment>(`/detections/${assessmentId}`);
  },

  /** Rule-based heuristic re-analysis of the assessment's entity. */
  async reAnalyze(assessmentId: string): Promise<RiskAssessment> {
    return apiRequest<RiskAssessment>(`/detections/${assessmentId}/re-analyze`, { method: 'POST' });
  },

  async getModel(): Promise<DetectionModelInfo> {
    return apiRequest<DetectionModelInfo>(`/detection/model`);
  },

  async listSignals(params: {
    entity_id?: string;
    assessment_id?: string;
    signal_type?: string;
    status?: string;
    latest_only?: boolean;
    page?: number;
    page_size?: number;
  } = {}): Promise<PaginatedResponse<RiskAssessment['signals'][number]>> {
    return apiRequest(`/detection/signals${qs(params)}`);
  },
};
