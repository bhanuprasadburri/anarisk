import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import '@xyflow/react/dist/style.css';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react';
import {
  ArrowLeft,
  AtSign,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Flag,
  Globe,
  History as HistoryIcon,
  Image as ImageIcon,
  Layers,
  Link2,
  MessageSquare,
  MoreHorizontal,
  Network,
  Pencil,
  Plus,
  Smartphone,
  Trash2,
  Upload,
  UserPlus,
  X,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge, CaseStatusBadge, SeverityBadge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Field, Input, Select, Textarea } from '../components/ui/input';
import { ConfirmDialog, Modal } from '../components/ui/modal';
import { Dropdown, Tabs, type TabItem } from '../components/ui/tabs';
import { EmptyState, ErrorState } from '../components/ui/table';
import { Avatar, CopyButton, LoadingBlock, SearchInput, Tooltip } from '../components/ui/misc';
import { ScoreBar, ScoreRing, severityColor } from '../components/ui/score';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { caseService, type TakedownReportDraft } from '../services/caseService';
import { entityService } from '../services/entityService';
import { evidenceService } from '../services/evidenceService';
import { ApiError, apiRequest } from '../services/apiClient';
import {
  CASE_STATUS_LABELS,
  ENTITY_TYPE_COLORS,
  ENTITY_TYPE_LABELS,
  EVIDENCE_KIND_LABELS,
  PLATFORM_LABELS,
  RELATIONSHIP_COLORS,
  RELATIONSHIP_LABELS,
  RESOLUTION_OUTCOME_LABELS,
  SEVERITY_LABELS,
  VERIFICATION_LABELS,
} from '../lib/constants';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';
import {
  CaseNote,
  CaseStatus,
  DigitalEntity,
  InvestigationCase,
  ResolutionOutcome,
} from '../types';

/* ------------------------------------------------------------------ *
 * Types & helpers
 * ------------------------------------------------------------------ */

interface EvidenceItem {
  id: string;
  entity_id?: string | null;
  kind: string;
  title?: string | null;
  description?: string | null;
  source_url?: string | null;
  sha256?: string | null;
  size_bytes?: number | null;
  has_file?: boolean;
  file_name?: string | null;
  text_content?: string | null;
  verification_status?: 'verified' | 'pending' | 'mismatch';
  created_at: string;
  role?: string;
  entity?: { id: string; display_name: string; entity_type: string } | null;
}

interface CaseDetail extends InvestigationCase {
  evidence?: EvidenceItem[];
}

interface Perms {
  triage: boolean;
  assign: boolean;
  escalate: boolean;
  resolve: boolean;
  note: boolean;
  create: boolean;
  evidenceWrite: boolean;
  graphRead: boolean;
  entityRead: boolean;
  remove: boolean;
}

const errMsg = (e: unknown, fallback: string): string =>
  e instanceof ApiError ? e.message : fallback;

const statusLabel = (s: string): string => CASE_STATUS_LABELS[s] || s.replace(/_/g, ' ');

const EVENT_META: Record<string, { label: string; dot: string }> = {
  created: { label: 'Case created', dot: 'bg-brand-500' },
  status_changed: { label: 'Status changed', dot: 'bg-violet-500' },
  assigned: { label: 'Owner assigned', dot: 'bg-brand-500' },
  reassigned: { label: 'Owner reassigned', dot: 'bg-warning' },
  note_added: { label: 'Note added', dot: 'bg-cyanx-500' },
  escalated: { label: 'Escalated to partner', dot: 'bg-danger' },
  resolved: { label: 'Case resolved', dot: 'bg-success' },
  reopened: { label: 'Case reopened', dot: 'bg-warning' },
  entity_added: { label: 'Entity linked', dot: 'bg-info' },
  entity_removed: { label: 'Entity unlinked', dot: 'bg-faint' },
};

const ENTITY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  social_profile: AtSign,
  website: Globe,
  domain: Globe,
  image: ImageIcon,
  mobile_app: Smartphone,
};

const typeChipStyle = (entityType: string): React.CSSProperties => {
  const c = ENTITY_TYPE_COLORS[entityType] || '#4778F5';
  return { backgroundColor: `${c}1F`, color: c };
};

/** Client-side permission view. Mirrors the API matrix; `hasPermission` from useAuth is
 *  authoritative for everything it covers, the role checks fill the known gaps. */
const usePerms = (): Perms => {
  const { hasPermission, role } = useAuth();
  return useMemo(
    () => ({
      triage: hasPermission('case:triage'),
      assign: hasPermission('case:assign'),
      escalate: hasPermission('case:escalate'),
      resolve: hasPermission('case:resolve'),
      note: hasPermission('case:note') || role === 'brand_owner', // brand owners may add notes
      create: hasPermission('case:create'),
      evidenceWrite: hasPermission('evidence:write') || role === 'brand_owner',
      graphRead: hasPermission('graph:read'),
      entityRead: hasPermission('entity:read'),
      remove: role === 'administrator',
    }),
    [hasPermission, role]
  );
};

/* ------------------------------------------------------------------ *
 * Graph (React Flow)
 * ------------------------------------------------------------------ */

type GraphNodeData = {
  label: string;
  severity: string;
  risk: number | null;
  inCase: boolean;
};
type CaseFlowNode = Node<GraphNodeData, 'caseEntity'>;

const CaseGraphNode: React.FC<NodeProps<CaseFlowNode>> = ({ data }) => (
  <div
    className={cn(
      'nn-node flex h-[104px] w-[104px] cursor-pointer flex-col items-center justify-center rounded-full border-2 bg-white px-2 text-center shadow-card transition-transform hover:scale-105',
      data.inCase && 'ring-2 ring-brand-400 ring-offset-2'
    )}
    style={{ borderColor: severityColor(data.severity) }}
    title={`${data.label} — risk ${data.risk === null ? 'n/a' : data.risk.toFixed(2)}`}
  >
    <span className="line-clamp-2 text-[10.5px] font-bold leading-tight text-ink">{data.label}</span>
    <span className="mt-1.5 flex items-center gap-1">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: severityColor(data.severity) }}
        aria-hidden
      />
      <span className="text-[9.5px] font-bold tabular-nums text-muted">
        {data.risk === null ? '—' : data.risk.toFixed(2)}
      </span>
    </span>
    <Handle type="target" position={Position.Left} className="!h-2 !w-2" />
    <Handle type="source" position={Position.Right} className="!h-2 !w-2" />
  </div>
);

const NODE_TYPES: NodeTypes = { caseEntity: CaseGraphNode };

const ringRadius = (count: number, min: number): number =>
  Math.max(min, (count * 118) / (2 * Math.PI));

interface GraphTabProps {
  data: CaseDetail;
  canRead: boolean;
}

const GraphTab: React.FC<GraphTabProps> = ({ data, canRead }) => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [flow, setFlow] = useState<{ nodes: CaseFlowNode[]; edges: Edge[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entities = data.entities || [];
  const primary = entities[0]?.entity;

  const load = useCallback(async () => {
    if (!primary) return;
    setLoading(true);
    setError(null);
    try {
      // Server-composed case sub-graph: linked entities + relationships among them
      const res = await caseService.getCaseGraph(data.id);
      const caseIds = new Set(entities.map((e) => e.entity.id));

      // BFS depth from the primary entity for a simple radial layout
      const dist: Record<string, number> = { [primary.id]: 0 };
      let frontier = [primary.id];
      while (frontier.length > 0) {
        const next: string[] = [];
        for (const e of res.edges) {
          for (const [a, b] of [
            [e.source, e.target],
            [e.target, e.source],
          ] as Array<[string, string]>) {
            if (dist[a] !== undefined && dist[b] === undefined) {
              dist[b] = dist[a] + 1;
              next.push(b);
            }
          }
        }
        frontier = next;
      }

      const ring1 = res.nodes.filter((n) => dist[n.id] === 1);
      const ring2 = res.nodes.filter((n) => dist[n.id] === undefined || dist[n.id] > 1);
      const r1 = ringRadius(ring1.length, 170);
      const r2 = r1 + ringRadius(ring2.length, 150) + 40;

      const nodes: CaseFlowNode[] = res.nodes.map((n) => {
        const d = dist[n.id];
        let x = 0;
        let y = 0;
        if (d === 1) {
          const i = ring1.findIndex((r) => r.id === n.id);
          const a = (i / Math.max(ring1.length, 1)) * 2 * Math.PI - Math.PI / 2;
          x = r1 * Math.cos(a);
          y = r1 * Math.sin(a);
        } else if (d === undefined || d > 1) {
          // ring 2: second-degree links AND isolated case entities (no relationships yet)
          const i = ring2.findIndex((r) => r.id === n.id);
          const a = (i / Math.max(ring2.length, 1)) * 2 * Math.PI - Math.PI / 2;
          x = r2 * Math.cos(a);
          y = r2 * Math.sin(a);
        }
        return {
          id: n.id,
          type: 'caseEntity',
          position: { x, y },
          data: {
            label: n.label,
            severity: n.severity,
            risk: n.risk_score,
            inCase: caseIds.has(n.id),
          },
        };
      });

      const edges: Edge[] = res.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'default',
        style: { stroke: RELATIONSHIP_COLORS[e.relationship_type] || '#94A3B8', strokeWidth: 1.8 },
      }));

      setFlow({ nodes, edges });
    } catch (e) {
      setError(errMsg(e, 'Could not load relationships for this case.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.id, primary?.id, entities.length]);

  useEffect(() => {
    if (canRead && primary) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canRead, data.id, primary?.id]);

  if (!canRead) {
    return (
      <EmptyState
        title="Risk graph not available for your role"
        description="Ask an administrator for graph access to explore relationships."
      />
    );
  }
  if (!primary) {
    return (
      <EmptyState
        title="No linked entities"
        description="Link an entity to this case to explore its relationship neighbourhood."
      />
    );
  }
  if (error) {
    return <ErrorState title="Could not load the graph" message={error} onRetry={() => void load()} />;
  }
  if (loading && !flow) return <LoadingBlock label="Loading relationships…" />;

  const usedRelationKeys: string[] = [];
  (flow?.edges ?? []).forEach((e) => {
    const stroke = (e.style as React.CSSProperties | undefined)?.stroke;
    const key = Object.keys(RELATIONSHIP_COLORS).find((k) => RELATIONSHIP_COLORS[k] === stroke);
    if (key && !usedRelationKeys.includes(key)) usedRelationKeys.push(key);
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">
          Neighbourhood of <span className="font-semibold text-ink">{primary.display_name}</span> (2 hops).
          Click a node to open the entity.
        </p>
        <Link
          to={`/risk-graph?focus=${primary.id}`}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-brand-600 hover:underline"
        >
          Open full Risk Graph <ExternalLink className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div
        className="h-[460px] w-full overflow-hidden rounded-2xl border border-line bg-[#f7faff]"
        role="region"
        aria-label="Case relationship graph"
      >
        <ReactFlow
          nodes={flow?.nodes ?? []}
          edges={flow?.edges ?? []}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.15}
          maxZoom={1.6}
          nodesDraggable
          nodesConnectable={false}
          zoomOnDoubleClick={false}
          onNodeClick={(_event, node) => navigate(`/entities/${node.id}`)}
        >
          <Background gap={18} color="#DCE6F5" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[11.5px] font-semibold text-muted">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-brand-400" /> ring = case entity
        </span>
        {(['critical', 'high', 'medium', 'low', 'unknown'] as const).map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: severityColor(s) }} />
            {SEVERITY_LABELS[s]}
          </span>
        ))}
        <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {usedRelationKeys.map((k) => (
            <span key={k} className="flex items-center gap-1.5">
              <span
                className="h-0.5 w-5 rounded-full"
                style={{ backgroundColor: RELATIONSHIP_COLORS[k] }}
              />
              {RELATIONSHIP_LABELS[k]}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * Entities tab
 * ------------------------------------------------------------------ */

interface EntitiesTabProps {
  data: CaseDetail;
  canLink: boolean;
  canOpenEntities: boolean;
  onLinked: (updated: CaseDetail) => void;
}

const EntitiesTab: React.FC<EntitiesTabProps> = ({ data, canLink, canOpenEntities, onLinked }) => {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<DigitalEntity[]>([]);
  const [searching, setSearching] = useState(false);
  const [linking, setLinking] = useState<string | null>(null);

  const entities = data.entities || [];
  const known = new Set(entities.map((e) => e.entity.id));
  const isResolved = data.status === 'resolved';

  useEffect(() => {
    if (!open) return;
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
  }, [query, open]);

  const link = async (entity: DigitalEntity) => {
    setLinking(entity.id);
    try {
      const updated = await apiRequest<CaseDetail>(`/cases/${data.id}/entities`, {
        method: 'POST',
        body: JSON.stringify([{ entity_id: entity.id, role: 'related' }]),
      });
      toast.success('Entity linked', entity.display_name);
      onLinked(updated);
      setOpen(false);
      setQuery('');
      setResults([]);
    } catch (e) {
      toast.error('Could not link entity', errMsg(e, 'The API rejected this request.'));
    } finally {
      setLinking(null);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">
          {entities.length} linked {entities.length === 1 ? 'entity' : 'entities'}
        </p>
        {canLink && !isResolved && (
          <Button size="sm" variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
            Link entity
          </Button>
        )}
      </div>

      {entities.length === 0 ? (
        <EmptyState
          title="No entities linked"
          description={
            canLink && !isResolved
              ? 'Link the assets this case is about to see their risk and evidence here.'
              : 'This case has no linked entities.'
          }
          action={
            canLink && !isResolved ? (
              <Button variant="outline" onClick={() => setOpen(true)}>
                Link entity
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-2.5">
          {entities.map((ce) => {
            const Icon = ENTITY_ICONS[ce.entity.entity_type] || FileText;
            const name = ce.entity.display_name;
            const inner = (
              <>
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
                  style={typeChipStyle(ce.entity.entity_type)}
                >
                  <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-bold text-ink">{name}</span>
                    <Badge tone={ce.role === 'subject' ? 'primary' : 'default'}>{ce.role}</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    {ENTITY_TYPE_LABELS[ce.entity.entity_type] || ce.entity.entity_type}
                    {ce.entity.platform ? ` · ${ce.entity.platform}` : ''} · {ce.evidence?.length || 0}{' '}
                    evidence
                  </p>
                </div>
                <div className="w-36 shrink-0">
                  <ScoreBar
                    value={ce.entity.current_risk_score}
                    severity={ce.entity.current_severity}
                  />
                </div>
                <SeverityBadge severity={ce.entity.current_severity} />
                {canOpenEntities ? (
                  <Link
                    to={`/entities/${ce.entity.id}`}
                    className="inline-flex h-8 shrink-0 items-center rounded-lg border border-line bg-white px-3 text-[13px] font-semibold text-ink-700 transition-colors hover:border-brand-200 hover:text-brand-700 focus-ring"
                  >
                    Open
                  </Link>
                ) : (
                  <span className="w-14" />
                )}
              </>
            );
            return canOpenEntities ? (
              <Link
                key={ce.entity.id}
                to={`/entities/${ce.entity.id}`}
                className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-white px-4 py-3 transition-colors hover:border-brand-200 hover:bg-bg focus-ring"
              >
                {inner}
              </Link>
            ) : (
              <div
                key={ce.entity.id}
                className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-white px-4 py-3"
              >
                {inner}
              </div>
            );
          })}
        </div>
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Link an entity to this case"
        description="Search your monitored assets and attach them as related entities."
        footer={
          <Button variant="outline" onClick={() => setOpen(false)}>
            Done
          </Button>
        }
      >
        <SearchInput value={query} onChange={setQuery} placeholder="Search entities… (min 2 characters)" />
        {searching && <p className="mt-3 text-xs text-muted">Searching…</p>}
        <ul className="mt-3 divide-y divide-line-soft rounded-xl border border-line bg-white">
          {results.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-[13px] font-semibold text-ink">{e.display_name}</p>
                <p className="text-xs text-muted">
                  {ENTITY_TYPE_LABELS[e.entity_type] || e.entity_type}
                  {e.platform ? ` · ${e.platform}` : ''}
                </p>
              </div>
              {known.has(e.id) ? (
                <span className="text-xs font-semibold text-faint">Already linked</span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  loading={linking === e.id}
                  onClick={() => void link(e)}
                >
                  Link
                </Button>
              )}
            </li>
          ))}
          {!searching && query.trim().length >= 2 && results.length === 0 && (
            <li className="px-3 py-3 text-[13px] text-muted">No entities match “{query.trim()}”.</li>
          )}
          {query.trim().length < 2 && (
            <li className="px-3 py-3 text-[13px] text-muted">
              Start typing to search by name, handle, domain or package.
            </li>
          )}
        </ul>
      </Modal>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * Evidence tab
 * ------------------------------------------------------------------ */

interface EvidenceTabProps {
  data: CaseDetail;
  evidence: EvidenceItem[];
  canWrite: boolean;
  onAdded: () => void;
}

const MAX_UPLOAD = 5 * 1024 * 1024;
const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif'];
const TEXT_EXTS = ['txt', 'log', 'json', 'csv'];
const ACCEPT_EXTS = [...IMAGE_EXTS, ...TEXT_EXTS, 'pdf'];

const EvidenceTab: React.FC<EvidenceTabProps> = ({ data, evidence, canWrite, onAdded }) => {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'upload' | 'text'>('upload');
  const [entityId, setEntityId] = useState(data.entities?.[0]?.entity.id || '');

  // upload path
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [uploading, setUploading] = useState(false);

  // text / url path
  const [kind, setKind] = useState('text');
  const [title, setTitle] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [textContent, setTextContent] = useState('');
  const [textDescription, setTextDescription] = useState('');
  const [creating, setCreating] = useState(false);

  const caseEntities = data.entities || [];

  const reset = () => {
    setFile(null);
    setFileError(null);
    setDescription('');
    setKind('text');
    setTitle('');
    setSourceUrl('');
    setTextContent('');
    setTextDescription('');
    setMode('upload');
  };

  const pickFile = (f: File | null) => {
    setFile(null);
    setFileError(null);
    if (!f) return;
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (!ACCEPT_EXTS.includes(ext)) {
      setFileError(`.${ext} files are not supported. Use an image, TXT/LOG/JSON/CSV or add it as evidence below.`);
      return;
    }
    if (f.size > MAX_UPLOAD) {
      setFileError('File is larger than 5 MB.');
      return;
    }
    if (ext === 'pdf') {
      setFileError('PDF storage is not available on the API yet — add PDFs through the Text / URL path.');
      return;
    }
    setFile(f);
  };

  const uploadFile = async () => {
    if (!file || !entityId) return;
    setUploading(true);
    try {
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      let created;
      if (IMAGE_EXTS.includes(ext)) {
        const form = new FormData();
        form.append('entity_id', entityId);
        form.append('title', file.name);
        if (description.trim()) form.append('description', description.trim());
        form.append('kind', 'screenshot');
        form.append('file', file);
        created = await apiRequest<{ id: string }>('/evidence/upload', { method: 'POST', body: form });
      } else {
        const text = await file.text();
        created = await apiRequest<{ id: string }>('/evidence', {
          method: 'POST',
          body: JSON.stringify({
            entity_id: entityId,
            kind: 'text',
            title: file.name,
            description: description.trim() || undefined,
            text_content: text.slice(0, 20000),
          }),
        });
      }
      await evidenceService.linkEvidence(created.id, { case_id: data.id });
      toast.success('Evidence added', file.name);
      reset();
      setOpen(false);
      onAdded();
    } catch (e) {
      toast.error('Upload failed', errMsg(e, 'The evidence could not be stored.'));
    } finally {
      setUploading(false);
    }
  };

  const createTextEvidence = async () => {
    if (!entityId) return;
    if (title.trim().length === 0) {
      toast.error('Title is required');
      return;
    }
    if (kind === 'url' && sourceUrl.trim().length < 4) {
      toast.error('A source URL is required for URL evidence');
      return;
    }
    if (kind === 'url' && textContent.trim().length === 0 && sourceUrl.trim().length === 0) {
      toast.error('Add a URL or text content');
      return;
    }
    setCreating(true);
    try {
      const created = await apiRequest<{ id: string }>('/evidence', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: entityId,
          kind,
          title: title.trim(),
          description: textDescription.trim() || undefined,
          source_url: sourceUrl.trim() || undefined,
          text_content: textContent.trim() || undefined,
        }),
      });
      await evidenceService.linkEvidence(created.id, { case_id: data.id });
      toast.success('Evidence added', title.trim());
      reset();
      setOpen(false);
      onAdded();
    } catch (e) {
      toast.error('Could not create evidence', errMsg(e, 'The API rejected this request.'));
    } finally {
      setCreating(false);
    }
  };

  const download = async (ev: EvidenceItem) => {
    try {
      await evidenceService.downloadEvidence(ev.id, ev.file_name || ev.title || 'evidence-download');
    } catch (e) {
      toast.error('Download failed', errMsg(e, 'Could not fetch this file.'));
    }
  };

  const verificationTone = (v?: string) =>
    v === 'verified' ? 'success' : v === 'mismatch' ? 'danger' : 'warning';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted">
          Evidence linked to this case and to its entities ({evidence.length}).
        </p>
        <div className="flex items-center gap-2">
          <Link
            to={`/evidence?case_id=${data.id}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-line bg-white px-3.5 text-[13px] font-semibold text-ink-700 transition-colors hover:border-brand-200 focus-ring"
          >
            Evidence Center <ExternalLink className="h-3.5 w-3.5" />
          </Link>
          {canWrite && (
            <Button size="sm" icon={<Upload className="h-4 w-4" />} onClick={() => setOpen(true)}>
              Add evidence
            </Button>
          )}
        </div>
      </div>

      {evidence.length === 0 ? (
        <EmptyState
          title="No evidence yet"
          description="Attach screenshots, files, text or URLs to support this investigation."
          action={
            canWrite ? (
              <Button variant="outline" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>
                Add evidence
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-2.5">
          {evidence.map((ev) => (
            <div
              key={ev.id}
              className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-white px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="info">{EVIDENCE_KIND_LABELS[ev.kind] || ev.kind}</Badge>
                  <span className="truncate text-sm font-bold text-ink">
                    {ev.title || ev.file_name || 'Untitled evidence'}
                  </span>
                  <Badge tone={verificationTone(ev.verification_status)}>
                    {VERIFICATION_LABELS[ev.verification_status || 'pending'] || 'Pending'}
                  </Badge>
                </div>
                {ev.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted">{ev.description}</p>
                )}
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-faint">
                  {ev.sha256 && (
                    <span className="flex items-center gap-1">
                      <span className="font-mono">{ev.sha256.slice(0, 16)}…</span>
                      <CopyButton text={ev.sha256} label="Copy full SHA-256" />
                    </span>
                  )}
                  <span>{formatRelativeTime(ev.created_at)}</span>
                  {ev.entity && <span>· {ev.entity.display_name}</span>}
                  {ev.size_bytes ? <span>· {(ev.size_bytes / 1024).toFixed(1)} KB</span> : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Tooltip content={ev.has_file ? 'Download the stored file' : 'No stored file for this record'}>
                  <span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!ev.has_file}
                      icon={<Download className="h-4 w-4" />}
                      onClick={() => void download(ev)}
                    >
                      Download
                    </Button>
                  </span>
                </Tooltip>
                <Link
                  to={`/evidence?case_id=${data.id}`}
                  className="inline-flex h-8 items-center rounded-lg border border-line bg-white px-3 text-[13px] font-semibold text-ink-700 transition-colors hover:border-brand-200 hover:text-brand-700 focus-ring"
                >
                  Open
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        size="lg"
        title="Add evidence"
        description="Upload a file or record text/URL evidence, then link it to this case."
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={uploading || creating}>
              Cancel
            </Button>
            {mode === 'upload' ? (
              <Button onClick={() => void uploadFile()} loading={uploading} disabled={!file || !entityId}>
                Upload & link
              </Button>
            ) : (
              <Button onClick={() => void createTextEvidence()} loading={creating} disabled={!entityId}>
                Create & link
              </Button>
            )}
          </>
        }
      >
        {caseEntities.length === 0 ? (
          <p className="text-sm text-muted">
            This case has no linked entities yet. The API stores evidence against an entity — link one
            first from the Entities tab.
          </p>
        ) : (
          <div className="space-y-4">
            <Field label="Attach to entity" required htmlFor="ev-entity">
              <Select id="ev-entity" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
                {caseEntities.map((ce) => (
                  <option key={ce.entity.id} value={ce.entity.id}>
                    {ce.entity.display_name}
                  </option>
                ))}
              </Select>
            </Field>

            <div className="flex gap-1 rounded-xl bg-bg p-1">
              {(['upload', 'text'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    'flex-1 rounded-lg px-3 py-2 text-[13px] font-semibold transition-colors focus-ring',
                    mode === m ? 'bg-white text-brand-700 shadow-sm' : 'text-muted hover:text-ink'
                  )}
                >
                  {m === 'upload' ? 'Upload file' : 'Text / URL'}
                </button>
              ))}
            </div>

            {mode === 'upload' ? (
              <div className="space-y-3">
                <Field
                  label="File"
                  error={fileError}
                  htmlFor="ev-file"
                  hint="Images (PNG/JPEG/WEBP/GIF) are stored as files; TXT/LOG/JSON/CSV are stored as text evidence. Max 5 MB."
                >
                  <input
                    id="ev-file"
                    type="file"
                    accept={ACCEPT_EXTS.map((e) => `.${e}`).join(',')}
                    onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                    className="block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3 file:py-2 file:text-[13px] file:font-semibold file:text-brand-700 hover:file:bg-brand-100"
                  />
                </Field>
                {file && !fileError && (
                  <p className="text-[13px] text-ink-700">
                    <span className="font-semibold">{file.name}</span>{' '}
                    <span className="text-muted">({(file.size / 1024).toFixed(1)} KB)</span>
                  </p>
                )}
                <Field label="Description (optional)" htmlFor="ev-upload-desc">
                  <Textarea
                    id="ev-upload-desc"
                    value={description}
                    maxLength={5000}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="What does this file prove?"
                  />
                </Field>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Kind" htmlFor="ev-kind">
                    <Select id="ev-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                      {['text', 'url', 'whois', 'url_inspection', 'other'].map((k) => (
                        <option key={k} value={k}>
                          {EVIDENCE_KIND_LABELS[k]}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Title" required htmlFor="ev-title">
                    <Input
                      id="ev-title"
                      value={title}
                      maxLength={300}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="e.g. Archived phishing page text"
                    />
                  </Field>
                </div>
                <Field label="Source URL" htmlFor="ev-url" hint={kind === 'url' ? 'Required for URL evidence.' : undefined}>
                  <Input
                    id="ev-url"
                    type="url"
                    value={sourceUrl}
                    maxLength={2048}
                    onChange={(e) => setSourceUrl(e.target.value)}
                    placeholder="https://…"
                  />
                </Field>
                <Field label="Text content" htmlFor="ev-text">
                  <Textarea
                    id="ev-text"
                    value={textContent}
                    maxLength={20000}
                    onChange={(e) => setTextContent(e.target.value)}
                    placeholder="Paste the captured text, response body or notes…"
                  />
                </Field>
                <Field label="Description (optional)" htmlFor="ev-desc">
                  <Input
                    id="ev-desc"
                    value={textDescription}
                    maxLength={5000}
                    onChange={(e) => setTextDescription(e.target.value)}
                    placeholder="Context for reviewers"
                  />
                </Field>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * Notes tab
 * ------------------------------------------------------------------ */

const NotesTab: React.FC<{ data: CaseDetail; canNote: boolean; authorName?: string }> = ({
  data,
  canNote,
  authorName,
}) => {
  const { toast } = useToast();
  const [body, setBody] = useState('');
  const [saving, setSaving] = useState(false);
  const [extra, setExtra] = useState<CaseNote[]>([]);

  const notes = useMemo(() => {
    const all = [...(data.notes || []), ...extra];
    return [...all].sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [data.notes, extra]);

  const submit = async () => {
    const value = body.trim();
    if (!value) return;
    setSaving(true);
    try {
      const created = await caseService.addNote(data.id, value);
      setExtra((prev) => [
        ...prev,
        created.author ? created : { ...created, author: { id: '', email: '', full_name: authorName || 'You' } },
      ]);
      setBody('');
      toast.success('Note added');
    } catch (e) {
      toast.error('Could not add note', errMsg(e, 'The API rejected this note.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {canNote && (
        <Card>
          <CardContent className="pt-4">
            <Field label="Add an investigation note" htmlFor="note-body">
              <Textarea
                id="note-body"
                value={body}
                maxLength={800}
                onChange={(e) => setBody(e.target.value)}
                placeholder="What did you observe, decide or verify? Notes are part of the audit trail."
              />
            </Field>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-xs text-faint">{body.length}/800</span>
              <Button size="sm" onClick={() => void submit()} loading={saving} disabled={!body.trim()}>
                Add note
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {notes.length === 0 ? (
        <EmptyState
          title="No notes yet"
          description={canNote ? 'Document your findings as you work the case.' : 'No notes have been added.'}
        />
      ) : (
        <ul className="space-y-3">
          {notes.map((n) => (
            <li key={n.id} className="rounded-xl border border-line bg-white px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Avatar name={n.author?.full_name || n.author?.email || '?'} size={28} />
                <span className="text-[13px] font-bold text-ink">
                  {n.author?.full_name || n.author?.email || 'Unknown author'}
                </span>
                <Tooltip content={formatDate(n.created_at)}>
                  <span className="text-xs text-faint">{formatRelativeTime(n.created_at)}</span>
                </Tooltip>
              </div>
              <div className="mt-2 space-y-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-700">
                {n.body.split('\n').map((line, i) => (
                  <p key={i}>{line}</p>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * History tab
 * ------------------------------------------------------------------ */

interface TimelineItem {
  id: string;
  at: string;
  dot: string;
  title: React.ReactNode;
  detail?: React.ReactNode;
}

const HistoryTab: React.FC<{ data: CaseDetail }> = ({ data }) => {
  const items = useMemo<TimelineItem[]>(() => {
    const out: TimelineItem[] = [];

    (data.events || []).forEach((ev) => {
      const meta = EVENT_META[ev.event_type] || { label: ev.event_type, dot: 'bg-faint' };
      out.push({
        id: `e-${ev.id}`,
        at: ev.created_at,
        dot: meta.dot,
        title: (
          <span className="font-semibold text-ink">
            {meta.label}
            {ev.actor ? ` by ${ev.actor.full_name || ev.actor.email}` : ''}
          </span>
        ),
        detail: (
          <span className="flex flex-wrap items-center gap-1.5">
            {ev.from_status && (
              <>
                <Badge tone="default">{statusLabel(ev.from_status)}</Badge>
                <span className="text-faint">→</span>
              </>
            )}
            {ev.to_status && <Badge tone="primary">{statusLabel(ev.to_status)}</Badge>}
            {typeof ev.details?.comment === 'string' && ev.details.comment && (
              <span className="text-muted">“{ev.details.comment}”</span>
            )}
            {typeof ev.details?.reason === 'string' && ev.details.reason && (
              <span className="text-muted">{ev.details.reason}</span>
            )}
            {typeof ev.details?.note === 'string' && ev.details.note && (
              <span className="text-muted">{ev.details.note}</span>
            )}
          </span>
        ),
      });
    });

    (data.assignments || []).forEach((a) => {
      out.push({
        id: `a-${a.id}`,
        at: a.assigned_at,
        dot: 'bg-brand-500',
        title: (
          <span className="font-semibold text-ink">
            Assigned to {a.assignee?.full_name || a.assignee?.email || 'investigator'}
          </span>
        ),
        detail: a.note ? <span className="text-muted">“{a.note}”</span> : undefined,
      });
      if (a.unassigned_at) {
        out.push({
          id: `u-${a.id}`,
          at: a.unassigned_at,
          dot: 'bg-faint',
          title: (
            <span className="font-semibold text-ink">
              Unassigned {a.assignee ? `(${a.assignee.full_name || a.assignee.email})` : ''}
            </span>
          ),
        });
      }
    });

    (data.escalations || []).forEach((esc) => {
      out.push({
        id: `x-${esc.id}`,
        at: esc.created_at,
        dot: 'bg-danger',
        title: (
          <span className="font-semibold text-ink">Escalated to {esc.partner_type} partner</span>
        ),
        detail: (
          <span className="space-y-0.5">
            <span className="block text-muted">{esc.reason}</span>
            {esc.requested_action && (
              <span className="block text-xs text-faint">Requested action: {esc.requested_action}</span>
            )}
            {esc.partner_contact && (
              <span className="block text-xs text-faint">Contact: {esc.partner_contact}</span>
            )}
          </span>
        ),
      });
    });

    return out.sort((a, b) => b.at.localeCompare(a.at));
  }, [data]);

  if (items.length === 0) {
    return <EmptyState title="No activity yet" description="Actions on this case will appear here." />;
  }

  return (
    <ol className="relative ml-2 border-l border-line-soft pl-5">
      {items.map((item) => (
        <li key={item.id} className="relative pb-5 last:pb-0">
          <span
            className={cn(
              'absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-white',
              item.dot
            )}
            aria-hidden
          />
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            {item.title}
            <Tooltip content={formatDate(item.at)}>
              <span className="text-xs text-faint">{formatRelativeTime(item.at)}</span>
            </Tooltip>
          </div>
          {item.detail && <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px]">{item.detail}</div>}
        </li>
      ))}
    </ol>
  );
};

/* ------------------------------------------------------------------ *
 * Overview tab
 * ------------------------------------------------------------------ */

const OverviewTab: React.FC<{
  data: CaseDetail;
  onShowTab: (tab: string) => void;
  canOpenEntities: boolean;
}> = ({ data, onShowTab, canOpenEntities }) => {
  const events = useMemo(
    () => [...(data.events || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [data.events]
  );
  const entities = data.entities || [];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Case description</CardTitle>
        </CardHeader>
        <CardContent>
          {data.summary ? (
            <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink-700">{data.summary}</p>
          ) : (
            <p className="text-[13px] text-muted">
              No summary recorded yet. Add one from the Case Summary card.
            </p>
          )}
          <dl className="mt-4 grid gap-x-6 gap-y-1 border-t border-line-soft pt-3 text-[13px] sm:grid-cols-2">
            <div className="flex justify-between py-1">
              <dt className="text-faint">Case number</dt>
              <dd className="font-mono font-semibold text-ink-700">{data.case_number}</dd>
            </div>
            <div className="flex justify-between py-1">
              <dt className="text-faint">Created by</dt>
              <dd className="font-medium text-ink-700">
                {data.created_by?.full_name || data.created_by?.email || '—'}
              </dd>
            </div>
            <div className="flex justify-between py-1">
              <dt className="text-faint">Created</dt>
              <dd className="font-medium text-ink-700">{formatDate(data.created_at)}</dd>
            </div>
            <div className="flex justify-between py-1">
              <dt className="text-faint">Last updated</dt>
              <dd className="font-medium text-ink-700">{formatRelativeTime(data.updated_at)}</dd>
            </div>
            {data.resolution_outcome && (
              <div className="flex justify-between py-1 sm:col-span-2">
                <dt className="text-faint">Resolution</dt>
                <dd className="font-medium text-success">
                  {RESOLUTION_OUTCOME_LABELS[data.resolution_outcome]}
                  {data.resolution_summary ? ` — ${data.resolution_summary}` : ''}
                </dd>
              </div>
            )}
            {data.escalation_summary && (
              <div className="flex justify-between py-1 sm:col-span-2">
                <dt className="text-faint">Escalation</dt>
                <dd className="font-medium text-danger">{data.escalation_summary}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Latest activity</CardTitle>
          <button
            onClick={() => onShowTab('history')}
            className="text-[13px] font-semibold text-brand-600 hover:underline"
          >
            Full history
          </button>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-[13px] text-muted">No activity recorded.</p>
          ) : (
            <ul className="space-y-3">
              {events.slice(0, 5).map((ev) => {
                const meta = EVENT_META[ev.event_type] || { label: ev.event_type, dot: 'bg-faint' };
                return (
                  <li key={ev.id} className="flex items-start gap-2.5">
                    <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', meta.dot)} aria-hidden />
                    <div className="min-w-0">
                      <p className="text-[13px] font-semibold text-ink">
                        {meta.label}
                        {ev.to_status && ev.from_status ? `: ${statusLabel(ev.from_status)} → ${statusLabel(ev.to_status)}` : ''}
                      </p>
                      <p className="text-xs text-faint">
                        {formatRelativeTime(ev.created_at)}
                        {ev.actor ? ` · ${ev.actor.full_name || ev.actor.email}` : ''}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Linked entities ({entities.length})</CardTitle>
          <button
            onClick={() => onShowTab('entities')}
            className="text-[13px] font-semibold text-brand-600 hover:underline"
          >
            Manage entities
          </button>
        </CardHeader>
        <CardContent>
          {entities.length === 0 ? (
            <p className="text-[13px] text-muted">No entities linked to this case yet.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {entities.slice(0, 8).map((ce) => (
                <li key={ce.entity.id}>
                  {canOpenEntities ? (
                    <Link
                      to={`/entities/${ce.entity.id}`}
                      className="inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 text-[13px] font-semibold text-ink-700 transition-colors hover:border-brand-200 hover:text-brand-700 focus-ring"
                    >
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: severityColor(ce.entity.current_severity) }}
                      />
                      {ce.entity.display_name}
                      <span className="font-mono text-xs text-muted">
                        {ce.entity.current_risk_score === null
                          ? '—'
                          : ce.entity.current_risk_score.toFixed(2)}
                      </span>
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 text-[13px] font-semibold text-ink-700">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: severityColor(ce.entity.current_severity) }}
                      />
                      {ce.entity.display_name}
                    </span>
                  )}
                </li>
              ))}
              {entities.length > 8 && (
                <li>
                  <button
                    onClick={() => onShowTab('entities')}
                    className="rounded-full border border-dashed border-line px-3 py-1.5 text-[13px] font-semibold text-muted hover:text-brand-600"
                  >
                    +{entities.length - 8} more
                  </button>
                </li>
              )}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * Header / workflow modals
 * ------------------------------------------------------------------ */

interface EditDetailsModalProps {
  open: boolean;
  onClose: () => void;
  data: CaseDetail;
  onSaved: (updated: CaseDetail) => void;
}

const EditDetailsModal: React.FC<EditDetailsModalProps> = ({ open, onClose, data, onSaved }) => {
  const { toast } = useToast();
  const [title, setTitle] = useState(data.title);
  const [summary, setSummary] = useState(data.summary || '');
  const [severity, setSeverity] = useState<string>(data.severity);
  const [platforms, setPlatforms] = useState<string[]>(data.platforms || []);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle(data.title);
    setSummary(data.summary || '');
    setSeverity(data.severity);
    setPlatforms(data.platforms || []);
  }, [open, data]);

  const togglePlatform = (key: string) =>
    setPlatforms((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));

  const submit = async () => {
    if (title.trim().length < 3) {
      toast.error('Title must be at least 3 characters');
      return;
    }
    setSaving(true);
    try {
      const updated = await caseService.updateCase(data.id, {
        title: title.trim(),
        summary,
        severity,
        platforms,
        version: data.version,
      });
      toast.success('Case updated');
      onSaved(updated);
      onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('Case was modified by someone else — reload');
        onClose();
      } else {
        toast.error('Could not save changes', errMsg(e, 'The API rejected this update.'));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Edit case details"
      description={`Optimistic concurrency is enforced with version ${data.version}.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Save changes
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Title" required htmlFor="edit-title">
          <Input
            id="edit-title"
            value={title}
            maxLength={300}
            onChange={(e) => setTitle(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-faint">{title.length}/300</p>
        </Field>
        <Field label="Summary" htmlFor="edit-summary">
          <Textarea
            id="edit-summary"
            value={summary}
            maxLength={10000}
            onChange={(e) => setSummary(e.target.value)}
          />
          <p className="mt-1 text-right text-xs text-faint">{summary.length}/10000</p>
        </Field>
        <Field label="Severity" htmlFor="edit-severity" hint="Recorded on the case by an investigator.">
          <Select id="edit-severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {Object.entries(SEVERITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="Platforms"
          hint="Where this case spans — tag the platforms involved (click to toggle)."
        >
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
      </div>
    </Modal>
  );
};

interface ResolveModalProps {
  open: boolean;
  onClose: () => void;
  data: CaseDetail;
  onResolved: (updated: CaseDetail) => void;
}

const ResolveModal: React.FC<ResolveModalProps> = ({ open, onClose, data, onResolved }) => {
  const { toast } = useToast();
  const [outcome, setOutcome] = useState<ResolutionOutcome>('confirmed_threat_actioned');
  const [summary, setSummary] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setOutcome('confirmed_threat_actioned');
    setSummary('');
  }, [open]);

  const submit = async () => {
    if (summary.trim().length < 5) {
      toast.error('Resolution summary is required', 'Describe the outcome in at least 5 characters.');
      return;
    }
    setSaving(true);
    try {
      const updated = await apiRequest<CaseDetail>(`/cases/${data.id}/status`, {
        method: 'POST',
        body: JSON.stringify({
          status: 'resolved',
          expected_status: data.status,
          resolution_outcome: outcome,
          resolution_summary: summary.trim(),
        }),
      });
      toast.success('Case resolved');
      onResolved(updated);
      onClose();
    } catch (e) {
      toast.error('Could not resolve this case', errMsg(e, 'The transition was rejected.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Resolve case"
      description="Resolution records an outcome and a summary; the case moves to Resolved."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="success" onClick={submit} loading={saving}>
            Resolve case
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Outcome" required htmlFor="resolve-outcome">
          <Select
            id="resolve-outcome"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as ResolutionOutcome)}
          >
            {Object.entries(RESOLUTION_OUTCOME_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="Resolution summary"
          required
          htmlFor="resolve-summary"
          hint="Minimum 5 characters. Shown on the case and in reports."
        >
          <Textarea
            id="resolve-summary"
            value={summary}
            maxLength={10000}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="e.g. Impersonation profile confirmed and taken down; monitoring remains active."
          />
        </Field>
      </div>
    </Modal>
  );
};

interface EscalateModalProps {
  open: boolean;
  onClose: () => void;
  data: CaseDetail;
  onEscalated: (updated: CaseDetail) => void;
}

const EscalateModal: React.FC<EscalateModalProps> = ({ open, onClose, data, onEscalated }) => {
  const { toast } = useToast();
  const [partnerType, setPartnerType] = useState('legal');
  const [reason, setReason] = useState('');
  const [contact, setContact] = useState('');
  const [action, setAction] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPartnerType('legal');
    setReason('');
    setContact('');
    setAction('');
  }, [open]);

  const submit = async () => {
    if (reason.trim().length < 5) {
      toast.error('A reason is required', 'Explain the handoff in at least 5 characters.');
      return;
    }
    setSaving(true);
    try {
      const updated = await caseService.escalate(data.id, {
        partner_type: partnerType,
        reason: reason.trim(),
        partner_contact: contact.trim() || undefined,
        requested_action: action.trim() || undefined,
      });
      toast.success('Escalation recorded', 'No external message was sent — the handoff is recorded only.');
      onEscalated(updated);
      onClose();
    } catch (e) {
      toast.error('Could not escalate', errMsg(e, 'The API rejected this escalation.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Escalate to a partner"
      description="Records a legal / marketing / platform handoff. Nothing is sent externally."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Record escalation
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Partner type" required htmlFor="esc-partner">
            <Select
              id="esc-partner"
              value={partnerType}
              onChange={(e) => setPartnerType(e.target.value)}
            >
              <option value="legal">Legal</option>
              <option value="marketing">Marketing</option>
              <option value="platform">Platform</option>
            </Select>
          </Field>
          <Field label="Partner contact (optional)" htmlFor="esc-contact">
            <Input
              id="esc-contact"
              value={contact}
              maxLength={300}
              onChange={(e) => setContact(e.target.value)}
              placeholder="legal@partner.example"
            />
          </Field>
        </div>
        <Field label="Reason" required htmlFor="esc-reason">
          <Textarea
            id="esc-reason"
            value={reason}
            maxLength={5000}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why does this case need a partner handoff? (min 5 characters)"
          />
        </Field>
        <Field label="Requested action (optional)" htmlFor="esc-action">
          <Input
            id="esc-action"
            value={action}
            maxLength={2000}
            onChange={(e) => setAction(e.target.value)}
            placeholder="e.g. Takedown review"
          />
        </Field>
      </div>
    </Modal>
  );
};

/* ------------------------------------------------------------------ *
 * Reopen a resolved case (server requires an explaining comment)
 * ------------------------------------------------------------------ */

interface ReopenModalProps {
  open: boolean;
  onClose: () => void;
  data: CaseDetail;
  onReopened: (updated: CaseDetail) => void;
}

const ReopenModal: React.FC<ReopenModalProps> = ({ open, onClose, data, onReopened }) => {
  const { toast } = useToast();
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setComment('');
  }, [open]);

  const submit = async () => {
    if (comment.trim().length < 5) {
      toast.error('A comment is required', 'Explain why the case is being reopened (min 5 characters).');
      return;
    }
    setSaving(true);
    try {
      const updated = await caseService.changeStatus(
        data.id,
        'under_review',
        comment.trim(),
        undefined,
        undefined,
        data.status
      );
      toast.success('Case reopened', 'The case is back under review and the reason was recorded.');
      onReopened(updated);
      onClose();
    } catch (e) {
      toast.error('Could not reopen', errMsg(e, 'The API rejected this reopen.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reopen this case?"
      description={`Moves ${data.case_number} from Resolved back to Under review and records who reopened it and why.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Reopen case
          </Button>
        </>
      }
    >
      <Field label="Why reopen this case?" required htmlFor="reopen-comment">
        <Textarea
          id="reopen-comment"
          value={comment}
          maxLength={5000}
          rows={4}
          onChange={(e) => setComment(e.target.value)}
          placeholder="e.g. New reports of the same impersonating profile since closure."
        />
      </Field>
      <p className="text-xs text-muted">
        Reopening clears the previous resolution. The decision history is kept and this comment is added to
        the case timeline.
      </p>
    </Modal>
  );
};

/* ------------------------------------------------------------------ *
 * Case detail / investigation workspace
 * ------------------------------------------------------------------ */

export const CaseDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { user, role, brands, hasPermission } = useAuth();
  const perms = usePerms();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'overview';

  const [data, setData] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportDraft, setReportDraft] = useState<TakedownReportDraft | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const c = (await caseService.getCase(id)) as CaseDetail;
      setData(c);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setNotFound(true);
      } else {
        setError(errMsg(e, 'We could not load this case. Check your connection and try again.'));
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const c = (await caseService.getCase(id)) as CaseDetail;
      setData(c);
    } catch {
      /* keep the current view */
    }
  }, [id]);

  const openReportDraft = async () => {
    if (!id) return;
    setReportLoading(true);
    try {
      setReportDraft(await caseService.getTakedownReport(id));
    } catch (e) {
      toast.error(errMsg(e, 'A report draft is available only for a confirmed case.'));
    } finally {
      setReportLoading(false);
    }
  };

  const reportText = (draft: TakedownReportDraft) => {
    const lines = [
      'AnaRisk platform review request (draft)',
      `Created: ${formatDate(draft.generated_at)}`,
      `Case: ${draft.case_number}`,
      `Brand: ${draft.brand.name}`,
      '',
      'Observed assets:',
      ...draft.suspected_assets.flatMap((asset) => [
        `- ${asset.type}${asset.platform ? ` on ${asset.platform}` : ''}: ${asset.name} (${asset.identifier})`,
        ...(asset.source_url ? [`  Source URL: ${asset.source_url}`] : []),
        ...(asset.publisher ? [`  Publisher/developer: ${asset.publisher}`] : []),
        ...(asset.observed_at ? [`  Observed: ${formatDate(asset.observed_at)}`] : []),
        ...(asset.assessment?.signals || []).map((signal) => `  ${signal.type} (${signal.status}${signal.value === null ? '' : `, ${signal.value.toFixed(2)}`}): ${signal.explanation}`),
      ]),
      ...(draft.case_evidence.length ? ['', 'Case evidence:', ...draft.case_evidence.map((ev) => `- ${ev.kind}: ${ev.title} (${ev.provenance}; ${formatDate(ev.collected_at)})${ev.source_url ? ` — ${ev.source_url}` : ''}${ev.sha256 ? ` [SHA-256 ${ev.sha256}]` : ''}`)] : []),
      '',
      `Analyst decision: ${draft.decision.outcome.replace(/_/g, ' ')} — ${draft.decision.reason}`,
      `Risk score: ${draft.decision.case_risk_score === null ? 'unavailable' : `${(draft.decision.case_risk_score * 100).toFixed(0)}/100`} (${draft.decision.case_risk_band}; ${draft.decision.score_version || 'no score version'})`,
      draft.decision.score_note,
      '',
      draft.requested_action,
      draft.submission_note,
    ];
    return lines.join('\n');
  };

  useEffect(() => {
    void load();
  }, [load]);

  const setTab = useCallback(
    (next: string) => {
      setParams((prev) => {
        const p = new URLSearchParams(prev);
        p.set('tab', next);
        return p;
      });
    },
    [setParams]
  );

  // ---- local header state
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [savingTitle, setSavingTitle] = useState(false);
  const [summaryEditing, setSummaryEditing] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState('');
  const [savingSummary, setSavingSummary] = useState(false);

  // ---- modals
  const [editOpen, setEditOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const evidence = useMemo(() => {
    if (!data) return [];
    const map = new Map<string, EvidenceItem>();
    (data.evidence || []).forEach((e) => map.set(e.id, e));
    (data.entities || []).forEach((ce) => {
      const list = (ce.evidence || []) as unknown as EvidenceItem[];
      list.forEach((e) => {
        if (!map.has(e.id)) {
          map.set(e.id, {
            ...e,
            entity: {
              id: ce.entity.id,
              display_name: ce.entity.display_name,
              entity_type: ce.entity.entity_type,
            },
          });
        }
      });
    });
    return Array.from(map.values()).sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [data]);

  const events = useMemo(
    () => [...(data?.events || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [data?.events]
  );

  const transitions = data?.allowed_transitions ?? [];

  const saveTitle = async () => {
    if (!data) return;
    if (titleDraft.trim().length < 3) {
      toast.error('Title must be at least 3 characters');
      return;
    }
    setSavingTitle(true);
    try {
      const updated = (await caseService.updateCase(data.id, {
        title: titleDraft.trim(),
        version: data.version,
      })) as CaseDetail;
      setData(updated);
      setTitleEditing(false);
      toast.success('Title updated');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('Case was modified by someone else — reload');
        setTitleEditing(false);
        void load();
      } else {
        toast.error('Could not update title', errMsg(e, 'The API rejected this update.'));
      }
    } finally {
      setSavingTitle(false);
    }
  };

  const saveSummary = async () => {
    if (!data) return;
    setSavingSummary(true);
    try {
      const updated = (await caseService.updateCase(data.id, {
        summary: summaryDraft,
        version: data.version,
      })) as CaseDetail;
      setData(updated);
      setSummaryEditing(false);
      toast.success('Summary updated');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.error('Case was modified by someone else — reload');
        setSummaryEditing(false);
        void load();
      } else {
        toast.error('Could not update summary', errMsg(e, 'The API rejected this update.'));
      }
    } finally {
      setSavingSummary(false);
    }
  };

  const moveTo = async (to: CaseStatus, comment?: string) => {
    if (!data) return;
    if (to === 'resolved') {
      setResolveOpen(true);
      return;
    }
    if (to === 'escalated') {
      setEscalateOpen(true);
      return;
    }
    if (to === 'assigned' && !data.assigned_to) {
      setAssignOpen(true);
      toast.info('Assign an owner first', 'A case needs an owner before it can move to Assigned.');
      return;
    }
    // Reopening a resolved case requires an explaining comment (server-enforced).
    if (data.status === 'resolved' && to === 'under_review' && !comment?.trim()) {
      setReopenOpen(true);
      return;
    }
    try {
      const updated = await caseService.changeStatus(data.id, to, comment?.trim() || undefined, undefined, undefined, data.status);
      setData(updated);
      toast.success(`Case moved to ${statusLabel(to)}`);
    } catch (e) {
      toast.error('Could not change status', errMsg(e, 'The transition was rejected.'));
    }
  };

  const confirmDelete = async () => {
    if (!data) return;
    setDeleting(true);
    try {
      await caseService.deleteCase(data.id);
      toast.success('Case deleted', data.case_number);
      navigate('/cases');
    } catch (e) {
      toast.error('Could not delete case', errMsg(e, 'Only administrators can delete cases.'));
      setDeleting(false);
    }
  };

  /* ---------------- render ---------------- */

  if (loading) return <LoadingBlock label="Loading case…" />;

  if (notFound) {
    return (
      <div className="py-10">
        <ErrorState
          title="Case not found"
          message="This case may have been deleted, or your role cannot access it."
          onRetry={() => navigate('/cases')}
        />
        <div className="mt-3 text-center">
          <Button variant="ghost" onClick={() => navigate('/cases')}>
            ← Back to Cases
          </Button>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-10">
        <ErrorState
          title="Could not load this case"
          message={error || 'Unknown error'}
          onRetry={() => void load()}
        />
      </div>
    );
  }

  const brandName = brands.find((b) => b.id === data.brand_id)?.name;
  const openAssignment = (data.assignments || []).find((a) => !a.unassigned_at);
  const canResolveNow = transitions.includes('resolved');
  const canEscalateNow = data.status === 'assigned' || data.status === 'escalated';

  const tabItems: TabItem[] = [
    { id: 'overview', label: 'Overview', icon: <Layers className="h-4 w-4" /> },
    {
      id: 'entities',
      label: 'Entities',
      icon: <Network className="h-4 w-4" />,
      count: data.entities?.length ?? 0,
    },
    { id: 'evidence', label: 'Evidence', icon: <FileText className="h-4 w-4" />, count: evidence.length },
    { id: 'graph', label: 'Graph', icon: <Link2 className="h-4 w-4" /> },
    { id: 'notes', label: 'Notes', icon: <MessageSquare className="h-4 w-4" />, count: data.notes?.length ?? 0 },
    {
      id: 'history',
      label: 'History',
      icon: <HistoryIcon className="h-4 w-4" />,
      count:
        (data.events?.length || 0) + (data.assignments?.length || 0) + (data.escalations?.length || 0),
    },
  ];

  return (
    <div>
      <Link
        to="/cases"
        className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-muted transition-colors hover:text-brand-600"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Cases
      </Link>

      {/* header */}
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="rounded-md border border-line bg-bg px-2 py-1 font-mono text-[12.5px] font-bold text-ink-700">
              {data.case_number}
            </span>
            {(data.platforms || []).map((p) => (
              <Badge key={p} tone="info">
                {PLATFORM_LABELS[p] || p}
              </Badge>
            ))}
            {titleEditing ? (
              <span className="flex items-center gap-2">
                <Input
                  autoFocus
                  value={titleDraft}
                  maxLength={300}
                  aria-label="Case title"
                  className="h-10 w-full min-w-[260px] text-base font-bold sm:w-[420px]"
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void saveTitle();
                    if (e.key === 'Escape') setTitleEditing(false);
                  }}
                />
                <Button size="sm" loading={savingTitle} onClick={() => void saveTitle()}>
                  Save
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setTitleEditing(false)}>
                  Cancel
                </Button>
              </span>
            ) : (
              <>
                <h1 className="text-xl font-extrabold tracking-tight text-ink sm:text-2xl">
                  {data.title}
                </h1>
                {perms.triage && (
                  <button
                    aria-label="Edit case title"
                    onClick={() => {
                      setTitleDraft(data.title);
                      setTitleEditing(true);
                    }}
                    className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-brand-600 focus-ring"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                )}
              </>
            )}
            <SeverityBadge severity={data.severity} />
            <CaseStatusBadge status={data.status} />
          </div>
          <p className="mt-1.5 text-[13px] text-muted">
            {brandName ? `${brandName} · ` : ''}Created {formatDate(data.created_at)} · Updated{' '}
            <span title={formatDate(data.updated_at)}>{formatRelativeTime(data.updated_at)}</span>
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {perms.resolve && data.status === 'resolved' &&
            ['confirmed_threat_actioned', 'confirmed_threat_monitoring'].includes(data.resolution_outcome || '') && (
              <Button variant="outline" size="sm" icon={<FileText className="h-4 w-4" />} loading={reportLoading} onClick={() => void openReportDraft()}>
                Takedown draft
              </Button>
            )}
          {perms.assign && (
            <Button variant="outline" size="sm" icon={<UserPlus className="h-4 w-4" />} onClick={() => setAssignOpen(true)}>
              Assign
            </Button>
          )}
          {perms.escalate && (
            <Button
              variant="outline"
              size="sm"
              icon={<Flag className="h-4 w-4" />}
              disabled={!canEscalateNow}
              title={canEscalateNow ? 'Record a partner handoff' : 'Only an assigned case can be escalated'}
              onClick={() => setEscalateOpen(true)}
            >
              Escalate
            </Button>
          )}
          {perms.resolve && (
            <Button
              variant="success"
              size="sm"
              icon={<CheckCircle2 className="h-4 w-4" />}
              disabled={!canResolveNow}
              title={canResolveNow ? 'Close this case with an outcome' : 'This status cannot resolve directly'}
              onClick={() => setResolveOpen(true)}
            >
              Resolve
            </Button>
          )}
          <Dropdown
            trigger={() => (
              <button
                aria-label="More case actions"
                className="rounded-lg border border-line bg-white p-2 text-ink-700 shadow-sm transition-colors hover:border-brand-200 focus-ring"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            )}
            items={[
              {
                label: 'Edit details',
                icon: <Pencil className="h-4 w-4" />,
                disabled: !perms.triage,
                onClick: () => setEditOpen(true),
              },
              {
                label: 'Copy case ID',
                icon: <Copy className="h-4 w-4" />,
                onClick: () => {
                  navigator.clipboard
                    .writeText(data.id)
                    .then(() => toast.success('Case ID copied'))
                    .catch(() => toast.error('Could not copy to clipboard'));
                },
              },
              {
                label: 'Delete case',
                icon: <Trash2 className="h-4 w-4" />,
                danger: true,
                separatorBefore: true,
                disabled: !perms.remove,
                onClick: () => setDeleteOpen(true),
              },
            ]}
          />
        </div>
      </div>

      {/* summary card row */}
      <div className="mb-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle>Case Summary</CardTitle>
            {perms.triage && !summaryEditing && (
              <button
                aria-label="Edit summary"
                onClick={() => {
                  setSummaryDraft(data.summary || '');
                  setSummaryEditing(true);
                }}
                className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-brand-600 focus-ring"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
          </CardHeader>
          <CardContent>
            {summaryEditing ? (
              <>
                <Textarea
                  autoFocus
                  value={summaryDraft}
                  maxLength={10000}
                  aria-label="Case summary"
                  onChange={(e) => setSummaryDraft(e.target.value)}
                />
                <div className="mt-2 flex items-center justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setSummaryEditing(false)}>
                    Cancel
                  </Button>
                  <Button size="sm" loading={savingSummary} onClick={() => void saveSummary()}>
                    Save
                  </Button>
                </div>
              </>
            ) : (
              <Textarea
                readOnly
                value={data.summary || ''}
                aria-label="Case summary"
                placeholder="No summary yet."
                className="min-h-[76px] border-dashed bg-bg/60 text-[13px]"
              />
            )}
            <dl className="mt-2 divide-y divide-line-soft border-t border-line-soft text-[12.5px]">
              <div className="flex justify-between py-1.5">
                <dt className="text-faint">Created</dt>
                <dd className="font-medium text-ink-700">{formatDate(data.created_at)}</dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-faint">Last updated</dt>
                <dd className="font-medium text-ink-700">{formatRelativeTime(data.updated_at)}</dd>
              </div>
              <div className="flex justify-between py-1.5">
                <dt className="text-faint">Created by</dt>
                <dd className="font-medium text-ink-700">
                  {data.created_by?.full_name || data.created_by?.email || '—'}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Risk &amp; Confidence</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center justify-around gap-2 pt-1">
            <ScoreRing value={data.risk_score} label="Risk score" severity={data.severity} size={92} />
            <ScoreRing
              value={data.confidence}
              label="Confidence"
              sublabel={data.confidence === null ? undefined : 'model'}
              size={92}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Assigned investigator</CardTitle>
          </CardHeader>
          <CardContent>
            {data.assigned_to ? (
              <div className="flex items-center gap-3">
                <Avatar name={data.assigned_to.full_name || data.assigned_to.email} size={44} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-ink">
                    {data.assigned_to.full_name || data.assigned_to.email}
                  </p>
                  <p className="truncate text-xs text-muted">
                    {openAssignment
                      ? `Assigned ${formatRelativeTime(openAssignment.assigned_at)}`
                      : 'Current owner'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-ink">Unassigned</p>
                  <p className="text-xs text-muted">No owner for this case yet.</p>
                </div>
                {perms.assign && (
                  <Button size="sm" variant="outline" onClick={() => setAssignOpen(true)}>
                    Assign
                  </Button>
                )}
              </div>
            )}
            {openAssignment?.note && (
              <p className="mt-3 rounded-lg bg-bg px-3 py-2 text-xs text-muted">“{openAssignment.note}”</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle>Status</CardTitle>
            <CaseStatusBadge status={data.status} />
          </CardHeader>
          <CardContent>
            {transitions.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {transitions.map((to) => (
                  <Button
                    key={to}
                    size="sm"
                    variant={to === 'resolved' ? 'success' : to === 'escalated' ? 'danger' : 'outline'}
                    onClick={() => void moveTo(to)}
                  >
                    Move to {statusLabel(to)}
                  </Button>
                ))}
              </div>
            ) : (
              <p className="text-[13px] text-muted">
                No transitions are available to your role from {statusLabel(data.status)}.
              </p>
            )}
            <p className="mt-3 rounded-lg bg-bg px-3 py-2 text-[11.5px] leading-relaxed text-muted">
              Transitions are enforced server-side — permissions are checked on every change (403) and
              workflow rules reject invalid moves (409/422). All results are reported back here.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* tabs */}
      <Tabs
        items={tabItems}
        value={tab}
        onChange={setTab}
        className="mb-4"
      />

      <div role="tabpanel">
        {tab === 'overview' && (
          <OverviewTab data={data} onShowTab={setTab} canOpenEntities={perms.entityRead} />
        )}
        {tab === 'entities' && (
          <EntitiesTab
            data={data}
            canLink={perms.triage}
            canOpenEntities={perms.entityRead}
            onLinked={(updated) => setData(updated)}
          />
        )}
        {tab === 'evidence' && (
          <EvidenceTab
            data={data}
            evidence={evidence}
            canWrite={perms.evidenceWrite && data.status !== 'resolved'}
            onAdded={() => void refresh()}
          />
        )}
        {tab === 'graph' && <GraphTab data={data} canRead={perms.graphRead} />}
        {tab === 'notes' && (
          <NotesTab
            data={data}
            canNote={perms.note}
            authorName={user?.full_name}
          />
        )}
        {tab === 'history' && <HistoryTab data={data} />}
      </div>

      {/* modals */}
      <Modal
        open={!!reportDraft}
        onClose={() => setReportDraft(null)}
        title="Takedown report draft"
        description="Generated from this confirmed case, saved evidence, and investigation history. Review before using; nothing is submitted."
        footer={
          <>
            <Button variant="outline" onClick={() => setReportDraft(null)}>Close</Button>
            {reportDraft && (
              <>
                <Button variant="outline" icon={<Copy className="h-4 w-4" />} onClick={() => {
                  void navigator.clipboard.writeText(reportText(reportDraft)).then(() => toast.success('Draft copied')).catch(() => toast.error('Could not copy the draft'));
                }}>Copy</Button>
                <Button icon={<Download className="h-4 w-4" />} onClick={() => {
                  const blob = new Blob([reportText(reportDraft)], { type: 'text/plain;charset=utf-8' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `anarisk-takedown-${reportDraft.case_number}.txt`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}>Download</Button>
              </>
            )}
          </>
        }
      >
        {reportDraft && <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-bg p-4 text-xs leading-5 text-ink">{reportText(reportDraft)}</pre>}
      </Modal>

      <EditDetailsModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        data={data}
        onSaved={(updated) => setData(updated)}
      />

      <ResolveModal
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        data={data}
        onResolved={(updated) => setData(updated)}
      />

      <EscalateModal
        open={escalateOpen}
        onClose={() => setEscalateOpen(false)}
        data={data}
        onEscalated={(updated) => setData(updated)}
      />

      <ReopenModal
        open={reopenOpen}
        onClose={() => setReopenOpen(false)}
        data={data}
        onReopened={(updated) => setData(updated)}
      />

      <AssignCaseModal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        data={data}
        onAssigned={(updated) => setData(updated)}
      />

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={confirmDelete}
        loading={deleting}
        destructive
        title="Delete this case?"
        confirmLabel="Delete case"
        message={
          <>
            <span className="font-semibold text-ink">{data.case_number}</span> — {data.title}. Notes,
            events, assignments and links are removed permanently. Entities and evidence are kept.
          </>
        }
      />

      {/* audit hint for role-aware behaviour */}
      {!perms.remove && role === 'partner' && (
        <p className="mt-5 text-center text-xs text-faint">
          You are viewing this case with read-only access ({role} role).
        </p>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ *
 * Assign modal (case detail)
 * ------------------------------------------------------------------ */

interface AssignCaseModalProps {
  open: boolean;
  onClose: () => void;
  data: CaseDetail;
  onAssigned: (updated: CaseDetail) => void;
}

const AssignCaseModal: React.FC<AssignCaseModalProps> = ({ open, onClose, data, onAssigned }) => {
  const { toast } = useToast();
  const [users, setUsers] = useState<Array<{ id: string; email: string; full_name: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [userId, setUserId] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setNote('');
    (async () => {
      setLoading(true);
      try {
        const raw = (await caseService.listAssignableUsers()) as unknown as
          | Array<{ id: string; email: string; full_name: string }>
          | { items: Array<{ id: string; email: string; full_name: string }> };
        const items = Array.isArray(raw) ? raw : raw.items || [];
        if (!cancelled) {
          setUsers(items);
          setUserId(data.assigned_to?.id || items[0]?.id || '');
        }
      } catch (e) {
        if (!cancelled) toast.error('Could not load users', errMsg(e, 'Assignable users are unavailable.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, data.id]);

  const submit = async () => {
    if (!userId) return;
    setSaving(true);
    try {
      const updated = await caseService.assign(data.id, userId, note.trim() || undefined);
      toast.success('Assignee updated');
      onAssigned(updated as CaseDetail);
      onClose();
    } catch (e) {
      toast.error('Could not assign this case', errMsg(e, 'The API rejected this assignment.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Assign case"
      description="Assigning an Under Review case moves it to Assigned; resolved cases must be reopened first."
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
          <Field label="Assign to" required htmlFor="cd-assign-user">
            <Select id="cd-assign-user" value={userId} onChange={(e) => setUserId(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Note (optional)" htmlFor="cd-assign-note">
            <Textarea
              id="cd-assign-note"
              value={note}
              maxLength={2000}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Context for the new owner…"
            />
          </Field>
        </div>
      )}
    </Modal>
  );
};

export default CaseDetailPage;
