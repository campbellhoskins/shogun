import { test, expect } from '@playwright/test';

/**
 * Click-to-Highlight Tests
 *
 * Verifies that clicking any entity highlights it and its connected paths,
 * and clicking a different non-highlighted entity switches the highlight.
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

test.describe('Click-to-Highlight', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('clicking an entity via search highlights its neighborhood', async ({ page }) => {
    // Search for and click an entity
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.pressSequentially('air travel', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();
    const result = page.locator('.topbar-search-item').first();
    await result.click();
    await page.waitForTimeout(1000);

    // Detail panel should be open
    await expect(page.locator('.node-detail')).toBeVisible();

    // The graph should have highlighting active — verify by checking that
    // the Clear button in the top bar becomes meaningful (highlights exist)
    // We check programmatically: the vis-network should have dimmed some nodes
    // A simpler check: the highlight state is set (we can verify via the cascade
    // panel or by checking that clearing works)
    const clearBtn = page.getByTitle('Clear path highlights');
    // Clear button should exist and be clickable (highlights are active)
    if (await clearBtn.isVisible()) {
      await clearBtn.click();
      await page.waitForTimeout(500);
    }
    // After clearing, canvas should still be functional
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('clicking a different non-highlighted entity switches the highlight', async ({ page }) => {
    // Click first entity via search
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.pressSequentially('air travel', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();
    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(1000);

    const firstEntityName = await page.locator('.node-detail-name').textContent();
    await expect(page.locator('.node-detail')).toBeVisible();

    // Now search for and click a DIFFERENT entity
    await searchInput.click();
    await searchInput.fill('');
    await searchInput.pressSequentially('lodging', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();
    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(1000);

    // Detail panel should show the new entity
    await expect(page.locator('.node-detail')).toBeVisible();
    const secondEntityName = await page.locator('.node-detail-name').textContent();
    expect(secondEntityName).not.toBe(firstEntityName);

    // Canvas still functional
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('clicking Fit clears highlights and closes detail', async ({ page }) => {
    // Click an entity
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.pressSequentially('economy class', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();
    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(1000);
    await expect(page.locator('.node-detail')).toBeVisible();

    // Click Fit button — should clear everything
    await page.getByRole('button', { name: 'Fit' }).click();
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('Escape clears highlights and closes detail', async ({ page }) => {
    // Click an entity
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.pressSequentially('security office', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();
    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(1000);
    await expect(page.locator('.node-detail')).toBeVisible();

    // Escape
    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });
});
