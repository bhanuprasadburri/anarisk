import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertCircle, CheckCircle2, MailCheck, Shield } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input, Field } from '../components/ui/input';
import { useToast } from '../components/ui/toast';
import { ApiError } from '../services/apiClient';
import { authService } from '../services/authService';

type Phase = 'idle' | 'verifying' | 'done';

/**
 * OTP entry for email verification. Signup verification is code-based (no email link):
 * the user requests a 6-digit code (sent by the backend, or shown as a dev-only code when
 * no email provider is configured) and confirms it here. Every state is honest — a failed
 * or skipped delivery is never presented as "email sent".
 */
export const VerifyEmailPage: React.FC = () => {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();

  const emailFromUrl = params.get('email') || '';
  const legacyToken = params.get('token'); // old link-based flow
  const [email, setEmail] = useState(emailFromUrl);
  const [code, setCode] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [resendInfo, setResendInfo] = useState<string | null>(null);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0); // seconds until another resend is allowed
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  useEffect(() => {
    if (emailFromUrl) codeRef.current?.focus();
  }, [emailFromUrl]);

  const describeVerifyError = (err: unknown): string => {
    if (err instanceof ApiError) {
      if (err.code === 'invalid_or_expired_otp') {
        return 'That code is incorrect or has expired. Request a new code and try again.';
      }
      if (err.code === 'rate_limited') {
        return 'Too many attempts. Please wait a minute before trying again.';
      }
      return err.message;
    }
    return 'Verification failed. Check the code and try again.';
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !/^\d{6}$/.test(code.trim())) return;
    setError(null);
    setPhase('verifying');
    try {
      await authService.verifyEmail(email.trim(), code.trim());
      setPhase('done');
      toast.success('Email verified', 'Your address is confirmed — you can sign in now.');
    } catch (err) {
      setPhase('idle');
      setError(describeVerifyError(err));
      setCode('');
      codeRef.current?.focus();
    }
  };

  const resend = async () => {
    if (!email.trim() || resending || cooldown > 0) return;
    setResending(true);
    setResendInfo(null);
    try {
      const res = await authService.resendVerification(email.trim());
      if (res.status === 'cooldown') {
        const wait = res.retry_after_seconds ?? 60;
        setCooldown(wait);
        setResendInfo(`Please wait ${wait} seconds before requesting another code.`);
      } else if (res.dev_otp) {
        setDevOtp(res.dev_otp);
        setResendInfo(
          'No email provider is configured in this environment, so no email was sent. Use the dev code below.'
        );
        if (res.retry_after_seconds) setCooldown(res.retry_after_seconds);
      } else if (res.email_sent) {
        setResendInfo('A new code is on its way. Check your inbox and spam folder.');
        if (res.retry_after_seconds) setCooldown(res.retry_after_seconds);
      } else {
        setResendInfo('The verification email could not be sent. Try again shortly.');
      }
    } catch (err) {
      setResendInfo(err instanceof ApiError ? err.message : 'Could not resend right now. Try again shortly.');
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-5 py-10">
      <div className="w-full max-w-[440px]">
        <div className="mb-8 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-gradient text-white">
            <Shield className="h-5 w-5" />
          </span>
          <p className="text-base font-extrabold tracking-[0.14em] text-ink">ANARISK</p>
        </div>

        {phase === 'done' ? (
          <div className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-success-100 text-success">
              <CheckCircle2 className="h-6 w-6" />
            </span>
            <h1 className="mt-4 text-xl font-extrabold tracking-tight text-ink">Email verified</h1>
            <p className="mt-1.5 text-sm text-muted">
              Your address is confirmed. You can now sign in with your credentials.
            </p>
            <Button className="mt-5 w-full" onClick={() => navigate('/login', { replace: true })}>
              Continue to sign in
            </Button>
          </div>
        ) : (
          <div className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <MailCheck className="h-6 w-6" />
            </span>
            <h1 className="mt-4 text-xl font-extrabold tracking-tight text-ink">Enter your verification code</h1>
            <p className="mt-1.5 text-sm text-muted">
              Type the 6-digit code we emailed you to activate your account.
            </p>

            {legacyToken && (
              <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-line bg-line-soft/60 px-3.5 py-3">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
                <p className="text-[13px] leading-snug text-ink-700">
                  Verification links are no longer used. Request a fresh 6-digit code below instead.
                </p>
              </div>
            )}

            {error && (
              <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-danger-100 bg-danger-100/60 px-3.5 py-3">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                <p className="text-[13px] font-medium leading-snug text-danger-600">{error}</p>
              </div>
            )}

            <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
              <Field label="Email address" hint="Where the code was sent">
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
              </Field>
              <Field label="Verification code" hint="6 digits, expires shortly">
                <Input
                  ref={codeRef}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="123456"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  className="tracking-[0.45em]"
                  maxLength={6}
                />
              </Field>
              <Button
                type="submit"
                className="w-full"
                loading={phase === 'verifying'}
                disabled={phase === 'verifying' || !/^\d{6}$/.test(code.trim()) || !email.trim()}
              >
                Verify email
              </Button>
            </form>

            <div className="mt-6 border-t border-line-soft pt-5">
              <p className="text-[13px] font-semibold text-ink">Need a new code?</p>
              {devOtp && (
                <p className="mt-2 break-all rounded-xl bg-line-soft px-3 py-2 text-[12px] leading-relaxed text-muted">
                  <strong className="text-ink-700">Development code:</strong>{' '}
                  <code className="font-semibold tracking-[0.25em] text-ink">{devOtp}</code>
                </p>
              )}
              {resendInfo && (
                <p className="mt-2 break-words rounded-xl bg-line-soft px-3 py-2 text-[12px] leading-relaxed text-ink-700">
                  {resendInfo}
                </p>
              )}
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full"
                onClick={resend}
                loading={resending}
                disabled={cooldown > 0 || !email.trim()}
              >
                {cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}
              </Button>
            </div>
          </div>
        )}

        <p className="mt-6 text-center text-[13px] text-muted">
          <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
            ← Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
};

export default VerifyEmailPage;
