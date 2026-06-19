import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { installResumeRefetch } from './lib/resumeRefetch';
import { AuthProvider } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ErrorBoundary } from './components/ErrorBoundary';
import { UpdateBanner } from './components/UpdateBanner';
import { InstallPromptController } from './components/InstallPromptController';
import { NotificationsPromptController } from './components/NotificationsPromptController';
import { Skeleton } from './components/ui/skeleton';
import { LoginPage } from './pages/LoginPage';

// Layout pulls framer-motion + OfflineBanner — lazy-load to keep login chunk lean.
const Layout = lazy(() => import('./components/Layout').then((m) => ({ default: m.Layout })));

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const OfflinePage = lazy(() =>
  import('./pages/OfflinePage').then((m) => ({ default: m.OfflinePage })),
);
const ForgotPinPage = lazy(() =>
  import('./pages/ForgotPinPage').then((m) => ({ default: m.ForgotPinPage })),
);
const PinResetPage = lazy(() =>
  import('./pages/PinResetPage').then((m) => ({ default: m.PinResetPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

// Widen the focus signal so refetchOnWindowFocus also fires on iOS PWA warm
// resume (pageshow/bfcache restore), not just visibilitychange.
installResumeRefetch();

function RouteFallback() {
  return (
    <div className="space-y-4" aria-label="Loading page">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-[320px] w-full" />
    </div>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <UpdateBanner />
            <InstallPromptController />
            <NotificationsPromptController />
            <Toaster position="bottom-right" richColors closeButton />
            <ErrorBoundary>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  {/* Public routes */}
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/forgot-pin" element={<ForgotPinPage />} />
                  <Route path="/pin/reset/:token" element={<PinResetPage />} />

                  {/* Protected routes */}
                  <Route element={<ProtectedRoute />}>
                    <Route element={<Layout />}>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="/offline" element={<OfflinePage />} />
                    </Route>
                  </Route>

                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
