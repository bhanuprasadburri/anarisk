import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Bell,
  Building2,
  Check,
  CheckCheck,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Globe,
  Image as ImageIcon,
  Info,
  KeyRound,
  Link2,
  Lock,
  MessageSquare,
  MoreVertical,
  Package,
  Palette,
  Pause,
  Pencil,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Save,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Store,
  Timer,
  Trash2,
  Upload,
  User as UserIcon,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import { PageHeader } from '../components/ui/page-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge, BadgeTone, ProvenanceBadge } from '../components/ui/badge';
import { Tabs, Dropdown, TabItem } from '../components/ui/tabs';
import { Column, DataTable, EmptyState, ErrorState, Pagination } from '../components/ui/table';
import { Modal, ConfirmDialog } from '../components/ui/modal';
import { Field, Input, Label, Select, Switch, Textarea } from '../components/ui/input';
import { Avatar, CopyButton, FilterSelect, SearchInput, Skeleton } from '../components/ui/misc';
import { ScoreBar } from '../components/ui/score';
import { useToast } from '../components/ui/toast';
import { useAuth } from '../hooks/useAuth';
import { ApiError, apiRequest } from '../services/apiClient';
import { authService } from '../services/authService';
import { brandService } from '../services/brandService';
import { integrationService } from '../services/integrationService';
import { monitoringService } from '../services/monitoringService';
import { notificationService } from '../services/notificationService';
import { settingsService } from '../services/settingsService';
import {
  AuditLog,
  Brand,
  BrandReference,
  FeedbackCategory,
  FeedbackItem,
  FeedbackStatus,
  IntegrationProvider,
  IntegrationTestResult,
  MonitoringTarget,
  NotificationItem,
  Organization,
  PaginatedResponse,
  ReferenceKind,
  User,
  UserPreferences,
} from '../types';
import { STORE_LABELS, USER_ROLE_LABELS } from '../lib/constants';
import { feedbackService } from '../services/feedbackService';
import { formatDate, formatRelativeTime } from '../lib/formatters';
import { cn } from '../lib/utils';

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

const errText = (e: unknown): string => (e instanceof Error ? e.message : 'Unexpected error');

/** Map a 422-style ApiError payload to { field: message } for inline form errors. */
const fieldErrorsOf = (e: unknown): Record<string, string> | null => {
  if (e instanceof ApiError && Array.isArray(e.details)) {
    const out: Record<string, string> = {};
    for (const d of e.details as Array<{ field?: string; message?: string }>) {
      if (d && typeof d.field === 'string') out[d.field] = d.message || 'Invalid value';
    }
    if (Object.keys(out).length > 0) return out;
  }
  return null;
};

const AccessDenied: React.FC<{ description?: string }> = ({ description }) => (
  <Card className="p-6">
    <EmptyState
      icon={<ShieldAlert className="h-6 w-6" />}
      title="Administrator access required"
      description={
        description ||
        "You don't have access to this section. Ask a workspace administrator if you need it."
      }
    />
  </Card>
);

type TeamUser = User & {
  last_login_at?: string | null;
  organization?: { id: string; name: string } | null;
};

const ROLE_TONES: Record<string, BadgeTone> = {
  administrator: 'violet',
  investigator: 'primary',
  brand_owner: 'info',
  partner: 'default',
};

/* ------------------------------------------------------------------ */
/*  Page shell                                                         */
/* ------------------------------------------------------------------ */

type SettingsTab = TabItem & {
  /** Only administrators may see this tab (workspace administration, team management, integrations). */
  adminOnly?: boolean;
  /** Minimum permission required to see this tab (mirrors the backend matrix). */
  perm?: string;
};

const TAB_ITEMS: SettingsTab[] = [
  { id: 'profile', label: 'Profile', icon: <UserIcon className="h-4 w-4" /> },
  { id: 'workspace', label: 'Workspace', icon: <Building2 className="h-4 w-4" />, adminOnly: true },
  { id: 'team', label: 'Team & Permissions', icon: <Users className="h-4 w-4" />, adminOnly: true },
  { id: 'brands', label: 'Brand References', icon: <Palette className="h-4 w-4" />, perm: 'brand:read' },
  { id: 'integrations', label: 'Integrations', icon: <Plug className="h-4 w-4" />, adminOnly: true },
  { id: 'monitoring', label: 'Monitoring', icon: <Activity className="h-4 w-4" />, perm: 'entity:read' },
  { id: 'notifications', label: 'Notifications', icon: <Bell className="h-4 w-4" /> },
  { id: 'feedback', label: 'Feedback', icon: <MessageSquare className="h-4 w-4" /> },
  { id: 'security', label: 'Security', icon: <ShieldCheck className="h-4 w-4" />, perm: 'audit:read' },
];

export const SettingsPage: React.FC = () => {
  const { hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get('tab') || 'profile';
  // Admin-only tabs are hidden entirely from regular users; a direct URL to a hidden tab
  // falls back to the profile tab (the backend would refuse the data regardless).
  const isAdmin = hasPermission('user:manage');
  const visibleTabs = TAB_ITEMS.filter((t) => (t.adminOnly ? isAdmin : !t.perm || hasPermission(t.perm)));
  const visibleIds = visibleTabs.map((t) => t.id);
  const tab = visibleIds.includes(raw) ? raw : 'profile';

  const setTab = (id: string) => setSearchParams({ tab: id });

  return (
    <div>
      <PageHeader
        title="Settings & Integrations"
        description="Your profile, workspace, brand references, connectors and security posture — all driven by the live API."
      />
      <Tabs items={visibleTabs} value={tab} onChange={setTab} className="mb-6" />
      {tab === 'profile' && <ProfileTab />}
      {tab === 'workspace' && <WorkspaceTab />}
      {tab === 'team' && <TeamTab />}
      {tab === 'brands' && <BrandsTab />}
      {tab === 'integrations' && <IntegrationsTab />}
      {tab === 'monitoring' && <MonitoringTab />}
      {tab === 'notifications' && <NotificationsTab />}
      {tab === 'feedback' && <FeedbackTab />}
      {tab === 'security' && <SecurityTab />}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Profile                                                            */
/* ------------------------------------------------------------------ */

const ProfileTab: React.FC = () => {
  const { user, refreshAuth } = useAuth();
  const { toast } = useToast();

  const [fullName, setFullName] = useState(user?.full_name || '');
  const [email, setEmail] = useState(user?.email || '');
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const mountedFor = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (user && mountedFor.current !== user.id) {
      mountedFor.current = user.id;
      setFullName(user.full_name);
      setEmail(user.email);
    }
  }, [user]);

  const save = async () => {
    setNameErr(null);
    setEmailErr(null);
    let valid = true;
    if (!fullName.trim()) {
      setNameErr('Full name is required');
      valid = false;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setEmailErr('Enter a valid email address');
      valid = false;
    }
    if (!valid || !user) return;
    if (fullName.trim() === user.full_name && email.trim() === user.email) {
      toast.info('Nothing to save', 'Change your name or email first.');
      return;
    }
    setSaving(true);
    try {
      await authService.updateProfile({ full_name: fullName.trim(), email: email.trim() });
      await refreshAuth();
      toast.success('Profile updated', 'Your name and email were saved.');
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.code === 'email_taken')) {
        setEmailErr('This email address is already in use by another account.');
      } else {
        toast.error('Could not save your profile', errText(e));
      }
    } finally {
      setSaving(false);
    }
  };

  /* --- password change --- */
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [pwErrs, setPwErrs] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [pwBusy, setPwBusy] = useState(false);

  const changePassword = async () => {
    const errs: typeof pwErrs = {};
    if (!current) errs.current = 'Enter your current password';
    if (next.length < 8) errs.next = 'New password must be at least 8 characters';
    if (confirm !== next) errs.confirm = 'Passwords do not match';
    setPwErrs(errs);
    if (Object.keys(errs).length > 0) return;
    setPwBusy(true);
    try {
      await authService.changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      toast.success('Password changed', 'Use your new password the next time you sign in.');
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        setPwErrs({ current: errText(e) });
      } else {
        toast.error('Could not change password', errText(e));
      }
    } finally {
      setPwBusy(false);
    }
  };

  if (!user) return null;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserIcon className="h-4 w-4 text-brand-500" /> My profile
          </CardTitle>
          <CardDescription>How you appear across AnaRisk.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 rounded-xl bg-brand-gradient-soft p-4">
            <Avatar name={user.full_name} size={56} />
            <div className="min-w-0">
              <p className="truncate text-[15px] font-bold text-ink">{user.full_name}</p>
              <p className="truncate text-[12.5px] text-muted">{user.email}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <Badge tone={ROLE_TONES[user.role] || 'default'}>{USER_ROLE_LABELS[user.role] || user.role}</Badge>
                <Badge tone="outline">
                  <Building2 className="h-3 w-3" /> {user.organization?.name || 'No organization'}
                </Badge>
              </div>
            </div>
          </div>

          <div className="mt-5 space-y-4">
            <Field label="Full name" error={nameErr} required htmlFor="profile-name">
              <Input
                id="profile-name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Analyst"
                className={nameErr ? 'border-danger' : undefined}
                autoComplete="name"
              />
            </Field>
            <Field label="Email" error={emailErr} required htmlFor="profile-email" hint="Used to sign in and receive notifications.">
              <Input
                id="profile-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="jane@anarisk.example"
                className={emailErr ? 'border-danger' : undefined}
                autoComplete="email"
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label>Role</Label>
                <div className="flex h-10 items-center">
                  <Badge tone={ROLE_TONES[user.role] || 'default'}>{USER_ROLE_LABELS[user.role] || user.role}</Badge>
                </div>
                <p className="mt-1.5 text-xs text-faint">Roles are managed by administrators.</p>
              </div>
              <div>
                <Label>Organization</Label>
                <div className="flex h-10 items-center gap-2 text-[13px] font-semibold text-ink">
                  <Building2 className="h-4 w-4 text-faint" />
                  {user.organization?.name || '—'}
                </div>
                <p className="mt-1.5 text-xs text-faint">Inherited from your workspace.</p>
              </div>
            </div>
            <div className="flex justify-end">
              <Button loading={saving} icon={<Save className="h-4 w-4" />} onClick={() => void save()}>
                Save changes
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="h-fit">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-brand-500" /> Change password
          </CardTitle>
          <CardDescription>Choose a strong password of at least 8 characters.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <Field label="Current password" error={pwErrs.current} required htmlFor="pw-current">
              <Input
                id="pw-current"
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
                className={pwErrs.current ? 'border-danger' : undefined}
              />
            </Field>
            <Field label="New password" error={pwErrs.next} required htmlFor="pw-new" hint="Minimum 8 characters.">
              <Input
                id="pw-new"
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                className={pwErrs.next ? 'border-danger' : undefined}
              />
            </Field>
            <Field label="Confirm new password" error={pwErrs.confirm} required htmlFor="pw-confirm">
              <Input
                id="pw-confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                className={pwErrs.confirm ? 'border-danger' : undefined}
              />
            </Field>
            <div className="flex justify-end">
              <Button variant="secondary" loading={pwBusy} icon={<KeyRound className="h-4 w-4" />} onClick={() => void changePassword()}>
                Update password
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Workspace (admin)                                                  */
/* ------------------------------------------------------------------ */

const WorkspaceTab: React.FC = () => {
  const { user, refreshAuth } = useAuth();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const isAdmin = user?.role === 'administrator';
  // Set after a successful create (?tab=workspace&org={id}) so the tab loads the new workspace.
  const orgParam = searchParams.get('org');

  const [org, setOrg] = useState<Organization | null>(null);
  const [orgName, setOrgName] = useState('');
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [brandRows, setBrandRows] = useState<Brand[]>([]);
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [createErr, setCreateErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const orgId = orgParam || user?.organization_id;
      if (orgId) {
        const detail = await settingsService.getOrganization(orgId);
        setOrg(detail);
        setOrgName(detail.name);
      } else {
        setOrg(null);
      }
      const res = await brandService.listBrands({ page_size: 100 });
      setBrandRows(res.items || []);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, [orgParam, user?.organization_id]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  if (!isAdmin) return <AccessDenied />;

  const saveName = async () => {
    if (!org) return;
    if (!orgName.trim()) {
      setNameErr('Workspace name cannot be empty');
      return;
    }
    setNameErr(null);
    setSaving(true);
    try {
      const updated = await settingsService.updateOrganization(org.id, { name: orgName.trim() });
      setOrg(updated);
      setOrgName(updated.name);
      await refreshAuth();
      toast.success('Workspace renamed', `Your organization is now "${updated.name}".`);
    } catch (e) {
      toast.error('Could not rename the workspace', errText(e));
    } finally {
      setSaving(false);
    }
  };

  const slugify = (s: string) =>
    s
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 100);

  const createWorkspace = async () => {
    const name = newName.trim();
    const slug = (newSlug.trim() || slugify(name)).toLowerCase();
    if (!name) {
      setCreateErr('Workspace name cannot be empty');
      return;
    }
    if (slug.length < 2 || !/^[a-z0-9][a-z0-9-]*$/.test(slug)) {
      setCreateErr('Slug must be at least 2 characters: lowercase letters, digits and hyphens.');
      return;
    }
    setCreateErr(null);
    setCreating(true);
    try {
      const created = await settingsService.createOrganization({ name, slug });
      toast.success('Workspace created', `"${created.name}" is ready.`);
      // Navigate ONLY on success — the `org` param makes load() fetch the new workspace.
      setSearchParams({ tab: 'workspace', org: created.id }, { replace: true });
    } catch (e) {
      // No navigation on failure: the typed values stay so the user can correct and retry.
      setCreateErr(errText(e));
      toast.error('Could not create the workspace', errText(e));
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="grid gap-5">
        <Skeleton className="h-[220px] rounded-2xl" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[110px] rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-6">
        <ErrorState title="Could not load the workspace" message={error} onRetry={() => void load()} />
      </Card>
    );
  }

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-brand-500" /> Organization
          </CardTitle>
          <CardDescription>The workspace that owns your brands, cases and connectors.</CardDescription>
        </CardHeader>
        <CardContent>
          {!org ? (
            <EmptyState
              icon={<Building2 className="h-6 w-6" />}
              title="No workspace selected"
              description="You don't belong to an organization yet — create your first workspace below."
            />
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Workspace name" error={nameErr} required htmlFor="org-name">
                  <Input id="org-name" value={orgName} onChange={(e) => setOrgName(e.target.value)} className={nameErr ? 'border-danger' : undefined} />
                </Field>
                <div className="grid grid-cols-3 gap-3 self-end">
                  <div className="rounded-xl border border-line-soft bg-bg/60 px-3 py-2.5">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Members</p>
                    <p className="mt-0.5 text-xl font-extrabold text-ink">{org.member_count ?? 0}</p>
                  </div>
                  <div className="rounded-xl border border-line-soft bg-bg/60 px-3 py-2.5">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Brands</p>
                    <p className="mt-0.5 text-xl font-extrabold text-ink">{org.brand_count ?? 0}</p>
                  </div>
                  <div className="rounded-xl border border-line-soft bg-bg/60 px-3 py-2.5">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-faint">Created</p>
                    <p className="mt-1 text-[13px] font-bold text-ink">{org.created_at ? formatDate(org.created_at).split(' ')[0] : '—'}</p>
                  </div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-[12px] text-faint">
                  Slug <code className="rounded bg-line-soft px-1.5 py-0.5 font-mono text-[11px]">{org.slug || '—'}</code>
                </p>
                <Button loading={saving} disabled={orgName.trim() === org.name} icon={<Save className="h-4 w-4" />} onClick={() => void saveName()}>
                  Save workspace
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4 text-brand-500" /> Create a workspace
          </CardTitle>
          <CardDescription>
            Creates a new organization owned by administrators — assign members to it from the Team &amp; Permissions tab.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Workspace name" required htmlFor="new-org-name">
              <Input
                id="new-org-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Acme Inc."
                disabled={creating}
              />
            </Field>
            <Field label="Slug" required htmlFor="new-org-slug">
              <Input
                id="new-org-slug"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value)}
                placeholder={slugify(newName) || 'acme-inc'}
                disabled={creating}
              />
            </Field>
          </div>
          <p className="mt-1 text-[11.5px] text-faint">
            The slug appears in URLs — leave it blank to derive it from the name (lowercase letters, digits, hyphens).
          </p>
          {createErr && <p className="mt-3 text-[12.5px] font-semibold text-danger">{createErr}</p>}
          <div className="mt-4 flex justify-end">
            <Button
              loading={creating}
              disabled={creating || !newName.trim()}
              icon={<Plus className="h-4 w-4" />}
              onClick={() => void createWorkspace()}
            >
              Create workspace
            </Button>
          </div>
        </CardContent>
      </Card>

      {(!org || org.id === user?.organization_id) && (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Palette className="h-4 w-4 text-brand-500" /> Brands in this workspace
            </CardTitle>
            <CardDescription>Brand references drive detection — manage them under Brand References.</CardDescription>
          </div>
          <Link to="/settings?tab=brands" className="text-[13px] font-semibold text-brand-600 hover:text-brand-700">
            Manage references →
          </Link>
        </CardHeader>
        <CardContent>
          {brandRows.length === 0 ? (
            <EmptyState icon={<Palette className="h-6 w-6" />} title="No brands yet" description="Create your first brand from the Brand References tab." />
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {brandRows.map((b) => (
                <li key={b.id} className="rounded-xl border border-line p-4 transition-shadow hover:shadow-card">
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 truncate text-[14px] font-bold text-ink">{b.name}</p>
                    <Badge tone={b.is_active ? 'success' : 'default'}>{b.is_active ? 'Active' : 'Inactive'}</Badge>
                  </div>
                  {b.description && <p className="mt-1 line-clamp-2 text-[12px] text-muted">{b.description}</p>}
                  <p className="mt-2 text-[11px] font-semibold text-faint">
                    {b.entity_count !== undefined && b.entity_count !== null ? `${b.entity_count} entities` : 'Entity count not exposed by this endpoint'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Team (admin)                                                       */
/* ------------------------------------------------------------------ */

const TeamTab: React.FC = () => {
  const { user } = useAuth();
  const { toast } = useToast();
  const isAdmin = user?.role === 'administrator';

  const [rows, setRows] = useState<PaginatedResponse<TeamUser> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [roleFilter, setRoleFilter] = useState('');
  const [roleKeys, setRoleKeys] = useState<string[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [editUser, setEditUser] = useState<TeamUser | null>(null);
  const [editName, setEditName] = useState('');
  const [editRole, setEditRole] = useState('investigator');
  const [editActive, setEditActive] = useState(true);
  const [editOrg, setEditOrg] = useState('');
  const [editErrs, setEditErrs] = useState<Record<string, string>>({});
  const [editSaving, setEditSaving] = useState(false);

  const [inviteOpen, setInviteOpen] = useState(false);
  const [invEmail, setInvEmail] = useState('');
  const [invName, setInvName] = useState('');
  const [invPassword, setInvPassword] = useState('');
  const [invRole, setInvRole] = useState('investigator');
  const [invOrg, setInvOrg] = useState(user?.organization_id || '');
  const [invErrs, setInvErrs] = useState<Record<string, string>>({});
  const [invSaving, setInvSaving] = useState(false);

  const [confirmDeactivate, setConfirmDeactivate] = useState<TeamUser | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await settingsService.listUsers({
        page,
        page_size: pageSize,
        role: roleFilter || undefined,
      });
      setRows(res as PaginatedResponse<TeamUser>);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, roleFilter]);

  useEffect(() => {
    if (!isAdmin) return;
    void load();
  }, [isAdmin, load]);

  useEffect(() => {
    if (!isAdmin) return;
    (async () => {
      try {
        const raw = await settingsService.listRoles() as unknown;
        const keys = Array.isArray(raw)
          ? (raw as Array<{ role: string }>).map((r) => r.role)
          : Object.keys((raw as Record<string, string[]>) || {});
        setRoleKeys(keys.length > 0 ? keys : ['administrator', 'investigator', 'brand_owner', 'partner']);
      } catch {
        setRoleKeys(['administrator', 'investigator', 'brand_owner', 'partner']);
      }
      try {
        const raw = await settingsService.listOrganizations() as unknown;
        const list: Organization[] = Array.isArray(raw)
          ? (raw as Organization[])
          : ((raw as { items?: Organization[] })?.items || []);
        setOrgs(list);
      } catch {
        setOrgs([]);
      }
    })();
  }, [isAdmin]);

  if (!isAdmin) return <AccessDenied />;

  const openEdit = (u: TeamUser) => {
    setEditUser(u);
    setEditName(u.full_name);
    setEditRole(u.role);
    setEditActive(u.is_active);
    setEditOrg(u.organization_id || '');
    setEditErrs({});
  };

  const saveEdit = async () => {
    if (!editUser) return;
    const errs: Record<string, string> = {};
    if (!editName.trim()) errs.full_name = 'Full name is required';
    setEditErrs(errs);
    if (Object.keys(errs).length > 0) return;
    const isSelf = editUser.id === user?.id;
    if (isSelf && !editActive) {
      toast.error('Not allowed', 'You cannot deactivate your own account.');
      return;
    }
    setEditSaving(true);
    try {
      if (editOrg) {
        await settingsService.updateUser(editUser.id, {
          full_name: editName.trim(),
          role: editRole,
          is_active: editActive,
          organization_id: editOrg,
        });
      } else if (editUser.organization_id) {
        await apiRequest(`/users/${editUser.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            full_name: editName.trim(),
            role: editRole,
            is_active: editActive,
            clear_organization: true,
          }),
        });
      } else {
        await settingsService.updateUser(editUser.id, {
          full_name: editName.trim(),
          role: editRole,
          is_active: editActive,
        });
      }
      toast.success('User updated', `${editUser.email} was updated.`);
      setEditUser(null);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        toast.error('Not allowed', errText(e));
      } else {
        toast.error('Could not update the user', errText(e));
      }
    } finally {
      setEditSaving(false);
    }
  };

  const toggleActive = async (u: TeamUser) => {
    setBusyId(u.id);
    try {
      await settingsService.updateUser(u.id, { is_active: !u.is_active });
      toast.success(u.is_active ? 'User deactivated' : 'User activated', `${u.email} is now ${!u.is_active ? 'active' : 'inactive'}.`);
      await load();
    } catch (e) {
      toast.error('Could not change the account state', errText(e));
    } finally {
      setBusyId(null);
    }
  };

  const invite = async () => {
    const errs: Record<string, string> = {};
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(invEmail.trim())) errs.email = 'Enter a valid email address';
    if (!invName.trim()) errs.full_name = 'Full name is required';
    if (invPassword.length < 8) errs.password = 'Password must be at least 8 characters';
    setInvErrs(errs);
    if (Object.keys(errs).length > 0) return;
    setInvSaving(true);
    try {
      await settingsService.createUser({
        email: invEmail.trim(),
        full_name: invName.trim(),
        password: invPassword,
        role: invRole,
        organization_id: invOrg || undefined,
      });
      toast.success('User invited', `${invEmail.trim()} can now sign in.`);
      setInviteOpen(false);
      setInvEmail('');
      setInvName('');
      setInvPassword('');
      setInvRole('investigator');
      await load();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.code === 'email_taken')) {
        setInvErrs({ email: 'An account with this email already exists.' });
      } else {
        toast.error('Could not create the user', errText(e));
      }
    } finally {
      setInvSaving(false);
    }
  };

  const columns: Column<TeamUser>[] = [
    {
      key: 'user',
      header: 'Member',
      cell: (u) => (
        <div className="flex items-center gap-3">
          <Avatar name={u.full_name} size={32} />
          <div className="min-w-0">
            <p className="truncate text-[13px] font-bold text-ink">
              {u.full_name}
              {u.id === user?.id && <span className="ml-1.5 text-[11px] font-semibold text-faint">(you)</span>}
            </p>
            <p className="truncate text-[11.5px] text-muted">{u.organization?.name || 'No organization'}</p>
          </div>
        </div>
      ),
    },
    { key: 'email', header: 'Email', cell: (u) => <span className="text-[13px]">{u.email}</span> },
    {
      key: 'role',
      header: 'Role',
      cell: (u) => <Badge tone={ROLE_TONES[u.role] || 'default'}>{USER_ROLE_LABELS[u.role] || u.role}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      cell: (u) => (u.is_active ? <Badge tone="success" dot>Active</Badge> : <Badge tone="default" dot>Inactive</Badge>),
    },
    {
      key: 'last_login',
      header: 'Last login',
      cell: (u) => <span className="text-[12.5px] text-muted">{formatRelativeTime(u.last_login_at || null)}</span>,
    },
    {
      key: 'joined',
      header: 'Joined',
      cell: (u) => <span className="text-[12.5px] text-muted">{formatDate(u.created_at).split(' ')[0]}</span>,
    },
    {
      key: 'actions',
      header: '',
      className: 'w-12 text-right',
      cell: (u) => {
        const isSelf = u.id === user?.id;
        return (
          <Dropdown
            align="right"
            trigger={({ open }) => (
              <button
                aria-label={`Actions for ${u.full_name}`}
                aria-expanded={open}
                className="rounded-lg p-1.5 text-muted transition-colors hover:bg-line-soft hover:text-ink focus-ring"
              >
                <MoreVertical className="h-4 w-4" />
              </button>
            )}
            items={[
              { label: 'Edit user', icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(u) },
              u.is_active
                ? {
                    label: 'Deactivate',
                    icon: <X className="h-4 w-4" />,
                    danger: true,
                    disabled: isSelf || busyId === u.id,
                    onClick: () => setConfirmDeactivate(u),
                  }
                : {
                    label: 'Activate',
                    icon: <Check className="h-4 w-4" />,
                    disabled: busyId === u.id,
                    onClick: () => void toggleActive(u),
                  },
            ]}
          />
        );
      },
    },
  ];

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-4 w-4 text-brand-500" /> Team & permissions
            </CardTitle>
            <CardDescription>Invite teammates and manage their roles.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <FilterSelect
              label="Filter by role"
              value={roleFilter}
              onChange={(v) => {
                setRoleFilter(v);
                setPage(1);
              }}
              options={roleKeys.map((r) => ({ value: r, label: USER_ROLE_LABELS[r] || r }))}
              allLabel="All roles"
            />
            <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setInviteOpen(true)}>
              Invite user
            </Button>
          </div>
        </CardHeader>
        <CardContent className="border-b border-line-soft">
          <DataTable
            columns={columns}
            rows={rows?.items || []}
            rowKey={(u) => u.id}
            loading={loading}
            emptyState={
              <EmptyState
                icon={<Users className="h-6 w-6" />}
                title={roleFilter ? 'No users with this role' : 'No users yet'}
                description={roleFilter ? 'Try a different role filter.' : 'Invite your first teammate to get started.'}
                action={<Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setInviteOpen(true)}>Invite user</Button>}
              />
            }
          />
          {error && !loading && (
            <div className="pt-4">
              <ErrorState title="Could not load users" message={error} onRetry={() => void load()} />
            </div>
          )}
        </CardContent>
        {rows && (
          <Pagination
            page={rows.page}
            pages={rows.pages}
            total={rows.total}
            onPageChange={setPage}
            pageSize={pageSize}
            onPageSizeChange={(s) => {
              setPageSize(s);
              setPage(1);
            }}
          />
        )}
      </Card>

      {/* Edit user modal */}
      <Modal
        open={!!editUser}
        onClose={() => setEditUser(null)}
        title="Edit user"
        description={editUser?.email}
        footer={
          <>
            <Button variant="outline" onClick={() => setEditUser(null)} disabled={editSaving}>
              Cancel
            </Button>
            <Button loading={editSaving} onClick={() => void saveEdit()}>
              Save changes
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Full name" error={editErrs.full_name || null} required htmlFor="edit-name">
            <Input id="edit-name" value={editName} onChange={(e) => setEditName(e.target.value)} className={editErrs.full_name ? 'border-danger' : undefined} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Role" htmlFor="edit-role" hint={editUser?.id === user?.id ? 'You cannot change your own role.' : undefined}>
              <Select
                id="edit-role"
                value={editRole}
                disabled={editUser?.id === user?.id}
                onChange={(e) => setEditRole(e.target.value)}
              >
                {roleKeys.map((r) => (
                  <option key={r} value={r}>
                    {USER_ROLE_LABELS[r] || r}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Organization" htmlFor="edit-org">
              <Select id="edit-org" value={editOrg} onChange={(e) => setEditOrg(e.target.value)}>
                <option value="">— No organization —</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-line-soft bg-bg/60 px-4 py-3">
            <div>
              <p className="text-[13px] font-semibold text-ink">Account active</p>
              <p className="text-[11.5px] text-muted">Inactive users cannot sign in.</p>
            </div>
            <Switch
              checked={editActive}
              onChange={setEditActive}
              disabled={editUser?.id === user?.id}
              label="Account active"
            />
          </div>
        </div>
      </Modal>

      {/* Invite modal */}
      <Modal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title="Invite user"
        description="Create an account for a teammate."
        footer={
          <>
            <Button variant="outline" onClick={() => setInviteOpen(false)} disabled={invSaving}>
              Cancel
            </Button>
            <Button loading={invSaving} icon={<UserPlus className="h-4 w-4" />} onClick={() => void invite()}>
              Create user
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Email" error={invErrs.email || null} required htmlFor="inv-email">
            <Input
              id="inv-email"
              type="email"
              value={invEmail}
              onChange={(e) => setInvEmail(e.target.value)}
              className={invErrs.email ? 'border-danger' : undefined}
              placeholder="teammate@anarisk.example"
            />
          </Field>
          <Field label="Full name" error={invErrs.full_name || null} required htmlFor="inv-name">
            <Input id="inv-name" value={invName} onChange={(e) => setInvName(e.target.value)} className={invErrs.full_name ? 'border-danger' : undefined} />
          </Field>
          <Field label="Password" error={invErrs.password || null} required htmlFor="inv-password" hint="Minimum 8 characters.">
            <Input
              id="inv-password"
              type="password"
              value={invPassword}
              onChange={(e) => setInvPassword(e.target.value)}
              className={invErrs.password ? 'border-danger' : undefined}
              autoComplete="new-password"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Role" htmlFor="inv-role">
              <Select id="inv-role" value={invRole} onChange={(e) => setInvRole(e.target.value)}>
                {roleKeys.map((r) => (
                  <option key={r} value={r}>
                    {USER_ROLE_LABELS[r] || r}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Organization" htmlFor="inv-org">
              <Select id="inv-org" value={invOrg} onChange={(e) => setInvOrg(e.target.value)}>
                <option value="">— None —</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!confirmDeactivate}
        onClose={() => setConfirmDeactivate(null)}
        onConfirm={async () => {
          if (!confirmDeactivate) return;
          await toggleActive(confirmDeactivate);
          setConfirmDeactivate(null);
        }}
        title="Deactivate account?"
        message={
          <>
            <strong>{confirmDeactivate?.email}</strong> will no longer be able to sign in. Their cases and audit
            history are kept.
          </>
        }
        confirmLabel="Deactivate"
        destructive
        loading={!!busyId && busyId === confirmDeactivate?.id}
      />
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Brand references                                                   */
/* ------------------------------------------------------------------ */

const REFERENCE_KINDS: ReferenceKind[] = ['name', 'handle', 'domain', 'image', 'app_package', 'publisher', 'bio'];

const KIND_TONES: Record<string, BadgeTone> = {
  name: 'primary',
  handle: 'violet',
  domain: 'info',
  image: 'warning',
  app_package: 'success',
  publisher: 'default',
  bio: 'outline',
};

const KIND_HINTS: Record<string, string> = {
  image: 'Perceptual hash (16 hex characters) — or use "Upload logo image" for a file.',
  domain: 'e.g. example.com',
  handle: 'e.g. anarisk',
  app_package: 'e.g. com.anarisk.app',
};

const RefValueCell: React.FC<{ refItem: BrandReference }> = ({ refItem }) => {
  const [broken, setBroken] = useState(false);
  const looksLikeUrl = /^https?:\/\//i.test(refItem.value) || refItem.value.startsWith('/');

  if (refItem.kind === 'image' && looksLikeUrl && !broken) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        <img
          src={refItem.value}
          alt="Brand reference"
          className="h-8 w-8 shrink-0 rounded-md border border-line object-cover"
          onError={() => setBroken(true)}
        />
        <code className="min-w-0 truncate font-mono text-[12px] text-ink-700">{refItem.value}</code>
        <CopyButton text={refItem.value} label="Copy value" />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      {refItem.kind === 'image' && (
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-warning-100 bg-warning-100 text-warning-600">
          <ImageIcon className="h-4 w-4" />
        </span>
      )}
      <code className="min-w-0 truncate font-mono text-[12px] text-ink-700" title={refItem.value}>
        {refItem.value}
      </code>
      <CopyButton text={refItem.value} label="Copy value" />
    </div>
  );
};

const BrandsTab: React.FC = () => {
  const { hasPermission, brands, refreshBrands } = useAuth();
  const { toast } = useToast();
  const canRead = hasPermission('brand:read');
  const canWrite = hasPermission('brand:write');

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Brand | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [refKind, setRefKind] = useState<ReferenceKind>('name');
  const [refValue, setRefValue] = useState('');
  const [refPlatform, setRefPlatform] = useState('');
  const [refNote, setRefNote] = useState('');
  const [refErrs, setRefErrs] = useState<Record<string, string>>({});
  const [refSaving, setRefSaving] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadNote, setUploadNote] = useState('');
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [newBrandOpen, setNewBrandOpen] = useState(false);
  const [nbName, setNbName] = useState('');
  const [nbDesc, setNbDesc] = useState('');
  const [nbErr, setNbErr] = useState<string | null>(null);
  const [nbSaving, setNbSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<BrandReference | null>(null);
  const [deleting, setDeleting] = useState(false);

  const activeId = selectedId || brands[0]?.id || null;

  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const b = await brandService.getBrand(activeId);
        if (!cancelled) setDetail(b);
      } catch (e) {
        if (!cancelled) setError(errText(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, brands]);

  if (!canRead) return <AccessDenied description="Brand references are not visible to your role." />;

  const reload = async (id?: string) => {
    await refreshBrands();
    if (id) setSelectedId(id);
  };

  const addReference = async () => {
    if (!activeId) return;
    const errs: Record<string, string> = {};
    if (!refValue.trim()) errs.value = 'A value is required';
    if (refKind === 'image' && !/^[0-9a-f]{16}$/i.test(refValue.trim()))
      errs.value = 'Kind "image" needs a 16-hex-character perceptual hash — or upload the file instead.';
    setRefErrs(errs);
    if (Object.keys(errs).length > 0) return;
    setRefSaving(true);
    try {
      await brandService.addReference(activeId, {
        kind: refKind,
        value: refValue.trim(),
        platform: refPlatform.trim() || undefined,
        note: refNote.trim() || undefined,
      });
      toast.success('Reference added', `Official ${refKind.replace('_', ' ')} reference registered.`);
      setAddOpen(false);
      setRefValue('');
      setRefPlatform('');
      setRefNote('');
      setRefErrs({});
      // force a detail reload even if the brand list is unchanged
      const b = await brandService.getBrand(activeId);
      setDetail(b);
    } catch (e) {
      const mapped = fieldErrorsOf(e);
      if (mapped) setRefErrs(mapped);
      else toast.error('Could not add the reference', errText(e));
    } finally {
      setRefSaving(false);
    }
  };

  const uploadImage = async () => {
    if (!activeId) return;
    if (!uploadFile) {
      setUploadErr('Choose a PNG or JPEG file (max 2 MB).');
      return;
    }
    if (!['image/png', 'image/jpeg'].includes(uploadFile.type)) {
      setUploadErr('Only PNG or JPEG images are supported.');
      return;
    }
    if (uploadFile.size > 2 * 1024 * 1024) {
      setUploadErr('The file is larger than 2 MB.');
      return;
    }
    setUploadErr(null);
    setUploading(true);
    try {
      await brandService.addReferenceImage(activeId, uploadFile, { note: uploadNote.trim() || undefined });
      toast.success('Logo uploaded', 'The image was hashed (pHash) and stored as an official reference.');
      setUploadOpen(false);
      setUploadFile(null);
      setUploadNote('');
      const b = await brandService.getBrand(activeId);
      setDetail(b);
    } catch (e) {
      toast.error('Upload failed', errText(e));
    } finally {
      setUploading(false);
    }
  };

  const createBrand = async () => {
    if (!nbName.trim()) {
      setNbErr('Brand name is required');
      return;
    }
    setNbErr(null);
    setNbSaving(true);
    try {
      const b = await brandService.createBrand({ name: nbName.trim(), description: nbDesc.trim() || undefined });
      toast.success('Brand created', `"${b.name}" is ready for official references.`);
      setNewBrandOpen(false);
      setNbName('');
      setNbDesc('');
      await reload(b.id);
      setSelectedId(b.id);
    } catch (e) {
      toast.error('Could not create the brand', errText(e));
    } finally {
      setNbSaving(false);
    }
  };

  const removeReference = async () => {
    if (!activeId || !deleteTarget) return;
    setDeleting(true);
    try {
      await brandService.deleteReference(activeId, deleteTarget.id);
      toast.success('Reference deleted', 'The official reference was removed.');
      const b = await brandService.getBrand(activeId);
      setDetail(b);
    } catch (e) {
      toast.error('Could not delete the reference', errText(e));
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const writeActions = canWrite ? (
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setAddOpen(true)}>
        Add reference
      </Button>
      <Button variant="outline" size="sm" icon={<Upload className="h-4 w-4" />} onClick={() => setUploadOpen(true)}>
        Upload logo image
      </Button>
    </div>
  ) : null;

  return (
    <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
      {/* brand picker */}
      <Card className="h-fit">
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle>Brands</CardTitle>
          {canWrite && (
            <Button size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setNewBrandOpen(true)}>
              New brand
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {brands.length === 0 ? (
            <EmptyState
              className="py-6"
              icon={<Palette className="h-6 w-6" />}
              title="No brands"
              description={canWrite ? 'Create a brand to register its official references.' : 'No brands are visible to your role.'}
              action={
                canWrite ? (
                  <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setNewBrandOpen(true)}>
                    New brand
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="space-y-1.5">
              {brands.map((b) => (
                <li key={b.id}>
                  <button
                    onClick={() => setSelectedId(b.id)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left transition-colors focus-ring',
                      b.id === activeId ? 'bg-brand-50 text-brand-700' : 'text-ink-700 hover:bg-line-soft'
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-bold">{b.name}</span>
                      <span className="block truncate text-[11px] text-faint">{b.slug}</span>
                    </span>
                    <Badge tone={b.is_active ? 'success' : 'default'} className="shrink-0">
                      {b.is_active ? 'Active' : 'Off'}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* references */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="truncate">{detail?.name || 'References'}</CardTitle>
            <CardDescription>
              Official names, handles, domains and images used by the detection engine to tell real brand assets from
              impersonators.
            </CardDescription>
          </div>
          {writeActions}
        </CardHeader>
        <CardContent>
          {!activeId ? (
            <EmptyState icon={<Palette className="h-6 w-6" />} title="Select a brand" description="Pick a brand on the left to manage its references." />
          ) : loading ? (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 rounded-lg" />
              ))}
            </div>
          ) : error ? (
            <ErrorState title="Could not load this brand" message={error} />
          ) : (detail?.references || []).length === 0 ? (
            <EmptyState
              icon={<Link2 className="h-6 w-6" />}
              title="No references yet"
              description="Add the official name, handle, domain or logo so detections can be scored against reality."
            />
          ) : (
            <DataTable
              columns={[
                {
                  key: 'kind',
                  header: 'Kind',
                  cell: (r: BrandReference) => <Badge tone={KIND_TONES[r.kind] || 'default'}>{r.kind.replace('_', ' ')}</Badge>,
                },
                {
                  key: 'value',
                  header: 'Value',
                  cell: (r: BrandReference) => <RefValueCell refItem={r} />,
                },
                {
                  key: 'platform',
                  header: 'Platform',
                  cell: (r: BrandReference) => <span className="text-[12.5px]">{r.platform || '—'}</span>,
                },
                {
                  key: 'provenance',
                  header: 'Provenance',
                  cell: (r: BrandReference) => <ProvenanceBadge provenance={r.provenance} />,
                },
                {
                  key: 'created',
                  header: 'Created',
                  cell: (r: BrandReference) => <span className="text-[12.5px] text-muted">{formatDate(r.created_at)}</span>,
                },
                {
                  key: 'actions',
                  header: '',
                  className: 'w-12 text-right',
                  cell: (r: BrandReference) =>
                    canWrite ? (
                      <button
                        aria-label={`Delete ${r.kind} reference`}
                        onClick={() => setDeleteTarget(r)}
                        className="rounded-lg p-1.5 text-muted transition-colors hover:bg-danger-100 hover:text-danger focus-ring"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    ) : null,
                },
              ]}
              rows={detail?.references || []}
              rowKey={(r) => r.id}
            />
          )}
        </CardContent>
      </Card>

      {/* add reference modal */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add official reference"
        description={`For ${detail?.name || 'the selected brand'}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={refSaving}>
              Cancel
            </Button>
            <Button loading={refSaving} onClick={() => void addReference()}>
              Add reference
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Kind" htmlFor="ref-kind">
            <Select id="ref-kind" value={refKind} onChange={(e) => setRefKind(e.target.value as ReferenceKind)}>
              {REFERENCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k.replace('_', ' ')}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Value"
            error={refErrs.value || null}
            required
            htmlFor="ref-value"
            hint={KIND_HINTS[refKind]}
          >
            <Input
              id="ref-value"
              value={refValue}
              onChange={(e) => setRefValue(e.target.value)}
              className={refErrs.value ? 'border-danger' : undefined}
              placeholder={KIND_HINTS[refKind]}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Platform" htmlFor="ref-platform" hint="Optional">
              <Input id="ref-platform" value={refPlatform} onChange={(e) => setRefPlatform(e.target.value)} placeholder="x, instagram, web…" />
            </Field>
            <Field label="Note" htmlFor="ref-note" hint="Optional">
              <Input id="ref-note" value={refNote} onChange={(e) => setRefNote(e.target.value)} placeholder="Why this matters" />
            </Field>
          </div>
        </div>
      </Modal>

      {/* upload modal */}
      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="Upload logo image"
        description="PNG or JPEG, max 2 MB. The file is hashed with a perceptual hash (pHash) for logo matching."
        footer={
          <>
            <Button variant="outline" onClick={() => setUploadOpen(false)} disabled={uploading}>
              Cancel
            </Button>
            <Button loading={uploading} icon={<Upload className="h-4 w-4" />} onClick={() => void uploadImage()}>
              Upload
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Image file" error={uploadErr} required htmlFor="ref-file">
            <input
              id="ref-file"
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                setUploadFile(e.target.files?.[0] || null);
                setUploadErr(null);
              }}
              className="block w-full cursor-pointer rounded-xl border border-line bg-white text-[13px] text-ink-700 file:mr-3 file:rounded-l-xl file:border-0 file:bg-brand-50 file:px-4 file:py-2.5 file:text-[13px] file:font-semibold file:text-brand-700 focus-ring"
            />
          </Field>
          <Field label="Note" htmlFor="ref-upload-note" hint="Optional">
            <Input id="ref-upload-note" value={uploadNote} onChange={(e) => setUploadNote(e.target.value)} placeholder="Primary logo (2024)" />
          </Field>
        </div>
      </Modal>

      {/* new brand modal */}
      <Modal
        open={newBrandOpen}
        onClose={() => setNewBrandOpen(false)}
        title="New brand"
        description="A brand groups the official references and every entity monitored for it."
        footer={
          <>
            <Button variant="outline" onClick={() => setNewBrandOpen(false)} disabled={nbSaving}>
              Cancel
            </Button>
            <Button loading={nbSaving} icon={<Plus className="h-4 w-4" />} onClick={() => void createBrand()}>
              Create brand
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Brand name" error={nbErr} required htmlFor="nb-name">
            <Input id="nb-name" value={nbName} onChange={(e) => setNbName(e.target.value)} className={nbErr ? 'border-danger' : undefined} placeholder="AnaRisk" />
          </Field>
          <Field label="Description" htmlFor="nb-desc" hint="Optional">
            <Textarea id="nb-desc" value={nbDesc} onChange={(e) => setNbDesc(e.target.value)} placeholder="What this brand covers" />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void removeReference()}
        title="Delete reference?"
        message={
          <>
            The <strong>{deleteTarget?.kind}</strong> reference <code className="rounded bg-line-soft px-1 px-1.5 py-0.5 font-mono text-[12px]">{deleteTarget?.value}</code>{' '}
            will be removed and no longer scored against. This cannot be undone.
          </>
        }
        confirmLabel="Delete"
        destructive
        loading={deleting}
      />
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Integrations                                                       */
/* ------------------------------------------------------------------ */

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  social: <Smartphone className="h-5 w-5" />,
  app_store: <Store className="h-5 w-5" />,
  web: <Globe className="h-5 w-5" />,
  infrastructure: <Server className="h-5 w-5" />,
};

const StatusBadge: React.FC<{ p: IntegrationProvider; verified?: boolean }> = ({ p, verified }) => {
  if (p.status === 'error') return <Badge tone="danger" dot>Error</Badge>;
  if (p.status === 'not_configured') return <Badge tone="outline" dot>Not connected</Badge>;
  if (verified) return <Badge tone="success" dot>Connected</Badge>;
  if (p.requires_credentials) return <Badge tone="warning" dot>Configured — unverified</Badge>;
  return <Badge tone="success" dot>Connected</Badge>;
};

const IntegrationsTab: React.FC = () => {
  const { hasPermission } = useAuth();
  const { toast } = useToast();
  const canRun = hasPermission('connector:run');

  const [items, setItems] = useState<IntegrationProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [setupFor, setSetupFor] = useState<IntegrationProvider | null>(null);
  const [configVals, setConfigVals] = useState<Record<string, string>>({});
  const [configErrs, setConfigErrs] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);

  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [syncingKey, setSyncingKey] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, IntegrationTestResult>>({});
  const [disconnectFor, setDisconnectFor] = useState<IntegrationProvider | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await integrationService.list();
      setItems(res.items || []);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openSetup = (p: IntegrationProvider) => {
    const seed: Record<string, string> = {};
    for (const f of p.config_fields) {
      const previewed = p.config_preview?.[f.key];
      // never pre-fill secrets with the masked echo
      seed[f.key] = f.type === 'secret' || previewed === '••••' ? '' : previewed || '';
    }
    setConfigVals(seed);
    setConfigErrs({});
    setReveal({});
    setSetupFor(p);
  };

  const connect = async () => {
    if (!setupFor) return;
    const errs: Record<string, string> = {};
    for (const f of setupFor.config_fields) {
      if (f.required && !(configVals[f.key] || '').trim()) errs[f.key] = 'This field is required';
    }
    setConfigErrs(errs);
    if (Object.keys(errs).length > 0) return;
    setSaving(true);
    try {
      await integrationService.connect(setupFor.key, configVals);
      toast.success(`${setupFor.name} configured`, 'Credentials are stored encrypted. Run a test to verify live access.');
      setSetupFor(null);
      await load();
    } catch (e) {
      const mapped = fieldErrorsOf(e);
      if (mapped) setConfigErrs(mapped);
      else toast.error('Could not save the configuration', errText(e));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (p: IntegrationProvider) => {
    setTestingKey(p.key);
    try {
      const res = await integrationService.test(p.key);
      setResults((prev) => ({ ...prev, [p.key]: res }));
      if (res.ok) toast.success(`${p.name}: connection verified`, res.message);
      else toast.error(`${p.name}: not verified`, res.message);
    } catch (e) {
      const msg = errText(e);
      setResults((prev) => ({ ...prev, [p.key]: { ok: false, message: msg, checked_at: new Date().toISOString() } }));
      toast.error(`${p.name}: test failed`, msg);
    } finally {
      setTestingKey(null);
    }
  };

  const runSync = async (p: IntegrationProvider) => {
    setSyncingKey(p.key);
    try {
      const res = await integrationService.sync(p.key);
      toast.success(`${p.name} sync completed`, `${res.synced} item(s) processed — ${res.created_entities} new entit${res.created_entities === 1 ? 'y' : 'ies'}. ${res.message}`);
      await load();
    } catch (e) {
      toast.error(`${p.name}: sync failed`, errText(e));
    } finally {
      setSyncingKey(null);
    }
  };

  const disconnect = async () => {
    if (!disconnectFor) return;
    setDisconnecting(true);
    try {
      await integrationService.disconnect(disconnectFor.key);
      toast.success(`${disconnectFor.name} disconnected`, 'The stored configuration was removed.');
      setResults((prev) => {
        const next = { ...prev };
        delete next[disconnectFor.key];
        return next;
      });
      setDisconnectFor(null);
      await load();
    } catch (e) {
      toast.error('Could not disconnect', errText(e));
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <div className="grid gap-5">
      <div className="flex items-start gap-3 rounded-2xl border border-brand-200 bg-brand-50 p-4">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm">
          <Info className="h-4 w-4" />
        </span>
        <div>
          <p className="text-[13.5px] font-bold text-brand-800">Connectors are honest</p>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-brand-700/90">
            Providers that need real API credentials show <strong>“Configured — unverified”</strong> until live access is
            proven by a passing test. AnaRisk never fakes a connected state, and secrets are encrypted at rest and
            never returned by the API.
            {!canRun && ' Your role has read-only access to connectors.'}
          </p>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-[220px] rounded-2xl" />
          ))}
        </div>
      ) : error ? (
        <Card className="p-6">
          <ErrorState title="Could not load integrations" message={error} onRetry={() => void load()} />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((p) => {
            const result = results[p.key];
            const configured = p.status !== 'not_configured';
            return (
              <Card key={p.key} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-gradient-soft text-brand-600">
                      {CATEGORY_ICON[p.category] || <Plug className="h-5 w-5" />}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-[14px] font-bold text-ink">{p.name}</p>
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">{p.category.replace('_', ' ')}</p>
                    </div>
                  </div>
                  <StatusBadge p={p} verified={result?.ok} />
                </div>

                <p className="mt-3 line-clamp-3 flex-1 text-[12.5px] leading-relaxed text-muted">{p.description}</p>

                {configured && p.config_preview && Object.keys(p.config_preview).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {Object.entries(p.config_preview).map(([k, v]) => (
                      <span key={k} className="rounded-full border border-line bg-bg px-2 py-0.5 font-mono text-[10.5px] text-ink-700">
                        {k}={v}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-3 space-y-1 text-[11.5px] text-muted">
                  <p className="flex items-center gap-1.5">
                    <Timer className="h-3.5 w-3.5 text-faint" />
                    Last sync: {p.last_sync_at ? formatRelativeTime(p.last_sync_at) : 'Never'}
                  </p>
                  {p.connected_by && (
                    <p className="flex items-center gap-1.5">
                      <UserIcon className="h-3.5 w-3.5 text-faint" />
                      Connected by {p.connected_by.full_name || p.connected_by.email}
                    </p>
                  )}
                  {p.last_error && <p className="italic text-danger">Last error: {p.last_error}</p>}
                </div>

                {result && (
                  <div
                    className={cn(
                      'mt-3 rounded-xl border px-3 py-2.5',
                      result.ok ? 'border-success-100 bg-success-100/60' : 'border-danger-100 bg-danger-100/60'
                    )}
                  >
                    <p className={cn('text-[12px] font-bold', result.ok ? 'text-success-600' : 'text-danger-600')}>
                      {result.ok ? 'Connection verified' : 'Not verified'} · {formatRelativeTime(result.checked_at)}
                    </p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-ink-700">{result.message}</p>
                  </div>
                )}

                {p.docs_url && (
                  <a
                    href={p.docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-3 inline-flex items-center gap-1 text-[12px] font-semibold text-brand-600 hover:text-brand-700"
                  >
                    Documentation <ExternalLink className="h-3 w-3" />
                  </a>
                )}

                {canRun && (
                  <div className="mt-4 flex flex-wrap gap-2 border-t border-line-soft pt-4">
                    <Button size="sm" variant={configured ? 'outline' : 'primary'} onClick={() => openSetup(p)}>
                      {configured ? 'Configure' : 'Setup'}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={testingKey === p.key}
                      onClick={() => void runTest(p)}
                    >
                      Test
                    </Button>
                    {configured && (
                      <Button size="sm" variant="secondary" loading={syncingKey === p.key} onClick={() => void runSync(p)}>
                        Sync now
                      </Button>
                    )}
                    {configured && (
                      <Button size="sm" variant="ghost" className="ml-auto text-danger" onClick={() => setDisconnectFor(p)}>
                        Disconnect
                      </Button>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* dynamic setup modal */}
      <Modal
        open={!!setupFor}
        onClose={() => setSetupFor(null)}
        title={setupFor ? `${setupFor.status === 'not_configured' ? 'Setup' : 'Configure'} ${setupFor.name}` : ''}
        description={setupFor?.description}
        footer={
          <>
            <Button variant="outline" onClick={() => setSetupFor(null)} disabled={saving}>
              Cancel
            </Button>
            <Button loading={saving} onClick={() => void connect()}>
              Save configuration
            </Button>
          </>
        }
      >
        {setupFor && (
          <div className="space-y-4">
            {setupFor.config_fields.map((f) => (
              <Field
                key={f.key}
                label={f.label}
                required={f.required}
                error={configErrs[f.key] || null}
                hint={f.type === 'secret' ? 'Stored encrypted — the value is never shown again.' : undefined}
                htmlFor={`cfg-${f.key}`}
              >
                {f.type === 'select' ? (
                  <Select
                    id={`cfg-${f.key}`}
                    value={configVals[f.key] || ''}
                    invalid={!!configErrs[f.key]}
                    onChange={(e) => setConfigVals((v) => ({ ...v, [f.key]: e.target.value }))}
                  >
                    <option value="">Select…</option>
                    {(f.options || []).map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </Select>
                ) : f.type === 'secret' ? (
                  <div className="relative">
                    <Input
                      id={`cfg-${f.key}`}
                      type={reveal[f.key] ? 'text' : 'password'}
                      value={configVals[f.key] || ''}
                      placeholder={f.placeholder}
                      className={configErrs[f.key] ? 'pr-10 border-danger' : 'pr-10'}
                      autoComplete="off"
                      onChange={(e) => setConfigVals((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                    <button
                      type="button"
                      onClick={() => setReveal((r) => ({ ...r, [f.key]: !r[f.key] }))}
                      aria-label={reveal[f.key] ? 'Hide value' : 'Show value'}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-faint transition-colors hover:text-ink focus-ring"
                    >
                      {reveal[f.key] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                ) : (
                  <Input
                    id={`cfg-${f.key}`}
                    type={f.type === 'url' ? 'url' : 'text'}
                    value={configVals[f.key] || ''}
                    placeholder={f.placeholder}
                    className={configErrs[f.key] ? 'border-danger' : undefined}
                    autoComplete="off"
                    onChange={(e) => setConfigVals((v) => ({ ...v, [f.key]: e.target.value }))}
                  />
                )}
              </Field>
            ))}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!disconnectFor}
        onClose={() => setDisconnectFor(null)}
        onConfirm={() => void disconnect()}
        title={`Disconnect ${disconnectFor?.name || ''}?`}
        message="The stored configuration is deleted and the provider returns to “Not connected”. You can set it up again later."
        confirmLabel="Disconnect"
        destructive
        loading={disconnecting}
      />
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Monitoring (compact)                                               */
/* ------------------------------------------------------------------ */

const MonitoringTab: React.FC = () => {
  const { hasPermission, brands } = useAuth();
  const { toast } = useToast();
  const canRead = hasPermission('entity:read');
  const canSubmit = hasPermission('entity:submit');
  const canRun = hasPermission('connector:run');

  const [rows, setRows] = useState<PaginatedResponse<MonitoringTarget> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<MonitoringTarget | null>(null);
  const [removing, setRemoving] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [addBrand, setAddBrand] = useState('');
  const [addPackage, setAddPackage] = useState('');
  const [addStore, setAddStore] = useState('google_play');
  const [addUrl, setAddUrl] = useState('');
  const [addErrs, setAddErrs] = useState<Record<string, string>>({});
  const [addSaving, setAddSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await monitoringService.listApps({ page, page_size: 50 });
      setRows(res);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    if (canRead) void load();
  }, [canRead, load]);

  if (!canRead) return <AccessDenied description="App monitoring is not visible to your role." />;

  const addTarget = async () => {
    const errs: Record<string, string> = {};
    if (!addBrand) errs.brand_id = 'Choose a brand';
    if (addPackage.trim().length < 3) errs.package_id = 'Package id must be at least 3 characters';
    setAddErrs(errs);
    if (Object.keys(errs).length > 0) return;
    setAddSaving(true);
    try {
      const res = await apiRequest<{ target: MonitoringTarget; message: string }>('/monitoring/apps', {
        method: 'POST',
        body: JSON.stringify({
          brand_id: addBrand,
          package_id: addPackage.trim(),
          store: addStore,
          store_url: addUrl.trim() || undefined,
        }),
      });
      toast.success('Monitoring started', res.message || `${addPackage.trim()} is now monitored.`);
      setAddOpen(false);
      setAddPackage('');
      setAddUrl('');
      await load();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.code === 'duplicate_monitoring_target')) {
        setAddErrs({ package_id: 'This package is already monitored.' });
      } else {
        const mapped = fieldErrorsOf(e);
        if (mapped) setAddErrs(mapped);
        else toast.error('Could not start monitoring', errText(e));
      }
    } finally {
      setAddSaving(false);
    }
  };

  const setStatus = async (t: MonitoringTarget, status: 'active' | 'paused') => {
    setBusyId(t.id);
    try {
      await monitoringService.updateApp(t.id, { monitoring_status: status });
      toast.success(status === 'active' ? 'Monitoring resumed' : 'Monitoring paused', `${t.app_name || t.package_id}.`);
      await load();
    } catch (e) {
      toast.error('Could not change the status', errText(e));
    } finally {
      setBusyId(null);
    }
  };

  const sync = async (t: MonitoringTarget) => {
    setBusyId(t.id);
    try {
      const res = await monitoringService.syncApp(t.id);
      toast.success('Sync completed', res.message);
      await load();
    } catch (e) {
      toast.error('Sync failed', errText(e));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async () => {
    if (!removeTarget) return;
    setRemoving(true);
    try {
      await monitoringService.removeApp(removeTarget.id);
      toast.success('Monitoring stopped', `${removeTarget.app_name || removeTarget.package_id} is no longer monitored.`);
      setRemoveTarget(null);
      await load();
    } catch (e) {
      toast.error('Could not stop monitoring', errText(e));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Smartphone className="h-4 w-4 text-brand-500" /> Monitored apps
            </CardTitle>
            <CardDescription>Package listings tracked across stores.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Link
              to="/mobile-apps"
              className="inline-flex items-center gap-1 text-[13px] font-semibold text-brand-600 hover:text-brand-700"
            >
              Open full monitoring page <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            {canSubmit && (
              <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setAddOpen(true)}>
                Add
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          ) : error ? (
            <ErrorState title="Could not load monitoring targets" message={error} onRetry={() => void load()} />
          ) : (rows?.items || []).length === 0 ? (
            <EmptyState
              icon={<Package className="h-6 w-6" />}
              title="No apps are monitored"
              description="Track a store package to watch its listing, publisher and permissions over time."
              action={
                canSubmit ? (
                  <Button icon={<Plus className="h-4 w-4" />} onClick={() => setAddOpen(true)}>
                    Add an app
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="divide-y divide-line-soft">
              {(rows?.items || []).map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-bold text-ink">{t.app_name || t.entity?.display_name || 'Unnamed app'}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
                      <code className="rounded bg-line-soft px-1.5 py-0.5 font-mono text-[11px]">{t.package_id}</code>
                      <Badge tone="outline" className="text-[10.5px]">
                        {STORE_LABELS[t.store] || t.store}
                      </Badge>
                      <Badge tone={t.monitoring_status === 'active' ? 'success' : 'warning'} dot>
                        {t.monitoring_status === 'active' ? 'Active' : 'Paused'}
                      </Badge>
                      <span>· synced {formatRelativeTime(t.last_sync_at || null)}</span>
                    </p>
                  </div>
                  <div className="w-32 shrink-0">
                    <ScoreBar value={t.entity?.risk_score ?? null} />
                  </div>
                  <Dropdown
                    align="right"
                    trigger={({ open }) => (
                      <button
                        aria-label={`Actions for ${t.package_id}`}
                        aria-expanded={open}
                        className="rounded-lg p-1.5 text-muted transition-colors hover:bg-line-soft hover:text-ink focus-ring"
                      >
                        <MoreVertical className="h-4 w-4" />
                      </button>
                    )}
                    items={[
                      {
                        label: busyId === t.id ? 'Working…' : 'Sync now',
                        icon: <RefreshCw className="h-4 w-4" />,
                        disabled: !canRun || busyId === t.id,
                        onClick: () => void sync(t),
                      },
                      t.monitoring_status === 'active'
                        ? {
                            label: 'Pause',
                            icon: <Pause className="h-4 w-4" />,
                            disabled: !canSubmit || busyId === t.id,
                            onClick: () => void setStatus(t, 'paused'),
                          }
                        : {
                            label: 'Resume',
                            icon: <Play className="h-4 w-4" />,
                            disabled: !canSubmit || busyId === t.id,
                            onClick: () => void setStatus(t, 'active'),
                          },
                      {
                        label: 'Remove',
                        icon: <Trash2 className="h-4 w-4" />,
                        danger: true,
                        separatorBefore: true,
                        disabled: !canSubmit,
                        onClick: () => setRemoveTarget(t),
                      },
                    ]}
                  />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
        {rows && <Pagination page={rows.page} pages={rows.pages} total={rows.total} onPageChange={setPage} />}
      </Card>

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Monitor an app"
        description="Watch a store listing for impersonation and permission changes."
        footer={
          <>
            <Button variant="outline" onClick={() => setAddOpen(false)} disabled={addSaving}>
              Cancel
            </Button>
            <Button loading={addSaving} onClick={() => void addTarget()}>
              Start monitoring
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Brand" error={addErrs.brand_id || null} required htmlFor="mon-brand">
            <Select id="mon-brand" value={addBrand} onChange={(e) => setAddBrand(e.target.value)} invalid={!!addErrs.brand_id}>
              <option value="">Select a brand…</option>
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Package id" error={addErrs.package_id || null} required htmlFor="mon-package" hint="e.g. com.anarisk.app">
            <Input
              id="mon-package"
              value={addPackage}
              onChange={(e) => setAddPackage(e.target.value)}
              className={addErrs.package_id ? 'border-danger' : undefined}
              placeholder="com.example.app"
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Store" htmlFor="mon-store">
              <Select id="mon-store" value={addStore} onChange={(e) => setAddStore(e.target.value)}>
                <option value="google_play">Google Play</option>
                <option value="app_store">App Store</option>
                <option value="other">Other</option>
              </Select>
            </Field>
            <Field label="Store URL" htmlFor="mon-url" hint="Optional">
              <Input id="mon-url" value={addUrl} onChange={(e) => setAddUrl(e.target.value)} placeholder="https://…" />
            </Field>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!removeTarget}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => void remove()}
        title="Stop monitoring?"
        message={
          <>
            Monitoring for <strong>{removeTarget?.app_name || removeTarget?.package_id}</strong> will stop. The linked
            entity and its history are kept.
          </>
        }
        confirmLabel="Stop monitoring"
        destructive
        loading={removing}
      />
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Notifications                                                      */
/* ------------------------------------------------------------------ */

const PREF_ROWS: Array<{ key: keyof UserPreferences; label: string; description: string }> = [
  { key: 'notify_inapp', label: 'In-app notifications', description: 'Show notifications in the bell menu while you use AnaRisk.' },
  { key: 'notify_case_events', label: 'Case events', description: 'Assignments, status changes, escalations and resolutions.' },
  { key: 'notify_high_risk', label: 'High-risk detections', description: 'New high or critical severity entities in your brands.' },
  { key: 'notify_evidence', label: 'Evidence updates', description: 'New evidence attached to entities and cases you follow.' },
  { key: 'notify_digest', label: 'Weekly digest', description: 'A weekly summary of detections and case activity.' },
];

const DEFAULT_PREFS: UserPreferences = {
  notify_inapp: true,
  notify_case_events: true,
  notify_high_risk: true,
  notify_evidence: true,
  notify_digest: false,
};

const NotificationsTab: React.FC = () => {
  const { user, refreshAuth, hasPermission } = useAuth();
  const { toast } = useToast();

  const [draft, setDraft] = useState<UserPreferences>({ ...DEFAULT_PREFS, ...(user?.preferences || {}) });
  const [saving, setSaving] = useState(false);
  const syncedFor = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (user && syncedFor.current !== user.id) {
      syncedFor.current = user.id;
      setDraft({ ...DEFAULT_PREFS, ...(user.preferences || {}) });
    }
  }, [user]);

  const dirty = PREF_ROWS.some((r) => Boolean(draft[r.key]) !== Boolean((user?.preferences || DEFAULT_PREFS)[r.key]));

  const save = async () => {
    setSaving(true);
    try {
      await authService.updateProfile({ preferences: draft });
      await refreshAuth();
      toast.success('Preferences saved', 'Your notification settings were updated.');
    } catch (e) {
      toast.error('Could not save preferences', errText(e));
    } finally {
      setSaving(false);
    }
  };

  /* live preview */
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [marking, setMarking] = useState(false);

  const loadList = useCallback(async () => {
    setListLoading(true);
    try {
      const res = await notificationService.list({ page_size: 10 });
      setItems(res.items || []);
      setUnread(res.unread_count || 0);
    } catch {
      /* keep the last list */
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const markAllRead = async () => {
    setMarking(true);
    try {
      const res = await notificationService.markRead();
      toast.success('All caught up', `${res.updated} notification(s) marked read.`);
      await loadList();
    } catch (e) {
      toast.error('Could not mark notifications read', errText(e));
    } finally {
      setMarking(false);
    }
  };

  /* administrator broadcast: persisted as one in-app notification per active user */
  const canBroadcast = hasPermission('org:manage');
  const [bcTitle, setBcTitle] = useState('');
  const [bcMessage, setBcMessage] = useState('');
  const [bcSending, setBcSending] = useState(false);
  const [bcStatus, setBcStatus] = useState<string | null>(null);

  const sendBroadcast = async () => {
    if (!bcTitle.trim() || !bcMessage.trim()) return;
    setBcSending(true);
    setBcStatus(null);
    try {
      const res = await notificationService.broadcast(bcTitle.trim(), bcMessage.trim());
      setBcStatus(`Delivered: ${res.created} of ${res.recipients} active users.`);
      toast.success('Announcement sent', `Stored for ${res.created} of ${res.recipients} active users.`);
      setBcTitle('');
      setBcMessage('');
      await loadList();
    } catch (e) {
      setBcStatus('Not delivered — the announcement was not stored for anyone.');
      toast.error('Broadcast failed', errText(e));
    } finally {
      setBcSending(false);
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-brand-500" /> Notification preferences
          </CardTitle>
          <CardDescription>Choose what reaches you inside AnaRisk.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-line-soft">
            {PREF_ROWS.map((r) => (
              <li key={r.key} className="flex items-center justify-between gap-4 py-3.5">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-semibold text-ink">{r.label}</p>
                  <p className="mt-0.5 text-[12px] text-muted">{r.description}</p>
                </div>
                <Switch
                  checked={Boolean(draft[r.key])}
                  onChange={(checked) => setDraft((d) => ({ ...d, [r.key]: checked }))}
                  label={r.label}
                />
              </li>
            ))}
          </ul>
          <div className="mt-4 flex justify-end">
            <Button loading={saving} disabled={!dirty} icon={<Save className="h-4 w-4" />} onClick={() => void save()}>
              Save preferences
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="h-fit">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-brand-500" /> Recent notifications
            </CardTitle>
            <CardDescription>
              {unread > 0 ? `${unread} unread` : 'You are all caught up'} · newest first.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" loading={marking} disabled={unread === 0} icon={<CheckCheck className="h-4 w-4" />} onClick={() => void markAllRead()}>
            Mark all read
          </Button>
        </CardHeader>
        <CardContent>
          {listLoading && items.length === 0 ? (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={<Bell className="h-6 w-6" />}
              title="No notifications yet"
              description="Case assignments, escalations and high-risk detections will show up here."
            />
          ) : (
            <ul className="divide-y divide-line-soft">
              {items.map((n) => (
                <li key={n.id} className={cn('flex items-start gap-3 py-3', !n.is_read && 'rounded-lg bg-brand-50/50 px-2')}>
                  <span
                    className={cn(
                      'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                      n.is_read ? 'bg-line' : 'bg-brand-500'
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className={cn('truncate text-[13px] text-ink', n.is_read ? 'font-medium' : 'font-bold')}>{n.title}</p>
                    {n.body && <p className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-muted">{n.body}</p>}
                    <p className="mt-1 text-[11px] font-medium text-faint">
                      <span className="rounded-full bg-line-soft px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                        {n.type.replace(/_/g, ' ')}
                      </span>{' '}
                      {formatRelativeTime(n.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {canBroadcast && (
        <Card className="h-fit lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-brand-500" /> Broadcast an announcement
            </CardTitle>
            <CardDescription>
              Persists one in-app notification for every active user. Recipients see it in their
              Alerts list — no emails are sent, and the delivery counts below are reported only
              after the rows are actually stored.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-w-2xl space-y-4">
              <Field label="Title" required>
                <Input
                  value={bcTitle}
                  onChange={(e) => setBcTitle(e.target.value)}
                  maxLength={255}
                  placeholder="Scheduled maintenance"
                />
              </Field>
              <Field label="Message" required hint="1-4000 characters">
                <Textarea
                  value={bcMessage}
                  onChange={(e) => setBcMessage(e.target.value)}
                  rows={4}
                  maxLength={4000}
                  placeholder="The platform will be read-only on Sunday from 02:00 UTC."
                />
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  loading={bcSending}
                  disabled={!bcTitle.trim() || !bcMessage.trim()}
                  onClick={() => void sendBroadcast()}
                >
                  Send to all users
                </Button>
                {bcStatus && <p className="text-[12.5px] font-medium text-muted">{bcStatus}</p>}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Feedback: user submissions + administrator review                  */
/* ------------------------------------------------------------------ */

const FEEDBACK_CATEGORIES: Array<{ value: FeedbackCategory; label: string }> = [
  { value: 'bug', label: 'Bug report' },
  { value: 'feature', label: 'Feature request' },
  { value: 'content', label: 'Content / data issue' },
  { value: 'other', label: 'Other' },
];

const FeedbackTab: React.FC = () => {
  const { toast } = useToast();
  const { hasPermission, brands, activeBrand } = useAuth();
  const canReview = hasPermission('org:manage');

  /* submission */
  const [category, setCategory] = useState<FeedbackCategory>('bug');
  const [message, setMessage] = useState('');
  const [pageRef, setPageRef] = useState('');
  const [brandId, setBrandId] = useState<string>(activeBrand?.id || '');
  const [sending, setSending] = useState(false);

  /* admin review */
  const [statusFilter, setStatusFilter] = useState<'all' | FeedbackStatus>('all');
  const [review, setReview] = useState<PaginatedResponse<FeedbackItem> | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewErr, setReviewErr] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const loadReview = React.useCallback(async () => {
    setReviewLoading(true);
    setReviewErr(null);
    try {
      const res = await feedbackService.list({
        status: statusFilter === 'all' ? undefined : statusFilter,
        page: 1,
        page_size: 50,
      });
      setReview(res);
    } catch (e) {
      setReviewErr(errText(e));
    } finally {
      setReviewLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (canReview) void loadReview();
  }, [canReview, loadReview]);

  const send = async () => {
    if (!message.trim()) return;
    setSending(true);
    try {
      await feedbackService.submit({
        category,
        message: message.trim(),
        page_ref: pageRef.trim() || undefined,
        brand_id: brandId || undefined,
      });
      toast.success('Feedback sent', 'Thanks — administrators can review it in this tab.');
      setMessage('');
      setPageRef('');
      if (canReview) void loadReview();
    } catch (e) {
      toast.error('Could not send feedback', errText(e));
    } finally {
      setSending(false);
    }
  };

  const setStatus = async (row: FeedbackItem, status: FeedbackStatus) => {
    setUpdatingId(row.id);
    try {
      await feedbackService.setStatus(row.id, status);
      toast.success(status === 'resolved' ? 'Marked resolved' : 'Reopened', row.message.slice(0, 60));
      void loadReview();
    } catch (e) {
      toast.error('Could not update status', errText(e));
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-brand-500" /> Send feedback
          </CardTitle>
          <CardDescription>
            Report a bug, request a feature, or flag bad content. Submissions are stored with
            your workspace scope and reviewed by administrators.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid max-w-2xl gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Category" required>
                <Select value={category} onChange={(e) => setCategory(e.target.value as FeedbackCategory)}>
                  {FEEDBACK_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Brand context (optional)">
                <Select value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                  <option value="">No specific brand</option>
                  {brands.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Message" required hint="1-4000 characters">
              <Textarea
                rows={5}
                maxLength={4000}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="What happened, and what did you expect?"
              />
            </Field>
            <Field label="Page or feature (optional)" hint="e.g. /risk-graph or “Evidence Center upload”">
              <Input
                value={pageRef}
                onChange={(e) => setPageRef(e.target.value)}
                maxLength={500}
                placeholder="/investigate"
              />
            </Field>
            <div>
              <Button loading={sending} disabled={!message.trim()} onClick={() => void send()}>
                Send feedback
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {canReview && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-4 w-4 text-brand-500" /> All submissions
                </CardTitle>
                <CardDescription>
                  Administrator triage across every workspace — global view for review only.
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Select
                  aria-label="Filter feedback by status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as 'all' | FeedbackStatus)}
                  className="w-auto"
                >
                  <option value="all">All statuses</option>
                  <option value="open">Open</option>
                  <option value="resolved">Resolved</option>
                </Select>
                <Button variant="outline" size="sm" onClick={() => void loadReview()} loading={reviewLoading}>
                  Refresh
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {reviewLoading && !review && <p className="text-[13px] text-muted">Loading…</p>}
            {reviewErr && <p className="text-[13px] text-danger">{reviewErr}</p>}
            {review && review.items.length === 0 && (
              <p className="text-[13px] text-muted">No feedback matches this filter.</p>
            )}
            {review && review.items.length > 0 && (
              <ul className="divide-y divide-line-soft">
                {review.items.map((row) => (
                  <li key={row.id} className="flex flex-wrap items-start justify-between gap-3 py-3.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="outline">{FEEDBACK_CATEGORIES.find((c) => c.value === row.category)?.label || row.category}</Badge>
                        <Badge tone={row.status === 'resolved' ? 'success' : 'warning'}>
                          {row.status === 'resolved' ? 'Resolved' : 'Open'}
                        </Badge>
                        <span className="text-[11.5px] font-medium text-faint">
                          {row.user_email || 'unknown user'} · {formatRelativeTime(row.created_at)}
                          {row.page_ref ? ` · ${row.page_ref}` : ''}
                        </span>
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink-700">
                        {row.message}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <Button
                        variant="outline"
                        size="sm"
                        loading={updatingId === row.id}
                        disabled={updatingId !== null}
                        onClick={() => void setStatus(row, row.status === 'resolved' ? 'open' : 'resolved')}
                      >
                        {row.status === 'resolved' ? 'Reopen' : 'Mark resolved'}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {review && review.pages > 1 && (
              <p className="mt-3 text-[11.5px] text-muted">
                Showing {review.items.length} of {review.total} (page {review.page} of {review.pages}).
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Security                                                           */
/* ------------------------------------------------------------------ */

const ACTION_TONES: Record<string, BadgeTone> = {
  auth: 'info',
  case: 'violet',
  entity: 'primary',
  evidence: 'warning',
  integration: 'success',
  user: 'outline',
  organization: 'default',
  brand: 'default',
};

const ACTION_PREFIXES = ['auth', 'case', 'entity', 'evidence', 'integration', 'user'];

const SecurityTab: React.FC = () => {
  const { hasPermission } = useAuth();
  const canRead = hasPermission('audit:read');

  const [rows, setRows] = useState<PaginatedResponse<AuditLog> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [prefix, setPrefix] = useState('');
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await settingsService.listAudit({ page, page_size: 20, action: prefix || undefined });
      setRows(res);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, [page, prefix]);

  useEffect(() => {
    if (canRead) void load();
  }, [canRead, load]);

  const filtered = useMemo(() => {
    const items = rows?.items || [];
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((r) =>
      [r.actor_email, r.action, r.resource_type, r.resource_id, r.ip_address]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [rows, search]);

  if (!canRead) return <AccessDenied description="The audit trail is restricted to roles with audit:read." />;

  return (
    <div className="grid gap-5">
      <div className="flex items-start gap-3 rounded-2xl border border-brand-200 bg-brand-50 p-4">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm">
          <ShieldCheck className="h-4 w-4" />
        </span>
        <div>
          <p className="text-[13.5px] font-bold text-brand-800">Security posture</p>
          <ul className="mt-1 grid gap-1 text-[12.5px] leading-relaxed text-brand-700/90 sm:grid-cols-2">
            <li>• Passwords hashed with bcrypt — never stored or logged in plain text.</li>
            <li>• API sessions use short-lived JWT bearer tokens.</li>
            <li>• Role-based access control: every endpoint checks a named permission.</li>
            <li>• Every mutation is recorded in the audit trail below.</li>
            <li>• Integration secrets are encrypted at rest and never returned by the API.</li>
            <li>• Authentication endpoints are rate-limited to slow credential stuffing.</li>
          </ul>
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-brand-500" /> Audit trail
            </CardTitle>
            <CardDescription>Every recorded action, newest first.</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <FilterSelect
              label="Filter by action prefix"
              value={prefix}
              onChange={(v) => {
                setPrefix(v);
                setPage(1);
              }}
              options={ACTION_PREFIXES.map((p) => ({ value: p, label: p }))}
              allLabel="All actions"
            />
            <SearchInput value={search} onChange={setSearch} placeholder="Search this page…" className="w-56" debounceMs={250} />
          </div>
        </CardHeader>
        <CardContent className="border-b border-line-soft">
          {loading ? (
            <div className="space-y-3">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-10 rounded-lg" />
              ))}
            </div>
          ) : error ? (
            <ErrorState title="Could not load the audit trail" message={error} onRetry={() => void load()} />
          ) : (
            <DataTable
              columns={[
                {
                  key: 'time',
                  header: 'Time',
                  cell: (r: AuditLog) => <span className="whitespace-nowrap text-[12.5px]">{formatDate(r.created_at)}</span>,
                },
                {
                  key: 'actor',
                  header: 'Actor',
                  cell: (r: AuditLog) => (
                    <span className="flex items-center gap-2 text-[12.5px]">
                      <Avatar name={r.actor_email || 'system'} size={22} />
                      {r.actor_email || <span className="text-faint">system</span>}
                    </span>
                  ),
                },
                {
                  key: 'action',
                  header: 'Action',
                  cell: (r: AuditLog) => {
                    const pfx = r.action.split('.')[0];
                    return <Badge tone={ACTION_TONES[pfx] || 'default'}>{r.action}</Badge>;
                  },
                },
                {
                  key: 'resource',
                  header: 'Resource',
                  cell: (r: AuditLog) => (
                    <span className="text-[12.5px]">
                      <span className="font-semibold text-ink">{r.resource_type}</span>
                      {r.resource_id && (
                        <code className="ml-1.5 rounded bg-line-soft px-1.5 py-0.5 font-mono text-[11px] text-ink-700" title={r.resource_id}>
                          {r.resource_id.slice(0, 8)}…
                        </code>
                      )}
                    </span>
                  ),
                },
                {
                  key: 'ip',
                  header: 'IP',
                  cell: (r: AuditLog) => <span className="font-mono text-[12px] text-muted">{r.ip_address || '—'}</span>,
                },
              ]}
              rows={filtered}
              rowKey={(r) => r.id}
              emptyState={
                <EmptyState
                  icon={<FileText className="h-6 w-6" />}
                  title={search || prefix ? 'No matching audit entries' : 'No audit entries yet'}
                  description={search || prefix ? 'Try a different filter.' : 'Actions performed in the app will be recorded here.'}
                />
              }
            />
          )}
        </CardContent>
        {rows && <Pagination page={rows.page} pages={rows.pages} total={rows.total} onPageChange={setPage} />}
      </Card>
    </div>
  );
};

export default SettingsPage;
