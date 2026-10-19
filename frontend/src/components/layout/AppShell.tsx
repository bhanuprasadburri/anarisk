import React, { useMemo, useState } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Globe, Network, BrainCircuit, Briefcase, Smartphone, FileSearch,
  BarChart3, Settings, Shield, Menu, X, Search, Bell, ChevronDown, LogOut, User as UserIcon,
  Building2, Users, SlidersHorizontal, Activity, SearchCheck, Sparkles, Radar, MessageSquare,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { cn } from '../../lib/utils';
import { Avatar } from '../ui/misc';
import { Dropdown } from '../ui/tabs';
import { notificationsPopover } from './NotificationsPopover';
import { USER_ROLE_LABELS } from '../../lib/constants';

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  /** Minimum permission required to see this item (mirrors the backend matrix). */
  perm?: string;
}

export const NAV_SECTIONS: Array<{ title?: string; items: NavItem[] }> = [
  {
    items: [
      { to: '/dashboard', label: 'Overview', icon: <LayoutDashboard className="h-[18px] w-[18px]" />, perm: 'dashboard:read' },
      { to: '/assets', label: 'Digital Assets', icon: <Globe className="h-[18px] w-[18px]" />, perm: 'entity:read' },
      { to: '/threat-intelligence', label: 'Threat Intelligence', icon: <BrainCircuit className="h-[18px] w-[18px]" />, perm: 'entity:read' },
      { to: '/investigate', label: 'Investigate', icon: <SearchCheck className="h-[18px] w-[18px]" />, perm: 'entity:read' },
      { to: '/assistant', label: 'AI Assistant', icon: <Sparkles className="h-[18px] w-[18px]" />, perm: 'entity:read' },
      { to: '/alerts', label: 'Alerts', icon: <Radar className="h-[18px] w-[18px]" /> },
      { to: '/risk-graph', label: 'Risk Graph', icon: <Network className="h-[18px] w-[18px]" />, perm: 'graph:read' },
      { to: '/cases', label: 'Investigations', icon: <Briefcase className="h-[18px] w-[18px]" />, perm: 'case:read' },
      { to: '/mobile-apps', label: 'Mobile Apps', icon: <Smartphone className="h-[18px] w-[18px]" />, perm: 'entity:read' },
      { to: '/evidence', label: 'Evidence Center', icon: <FileSearch className="h-[18px] w-[18px]" />, perm: 'evidence:read' },
      { to: '/reports', label: 'Reports', icon: <BarChart3 className="h-[18px] w-[18px]" />, perm: 'dashboard:read' },
      { to: '/settings', label: 'Settings', icon: <Settings className="h-[18px] w-[18px]" /> },
    ],
  },
];

const Sidebar: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const location = useLocation();
  const { hasPermission } = useAuth();
  const settingsActive = location.pathname.startsWith('/settings');

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-semibold transition-all duration-150',
      isActive
        ? 'bg-brand-50 text-brand-700 shadow-[inset_3px_0_0_0_#4778F5]'
        : 'text-ink-500 hover:bg-line-soft hover:text-ink'
    );

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-30 bg-ink/30 backdrop-blur-[1px] lg:hidden" onClick={onClose} />
      )}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-[248px] flex-col border-r border-line bg-surface transition-transform duration-200 lg:translate-x-0',
          open ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-sm">
              <Shield className="h-5 w-5" />
            </span>
            <div className="leading-tight">
              <p className="text-[15px] font-extrabold tracking-tight text-ink">ANARISK</p>
              <p className="-mt-0.5 text-[10px] font-bold uppercase tracking-[0.18em] text-brand-500">Digital Risk</p>
            </div>
          </div>
          <button className="rounded-lg p-1.5 text-faint hover:bg-line-soft lg:hidden" onClick={onClose} aria-label="Close menu">
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto scrollbar-thin px-3 py-3" aria-label="Main navigation">
          {NAV_SECTIONS.map((section, si) => (
            <React.Fragment key={si}>
              {section.title && (
                <p className="px-3 pb-1 pt-3 text-[10px] font-bold uppercase tracking-[0.14em] text-faint">
                  {section.title}
                </p>
              )}
              {section.items
                .filter((item) => !item.perm || hasPermission(item.perm))
                .map((item) => (
                  <NavLink key={item.to} to={item.to} className={linkClass} onClick={onClose}>
                    {item.icon}
                    {item.label}
                  </NavLink>
                ))}
            </React.Fragment>
          ))}
        </nav>

        <div className="border-t border-line-soft p-4">
          <div className="rounded-xl bg-brand-gradient-soft p-3.5">
            <p className="flex items-center gap-1.5 text-[12px] font-bold text-ink">
              <Activity className="h-3.5 w-3.5 text-brand-500" /> Heuristic engine v1
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted">
              Risk scores are explainable heuristics — always confirm with evidence before action.
            </p>
          </div>
        </div>
      </aside>
    </>
  );
};

const GlobalSearch: React.FC = () => {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Array<{ id: string; label: string; sub: string; kind: string }>>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const { entityService } = await import('../../services/entityService');
        const { caseService } = await import('../../services/caseService');
        const [ents, cases] = await Promise.all([
          entityService.listEntities({ q: q.trim(), page_size: 5 }),
          caseService.listCases({ q: q.trim(), page_size: 4 }),
        ]);
        if (cancelled) return;
        setResults([
          ...ents.items.map((e) => ({
            id: e.id,
            label: e.display_name,
            sub: `${e.entity_type.replace(/_/g, ' ')} · risk ${(e.current_risk_score ?? 0).toFixed(2)}`,
            kind: 'entity',
          })),
          ...cases.items.map((c) => ({
            id: c.id,
            label: `${c.case_number} — ${c.title}`,
            sub: `case · ${c.status.replace(/_/g, ' ')}`,
            kind: 'case',
          })),
        ]);
        setOpen(true);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  const pick = (r: { id: string; kind: string }) => {
    setOpen(false);
    setQ('');
    navigate(r.kind === 'entity' ? `/entities/${r.id}` : `/cases/${r.id}`);
  };

  return (
    <div className="relative w-full max-w-xl">
      <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => q.trim().length >= 2 && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false);
          if (e.key === 'Enter' && results[0]) pick(results[0]);
        }}
        placeholder="Search entities, cases…"
        aria-label="Global search"
        className="h-10 w-full rounded-xl border border-line bg-bg pl-10 pr-14 text-sm text-ink placeholder:text-faint focus-ring focus:bg-white"
      />
      <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border border-line bg-white px-1.5 py-0.5 text-[10px] font-semibold text-faint sm:block">
        Ctrl K
      </kbd>
      {open && (results.length > 0 || loading) && (
        <div className="absolute left-0 right-0 top-12 z-50 animate-scale-in rounded-xl border border-line bg-surface p-1.5 shadow-popover">
          {loading && results.length === 0 && (
            <p className="px-3 py-2 text-[13px] text-muted">Searching…</p>
          )}
          {results.map((r) => (
            <button
              key={r.kind + r.id}
              onClick={() => pick(r)}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-brand-50"
            >
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold text-ink">{r.label}</span>
                <span className="block text-[11px] text-muted">{r.sub}</span>
              </span>
              <span className="shrink-0 rounded-full bg-line-soft px-2 py-0.5 text-[10px] font-bold uppercase text-faint">
                {r.kind}
              </span>
            </button>
          ))}
          <button
            onClick={() => {
              setOpen(false);
              navigate(`/assets?q=${encodeURIComponent(q.trim())}`);
              setQ('');
            }}
            className="mt-1 w-full rounded-lg border-t border-line-soft px-3 py-2 text-left text-[12px] font-semibold text-brand-600 hover:bg-brand-50"
          >
            See all results in Digital Assets →
          </button>
        </div>
      )}
    </div>
  );
};

const Topbar: React.FC<{ onMenuClick: () => void }> = ({ onMenuClick }) => {
  const { user, logout, hasPermission } = useAuth();
  const navigate = useNavigate();

  const roleLabel = USER_ROLE_LABELS[user?.role || ''] || user?.role;

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/90 px-4 backdrop-blur-md sm:px-6">
      <button
        onClick={onMenuClick}
        className="rounded-lg p-2 text-ink-500 hover:bg-line-soft lg:hidden"
        aria-label="Open navigation menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      <div className="hidden flex-1 justify-center md:flex">
        <GlobalSearch />
      </div>
      <div className="flex-1 md:hidden" />

      <div className="flex items-center gap-1.5">
        {notificationsPopover()}
        <Dropdown
          align="right"
          header={
            user ? (
              <div className="flex items-center gap-2.5">
                <Avatar name={user.full_name} size={34} />
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-bold text-ink">{user.full_name}</p>
                  <p className="truncate text-[11px] text-muted">{user.email}</p>
                </div>
              </div>
            ) : null
          }
          items={[
            { label: 'My profile', icon: <UserIcon className="h-4 w-4" />, onClick: () => navigate('/settings?tab=profile') },
            {
              label: 'Notification preferences',
              icon: <Bell className="h-4 w-4" />,
              onClick: () => navigate('/settings?tab=notifications'),
            },
            {
              label: 'Send feedback',
              icon: <MessageSquare className="h-4 w-4" />,
              onClick: () => navigate('/settings?tab=feedback'),
            },
            ...(user?.role === 'administrator'
              ? [
                  {
                    label: 'Workspace settings',
                    icon: <Building2 className="h-4 w-4" />,
                    onClick: () => navigate('/settings?tab=workspace'),
                  },
                  {
                    label: 'Team & permissions',
                    icon: <Users className="h-4 w-4" />,
                    onClick: () => navigate('/settings?tab=team'),
                  },
                ]
              : []),
            ...(hasPermission('audit:read')
              ? [
                  {
                    label: 'Audit trail',
                    icon: <SlidersHorizontal className="h-4 w-4" />,
                    onClick: () => navigate('/settings?tab=security'),
                  },
                ]
              : []),
            {
              label: 'Sign out',
              icon: <LogOut className="h-4 w-4" />,
              onClick: () => {
                logout();
                navigate('/login');
              },
              danger: true,
              separatorBefore: true,
            },
          ]}
          trigger={({ open }) => (
            <button
              className="flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition-colors hover:bg-line-soft focus-ring"
              aria-haspopup="menu"
              aria-expanded={open}
            >
              <Avatar name={user?.full_name} size={34} />
              <span className="hidden text-left lg:block">
                <span className="block text-[13px] font-bold leading-tight text-ink">{user?.full_name}</span>
                <span className="block text-[11px] font-medium leading-tight text-muted">{roleLabel}</span>
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-faint" />
            </button>
          )}
        />
      </div>
    </header>
  );
};

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const input = document.querySelector<HTMLInputElement>('input[aria-label="Global search"]');
        input?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const memoChildren = useMemo(() => children, [children]);

  return (
    <div className="min-h-screen bg-bg">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="lg:pl-[248px]">
        <Topbar onMenuClick={() => setSidebarOpen(true)} />
        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">{memoChildren}</main>
      </div>
    </div>
  );
};

export default AppShell;
