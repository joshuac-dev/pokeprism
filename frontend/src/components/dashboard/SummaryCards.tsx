import type { RoundRow } from '../../types/dashboard';

interface Props {
  numRounds: number;
  roundsCompleted: number;
  matchesPerOpponent: number;
  totalMatches: number;
  rounds: RoundRow[];
}

export default function SummaryCards({ numRounds, roundsCompleted, matchesPerOpponent, totalMatches }: Props) {
  const cards = [
    { label: 'Rounds', value: `${roundsCompleted} / ${numRounds}` },
    { label: 'Matches / Round', value: `${matchesPerOpponent}` },
    { label: 'Total Matches', value: `${totalMatches}` },
  ];

  return (
    <div className="grid grid-cols-3 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-slate-100 dark:bg-slate-800 rounded-xl p-5 border border-slate-200 dark:border-slate-700"
        >
          <p className="text-sm text-slate-400 mb-1">{card.label}</p>
          <p className="text-3xl font-bold text-slate-900 dark:text-white">{card.value}</p>
        </div>
      ))}
    </div>
  );
}
