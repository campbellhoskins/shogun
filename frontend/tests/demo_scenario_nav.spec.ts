import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEMO_PATH = 'file:///' + path.resolve(__dirname, '..', '..', 'demo_v2.html').replace(/\\/g, '/');

test.describe('Scenario Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(DEMO_PATH);
    // Advance to graph view
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');
    await page.locator('#overlay-pipeline .ov-btn').click();
    await page.waitForTimeout(4000); // wait for stabilization
    // Start scenario 1
    await page.locator('.scenario-btn').first().click();
    await page.waitForTimeout(1000);
  });

  test('forward through all steps records scale at each step', async ({ page }) => {
    // Step through all steps forward, recording scale at each
    const stepCount = await page.evaluate(() => currentScenario.steps.length);
    console.log(`Scenario has ${stepCount} steps`);

    const scales: number[] = [];
    for (let i = 0; i < stepCount; i++) {
      await page.waitForTimeout(800);
      const scale = await page.evaluate(() => network.getScale());
      const viewPos = await page.evaluate(() => network.getViewPosition());
      const revealed = await page.evaluate(() => revealedNodes.size);
      console.log(`Step ${i}: scale=${scale.toFixed(4)}, pos=(${viewPos.x.toFixed(0)},${viewPos.y.toFixed(0)}), revealed=${revealed}`);
      scales.push(scale);

      if (i < stepCount - 1) {
        await page.locator('#btn-next').click();
      }
    }

    // All scales should be reasonable (> 0.1, not zoomed to infinity)
    for (let i = 0; i < scales.length; i++) {
      expect(scales[i]).toBeGreaterThan(0.05);
      expect(scales[i]).toBeLessThan(5);
    }
  });

  test('prev then next does not corrupt zoom', async ({ page }) => {
    // Go to step 3
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);

    const scaleAtStep3 = await page.evaluate(() => network.getScale());
    console.log(`At step 3: scale=${scaleAtStep3.toFixed(4)}`);

    // Go back to step 2
    await page.locator('#btn-prev').click();
    await page.waitForTimeout(800);
    const scaleAfterPrev = await page.evaluate(() => network.getScale());
    console.log(`After prev to step 2: scale=${scaleAfterPrev.toFixed(4)}`);

    // Go forward again to step 3
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    const scaleAfterNextAgain = await page.evaluate(() => network.getScale());
    console.log(`After next back to step 3: scale=${scaleAfterNextAgain.toFixed(4)}`);

    // Scale should be reasonable, not zoomed way out or in
    expect(scaleAfterPrev).toBeGreaterThan(0.1);
    expect(scaleAfterNextAgain).toBeGreaterThan(0.1);
    expect(scaleAfterPrev).toBeLessThan(5);
    expect(scaleAfterNextAgain).toBeLessThan(5);
  });

  test('rapid prev-next-prev-next does not break zoom', async ({ page }) => {
    // Advance a few steps first
    await page.locator('#btn-next').click();
    await page.waitForTimeout(600);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(600);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(600);

    // Now rapidly toggle prev/next
    for (let i = 0; i < 5; i++) {
      await page.locator('#btn-prev').click();
      await page.waitForTimeout(300);
      await page.locator('#btn-next').click();
      await page.waitForTimeout(300);
    }

    await page.waitForTimeout(1000);

    const finalScale = await page.evaluate(() => network.getScale());
    const revealed = await page.evaluate(() => revealedNodes.size);
    console.log(`After rapid toggle: scale=${finalScale.toFixed(4)}, revealed=${revealed}`);

    await page.screenshot({ path: 'screenshots/scenario_rapid_toggle.png' });

    // Scale should still be reasonable
    expect(finalScale).toBeGreaterThan(0.1);
    expect(finalScale).toBeLessThan(5);
    // Should still have revealed nodes
    expect(revealed).toBeGreaterThan(0);
  });

  test('going backward rebuilds graph correctly', async ({ page }) => {
    // Go to step 4
    for (let i = 0; i < 4; i++) {
      await page.locator('#btn-next').click();
      await page.waitForTimeout(600);
    }
    const revealedAtStep4 = await page.evaluate(() => revealedNodes.size);

    // Go back to step 1
    await page.locator('#btn-prev').click();
    await page.waitForTimeout(600);
    await page.locator('#btn-prev').click();
    await page.waitForTimeout(600);
    await page.locator('#btn-prev').click();
    await page.waitForTimeout(600);

    const revealedAtStep1 = await page.evaluate(() => revealedNodes.size);
    const scale = await page.evaluate(() => network.getScale());

    console.log(`Step 4 had ${revealedAtStep4} revealed, step 1 has ${revealedAtStep1}, scale=${scale.toFixed(4)}`);

    await page.screenshot({ path: 'screenshots/scenario_backward.png' });

    // Step 1 should have fewer revealed nodes than step 4
    expect(revealedAtStep1).toBeLessThan(revealedAtStep4);
    expect(revealedAtStep1).toBeGreaterThan(0);
    expect(scale).toBeGreaterThan(0.1);
    expect(scale).toBeLessThan(5);
  });
});
