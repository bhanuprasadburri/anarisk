import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Briefcase,
  Check,
  ExternalLink,
  Eye,
  Info,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Smartphone,
  Trash2,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge, SeverityBadge } from '../components/ui/badge';
import { Modal, ConfirmDialog } from '../components/ui/modal';
import { Field, Input, Select } from '../components/ui/input';
import { DataTable, EmptyState, ErrorState, Pagination, type Column } from '../components/ui/table';
import { Dropdown } from '../components/ui/tabs';
import {
  CopyButton,
  FilterSelect,
  KeyValue,
  SearchInput,
  Tooltip,
} from '../components/ui/misc';
import { ScoreBar, ScoreRing, severityColor } from '../components/ui/score';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { monitoringService } from '../services/monitoringService';
import { dashboardService } from '../services/dashboardService';
import { ApiError } from '../services/apiClient';
import { STORE_LABELS } from '../lib/constants';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';
import { MonitoringTarget } from '../types';

/* ------------------------------------------------------------------ *
 * Store intake validation — mirrors the backend rules exactly so the
 * form tells the truth before the request is made.
 * ------------------------------------------------------------------ */

const GOOGLE_PLAY_PACKAGE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/;
const APP_STORE_NUMERIC = /^\d{8,15}$/;
const APP_STORE_SLUG = /^[A-Za-z][A-Za-z0-9._-]{2,64}$/;

const STORE_OPTIONS = [
  { value: 'google_play', label: 'Google Play' },
  { value: 'app_store', label: 'App Store' },
  { value: 'other', label: 'Other' },
];

const SEVERITY_OPTIONS = [
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
  { value: 'unknown', label: 'Unknown' },
];

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
];

const SORT_OPTIONS = [
  { value: 'package_id', label: 'Package ID' },
  { value: 'risk_score', label: 'Risk score' },
  { value: 'last_seen_at', label: 'Last seen' },
  { value: 'created_at', label: 'Date added' },
];

const SEVERITY_DOT_ORDER = ['critical', 'high', 'medium', 'low'];

function packageHint(store: string): string {
  if (store === 'google_play') return 'Expected: at least 3 dot-separated segments, e.g. com.example.app';
  if (store === 'app_store') return 'Expected: 8–15 digit id (e.g. 1234567890) or a slug such as my-great-app';
  return 'Expected: at least 3 characters';
}

function validatePackage(store: string, raw: string): string | null {
  const value = (raw || '').trim();
  if (!value) return 'Package ID is required';
  if (store === 'google_play') {
    return GOOGLE_PLAY_PACKAGE.test(value) && (value.match(/\./g) || []).length >= 2
      ? null
      : 'must be a Google Play package id with at least 3 dot-separated segments, e.g. com.example.app';
  }
  if (store === 'app_store') {
    return APP_STORE_NUMERIC.test(value) || APP_STORE_SLUG.test(value)
      ? null
      : 'must be an App Store id: 8–15 digits (e.g. 1234567890) or an alphanumeric slug (3–65 chars)';
  }
  return value.length >= 3 ? null : 'must be at least 3 characters';
}

function storeUrlHint(store: string, pkg: string): string {
  const p = (pkg || '').trim() || '<the same package id>';
  if (store === 'google_play') return `Expected: https://play.google.com/store/apps/details?id=${p}`;
  if (store === 'app_store') return `Expected: https://apps.apple.com/.../app/id${p}`;
  return 'Expected: a valid https URL';
}

function validateStoreUrl(store: string, pkg: string, raw: string): string | null {
  const url = (raw || '').trim();
  if (!url) return null; // optional
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return 'must be a valid https URL';
  }
  if (parsed.protocol !== 'https:') return 'must be a valid https URL';
  if (store === 'other') return null;
  const id = (pkg || '').trim();
  if (store === 'google_play') {
    const ok =
      parsed.hostname === 'play.google.com' &&
      parsed.pathname.startsWith('/store/apps/details') &&
      parsed.searchParams.get('id') === id;
    return ok ? null : `must be https://play.google.com/store/apps/details?id=${id || '<the same package_id>'}`;
  }
  const ok = parsed.hostname === 'apps.apple.com' && parsed.pathname.replace(/\/+$/, '').endsWith(`/id${id}`);
  return ok ? null : `must be https://apps.apple.com/.../app/id${id || '<package_id>'}`;
}

/** Extract `{field: message}` from a 422/409 ApiError, plus its top-level message. */
function readApiError(err: unknown): { fields: Record<string, string>; message: string } {
  const e = err as ApiError | undefined;
  const fields: Record<string, string> = {};
  const details = Array.isArray(e?.details)
    ? (e.details as Array<{ field?: string; message?: string }>)
    : [];
  details.forEach((d) => {
    if (d && d.field) fields[d.field] = d.message || 'Invalid value';
  });
  return { fields, message: e?.message || 'The request failed. Please try again.' };
}

const errMessage = (err: unknown): string =>
  (err as ApiError | undefined)?.message || 'The request failed. Please try again.';

/* ------------------------------------------------------------------ */

type FormState = {
  brand_id: string;
  store: string;
  package_id: string;
  store_url: string;
};

export const MobileAppsPage: React.FC = () => {
  const { brands, activeBrand, hasPermission } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const canSubmit = hasPermission('entity:submit');
  const canSync = hasPermission('connector:run');

  /* ---------------- URL-backed filter state ---------------- */
  const q = searchParams.get('q') || '';
  const severity = searchParams.get('severity') || '';
  const status = searchParams.get('status') || '';
  const store = searchParams.get('store') || '';
  const sort = searchParams.get('sort') || '';
  const order: 'asc' | 'desc' = searchParams.get('order') === 'asc' ? 'asc' : 'desc';
  const page = Math.max(1, parseInt(searchParams.get('page') || '1', 10) || 1);
  const pageSize = Math.min(100, Math.max(10, parseInt(searchParams.get('page_size') || '25', 10) || 25));

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          Object.entries(patch).forEach(([key, value]) => {
            if (value === null || value === '') next.delete(key);
            else next.set(key, value);
          });
          if (!('page' in patch)) next.delete('page');
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const clearFilters = () => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ['q', 'severity', 'status', 'store', 'page'].forEach((k) => next.delete(k));
        return next;
      },
      { replace: true }
    );
  };

  /* ---------------- data ---------------- */
  const listArgs = useMemo(
    () => ({
      q: q || undefined,
      store: store || undefined,
      risk_severity: severity || undefined,
      monitoring_status: status || undefined,
      page,
      page_size: pageSize,
      sort: sort || undefined,
      order,
    }),
    [q, store, severity, status, page, pageSize, sort, order]
  );

  const appsQuery = useQuery({
    queryKey: ['monitoring-apps', listArgs],
    queryFn: () => monitoringService.listApps(listArgs),
    placeholderData: keepPreviousData,
  });

  const summaryQuery = useQuery({
    queryKey: ['mobile-apps-summary'],
    queryFn: () => dashboardService.getMobileApps(),
  });

  const refetchAll = () => {
    queryClient.invalidateQueries({ queryKey: ['monitoring-apps'] });
    queryClient.invalidateQueries({ queryKey: ['mobile-apps-summary'] });
  };

  /** Rows come pre-filtered by the API (q / store / risk_severity / monitoring_status). */
  const rows = appsQuery.data?.items || [];

  const hasFilters = !!(q || severity || status || store);
  const loading = !appsQuery.data && (appsQuery.isPending || appsQuery.isFetching);

  // Deep-linked page numbers beyond the result set are clamped so the table never shows a false empty state.
  const totalPages = appsQuery.data?.pages;
  useEffect(() => {
    if (totalPages && page > totalPages) setParams({ page: String(totalPages) });
  }, [totalPages, page, setParams]);

  /* ---------------- honesty banner ---------------- */
  const [bannerOpen, setBannerOpen] = useState(
    () => localStorage.getItem('nimbus_monitoring_honesty_dismissed') !== '1'
  );
  const dismissBanner = () => {
    setBannerOpen(false);
    try {
      localStorage.setItem('nimbus_monitoring_honesty_dismissed', '1');
    } catch {
      /* storage unavailable — the banner simply returns next visit */
    }
  };

  /* ---------------- add app modal ---------------- */
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState<FormState>({
    brand_id: activeBrand?.id || '',
    store: 'google_play',
    package_id: '',
    store_url: '',
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const openAdd = () => {
    setForm({ brand_id: activeBrand?.id || brands[0]?.id || '', store: 'google_play', package_id: '', store_url: '' });
    setFieldErrors({});
    setFormError(null);
    setAddOpen(true);
  };

  const patchForm = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    setFieldErrors({});
    setFormError(null);
  };

  const livePackageError = form.package_id ? validatePackage(form.store, form.package_id) : null;
  const liveUrlError = form.store_url ? validateStoreUrl(form.store, form.package_id, form.store_url) : null;
  const packageError = fieldErrors.package_id || livePackageError;
  const urlError = fieldErrors.store_url || liveUrlError;

  const submitAdd = async () => {
    const errors: Record<string, string> = {};
    if (!form.brand_id) errors.brand_id = 'Select a brand to monitor this package for';
    const pkgErr = validatePackage(form.store, form.package_id);
    if (pkgErr) errors.package_id = pkgErr;
    const uErr = validateStoreUrl(form.store, form.package_id, form.store_url);
    if (uErr) errors.store_url = uErr;
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormError(null);
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const res = await monitoringService.addApp({
        brand_id: form.brand_id,
        package_id: form.package_id.trim(),
        store: form.store,
        store_url: form.store_url.trim() || undefined,
      });
      toast.success(
        'Monitoring started',
        res?.message ||
          'The package was added and linked to a mobile_app entity from the synthetic sample pipeline.'
      );
      setAddOpen(false);
      refetchAll();
    } catch (err) {
      const { fields, message } = readApiError(err);
      if ((err as ApiError)?.status === 409) {
        setFieldErrors({ package_id: message });
      } else if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
        setFormError(null);
      } else {
        setFormError(message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  /* ---------------- row actions ---------------- */
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MonitoringTarget | null>(null);
  const [removeTarget, setRemoveTarget] = useState<MonitoringTarget | null>(null);
  const [removing, setRemoving] = useState(false);

  const openDetails = (t: MonitoringTarget) => setDetail(t);

  const onSync = async (t: MonitoringTarget) => {
    setSyncingId(t.id);
    try {
      const res = await monitoringService.syncApp(t.id);
      toast.success('Sync complete', res.message);
      setDetail((prev) => (prev && prev.id === t.id ? res.target : prev));
      refetchAll();
    } catch (err) {
      toast.error('Sync failed', errMessage(err));
    } finally {
      setSyncingId(null);
    }
  };

  const onToggleStatus = async (t: MonitoringTarget) => {
    const next = t.monitoring_status === 'active' ? 'paused' : 'active';
    try {
      const updated = await monitoringService.updateApp(t.id, { monitoring_status: next });
      toast.success(
        next === 'paused' ? 'Monitoring paused' : 'Monitoring resumed',
        `${t.package_id} is now ${next}.`
      );
      setDetail((prev) => (prev && prev.id === t.id ? updated : prev));
      refetchAll();
    } catch (err) {
      toast.error('Could not update monitoring', errMessage(err));
    }
  };

  const onRemove = async () => {
    if (!removeTarget) return;
    setRemoving(true);
    try {
      await monitoringService.removeApp(removeTarget.id);
      toast.success(
        'Monitoring stopped',
        `${removeTarget.package_id} was removed from the watch list. The linked digital entity and its evidence were kept.`
      );
      setRemoveTarget(null);
      setDetail((prev) => (prev && prev.id === removeTarget.id ? null : prev));
      refetchAll();
    } catch (err) {
      toast.error('Could not stop monitoring', errMessage(err));
    } finally {
      setRemoving(false);
    }
  };

  /* ---------------- table ---------------- */
  const onSortChange = (key: string) => {
    if (sort === key) setParams({ sort: key, order: order === 'asc' ? 'desc' : 'asc' });
    else setParams({ sort: key, order: 'desc' });
  };

  const columns: Column<MonitoringTarget>[] = [
    {
      key: 'app',
      header: 'App',
      cell: (row) => (
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-cyanx-100 text-cyanx-600">
            <Smartphone className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13px] font-bold text-ink">
              {row.app_name || row.entity?.display_name || row.package_id}
            </p>
            <p className="truncate text-[11px] text-muted">{STORE_LABELS[row.store] || row.store}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'package_id',
      header: 'Package ID',
      sortable: true,
      cell: (row) => (
        <span
          className="inline-flex items-center gap-1"
          onClick={(e) => e.stopPropagation()}
          role="presentation"
        >
          <code className="font-mono text-[12px] text-ink-700">{row.package_id}</code>
          <CopyButton text={row.package_id} label="Copy package id" />
        </span>
      ),
    },
    {
      key: 'publisher',
      header: 'Publisher',
      cell: (row) =>
        row.publisher_name ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] text-ink-700">{row.publisher_name}</span>
            <Tooltip content="Publisher identity is never verified by this platform">
              <Badge tone="default" className="px-2 text-[10px] uppercase tracking-wide">
                unverified
              </Badge>
            </Tooltip>
          </span>
        ) : (
          <span className="text-faint">—</span>
        ),
    },
    {
      key: 'risk_score',
      header: 'Risk Score',
      sortable: true,
      cell: (row) => <ScoreBar value={row.entity?.risk_score ?? null} severity={row.entity?.severity} />,
    },
    {
      key: 'severity',
      header: 'Severity',
      cell: (row) => <SeverityBadge severity={row.entity?.severity} />,
    },
    {
      key: 'last_seen_at',
      header: 'Last Seen',
      sortable: true,
      cell: (row) => (
        <Tooltip content={formatDate(row.entity?.last_seen_at)}>
          <span className="text-[13px]">{formatRelativeTime(row.entity?.last_seen_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => (
        <Badge tone={row.monitoring_status === 'active' ? 'success' : 'warning'} dot>
          {row.monitoring_status === 'active' ? 'Active' : 'Paused'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      header: '',
      headerClassName: 'w-12',
      cell: (row) => (
        <div onClick={(e) => e.stopPropagation()} role="presentation">
          <Dropdown
            trigger={({ open }) => (
              <button
                aria-label={`Actions for ${row.package_id}`}
                aria-haspopup="menu"
                aria-expanded={open}
                className="rounded-lg px-2.5 py-1.5 text-[13px] font-bold text-muted transition-colors hover:bg-line-soft hover:text-ink focus-ring"
              >
                ⋯
              </button>
            )}
            items={[
              {
                label: row.entity ? 'View entity' : 'View details',
                icon: row.entity ? <ExternalLink className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />,
                onClick: () => (row.entity ? navigate(`/entities/${row.entity.id}`) : openDetails(row)),
              },
              ...(canSync
                ? [
                    {
                      label: 'Sync now',
                      icon: <RefreshCw className="h-3.5 w-3.5" />,
                      onClick: () => void onSync(row),
                      disabled: syncingId === row.id,
                    },
                  ]
                : []),
              ...(canSubmit
                ? [
                    {
                      label: row.monitoring_status === 'active' ? 'Pause monitoring' : 'Resume monitoring',
                      icon: row.monitoring_status === 'active' ? (
                        <Pause className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      ),
                      onClick: () => void onToggleStatus(row),
                    },
                    {
                      label: 'Remove from watch list',
                      icon: <Trash2 className="h-3.5 w-3.5" />,
                      danger: true,
                      separatorBefore: true,
                      onClick: () => setRemoveTarget(row),
                    },
                  ]
                : []),
            ]}
          />
          {syncingId === row.id && (
            <span className="ml-1 inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-500 align-middle" />
          )}
        </div>
      ),
    },
  ];

  /* ---------------- stats ---------------- */
  const summary = summaryQuery.data;
  const bySeverity = summary?.by_severity || {};
  const severityTotal = SEVERITY_DOT_ORDER.reduce((acc, s) => acc + (bySeverity[s] || 0), 0) + (bySeverity.unknown || 0);

  const StatCard: React.FC<{
    label: string;
    value: React.ReactNode;
    sub: string;
    icon: React.ReactNode;
  }> = ({ label, value, sub, icon }) => (
    <Card className="flex items-start gap-3 px-4 py-3.5">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-[11px] font-bold uppercase tracking-wider text-faint">{label}</p>
        <p className="mt-0.5 text-xl font-extrabold tracking-tight text-ink">{value}</p>
        <p className="truncate text-[11px] text-muted">{sub}</p>
      </div>
    </Card>
  );

  const statValue = (v: React.ReactNode) =>
    summaryQuery.isPending ? <span className="skeleton block h-7 w-12 rounded-md" /> : v;

  const detailEntity = detail?.entity;

  /* ---------------- render ---------------- */
  return (
    <div>
      <PageHeader
        title="Mobile App Monitoring"
        description="Track suspicious and unauthorized mobile applications."
        actions={
          canSubmit ? (
            <Button icon={<Plus className="h-4 w-4" />} onClick={openAdd}>
              Add App
            </Button>
          ) : null
        }
      />

      {bannerOpen && (
        <div className="mb-5 flex items-start gap-3 rounded-2xl border border-warning-500/40 bg-warning-100 px-4 py-3.5">
          <span className="mt-0.5 shrink-0 text-warning-600">
            <Info className="h-4 w-4" />
          </span>
          <p className="flex-1 text-[13px] leading-relaxed text-warning-600">
            Monitoring results come from sample connectors unless a real store integration is configured in{' '}
            <Link
              to="/settings?tab=integrations"
              className="font-bold underline underline-offset-2 hover:text-ink"
            >
              Settings → Integrations
            </Link>
            . Publisher identity is never verified.
          </p>
          <button
            onClick={dismissBanner}
            aria-label="Dismiss monitoring notice"
            className="shrink-0 rounded-lg p-1 text-warning-600 transition-colors hover:bg-warning-500/10 focus-ring"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Stat strip */}
      <div className="mb-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total monitored"
          value={statValue(appsQuery.data?.total ?? '—')}
          sub="packages on the watch list"
          icon={<Smartphone className="h-4 w-4" />}
        />
        <StatCard
          label="High-risk apps"
          value={statValue(summary?.high_risk_apps ?? '—')}
          sub="high or critical severity"
          icon={<ShieldAlert className="h-4 w-4" />}
        />
        <StatCard
          label="Apps with cases"
          value={statValue(summary?.apps_with_cases ?? '—')}
          sub="linked to at least one case"
          icon={<Briefcase className="h-4 w-4" />}
        />
        <Card className="px-4 py-3.5">
          <p className="text-[11px] font-bold uppercase tracking-wider text-faint">Severity distribution</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
            {SEVERITY_DOT_ORDER.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink-700">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: severityColor(s) }} />
                <span className="capitalize">{s}</span>
                <span className="tabular-nums text-muted">
                  {summaryQuery.isPending ? '—' : (summary?.by_severity?.[s] ?? 0)}
                </span>
              </span>
            ))}
          </div>
        </Card>
      </div>
      {summary?.note && (
        <p className="mb-5 flex items-center gap-1.5 text-[12px] text-muted">
          <Info className="h-3.5 w-3.5 shrink-0 text-faint" />
          {summary.note}
        </p>
      )}

      {/* Toolbar */}
      <Card className="mb-4">
        <div className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-2">
            <SearchInput
              value={q}
              onChange={(v) => setParams({ q: v })}
              placeholder="Search app name or package id…"
              className="w-full sm:w-72"
              debounceMs={350}
            />
            <FilterSelect
              label="Risk severity"
              value={severity}
              onChange={(v) => setParams({ severity: v })}
              options={SEVERITY_OPTIONS}
              allLabel="All severities"
            />
            <FilterSelect
              label="Monitoring status"
              value={status}
              onChange={(v) => setParams({ status: v })}
              options={STATUS_OPTIONS}
              allLabel="All statuses"
            />
            <FilterSelect
              label="Store"
              value={store}
              onChange={(v) => setParams({ store: v })}
              options={STORE_OPTIONS}
              allLabel="All stores"
            />
            <FilterSelect
              label="Sort"
              value={sort}
              onChange={(v) => setParams({ sort: v })}
              options={SORT_OPTIONS}
              allLabel="Default sort"
            />
            {hasFilters && (
              <button
                onClick={clearFilters}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl px-2.5 text-[13px] font-semibold text-muted transition-colors hover:text-ink focus-ring"
              >
                <X className="h-3.5 w-3.5" /> Clear
              </button>
            )}
          </div>
        </div>
      </Card>

      {/* Table */}
      <Card>
        {appsQuery.isError ? (
          <div className="px-5 py-10">
            <ErrorState title="Could not load monitored apps" message={errMessage(appsQuery.error)} onRetry={() => void appsQuery.refetch()} />
          </div>
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.id}
              sort={sort || null}
              order={order}
              onSortChange={onSortChange}
              onRowClick={openDetails}
              loading={loading}
              emptyState={
                hasFilters ? (
                  <EmptyState
                    icon={<Search className="h-6 w-6" />}
                    title="No apps match"
                    description="No monitored app matches the current search and filters."
                    action={
                      <Button variant="outline" size="sm" onClick={clearFilters}>
                        Clear filters
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    icon={<Smartphone className="h-6 w-6" />}
                    title="No apps are monitored yet"
                    description="Add a store package to start watching a suspicious or unauthorized mobile app."
                    action={
                      canSubmit ? (
                        <Button icon={<Plus className="h-4 w-4" />} onClick={openAdd}>
                          Add App
                        </Button>
                      ) : undefined
                    }
                  />
                )
              }
            />
            <Pagination
              page={page}
              pages={appsQuery.data?.pages ?? 1}
              total={appsQuery.data?.total ?? 0}
              onPageChange={(p) => setParams({ page: String(p) })}
              pageSize={pageSize}
              onPageSizeChange={(s) => setParams({ page_size: String(s) })}
            />
          </>
        )}
      </Card>

      {/* ---------------- Add app modal ---------------- */}
      <Modal
        open={addOpen}
        onClose={() => !submitting && setAddOpen(false)}
        title="Add app to monitoring"
        description="The package is validated against the selected store format before it is added."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={() => void submitAdd()} loading={submitting}>
              Start monitoring
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {formError && (
            <div className="rounded-xl border border-danger-100 bg-danger-100 px-3.5 py-2.5 text-[13px] font-medium text-danger-600">
              {formError}
            </div>
          )}

          <Field
            label="Brand"
            required
            htmlFor="add-brand"
            error={fieldErrors.brand_id}
            hint={
              brands.length === 0
                ? 'No brands are available in your workspace yet.'
                : 'Monitoring targets and linked entities belong to this brand.'
            }
          >
            <Select
              id="add-brand"
              value={form.brand_id}
              invalid={!!fieldErrors.brand_id}
              onChange={(e) => patchForm({ brand_id: e.target.value })}
            >
              <option value="">Select a brand…</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Store" required htmlFor="add-store">
              <Select id="add-store" value={form.store} onChange={(e) => patchForm({ store: e.target.value })}>
                {STORE_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field
              label="Package ID"
              required
              htmlFor="add-package"
              error={packageError}
              hint={!packageError ? <span>{packageHint(form.store)}</span> : undefined}
            >
              <div className="relative">
                <Input
                  id="add-package"
                  value={form.package_id}
                  onChange={(e) => patchForm({ package_id: e.target.value })}
                  placeholder={form.store === 'app_store' ? '1234567890' : 'com.example.app'}
                  className={cn('pr-9 font-mono', packageError && 'border-danger')}
                  aria-describedby="add-package-hint"
                />
                {!packageError && form.package_id && (
                  <Check className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-success" />
                )}
              </div>
            </Field>
          </div>

          <Field
            label="Store URL"
            htmlFor="add-url"
            error={urlError}
            hint={!urlError ? storeUrlHint(form.store, form.package_id) : undefined}
          >
            <Input
              id="add-url"
              value={form.store_url}
              onChange={(e) => patchForm({ store_url: e.target.value })}
              placeholder={storeUrlHint(form.store, form.package_id).replace('Expected: ', '')}
              className={cn('font-mono text-[13px]', urlError && 'border-danger')}
            />
          </Field>

          <div className="rounded-xl bg-bg px-3.5 py-3 text-[12px] leading-relaxed text-muted">
            <span className="font-semibold text-ink-700">What happens next:</span> the package is stored on the watch
            list and linked to a <code className="font-mono">mobile_app</code> entity with synthetic sample provenance.
            No live app-store data is fetched until a store integration is configured.
          </div>
        </div>
      </Modal>

      {/* ---------------- Details modal ---------------- */}
      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        size="lg"
        title={detail?.app_name || detail?.package_id || 'App details'}
        description={detail ? `${detail.package_id} · ${STORE_LABELS[detail.store] || detail.store}` : undefined}
        footer={
          detail ? (
            <>
              <Button
                variant="outline"
                onClick={() => setDetail(null)}
              >
                Close
              </Button>
              {detail.entity && (
                <Button
                  variant="outline"
                  icon={<ExternalLink className="h-4 w-4" />}
                  onClick={() => navigate(`/evidence?entity_id=${detail.entity!.id}`)}
                >
                  Open in Evidence
                </Button>
              )}
              {canSync && (
                <Button
                  icon={<RefreshCw className="h-4 w-4" />}
                  loading={syncingId === detail.id}
                  onClick={() => void onSync(detail)}
                >
                  Sync now
                </Button>
              )}
            </>
          ) : null
        }
      >
        {detail && (
          <div className="space-y-5">
            <dl className="grid gap-x-6 sm:grid-cols-2">
              <KeyValue
                label="Brand"
                value={
                  <Link to="/settings?tab=brands" className="text-brand-600 hover:underline">
                    {detail.brand.name}
                  </Link>
                }
              />
              <KeyValue
                label="Package ID"
                value={
                  <span className="inline-flex items-center gap-1">
                    <code className="font-mono text-[13px]">{detail.package_id}</code>
                    <CopyButton text={detail.package_id} label="Copy package id" />
                  </span>
                }
              />
              <KeyValue
                label="Store"
                value={
                  detail.store_url ? (
                    <a
                      href={detail.store_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 text-brand-600 hover:underline"
                    >
                      {STORE_LABELS[detail.store] || detail.store}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    STORE_LABELS[detail.store] || detail.store
                  )
                }
              />
              <KeyValue
                label="Monitoring status"
                value={
                  <Badge tone={detail.monitoring_status === 'active' ? 'success' : 'warning'} dot>
                    {detail.monitoring_status === 'active' ? 'Active' : 'Paused'}
                  </Badge>
                }
              />
              <KeyValue label="Last sync" value={
                detail.last_sync_at ? (
                  <span title={formatDate(detail.last_sync_at)}>{formatRelativeTime(detail.last_sync_at)}</span>
                ) : (
                  'Never synced'
                )
              } />
              <KeyValue label="Added to watch list" value={formatDate(detail.created_at)} />
            </dl>

            <div className="rounded-2xl border border-line-soft bg-bg p-4">
              <p className="mb-3 text-[11px] font-bold uppercase tracking-wider text-faint">Linked entity</p>
              {detailEntity ? (
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  <ScoreRing
                    value={detailEntity.risk_score}
                    severity={detailEntity.severity}
                    size={84}
                    label="Risk"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[15px] font-bold text-ink">{detailEntity.display_name}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={detailEntity.severity} />
                      <span className="text-[12px] font-semibold text-muted">
                        confidence {detailEntity.confidence === null || detailEntity.confidence === undefined ? '—' : detailEntity.confidence.toFixed(2)}
                      </span>
                    </div>
                    <dl className="mt-3 space-y-1.5 text-[12px] text-muted">
                      <div className="flex items-center gap-2">
                        <dt className="font-semibold text-ink-700">Provenance:</dt>
                        <dd>
                          <Badge tone={detailEntity.provenance === 'synthetic' ? 'warning' : detailEntity.provenance === 'collected' ? 'success' : 'primary'}>
                            {detailEntity.provenance === 'synthetic' ? 'Sample data' : detailEntity.provenance}
                          </Badge>
                        </dd>
                      </div>
                      <div className="flex items-center gap-2">
                        <dt className="font-semibold text-ink-700">Last seen:</dt>
                        <dd title={formatDate(detailEntity.last_seen_at)}>
                          {formatRelativeTime(detailEntity.last_seen_at)}
                        </dd>
                      </div>
                      {detailEntity.source_url && (
                        <div className="flex items-center gap-2">
                          <dt className="font-semibold text-ink-700">Source URL:</dt>
                          <dd className="min-w-0">
                            <a
                              href={detailEntity.source_url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="inline-flex max-w-full items-center gap-1 truncate text-brand-600 hover:underline"
                            >
                              <span className="truncate">{detailEntity.source_url}</span>
                              <ExternalLink className="h-3 w-3 shrink-0" />
                            </a>
                          </dd>
                        </div>
                      )}
                    </dl>
                    <div className="mt-3">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => navigate(`/entities/${detailEntity.id}`)}
                        icon={<Eye className="h-3.5 w-3.5" />}
                      >
                        Open entity
                      </Button>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-[13px] text-muted">
                  No linked entity yet. Run a sync to create or refresh the linked{' '}
                  <code className="font-mono text-[12px]">mobile_app</code> entity.
                </p>
              )}
            </div>

            <div className="rounded-2xl border border-line-soft p-4">
              <p className="mb-2 text-[11px] font-bold uppercase tracking-wider text-faint">Sync history</p>
              <p className="text-[13px] text-muted">
                {detail.last_sync_at ? (
                  <>
                    Last connector run{' '}
                    <span className="font-semibold text-ink-700" title={formatDate(detail.last_sync_at)}>
                      {formatRelativeTime(detail.last_sync_at)}
                    </span>
                    . The sample connector updates attributes from SAMPLE data — it is not a live app-store fetch.
                  </>
                ) : (
                  <>This target has never been synced. Syncs run the SYNTHETIC sample connector, not a live store API.</>
                )}
              </p>
            </div>
          </div>
        )}
      </Modal>

      {/* ---------------- Remove confirmation ---------------- */}
      <ConfirmDialog
        open={!!removeTarget}
        onClose={() => setRemoveTarget(null)}
        onConfirm={onRemove}
        loading={removing}
        destructive
        confirmLabel="Stop monitoring"
        title="Stop monitoring this app?"
        message={
          removeTarget ? (
            <>
              <span className="font-semibold text-ink">
                {removeTarget.app_name || removeTarget.package_id}
              </span>{' '}
              (<code className="font-mono text-[12px]">{removeTarget.package_id}</code>) will be removed from the watch
              list. The linked digital entity and its evidence are kept — only the monitoring target is deleted.
            </>
          ) : (
            ''
          )
        }
      />
    </div>
  );
};

export default MobileAppsPage;
