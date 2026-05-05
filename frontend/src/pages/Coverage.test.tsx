import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Coverage from './Coverage';

// ── Global fetch mock ────────────────────────────────────────────────────────

const MOCK_COVERAGE: object = {
  total: 2,
  implemented: 1,
  flat_only: 0,
  missing: 1,
  coverage_pct: 50.0,
  cards: [
    {
      tcgdex_id: 'sv06-130',
      name: 'Dragapult ex',
      set_abbrev: 'TWM',
      set_number: '130',
      category: 'pokemon',
      subcategory: null,
      status: 'implemented',
      missing_effects: [],
      image_url: 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp',
    },
    {
      tcgdex_id: 'sv05-015',
      name: 'Weezing',
      set_abbrev: 'TEF',
      set_number: '15',
      category: 'pokemon',
      subcategory: null,
      status: 'missing',
      missing_effects: ['Wafting Heal'],
      image_url: null,
    },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(MOCK_COVERAGE),
  } as Response));
});

async function renderAndWait() {
  render(
    <MemoryRouter>
      <Coverage />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByTestId('coverage-table')).toBeInTheDocument());
}

describe('Coverage page', () => {
  it('renders the coverage table', async () => {
    await renderAndWait();
    expect(screen.getByTestId('coverage-table')).toBeInTheDocument();
  });

  it('shows summary bar with correct metrics', async () => {
    await renderAndWait();
    expect(screen.getByTestId('coverage-summary')).toHaveTextContent('50%');
  });

  it('renders card names as clickable buttons', async () => {
    await renderAndWait();
    const btns = screen.getAllByTestId('coverage-card-name-btn');
    expect(btns.length).toBeGreaterThanOrEqual(2);
    expect(btns[0].tagName).toBe('BUTTON');
  });

  it('clicking card name with image_url opens modal with image', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    const btns = screen.getAllByTestId('coverage-card-name-btn');
    const dragapultBtn = btns.find(b => b.textContent?.includes('Dragapult ex'))!;
    await user.click(dragapultBtn);

    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();
    expect(screen.getByTestId('card-lightbox-name')).toHaveTextContent('Dragapult ex');
    const img = screen.getByTestId('card-lightbox-image');
    expect(img).toHaveAttribute('src', 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp');
    expect(img).toHaveAttribute('alt', 'Dragapult ex');
    expect(screen.getByTestId('card-lightbox-set')).toHaveTextContent('TWM 130');
    expect(screen.getByTestId('card-lightbox-tcgdex-id')).toHaveTextContent('sv06-130');
  });

  it('clicking card with null image_url opens modal and shows fallback', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    const btns = screen.getAllByTestId('coverage-card-name-btn');
    const weezingBtn = btns.find(b => b.textContent?.includes('Weezing'))!;
    await user.click(weezingBtn);

    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();
    expect(screen.queryByTestId('card-lightbox-image')).not.toBeInTheDocument();
    expect(screen.getByTestId('card-lightbox-no-image')).toHaveTextContent('No card image available.');
  });

  it('missing effects still display in table row', async () => {
    await renderAndWait();
    expect(screen.getByTestId('coverage-table')).toHaveTextContent('Wafting Heal');
  });

  it('Escape key closes the modal', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    await user.click(screen.getAllByTestId('coverage-card-name-btn')[0]);
    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument(),
    );
  });

  it('backdrop click closes the modal', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    await user.click(screen.getAllByTestId('coverage-card-name-btn')[0]);
    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();

    await user.click(screen.getByTestId('card-lightbox'));
    await waitFor(() =>
      expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument(),
    );
  });

  it('close button closes the modal', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    await user.click(screen.getAllByTestId('coverage-card-name-btn')[0]);
    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();

    await user.click(screen.getByTestId('card-lightbox-close'));
    await waitFor(() =>
      expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument(),
    );
  });

  it('search filter still narrows results after modal is added', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    const searchInput = screen.getByPlaceholderText(/Search by name or set/i);
    await user.type(searchInput, 'Dragapult');

    await waitFor(() => {
      const btns = screen.getAllByTestId('coverage-card-name-btn');
      expect(btns).toHaveLength(1);
      expect(btns[0]).toHaveTextContent('Dragapult ex');
    });

    expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument();
  });

  it('sort button does not open modal', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    const sortButtons = screen.getAllByRole('button', { name: /card name|set|category|status/i });
    await user.click(sortButtons[0]);

    expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument();
  });

  it('filter buttons do not open modal', async () => {
    const user = userEvent.setup();
    await renderAndWait();

    const allBtn = screen.getByRole('button', { name: /All/i });
    await user.click(allBtn);

    expect(screen.queryByTestId('card-lightbox')).not.toBeInTheDocument();
  });
});
