/** Mode badge for simulation game_mode values. */

const MODE_STYLES: Record<string, string> = {
  hh:    'bg-purple-900 text-purple-300',
  ai_h:  'bg-indigo-900 text-indigo-300',
  ai_ai: 'bg-cyan-900 text-cyan-300',
};

const MODE_LABEL: Record<string, string> = {
  hh:    'H/H',
  ai_h:  'AI/H',
  ai_ai: 'AI/AI',
};

interface Props {
  mode: string;
}

export default function ModeBadge({ mode }: Props) {
  const cls = MODE_STYLES[mode] ?? 'bg-slate-700 text-slate-300';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {MODE_LABEL[mode] ?? mode}
    </span>
  );
}
