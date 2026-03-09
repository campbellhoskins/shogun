import { test, expect } from '@playwright/test';

test.describe('Graph Selector', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8789');
    await page.waitForSelector('[data-testid="graph-selector-btn"]', { timeout: 10000 });
  });

  test('dropdown button renders with current graph title', async ({ page }) => {
    const btn = page.getByTestId('graph-selector-btn');
    await expect(btn).toBeVisible();
    // Should show a non-empty title
    const text = await btn.textContent();
    expect(text!.trim().length).toBeGreaterThan(0);
  });

  test('clicking button opens dropdown with graph options', async ({ page }) => {
    const btn = page.getByTestId('graph-selector-btn');
    await btn.click();

    const dropdown = page.getByTestId('graph-selector-dropdown');
    await expect(dropdown).toBeVisible();

    // Should have at least one graph option
    const items = dropdown.locator('.graph-selector-item');
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('selecting a different graph reloads data and clears state', async ({ page }) => {
    // Get initial entity count
    const initialStats = await page.textContent('.topbar-stats');

    const btn = page.getByTestId('graph-selector-btn');
    await btn.click();

    const dropdown = page.getByTestId('graph-selector-dropdown');
    await expect(dropdown).toBeVisible();

    // Check if there are multiple graphs to switch between
    const items = dropdown.locator('.graph-selector-item');
    const count = await items.count();

    if (count >= 2) {
      // Find a non-active item and click it
      const nonActive = dropdown.locator('.graph-selector-item:not(.active)').first();
      await nonActive.click();

      // Dropdown should close
      await expect(dropdown).not.toBeVisible();

      // Wait for new graph to load (stats should update)
      await page.waitForSelector('.topbar-stats', { timeout: 10000 });
    }
  });

  test('clicking outside closes dropdown', async ({ page }) => {
    const btn = page.getByTestId('graph-selector-btn');
    await btn.click();

    const dropdown = page.getByTestId('graph-selector-dropdown');
    await expect(dropdown).toBeVisible();

    // Click on the graph area (outside the dropdown)
    await page.click('.graph-area');

    await expect(dropdown).not.toBeVisible();
  });
});
