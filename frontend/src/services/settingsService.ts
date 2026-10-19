import { apiRequest, qs } from './apiClient';
import { AuditLog, Brand, CurrentUser, Organization, PaginatedResponse, User } from '../types';

export const settingsService = {
  /* ---- Team & permissions ---- */
  async listUsers(params: {
    q?: string;
    role?: string;
    is_active?: boolean;
    page?: number;
    page_size?: number;
  } = {}): Promise<PaginatedResponse<User>> {
    return apiRequest<PaginatedResponse<User>>(`/users${qs(params)}`);
  },

  async createUser(payload: {
    email: string;
    full_name: string;
    password?: string;
    role: string;
    organization_id?: string;
  }): Promise<User> {
    return apiRequest<User>(`/users`, { method: 'POST', body: JSON.stringify(payload) });
  },

  async updateUser(
    userId: string,
    payload: { full_name?: string; role?: string; is_active?: boolean; organization_id?: string | null }
  ): Promise<User> {
    return apiRequest<User>(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(payload) });
  },

  async getUser(userId: string): Promise<User> {
    return apiRequest<User>(`/users/${userId}`);
  },

  /* ---- Workspace (organization) ---- */
  async listOrganizations(): Promise<Organization[]> {
    return apiRequest<Organization[]>(`/organizations`);
  },

  async getOrganization(orgId: string): Promise<Organization> {
    return apiRequest<Organization>(`/organizations/${orgId}`);
  },

  async updateOrganization(orgId: string, payload: { name?: string }): Promise<Organization> {
    return apiRequest<Organization>(`/organizations/${orgId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  },

  /** Create a workspace (administrator only). `slug` is required by the API. */
  async createOrganization(payload: { name: string; slug: string; description?: string }): Promise<Organization> {
    return apiRequest<Organization>('/organizations', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /* ---- Roles catalog ---- */
  async listRoles(): Promise<Array<{ role: string; permissions: string[] }>> {
    return apiRequest<Array<{ role: string; permissions: string[] }>>(`/users/roles`);
  },

  /* ---- Audit trail (Settings → Security) ---- */
  async listAudit(params: {
    action?: string;
    resource_type?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<PaginatedResponse<AuditLog>> {
    return apiRequest<PaginatedResponse<AuditLog>>(`/audit${qs(params)}`);
  },

  /* ---- Brands (used by Settings → Brand references) ---- */
  async listBrands(params: { q?: string; page?: number; page_size?: number } = {}): Promise<{
    items: Brand[];
    total: number;
  }> {
    return apiRequest(`/brands${qs(params)}`);
  },
};

export type { CurrentUser };
