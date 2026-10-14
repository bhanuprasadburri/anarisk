import { apiRequest } from './apiClient';
import { IntegrationProvider, IntegrationTestResult } from '../types';

export const integrationService = {
  async list(): Promise<{ items: IntegrationProvider[]; total: number }> {
    return apiRequest(`/integrations`);
  },

  async connect(key: string, config: Record<string, string>): Promise<IntegrationProvider> {
    return apiRequest<IntegrationProvider>(`/integrations/${key}/connect`, {
      method: 'POST',
      body: JSON.stringify({ config }),
    });
  },

  async disconnect(key: string): Promise<IntegrationProvider> {
    return apiRequest<IntegrationProvider>(`/integrations/${key}/disconnect`, { method: 'POST', body: JSON.stringify({}) });
  },

  async test(key: string): Promise<IntegrationTestResult> {
    return apiRequest<IntegrationTestResult>(`/integrations/${key}/test`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },

  async sync(key: string): Promise<{ synced: number; created_entities: number; message: string }> {
    return apiRequest(`/integrations/${key}/sync`, { method: 'POST', body: JSON.stringify({}) });
  },
};
