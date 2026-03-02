import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { GraphStats, EntitySummary } from '../types';
import EntityChip from './EntityChip';
import '../styles/TopBar.css';

interface Props {
  stats: GraphStats | null;
  typeColors: Record<string, string>;
  onEntitySelect: (entityId: string) => void;
  onFitToScreen: () => void;
  onClearHighlights: () => void;
}

export default function TopBar({ stats, typeColors, onEntitySelect, onFitToScreen, onClearHighlights }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<EntitySummary[]>([]);
  const [showResults, setShowResults] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const handleSearch = useCallback((q: string) => {
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (q.length < 2) {
      setResults([]);
      setShowResults(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.search(q);
        setResults(res.slice(0, 12));
        setShowResults(true);
      } catch {
        setResults([]);
      }
    }, 200);
  }, []);

  const handleSelect = useCallback((entityId: string) => {
    setShowResults(false);
    setQuery('');
    onEntitySelect(entityId);
  }, [onEntitySelect]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('.topbar-search')) {
        setShowResults(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  return (
    <div className="topbar">
      <span className="topbar-brand">SHOGUN</span>
      <div className="topbar-separator" />

      {stats && (
        <>
          <span className="topbar-doc">{stats.source_document || 'Ontology Explorer'}</span>
          <div className="topbar-stats">
            <span>
              <span className="topbar-stat-value">{stats.entity_count}</span> entities
            </span>
            <span>
              <span className="topbar-stat-value">{stats.relationship_count}</span> relationships
            </span>
          </div>
        </>
      )}

      <div className="topbar-spacer" />

      <div className="topbar-search">
        <span className="topbar-search-icon">{'\u2315'}</span>
        <input
          ref={inputRef}
          className="topbar-search-input"
          type="text"
          placeholder="Search entities..."
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          onFocus={() => results.length > 0 && setShowResults(true)}
        />
        {showResults && (
          <div className="topbar-search-results">
            {results.length === 0 ? (
              <div className="topbar-search-empty">No matching entities</div>
            ) : (
              results.map((r) => (
                <div
                  key={r.id}
                  className="topbar-search-item"
                  onClick={() => handleSelect(r.id)}
                >
                  <span
                    className="entity-chip-dot"
                    style={{ backgroundColor: typeColors[r.type] || '#6b7280', width: 8, height: 8, borderRadius: '50%', flexShrink: 0 }}
                  />
                  <span className="topbar-search-item-name">{r.name}</span>
                  <span className="topbar-search-item-type" style={{ color: typeColors[r.type] || '#6b7280' }}>
                    {r.type}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="topbar-controls">
        <button className="topbar-btn" onClick={onFitToScreen} title="Fit graph to screen">
          Fit
        </button>
        <button className="topbar-btn" onClick={onClearHighlights} title="Clear path highlights">
          Clear
        </button>
      </div>
    </div>
  );
}
