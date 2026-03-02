import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { GraphNode, PathStep } from '../types';
import EntityChip from './EntityChip';
import '../styles/PathFinder.css';

interface Props {
  nodes: GraphNode[];
  typeColors: Record<string, string>;
  onPathsFound: (nodeIds: Set<string>, edgeKeys: Set<string>) => void;
  onClearPaths: () => void;
  onEntitySelect: (entityId: string) => void;
}

export default function PathFinder({ nodes, typeColors, onPathsFound, onClearPaths, onEntitySelect }: Props) {
  const [sourceQuery, setSourceQuery] = useState('');
  const [targetQuery, setTargetQuery] = useState('');
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [sourceFocused, setSourceFocused] = useState(false);
  const [targetFocused, setTargetFocused] = useState(false);
  const [paths, setPaths] = useState<PathStep[][] | null>(null);
  const [loading, setLoading] = useState(false);
  const [sourceName, setSourceName] = useState('');
  const [targetName, setTargetName] = useState('');

  const filterNodes = useCallback((q: string) => {
    if (q.length < 1) return [];
    const lower = q.toLowerCase();
    return nodes.filter((n) => n.name.toLowerCase().includes(lower)).slice(0, 8);
  }, [nodes]);

  const handleFindPaths = useCallback(async () => {
    if (!sourceId || !targetId) return;
    setLoading(true);
    try {
      const res = await api.findPaths(sourceId, targetId);
      setPaths(res.paths);
      setSourceName(res.source_name);
      setTargetName(res.target_name);

      // Highlight paths on graph
      const nodeIds = new Set<string>();
      const edgeKeys = new Set<string>();
      for (const path of res.paths) {
        for (const step of path) {
          nodeIds.add(step.from_id);
          nodeIds.add(step.to_id);
          if (step.direction === 'forward') {
            edgeKeys.add(`${step.from_id}->${step.to_id}`);
          } else {
            edgeKeys.add(`${step.to_id}->${step.from_id}`);
          }
        }
      }
      onPathsFound(nodeIds, edgeKeys);
    } catch (err) {
      console.error('Path finding failed:', err);
    } finally {
      setLoading(false);
    }
  }, [sourceId, targetId, onPathsFound]);

  const handleClear = useCallback(() => {
    setSourceQuery('');
    setTargetQuery('');
    setSourceId(null);
    setTargetId(null);
    setPaths(null);
    onClearPaths();
  }, [onClearPaths]);

  const selectSource = useCallback((node: GraphNode) => {
    setSourceId(node.id);
    setSourceQuery(node.name);
    setSourceFocused(false);
  }, []);

  const selectTarget = useCallback((node: GraphNode) => {
    setTargetId(node.id);
    setTargetQuery(node.name);
    setTargetFocused(false);
  }, []);

  const sourceResults = sourceFocused ? filterNodes(sourceQuery) : [];
  const targetResults = targetFocused ? filterNodes(targetQuery) : [];

  return (
    <div className="pathfinder">
      <div className="pathfinder-title">Find Paths</div>

      <div className="pathfinder-field">
        <span className="pathfinder-label">From</span>
        <div className="pathfinder-input-wrap">
          <input
            className="pathfinder-input"
            placeholder="Search entity..."
            value={sourceQuery}
            onChange={(e) => { setSourceQuery(e.target.value); setSourceId(null); }}
            onFocus={() => setSourceFocused(true)}
            onBlur={() => setTimeout(() => setSourceFocused(false), 200)}
          />
          {sourceResults.length > 0 && (
            <div className="pathfinder-dropdown">
              {sourceResults.map((n) => (
                <div key={n.id} className="pathfinder-dropdown-item" onMouseDown={() => selectSource(n)}>
                  <span className="entity-chip-dot" style={{ backgroundColor: n.color, width: 7, height: 7, borderRadius: '50%' }} />
                  {n.name}
                  <span className="pathfinder-dropdown-type">{n.type}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="pathfinder-field">
        <span className="pathfinder-label">To</span>
        <div className="pathfinder-input-wrap">
          <input
            className="pathfinder-input"
            placeholder="Search entity..."
            value={targetQuery}
            onChange={(e) => { setTargetQuery(e.target.value); setTargetId(null); }}
            onFocus={() => setTargetFocused(true)}
            onBlur={() => setTimeout(() => setTargetFocused(false), 200)}
          />
          {targetResults.length > 0 && (
            <div className="pathfinder-dropdown">
              {targetResults.map((n) => (
                <div key={n.id} className="pathfinder-dropdown-item" onMouseDown={() => selectTarget(n)}>
                  <span className="entity-chip-dot" style={{ backgroundColor: n.color, width: 7, height: 7, borderRadius: '50%' }} />
                  {n.name}
                  <span className="pathfinder-dropdown-type">{n.type}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="pathfinder-actions">
        <button
          className="pathfinder-btn pathfinder-btn-primary"
          disabled={!sourceId || !targetId || loading}
          onClick={handleFindPaths}
        >
          {loading ? 'Searching...' : 'Find Paths'}
        </button>
        <button className="pathfinder-btn pathfinder-btn-secondary" onClick={handleClear}>
          Clear
        </button>
      </div>

      {/* Results */}
      {paths !== null && (
        <div className="pathfinder-results">
          <div className="pathfinder-result-header">
            {paths.length === 0
              ? 'No paths found'
              : `${paths.length} path${paths.length > 1 ? 's' : ''} found`}
          </div>
          {paths.length === 0 && (
            <div className="pathfinder-no-paths">
              No connection between {sourceName} and {targetName}
            </div>
          )}
          {paths.map((path, pi) => (
            <div key={pi} className="path-result">
              <div className="path-result-label">Path {pi + 1}</div>
              <div className="path-result-chain">
                {path.map((step, si) => (
                  <span key={si} style={{ display: 'contents' }}>
                    {si === 0 && (
                      <EntityChip
                        name={step.from_name}
                        color={typeColors[nodes.find((n) => n.id === step.from_id)?.type || ''] || '#6b7280'}
                        onClick={() => onEntitySelect(step.from_id)}
                      />
                    )}
                    <span className="path-result-arrow">
                      {step.direction === 'forward' ? '\u2192' : '\u2190'}
                    </span>
                    <span className="path-result-rel">[{step.relationship_type}]</span>
                    <span className="path-result-arrow">
                      {step.direction === 'forward' ? '\u2192' : '\u2190'}
                    </span>
                    <EntityChip
                      name={step.to_name}
                      color={typeColors[nodes.find((n) => n.id === step.to_id)?.type || ''] || '#6b7280'}
                      onClick={() => onEntitySelect(step.to_id)}
                    />
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
