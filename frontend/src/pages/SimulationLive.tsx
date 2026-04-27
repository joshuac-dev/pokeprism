import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import PageShell from '../components/layout/PageShell';
import { useSimulation } from '../hooks/useSimulation';

export default function SimulationLive() {
  const { id } = useParams<{ id: string }>();
  const { status, deckName, events } = useSimulation(id ?? null);

  useEffect(() => {
    if (events.length > 0) {
      console.log('[PokéPrism] sim_event', events[events.length - 1]);
    }
  }, [events]);

  return (
    <PageShell title={deckName ?? 'Simulation Live'}>
      <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-400">
        <div className="text-sm font-mono bg-slate-800 px-4 py-2 rounded-md border border-slate-700">
          Simulation ID: {id}
        </div>
        <div>
          Status: <span className="text-blue-400 font-semibold">{status ?? '…'}</span>
        </div>
        <div>
          Events received: <span className="text-slate-100">{events.length}</span>
        </div>
        <p className="text-xs text-slate-600">
          Phase 9 — Live console coming soon. Open DevTools → Console to see streaming events.
        </p>
      </div>
    </PageShell>
  );
}
