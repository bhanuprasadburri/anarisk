import { apiRequest, qs } from './apiClient';
import { MonitoringCreateResult, MonitoringSyncResult, MonitoringTarget, PaginatedResponse } from '../types';

export interface MonitoringListParams {
  q?: string;
  brand_id?: string;
  risk_severity?: string;
  monitoring_status?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: 'asc' | 'desc';
}

export const monitoringService = {
  async listApps(params: MonitoringListParams = {}): Promise<PaginatedResponse<MonitoringTarget>> {
    return apiRequest<PaginatedResponse<MonitoringTarget>>(`/monitoring/apps${qs(params)}`);
  },

  async addApp(payload: {
    brand_id: string;
    package_id: string;
    store: string;
    store_url?: string;
  }): Promise<MonitoringCreateResult> {
    return apiRequest<MonitoringCreateResult>(`/monitoring/apps`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async updateApp(
    id: string,
    payload: { monitoring_status?: 'active' | 'paused'; store_url?: string }
  ): Promise<MonitoringTarget> {
    return apiRequest<MonitoringTarget>(`/monitoring/apps/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  async removeApp(id: string): Promise<void> {
    await apiRequest(`/monitoring/apps/${id}`, { method: 'DELETE' });
  },

  async syncApp(id: string): Promise<MonitoringSyncResult> {
    return apiRequest<MonitoringSyncResult>(`/monitoring/apps/${id}/sync`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
};
