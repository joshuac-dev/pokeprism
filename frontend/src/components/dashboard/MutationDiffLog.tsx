import { useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import type { MutationRow } from '../../types/dashboard';

interface Props {
  mutations: MutationRow[];
}

export default function MutationDiffLog({ mutations }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'round_number', desc: false }]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const columns: ColumnDef<MutationRow>[] = [
    {
      accessorKey: 'round_number',
      header: 'Round',
      size: 60,
    },
    {
      accessorKey: 'card_removed',
      header: 'Card Removed',
      cell: (info) => (
        <span className="text-ctp-red">{info.getValue<string>()}</span>
      ),
    },
    {
      accessorKey: 'card_added',
      header: 'Card Added',
      cell: (info) => (
        <span className="text-ctp-green">{info.getValue<string>()}</span>
      ),
    },
    {
      accessorKey: 'reasoning',
      header: 'Reasoning',
      cell: (info) => {
        const val = info.getValue<string | null>() ?? '';
        return (
          <span className="text-app-text-subtle truncate block max-w-[200px]" title={val}>
            {val.length > 60 ? `${val.slice(0, 60)}…` : val}
          </span>
        );
      },
    },
  ];

  const table = useReactTable({
    data: mutations,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (!mutations.length) {
    return (
      <div className="flex items-center justify-center h-24 text-app-text-subtle text-sm">
        No deck mutations recorded.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className="text-app-text-subtle text-xs uppercase tracking-wide text-left px-3 py-2 cursor-pointer select-none"
                  onClick={header.column.getToggleSortingHandler()}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  {header.column.getIsSorted() === 'asc' && ' ↑'}
                  {header.column.getIsSorted() === 'desc' && ' ↓'}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <>
              <tr
                key={row.id}
                className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors"
                onClick={() => setExpandedId(expandedId === row.original.id ? null : row.original.id)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2 text-app-text">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
              {expandedId === row.original.id && (
                <tr key={`${row.id}-expanded`}>
                  <td colSpan={columns.length} className="px-3 pb-3">
                    <div className="bg-slate-50 dark:bg-slate-900 rounded p-3 text-slate-600 dark:text-slate-300 text-sm italic">
                      {row.original.reasoning ?? 'No reasoning provided.'}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
