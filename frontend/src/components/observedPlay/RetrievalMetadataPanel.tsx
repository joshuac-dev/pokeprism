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
  const deckLabels = meta.deck_labels ?? [];
  const candidateLabels = meta.candidate_labels ?? [];
  const labelBoostApplied = meta.label_boost_applied_count ?? 0;

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

      {/* Label ranking debug */}
      {meta.label_ranking_enabled ? (
        <div className="rounded border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-2">
          <div className="flex flex-wrap gap-3 text-xs text-amber-800 dark:text-amber-200">
            <span>
              <span className="font-semibold">Label strategy:</span>{' '}
              <code>{meta.label_strategy ?? 'unknown'}</code>
            </span>
            <span>
              <span className="font-semibold">Boost cap:</span>{' '}
              {(meta.label_boost_cap ?? 0).toFixed(2)}
            </span>
            <span>
              <span className="font-semibold">Applied:</span>{' '}
              {labelBoostApplied} evidence item{labelBoostApplied === 1 ? '' : 's'}
            </span>
          </div>
          {(deckLabels.length > 0 || candidateLabels.length > 0) ? (
            <div className="mt-2 space-y-1">
              {deckLabels.length > 0 && (
                <div>
                  <span className="text-xs font-semibold text-amber-800 dark:text-amber-200 mr-2">
                    Deck labels
                  </span>
                  <span className="text-xs text-amber-700 dark:text-amber-300">
                    {deckLabels.map((label) => `${label.label} (${label.label_type})`).join(', ')}
                  </span>
                </div>
              )}
              {candidateLabels.length > 0 && (
                <div>
                  <span className="text-xs font-semibold text-amber-800 dark:text-amber-200 mr-2">
                    Candidate labels
                  </span>
                  <span className="text-xs text-amber-700 dark:text-amber-300">
                    {candidateLabels.map((label) => `${label.label} (${label.label_type})`).join(', ')}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
              No label ranking signal applied.
            </p>
          )}
          <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
            Label boosts are retrieval-debug metadata only. They are not card rules and do not approve
            or persist labels.
          </p>
        </div>
      ) : (
        <p className="text-xs text-slate-400 italic">No label ranking signal applied.</p>
      )}

      {/* Matchup context (Phase 7.2c) */}
      {meta.matchup_context_enabled && (
        <div className="rounded border border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/30 p-2">
          <div className="flex flex-wrap gap-3 text-xs text-sky-800 dark:text-sky-200 mb-2">
            <span>
              <span className="font-semibold">Matchup strategy:</span>{' '}
              <code>{meta.matchup_strategy ?? 'unknown'}</code>
            </span>
            <span>
              <span className="font-semibold">Matchup ranking:</span>{' '}
              {meta.matchup_ranking_enabled ? (
                <span className="text-green-600 dark:text-green-400 font-semibold">enabled</span>
              ) : (
                <span className="text-slate-500 dark:text-slate-400">disabled</span>
              )}
            </span>
            <span>
              <span className="font-semibold">Candidate pool expansion:</span>{' '}
              <span className="text-slate-500 dark:text-slate-400">disabled</span>
            </span>
            <span>
              <span className="font-semibold">Filter applied:</span>{' '}
              <span className="text-slate-500 dark:text-slate-400">no</span>
            </span>
          </div>
          {meta.matchup_boost_cap != null && (
            <div className="flex flex-wrap gap-3 text-xs text-sky-700 dark:text-sky-300 mb-1">
              <span>
                <span className="font-semibold">Boost cap:</span> {meta.matchup_boost_cap.toFixed(2)}
              </span>
              <span>
                <span className="font-semibold">Min pair logs:</span> {meta.matchup_min_pair_logs ?? 3}
              </span>
              <span>
                <span className="font-semibold">Pair log count:</span>{' '}
                <span className={
                  (meta.matchup_pair_log_count ?? 0) >= (meta.matchup_min_pair_logs ?? 3)
                    ? 'text-green-600 dark:text-green-400 font-semibold'
                    : 'text-amber-600 dark:text-amber-400'
                }>
                  {meta.matchup_pair_log_count ?? 0}
                </span>
              </span>
              <span>
                <span className="font-semibold">Eligible:</span>{' '}
                {meta.matchup_pair_eligible ? (
                  <span className="text-green-600 dark:text-green-400 font-semibold">yes</span>
                ) : (
                  <span className="text-amber-600 dark:text-amber-400">no</span>
                )}
              </span>
              <span>
                <span className="font-semibold">Boost applied:</span>{' '}
                {meta.matchup_boost_applied_count ?? 0}{' '}
                item{(meta.matchup_boost_applied_count ?? 0) === 1 ? '' : 's'}
              </span>
            </div>
          )}
          {meta.directed_matchup_key ? (
            <div className="text-xs text-sky-800 dark:text-sky-200 mb-1">
              <span className="font-semibold">Directed matchup key:</span>{' '}
              <code className="px-1.5 py-0.5 rounded bg-sky-100 dark:bg-sky-900/50 text-sky-700 dark:text-sky-300">
                {meta.directed_matchup_key}
              </code>
              {meta.matchup_confidence != null && (
                <span className="ml-2 text-sky-600 dark:text-sky-400">
                  (confidence {meta.matchup_confidence.toFixed(2)})
                </span>
              )}
            </div>
          ) : meta.no_matchup_signal_reason ? (
            <div className="text-xs text-sky-600 dark:text-sky-400 italic mb-1">
              No directed matchup key — {meta.no_matchup_signal_reason.replace(/_/g, ' ')}
            </div>
          ) : null}
          {meta.matchup_coverage_reason && !meta.matchup_pair_eligible && (
            <div className="text-xs text-amber-600 dark:text-amber-400 italic mb-1">
              Coverage: {meta.matchup_coverage_reason}
            </div>
          )}
          {((meta.current_archetype_labels?.length ?? 0) > 0 || (meta.opponent_archetype_labels?.length ?? 0) > 0) && (
            <div className="mt-1 space-y-1">
              {(meta.current_archetype_labels?.length ?? 0) > 0 && (
                <div className="text-xs">
                  <span className="font-semibold text-sky-800 dark:text-sky-200 mr-1">Current archetypes:</span>
                  <span className="text-sky-700 dark:text-sky-300">
                    {meta.current_archetype_labels!.map((l) => l.label).join(', ')}
                  </span>
                </div>
              )}
              {(meta.opponent_archetype_labels?.length ?? 0) > 0 && (
                <div className="text-xs">
                  <span className="font-semibold text-sky-800 dark:text-sky-200 mr-1">Opponent archetypes:</span>
                  <span className="text-sky-700 dark:text-sky-300">
                    {meta.opponent_archetype_labels!.map((l) => l.label).join(', ')}
                  </span>
                </div>
              )}
            </div>
          )}
          <p className="mt-2 text-[11px] text-sky-600 dark:text-sky-400">
            Matchup boost is generic and gated by corpus coverage. If a matchup is unseen or under-covered,
            PokéPrism falls back to card overlap and archetype/package/strategy labels.
          </p>
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
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Label boost</th>
                  <th className="py-1 pr-3 font-semibold whitespace-nowrap">Matchup boost</th>
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
                      {(ev.final_relevance_score ?? ev.relevance_score).toFixed(3)}
                      {ev.base_relevance_score != null && (
                        <span className="block text-[10px] text-violet-500 dark:text-violet-400">
                          base {ev.base_relevance_score.toFixed(3)}
                        </span>
                      )}
                    </td>
                    <td className="py-1 pr-3 whitespace-nowrap text-violet-700 dark:text-violet-300">
                      {(ev.label_boost ?? 0) > 0 ? `+${(ev.label_boost ?? 0).toFixed(2)}` : '—'}
                      {ev.matched_label_names && ev.matched_label_names.length > 0 && (
                        <span className="block text-[10px] text-violet-500 dark:text-violet-400">
                          {ev.matched_label_names.join(', ')}
                        </span>
                      )}
                    </td>
                    <td className="py-1 pr-3 whitespace-nowrap text-sky-700 dark:text-sky-300">
                      {(ev.matchup_boost ?? 0) > 0 ? `+${(ev.matchup_boost ?? 0).toFixed(2)}` : '—'}
                      {ev.source_log_matchup_key && (
                        <span className="block text-[10px] text-sky-500 dark:text-sky-400">
                          {ev.source_log_matchup_key}
                        </span>
                      )}
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
                      {ev.label_match_reason && (
                        <span className="block mt-1 text-[11px] text-amber-700 dark:text-amber-300">
                          {ev.label_match_reason}
                        </span>
                      )}
                      {ev.matchup_match_reason && (
                        <span className="block mt-1 text-[11px] text-sky-500 dark:text-sky-400">
                          {ev.matchup_match_reason}
                        </span>
                      )}
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
