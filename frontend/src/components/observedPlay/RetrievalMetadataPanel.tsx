import type { ObservedPlayRetrievalMetadata } from '../../types/observedPlay';

const MATCH_SOURCE_LABELS: Record<string, string> = {
  deck_card: 'Deck card',
  candidate_card: 'Candidate',
  name_fallback_deck: 'Name match (deck)',
  name_fallback_candidate: 'Name match (candidate)',
  global_fallback: 'Global fallback',
};

export default function RetrievalMetadataPanel({ meta }: { meta: ObservedPlayRetrievalMetadata }) {
  const hasExclusions =
    meta.excluded_summary.low_confidence > 0 ||
    meta.excluded_summary.source_cap_excluded > 0 ||
    meta.excluded_summary.unresolved_reference > 0;

  return (
    <div className="space-y-3">
      {/* Deck / candidate context cards */}
      {(meta.deck_card_names.length > 0 || meta.candidate_card_names.length > 0) && (
        <div>
          {meta.deck_card_names.length > 0 && (
            <div className="mb-1">
              <span className="text-xs font-semibold text-violet-700 dark:text-violet-400 uppercase tracking-wide mr-2">
                Deck context
              </span>
              <span className="text-xs text-violet-600 dark:text-violet-400">
                ({meta.deck_card_ids.length} unique IDs)
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {meta.deck_card_names.map((name, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900/50 text-violet-800 dark:text-violet-200 text-xs font-mono"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}
          {meta.candidate_card_names.length > 0 && (
            <div className="mt-2">
              <span className="text-xs font-semibold text-blue-700 dark:text-blue-400 uppercase tracking-wide mr-2">
                Candidate cards
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {meta.candidate_card_names.map((name, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 text-xs font-mono"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* No-relevant-evidence note */}
      {meta.no_relevant_evidence && (
        <p className="text-xs text-amber-700 dark:text-amber-400 italic">
          No deck-relevant evidence found — no block injected.
        </p>
      )}

      {/* Evidence selected table */}
      {meta.evidence_selected.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-violet-700 dark:text-violet-400 uppercase tracking-wide mb-1">
            Evidence selected ({meta.evidence_selected.length})
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-left text-violet-600 dark:text-violet-400 border-b border-violet-200 dark:border-violet-700">
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Tier</th>
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Score</th>
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Match source</th>
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Matched card(s)</th>
                  <th className="py-1 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {meta.evidence_selected.map((ev) => (
                  <tr
                    key={ev.memory_item_id}
                    className="border-b border-violet-100 dark:border-violet-800/50 hover:bg-violet-50 dark:hover:bg-violet-900/20"
                  >
                    <td className="py-1 pr-3 whitespace-nowrap">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        ev.tier === 1
                          ? 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300'
                          : ev.tier === 2
                          ? 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                      }`}>
                        T{ev.tier}
                      </span>
                    </td>
                    <td className="py-1 pr-3 font-mono whitespace-nowrap text-violet-800 dark:text-violet-200">
                      {ev.relevance_score.toFixed(3)}
                    </td>
                    <td className="py-1 pr-3 whitespace-nowrap">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        ev.match_source === 'deck_card'
                          ? 'bg-violet-100 dark:bg-violet-900/50 text-violet-700 dark:text-violet-300'
                          : ev.match_source === 'candidate_card'
                          ? 'bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                      }`}>
                        {ev.match_source ? (MATCH_SOURCE_LABELS[ev.match_source] ?? ev.match_source) : '—'}
                      </span>
                    </td>
                    <td className="py-1 pr-3 text-violet-800 dark:text-violet-200">
                      {ev.matched_card_names.length > 0
                        ? ev.matched_card_names.join(', ')
                        : ev.matched_card_ids.length > 0
                        ? ev.matched_card_ids.join(', ')
                        : '—'}
                    </td>
                    <td className="py-1 text-violet-600 dark:text-violet-400 break-words max-w-[24rem]">
                      {ev.matched_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Exclusion summary */}
      {hasExclusions && (
        <div className="text-xs text-violet-600 dark:text-violet-400">
          <span className="font-semibold">Excluded: </span>
          {[
            meta.excluded_summary.low_confidence > 0 && `${meta.excluded_summary.low_confidence} low-confidence`,
            meta.excluded_summary.source_cap_excluded > 0 && `${meta.excluded_summary.source_cap_excluded} source-cap`,
            meta.excluded_summary.unresolved_reference > 0 && `${meta.excluded_summary.unresolved_reference} unresolved`,
          ]
            .filter(Boolean)
            .join(', ')}
        </div>
      )}
    </div>
  );
}
