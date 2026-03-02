import type { GraphData, GraphStats, EntityDetail, EntitySummary, PathResponse, AgentAnswer } from './types';

const BASE = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
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
};
