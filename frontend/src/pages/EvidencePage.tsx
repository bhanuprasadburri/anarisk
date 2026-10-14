import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Camera,
  Check,
  CheckCircle2,
  AlertTriangle,
  Download,
  Eye,
  File as FileIcon,
  FileSearch,
  FileText,
  Globe,
  Image as ImageIcon,
  Link2,
  Paperclip,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  Unlink,
  Upload,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Badge, ProvenanceBadge } from '../components/ui/badge';
import { Modal, ConfirmDialog } from '../components/ui/modal';
import { Field, Input, Select, Textarea, inputBase } from '../components/ui/input';
import { DataTable, EmptyState, ErrorState, Pagination, type Column } from '../components/ui/table';
import { Tabs, Dropdown, type DropdownItem } from '../components/ui/tabs';
import { CopyButton, FilterSelect, KeyValue, SearchInput, Tooltip } from '../components/ui/misc';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { evidenceService, type EvidenceListParams } from '../services/evidenceService';
import { caseService } from '../services/caseService';
import { entityService } from '../services/entityService';
import { apiRequest, ApiError, getToken } from '../services/apiClient';
import { API_BASE_URL, EVIDENCE_KIND_LABELS, VERIFICATION_LABELS } from '../lib/constants';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';
import {
  DigitalEntity,
  EvidenceListItem,
  EvidenceVerificationResult,
  InvestigationCase,
} from '../types';

type EvidenceRow = EvidenceListItem;

interface EntityPick {
  id: string;
  display_name: string;
}

/* ---------------- chips ---------------- */

const CHIP_KINDS: Record<string, string[] | null> = {
  all: null,
  images: ['image', 'screenshot'],
  docs: ['text', 'other'],
  logs: ['url_inspection', 'whois'],
  network: ['url'],
};

const CHIP_ITEMS = [
  { id: 'all', label: 'All' },
  { id: 'images', label: 'Images' },
  { id: 'docs', label: 'Docs' },
  { id: 'logs', label: 'Logs' },
  { id: 'network', label: 'Network' },
];

const MANUAL_KINDS = ['text', 'url', 'url_inspection', 'whois', 'other'];
const UPLOAD_KINDS = ['screenshot', 'image'];
const ALLOWED_UPLOAD_MIME = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
const ALLOWED_UPLOAD_EXT = ['.png', '.jpg', '.jpeg', '.webp', '.gif'];
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

const KIND_META: Record<string, { icon: React.ReactNode; chip: string; tone: 'warning' | 'primary' | 'info' | 'violet' | 'success' | 'default' }> = {
  screenshot: { icon: <Camera className="h-4 w-4" />, chip: 'bg-warning-100 text-warning-600', tone: 'warning' },
  image: { icon: <ImageIcon className="h-4 w-4" />, chip: 'bg-warning-100 text-warning-600', tone: 'warning' },
  text: { icon: <FileText className="h-4 w-4" />, chip: 'bg-brand-50 text-brand-600', tone: 'primary' },
  url: { icon: <Link2 className="h-4 w-4" />, chip: 'bg-cyanx-100 text-cyanx-600', tone: 'info' },
  url_inspection: { icon: <FileSearch className="h-4 w-4" />, chip: 'bg-violet-100 text-violet-600', tone: 'violet' },
  whois: { icon: <Globe className="h-4 w-4" />, chip: 'bg-success-100 text-success-600', tone: 'success' },
  other: { icon: <FileIcon className="h-4 w-4" />, chip: 'bg-line-soft text-muted', tone: 'default' },
};

const VERIF_TONE: Record<string, 'success' | 'warning' | 'danger'> = {
  verified: 'success',
  pending: 'warning',
  mismatch: 'danger',
};

/* ---------------- helpers ---------------- */

const evidenceName = (row: EvidenceRow): string =>
  row.file_name || row.title || row.description || 'Untitled evidence';

const formatSize = (n?: number | null): string => {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
};

const prettyJson = (value: unknown): string | null => {
  if (!value || typeof value !== 'object' || Object.keys(value as object).length === 0) return null;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return null;
  }
};

const errMessage = (err: unknown): string =>
  (err as ApiError | undefined)?.message || 'The request failed. Please try again.';

function readApiError(err: unknown): { fields: Record<string, string>; message: string } {
  const e = err as ApiError | undefined;
  const fields: Record<string, string> = {};
  const details = Array.isArray(e?.details) ? (e.details as Array<{ field?: string; message?: string }>) : [];
  details.forEach((d) => {
    if (d && d.field) fields[d.field] = d.message || 'Invalid value';
  });
  return { fields, message: e?.message || 'The request failed. Please try again.' };
}

function validateUploadFile(f: File | null): string | null {
  if (!f) return 'Choose a file to upload';
  const ext = (f.name.toLowerCase().match(/\.[a-z0-9]+$/) || [''])[0];
  const typeOk = ALLOWED_UPLOAD_MIME.includes(f.type) || (f.type === '' && ALLOWED_UPLOAD_EXT.includes(ext));
  if (!typeOk)
    return 'Only PNG, JPEG, WEBP or GIF images can be uploaded — the server validates the real file content. Use Manual record for text, logs, URLs or other documents.';
  if (f.size === 0) return 'The selected file is empty';
  if (f.size > MAX_UPLOAD_BYTES) return 'The file is larger than the 5 MB limit';
  return null;
}

/** Stable client-side comparator for multi-kind (OR) queries — mirrors server order (nulls last). */
function compareEvidence(a: EvidenceRow, b: EvidenceRow, sort: string, order: 'asc' | 'desc'): number {
  const dir = order === 'asc' ? 1 : -1;
  if (sort === 'title') return (a.title || '').localeCompare(b.title || '') * dir;
  if (sort === 'size_bytes') return ((a.size_bytes ?? -1) - (b.size_bytes ?? -1)) * dir;
  const key = (r: EvidenceRow) =>
    new Date(sort === 'collected_at' ? r.collected_at || r.created_at : r.created_at).getTime();
  return (key(a) - key(b)) * dir;
}

/* ------------------------------------------------------------------ *
 * Entity search-select (used by both Add Evidence tabs)
 * ------------------------------------------------------------------ */

const EntityPicker: React.FC<{
  id: string;
  label: string;
  required?: boolean;
  error?: string | null;
  hint?: React.ReactNode;
  value: EntityPick | null;
  onChange: (v: EntityPick | null) => void;
}> = ({ id, label, required, error, hint, value, onChange }) => {
  const [text, setText] = useState('');
  const [results, setResults] = useState<DigitalEntity[]>([]);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => timer.current && clearTimeout(timer.current), []);

  const onType = (raw: string) => {
    setText(raw);
    if (value) onChange(null);
    clearTimeout(timer.current);
    if (raw.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    setSearching(true);
    timer.current = setTimeout(async () => {
      try {
        const res = await entityService.listEntities({ q: raw.trim(), page_size: 5 });
        setResults(res.items);
        setOpen(true);
      } catch {
        setResults([]);
        setOpen(false);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const pick = (e: DigitalEntity) => {
    onChange({ id: e.id, display_name: e.display_name });
    setText('');
    setResults([]);
    setOpen(false);
  };

  return (
    <Field label={label} required={required} error={error} hint={hint} htmlFor={id}>
      <div className="relative">
        <input
          id={id}
          type="search"
          value={text}
          onChange={(e) => onType(e.target.value)}
          placeholder={value ? value.display_name : 'Search entities by name…'}
          aria-label={label}
          autoComplete="off"
          className={cn(inputBase, 'h-10 pr-9', error && 'border-danger')}
        />
        {(searching || value) && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-faint">
            {searching ? (
              <span className="block h-4 w-4 animate-spin rounded-full border-2 border-brand-200 border-t-brand-500" />
            ) : (
              <Check className="h-4 w-4 text-success" />
            )}
          </span>
        )}
        {open && (results.length > 0 || searching) && (
          <div className="absolute left-0 right-0 top-11 z-30 animate-scale-in rounded-xl border border-line bg-surface p-1.5 shadow-popover">
            {searching && results.length === 0 && (
              <p className="px-3 py-2 text-[13px] text-muted">Searching…</p>
            )}
            {results.map((e) => (
              <button
                key={e.id}
                type="button"
                onMouseDown={(ev) => ev.preventDefault()}
                onClick={() => pick(e)}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-brand-50 focus-ring"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-semibold text-ink">{e.display_name}</span>
                  <span className="block text-[11px] text-muted">{e.entity_type.replace(/_/g, ' ')}</span>
                </span>
                <span className="shrink-0 rounded-full bg-line-soft px-2 py-0.5 text-[10px] font-bold uppercase text-faint">
                  select
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
      {value && (
        <span className="mt-1.5 inline-flex items-center gap-1.5 rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 text-[12px] font-semibold text-brand-700">
          <Paperclip className="h-3 w-3" />
          <span className="max-w-[220px] truncate">{value.display_name}</span>
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setText('');
            }}
            aria-label="Clear selected entity"
            className="rounded p-0.5 hover:bg-brand-100 focus-ring"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
    </Field>
  );
};

/* ------------------------------------------------------------------ */

export const EvidencePage: React.FC = () => {
  const { user, hasPermission } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const canWrite = hasPermission('evidence:write');
  const canDelete = user?.role === 'administrator' || user?.role === 'investigator';

  /* ---------------- URL-backed filter state ---------------- */
  const q = searchParams.get('q') || '';
  const chip = searchParams.get('chip') || 'all';
  const typeFilter = searchParams.get('type') || '';
  const caseId = searchParams.get('case') || '';
  const verif = searchParams.get('verif') || '';
  const entityId = searchParams.get('entity_id') || '';
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

  const clearFilters = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        // keep a manual entity scoping only when explicitly asked to
        ['q', 'type', 'case', 'verif', 'chip', 'sort', 'order'].forEach((k) => next.delete(k));
        next.delete('page');
        return next;
      },
      { replace: true }
    );

  /* ---------------- effective kind selection ---------------- */
  const chipKinds: string[] | null = CHIP_KINDS[chip] ?? null;
  const kinds: string[] | null = typeFilter ? [typeFilter] : chipKinds;
  const singleMode = kinds === null || kinds.length === 1;
  const singleKind = kinds && kinds.length === 1 ? kinds[0] : undefined;

  const baseArgs: EvidenceListParams = useMemo(
    () => ({
      q: q || undefined,
      case_id: caseId || undefined,
      verification_status: verif || undefined,
      entity_id: entityId || undefined,
    }),
    [q, caseId, verif, entityId]
  );

  const singleQuery = useQuery({
    queryKey: ['evidence-list', baseArgs, singleKind, page, pageSize, sort, order],
    queryFn: () =>
      evidenceService.listEvidence({
        ...baseArgs,
        kind: singleKind,
        page,
        page_size: pageSize,
        sort: sort || undefined,
        order,
      }),
    enabled: singleMode,
    placeholderData: keepPreviousData,
  });

  const multiQuery = useQuery({
    queryKey: ['evidence-group', baseArgs, kinds, sort, order],
    queryFn: async () => {
      const ks = kinds as string[];
      const results = await Promise.all(
        ks.map((k) =>
          evidenceService.listEvidence({
            ...baseArgs,
            kind: k,
            page: 1,
            page_size: 100,
            sort: sort || undefined,
            order,
          })
        )
      );
      let serverTotal = 0;
      let truncated = false;
      const seen = new Set<string>();
      const merged: EvidenceRow[] = [];
      results.forEach((r) => {
        serverTotal += r.total;
        if (r.pages > 1) truncated = true;
        r.items.forEach((it) => {
          const row = it as EvidenceRow;
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        });
      });
      merged.sort((a, b) => compareEvidence(a, b, sort, order));
      return { items: merged, serverTotal, truncated };
    },
    enabled: !singleMode,
  });

  const normalized = useMemo(() => {
    if (singleMode) {
      const d = singleQuery.data;
      if (!d) return null;
      return { items: d.items as EvidenceRow[], total: d.total, pages: d.pages, truncated: false };
    }
    const d = multiQuery.data;
    if (!d) return null;
    const pages = Math.max(1, Math.ceil(d.items.length / pageSize));
    return {
      items: d.items,
      total: d.items.length,
      pages,
      truncated: d.truncated || d.serverTotal > d.items.length,
      serverTotal: d.serverTotal,
    };
  }, [singleMode, singleQuery.data, multiQuery.data, pageSize]);

  const rows: EvidenceRow[] = useMemo(() => {
    if (!normalized) return [];
    if (singleMode) return normalized.items;
    return normalized.items.slice((page - 1) * pageSize, page * pageSize);
  }, [normalized, singleMode, page, pageSize]);

  const listError = singleMode ? singleQuery.error : multiQuery.error;
  const listIsPending = singleMode ? singleQuery.isPending : multiQuery.isPending;
  const listIsError = singleMode ? singleQuery.isError : multiQuery.isError;
  const refetchList = () => {
    if (singleMode) void singleQuery.refetch();
    else void multiQuery.refetch();
  };

  const refetchAll = () => {
    queryClient.invalidateQueries({ queryKey: ['evidence-list'] });
    queryClient.invalidateQueries({ queryKey: ['evidence-group'] });
  };

  const hasFilters = !!(q || typeFilter || caseId || verif || entityId || (chip && chip !== 'all'));

  // Deep-linked page numbers beyond the result set are clamped so the table never shows a false empty state.
  const totalPages = normalized?.pages;
  useEffect(() => {
    if (totalPages && page > totalPages) setParams({ page: String(totalPages) });
  }, [totalPages, page, setParams]);

  /* ---------------- cases (chips + selects) ---------------- */
  const casesQuery = useQuery({
    queryKey: ['evidence-cases-select'],
    queryFn: () => caseService.listCases({ page_size: 100 }),
    staleTime: 5 * 60 * 1000,
  });
  const caseItems: InvestigationCase[] = useMemo(() => casesQuery.data?.items || [], [casesQuery.data]);
  const caseMap = useMemo(() => new Map(caseItems.map((c) => [c.id, c])), [caseItems]);

  /* ---------------- entity scope chip ---------------- */
  const entityQuery = useQuery({
    queryKey: ['evidence-entity-scope', entityId],
    queryFn: () => entityService.getEntity(entityId),
    enabled: !!entityId,
  });

  /* ---------------- CSV export ---------------- */
  const onExport = async () => {
    const params: EvidenceListParams = { ...baseArgs };
    if (kinds && kinds.length === 1) params.kind = kinds[0];
    try {
      await evidenceService.exportCsv(params);
      if (kinds && kinds.length > 1) {
        toast.info(
          'CSV exported (all types)',
          'The export endpoint accepts a single type, so the active type group was not applied — every other filter was.'
        );
      } else {
        toast.success('CSV exported', 'The file covers every record matching the current filters.');
      }
    } catch (err) {
      toast.error('Export failed', errMessage(err));
    }
  };

  /* ---------------- preview ---------------- */
  const [preview, setPreview] = useState<EvidenceRow | null>(null);
  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const [imgLoading, setImgLoading] = useState(false);
  const [imgError, setImgError] = useState(false);

  const previewIsImage = !!preview && (preview.kind === 'image' || preview.kind === 'screenshot') && !!preview.has_file;

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setImgSrc(null);
    setImgError(false);
    if (!previewIsImage || !preview) return;
    setImgLoading(true);
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/evidence/${preview.id}/file`, {
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImgSrc(objectUrl);
      } catch {
        if (!cancelled) setImgError(true);
      } finally {
        if (!cancelled) setImgLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [preview, previewIsImage]);

  /* ---------------- verify ---------------- */
  const [verifyResult, setVerifyResult] = useState<EvidenceVerificationResult | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

  const onVerify = async (row: EvidenceRow) => {
    setVerifyingId(row.id);
    try {
      const res = await evidenceService.verifyEvidence(row.id);
      setVerifyResult(res);
      if (res.matches) toast.success('Verification passed', 'The recomputed SHA-256 matches the stored hash.');
      else
        toast.error(
          'Verification mismatch',
          'The recomputed SHA-256 differs from the stored hash — the stored bytes changed.'
        );
      refetchAll();
    } catch (err) {
      toast.error('Verification failed', errMessage(err));
    } finally {
      setVerifyingId(null);
    }
  };

  /* ---------------- download ---------------- */
  const onDownload = async (row: EvidenceRow) => {
    try {
      await evidenceService.downloadEvidence(row.id, row.file_name || undefined);
      toast.success('Download started', evidenceName(row));
    } catch (err) {
      toast.error('Download failed', errMessage(err));
    }
  };

  /* ---------------- link / unlink ---------------- */
  const [linkTarget, setLinkTarget] = useState<EvidenceRow | null>(null);
  const [linkCaseId, setLinkCaseId] = useState('');
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const onLink = async () => {
    if (!linkTarget || !linkCaseId) return;
    setLinkBusy(true);
    setLinkError(null);
    try {
      await evidenceService.linkEvidence(linkTarget.id, { case_id: linkCaseId });
      toast.success('Evidence linked', 'The case now references this evidence record.');
      setLinkTarget(null);
      setLinkCaseId('');
      refetchAll();
    } catch (err) {
      setLinkError(errMessage(err));
    } finally {
      setLinkBusy(false);
    }
  };

  const [unlinkTarget, setUnlinkTarget] = useState<EvidenceRow | null>(null);
  const [unlinkBusyId, setUnlinkBusyId] = useState<string | null>(null);

  const onUnlink = async (caseId: string) => {
    if (!unlinkTarget) return;
    setUnlinkBusyId(caseId);
    try {
      await evidenceService.unlinkEvidence(unlinkTarget.id, { case_id: caseId });
      toast.success('Case link removed', 'The evidence record itself was kept.');
      setUnlinkTarget((prev) =>
        prev ? { ...prev, case_ids: prev.case_ids.filter((c) => c !== caseId) } : prev
      );
      refetchAll();
    } catch (err) {
      toast.error('Could not unlink', errMessage(err));
    } finally {
      setUnlinkBusyId(null);
    }
  };

  /* ---------------- delete ---------------- */
  const [deleteTarget, setDeleteTarget] = useState<EvidenceRow | null>(null);
  const [deleting, setDeleting] = useState(false);

  const onDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await evidenceService.deleteEvidence(deleteTarget.id);
      toast.success('Evidence deleted', `${evidenceName(deleteTarget)} was permanently removed.`);
      setDeleteTarget(null);
      setPreview((prev) => (prev && prev.id === deleteTarget.id ? null : prev));
      refetchAll();
    } catch (err) {
      toast.error('Could not delete evidence', errMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  /* ---------------- add evidence ---------------- */
  const [addOpen, setAddOpen] = useState(false);
  const [addTab, setAddTab] = useState('upload');
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  // upload tab
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [upKind, setUpKind] = useState('screenshot');
  const [upTitle, setUpTitle] = useState('');
  const [upDesc, setUpDesc] = useState('');
  const [upEntity, setUpEntity] = useState<EntityPick | null>(null);

  // manual tab
  const [manKind, setManKind] = useState('text');
  const [manTitle, setManTitle] = useState('');
  const [manDesc, setManDesc] = useState('');
  const [manText, setManText] = useState('');
  const [manUrl, setManUrl] = useState('');
  const [manEntity, setManEntity] = useState<EntityPick | null>(null);
  const [manCase, setManCase] = useState('');

  const manNeedsUrl = ['url', 'url_inspection', 'whois'].includes(manKind);

  const openAdd = () => {
    setAddTab('upload');
    setFieldErrors({});
    setFormError(null);
    setAddOpen(true);
  };

  const resetAdd = () => {
    setFile(null);
    setFileError(null);
    setUpKind('screenshot');
    setUpTitle('');
    setUpDesc('');
    setUpEntity(null);
    setManKind('text');
    setManTitle('');
    setManDesc('');
    setManText('');
    setManUrl('');
    setManEntity(null);
    setManCase('');
    setFieldErrors({});
    setFormError(null);
  };

  const closeAdd = () => {
    if (submitting) return;
    setAddOpen(false);
    resetAdd();
  };

  const handleFile = (f: File | null) => {
    setFieldErrors({});
    setFormError(null);
    if (!f) {
      setFile(null);
      setFileError(null);
      return;
    }
    const err = validateUploadFile(f);
    setFile(f);
    setFileError(err);
    if (!err) setUpTitle((t) => t || f.name);
  };

  const submitUpload = async () => {
    const errors: Record<string, string> = {};
    const fileErr = validateUploadFile(file);
    if (fileErr) errors.file = fileErr;
    if (!upEntity) errors.entity_id = 'Select the entity this evidence belongs to';
    if (!upTitle.trim()) errors.title = 'A title is required';
    setFileError(fileErr);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormError(null);
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const form = new FormData();
      form.append('file', file as File);
      form.append('entity_id', (upEntity as EntityPick).id);
      form.append('title', upTitle.trim());
      if (upDesc.trim()) form.append('description', upDesc.trim());
      form.append('kind', upKind);
      form.append('provenance', 'manual');
      await apiRequest<unknown>('/evidence/upload', { method: 'POST', body: form });
      toast.success(
        'Evidence uploaded',
        'The SHA-256 hash was computed server-side on the stored bytes and the record starts as verified.'
      );
      setAddOpen(false);
      resetAdd();
      refetchAll();
    } catch (err) {
      const { fields, message } = readApiError(err);
      if (Object.keys(fields).length > 0) setFieldErrors(fields);
      else setFormError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const submitManual = async () => {
    const errors: Record<string, string> = {};
    if (!manKind) errors.kind = 'Choose an evidence type';
    if (!manTitle.trim()) errors.title = 'A title is required';
    if (!manDesc.trim()) errors.description = 'A description is required';
    if (!manEntity) errors.entity_id = 'Select the entity this evidence belongs to';
    if (manNeedsUrl && !manUrl.trim()) errors.source_url = 'A URL is required for this type';
    if (!manNeedsUrl && !manText.trim()) errors.text_content = 'Text content is required for this type';
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setFormError(null);
      return;
    }
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const payload: Record<string, unknown> = {
        entity_id: (manEntity as EntityPick).id,
        kind: manKind,
        title: manTitle.trim(),
        description: manDesc.trim(),
      };
      if (manNeedsUrl) payload.source_url = manUrl.trim();
      else payload.text_content = manText;
      const created = await apiRequest<{ id: string }>('/evidence', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (manCase) {
        await evidenceService.linkEvidence(created.id, { case_id: manCase });
      }
      toast.success(
        'Evidence recorded',
        manCase ? 'The record was created and linked to the selected case.' : 'The record was added to the evidence pool.'
      );
      setAddOpen(false);
      resetAdd();
      refetchAll();
    } catch (err) {
      const { fields, message } = readApiError(err);
      if (Object.keys(fields).length > 0) setFieldErrors(fields);
      else setFormError(message);
    } finally {
      setSubmitting(false);
    }
  };

  /* ---------------- table ---------------- */
  const onSortChange = (key: string) => {
    if (sort === key) setParams({ sort: key, order: order === 'asc' ? 'desc' : 'asc' });
    else setParams({ sort: key, order: 'desc' });
  };

  const rowActions = (row: EvidenceRow): DropdownItem[] => {
    const items: DropdownItem[] = [
      { label: 'Preview', icon: <Eye className="h-3.5 w-3.5" />, onClick: () => setPreview(row) },
    ];
    if (row.has_file) {
      items.push({ label: 'Download', icon: <Download className="h-3.5 w-3.5" />, onClick: () => void onDownload(row) });
    } else {
      items.push({ label: 'Download (no file)', icon: <Download className="h-3.5 w-3.5" />, disabled: true });
    }
    if (canWrite) {
      const rehashable = !!row.has_file || !!row.text_content;
      items.push(
        rehashable
          ? {
              label: verifyingId === row.id ? 'Verifying…' : 'Verify now',
              icon: <ShieldCheck className="h-3.5 w-3.5" />,
              onClick: () => void onVerify(row),
              disabled: verifyingId === row.id,
            }
          : { label: 'Verify now (no re-hashable content)', icon: <ShieldCheck className="h-3.5 w-3.5" />, disabled: true }
      );
      items.push({
        label: 'Link to case',
        icon: <Link2 className="h-3.5 w-3.5" />,
        onClick: () => {
          setLinkTarget(row);
          setLinkCaseId('');
          setLinkError(null);
        },
      });
      if (row.case_ids.length > 0) {
        items.push({
          label: 'Unlink from case',
          icon: <Unlink className="h-3.5 w-3.5" />,
          onClick: () => setUnlinkTarget(row),
        });
      }
      if (canDelete) {
        items.push({
          label: 'Delete',
          icon: <Trash2 className="h-3.5 w-3.5" />,
          danger: true,
          separatorBefore: true,
          onClick: () => setDeleteTarget(row),
        });
      }
    }
    return items;
  };

  const columns: Column<EvidenceRow>[] = [
    {
      key: 'name',
      header: 'Name',
      sortable: true,
      cell: (row) => {
        const meta = KIND_META[row.kind] || KIND_META.other;
        return (
          <div className="flex items-center gap-3">
            <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-xl', meta.chip)}>
              {meta.icon}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-bold text-ink">{evidenceName(row)}</p>
              <p className="truncate text-[11px] text-muted">
                {EVIDENCE_KIND_LABELS[row.kind] || row.kind}
                {row.file_name && row.title ? ` · ${row.title}` : ''}
              </p>
            </div>
          </div>
        );
      },
    },
    {
      key: 'kind',
      header: 'Type',
      cell: (row) => (
        <Badge tone={(KIND_META[row.kind] || KIND_META.other).tone}>
          {EVIDENCE_KIND_LABELS[row.kind] || row.kind}
        </Badge>
      ),
    },
    {
      key: 'case',
      header: 'Case',
      cell: (row) =>
        row.case_ids.length === 0 ? (
          <span className="text-faint">—</span>
        ) : (
          <span className="flex flex-wrap gap-1.5">
            {row.case_ids.map((cid) => {
              const c = caseMap.get(cid);
              return (
                <Link
                  key={cid}
                  to={`/cases/${cid}`}
                  onClick={(e) => e.stopPropagation()}
                  title={c ? `${c.case_number} — ${c.title}` : cid}
                  className="rounded-full border border-line bg-white px-2 py-0.5 text-[11px] font-semibold text-ink-700 transition-colors hover:border-brand-200 hover:text-brand-700 focus-ring"
                >
                  {c ? c.case_number : `#${cid.slice(0, 8)}`}
                </Link>
              );
            })}
          </span>
        ),
    },
    {
      key: 'entity',
      header: 'Entity',
      cell: (row) =>
        row.entity ? (
          <Link
            to={`/entities/${row.entity.id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-[13px] text-brand-600 hover:underline"
          >
            {row.entity.display_name}
          </Link>
        ) : (
          <span className="text-faint">—</span>
        ),
    },
    {
      key: 'created_at',
      header: 'Date',
      sortable: true,
      cell: (row) => (
        <Tooltip content={formatDate(row.created_at)}>
          <span className="text-[13px]">{formatRelativeTime(row.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => (
        <Badge tone={VERIF_TONE[row.verification_status] || 'default'}>
          {row.verification_status === 'verified' && <Check className="h-3 w-3" />}
          {row.verification_status === 'mismatch' && <AlertTriangle className="h-3 w-3" />}
          {VERIFICATION_LABELS[row.verification_status] || row.verification_status}
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
                aria-label={`Actions for ${evidenceName(row)}`}
                aria-haspopup="menu"
                aria-expanded={open}
                className="rounded-lg px-2.5 py-1.5 text-[13px] font-bold text-muted transition-colors hover:bg-line-soft hover:text-ink focus-ring"
              >
                ⋯
              </button>
            )}
            items={rowActions(row)}
          />
        </div>
      ),
    },
  ];

  /* ---------------- preview body ---------------- */
  const previewBody = (row: EvidenceRow) => {
    if (previewIsImage) {
      return (
        <div className="flex min-h-[180px] items-center justify-center rounded-2xl border border-line-soft bg-bg p-3">
          {imgLoading ? (
            <span className="flex items-center gap-2 text-[13px] text-muted">
              <span className="block h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-500" />
              Loading preview…
            </span>
          ) : imgError || !imgSrc ? (
            <div className="text-center">
              <p className="text-[13px] font-semibold text-ink">Preview unavailable</p>
              <p className="mt-1 max-w-sm text-[12px] text-muted">
                The stored file could not be loaded in the browser. Use Download to retrieve the original bytes.
              </p>
            </div>
          ) : (
            <img
              src={imgSrc}
              alt={evidenceName(row)}
              className="max-h-[42vh] rounded-xl border border-line bg-white object-contain"
            />
          )}
        </div>
      );
    }

    const text = row.text_content || prettyJson(row.metadata);
    const isUrlKind = ['url', 'url_inspection', 'whois'].includes(row.kind);

    if (!text && row.has_file) {
      return (
        <div className="rounded-2xl border border-line-soft bg-bg p-4 text-[13px] text-muted">
          <p className="font-semibold text-ink">Binary attachment</p>
          <p className="mt-1">
            No text content is stored for this record. Download the file to inspect its contents.
          </p>
        </div>
      );
    }

    return (
      <div className="space-y-3">
        {isUrlKind && row.source_url && (
          <a
            href={row.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex max-w-full items-center gap-1.5 rounded-xl border border-line bg-bg px-3 py-2 text-[13px] text-brand-600 hover:underline"
          >
            <Link2 className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{row.source_url}</span>
          </a>
        )}
        <pre className="max-h-[38vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line-soft bg-bg p-3.5 font-mono text-[12px] leading-relaxed text-ink-700">
          {text || 'No text content stored for this record.'}
        </pre>
      </div>
    );
  };

  const previewMeta = (row: EvidenceRow) => (
    <dl className="grid gap-x-6 sm:grid-cols-2">
      <KeyValue
        label="SHA-256"
        value={
          row.sha256 ? (
            <span className="inline-flex max-w-full items-center gap-1">
              <code className="break-all font-mono text-[11px]">{row.sha256}</code>
              <CopyButton text={row.sha256} label="Copy SHA-256" />
            </span>
          ) : (
            <span className="text-faint">—</span>
          )
        }
      />
      <KeyValue label="Perceptual hash" value={row.perceptual_hash ? <code className="font-mono text-[12px]">{row.perceptual_hash}</code> : <span className="text-faint">—</span>} />
      <KeyValue label="MIME type" value={row.content_type || <span className="text-faint">—</span>} />
      <KeyValue label="Size" value={formatSize(row.size_bytes)} />
      <KeyValue label="Created" value={formatDate(row.created_at)} />
      <KeyValue
        label="Evidence ID"
        value={
          <span className="inline-flex items-center gap-1">
            <code className="font-mono text-[12px]">{row.id}</code>
            <CopyButton text={row.id} label="Copy evidence id" />
          </span>
        }
      />
      <KeyValue
        label="Source entity"
        value={
          row.entity ? (
            <Link to={`/entities/${row.entity.id}`} className="text-brand-600 hover:underline">
              {row.entity.display_name}
            </Link>
          ) : (
            <span className="text-faint">—</span>
          )
        }
      />
      <KeyValue
        label="Linked cases"
        value={
          row.case_ids.length === 0 ? (
            <span className="text-faint">—</span>
          ) : (
            <span className="flex flex-wrap gap-1.5">
              {row.case_ids.map((cid) => {
                const c = caseMap.get(cid);
                return (
                  <Link
                    key={cid}
                    to={`/cases/${cid}`}
                    className="rounded-full border border-line bg-white px-2 py-0.5 text-[11px] font-semibold text-ink-700 hover:border-brand-200 hover:text-brand-700"
                  >
                    {c ? c.case_number : `#${cid.slice(0, 8)}`}
                  </Link>
                );
              })}
            </span>
          )
        }
      />
      <KeyValue
        label="Provenance"
        value={row.provenance ? <ProvenanceBadge provenance={row.provenance} /> : <span className="text-faint">—</span>}
      />
      <KeyValue
        label="Verification"
        value={
          <Badge tone={VERIF_TONE[row.verification_status] || 'default'}>
            {VERIFICATION_LABELS[row.verification_status] || row.verification_status}
          </Badge>
        }
      />
    </dl>
  );

  /* ---------------- render ---------------- */
  const caseOptions = caseItems.map((c) => ({ value: c.id, label: `${c.case_number} — ${c.title}` }));

  return (
    <div>
      <PageHeader
        title="Evidence Center"
        description="View and manage collected evidence."
        actions={
          <>
            <Button variant="outline" onClick={() => void onExport()}>
              Export CSV
            </Button>
            {canWrite && (
              <Button icon={<Plus className="h-4 w-4" />} onClick={openAdd}>
                Add Evidence
              </Button>
            )}
          </>
        }
      >
        <Tabs
          items={CHIP_ITEMS}
          value={chip}
          onChange={(id) => setParams({ chip: id === 'all' ? null : id, type: null })}
        />
      </PageHeader>

      {/* Toolbar */}
      <Card className="mb-4">
        <div className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-2">
            <SearchInput
              value={q}
              onChange={(v) => setParams({ q: v })}
              placeholder="Search file name or description…"
              className="w-full sm:w-72"
              debounceMs={350}
            />
            <FilterSelect
              label="Evidence type"
              value={typeFilter}
              onChange={(v) => setParams({ type: v, chip: null })}
              options={Object.entries(EVIDENCE_KIND_LABELS).map(([value, label]) => ({ value, label }))}
              allLabel="All types"
            />
            <FilterSelect
              label="Case"
              value={caseId}
              onChange={(v) => setParams({ case: v })}
              options={caseOptions}
              allLabel={casesQuery.isPending ? 'Loading cases…' : 'All cases'}
            />
            <FilterSelect
              label="Verification"
              value={verif}
              onChange={(v) => setParams({ verif: v })}
              options={[
                { value: 'verified', label: 'Verified' },
                { value: 'pending', label: 'Pending' },
                { value: 'mismatch', label: 'Mismatch' },
              ]}
              allLabel="Any status"
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
          <div className="flex shrink-0 items-center gap-2 text-[12px] text-muted">
            <span className="font-semibold text-ink-700">Showing:</span>
            {typeFilter
              ? EVIDENCE_KIND_LABELS[typeFilter] || typeFilter
              : chip === 'all'
                ? 'all evidence types'
                : (CHIP_ITEMS.find((c) => c.id === chip)?.label || 'all evidence types').toLowerCase()}
          </div>
        </div>

        {entityId && (
          <div className="flex items-center justify-between gap-2 border-t border-line-soft px-4 py-2.5">
            <span className="inline-flex min-w-0 items-center gap-2 text-[12px] text-muted">
              <span className="font-semibold text-ink-700">Scoped to entity:</span>
              <span className="truncate">
                {entityQuery.isPending
                  ? 'loading…'
                  : entityQuery.data?.display_name || entityId}
              </span>
            </span>
            <button
              onClick={() => setParams({ entity_id: null })}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-semibold text-muted hover:text-ink focus-ring"
            >
              <X className="h-3.5 w-3.5" /> Remove filter
            </button>
          </div>
        )}
      </Card>

      {normalized?.truncated && (
        <p className="mb-3 rounded-xl border border-line bg-white px-3.5 py-2.5 text-[12px] text-muted">
          <span className="font-semibold text-ink-700">Limited view:</span> the API returns at most 100 records per
          type for grouped type filters, so some older records are not listed here. Narrow the search for complete,
          page-level results.
        </p>
      )}

      {/* Table */}
      <Card>
        {listIsError ? (
          <div className="px-5 py-10">
            <ErrorState
              title="Could not load evidence"
              message={errMessage(listError)}
              onRetry={refetchList}
            />
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
              onRowClick={(r) => setPreview(r)}
              loading={listIsPending}
              emptyState={
                hasFilters ? (
                  <EmptyState
                    icon={<Search className="h-6 w-6" />}
                    title="No evidence matches"
                    description="No record matches the current search, type and verification filters."
                    action={
                      <Button variant="outline" size="sm" onClick={clearFilters}>
                        Clear filters
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    icon={<FileSearch className="h-6 w-6" />}
                    title="No evidence yet"
                    description="Upload an image or record text, URL or WHOIS evidence against an entity."
                    action={
                      canWrite ? (
                        <Button icon={<Plus className="h-4 w-4" />} onClick={openAdd}>
                          Add Evidence
                        </Button>
                      ) : undefined
                    }
                  />
                )
              }
            />
            <Pagination
              page={page}
              pages={normalized?.pages ?? 1}
              total={normalized?.total ?? 0}
              onPageChange={(p) => setParams({ page: String(p) })}
              pageSize={pageSize}
              onPageSizeChange={(s) => setParams({ page_size: String(s) })}
            />
          </>
        )}
      </Card>

      {/* ---------------- Preview modal ---------------- */}
      <Modal
        open={!!preview}
        onClose={() => setPreview(null)}
        size="lg"
        title={preview ? evidenceName(preview) : undefined}
        description={
          preview
            ? `${EVIDENCE_KIND_LABELS[preview.kind] || preview.kind} · ${formatDate(preview.created_at)}`
            : undefined
        }
        footer={
          preview ? (
            <>
              <Button variant="outline" onClick={() => setPreview(null)}>
                Close
              </Button>
              {preview.has_file && (
                <Button
                  variant="outline"
                  icon={<Download className="h-4 w-4" />}
                  onClick={() => void onDownload(preview)}
                >
                  Download
                </Button>
              )}
              {canWrite &&
                (preview.has_file || preview.text_content ? (
                  <Button
                    icon={<ShieldCheck className="h-4 w-4" />}
                    loading={verifyingId === preview.id}
                    onClick={() => void onVerify(preview)}
                  >
                    Verify now
                  </Button>
                ) : null)}
            </>
          ) : null
        }
      >
        {preview && (
          <div className="space-y-5">
            {previewBody(preview)}
            <div className="border-t border-line-soft pt-1">{previewMeta(preview)}</div>
          </div>
        )}
      </Modal>

      {/* ---------------- Verify result modal ---------------- */}
      <Modal
        open={!!verifyResult}
        onClose={() => setVerifyResult(null)}
        size="md"
        title="Verification result"
        description={verifyResult ? `Checked ${formatDate(verifyResult.verified_at)}` : undefined}
        footer={
          <Button variant="outline" onClick={() => setVerifyResult(null)}>
            Close
          </Button>
        }
      >
        {verifyResult && (
          <div className="space-y-4">
            <div
              className={cn(
                'flex items-start gap-3 rounded-2xl border px-4 py-3.5',
                verifyResult.matches
                  ? 'border-success-100 bg-success-100'
                  : 'border-danger-100 bg-danger-100'
              )}
            >
              <span className={verifyResult.matches ? 'text-success' : 'text-danger'}>
                {verifyResult.matches ? (
                  <CheckCircle2 className="h-5 w-5" />
                ) : (
                  <AlertTriangle className="h-5 w-5" />
                )}
              </span>
              <div>
                <p className={cn('text-[14px] font-bold', verifyResult.matches ? 'text-success-600' : 'text-danger-600')}>
                  {verifyResult.matches ? 'Hash matches — evidence unchanged' : 'Hash mismatch — stored bytes differ'}
                </p>
                <p className="mt-0.5 text-[12px] text-muted">
                  {verifyResult.matches
                    ? 'The SHA-256 recomputed from the stored content equals the recorded hash.'
                    : 'The SHA-256 recomputed from the stored content does not equal the recorded hash. Treat this record as tampered or corrupted.'}
                </p>
              </div>
            </div>
            <dl className="grid gap-x-6">
              <KeyValue
                label="Computed SHA-256"
                value={
                  verifyResult.sha256 ? (
                    <span className="inline-flex max-w-full items-center gap-1">
                      <code className="break-all font-mono text-[11px]">{verifyResult.sha256}</code>
                      <CopyButton text={verifyResult.sha256} label="Copy computed hash" />
                    </span>
                  ) : (
                    <span className="text-faint">—</span>
                  )
                }
              />
              <KeyValue
                label="Stored SHA-256"
                value={
                  verifyResult.stored_sha256 ? (
                    <span className="inline-flex max-w-full items-center gap-1">
                      <code className="break-all font-mono text-[11px]">{verifyResult.stored_sha256}</code>
                      <CopyButton text={verifyResult.stored_sha256} label="Copy stored hash" />
                    </span>
                  ) : (
                    <span className="text-faint">—</span>
                  )
                }
              />
              <KeyValue label="Verified at" value={formatDate(verifyResult.verified_at)} />
            </dl>
          </div>
        )}
      </Modal>

      {/* ---------------- Link to case modal ---------------- */}
      <Modal
        open={!!linkTarget}
        onClose={() => !linkBusy && setLinkTarget(null)}
        size="md"
        title="Link evidence to a case"
        description={linkTarget ? evidenceName(linkTarget) : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setLinkTarget(null)} disabled={linkBusy}>
              Cancel
            </Button>
            <Button onClick={() => void onLink()} loading={linkBusy} disabled={!linkCaseId}>
              Link
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {linkError && (
            <div className="rounded-xl border border-danger-100 bg-danger-100 px-3.5 py-2.5 text-[13px] font-medium text-danger-600">
              {linkError}
            </div>
          )}
          <Field label="Case" required htmlFor="link-case" hint="Only cases in your workspace are listed.">
            <Select id="link-case" value={linkCaseId} onChange={(e) => setLinkCaseId(e.target.value)}>
              <option value="">Select a case…</option>
              {caseOptions.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
          {caseItems.length === 0 && (
            <p className="text-[13px] text-muted">No cases are available yet — create a case first.</p>
          )}
        </div>
      </Modal>

      {/* ---------------- Unlink modal ---------------- */}
      <Modal
        open={!!unlinkTarget}
        onClose={() => setUnlinkTarget(null)}
        size="md"
        title="Unlink from cases"
        description={unlinkTarget ? evidenceName(unlinkTarget) : undefined}
        footer={
          <Button variant="outline" onClick={() => setUnlinkTarget(null)}>
            Close
          </Button>
        }
      >
        {unlinkTarget && (
          <div className="space-y-2">
            {unlinkTarget.case_ids.length === 0 ? (
              <p className="text-[13px] text-muted">This record is not linked to any case.</p>
            ) : (
              unlinkTarget.case_ids.map((cid) => {
                const c = caseMap.get(cid);
                return (
                  <div
                    key={cid}
                    className="flex items-center justify-between gap-3 rounded-xl border border-line-soft px-3.5 py-2.5"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-semibold text-ink">
                        {c ? `${c.case_number} — ${c.title}` : `#${cid.slice(0, 8)}`}
                      </span>
                      <span className="block text-[11px] text-muted">Linked case</span>
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={unlinkBusyId === cid}
                      onClick={() => void onUnlink(cid)}
                    >
                      Unlink
                    </Button>
                  </div>
                );
              })
            )}
            <p className="pt-1 text-[12px] text-muted">
              Unlinking removes the case reference only — the evidence record and its stored file are kept.
            </p>
          </div>
        )}
      </Modal>

      {/* ---------------- Delete confirmation ---------------- */}
      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={onDelete}
        loading={deleting}
        destructive
        confirmLabel="Delete evidence"
        title="Delete this evidence?"
        message={
          deleteTarget ? (
            <>
              <span className="font-semibold text-ink">{evidenceName(deleteTarget)}</span> will be permanently removed
              together with its stored file and case links. This cannot be undone.
            </>
          ) : (
            ''
          )
        }
      />

      {/* ---------------- Add evidence modal ---------------- */}
      <Modal
        open={addOpen}
        onClose={closeAdd}
        size="lg"
        title="Add evidence"
        description="Attachments are hashed server-side; manual records store exactly what you submit."
        footer={
          <>
            <Button variant="outline" onClick={closeAdd} disabled={submitting}>
              Cancel
            </Button>
            <Button
              onClick={() => void (addTab === 'upload' ? submitUpload() : submitManual())}
              loading={submitting}
            >
              {addTab === 'upload' ? 'Upload evidence' : 'Create record'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Tabs
            items={[
              { id: 'upload', label: 'Upload', icon: <Upload className="h-3.5 w-3.5" /> },
              { id: 'manual', label: 'Manual record', icon: <FileText className="h-3.5 w-3.5" /> },
            ]}
            value={addTab}
            onChange={(id) => {
              setAddTab(id);
              setFieldErrors({});
              setFormError(null);
            }}
          />

          {formError && (
            <div className="rounded-xl border border-danger-100 bg-danger-100 px-3.5 py-2.5 text-[13px] font-medium text-danger-600">
              {formError}
            </div>
          )}

          {addTab === 'upload' ? (
            <div className="space-y-4">
              <Field
                label="File"
                required
                error={fieldErrors.file || fileError}
                hint="PNG, JPEG, WEBP or GIF · max 5 MB. The server re-validates the real image content."
              >
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    handleFile(e.dataTransfer.files?.[0] || null);
                  }}
                  className={cn(
                    'flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-7 text-center transition-colors',
                    dragging ? 'border-brand-400 bg-brand-50' : 'border-line bg-bg',
                    (fieldErrors.file || fileError) && 'border-danger-500'
                  )}
                >
                  <input
                    id="ev-file"
                    type="file"
                    className="sr-only"
                    accept=".png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif"
                    onChange={(e) => handleFile(e.target.files?.[0] || null)}
                  />
                  <label
                    htmlFor="ev-file"
                    className="cursor-pointer text-[13px] font-semibold text-brand-600 hover:text-brand-700"
                  >
                    {file ? 'Choose a different file' : 'Click to select a file'}
                    <span className="block text-[12px] font-normal text-muted">or drop it here</span>
                  </label>
                  {file && (
                    <div className="mt-3 w-full max-w-md rounded-xl border border-line bg-white px-3 py-2 text-left">
                      <p className="truncate text-[13px] font-semibold text-ink">{file.name}</p>
                      <p className="text-[11px] text-muted">
                        {formatSize(file.size)} · {file.type || 'unknown type'}
                      </p>
                    </div>
                  )}
                </div>
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Kind" required htmlFor="up-kind">
                  <Select id="up-kind" value={upKind} onChange={(e) => setUpKind(e.target.value)}>
                    {UPLOAD_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {EVIDENCE_KIND_LABELS[k]}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field
                  label="Title"
                  required
                  htmlFor="up-title"
                  error={fieldErrors.title}
                  hint="Shown in the evidence list."
                >
                  <Input
                    id="up-title"
                    value={upTitle}
                    onChange={(e) => setUpTitle(e.target.value)}
                    placeholder="Screenshot of fake login page"
                    className={cn(fieldErrors.title && 'border-danger')}
                  />
                </Field>
              </div>

              <Field label="Description" htmlFor="up-desc" error={fieldErrors.description} hint="Optional context for investigators.">
                <Textarea
                  id="up-desc"
                  value={upDesc}
                  onChange={(e) => setUpDesc(e.target.value)}
                  placeholder="What this file shows and where it came from"
                  className="min-h-[70px]"
                />
              </Field>

              <EntityPicker
                id="up-entity"
                label="Linked entity"
                required
                value={upEntity}
                onChange={setUpEntity}
                error={fieldErrors.entity_id}
                hint="The API requires evidence to belong to an entity."
              />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Kind"
                  required
                  htmlFor="man-kind"
                  error={fieldErrors.kind}
                  hint="Image kinds (Screenshot / Image) are handled by the Upload tab."
                >
                  <Select id="man-kind" value={manKind} onChange={(e) => setManKind(e.target.value)}>
                    {MANUAL_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {EVIDENCE_KIND_LABELS[k]}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Title" required htmlFor="man-title" error={fieldErrors.title}>
                  <Input
                    id="man-title"
                    value={manTitle}
                    onChange={(e) => setManTitle(e.target.value)}
                    placeholder="WHOIS for suspicious-domain.example"
                    className={cn(fieldErrors.title && 'border-danger')}
                  />
                </Field>
              </div>

              <Field
                label="Description"
                required
                htmlFor="man-desc"
                error={fieldErrors.description}
                hint="Required — say what this record proves."
              >
                <Textarea
                  id="man-desc"
                  value={manDesc}
                  onChange={(e) => setManDesc(e.target.value)}
                  placeholder="Why this evidence matters"
                  className={cn('min-h-[70px]', fieldErrors.description && 'border-danger')}
                />
              </Field>

              {manNeedsUrl ? (
                <Field
                  label="URL"
                  required
                  htmlFor="man-url"
                  error={fieldErrors.source_url}
                  hint="The URL this record documents."
                >
                  <Input
                    id="man-url"
                    type="url"
                    value={manUrl}
                    onChange={(e) => setManUrl(e.target.value)}
                    placeholder="https://suspicious-domain.example/login"
                    className={cn('font-mono text-[13px]', fieldErrors.source_url && 'border-danger')}
                  />
                </Field>
              ) : (
                <Field
                  label="Text content"
                  required
                  htmlFor="man-text"
                  error={fieldErrors.text_content}
                  hint="Stored verbatim; its SHA-256 is computed by the server."
                >
                  <Textarea
                    id="man-text"
                    value={manText}
                    onChange={(e) => setManText(e.target.value)}
                    placeholder="Paste the captured content…"
                    className={cn('min-h-[110px] font-mono text-[12px]', fieldErrors.text_content && 'border-danger')}
                  />
                </Field>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <EntityPicker
                  id="man-entity"
                  label="Linked entity"
                  required
                  value={manEntity}
                  onChange={setManEntity}
                  error={fieldErrors.entity_id}
                  hint="The API requires evidence to belong to an entity."
                />
                <Field label="Link to case" htmlFor="man-case" hint="Optional — links immediately after creation.">
                  <Select id="man-case" value={manCase} onChange={(e) => setManCase(e.target.value)}>
                    <option value="">No case</option>
                    {caseOptions.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
};

export default EvidencePage;
