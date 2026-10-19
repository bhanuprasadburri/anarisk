import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  AtSign,
  Briefcase,
  ChevronRight,
  Globe,
  Image as ImageIcon,
  Layers,
  Link2,
  PieChart as PieChartIcon,
  RefreshCw,
  ShieldAlert,
  Smartphone,
  Siren,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { dashboardService } from '../services/dashboardService';
import { reportService } from '../services/reportService';
import { DashboardStats, ReportsOverview } from '../types';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { SeverityBadge } from '../components/ui/badge';
import {
  CardSkeleton,
  DateRangeSelect,
  DateRangeValue,
  FilterSelect,
  RANGE_LABELS,
  Skeleton,
  rangeToDates,
} from '../components/ui/misc';
import { EmptyState, ErrorState } from '../components/ui/table';
import { severityColor } from '../components/ui/score';
import { useToast } from '../components/ui/toast';
import { ENTITY_TYPE_COLORS, ENTITY_TYPE_LABELS, PROVENANCE_LABELS, SEVERITY_LABELS } from '../lib/constants';
import { formatNumber, formatRelativeTime } from '../lib/formatters';
import { cn, scoreTextClass } from '../lib/utils';

/* ------------------------------------------------------------------ */
/* Local types (backend contract for /dashboard/stats)                */
/* ------------------------------------------------------------------ */

interface RecentDetection {
  id: string;
  entity_type: string;
  display_name: string;
  severity?: string | null;
  risk_score?: number | null;
  last_assessed_at?: string | null;
}

interface DashboardData {
  stats: DashboardStats;
  overview: ReportsOverview;
  /** Overview for the previous period of equal length (used for an honest detections delta). */
  prev: ReportsOverview | null;
}

type LoadMode = 'initial' | 'refresh' | 'auto';

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'unknown'] as const;

const ENTITY_TYPE_ICONS: Record<string, React.ReactNode> = {
  social_profile: <AtSign className="h-4 w-4" />,
  website: <Globe className="h-4 w-4" />,
  domain: <Link2 className="h-4 w-4" />,
  image: <ImageIcon className="h-4 w-4" />,
  mobile_app: <Smartphone className="h-4 w-4" />,
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const isoDate = (d: Date) => d.toISOString().slice(0, 10);

/** The period immediately before [from, to] with the same number of days. */
function previousPeriod(from: string, to: string): { from: string; to: string } | null {
  const f = Date.parse(`${from}T00:00:00Z`);
  const t = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(f) || Number.isNaN(t) || t < f) return null;
  const days = Math.round((t - f) / 86400000) + 1;
  return { from: isoDate(new Date(f - days * 86400000)), to: isoDate(new Date(f - 86400000)) };
}

const eventLabel = (eventType: string) =>
  (eventType || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const safeDateLabel = (value: unknown): string => {
  try {
    return format(parseISO(String(value)), 'MMM d, yyyy');
  } catch {
    return String(value ?? '');
  }
};

const axisDate = (value: unknown): string => {
  try {
    return format(parseISO(String(value)), 'MMM d');
  } catch {
    return String(value ?? '');
  }
};

/* ------------------------------------------------------------------ */
/* Sub-components                                                      */
/* ------------------------------------------------------------------ */

const ContextChip: React.FC<{ title?: string; children: React.ReactNode }> = ({ title, children }) => (
  <span
    title={title}
    className="whitespace-nowrap rounded-full bg-line-soft px-2 py-1 text-[11px] font-semibold text-muted"
  >
    {children}
  </span>
);

const MetricCard: React.FC<{
  label: string;
  value: number;
  icon: React.ReactNode;
  iconClassName: string;
  chip: string;
  chipTitle?: string;
}> = ({ label, value, icon, iconClassName, chip, chipTitle }) => (
  <Card className="p-5 transition-shadow hover:shadow-card-hover">
    <div className="flex items-start justify-between gap-3">
      <span className={cn('flex h-10 w-10 items-center justify-center rounded-xl', iconClassName)} aria-hidden="true">
        {icon}
      </span>
      <ContextChip title={chipTitle}>{chip}</ContextChip>
    </div>
    <p className="mt-4 text-[13px] font-semibold text-muted">{label}</p>
    <p className="mt-1 text-3xl font-extrabold tracking-tight text-ink tabular-nums">{formatNumber(value)}</p>
  </Card>
);

const DonutTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ name?: string; value?: number | string }>;
}> = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0];
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 shadow-popover">
      <p className="text-[12px] font-bold text-ink">{p.name}</p>
      <p className="mt-0.5 text-[11px] tabular-nums text-muted">{formatNumber(Number(p.value ?? 0))} entities</p>
    </div>
  );
};

const TrendTooltip: React.FC<any> = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0];
  const avg = p.value as number | null | undefined;
  const detections = (p.payload?.detections ?? 0) as number;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 shadow-popover">
      <p className="text-[12px] font-bold text-ink">{safeDateLabel(label)}</p>
      <p className="mt-1 text-[11px] text-muted">
        Avg risk{' '}
        <span className="font-bold tabular-nums text-ink">
          {avg === null || avg === undefined ? '—' : Number(avg).toFixed(2)}
        </span>
      </p>
      <p className="text-[11px] text-muted">
        Detections <span className="font-bold tabular-nums text-ink">{detections}</span>
      </p>
    </div>
  );
};

const DashboardSkeletons: React.FC = () => (
  <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <CardSkeleton key={i} className="p-5" />
      ))}
    </div>
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="min-w-0 space-y-6 lg:col-span-2">
        <Card className="p-5">
          <Skeleton className="h-4 w-44" />
          <Skeleton className="mt-4 h-[260px] w-full" />
        </Card>
        <Card className="p-5">
          <Skeleton className="h-4 w-44" />
          <Skeleton className="mt-4 h-[260px] w-full" />
        </Card>
      </div>
      <Card className="min-w-0 p-5">
        <Skeleton className="h-4 w-40" />
        <div className="mt-4 space-y-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </Card>
    </div>
  </div>
);

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export const DashboardPage: React.FC = () => {
  const { user, brands } = useAuth();
  const { toast } = useToast();

  // Keep the latest toast fns in a ref so `load` identity only depends on query params.
  const toastRef = useRef(toast);
  toastRef.current = toast;

  const [range, setRange] = useState<DateRangeValue>({ key: '30d' });
  const [brandId, setBrandId] = useState('');
  const [purpose, setPurpose] = useState('');
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const reqIdRef = useRef(0);

  const load = useCallback(
    async (mode: LoadMode) => {
      const id = ++reqIdRef.current;
      const { from, to } = rangeToDates(range);
      const prev = from && to ? previousPeriod(from, to) : null;
      if (mode === 'initial') setLoading(true);
      if (mode === 'refresh') setRefreshing(true);
      try {
        const scoped = {
          ...(brandId ? { brand_id: brandId } : {}),
          ...(purpose ? { provenance: purpose } : {}),
        };
        const [stats, overview, prevOverview] = await Promise.all([
          dashboardService.getStats(scoped),
          reportService.getOverview({ ...scoped, from, to }),
          prev ? reportService.getOverview({ ...scoped, from: prev.from, to: prev.to }) : Promise.resolve(null),
        ]);
        if (id !== reqIdRef.current) return; // a newer request superseded this one
        setData({ stats, overview, prev: prevOverview });
        setError(null);
        setLastUpdated(new Date());
      } catch (err) {
        if (id !== reqIdRef.current) return;
        const message = err instanceof Error ? err.message : 'We could not load your dashboard data.';
        if (mode === 'auto') {
          // background refresh: keep showing the last good data, the next cycle retries
        } else if (mode === 'refresh') {
          toastRef.current.error('Refresh failed', message);
        } else {
          setError(message);
        }
      } finally {
        if (id === reqIdRef.current) {
          setLoading(false);
          setRefreshing(false);
        } else if (mode === 'refresh') {
          // a range/brand change superseded this refresh — never leave the button spinning
          setRefreshing(false);
        }
      }
    },
    [range, brandId, purpose]
  );

  // Initial load + refetch whenever the date range or brand scope changes.
  useEffect(() => {
    load('initial');
  }, [load]);

  // Auto-refetch every 60 seconds.
  useEffect(() => {
    const timer = setInterval(() => load('auto'), 60000);
    return () => clearInterval(timer);
  }, [load]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : 'Good afternoon';
  const firstName = (user?.full_name?.trim() || user?.email?.split('@')[0] || 'there').split(/\s+/)[0] || 'there';
  const brandName = brands.find((b) => b.id === brandId)?.name;
  const rangeLabel = range.key === 'custom' ? `${range.from || '…'} → ${range.to || '…'}` : RANGE_LABELS[range.key];

  const brandOptions = brands.map((b) => ({ value: b.id, label: b.name }));

  const scopeLabel = brandName || 'All brands';

  const onRetry = () => {
    setError(null);
    load('initial');
  };

  let content: React.ReactNode;
  if (loading) {
    content = <DashboardSkeletons />;
  } else if (error) {
    content = (
      <ErrorState
        title="Couldn't load the dashboard"
        message={error}
        onRetry={onRetry}
      />
    );
  } else if (data) {
    const totals = data.stats.totals;
    const totalCases = Object.values(data.stats.case_status_distribution || {}).reduce((a, b) => a + b, 0);
    const detections = (data.stats.recent_detections || []) as unknown as RecentDetection[];
    const trend = data.overview.risk_trend || [];
    const distData = SEVERITIES.map((s) => ({
      key: s,
      label: SEVERITY_LABELS[s] || s,
      value: Number(data.stats.risk_distribution?.[s] ?? 0),
      color: severityColor(s),
    }));
    const distTotal = distData.reduce((a, d) => a + d.value, 0);
    const hasTrendData = trend.some((d) => (d.avg_risk !== null && d.avg_risk !== undefined) || d.detections > 0);

    const currentDetections = data.overview.totals.detections;
    const prevDetections = data.prev ? data.prev.totals.detections : null;
    const detDelta = prevDetections !== null ? currentDetections - prevDetections : null;

    const metrics: Array<{
      label: string;
      value: number;
      icon: React.ReactNode;
      iconClassName: string;
      chip: string;
      chipTitle?: string;
    }> = [
      {
        label: 'Monitored Entities',
        value: totals.monitored_entities,
        icon: <Globe className="h-5 w-5" />,
        iconClassName: 'bg-brand-50 text-brand-500',
        chip: `${formatNumber(totals.unassessed_entities)} unassessed`,
        chipTitle: 'Entities that do not have a risk assessment yet',
      },
      {
        label: 'High-Risk Entities',
        value: totals.high_risk_entities,
        icon: <ShieldAlert className="h-5 w-5" />,
        iconClassName: 'bg-danger-100 text-danger-500',
        chip: `of ${formatNumber(totals.monitored_entities)} total`,
        chipTitle: 'Critical + high severity entities, out of all monitored entities',
      },
      {
        label: 'Open Cases',
        value: totals.open_cases,
        icon: <Briefcase className="h-5 w-5" />,
        iconClassName: 'bg-cyanx-100 text-cyanx-600',
        chip: `of ${formatNumber(totalCases)} total`,
        chipTitle: 'Cases not yet resolved, out of all cases',
      },
      {
        label: 'Escalated Cases',
        value: totals.escalated_cases,
        icon: <Siren className="h-5 w-5" />,
        iconClassName: 'bg-warning-100 text-warning-600',
        chip: `of ${formatNumber(totals.open_cases)} open`,
        chipTitle: 'Open cases escalated to a partner',
      },
    ];

    content = (
      <div className="space-y-6">
        {/* ---- Metric cards ---- */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((m) => (
            <MetricCard key={m.label} {...m} />
          ))}
        </div>

        {/* ---- Charts + recent detections ---- */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="min-w-0 space-y-6 lg:col-span-2">
            {/* Threat distribution */}
            <Card>
              <CardHeader>
                <CardTitle>Threat Distribution</CardTitle>
                <CardDescription>
                  Entities by current severity · {scopeLabel}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {distTotal === 0 ? (
                  <div className="flex min-h-[260px] items-center justify-center">
                    <EmptyState
                      icon={<PieChartIcon className="h-6 w-6" />}
                      title="No entities yet"
                      description="Once entities are monitored and assessed, their severity breakdown shows up here."
                    />
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-6 sm:flex-row">
                    <div className="relative h-[260px] w-full min-w-0 sm:w-1/2">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                          <Pie
                            data={distData}
                            dataKey="value"
                            nameKey="label"
                            cx="50%"
                            cy="50%"
                            innerRadius={58}
                            outerRadius={88}
                            paddingAngle={2}
                            stroke="#FFFFFF"
                            strokeWidth={2}
                          >
                            {distData.map((d) => (
                              <Cell key={d.key} fill={d.color} />
                            ))}
                          </Pie>
                          <ChartTooltip content={<DonutTooltip />} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                        <span className="text-2xl font-extrabold tracking-tight text-ink tabular-nums">
                          {formatNumber(distTotal)}
                        </span>
                        <span className="mt-0.5 text-[11px] font-bold uppercase tracking-wider text-faint">Total</span>
                      </div>
                    </div>
                    <ul className="w-full min-w-0 space-y-2.5 sm:w-1/2">
                      {distData.map((d) => {
                        const pct = distTotal > 0 ? Math.round((d.value / distTotal) * 100) : 0;
                        return (
                          <li key={d.key} className="flex items-center gap-2.5">
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full"
                              style={{ backgroundColor: d.color }}
                              aria-hidden="true"
                            />
                            <span className="text-[13px] font-semibold text-ink-700">{d.label}</span>
                            <span className="ml-auto flex items-baseline gap-2 tabular-nums">
                              <span className="text-[13px] font-bold text-ink">{formatNumber(d.value)}</span>
                              <span className="w-9 text-right text-[12px] text-faint">{pct}%</span>
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Risk trend */}
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle>Risk Trend</CardTitle>
                  <CardDescription>
                    Daily average risk score · {rangeLabel} · {scopeLabel}
                  </CardDescription>
                </div>
                <span
                  className="shrink-0 whitespace-nowrap rounded-full bg-line-soft px-2 py-1 text-[11px] font-semibold text-muted"
                  title={
                    data.prev
                      ? `Detections in this range vs the previous period of equal length (${data.prev.date_range.from} → ${data.prev.date_range.to})`
                      : 'Detections in the selected range'
                  }
                >
                  {formatNumber(currentDetections)} detections
                  {detDelta !== null && ` · ${detDelta >= 0 ? '+' : ''}${detDelta} vs prev`}
                </span>
              </CardHeader>
              <CardContent>
                {!hasTrendData ? (
                  <div className="flex min-h-[260px] items-center justify-center">
                    <EmptyState
                      icon={<Activity className="h-6 w-6" />}
                      title="No assessments in this range"
                      description="No risk assessments were recorded in the selected date range. Try a wider range."
                    />
                  </div>
                ) : (
                  <div className="h-[260px] w-full min-w-0">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={trend} margin={{ top: 10, right: 12, bottom: 0, left: -14 }}>
                        <defs>
                          <linearGradient id="riskAreaFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#4778F5" stopOpacity={0.32} />
                            <stop offset="100%" stopColor="#4778F5" stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" vertical={false} />
                        <XAxis
                          dataKey="date"
                          tickFormatter={axisDate}
                          tick={{ fontSize: 11, fill: '#94A3B8' }}
                          tickLine={false}
                          axisLine={{ stroke: '#EDF2FC' }}
                          minTickGap={28}
                        />
                        <YAxis
                          domain={[0, 1]}
                          tickFormatter={(v: number) => Number(v).toFixed(1)}
                          tick={{ fontSize: 11, fill: '#94A3B8' }}
                          tickLine={false}
                          axisLine={false}
                          width={44}
                        />
                        <ChartTooltip content={<TrendTooltip />} />
                        <Area
                          type="monotone"
                          dataKey="avg_risk"
                          name="Avg risk"
                          stroke="#4778F5"
                          strokeWidth={2.5}
                          fill="url(#riskAreaFill)"
                          dot={false}
                          activeDot={{ r: 4, fill: '#4778F5', strokeWidth: 0 }}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Recent detections */}
          <Card className="flex min-w-0 flex-col">
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <div>
                <CardTitle>Recent Detections</CardTitle>
                <CardDescription>Latest assessed entities</CardDescription>
              </div>
              <Activity className="h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
            </CardHeader>
            <div className="min-w-0 flex-1">
              {detections.length === 0 ? (
                <div className="px-5 pb-5">
                  <EmptyState
                    icon={<Activity className="h-6 w-6" />}
                    title="No detections yet"
                    description="Entities appear here once they have been assessed."
                  />
                </div>
              ) : (
                <ul className="divide-y divide-line-soft border-t border-line-soft">
                  {detections.map((d) => {
                    const icon = ENTITY_TYPE_ICONS[d.entity_type] || <Layers className="h-4 w-4" />;
                    const color = ENTITY_TYPE_COLORS[d.entity_type] || '#94A3B8';
                    return (
                      <li
                        key={d.id}
                        className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-bg/70"
                      >
                        <span
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                          style={{ backgroundColor: `${color}1F`, color }}
                          aria-hidden="true"
                        >
                          {icon}
                        </span>
                        <div className="min-w-0 flex-1">
                          <Link
                            to={`/entities/${d.id}`}
                            className="block truncate text-[13px] font-semibold text-ink transition-colors hover:text-brand-600"
                          >
                            {d.display_name}
                          </Link>
                          <p className="mt-0.5 truncate text-[11px] text-muted">
                            {ENTITY_TYPE_LABELS[d.entity_type] || d.entity_type} ·{' '}
                            {formatRelativeTime(d.last_assessed_at)}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <SeverityBadge severity={d.severity} className="!px-2 !py-0 !text-[11px]" />
                          <span
                            className={cn('text-[12px] font-bold tabular-nums', scoreTextClass(d.risk_score))}
                            title="Risk score (heuristic, 0–1)"
                          >
                            {d.risk_score === null || d.risk_score === undefined
                              ? '—'
                              : d.risk_score.toFixed(2)}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <CardFooter className="mt-auto justify-center">
              <Link
                to="/threat-intelligence"
                className="inline-flex items-center gap-1 text-[13px] font-semibold text-brand-600 transition-colors hover:text-brand-700"
              >
                View all <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </CardFooter>
          </Card>
        </div>

        {/* ---- Case activity strip ---- */}
        <Card>
          <CardContent className="py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="mr-1 text-[11px] font-bold uppercase tracking-wider text-faint">Case activity</span>
              {(data.stats.latest_activity || []).slice(0, 6).map((a) => (
                <Link
                  key={`${a.case_id}-${a.created_at}`}
                  to={`/cases/${a.case_id}`}
                  title={a.case_title}
                  className="inline-flex max-w-full items-center gap-2 truncate rounded-full border border-line bg-white px-3 py-1.5 shadow-sm transition-colors hover:border-brand-200 hover:bg-brand-50 focus-ring"
                >
                  <span className="shrink-0 text-[12px] font-bold text-brand-600">{a.case_number}</span>
                  <span className="truncate text-[11px] font-medium text-ink-700">{eventLabel(a.event_type)}</span>
                  <span className="shrink-0 text-[11px] text-faint">{formatRelativeTime(a.created_at)}</span>
                </Link>
              ))}
              {(data.stats.latest_activity || []).length === 0 && (
                <span className="text-[13px] text-muted">No recent case activity.</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ---- Content header ---- */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-extrabold tracking-tight text-ink sm:text-2xl">
            {greeting}, {firstName} 👋
          </h1>
          <p className="mt-1 text-[13px] text-muted sm:text-sm">
            Here's what's happening with your digital risk landscape.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <span
            role="status"
            className="inline-flex items-center gap-1.5 rounded-full border border-success-100 bg-success-100 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-success-600"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-success" aria-hidden="true" />
            Live
          </span>
          <span className="text-[12px] font-medium tabular-nums text-faint" aria-live="polite">
            Last updated{' '}
            {lastUpdated
              ? lastUpdated.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
              : '—'}
          </span>
          <DateRangeSelect value={range} onChange={setRange} />
          <Button
            variant="outline"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            loading={refreshing}
            onClick={() => load('refresh')}
            aria-label="Refresh dashboard data"
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* ---- Brand scope and data purpose ---- */}
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-faint">Scope</span>
        <FilterSelect
          value={brandId}
          onChange={setBrandId}
          options={brandOptions}
          label="Brand scope"
          allLabel="All brands"
        />
        <span className="ml-2 text-[11px] font-bold uppercase tracking-wider text-faint">Purpose</span>
        <FilterSelect
          value={purpose}
          onChange={setPurpose}
          options={Object.entries(PROVENANCE_LABELS).map(([value, label]) => ({ value, label }))}
          label="Purpose"
          allLabel="All purposes"
        />
      </div>

      {content}
    </div>
  );
};

export default DashboardPage;
