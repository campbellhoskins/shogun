import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEMO_PATH = 'file:///' + path.resolve(__dirname, '..', '..', 'demo_v2.html').replace(/\\/g, '/');

test.describe('Scenario Edge Labels', () => {
  test('revealed edges show relationship type labels during scenario steps', async ({ page }) => {
    await page.goto(DEMO_PATH);

    // Advance to graph view
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');
    await page.locator('#overlay-pipeline .ov-btn').click();
    await page.waitForTimeout(4000);

    // Start scenario 1 (earthquake)
    await page.locator('.scenario-btn').first().click();
    await page.waitForTimeout(1000);

    // Step 0 has edge r64 (ENABLED_BY)
    // Advance to step 1 which has edge r93 (CLASSIFIED_AS)
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);

    // Check that revealed edges have their type as label
    const edgeLabels = await page.evaluate(() => {
      // @ts-ignore
      const edges = visEdges.get();
      const visible = edges.filter((e: any) => !e.hidden && e.label && e.label.length > 0);
      return visible.map((e: any) => ({ id: e.id, label: e.label }));
    });

    console.log('Visible edge labels after step 1:', JSON.stringify(edgeLabels));

    // Should have at least 1 edge from step 1 (step 0 has no edges)
    expect(edgeLabels.length).toBeGreaterThanOrEqual(1);

    // Check that labels are actual relationship types (not empty strings)
    for (const e of edgeLabels) {
      expect(e.label.length).toBeGreaterThan(0);
      // Relationship types are uppercase with underscores
      expect(e.label).toMatch(/^[A-Z_]+$/);
    }

    // Verify specific expected label
    const labels = edgeLabels.map((e: any) => e.label);
    expect(labels).toContain('CLASSIFIED_AS'); // r93 from step 1

    // Advance a few more steps and verify labels keep appearing
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);

    const moreLabels = await page.evaluate(() => {
      // @ts-ignore
      const edges = visEdges.get();
      return edges.filter((e: any) => !e.hidden && e.label && e.label.length > 0)
        .map((e: any) => e.label);
    });

    console.log(`After step 3: ${moreLabels.length} labeled edges:`, moreLabels);
    expect(moreLabels.length).toBeGreaterThan(edgeLabels.length);
  });
});
