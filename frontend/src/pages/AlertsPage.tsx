import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bell, BellOff, CheckCheck, Clock, Pause, Play, RefreshCw, Radar, AlertTriangle, Trash2,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge, SeverityBadge } from '../components/ui/badge';
import { Tabs } from '../components/ui/tabs';
import { EmptyState, ErrorState, Pagination } from '../components/ui/table';
import { TableSkeleton } from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { Input, Field, Select } from '../components/ui/input';
import { useAuth } from '../hooks/useAuth';
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
  broadcast: '📣',
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

  const removeOne = async (n: NotificationItem) => {
    try {
      await notificationService.remove(n.id);
      toast.success('Notification deleted', n.title);
      query.refetch();
    } catch (err) {
      toast.error('Could not delete notification', errMessage(err));
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
            <li key={n.id} className="flex items-start gap-1.5">
              <button
                onClick={() => markOne(n)}
                className={cn(
                  'flex min-w-0 flex-1 items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left transition-colors hover:border-brand-200',
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
              <button
                onClick={() => removeOne(n)}
                aria-label={`Delete notification: ${n.title}`}
                title="Delete notification"
                className="mt-3 shrink-0 rounded-lg p-1.5 text-faint transition-colors hover:bg-danger-100 hover:text-danger focus-ring"
              >
                <Trash2 className="h-4 w-4" />
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
  const { brands, activeBrand, hasPermission } = useAuth();
  const canSubmit = hasPermission('entity:submit');
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addingBusy, setAddingBusy] = useState(false);
  const [form, setForm] = useState({ brand_id: activeBrand?.id || '', store: 'google_play', package_id: '', store_url: '' });

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

  const add = async () => {
    if (!form.brand_id || !form.package_id.trim()) return;
    setAddingBusy(true);
    try {
      await monitoringService.addApp({
        brand_id: form.brand_id,
        package_id: form.package_id.trim(),
        store: form.store,
        store_url: form.store_url.trim() || undefined,
      });
      toast.success('Added to watchlist', form.package_id.trim());
      setAdding(false);
      setForm((f) => ({ ...f, package_id: '', store_url: '' }));
      qc.invalidateQueries({ queryKey: ['alerts-watchlist'] });
    } catch (err) {
      toast.error('Could not add to watchlist', errMessage(err));
    } finally {
      setAddingBusy(false);
    }
  };

  const remove = async (t: MonitoringTarget) => {
    setRemovingId(t.id);
    try {
      await monitoringService.removeApp(t.id);
      toast.success('Removed from watchlist', t.package_id);
      qc.invalidateQueries({ queryKey: ['alerts-watchlist'] });
    } catch (err) {
      toast.error('Could not remove from watchlist', errMessage(err));
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-muted">
          Background scheduler runs due targets automatically — state lives in the database and survives restarts.
        </p>
        <div className="flex items-center gap-2">
          {canSubmit && !adding && (
            <Button size="sm" onClick={() => setAdding(true)}>
              Add to watchlist
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => query.refetch()}>
            <RefreshCw className={cn('h-4 w-4', query.isFetching && 'animate-spin')} /> Refresh
          </Button>
        </div>
      </div>

      {adding && canSubmit && (
        <div className="mb-4 rounded-xl border border-line bg-surface p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Brand" required>
              <Select value={form.brand_id} onChange={(e) => setForm((f) => ({ ...f, brand_id: e.target.value }))}>
                <option value="">Select a brand…</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="Store" required>
              <Select value={form.store} onChange={(e) => setForm((f) => ({ ...f, store: e.target.value }))}>
                <option value="google_play">Google Play</option>
                <option value="app_store">App Store</option>
              </Select>
            </Field>
            <Field label="Package ID" required>
              <Input
                value={form.package_id}
                onChange={(e) => setForm((f) => ({ ...f, package_id: e.target.value }))}
                placeholder="com.example.app"
              />
            </Field>
            <Field label="Store URL (optional)">
              <Input
                value={form.store_url}
                onChange={(e) => setForm((f) => ({ ...f, store_url: e.target.value }))}
                placeholder="https://…"
              />
            </Field>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <Button
              size="sm"
              loading={addingBusy}
              disabled={!form.brand_id || !form.package_id.trim()}
              onClick={() => void add()}
            >
              Start monitoring
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)} disabled={addingBusy}>
              Cancel
            </Button>
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-muted">
            Sync runs against the sample connector until a live store integration is configured —
            results are labelled as sample data, never as live store fetches.
          </p>
        </div>
      )}

      {query.isLoading && <TableSkeleton rows={5} />}
      {query.isError && (
        <ErrorState title="Could not load watchlist" message={errMessage(query.error)} onRetry={() => query.refetch()} />
      )}
      {query.data && query.data.items.length === 0 && (
        <EmptyState
          icon={<Radar className="h-6 w-6" />}
          title="Nothing on the watchlist"
          description="Add a package above, or from the Mobile Apps page, to start monitoring it."
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
                {canSubmit && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => remove(t)}
                    loading={removingId === t.id}
                    disabled={removingId !== null}
                    title="Remove from watchlist"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
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
