import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bell, BellOff, CheckCheck, Clock, Pause, Play, RefreshCw, Radar, AlertTriangle,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge, SeverityBadge } from '../components/ui/badge';
import { Tabs } from '../components/ui/tabs';
import { EmptyState, ErrorState, Pagination } from '../components/ui/table';
import { TableSkeleton } from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { ApiError } from '../services/apiClient';
import { notificationService } from '../services/notificationService';
import { monitoringService } from '../services/monitoringService';
import { formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';
import { NotificationItem, PaginatedResponse, MonitoringTarget } from '../types';

const TYPE_ICONS: Record<string, string> = {
  high_risk_detection: '🚨',
  case_assigned: '👤',
  case_escalated: '🔺',
  case_created: '📁',
  case_status: '🔄',
  case_resolved: '✅',
  evidence_added: '📎',
  integration_sync: '🔌',
  monitoring_stopped: '⏸️',
};

const errMessage = (err: unknown): string =>
  err instanceof ApiError ? err.message : 'The request failed. Please try again.';

const NotificationList: React.FC = () => {
  const { toast } = useToast();
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ['notifications-page', page],
    queryFn: () => notificationService.list({ page, page_size: 20 }),
  });

  const markAll = async () => {
    try {
      await notificationService.markRead();
      query.refetch();
    } catch (err) {
      toast.error('Could not mark read', errMessage(err));
    }
  };

  const markOne = async (n: NotificationItem) => {
    if (n.is_read) return;
    try {
      await notificationService.markRead([n.id]);
      query.refetch();
    } catch {
      /* non-critical */
    }
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[13px] text-muted">
          {query.data ? `${query.data.unread_count} unread` : 'Loading…'}
        </p>
        <Button variant="outline" size="sm" onClick={markAll} disabled={!query.data || query.data.unread_count === 0}>
          <CheckCheck className="h-4 w-4" /> Mark all read
        </Button>
      </div>

      {query.isLoading && <TableSkeleton rows={6} />}
      {query.isError && (
        <ErrorState title="Could not load alerts" message={errMessage(query.error)} onRetry={() => query.refetch()} />
      )}
      {query.data && query.data.items.length === 0 && (
        <EmptyState
          icon={<BellOff className="h-6 w-6" />}
          title="No alerts yet"
          description="Case assignments, escalations and high-risk detections will land here."
        />
      )}
      {query.data && query.data.items.length > 0 && (
        <ul className="space-y-2">
          {query.data.items.map((n) => (
            <li key={n.id}>
              <button
                onClick={() => markOne(n)}
                className={cn(
                  'flex w-full items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:border-brand-200',
                  !n.is_read && 'border-brand-100 bg-brand-50/50'
                )}
              >
                <span className="mt-0.5 text-lg leading-none">{TYPE_ICONS[n.type] || '🔔'}</span>
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      'block text-[13.5px] leading-snug',
                      n.is_read ? 'font-medium text-ink-700' : 'font-bold text-ink'
                    )}
                  >
                    {n.title}
                  </span>
                  {n.body && <span className="mt-0.5 block text-[12.5px] leading-snug text-muted">{n.body}</span>}
                  <span className="mt-1 block text-[11px] font-medium text-faint">
                    {formatRelativeTime(n.created_at)}
                  </span>
                </span>
                {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />}
              </button>
            </li>
          ))}
        </ul>
      )}
      {query.data && query.data.pages > 1 && (
        <Pagination
          page={query.data.page}
          pages={query.data.pages}
          total={query.data.total}
          onPageChange={setPage}
          className="px-0"
        />
      )}
    </div>
  );
};

const Watchlist: React.FC = () => {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const query = useQuery<PaginatedResponse<MonitoringTarget>>({
    queryKey: ['alerts-watchlist'],
    queryFn: () => monitoringService.listApps({ page: 1, page_size: 50 }),
  });

  const sync = async (t: MonitoringTarget) => {
    setSyncingId(t.id);
    try {
      const res = await monitoringService.syncApp(t.id);
      toast.success('Sync complete', res.message || `${t.package_id} checked.`);
      qc.invalidateQueries({ queryKey: ['alerts-watchlist'] });
    } catch (err) {
      toast.error('Sync failed', errMessage(err));
    } finally {
      setSyncingId(null);
    }
  };

  const toggle = async (t: MonitoringTarget) => {
    setTogglingId(t.id);
    const next = t.monitoring_status === 'active' ? 'paused' : 'active';
    try {
      await monitoringService.updateApp(t.id, { monitoring_status: next });
      toast.success(next === 'active' ? 'Monitoring resumed' : 'Monitoring paused', t.package_id);
      qc.invalidateQueries({ queryKey: ['alerts-watchlist'] });
    } catch (err) {
      toast.error('Update failed', errMessage(err));
    } finally {
      setTogglingId(null);
    }
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[13px] text-muted">
          Background scheduler runs due targets automatically — state lives in the database and survives restarts.
        </p>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          <RefreshCw className={cn('h-4 w-4', query.isFetching && 'animate-spin')} /> Refresh
        </Button>
      </div>

      {query.isLoading && <TableSkeleton rows={5} />}
      {query.isError && (
        <ErrorState title="Could not load watchlist" message={errMessage(query.error)} onRetry={() => query.refetch()} />
      )}
      {query.data && query.data.items.length === 0 && (
        <EmptyState
          icon={<Radar className="h-6 w-6" />}
          title="Nothing on the watchlist"
          description="Add packages in Mobile Apps to monitor them for abuse."
        />
      )}
      {query.data && query.data.items.length > 0 && (
        <ul className="space-y-2">
          {query.data.items.map((t) => (
            <li
              key={t.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-semibold text-ink">
                  {t.app_name || t.package_id}{' '}
                  <span className="font-normal text-muted">· {t.brand?.name}</span>
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
                  <span>{t.package_id}</span>
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {t.next_run_at ? `next run ${formatRelativeTime(t.next_run_at)}` : 'not scheduled'}
                  </span>
                  {t.last_run_status === 'failed' && (
                    <span className="inline-flex items-center gap-1 font-semibold text-danger">
                      <AlertTriangle className="h-3 w-3" /> last run failed{t.retry_count ? ` (retry ${t.retry_count})` : ''}
                    </span>
                  )}
                  {t.last_sync_at && <span>synced {formatRelativeTime(t.last_sync_at)}</span>}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                {t.entity && <SeverityBadge severity={t.entity.severity} />}
                <Badge tone={t.monitoring_status === 'active' ? 'success' : 'default'} dot>
                  {t.monitoring_status === 'active' ? 'Active' : 'Paused'}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => sync(t)}
                  loading={syncingId === t.id}
                  disabled={syncingId !== null}
                >
                  <RefreshCw className={cn('h-3.5 w-3.5', syncingId === t.id && 'animate-spin')} /> Sync
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggle(t)}
                  loading={togglingId === t.id}
                  disabled={togglingId !== null}
                  title={t.monitoring_status === 'active' ? 'Pause monitoring' : 'Resume monitoring'}
                >
                  {t.monitoring_status === 'active' ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export const AlertsPage: React.FC = () => {
  const [tab, setTab] = useState<'alerts' | 'watchlist'>('alerts');

  return (
    <div>
      <PageHeader
        title="Alerts & Watchlist"
        description="Everything that needs your attention: notifications from cases and detections, plus the monitoring watchlist backed by the persistent scheduler."
      />

      <Tabs
        items={[
          { id: 'alerts', label: 'Notifications', icon: <Bell className="h-4 w-4" /> },
          { id: 'watchlist', label: 'Watchlist', icon: <Radar className="h-4 w-4" /> },
        ]}
        value={tab}
        onChange={(id) => setTab(id as 'alerts' | 'watchlist')}
        className="mb-4"
      />

      {tab === 'alerts' && <NotificationList />}
      {tab === 'watchlist' && <Watchlist />}
    </div>
  );
};

export default AlertsPage;
