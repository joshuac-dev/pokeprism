import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ObservedPlay from './ObservedPlay';

// ── Mock API ───────────────────────────────────────────────────────────────────

vi.mock('../api/observedPlay', () => ({
  uploadObservedPlayLog: vi.fn(),
  listObservedPlayBatches: vi.fn(),
  listObservedPlayLogs: vi.fn(),
  getObservedPlayLog: vi.fn(),
  getObservedPlayLogEvents: vi.fn(),
  reparseObservedPlayLog: vi.fn(),
  getCardMentions: vi.fn(),
  getUnresolvedCards: vi.fn(),
  resolveCards: vi.fn(),
  createResolutionRule: vi.fn(),
  previewMemoryIngestion: vi.fn(),
  ingestMemory: vi.fn(),
  getMemoryItems: vi.fn(),
  getMemorySummary: vi.fn(),
  getMemoryAnalytics: vi.fn(),
  getMemoryAnalyticsSourceItems: vi.fn(),
  bulkReparseAll: vi.fn(),
  bulkPreviewEligible: vi.fn(),
  bulkIngestEligible: vi.fn(),
  getCorpusReadiness: vi.fn(),
  getCoachEvidence: vi.fn(),
  getCoachContextPreview: vi.fn(),
}));

import {
  uploadObservedPlayLog,
  listObservedPlayBatches,
  listObservedPlayLogs,
  getObservedPlayLog,
  getObservedPlayLogEvents,
  reparseObservedPlayLog,
  getCardMentions,
  getUnresolvedCards,
  previewMemoryIngestion,
  ingestMemory,
  getMemoryItems,
  getMemorySummary,
  getMemoryAnalytics,
  getMemoryAnalyticsSourceItems,
  bulkReparseAll,
  bulkPreviewEligible,
  bulkIngestEligible,
  getCorpusReadiness,
  getCoachEvidence,
  getCoachContextPreview,
} from '../api/observedPlay';

const emptyBatches = { items: [], total: 0, page: 1, per_page: 25 };
const emptyLogs = { items: [], total: 0, page: 1, per_page: 25 };

const sampleBatch = {
  id: 'batch-001',
  source: 'upload_single',
  uploaded_filename: 'game.md',
  status: 'completed',
  original_file_count: 1,
  accepted_file_count: 1,
  duplicate_file_count: 0,
  failed_file_count: 0,
  imported_file_count: 1,
  skipped_file_count: 0,
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:00:01Z',
  created_at: '2026-01-01T00:00:00Z',
};

const sampleLog = {
  id: 'log-001',
  import_batch_id: 'batch-001',
  source: 'ptcgl_export',
  original_filename: 'game.md',
  sha256_hash: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
  file_size_bytes: 1024,
  parse_status: 'raw_archived',
  memory_status: 'not_ingested',
  stored_path: 'archive/ab/abcdef.md',
  created_at: '2026-01-01T00:00:00Z',
  parser_version: null,
  event_count: 0,
  confidence_score: null,
  winner_raw: null,
  win_condition: null,
};

const sampleUploadResult = {
  batch_id: 'batch-001',
  status: 'completed',
  original_file_count: 1,
  accepted_file_count: 1,
  duplicate_file_count: 0,
  failed_file_count: 0,
  imported_file_count: 1,
  skipped_file_count: 0,
  logs: [
    {
      log_id: 'log-001',
      original_filename: 'game.md',
      sha256_hash: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
      status: 'imported' as const,
      parse_status: 'raw_archived',
      stored_path: 'archive/ab/abcdef.md',
      error: null,
    },
  ],
  errors: [],
  warnings: [],
};

const emptyAnalytics = {
  top_memory_types: [],
  top_actor_cards: [],
  top_target_cards: [],
  top_actions: [],
  top_attacks: [],
  top_abilities: [],
  top_attachments: [],
  top_evolutions: [],
  top_knockouts: [],
  quality_flags: [],
};

const sampleSummary = {
  ingested_log_count: 3,
  memory_item_count: 158,
  memory_type_counts: { attack_used: 18, card_played: 32 },
  average_confidence: 0.82,
  low_confidence_count: 5,
  ambiguous_reference_count: 10,
  unresolved_reference_count: 0,
  latest_ingested_at: '2026-05-06T16:00:00Z',
};

const emptySummary = {
  ingested_log_count: 0,
  memory_item_count: 0,
  memory_type_counts: {},
  average_confidence: null,
  low_confidence_count: 0,
  ambiguous_reference_count: 0,
  unresolved_reference_count: 0,
  latest_ingested_at: null,
};

function setup() {
  return render(
    <MemoryRouter>
      <ObservedPlay />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (listObservedPlayBatches as ReturnType<typeof vi.fn>).mockResolvedValue(emptyBatches);
  (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue(emptyLogs);
  (getObservedPlayLogEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [], total: 0, page: 1, per_page: 50,
  });
  (reparseObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
    log_id: 'log-001', parse_status: 'parsed', event_count: 0,
    turn_count: 0, confidence_score: null, parser_version: null,
    warnings: [], errors: [], parser_diagnostics: null,
    card_mention_count: 0, resolved_card_count: 0, ambiguous_card_count: 0,
    unresolved_card_count: 0, card_resolution_status: null,
  });
  (getCardMentions as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [], total: 0, page: 1, per_page: 50,
  });
  (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [], total: 0, page: 1, per_page: 20,
  });
  (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
    eligible: true,
    eligibility_status: 'eligible',
    reasons: [],
    estimated_memory_item_count: 5,
    event_type_counts: { attack_used: 3, knockout: 2 },
    sample_items: [],
  });
  (ingestMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
    ingestion_id: 'ing-001',
    log_id: 'log-001',
    status: 'completed',
    eligibility_status: 'eligible',
    reasons: [],
    memory_item_count: 5,
    ingestion_version: '1.0',
  });
  (getMemoryItems as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [], total: 0, page: 1, per_page: 50,
  });
  (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(emptySummary);
  (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue(emptyAnalytics);
  (getMemoryAnalyticsSourceItems as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [], total: 0, page: 1, per_page: 20,
  });
  (bulkReparseAll as ReturnType<typeof vi.fn>).mockResolvedValue({
    considered_count: 0, reparsed_count: 0, skipped_count: 0, failed_count: 0,
    reparsed: [], skipped: [], failed: [], average_confidence: null, total_event_count: 0,
  });
  const emptyBulkPreview = {
    considered_count: 0, eligible_count: 0, ineligible_count: 0,
    already_ingested_count: 0, not_ready_count: 0, estimated_memory_item_count: 0,
    eligible_logs: [], skipped_logs: [], top_blocker_reasons: [],
  };
  (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue(emptyBulkPreview);
  (bulkIngestEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
    considered_count: 0, eligible_count: 0, ingested_count: 0, skipped_count: 0,
    failed_count: 0, memory_items_created: 0,
    ingested_logs: [], skipped_logs: [], failed_logs: [],
  });
  (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue({
    verdict: 'ready',
    readiness_score: 95.0,
    generated_at: '2026-06-01T12:00:00Z',
    review_only: true,
    safety_note: 'This scorecard is read-only.',
    corpus: {
      log_count: 49, parsed_log_count: 49, ingested_log_count: 49,
      not_ingested_log_count: 0, failed_log_count: 0,
      event_count: 10047, memory_item_count: 1234,
    },
    parser_quality: {
      avg_event_confidence: 0.8879, min_log_confidence: 0.81, avg_log_confidence: 0.887,
      unknown_event_count: 0, low_confidence_event_count: 0,
      low_confidence_threshold: 0.80, logs_below_ingestion_threshold: 0,
    },
    card_resolution: {
      card_mention_count: 500, resolved_count: 490, ambiguous_count: 0,
      unresolved_count: 0, critical_unresolved_count: 0,
      top_ambiguous: [], top_unresolved: [],
    },
    memory_quality: {
      avg_memory_confidence: 0.88, low_confidence_memory_item_count: 0,
      ambiguous_reference_item_count: 0, unresolved_reference_item_count: 0,
      memory_type_counts: [],
      top_quality_flags: [],
    },
    blockers: [], warnings: [], recommendations: [],
  });
  (getCoachEvidence as ReturnType<typeof vi.fn>).mockResolvedValue({
    review_only: true,
    query: { card_name: null, memory_type: null, action_name: null, player_alias: null, min_confidence: 0.80, limit: 25 },
    summary: {
      matching_item_count: 0,
      avg_confidence: null,
      memory_type_counts: [],
      top_actors: [],
      top_targets: [],
      top_actions: [],
    },
    evidence: [],
    warnings: [],
  });
  (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
    enabled: false,
    readiness_verdict: null,
    readiness_score: null,
    would_inject: false,
    reason: 'OBSERVED_PLAY_MEMORY_ENABLED is false',
    prompt_block: '',
    evidence_count: 0,
    evidence_ids: [],
    warnings: [],
    filters_applied: { min_confidence: 0.85, limit: 8 },
  });
});

describe('ObservedPlay page', () => {
  it('renders the upload panel', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText('Upload Battle Log')).toBeInTheDocument();
    });
    expect(screen.getByText('Choose file…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /upload/i })).toBeInTheDocument();
  });

  it('shows phase 4 active banner', async () => {
    setup();
    await waitFor(() => {
      expect(
        screen.getByText(/phase 4 active/i),
      ).toBeInTheDocument();
    });
  });

  it('upload button is disabled when no file is selected', async () => {
    setup();
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /upload/i });
      expect(btn).toBeDisabled();
    });
  });

  it('shows import report counts after successful upload', async () => {
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(sampleUploadResult);
    (listObservedPlayBatches as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleBatch],
      total: 1,
      page: 1,
      per_page: 25,
    });
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1,
      page: 1,
      per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    // Select a file
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['# log content'], 'game.md', { type: 'text/markdown' });
    await userEvent.upload(input, file);

    // Wait for the upload button to become enabled (file selected)
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /upload/i });
      expect(btn).not.toBeDisabled();
    });

    // Click upload
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(screen.getByText('Import Report')).toBeInTheDocument();
    });
    expect(screen.getByText('batch-001')).toBeInTheDocument();
  });

  it('shows upload error message on failure', async () => {
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Server error'),
    );

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['# log'], 'game.md', { type: 'text/markdown' });
    await userEvent.upload(input, file);

    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  it('renders import history table with batches', async () => {
    (listObservedPlayBatches as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleBatch],
      total: 1,
      page: 1,
      per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByText('Import History')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('game.md')).toBeInTheDocument();
    });
  });

  it('renders raw logs table', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1,
      page: 1,
      per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByText('Raw Logs')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getAllByText('game.md').length).toBeGreaterThan(0);
    });
    expect(screen.getByRole('button', { name: /view raw/i })).toBeInTheDocument();
  });

  it('opens raw log modal on View raw click', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1,
      page: 1,
      per_page: 25,
    });
    (getObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sampleLog,
      raw_content: '# PTCGL Log\nTurn 1\n',
      player_1_name_raw: null,
      player_2_name_raw: null,
      player_1_alias: null,
      player_2_alias: null,
      winner_raw: null,
      win_condition: null,
      turn_count: 0,
      event_count: 0,
      confidence_score: null,
      errors_json: [],
      warnings_json: [],
      metadata_json: {},
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view raw/i }));
    await userEvent.click(screen.getByRole('button', { name: /view raw/i }));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText(/PTCGL Log/)).toBeInTheDocument();
    });
  });

  it('closes modal on Escape key', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1,
      page: 1,
      per_page: 25,
    });
    (getObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sampleLog,
      raw_content: '# Game',
      player_1_name_raw: null,
      player_2_name_raw: null,
      player_1_alias: null,
      player_2_alias: null,
      winner_raw: null,
      win_condition: null,
      turn_count: 0,
      event_count: 0,
      confidence_score: null,
      errors_json: [],
      warnings_json: [],
      metadata_json: {},
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view raw/i }));
    await userEvent.click(screen.getByRole('button', { name: /view raw/i }));
    await waitFor(() => screen.getByRole('dialog'));

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('closes modal on backdrop click', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1,
      page: 1,
      per_page: 25,
    });
    (getObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sampleLog,
      raw_content: '# Game',
      player_1_name_raw: null,
      player_2_name_raw: null,
      player_1_alias: null,
      player_2_alias: null,
      winner_raw: null,
      win_condition: null,
      turn_count: 0,
      event_count: 0,
      confidence_score: null,
      errors_json: [],
      warnings_json: [],
      metadata_json: {},
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view raw/i }));
    await userEvent.click(screen.getByRole('button', { name: /view raw/i }));
    await waitFor(() => screen.getByRole('dialog'));

    // Click the backdrop (the dialog element itself, not the inner panel)
    await userEvent.click(screen.getByRole('dialog'));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('shows duplicate and skipped counts when present', async () => {
    const resultWithDup = {
      ...sampleUploadResult,
      duplicate_file_count: 1,
      skipped_file_count: 2,
      imported_file_count: 0,
      logs: [
        {
          ...sampleUploadResult.logs[0],
          status: 'duplicate' as const,
        },
      ],
    };
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(resultWithDup);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['#log'], 'game.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => screen.getByText('Import Report'));

    // Duplicate = 1, Skipped = 2 should appear somewhere in the counts grid
    const dupCells = screen.getAllByText('1');
    const skipCells = screen.getAllByText('2');
    expect(dupCells.length).toBeGreaterThan(0);
    expect(skipCells.length).toBeGreaterThan(0);
  });

  it('shows file-level error in Error column for failed imports', async () => {
    const failedResult = {
      ...sampleUploadResult,
      status: 'failed',
      failed_file_count: 1,
      imported_file_count: 0,
      logs: [
        {
          log_id: null,
          original_filename: 'bad.md',
          sha256_hash: 'deadbeef',
          status: 'failed' as const,
          parse_status: 'decode_failed',
          stored_path: null,
          error: 'File is not valid UTF-8 or UTF-8 BOM text.',
        },
      ],
      errors: ['bad.md: File is not valid UTF-8 or UTF-8 BOM text.'],
      warnings: [],
    };
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(failedResult);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['\xff\xfe'], 'bad.md', { type: 'application/octet-stream' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => screen.getByText('Import Report'));

    // Error column header
    expect(screen.getByText('Error')).toBeInTheDocument();
    // Error message displayed in the row
    expect(screen.getByText('File is not valid UTF-8 or UTF-8 BOM text.')).toBeInTheDocument();
  });

  it('shows em-dash in Error column for successful imports', async () => {
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(sampleUploadResult);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['# log'], 'game.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => screen.getByText('Import Report'));

    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows batch-level errors when returned', async () => {
    const resultWithBatchErrors = {
      ...sampleUploadResult,
      status: 'failed',
      failed_file_count: 1,
      imported_file_count: 0,
      logs: [
        {
          ...sampleUploadResult.logs[0],
          status: 'failed' as const,
          error: 'Permission denied writing archive.',
        },
      ],
      errors: ['game.md: Permission denied writing archive.'],
      warnings: ['Disk usage is high.'],
    };
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(resultWithBatchErrors);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['# log'], 'game.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => screen.getByText('Import Report'));

    // Error appears both in batch errors section and in the per-file table row
    const errorEls = screen.getAllByText(/Permission denied writing archive/);
    expect(errorEls.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Disk usage is high/)[0]).toBeInTheDocument();
  });

  it('upload server 500 shows backend detail from response', async () => {
    const axiosErr = Object.assign(new Error('Request failed with status code 500'), {
      response: { data: { detail: 'Import failed: disk quota exceeded' } },
    });
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockRejectedValue(axiosErr);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['# log'], 'game.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(screen.getByText(/disk quota exceeded/i)).toBeInTheDocument();
  });

  it('duplicate upload response with null event_count renders import report', async () => {
    const dupResult = {
      ...sampleUploadResult,
      duplicate_file_count: 1,
      imported_file_count: 0,
      logs: [
        {
          log_id: 'log-001',
          original_filename: 'game.md',
          sha256_hash: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
          status: 'duplicate' as const,
          parse_status: 'raw_archived',
          stored_path: 'archive/ab/abcdef.md',
          error: null,
          event_count: 0,
          confidence_score: null,
        },
      ],
    };
    (uploadObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue(dupResult);

    setup();
    await waitFor(() => screen.getByText('Upload Battle Log'));

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['# log'], 'game.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: /upload/i }));

    await waitFor(() => screen.getByText('Import Report'));
    // duplicate status chip appears
    expect(screen.getByText('duplicate')).toBeInTheDocument();
    // no crash, error column shows dash
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('event viewer shows empty state when log has no events', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1, page: 1, per_page: 25,
    });
    (getObservedPlayLogEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 50,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText(/no parsed events found/i)).toBeInTheDocument();
    });
    // Reparse button still accessible inside empty state
    expect(screen.getAllByRole('button', { name: /reparse/i }).length).toBeGreaterThan(0);
  });

  it('event viewer shows events table when events exist', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ ...sampleLog, parse_status: 'parsed', event_count: 3 }],
      total: 1, page: 1, per_page: 25,
    });
    (getObservedPlayLogEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: 1, event_index: 0, turn_number: 1, phase: 'turn',
          player_raw: 'Alice', player_alias: 'player_1', actor_type: 'player',
          event_type: 'draw', raw_line: 'Alice drew 1 card.', raw_block: null,
          card_name_raw: null, target_card_name_raw: null,
          zone: null, target_zone: null, amount: 1, damage: null, base_damage: null,
          event_payload_json: {}, confidence_score: 0.95, confidence_reasons_json: [],
        },
      ],
      total: 1, page: 1, per_page: 50,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText('draw')).toBeInTheDocument();
    });
    expect(screen.getByText('Alice drew 1 card.')).toBeInTheDocument();
  });

  it('event viewer shows error when fetch fails', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1, page: 1, per_page: 25,
    });
    (getObservedPlayLogEvents as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('network error'),
    );

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to load events/i)).toBeInTheDocument();
    });
  });

  it('event modal shows diagnostics panel when log has parser_diagnostics', async () => {
    const logWithDiag = {
      ...sampleLog,
      parser_diagnostics: {
        unknown_count: 12,
        unknown_ratio: 0.041,
        low_confidence_count: 5,
        event_type_counts: { draw_hidden: 20, unknown: 12 },
        top_unknown_raw_lines: ['- some unknown line', 'another unknown line'],
      },
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithDiag],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText(/parser diagnostics/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/unknown: 12/i)).toBeInTheDocument();
    expect(screen.getByText(/low confidence: 5/i)).toBeInTheDocument();
    // unknown_ratio 0.041 → 4.1%
    expect(screen.getByText(/4\.1%/)).toBeInTheDocument();
  });

  it('event modal shows top unknown lines when present', async () => {
    const logWithDiag = {
      ...sampleLog,
      parser_diagnostics: {
        unknown_count: 2,
        unknown_ratio: 0.02,
        low_confidence_count: 0,
        event_type_counts: {},
        top_unknown_raw_lines: ['mystery line 1', 'mystery line 2'],
      },
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithDiag],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText('mystery line 1')).toBeInTheDocument();
    });
    expect(screen.getByText('mystery line 2')).toBeInTheDocument();
  });

  it('event modal works without diagnostics (null)', async () => {
    const logNoDiag = { ...sampleLog, parser_diagnostics: null };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logNoDiag],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /parsed events/i })).toBeInTheDocument();
    });
    // Diagnostics panel should not appear
    expect(screen.queryByText(/parser diagnostics/i)).not.toBeInTheDocument();
  });

  it('reparse updates diagnostics in event modal', async () => {
    const logWithDiag = {
      ...sampleLog,
      parser_diagnostics: {
        unknown_count: 10,
        unknown_ratio: 0.10,
        low_confidence_count: 3,
        event_type_counts: {},
        top_unknown_raw_lines: [],
      },
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithDiag],
      total: 1, page: 1, per_page: 25,
    });
    (reparseObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      log_id: 'log-001', parse_status: 'parsed', event_count: 5,
      turn_count: 1, confidence_score: 0.9, parser_version: 'v1',
      warnings: [], errors: [],
      parser_diagnostics: {
        unknown_count: 2,
        unknown_ratio: 0.02,
        low_confidence_count: 1,
        event_type_counts: {},
        top_unknown_raw_lines: ['new unknown'],
      },
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view events/i }));
    await userEvent.click(screen.getByRole('button', { name: /view events/i }));

    await waitFor(() => {
      expect(screen.getByText(/unknown: 10/i)).toBeInTheDocument();
    });

    await userEvent.click(screen.getAllByRole('button', { name: /^reparse$/i })[0]);

    await waitFor(() => {
      expect(screen.getByText(/unknown: 2/i)).toBeInTheDocument();
    });
  });
});

// ── Phase 3: Card resolution tests ───────────────────────────────────────────

describe('Phase 3 card resolution', () => {
  it('shows card resolution badges when log has card mentions', async () => {
    const logWithCards = {
      ...sampleLog,
      card_mention_count: 10,
      resolved_card_count: 7,
      ambiguous_card_count: 2,
      unresolved_card_count: 1,
      card_resolution_status: 'has_unresolved',
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithCards],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByText('7✓')).toBeInTheDocument();
      expect(screen.getByText('2?')).toBeInTheDocument();
      expect(screen.getByText('1✗')).toBeInTheDocument();
    });
  });

  it('shows dash for logs with no card mentions', async () => {
    const logNoCards = {
      ...sampleLog,
      card_mention_count: 0,
      resolved_card_count: 0,
      ambiguous_card_count: 0,
      unresolved_card_count: 0,
      card_resolution_status: 'not_resolved',
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logNoCards],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      // The dash from CardResolutionBadges
      expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    });
  });

  it('shows View cards button only when card_mention_count > 0', async () => {
    const logWithCards = {
      ...sampleLog,
      card_mention_count: 5,
      resolved_card_count: 5,
      ambiguous_card_count: 0,
      unresolved_card_count: 0,
      card_resolution_status: 'resolved',
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithCards],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view cards/i })).toBeInTheDocument();
    });
  });

  it('does not show View cards button when no mentions', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByText('Raw Logs'));
    expect(screen.queryByRole('button', { name: /view cards/i })).not.toBeInTheDocument();
  });

  it('opens card mentions modal when View cards is clicked', async () => {
    const logWithCards = {
      ...sampleLog,
      card_mention_count: 3,
      resolved_card_count: 2,
      ambiguous_card_count: 1,
      unresolved_card_count: 0,
      card_resolution_status: 'has_ambiguous',
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithCards],
      total: 1, page: 1, per_page: 25,
    });
    (getCardMentions as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: 'cm-001', observed_play_log_id: 'log-001', observed_play_event_id: 1,
          mention_index: 0, mention_role: 'trainer_card',
          raw_name: 'Buddy-Buddy Poffin', normalized_name: 'buddy-buddy poffin',
          resolved_card_def_id: 'sv04-223', resolved_card_name: 'Buddy-Buddy Poffin',
          resolution_status: 'resolved', resolution_confidence: 0.98,
          resolution_method: 'exact_name_unique', candidate_count: 1,
          candidates_json: [], source_event_type: 'play_item',
          source_field: 'card_name_raw', source_payload_path: null,
          resolver_version: '1.0',
        },
      ],
      total: 1, page: 1, per_page: 50,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view cards/i }));
    await userEvent.click(screen.getByRole('button', { name: /view cards/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /card mentions/i });
      expect(dialog).toBeInTheDocument();
      expect(within(dialog).getAllByText('Buddy-Buddy Poffin').length).toBeGreaterThan(0);
    });
  });

  it('card mentions modal renders no-mentions message when empty', async () => {
    const logWithCards = {
      ...sampleLog,
      card_mention_count: 5,
    };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithCards],
      total: 1, page: 1, per_page: 25,
    });
    (getCardMentions as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 50,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view cards/i }));
    await userEvent.click(screen.getByRole('button', { name: /view cards/i }));

    await waitFor(() => {
      expect(screen.getByText(/no card mentions found/i)).toBeInTheDocument();
    });
  });

  it('card mentions modal can be closed with close button', async () => {
    const logWithCards = { ...sampleLog, card_mention_count: 3 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [logWithCards], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view cards/i }));
    await userEvent.click(screen.getByRole('button', { name: /view cards/i }));
    await waitFor(() => screen.getByRole('dialog', { name: /card mentions/i }));

    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: /card mentions/i })).not.toBeInTheDocument();
    });
  });

  it('unresolved cards section does not render when list is empty', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 20,
    });

    setup();
    await waitFor(() => screen.getByText('Import History'));
    expect(screen.queryByText(/unresolved.*cards/i)).not.toBeInTheDocument();
  });

  it('unresolved cards section renders when there are unresolved cards', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          raw_name: 'Spiky Energy',
          normalized_name: 'spiky energy',
          status: 'unresolved',
          mention_count: 3,
          log_count: 1,
          candidate_count: 0,
          candidates: [],
        },
      ],
      total: 1, page: 1, per_page: 20,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByText(/unresolved.*ambiguous.*cards/i)).toBeInTheDocument();
      expect(screen.getByText('Spiky Energy')).toBeInTheDocument();
    });
  });

  it('phase banner reflects Phase 4', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText(/phase 4 active/i)).toBeInTheDocument();
    });
  });

  // ── Phase 4: Memory ingestion tests ──────────────────────────────────────────

  it('shows "Preview memory" button for parsed logs', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10, confidence_score: 0.9 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /preview memory/i })).toBeInTheDocument();
    });
    // Row button must NOT say "Ingest memory" — that label lives only inside the modal
    expect(screen.queryByRole('button', { name: /^ingest memory$/i })).not.toBeInTheDocument();
  });

  it('shows "Re-preview memory" button for already-ingested logs', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 5 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /re-preview memory/i })).toBeInTheDocument();
    });
  });

  it('shows "View memory" button for logs with memory items', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 3 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'View memory' })).toBeInTheDocument();
    });
  });

  it('clicking "Preview memory" opens the MemoryPreviewModal with "Ingest memory" action inside', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10, confidence_score: 0.9 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /memory preview/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/estimated 5 memory items/i)).toBeInTheDocument();
    // "Ingest memory" exists but only inside the modal — not as a row-level button
    expect(screen.getByRole('button', { name: /^ingest memory$/i })).toBeInTheDocument();
  });

  it('MemoryPreviewModal shows eligibility reasons when ineligible', async () => {
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'low_confidence', detail: 'score 0.70 below 0.80' }],
      estimated_memory_item_count: 0,
    });

    const parsedLog = { ...sampleLog, parse_status: 'parsed' };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      expect(screen.getByText(/not eligible/i)).toBeInTheDocument();
      expect(screen.getByText(/low_confidence/i)).toBeInTheDocument();
    });
  });

  it('MemoryPreviewModal does not show "Force ingest" when ineligible', async () => {
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'low_confidence', detail: 'score 0.70 below 0.80' }],
      estimated_memory_item_count: 0,
    });

    const parsedLog = { ...sampleLog, parse_status: 'parsed' };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => expect(screen.getByText(/not eligible/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /force ingest/i })).not.toBeInTheDocument();
    // Ingest memory button must not appear when ineligible
    expect(screen.queryByRole('button', { name: /^ingest memory$/i })).not.toBeInTheDocument();
  });

  it('clicking "View memory" opens the MemoryItemsModal', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 2 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });
    (getMemoryItems as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        {
          id: 'item-001',
          ingestion_id: 'ing-001',
          observed_play_log_id: 'log-001',
          observed_play_event_id: 42,
          memory_type: 'attack_used',
          memory_key: 'attack_used:42:Pikachu:Thunderbolt:',
          turn_number: 3,
          phase: 'turn',
          player_alias: 'P1',
          player_raw: 'Player1',
          actor_card_raw: 'Pikachu',
          actor_card_def_id: 'sv06-049',
          actor_resolution_status: 'resolved',
          target_card_raw: null,
          target_card_def_id: null,
          target_resolution_status: null,
          related_card_raw: null,
          related_card_def_id: null,
          related_resolution_status: null,
          action_name: 'Thunderbolt',
          amount: null,
          damage: 90,
          zone: 'active',
          target_zone: 'active',
          confidence_score: 0.88,
          source_event_type: 'attack_used',
          source_raw_line: "P1's Pikachu used Thunderbolt.",
          created_at: null,
        },
      ],
      total: 1, page: 1, per_page: 50,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: 'View memory' }));
    await userEvent.click(screen.getByRole('button', { name: 'View memory' }));

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /memory items/i })).toBeInTheDocument();
    });
    expect(screen.getByText('attack_used')).toBeInTheDocument();
    expect(screen.getByText('Pikachu')).toBeInTheDocument();
  });

  it('memory item count shows in logs table for ingested logs', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 7 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByText('7')).toBeInTheDocument();
    });
  });

  it('phase 4 banner mentions "not used by Coach or AI Player"', async () => {
    setup();
    await waitFor(() => {
      const matches = screen.getAllByText(/not used by coach or ai player/i);
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('MemoryPreviewModal shows safety copy about Coach/AI', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed' };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText(/not used by coach or ai player/i)).toBeInTheDocument();
    });
  });

  // ── Phase 4.1: Memory preview blocker details ────────────────────────────────

  it('shows blocker table when preview response includes blockers', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'unresolved_critical_cards', detail: '1 unresolved critical' }],
      estimated_memory_item_count: 0,
      blockers: [{
        code: 'unresolved_critical_card',
        raw_name: 'Mystery Card',
        mention_role: 'actor_card',
        turn_number: 3,
        player_alias: 'P1',
        source_event_type: 'attack_used',
        raw_line: "P1's Mystery Card used Tackle.",
      }],
      blocker_count: 1,
      blockers_truncated: false,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText(/blocking unresolved mentions/i)).toBeInTheDocument();
      expect(within(dialog).getByText('Mystery Card')).toBeInTheDocument();
      expect(within(dialog).getByText('actor_card')).toBeInTheDocument();
    });
  });

  it('blocker table shows raw name, role, turn, player, event, and source line', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'unresolved_critical_cards', detail: '1 unresolved critical' }],
      estimated_memory_item_count: 0,
      blockers: [{
        code: 'unresolved_critical_card',
        raw_name: 'FireCard',
        mention_role: 'target_card',
        turn_number: 7,
        player_alias: 'Opponent',
        source_event_type: 'knockout',
        raw_line: "Opponent's FireCard was knocked out.",
      }],
      blocker_count: 1,
      blockers_truncated: false,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText('FireCard')).toBeInTheDocument();
      expect(within(dialog).getByText('target_card')).toBeInTheDocument();
      expect(within(dialog).getByText('7')).toBeInTheDocument();
      expect(within(dialog).getByText('Opponent')).toBeInTheDocument();
      expect(within(dialog).getByText('knockout')).toBeInTheDocument();
      expect(within(dialog).getByText("Opponent's FireCard was knocked out.")).toBeInTheDocument();
    });
  });

  it('blocker section is absent when no blockers are present', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    // Default mock: eligible, no blockers

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => screen.getByRole('dialog', { name: /memory preview/i }));
    const dialog = screen.getByRole('dialog', { name: /memory preview/i });
    expect(within(dialog).queryByText(/blocking unresolved mentions/i)).not.toBeInTheDocument();
  });

  it('shows truncation notice when blockers_truncated is true', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'unresolved_critical_cards', detail: '30 unresolved critical' }],
      estimated_memory_item_count: 0,
      blockers: Array.from({ length: 25 }, (_, i) => ({
        code: 'unresolved_critical_card',
        raw_name: `Card ${i + 1}`,
        mention_role: 'actor_card',
        turn_number: i + 1,
        player_alias: 'P1',
        source_event_type: 'attack_used',
        raw_line: `Card ${i + 1} used move.`,
      })),
      blocker_count: 30,
      blockers_truncated: true,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText(/showing first 25 blockers/i)).toBeInTheDocument();
    });
  });

  it('eligibility reasons still render alongside blockers', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: false,
      eligibility_status: 'ineligible',
      reasons: [{ code: 'unresolved_critical_cards', detail: '2 critical unresolved' }],
      estimated_memory_item_count: 0,
      blockers: [{ code: 'unresolved_critical_card', raw_name: 'A', mention_role: 'actor_card' }],
      blocker_count: 1,
      blockers_truncated: false,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText('unresolved_critical_cards')).toBeInTheDocument();
      expect(within(dialog).getByText(/2 critical unresolved/i)).toBeInTheDocument();
      expect(within(dialog).getByText(/blocking unresolved mentions/i)).toBeInTheDocument();
    });
  });

  it('ingest 422 error with blockers displays blockers in modal', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });
    (ingestMemory as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: {
        data: {
          detail: {
            message: 'Ineligible for ingestion',
            blockers: [{
              code: 'unresolved_critical_card',
              raw_name: 'ErrorCard',
              mention_role: 'actor_card',
              turn_number: 2,
              player_alias: 'P2',
              source_event_type: 'attack_used',
            }],
            blocker_count: 1,
            blockers_truncated: false,
          },
        },
      },
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));

    await waitFor(() => screen.getByRole('dialog', { name: /memory preview/i }));
    await userEvent.click(screen.getByRole('button', { name: /^ingest memory$/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory preview/i });
      expect(within(dialog).getByText(/ineligible for ingestion/i)).toBeInTheDocument();
      expect(within(dialog).getByText('ErrorCard')).toBeInTheDocument();
    });
  });
});


// ── Phase 3.2: Resolution rule UI tests ──────────────────────────────────────

import { createResolutionRule, resolveCards } from '../api/observedPlay';

const sampleUnresolvedItem = {
  raw_name: 'Dragapult ex',
  normalized_name: 'dragapult ex',
  status: 'ambiguous' as const,
  mention_count: 8,
  log_count: 2,
  candidate_count: 1,
  candidates: [
    {
      card_def_id: 'sv08-164',
      name: 'Dragapult ex',
      set_abbrev: 'sv08',
      set_number: '164',
      image_url: null,
      confidence: 1.0,
      reason: 'exact normalized name',
    },
  ],
  sample_mentions: [
    {
      log_id: 'log-001',
      filename: 'game.md',
      event_id: 100,
      turn_number: 3,
      player_alias: 'player_1',
      mention_role: 'actor_card',
      source_event_type: 'attack_used',
      raw_line: 'Dragapult ex used Phantom Dive',
    },
  ],
  affected_log_ids: ['log-001'],
};

describe('Phase 3.2 — Unresolved/Ambiguous Cards section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (listObservedPlayBatches as ReturnType<typeof vi.fn>).mockResolvedValue(emptyBatches);
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue(emptyLogs);
    (getObservedPlayLogEvents as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 50,
    });
    (reparseObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      log_id: 'log-001', parse_status: 'parsed', event_count: 0,
      turn_count: 0, confidence_score: null, parser_version: null,
      warnings: [], errors: [], parser_diagnostics: null,
      card_mention_count: 0, resolved_card_count: 0, ambiguous_card_count: 0,
      unresolved_card_count: 0, card_resolution_status: null,
    });
    (getCardMentions as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 50,
    });
    (previewMemoryIngestion as ReturnType<typeof vi.fn>).mockResolvedValue({
      eligible: true, eligibility_status: 'eligible', reasons: [],
      estimated_memory_item_count: 5, event_type_counts: {}, sample_items: [],
    });
    (ingestMemory as ReturnType<typeof vi.fn>).mockResolvedValue({
      ingestion_id: 'ing-001', log_id: 'log-001', status: 'completed',
      eligibility_status: 'eligible', reasons: [], memory_item_count: 5, ingestion_version: '1.0',
    });
    (getMemoryItems as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 25 });
    (createResolutionRule as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'rule-001', raw_name: 'Dragapult ex', normalized_name: 'dragapult ex',
      action: 'resolve', target_card_def_id: 'sv08-164', target_card_name: 'Dragapult ex',
      scope: 'global', notes: null, created_at: null,
    });
    (resolveCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      log_id: 'log-001', resolved_count: 1, ambiguous_count: 0, unresolved_count: 0,
    });
  });

  it('renders Review action button for each unresolved item', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });

    setup();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /review dragapult ex/i })).toBeInTheDocument();
    });
  });

  it('clicking Review opens resolution modal', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));

    await waitFor(() => {
      expect(screen.getByText(/resolve card mention/i)).toBeInTheDocument();
    });
  });

  it('modal renders raw name and candidate list', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));

    await waitFor(() => {
      expect(screen.getAllByText('Dragapult ex').length).toBeGreaterThan(0);
      expect(screen.getByText('sv08-164')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^select$/i })).toBeInTheDocument();
    });
  });

  it('modal renders sample mentions table', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));

    await waitFor(() => {
      expect(screen.getByText(/sample mentions/i)).toBeInTheDocument();
      expect(screen.getByText('Dragapult ex used Phantom Dive')).toBeInTheDocument();
      expect(screen.getByText('actor_card')).toBeInTheDocument();
    });
  });

  it('selecting a candidate calls createResolutionRule with action=resolve', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect(createResolutionRule).toHaveBeenCalledWith(
        expect.objectContaining({ action: 'resolve', target_card_def_id: 'sv08-164' })
      );
    });
  });

  it('after successful resolve, reruns resolution for affected logs', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect(resolveCards).toHaveBeenCalledWith('log-001');
    });
  });

  it('after successful resolve, shows success message', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect(screen.getByText(/rule created/i)).toBeInTheDocument();
    });
  });

  it('ignore action calls createResolutionRule with action=ignore', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /ignore this name/i }));
    await userEvent.click(screen.getByRole('button', { name: /ignore this name/i }));

    await waitFor(() => {
      expect(createResolutionRule).toHaveBeenCalledWith(
        expect.objectContaining({ action: 'ignore' })
      );
    });
  });

  it('API error in rule creation shows error message in modal', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });
    (createResolutionRule as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'A rule already exists for this name' } },
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect(screen.getByText(/a rule already exists/i)).toBeInTheDocument();
    });
  });

  it('after successful resolve, listObservedPlayLogs is called again without waiting for Close', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));

    const callsBefore = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect((listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('after ignore rule, listObservedPlayLogs is called again without waiting for Close', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /ignore this name/i }));

    const callsBefore = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /ignore this name/i }));

    await waitFor(() => {
      expect((listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('Raw Logs table card counts reflect updated data after rule creation', async () => {
    const logWithCounts = {
      id: 'log-001', filename: 'game.md', upload_batch_id: 'b1',
      parse_status: 'parsed', created_at: '2024-01-01T00:00:00Z',
      card_mention_count: 10, resolved_card_count: 7, ambiguous_card_count: 3, unresolved_card_count: 0,
      card_resolution_status: 'ambiguous', memory_status: null, memory_item_count: 0,
      event_count: 0, turn_count: 0, confidence_score: null, parser_version: null,
      warnings: [], errors: [], parser_diagnostics: null,
      sha256_hash: 'abcdef1234567890', file_size_bytes: 1024,
    };
    const updatedLog = { ...logWithCounts, resolved_card_count: 10, ambiguous_card_count: 0, card_resolution_status: 'resolved' };

    (listObservedPlayLogs as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ items: [logWithCounts], total: 1, page: 1, per_page: 25 })
      .mockResolvedValue({ items: [updatedLog], total: 1, page: 1, per_page: 25 });
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    }).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 20 });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    setup();

    // initial counts: resolved=7✓, ambiguous=3?
    await waitFor(() => expect(screen.getByText('7✓')).toBeInTheDocument());
    expect(screen.getByText('3?')).toBeInTheDocument();

    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));

    // after refresh: resolved=10✓, no ambiguous badge
    await waitFor(() => expect(screen.getByText('10✓')).toBeInTheDocument());
    expect(screen.queryByText('3?')).not.toBeInTheDocument();
  });
});

// ── Bugfix: sequential resolution refresh ────────────────────────────────────

describe('Bugfix — sequential resolution refresh', () => {
  const cardA = {
    raw_name: 'Pikachu ex',
    normalized_name: 'pikachu ex',
    status: 'ambiguous' as const,
    mention_count: 3,
    log_count: 1,
    candidate_count: 1,
    candidates: [{
      card_def_id: 'sv01-100',
      name: 'Pikachu ex',
      set_abbrev: 'sv01',
      set_number: '100',
      image_url: null,
      confidence: 1.0,
      reason: 'exact',
    }],
    sample_mentions: [],
    affected_log_ids: ['log-001'],
  };
  const cardB = {
    ...cardA,
    raw_name: 'Charizard ex',
    normalized_name: 'charizard ex',
    candidates: [{ ...cardA.candidates[0], card_def_id: 'sv03-200', name: 'Charizard ex' }],
    affected_log_ids: ['log-002'],
  };
  const cardC = {
    ...cardA,
    raw_name: 'Mewtwo V',
    normalized_name: 'mewtwo v',
    candidates: [{ ...cardA.candidates[0], card_def_id: 'sv02-150', name: 'Mewtwo V' }],
    affected_log_ids: ['log-003'],
  };
  const allCards = [cardA, cardB, cardC];
  let resolvedCount = 0;

  beforeEach(() => {
    resolvedCount = 0;
    (resolveCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      log_id: 'log-001', resolved_count: 1, ambiguous_count: 0, unresolved_count: 0,
    });
    (createResolutionRule as ReturnType<typeof vi.fn>).mockImplementation(() => {
      resolvedCount++;
      const card = allCards[resolvedCount - 1] ?? cardA;
      return Promise.resolve({
        id: `rule-${resolvedCount}`,
        raw_name: card.raw_name,
        normalized_name: card.normalized_name,
        action: 'resolve',
        target_card_def_id: card.candidates[0].card_def_id,
        target_card_name: card.candidates[0].name,
        scope: 'global',
        notes: null,
        created_at: null,
      });
    });
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockImplementation(() =>
      Promise.resolve({
        items: allCards.slice(resolvedCount),
        total: allCards.length - resolvedCount,
        page: 1,
        per_page: 20,
      })
    );
  });

  it('resolving one ambiguous row removes it from the list immediately', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));
    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /review pikachu ex/i })).not.toBeInTheDocument();
    });
  });

  it('resolving three rows sequentially removes each row without page refresh — regression case', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));

    // Resolution 1
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));
    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));
    await waitFor(() => expect(screen.queryByRole('button', { name: /review pikachu ex/i })).not.toBeInTheDocument());

    // Resolution 2
    await waitFor(() => screen.getByRole('button', { name: /review charizard ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review charizard ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));
    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));
    await waitFor(() => expect(screen.queryByRole('button', { name: /review charizard ex/i })).not.toBeInTheDocument());

    // Resolution 3 — this is the regression case that was broken before the fix
    await waitFor(() => screen.getByRole('button', { name: /review mewtwo v/i }));
    await userEvent.click(screen.getByRole('button', { name: /review mewtwo v/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));
    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));
    await waitFor(() => expect(screen.queryByRole('button', { name: /review mewtwo v/i })).not.toBeInTheDocument());
  });

  it('ignore rule path removes row without page refresh', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /ignore this name/i }));
    await userEvent.click(screen.getByRole('button', { name: /ignore this name/i }));
    await waitFor(() => screen.getByText(/ignore rule created/i));
    await userEvent.click(screen.getByText('Close'));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /review pikachu ex/i })).not.toBeInTheDocument();
    });
  });

  it('after resolution, getUnresolvedCards is called again', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));

    const callsBefore = (getUnresolvedCards as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect((getUnresolvedCards as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('after resolution, listObservedPlayLogs is called again', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));

    const callsBefore = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect((listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('after resolution, getMemoryAnalytics is called again', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));

    const callsBefore = (getMemoryAnalytics as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => {
      expect((getMemoryAnalytics as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('when all rows are resolved, the unresolved section disappears', async () => {
    resolvedCount = 2; // only cardC remains
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review mewtwo v/i }));
    await userEvent.click(screen.getByRole('button', { name: /review mewtwo v/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));
    await waitFor(() => screen.getByText(/rule created/i));
    await userEvent.click(screen.getByText('Close'));

    await waitFor(() => {
      expect(screen.queryByText(/unresolved \/ ambiguous cards/i)).not.toBeInTheDocument();
    });
  });

  it('API error does not remove the row from the list', async () => {
    (createResolutionRule as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'Duplicate: rule already exists' } },
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    setup();

    await waitFor(() => screen.getByRole('button', { name: /review pikachu ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review pikachu ex/i }));
    await waitFor(() => screen.getByRole('button', { name: /^select$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^select$/i }));

    await waitFor(() => screen.getByText(/duplicate: rule already exists/i));

    // Row remains in the list — error path must not remove it
    expect(screen.getByRole('button', { name: /review pikachu ex/i })).toBeInTheDocument();
  });
});

// ── Dark mode styling tests ───────────────────────────────────────────────────

describe('Dark mode styling', () => {
  it('Raw Logs section panel has dark:bg-slate-900 class', async () => {
    setup();
    await waitFor(() => screen.getByText('Raw Logs'));
    const section = screen.getByText('Raw Logs').closest('section');
    expect(section?.className).toContain('dark:bg-slate-900');
  });

  it('Import History section panel has dark:bg-slate-900 class', async () => {
    setup();
    await waitFor(() => screen.getByText('Import History'));
    const section = screen.getByText('Import History').closest('section');
    expect(section?.className).toContain('dark:bg-slate-900');
  });

  it('Unresolved section has dark amber border class when items present', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });
    setup();
    await waitFor(() => screen.getByText(/unresolved \/ ambiguous cards/i));
    const section = screen.getByText(/unresolved \/ ambiguous cards/i).closest('section');
    expect(section?.className).toContain('dark:border-amber-800');
    expect(section?.className).toContain('dark:bg-amber-950/50');
  });

  it('RawLogModal has dark:bg-slate-900 on the panel', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleLog], total: 1, page: 1, per_page: 25,
    });
    (getObservedPlayLog as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sampleLog,
      raw_content: '# Game',
      player_1_name_raw: null, player_2_name_raw: null,
      player_1_alias: null, player_2_alias: null,
      winner_raw: null, win_condition: null,
      turn_count: 0, event_count: 0, confidence_score: null,
      errors_json: [], warnings_json: [], metadata_json: {},
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /view raw/i }));
    await userEvent.click(screen.getByRole('button', { name: /view raw/i }));
    await waitFor(() => screen.getByRole('dialog'));

    const panel = screen.getByRole('dialog').querySelector('.dark\\:bg-slate-900');
    expect(panel).toBeTruthy();
  });

  it('MemoryPreviewModal has dark:bg-slate-900 on the panel', async () => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ ...sampleLog, parse_status: 'parsed' }],
      total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /preview memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /preview memory/i }));
    await waitFor(() => screen.getByRole('dialog', { name: /memory preview/i }));

    const panel = screen.getByRole('dialog', { name: /memory preview/i })
      .querySelector('.dark\\:bg-slate-900');
    expect(panel).toBeTruthy();
  });

  it('ResolutionRuleModal has dark:bg-slate-900 on the panel', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleUnresolvedItem], total: 1, page: 1, per_page: 20,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /review dragapult ex/i }));
    await userEvent.click(screen.getByRole('button', { name: /review dragapult ex/i }));
    await waitFor(() => screen.getByText(/resolve card mention/i));

    const panel = document.querySelector('.dark\\:bg-slate-900');
    expect(panel).toBeTruthy();
  });
});
describe('Phase 5 — Memory Analytics', () => {
  it('Memory Analytics section renders', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText('Memory Analytics')).toBeInTheDocument();
    });
  });

  it('Empty state renders when no memory items', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(emptySummary);
    setup();
    await waitFor(() => {
      expect(screen.getByText(/no observed memories have been ingested yet/i)).toBeInTheDocument();
    });
  });

  it('Summary cards render when items exist', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    setup();
    await waitFor(() => {
      expect(screen.getByText('158')).toBeInTheDocument();
      expect(screen.getByText('Memory Analytics')).toBeInTheDocument();
    });
  });

  it('Memory type counts render', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_memory_types: [{
        label: 'attack_used',
        memory_type: 'attack_used',
        count: 18,
        average_confidence: 0.9,
        resolved_count: 15,
        ambiguous_count: 2,
        unresolved_count: 1,
        sample_memory_item_ids: [],
        sample_source_lines: [],
      }],
    });
    setup();
    await waitFor(() => {
      expect(screen.getByText('attack_used')).toBeInTheDocument();
    });
  });

  it('View examples opens modal', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_memory_types: [{
        label: 'attack_used',
        memory_type: 'attack_used',
        count: 18,
        average_confidence: 0.9,
        resolved_count: 15,
        ambiguous_count: 2,
        unresolved_count: 1,
        sample_memory_item_ids: [],
        sample_source_lines: [],
      }],
    });
    (getMemoryAnalyticsSourceItems as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [], total: 0, page: 1, per_page: 20,
    });
    setup();
    await waitFor(() => screen.getByText('attack_used'));
    const examplesBtns = screen.getAllByRole('button', { name: /examples/i });
    await userEvent.click(examplesBtns[0]);
    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /memory examples/i })).toBeInTheDocument();
    });
  });

  it('Refresh analytics button calls APIs', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    const refreshBtn = screen.getByRole('button', { name: /refresh analytics/i });
    await userEvent.click(refreshBtn);
    await waitFor(() => {
      expect(getMemorySummary as ReturnType<typeof vi.fn>).toHaveBeenCalledTimes(2);
    });
  });

  it('Safety copy present', async () => {
    setup();
    await waitFor(() => {
      const matches = screen.getAllByText(/not used by coach or ai player yet/i);
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('Dark mode classes on analytics panel', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    const section = screen.getByText('Memory Analytics').closest('section');
    expect(section?.className).toContain('dark:bg-slate-900');
  });
});

describe('Phase 5.1 — Analytics Quality Triage', () => {
  it('quality filter controls render', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Ambiguous refs')).toBeInTheDocument();
    expect(screen.getByText('Low confidence')).toBeInTheDocument();
    expect(screen.getByText('Unresolved refs')).toBeInTheDocument();
  });

  it('selecting Ambiguous refs calls getMemoryAnalytics with quality_filter=ambiguous', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    const btn = screen.getByRole('button', { name: /ambiguous refs/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(getMemoryAnalytics as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
        expect.objectContaining({ quality_filter: 'ambiguous' })
      )
    );
  });

  it('selecting Low confidence calls getMemoryAnalytics with quality_filter=low_confidence', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    const btn = screen.getByRole('button', { name: /low confidence/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(getMemoryAnalytics as ReturnType<typeof vi.fn>).toHaveBeenCalledWith(
        expect.objectContaining({ quality_filter: 'low_confidence' })
      )
    );
  });

  it('Review button appears for rows with can_review_resolution and ambiguous/unresolved counts', async () => {
    (getUnresolvedCards as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0, page: 1, per_page: 100 });
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_actor_cards: [{
        label: 'Dudunsparce',
        memory_type: 'actor_card',
        count: 5,
        average_confidence: 0.7,
        resolved_count: 1,
        ambiguous_count: 4,
        unresolved_count: 0,
        sample_memory_item_ids: [],
        sample_source_lines: [],
        can_review_resolution: true,
        review_raw_name: 'Dudunsparce',
        review_status: 'ambiguous',
      }],
    });
    setup();
    await waitFor(() => screen.getByText('Dudunsparce'));
    expect(screen.getByRole('button', { name: /^review$/i })).toBeInTheDocument();
  });

  it('re-ingestion note is visible', async () => {
    setup();
    await waitFor(() => screen.getByText('Memory Analytics'));
    expect(screen.getByText(/re-ingest logs to reflect changed resolution/i)).toBeInTheDocument();
  });

  it('examples modal shows filter label', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_memory_types: [{
        label: 'attack_used',
        memory_type: 'attack_used',
        count: 5,
        average_confidence: 0.9,
        resolved_count: 5,
        ambiguous_count: 0,
        unresolved_count: 0,
        sample_memory_item_ids: [],
        sample_source_lines: [],
      }],
    });
    (getMemoryAnalyticsSourceItems as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      per_page: 20,
    });
    setup();
    await waitFor(() => screen.getByText('attack_used'));
    fireEvent.click(screen.getByRole('button', { name: 'Examples' }));
    await waitFor(() => screen.getByRole('dialog', { name: /memory examples/i }));
    expect(screen.getByText(/filter:/i)).toBeInTheDocument();
  });
});

describe('Phase 5.1 — Analytics Table Column Alignment', () => {
  it('analytics table always renders Examples and Review column headers', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_memory_types: [{
        label: 'card_played',
        memory_type: 'card_played',
        count: 3,
        average_confidence: 0.9,
        resolved_count: 3,
        ambiguous_count: 0,
        unresolved_count: 0,
        sample_memory_item_ids: [],
        sample_source_lines: [],
      }],
    });
    setup();
    await waitFor(() => screen.getByText('Memory types'));
    // Both column headers must be visible
    const examplesHeaders = screen.getAllByText('Examples');
    const reviewHeaders = screen.getAllByText('Review');
    expect(examplesHeaders.length).toBeGreaterThan(0);
    expect(reviewHeaders.length).toBeGreaterThan(0);
  });

  it('non-reviewable rows render a placeholder in the Review column', async () => {
    (getMemorySummary as ReturnType<typeof vi.fn>).mockResolvedValue(sampleSummary);
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_actor_cards: [{
        label: 'Pikachu',
        memory_type: 'actor_card',
        count: 2,
        average_confidence: 0.95,
        resolved_count: 2,
        ambiguous_count: 0,
        unresolved_count: 0,
        sample_memory_item_ids: [],
        sample_source_lines: [],
        can_review_resolution: false,
      }],
    });
    setup();
    await waitFor(() => screen.getByText('Pikachu'));
    // Placeholder — should be present; no Review button
    expect(screen.queryByRole('button', { name: /^review$/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Not reviewable')).toBeInTheDocument();
  });

  it('label cell renders title attribute for truncation', async () => {
    (getMemoryAnalytics as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...emptyAnalytics,
      top_actions: [{
        label: 'attack_used:Very Long Attack Name That Would Overflow',
        memory_type: 'attack_used',
        count: 1,
        average_confidence: 0.8,
        resolved_count: 0,
        ambiguous_count: 1,
        unresolved_count: 0,
        sample_memory_item_ids: [],
        sample_source_lines: [],
      }],
    });
    setup();
    await waitFor(() => screen.getByText('attack_used:Very Long Attack Name That Would Overflow'));
    const cell = screen.getByTitle('attack_used:Very Long Attack Name That Would Overflow');
    expect(cell).toBeInTheDocument();
  });
});

// ── Raw Logs — sorting ────────────────────────────────────────────────────────

describe('Raw Logs — sorting', () => {
  const logsResponse = {
    items: [{
      id: 'log-001',
      import_batch_id: 'batch-001',
      source: 'ptcgl_export',
      original_filename: 'alpha.md',
      sha256_hash: 'aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344',
      file_size_bytes: 2048,
      parse_status: 'parsed',
      memory_status: 'not_ingested',
      stored_path: 'archive/aa/aa.md',
      created_at: '2026-01-01T00:00:00Z',
      parser_version: null,
      event_count: 120,
      confidence_score: 0.92,
      winner_raw: null,
      win_condition: null,
      card_mention_count: 50,
      resolved_card_count: 45,
      ambiguous_card_count: 5,
      unresolved_card_count: 0,
      memory_item_count: 0,
    }],
    total: 1,
    page: 1,
    per_page: 25,
  };

  beforeEach(() => {
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue(logsResponse);
  });

  it('renders sortable column header buttons', async () => {
    setup();
    await waitFor(() => screen.getByText('Raw Logs'));
    await waitFor(() => screen.getByRole('button', { name: /sort by confidence/i }));
    expect(screen.getByRole('button', { name: /sort by events/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sort by filename/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sort by imported at/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sort by cards/i })).toBeInTheDocument();
  });

  it('default sort direction indicator shows active ▼ on Imported at (default sort)', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by imported at/i }));
    // "Imported at" is default sort (created_at desc) — should show ▼
    const importedAtBtn = screen.getByRole('button', { name: /sort by imported at/i });
    expect(importedAtBtn.textContent).toContain('▼');
  });

  it('clicking Confidence calls listObservedPlayLogs with sort_by=confidence_score', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by confidence/i }));
    const callsBefore = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls.length;

    await userEvent.click(screen.getByRole('button', { name: /sort by confidence/i }));

    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      expect(calls.length).toBeGreaterThan(callsBefore);
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('confidence_score');
      expect(lastParams.sort_dir).toBe('desc');
    });
  });

  it('clicking active Confidence column toggles direction to asc', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by confidence/i }));

    // First click: set confidence desc
    await userEvent.click(screen.getByRole('button', { name: /sort by confidence/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('confidence_score');
      expect(lastParams.sort_dir).toBe('desc');
    });

    // Second click on same column: toggles to asc
    await userEvent.click(screen.getByRole('button', { name: /sort by confidence/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('confidence_score');
      expect(lastParams.sort_dir).toBe('asc');
    });
  });

  it('clicking Events resets to page 1 and sorts by event_count', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by events/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by events/i }));

    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('event_count');
      expect(lastParams.sort_dir).toBe('desc');
      expect(lastParams.page).toBe(1);
    });
  });

  it('clicking Cards sends sort_by=cards desc (composite sort)', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by cards/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by cards/i }));

    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('cards');
      expect(lastParams.sort_dir).toBe('desc');
    });
  });

  it('clicking Cards again toggles to asc', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by cards/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by cards/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      expect(calls[calls.length - 1][0].sort_by).toBe('cards');
      expect(calls[calls.length - 1][0].sort_dir).toBe('desc');
    });

    await userEvent.click(screen.getByRole('button', { name: /sort by cards/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      expect(calls[calls.length - 1][0].sort_by).toBe('cards');
      expect(calls[calls.length - 1][0].sort_dir).toBe('asc');
    });
  });

  it('Cards header has tooltip about unresolved/ambiguous/card mention sort', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by cards/i }));
    const cardsBtn = screen.getByRole('button', { name: /sort by cards/i });
    expect(cardsBtn.title).toContain('unresolved');
    expect(cardsBtn.title).toContain('ambiguous');
  });

  it('active sort column shows directional arrow, inactive columns show muted ↕', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by confidence/i }));
    await userEvent.click(screen.getByRole('button', { name: /sort by confidence/i }));

    await waitFor(() => {
      const confidenceBtn = screen.getByRole('button', { name: /sort by confidence/i });
      expect(confidenceBtn.textContent).toContain('▼');
    });
    // Events (inactive) should show ↕
    const eventsBtn = screen.getByRole('button', { name: /sort by events/i });
    expect(eventsBtn.textContent).toContain('↕');
  });

  it('sorting preserves table row actions (View raw, View events)', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by confidence/i }));
    await userEvent.click(screen.getByRole('button', { name: /sort by confidence/i }));

    await waitFor(() => screen.getByRole('button', { name: /view raw/i }));
    expect(screen.getByRole('button', { name: /view events/i })).toBeInTheDocument();
  });

  it('clicking Filename sorts alphabetically (asc)', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by filename/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by filename/i }));

    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('filename');
      expect(lastParams.sort_dir).toBe('asc');
    });
  });

  it('clicking Parse sends sort_by=parse_status asc', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by parse/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by parse/i }));

    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      const lastParams = calls[calls.length - 1][0];
      expect(lastParams.sort_by).toBe('parse_status');
      expect(lastParams.sort_dir).toBe('asc');
    });
  });

  it('clicking active Parse toggles to desc', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by parse/i }));

    await userEvent.click(screen.getByRole('button', { name: /sort by parse/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      expect(calls[calls.length - 1][0].sort_by).toBe('parse_status');
      expect(calls[calls.length - 1][0].sort_dir).toBe('asc');
    });

    await userEvent.click(screen.getByRole('button', { name: /sort by parse/i }));
    await waitFor(() => {
      const calls = (listObservedPlayLogs as ReturnType<typeof vi.fn>).mock.calls;
      expect(calls[calls.length - 1][0].sort_by).toBe('parse_status');
      expect(calls[calls.length - 1][0].sort_dir).toBe('desc');
    });
  });

  it('Parse header has tooltip about status/quality ordering', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /sort by parse/i }));
    const parseBtn = screen.getByRole('button', { name: /sort by parse/i });
    expect(parseBtn.title).toContain('parse status');
  });
});

// ── Bulk actions ──────────────────────────────────────────────────────────────

describe('Bulk actions panel', () => {
  it('renders Parse / Reparse all and Ingest all eligible buttons', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('Bulk Actions')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /parse \/ reparse all/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ingest all eligible/i })).toBeInTheDocument();
  });

  it('clicking Parse / Reparse all opens the confirm modal', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    expect(screen.getByRole('dialog', { name: /bulk parse modal/i })).toBeInTheDocument();
  });

  it('bulk parse modal has Run button', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    expect(screen.getByRole('button', { name: /run parse \/ reparse/i })).toBeInTheDocument();
  });

  it('bulk parse modal close button dismisses modal', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    const dialog = screen.getByRole('dialog', { name: /bulk parse modal/i });
    const closeBtns = within(dialog).getAllByRole('button', { name: /^close$/i });
    await userEvent.click(closeBtns[closeBtns.length - 1]); // footer Close button
    expect(screen.queryByRole('dialog', { name: /bulk parse modal/i })).not.toBeInTheDocument();
  });

  it('running bulk parse calls bulkReparseAll and shows result counts', async () => {
    (bulkReparseAll as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 5, reparsed_count: 4, skipped_count: 1, failed_count: 0,
      reparsed: [], skipped: [], failed: [], average_confidence: 0.88, total_event_count: 120,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /run parse \/ reparse/i }));

    await waitFor(() => {
      expect(bulkReparseAll as ReturnType<typeof vi.fn>).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText('4')).toBeInTheDocument(); // reparsed_count
    });
  });

  it('bulk parse shows average confidence after run', async () => {
    (bulkReparseAll as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, reparsed_count: 3, skipped_count: 0, failed_count: 0,
      reparsed: [], skipped: [], failed: [], average_confidence: 0.92, total_event_count: 60,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /run parse \/ reparse/i }));

    await waitFor(() => {
      expect(screen.getByText(/avg confidence/i)).toBeInTheDocument();
      expect(screen.getByText(/92\.0%/)).toBeInTheDocument();
    });
  });

  it('bulk parse error displays message', async () => {
    (bulkReparseAll as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('server error'));

    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /run parse \/ reparse/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  it('clicking Ingest all eligible opens modal and calls bulkPreviewEligible', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => {
      expect(bulkPreviewEligible as ReturnType<typeof vi.fn>).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByRole('dialog', { name: /bulk ingest eligible modal/i })).toBeInTheDocument();
  });

  it('ingest modal shows eligible count from preview', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 5, eligible_count: 3, ineligible_count: 1,
      already_ingested_count: 1, not_ready_count: 0, estimated_memory_item_count: 15,
      eligible_logs: [], skipped_logs: [], top_blocker_reasons: [],
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /ingest 3 eligible log/i })).toBeInTheDocument();
    });
  });

  it('ingest modal shows no eligible message when count is 0', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 2, eligible_count: 0, ineligible_count: 2,
      already_ingested_count: 0, not_ready_count: 0, estimated_memory_item_count: 0,
      eligible_logs: [], skipped_logs: [], top_blocker_reasons: [],
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => {
      expect(screen.getByText(/no eligible logs to ingest/i)).toBeInTheDocument();
    });
  });

  it('bulk ingest run calls bulkIngestEligible and shows result', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, eligible_count: 2, ineligible_count: 1,
      already_ingested_count: 0, not_ready_count: 0, estimated_memory_item_count: 10,
      eligible_logs: [], skipped_logs: [], top_blocker_reasons: [],
    });
    (bulkIngestEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, eligible_count: 2, ingested_count: 2, skipped_count: 1,
      failed_count: 0, memory_items_created: 10,
      ingested_logs: [], skipped_logs: [], failed_logs: [],
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));
    await waitFor(() => screen.getByRole('button', { name: /ingest 2 eligible log/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest 2 eligible log/i }));

    await waitFor(() => {
      expect(bulkIngestEligible as ReturnType<typeof vi.fn>).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText('10')).toBeInTheDocument(); // memory_items_created
    });
  });

  it('ingest modal close button dismisses modal', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));
    await waitFor(() => screen.getByRole('dialog', { name: /bulk ingest eligible modal/i }));
    const dialog = screen.getByRole('dialog', { name: /bulk ingest eligible modal/i });
    const closeBtns = within(dialog).getAllByRole('button', { name: /^close$/i });
    await userEvent.click(closeBtns[closeBtns.length - 1]); // footer Close button
    expect(screen.queryByRole('dialog', { name: /bulk ingest eligible modal/i })).not.toBeInTheDocument();
  });

  it('ingest preview error displays message', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('preview failed'));

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  it('parse modal has unchecked "Include already-ingested logs" checkbox by default', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));
    const checkbox = screen.getByRole('checkbox', { name: /include already-ingested logs/i });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
  });

  it('checking "Include already-ingested logs" sends include_ingested=true', async () => {
    (bulkReparseAll as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, reparsed_count: 3, skipped_count: 0, failed_count: 0,
      ingested_reparsed_count: 2,
      reparsed: [], skipped: [], failed: [], average_confidence: 0.85, total_event_count: 60,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));

    const checkbox = screen.getByRole('checkbox', { name: /include already-ingested logs/i });
    await userEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    await userEvent.click(screen.getByRole('button', { name: /run parse \/ reparse/i }));

    await waitFor(() => {
      expect(bulkReparseAll as ReturnType<typeof vi.fn>).toHaveBeenCalledWith({ include_ingested: true });
    });
  });

  it('checking include-ingested shows warning copy', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));

    const checkbox = screen.getByRole('checkbox', { name: /include already-ingested logs/i });
    await userEvent.click(checkbox);

    expect(screen.getByText(/already-ingested logs will be reparsed/i)).toBeInTheDocument();
  });

  it('parse result shows ingested_reparsed_count when non-zero', async () => {
    (bulkReparseAll as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 5, reparsed_count: 5, skipped_count: 0, failed_count: 0,
      ingested_reparsed_count: 3,
      reparsed: [], skipped: [], failed: [], average_confidence: 0.90, total_event_count: 100,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /parse \/ reparse all/i }));
    await userEvent.click(screen.getByRole('button', { name: /parse \/ reparse all/i }));

    const checkbox = screen.getByRole('checkbox', { name: /include already-ingested logs/i });
    await userEvent.click(checkbox);
    await userEvent.click(screen.getByRole('button', { name: /run parse \/ reparse/i }));

    await waitFor(() => {
      expect(screen.getByText(/already-ingested logs reparsed: 3/i)).toBeInTheDocument();
    });
  });

  it('ingest modal has unchecked "Re-ingest already-ingested eligible logs" checkbox by default', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => {
      const checkbox = screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i });
      expect(checkbox).toBeInTheDocument();
      expect(checkbox).not.toBeChecked();
    });
  });

  it('checking re-ingest checkbox shows replacement warning', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));
    const checkbox = screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i });
    await userEvent.click(checkbox);

    await waitFor(() => {
      expect(screen.getByText(/existing observed memory items.*will be replaced/i)).toBeInTheDocument();
    });
  });

  it('checking re-ingest sends include_already_ingested=true for preview', async () => {
    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));
    const checkbox = screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i });
    await userEvent.click(checkbox);

    await waitFor(() => {
      expect(bulkPreviewEligible as ReturnType<typeof vi.fn>).toHaveBeenLastCalledWith({ include_already_ingested: true });
    });
  });

  it('ingest run sends include_already_ingested=true when checkbox is checked', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 2, eligible_count: 0, eligible_for_reingest_count: 1,
      ineligible_count: 0, already_ingested_count: 0, not_ready_count: 0,
      estimated_memory_item_count: 5,
      eligible_logs: [{ log_id: 'x1', filename: 'x1.txt', status: 'eligible_for_reingest', blocker_reasons: [] }],
      skipped_logs: [], top_blocker_reasons: [],
    });
    (bulkIngestEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 2, eligible_count: 1, ingested_count: 0, reingested_count: 1,
      skipped_count: 1, failed_count: 0, memory_items_created: 5,
      ingested_logs: [{ log_id: 'x1', filename: 'x1.txt', status: 'reingested', memory_item_count: 5 }],
      skipped_logs: [], failed_logs: [],
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));
    await userEvent.click(screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));

    await waitFor(() => screen.getByRole('button', { name: /ingest\/re-ingest/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest\/re-ingest/i }));

    await waitFor(() => {
      expect(bulkIngestEligible as ReturnType<typeof vi.fn>).toHaveBeenCalledWith({ include_already_ingested: true });
    });
  });

  it('ingest result shows reingested count separately when non-zero', async () => {
    (bulkPreviewEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, eligible_count: 1, eligible_for_reingest_count: 1,
      ineligible_count: 0, already_ingested_count: 0, not_ready_count: 0,
      estimated_memory_item_count: 10,
      eligible_logs: [], skipped_logs: [], top_blocker_reasons: [],
    });
    (bulkIngestEligible as ReturnType<typeof vi.fn>).mockResolvedValue({
      considered_count: 3, eligible_count: 2, ingested_count: 1, reingested_count: 1,
      skipped_count: 1, failed_count: 0, memory_items_created: 10,
      ingested_logs: [], skipped_logs: [], failed_logs: [],
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest all eligible/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest all eligible/i }));

    await waitFor(() => screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));
    await userEvent.click(screen.getByRole('checkbox', { name: /re-ingest already-ingested eligible logs/i }));
    await waitFor(() => screen.getByRole('button', { name: /ingest\/re-ingest/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest\/re-ingest/i }));

    await waitFor(() => {
      expect(screen.getByText('Re-ingested')).toBeInTheDocument();
    });
  });
});

// ── Phase 5.2: Corpus Readiness Scorecard tests ───────────────────────────────

const emptyReadiness = {
  verdict: 'not_ready' as const,
  readiness_score: 0,
  generated_at: '2026-06-01T12:00:00Z',
  review_only: true,
  safety_note: 'This scorecard is read-only. Observed memories are not used by Coach, AI Player, simulator runtime, deck builder, pgvector, Neo4j, match_events, or card_performance.',
  corpus: {
    log_count: 0, parsed_log_count: 0, ingested_log_count: 0,
    not_ingested_log_count: 0, failed_log_count: 0,
    event_count: 0, memory_item_count: 0,
  },
  parser_quality: {
    avg_event_confidence: null, min_log_confidence: null, avg_log_confidence: null,
    unknown_event_count: 0, low_confidence_event_count: 0,
    low_confidence_threshold: 0.80, logs_below_ingestion_threshold: 0,
  },
  card_resolution: {
    card_mention_count: 0, resolved_count: 0, ambiguous_count: 0,
    unresolved_count: 0, critical_unresolved_count: 0,
    top_ambiguous: [], top_unresolved: [],
  },
  memory_quality: {
    avg_memory_confidence: null, low_confidence_memory_item_count: 0,
    ambiguous_reference_item_count: 0, unresolved_reference_item_count: 0,
    memory_type_counts: [], top_quality_flags: [],
  },
  blockers: ['No logs have been parsed. Upload and parse logs before reviewing readiness.'],
  warnings: [],
  recommendations: ['Upload observed-play logs to begin corpus evaluation.'],
};

const readyReadiness = {
  verdict: 'ready' as const,
  readiness_score: 97.5,
  generated_at: '2026-06-01T12:00:00Z',
  review_only: true,
  safety_note: 'This scorecard is read-only.',
  corpus: {
    log_count: 49, parsed_log_count: 49, ingested_log_count: 49,
    not_ingested_log_count: 0, failed_log_count: 0,
    event_count: 10047, memory_item_count: 1234,
  },
  parser_quality: {
    avg_event_confidence: 0.8879, min_log_confidence: 0.81, avg_log_confidence: 0.887,
    unknown_event_count: 0, low_confidence_event_count: 0,
    low_confidence_threshold: 0.80, logs_below_ingestion_threshold: 0,
  },
  card_resolution: {
    card_mention_count: 500, resolved_count: 500, ambiguous_count: 0,
    unresolved_count: 0, critical_unresolved_count: 0,
    top_ambiguous: [], top_unresolved: [],
  },
  memory_quality: {
    avg_memory_confidence: 0.88, low_confidence_memory_item_count: 0,
    ambiguous_reference_item_count: 0, unresolved_reference_item_count: 0,
    memory_type_counts: [{ memory_type: 'attack_used', count: 600 }],
    top_quality_flags: [],
  },
  blockers: [], warnings: [], recommendations: [],
};

const needsReviewReadiness = {
  ...readyReadiness,
  verdict: 'needs_review' as const,
  readiness_score: 72.0,
  warnings: ['10 ambiguous card mention(s).'],
  card_resolution: { ...readyReadiness.card_resolution, ambiguous_count: 10 },
};

describe('Phase 5.2 — Corpus Readiness Scorecard', () => {
  it('renders the scorecard section on /observed-play', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('corpus-scorecard-section')).toBeInTheDocument();
    });
  });

  it('renders the safety note', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('scorecard-safety-note')).toBeInTheDocument();
    });
  });

  it('renders ready verdict badge', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText(/ready for limited downstream experimentation/i)).toBeInTheDocument();
    });
  });

  it('renders needs_review verdict badge', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(needsReviewReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText(/needs review/i)).toBeInTheDocument();
    });
  });

  it('renders not_ready verdict badge for empty corpus', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(emptyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText(/not ready/i)).toBeInTheDocument();
    });
  });

  it('renders the readiness score', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('readiness-score')).toBeInTheDocument();
      expect(screen.getByTestId('readiness-score')).toHaveTextContent('97.5');
    });
  });

  it('renders corpus coverage stats', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText('Corpus Coverage')).toBeInTheDocument();
      expect(screen.getByText('10,047')).toBeInTheDocument();
    });
  });

  it('renders parser quality stats', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText('Parser Quality')).toBeInTheDocument();
      expect(screen.getByText('Unknown events')).toBeInTheDocument();
    });
  });

  it('renders card resolution stats', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText('Card Resolution Burden')).toBeInTheDocument();
      expect(screen.getByText('Critical unresolved')).toBeInTheDocument();
    });
  });

  it('renders memory quality stats', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByText('Memory Quality')).toBeInTheDocument();
      expect(screen.getByText('Avg memory confidence')).toBeInTheDocument();
    });
  });

  it('renders blockers when present', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(emptyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('scorecard-blockers')).toBeInTheDocument();
      expect(screen.getByText(/No logs have been parsed/i)).toBeInTheDocument();
    });
  });

  it('renders warnings when present', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(needsReviewReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('scorecard-warnings')).toBeInTheDocument();
    });
  });

  it('renders recommendations when present', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(emptyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('scorecard-recommendations')).toBeInTheDocument();
    });
  });

  it('renders error state on API failure', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'));
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('scorecard-error')).toBeInTheDocument();
    });
  });

  it('refresh button calls getCorpusReadiness again', async () => {
    (getCorpusReadiness as ReturnType<typeof vi.fn>).mockResolvedValue(readyReadiness);
    setup();
    await waitFor(() => {
      expect(screen.getByTestId('corpus-scorecard-section')).toBeInTheDocument();
    });
    const refreshBtn = screen.getByRole('button', { name: /refresh scorecard/i });
    expect(refreshBtn).toBeInTheDocument();
    await userEvent.click(refreshBtn);
    await waitFor(() => {
      expect(getCorpusReadiness).toHaveBeenCalledTimes(2);
    });
  });

  it('scorecard section has dark-mode classes', async () => {
    setup();
    await waitFor(() => {
      const section = screen.getByTestId('corpus-scorecard-section');
      expect(section.className).toMatch(/dark:/);
    });
  });

  it('existing memory analytics section still renders', async () => {
    setup();
    await waitFor(() => {
      expect(screen.getByText('Memory Analytics')).toBeInTheDocument();
    });
  });

  // ── Phase 6.0: Coach Evidence Preview ──────────────────────────────────────

  describe('CoachEvidenceSection', () => {
    it('renders the Coach Evidence Preview panel', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByText('Coach Evidence Preview')).toBeInTheDocument();
      });
    });

    it('renders the review-only safety note', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByText(/review-only advisory evidence/i)).toBeInTheDocument();
      });
    });

    it('renders the search form fields', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByPlaceholderText(/dragapult ex/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText(/attack_used/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText(/phantom dive/i)).toBeInTheDocument();
      });
    });

    it('renders the Search / Refresh button', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument();
      });
    });

    it('renders empty state after default load', async () => {
      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));
      await waitFor(() => {
        expect(screen.getByText(/no matching evidence found/i)).toBeInTheDocument();
      });
    });

    it('calls getCoachEvidence with card_name filter on search', async () => {
      const user = userEvent.setup();
      setup();
      await waitFor(() => expect(screen.getByPlaceholderText(/dragapult ex/i)).toBeInTheDocument());

      const input = screen.getByPlaceholderText(/dragapult ex/i);
      await user.clear(input);
      await user.type(input, 'Charizard ex');

      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));
      await waitFor(() => {
        expect(getCoachEvidence).toHaveBeenCalledWith(expect.objectContaining({
          card_name: 'Charizard ex',
        }));
      });
    });

    it('renders evidence summary when items are returned', async () => {
      (getCoachEvidence as ReturnType<typeof vi.fn>).mockResolvedValue({
        review_only: true,
        query: { card_name: 'Dragapult ex', memory_type: null, action_name: null, player_alias: null, min_confidence: 0.80, limit: 25 },
        summary: {
          matching_item_count: 42,
          avg_confidence: 0.91,
          memory_type_counts: [{ memory_type: 'attack_used', count: 12 }],
          top_actors: [],
          top_targets: [],
          top_actions: [],
        },
        evidence: [],
        warnings: [],
      });

      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByPlaceholderText(/dragapult ex/i)).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));

      await waitFor(() => {
        expect(screen.getByText(/42 matching items/i)).toBeInTheDocument();
      });
    });

    it('renders evidence rows with source details', async () => {
      (getCoachEvidence as ReturnType<typeof vi.fn>).mockResolvedValue({
        review_only: true,
        query: { card_name: null, memory_type: null, action_name: null, player_alias: null, min_confidence: 0.80, limit: 25 },
        summary: {
          matching_item_count: 1,
          avg_confidence: 0.95,
          memory_type_counts: [],
          top_actors: [],
          top_targets: [],
          top_actions: [],
        },
        evidence: [{
          memory_item_id: 'mem-001',
          log_id: 'log-001',
          filename: 'battle_log.md',
          turn_number: 5,
          player_alias: 'player_1',
          memory_type: 'attack_used',
          actor_card_raw: 'Dragapult ex',
          actor_card_def_id: null,
          target_card_raw: 'Salazzle ex',
          target_card_def_id: null,
          related_card_raw: null,
          action_name: 'Phantom Dive',
          damage: 130,
          amount: null,
          confidence_score: 0.95,
          source_event_type: 'attack_used',
          source_raw_line: "Player used Phantom Dive",
          source_link: { log_id: 'log-001', event_id: 68 },
        }],
        warnings: [],
      });

      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));

      await waitFor(() => {
        expect(screen.getByText('attack_used')).toBeInTheDocument();
        expect(screen.getByText('Dragapult ex')).toBeInTheDocument();
        expect(screen.getByText('Phantom Dive')).toBeInTheDocument();
        expect(screen.getByText('battle_log.md')).toBeInTheDocument();
      });
    });

    it('renders needs-review warning from response', async () => {
      (getCoachEvidence as ReturnType<typeof vi.fn>).mockResolvedValue({
        review_only: true,
        query: { card_name: null, memory_type: null, action_name: null, player_alias: null, min_confidence: 0.80, limit: 25 },
        summary: {
          matching_item_count: 0, avg_confidence: null,
          memory_type_counts: [], top_actors: [], top_targets: [], top_actions: [],
        },
        evidence: [],
        warnings: ['Corpus has low parser coverage. Evidence may be incomplete.'],
      });

      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));

      await waitFor(() => {
        expect(screen.getByText(/low parser coverage/i)).toBeInTheDocument();
      });
    });

    it('renders error state on HTTP 409 (corpus not ready)', async () => {
      const err = Object.assign(new Error('Not ready'), {
        response: {
          status: 409,
          data: { message: 'Corpus not ready for evidence retrieval.', blockers: ['No logs ingested.'] },
        },
      });
      (getCoachEvidence as ReturnType<typeof vi.fn>).mockRejectedValue(err);

      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));

      await waitFor(() => {
        expect(screen.getByText(/corpus not ready/i)).toBeInTheDocument();
        expect(screen.getByText(/no logs ingested/i)).toBeInTheDocument();
      });
    });

    it('renders generic error state on non-409 failure', async () => {
      (getCoachEvidence as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'));

      setup();
      const user = userEvent.setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());
      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));

      await waitFor(() => {
        expect(screen.getByText(/failed to load coach evidence/i)).toBeInTheDocument();
      });
    });

    it('min confidence input updates query on search', async () => {
      const user = userEvent.setup();
      setup();
      await waitFor(() => expect(screen.getByRole('button', { name: /search.*refresh/i })).toBeInTheDocument());

      const confInput = screen.getByDisplayValue('0.8');
      await user.clear(confInput);
      await user.type(confInput, '0.95');

      await user.click(screen.getByRole('button', { name: /search.*refresh/i }));
      await waitFor(() => {
        expect(getCoachEvidence).toHaveBeenCalledWith(expect.objectContaining({
          min_confidence: 0.95,
        }));
      });
    });

    it('dark mode classes are present on the section', async () => {
      const { container } = setup();
      await waitFor(() => {
        expect(screen.getByText('Coach Evidence Preview')).toBeInTheDocument();
      });
      const section = container.querySelector('section.mt-8');
      expect(section?.className).toContain('dark:');
    });

    it('existing corpus scorecard tests still pass after Phase 6.0', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Corpus Quality.*Readiness Scorecard/i })).toBeInTheDocument();
      });
    });

    it('existing memory analytics section still passes after Phase 6.0', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByText('Memory Analytics')).toBeInTheDocument();
      });
    });
  });

  // ── Phase 6.1: Coach Context Preview ────────────────────────────────────────

  describe('CoachContextPreviewSection', () => {
    it('renders the Coach Context Preview panel', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Observed Play Coach Context Preview/i })).toBeInTheDocument();
      });
    });

    it('shows safety copy about advisory-only nature', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByText(/advisory only/i)).toBeInTheDocument();
      });
    });

    it('shows disabled state when flag is off and Preview Context clicked', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: false,
        readiness_verdict: null,
        readiness_score: null,
        would_inject: false,
        reason: 'OBSERVED_PLAY_MEMORY_ENABLED is false',
        prompt_block: '',
        evidence_count: 0,
        evidence_ids: [],
        warnings: [],
        filters_applied: { min_confidence: 0.85, limit: 8 },
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(screen.getByText(/OBSERVED_PLAY_MEMORY_ENABLED=false/i)).toBeInTheDocument();
      });
    });

    it('shows disabled message when flag is off', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: false,
        readiness_verdict: null,
        readiness_score: null,
        would_inject: false,
        reason: 'OBSERVED_PLAY_MEMORY_ENABLED is false',
        prompt_block: '',
        evidence_count: 0,
        evidence_ids: [],
        warnings: [],
        filters_applied: {},
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(screen.getByText(/disabled for Coach prompts/i)).toBeInTheDocument();
      });
    });

    it('shows prompt block when enabled and corpus is ready', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: true,
        readiness_verdict: 'ready',
        readiness_score: 97.0,
        would_inject: true,
        reason: 'OBSERVED_PLAY_MEMORY_ENABLED is true; corpus is ready',
        prompt_block: 'OBSERVED PLAY EVIDENCE — REVIEW ONLY\nEvidence:\n1. ...',
        evidence_count: 1,
        evidence_ids: ['abc-123'],
        warnings: [],
        filters_applied: { min_confidence: 0.85, limit: 8 },
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(screen.getByText(/OBSERVED PLAY EVIDENCE/)).toBeInTheDocument();
      });
    });

    it('shows readiness verdict when enabled', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: true,
        readiness_verdict: 'ready',
        readiness_score: 97.0,
        would_inject: true,
        reason: 'OBSERVED_PLAY_MEMORY_ENABLED is true; corpus is ready',
        prompt_block: 'OBSERVED PLAY EVIDENCE — REVIEW ONLY\nEvidence:\n1. ...',
        evidence_count: 1,
        evidence_ids: ['abc-123'],
        warnings: [],
        filters_applied: { min_confidence: 0.85, limit: 8 },
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        const section = screen.getByRole('region', { name: /Coach Context Preview/i });
        expect(within(section).getByText(/Corpus readiness:/i)).toBeInTheDocument();
      });
    });

    it('shows not-ready blockers and no injection when not_ready', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: true,
        readiness_verdict: 'not_ready',
        readiness_score: 10.0,
        would_inject: false,
        reason: 'Corpus is not_ready',
        prompt_block: '',
        evidence_count: 0,
        evidence_ids: [],
        warnings: ['Critical unresolved cards exceed threshold.'],
        filters_applied: {},
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        const section = screen.getByRole('region', { name: /Coach Context Preview/i });
        // The section renders the verdict badge with not_ready (there may be multiple matches)
        const allNotReady = within(section).getAllByText(/not_ready/i);
        expect(allNotReady.length).toBeGreaterThan(0);
        expect(within(section).getByText(/Critical unresolved cards exceed threshold/i)).toBeInTheDocument();
      });
    });

    it('shows needs_review warnings', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: true,
        readiness_verdict: 'needs_review',
        readiness_score: 70.0,
        would_inject: true,
        reason: 'OBSERVED_PLAY_MEMORY_ENABLED is true; corpus is needs_review',
        prompt_block: 'OBSERVED PLAY EVIDENCE — REVIEW ONLY\n...',
        evidence_count: 2,
        evidence_ids: ['x1', 'x2'],
        warnings: ['Low parse coverage for some logs.'],
        filters_applied: { min_confidence: 0.85, limit: 8 },
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(screen.getByText(/Low parse coverage for some logs/i)).toBeInTheDocument();
      });
    });

    it('shows evidence count and IDs when would_inject', async () => {
      (getCoachContextPreview as ReturnType<typeof vi.fn>).mockResolvedValue({
        enabled: true,
        readiness_verdict: 'ready',
        readiness_score: 97.0,
        would_inject: true,
        reason: 'enabled',
        prompt_block: 'OBSERVED PLAY EVIDENCE — REVIEW ONLY\n...',
        evidence_count: 3,
        evidence_ids: ['id-a', 'id-b', 'id-c'],
        warnings: [],
        filters_applied: {},
      });
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(screen.getByText(/Evidence count:/i)).toBeInTheDocument();
        expect(screen.getByText(/id-a/)).toBeInTheDocument();
      });
    });

    it('calls getCoachContextPreview with filter params', async () => {
      setup();
      const btn = await screen.findByRole('button', { name: /preview context/i });
      await userEvent.click(btn);
      await waitFor(() => {
        expect(getCoachContextPreview).toHaveBeenCalledWith(
          expect.objectContaining({ min_confidence: expect.any(Number), limit: expect.any(Number) }),
        );
      });
    });

    it('renders dark-mode classes on the panel', async () => {
      setup();
      await waitFor(() => {
        const section = screen.getByRole('region', { name: /Coach Context Preview/i });
        expect(section.className).toMatch(/dark:/);
      });
    });

    it('existing Coach Evidence section still passes after Phase 6.1', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Coach Evidence Preview/i })).toBeInTheDocument();
      });
    });

    it('existing Corpus Readiness section still passes after Phase 6.1', async () => {
      setup();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Corpus Quality.*Readiness Scorecard/i })).toBeInTheDocument();
      });
    });
  });
});
