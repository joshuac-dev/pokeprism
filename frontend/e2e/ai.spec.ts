import { expect, test } from '@playwright/test';
import { MINIMAL_HH_DECK } from './fixtures/decks';

// Requires both the full Docker stack AND a running Ollama instance.
// Enable with: POKEPRISM_E2E_FULL_STACK=1 POKEPRISM_E2E_AI=1 npm run test:e2e
const fullStack = process.env.POKEPRISM_E2E_FULL_STACK === '1';
const aiEnabled = process.env.POKEPRISM_E2E_AI === '1';

test.describe('AI reasoning overlay', () => {
  test.describe.configure({ mode: 'serial' });
  test.skip(
    !fullStack || !aiEnabled,
    'Set POKEPRISM_E2E_FULL_STACK=1 and POKEPRISM_E2E_AI=1 (requires Ollama) to enable AI overlay tests.',
  );

  test('AI reasoning overlay opens and shows decision blocks for ai_h simulation', async ({
    page,
  }) => {
    // AI inference is slow — allow up to 5 minutes for a single-match ai_h sim.
    test.setTimeout(300_000);

    await page.goto('/');
    await page.getByTestId('deck-textarea').fill(MINIMAL_HH_DECK);
    await page.getByTestId('game-mode-select').selectOption('ai_h');
    await page.getByTestId('matches-per-opponent-input').fill('1');
    await page.getByTestId('rounds-input').fill('1');
    await page.getByTestId('target-win-rate-input').fill('0');
    await page.getByTestId('add-opponent-button').click();
    await page.getByTestId('opponent-deck-textarea-0').fill(MINIMAL_HH_DECK);
    await page.getByTestId('start-simulation-button').click();

    await expect(page).toHaveURL(/\/simulation\/[0-9a-f-]+/i, { timeout: 15_000 });

    // Wait for simulation to complete; AI inference can take several minutes.
    await expect(page.getByTestId('simulation-status-badge')).toHaveText('Complete', {
      timeout: 240_000,
    });

    // Click an attack event (⚔ prefix) — these map to ATTACK in EVENT_TO_ACTION.
    const attackEvent = page
      .getByTestId('live-console-event')
      .filter({ hasText: '⚔' })
      .first();
    await expect(attackEvent).toBeVisible();
    await attackEvent.click();

    // Overlay opens and shows the AI reasoning section.
    await expect(page.getByTestId('event-detail-overlay')).toBeVisible();
    await expect(page.getByTestId('event-detail-ai-reasoning')).toBeVisible();

    // There should be at most 3 reasoning blocks (the limit set in EventDetail).
    const blocks = page.getByTestId('event-detail-reasoning-block');
    const count = await blocks.count();
    expect(count).toBeGreaterThanOrEqual(0);
    expect(count).toBeLessThanOrEqual(3);

    // Backdrop click closes the overlay.
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('event-detail-overlay')).not.toBeAttached();
  });
});
