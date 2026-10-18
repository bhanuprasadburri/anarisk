import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, ProtectedRoute } from './hooks/useAuth';
import { ToastProvider } from './components/ui/toast';
import { AppShell } from './components/layout/AppShell';
import { LoadingBlock } from './components/ui/misc';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'));
const ResetPasswordPage = lazy(() => import('./pages/ResetPasswordPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const AssetsPage = lazy(() => import('./pages/AssetsPage'));
const EntityDetailPage = lazy(() => import('./pages/EntityDetailPage'));
const ThreatIntelPage = lazy(() => import('./pages/ThreatIntelPage'));
const RiskGraphPage = lazy(() => import('./pages/RiskGraphPage'));
const CasesPage = lazy(() => import('./pages/CasesPage'));
const CaseDetailPage = lazy(() => import('./pages/CaseDetailPage'));
const MobileAppsPage = lazy(() => import('./pages/MobileAppsPage'));
const EvidencePage = lazy(() => import('./pages/EvidencePage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const VerifyEmailPage = lazy(() => import('./pages/VerifyEmailPage'));
const InvestigatePage = lazy(() => import('./pages/InvestigatePage'));
const AssistantPage = lazy(() => import('./pages/AssistantPage'));
const AlertsPage = lazy(() => import('./pages/AlertsPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const NotFoundPage: React.FC = () => {
  const location = useLocation();
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center text-center">
      <p className="text-6xl font-extrabold tracking-tight text-brand-200">404</p>
      <h1 className="mt-4 text-xl font-bold text-ink">Page not found</h1>
      <p className="mt-1.5 max-w-md text-sm text-muted">
        The path <code className="rounded bg-line-soft px-1.5 py-0.5 text-[13px]">{location.pathname}</code> doesn't
        exist in AnaRisk.
      </p>
      <a
        href="/dashboard"
        className="mt-6 inline-flex h-10 items-center rounded-xl bg-brand-gradient px-5 text-sm font-semibold text-white shadow-sm hover:brightness-110"
      >
        Back to Overview
      </a>
    </div>
  );
};

const Page: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Suspense fallback={<LoadingBlock label="Loading page…" />}>{children}</Suspense>
);

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Page><LoginPage /></Page>} />
              <Route path="/forgot-password" element={<Page><ForgotPasswordPage /></Page>} />
              <Route path="/reset-password" element={<Page><ResetPasswordPage /></Page>} />
              <Route path="/verify-email" element={<Page><VerifyEmailPage /></Page>} />
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <Page><DashboardPage /></Page>
                    </AppShell>
                  </ProtectedRoute>
                }
              >
                <Route index element={<Navigate to="/dashboard" replace />} />
              </Route>
              {[
                { path: '/dashboard', el: <DashboardPage /> },
                { path: '/assets', el: <AssetsPage /> },
                { path: '/entities/:id', el: <EntityDetailPage /> },
                { path: '/threat-intelligence', el: <ThreatIntelPage /> },
                { path: '/investigate', el: <InvestigatePage /> },
                { path: '/assistant', el: <AssistantPage /> },
                { path: '/alerts', el: <AlertsPage /> },
                { path: '/risk-graph', el: <RiskGraphPage /> },
                { path: '/cases', el: <CasesPage /> },
                { path: '/cases/:id', el: <CaseDetailPage /> },
                { path: '/mobile-apps', el: <MobileAppsPage /> },
                { path: '/evidence', el: <EvidencePage /> },
                { path: '/reports', el: <ReportsPage /> },
                { path: '/settings', el: <SettingsPage /> },
              ].map((r) => (
                <Route
                  key={r.path}
                  path={r.path}
                  element={
                    <ProtectedRoute>
                      <AppShell>
                        <Page>{r.el}</Page>
                      </AppShell>
                    </ProtectedRoute>
                  }
                />
              ))}
              <Route
                path="*"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <NotFoundPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
};

export default App;
