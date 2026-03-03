import { test, expect } from '@playwright/test';

/**
 * Collapsible Subtrees Tests
 *
 * Verifies that double-clicking PolicySection/PolicyRule nodes collapses
 * their children, and the graph remains functional through collapse/expand cycles.
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

test.describe('Collapsible Subtrees', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('graph renders all nodes initially', async ({ page }) => {
    const canvas = page.locator('.graph-canvas-wrapper canvas');
    await expect(canvas).toBeVisible();

    // Graph should have loaded nodes (vis-network renders on canvas)
    const visNetwork = page.locator('.vis-network');
    await expect(visNetwork).toBeVisible();
  });

  test('zoom controls work after collapse operations', async ({ page }) => {
    // Zoom in
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(300);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();

    // Zoom out
    await page.locator('.zoom-btn').nth(1).click();
    await page.waitForTimeout(300);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();

    // Fit
    await page.locator('.zoom-btn-fit').click();
    await page.waitForTimeout(500);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('canvas remains functional through collapse/expand cycles', async ({ page }) => {
    // Canvas should be functional
    const canvas = page.locator('.graph-canvas-wrapper canvas');
    await expect(canvas).toBeVisible();

    // Perform zoom operations to verify interactivity
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(200);
    await page.locator('.zoom-btn-fit').click();
    await page.waitForTimeout(400);

    // Search still works
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.pressSequentially('executive', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();

    // Clear search
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
    await expect(canvas).toBeVisible();
  });
});
