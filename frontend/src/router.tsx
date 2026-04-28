import { createBrowserRouter } from 'react-router-dom';
import SimulationSetup from './pages/SimulationSetup';
import SimulationLive from './pages/SimulationLive';
import Dashboard from './pages/Dashboard';
import History from './pages/History';
import Memory from './pages/Memory';
import Coverage from './pages/Coverage';

export const router = createBrowserRouter([
  { path: '/', element: <SimulationSetup /> },
  { path: '/simulation/:id', element: <SimulationLive /> },
  { path: '/dashboard/:id', element: <Dashboard /> },
  { path: '/history', element: <History /> },
  { path: '/memory', element: <Memory /> },
  { path: '/coverage', element: <Coverage /> },
]);
