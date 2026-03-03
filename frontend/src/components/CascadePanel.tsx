import type { CascadeResponse } from '../types';
import EntityChip from './EntityChip';
import '../styles/CascadePanel.css';

interface Props {
  cascade: CascadeResponse | null;
  typeColors: Record<string, string>;
  onEntitySelect: (entityId: string) => void;
  onClearCascade: () => void;
}

export default function CascadePanel({ cascade, typeColors, onEntitySelect, onClearCascade }: Props) {
  if (!cascade) {
    return (
      <div className="cascade-panel">
        <div className="cascade-empty">
          <div className="cascade-empty-icon">{'\u26A1'}</div>
          <div className="cascade-empty-title">No cascade active</div>
          <div className="cascade-empty-hint">
            Click a <strong>TravelEvent</strong> node in the graph to trace its cascade through the policy structure.
          </div>
        </div>
      </div>
    );
  }

  // Group steps by depth for tree-like indentation
  const maxDepth = Math.max(...cascade.steps.map((s) => s.depth));

  return (
    <div className="cascade-panel">
      <div className="cascade-header">
        <div className="cascade-title">
          Cascade from <strong>{cascade.event_name}</strong>
        </div>
        <div className="cascade-stats">
          {cascade.node_ids.length} nodes &middot; {cascade.edge_keys.length} edges &middot; {maxDepth} depth
        </div>
        <button className="cascade-clear-btn" onClick={onClearCascade}>
          Clear Cascade
        </button>
      </div>
      <div className="cascade-tree">
        {cascade.steps.map((step) => (
          <div
            key={step.node_id}
            className="cascade-step"
            style={{ paddingLeft: `${step.depth * 16 + 8}px` }}
          >
            {step.depth > 0 && (
              <span className="cascade-edge-label">{step.edge_type}</span>
            )}
            <EntityChip
              name={step.node_name}
              type={step.node_type}
              color={typeColors[step.node_type]}
              onClick={() => onEntitySelect(step.node_id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
