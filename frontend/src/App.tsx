import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createBrowserRouter, Outlet, RouterProvider, useLocation } from 'react-router-dom';
import { AuthProvider } from './auth/AuthProvider';
import { AppShell } from './components/AppShell';
import { RequireAuth } from './components/RequireAuth';
import { ErrorBoundary, NotFound } from './components/States';
import { envError } from './lib/env';
import { CapturePage } from './pages/CapturePage';
import { DetailPage } from './pages/DetailPage';
import { LedgerPage } from './pages/LedgerPage';
import { LoginPage } from './pages/LoginPage';
import { ModelPage } from './pages/ModelPage';
import { ScanPage } from './pages/ScanPage';
import { ScreeningsPage } from './pages/ScreeningsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 10_000 },
  },
});

function NotFoundRoute() {
  return <NotFound path={useLocation().pathname} />;
}

function Root() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: '/login', element: <LoginPage /> },
      {
        element: <RequireAuth><AppShell /></RequireAuth>,
        children: [
          { path: '/', element: <LedgerPage /> },
          { path: '/screenings', element: <ScreeningsPage /> },
          { path: '/screenings/new', element: <CapturePage /> },
          { path: '/screenings/:id', element: <DetailPage /> },
          { path: '/screenings/:id/scan', element: <ScanPage /> },
          { path: '/model', element: <ModelPage /> },
          { path: '*', element: <NotFoundRoute /> },
        ],
      },
    ],
  },
]);

export function App() {
  if (envError) {
    return (
      <main id="main" className="loading" role="alert">
        <div className="error-state">
          <span className="label c-pos">▲ ERR · CONFIGURATION</span>
          <h1>Invalid frontend environment</h1>
          <p className="mono">{envError}</p>
          <p>Fix frontend/.env (see .env.example), then rebuild.</p>
        </div>
      </main>
    );
  }
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
