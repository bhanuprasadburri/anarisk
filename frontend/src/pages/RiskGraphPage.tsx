import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Handle,
  Position,
  BackgroundVariant,
  type Node as RFNode,
  type Edge,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Activity,
  Building2,
  Check,
  ChevronDown,
  ExternalLink,
  Focus,
  Globe,
  Image as ImageIcon,
  Link2,
  ListTree,
  MapPin,
  Network,
  RefreshCw,
  RotateCcw,
  Smartphone,
  UserRound,
  Waypoints,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Button } from '../components/ui/button';
import { Badge, CaseStatusBadge, ProvenanceBadge, SeverityBadge } from '../components/ui/badge';
import { Modal } from '../components/ui/modal';
import { ScoreRing } from '../components/ui/score';
import { CopyButton, KeyValue, LoadingBlock, SearchInput, Skeleton } from '../components/ui/misc';
import { EmptyState, ErrorState } from '../components/ui/table';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { apiRequest } from '../services/apiClient';
import { graphService } from '../services/graphService';
import { entityService } from '../services/entityService';
import { caseService } from '../services/caseService';
import {
  ClusterSummary,
  DigitalEntity,
  EntityType,
  GraphEdge,
  GraphNode,
  GraphResponse,
  InvestigationCase,
  Severity,
} from '../types';
import {
  ENTITY_TYPE_COLORS,
  ENTITY_TYPE_LABELS,
  PLATFORM_LABELS,
  RELATIONSHIP_COLORS,
  RELATIONSHIP_LABELS,
  SEVERITY_LABELS,
} from '../lib/constants';
import { cn } from '../lib/utils';
import { formatRelativeTime, formatDate } from '../lib/formatters';

/* ================================================================== */
/* Types & constants                                                   */
/* ================================================================== */

type EntityNodeData = {
  entity: GraphNode;
  color: string;
  severityHex: string;
  riskLabel: string;
  focused: boolean;
  inCluster: boolean;
  dimmed: boolean;
};

type EntityFlowNode = RFNode<EntityNodeData, 'entity'>;

const ENTITY_ICONS: Record<EntityType, React.ReactNode> = {
  social_profile: <UserRound className="h-3.5 w-3.5" />,
  website: <Globe className="h-3.5 w-3.5" />,
  domain: <Link2 className="h-3.5 w-3.5" />,
  image: <ImageIcon className="h-3.5 w-3.5" />,
  mobile_app: <Smartphone className="h-3.5 w-3.5" />,
};

const SEVERITY_HEX: Record<string, string> = {
  critical: '#E11D48',
  high: '#F04464',
  medium: '#F59E0B',
  low: '#10B981',
  unknown: '#94A3B8',
};

const ENTITY_TYPES: EntityType[] = ['social_profile', 'website', 'domain', 'image', 'mobile_app'];
const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'unknown'];

const MAX_RENDER_NODES = 150;

/* ================================================================== */
/* Custom node                                                         */
/* ================================================================== */

const EntityNodeComponent: React.FC<NodeProps<EntityFlowNode>> = ({ data }) => {
  const { entity, color, severityHex, riskLabel, focused, inCluster, dimmed } = data;
  return (
    <div
      className={cn(
        'nn-node flex w-[196px] items-center gap-2.5 rounded-xl border-2 bg-white px-3 py-2.5 shadow-card transition-shadow hover:shadow-popover',
        focused && 'ring-2 ring-[#4778F5] ring-offset-2 ring-offset-[#f7faff]',
        inCluster && 'ring-2 ring-[#8B5CF6] ring-offset-2 ring-offset-[#f7faff]',
        dimmed && 'opacity-45'
      )}
      style={{ borderColor: `${severityHex}66` }}
      title={`${entity.label} — ${ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type} · risk ${
        entity.risk_score === null || entity.risk_score === undefined ? '—' : entity.risk_score.toFixed(2)
      }`}
      aria-label={`Entity ${entity.label}, ${ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type}, severity ${
        SEVERITY_LABELS[entity.severity] || entity.severity
      }`}
    >
      <Handle type="target" position={Position.Left} />
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
        style={{ backgroundColor: `${color}1A`, color }}
        aria-hidden="true"
      >
        {ENTITY_ICONS[entity.entity_type] || <Network className="h-3.5 w-3.5" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-bold leading-tight text-ink">
          {entity.label.length > 18 ? `${entity.label.slice(0, 18)}…` : entity.label}
        </span>
        <span className="mt-0.5 block text-[10px] font-semibold uppercase tracking-wide text-faint">
          {ENTITY_TYPE_LABELS[entity.entity_type] || entity.entity_type}
        </span>
      </span>
      <span
        className="shrink-0 rounded-full px-1.5 py-0.5 text-[10.5px] font-extrabold tabular-nums"
        style={{ backgroundColor: `${severityHex}18`, color: severityHex }}
      >
        {riskLabel}
      </span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
};

const nodeTypes = { entity: EntityNodeComponent as unknown as React.ComponentType<NodeProps> };

/* ================================================================== */
/* Layout helpers (deterministic, no dependencies)                     */
/* ================================================================== */

type Pos = { x: number; y: number };

/** Group entities by type and place each group on its own ring, groups spread on a big circle. */
function groupLayout(entities: GraphNode[]): Record<string, Pos> {
  const groups = new Map<string, GraphNode[]>();
  for (const n of entities) {
    const g = groups.get(n.entity_type);
    if (g) g.push(n);
    else groups.set(n.entity_type, [n]);
  }
  const keys = Array.from(groups.keys()).sort();
  const out: Record<string, Pos> = {};
  const spread = Math.max(420, entities.length * 16);
  keys.forEach((key, gi) => {
    const angle = (2 * Math.PI * gi) / Math.max(keys.length, 1) - Math.PI / 2;
    const cx = spread * Math.cos(angle);
    const cy = spread * Math.sin(angle);
    const members = groups.get(key)!;
    const ring = 110 + members.length * 26;
    members.forEach((n, i) => {
      const a = (2 * Math.PI * i) / members.length - Math.PI / 2;
      out[n.id] = { x: cx + ring * Math.cos(a), y: cy + ring * Math.sin(a) };
    });
  });
  return out;
}

/** Place new nodes in rings around an anchor point (used when focusing a neighborhood). */
function radialNew(anchor: Pos, index: number, total: number): Pos {
  const perRing = Math.min(Math.max(total, 1), 9);
  const ringIdx = Math.floor(index / perRing);
  const a = (2 * Math.PI * (index % perRing)) / perRing;
  const r = 210 + ringIdx * 130;
  return { x: anchor.x + r * Math.cos(a), y: anchor.y + r * Math.sin(a) };
}

const EMPTY_GRAPH: GraphResponse = { nodes: [], edges: [], node_count: 0, edge_count: 0, cluster_count: 0 };

function mergeGraphs(base: GraphResponse | null, extra: GraphResponse | null): GraphResponse {
  if (!base) return extra ?? EMPTY_GRAPH;
  if (!extra) return base;
  const nodes = [...base.nodes];
  const seenNodes = new Set(nodes.map((n) => n.id));
  for (const n of extra.nodes) {
    if (!seenNodes.has(n.id)) {
      nodes.push(n);
      seenNodes.add(n.id);
    }
  }
  const edges = [...base.edges];
  const seenEdges = new Set(edges.map((e) => e.id));
  for (const e of extra.edges) {
    if (!seenEdges.has(e.id)) {
      edges.push(e);
      seenEdges.add(e.id);
    }
  }
  return { nodes, edges, node_count: nodes.length, edge_count: edges.length, cluster_count: base.cluster_count };
}

/* ================================================================== */
/* Inline multi-select filter                                          */
/* ================================================================== */

interface MultiSelectProps {
  label: string;
  options: Array<{ value: string; label: string; dot?: string }>;
  selected: string[];
  onChange: (values: string[]) => void;
}

const MultiSelect: React.FC<MultiSelectProps> = ({ label, options, selected, onChange }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label} filter${selected.length ? `, ${selected.length} selected` : ''}`}
        className={cn(
          'inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-xl border px-3 text-[13px] font-semibold shadow-sm transition-colors focus-ring',
          'h-9',
          selected.length > 0
            ? 'border-brand-200 bg-brand-50 text-brand-700'
            : 'border-line bg-white text-ink-700 hover:border-brand-200'
        )}
      >
        {label}
        {selected.length > 0 && (
          <span className="rounded-full bg-brand-100 px-1.5 text-[11px] font-bold text-brand-700">
            {selected.length}
          </span>
        )}
        <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
      </button>
      {open && (
        <div
          role="listbox"
          aria-multiselectable="true"
          aria-label={label}
          className="absolute left-0 z-40 mt-2 w-56 animate-scale-in rounded-xl border border-line bg-surface p-1.5 shadow-popover"
        >
          {options.map((o) => {
            const checked = selected.includes(o.value);
            return (
              <label
                key={o.value}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium text-ink-700 transition-colors hover:bg-line-soft"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(o.value)}
                  aria-label={o.label}
                  className="h-3.5 w-3.5 rounded border-line accent-[#4778F5] focus-ring"
                />
                {o.dot && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: o.dot }} />}
                <span className="flex-1">{o.label}</span>
                {checked && <Check className="h-3.5 w-3.5 text-brand-600" aria-hidden="true" />}
              </label>
            );
          })}
          {selected.length > 0 && (
            <button
              onClick={() => onChange([])}
              className="mt-1 w-full rounded-lg border-t border-line-soft px-3 py-1.5 text-left text-[12px] font-semibold text-muted transition-colors hover:text-ink"
            >
              Clear {label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

/* ================================================================== */
/* Page                                                                */
/* ================================================================== */

export const RiskGraphPage: React.FC = () => {
  const navigate = useNavigate();
  const { activeBrand } = useAuth();
  const { toast } = useToast();
  const brandId = activeBrand?.id;

  /* ---------------- Graph data ---------------- */
  const [baseGraph, setBaseGraph] = useState<GraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [fetchNonce, setFetchNonce] = useState(0);
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [sevFilter, setSevFilter] = useState<string[]>([]);

  const fetchGraph = useCallback(async () => {
    setGraphLoading(true);
    setGraphError(null);
    try {
      const g = await graphService.getGraph({
        brand_id: brandId,
        entity_type: typeFilter.length ? typeFilter : undefined,
        severity: sevFilter.length ? sevFilter : undefined,
      });
      setBaseGraph(g);
    } catch (err) {
      setGraphError(err instanceof Error ? err.message : 'Failed to load the graph.');
    } finally {
      setGraphLoading(false);
    }
  }, [brandId, typeFilter, sevFilter]);

  useEffect(() => {
    void fetchGraph();
  }, [fetchGraph, fetchNonce]);

  /* ---------------- Focus (search / neighbors) ---------------- */
  const [neighborhood, setNeighborhood] = useState<{ focusId: string; graph: GraphResponse } | null>(null);
  const [neighborhoodLoading, setNeighborhoodLoading] = useState(false);

  const viewGraph = useMemo(
    () => mergeGraphs(baseGraph, neighborhood?.graph ?? null),
    [baseGraph, neighborhood]
  );

  const focusEntity = useCallback(
    async (entityId: string) => {
      setNeighborhoodLoading(true);
      try {
        const g = await graphService.getNeighbors(entityId, 2);
        setNeighborhood({ focusId: entityId, graph: g });
      } catch (err) {
        toast.error('Could not load neighbors', err instanceof Error ? err.message : undefined);
      } finally {
        setNeighborhoodLoading(false);
      }
    },
    [toast]
  );

  const clearFocus = useCallback(() => {
    setNeighborhood(null);
  }, []);

  /* ---------------- Capping ---------------- */
  const cappedView = useMemo(() => {
    const g = viewGraph;
    if (g.nodes.length <= MAX_RENDER_NODES) {
      return { nodes: g.nodes, edges: g.edges, totalNodes: g.node_count, capped: false };
    }
    const sorted = [...g.nodes].sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0));
    const kept = sorted.slice(0, MAX_RENDER_NODES);
    const ids = new Set(kept.map((n) => n.id));
    return {
      nodes: kept,
      edges: g.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
      totalNodes: g.node_count,
      capped: true,
    };
  }, [viewGraph]);

  /* ---------------- Selection ---------------- */
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [entityDetail, setEntityDetail] = useState<DigitalEntity | null>(null);
  const [entityDetailLoading, setEntityDetailLoading] = useState(false);
  const [entityDetailError, setEntityDetailError] = useState<string | null>(null);
  const [entityDetailRetry, setEntityDetailRetry] = useState(0);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [hoverEdge, setHoverEdge] = useState<{ edge: GraphEdge; x: number; y: number } | null>(null);
  const [clusterHighlight, setClusterHighlight] = useState<string[] | null>(null);

  const selectedNode = useMemo(
    () => cappedView.nodes.find((n) => n.id === selectedEntityId) || viewGraph.nodes.find((n) => n.id === selectedEntityId) || null,
    [cappedView.nodes, viewGraph.nodes, selectedEntityId]
  );

  useEffect(() => {
    if (!selectedEntityId) {
      setEntityDetail(null);
      setEntityDetailError(null);
      return;
    }
    let cancelled = false;
    setEntityDetailLoading(true);
    setEntityDetailError(null);
    entityService
      .getEntity(selectedEntityId)
      .then((e) => {
        if (!cancelled) {
          setEntityDetail(e);
          setEntityDetailLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setEntityDetailError(err.message || 'Failed to load entity.');
          setEntityDetailLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEntityId, entityDetailRetry]);

  /* ---------------- React Flow state ---------------- */
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<EntityFlowNode>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const posRef = useRef<Record<string, Pos>>({});
  const instanceRef = useRef<ReactFlowInstance<EntityFlowNode, Edge> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const clusterSet = useMemo(() => new Set(clusterHighlight || []), [clusterHighlight]);

  useEffect(() => {
    const { nodes: keptEntities, edges: keptEdges } = cappedView;
    const layout = groupLayout(keptEntities);
    const anchor = neighborhood?.focusId ? posRef.current[neighborhood.focusId] : null;
    const missing = keptEntities.filter((e) => !posRef.current[e.id]);
    let newIdx = 0;
    const newNodes: EntityFlowNode[] = keptEntities.map((entity) => {
      const existing = posRef.current[entity.id];
      const pos = existing ?? (anchor ? radialNew(anchor, newIdx++, missing.length) : layout[entity.id] ?? { x: 0, y: 0 });
      return {
        id: entity.id,
        type: 'entity',
        position: pos,
        data: {
          entity,
          color: ENTITY_TYPE_COLORS[entity.entity_type] || '#64748B',
          severityHex: SEVERITY_HEX[entity.severity] || SEVERITY_HEX.unknown,
          riskLabel:
            entity.risk_score === null || entity.risk_score === undefined
              ? '—'
              : entity.risk_score.toFixed(2),
          focused: entity.id === selectedEntityId || entity.id === neighborhood?.focusId,
          inCluster: clusterSet.has(entity.id),
          dimmed: clusterSet.size > 0 && !clusterSet.has(entity.id),
        },
      };
    });
    const newEdges = keptEdges
      .filter((e) => newNodes.some((n) => n.id === e.source) && newNodes.some((n) => n.id === e.target))
      .map((e) => {
        const color = RELATIONSHIP_COLORS[e.relationship_type] || '#94A3B8';
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: 'default',
          animated: e.relationship_type === 'coordinated_behavior',
          label: RELATIONSHIP_LABELS[e.relationship_type] || e.relationship_type,
          labelStyle: { fill: '#475569', fontWeight: 600, fontSize: 10 },
          labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
          labelBgPadding: [5, 3] as [number, number],
          style: { stroke: color, cursor: 'pointer' },
          markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15, color },
        };
      });
    setRfNodes(newNodes);
    setRfEdges(newEdges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cappedView, selectedEntityId, neighborhood, clusterSet, setRfNodes, setRfEdges]);

  const edgeMap = useMemo(() => new Map(viewGraph.edges.map((e) => [e.id, e])), [viewGraph.edges]);

  const fitToScreen = useCallback(() => {
    instanceRef.current?.fitView({ padding: 0.2, duration: 400, maxZoom: 1.1 });
  }, []);

  const resetLayout = useCallback(() => {
    // Drop all stored (user-moved and computed) positions and recompute from the API data.
    posRef.current = {};
    setFetchNonce((k) => k + 1);
    setTimeout(() => instanceRef.current?.fitView({ padding: 0.2, duration: 400, maxZoom: 1.1 }), 400);
  }, []);

  const onNodeDragStop = useCallback((_event: unknown, _node: EntityFlowNode, nodes: EntityFlowNode[]) => {
    for (const n of nodes) posRef.current[n.id] = { x: n.position.x, y: n.position.y };
  }, []);

  /* ---------------- Entity search ---------------- */
  const [searchText, setSearchText] = useState('');
  const [searchResults, setSearchResults] = useState<DigitalEntity[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const searchWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!searchOpen) return;
    const onClick = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) setSearchOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSearchOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [searchOpen]);

  useEffect(() => {
    if (searchText.trim().length < 2) {
      setSearchResults([]);
      setSearchOpen(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const t = setTimeout(() => {
      entityService
        .listEntities({ q: searchText.trim(), page_size: 5 })
        .then((res) => {
          if (cancelled) return;
          setSearchResults(res.items);
          setSearchOpen(true);
          setSearching(false);
        })
        .catch(() => {
          if (!cancelled) {
            setSearchResults([]);
            setSearchOpen(false);
            setSearching(false);
          }
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [searchText]);

  const pickSearchResult = useCallback(
    (entity: DigitalEntity) => {
      setSearchOpen(false);
      setSearchText(entity.display_name);
      setSelectedEntityId(entity.id);
      void focusEntity(entity.id);
    },
    [focusEntity]
  );

  /* ---------------- Rebuild ---------------- */
  const [rebuilding, setRebuilding] = useState(false);
  const rebuildGraph = useCallback(async () => {
    setRebuilding(true);
    try {
      const res = await graphService.rebuild(brandId || undefined);
      toast.success(
        'Relationship graph rebuilt',
        `${res.edge_count} relationships across ${res.node_count} entities (${res.cluster_count} clusters).`
      );
      posRef.current = {};
      setFetchNonce((k) => k + 1);
      if (clustersOpen) loadClusters();
    } catch (err) {
      toast.error('Rebuild failed', err instanceof Error ? err.message : undefined);
    } finally {
      setRebuilding(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, toast]);

  /* ---------------- Clusters ---------------- */
  const [clustersOpen, setClustersOpen] = useState(false);
  const [clusters, setClusters] = useState<ClusterSummary[] | null>(null);
  const [clustersLoading, setClustersLoading] = useState(false);
  const [clustersError, setClustersError] = useState<string | null>(null);

  const loadClusters = useCallback(async () => {
    setClustersLoading(true);
    setClustersError(null);
    try {
      const res = await graphService.getClusters({ brand_id: brandId });
      setClusters(res);
    } catch (err) {
      setClustersError(err instanceof Error ? err.message : 'Failed to load clusters.');
    } finally {
      setClustersLoading(false);
    }
  }, [brandId]);

  useEffect(() => {
    if (clustersOpen && !clusters && !clustersLoading) void loadClusters();
  }, [clustersOpen, clusters, clustersLoading, loadClusters]);

  /* ---------------- Add to case ---------------- */
  const [caseModalOpen, setCaseModalOpen] = useState(false);
  const [cases, setCases] = useState<InvestigationCase[] | null>(null);
  const [casesLoading, setCasesLoading] = useState(false);
  const [linkingCaseId, setLinkingCaseId] = useState<string | null>(null);

  const openCaseModal = useCallback(() => {
    setCaseModalOpen(true);
    if (cases) return;
    setCasesLoading(true);
    caseService
      .listCases({ page_size: 20 })
      .then((res) => setCases(res.items))
      .catch((err: Error) => {
        toast.error('Failed to load cases', err.message);
        setCaseModalOpen(false);
      })
      .finally(() => setCasesLoading(false));
  }, [cases, toast]);

  const linkToCase = useCallback(
    async (caseItem: InvestigationCase) => {
      if (!selectedEntityId) return;
      setLinkingCaseId(caseItem.id);
      try {
        await caseService.linkEntity(caseItem.id, selectedEntityId);
        toast.success('Entity added to case', `${caseItem.case_number} — ${caseItem.title}`);
        setCaseModalOpen(false);
      } catch (err) {
        toast.error('Could not link entity', err instanceof Error ? err.message : undefined);
      } finally {
        setLinkingCaseId(null);
      }
    },
    [selectedEntityId, toast]
  );

  /* ---------------- Edge interactions ---------------- */
  const handleEdgeEnter = useCallback(
    (event: React.MouseEvent, edgeId: string) => {
      const rel = edgeMap.get(edgeId);
      const rect = wrapRef.current?.getBoundingClientRect();
      if (!rel || !rect) return;
      setHoverEdge({ edge: rel, x: event.clientX - rect.left, y: event.clientY - rect.top });
    },
    [edgeMap]
  );

  /* ---------------- Legend ---------------- */
  const [legendOpen, setLegendOpen] = useState(() => typeof window === 'undefined' || window.innerWidth >= 640);

  /* ---------------- Derived ---------------- */
  const hasFilters = typeFilter.length > 0 || sevFilter.length > 0;
  const clearFilters = () => {
    setTypeFilter([]);
    setSevFilter([]);
  };

  const renderPanel = () => {
    if (!selectedEntityId) return null;
    return (
      <aside
        className={cn(
          'z-30 flex w-80 shrink-0 flex-col border-line bg-surface',
          'fixed inset-y-0 right-0 z-40 shadow-2xl lg:static lg:z-auto lg:border-l lg:shadow-none'
        )}
        aria-label="Entity details panel"
      >
        <div className="flex items-start justify-between gap-2 border-b border-line-soft px-4 py-3.5">
          <div className="min-w-0">
            <p className="truncate text-[14px] font-bold text-ink">
              {entityDetail?.display_name || selectedNode?.label || 'Entity'}
            </p>
            <p className="mt-0.5 text-[11px] font-semibold uppercase tracking-wider text-faint">
              {selectedNode ? ENTITY_TYPE_LABELS[selectedNode.entity_type] || selectedNode.entity_type : 'Entity'}
            </p>
          </div>
          <button
            onClick={() => setSelectedEntityId(null)}
            aria-label="Close entity panel"
            className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4">
          {entityDetailLoading && (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-28" />
            </div>
          )}
          {!entityDetailLoading && entityDetailError && (
            <ErrorState
              title="Could not load entity"
              message={entityDetailError}
              onRetry={() => setEntityDetailRetry((n) => n + 1)}
            />
          )}
          {!entityDetailLoading && !entityDetailError && (
            <>
              <div className="flex items-center gap-4 rounded-xl border border-line-soft bg-bg/60 p-3.5">
                <ScoreRing value={entityDetail?.current_risk_score ?? selectedNode?.risk_score ?? null} size={72} thickness={7} />
                <dl className="min-w-0 flex-1 space-y-1.5 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-faint">Severity</dt>
                    <dd>
                      <SeverityBadge severity={entityDetail?.current_severity ?? selectedNode?.severity} />
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-faint">Confidence</dt>
                    <dd className="font-semibold tabular-nums text-ink-700">
                      {(entityDetail?.current_confidence ?? selectedNode?.confidence ?? null)?.toFixed?.(2) ?? '—'}
                    </dd>
                  </div>
                </dl>
              </div>
              <dl className="mt-2 divide-y divide-line-soft">
                <KeyValue
                  label="Type"
                  value={
                    <span className="flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: ENTITY_TYPE_COLORS[selectedNode?.entity_type || ''] || '#64748B' }}
                      />
                      {selectedNode ? ENTITY_TYPE_LABELS[selectedNode.entity_type] || selectedNode.entity_type : '—'}
                    </span>
                  }
                />
                <KeyValue
                  label="Platform"
                  value={
                    entityDetail?.platform
                      ? PLATFORM_LABELS[entityDetail.platform] || entityDetail.platform
                      : '—'
                  }
                />
                <KeyValue
                  label="Provenance"
                  value={<ProvenanceBadge provenance={entityDetail?.provenance ?? selectedNode?.provenance} />}
                />
                <KeyValue
                  label="Last seen"
                  value={
                    <span title={formatDate(entityDetail?.last_seen_at)}>
                      {formatRelativeTime(entityDetail?.last_seen_at)}
                    </span>
                  }
                />
                {entityDetail?.source_url && (
                  <KeyValue
                    label="Source"
                    value={
                      <a
                        href={entityDetail.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="break-all text-brand-600 hover:underline"
                      >
                        {entityDetail.source_url}
                      </a>
                    }
                  />
                )}
                <KeyValue
                  label="Canonical ID"
                  value={
                    <span className="flex items-center gap-1 font-mono text-[11.5px]">
                      <span className="truncate">{entityDetail?.canonical_id || selectedNode?.id || '—'}</span>
                      {(entityDetail?.canonical_id || selectedNode?.id) && (
                        <CopyButton text={entityDetail?.canonical_id || selectedNode?.id || ''} label="Copy canonical ID" />
                      )}
                    </span>
                  }
                />
              </dl>
              <div className="mt-4 space-y-2">
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  icon={<ExternalLink className="h-3.5 w-3.5" />}
                  onClick={() => navigate(`/entities/${selectedEntityId}`)}
                >
                  Open entity details
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  loading={neighborhoodLoading}
                  icon={<Focus className="h-3.5 w-3.5" />}
                  onClick={() => void focusEntity(selectedEntityId)}
                >
                  Focus neighbors
                </Button>
                <Button variant="outline" size="sm" className="w-full" onClick={openCaseModal}>
                  Add to case
                </Button>
              </div>
            </>
          )}
        </div>
      </aside>
    );
  };

  /* ---------------- Render ---------------- */
  return (
    <div className="flex flex-col lg:h-[calc(100vh-112px)]">
      <PageHeader
        title="Risk Graph"
        description="How monitored entities connect — relationships derived from observable evidence, grouped into investigation-ready clusters."
        className="mb-4"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="outline" aria-live="polite">
              <Network className="h-3 w-3" aria-hidden="true" />
              {cappedView.nodes.length} entities · {cappedView.edges.length} relationships
            </Badge>
            {cappedView.capped && (
              <Badge tone="warning">
                Showing {cappedView.nodes.length} of {cappedView.totalNodes} — refine filters
              </Badge>
            )}
            {neighborhood && (
              <button
                onClick={clearFocus}
                className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-700 transition-colors hover:bg-brand-100 focus-ring"
                aria-label="Clear focused neighborhood"
              >
                Focused view
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            )}
          </div>
        }
      >
        {/* Toolbar */}
        <div className="mt-4 flex flex-wrap items-center gap-2.5">
          <div
            ref={searchWrapRef}
            className="relative w-full sm:w-64"
            onKeyDown={(e) => {
              // SearchInput is a shared component; Enter-to-focus-first-result is handled here.
              if (e.key === 'Enter' && searchResults[0]) pickSearchResult(searchResults[0]);
            }}
          >
            <SearchInput
              value={searchText}
              onChange={setSearchText}
              placeholder="Search entities to focus…"
              className="w-full"
            />
            {(searching || (searchOpen && searchResults.length > 0)) && (
              <div className="absolute left-0 right-0 top-11 z-40 animate-scale-in rounded-xl border border-line bg-surface p-1.5 shadow-popover">
                {searching && searchResults.length === 0 && (
                  <p className="px-3 py-2 text-[13px] text-muted">Searching…</p>
                )}
                {searchResults.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => pickSearchResult(r)}
                    className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-brand-50 focus-ring"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-semibold text-ink">{r.display_name}</span>
                      <span className="block text-[11px] text-muted">
                        {ENTITY_TYPE_LABELS[r.entity_type] || r.entity_type}
                        {r.platform ? ` · ${r.platform}` : ''}
                      </span>
                    </span>
                    <SeverityBadge severity={r.current_severity} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <MultiSelect
            label="Entity type"
            options={ENTITY_TYPES.map((t) => ({
              value: t,
              label: ENTITY_TYPE_LABELS[t] || t,
              dot: ENTITY_TYPE_COLORS[t],
            }))}
            selected={typeFilter}
            onChange={setTypeFilter}
          />
          <MultiSelect
            label="Risk severity"
            options={SEVERITIES.map((s) => ({
              value: s,
              label: SEVERITY_LABELS[s] || s,
              dot: SEVERITY_HEX[s],
            }))}
            selected={sevFilter}
            onChange={setSevFilter}
          />
          <Button variant="outline" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={resetLayout}>
            Reset layout
          </Button>
          <Button variant="outline" size="sm" icon={<MapPin className="h-3.5 w-3.5" />} onClick={fitToScreen}>
            Fit to screen
          </Button>
          <Button
            variant="outline"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            loading={rebuilding}
            onClick={() => void rebuildGraph()}
          >
            Rebuild relationships
          </Button>
          <Button
            variant={clustersOpen ? 'secondary' : 'outline'}
            size="sm"
            icon={<ListTree className="h-3.5 w-3.5" />}
            aria-pressed={clustersOpen}
            onClick={() => setClustersOpen((o) => !o)}
          >
            Clusters
          </Button>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>
      </PageHeader>

      {/* Workspace */}
      <div className="flex min-h-0 flex-1 gap-0">
        <div ref={wrapRef} className="relative h-[62vh] min-h-[380px] overflow-hidden rounded-2xl border border-line lg:h-auto lg:min-h-0 lg:flex-1">
          {baseGraph && (
            <ReactFlow<EntityFlowNode>
              nodes={rfNodes}
              edges={rfEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_e, node) => {
                setSelectedEdge(null);
                setSelectedEntityId(node.id);
              }}
              onEdgeClick={(_e, edge) => {
                const rel = edgeMap.get(edge.id);
                if (rel) setSelectedEdge(rel);
              }}
              onEdgeMouseEnter={(e, edge) => handleEdgeEnter(e, edge.id)}
              onEdgeMouseLeave={() => setHoverEdge(null)}
              onPaneClick={() => {
                setSelectedEdge(null);
                setHoverEdge(null);
              }}
              onNodeDragStop={onNodeDragStop}
              onInit={(instance) => {
                instanceRef.current = instance;
                instance.fitView({ padding: 0.2, maxZoom: 1.1 });
              }}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
              minZoom={0.1}
              maxZoom={1.8}
              nodesConnectable={false}
              proOptions={{ hideAttribution: true }}
              aria-label="Risk relationship graph"
            >
              <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#c8d7ef" />
              <Controls showInteractive={false} />
              <MiniMap<EntityFlowNode>
                pannable
                zoomable
                position="bottom-right"
                maskColor="rgba(241,246,255,0.75)"
                nodeColor={(n) => n.data.severityHex || '#94A3B8'}
                style={{ width: 150, height: 100 }}
              />
            </ReactFlow>
          )}

          {/* Loading overlay */}
          {graphLoading && !baseGraph && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-bg/70">
              <LoadingBlock label="Loading relationship graph…" />
            </div>
          )}
          {graphLoading && baseGraph && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-bg/50">
              <Skeleton className="h-8 w-8 rounded-full" />
            </div>
          )}

          {/* Error state */}
          {graphError && !baseGraph && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-surface/90 px-6">
              <ErrorState
                title="Could not load the graph"
                message={graphError}
                onRetry={() => setFetchNonce((k) => k + 1)}
              />
            </div>
          )}

          {/* Empty state */}
          {!graphLoading && !graphError && baseGraph && viewGraph.nodes.length === 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-surface/80 px-6">
              <EmptyState
                icon={<Waypoints className="h-6 w-6" />}
                title="No relationships match"
                description={
                  hasFilters
                    ? 'No entities match the current filters. Clear them to see the full graph.'
                    : 'Submit or collect entities, then rebuild relationships to populate the graph.'
                }
                action={
                  hasFilters ? (
                    <Button variant="outline" size="sm" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  ) : (
                    <Button variant="outline" size="sm" onClick={() => setFetchNonce((k) => k + 1)}>
                      Reload
                    </Button>
                  )
                }
              />
            </div>
          )}

          {/* Edge hover tooltip */}
          {hoverEdge && (
            <div
              className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-lg bg-ink px-2.5 py-1.5 text-[11px] font-medium text-white shadow-popover"
              style={{ left: hoverEdge.x, top: hoverEdge.y - 10 }}
              role="tooltip"
            >
              <span className="font-bold">{RELATIONSHIP_LABELS[hoverEdge.edge.relationship_type]}</span>
              {' · confidence '}
              <span className="tabular-nums">{hoverEdge.edge.confidence.toFixed(2)}</span>
              {hoverEdge.edge.evidence_note && (
                <span className="block max-w-[240px] truncate opacity-80">{hoverEdge.edge.evidence_note}</span>
              )}
            </div>
          )}

          {/* Edge details panel */}
          {selectedEdge && (
            <div className="absolute right-3 top-3 z-20 w-80 animate-scale-in rounded-2xl border border-line bg-surface p-4 shadow-popover">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className="h-0.5 w-6 rounded-full"
                    style={{ background: RELATIONSHIP_COLORS[selectedEdge.relationship_type] || '#94A3B8' }}
                    aria-hidden="true"
                  />
                  <p className="text-[13px] font-bold text-ink">
                    {RELATIONSHIP_LABELS[selectedEdge.relationship_type] || selectedEdge.relationship_type}
                  </p>
                </div>
                <button
                  onClick={() => setSelectedEdge(null)}
                  aria-label="Close relationship details"
                  className="rounded-lg p-1 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <dl className="mt-2 divide-y divide-line-soft">
                <KeyValue label="Confidence" value={<span className="tabular-nums">{selectedEdge.confidence.toFixed(2)}</span>} />
                <KeyValue label="Evidence" value={selectedEdge.evidence_note || '—'} />
                <KeyValue
                  label="Source"
                  value={
                    <span className="truncate font-mono text-[11px]" title={selectedEdge.source}>
                      {viewGraph.nodes.find((n) => n.id === selectedEdge.source)?.label || selectedEdge.source}
                    </span>
                  }
                />
                <KeyValue
                  label="Target"
                  value={
                    <span className="truncate font-mono text-[11px]" title={selectedEdge.target}>
                      {viewGraph.nodes.find((n) => n.id === selectedEdge.target)?.label || selectedEdge.target}
                    </span>
                  }
                />
                <KeyValue
                  label="Created"
                  value={<span className="text-muted">{formatDate(selectedEdge.created_at)}</span>}
                />
                {selectedEdge.auto_generated && (
                  <KeyValue label="Origin" value={<Badge tone="info">Auto-derived from evidence</Badge>} />
                )}
              </dl>
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="outline" className="flex-1" onClick={() => navigate(`/entities/${selectedEdge.source}`)}>
                  Open source
                </Button>
                <Button size="sm" variant="outline" className="flex-1" onClick={() => navigate(`/entities/${selectedEdge.target}`)}>
                  Open target
                </Button>
              </div>
            </div>
          )}

          {/* Clusters panel */}
          {clustersOpen && (
            <div className="absolute left-3 top-3 z-20 flex max-h-[75%] w-[320px] max-w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-popover">
              <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
                <p className="text-[13px] font-bold text-ink">Connected clusters</p>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => void loadClusters()}
                    aria-label="Refresh clusters"
                    className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setClustersOpen(false)}
                    aria-label="Close clusters panel"
                    className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto scrollbar-thin p-3">
                {clustersLoading && (
                  <div className="space-y-2">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-20 w-full" />
                  </div>
                )}
                {!clustersLoading && clustersError && (
                  <ErrorState title="Could not load clusters" message={clustersError} onRetry={() => void loadClusters()} />
                )}
                {!clustersLoading && !clustersError && clusters && clusters.length === 0 && (
                  <p className="px-1 py-2 text-[12.5px] text-muted">
                    No connected clusters yet — rebuild relationships to derive them from evidence.
                  </p>
                )}
                {!clustersLoading &&
                  clusters?.map((c) => {
                    const active = !!clusterHighlight && c.entity_ids.every((id) => clusterHighlight.includes(id));
                    return (
                      <div
                        key={c.cluster_id}
                        className={cn(
                          'rounded-xl border p-3 transition-colors',
                          active ? 'border-violet-200 bg-violet-50' : 'border-line-soft bg-bg/50'
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-[12.5px] font-bold leading-snug text-ink">{c.headline}</p>
                          <SeverityBadge severity={c.max_severity} className="shrink-0" />
                        </div>
                        <p className="mt-1 text-[11.5px] text-muted">
                          {c.size} entities · max risk{' '}
                          <span className="font-semibold tabular-nums">
                            {c.max_risk_score === null || c.max_risk_score === undefined ? '—' : c.max_risk_score.toFixed(2)}
                          </span>
                          {c.propose_for_investigation && (
                            <span className="ml-1 font-semibold text-warning-600">· proposal</span>
                          )}
                        </p>
                        {c.propose_for_investigation && c.proposal_reasons.length > 0 && (
                          <p className="mt-1 text-[11px] leading-relaxed text-faint">{c.proposal_reasons.join(' · ')}</p>
                        )}
                        <button
                          onClick={() => setClusterHighlight(active ? null : c.entity_ids)}
                          className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1 text-[11.5px] font-semibold text-ink-700 shadow-sm transition-colors hover:border-brand-200 hover:text-brand-700 focus-ring"
                        >
                          <Focus className="h-3 w-3" aria-hidden="true" />
                          {active ? 'Clear highlight' : 'Focus cluster'}
                        </button>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Legend */}
          <div className="absolute bottom-3 left-3 z-10">
            {legendOpen ? (
              <div className="w-[236px] rounded-2xl border border-line bg-surface/95 p-3.5 shadow-popover backdrop-blur">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-faint">Legend</p>
                  <button
                    onClick={() => setLegendOpen(false)}
                    aria-label="Hide legend"
                    className="rounded p-0.5 text-faint transition-colors hover:text-ink focus-ring"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="mt-2.5 text-[10px] font-bold uppercase tracking-wider text-faint">Relationships</p>
                <ul className="mt-1 space-y-1">
                  {Object.entries(RELATIONSHIP_LABELS).map(([k, label]) => (
                    <li key={k} className="flex items-center gap-2 text-[11px] font-medium text-ink-700">
                      <span
                        className="h-0.5 w-5 shrink-0 rounded-full"
                        style={{ background: RELATIONSHIP_COLORS[k] || '#94A3B8' }}
                        aria-hidden="true"
                      />
                      {label}
                    </li>
                  ))}
                </ul>
                <p className="mt-2.5 text-[10px] font-bold uppercase tracking-wider text-faint">Entity types</p>
                <ul className="mt-1 grid grid-cols-1 gap-1">
                  {Object.entries(ENTITY_TYPE_LABELS).map(([k, label]) => (
                    <li key={k} className="flex items-center gap-2 text-[11px] font-medium text-ink-700">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: ENTITY_TYPE_COLORS[k] || '#64748B' }}
                        aria-hidden="true"
                      />
                      {label}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <button
                onClick={() => setLegendOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-surface/95 px-3 py-1.5 text-[11.5px] font-bold text-ink-700 shadow-popover backdrop-blur transition-colors hover:border-brand-200 focus-ring"
                aria-label="Show legend"
              >
                <Activity className="h-3.5 w-3.5 text-brand-500" aria-hidden="true" />
                Legend
              </button>
            )}
          </div>
        </div>

        {/* Entity detail panel (in-layout on lg, drawer below) */}
        {renderPanel()}
        {selectedEntityId && (
          <div
            className="fixed inset-0 z-20 bg-ink/20 backdrop-blur-[1px] lg:hidden"
            onClick={() => setSelectedEntityId(null)}
            aria-hidden="true"
          />
        )}
      </div>

      {/* Add to case modal */}
      <Modal
        open={caseModalOpen}
        onClose={() => setCaseModalOpen(false)}
        title="Add entity to a case"
        description={selectedNode ? `${selectedNode.label} will be linked to the case you choose.` : undefined}
      >
        {casesLoading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {!casesLoading && cases && cases.length === 0 && (
          <EmptyState
            title="No cases available"
            description="Create an investigation case first, then link entities to it from here."
            action={<Button size="sm" onClick={() => navigate('/cases')}>Go to cases</Button>}
          />
        )}
        {!casesLoading &&
          cases?.map((c) => (
            <button
              key={c.id}
              onClick={() => void linkToCase(c)}
              disabled={linkingCaseId !== null}
              className="flex w-full items-center justify-between gap-3 rounded-xl border border-line-soft px-3.5 py-3 text-left transition-colors hover:border-brand-200 hover:bg-brand-50/60 focus-ring disabled:opacity-60"
            >
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-bold text-ink">
                  {c.case_number} — {c.title}
                </span>
                <span className="mt-0.5 flex items-center gap-2">
                  <CaseStatusBadge status={c.status} />
                  <span className="text-[11px] text-muted">{c.entity_count} entities</span>
                </span>
              </span>
              {linkingCaseId === c.id ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-200 border-t-brand-500" role="status" aria-label="Linking" />
              ) : (
                <Building2 className="h-4 w-4 shrink-0 text-faint" aria-hidden="true" />
              )}
            </button>
          ))}
      </Modal>
    </div>
  );
};

export default RiskGraphPage;
