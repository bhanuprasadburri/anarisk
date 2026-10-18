import React, { useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Briefcase, CheckCircle2, CircleDashed, ExternalLink, HelpCircle, Link2, Mail,
  RefreshCw, Search, ShieldAlert, Users, XCircle,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge, SeverityBadge, type BadgeTone } from '../components/ui/badge';
import { Field, Input, Textarea } from '../components/ui/input';
import { Tabs } from '../components/ui/tabs';
import { EmptyState, ErrorState } from '../components/ui/table';
import { TableSkeleton } from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { ApiError } from '../services/apiClient';
import { toolService, type ToolAnalysisListResponse } from '../services/toolService';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';
import { FindingStatus, ToolAnalysis, ToolFinding, ToolKey } from '../types';

const STATUS_META: Record<FindingStatus, { label: string; tone: BadgeTone; icon: React.ReactNode }> = {
  verified: { label: 'Verified', tone: 'success', icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
  suspicious: { label: 'Suspicious', tone: 'danger', icon: <ShieldAlert className="h-3.5 w-3.5" /> },
  inconclusive: { label: 'Inconclusive', tone: 'warning', icon: <HelpCircle className="h-3.5 w-3.5" /> },
  unable_to_verify: { label: 'Unable to verify', tone: 'default', icon: <CircleDashed className="h-3.5 w-3.5" /> },
  info: { label: 'Info', tone: 'info', icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
};

const TOOL_META: Record<ToolKey, { label: string; icon: React.ReactNode }> = {
  email: { label: 'Email / Phishing', icon: <Mail className="h-4 w-4" /> },
  job_offer: { label: 'Job Offer', icon: <Briefcase className="h-4 w-4" /> },
  social_profile: { label: 'Social Profile', icon: <Users className="h-4 w-4" /> },
  url: { label: 'URL Scanner', icon: <Link2 className="h-4 w-4" /> },
};

const errMessage = (err: unknown): string =>
  err instanceof ApiError ? err.message : 'The request failed. Please try again.';

const FindingRow: React.FC<{ f: ToolFinding }> = ({ f }) => {
  const meta = STATUS_META[f.status] || STATUS_META.info;
  return (
    <li className="rounded-xl border border-line bg-bg/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13.5px] font-bold text-ink">{f.title}</p>
          <p className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{f.check}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge tone={meta.tone}>
            {meta.icon}
            {meta.label}
          </Badge>
          <SeverityBadge severity={f.severity} />
        </div>
      </div>
      {f.summary && <p className="mt-2 text-[13px] leading-relaxed text-ink-700">{f.summary}</p>}
      {f.evidence?.length > 0 && (
        <div className="mt-2.5">
          <p className="text-[10.5px] font-bold uppercase tracking-wider text-faint">Evidence</p>
          <ul className="mt-1 space-y-1">
            {f.evidence.map((ev, i) => (
              <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-muted">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-400" />
                <span className="min-w-0 break-words">{ev}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px] text-muted">
        {f.source && (
          <span>
            <span className="font-semibold text-ink-700">Source:</span> {f.source}
          </span>
        )}
        {f.limitation && (
          <span className="text-warning-600">
            <span className="font-semibold">Limitation:</span> {f.limitation}
          </span>
        )}
      </div>
    </li>
  );
};

const AnalysisResult: React.FC<{ analysis: ToolAnalysis }> = ({ analysis }) => (
  <div className="mt-5 space-y-4">
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle className="break-words">{analysis.subject}</CardTitle>
          <CardDescription>
            {TOOL_META[analysis.tool]?.label || analysis.tool} · {formatDate(analysis.created_at)} · methodology{' '}
            {analysis.methodology_version}
          </CardDescription>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <SeverityBadge severity={analysis.severity} />
          <Badge tone="outline">
            Risk {analysis.risk_score != null ? analysis.risk_score.toFixed(2) : '—'}
          </Badge>
          <Badge tone="outline">
            Confidence {analysis.confidence != null ? `${Math.round(analysis.confidence * 100)}%` : '—'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-[12px] leading-relaxed text-muted">
          Risk reflects how concerning the signals are; confidence reflects how well the evidence supports the
          conclusion. They are independent — a high-risk score with low confidence means verify before acting.
        </p>
      </CardContent>
    </Card>

    <div>
      <h3 className="mb-2 text-[13px] font-bold uppercase tracking-wider text-faint">
        Findings ({analysis.findings.length})
      </h3>
      {analysis.findings.length === 0 ? (
        <p className="text-[13px] text-muted">No discrete findings were produced for this input.</p>
      ) : (
        <ul className="space-y-3">
          {analysis.findings.map((f, i) => (
            <FindingRow key={`${f.check}-${i}`} f={f} />
          ))}
        </ul>
      )}
    </div>
  </div>
);

/* ---------------- input forms (one per tool) ---------------- */

const EmailForm: React.FC<{ onSubmit: (input: Record<string, unknown>) => Promise<void>; busy: boolean }> = ({
  onSubmit,
  busy,
}) => {
  const [raw, setRaw] = useState('');
  const [from, setFrom] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [claimed, setClaimed] = useState('');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const input: Record<string, unknown> = {};
        if (raw.trim()) input.raw_email = raw;
        if (from.trim()) input.from_address = from.trim();
        if (subject.trim()) input.subject = subject.trim();
        if (body.trim()) input.body = body;
        if (claimed.trim()) input.claimed_domain = claimed.trim();
        onSubmit(input);
      }}
      className="space-y-4"
    >
      <Field label="Raw email (.eml text)" hint="Paste the full message — headers included — for the deepest analysis">
        <Textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={7}
          placeholder={'From: support@exampl3-secure.com\nSubject: Your account will be closed\n\n...'}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="From address" hint="Or fill this instead of a raw email">
          <Input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="billing@examp1e.com" />
        </Field>
        <Field label="Claimed domain">
          <Input value={claimed} onChange={(e) => setClaimed(e.target.value)} placeholder="example.com" />
        </Field>
      </div>
      <Field label="Subject">
        <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Urgent: verify your account" />
      </Field>
      <Field label="Body text">
        <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="Message body…" />
      </Field>
      <Button type="submit" loading={busy} disabled={busy}>
        Analyze email
      </Button>
      <p className="text-[12px] text-muted">
        Submit at least a raw email or a from-address. Nothing here is sent anywhere except this platform's analyzer.
      </p>
    </form>
  );
};

const JobForm: React.FC<{ onSubmit: (input: Record<string, unknown>) => Promise<void>; busy: boolean }> = ({
  onSubmit,
  busy,
}) => {
  const [text, setText] = useState('');
  const [employer, setEmployer] = useState('');
  const [site, setSite] = useState('');
  const [recruiterEmail, setRecruiterEmail] = useState('');
  const [applyUrl, setApplyUrl] = useState('');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const input: Record<string, unknown> = {};
        if (text.trim()) input.offer_text = text;
        if (employer.trim()) input.employer_name = employer.trim();
        if (site.trim()) input.employer_website = site.trim();
        if (recruiterEmail.trim()) input.recruiter_email = recruiterEmail.trim();
        if (applyUrl.trim()) input.application_url = applyUrl.trim();
        onSubmit(input);
      }}
      className="space-y-4"
    >
      <Field label="Offer text" hint="Paste the posting or the message you received">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={7}
          placeholder="We are offering a remote position paying $8,000/week…"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Employer name">
          <Input value={employer} onChange={(e) => setEmployer(e.target.value)} placeholder="Acme Corp" />
        </Field>
        <Field label="Employer website">
          <Input value={site} onChange={(e) => setSite(e.target.value)} placeholder="https://acme-jobs.com" />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Recruiter email">
          <Input
            type="email"
            value={recruiterEmail}
            onChange={(e) => setRecruiterEmail(e.target.value)}
            placeholder="hr@recruiter.example"
          />
        </Field>
        <Field label="Application URL">
          <Input value={applyUrl} onChange={(e) => setApplyUrl(e.target.value)} placeholder="https://…" />
        </Field>
      </div>
      <Button type="submit" loading={busy} disabled={busy}>
        Check job offer
      </Button>
    </form>
  );
};

const SocialForm: React.FC<{ onSubmit: (input: Record<string, unknown>) => Promise<void>; busy: boolean }> = ({
  onSubmit,
  busy,
}) => {
  const [platform, setPlatform] = useState('');
  const [url, setUrl] = useState('');
  const [handle, setHandle] = useState('');
  const [name, setName] = useState('');
  const [bio, setBio] = useState('');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const input: Record<string, unknown> = {};
        if (platform.trim()) input.platform = platform.trim();
        if (url.trim()) input.profile_url = url.trim();
        if (handle.trim()) input.handle = handle.trim();
        if (name.trim()) input.display_name = name.trim();
        if (bio.trim()) input.bio = bio.trim();
        onSubmit(input);
      }}
      className="space-y-4"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Platform">
          <Input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="linkedin / x / instagram" />
        </Field>
        <Field label="Handle">
          <Input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@example_brand" />
        </Field>
      </div>
      <Field label="Profile URL">
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
      </Field>
      <Field label="Display name">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Example Support" />
      </Field>
      <Field label="Bio / about text">
        <Textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={4} placeholder="Profile bio…" />
      </Field>
      <Button type="submit" loading={busy} disabled={busy}>
        Verify profile
      </Button>
    </form>
  );
};

const UrlForm: React.FC<{ onSubmit: (input: Record<string, unknown>) => Promise<void>; busy: boolean }> = ({
  onSubmit,
  busy,
}) => {
  const [url, setUrl] = useState('');
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) onSubmit({ url: url.trim() });
      }}
      className="space-y-4"
    >
      <Field label="URL to scan" hint="Scheme required — http:// or https://">
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://suspicious-example.com/login" />
      </Field>
      <Button type="submit" loading={busy} disabled={busy}>
        Scan URL
      </Button>
      <p className="text-[12px] text-muted">
        Scanning fetches public metadata only (DNS, redirects, certificate and content signals). It never executes
        page scripts or downloads files.
      </p>
    </form>
  );
};

/* ---------------- page ---------------- */

export const InvestigatePage: React.FC = () => {
  const { toast } = useToast();
  const [tab, setTab] = useState<ToolKey>('email');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ToolAnalysis | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const history = useQuery<ToolAnalysisListResponse>({
    queryKey: ['tool-analyses'],
    queryFn: () => toolService.listAnalyses({ page: 1, page_size: 20 }),
  });

  const runAnalysis = useCallback(
    async (input: Record<string, unknown>) => {
      setBusy(true);
      setFormError(null);
      setResult(null);
      try {
        const analysis =
          tab === 'email'
            ? await toolService.analyzeEmail(input)
            : tab === 'job_offer'
              ? await toolService.analyzeJobOffer(input)
              : tab === 'social_profile'
                ? await toolService.analyzeSocialProfile(input)
                : await toolService.analyzeUrl(input as { url: string });
        setResult(analysis);
        toast.success('Analysis complete', `${analysis.findings.length} finding(s) recorded.`);
        history.refetch();
      } catch (err) {
        const msg = errMessage(err);
        setFormError(msg);
        toast.error('Analysis failed', msg);
      } finally {
        setBusy(false);
      }
    },
    [tab, toast, history]
  );

  return (
    <div>
      <PageHeader
        title="Investigate"
        description="Run evidence-based checks on emails, job offers, social profiles and URLs. Every finding lists its status, evidence, source and limitation."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setResult(null);
              setFormError(null);
            }}
            disabled={!result && !formError}
          >
            <RefreshCw className="h-4 w-4" /> Reset
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <Card>
            <CardContent className="pt-5">
              <Tabs
                items={(['email', 'job_offer', 'social_profile', 'url'] as ToolKey[]).map((k) => ({
                  id: k,
                  label: TOOL_META[k].label,
                  icon: TOOL_META[k].icon,
                }))}
                value={tab}
                onChange={(id) => {
                  setTab(id as ToolKey);
                  setResult(null);
                  setFormError(null);
                }}
              />
              <div className="pt-5">
                {tab === 'email' && <EmailForm onSubmit={runAnalysis} busy={busy} />}
                {tab === 'job_offer' && <JobForm onSubmit={runAnalysis} busy={busy} />}
                {tab === 'social_profile' && <SocialForm onSubmit={runAnalysis} busy={busy} />}
                {tab === 'url' && <UrlForm onSubmit={runAnalysis} busy={busy} />}
              </div>
            </CardContent>
          </Card>

          {formError && (
            <div className="mt-4">
              <ErrorState title="Analysis failed" message={formError} onRetry={() => setFormError(null)} />
            </div>
          )}
          {result && <AnalysisResult analysis={result} />}
        </div>

        <aside className="min-w-0">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Search className="h-4 w-4 text-brand-500" /> Recent analyses
              </CardTitle>
              <CardDescription>Saved to your organization — newest first.</CardDescription>
            </CardHeader>
            <CardContent>
              {history.isLoading && <TableSkeleton rows={5} />}
              {history.isError && (
                <ErrorState
                  title="Could not load history"
                  message={errMessage(history.error)}
                  onRetry={() => history.refetch()}
                />
              )}
              {history.data && history.data.items.length === 0 && (
                <EmptyState
                  icon={<Search className="h-6 w-6" />}
                  title="No analyses yet"
                  description="Run a check on the left — results are stored here for your team."
                />
              )}
              {history.data && history.data.items.length > 0 && (
                <ul className="space-y-2">
                  {history.data.items.map((a) => (
                    <li key={a.id}>
                      <button
                        onClick={async () => {
                          try {
                            const full = await toolService.getAnalysis(a.id);
                            setResult(full);
                            setTab(full.tool);
                            setFormError(null);
                          } catch (err) {
                            toast.error('Could not open analysis', errMessage(err));
                          }
                        }}
                        className={cn(
                          'w-full rounded-xl border border-line bg-bg/60 px-3.5 py-2.5 text-left transition-colors hover:border-brand-200 hover:bg-brand-50/50',
                          result?.id === a.id && 'border-brand-200 bg-brand-50'
                        )}
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate text-[13px] font-semibold text-ink">{a.subject}</span>
                          <SeverityBadge severity={a.severity} />
                        </span>
                        <span className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-muted">
                          <span>{TOOL_META[a.tool]?.label || a.tool}</span>
                          <span>{formatRelativeTime(a.created_at)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardContent className="pt-5">
              <p className="flex items-center gap-2 text-[12.5px] font-bold text-ink">
                <XCircle className="h-4 w-4 text-warning" /> How to read results
              </p>
              <ul className="mt-2 space-y-1.5 text-[12px] leading-relaxed text-muted">
                <li>
                  <strong className="text-ink-700">Verified</strong> — the signal was confirmed against a named
                  source.
                </li>
                <li>
                  <strong className="text-ink-700">Suspicious</strong> — strong indicator of abuse, still confirm
                  before action.
                </li>
                <li>
                  <strong className="text-ink-700">Inconclusive / Unable to verify</strong> — evidence was missing
                  or a check could not run; we say so instead of guessing.
                </li>
                <li>
                  <strong className="text-ink-700">Risk ≠ confidence</strong> — a high risk score with low
                  confidence means: investigate further.
                </li>
              </ul>
              <a
                href="/docs"
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-flex items-center gap-1 text-[12px] font-semibold text-brand-600 hover:text-brand-700"
              >
                Methodology in API docs <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
};

export default InvestigatePage;
