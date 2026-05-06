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

    await userEvent.click(screen.getAllByRole('button', { name: /reparse/i })[0]);

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

  it('shows "Ingest memory" button for parsed logs', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10, confidence_score: 0.9 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /ingest memory/i })).toBeInTheDocument();
    });
  });

  it('shows "Re-ingest" button for already-ingested logs', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 5 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /re-ingest/i })).toBeInTheDocument();
    });
  });

  it('shows "View memory" button for logs with memory items', async () => {
    const ingestedLog = { ...sampleLog, parse_status: 'parsed', memory_status: 'ingested', memory_item_count: 3 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [ingestedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /view memory/i })).toBeInTheDocument();
    });
  });

  it('clicking "Ingest memory" opens the MemoryPreviewModal', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed', event_count: 10, confidence_score: 0.9 };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest memory/i }));

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /memory ingestion/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/estimated 5 memory items/i)).toBeInTheDocument();
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
    await waitFor(() => screen.getByRole('button', { name: /ingest memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest memory/i }));

    await waitFor(() => {
      expect(screen.getByText(/not eligible/i)).toBeInTheDocument();
      expect(screen.getByText(/low_confidence/i)).toBeInTheDocument();
    });
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
    await waitFor(() => screen.getByRole('button', { name: /view memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /view memory/i }));

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
      expect(screen.getByText(/not used by coach or ai player/i)).toBeInTheDocument();
    });
  });

  it('MemoryPreviewModal shows safety copy about Coach/AI', async () => {
    const parsedLog = { ...sampleLog, parse_status: 'parsed' };
    (listObservedPlayLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [parsedLog], total: 1, page: 1, per_page: 25,
    });

    setup();
    await waitFor(() => screen.getByRole('button', { name: /ingest memory/i }));
    await userEvent.click(screen.getByRole('button', { name: /ingest memory/i }));

    await waitFor(() => {
      const dialog = screen.getByRole('dialog', { name: /memory ingestion/i });
      expect(within(dialog).getByText(/not used by coach or ai player/i)).toBeInTheDocument();
    });
  });
});
