import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CardImageLightbox from './CardImageLightbox';
import type { CardImageLightboxCard } from './CardImageLightbox';

// Base URL (no extension) — lightbox must normalize to /high.webp
const CARD_WITH_IMAGE: CardImageLightboxCard = {
  name: 'Dragapult ex',
  tcgdex_id: 'sv06-130',
  set_abbrev: 'TWM',
  set_number: '130',
  category: 'pokemon',
  subcategory: null,
  image_url: 'https://assets.tcgdex.net/en/sv/sv06/130',
  status: 'implemented',
  missing_effects: [],
};

// Already-normalized URL — must NOT double-append
const CARD_ALREADY_NORMALIZED: CardImageLightboxCard = {
  ...CARD_WITH_IMAGE,
  image_url: 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp',
};

// PNG URL — must remain unchanged
const CARD_PNG: CardImageLightboxCard = {
  ...CARD_WITH_IMAGE,
  image_url: 'https://example.com/card.png',
};

const CARD_WITHOUT_IMAGE: CardImageLightboxCard = {
  name: 'Weezing',
  tcgdex_id: 'sv05-015',
  set_abbrev: 'TEF',
  set_number: '15',
  category: 'pokemon',
  subcategory: null,
  image_url: null,
  status: 'missing',
  missing_effects: ['Wafting Heal'],
};

describe('CardImageLightbox', () => {
  it('normalizes a bare TCGDex base URL to /high.webp', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);

    const img = screen.getByTestId('card-lightbox-image');
    expect(img).toHaveAttribute('src', 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp');
    expect(img).toHaveAttribute('alt', 'Dragapult ex');
  });

  it('does not double-append /high.webp on an already-normalized URL', () => {
    render(<CardImageLightbox card={CARD_ALREADY_NORMALIZED} onClose={vi.fn()} />);

    const img = screen.getByTestId('card-lightbox-image');
    expect(img).toHaveAttribute('src', 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp');
  });

  it('leaves .png URLs unchanged', () => {
    render(<CardImageLightbox card={CARD_PNG} onClose={vi.fn()} />);

    const img = screen.getByTestId('card-lightbox-image');
    expect(img).toHaveAttribute('src', 'https://example.com/card.png');
  });

  it('renders the dialog with card name', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);

    expect(screen.getByTestId('card-lightbox')).toBeInTheDocument();
    expect(screen.getByTestId('card-lightbox-name')).toHaveTextContent('Dragapult ex');
  });

  it('shows set label and tcgdex_id', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);

    expect(screen.getByTestId('card-lightbox-set')).toHaveTextContent('TWM 130');
    expect(screen.getByTestId('card-lightbox-tcgdex-id')).toHaveTextContent('sv06-130');
  });

  it('shows status label for implemented card', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);
    expect(screen.getByTestId('card-lightbox-status')).toHaveTextContent('Implemented');
  });

  it('shows "No card image available." when image_url is null', () => {
    render(<CardImageLightbox card={CARD_WITHOUT_IMAGE} onClose={vi.fn()} />);

    expect(screen.queryByTestId('card-lightbox-image')).not.toBeInTheDocument();
    expect(screen.getByTestId('card-lightbox-no-image')).toHaveTextContent('No card image available.');
  });

  it('shows missing effects for a missing-handler card', () => {
    render(<CardImageLightbox card={CARD_WITHOUT_IMAGE} onClose={vi.fn()} />);
    expect(screen.getByTestId('card-lightbox-missing')).toHaveTextContent('Wafting Heal');
  });

  it('does not show missing-effects section when there are none', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);
    expect(screen.queryByTestId('card-lightbox-missing')).not.toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={onClose} />);

    await user.click(screen.getByTestId('card-lightbox-close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onClose when backdrop is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={onClose} />);

    await user.click(screen.getByTestId('card-lightbox'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does NOT call onClose when the inner content panel is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={onClose} />);

    await user.click(screen.getByTestId('card-lightbox-name'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('calls onClose on Escape key', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={onClose} />);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('has role=dialog and aria-modal on backdrop', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('close button has aria-label="Close card preview"', () => {
    render(<CardImageLightbox card={CARD_WITH_IMAGE} onClose={vi.fn()} />);
    expect(screen.getByLabelText('Close card preview')).toBeInTheDocument();
  });
});
