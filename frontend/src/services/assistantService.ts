import { apiRequest } from './apiClient';
import { AIStatus, AssistantAskResponse } from '../types';

export const assistantService = {
  ask(question: string, scope?: { entity_id?: string; case_id?: string }): Promise<AssistantAskResponse> {
    return apiRequest<AssistantAskResponse>('/assistant/ask', {
      method: 'POST',
      body: JSON.stringify({
        question,
        entity_id: scope?.entity_id || null,
        case_id: scope?.case_id || null,
      }),
    });
  },

  /** Honest provider status — reports "none" when no AI provider is configured. */
  status(): Promise<AIStatus> {
    return apiRequest<AIStatus>('/assistant/status');
  },
};

export default assistantService;
