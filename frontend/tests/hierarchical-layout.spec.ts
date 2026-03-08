import { test, expect } from '@playwright/test';

/**
 * Graph Layout + Type System Tests
 *
 * Verifies the graph renders, the legend shows grouped entity types,
 * and existing interactions (zoom, search, detail panel) still work.
 *
 * Data-agnostic: works with any loaded graph (policy pipeline or LangChain baseline).
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

test.describe('Graph Layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('graph renders with vis-network canvas', async ({ page }) => {
    const canvas = page.locator('.graph-canvas-wrapper canvas');
    await expect(canvas).toBeVisible();
  });

  test('legend shows grouped entity types with group headers', async ({ page }) => {
    const legend = page.locator('.legend');
    await expect(legend).toBeVisible();

    const groupHeaders = page.locator('.legend-group-header');
    const headerCount = await groupHeaders.count();
    expect(headerCount).toBeGreaterThanOrEqual(1);
  });

  test('legend contains entity type names from the loaded graph', async ({ page }) => {
    const legend = page.locator('.legend');
    await expect(legend).toBeVisible();

    const legendText = await legend.textContent();
    // The legend should contain at least one recognizable entity type name
    // These cover both the old policy schema and the duty-of-care schema
    const allPossibleTypes = [
      'PolicyRule', 'TravelEvent', 'PolicySection', 'Constraint', 'Requirement',
      'Service', 'Organization', 'SeverityLevel', 'Obligation', 'Incident',
      'Agreement', 'Traveler', 'ContactRole', 'Platform', 'Alert',
    ];
    const foundTypes = allPossibleTypes.filter((t) => legendText?.includes(t));
    expect(foundTypes.length).toBeGreaterThanOrEqual(1);
  });

  test('zoom controls remain functional', async ({ page }) => {
    const controls = page.locator('.zoom-controls');
    await expect(controls).toBeVisible();

    const buttons = controls.locator('.zoom-btn');
    await expect(buttons).toHaveCount(3);

    await buttons.first().click();
    await page.waitForTimeout(300);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();

    await buttons.nth(1).click();
    await page.waitForTimeout(300);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();

    await page.locator('.zoom-btn-fit').click();
    await page.waitForTimeout(500);
    await expect(page.locator('.graph-canvas-wrapper canvas')).toBeVisible();
  });

  test('search and entity detail panel still works', async ({ page }) => {
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    // Use a single common letter to match entities in any graph
    await searchInput.pressSequentially('travel', { delay: 50 });

    await expect(page.locator('.topbar-search-results')).toBeVisible();
    await expect(page.locator('.topbar-search-item').first()).toBeVisible();

    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(800);

    await expect(page.locator('.node-detail')).toBeVisible();
  });
});
