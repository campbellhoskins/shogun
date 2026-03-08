import { test, expect } from '@playwright/test';

/**
 * Centrality Metrics Tests
 *
 * Tests that the backend computes importance scores, the frontend
 * renders nodes with varying visual weight, and the detail panel
 * displays metric bars.
 *
 * Requires: server running at localhost:8789 with a loaded graph.
 */

test.describe('Centrality Metrics', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.graph-canvas-wrapper canvas', { timeout: 10_000 });
    await page.waitForTimeout(3000);
  });

  test('API returns importance scores in [0, 1] for every node', async ({ page }) => {
    const response = await page.request.get('/api/graph');
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.nodes.length).toBeGreaterThan(0);

    for (const node of data.nodes) {
      expect(node).toHaveProperty('importance');
      expect(node.importance).toBeGreaterThanOrEqual(0);
      expect(node.importance).toBeLessThanOrEqual(1);
      expect(node).toHaveProperty('betweenness');
      expect(node).toHaveProperty('pagerank');
      expect(node).toHaveProperty('degree_centrality');
    }
  });

  test('nodes have varying sizes driven by importance', async ({ page }) => {
    // Query vis-network for node sizes
    const sizes: number[] = await page.evaluate(() => {
      const net = (window as any).__visNetwork;
      if (!net) return [];
      const nodeIds = net.body.data.nodes.getIds();
      return nodeIds.map((id: string) => {
        const node = net.body.nodes[id];
        return node?.options?.size ?? 0;
      });
    });

    expect(sizes.length).toBeGreaterThan(0);

    // Check that there's meaningful variation (std dev > 2)
    const mean = sizes.reduce((a, b) => a + b, 0) / sizes.length;
    const variance = sizes.reduce((a, b) => a + (b - mean) ** 2, 0) / sizes.length;
    const stdDev = Math.sqrt(variance);
    expect(stdDev).toBeGreaterThan(2);
  });

  test('high-importance nodes have larger fonts', async ({ page }) => {
    const fontSizes: number[] = await page.evaluate(() => {
      const net = (window as any).__visNetwork;
      if (!net) return [];
      const nodeIds = net.body.data.nodes.getIds();
      return nodeIds.map((id: string) => {
        const node = net.body.nodes[id];
        return node?.options?.font?.size ?? 0;
      });
    });

    expect(fontSizes.length).toBeGreaterThan(0);
    const maxFont = Math.max(...fontSizes);
    const minFont = Math.min(...fontSizes);
    expect(maxFont - minFont).toBeGreaterThanOrEqual(4);
  });

  test('detail panel shows graph metrics when a node is clicked', async ({ page }) => {
    // Search for an entity using the search bar
    const searchInput = page.getByRole('textbox', { name: 'Search entities...' });
    await searchInput.click();
    await searchInput.fill('');
    await searchInput.pressSequentially('org', { delay: 80 });
    await expect(page.locator('.topbar-search-results')).toBeVisible({ timeout: 5000 });
    await page.locator('.topbar-search-item').first().click();
    await page.waitForTimeout(1200);

    // Check that the detail panel shows metrics
    await expect(page.locator('.node-detail-metrics')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.node-detail-metric-row')).toHaveCount(4);
    // Verify labels
    const labels = await page.locator('.node-detail-metric-label').allTextContents();
    expect(labels).toContain('Importance');
    expect(labels).toContain('Betweenness');
    expect(labels).toContain('PageRank');
    expect(labels).toContain('Degree');
  });

  test('edge widths vary based on endpoint importance', async ({ page }) => {
    const widths: number[] = await page.evaluate(() => {
      const net = (window as any).__visNetwork;
      if (!net) return [];
      const edgeIds = net.body.data.edges.getIds();
      return edgeIds.map((id: string) => {
        const edge = net.body.edges[id];
        return edge?.options?.width ?? 0;
      });
    });

    expect(widths.length).toBeGreaterThan(0);
    const maxWidth = Math.max(...widths);
    const minWidth = Math.min(...widths);
    expect(maxWidth).toBeGreaterThanOrEqual(minWidth * 1.5);
  });
});
