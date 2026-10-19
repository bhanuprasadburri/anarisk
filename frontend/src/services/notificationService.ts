import { apiRequest, qs } from './apiClient';
import { NotificationItem, NotificationListResponse } from '../types';

export const notificationService = {
  async list(params: { unread_only?: boolean; page?: number; page_size?: number } = {}): Promise<NotificationListResponse> {
    return apiRequest<NotificationListResponse>(`/notifications${qs(params)}`);
  },

  async markRead(ids?: string[]): Promise<{ updated: number; unread_count: number }> {
    return apiRequest(`/notifications/read`, {
      method: 'POST',
      body: JSON.stringify(ids ? { ids } : {}),
    });
  },

  /** Delete one notification (owner, or an administrator). */
  async remove(id: string): Promise<void> {
    await apiRequest(`/notifications/${id}`, { method: 'DELETE' });
  },

  /** Administrator announcement: persisted for every active user; returns honest delivery counts. */
  async broadcast(title: string, message: string): Promise<{ recipients: number; created: number }> {
    return apiRequest(`/notifications/broadcast`, {
      method: 'POST',
      body: JSON.stringify({ title, message }),
    });
  },
};

export function notificationLink(item: NotificationItem): string | null {
  return item.link_url || null;
}
