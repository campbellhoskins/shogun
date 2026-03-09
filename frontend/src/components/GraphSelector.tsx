import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import type { GraphListItem } from '../types';
import '../styles/GraphSelector.css';

interface Props {
  currentTitle: string;
  onGraphSwitch: (filename: string) => void;
}

export default function GraphSelector({ currentTitle, onGraphSwitch }: Props) {
  const [graphs, setGraphs] = useState<GraphListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listGraphs().then(setGraphs).catch(() => setGraphs([]));
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (graphs.length <= 1) return null;

  const handleSelect = async (filename: string) => {
    setOpen(false);
    setLoading(true);
    try {
      await onGraphSwitch(filename);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="graph-selector" ref={ref}>
      <button
        className="graph-selector-btn"
        onClick={() => setOpen(!open)}
        disabled={loading}
        data-testid="graph-selector-btn"
      >
        <span className="graph-selector-label">{loading ? 'Loading...' : currentTitle || 'Select Graph'}</span>
        <span className="graph-selector-chevron">{open ? '\u25B4' : '\u25BE'}</span>
      </button>
      {open && (
        <div className="graph-selector-dropdown" data-testid="graph-selector-dropdown">
          {graphs.map((g) => (
            <div
              key={g.filename}
              className={`graph-selector-item ${g.graph_title === currentTitle ? 'active' : ''}`}
              onClick={() => handleSelect(g.filename)}
              data-testid={`graph-option-${g.filename}`}
            >
              <span className="graph-selector-item-title">{g.graph_title}</span>
              <span className="graph-selector-item-meta">
                {g.entity_count} entities &middot; {g.relationship_count} rels
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
