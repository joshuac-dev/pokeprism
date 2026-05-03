import { expect, test } from '@playwright/test';
import { MINIMAL_HH_DECK, PARTIAL_DECK_10 } from './fixtures/decks';

const fullStack = process.env.POKEPRISM_E2E_FULL_STACK === '1';

async function startMinimalSimulation(
  page: import('@playwright/test').Page,
  options: { matchesPerOpponent?: string; rounds?: string; targetWinRate?: string } = {},
) {
  await page.goto('/');

  await page.getByTestId('deck-textarea').fill(MINIMAL_HH_DECK);
  await page.getByTestId('matches-per-opponent-input').fill(options.matchesPerOpponent ?? '1');
  await page.getByTestId('rounds-input').fill(options.rounds ?? '1');
  await page.getByTestId('target-win-rate-input').fill(options.targetWinRate ?? '0');
  await page.getByTestId('add-opponent-button').click();
  await page.getByTestId('opponent-deck-textarea-0').fill(MINIMAL_HH_DECK);
  await page.getByTestId('start-simulation-button').click();

  await expect(page).toHaveURL(/\/simulation\/[0-9a-f-]+/i, { timeout: 15_000 });
  await expect(page.getByTestId('simulation-status')).toBeVisible();
  await expect(page.getByTestId('live-console')).toBeVisible();
}

async function completeMinimalSimulation(page: import('@playwright/test').Page): Promise<string> {
  await startMinimalSimulation(page);

  await expect.poll(
    async () => page.getByTestId('live-console-event').count(),
    { timeout: 15_000 },
  ).toBeGreaterThan(0);

  await expect(page.getByTestId('simulation-status-badge')).toHaveText('Complete', {
    timeout: 45_000,
  });

  const match = page.url().match(/\/simulation\/([0-9a-f-]+)/i);
  expect(match?.[1]).toBeTruthy();
  return match![1];
}

function simulationIdFromUrl(page: import('@playwright/test').Page): string {
  const match = page.url().match(/\/simulation\/([0-9a-f-]+)/i);
  expect(match?.[1]).toBeTruthy();
  return match![1];
}

test.describe('full stack browser smoke', () => {
  test.describe.configure({ mode: 'serial' });
  test.skip(!fullStack, 'Set POKEPRISM_E2E_FULL_STACK=1 and run the Docker stack to enable full-stack E2E.');

  test('creates a minimal H/H simulation and streams live events', async ({ page }) => {
    await completeMinimalSimulation(page);
  });

  test('cancels a queued simulation from the live view', async ({ page }) => {
    test.setTimeout(60_000);
    await startMinimalSimulation(page, { matchesPerOpponent: '1000', targetWinRate: '100' });
    const simulationId = simulationIdFromUrl(page);

    try {
      const cancelButton = page.getByTestId('cancel-simulation-button');
      await expect(cancelButton).toBeVisible({ timeout: 15_000 });
      const box = await cancelButton.boundingBox();
      expect(box).toBeTruthy();
      const cancelResponse = page.waitForResponse(
        (response) => response.url().includes('/cancel') && response.status() === 200,
        { timeout: 10_000 },
      );
      await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
      await cancelResponse;
    } catch (error) {
      await page.request.post(`/api/simulations/${simulationId}/cancel`).catch(() => {});
      throw error;
    }

    await expect(page.getByTestId('simulation-status-badge')).toHaveText('Cancelled', {
      timeout: 10_000,
    });
  });

  test('coverage page loads real card coverage data', async ({ page }) => {
    await page.goto('/coverage');

    await expect(page.getByTestId('coverage-summary')).toContainText('100%', { timeout: 15_000 });
    await expect(page.getByTestId('coverage-table')).toBeVisible();
    await expect(page.getByText(/Showing [\d,]+ of [\d,]+ cards/)).toBeVisible();
  });

  test('dashboard charts render for a completed simulation', async ({ page }) => {
    const simulationId = await completeMinimalSimulation(page);

    await page.goto(`/dashboard/${simulationId}`);

    await expect(page.getByTestId('dashboard-grid')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('dashboard-overall-win-rate').locator('svg')).toBeVisible();
    await expect(page.getByTestId('dashboard-win-rate-progress').locator('svg')).toBeVisible();
    await expect(page.getByTestId('dashboard-prize-race').getByRole('application')).toBeVisible();
  });

  test('history list shows completed simulations', async ({ page }) => {
    await completeMinimalSimulation(page);

    await page.goto('/history');

    await expect(page.getByTestId('history-table')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('history-row').first()).toContainText('Complete');
  });

  test('event detail overlay opens and closes on console event click', async ({ page }) => {
    test.setTimeout(60_000);
    await completeMinimalSimulation(page);

    // After completion the live console still shows events — click the first visible one.
    const firstEvent = page.getByTestId('live-console-event').first();
    await expect(firstEvent).toBeVisible({ timeout: 15_000 });
    await firstEvent.click();

    // Overlay panel opens.
    await expect(page.getByTestId('event-detail-overlay')).toBeVisible();
    // H/H mode — AI reasoning section is not rendered at all.
    await expect(page.getByTestId('event-detail-ai-reasoning')).not.toBeAttached();

    // Escape closes the overlay.
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('event-detail-overlay')).not.toBeAttached();
  });

  test('partial deck mode fills deck and starts simulation', async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto('/');

    await page.getByTestId('deck-mode-partial').click();
    await page.getByTestId('deck-textarea').fill(PARTIAL_DECK_10);
    await page.getByTestId('matches-per-opponent-input').fill('1');
    await page.getByTestId('rounds-input').fill('1');
    await page.getByTestId('target-win-rate-input').fill('0');
    await page.getByTestId('add-opponent-button').click();
    await page.getByTestId('opponent-deck-textarea-0').fill(MINIMAL_HH_DECK);
    await page.getByTestId('start-simulation-button').click();

    // DeckBuilder fills the 10-card partial deck and the simulation starts.
    await expect(page).toHaveURL(/\/simulation\/[0-9a-f-]+/i, { timeout: 20_000 });
    await expect(page.getByTestId('simulation-status')).toBeVisible();
    await expect(page.getByTestId('live-console')).toBeVisible();
  });

  test('no-deck mode starts simulation from card pool', async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto('/');

    await page.getByTestId('deck-mode-none').click();
    // Deck textarea is hidden in no-deck mode.
    await expect(page.getByTestId('deck-textarea')).not.toBeAttached();
    await page.getByTestId('matches-per-opponent-input').fill('1');
    await page.getByTestId('rounds-input').fill('1');
    await page.getByTestId('target-win-rate-input').fill('0');
    await page.getByTestId('add-opponent-button').click();
    await page.getByTestId('opponent-deck-textarea-0').fill(MINIMAL_HH_DECK);
    await page.getByTestId('start-simulation-button').click();

    // DeckBuilder builds a full deck from the card pool and the simulation starts.
    await expect(page).toHaveURL(/\/simulation\/[0-9a-f-]+/i, { timeout: 20_000 });
    await expect(page.getByTestId('simulation-status')).toBeVisible();
    await expect(page.getByTestId('live-console')).toBeVisible();
  });

  test('memory page card search returns results', async ({ page }) => {
    await page.goto('/memory');

    await page.getByTestId('memory-search-input').fill('Dreepy');
    await expect(page.getByTestId('memory-search-dropdown')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('memory-search-result').first()).toBeVisible();
  });

  test('memory page loads card profile from search selection', async ({ page }) => {
    // Prior tests in this serial suite have run H/H sims, so Dreepy has card_performance rows.
    await page.goto('/memory');

    await page.getByTestId('memory-search-input').fill('Dreepy');
    await expect(page.getByTestId('memory-search-result').first()).toBeVisible({ timeout: 5_000 });
    await page.getByTestId('memory-search-result').first().click();

    await expect(page.getByTestId('card-profile')).toBeVisible({ timeout: 10_000 });
  });
});
