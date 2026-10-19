import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ExternalLink,
  Image as ImageIcon,
  Info,
  Link2,
  RefreshCw,
  Search,
  UserRound,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge, ProvenanceBadge, SeverityBadge } from '../components/ui/badge';
import { Tabs } from '../components/ui/tabs';
import { DataTable, EmptyState, ErrorState, Pagination, type Column } from '../components/ui/table';
import { Modal } from '../components/ui/modal';
import { ScoreBar, ScoreRing, scoreSeverity, severityColor } from '../components/ui/score';
import {
  DateRangeSelect,
  FilterSelect,
  LoadingBlock,
  SearchInput,
  Skeleton,
  Tooltip,
  rangeToDates,
  type DateRangeValue,
  type RangeKey,
} from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { detectionService } from '../services/detectionService';
import {
  DetectionItem,
  DetectionModelInfo,
  DetectionSignal,
  PaginatedResponse,
  RiskAssessment,
  SignalType,
} from '../types';
import {
  DETECTION_STATUS_LABELS,
  ENTITY_TYPE_LABELS,
  PROVENANCE_LABELS,
  SEVERITY_LABELS,
  SIGNAL_STATUS_LABELS,
  SIGNAL_TYPE_LABELS,
} from '../lib/constants';
import { cn } from '../lib/utils';
import { formatDate, formatRelativeTime } from '../lib/formatters';

/* ------------------------------------------------------------------ */
/* Local helpers & constants                                            */
/* ------------------------------------------------------------------ */

interface ConfidenceInfo {
  weights?: Record<string, number>;
  provenance_factors?: Record<string, number>;
  synthetic_cap?: number;
  labels?: Record<string, number>;
}

/** Backend /detection/model returns more fields than the shared type declares. */
type ModelInfoFull = DetectionModelInfo & {
  severity_thresholds?: Record<string, number>;
  confidence?: ConfidenceInfo;
  status?: string;
};

const SIGNAL_META: Record<SignalType, { color: string; icon: React.ReactNode }> = {
  brand_logo: { color: '#F59E0B', icon: <ImageIcon className="h-3.5 w-3.5" /> },
  impersonation: { color: '#8B5CF6', icon: <UserRound className="h-3.5 w-3.5" /> },
  url_risk: { color: '#4778F5', icon: <Link2 className="h-3.5 w-3.5" /> },
  behavior: { color: '#20C5D7', icon: <Activity className="h-3.5 w-3.5" /> },
};

const STATUS_TONE: Record<string, 'success' | 'warning' | 'default'> = {
  analyzed: 'success',
  partial: 'warning',
  unavailable: 'default',
};

function signalStatusTone(status: string): 'success' | 'warning' | 'default' | 'danger' {
  if (status === 'ok') return 'success';
  if (status === 'failed') return 'danger';
  return 'default';
}

const TAB_IDS = ['results', 'signals', 'model'] as const;
type TabId = (typeof TAB_IDS)[number];

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'unknown'];
const ENTITY_TYPES = ['social_profile', 'website', 'domain', 'image', 'mobile_app'];
const DETECTION_STATUSES = ['analyzed', 'partial', 'unavailable'];

function signalMeta(signalType?: SignalType | null) {
  return SIGNAL_META[(signalType || 'behavior') as SignalType] || SIGNAL_META.behavior;
}

/* ------------------------------------------------------------------ */
/* Page                                                                 */
/* ------------------------------------------------------------------ */

export const ThreatIntelPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { toast } = useToast();
  const { activeBrand } = useAuth();
  // brand scope: the brand chosen at login (admins have none → global view), same as the risk graph
  const brandId = activeBrand?.id;

  /* ---------------- URL state ---------------- */
  const tab = ((): TabId => {
    const t = searchParams.get('tab');
    return TAB_IDS.includes(t as TabId) ? (t as TabId) : 'results';
  })();
  const q = searchParams.get('q') || '';
  const severity = searchParams.get('severity') || '';
  const entityType = searchParams.get('entity_type') || '';
  const status = searchParams.get('status') || '';
  // "Purpose" in the UI = the entity's provenance (manual / collected / synthetic)
  const purpose = searchParams.get('purpose') || '';
  const rangeKey = searchParams.get('range') || '';
  const customFrom = searchParams.get('from') || '';
  const customTo = searchParams.get('to') || '';
  const sort = searchParams.get('sort') || 'assessed_at';
  const order: 'asc' | 'desc' = searchParams.get('order') === 'asc' ? 'asc' : 'desc';
  const page = Math.max(1, Number(searchParams.get('page') || 1));
  const pageSize = [10, 20, 50, 100].includes(Number(searchParams.get('page_size')))
    ? Number(searchParams.get('page_size'))
    : 20;

  const setParams = useCallback(
    (patch: Record<string, string | number | undefined>, resetPage = true) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === undefined || v === '' || v === null) next.delete(k);
            else next.set(k, String(v));
          }
          if (resetPage && !('page' in patch)) next.delete('page');
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  /* ---------------- Derived date range ---------------- */
  const { from, to } = useMemo(() => {
    if (!rangeKey) return { from: undefined, to: undefined };
    if (rangeKey === 'custom') {
      return { from: customFrom || undefined, to: customTo || undefined };
    }
    return rangeToDates({ key: rangeKey as RangeKey });
  }, [rangeKey, customFrom, customTo]);

  const rangeValue: DateRangeValue = useMemo(
    () => ({ key: (rangeKey || 'custom') as RangeKey, from: customFrom || undefined, to: customTo || undefined }),
    [rangeKey, customFrom, customTo]
  );

  /* ---------------- List state ---------------- */
  const [result, setResult] = useState<{ items: DetectionItem[]; total: number; pages: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    detectionService
      .listDetections({
        q: q || undefined,
        severity: severity || undefined,
        entity_type: entityType || undefined,
        status: status || undefined,
        provenance: purpose || undefined,
        brand_id: brandId,
        from,
        to,
        sort,
        order,
        page,
        page_size: pageSize,
      })
      .then((res) => {
        if (cancelled) return;
        setResult({ items: res.items, total: res.total, pages: res.pages });
        setLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load detections.');
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, severity, entityType, status, purpose, brandId, from, to, sort, order, page, pageSize, refreshKey]);

  /* ---------------- Stat strip (parallel light totals) ---------------- */
  const [stats, setStats] = useState<{ total: number; critical: number; high: number; medium: number; low: number } | null>(
    null
  );

  useEffect(() => {
    let cancelled = false;
    // same filter set as the table (minus the per-bucket severity) so the strip always matches the rows
    const base = {
      q: q || undefined,
      entity_type: entityType || undefined,
      status: status || undefined,
      provenance: purpose || undefined,
      brand_id: brandId,
      from,
      to,
      page_size: 1,
    };
    Promise.all([
      detectionService.listDetections(base),
      detectionService.listDetections({ ...base, severity: 'critical' }),
      detectionService.listDetections({ ...base, severity: 'high' }),
      detectionService.listDetections({ ...base, severity: 'medium' }),
      detectionService.listDetections({ ...base, severity: 'low' }),
    ])
      .then(([all, crit, high, med, low]) => {
        if (cancelled) return;
        setStats({
          total: all.total,
          critical: crit.total,
          high: high.total,
          medium: med.total,
          low: low.total,
        });
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, entityType, status, purpose, brandId, from, to, refreshKey]);

  /* ---------------- Signals tab (real signal results) ---------------- */
  const [sigType, setSigType] = useState('');
  const [sigStatus, setSigStatus] = useState('');
  const [sigPage, setSigPage] = useState(1);
  const [sigPageSize, setSigPageSize] = useState(20);
  const [signals, setSignals] = useState<PaginatedResponse<DetectionSignal> | null>(null);
  const [sigLoading, setSigLoading] = useState(true);
  const [sigError, setSigError] = useState<string | null>(null);
  const [sigNonce, setSigNonce] = useState(0);

  useEffect(() => {
    if (tab !== 'signals') return; // lazy-load: only fetch when the tab is open
    let cancelled = false;
    setSigLoading(true);
    setSigError(null);
    detectionService
      .listSignals({
        signal_type: sigType || undefined,
        status: sigStatus || undefined,
        page: sigPage,
        page_size: sigPageSize,
      })
      .then((res) => {
        if (cancelled) return;
        setSignals(res);
        setSigLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setSigError(err.message || 'Failed to load signals.');
        setSigLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, sigType, sigStatus, sigPage, sigPageSize, sigNonce]);

  /* ---------------- Selection + detail modal ---------------- */
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailItem, setDetailItem] = useState<DetectionItem | null>(null);
  const [assessment, setAssessment] = useState<RiskAssessment | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);

  useEffect(() => {
    if (!detailId) {
      setAssessment(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    detectionService
      .getAssessment(detailId)
      .then((a) => {
        if (!cancelled) {
          setAssessment(a);
          setDetailLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setDetailError(err.message || 'Failed to load the full assessment.');
          setDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detailId, detailRetry]);

  const openDetail = useCallback((item: DetectionItem) => {
    setSelectedId(item.id);
    setDetailItem(item);
    setDetailId(item.id);
  }, []);

  /* ---------------- Re-analyze ---------------- */
  const [toolbarReanalyzing, setToolbarReanalyzing] = useState(false);
  const [modalReanalyzing, setModalReanalyzing] = useState(false);

  const runReanalyze = useCallback(
    async (assessmentId: string, setBusy: (v: boolean) => void, refreshList: boolean) => {
      setBusy(true);
      try {
        const fresh = await detectionService.reAnalyze(assessmentId);
        toast.success('Rule-based heuristic re-analysis completed', 'Scores and explanations were refreshed.');
        if (refreshList) {
          setDetailId(assessmentId);
        } else {
          setAssessment(fresh);
        }
        setRefreshKey((k) => k + 1);
      } catch (err) {
        toast.error('Re-analysis failed', err instanceof Error ? err.message : undefined);
      } finally {
        setBusy(false);
      }
    },
    [toast]
  );

  /* ---------------- Model info (signals + model tabs) ---------------- */
  const [model, setModel] = useState<ModelInfoFull | null>(null);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  useEffect(() => {
    if (tab === 'results' || model || modelLoading) return;
    let cancelled = false;
    setModelLoading(true);
    detectionService
      .getModel()
      .then((m) => {
        if (!cancelled) {
          setModel(m as ModelInfoFull);
          setModelLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setModelError(err.message || 'Failed to load model information.');
          setModelLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tab, model, modelLoading]);

  /* ---------------- Table columns ---------------- */
  const columns: Column<DetectionItem>[] = useMemo(
    () => [
      {
        key: 'type',
        header: 'Type',
        className: 'min-w-[190px]',
        cell: (row) => {
          const meta = signalMeta(row.signal_type);
          return (
            <div className="flex items-center gap-2.5">
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                style={{ backgroundColor: `${meta.color}18`, color: meta.color }}
                aria-hidden="true"
              >
                {meta.icon}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold text-ink">{row.detection_type}</span>
                <span className="block text-[11px] text-muted">
                  {row.signal_type ? SIGNAL_TYPE_LABELS[row.signal_type] || row.signal_type : 'No signal'}
                </span>
              </span>
            </div>
          );
        },
      },
      {
        key: 'entity',
        header: 'Entity',
        className: 'min-w-[180px]',
        cell: (row) => (
          <span className="block min-w-0">
            <Link
              to={`/entities/${row.entity.id}`}
              onClick={(e) => e.stopPropagation()}
              className="block truncate text-[13px] font-semibold text-ink transition-colors hover:text-brand-600 focus-ring rounded"
            >
              {row.entity.display_name}
            </Link>
            <span className="block text-[11px] text-muted">
              {ENTITY_TYPE_LABELS[row.entity.entity_type] || row.entity.entity_type}
              {row.entity.platform ? ` · ${row.entity.platform}` : ''}
            </span>
          </span>
        ),
      },
      {
        key: 'risk_score',
        header: 'Score',
        sortable: true,
        className: 'w-[150px]',
        cell: (row) => (
          <div>
            <span
              className="text-[13px] font-bold tabular-nums"
              style={{ color: severityColor(row.severity) }}
            >
              {row.risk_score === null || row.risk_score === undefined ? '—' : row.risk_score.toFixed(2)}
            </span>
            <ScoreBar value={row.risk_score} severity={row.severity} showLabel={false} className="mt-1" />
          </div>
        ),
      },
      {
        key: 'confidence',
        header: 'Confidence',
        sortable: true,
        className: 'w-[100px]',
        cell: (row) => (
          <span className="text-[13px] font-semibold tabular-nums text-ink-700">
            {row.confidence === null || row.confidence === undefined ? '—' : row.confidence.toFixed(2)}
          </span>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        className: 'w-[120px]',
        cell: (row) => (
          <Badge tone={STATUS_TONE[row.status] || 'default'}>
            {DETECTION_STATUS_LABELS[row.status] || row.status}
          </Badge>
        ),
      },
      {
        key: 'explanation',
        header: 'Explanation',
        className: 'max-w-[280px]',
        cell: (row) =>
          row.explanation ? (
            <Tooltip
              content={row.explanation}
              className="block w-full [&>span:last-child]:w-72 [&>span:last-child]:whitespace-normal"
            >
              <span className="line-clamp-2 block w-full text-[12px] leading-relaxed text-muted">
                {row.explanation}
              </span>
            </Tooltip>
          ) : (
            <span className="text-[12px] text-faint">—</span>
          ),
      },
      {
        key: 'assessed_at',
        header: 'Detected',
        sortable: true,
        className: 'w-[130px]',
        cell: (row) => (
          <Tooltip content={formatDate(row.assessed_at)}>
            <span className="text-[12px] text-muted">{formatRelativeTime(row.assessed_at)}</span>
          </Tooltip>
        ),
      },
    ],
    []
  );

  const hasFilters = !!(q || severity || entityType || status || purpose || rangeKey);
  const clearFilters = () =>
    setParams({ q: undefined, severity: undefined, entity_type: undefined, status: undefined, purpose: undefined, range: undefined, from: undefined, to: undefined });

  /* ---------------- Stat strip rendering ---------------- */
  const statCards = stats
    ? [
        { label: 'Total detections', value: stats.total, color: '#4778F5' },
        {
          label: 'High risk',
          value: stats.high + stats.critical,
          color: '#F04464',
          hint: stats.critical > 0 ? `${stats.critical} critical` : undefined,
        },
        { label: 'Medium risk', value: stats.medium, color: '#F59E0B' },
        { label: 'Low risk', value: stats.low, color: '#10B981' },
      ]
    : null;

  /* ---------------- Model-based tabs ---------------- */
  const ruleDescriptions = model?.rule_description || [];
  const weights = model?.weights || {};
  const thresholds = model?.severity_thresholds || null;
  const confidenceInfo = model?.confidence;

  /* ---------------- Signals tab body (real signal results) ---------------- */
  const sigColumns: Column<DetectionSignal>[] = [
    {
      key: 'entity',
      header: 'Entity',
      cell: (s) =>
        s.entity ? (
          <Link
            to={`/entities/${s.entity_id}`}
            className="block truncate text-[13px] font-semibold text-ink transition-colors hover:text-brand-600 focus-ring rounded"
          >
            {s.entity.display_name}
            <span className="mt-0.5 block text-[11px] font-medium text-faint">
              {ENTITY_TYPE_LABELS[s.entity.entity_type] || s.entity.entity_type}
            </span>
          </Link>
        ) : (
          <span className="text-[12px] text-faint">{s.entity_id.slice(0, 8)}…</span>
        ),
    },
    {
      key: 'signal_type',
      header: 'Signal',
      cell: (s) => {
        const meta = signalMeta(s.signal_type);
        return (
          <span className="flex items-center gap-2">
            <span
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
              style={{ backgroundColor: `${meta.color}18`, color: meta.color }}
              aria-hidden="true"
            >
              {meta.icon}
            </span>
            <span className="text-[12.5px] font-semibold text-ink">
              {SIGNAL_TYPE_LABELS[s.signal_type] || s.signal_type}
            </span>
          </span>
        );
      },
    },
    {
      key: 'status',
      header: 'Status',
      cell: (s) => <Badge tone={signalStatusTone(s.status)}>{SIGNAL_STATUS_LABELS[s.status] || s.status}</Badge>,
    },
    {
      key: 'score',
      header: 'Score',
      className: 'w-[90px]',
      cell: (s) => (
        <span className="text-[12.5px] font-bold tabular-nums text-ink-700">
          {s.score != null ? s.score.toFixed(2) : '—'}
        </span>
      ),
    },
    {
      key: 'explanation',
      header: 'Explanation',
      cell: (s) => (
        <span className="line-clamp-2 max-w-[420px] text-[12px] text-muted" title={s.explanation}>
          {s.explanation || '—'}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: 'Detected',
      className: 'w-[130px]',
      cell: (s) => (
        <Tooltip content={formatDate(s.created_at)}>
          <span className="text-[12px] text-muted">{formatRelativeTime(s.created_at)}</span>
        </Tooltip>
      ),
    },
  ];

  const renderSignalsBody = () => {
    const sigFiltersActive = !!(sigType || sigStatus);
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <FilterSelect
            label="Signal type"
            value={sigType}
            onChange={(v) => {
              setSigType(v);
              setSigPage(1);
            }}
            options={Object.entries(SIGNAL_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <FilterSelect
            label="Signal status"
            value={sigStatus}
            onChange={(v) => {
              setSigStatus(v);
              setSigPage(1);
            }}
            options={Object.entries(SIGNAL_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
          />
          {sigFiltersActive && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSigType('');
                setSigStatus('');
                setSigPage(1);
              }}
            >
              Clear filters
            </Button>
          )}
          <div className="ml-auto">
            <Button
              variant="outline"
              icon={<RefreshCw className="h-4 w-4" />}
              onClick={() => setSigNonce((k) => k + 1)}
              aria-label="Refresh signals"
            >
              Refresh
            </Button>
          </div>
        </div>

        <Card>
          {sigLoading && !signals && (
            <div className="space-y-3 p-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={`sig-sk-${i}`} className="h-11 w-full" />
              ))}
            </div>
          )}

          {sigError && !sigLoading && (
            <ErrorState title="Failed to load signals" message={sigError} onRetry={() => setSigNonce((k) => k + 1)} />
          )}

          {!sigError && signals && signals.items.length === 0 && !sigLoading && (
            <EmptyState
              icon={<Activity className="h-6 w-6" />}
              title="No signals match"
              description={
                sigFiltersActive
                  ? 'Try adjusting the signal type or status filters.'
                  : 'Signals appear here once entities have been analyzed by the detection engine.'
              }
              action={
                sigFiltersActive ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSigType('');
                      setSigStatus('');
                      setSigPage(1);
                    }}
                  >
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          )}

          {!sigError && signals && signals.items.length > 0 && (
            <DataTable<DetectionSignal> columns={sigColumns} rows={signals.items} rowKey={(s) => s.id} />
          )}

          {!sigError && signals && !sigLoading && (
            <Pagination
              page={sigPage}
              pages={signals.pages}
              total={signals.total}
              onPageChange={(p) => setSigPage(p)}
              pageSize={sigPageSize}
              onPageSizeChange={(s) => {
                setSigPageSize(s);
                setSigPage(1);
              }}
              className="border-t border-line-soft"
            />
          )}
        </Card>
      </div>
    );
  };

  /* ---------------- Risk Assessment tab body ---------------- */
  const renderModelBody = () => {
    if (modelLoading && !model) return <LoadingBlock label="Loading model information…" />;
    if (modelError && !model)
      return <ErrorState title="Model information unavailable" message={modelError} onRetry={() => setRefreshKey((k) => k + 1)} />;
    if (!model) return null;

    return (
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle>Scoring model</CardTitle>
                <Badge tone="primary">v{model.model_version}</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <dl className="divide-y divide-line-soft">
                {Object.entries(weights).map(([k, w]) => (
                  <div key={k} className="flex items-center justify-between gap-3 py-2.5">
                    <span className="text-[13px] font-medium text-ink">
                      {SIGNAL_TYPE_LABELS[k] || k.replace(/_/g, ' ')}
                    </span>
                    <span className="flex min-w-[120px] items-center gap-2">
                      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-line-soft">
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${Math.min(100, w * 100)}%`,
                            backgroundColor: signalMeta(k as SignalType).color,
                          }}
                        />
                      </span>
                      <span className="w-9 text-right text-[12px] font-bold tabular-nums text-ink-700">
                        {Math.round(w * 100)}%
                      </span>
                    </span>
                  </div>
                ))}
              </dl>
              {model.status && (
                <p className="mt-3 flex items-start gap-2 rounded-xl bg-bg p-3 text-[12px] leading-relaxed text-muted">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" aria-hidden="true" />
                  {model.status}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Severity thresholds</CardTitle>
            </CardHeader>
            <CardContent>
              {thresholds ? (
                <>
                  <div className="relative mt-6 mb-10 h-2.5 rounded-full bg-gradient-to-r from-[#10B981] via-[#F59E0B] to-[#E11D48]" />
                  <div className="relative h-0">
                    {(['medium', 'high', 'critical'] as const).map((k) => {
                      const v = thresholds[k];
                      if (typeof v !== 'number') return null;
                      const color = severityColor(k);
                      return (
                        <div
                          key={k}
                          className="absolute -translate-x-1/2"
                          style={{ left: `${Math.min(100, Math.max(0, v * 100))}%` }}
                        >
                          <span
                            className="block h-4 w-0.5 rounded"
                            style={{ backgroundColor: color }}
                            aria-hidden="true"
                          />
                          <span
                            className="mt-1 block whitespace-nowrap text-center text-[11px] font-bold"
                            style={{ color }}
                          >
                            {SEVERITY_LABELS[k]}
                            <span className="block font-medium text-faint">{v.toFixed(2)}</span>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <p className="mt-12 text-[12px] leading-relaxed text-muted">
                    Combined risk scores map to severities on a 0–1 scale. Scores at or above a marker inherit that
                    severity (critical ≥ high ≥ medium).
                  </p>
                </>
              ) : (
                <p className="text-[13px] text-muted">This model version does not publish severity thresholds.</p>
              )}
            </CardContent>
          </Card>
        </div>

        {confidenceInfo && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Confidence components</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-5 md:grid-cols-2">
                {confidenceInfo.weights && (
                  <div>
                    <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-faint">Score weights</p>
                    <dl className="divide-y divide-line-soft">
                      {Object.entries(confidenceInfo.weights).map(([k, w]) => (
                        <div key={k} className="flex items-center justify-between py-2">
                          <span className="text-[13px] font-medium capitalize text-ink">{k.replace(/_/g, ' ')}</span>
                          <span className="text-[12px] font-bold tabular-nums text-ink-700">
                            {Math.round(w * 100)}%
                          </span>
                        </div>
                      ))}
                    </dl>
                  </div>
                )}
                {confidenceInfo.provenance_factors && (
                  <div>
                    <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-faint">
                      Provenance factors
                    </p>
                    <dl className="divide-y divide-line-soft">
                      {Object.entries(confidenceInfo.provenance_factors).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between py-2">
                          <span className="text-[13px] font-medium capitalize text-ink">{k}</span>
                          <span className="text-[12px] font-bold tabular-nums text-ink-700">
                            {Number(v).toFixed(2)}
                          </span>
                        </div>
                      ))}
                    </dl>
                    {typeof confidenceInfo.synthetic_cap === 'number' && (
                      <p className="mt-2 text-[12px] text-muted">
                        Synthetic sample data is capped at {confidenceInfo.synthetic_cap.toFixed(2)} confidence.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Plain-English rule descriptions (moved here from the Signals tab, which now lists real signals) */}
        <section>
          <div className="mb-3 flex items-start gap-3 rounded-2xl border border-warning-100 bg-warning-100/50 p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning-600" aria-hidden="true" />
            <div>
              <p className="text-[13px] font-bold text-ink">Hand-written rules, not a trained model</p>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">
                Each signal family below is a transparent heuristic computed from observable data. Weights decide how
                much each family contributes to the combined risk score. Every result still requires analyst review —
                confirm with evidence before taking action.
              </p>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {ruleDescriptions.map((r) => {
              const w = weights[r.signal_type];
              const meta = signalMeta(r.signal_type as SignalType);
              return (
                <Card key={r.signal_type}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <span
                          className="flex h-8 w-8 items-center justify-center rounded-lg"
                          style={{ backgroundColor: `${meta.color}18`, color: meta.color }}
                          aria-hidden="true"
                        >
                          {meta.icon}
                        </span>
                        <CardTitle>{r.label}</CardTitle>
                      </div>
                      <Badge tone="outline">
                        {typeof w === 'number' ? `${Math.round(w * 100)}% weight` : 'n/a'}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-[12.5px] leading-relaxed text-muted">{r.rules}</p>
                    {typeof w === 'number' && (
                      <div className="mt-3">
                        <div className="h-1.5 overflow-hidden rounded-full bg-line-soft">
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${Math.min(100, w * 100)}%`, backgroundColor: meta.color }}
                          />
                        </div>
                        <p className="mt-1 text-[11px] font-semibold text-faint">
                          Contributes {Math.round(w * 100)}% of the combined score (when available)
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
            {ruleDescriptions.length === 0 && (
              <p className="text-[13px] text-muted md:col-span-2">
                This model version does not publish per-family rule descriptions.
              </p>
            )}
          </div>
        </section>

        <div className="flex items-start gap-3 rounded-2xl border border-brand-100 bg-brand-gradient-soft p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
          <div>
            <p className="text-[13px] font-bold text-ink">Heuristic, unvalidated — confirm with evidence</p>
            <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted">
              These scores are transparent heuristics, not validated predictions. They are not calibrated against
              ground truth and sample (synthetic) data is explicitly labelled. Treat every score as a triage signal
              only: verify with collected evidence and analyst judgement before any enforcement or takedown action.
            </p>
          </div>
        </div>
      </div>
    );
  };

  /* ---------------- Render ---------------- */
  return (
    <>
      <PageHeader
        title="Threat Intelligence"
        description="Rule-based detection results across your monitored assets — every score is an explainable heuristic requiring analyst review."
        actions={
          <Button
            variant="outline"
            icon={<RefreshCw className="h-4 w-4" />}
            onClick={() => setRefreshKey((k) => k + 1)}
            aria-label="Refresh detections"
          >
            Refresh
          </Button>
        }
      >
        <div className="mt-4">
          <Tabs
            value={tab}
            onChange={(id) => setParams({ tab: id === 'results' ? undefined : id }, false)}
            items={[
              { id: 'results', label: 'Detection Results' },
              { id: 'signals', label: 'Signals' },
              { id: 'model', label: 'Risk Assessment' },
            ]}
          />
        </div>
      </PageHeader>

      {tab === 'results' && (
        <>
          {/* Toolbar */}
          <div className="mb-4 flex flex-wrap items-center gap-2.5">
            <SearchInput
              value={q}
              onChange={(v) => setParams({ q: v })}
              placeholder="Search threats, domains, hashes…"
              debounceMs={350}
              className="w-full sm:w-72"
            />
            <DateRangeSelect
              value={rangeValue}
              onChange={(v) => {
                if (v.key === 'custom') setParams({ range: 'custom', from: v.from, to: v.to });
                else setParams({ range: v.key, from: undefined, to: undefined });
              }}
            />
            <FilterSelect
              label="Entity type"
              value={entityType}
              onChange={(v) => setParams({ entity_type: v })}
              options={ENTITY_TYPES.map((t) => ({ value: t, label: ENTITY_TYPE_LABELS[t] || t }))}
            />
            <FilterSelect
              label="Severity"
              value={severity}
              onChange={(v) => setParams({ severity: v })}
              options={SEVERITIES.map((s) => ({ value: s, label: SEVERITY_LABELS[s] || s }))}
            />
            <FilterSelect
              label="Detection status"
              value={status}
              onChange={(v) => setParams({ status: v })}
              options={DETECTION_STATUSES.map((s) => ({ value: s, label: DETECTION_STATUS_LABELS[s] || s }))}
            />
            <FilterSelect
              label="Purpose"
              value={purpose}
              onChange={(v) => setParams({ purpose: v })}
              allLabel="Any purpose"
              options={Object.entries(PROVENANCE_LABELS).map(([value, label]) => ({ value, label }))}
            />
            <div className="ml-auto flex items-center gap-2.5">
              {hasFilters && (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              )}
              <Button
                variant="outline"
                icon={<RefreshCw className="h-4 w-4" />}
                loading={toolbarReanalyzing}
                disabled={!selectedId || toolbarReanalyzing}
                onClick={() => selectedId && void runReanalyze(selectedId, setToolbarReanalyzing, true)}
                title={selectedId ? 'Re-run detection for the selected row' : 'Select a row to re-analyze'}
              >
                Re-analyze
              </Button>
            </div>
          </div>

          {/* Stat strip */}
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {statCards
              ? statCards.map((c) => {
                  const share = stats && stats.total > 0 ? Math.round((c.value / stats.total) * 100) : 0;
                  return (
                    <Card key={c.label} className="p-4">
                      <p className="text-[11px] font-bold uppercase tracking-wider text-faint">{c.label}</p>
                      <div className="mt-1.5 flex items-baseline gap-2">
                        <span className="text-2xl font-extrabold tabular-nums tracking-tight text-ink">
                          {c.value.toLocaleString()}
                        </span>
                        <span className="text-[11px] font-semibold" style={{ color: c.color }}>
                          {stats && stats.total > 0 ? `${share}%` : '—'}
                        </span>
                        {c.hint && <span className="text-[11px] font-semibold text-danger">{c.hint}</span>}
                      </div>
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-line-soft">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${share}%`, backgroundColor: c.color }}
                        />
                      </div>
                    </Card>
                  );
                })
              : Array.from({ length: 4 }).map((_, i) => (
                  <Card key={`sk${i}`} className="p-4">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="mt-2.5 h-7 w-16" />
                    <Skeleton className="mt-2.5 h-1 w-full" />
                  </Card>
                ))}
          </div>

          {/* Table */}
          <Card>
            <DataTable
              columns={columns}
              rows={result?.items || []}
              rowKey={(row) => row.id}
              sort={sort}
              order={order}
              onSortChange={(key) => {
                if (sort === key) setParams({ sort: key, order: order === 'asc' ? 'desc' : 'asc' }, false);
                else setParams({ sort: key, order: 'desc' }, false);
              }}
              onRowClick={openDetail}
              isRowSelected={(row) => row.id === selectedId}
              loading={loading && !result}
              emptyState={
                error ? (
                  <ErrorState title="Failed to load detections" message={error} onRetry={() => setRefreshKey((k) => k + 1)} />
                ) : (
                  <EmptyState
                    icon={<Search className="h-6 w-6" />}
                    title="No detections match"
                    description={
                      hasFilters
                        ? 'Try adjusting your search or filters — detections appear once entities have been analyzed.'
                        : 'Detections appear here once entities have been analyzed by the detection engine.'
                    }
                    action={
                      hasFilters ? (
                        <Button variant="outline" size="sm" onClick={clearFilters}>
                          Clear filters
                        </Button>
                      ) : undefined
                    }
                  />
                )
              }
            />
            {error && result && (
              <div className="border-t border-line-soft px-5 py-3 text-[12.5px] text-danger">
                Refresh failed: {error} — showing last loaded results.
              </div>
            )}
            {result && !loading && (
              <Pagination
                page={page}
                pages={result.pages}
                total={result.total}
                onPageChange={(p) => setParams({ page: p }, false)}
                pageSize={pageSize}
                onPageSizeChange={(s) => setParams({ page_size: s, page: 1 }, false)}
                className="border-t border-line-soft"
              />
            )}
          </Card>
        </>
      )}

      {tab === 'signals' && renderSignalsBody()}
      {tab === 'model' && renderModelBody()}

      {/* Detection details modal */}
      <Modal
        open={!!detailId}
        onClose={() => setDetailId(null)}
        size="lg"
        title={
          detailItem ? (
            <span className="flex flex-wrap items-center gap-2">
              {detailItem.entity.display_name}
              <SeverityBadge severity={assessment?.severity ?? detailItem.severity} />
              <ProvenanceBadge provenance={detailItem.entity.provenance} />
            </span>
          ) : (
            'Detection details'
          )
        }
        description={
          detailItem
            ? `${ENTITY_TYPE_LABELS[detailItem.entity.entity_type] || detailItem.entity.entity_type}${
                detailItem.entity.platform ? ` · ${detailItem.entity.platform}` : ''
              } · ${detailItem.entity.canonical_id}`
            : undefined
        }
        footer={
          <>
            {detailItem && (
              <Link
                to={`/entities/${detailItem.entity.id}`}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-line bg-white px-4 text-sm font-semibold text-ink-700 shadow-sm transition-colors hover:border-brand-200 hover:bg-bg focus-ring"
              >
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                Open entity
              </Link>
            )}
            <Button
              variant="primary"
              icon={<RefreshCw className="h-4 w-4" />}
              loading={modalReanalyzing}
              disabled={!detailId || modalReanalyzing}
              onClick={() => detailId && void runReanalyze(detailId, setModalReanalyzing, false)}
            >
              Re-analyze now
            </Button>
          </>
        }
      >
        {detailLoading && (
          <div className="space-y-4">
            <div className="flex gap-6">
              <Skeleton className="h-24 w-24 rounded-full" />
              <Skeleton className="h-24 w-24 rounded-full" />
            </div>
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {!detailLoading && detailError && (
          <ErrorState
            title="Could not load the full assessment"
            message={detailError}
            onRetry={() => setDetailRetry((n) => n + 1)}
          />
        )}

        {!detailLoading && !detailError && assessment && (
          <div className="space-y-5">
            {/* Scores */}
            <div className="flex flex-wrap items-start gap-8 rounded-2xl border border-line-soft bg-bg/60 p-5">
              <ScoreRing value={assessment.risk_score} label="Risk score" severity={assessment.severity} size={92} />
              <ScoreRing value={assessment.confidence_score} label="Confidence" size={92} />
              <div className="min-w-[200px] flex-1 space-y-1 text-[12.5px] text-muted">
                <p>
                  <span className="font-semibold text-ink">Model:</span> v{assessment.model_version}
                </p>
                <p>
                  <span className="font-semibold text-ink">Assessed:</span> {formatDate(assessment.assessed_at)}
                </p>
                {assessment.is_synthetic && (
                  <p className="text-warning-600">
                    Sample data — synthetic demo assessment, not a live threat.
                  </p>
                )}
                {assessment.notes && <p className="italic">{assessment.notes}</p>}
              </div>
            </div>

            {/* Explanation */}
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-faint">Explanation</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-700">
                {detailItem?.explanation ||
                  assessment.signals
                    .filter((s) => s.status === 'ok' && s.explanation)
                    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0]?.explanation ||
                  'No explanation was produced — no signal produced a score for this entity.'}
              </p>
            </section>

            {/* Signals breakdown */}
            <section>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-faint">
                Signals breakdown ({assessment.signals.length})
              </h3>
              <div className="mt-2 overflow-hidden rounded-xl border border-line-soft">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line-soft bg-bg/60">
                      <th className="px-3.5 py-2.5 text-[11px] font-bold uppercase tracking-wider text-faint">Signal</th>
                      <th className="px-3.5 py-2.5 text-[11px] font-bold uppercase tracking-wider text-faint">Status</th>
                      <th className="px-3.5 py-2.5 text-[11px] font-bold uppercase tracking-wider text-faint">Score</th>
                      <th className="px-3.5 py-2.5 text-[11px] font-bold uppercase tracking-wider text-faint">
                        Explanation
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {assessment.signals.map((s: DetectionSignal) => {
                      const meta = signalMeta(s.signal_type);
                      return (
                        <tr key={s.id} className="border-b border-line-soft last:border-0 align-top">
                          <td className="px-3.5 py-3">
                            <span className="flex items-center gap-2">
                              <span
                                className="flex h-6 w-6 items-center justify-center rounded-md"
                                style={{ backgroundColor: `${meta.color}18`, color: meta.color }}
                                aria-hidden="true"
                              >
                                {meta.icon}
                              </span>
                              <span className="text-[12.5px] font-semibold text-ink">
                                {SIGNAL_TYPE_LABELS[s.signal_type] || s.signal_type}
                              </span>
                            </span>
                          </td>
                          <td className="px-3.5 py-3">
                            <Badge tone={signalStatusTone(s.status)}>
                              {SIGNAL_STATUS_LABELS[s.status] || s.status}
                            </Badge>
                          </td>
                          <td className="px-3.5 py-3">
                            <span
                              className="text-[13px] font-bold tabular-nums"
                              style={{ color: severityColor(scoreSeverity(s.score)) }}
                            >
                              {s.score === null || s.score === undefined ? '—' : s.score.toFixed(2)}
                            </span>
                          </td>
                          <td className="max-w-[320px] px-3.5 py-3">
                            <p className="text-[12px] leading-relaxed text-muted">
                              {s.explanation || '—'}
                            </p>
                            {s.evidence_refs && s.evidence_refs.length > 0 && (
                              <details className="mt-1.5">
                                <summary className="cursor-pointer select-none text-[11px] font-semibold text-brand-600 hover:text-brand-700 focus-ring rounded">
                                  {s.evidence_refs.length} evidence reference{s.evidence_refs.length === 1 ? '' : 's'}
                                </summary>
                                <ul className="mt-1.5 space-y-1 rounded-lg bg-bg p-2.5">
                                  {s.evidence_refs.map((ref, i) => (
                                    <li key={i} className="font-mono text-[11px] leading-relaxed text-ink-700">
                                      {Object.entries(ref)
                                        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
                                        .join(' · ')}
                                    </li>
                                  ))}
                                </ul>
                              </details>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11.5px] text-faint">
                Unavailable signals are never scored as 0 — they are excluded and the remaining weights are
                renormalized.
              </p>
            </section>
          </div>
        )}
      </Modal>
    </>
  );
};

export default ThreatIntelPage;
