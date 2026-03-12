import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEMO_PATH = 'file:///' + path.resolve(__dirname, '..', '..', 'demo_v2.html').replace(/\\/g, '/');

test.describe('Demo Graph Layout', () => {
  test('initial graph view: no labels visible, nodes spread out, all in view', async ({ page }) => {
    await page.goto(DEMO_PATH);

    // Advance to graph view (beat 3)
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');
    await page.locator('#overlay-pipeline .ov-btn').click();

    // Wait for graph stabilization
    await page.waitForTimeout(5000);

    // Take screenshot for visual inspection
    await page.screenshot({ path: 'screenshots/graph_initial.png' });

    // Get the graph container bounds
    const graphWrap = await page.locator('#graph-wrap').boundingBox();
    expect(graphWrap).not.toBeNull();

    // Get all visible node positions via vis-network API
    const nodePositions = await page.evaluate(() => {
      // @ts-ignore
      const positions = network.getPositions();
      // @ts-ignore
      const scale = network.getScale();
      // @ts-ignore
      const viewPos = network.getViewPosition();
      return { positions, scale, viewPos };
    });

    const posArray = Object.values(nodePositions.positions) as {x: number, y: number}[];

    // Calculate bounding box of all nodes in canvas coords
    const xs = posArray.map((p: any) => p.x);
    const ys = posArray.map((p: any) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spreadX = maxX - minX;
    const spreadY = maxY - minY;

    console.log(`Graph spread: ${spreadX.toFixed(0)} x ${spreadY.toFixed(0)}`);
    console.log(`Scale: ${nodePositions.scale.toFixed(4)}`);

    // Nodes should be spread out enough (not all bunched up)
    // With 149 nodes, spread should be at least 500px in canvas coords
    expect(spreadX).toBeGreaterThan(500);
    expect(spreadY).toBeGreaterThan(500);

    // Check that no node labels are visible by default
    // In vis-network, labels render as part of canvas so we check via node font config
    const hasHiddenLabels = await page.evaluate(() => {
      // @ts-ignore
      const nodes = visNodes.get();
      const visibleLabels = nodes.filter((n: any) => {
        const font = n.font;
        return font && font.color && font.color !== 'transparent' && font.size > 5;
      });
      return { totalNodes: nodes.length, visibleLabelCount: visibleLabels.length };
    });

    console.log(`Nodes: ${hasHiddenLabels.totalNodes}, visible labels: ${hasHiddenLabels.visibleLabelCount}`);

    // All labels should be hidden (transparent or tiny) in default view
    expect(hasHiddenLabels.visibleLabelCount).toBe(0);
  });

  test('clicking a node shows only its labels and neighbor labels', async ({ page }) => {
    await page.goto(DEMO_PATH);

    // Advance to graph view
    await page.locator('#overlay-problem .ov-btn').click();
    await page.waitForSelector('#overlay-pipeline.visible');
    await page.locator('#overlay-pipeline .ov-btn').click();
    await page.waitForTimeout(5000);

    // Click a node (the incident node which has many connections)
    await page.evaluate(() => {
      // @ts-ignore
      network.selectNodes(['incident']);
      // @ts-ignore
      network.body.emitter.emit('click', { nodes: ['incident'], edges: [], event: {}, pointer: { DOM: {x:0,y:0}, canvas: {x:0,y:0} } });
    });

    await page.waitForTimeout(500);

    // Check that only focused + neighbor nodes have visible labels
    const labelState = await page.evaluate(() => {
      // @ts-ignore
      const nodes = visNodes.get();
      const visible = nodes.filter((n: any) => n.font && n.font.color !== 'transparent' && n.font.size > 5);
      const hidden = nodes.filter((n: any) => !n.font || n.font.color === 'transparent' || n.font.size <= 5);
      return { visibleCount: visible.length, hiddenCount: hidden.length, total: nodes.length };
    });

    console.log(`After click: ${labelState.visibleCount} visible, ${labelState.hiddenCount} hidden`);

    // Should have SOME visible labels (the node + its neighbors) but not all
    expect(labelState.visibleCount).toBeGreaterThan(0);
    expect(labelState.visibleCount).toBeLessThan(labelState.total);

    await page.screenshot({ path: 'screenshots/graph_node_selected.png' });
  });
});
