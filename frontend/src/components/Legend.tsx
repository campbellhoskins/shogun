import { useState } from 'react';
import type { GraphStats } from '../types';
import '../styles/Legend.css';

interface Props {
  stats: GraphStats | null;
  typeColors: Record<string, string>;
}

export default function Legend({ stats, typeColors }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  if (!stats) return null;

  const entries = Object.entries(stats.entity_types).sort((a, b) => b[1] - a[1]);

  return (
    <div className="legend">
      <div className="legend-header" onClick={() => setCollapsed(!collapsed)}>
        <span className="legend-title">Entity Types</span>
        <span className={`legend-toggle ${collapsed ? 'collapsed' : ''}`}>
          {collapsed ? '+' : '\u2212'}
        </span>
      </div>
      {!collapsed && (
        <div className="legend-items">
          {entries.map(([type, count]) => (
            <div key={type} className="legend-item">
              <span
                className="legend-dot"
                style={{ backgroundColor: typeColors[type] || '#6b7280' }}
              />
              <span>{type}</span>
              <span className="legend-count">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
