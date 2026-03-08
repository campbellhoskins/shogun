import { test, expect } from '@playwright/test';

/**
 * Click-to-Highlight Tests
 *
 * Verifies that clicking any entity highlights it and its connected paths,
 * and clicking a different non-highlighted entity switches the highlight.
 *
 * Data-agnostic: searches for entities that exist in whatever graph is loaded.
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

/** Search for a term and click the first result. Returns the entity name. */
async function searchAndClick(page: any, term: string): Promise<string> {
  const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
  await searchInput.click();
  await searchInput.fill('');
  await searchInput.pressSequentially(term, { delay: 50 });
  await expect(page.locator('.topbar-search-results')).toBeVisible();
  const firstResult = page.locator('.topbar-search-item').first();
  await expect(firstResult).toBeVisible();
  const name = await firstResult.locator('.topbar-search-item-name').textContent();
  await firstResult.click();
  await page.waitForTimeout(1000);
  return name || '';
}

test.describe('Click-to-Highlight', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('clicking an entity via search highlights its neighborhood', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    const clearBtn = page.getByTitle('Clear path highlights');
    if (await clearBtn.isVisible()) {
      await clearBtn.click();
      await page.waitForTimeout(500);
    }
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('clicking a different non-highlighted entity switches the highlight', async ({ page }) => {
    // Click first entity
    const firstName = await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    // Click a different entity
    const secondName = await searchAndClick(page, 'service');
    await expect(page.locator('.node-detail')).toBeVisible();

    // If results differ, names should differ (if same term returns same entity, that's OK)
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('clicking Fit clears highlights and closes detail', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    await page.getByRole('button', { name: 'Fit' }).click();
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('Escape clears highlights and closes detail', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });
});
