import { test, expect } from '@playwright/test';

/**
 * Tests that the graph renders with a force-directed layout that spreads
 * nodes across the viewport instead of cramming them into a single column.
 *
 * The old hierarchical LR layout only works for tree-shaped policy data.
 * Non-hierarchical knowledge graphs (like LangChain baseline output) need
 * a force-directed solver that distributes nodes spatially.
 */

test.describe('Force-directed layout for knowledge graphs', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8789');
    await page.waitForSelector('.graph-canvas canvas', { timeout: 10000 });
    // Wait for physics stabilization
    await page.waitForTimeout(5000);
  });

  test('nodes spread across both X and Y axes, not in a single line', async ({ page }) => {
    const spread = await page.evaluate(() => {
      const net = (window as any).__visNetwork;
      if (!net) return null;

      const nodeIds = net.body.data.nodes.getIds();
      const positions = net.getPositions(nodeIds);
      const xs: number[] = [];
      const ys: number[] = [];
      for (const id of nodeIds) {
        if (positions[id]) {
          xs.push(positions[id].x);
          ys.push(positions[id].y);
        }
      }
      if (xs.length === 0) return null;

      return {
        xRange: Math.max(...xs) - Math.min(...xs),
        yRange: Math.max(...ys) - Math.min(...ys),
        nodeCount: xs.length,
      };
    });

    expect(spread).not.toBeNull();
    expect(spread!.nodeCount).toBeGreaterThan(10);

    // With a proper force-directed layout, nodes spread in BOTH dimensions.
    // The hierarchical LR layout produces xRange >> yRange (thin column).
    // We require both axes to have meaningful spread (> 300px).
    expect(spread!.xRange).toBeGreaterThan(300);
    expect(spread!.yRange).toBeGreaterThan(300);

    // Aspect ratio check: min dimension should be at least 25% of max
    // A line has ratio ~0; a healthy spread has ratio > 0.25
    const ratio = Math.min(spread!.xRange, spread!.yRange) /
                  Math.max(spread!.xRange, spread!.yRange);
    expect(ratio).toBeGreaterThan(0.25);
  });

  test('duty-of-care entity types have mapped shapes (not all default dots)', async ({ page }) => {
    // Query the vis-network for node shapes
    const shapeInfo = await page.evaluate(() => {
      const net = (window as any).__visNetwork;
      if (!net) return null;

      const nodeIds = net.body.data.nodes.getIds();
      const shapes = new Set<string>();
      const typeToShape: Record<string, string> = {};

      for (const id of nodeIds) {
        const node = net.body.data.nodes.get(id);
        if (node) {
          shapes.add(node.shape);
          // Get the type from the title "[Type]"
          const match = (node.title || '').match(/\[(\w+)\]/);
          if (match) {
            typeToShape[match[1]] = node.shape;
          }
        }
      }

      return {
        uniqueShapes: [...shapes],
        shapeCount: shapes.size,
        typeToShape,
      };
    });

    expect(shapeInfo).not.toBeNull();
    // Should have more than just 'dot' — at least 3 distinct shapes
    expect(shapeInfo!.shapeCount).toBeGreaterThanOrEqual(3);
    // 'Service' and 'Organization' should NOT be default 'dot'
    if (shapeInfo!.typeToShape['Service']) {
      expect(shapeInfo!.typeToShape['Service']).not.toBe('dot');
    }
    if (shapeInfo!.typeToShape['Organization']) {
      expect(shapeInfo!.typeToShape['Organization']).not.toBe('dot');
    }
  });

  test('legend groups duty-of-care types into named categories', async ({ page }) => {
    const legend = page.locator('.legend');
    await expect(legend).toBeVisible({ timeout: 5000 });

    // Should have named category groups, not just "OTHER"
    const groupHeaders = legend.locator('.legend-group-header, .legend-group-title');
    const headerTexts = await groupHeaders.allTextContents();

    // At least one group should NOT be "OTHER" — meaning our ENTITY_GROUPS
    // mapping covers the duty-of-care types
    const nonOther = headerTexts.filter(t => !t.toUpperCase().includes('OTHER'));
    expect(nonOther.length).toBeGreaterThan(0);
  });
});
