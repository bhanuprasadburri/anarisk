import { apiRequest, qs } from './apiClient';
import { FeedbackCategory, FeedbackItem, FeedbackStatus, PaginatedResponse } from '../types';

export const feedbackService = {
  /** Submit feedback. brand_id / related_case_id are validated server-side against the caller's scope. */
  async submit(payload: {
    category: FeedbackCategory;
    message: string;
    page_ref?: string;
    brand_id?: string;
    related_case_id?: string;
  }): Promise<FeedbackItem> {
    return apiRequest<FeedbackItem>('/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Administrator-only list (global triage), filterable by status and category. */
  async list(params: { status?: FeedbackStatus; category?: FeedbackCategory; page?: number; page_size?: number } = {}): Promise<PaginatedResponse<FeedbackItem>> {
    return apiRequest<PaginatedResponse<FeedbackItem>>(`/feedback${qs(params)}`);
  },

  /** Administrator-only status transition (open <-> resolved). */
  async setStatus(id: string, status: FeedbackStatus): Promise<FeedbackItem> {
    return apiRequest<FeedbackItem>(`/feedback/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },
};
