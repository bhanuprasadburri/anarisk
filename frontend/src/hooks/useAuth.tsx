import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Brand, CurrentUser, UserPreferences } from '../types';
import { authService } from '../services/authService';
import { brandService } from '../services/brandService';
import { checkBackendHealth, ApiError } from '../services/apiClient';

interface AuthContextType {
  user: CurrentUser | null;
  role: string;
  isAuthenticated: boolean;
  isLoading: boolean;
  isBackendConnected: boolean;
  brands: Brand[];
  activeBrand: Brand | null;
  setActiveBrand: (brand: Brand | null) => void;
  refreshBrands: () => Promise<void>;
  login: (email: string, password: string) => Promise<CurrentUser>;
  logout: () => void;
  refreshAuth: () => Promise<void>;
  updateProfile: (payload: {
    full_name?: string;
    email?: string;
    preferences?: UserPreferences;
  }) => Promise<void>;
  hasPermission: (perm: string) => boolean;
}

// Mirrors app/core/permissions.py (backend). The backend is authoritative — this matrix only
// drives which controls the UI shows, never access itself (every endpoint re-checks server-side).
const ROLE_PERMISSIONS: Record<string, string[]> = {
  administrator: ['*'],
  investigator: [
    'brand:read', 'entity:read', 'entity:submit', 'entity:analyze', 'evidence:read', 'evidence:write',
    'graph:read', 'graph:write', 'case:read', 'case:create', 'case:triage', 'case:assign',
    'case:escalate', 'case:resolve', 'case:note', 'dashboard:read', 'audit:read', 'connector:run', 'url:inspect',
  ],
  brand_owner: [
    'brand:read', 'brand:write', 'entity:read', 'entity:submit', 'evidence:read', 'evidence:write',
    'graph:read', 'case:read', 'case:note', 'dashboard:read',
  ],
  partner: ['brand:read', 'entity:read', 'evidence:read', 'case:read', 'case:note'],
};

const ACTIVE_BRAND_KEY = 'nimbus_active_brand';

/** First permitted page for a role (e.g. partners have no dashboard:read -> Investigations). */
export const homePathFor = (role: string | undefined): string => {
  const perms = ROLE_PERMISSIONS[role ?? ''] || [];
  return perms.includes('*') || perms.includes('dashboard:read') ? '/dashboard' : '/cases';
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isBackendConnected, setIsBackendConnected] = useState(true);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [activeBrand, setActiveBrandState] = useState<Brand | null>(null);

  // Selection made at login (or later) is persisted so page reloads keep the same scope.
  const setActiveBrand = useCallback((brand: Brand | null) => {
    setActiveBrandState(brand);
    try {
      if (brand) localStorage.setItem(ACTIVE_BRAND_KEY, brand.id);
      else localStorage.removeItem(ACTIVE_BRAND_KEY);
    } catch { /* storage unavailable (private mode) — selection stays in memory */ }
  }, []);

  const refreshBrands = useCallback(async () => {
    try {
      const res = await brandService.listBrands({ page_size: 100 });
      const items = Array.isArray(res) ? (res as Brand[]) : res.items || [];
      setBrands(items);
      let storedId: string | null = null;
      try { storedId = localStorage.getItem(ACTIVE_BRAND_KEY); } catch { /* ignore */ }
      setActiveBrandState((prev) => {
        const wanted = prev?.id ?? storedId;
        return (wanted && items.find((b) => b.id === wanted)) || items[0] || null;
      });
    } catch {
      setBrands([]);
    }
  }, []);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      const backendOk = await checkBackendHealth();
      setIsBackendConnected(backendOk);
      if (localStorage.getItem('nimbus_auth_token')) {
        try {
          const me = await authService.getCurrentUser();
          setUser(me);
          await refreshBrands();
        } catch {
          authService.logout();
          setUser(null);
        }
      }
      setIsLoading(false);
    })();
  }, [refreshBrands]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authService.login(email, password);
    const me = await authService.getCurrentUser();
    const fresh = me || (res.user as CurrentUser);
    setUser(fresh);
    await refreshBrands();
    return fresh;
  }, [refreshBrands]);

  const logout = useCallback(() => {
    authService.logout();
    setUser(null);
    setBrands([]);
    setActiveBrand(null);
  }, []);

  const refreshAuth = useCallback(async () => {
    try {
      const me = await authService.getCurrentUser();
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) logout();
    }
  }, [logout]);

  const updateProfile = useCallback(
    async (payload: { full_name?: string; email?: string; preferences?: UserPreferences }) => {
      const me = await authService.updateProfile(payload);
      setUser(me);
    },
    []
  );

  const hasPermission = useCallback(
    (perm: string) => {
      const role = user?.role || '';
      const perms = ROLE_PERMISSIONS[role] || [];
      return perms.includes('*') || perms.includes(perm);
    },
    [user]
  );

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      role: user?.role || '',
      isAuthenticated: !!user,
      isLoading,
      isBackendConnected,
      brands,
      activeBrand,
      setActiveBrand,
      refreshBrands,
      login,
      logout,
      refreshAuth,
      updateProfile,
      hasPermission,
    }),
    [user, isLoading, isBackendConnected, brands, activeBrand, refreshBrands, login, logout, refreshAuth, updateProfile, hasPermission]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};

/** Route guard: redirects to /login when unauthenticated. */
export const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <div className="flex flex-col items-center gap-3">
          <div className="h-9 w-9 animate-spin rounded-full border-[3px] border-brand-200 border-t-brand-500" />
          <p className="text-[13px] font-medium text-muted">Loading AnaRisk…</p>
        </div>
      </div>
    );
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
};
