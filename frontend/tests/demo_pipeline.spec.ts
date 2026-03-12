import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEMO_PATH = 'file:///' + path.resolve(__dirname, '..', '..', 'demo_v2.html').replace(/\\/g, '/');

test.describe('Demo Pipeline Layout', () => {
  test('all 5 pipeline stages are on one horizontal line', async ({ page }) => {
    await page.goto(DEMO_PATH);

    // Advance to beat 2 (pipeline overlay) via button
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');

    // Wait for all stages to animate in
    await page.waitForTimeout(3000);

    // Get all stage elements (6 stages: 0-4 + Final)
    const stages = page.locator('#pipeline-stages .stage');
    await expect(stages).toHaveCount(6);

    // Get bounding boxes of all 5 stages
    const boxes = [];
    for (let i = 0; i < 6; i++) {
      const box = await stages.nth(i).boundingBox();
      expect(box).not.toBeNull();
      boxes.push(box!);
    }

    // All stages should share the same vertical center (same row)
    // Different text lengths cause slight height differences, so compare centers
    // with tolerance. A second row would be 80+ px off.
    const centers = boxes.map(b => b.y + b.height / 2);
    const firstCenter = centers[0];
    for (let i = 1; i < centers.length; i++) {
      expect(Math.abs(centers[i] - firstCenter)).toBeLessThanOrEqual(10);
    }

    // Each stage should be to the right of the previous one (left-to-right order)
    for (let i = 1; i < boxes.length; i++) {
      expect(boxes[i].x).toBeGreaterThan(boxes[i - 1].x);
    }
  });
});
