import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Shield, Search, Radar, Zap, AlertCircle, ArrowRight, MailCheck, Building2 } from 'lucide-react';
import { useAuth, homePathFor } from '../hooks/useAuth';
import { Button } from '../components/ui/button';
import { Input, Field } from '../components/ui/input';
import { useToast } from '../components/ui/toast';
import { ApiError } from '../services/apiClient';
import { cn } from '../lib/utils';

const FEATURES = [
  {
    icon: <Search className="h-4 w-4" />,
    title: 'Detect',
    sub: 'Investigate. Protect.',
    color: 'from-brand-500 to-brand-600',
  },
  {
    icon: <Radar className="h-4 w-4" />,
    title: 'Monitor',
    sub: 'Digital assets & threats.',
    color: 'from-cyanx-500 to-cyanx-600',
  },
  {
    icon: <Zap className="h-4 w-4" />,
    title: 'Respond',
    sub: 'Turn insights into action.',
    color: 'from-violet-500 to-violet-600',
  },
];

const BrandPanel: React.FC = () => (
  <div className="relative hidden overflow-hidden bg-hero-gradient lg:flex lg:w-[46%] xl:w-[42%]">
    {/* soft decorative shapes */}
    <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-2xl" />
    <div className="absolute -bottom-32 -right-24 h-[28rem] w-[28rem] rounded-full bg-cyanx-500/20 blur-3xl" />
    <svg
      className="absolute inset-0 h-full w-full opacity-[0.14]"
      viewBox="0 0 800 900"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* abstract mountain / network landscape */}
      <path d="M0 640 L160 470 L290 590 L430 400 L560 540 L700 380 L800 500 L800 900 L0 900 Z" fill="url(#lg1)" opacity="0.35" />
      <path d="M0 720 L140 600 L300 700 L470 560 L640 690 L800 580 L800 900 L0 900 Z" fill="url(#lg1)" opacity="0.5" />
      {[
        [140, 470], [290, 590], [430, 400], [560, 540], [700, 380],
      ].map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="6" fill="#fff" opacity="0.9" />
          <circle cx={x} cy={y} r="16" fill="#fff" opacity="0.18" />
        </g>
      ))}
      <path d="M140 470 L290 590 L430 400 L560 540 L700 380" stroke="#fff" strokeOpacity="0.4" strokeWidth="1.5" fill="none" />
    </svg>

    <div className="relative z-10 flex w-full flex-col justify-between p-10 xl:p-14">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/15 backdrop-blur">
          <Shield className="h-6 w-6 text-white" />
        </span>
        <div className="leading-tight">
          <p className="text-lg font-extrabold tracking-[0.16em] text-white">ANARISK</p>
          <p className="-mt-0.5 text-[11px] font-bold uppercase tracking-[0.34em] text-white/70">Digital Risk</p>
        </div>
      </div>

      <div>
        <h1 className="max-w-sm text-3xl font-extrabold leading-tight tracking-tight text-white xl:text-[34px]">
          Make digital trust visible, explainable, and actionable.
        </h1>
        <div className="mt-8 space-y-3.5">
          {FEATURES.map((f) => (
            <div key={f.title} className="flex items-center gap-3.5">
              <span className={cn('flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-lg', f.color)}>
                {f.icon}
              </span>
              <div>
                <p className="text-[15px] font-bold text-white">{f.title}</p>
                <p className="text-[13px] text-white/70">{f.sub}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="text-[12px] font-semibold uppercase tracking-[0.22em] text-white/60">
        Stronger Intelligence &nbsp;•&nbsp; Safer Tomorrow
      </p>
    </div>
  </div>
);

export const LoginPage: React.FC = () => {
  const { login, logout, isAuthenticated, isLoading, user, brands, setActiveBrand } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();

  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState(() => localStorage.getItem('nimbus_remember_email') || '');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [organizationName, setOrganizationName] = useState(''); // signup: optional workspace name
  const [remember, setRemember] = useState(() => !!localStorage.getItem('nimbus_remember_email'));
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  // Post-login brand scope selection: standard users choose a brand on the login interface;
  // administrators keep global access and skip this step.
  const [brandStep, setBrandStep] = useState(false);
  // Post-registration state: the account is NOT activated until the emailed OTP is confirmed.
  const [registered, setRegistered] = useState<{
    email: string;
    devOtp?: string | null;
    emailSent?: boolean;
    deliveryFailed?: boolean;
  } | null>(null);
  const [resendInfo, setResendInfo] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(0); // seconds until another resend is allowed

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  useEffect(() => {
    // `submitting` guards the race where `login()` commits the user (setUser) and then awaits
    // refreshBrands(): without it this effect navigated away before the brand-scope step could
    // be shown, silently skipping brand selection for every non-admin sign-in.
    if (!isLoading && isAuthenticated && !brandStep && !submitting) {
      navigate((location.state as any)?.from || homePathFor(user?.role), { replace: true });
    }
  }, [isLoading, isAuthenticated, brandStep, submitting, user, navigate, location]);

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!email.trim()) errs.email = 'Email is required';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) errs.email = 'Enter a valid email address';
    if (!password) errs.password = 'Password is required';
    else if (mode === 'signup' && password.length < 8) errs.password = 'Password must be at least 8 characters';
    if (mode === 'signup' && !fullName.trim()) errs.fullName = 'Name is required';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!validate()) return;
    setSubmitting(true);
    try {
      if (mode === 'signin') {
        const me = await login(email.trim(), password);
        if (remember) localStorage.setItem('nimbus_remember_email', email.trim());
        else localStorage.removeItem('nimbus_remember_email');
        toast.success('Welcome back', 'Signed in to AnaRisk.');
        if (me.role === 'administrator') {
          // Admins keep authorized global access and are never asked to pick a brand.
          navigate((location.state as any)?.from || homePathFor(me.role), { replace: true });
        } else {
          // Standard users select their brand scope right here on the login interface.
          setBrandStep(true);
        }
      } else {
        const { authService } = await import('../services/authService');
        const res = await authService.register({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          organization_name: organizationName.trim() || undefined,
        });
        // Honest state: never auto-login before verification, and never claim an email was
        // sent unless the backend confirmed delivery (or returned a dev-only code).
        setRegistered({
          email: res.email,
          devOtp: res.dev_otp ?? null,
          emailSent: res.email_sent,
          deliveryFailed: !res.email_sent && !res.dev_otp,
        });
        if (res.email_sent) {
          toast.info('Verification code sent', `Enter the 6-digit code we emailed to ${res.email}.`);
        } else if (res.dev_otp) {
          toast.info('No email provider configured', 'No email was sent — use the dev code shown below.');
        } else {
          toast.error('Verification email not sent', 'Delivery failed or no email provider is configured. Try resending, or ask an administrator for help.');
        }
        setSubmitting(false);
        return;
      }
    } catch (err) {
      // Login failures are uniform: unknown email, wrong password, inactive and UNVERIFIED
      // accounts all show the same error — the sign-in form never jumps to the verification
      // panel. Unverified users are directed (below) to complete signup instead.
      const msg =
        err instanceof ApiError
          ? err.message
          : 'Could not sign in. Check your connection and try again.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const resendVerification = async () => {
    if (!registered || cooldown > 0) return;
    setResending(true);
    setResendInfo(null);
    try {
      const { authService } = await import('../services/authService');
      const res = await authService.resendVerification(registered.email);
      if (res.status === 'cooldown') {
        const wait = res.retry_after_seconds ?? 60;
        setCooldown(wait);
        setResendInfo(`Please wait ${wait} seconds before requesting another code.`);
      } else if (res.dev_otp) {
        setRegistered((r) => (r ? { ...r, devOtp: res.dev_otp ?? null, deliveryFailed: false } : r));
        setResendInfo('No email provider configured in this environment — no email was sent. Use the dev code above.');
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
    <div className="flex min-h-screen bg-bg">
      <BrandPanel />
      <div className="flex w-full items-center justify-center px-5 py-10 lg:w-[54%] xl:w-[58%]">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-gradient text-white">
              <Shield className="h-5 w-5" />
            </span>
            <p className="text-base font-extrabold tracking-[0.14em] text-ink">ANARISK</p>
          </div>

          <h2 className="text-2xl font-extrabold tracking-tight text-ink">
            {brandStep ? 'Choose your brand' : mode === 'signin' ? 'Welcome back' : 'Create your account'}
          </h2>
          <p className="mt-1.5 text-sm text-muted">
            {brandStep
              ? 'Select the brand scope you want to work with'
              : mode === 'signin'
                ? 'Sign in to your AnaRisk account'
                : 'Start monitoring your digital surface in minutes'}
          </p>

          {error && (
            <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-danger-100 bg-danger-100/60 px-3.5 py-3">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-[13px] font-medium leading-snug text-danger-600">{error}</p>
            </div>
          )}

          {error && mode === 'signin' && (
            <p className="mt-2.5 text-[12px] leading-relaxed text-muted">
              No account yet?{' '}
              <button
                type="button"
                className="font-semibold text-brand-600 hover:underline"
                onClick={() => {
                  setMode('signup');
                  setError(null);
                  setFieldErrors({});
                }}
              >
                Create your account
              </button>{' '}
              — sign up, verify your email with the 6-digit code we send you, then sign in here.
            </p>
          )}

          {brandStep ? (
            <div className="mt-6 rounded-2xl border border-line bg-white p-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 shadow-sm">
                <Building2 className="h-5 w-5" />
              </span>
              <h3 className="mt-3 text-[15px] font-bold text-ink">Your brand scope</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">
                Signed in as <strong className="text-ink-700">{email}</strong>. Pick the brand you want
                to work with — the selected brand seeds the filters across your pages, and you can
                switch it at any time.
              </p>

              {brands.length === 0 ? (
                <div className="mt-4 rounded-xl border border-line bg-bg px-3.5 py-3">
                  <p className="text-[13px] leading-relaxed text-muted">
                    No brands are assigned to your account yet. An administrator can assign you to a
                    brand, or you can create one in{' '}
                    <strong className="text-ink-700">Settings → Brand References</strong>.
                  </p>
                  <Button
                    size="sm"
                    className="mt-3"
                    onClick={() => navigate((location.state as any)?.from || homePathFor(user?.role), { replace: true })}
                  >
                    Continue
                    <ArrowRight className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <ul className="mt-4 space-y-2">
                  {brands.map((b) => (
                    <li key={b.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setActiveBrand(b);
                          navigate((location.state as any)?.from || homePathFor(user?.role), { replace: true });
                        }}
                        className="flex w-full items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3 text-left transition-colors hover:border-brand-200 hover:bg-brand-50/50"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[13.5px] font-bold text-ink">{b.name}</p>
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                            {b.name === 'Self' ? 'Self' : 'Organization'}
                          </p>
                        </div>
                        <ArrowRight className="h-4 w-4 shrink-0 text-brand-500" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <button
                type="button"
                className="mt-4 text-[12.5px] font-semibold text-muted hover:text-ink"
                onClick={() => {
                  logout();
                  setBrandStep(false);
                }}
              >
                Not you? Sign out
              </button>
            </div>
          ) : registered ? (
            <div className="mt-6 rounded-2xl border border-brand-100 bg-brand-50/60 p-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-brand-600 shadow-sm">
                <MailCheck className="h-5 w-5" />
              </span>
              <h3 className="mt-3 text-[15px] font-bold text-ink">Verification required</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-700">
                Enter the 6-digit code we emailed to{' '}
                <code className="rounded bg-white px-1.5 py-0.5 font-semibold">{registered.email}</code> to
                activate your account. The code expires after a short time and can only be used once.
              </p>

              {registered.deliveryFailed && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-danger-100 bg-white px-3 py-2.5">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                  <p className="text-[12px] leading-relaxed text-danger-600">
                    No verification email was sent — delivery failed or no email provider is configured. Try
                    resending, or ask an administrator to verify your address.
                  </p>
                </div>
              )}
              {registered.devOtp && (
                <p className="mt-2 break-all rounded-lg bg-white px-3 py-2 text-[12px] leading-relaxed text-muted">
                  <strong className="text-ink-700">Development mode (no email provider configured):</strong> no
                  email was sent. Your code is{' '}
                  <code className="font-semibold tracking-[0.25em] text-ink">{registered.devOtp}</code>.
                </p>
              )}
              {resendInfo && (
                <p className="mt-2 break-words rounded-lg bg-white px-3 py-2 text-[12px] leading-relaxed text-ink-700">
                  {resendInfo}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => navigate(`/verify-email?email=${encodeURIComponent(registered.email)}`)}
                >
                  Enter code
                  <ArrowRight className="ml-1 h-3.5 w-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={resendVerification}
                  loading={resending}
                  disabled={cooldown > 0}
                >
                  {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setRegistered(null);
                    setResendInfo(null);
                    setError(null);
                    setMode('signin');
                  }}
                >
                  Back to sign in
                </Button>
              </div>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
            {mode === 'signup' && (
              <Field label="Full name" error={fieldErrors.fullName} required>
                <Input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Alex Vance"
                  autoComplete="name"
                />
              </Field>
            )}
            {mode === 'signup' && (
              <Field
                label="Organization name (optional)"
                error={fieldErrors.organizationName}
              >
                <Input
                  value={organizationName}
                  onChange={(e) => setOrganizationName(e.target.value)}
                  placeholder="Acme Corp — leave empty for a personal account"
                  autoComplete="organization"
                />
              </Field>
            )}
            <Field label="Email address" error={fieldErrors.email} required>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field>
            <Field label="Password" error={fieldErrors.password} required>
              <div className="relative">
                <Input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                  className="pr-11"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-faint transition-colors hover:text-ink"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </Field>

            <div className="flex items-center justify-between pt-1">
              <label className="flex cursor-pointer items-center gap-2.5">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  className="h-4 w-4 rounded border-line accent-[#4778F5]"
                />
                <span className="text-[13px] font-medium text-ink-700">Remember me</span>
              </label>
              {mode === 'signin' && (
                <Link to="/forgot-password" className="text-[13px] font-semibold text-brand-600 hover:text-brand-700">
                  Forgot password?
                </Link>
              )}
            </div>

            <Button type="submit" size="lg" loading={submitting} className="w-full">
              {mode === 'signin' ? 'Sign In' : 'Create Account'}
              {!submitting && <ArrowRight className="ml-1 h-4 w-4" />}
            </Button>
          </form>
          )}

          <p className="mt-6 text-center text-[13px] text-muted">
            {mode === 'signin' ? "Don't have an account? " : 'Already have an account? '}
            <button
              onClick={() => {
                setMode(mode === 'signin' ? 'signup' : 'signin');
                setError(null);
                setFieldErrors({});
                setRegistered(null);
                setResendInfo(null);
              }}
              className="font-semibold text-brand-600 hover:text-brand-700"
            >
              {mode === 'signin' ? 'Create one' : 'Sign in'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
