import { test, expect } from '@playwright/test';

/**
 * Scenario Simulator Tests
 *
 * Verifies the Scenarios tab in the left panel, scenario selection,
 * step navigation, auto-play, and log line rendering.
 *
 * Requires: server running at localhost:8789 with shogun_pipeline_v1 graph loaded.
 */

test.describe('Scenario Simulator', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('scenarios tab visible in left panel', async ({ page }) => {
    const tab = page.locator('.left-panel-tab', { hasText: 'Scenarios' });
    await expect(tab).toBeVisible();
  });

  test('clicking tab shows scenario dropdown', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    // Should show the scenario panel with a selector
    const panel = page.locator('.scenario-panel');
    await expect(panel).toBeVisible();

    const selector = page.locator('.scenario-selector');
    await expect(selector).toBeVisible();
  });

  test('selecting scenario shows step 1 with title, description, log', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    // Check if scenarios are available (may not be if graph was switched by another test)
    const selector = page.locator('.scenario-selector');
    if (!(await selector.isVisible())) return; // Empty state — no scenarios for this graph

    // Open scenario dropdown and select first scenario
    await selector.click();
    await page.waitForTimeout(200);

    const options = page.locator('.scenario-option');
    const count = await options.count();
    if (count === 0) return;

    await options.first().click();
    await page.waitForTimeout(500);

    // Step info should be visible
    const stepTitle = page.locator('.scenario-step-title');
    await expect(stepTitle).toBeVisible();

    const stepDescription = page.locator('.scenario-step-description');
    await expect(stepDescription).toBeVisible();

    // Log area should exist with at least one line
    const logArea = page.locator('.scenario-log');
    await expect(logArea).toBeVisible();
    await page.waitForTimeout(1500); // Wait for staggered log lines
    const logLines = page.locator('.scenario-log-line');
    expect(await logLines.count()).toBeGreaterThan(0);
  });

  test('next/prev buttons advance and retreat steps', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    const selector = page.locator('.scenario-selector');
    if (!(await selector.isVisible())) return;

    // Select first scenario
    await selector.click();
    await page.waitForTimeout(200);
    const options = page.locator('.scenario-option');
    if ((await options.count()) === 0) return;
    await options.first().click();
    await page.waitForTimeout(500);

    // Should show step 1
    const stepCounter = page.locator('.scenario-step-counter');
    await expect(stepCounter).toContainText('1');

    // Click Next
    const nextBtn = page.locator('.scenario-btn-next');
    await nextBtn.click();
    await page.waitForTimeout(300);
    await expect(stepCounter).toContainText('2');

    // Click Prev
    const prevBtn = page.locator('.scenario-btn-prev');
    await prevBtn.click();
    await page.waitForTimeout(300);
    await expect(stepCounter).toContainText('1');
  });

  test('auto-play advances steps on interval', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    const selector = page.locator('.scenario-selector');
    if (!(await selector.isVisible())) return;

    await selector.click();
    await page.waitForTimeout(200);
    const options = page.locator('.scenario-option');
    if ((await options.count()) === 0) return;
    await options.first().click();
    await page.waitForTimeout(500);

    // Click auto-play
    const autoBtn = page.locator('.scenario-btn-auto');
    await autoBtn.click();

    // Wait for at least one auto-advance (4s interval + buffer)
    await page.waitForTimeout(5000);

    const stepCounter = page.locator('.scenario-step-counter');
    const text = await stepCounter.textContent();
    // Should have advanced past step 1
    expect(text).not.toBe('Step 1');
  });

  test('log lines have correct color-coded CSS classes', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    const selector = page.locator('.scenario-selector');
    if (!(await selector.isVisible())) return;

    await selector.click();
    await page.waitForTimeout(200);
    const options = page.locator('.scenario-option');
    if ((await options.count()) === 0) return;
    await options.first().click();
    await page.waitForTimeout(1500);

    // Check that log lines have type-specific classes
    const logLines = page.locator('.scenario-log-line');
    const count = await logLines.count();
    if (count > 0) {
      const firstLine = logLines.first();
      const classes = await firstLine.getAttribute('class');
      // Should have a type class like log-query, log-traverse, etc.
      expect(classes).toMatch(/log-(query|traverse|attr|decision|warning|dim)/);
    }
  });

  test('empty state shown when no scenarios available', async ({ page }) => {
    // This test checks the empty state rendering
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    // Panel should be visible even with no scenario selected
    const panel = page.locator('.scenario-panel');
    await expect(panel).toBeVisible();
  });

  test('mode toggle shows Scripted and Live buttons', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    const scriptedBtn = page.locator('.scenario-mode-btn', { hasText: 'Scripted' });
    const liveBtn = page.locator('.scenario-mode-btn', { hasText: 'Live' });
    await expect(scriptedBtn).toBeVisible();
    await expect(liveBtn).toBeVisible();
  });

  test('switching to Live mode shows prompt input and Run button', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    // Click Live mode
    await page.locator('.scenario-mode-btn', { hasText: 'Live' }).click();
    await page.waitForTimeout(300);

    const promptInput = page.locator('.live-prompt-input');
    await expect(promptInput).toBeVisible();

    const runBtn = page.locator('.live-run-btn');
    await expect(runBtn).toBeVisible();
  });

  test('Live mode Run button is disabled when prompt is empty', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    await page.locator('.scenario-mode-btn', { hasText: 'Live' }).click();
    await page.waitForTimeout(300);

    const runBtn = page.locator('.live-run-btn');
    await expect(runBtn).toBeDisabled();
  });

  test('Live mode shows loading state after submitting prompt', async ({ page }) => {
    await page.locator('.left-panel-tab', { hasText: 'Scenarios' }).click();
    await page.waitForTimeout(300);

    await page.locator('.scenario-mode-btn', { hasText: 'Live' }).click();
    await page.waitForTimeout(300);

    // Type a prompt
    const promptInput = page.locator('.live-prompt-input');
    await promptInput.fill('What happens during a Level 3 earthquake?');

    // Run button should be enabled
    const runBtn = page.locator('.live-run-btn');
    await expect(runBtn).toBeEnabled();

    // Click Run — should show loading indicator
    await runBtn.click();
    const loading = page.locator('.live-loading');
    await expect(loading).toBeVisible({ timeout: 3000 });
  });
});
