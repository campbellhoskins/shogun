import { useState } from 'react';
import type { GraphStats } from '../types';
import { ENTITY_GROUPS } from '../constants';
import '../styles/Legend.css';

interface Props {
  stats: GraphStats | null;
  typeColors: Record<string, string>;
}

export default function Legend({ stats, typeColors }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  if (!stats) return null;

  const typeCounts = stats.entity_types;

  const toggleGroup = (group: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  };

  // Build ordered groups: only show groups that have at least one entity in the graph
  const groupEntries = Object.entries(ENTITY_GROUPS)
    .map(([groupName, types]) => {
      const items = types
        .filter((t) => typeCounts[t] && typeCounts[t] > 0)
        .map((t) => ({ type: t, count: typeCounts[t] }));
      return { groupName, items };
    })
    .filter((g) => g.items.length > 0);

  // Collect any types not in the defined groups
  const knownTypes = new Set(Object.values(ENTITY_GROUPS).flat());
  const ungroupedEntries = Object.entries(typeCounts)
    .filter(([t]) => !knownTypes.has(t))
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => ({ type, count }));

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
          {groupEntries.map(({ groupName, items }) => (
            <div key={groupName} className="legend-group">
              <div
                className="legend-group-header"
                onClick={() => toggleGroup(groupName)}
              >
                <span className="legend-group-name">{groupName}</span>
                <span className="legend-group-toggle">
                  {collapsedGroups.has(groupName) ? '+' : '\u2212'}
                </span>
              </div>
              {!collapsedGroups.has(groupName) &&
                items.map(({ type, count }) => (
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
          ))}
          {ungroupedEntries.length > 0 && (
            <div className="legend-group">
              <div
                className="legend-group-header"
                onClick={() => toggleGroup('Other')}
              >
                <span className="legend-group-name">Other</span>
                <span className="legend-group-toggle">
                  {collapsedGroups.has('Other') ? '+' : '\u2212'}
                </span>
              </div>
              {!collapsedGroups.has('Other') &&
                ungroupedEntries.map(({ type, count }) => (
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
      )}
    </div>
  );
}
