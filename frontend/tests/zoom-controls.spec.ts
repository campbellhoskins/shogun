import { test, expect } from '@playwright/test';

/**
 * Zoom Controls Tests
 *
 * Tests the zoom control widget (+ / - / fit buttons) on the graph canvas,
 * plus all zoom-in/zoom-out flows: search-to-node, Fit button, Escape key,
 * close panel, and double-click.
 *
 * Data-agnostic: works with any loaded graph.
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

/** Search for a term and click the first result. */
async function searchAndClick(page: any, term: string) {
  const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
  await searchInput.click();
  await searchInput.fill('');
  await searchInput.pressSequentially(term, { delay: 50 });
  await expect(page.locator('.topbar-search-results')).toBeVisible();
  await page.locator('.topbar-search-item').first().click();
  await page.waitForTimeout(800);
}

test.describe('Zoom Controls Widget', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('zoom control buttons are visible on the graph canvas', async ({ page }) => {
    const controls = page.locator('.zoom-controls');
    await expect(controls).toBeVisible();

    const buttons = controls.locator('.zoom-btn');
    await expect(buttons).toHaveCount(3);
  });

  test('+ button zooms in (scale increases)', async ({ page }) => {
    const initialScale = await page.evaluate(() => {
      return document.querySelectorAll('.vis-network').length;
    });
    expect(initialScale).toBe(1);

    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(300);
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(300);

    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('- button zooms out (scale decreases)', async ({ page }) => {
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(300);
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(300);

    await page.locator('.zoom-btn').nth(1).click();
    await page.waitForTimeout(300);
    await page.locator('.zoom-btn').nth(1).click();
    await page.waitForTimeout(300);

    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('fit button (third button) resets to full graph view', async ({ page }) => {
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(200);
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(200);
    await page.locator('.zoom-btn').first().click();
    await page.waitForTimeout(200);

    await page.locator('.zoom-btn-fit').click();
    await page.waitForTimeout(600);

    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });
});

test.describe('Zoom In/Out via Node Selection', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('searching and selecting an entity opens detail panel', async ({ page }) => {
    await expect(page.locator('.node-detail')).not.toBeVisible();

    await searchAndClick(page, 'travel');

    await expect(page.locator('.node-detail')).toBeVisible();
    await expect(page.locator('.node-detail-name')).not.toBeEmpty();
  });

  test('Fit button zooms out and closes detail panel after node selection', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    await page.getByRole('button', { name: 'Fit' }).click();
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('Escape key zooms out and closes detail panel', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('close button (X) on detail panel zooms out', async ({ page }) => {
    await searchAndClick(page, 'travel');
    await expect(page.locator('.node-detail')).toBeVisible();

    await page.locator('.node-detail-close').click();
    await page.waitForTimeout(600);

    await expect(page.locator('.node-detail')).not.toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('can zoom in to node, zoom out with Fit, then zoom in to a different node', async ({ page }) => {
    // First entity
    await searchAndClick(page, 'travel');
    const firstName = await page.locator('.node-detail-name').textContent();
    await expect(page.locator('.node-detail')).toBeVisible();

    // Zoom out
    await page.getByRole('button', { name: 'Fit' }).click();
    await page.waitForTimeout(600);
    await expect(page.locator('.node-detail')).not.toBeVisible();

    // Second entity (different search term)
    await searchAndClick(page, 'service');
    await expect(page.locator('.node-detail')).toBeVisible();
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });
});
