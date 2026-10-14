import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  AtSign,
  Briefcase,
  ExternalLink,
  FileText,
  Globe,
  Image as ImageIcon,
  Link2,
  MoreVertical,
  Network,
  RefreshCw,
  SearchX,
  Share2,
  Smartphone,
  Trash2,
  UserX,
  Zap,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge, BadgeTone, CaseStatusBadge, ProvenanceBadge, SeverityBadge } from '../components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Column, DataTable, EmptyState, ErrorState, Pagination } from '../components/ui/table';
import { Tabs, Dropdown } from '../components/ui/tabs';
import { CopyButton, KeyValue, LoadingBlock, TableSkeleton, Tooltip } from '../components/ui/misc';
import { ScoreBar, ScoreRing, scoreSeverity, severityColor } from '../components/ui/score';
import { ConfirmDialog } from '../components/ui/modal';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { entityService } from '../services/entityService';
import { detectionService } from '../services/detectionService';
import { graphService } from '../services/graphService';
import { apiRequest, ApiError, qs } from '../services/apiClient';
import {
  DetectionModelInfo,
  EvidenceRecord,
  GraphNode,
  InvestigationCase,
  PaginatedResponse,
  RelatedEntity,
  RiskAssessment,
} from '../types';
import {
  ENTITY_TYPE_COLORS,
  ENTITY_TYPE_LABELS,
  EVIDENCE_KIND_LABELS,
  PLATFORM_LABELS,
  RELATIONSHIP_COLORS,
  RELATIONSHIP_LABELS,
  SIGNAL_STATUS_LABELS,
  SIGNAL_TYPE_LABELS,
  STORE_LABELS,
} from '../lib/constants';
import { formatDate, formatNumber, formatRelativeTime } from '../lib/formatters';
import { cn, truncate } from '../lib/utils';
import { EntityDetail } from '../services/entityService';

/* ---------------- small shared bits ---------------- */

const TYPE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  social_profile: AtSign,
  website: Globe,
  domain: Network,
  image: ImageIcon,
  mobile_app: Smartphone,
};

const EntityTypeChip: React.FC<{ type: string; size?: 'sm' | 'md' }> = ({ type, size = 'sm' }) => {
  const Icon = TYPE_ICONS[type] || Globe;
  const color = ENTITY_TYPE_COLORS[type] || '#4778F5';
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-xl',
        size === 'sm' ? 'h-8 w-8' : 'h-11 w-11'
      )}
      style={{ backgroundColor: `${color}1A`, color }}
      aria-hidden="true"
    >
      <Icon className={size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'} />
    </span>
  );
};

function confidenceLabel(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  if (v >= 0.7) return 'High';
  if (v >= 0.4) return 'Medium';
  return 'Low';
}

const SIGNAL_ORDER = ['brand_logo', 'impersonation', 'url_risk', 'behavior'];

const SIGNAL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  brand_logo: ImageIcon,
  impersonation: UserX,
  url_risk: Link2,
  behavior: Activity,
};

const SIGNAL_STATUS_TONE: Record<string, BadgeTone> = {
  ok: 'success',
  unavailable: 'default',
  failed: 'danger',
};

type RelatedRow = {
  id: string;
  name: string;
  entity_type: string;
  relationship: string;
  confidence: number;
  severity: string;
};

type PageState<T> = { items: T[]; page: number; pages: number; total: number; paginated: boolean };

/* ---------------- type-specific attribute rows ---------------- */

function typeAttributeRows(entity: EntityDetail): React.ReactNode[] {
  const a = (entity.attributes || {}) as Record<string, unknown>;
  const str = (k: string): string | null => {
    const v = a[k];
    return v === undefined || v === null || v === '' ? null : String(v);
  };
  const num = (k: string): number | null => {
    const v = a[k];
    if (typeof v === 'number') return v;
    if (v === undefined || v === null || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const rows: React.ReactNode[] = [];
  switch (entity.entity_type) {
    case 'social_profile': {
      const handle = str('handle');
      const followers = num('followers_count');
      const created = str('account_created_at');
      const bio = str('bio');
      if (handle)
        rows.push(
          <KeyValue key="handle" label="Handle" value={<span className="font-mono">@{handle.replace(/^@/, '')}</span>} />
        );
      if (followers !== null) rows.push(<KeyValue key="followers" label="Followers" value={formatNumber(followers)} />);
      if (created) rows.push(<KeyValue key="created" label="Account created" value={formatDate(created)} />);
      if (bio) rows.push(<KeyValue key="bio" label="Bio" value={<span className="text-muted">{truncate(bio, 140)}</span>} />);
      break;
    }
    case 'website': {
      const url = str('url');
      const title = str('page_title');
      const registered = str('registered_at');
      if (url)
        rows.push(
          <KeyValue
            key="url"
            label="URL"
            value={
              <a
                href={url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 break-all text-brand-600 transition-colors hover:text-brand-700 hover:underline"
              >
                {truncate(url, 44)}
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            }
          />
        );
      if (title) rows.push(<KeyValue key="title" label="Page title" value={<span className="text-muted">{truncate(title, 120)}</span>} />);
      if (registered) rows.push(<KeyValue key="registered" label="Registered" value={formatDate(registered)} />);
      break;
    }
    case 'domain': {
      const domain = str('domain');
      const registered = str('registered_at');
      if (domain) rows.push(<KeyValue key="domain" label="Domain" value={<span className="font-mono">{domain}</span>} />);
      if (registered) rows.push(<KeyValue key="registered" label="Registered" value={formatDate(registered)} />);
      break;
    }
    case 'mobile_app': {
      const pkg = str('package_id');
      const store = str('store');
      const publisher = str('publisher_name');
      const perms = Array.isArray(a.permissions) ? (a.permissions as unknown[]).length : null;
      if (pkg) rows.push(<KeyValue key="pkg" label="Package ID" value={<span className="break-all font-mono">{pkg}</span>} />);
      if (store) rows.push(<KeyValue key="store" label="Store" value={STORE_LABELS[store] || store} />);
      if (publisher) rows.push(<KeyValue key="publisher" label="Publisher" value={publisher} />);
      if (perms !== null)
        rows.push(<KeyValue key="perms" label="Permissions" value={`${perms} declared`} />);
      break;
    }
    case 'image': {
      const phash = str('phash');
      const sha = str('sha256');
      const note = str('source_note');
      if (phash)
        rows.push(
          <KeyValue
            key="phash"
            label="Perceptual hash"
            value={
              <span className="flex items-center gap-1">
                <code className="font-mono text-[12px]">{phash}</code>
                <CopyButton text={phash} label="Copy perceptual hash" />
              </span>
            }
          />
        );
      if (sha)
        rows.push(
          <KeyValue
            key="sha"
            label="SHA-256"
            value={
              <span className="flex items-center gap-1">
                <code className="font-mono text-[12px]">{truncate(sha, 20)}</code>
                <CopyButton text={sha} label="Copy SHA-256" />
              </span>
            }
          />
        );
      if (note) rows.push(<KeyValue key="note" label="Source note" value={<span className="text-muted">{truncate(note, 120)}</span>} />);
      break;
    }
    default:
      break;
  }
  return rows;
}

/* ---------------- page ---------------- */

export const EntityDetailPage: React.FC = () => {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { role, brands } = useAuth();
  const isAdmin = role === 'administrator';

  /* ----- tab (kept in the URL for shareability) ----- */
  const TAB_IDS = ['overview', 'signals', 'evidence', 'relations', 'cases'];
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') || '';
  const [tab, setTab] = useState<string>(TAB_IDS.includes(tabParam) ? tabParam : 'overview');

  const changeTab = useCallback(
    (t: string) => {
      setTab(t);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (t === 'overview') next.delete('tab');
          else next.set('tab', t);
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  /* ----- entity ----- */
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setNotFound(false);
    setError(null);
    entityService
      .getEntity(id)
      .then((res) => {
        if (!cancelled) setEntity(res);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
        else setError(err instanceof ApiError ? err.message : 'We could not load this asset.');
      });
    return () => {
      cancelled = true;
    };
  }, [id, reload]);

  /* ----- lazy tab data ----- */
  const [assessments, setAssessments] = useState<PaginatedResponse<RiskAssessment> | null>(null);
  const [evidence, setEvidence] = useState<PageState<EvidenceRecord> | null>(null);
  const [cases, setCases] = useState<PageState<InvestigationCase> | null>(null);
  const [model, setModel] = useState<DetectionModelInfo | null>(null);
  const [relatedFallback, setRelatedFallback] = useState<RelatedRow[] | null>(null);
  const [loadState, setLoadState] = useState<Record<string, { loading: boolean; error?: string }>>({});
  const inflight = useRef<Set<string>>(new Set());

  const guard = useCallback(async (key: string, fn: () => Promise<void>) => {
    if (inflight.current.has(key)) return;
    inflight.current.add(key);
    setLoadState((s) => ({ ...s, [key]: { loading: true } }));
    try {
      await fn();
      setLoadState((s) => ({ ...s, [key]: { loading: false } }));
    } catch (err) {
      setLoadState((s) => ({
        ...s,
        [key]: { loading: false, error: err instanceof ApiError ? err.message : 'We could not load this data.' },
      }));
    } finally {
      inflight.current.delete(key);
    }
  }, []);

  const loadAssessments = useCallback(
    (page = 1) =>
      guard('assessments', async () => {
        const res = await apiRequest<PaginatedResponse<RiskAssessment>>(
          `/entities/${id}/assessments${qs({ page, page_size: 10 })}`
        );
        setAssessments({
          items: res.items || [],
          total: res.total || 0,
          page: res.page || page,
          page_size: res.page_size || 10,
          pages: res.pages || 1,
        });
      }),
    [guard, id]
  );

  const loadEvidence = useCallback(
    (page = 1) =>
      guard('evidence', async () => {
        const res = await apiRequest<unknown>(`/entities/${id}/evidence${qs({ page, page_size: 20 })}`);
        if (Array.isArray(res)) {
          const items = res as EvidenceRecord[];
          setEvidence({ items, page: 1, pages: 1, total: items.length, paginated: false });
        } else {
          const p = res as PaginatedResponse<EvidenceRecord>;
          const items = p.items || [];
          setEvidence({
            items,
            page: p.page || page,
            pages: p.pages || 1,
            total: p.total ?? items.length,
            paginated: true,
          });
        }
      }),
    [guard, id]
  );

  const loadCases = useCallback(
    (page = 1) =>
      guard('cases', async () => {
        const res =
          page <= 1
            ? await entityService.getCases(id)
            : await apiRequest<unknown>(`/entities/${id}/cases${qs({ page, page_size: 20 })}`);
        if (Array.isArray(res)) {
          const items = res as unknown as InvestigationCase[];
          setCases({ items, page: 1, pages: 1, total: items.length, paginated: false });
        } else {
          const p = res as PaginatedResponse<InvestigationCase>;
          const items = p.items || [];
          setCases({ items, page: p.page || page, pages: p.pages || 1, total: p.total ?? items.length, paginated: true });
        }
      }),
    [guard, id]
  );

  const loadModel = useCallback(
    () =>
      guard('model', async () => {
        const m = await detectionService.getModel();
        setModel(m);
      }),
    [guard]
  );

  const loadRelatedFallback = useCallback(
    () =>
      guard('related', async () => {
        const res = await graphService.getRelated(id);
        setRelatedFallback(
          res.map((r) => {
            const node = r.entity as GraphNode & { display_name?: string };
            return {
              id: node.id,
              name: node.display_name || node.label,
              entity_type: node.entity_type,
              relationship: r.via?.[0] || '',
              confidence: typeof r.path_confidence === 'number' ? r.path_confidence : 0,
              severity: node.severity,
            };
          })
        );
      }),
    [guard, id]
  );

  const entityLoaded = !!entity;

  // reset per-entity tab caches whenever the route id changes
  useEffect(() => {
    clearTabCaches();
    const t = new URLSearchParams(window.location.search).get('tab') || 'overview';
    setTab(TAB_IDS.includes(t) ? t : 'overview');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!entityLoaded) return;
    if (tab === 'overview' && !assessments) loadAssessments(1);
    if (tab === 'evidence' && !evidence) loadEvidence(1);
    if (tab === 'cases' && !cases) loadCases(1);
    if (tab === 'signals' && !model) loadModel();
    if (tab === 'relations' && !entity?.related_entities?.length && relatedFallback === null) loadRelatedFallback();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, entityLoaded, id, reload]);

  /* ----- actions ----- */
  const [analyzing, setAnalyzing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const clearTabCaches = useCallback(() => {
    setAssessments(null);
    setEvidence(null);
    setCases(null);
    setRelatedFallback(null);
    setLoadState({});
  }, []);

  const handleReanalyze = useCallback(async () => {
    if (!entity) return;
    setAnalyzing(true);
    try {
      await entityService.analyzeEntity(entity.id);
      toast.success('Re-analysis complete', `${entity.display_name} has been re-scored with the latest detection model.`);
      clearTabCaches();
      setReload((r) => r + 1);
    } catch (err) {
      toast.error('Re-analysis failed', err instanceof ApiError ? err.message : 'Unexpected error.');
    } finally {
      setAnalyzing(false);
    }
  }, [entity, toast, clearTabCaches]);

  const handleDelete = useCallback(async () => {
    if (!entity) return;
    setDeleteBusy(true);
    try {
      await entityService.deleteEntity(entity.id);
      toast.success('Asset deleted', `${entity.display_name} was removed.`);
      navigate('/assets');
    } catch (err) {
      toast.error(err instanceof ApiError && err.status === 403 ? 'Not allowed to delete' : 'Delete failed', err instanceof ApiError ? err.message : 'Unexpected error.');
      setConfirmDelete(false);
    } finally {
      setDeleteBusy(false);
    }
  }, [entity, toast, navigate]);

  /* ----- derived ----- */
  const latest = useMemo<RiskAssessment | null>(
    () => entity?.latest_assessment || assessments?.items?.[0] || null,
    [entity, assessments]
  );
  const signals = useMemo(() => latest?.signals || [], [latest]);
  const orderedSignals = useMemo(
    () =>
      SIGNAL_ORDER.map((st) => signals.find((s) => s.signal_type === st)).filter(Boolean) as typeof signals,
    [signals]
  );

  const relatedRows = useMemo<RelatedRow[]>(() => {
    if (entity?.related_entities?.length) {
      return entity.related_entities.map((raw) => {
        // backend RelatedEntityOut carries entity + relationship_type + confidence; the shared
        // RelatedEntity type predates those fields, so read them defensively.
        const r = raw as RelatedEntity & { relationship_type?: string; confidence?: number };
        const node = r.entity as GraphNode & { display_name?: string };
        return {
          id: node.id,
          name: node.display_name || node.label,
          entity_type: node.entity_type,
          relationship: r.relationship_type || r.via?.[0] || '',
          confidence: typeof r.confidence === 'number' ? r.confidence : r.path_confidence ?? 0,
          severity: node.severity,
        };
      });
    }
    return relatedFallback || [];
  }, [entity, relatedFallback]);

  const brandName = useMemo(() => {
    if (!entity) return '—';
    return brands.find((b) => b.id === entity.brand_id)?.name || '—';
  }, [entity, brands]);

  /* ----- early returns: not found / error / loading ----- */
  if (notFound) {
    return (
      <div className="rounded-2xl border border-line bg-surface px-5 py-16 shadow-card">
        <EmptyState
          icon={<SearchX className="h-6 w-6" />}
          title="Asset not found"
          description="This digital asset does not exist or has been deleted. It may have been removed by an administrator."
          action={
            <Button onClick={() => navigate('/assets')} icon={<ArrowLeft className="h-4 w-4" />}>
              Back to Digital Assets
            </Button>
          }
        />
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-line bg-surface px-5 py-16 shadow-card">
        <ErrorState title="Could not load asset" message={error} onRetry={() => setReload((r) => r + 1)} />
      </div>
    );
  }
  if (!entity || entity.id.toLowerCase() !== id.toLowerCase()) return <LoadingBlock label="Loading asset…" />;

  /* ----- table columns per tab ----- */
  const assessmentColumns: Column<RiskAssessment>[] = [
    {
      key: 'assessed_at',
      header: 'Assessed',
      cell: (a) => (
        <Tooltip content={formatDate(a.assessed_at)}>
          <span className="whitespace-nowrap text-[13px] text-ink-700">{formatRelativeTime(a.assessed_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: 'risk_score',
      header: 'Risk Score',
      className: 'min-w-[150px]',
      cell: (a) =>
        a.risk_score === null || a.risk_score === undefined ? (
          <span className="text-xs font-medium text-faint">—</span>
        ) : (
          <ScoreBar value={a.risk_score} severity={a.severity} />
        ),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      cell: (a) => <span className="text-[13px] font-semibold text-ink-700">{Math.round((a.confidence_score ?? 0) * 100)}%</span>,
    },
    { key: 'severity', header: 'Severity', cell: (a) => <SeverityBadge severity={a.severity} /> },
    {
      key: 'model',
      header: 'Model',
      cell: (a) => <Badge tone="outline">{a.model_version}</Badge>,
    },
  ];

  const evidenceColumns: Column<EvidenceRecord>[] = [
    {
      key: 'kind',
      header: 'Kind',
      cell: (ev) => <Badge tone="info">{EVIDENCE_KIND_LABELS[ev.kind] || ev.kind}</Badge>,
    },
    {
      key: 'description',
      header: 'Description',
      className: 'min-w-[220px]',
      cell: (ev) => (
        <span className="block max-w-[380px] truncate text-[13px] text-ink-700">
          {ev.description || ev.file_name || (ev.text_content ? truncate(ev.text_content, 80) : ev.source_url || '—')}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: 'Created',
      cell: (ev) => (
        <Tooltip content={formatDate(ev.created_at)}>
          <span className="whitespace-nowrap text-[13px] text-muted">{formatRelativeTime(ev.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: 'sha256',
      header: 'SHA-256',
      cell: (ev) =>
        ev.sha256 ? (
          <span className="flex items-center gap-1">
            <code className="font-mono text-[11px] text-muted">{truncate(ev.sha256, 14)}</code>
            <CopyButton text={ev.sha256} label="Copy SHA-256" />
          </span>
        ) : (
          <span className="text-xs text-faint">—</span>
        ),
    },
    {
      key: 'open',
      header: '',
      headerClassName: 'w-24',
      className: 'text-right',
      cell: () => (
        <Button variant="link" size="sm" onClick={() => navigate('/evidence')}>
          Open
        </Button>
      ),
    },
  ];

  const relatedColumns: Column<RelatedRow>[] = [
    {
      key: 'name',
      header: 'Asset',
      className: 'min-w-[220px]',
      cell: (r) => (
        <button
          onClick={() => navigate(`/entities/${r.id}`)}
          className="flex items-center gap-3 text-left focus-ring rounded-lg"
        >
          <EntityTypeChip type={r.entity_type} />
          <span className="truncate text-[13px] font-bold text-ink hover:text-brand-600">{r.name}</span>
        </button>
      ),
    },
    {
      key: 'relationship',
      header: 'Relationship',
      cell: (r) => (
        <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] font-medium text-ink-700">
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: RELATIONSHIP_COLORS[r.relationship] || '#94A3B8' }}
          />
          {RELATIONSHIP_LABELS[r.relationship] || r.relationship || 'Related'}
        </span>
      ),
    },
    {
      key: 'confidence',
      header: 'Confidence',
      cell: (r) => <span className="text-[13px] font-semibold text-ink-700">{Math.round(r.confidence * 100)}%</span>,
    },
    { key: 'severity', header: 'Severity', cell: (r) => <SeverityBadge severity={r.severity} /> },
  ];

  const caseColumns: Column<InvestigationCase>[] = [
    {
      key: 'case',
      header: 'Case',
      className: 'min-w-[240px]',
      cell: (c) => (
        <button onClick={() => navigate(`/cases/${c.id}`)} className="text-left focus-ring rounded-lg">
          <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-brand-600">{c.case_number}</span>
          <p className="truncate text-[13px] font-bold text-ink hover:text-brand-600">{c.title}</p>
        </button>
      ),
    },
    { key: 'status', header: 'Status', cell: (c) => <CaseStatusBadge status={c.status} /> },
    { key: 'severity', header: 'Severity', cell: (c) => <SeverityBadge severity={c.severity} /> },
    {
      key: 'updated',
      header: 'Updated',
      cell: (c) => (
        <Tooltip content={formatDate(c.updated_at)}>
          <span className="whitespace-nowrap text-[13px] text-muted">{formatRelativeTime(c.updated_at)}</span>
        </Tooltip>
      ),
    },
  ];

  /* ----- tab renderers ----- */
  const renderOverview = () => {
    const state = loadState.assessments;
    return (
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Assessment History</CardTitle>
            <CardDescription>Newest first — every re-analysis is retained for audit.</CardDescription>
          </CardHeader>
          {state?.loading ? (
            <TableSkeleton rows={4} />
          ) : state?.error ? (
            <div className="px-5 pb-5">
              <ErrorState title="Could not load assessments" message={state.error} onRetry={() => loadAssessments(assessments?.page || 1)} />
            </div>
          ) : (
            <>
              <DataTable<RiskAssessment>
                columns={assessmentColumns}
                rows={assessments?.items || []}
                rowKey={(a) => a.id}
                emptyState={
                  <EmptyState
                    title="No assessments yet"
                    description="This asset has not been analyzed yet. Run a re-analysis to generate a risk score."
                    action={
                      <Button variant="outline" size="sm" loading={analyzing} onClick={() => void handleReanalyze()}>
                        Re-analyze
                      </Button>
                    }
                  />
                }
              />
              {assessments && assessments.pages > 1 && (
                <div className="border-t border-line-soft">
                  <Pagination
                    page={assessments.page}
                    pages={assessments.pages}
                    total={assessments.total}
                    onPageChange={(p) => loadAssessments(p)}
                  />
                </div>
              )}
            </>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Why this score</CardTitle>
            <CardDescription>
              {latest ? `Signals from the assessment ${formatRelativeTime(latest.assessed_at)}.` : 'Latest assessment signals.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!latest || !latest.signals?.length ? (
              <p className="text-[13px] leading-relaxed text-muted">
                No signal breakdown is available yet. Run a re-analysis to see which detection families contribute to
                the score.
              </p>
            ) : (
              <ul className="space-y-4">
                {latest.signals.map((s) => (
                  <li key={s.id}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[13px] font-bold text-ink">{SIGNAL_TYPE_LABELS[s.signal_type] || s.signal_type}</span>
                      {s.score === null || s.score === undefined ? (
                        <span className="text-xs font-semibold text-faint">No signal</span>
                      ) : (
                        <span className="text-[12px] font-bold" style={{ color: severityColor(scoreSeverity(s.score)) }}>
                          {(s.score * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    <Badge tone={SIGNAL_STATUS_TONE[s.status] || 'default'} className="mt-1">
                      {SIGNAL_STATUS_LABELS[s.status] || s.status}
                    </Badge>
                    {s.explanation && <p className="mt-1.5 text-xs leading-relaxed text-muted">{s.explanation}</p>}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    );
  };

  const renderSignals = () => {
    const state = loadState.model;
    return (
      <div className="space-y-4">
        {!latest ? (
          <Card>
            <CardContent className="py-10">
              <EmptyState
                title="No signals yet"
                description="This asset has not been analyzed yet. Run a re-analysis to produce the four detection families."
                action={
                  <Button variant="outline" size="sm" loading={analyzing} onClick={() => void handleReanalyze()}>
                    Re-analyze
                  </Button>
                }
              />
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {(orderedSignals.length ? orderedSignals : signals).map((s) => {
              const Icon = SIGNAL_ICONS[s.signal_type] || Activity;
              const hasRefs = Array.isArray(s.evidence_refs) && s.evidence_refs.length > 0;
              const metaKeys = s.metadata && typeof s.metadata === 'object' ? Object.keys(s.metadata) : [];
              return (
                <Card key={s.id}>
                  <CardHeader className="flex flex-row items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-brand-gradient-soft text-brand-500">
                        <Icon className="h-4 w-4" />
                      </span>
                      <CardTitle>{SIGNAL_TYPE_LABELS[s.signal_type] || s.signal_type}</CardTitle>
                    </div>
                    <Badge tone={SIGNAL_STATUS_TONE[s.status] || 'default'}>
                      {SIGNAL_STATUS_LABELS[s.status] || s.status}
                    </Badge>
                  </CardHeader>
                  <CardContent>
                    {s.score === null || s.score === undefined ? (
                      <p className="mb-2 text-[13px] font-semibold text-faint">No signal</p>
                    ) : (
                      <ScoreBar value={s.score} className="mb-2 max-w-[240px]" />
                    )}
                    <p className="text-[13px] leading-relaxed text-muted">{s.explanation || 'No explanation recorded.'}</p>
                    {(hasRefs || metaKeys.length > 0) && (
                      <div className="mt-3 space-y-2">
                        {hasRefs && (
                          <details className="rounded-lg border border-line-soft bg-bg/60 px-3 py-2">
                            <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wider text-faint focus-ring">
                              Evidence references ({s.evidence_refs.length})
                            </summary>
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-muted">
                              {JSON.stringify(s.evidence_refs, null, 2)}
                            </pre>
                          </details>
                        )}
                        {metaKeys.length > 0 && (
                          <details className="rounded-lg border border-line-soft bg-bg/60 px-3 py-2">
                            <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wider text-faint focus-ring">
                              Metadata ({metaKeys.length})
                            </summary>
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-muted">
                              {JSON.stringify(s.metadata, null, 2)}
                            </pre>
                          </details>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {state?.loading ? (
          <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
            <div className="skeleton h-4 w-40 rounded-md" />
            <div className="mt-3 space-y-2">
              <div className="skeleton h-3 w-3/4 rounded-md" />
              <div className="skeleton h-3 w-1/2 rounded-md" />
            </div>
          </div>
        ) : state?.error ? (
          <ErrorState title="Could not load scoring model" message={state.error} onRetry={loadModel} />
        ) : (
          model && (
            <Card>
              <CardHeader>
                <CardTitle>Scoring model</CardTitle>
                <CardDescription>
                  Version {model.model_version} — signal weights used to compose the risk score.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {Object.entries(model.weights || {}).map(([k, v]) => {
                    const pct = v <= 1 ? v * 100 : v;
                    return (
                      <li key={k} className="rounded-xl border border-line-soft bg-bg/50 px-3.5 py-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-semibold text-ink">{SIGNAL_TYPE_LABELS[k] || k}</span>
                          <span className="text-[12px] font-bold text-brand-600">{Math.round(pct)}%</span>
                        </div>
                        <ScoreBar value={Math.max(0, Math.min(1, pct / 100))} showLabel={false} className="mt-1.5" />
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>
          )
        )}
      </div>
    );
  };

  const renderEvidence = () => {
    const state = loadState.evidence;
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>Evidence</CardTitle>
            <CardDescription>Files, screenshots, URL inspections and WHOIS records linked to this asset.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate('/evidence')}>
            Evidence Center
          </Button>
        </CardHeader>
        {state?.loading ? (
          <TableSkeleton rows={4} />
        ) : state?.error ? (
          <div className="px-5 pb-5">
            <ErrorState title="Could not load evidence" message={state.error} onRetry={() => loadEvidence(evidence?.page || 1)} />
          </div>
        ) : (
          <>
            <DataTable<EvidenceRecord>
              columns={evidenceColumns}
              rows={evidence?.items || []}
              rowKey={(ev) => ev.id}
              emptyState={
                <EmptyState
                  title="No evidence linked"
                  description="Add screenshots, files or URL inspections for this asset in the Evidence Center."
                  action={
                    <Button size="sm" onClick={() => navigate('/evidence')}>
                      Add evidence in Evidence Center
                    </Button>
                  }
                />
              }
            />
            {evidence?.paginated && evidence.pages > 1 && (
              <div className="border-t border-line-soft">
                <Pagination
                  page={evidence.page}
                  pages={evidence.pages}
                  total={evidence.total}
                  onPageChange={(p) => loadEvidence(p)}
                />
              </div>
            )}
          </>
        )}
      </Card>
    );
  };

  const renderRelations = () => {
    const state = loadState.related;
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>Related Assets</CardTitle>
            <CardDescription>
              Assets connected through shared images, domains, identity signals or infrastructure.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" icon={<Share2 className="h-4 w-4" />} onClick={() => navigate(`/risk-graph?focus=${entity.id}`)}>
            Open in Risk Graph
          </Button>
        </CardHeader>
        {state?.loading ? (
          <TableSkeleton rows={3} />
        ) : state?.error ? (
          <div className="px-5 pb-5">
            <ErrorState title="Could not load relations" message={state.error} onRetry={loadRelatedFallback} />
          </div>
        ) : (
          <DataTable<RelatedRow>
            columns={relatedColumns}
            rows={relatedRows}
            rowKey={(r) => `${r.id}-${r.relationship}`}
            onRowClick={(r) => navigate(`/entities/${r.id}`)}
            emptyState={
              <EmptyState
                title="No relationships yet"
                description="No other assets are connected to this one yet. Explore the Risk Graph to discover clusters."
                action={
                  <Button variant="outline" size="sm" onClick={() => navigate(`/risk-graph?focus=${entity.id}`)}>
                    Open in Risk Graph
                  </Button>
                }
              />
            }
          />
        )}
      </Card>
    );
  };

  const renderCases = () => {
    const state = loadState.cases;
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>Cases</CardTitle>
            <CardDescription>Investigation cases that include this asset.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate('/cases')}>
            All cases
          </Button>
        </CardHeader>
        {state?.loading ? (
          <TableSkeleton rows={3} />
        ) : state?.error ? (
          <div className="px-5 pb-5">
            <ErrorState title="Could not load cases" message={state.error} onRetry={loadCases} />
          </div>
        ) : (
          <>
            <DataTable<InvestigationCase>
              columns={caseColumns}
              rows={cases?.items || []}
              rowKey={(c) => c.id}
              onRowClick={(c) => navigate(`/cases/${c.id}`)}
              emptyState={
                <EmptyState
                  title="Not part of any case"
                  description="This asset has not been attached to an investigation case yet."
                  action={
                    <Button variant="outline" size="sm" onClick={() => navigate('/cases')}>
                      Go to Cases
                    </Button>
                  }
                />
              }
            />
            {cases?.paginated && cases.pages > 1 && (
              <div className="border-t border-line-soft">
                <Pagination
                  page={cases.page}
                  pages={cases.pages}
                  total={cases.total}
                  onPageChange={() => loadCases()}
                />
              </div>
            )}
          </>
        )}
      </Card>
    );
  };

  /* ----- header + summary + tabs ----- */
  return (
    <div>
      {/* header */}
      <div className="mb-6">
        <Link
          to="/assets"
          className="inline-flex items-center gap-1.5 rounded text-[13px] font-semibold text-muted transition-colors hover:text-brand-600 focus-ring"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Digital Assets
        </Link>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <EntityTypeChip type={entity.entity_type} size="md" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="truncate text-xl font-extrabold tracking-tight text-ink sm:text-2xl">{entity.display_name}</h1>
                <SeverityBadge severity={entity.current_severity} />
                <ProvenanceBadge provenance={entity.provenance} />
              </div>
              <p className="mt-1 flex min-w-0 items-center gap-1 text-[13px] text-muted">
                <code className="truncate font-mono text-xs">{truncate(entity.canonical_id, 52)}</code>
                <CopyButton text={entity.canonical_id} label="Copy identifier" />
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2.5">
            <Button
              variant="outline"
              loading={analyzing}
              icon={analyzing ? undefined : <RefreshCw className="h-4 w-4" />}
              onClick={() => void handleReanalyze()}
            >
              {analyzing ? 'Analyzing…' : 'Re-analyze'}
            </Button>
            <Dropdown
              align="right"
              trigger={({ open: ddOpen }) => (
                <button
                  aria-label="Asset actions"
                  aria-haspopup="menu"
                  className={cn(
                    'rounded-lg p-1.5 transition-colors focus-ring',
                    ddOpen ? 'bg-brand-50 text-brand-600' : 'border border-line bg-white text-ink-700 hover:bg-bg'
                  )}
                >
                  <MoreVertical className="h-4 w-4" />
                </button>
              )}
              items={[
                {
                  label: 'View in Risk Graph',
                  icon: <Share2 className="h-3.5 w-3.5" />,
                  onClick: () => navigate(`/risk-graph?focus=${entity.id}`),
                },
                {
                  label: 'Copy identifier',
                  icon: <FileText className="h-3.5 w-3.5" />,
                  onClick: () => {
                    navigator.clipboard
                      .writeText(entity.canonical_id)
                      .then(() => toast.success('Identifier copied', entity.canonical_id))
                      .catch(() => toast.error('Could not copy', 'Clipboard access was denied.'));
                  },
                },
                ...(isAdmin
                  ? [
                      {
                        label: 'Delete entity',
                        icon: <Trash2 className="h-3.5 w-3.5" />,
                        danger: true,
                        separatorBefore: true,
                        onClick: () => setConfirmDelete(true),
                      },
                    ]
                  : []),
              ]}
            />
          </div>
        </div>
      </div>

      {/* summary strip */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="flex flex-col items-center justify-center px-5 py-6">
          <ScoreRing
            value={entity.current_risk_score}
            size={100}
            severity={entity.current_severity}
            label="Risk Score"
            sublabel={entity.current_risk_score === null || entity.current_risk_score === undefined ? 'unscored' : undefined}
          />
          <div className="mt-2">
            <SeverityBadge severity={entity.current_severity} />
          </div>
        </Card>

        <Card className="flex flex-col items-center justify-center px-5 py-6">
          <ScoreRing
            value={entity.current_confidence}
            size={100}
            label="Confidence"
            sublabel={confidenceLabel(entity.current_confidence)}
          />
          <p className="mt-4 text-[11px] font-bold uppercase tracking-wider text-faint">
            {entity.current_confidence === null || entity.current_confidence === undefined
              ? 'Not assessed'
              : `${Math.round(entity.current_confidence * 100)}% confidence`}
          </p>
        </Card>

        <Card className="sm:col-span-2">
          <CardHeader>
            <CardTitle>Asset Information</CardTitle>
            <CardDescription>Identity, provenance and type-specific metadata.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
              <KeyValue
                label="Canonical ID"
                value={
                  <span className="flex min-w-0 items-center gap-1">
                    <code className="truncate font-mono text-[12px]">{truncate(entity.canonical_id, 34)}</code>
                    <CopyButton text={entity.canonical_id} label="Copy canonical ID" />
                  </span>
                }
              />
              <KeyValue label="Type" value={ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type} />
              <KeyValue
                label="Platform"
                value={entity.platform ? PLATFORM_LABELS[entity.platform] || entity.platform : '—'}
              />
              <KeyValue
                label="Source URL"
                value={
                  entity.source_url ? (
                    <a
                      href={entity.source_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 break-all text-brand-600 transition-colors hover:text-brand-700 hover:underline"
                    >
                      {truncate(entity.source_url, 40)}
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                  ) : (
                    '—'
                  )
                }
              />
              <KeyValue label="Brand" value={brandName} />
              <KeyValue label="Provenance" value={<ProvenanceBadge provenance={entity.provenance} />} />
              <KeyValue label="First seen" value={formatDate(entity.first_seen_at)} />
              <KeyValue label="Last seen" value={formatDate(entity.last_seen_at)} />
              <KeyValue label="Submissions" value={formatNumber(entity.submission_count)} />
              {typeAttributeRows(entity)}
            </dl>
          </CardContent>
        </Card>
      </div>

      {/* tabs */}
      <Tabs
        value={tab}
        onChange={changeTab}
        className="mb-5"
        items={[
          { id: 'overview', label: 'Overview', icon: <Activity className="h-3.5 w-3.5" /> },
          {
            id: 'signals',
            label: 'Signals',
            icon: <Zap className="h-3.5 w-3.5" />,
            count: signals.length || undefined,
          },
          {
            id: 'evidence',
            label: 'Evidence',
            icon: <FileText className="h-3.5 w-3.5" />,
            count: entity.evidence_count ?? entity.evidence?.length ?? evidence?.total,
          },
          {
            id: 'relations',
            label: 'Relations',
            icon: <Share2 className="h-3.5 w-3.5" />,
            count: relatedRows.length || undefined,
          },
          {
            id: 'cases',
            label: 'Cases',
            icon: <Briefcase className="h-3.5 w-3.5" />,
            count: entity.cases?.length ?? cases?.total,
          },
        ]}
      />

      <div role="tabpanel" aria-label={tab}>
        {tab === 'overview' && renderOverview()}
        {tab === 'signals' && renderSignals()}
        {tab === 'evidence' && renderEvidence()}
        {tab === 'relations' && renderRelations()}
        {tab === 'cases' && renderCases()}
      </div>

      {/* delete confirm */}
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
        loading={deleteBusy}
        destructive
        title="Delete asset"
        confirmLabel="Delete"
        message={
          <>
            Delete <span className="font-semibold text-ink">{entity.display_name}</span> and its linked evidence? This
            cannot be undone. Linked cases keep their history.
          </>
        }
      />
    </div>
  );
};

export default EntityDetailPage;
