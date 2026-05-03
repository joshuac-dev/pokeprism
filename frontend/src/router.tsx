import { lazy, Suspense } from 'react';
import type { ReactElement } from 'react';
import { createBrowserRouter } from 'react-router-dom';

const SimulationSetup = lazy(() => import('./pages/SimulationSetup'));
const SimulationLive = lazy(() => import('./pages/SimulationLive'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const History = lazy(() => import('./pages/History'));
const Memory = lazy(() => import('./pages/Memory'));
const Coverage = lazy(() => import('./pages/Coverage'));

function Page(element: ReactElement) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading...</div>}>
      {element}
    </Suspense>
  );
}

export const router = createBrowserRouter([
  { path: '/', element: Page(<SimulationSetup />) },
  { path: '/simulation/:id', element: Page(<SimulationLive />) },
  { path: '/dashboard/:id', element: Page(<Dashboard />) },
  { path: '/history', element: Page(<History />) },
  { path: '/memory', element: Page(<Memory />) },
  { path: '/coverage', element: Page(<Coverage />) },
]);
