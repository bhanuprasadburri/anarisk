import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Eye, MoreHorizontal, Pencil, Plus, Trash2, UserPlus, X } from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { CaseStatusBadge, SeverityBadge } from '../components/ui/badge';
import { Field, Input, Select, Textarea } from '../components/ui/input';
import { ConfirmDialog, Modal } from '../components/ui/modal';
import { Dropdown } from '../components/ui/tabs';
import { Column, DataTable, EmptyState, ErrorState, Pagination } from '../components/ui/table';
import { Avatar, FilterSelect, SearchInput, Tooltip } from '../components/ui/misc';
import { ScoreBar } from '../components/ui/score';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { caseService } from '../services/caseService';
import { entityService } from '../services/entityService';
import { ApiError } from '../services/apiClient';
import { CASE_STATUS_LABELS, ENTITY_TYPE_LABELS, PLATFORM_LABELS, SEVERITY_LABELS } from '../lib/constants';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { CaseUserRef, DigitalEntity, InvestigationCase, PaginatedResponse } from '../types';

const STATUS_OPTIONS = Object.entries(CASE_STATUS_LABELS).map(([value, label]) => ({ value, label }));
const SEVERITY_OPTIONS = Object.entries(SEVERITY_LABELS).map(([value, label]) => ({ value, label }));
const SORTABLE = ['updated_at', 'risk_score', 'case_number'];

const errMsg = (e: unknown, fallback: string): string =>
  e instanceof ApiError ? e.message : fallback;

/* ------------------------------------------------------------------ *
 * New / Edit case modal
 * ------------------------------------------------------------------ */

interface CaseFormModalProps {
  open: boolean;
  onClose: () => void;
  record: InvestigationCase | null;
  existingEntities?: Array<{ id: string; name: string }>;
  onSaved: (saved: InvestigationCase | null) => void;
}

const CaseFormModal: React.FC<CaseFormModalProps> = ({
  open,
  onClose,
  record,
  existingEntities = [],
  onSaved,
}) => {
  const { brands } = useAuth();
  const { toast } = useToast();
  const isEdit = !!record;

  const [brandId, setBrandId] = useState('');
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [picked, setPicked] = useState<Array<{ id: string; name: string }>>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<DigitalEntity[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<{ brand?: string; title?: string; entities?: string }>({});

  useEffect(() => {
    if (!open) return;
    setBrandId(record?.brand_id || brands[0]?.id || '');
    setTitle(record?.title || '');
    setSummary(record?.summary || '');
    setSeverity(record?.severity || 'medium');
    setPlatforms(record?.platforms || []);
    setPicked([]);
    setQuery('');
    setResults([]);
    setErrors({});
    setSaving(false);
  }, [open, record, brands]);

  const togglePlatform = (key: string) =>
    setPlatforms((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));

  // Debounced entity search (create mode only — edits add entities from the workspace)
  useEffect(() => {
    if (!open || isEdit) return;
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await entityService.listEntities({ q, page_size: 5 });
        if (!cancelled) setResults(res.items);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, open, isEdit]);

  const submit = async () => {
    const next: { brand?: string; title?: string; entities?: string } = {};
    if (!isEdit && !brandId) next.brand = 'Choose a brand for this case';
    if (title.trim().length < 3) next.title = 'Title must be at least 3 characters';
    if (!isEdit && picked.length === 0) next.entities = 'Link at least one entity to open a case';
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setSaving(true);
    try {
      if (record) {
        const updated = await caseService.updateCase(record.id, {
          title: title.trim(),
          summary,
          severity,
          platforms,
          version: record.version,
        });
        toast.success('Case updated', `${updated.case_number} saved`);
        onSaved(updated);
        onClose();
      } else {
        const created = await caseService.createCase({
          brand_id: brandId,
          title: title.trim(),
          summary: summary.trim() || undefined,
          entity_ids: picked.map((p) => p.id),
          platforms,
        });
        toast.success('Case created', created.case_number);
        onSaved(created);
        onClose();
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('Case was modified by someone else — reload', 'Your changes were not saved.');
        onSaved(null);
        onClose();
      } else {
        toast.error(errMsg(e, 'Could not save the case'));
      }
    } finally {
      setSaving(false);
    }
  };

  const availableResults = results.filter((r) => !picked.some((p) => p.id === r.id));

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={isEdit ? `Edit ${record?.case_number}` : 'New investigation case'}
      description={
        isEdit
          ? 'Update the title, summary and severity. The version guard protects against conflicting edits.'
          : 'A case always starts in Detected with at least one linked entity.'
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            {isEdit ? 'Save changes' : 'Create case'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Brand" required error={errors.brand} htmlFor="case-brand">
            <Select
              id="case-brand"
              value={brandId}
              disabled={isEdit}
              invalid={!!errors.brand}
              onChange={(e) => setBrandId(e.target.value)}
            >
              <option value="">Select a brand…</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
            {isEdit && <p className="mt-1 text-xs text-faint">Brand cannot be changed after creation.</p>}
          </Field>

          <Field
            label="Severity"
            htmlFor="case-severity"
            hint={
              isEdit
                ? 'Recorded on the case by an investigator.'
                : 'Derived from the linked entities’ risk when the case is created.'
            }
          >
            <Select
              id="case-severity"
              value={severity}
              disabled={!isEdit}
              onChange={(e) => setSeverity(e.target.value)}
            >
              {SEVERITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="Title" required error={errors.title} htmlFor="case-title">
          <Input
            id="case-title"
            value={title}
            maxLength={300}
            placeholder="e.g. AcmeBank impersonation cluster"
            aria-invalid={!!errors.title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-faint">{title.length}/300</p>
        </Field>

        <Field label="Summary" htmlFor="case-summary">
          <Textarea
            id="case-summary"
            value={summary}
            maxLength={10000}
            placeholder="What is being investigated and why…"
            onChange={(e) => setSummary(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-faint">{summary.length}/10000</p>
        </Field>

        <Field label="Platforms" hint="Optional — where this case spans (click to toggle).">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Case platforms">
            {Object.entries(PLATFORM_LABELS)
              .filter(([key]) => key !== 'twitter') // 'x' is the canonical key; 'twitter' is its legacy alias
              .map(([key, label]) => {
                const active = platforms.includes(key);
                return (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => togglePlatform(key)}
                    className={
                      active
                        ? 'rounded-full border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 transition-colors hover:bg-brand-100'
                        : 'rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-muted transition-colors hover:border-brand-200 hover:text-ink-700'
                    }
                  >
                    {label}
                  </button>
                );
              })}
          </div>
        </Field>

        {isEdit ? (
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-ink-700">Linked entities</p>
            <div className="flex flex-wrap gap-2">
              {existingEntities.length === 0 && (
                <span className="text-[13px] text-muted">No entities linked.</span>
              )}
              {existingEntities.map((e) => (
                <span
                  key={e.id}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line bg-bg px-2.5 py-1 text-xs font-semibold text-ink-700"
                >
                  {e.name}
                </span>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-faint">
              Entities are added or removed from the case workspace (Entities tab).
            </p>
          </div>
        ) : (
          <div>
            <p className="mb-1.5 text-[13px] font-semibold text-ink-700">
              Linked entities <span className="text-danger">*</span>
            </p>
            <SearchInput
              value={query}
              onChange={setQuery}
              placeholder="Search entities to link (min 2 characters)…"
            />
            {errors.entities && <p className="mt-1.5 text-xs font-medium text-danger">{errors.entities}</p>}

            {availableResults.length > 0 && (
              <ul className="mt-2 divide-y divide-line-soft rounded-xl border border-line bg-white">
                {availableResults.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-semibold text-ink">{e.display_name}</p>
                      <p className="text-xs text-muted">
                        {ENTITY_TYPE_LABELS[e.entity_type] || e.entity_type}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setPicked((p) => [...p, { id: e.id, name: e.display_name }]);
                        setQuery('');
                        setResults([]);
                        setErrors((prev) => ({ ...prev, entities: undefined }));
                      }}
                    >
                      Add
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {searching && <p className="mt-2 text-xs text-muted">Searching…</p>}
            {!searching && query.trim().length >= 2 && availableResults.length === 0 && (
              <p className="mt-2 text-xs text-muted">No entities match “{query.trim()}”.</p>
            )}

            {picked.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {picked.map((p) => (
                  <span
                    key={p.id}
                    className="inline-flex items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700"
                  >
                    {p.name}
                    <button
                      type="button"
                      aria-label={`Remove ${p.name}`}
                      onClick={() => setPicked((prev) => prev.filter((x) => x.id !== p.id))}
                      className="rounded-full p-0.5 hover:bg-brand-100"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};

/* ------------------------------------------------------------------ *
 * Assign case modal
 * ------------------------------------------------------------------ */

interface AssignModalProps {
  open: boolean;
  onClose: () => void;
  record: InvestigationCase | null;
  onSaved: (saved: InvestigationCase) => void;
}

const AssignModal: React.FC<AssignModalProps> = ({ open, onClose, record, onSaved }) => {
  const { toast } = useToast();
  const [users, setUsers] = useState<CaseUserRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [userId, setUserId] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setNote('');
    setSaving(false);
    (async () => {
      setLoading(true);
      try {
        const raw = (await caseService.listAssignableUsers()) as unknown as
          | CaseUserRef[]
          | { items: CaseUserRef[] };
        const items = Array.isArray(raw) ? raw : raw.items || [];
        if (!cancelled) {
          setUsers(items);
          setUserId(record?.assigned_to?.id || items[0]?.id || '');
        }
      } catch (e) {
        if (!cancelled) toast.error(errMsg(e, 'Could not load assignable users'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, record?.id]);

  const submit = async () => {
    if (!record || !userId) return;
    setSaving(true);
    try {
      const updated = await caseService.assign(record.id, userId, note.trim() || undefined);
      toast.success('Assignee updated');
      onSaved(updated);
      onClose();
    } catch (e) {
      toast.error(errMsg(e, 'Could not assign this case'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Assign case"
      description="The owner is recorded in the case history. Assigning an Under Review case moves it to Assigned."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving} disabled={!userId}>
            Assign
          </Button>
        </>
      }
    >
      {loading ? (
        <p className="text-sm text-muted">Loading assignable investigators…</p>
      ) : users.length === 0 ? (
        <p className="text-sm text-muted">No investigators are available to take this case.</p>
      ) : (
        <div className="space-y-4">
          <Field label="Assign to" required htmlFor="assign-user">
            <Select id="assign-user" value={userId} onChange={(e) => setUserId(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Note (optional)" htmlFor="assign-note">
            <Textarea
              id="assign-note"
              value={note}
              maxLength={2000}
              placeholder="Context for the new owner…"
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        </div>
      )}
    </Modal>
  );
};

/* ------------------------------------------------------------------ *
 * Investigation Cases list page
 * ------------------------------------------------------------------ */

export const CasesPage: React.FC = () => {
  const navigate = useNavigate();
  const { brands, role, hasPermission } = useAuth();
  const { toast } = useToast();
  const [params, setParams] = useSearchParams();

  const q = params.get('q') ?? '';
  const status = params.get('status') ?? '';
  const severity = params.get('severity') ?? '';
  const brandId = params.get('brand') ?? '';
  const sort = params.get('sort') ?? 'updated_at';
  const order: 'asc' | 'desc' = params.get('order') === 'asc' ? 'asc' : 'desc';
  const page = Math.max(1, Number(params.get('page') || 1));
  const pageSize = Math.max(1, Number(params.get('page_size') || 20));

  const canCreate = hasPermission('case:create');
  const canTriage = hasPermission('case:triage');
  const canAssign = hasPermission('case:assign');
  const isAdmin = role === 'administrator';
  const hasFilters = !!(q || status || severity || brandId);

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        Object.entries(patch).forEach(([key, value]) => {
          if (value === null || value === '') next.delete(key);
          else next.set(key, value);
        });
        if (!('page' in patch)) next.delete('page');
        return next;
      });
    },
    [setParams]
  );

  const [data, setData] = useState<PaginatedResponse<InvestigationCase> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await caseService.listCases({
        q: q || undefined,
        status: status ? [status] : undefined,
        severity: severity ? [severity] : undefined,
        brand_id: brandId || undefined,
        page,
        page_size: pageSize,
        sort,
        order,
      });
      setData(res);
    } catch (e) {
      setError(errMsg(e, 'We could not load your cases. Check your connection and try again.'));
    } finally {
      setLoading(false);
    }
  }, [q, status, severity, brandId, page, pageSize, sort, order]);

  useEffect(() => {
    void load();
  }, [load]);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<InvestigationCase | null>(null);
  const [assignTarget, setAssignTarget] = useState<InvestigationCase | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<InvestigationCase | null>(null);
  const [deleting, setDeleting] = useState(false);

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };
  const openEdit = (row: InvestigationCase) => {
    setEditing(row);
    setFormOpen(true);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await caseService.deleteCase(deleteTarget.id);
      toast.success('Case deleted', `${deleteTarget.case_number} removed`);
      setDeleteTarget(null);
      void load();
    } catch (e) {
      toast.error(errMsg(e, 'Could not delete this case'));
    } finally {
      setDeleting(false);
    }
  };

  const brandName = useCallback(
    (id: string) => brands.find((b) => b.id === id)?.name ?? '—',
    [brands]
  );

  const onSortChange = (key: string) => {
    const nextOrder = sort === key ? (order === 'asc' ? 'desc' : 'asc') : 'desc';
    update({ sort: key, order: nextOrder });
  };

  const columns: Column<InvestigationCase>[] = useMemo(
    () => [
      {
        key: 'case_number',
        header: 'Case #',
        sortable: true,
        className: 'whitespace-nowrap',
        cell: (row) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/cases/${row.id}`);
            }}
            className="rounded-md font-mono text-[12.5px] font-semibold text-brand-600 transition-colors hover:text-brand-700 hover:underline focus-ring"
          >
            {row.case_number}
          </button>
        ),
      },
      {
        key: 'title',
        header: 'Title',
        cell: (row) => (
          <div className="min-w-0">
            <div className="truncate font-semibold text-ink">{row.title}</div>
            <div className="truncate text-xs text-muted">
              {row.entity_count} linked {row.entity_count === 1 ? 'entity' : 'entities'}
            </div>
          </div>
        ),
      },
      {
        key: 'brand',
        header: 'Brand',
        cell: (row) => <span className="whitespace-nowrap">{brandName(row.brand_id)}</span>,
      },
      {
        key: 'risk_score',
        header: 'Risk',
        sortable: true,
        className: 'min-w-[130px]',
        cell: (row) => <ScoreBar value={row.risk_score} severity={row.severity} />,
      },
      {
        key: 'severity',
        header: 'Severity',
        cell: (row) => <SeverityBadge severity={row.severity} />,
      },
      {
        key: 'status',
        header: 'Status',
        cell: (row) => <CaseStatusBadge status={row.status} />,
      },
      {
        key: 'assignee',
        header: 'Assignee',
        cell: (row) =>
          row.assigned_to ? (
            <div className="flex items-center gap-2">
              <Avatar name={row.assigned_to.full_name || row.assigned_to.email} size={24} />
              <span className="truncate text-[13px] font-medium">
                {row.assigned_to.full_name || row.assigned_to.email}
              </span>
            </div>
          ) : (
            <span className="text-[13px] text-faint">Unassigned</span>
          ),
      },
      {
        key: 'updated_at',
        header: 'Updated',
        sortable: true,
        className: 'whitespace-nowrap',
        cell: (row) => (
          <Tooltip content={formatDate(row.updated_at)}>
            <span className="text-[13px] text-muted">{formatRelativeTime(row.updated_at)}</span>
          </Tooltip>
        ),
      },
      {
        key: 'actions',
        header: '',
        headerClassName: 'w-12',
        className: 'w-12',
        cell: (row) => (
          <div onClick={(e) => e.stopPropagation()}>
            <Dropdown
              trigger={() => (
                <button
                  aria-label={`Actions for ${row.case_number}`}
                  className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              )}
              items={[
                {
                  label: 'View case',
                  icon: <Eye className="h-4 w-4" />,
                  onClick: () => navigate(`/cases/${row.id}`),
                },
                {
                  label: 'Edit details',
                  icon: <Pencil className="h-4 w-4" />,
                  disabled: !canTriage,
                  onClick: () => openEdit(row),
                },
                {
                  label: 'Assign',
                  icon: <UserPlus className="h-4 w-4" />,
                  disabled: !canAssign,
                  onClick: () => setAssignTarget(row),
                },
                {
                  label: 'Delete case',
                  icon: <Trash2 className="h-4 w-4" />,
                  danger: true,
                  separatorBefore: true,
                  disabled: !isAdmin,
                  onClick: () => setDeleteTarget(row),
                },
              ]}
            />
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [brandName, canTriage, canAssign, isAdmin, order, sort]
  );

  const emptyState = hasFilters ? (
    <EmptyState
      title="No cases match"
      description="Try a different search term or clear the active filters."
      action={
        <Button variant="outline" onClick={() => update({ q: null, status: null, severity: null, brand: null })}>
          Clear filters
        </Button>
      }
    />
  ) : (
    <EmptyState
      title="No cases yet"
      description="Open your first investigation case to start tracking entities, evidence and response."
      action={
        canCreate ? (
          <Button icon={<Plus className="h-4 w-4" />} onClick={openCreate}>
            New Case
          </Button>
        ) : undefined
      }
    />
  );

  return (
    <div>
      <PageHeader
        title="Investigation Cases"
        description="Manage and track your investigation cases."
        actions={
          canCreate ? (
            <Button icon={<Plus className="h-4 w-4" />} onClick={openCreate}>
              New Case
            </Button>
          ) : undefined
        }
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchInput
            className="w-full sm:w-72"
            value={q}
            onChange={(v) => update({ q: v })}
            debounceMs={400}
            placeholder="Search by case number or title…"
          />
          <FilterSelect
            label="Filter by status"
            value={status}
            onChange={(v) => update({ status: v })}
            options={STATUS_OPTIONS}
            allLabel="All statuses"
          />
          <FilterSelect
            label="Filter by severity"
            value={severity}
            onChange={(v) => update({ severity: v })}
            options={SEVERITY_OPTIONS}
            allLabel="All severities"
          />
          <FilterSelect
            label="Filter by brand"
            value={brandId}
            onChange={(v) => update({ brand: v })}
            options={brands.map((b) => ({ value: b.id, label: b.name }))}
            allLabel="All brands"
          />
          {hasFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => update({ q: null, status: null, severity: null, brand: null })}
            >
              Clear filters
            </Button>
          )}
        </div>
      </PageHeader>

      <div className="rounded-2xl border border-line bg-surface shadow-card">
        {error ? (
          <div className="px-5 py-10">
            <ErrorState title="Could not load cases" message={error} onRetry={() => void load()} />
          </div>
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.id}
              sort={SORTABLE.includes(sort) ? sort : null}
              order={order}
              onSortChange={onSortChange}
              onRowClick={(row) => navigate(`/cases/${row.id}`)}
              loading={loading}
              emptyState={emptyState}
              className="min-w-[1024px]"
            />
            {data && data.total > 0 && (
              <div className="border-t border-line-soft">
                <Pagination
                  page={data.page}
                  pages={data.pages}
                  total={data.total}
                  onPageChange={(p) => update({ page: String(p) })}
                  pageSize={pageSize}
                  onPageSizeChange={(s) => update({ page_size: String(s) })}
                />
              </div>
            )}
          </>
        )}
      </div>

      <CaseFormModal
        open={formOpen}
        record={editing}
        onClose={() => setFormOpen(false)}
        onSaved={() => void load()}
      />

      <AssignModal
        open={!!assignTarget}
        record={assignTarget}
        onClose={() => setAssignTarget(null)}
        onSaved={() => void load()}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
        loading={deleting}
        destructive
        title="Delete this case?"
        confirmLabel="Delete case"
        message={
          <>
            <span className="font-semibold text-ink">{deleteTarget?.case_number}</span> —{' '}
            {deleteTarget?.title}. Notes, events, assignments and links are removed permanently.
            Entities and evidence are kept. This cannot be undone.
          </>
        }
      />
    </div>
  );
};

export default CasesPage;
