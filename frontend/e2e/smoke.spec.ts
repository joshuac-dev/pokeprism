import { expect, test } from '@playwright/test';

test('app loads with primary navigation', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Simulation Setup' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'New Simulation' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'History' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Memory' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Coverage' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('simulation form renders and validates required opponent deck', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByTestId('simulation-form')).toBeVisible();
  await expect(page.getByTestId('deck-textarea')).toBeVisible();
  await expect(page.getByTestId('simulation-parameters')).toBeVisible();
  await expect(page.getByTestId('opponent-decks')).toBeVisible();

  await page.getByTestId('start-simulation-button').click();

  await expect(page.getByTestId('simulation-error')).toContainText(
    'Full deck mode requires exactly 60 cards',
  );
});

test('invalid full deck input shows card-count error', async ({ page }) => {
  await page.goto('/');

  await page.getByTestId('deck-textarea').fill(`Pokémon: 4
4 Dreepy TWM 128`);
  await page.getByTestId('add-opponent-button').click();
  await page.getByTestId('opponent-deck-textarea-0').fill(`Pokémon: 4
4 Dreepy TWM 128`);
  await page.getByTestId('start-simulation-button').click();

  await expect(page.getByTestId('simulation-error')).toContainText(
    'Full deck mode requires exactly 60 cards',
  );
});
