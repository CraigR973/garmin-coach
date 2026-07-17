import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { queryClient, persistOptions } from './lib/queryClient';
import { installResumeRefetch } from './lib/resumeRefetch';
import { AuthProvider } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AppToaster } from './components/AppToaster';
import { ScrollToTop } from './components/ScrollToTop';
import { PushNavigationController } from './components/PushNavigationController';
import { UpdateBanner } from './components/UpdateBanner';
import { InstallPromptController } from './components/InstallPromptController';
import { NotificationsPromptController } from './components/NotificationsPromptController';
import { Skeleton } from './components/ui/skeleton';
import { ActivatePage } from './pages/ActivatePage';
import { LoginPage } from './pages/LoginPage';

// Layout pulls framer-motion + OfflineBanner — lazy-load to keep login chunk lean.
const Layout = lazy(() => import('./components/Layout').then((m) => ({ default: m.Layout })));

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const CheckInPage = lazy(() =>
  import('./pages/CheckInPage').then((m) => ({ default: m.CheckInPage })),
);
const MorningBriefPage = lazy(() =>
  import('./pages/MorningBriefPage').then((m) => ({ default: m.MorningBriefPage })),
);
const SleepPage = lazy(() =>
  import('./pages/SleepPage').then((m) => ({ default: m.SleepPage })),
);
const EnvironmentPage = lazy(() =>
  import('./pages/EnvironmentPage').then((m) => ({ default: m.EnvironmentPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const CoachStatePage = lazy(() =>
  import('./pages/CoachStatePage').then((m) => ({ default: m.CoachStatePage })),
);
const WeekAheadPage = lazy(() =>
  import('./pages/WeekAheadPage').then((m) => ({ default: m.WeekAheadPage })),
);
const HolidayPage = lazy(() =>
  import('./pages/HolidayPage').then((m) => ({ default: m.HolidayPage })),
);
const BlockGeneratorPage = lazy(() =>
  import('./pages/BlockGeneratorPage').then((m) => ({ default: m.BlockGeneratorPage })),
);
const ReviewsPage = lazy(() =>
  import('./pages/ReviewsPage').then((m) => ({ default: m.ReviewsPage })),
);
const TrendsPage = lazy(() =>
  import('./pages/TrendsPage').then((m) => ({ default: m.TrendsPage })),
);
const ExperimentsPage = lazy(() =>
  import('./pages/ExperimentsPage').then((m) => ({ default: m.ExperimentsPage })),
);
const HandoverPage = lazy(() =>
  import('./pages/HandoverPage').then((m) => ({ default: m.HandoverPage })),
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
      <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
        <BrowserRouter>
          <PushNavigationController />
          <ScrollToTop />
          <AuthProvider>
            <UpdateBanner />
            <InstallPromptController />
            <NotificationsPromptController />
            <AppToaster />
            <ErrorBoundary>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  {/* Public routes */}
                  <Route path="/activate" element={<ActivatePage />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/forgot-pin" element={<ForgotPinPage />} />
                  <Route path="/pin/reset/:token" element={<PinResetPage />} />

                  {/* Protected routes */}
                  <Route element={<ProtectedRoute />}>
                    <Route element={<Layout />}>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/check-in" element={<CheckInPage />} />
                      <Route path="/brief" element={<MorningBriefPage />} />
                      <Route path="/sleep" element={<SleepPage />} />
                      <Route path="/environment" element={<EnvironmentPage />} />
                      <Route path="/bedroom" element={<Navigate to="/environment" replace />} />
                      <Route path="/delivery" element={<WeekAheadPage />} />
                      <Route path="/holiday" element={<HolidayPage />} />
                      <Route path="/builder" element={<BlockGeneratorPage />} />
                      <Route path="/reviews" element={<ReviewsPage />} />
                      <Route path="/trends" element={<TrendsPage />} />
                      <Route path="/experiments" element={<ExperimentsPage />} />
                      <Route path="/handover" element={<HandoverPage />} />
                      <Route path="/coach-state" element={<CoachStatePage />} />
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
      </PersistQueryClientProvider>
    </ThemeProvider>
  );
}
