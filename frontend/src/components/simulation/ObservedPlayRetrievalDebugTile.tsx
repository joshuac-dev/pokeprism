import { useState } from 'react';
import type { CoachDebugAnalysisRound } from '../../types/simulation';
import RetrievalMetadataPanel from '../observedPlay/RetrievalMetadataPanel';

function RoundDetail({ round }: { round: CoachDebugAnalysisRound }) {
  const [expanded, setExpanded] = useState(false);
  const meta = round.retrieval_metadata;

  return (
    <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors rounded"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            Round {round.round_number}
          </span>
          {round.no_relevant_evidence ? (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300">
              no relevant evidence
            </span>
          ) : round.block_injected ? (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300">
              injected
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
              not injected
            </span>
          )}
          {meta && (
            <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
              {meta.strategy} · {meta.evidence_selected.length} selected
              {meta.deck_card_ids.length > 0 && ` · ${meta.deck_card_ids.length} deck IDs`}
            </span>
          )}
        </div>
        <span className="text-slate-400 text-xs ml-2">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-200 dark:border-slate-700">
          {/* No-relevant-evidence banner */}
          {round.no_relevant_evidence && (
            <div className="mb-3 rounded border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 p-2">
              <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">
                No deck-relevant evidence found — no block injected into this round's prompt.
              </p>
            </div>
          )}

          {/* Retrieval metadata */}
          {meta ? (
            <RetrievalMetadataPanel meta={meta} />
          ) : (
            <p className="text-xs text-slate-400 italic">No retrieval metadata for this round.</p>
          )}

          {/* Acknowledgment summary */}
          {round.acknowledgment && (
            <div className="mt-3 text-xs text-slate-500 dark:text-slate-400">
              <span className="font-semibold">Acknowledgment: </span>
              {round.acknowledgment.acknowledgment_missing ? (
                <span className="text-yellow-600 dark:text-yellow-400">missing after retries</span>
              ) : round.acknowledgment.used_evidence_ids && round.acknowledgment.used_evidence_ids.length > 0 ? (
                <span className="text-green-600 dark:text-green-400">
                  used {round.acknowledgment.used_evidence_ids.length} evidence ID(s)
                </span>
              ) : round.acknowledgment.not_used_reason ? (
                <span className="text-slate-500">{round.acknowledgment.not_used_reason}</span>
              ) : (
                <span className="text-slate-400">—</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface Props {
  simulationId: string;
  rounds: CoachDebugAnalysisRound[];
  flagEnabled: boolean;
  anyBlockInjected: boolean;
}

export default function ObservedPlayRetrievalDebugTile({
  simulationId,
  rounds,
  flagEnabled,
  anyBlockInjected,
}: Props) {
  const roundsWithMeta = rounds.filter((r) => r.retrieval_metadata != null);
  const roundsWithEvidence = rounds.filter((r) => r.block_injected);
  const roundsNoRelevant = rounds.filter((r) => r.no_relevant_evidence);

  if (!flagEnabled) {
    return (
      <div className="text-sm text-slate-400 italic">
        <code className="font-mono text-xs">OBSERVED_PLAY_MEMORY_ENABLED=false</code> — no retrieval
        metadata available. Enable the flag and run a new simulation to see observed-play evidence retrieval.
      </div>
    );
  }

  if (rounds.length === 0) {
    return (
      <div className="text-sm text-slate-400 italic">
        No observed-play analysis rounds recorded for simulation{' '}
        <span className="font-mono text-xs">{simulationId}</span>.
        This may mean the simulation predates Phase 6.2a, or the flag was off when it ran.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Summary row */}
      <div className="flex flex-wrap gap-3 text-xs">
        <span className="flex items-center gap-1">
          <span className="font-semibold text-slate-500 dark:text-slate-400">Flag:</span>
          <span className="px-2 py-0.5 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 font-semibold">
            enabled
          </span>
        </span>
        <span className="flex items-center gap-1">
          <span className="font-semibold text-slate-500 dark:text-slate-400">Any block injected:</span>
          <span className={`px-2 py-0.5 rounded font-semibold ${
            anyBlockInjected
              ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
              : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
          }`}>
            {anyBlockInjected ? 'Yes' : 'No'}
          </span>
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          <span className="font-semibold">{rounds.length}</span> rounds recorded ·{' '}
          <span className="font-semibold">{roundsWithEvidence.length}</span> injected ·{' '}
          <span className="font-semibold">{roundsNoRelevant.length}</span> no-relevant-evidence ·{' '}
          <span className="font-semibold">{roundsWithMeta.length}</span> with retrieval metadata
        </span>
      </div>

      {/* Per-round accordion */}
      <div className="space-y-2">
        {rounds.map((round) => (
          <RoundDetail key={round.round_number} round={round} />
        ))}
      </div>
    </div>
  );
}
