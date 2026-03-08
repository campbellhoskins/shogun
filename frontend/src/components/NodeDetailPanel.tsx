import type { EntityDetail, GraphNode } from '../types';
import EntityChip from './EntityChip';
import '../styles/NodeDetailPanel.css';

interface Props {
  detail: EntityDetail | null;
  graphNode?: GraphNode;
  typeColors: Record<string, string>;
  onClose: () => void;
  onEntitySelect: (entityId: string) => void;
}

export default function NodeDetailPanel({ detail, graphNode, typeColors, onClose, onEntitySelect }: Props) {
  if (!detail) return null;

  const color = typeColors[detail.type] || '#6b7280';
  const attrs = Object.entries(detail.attributes);
  const outgoing = detail.relationships.filter((r) => r.direction === 'outgoing');
  const incoming = detail.relationships.filter((r) => r.direction === 'incoming');

  return (
    <div className="node-detail">
      <div className="node-detail-header">
        <h2 className="node-detail-name">{detail.name}</h2>
        <button className="node-detail-close" onClick={onClose} title="Close (Esc)">
          {'\u2715'}
        </button>
      </div>

      <div className="node-detail-type-badge" style={{ backgroundColor: color + '15', color }}>
        <span className="node-detail-type-dot" style={{ backgroundColor: color }} />
        {detail.type}
      </div>

      {graphNode && (
        <div className="node-detail-metrics">
          <h3 className="node-detail-section-title">Graph Metrics</h3>
          {([
            ['Importance', graphNode.importance ?? 0],
            ['Betweenness', graphNode.betweenness ?? 0],
            ['PageRank', graphNode.pagerank ?? 0],
            ['Degree', graphNode.degree_centrality ?? 0],
          ] as [string, number][]).map(([label, value]) => (
            <div key={label} className="node-detail-metric-row">
              <span className="node-detail-metric-label">{label}</span>
              <div className="node-detail-metric-bar">
                <div
                  className="node-detail-metric-fill"
                  style={{ width: `${Math.round(value * 100)}%`, backgroundColor: color }}
                />
              </div>
              <span className="node-detail-metric-value">{(value * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}

      <p className="node-detail-description">{detail.description}</p>

      <div className="node-detail-id">ID: {detail.id}</div>

      {/* Attributes */}
      {attrs.length > 0 && (
        <div className="node-detail-section">
          <h3 className="node-detail-section-title">Attributes</h3>
          <div className="node-detail-attrs">
            {attrs.map(([key, value]) => (
              <div key={key} className="node-detail-attr">
                <span className="node-detail-attr-key">{key}</span>
                <span className="node-detail-attr-value">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Source text */}
      {detail.source_text && (
        <div className="node-detail-section">
          <h3 className="node-detail-section-title">Source Text</h3>
          <div className="node-detail-source">
            {detail.source_text}
            {detail.source_section && (
              <div className="node-detail-source-section">
                Section {detail.source_section}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Outgoing relationships */}
      {outgoing.length > 0 && (
        <div className="node-detail-section">
          <h3 className="node-detail-section-title">
            Outgoing ({outgoing.length})
          </h3>
          <div className="node-detail-rels">
            {outgoing.map((rel, i) => (
              <div key={`out-${i}`} className="node-detail-rel">
                <span className="node-detail-rel-direction">{'\u2192'}</span>
                <span className="node-detail-rel-type">{rel.relationship_type}</span>
                <div className="node-detail-rel-entity">
                  <EntityChip
                    name={rel.entity_name}
                    type={rel.entity_type}
                    color={typeColors[rel.entity_type]}
                    onClick={() => onEntitySelect(rel.entity_id)}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Incoming relationships */}
      {incoming.length > 0 && (
        <div className="node-detail-section">
          <h3 className="node-detail-section-title">
            Incoming ({incoming.length})
          </h3>
          <div className="node-detail-rels">
            {incoming.map((rel, i) => (
              <div key={`in-${i}`} className="node-detail-rel">
                <span className="node-detail-rel-direction">{'\u2190'}</span>
                <span className="node-detail-rel-type">{rel.relationship_type}</span>
                <div className="node-detail-rel-entity">
                  <EntityChip
                    name={rel.entity_name}
                    type={rel.entity_type}
                    color={typeColors[rel.entity_type]}
                    onClick={() => onEntitySelect(rel.entity_id)}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
