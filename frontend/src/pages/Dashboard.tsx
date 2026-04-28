import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import PageShell from '../components/layout/PageShell';
import {
  getSimulation,
  getSimulationRounds,
  getSimulationMatches,
  getSimulationPrizeRace,
  getSimulationMutations,
} from '../api/simulations';
import type { SimulationDetail } from '../types/simulation';
import type { MatchRow, RoundRow, PrizeRaceData, MutationRow, OpponentStat } from '../types/dashboard';
import SummaryCards from '../components/dashboard/SummaryCards';
import WinRateDonut from '../components/dashboard/WinRateDonut';
import WinRateProgress from '../components/dashboard/WinRateProgress';
import OpponentWinRateBar from '../components/dashboard/OpponentWinRateBar';
import MatchupMatrix from '../components/dashboard/MatchupMatrix';
import WinRateDistribution from '../components/dashboard/WinRateDistribution';
import PrizeRaceGraph from '../components/dashboard/PrizeRaceGraph';
import DecisionMap from '../components/dashboard/DecisionMap';
import CardSwapHeatMap from '../components/dashboard/CardSwapHeatMap';
import MutationDiffLog from '../components/dashboard/MutationDiffLog';

function DashboardTile({
  title,
  children,
  className = '',
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-slate-800 rounded-xl border border-slate-700 p-5 ${className}`}>
      <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wide mb-4">{title}</h2>
      {children}
    </div>
  );
}

function deriveOpponentStats(matches: MatchRow[]): OpponentStat[] {
  const map = new Map<string, { wins: number; total: number }>();
  for (const m of matches) {
    const name = m.p2_deck_name ?? 'Unknown';
    const cur = map.get(name) ?? { wins: 0, total: 0 };
    map.set(name, {
      wins: cur.wins + (m.winner === 'p1' ? 1 : 0),
      total: cur.total + 1,
    });
  }
  return [...map.entries()].map(([name, { wins, total }]) => ({
    name,
    wins,
    total,
    win_rate: total ? wins / total : 0,
  }));
}

export default function Dashboard() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<SimulationDetail | null>(null);
  const [rounds, setRounds] = useState<RoundRow[]>([]);
  const [matches, setMatches] = useState<MatchRow[]>([]);
  const [prizeRace, setPrizeRace] = useState<PrizeRaceData>({ matches: [], average: [] });
  const [mutations, setMutations] = useState<MutationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      getSimulation(id),
      getSimulationRounds(id),
      getSimulationMatches(id),
      getSimulationPrizeRace(id),
      getSimulationMutations(id),
    ])
      .then(([sim, r, m, pr, mut]) => {
        setDetail(sim);
        setRounds(r);
        setMatches(m);
        setPrizeRace(pr);
        setMutations(mut);
      })
      .catch((err) => {
        setError(err?.response?.status === 404 ? 'Simulation not found.' : 'Failed to load dashboard data.');
      })
      .finally(() => setLoading(false));
  }, [id]);

  const deckName = detail?.user_deck_name ?? 'Dashboard';
  const opponents = deriveOpponentStats(matches);

  return (
    <PageShell title={deckName}>
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={() => navigate(`/simulation/${id}`)}
          className="text-sm text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
        >
          ← Back to Simulation
        </button>
        <span className="text-slate-400 font-mono text-xs">{id}</span>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            Loading dashboard…
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-center h-64">
          <div className="bg-slate-800 border border-red-800 rounded-xl p-8 text-center">
            <p className="text-red-400 font-medium mb-1">{error}</p>
            <p className="text-slate-400 text-sm">Check the simulation ID and try again.</p>
          </div>
        </div>
      )}

      {!loading && !error && detail && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {/* Row 1: Summary cards — full width */}
          <div className="col-span-1 md:col-span-2 xl:col-span-3">
            <SummaryCards
              numRounds={detail.num_rounds}
              roundsCompleted={detail.rounds_completed}
              matchesPerOpponent={detail.matches_per_opponent}
              totalMatches={detail.total_matches}
              rounds={rounds}
            />
          </div>

          {/* Tile 4: Win Rate Donut */}
          <DashboardTile title="Overall Win Rate">
            <WinRateDonut
              winRate={detail.final_win_rate}
              totalMatches={detail.total_matches}
            />
          </DashboardTile>

          {/* Tile 6: Win Rate Over Rounds */}
          <DashboardTile title="Win Rate Progress">
            <WinRateProgress rounds={rounds} targetWinRate={detail.target_win_rate} />
          </DashboardTile>

          {/* Tile 5: Opponent Win Rate Bar */}
          <DashboardTile title="Win Rate vs Opponents">
            <OpponentWinRateBar opponents={opponents} />
          </DashboardTile>

          {/* Tile 7: Matchup Matrix */}
          <DashboardTile title="Matchup Matrix (Round × Opponent)" className="col-span-1 md:col-span-2">
            <MatchupMatrix matches={matches} rounds={rounds} />
          </DashboardTile>

          {/* Tile 8: Win Rate Distribution */}
          <DashboardTile title="Win/Loss Distribution">
            <WinRateDistribution matches={matches} opponents={opponents} />
          </DashboardTile>

          {/* Tile 9: Prize Race */}
          <DashboardTile title="Prize Race" className="col-span-1 md:col-span-2">
            <PrizeRaceGraph prizeRace={prizeRace} />
          </DashboardTile>

          {/* Tile 10: Decision Map */}
          {id && (
            <DashboardTile title="AI Decision Map" className="col-span-1 md:col-span-2 xl:col-span-2">
              <DecisionMap simulationId={id} />
            </DashboardTile>
          )}

          {/* Tile 11: Card Swap Heat Map */}
          <DashboardTile title="Card Swap Heat Map">
            <CardSwapHeatMap mutations={mutations} numRounds={detail.num_rounds} />
          </DashboardTile>

          {/* Tile 12: Mutation Diff Log */}
          <DashboardTile title="Deck Mutation Log" className="col-span-1 md:col-span-2 xl:col-span-3">
            <MutationDiffLog mutations={mutations} />
          </DashboardTile>
        </div>
      )}
    </PageShell>
  );
}

