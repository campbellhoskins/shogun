import type { GraphData, GraphStats, GraphListItem, EntityDetail, EntitySummary, PathResponse, AgentAnswer, CascadeResponse, ScenariosResponse, Scenario } from './types';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  listGraphs: () => fetchJSON<GraphListItem[]>(`${BASE}/graphs`),
  loadGraph: (filename: string) =>
    fetchJSON<GraphStats>(
      `${BASE}/graphs/load`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      },
    ),
  getGraph: () => fetchJSON<GraphData>(`${BASE}/graph`),
  getStats: () => fetchJSON<GraphStats>(`${BASE}/graph/stats`),
  getEntity: (id: string) => fetchJSON<EntityDetail>(`${BASE}/entity/${encodeURIComponent(id)}`),
  search: (q: string) => fetchJSON<EntitySummary[]>(`${BASE}/search?q=${encodeURIComponent(q)}`),
  findPaths: (sourceId: string, targetId: string) =>
    fetchJSON<PathResponse>(
      `${BASE}/paths`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
      },
    ),
  askAgent: (question: string) =>
    fetchJSON<AgentAnswer>(
      `${BASE}/agent/ask`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      },
    ),
  getCascade: (nodeId: string) =>
    fetchJSON<CascadeResponse>(
      `${BASE}/cascade`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_node_id: nodeId }),
      },
    ),
  getScenarios: () => fetchJSON<ScenariosResponse>(`${BASE}/scenarios`),
  runWalkthrough: (prompt: string) =>
    fetchJSON<Scenario>(
      `${BASE}/agent/walkthrough`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      },
    ),
};
