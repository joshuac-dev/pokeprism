import { useEffect, useState } from 'react';
import { RefreshCw, Play } from 'lucide-react';
import PageShell from '../components/layout/PageShell';
import {
  getNightlyHHRerunStatus,
  previewNightlyHHRerun,
  triggerNightlyHHRerun,
} from '../api/admin';
import type {
  NightlyHHRerunStatus,
  PreviewResult,
  TriggerResult,
} from '../types/admin';

function ParamRow({ label, value }: { label: string; value: string | number | boolean }) {
  return (
    <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-700 text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="font-mono font-medium text-slate-800 dark:text-slate-200">
        {String(value)}
      </span>
    </div>
  );
}

export default function Administration() {
  const [status, setStatus] = useState<NightlyHHRerunStatus | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);

  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  const [trigger, setTrigger] = useState<TriggerResult | null>(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerErr, setTriggerErr] = useState<string | null>(null);

  useEffect(() => {
    getNightlyHHRerunStatus()
      .then(setStatus)
      .catch((e) => setStatusErr(String(e)));
  }, []);

  async function handlePreview() {
    setPreviewLoading(true);
    setPreviewErr(null);
    setPreview(null);
    try {
      setPreview(await previewNightlyHHRerun());
    } catch (e) {
      setPreviewErr(String(e));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleTrigger() {
    setTriggerLoading(true);
    setTriggerErr(null);
    setTrigger(null);
    try {
      const result = await triggerNightlyHHRerun();
      setTrigger(result);
      // Refresh status after trigger
      const newStatus = await getNightlyHHRerunStatus();
      setStatus(newStatus);
    } catch (e) {
      setTriggerErr(String(e));
    } finally {
      setTriggerLoading(false);
    }
  }

  return (
    <PageShell title="Administration">
      <div className="max-w-2xl space-y-8">

        {/* ── Nightly H/H Rerun ───────────────────────────────────────────── */}
        <section>
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100 mb-4">
            Nightly H/H Rerun
          </h2>

          {statusErr && (
            <p className="text-sm text-red-500 mb-4">{statusErr}</p>
          )}

          {status && (
            <div className="space-y-4">
              {/* Overview */}
              <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4 space-y-1">
                <ParamRow label="Status" value={status.enabled ? 'Enabled' : 'Disabled'} />
                <ParamRow label="Schedule" value={status.schedule} />
                <ParamRow label="Eligible source simulations" value={status.eligible_source_count} />
                <ParamRow label="Current cycle" value={status.current_cycle} />
                <ParamRow
                  label="Cycle progress"
                  value={`${status.current_cycle_completed_count} / ${status.current_cycle_total_count}`}
                />
              </div>

              {/* Fixed parameters */}
              <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
                  Fixed Generated Parameters
                </h3>
                <ParamRow label="Lock Deck" value={status.fixed_parameters.deck_locked ? 'Enabled' : 'Disabled'} />
                <ParamRow label="Game Mode" value={status.fixed_parameters.game_mode.toUpperCase()} />
                <ParamRow label="Matches per Opponent" value={status.fixed_parameters.matches_per_opponent} />
                <ParamRow label="Rounds" value={status.fixed_parameters.num_rounds} />
                <ParamRow label="Target Win Rate" value={`${status.fixed_parameters.target_win_rate}%`} />
                <ParamRow label="Rounds to Confirm" value={status.fixed_parameters.target_consecutive_rounds} />
                <ParamRow label="Target Mode" value={status.fixed_parameters.target_mode} />
              </div>

              {/* Last rerun */}
              {status.last_rerun && (
                <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
                    Last Rerun
                  </h3>
                  <ParamRow label="Source sim" value={status.last_rerun.source_simulation_id.slice(0, 8) + '…'} />
                  <ParamRow
                    label="Generated sim"
                    value={status.last_rerun.generated_simulation_id
                      ? status.last_rerun.generated_simulation_id.slice(0, 8) + '…'
                      : '—'}
                  />
                  <ParamRow label="Your Deck" value={status.last_rerun.source_user_deck_name ?? '—'} />
                  <ParamRow
                    label="Opponent(s)"
                    value={status.last_rerun.source_opponent_deck_names?.join(', ') ?? '—'}
                  />
                  <ParamRow label="Status" value={status.last_rerun.status} />
                  <ParamRow label="Triggered by" value={status.last_rerun.triggered_by} />
                  <ParamRow label="At" value={status.last_rerun.created_at ?? '—'} />
                  {status.last_rerun.error_message && (
                    <p className="mt-2 text-xs text-red-500">{status.last_rerun.error_message}</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Buttons */}
          <div className="mt-4 flex gap-3">
            <button
              onClick={handlePreview}
              disabled={previewLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50"
            >
              <RefreshCw size={14} className={previewLoading ? 'animate-spin' : ''} />
              Preview Next Run
            </button>
            <button
              onClick={handleTrigger}
              disabled={triggerLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Play size={14} />
              Trigger Nightly H/H Rerun Now
            </button>
          </div>

          {/* Preview result */}
          {previewErr && <p className="mt-3 text-sm text-red-500">{previewErr}</p>}
          {preview && (
            <div className="mt-3 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
                Preview
              </h3>
              {preview.status === 'skipped' ? (
                <p className="text-sm text-slate-500">Skipped: {preview.reason}</p>
              ) : preview.next_source ? (
                <div className="space-y-1">
                  <ParamRow label="Source sim" value={preview.next_source.simulation_id.slice(0, 8) + '…'} />
                  <ParamRow label="Your Deck" value={preview.next_source.user_deck_name ?? '—'} />
                  <ParamRow
                    label="Opponent(s)"
                    value={preview.next_source.opponents.map((o) => o.deck_name ?? o.deck_id).join(', ') || '—'}
                  />
                  <ParamRow
                    label="Cycle"
                    value={preview.cycle_number ?? '—'}
                  />
                </div>
              ) : null}
            </div>
          )}

          {/* Trigger result */}
          {triggerErr && <p className="mt-3 text-sm text-red-500">{triggerErr}</p>}
          {trigger && (
            <div className={`mt-3 rounded-lg border p-4 text-sm ${
              trigger.status === 'created'
                ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700 text-green-800 dark:text-green-200'
                : trigger.status === 'failed'
                ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700 text-red-800 dark:text-red-200'
                : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300'
            }`}>
              {trigger.status === 'created' ? (
                <>
                  <strong>Created</strong> — generated sim{' '}
                  <code>{trigger.generated_simulation_id?.slice(0, 8)}…</code> (cycle {trigger.cycle_number})
                </>
              ) : trigger.status === 'skipped' ? (
                <>Skipped: {trigger.reason}</>
              ) : (
                <>Failed: {trigger.reason}</>
              )}
            </div>
          )}
        </section>
      </div>
    </PageShell>
  );
}
