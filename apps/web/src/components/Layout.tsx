import { Outlet, useLocation } from 'react-router-dom';
import { TopBar } from './TopBar';
import { TabBar } from './TabBar';
import { OfflineBanner } from './OfflineBanner';
import { ErrorBoundary } from './ErrorBoundary';
import { PageTransition } from './PageTransition';

export function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-bg flex flex-col">
      <TopBar />
      <OfflineBanner />
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-5 pb-tabbar-safe md:pb-8">
        <ErrorBoundary key={location.pathname}>
          <PageTransition>
            <Outlet />
          </PageTransition>
        </ErrorBoundary>
      </main>
      <TabBar />
    </div>
  );
}
