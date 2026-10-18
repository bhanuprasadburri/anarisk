import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  ArrowRight,
  BarChart3,
  Briefcase,
  Download,
  FileDown,
  Info,
  Link2,
  Network,
  RefreshCw,
  Smartphone,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, Dropdown } from '../components/ui/tabs';
import { DataTable, EmptyState, ErrorState } from '../components/ui/table';
import { severityColor, ScoreBar } from '../components/ui/score';
import {
  DateRangeSelect,
  DateRangeValue,
  FilterSelect,
  rangeToDates,
  Skeleton,
} from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { reportService, ReportKind } from '../services/reportService';
import { ReportsOverview } from '../types';
import {
  CASE_STATUS_LABELS,
  ENTITY_TYPE_COLORS,
  ENTITY_TYPE_LABELS,
  SEVERITY_LABELS,
  STORE_LABELS,
} from '../lib/constants';
import { formatNumber, formatRelativeTime } from '../lib/formatters';

/* ------------------------------------------------------------------ */
/*  Chart primitives                                                   */
/* ------------------------------------------------------------------ */

interface TipEntry {
  name?: string | number;
  value?: number | string | Array<number | string>;
  color?: string;
}

interface TipProps {
  active?: boolean;
  payload?: TipEntry[];
  label?: string | number;
}

const fmtVal = (v: TipEntry['value']): string => {
  if (Array.isArray(v)) return v.map((x) => String(x)).join(', ');
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
  return String(v ?? '—');
};

/** White card, border, shadow — shared tooltip for every chart. */
const ChartTip: React.FC<TipProps> = ({ active, payload, label }) => {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-xl border border-line bg-white px-3 py-2 shadow-popover">
      {label !== undefined && label !== '' && (
        <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-faint">{label}</p>
      )}
      <div className="space-y-1">
        {payload.map((p, i) => (
          <p key={i} className="flex items-center gap-2 text-[12px] font-semibold">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: p.color || '#4778F5' }} />
            <span className="text-muted">{p.name}</span>
            <span className="ml-auto pl-4 tabular-nums text-ink">{fmtVal(p.value)}</span>
          </p>
        ))}
      </div>
    </div>
  );
};

const legendFormatter = (value: string | number): React.ReactNode => (
  <span className="text-[11px] font-semibold text-muted">{String(value)}</span>
);

const axisTick = { fontSize: 11, fill: '#94A3B8' };

/* ------------------------------------------------------------------ */
/*  Layout helpers                                                     */
/* ------------------------------------------------------------------ */

const ChartCard: React.FC<{
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  loading?: boolean;
  empty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  children: React.ReactNode;
}> = ({ title, description, action, className, loading, empty, emptyTitle, emptyDescription, children }) => (
  <Card className={className}>
    <CardHeader className="flex flex-row items-start justify-between gap-3 pb-2">
      <div className="min-w-0">
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </div>
      {action}
    </CardHeader>
    <CardContent>
      {loading ? (
        <Skeleton className="h-[240px] w-full rounded-xl" />
      ) : empty ? (
        <div className="flex min-h-[220px] items-center justify-center">
          <EmptyState
            icon={<BarChart3 className="h-6 w-6" />}
            title={emptyTitle || 'No data in range'}
            description={emptyDescription || 'Nothing matched the selected date range and brand filter.'}
          />
        </div>
      ) : (
        children
      )}
    </CardContent>
  </Card>
);

const StatCard: React.FC<{
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: string;
}> = ({ label, value, sub, icon, tone = '#4778F5' }) => (
  <Card className="p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-[11px] font-bold uppercase tracking-wider text-faint">{label}</p>
        <p className="mt-1 text-2xl font-extrabold tracking-tight text-ink">{value}</p>
        {sub && <p className="mt-0.5 text-[11px] leading-snug text-muted">{sub}</p>}
      </div>
      {icon && (
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
          style={{ backgroundColor: `${tone}1A`, color: tone }}
        >
          {icon}
        </span>
      )}
    </div>
  </Card>
);

const SectionGrid: React.FC<{ children: React.ReactNode; cols?: 2 | 3 }> = ({ children, cols = 2 }) => (
  <div className={cols === 2 ? 'grid gap-4 lg:grid-cols-2' : 'grid gap-4 sm:grid-cols-2 xl:grid-cols-3'}>{children}</div>
);

/* ------------------------------------------------------------------ */
/*  Data helpers                                                       */
/* ------------------------------------------------------------------ */

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'unknown'] as const;

const CASE_STATUS_ORDER = ['detected', 'triaged', 'under_review', 'assigned', 'escalated', 'resolved'];
const CASE_STATUS_COLORS: Record<string, string> = {
  detected: '#6391F7',
  triaged: '#4778F5',
  under_review: '#8B5CF6',
  assigned: '#20C5D7',
  escalated: '#F04464',
  resolved: '#10B981',
};

const CHANNEL_COLORS = ['#4778F5', '#7C5CF6', '#8B5CF6', '#20C5D7', '#94A3B8'];

const errText = (e: unknown): string => (e instanceof Error ? e.message : 'Unexpected error');

const hasValues = (rec: Record<string, number>): boolean => Object.values(rec).some((v) => Number(v) > 0);

const prettyKey = (k: string): string => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

type PieDatum = { name: string; value: number; color: string };

const toPie = (rec: Record<string, number>, colorOf: (k: string) => string, labelOf?: (k: string) => string): PieDatum[] =>
  Object.entries(rec)
    .filter(([, v]) => Number(v) > 0)
    .map(([k, v]) => ({ name: labelOf ? labelOf(k) : prettyKey(k), value: Number(v), color: colorOf(k) }));

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */

type ReportTab = 'overview' | 'threats' | 'cases' | 'entities' | 'apps';

const TAB_ITEMS = [
  { id: 'overview', label: 'Overview' },
  { id: 'threats', label: 'Threats' },
  { id: 'cases', label: 'Cases' },
  { id: 'entities', label: 'Entities' },
  { id: 'apps', label: 'Mobile Apps' },
];

export const ReportsPage: React.FC = () => {
  const { brands, hasPermission } = useAuth();
  const { toast } = useToast();

  const [range, setRange] = useState<DateRangeValue>({ key: '30d' });
  const [brandId, setBrandId] = useState('');
  const [tab, setTab] = useState<ReportTab>('overview');

  const [overview, setOverview] = useState<ReportsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [exporting, setExporting] = useState<ReportKind | 'pdf' | null>(null);
  const hasDataRef = useRef(false);

  const dates = useMemo(() => rangeToDates(range), [range]);
  const params = useMemo(
    () => ({ from: dates.from, to: dates.to, brand_id: brandId || undefined }),
    [dates.from, dates.to, brandId]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const data = await reportService.getOverview(params);
        if (cancelled) return;
        setOverview(data);
        setError(null);
        hasDataRef.current = true;
      } catch (e) {
        if (cancelled) return;
        const msg = errText(e);
        setError(msg);
        if (hasDataRef.current) toast.error('Refresh failed', msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params, nonce, toast]);

  const brandOptions = useMemo(() => brands.map((b) => ({ value: b.id, label: b.name })), [brands]);

  const onExportCsv = async (kind: ReportKind) => {
    setExporting(kind);
    try {
      await reportService.exportCsv(kind, params);
      toast.success('CSV downloaded', `${kind} export for ${params.from} → ${params.to}.`);
    } catch (e) {
      toast.error('Export failed', errText(e));
    } finally {
      setExporting(null);
    }
  };

  const onGeneratePdf = async () => {
    if (!overview) return;
    setExporting('pdf');
    try {
      await reportService.exportPdfHtml(overview, 'AnaRisk Report');
      toast.info(
        'Print-ready report downloaded',
        "Open it and use your browser's Save as PDF to export the final document."
      );
    } catch (e) {
      toast.error('Report generation failed', errText(e));
    } finally {
      setExporting(null);
    }
  };

  const o = overview;

  const renderBody = () => {
    if (!o) {
      if (error) {
        return (
          <Card className="p-6">
            <ErrorState title="Could not load the report overview" message={error} onRetry={() => setNonce((n) => n + 1)} />
          </Card>
        );
      }
      return (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-[92px] rounded-2xl" />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-[320px] rounded-2xl" />
            ))}
          </div>
        </div>
      );
    }

    return (
      <div className="grid gap-5">
        {error && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning-100 bg-warning-100/60 px-4 py-3">
            <p className="text-[13px] font-semibold text-warning-600">
              Showing the last successful refresh — the latest attempt failed: {error}
            </p>
            <Button variant="outline" size="sm" onClick={() => setNonce((n) => n + 1)}>
              Retry
            </Button>
          </div>
        )}

        {tab === 'overview' && <OverviewTab o={o} />}
        {tab === 'threats' && <ThreatsTab o={o} />}
        {tab === 'cases' && <CasesTab o={o} />}
        {tab === 'entities' && <EntitiesTab o={o} />}
        {tab === 'apps' && <AppsTab o={o} />}
      </div>
    );
  };

  return (
    <div>
      <PageHeader
        title="Reports & Analytics"
        description="Aggregate risk, case and evidence reporting for the selected date range — every number comes straight from the API."
        actions={
          <>
            <DateRangeSelect value={range} onChange={setRange} />
            <FilterSelect
              label="Filter by brand"
              value={brandId}
              onChange={setBrandId}
              options={brandOptions}
              allLabel="All brands"
            />
            <Button
              variant="outline"
              icon={<RefreshCw className="h-4 w-4" />}
              loading={loading && !!o}
              onClick={() => setNonce((n) => n + 1)}
            >
              Refresh
            </Button>
            <Dropdown
              trigger={({ open }) => (
                <Button variant="outline" icon={<Download className="h-4 w-4" />} aria-expanded={open}>
                  Export CSV
                </Button>
              )}
              items={(
                [
                  ['threats', 'Threats'],
                  ['cases', 'Cases'],
                  ['entities', 'Entities'],
                  ['apps', 'Apps'],
                  ['evidence', 'Evidence'],
                ] as Array<[ReportKind, string]>
              ).map(([kind, label]) => ({
                label: exporting === kind ? `Exporting ${label}…` : label,
                icon: <FileDown className="h-4 w-4" />,
                disabled: exporting !== null,
                onClick: () => void onExportCsv(kind),
              }))}
            />
            <Button icon={<Download className="h-4 w-4" />} loading={exporting === 'pdf'} disabled={!o} onClick={() => void onGeneratePdf()}>
              Generate PDF
            </Button>
          </>
        }
      >
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <Tabs
            className="flex-1 border-b-0"
            items={TAB_ITEMS}
            value={tab}
            onChange={(id) => setTab(id as ReportTab)}
          />
          <p className="text-[12px] font-medium text-faint">
            {o ? (
              <>
                Range {o.date_range.from} → {o.date_range.to}
                {brandId ? ` · ${brandOptions.find((b) => b.value === brandId)?.label || 'brand'}` : ' · all brands'} ·
                updated {formatRelativeTime(o.generated_at)}
              </>
            ) : (
              'Loading range…'
            )}
          </p>
        </div>
      </PageHeader>

      {renderBody()}

      {o && <DataHonestyCard notes={o.data_notes} />}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Data honesty                                                       */
/* ------------------------------------------------------------------ */

const DataHonestyCard: React.FC<{ notes: string[] }> = ({ notes }) => (
  <Card className="mt-5 border-brand-200 bg-brand-50/70">
    <CardHeader className="pb-2">
      <CardTitle className="flex items-center gap-2 text-brand-800">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm">
          <Info className="h-4 w-4" />
        </span>
        Data honesty
      </CardTitle>
      <CardDescription className="text-brand-700/80">
        How to read the numbers on this page — nothing here is estimated or invented.
      </CardDescription>
    </CardHeader>
    <CardContent>
      <ul className="grid gap-2 sm:grid-cols-2">
        {notes.map((n, i) => (
          <li key={i} className="flex gap-2 rounded-lg bg-white/70 px-3 py-2 text-[12.5px] leading-relaxed text-ink-700">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
            {n}
          </li>
        ))}
      </ul>
    </CardContent>
  </Card>
);

/* ------------------------------------------------------------------ */
/*  Overview tab                                                       */
/* ------------------------------------------------------------------ */

const OverviewTab: React.FC<{ o: ReportsOverview }> = ({ o }) => {
  const trendData = useMemo(
    () => o.risk_trend.map((d) => ({ ...d, short: d.date.slice(5) })),
    [o.risk_trend]
  );
  const trendEmpty = !o.risk_trend.some((d) => d.avg_risk !== null || d.detections > 0);
  const riskPie = useMemo(() => toPie(o.threat_distribution, severityColor, (k) => SEVERITY_LABELS[k] || prettyKey(k)), [o.threat_distribution]);
  const casePie = useMemo(
    () =>
      CASE_STATUS_ORDER.filter((s) => Number(o.cases_by_status[s] || 0) > 0).map((s) => ({
        name: CASE_STATUS_LABELS[s] || prettyKey(s),
        value: Number(o.cases_by_status[s] || 0),
        color: CASE_STATUS_COLORS[s] || '#94A3B8',
      })),
    [o.cases_by_status]
  );
  const channelData = o.threats_by_channel.filter((c) => c.count > 0);

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Entities monitored" value={formatNumber(o.totals.entities)} icon={<Network className="h-4 w-4" />} />
        <StatCard
          label="High risk"
          value={formatNumber(o.totals.high_risk)}
          sub="severity = high"
          tone="#F04464"
          icon={<Activity className="h-4 w-4" />}
        />
        <StatCard
          label="Critical"
          value={formatNumber(o.totals.critical)}
          sub="severity = critical"
          tone="#E11D48"
          icon={<Activity className="h-4 w-4" />}
        />
        <StatCard
          label="Detections in range"
          value={formatNumber(o.totals.detections)}
          sub={`${formatNumber(o.totals.evidence)} evidence items · ${formatNumber(o.totals.relationships)} relationships`}
          tone="#8B5CF6"
          icon={<BarChart3 className="h-4 w-4" />}
        />
      </div>

      <SectionGrid>
        <ChartCard
          title="Risk distribution"
          description="Current severity of every entity in scope"
          empty={!hasValues(o.threat_distribution)}
          emptyTitle="No entities in range"
          emptyDescription="No entity has a severity breakdown for this scope yet."
        >
          <div className="relative">
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={riskPie} dataKey="value" nameKey="name" innerRadius={64} outerRadius={95} paddingAngle={2} stroke="#fff" strokeWidth={2}>
                  {riskPie.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTip />} />
                <Legend formatter={legendFormatter} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-x-0 top-[92px] flex flex-col items-center">
              <span className="text-2xl font-extrabold tracking-tight text-ink">
                {formatNumber(o.totals.entities)}
              </span>
              <span className="text-[10px] font-bold uppercase tracking-wider text-faint">entities</span>
            </div>
          </div>
        </ChartCard>

        <ChartCard
          title="Cases by status"
          description="Live investigation pipeline"
          empty={casePie.length === 0}
          emptyTitle="No cases yet"
          emptyDescription="Cases appear here as soon as detections are triaged."
        >
          <div className="relative">
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={casePie} dataKey="value" nameKey="name" innerRadius={64} outerRadius={95} paddingAngle={2} stroke="#fff" strokeWidth={2}>
                  {casePie.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTip />} />
                <Legend formatter={legendFormatter} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-x-0 top-[92px] flex flex-col items-center">
              <span className="text-2xl font-extrabold tracking-tight text-ink">
                {formatNumber(o.totals.open_cases)}
              </span>
              <span className="text-[10px] font-bold uppercase tracking-wider text-faint">open</span>
            </div>
          </div>
        </ChartCard>
      </SectionGrid>

      <ChartCard
        title="Risk trend"
        description="Daily average risk score (left axis) and detections (right axis)"
        empty={trendEmpty}
        emptyDescription="No assessments were recorded inside this date range."
      >
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={trendData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <defs>
              <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#4778F5" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#4778F5" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" vertical={false} />
            <XAxis dataKey="short" tick={axisTick} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis yAxisId="left" domain={[0, 1]} tickFormatter={(v: number) => v.toFixed(1)} tick={axisTick} tickLine={false} axisLine={false} width={44} />
            <YAxis yAxisId="right" orientation="right" allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} width={36} />
            <Tooltip content={<ChartTip />} />
            <Legend formatter={legendFormatter} wrapperStyle={{ fontSize: 11 }} />
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="avg_risk"
              name="Avg risk"
              stroke="#4778F5"
              strokeWidth={2}
              fill="url(#riskFill)"
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Area
              yAxisId="right"
              type="monotone"
              dataKey="detections"
              name="Detections"
              stroke="#8B5CF6"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              fill="transparent"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>

      <SectionGrid>
        <ChartCard
          title="Threats by channel"
          description="High & critical entities per product channel"
          empty={channelData.length === 0}
          emptyTitle="No entities at risk"
          emptyDescription="No high or critical entities are in scope for this range."
        >
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={channelData} margin={{ top: 16, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="channelGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4778F5" />
                  <stop offset="100%" stopColor="#8B5CF6" />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" vertical={false} />
              <XAxis dataKey="channel" tick={axisTick} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} width={36} />
              <Tooltip content={<ChartTip />} cursor={{ fill: '#EDF2FC' }} />
              <Bar dataKey="count" name="Entities at risk" fill="url(#channelGrad)" radius={[6, 6, 0, 0]} maxBarSize={64}>
                <LabelList dataKey="count" position="top" style={{ fontSize: 11, fontWeight: 700, fill: '#1D3A6B' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Top connected entities"
          description="Most linked nodes in the relationship graph"
          empty={o.top_connected_entities.length === 0}
          emptyTitle="No relationships yet"
          emptyDescription="Links appear once entities share images, domains or infrastructure."
        >
          <ol className="divide-y divide-line-soft">
            {o.top_connected_entities.map((e, i) => (
              <li key={e.entity_id} className="flex items-center gap-3 py-2.5">
                <span className="w-5 shrink-0 text-center text-[12px] font-extrabold text-faint">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/entities/${e.entity_id}`}
                    className="block truncate text-[13px] font-bold text-ink transition-colors hover:text-brand-600"
                  >
                    {e.display_name}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Badge
                      tone="outline"
                      className="text-[10.5px]"
                      style={{
                        borderColor: `${ENTITY_TYPE_COLORS[e.entity_type] || '#94A3B8'}55`,
                        color: ENTITY_TYPE_COLORS[e.entity_type] || '#64748B',
                      }}
                    >
                      {ENTITY_TYPE_LABELS[e.entity_type] || e.entity_type}
                    </Badge>
                    <span className="flex items-center gap-1 text-[11px] font-semibold text-muted">
                      <Link2 className="h-3 w-3" /> {e.relationship_count} links
                    </span>
                  </div>
                </div>
                <div className="w-28 shrink-0">
                  <ScoreBar value={e.risk_score} />
                </div>
              </li>
            ))}
          </ol>
        </ChartCard>
      </SectionGrid>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Open cases" value={formatNumber(o.totals.open_cases)} icon={<Briefcase className="h-4 w-4" />} />
        <StatCard label="Escalated" value={formatNumber(o.totals.escalated_cases)} tone="#F04464" icon={<Briefcase className="h-4 w-4" />} />
        <StatCard label="Resolved" value={formatNumber(o.totals.resolved_cases)} tone="#10B981" icon={<Briefcase className="h-4 w-4" />} />
        <StatCard label="Evidence in range" value={formatNumber(o.evidence.total)} sub={`${formatNumber(o.evidence.verified)} verified · ${formatNumber(o.evidence.pending)} pending`} tone="#20C5D7" icon={<FileDown className="h-4 w-4" />} />
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Threats tab                                                        */
/* ------------------------------------------------------------------ */

const ThreatsTab: React.FC<{ o: ReportsOverview }> = ({ o }) => {
  const rows = useMemo(
    () =>
      o.severity_by_type
        .map((r) => ({ ...r, label: ENTITY_TYPE_LABELS[r.entity_type] || prettyKey(r.entity_type) }))
        .filter((r) => SEVERITIES.some((s) => Number(r[s]) > 0)),
    [o.severity_by_type]
  );
  const typePie = useMemo(() => toPie(o.entity_type_distribution, (k) => ENTITY_TYPE_COLORS[k] || '#94A3B8', (k) => ENTITY_TYPE_LABELS[k] || prettyKey(k)), [o.entity_type_distribution]);

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="High risk entities" value={formatNumber(o.totals.high_risk)} tone="#F04464" sub="severity = high" icon={<Activity className="h-4 w-4" />} />
        <StatCard label="Critical entities" value={formatNumber(o.totals.critical)} tone="#E11D48" sub="severity = critical" icon={<Activity className="h-4 w-4" />} />
        <StatCard label="Detections in range" value={formatNumber(o.totals.detections)} tone="#8B5CF6" sub="risk assessments assessed in the range" icon={<BarChart3 className="h-4 w-4" />} />
      </div>

      <SectionGrid>
        <ChartCard
          title="Severity by entity type"
          description="Stacked severity counts per entity type"
          className="lg:col-span-1"
          empty={rows.length === 0}
          emptyTitle="No entities in range"
        >
          <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 56)}>
            <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 11, fill: '#3C5A8F' }} tickLine={false} axisLine={false} />
              <Tooltip content={<ChartTip />} cursor={{ fill: '#EDF2FC' }} />
              <Legend formatter={legendFormatter} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              {SEVERITIES.map((s) => (
                <Bar key={s} dataKey={s} stackId="sev" name={SEVERITY_LABELS[s]} fill={severityColor(s)} maxBarSize={26} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Entity type distribution"
          description="Composition of the monitored asset inventory"
          empty={typePie.length === 0}
          emptyTitle="No entities in range"
        >
          <div className="relative">
            <ResponsiveContainer width="100%" height={Math.max(240, rows.length * 40)}>
              <PieChart>
                <Pie data={typePie} dataKey="value" nameKey="name" innerRadius={60} outerRadius={92} paddingAngle={2} stroke="#fff" strokeWidth={2}>
                  {typePie.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTip />} />
                <Legend formatter={legendFormatter} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </SectionGrid>

      <ChartCard
        title="Severity breakdown"
        description="Exact counts per entity type and severity"
        empty={rows.length === 0}
        emptyTitle="No entities in range"
      >
        <DataTable
          columns={[
            { key: 'type', header: 'Entity type', cell: (r: (typeof rows)[number]) => <span className="font-semibold text-ink">{r.label}</span> },
            ...SEVERITIES.map((s) => ({
              key: s,
              header: SEVERITY_LABELS[s],
              headerClassName: s === 'critical' ? 'text-[#E11D48]' : undefined,
              cell: (r: (typeof rows)[number]) => <span className="tabular-nums font-semibold">{formatNumber(r[s])}</span>,
            })),
            {
              key: 'total',
              header: 'Total',
              cell: (r: (typeof rows)[number]) => (
                <span className="tabular-nums font-bold text-ink">
                  {formatNumber(SEVERITIES.reduce((sum, s) => sum + Number(r[s]), 0))}
                </span>
              ),
            },
          ]}
          rows={rows}
          rowKey={(r) => r.entity_type}
        />
      </ChartCard>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Cases tab                                                          */
/* ------------------------------------------------------------------ */

const CasesTab: React.FC<{ o: ReportsOverview }> = ({ o }) => {
  const caseData = CASE_STATUS_ORDER.map((s) => ({
    status: CASE_STATUS_LABELS[s] || prettyKey(s),
    key: s,
    count: Number(o.cases_by_status[s] || 0),
  }));
  const totalCases = caseData.reduce((sum, c) => sum + c.count, 0);

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Open cases" value={formatNumber(o.totals.open_cases)} sub="any status except resolved" icon={<Briefcase className="h-4 w-4" />} />
        <StatCard label="Escalated" value={formatNumber(o.totals.escalated_cases)} tone="#F04464" sub="sent to a partner" icon={<Briefcase className="h-4 w-4" />} />
        <StatCard label="Resolved" value={formatNumber(o.totals.resolved_cases)} tone="#10B981" sub="closed investigations" icon={<Briefcase className="h-4 w-4" />} />
      </div>

      <ChartCard
        title="Cases by status"
        description="Full pipeline from detection to resolution"
        empty={totalCases === 0}
        emptyTitle="No cases yet"
        emptyDescription="Investigations appear here as detections are triaged."
      >
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={caseData} margin={{ top: 16, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" vertical={false} />
            <XAxis dataKey="status" tick={axisTick} tickLine={false} axisLine={false} interval={0} angle={-16} height={46} textAnchor="end" />
            <YAxis allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} width={36} />
            <Tooltip content={<ChartTip />} cursor={{ fill: '#EDF2FC' }} />
            <Bar dataKey="count" name="Cases" radius={[6, 6, 0, 0]} maxBarSize={56}>
              {caseData.map((d) => (
                <Cell key={d.key} fill={CASE_STATUS_COLORS[d.key] || '#94A3B8'} />
              ))}
              <LabelList dataKey="count" position="top" style={{ fontSize: 11, fontWeight: 700, fill: '#1D3A6B' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard
        title="Entities behind open work"
        description="Most connected entities in scope — network context for investigators (no case linkage is exposed by this endpoint)"
        empty={o.top_connected_entities.length === 0}
        emptyTitle="No connected entities"
      >
        <DataTable
          columns={[
            {
              key: 'name',
              header: 'Entity',
              cell: (r: ReportsOverview['top_connected_entities'][number]) => (
                <Link to={`/entities/${r.entity_id}`} className="font-semibold text-ink hover:text-brand-600">
                  {r.display_name}
                </Link>
              ),
            },
            {
              key: 'type',
              header: 'Type',
              cell: (r: ReportsOverview['top_connected_entities'][number]) => (
                <Badge tone="outline" className="text-[11px]">
                  {ENTITY_TYPE_LABELS[r.entity_type] || r.entity_type}
                </Badge>
              ),
            },
            {
              key: 'links',
              header: 'Relationships',
              cell: (r: ReportsOverview['top_connected_entities'][number]) => (
                <span className="tabular-nums font-semibold">{r.relationship_count}</span>
              ),
            },
            {
              key: 'risk',
              header: 'Risk',
              className: 'w-40',
              cell: (r: ReportsOverview['top_connected_entities'][number]) => <ScoreBar value={r.risk_score} />,
            },
          ]}
          rows={o.top_connected_entities}
          rowKey={(r) => r.entity_id}
        />
      </ChartCard>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Entities tab                                                       */
/* ------------------------------------------------------------------ */

const EntitiesTab: React.FC<{ o: ReportsOverview }> = ({ o }) => {
  const typePie = useMemo(() => toPie(o.entity_type_distribution, (k) => ENTITY_TYPE_COLORS[k] || '#94A3B8', (k) => ENTITY_TYPE_LABELS[k] || prettyKey(k)), [o.entity_type_distribution]);
  const rows = useMemo(
    () =>
      o.severity_by_type
        .map((r) => ({ ...r, label: ENTITY_TYPE_LABELS[r.entity_type] || prettyKey(r.entity_type) }))
        .filter((r) => SEVERITIES.some((s) => Number(r[s]) > 0)),
    [o.severity_by_type]
  );

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Entities" value={formatNumber(o.totals.entities)} icon={<Network className="h-4 w-4" />} />
        <StatCard label="High risk" value={formatNumber(o.totals.high_risk)} tone="#F04464" icon={<Activity className="h-4 w-4" />} />
        <StatCard label="Critical" value={formatNumber(o.totals.critical)} tone="#E11D48" icon={<Activity className="h-4 w-4" />} />
        <StatCard label="Relationships" value={formatNumber(o.totals.relationships)} tone="#8B5CF6" icon={<Link2 className="h-4 w-4" />} />
      </div>

      <SectionGrid>
        <ChartCard title="Entity type distribution" description="Inventory by asset type" empty={typePie.length === 0} emptyTitle="No entities in range">
          <div className="relative">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={typePie} dataKey="value" nameKey="name" innerRadius={64} outerRadius={95} paddingAngle={2} stroke="#fff" strokeWidth={2}>
                  {typePie.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTip />} />
                <Legend formatter={legendFormatter} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Severity by type" description="Exact counts from the same overview payload" empty={rows.length === 0} emptyTitle="No entities in range">
          <DataTable
            columns={[
              { key: 'type', header: 'Entity type', cell: (r: (typeof rows)[number]) => <span className="font-semibold text-ink">{r.label}</span> },
              ...SEVERITIES.map((s) => ({
                key: s,
                header: SEVERITY_LABELS[s],
                cell: (r: (typeof rows)[number]) => <span className="tabular-nums font-semibold">{formatNumber(r[s])}</span>,
              })),
              {
                key: 'total',
                header: 'Total',
                cell: (r: (typeof rows)[number]) => (
                  <span className="tabular-nums font-bold text-ink">{formatNumber(SEVERITIES.reduce((sum, s) => sum + Number(r[s]), 0))}</span>
                ),
              },
            ]}
            rows={rows}
            rowKey={(r) => r.entity_type}
          />
        </ChartCard>
      </SectionGrid>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Mobile apps tab                                                    */
/* ------------------------------------------------------------------ */

const AppsTab: React.FC<{ o: ReportsOverview }> = ({ o }) => {
  const storeData = o.mobile_apps.by_store.filter((s) => s.count > 0);

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Mobile apps" value={formatNumber(o.mobile_apps.total)} sub="entities of type mobile_app" icon={<Smartphone className="h-4 w-4" />} />
        <StatCard label="High-risk apps" value={formatNumber(o.mobile_apps.high_risk)} tone="#F04464" sub="high or critical severity" icon={<Smartphone className="h-4 w-4" />} />
        <StatCard label="Stores covered" value={formatNumber(storeData.length)} tone="#20C5D7" sub="distinct stores in scope" icon={<BarChart3 className="h-4 w-4" />} />
      </div>

      <ChartCard
        title="Apps by store"
        description="Distribution of mobile app entities across stores"
        empty={storeData.length === 0}
        emptyTitle="No mobile apps in range"
        emptyDescription="Add a package on the monitoring page to start tracking store listings."
      >
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={storeData} margin={{ top: 16, right: 8, left: -18, bottom: 0 }}>
            <defs>
              <linearGradient id="storeGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#20C5D7" />
                <stop offset="100%" stopColor="#4778F5" />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#EDF2FC" vertical={false} />
            <XAxis dataKey="store" tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(v: string) => STORE_LABELS[v] || prettyKey(v)} />
            <YAxis allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} width={36} />
            <Tooltip content={<ChartTip />} cursor={{ fill: '#EDF2FC' }} />
            <Bar dataKey="count" name="Apps" fill="url(#storeGrad)" radius={[6, 6, 0, 0]} maxBarSize={72}>
              <LabelList dataKey="count" position="top" style={{ fontSize: 11, fontWeight: 700, fill: '#1D3A6B' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <Card className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <p className="text-[14px] font-bold text-ink">Need per-app detail?</p>
          <p className="mt-0.5 text-[13px] text-muted">
            Permissions, publishers, store URLs and sync history live on the full monitoring page.
          </p>
        </div>
        <Link
          to="/mobile-apps"
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-brand-100 bg-brand-50 px-4 text-sm font-semibold text-brand-700 transition-colors hover:bg-brand-100 focus-ring"
        >
          Open full monitoring page
          <ArrowRight className="h-4 w-4" />
        </Link>
      </Card>
    </div>
  );
};

export default ReportsPage;
