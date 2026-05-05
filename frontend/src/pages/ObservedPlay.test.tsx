import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
}));

import {
  uploadObservedPlayLog,
  listObservedPlayBatches,
  listObservedPlayLogs,
  getObservedPlayLog,
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

  it('shows parser/memory inactive note', async () => {
    setup();
    await waitFor(() => {
      expect(
        screen.getByText(/raw archive only/i),
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
});
