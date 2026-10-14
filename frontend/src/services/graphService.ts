import { apiRequest, qs } from './apiClient';
import { GraphResponse, ClusterSummary, RelatedEntity } from '../types';

export const graphService = {
  async getGraph(params: {
    brand_id?: string;
    entity_type?: string[];
    severity?: string[];
    min_risk?: number;
    min_confidence?: number;
  } = {}): Promise<GraphResponse> {
    return apiRequest<GraphResponse>(`/graph${qs(params)}`);
  },

  async rebuild(brand_id?: string): Promise<{ node_count: number; edge_count: number; cluster_count: number; source: string }> {
    return apiRequest(`/graph/rebuild${qs({ brand_id })}`, { method: 'POST' });
  },

  async getClusters(params: { brand_id?: string; proposed_only?: boolean } = {}): Promise<ClusterSummary[]> {
    return apiRequest<ClusterSummary[]>(`/graph/clusters${qs(params)}`);
  },

  async getNeighbors(entityId: string, depth = 1): Promise<GraphResponse> {
    return apiRequest<GraphResponse>(`/graph/entities/${entityId}/neighbors${qs({ depth })}`);
  },

  async getRelated(entityId: string, maxDepth = 3): Promise<RelatedEntity[]> {
    return apiRequest(`/graph/entities/${entityId}/related${qs({ max_depth: maxDepth })}`);
  },

  async addRelationship(payload: {
    source_entity_id: string;
    target_entity_id: string;
    relationship_type: string;
    confidence: number;
    evidence_id?: string;
    evidence_note: string;
  }): Promise<unknown> {
    return apiRequest(`/graph/relationships`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async discover(brandId: string): Promise<{
    pairs_compared: number;
    relationships_created: number;
    relationships_existing: number;
  }> {
    return apiRequest(`/graph/discover${qs({ brand_id: brandId})}`, { method: 'POST' });
  },
};
