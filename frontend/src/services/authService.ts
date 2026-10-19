import { apiRequest, ApiError } from './apiClient';
import { AuthResponse, CurrentUser, RegisterResult, ResendVerificationResult, UserPreferences } from '../types';
import { supabase, supabaseAuthEnabled } from '../lib/supabase';

const redirectUrl = (path: string) => `${window.location.origin}${path}`;

function supabaseError(error: { message: string; status?: number; code?: string }): ApiError {
  const message = /invalid login credentials/i.test(error.message)
    ? 'Invalid email or password.'
    : error.message;
  return new ApiError(message, error.code || 'supabase_auth_error', error.status || 400);
}

export const authService = {
  async login(email: string, password: string): Promise<AuthResponse | null> {
    if (supabaseAuthEnabled && supabase) {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw supabaseError(error);
      if (!data.session) throw new ApiError('Check your email to confirm your account, then sign in.', 'email_not_confirmed', 401);
      return null;
    }
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
    /** Optional: organization ("workspace") name for organization signups. */
    organization_name?: string;
  }): Promise<RegisterResult> {
    if (supabaseAuthEnabled && supabase) {
      const { data, error } = await supabase.auth.signUp({
        email: payload.email,
        password: payload.password,
        options: {
          emailRedirectTo: redirectUrl('/verify-email'),
          data: {
            full_name: payload.full_name,
            organization_name: payload.organization_name || null,
          },
        },
      });
      if (error) throw supabaseError(error);
      return {
        status: data.session ? 'signed_in' : 'verification_required',
        email: payload.email,
        verification_required: !data.session,
        email_sent: !data.session,
        dev_otp: null,
        dev_only: false,
      };
    }
    return apiRequest<RegisterResult>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Confirm the 6-digit OTP from the verification email (single-use, attempt-limited). */
  async verifyEmail(email: string, code: string): Promise<CurrentUser> {
    if (supabaseAuthEnabled) {
      const user = await authService.getCurrentUser();
      if (!user || user.email.toLowerCase() !== email.toLowerCase()) {
        throw new ApiError('Open the verification link sent to your email, then sign in.', 'verification_pending', 400);
      }
      return user;
    }
    return apiRequest<CurrentUser>('/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    });
  },

  /**
   * Resend the signup OTP. Always 200 (uniform for unknown/verified/pending addresses —
   * no enumeration). `status: 'cooldown'` carries `retry_after_seconds`; `dev_otp` only
   * appears outside production when no email provider is configured. `email_sent` reports
   * honest delivery — never assume an email went out.
   */
  async resendVerification(email: string): Promise<ResendVerificationResult> {
    if (supabaseAuthEnabled && supabase) {
      const { error } = await supabase.auth.resend({
        type: 'signup',
        email,
        options: { emailRedirectTo: redirectUrl('/verify-email') },
      });
      if (error) throw supabaseError(error);
      return { status: 'accepted', email_sent: true, retry_after_seconds: 60, dev_only: false };
    }
    return apiRequest('/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify({ email }),
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
    if (supabaseAuthEnabled && supabase) {
      const profile = await apiRequest<CurrentUser>('/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ full_name: payload.full_name, preferences: payload.preferences }),
      });
      if (payload.email) {
        const { error } = await supabase.auth.updateUser({ email: payload.email });
        if (error) throw supabaseError(error);
      }
      return profile;
    }
    return apiRequest<CurrentUser>('/auth/me', { method: 'PATCH', body: JSON.stringify(payload) });
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    if (supabaseAuthEnabled && supabase) {
      const { data: sessionData } = await supabase.auth.getSession();
      const email = sessionData.session?.user.email;
      if (!email) throw new ApiError('Your session has expired. Sign in again.', 'not_authenticated', 401);
      const { error: reauthError } = await supabase.auth.signInWithPassword({ email, password: currentPassword });
      if (reauthError) throw supabaseError(reauthError);
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw supabaseError(error);
      return;
    }
    await apiRequest('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },

  /** In development the backend returns a dev_reset_token to complete the flow without SMTP. */
  async forgotPassword(email: string): Promise<{ status: string; dev_reset_token?: string; dev_only?: boolean }> {
    if (supabaseAuthEnabled && supabase) {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: redirectUrl('/reset-password'),
      });
      if (error) throw supabaseError(error);
      return { status: 'sent' };
    }
    return apiRequest('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    if (supabaseAuthEnabled && supabase) {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw supabaseError(error);
      await supabase.auth.signOut();
      return;
    }
    await apiRequest('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },

  logout(): void {
    if (supabaseAuthEnabled && supabase) {
      void supabase.auth.signOut();
    }
    localStorage.removeItem('nimbus_auth_token');
  },

  async getSession(): Promise<boolean> {
    if (!supabaseAuthEnabled || !supabase) return Boolean(localStorage.getItem('nimbus_auth_token'));
    const { data } = await supabase.auth.getSession();
    return Boolean(data.session);
  },

  onAuthStateChange(callback: (event: string, hasSession: boolean) => void) {
    if (!supabaseAuthEnabled || !supabase) return () => undefined;
    const { data } = supabase.auth.onAuthStateChange((event, session) => callback(event, Boolean(session)));
    return () => data.subscription.unsubscribe();
  },
};
