import type {
  ArchetypeLabel,
  DeckArchetypeLabelPreview,
  ObservedLogArchetypeLabelPreview,
} from '../../types/observedPlay';

type Props =
  | {
      variant: 'deck';
      preview: DeckArchetypeLabelPreview | null;
      loading?: boolean;
      error?: string | null;
      title?: string;
    }
  | {
      variant: 'observed-log';
      preview: ObservedLogArchetypeLabelPreview | null;
      loading?: boolean;
      error?: string | null;
      title?: string;
    };

const TYPE_LABELS: Record<string, string> = {
  archetype: 'Archetype',
  package: 'Package',
  strategy: 'Strategy',
  matchup: 'Matchup',
  format: 'Format',
};

function confidenceText(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function safeCounts(value: Record<string, number> | null | undefined): Record<string, number> {
  return value && typeof value === 'object' ? value : {};
}

function evidenceCountFor(label: ArchetypeLabel, name: string): number | undefined {
  const counts = safeCounts(label.evidence_counts);
  return counts[name] ?? counts[name.toLowerCase()];
}

function evidenceSummary(label: ArchetypeLabel): string {
  const evidenceCardNames = safeArray(label.evidence_card_names);
  if (evidenceCardNames.length === 0) return 'No card evidence listed';
  return evidenceCardNames
    .slice(0, 8)
    .map((name) => {
      const count = evidenceCountFor(label, name);
      return count && count > 1 ? `${name} x${count}` : name;
    })
    .join(', ');
}

function LabelCard({ label, primary = false }: { label: ArchetypeLabel; primary?: boolean }) {
  const evidenceEventIds = safeArray(label.evidence_event_ids);
  const evidenceMemoryItemIds = safeArray(label.evidence_memory_item_ids);

  return (
    <div className="rounded border border-amber-200 dark:border-amber-800 bg-white dark:bg-slate-900 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {label.label}
            </span>
            {primary && (
              <span className="rounded-full bg-amber-100 dark:bg-amber-900/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
                Primary preview
              </span>
            )}
            <span className="rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
              {TYPE_LABELS[label.label_type] ?? label.label_type}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span>Confidence {confidenceText(label.confidence)}</span>
            <span>Source {label.source}</span>
            <span>Status {label.review_status}</span>
            {label.player_alias && <span>Alias {label.player_alias}</span>}
          </div>
        </div>
        <code className="rounded bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] text-slate-500 dark:text-slate-400">
          {label.canonical_key}
        </code>
      </div>

      <div className="mt-2 text-xs text-slate-600 dark:text-slate-300">
        <span className="font-semibold text-slate-500 dark:text-slate-400">Evidence: </span>
        {evidenceSummary(label)}
      </div>

      {(evidenceEventIds.length > 0 || evidenceMemoryItemIds.length > 0) && (
        <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          {evidenceEventIds.length > 0 && (
            <span>{evidenceEventIds.length} event ID(s)</span>
          )}
          {evidenceMemoryItemIds.length > 0 && (
            <span>{evidenceMemoryItemIds.length} memory item ID(s)</span>
          )}
        </div>
      )}

      {label.notes && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{label.notes}</p>
      )}
    </div>
  );
}

function AdvisoryNote() {
  return (
    <p className="rounded border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
      These labels are advisory context inferred from deck cards or observed-play logs. They are not
      card rules and are not currently used for Coach retrieval ranking.
    </p>
  );
}

function NoLabelState({ reason }: { reason?: string | null }) {
  return (
    <div className="rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-3 py-2 text-sm text-slate-500 dark:text-slate-400">
      No label preview available{reason ? `: ${reason}` : '.'}
    </div>
  );
}

export default function ArchetypeLabelPreviewPanel(props: Props) {
  const { preview, loading = false, error = null, title } = props;

  if (loading) {
    return (
      <div className="space-y-3" data-testid="archetype-label-preview">
        {title && <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>}
        <AdvisoryNote />
        <p className="text-sm text-slate-500 dark:text-slate-400">Loading label preview...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3" data-testid="archetype-label-preview">
        {title && <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>}
        <AdvisoryNote />
        <p className="rounded border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 px-3 py-2 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="space-y-3" data-testid="archetype-label-preview">
        {title && <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>}
        <AdvisoryNote />
        <NoLabelState />
      </div>
    );
  }

  const noLabelReason = preview.no_label_reason;

  if (props.variant === 'deck') {
    const deckPreview = preview as DeckArchetypeLabelPreview;
    const labels: ArchetypeLabel[] = safeArray(deckPreview.labels);
    const primaryKey = deckPreview.primary_label?.canonical_key;

    return (
      <div className="space-y-3" data-testid="archetype-label-preview">
        {title && <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>}
        <AdvisoryNote />
        {deckPreview.ambiguous && (
          <p className="rounded border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/30 px-3 py-2 text-xs text-yellow-800 dark:text-yellow-200">
            Ambiguous preview: multiple labels have similar evidence.
          </p>
        )}
        {labels.length === 0 ? (
          <NoLabelState reason={noLabelReason} />
        ) : (
          <div className="space-y-2">
            {labels.map((label) => (
              <LabelCard
                key={`${label.canonical_key}-${label.label_type}-${label.source}`}
                label={label}
                primary={label.canonical_key === primaryKey}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const logPreview = preview as ObservedLogArchetypeLabelPreview;
  const groups = Object.entries(logPreview.labels_by_player ?? {})
    .map(([player, labels]) => [player, safeArray(labels)] as [string, ArchetypeLabel[]]);
  const globalLabels: ArchetypeLabel[] = safeArray(logPreview.global_labels);
  const hasLabels = groups.some(([, labels]) => labels.length > 0) || globalLabels.length > 0;

  return (
    <div className="space-y-3" data-testid="archetype-label-preview">
      {title && <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>}
      <AdvisoryNote />
      {logPreview.ambiguous && (
        <p className="rounded border border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-950/30 px-3 py-2 text-xs text-yellow-800 dark:text-yellow-200">
          Ambiguous preview: observed-log evidence does not cleanly identify one label.
        </p>
      )}
      {!hasLabels ? (
        <NoLabelState reason={noLabelReason} />
      ) : (
        <div className="space-y-3">
          {groups.map(([player, labels]) => (
            <div key={player} className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                {player}
              </h4>
              {labels.length === 0 ? (
                <NoLabelState reason="no player-specific labels inferred" />
              ) : (
                labels.map((label) => (
                  <LabelCard
                    key={`${player}-${label.canonical_key}-${label.label_type}-${label.source}`}
                    label={label}
                  />
                ))
              )}
            </div>
          ))}
          {globalLabels.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Global labels
              </h4>
              {globalLabels.map((label) => (
                <LabelCard
                  key={`global-${label.canonical_key}-${label.label_type}-${label.source}`}
                  label={label}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
