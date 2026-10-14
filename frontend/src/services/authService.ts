import { apiRequest } from './apiClient';
import { AuthResponse, CurrentUser, UserPreferences } from '../types';

export const authService = {
  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await apiRequest<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    localStorage.setItem('nimbus_auth_token', res.access_token);
    return res;
  },

  async register(payload: {
    email: string;
    password: string;
    full_name: string;
  }): Promise<CurrentUser> {
    return apiRequest<CurrentUser>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getCurrentUser(): Promise<CurrentUser> {
    return apiRequest<CurrentUser>('/auth/me');
  },

  async updateProfile(payload: {
    full_name?: string;
    email?: string;
    preferences?: UserPreferences;
  }): Promise<CurrentUser> {
    return apiRequest<CurrentUser>('/auth/me', { method: 'PATCH', body: JSON.stringify(payload) });
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await apiRequest('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },

  /** In development the backend returns a dev_reset_token to complete the flow without SMTP. */
  async forgotPassword(email: string): Promise<{ status: string; dev_reset_token?: string; dev_only?: boolean }> {
    return apiRequest('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    await apiRequest('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },

  logout(): void {
    localStorage.removeItem('nimbus_auth_token');
  },
};
