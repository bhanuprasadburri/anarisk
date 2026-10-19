import { apiRequest, qs } from './apiClient';
import { DashboardStats, MobileAppsSummary } from '../types';

export const dashboardService = {
  async getStats(params: { brand_id?: string; from?: string; to?: string; provenance?: string } = {}): Promise<DashboardStats> {
    return apiRequest<DashboardStats>(`/dashboard/stats${qs(params)}`);
  },

  async getMobileApps(params: { brand_id?: string; limit?: number } = {}): Promise<MobileAppsSummary> {
    return apiRequest<MobileAppsSummary>(`/dashboard/mobile-apps${qs(params)}`);
  },
};
