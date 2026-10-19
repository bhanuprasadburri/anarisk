import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Shield, ArrowLeft, AlertCircle, CheckCircle2 } from 'lucide-react';
import { authService } from '../services/authService';
import { Button } from '../components/ui/button';
import { Input, Field } from '../components/ui/input';
import { useToast } from '../components/ui/toast';
import { ApiError } from '../services/apiClient';
import { supabaseAuthEnabled } from '../lib/supabase';

export const ResetPasswordPage: React.FC = () => {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [token, setToken] = useState(params.get('token') || '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!supabaseAuthEnabled && !token.trim()) errs.token = 'Reset token is required';
    if (password.length < 8) errs.password = 'Password must be at least 8 characters';
    if (password !== confirm) errs.confirm = 'Passwords do not match';
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setSubmitting(true);
    setError(null);
    try {
      await authService.resetPassword(token.trim(), password);
      setDone(true);
      toast.success('Password updated', 'You can now sign in with your new password.');
      setTimeout(() => navigate('/login'), 1800);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Reset failed. The token may have expired — request a new link.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-5 py-10">
      <div className="w-full max-w-[430px]">
        <Link to="/login" className="mb-6 inline-flex items-center gap-1.5 text-[13px] font-semibold text-muted hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> Back to sign in
        </Link>
        <div className="rounded-2xl border border-line bg-surface p-7 shadow-card">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-gradient text-white">
            <Shield className="h-5 w-5" />
          </span>
          <h1 className="mt-5 text-xl font-extrabold tracking-tight text-ink">Set a new password</h1>
          <p className="mt-1.5 text-[13px] text-muted">
            {supabaseAuthEnabled ? 'Choose a new password for your AnaRisk account.' : 'Paste your reset token and choose a new password.'}
          </p>

          {error && (
            <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-danger-100 bg-danger-100/60 px-3.5 py-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-[13px] font-medium text-danger-600">{error}</p>
            </div>
          )}
          {done && (
            <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-success-100 bg-success-100/50 px-3.5 py-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
              <p className="text-[13px] font-medium text-success-600">Password reset — redirecting to sign in…</p>
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
            {!supabaseAuthEnabled && !params.get('token') && (
              <Field label="Reset token" error={fieldErrors.token} required>
                <Input value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste token" />
              </Field>
            )}
            <Field label="New password" error={fieldErrors.password} required hint="At least 8 characters">
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Confirm password" error={fieldErrors.confirm} required>
              <Input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Button type="submit" size="lg" loading={submitting} className="w-full">
              Reset password
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default ResetPasswordPage;
