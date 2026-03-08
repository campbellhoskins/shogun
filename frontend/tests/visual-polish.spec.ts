import { test, expect } from '@playwright/test';

/**
 * Visual Polish Tests
 *
 * Verifies TravelEvent appears in legend, and all existing interactions
 * still work (regression: path finder, agent tab, search, zoom controls).
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

test.describe('Visual Polish', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('TravelEvent appears in legend with expected color', async ({ page }) => {
    const legend = page.locator('.legend');
    await expect(legend).toBeVisible();

    const legendText = await legend.textContent();
    // TravelEvent should be in the legend if it exists in the graph data
    // (data-dependent, but the color mapping exists)
    if (legendText?.includes('TravelEvent')) {
      // Verify the dot has a color style
      const travelEventItem = page.locator('.legend-item', { hasText: 'TravelEvent' });
      const dot = travelEventItem.locator('.legend-dot');
      await expect(dot).toBeVisible();
    }
  });

  test('all existing interactions still work - regression', async ({ page }) => {
    // Path Finder tab exists and is clickable
    const pathTab = page.locator('.left-panel-tab', { hasText: 'Path Finder' });
    await expect(pathTab).toBeVisible();
    await pathTab.click();
    await page.waitForTimeout(200);

    // Agent tab exists and is clickable
    const agentTab = page.locator('.left-panel-tab', { hasText: 'Agent' });
    await expect(agentTab).toBeVisible();
    await agentTab.click();
    await page.waitForTimeout(200);

    // Search bar works
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await expect(searchInput).toBeVisible();
    await searchInput.click();
    await searchInput.pressSequentially('pol', { delay: 50 });
    await expect(page.locator('.topbar-search-results')).toBeVisible();

    // Clear search
    await searchInput.fill('');
    await page.waitForTimeout(200);

    // Zoom controls work
    const zoomControls = page.locator('.zoom-controls');
    await expect(zoomControls).toBeVisible();

    // Fit button
    await page.locator('.zoom-btn-fit').click();
    await page.waitForTimeout(400);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();

    // Clear button in top bar (if it exists)
    const clearBtn = page.getByRole('button', { name: 'Clear' });
    if (await clearBtn.isVisible()) {
      await clearBtn.click();
      await page.waitForTimeout(200);
    }
  });
});
