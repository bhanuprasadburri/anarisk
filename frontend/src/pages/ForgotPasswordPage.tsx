import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Shield, ArrowLeft, MailCheck, AlertCircle, Copy } from 'lucide-react';
import { authService } from '../services/authService';
import { Button } from '../components/ui/button';
import { Input, Field } from '../components/ui/input';
import { ApiError } from '../services/apiClient';
import { supabaseAuthEnabled } from '../lib/supabase';

export const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setFieldError('Enter a valid email address');
      return;
    }
    setFieldError(null);
    setSubmitting(true);
    try {
      const res = await authService.forgotPassword(email.trim());
      setSent(true);
      if (res.dev_reset_token) setDevToken(res.dev_reset_token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Request failed. Try again.');
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
          <h1 className="mt-5 text-xl font-extrabold tracking-tight text-ink">Reset your password</h1>
          <p className="mt-1.5 text-[13px] text-muted">
            {supabaseAuthEnabled
              ? "Enter your account email and we'll send a secure password reset link."
              : "Enter the email tied to your account and we'll send a reset link valid for 30 minutes."}
          </p>

          {error && (
            <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-danger-100 bg-danger-100/60 px-3.5 py-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-[13px] font-medium text-danger-600">{error}</p>
            </div>
          )}

          {sent ? (
            <div className="mt-6">
              <div className="flex items-start gap-2.5 rounded-xl border border-success-100 bg-success-100/50 px-3.5 py-3">
                <MailCheck className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
                <p className="text-[13px] font-medium leading-snug text-success-600">
                  If an account exists for <strong>{email}</strong>, a reset link has been sent.
                </p>
              </div>
              {devToken && (
                <div className="mt-4 rounded-xl border border-warning-100 bg-warning-100/40 p-3.5">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-warning-600">
                    Development mode — no email is actually sent
                  </p>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-ink-700">
                    Use this token on the reset screen:
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg bg-white px-2.5 py-2 text-[11.5px] font-semibold text-ink">
                      {devToken}
                    </code>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={<Copy className="h-3.5 w-3.5" />}
                      onClick={() => navigator.clipboard.writeText(devToken)}
                    >
                      Copy
                    </Button>
                  </div>
                  <Link
                    to={`/reset-password?token=${encodeURIComponent(devToken)}`}
                    className="mt-3 inline-flex text-[12.5px] font-semibold text-brand-600 hover:text-brand-700"
                  >
                    Continue to reset →
                  </Link>
                </div>
              )}
            </div>
          ) : (
            <form onSubmit={onSubmit} className="mt-6" noValidate>
              <Field label="Email address" error={fieldError} required>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
              </Field>
              <Button type="submit" size="lg" loading={submitting} className="mt-5 w-full">
                Send reset link
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default ForgotPasswordPage;
