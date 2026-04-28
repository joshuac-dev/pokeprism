/** Status badge for simulation status values. */

const STATUS_STYLES: Record<string, string> = {
  pending:   'bg-slate-700 text-slate-300',
  running:   'bg-blue-900 text-blue-300',
  complete:  'bg-green-900 text-green-300',
  failed:    'bg-red-900 text-red-300',
  cancelled: 'bg-yellow-900 text-yellow-300',
};

const STATUS_LABEL: Record<string, string> = {
  pending:   'Pending',
  running:   'Running',
  complete:  'Complete',
  failed:    'Failed',
  cancelled: 'Cancelled',
};

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  const cls = STATUS_STYLES[status] ?? 'bg-slate-700 text-slate-300';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
