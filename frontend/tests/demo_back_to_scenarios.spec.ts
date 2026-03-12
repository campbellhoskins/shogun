import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEMO_PATH = 'file:///' + path.resolve(__dirname, '..', '..', 'demo_v2.html').replace(/\\/g, '/');

test.describe('Back to Scenarios', () => {
  test('graph state after returning from scenario matches initial state', async ({ page }) => {
    await page.goto(DEMO_PATH);

    // Advance to graph view
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');
    await page.locator('#overlay-pipeline .ov-btn').click();
    await page.waitForTimeout(5000);

    // Capture initial graph state
    await page.screenshot({ path: 'screenshots/01_initial.png' });
    const initialState = await page.evaluate(() => {
      // @ts-ignore
      const nodes = visNodes.get();
      const edges = visEdges.get();
      const hiddenNodes = nodes.filter((n: any) => n.hidden).length;
      const hiddenEdges = edges.filter((e: any) => e.hidden).length;
      const transparentLabels = nodes.filter((n: any) => n.font && n.font.color === 'transparent').length;
      const visibleLabels = nodes.filter((n: any) => n.font && n.font.color !== 'transparent' && n.font.size > 5).length;
      const faintEdges = edges.filter((e: any) => !e.hidden && e.width <= 1).length;
      const highlightedEdges = edges.filter((e: any) => !e.hidden && e.width > 1).length;
      return {
        hiddenNodes, hiddenEdges, transparentLabels, visibleLabels,
        faintEdges, highlightedEdges,
        totalNodes: nodes.length, totalEdges: edges.length,
        // @ts-ignore
        scale: network.getScale(),
        // @ts-ignore
        scenarioMode: scenarioMode,
        // @ts-ignore
        focusedNodeEdgesSize: focusedNodeEdges.size,
        // @ts-ignore
        focusedNeighborIdsSize: focusedNeighborIds.size,
      };
    });
    console.log('INITIAL:', JSON.stringify(initialState, null, 2));

    // Start scenario 1, go through a few steps
    await page.locator('.scenario-btn').first().click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);
    await page.locator('#btn-next').click();
    await page.waitForTimeout(800);

    await page.screenshot({ path: 'screenshots/02_mid_scenario.png' });

    // Go to results
    for (let i = 0; i < 10; i++) {
      const btnText = await page.locator('#btn-next').textContent();
      if (btnText && btnText.includes('Results')) {
        await page.locator('#btn-next').click();
        break;
      }
      await page.locator('#btn-next').click();
      await page.waitForTimeout(400);
    }
    await page.waitForTimeout(800);

    await page.screenshot({ path: 'screenshots/03_results.png' });

    // Click back to scenarios
    await page.locator('#results-footer button').click();
    await page.waitForTimeout(2000);

    await page.screenshot({ path: 'screenshots/04_after_back.png' });

    // Capture state after returning
    const afterState = await page.evaluate(() => {
      // @ts-ignore
      const nodes = visNodes.get();
      const edges = visEdges.get();
      const hiddenNodes = nodes.filter((n: any) => n.hidden).length;
      const hiddenEdges = edges.filter((e: any) => e.hidden).length;
      const transparentLabels = nodes.filter((n: any) => n.font && n.font.color === 'transparent').length;
      const visibleLabels = nodes.filter((n: any) => n.font && n.font.color !== 'transparent' && n.font.size > 5).length;
      const faintEdges = edges.filter((e: any) => !e.hidden && e.width <= 1).length;
      const highlightedEdges = edges.filter((e: any) => !e.hidden && e.width > 1).length;
      return {
        hiddenNodes, hiddenEdges, transparentLabels, visibleLabels,
        faintEdges, highlightedEdges,
        totalNodes: nodes.length, totalEdges: edges.length,
        // @ts-ignore
        scale: network.getScale(),
        // @ts-ignore
        scenarioMode: scenarioMode,
        // @ts-ignore
        focusedNodeEdgesSize: focusedNodeEdges.size,
        // @ts-ignore
        focusedNeighborIdsSize: focusedNeighborIds.size,
      };
    });
    console.log('AFTER BACK:', JSON.stringify(afterState, null, 2));

    // Verify state matches initial
    expect(afterState.scenarioMode).toBe(false);
    expect(afterState.hiddenNodes).toBe(initialState.hiddenNodes);
    expect(afterState.visibleLabels).toBe(initialState.visibleLabels);
    expect(afterState.transparentLabels).toBe(initialState.transparentLabels);
    expect(afterState.hiddenEdges).toBe(initialState.hiddenEdges);
    expect(afterState.focusedNodeEdgesSize).toBe(0);
    expect(afterState.focusedNeighborIdsSize).toBe(0);

    // Test that clicking a node still works correctly after returning
    await page.evaluate(() => {
      // @ts-ignore
      network.selectNodes(['incident']);
      // @ts-ignore
      network.body.emitter.emit('click', { nodes: ['incident'], edges: [], event: {}, pointer: { DOM: {x:0,y:0}, canvas: {x:0,y:0} } });
    });
    await page.waitForTimeout(1000);

    await page.screenshot({ path: 'screenshots/05_click_after_back.png' });

    const clickState = await page.evaluate(() => {
      // @ts-ignore
      const nodes = visNodes.get();
      const visible = nodes.filter((n: any) => n.font && n.font.color !== 'transparent' && n.font.size > 5).length;
      const dimmed = nodes.filter((n: any) => n.opacity < 0.2).length;
      return { visibleLabels: visible, dimmedNodes: dimmed };
    });
    console.log('AFTER CLICK:', JSON.stringify(clickState));

    // Should have some visible labels (focused + neighbors) and dimmed nodes
    expect(clickState.visibleLabels).toBeGreaterThan(0);
    expect(clickState.visibleLabels).toBeLessThan(149);
    expect(clickState.dimmedNodes).toBeGreaterThan(0);
  });
});
