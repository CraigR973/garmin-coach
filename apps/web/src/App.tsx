import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { installResumeRefetch } from './lib/resumeRefetch';
import { AuthProvider } from './contexts/AuthContext';
import { LeagueProvider } from './contexts/LeagueContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ErrorBoundary } from './components/ErrorBoundary';
import { UpdateBanner } from './components/UpdateBanner';
import { InstallPromptController } from './components/InstallPromptController';
import { FirstRunController } from './components/FirstRunController';
import { NotificationsPromptController } from './components/NotificationsPromptController';
import { Week1SurveyController } from './components/Week1SurveyController';
import { TournamentRevealModal } from './components/TournamentRevealModal';
import { Skeleton } from './components/ui/skeleton';
import { LoginPage } from './pages/LoginPage';
import { JoinPage } from './pages/JoinPage';
import { DEFAULT_LEAGUE_SLUG } from './lib/api';

// Layout pulls in framer-motion + supabase realtime via NavBar/OfflineBanner;
// lazy-loading it keeps those deps out of the unauthenticated /login chunk.
const Layout = lazy(() => import('./components/Layout').then((m) => ({ default: m.Layout })));

// Lazy-loaded routes: only login + join ship eagerly so the unauth entry is fast.
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const SchedulePage = lazy(() => import('./pages/SchedulePage').then((m) => ({ default: m.SchedulePage })));
const PredictionsPage = lazy(() => import('./pages/PredictionsPage').then((m) => ({ default: m.PredictionsPage })));
const GroupPredictionsPage = lazy(() => import('./pages/GroupPredictionsPage').then((m) => ({ default: m.GroupPredictionsPage })));
const KnockoutPredictionsPage = lazy(() => import('./pages/KnockoutPredictionsPage').then((m) => ({ default: m.KnockoutPredictionsPage })));
const SpecialsPage = lazy(() => import('./pages/SpecialsPage').then((m) => ({ default: m.SpecialsPage })));
const BracketPage = lazy(() => import('./pages/BracketPage').then((m) => ({ default: m.BracketPage })));
const GroupsPage = lazy(() => import('./pages/GroupsPage').then((m) => ({ default: m.GroupsPage })));
const GroupDetailPage = lazy(() => import('./pages/GroupDetailPage').then((m) => ({ default: m.GroupDetailPage })));
const MatchDetailPage = lazy(() => import('./pages/MatchDetailPage').then((m) => ({ default: m.MatchDetailPage })));
const LeaderboardPage = lazy(() => import('./pages/LeaderboardPage').then((m) => ({ default: m.LeaderboardPage })));
const LeaderboardHistoryPage = lazy(() => import('./pages/LeaderboardHistoryPage').then((m) => ({ default: m.LeaderboardHistoryPage })));
const RoundLeaderboardPage = lazy(() => import('./pages/RoundLeaderboardPage').then((m) => ({ default: m.RoundLeaderboardPage })));
const PlayerProfilePage = lazy(() => import('./pages/PlayerProfilePage').then((m) => ({ default: m.PlayerProfilePage })));
const ComparePage = lazy(() => import('./pages/ComparePage').then((m) => ({ default: m.ComparePage })));
const OfflinePage = lazy(() => import('./pages/OfflinePage').then((m) => ({ default: m.OfflinePage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const AboutPage = lazy(() => import('./pages/AboutPage').then((m) => ({ default: m.AboutPage })));
const AdminInvitesPage = lazy(() => import('./pages/admin/InvitesPage').then((m) => ({ default: m.AdminInvitesPage })));
const AdminPlayersPage = lazy(() => import('./pages/admin/PlayersPage').then((m) => ({ default: m.AdminPlayersPage })));
const AdminDashboardPage = lazy(() => import('./pages/admin/DashboardPage').then((m) => ({ default: m.AdminDashboardPage })));
const AdminSyncPage = lazy(() => import('./pages/admin/SyncPage').then((m) => ({ default: m.AdminSyncPage })));
const AdminResultsPage = lazy(() => import('./pages/admin/ResultsPage').then((m) => ({ default: m.AdminResultsPage })));
const AdminAllLeaguesPage = lazy(() => import('./pages/admin/AllLeaguesPage').then((m) => ({ default: m.AdminAllLeaguesPage })));

// U10 new pages
const ForgotPinPage = lazy(() => import('./pages/ForgotPinPage').then((m) => ({ default: m.ForgotPinPage })));
const PinResetPage = lazy(() => import('./pages/PinResetPage').then((m) => ({ default: m.PinResetPage })));

// M6 new pages
const SignupPage = lazy(() => import('./pages/SignupPage').then((m) => ({ default: m.SignupPage })));
const VerifyEmailPage = lazy(() => import('./pages/VerifyEmailPage').then((m) => ({ default: m.VerifyEmailPage })));
const MyLeaguesPage = lazy(() => import('./pages/MyLeaguesPage').then((m) => ({ default: m.MyLeaguesPage })));
const GlobalLeaderboardPage = lazy(() => import('./pages/GlobalLeaderboardPage').then((m) => ({ default: m.GlobalLeaderboardPage })));
const CreateLeaguePage = lazy(() => import('./pages/CreateLeaguePage').then((m) => ({ default: m.CreateLeaguePage })));
const DiscoverLeaguesPage = lazy(() => import('./pages/DiscoverLeaguesPage').then((m) => ({ default: m.DiscoverLeaguesPage })));
const LeagueMembersPage = lazy(() => import('./pages/LeagueMembersPage').then((m) => ({ default: m.LeagueMembersPage })));
const LeagueSettingsPage = lazy(() => import('./pages/LeagueSettingsPage').then((m) => ({ default: m.LeagueSettingsPage })));
const LeagueJoinRequestsPage = lazy(() => import('./pages/LeagueJoinRequestsPage').then((m) => ({ default: m.LeagueJoinRequestsPage })));
const LeagueAdminInvitesPage = lazy(() => import('./pages/LeagueAdminInvitesPage').then((m) => ({ default: m.LeagueAdminInvitesPage })));

// U12 new pages
const JoinByCodePage = lazy(() => import('./pages/JoinByCodePage').then((m) => ({ default: m.JoinByCodePage })));
const WelcomePage = lazy(() => import('./pages/WelcomePage').then((m) => ({ default: m.WelcomePage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

// Widen the focus signal so refetchOnWindowFocus also fires on iOS PWA warm
// resume (pageshow/bfcache restore), not just visibilitychange. See resumeRefetch.ts.
installResumeRefetch();

function RouteFallback() {
  return (
    <div className="space-y-4" aria-label="Loading page">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-[320px] w-full" />
    </div>
  );
}

/**
 * Wraps protected routes with LeagueProvider.
 * Must be inside BrowserRouter (for useNavigate) and QueryClientProvider (for useQuery).
 */
function LeagueAwareLayout() {
  return (
    <LeagueProvider>
      <Outlet />
    </LeagueProvider>
  );
}

/**
 * Redirects /leagues/:slug/members and siblings to the new /admin/* sub-paths.
 * Reads :slug from URL params so the slug is preserved exactly.
 */
function LeagueAdminRedirect({ suffix }: { suffix: string }) {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  return <Navigate to={`/leagues/${slug}/admin/${suffix}`} replace />;
}

/**
 * The league landing page is now the leaderboard itself — entering a league
 * drops you straight onto the full standings (no intermediate summary page).
 */
function LeagueHomeRedirect() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  return <Navigate to={`/leagues/${slug}/leaderboard`} replace />;
}

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
          <UpdateBanner />
          <InstallPromptController />
          <FirstRunController />
          <NotificationsPromptController />
          <Week1SurveyController />
          <TournamentRevealModal />
          <Toaster position="bottom-right" richColors closeButton />
          <ErrorBoundary>
            <Suspense fallback={<RouteFallback />}>
              <Routes>
                {/* Public routes (no auth, no league context) */}
                <Route path="/login" element={<LoginPage />} />
                <Route path="/signup" element={<SignupPage />} />
                <Route path="/forgot-pin" element={<ForgotPinPage />} />
                <Route path="/pin/reset/:token" element={<PinResetPage />} />
                <Route path="/verify-email/:token" element={<VerifyEmailPage />} />
                <Route path="/join/:token" element={<JoinPage />} />
                <Route path="/welcome" element={<WelcomePage />} />

                {/* Protected: authenticated + LeagueProvider */}
                <Route element={<ProtectedRoute />}>
                  <Route element={<LeagueAwareLayout />}>
                    {/* Standard app shell with TopBar + TabBar */}
                    <Route element={<Layout />}>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/schedule" element={<SchedulePage />} />
                      <Route path="/predictions" element={<PredictionsPage />} />
                      <Route path="/predictions/group" element={<GroupPredictionsPage />} />
                      <Route path="/predictions/knockout" element={<KnockoutPredictionsPage />} />
                      <Route path="/predictions/specials" element={<SpecialsPage />} />
                      <Route path="/bracket" element={<BracketPage />} />
                      <Route path="/groups" element={<GroupsPage />} />
                      <Route path="/groups/:name" element={<GroupDetailPage />} />
                      <Route path="/matches/:id" element={<MatchDetailPage />} />
                      <Route path="/players/:id" element={<PlayerProfilePage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="/about" element={<AboutPage />} />
                      <Route path="/offline" element={<OfflinePage />} />

                      {/* Global cross-league standings */}
                      <Route path="/leaderboard/global" element={<GlobalLeaderboardPage />} />

                      {/* Old top-level routes → redirect to the Leagues hub */}
                      <Route path="/leaderboard" element={<Navigate to="/leagues" replace />} />
                      <Route path="/leaderboard/history" element={<Navigate to="/leagues" replace />} />
                      <Route path="/leaderboard/round/:stage" element={<Navigate to="/leagues" replace />} />
                      <Route path="/compare" element={<Navigate to="/leagues" replace />} />

                      {/* League management — public (all members) */}
                      <Route path="/leagues" element={<MyLeaguesPage />} />
                      <Route path="/leagues/new" element={<CreateLeaguePage />} />
                      <Route path="/leagues/discover" element={<DiscoverLeaguesPage />} />
                      <Route path="/leagues/join" element={<JoinByCodePage />} />
                      <Route path="/leagues/:slug" element={<LeagueHomeRedirect />} />

                      {/* Per-league standings + compare */}
                      <Route path="/leagues/:slug/leaderboard" element={<LeaderboardPage />} />
                      <Route path="/leagues/:slug/leaderboard/history" element={<LeaderboardHistoryPage />} />
                      <Route path="/leagues/:slug/leaderboard/round/:stage" element={<RoundLeaderboardPage />} />
                      <Route path="/leagues/:slug/compare" element={<ComparePage />} />

                      {/* Old per-league member/settings paths → redirect to /admin/* sub-paths */}
                      <Route path="/leagues/:slug/members" element={<LeagueAdminRedirect suffix="members" />} />
                      <Route path="/leagues/:slug/settings" element={<LeagueAdminRedirect suffix="settings" />} />
                      <Route path="/leagues/:slug/requests" element={<LeagueAdminRedirect suffix="requests" />} />

                      {/* Per-league admin */}
                      <Route path="/leagues/:slug/admin/members" element={<LeagueMembersPage />} />
                      <Route path="/leagues/:slug/admin/settings" element={<LeagueSettingsPage />} />
                      <Route path="/leagues/:slug/admin/requests" element={<LeagueJoinRequestsPage />} />
                      <Route path="/leagues/:slug/admin/invites" element={<LeagueAdminInvitesPage />} />
                    </Route>
                  </Route>
                </Route>

                {/* Admin-only routes — no LeagueProvider needed */}
                <Route element={<ProtectedRoute requireAdmin />}>
                  <Route element={<Layout />}>
                    <Route path="/admin" element={<AdminDashboardPage />} />
                    <Route path="/admin/sync" element={<AdminSyncPage />} />
                    <Route path="/admin/results" element={<AdminResultsPage />} />
                    <Route path="/admin/invites" element={<AdminInvitesPage />} />
                    <Route path="/admin/players" element={<AdminPlayersPage />} />
                    <Route path="/admin/all-leagues" element={<AdminAllLeaguesPage />} />
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
