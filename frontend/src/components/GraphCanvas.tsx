import { useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import { Network, DataSet } from 'vis-network/standalone';
import type { GraphData } from '../types';
import { TYPE_SHAPES, DEFAULT_SHAPE, PHYSICS_OPTIONS } from '../constants';
import '../styles/GraphCanvas.css';

interface Props {
  graphData: GraphData | null;
  selectedNodeId: string | null;
  highlightedNodeIds: Set<string>;
  highlightedEdgeKeys: Set<string>;
  onNodeClick: (nodeId: string) => void;
  onBackgroundClick: () => void;
}

export interface GraphCanvasHandle {
  fitToScreen: () => void;
  focusNode: (nodeId: string) => void;
}

const GraphCanvas = forwardRef<GraphCanvasHandle, Props>(({
  graphData,
  selectedNodeId,
  highlightedNodeIds,
  highlightedEdgeKeys,
  onNodeClick,
  onBackgroundClick,
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const nodesRef = useRef<DataSet<any> | null>(null);
  const edgesRef = useRef<DataSet<any> | null>(null);
  const graphDataRef = useRef<GraphData | null>(null);
  // Track which node we last focused on to avoid re-focusing on the same node
  const lastFocusedRef = useRef<string | null>(null);

  useImperativeHandle(ref, () => ({
    fitToScreen: () => {
      if (!networkRef.current) return;
      lastFocusedRef.current = null;
      networkRef.current.unselectAll();
      networkRef.current.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    },
    focusNode: (nodeId: string) => {
      if (!networkRef.current) return;
      lastFocusedRef.current = nodeId;
      networkRef.current.focus(nodeId, {
        scale: 1.5,
        animation: { duration: 600, easingFunction: 'easeInOutQuad' },
      });
      networkRef.current.selectNodes([nodeId]);
    },
  }));

  // Initialize network when graphData loads
  useEffect(() => {
    if (!containerRef.current || !graphData) return;
    graphDataRef.current = graphData;

    const nodes = new DataSet(
      graphData.nodes.map((n) => ({
        id: n.id,
        label: n.name,
        shape: TYPE_SHAPES[n.type] || DEFAULT_SHAPE,
        color: {
          background: n.color,
          border: n.color,
          highlight: { background: n.color, border: '#f59e0b' },
          hover: { background: n.color, border: '#818cf8' },
        },
        size: Math.max(12, Math.min(36, 12 + n.degree * 2.5)),
        font: {
          color: '#e8e6e3',
          size: 13,
          face: "'IBM Plex Sans', system-ui, sans-serif",
          strokeWidth: 3,
          strokeColor: '#0b0d14',
          vadjust: -2,
        },
        scaling: {
          label: { enabled: true, min: 10, max: 16, drawThreshold: 8 },
        },
        borderWidth: 2,
        borderWidthSelected: 3,
        shadow: {
          enabled: true,
          color: n.color + '30',
          size: 12,
          x: 0,
          y: 0,
        },
      })),
    );

    const edges = new DataSet(
      graphData.edges.map((e, i) => ({
        id: `edge-${i}`,
        from: e.from_id,
        to: e.to_id,
        label: e.type,
        _fromId: e.from_id,
        _toId: e.to_id,
        arrows: { to: { enabled: true, scaleFactor: 0.7 } },
        color: { color: '#3a3a5c', highlight: '#f59e0b', hover: '#555580' },
        font: {
          size: 9,
          color: '#5a5a7a',
          face: "'IBM Plex Sans', system-ui, sans-serif",
          align: 'middle',
          strokeWidth: 2,
          strokeColor: '#0b0d14',
        },
        smooth: { enabled: true, type: 'cubicBezier', roundness: 0.3 },
        width: 1,
        hoverWidth: 0.5,
      })),
    );

    nodesRef.current = nodes;
    edgesRef.current = edges;

    const network = new Network(
      containerRef.current,
      { nodes, edges },
      {
        physics: PHYSICS_OPTIONS,
        interaction: {
          hover: true,
          tooltipDelay: 200,
          navigationButtons: false,
          keyboard: { enabled: true, bindToWindow: false },
          multiselect: false,
          zoomView: true,
          dragView: true,
        },
        layout: {
          improvedLayout: true,
        },
      },
    );

    networkRef.current = network;

    network.on('click', (params: any) => {
      if (params.nodes.length > 0) {
        onNodeClick(params.nodes[0]);
      } else {
        onBackgroundClick();
      }
    });

    // Double-click on background to fit entire graph
    network.on('doubleClick', (params: any) => {
      if (params.nodes.length === 0) {
        lastFocusedRef.current = null;
        network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
      }
    });

    // Fit to screen after stabilization
    network.on('stabilizationIterationsDone', () => {
      network.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    });

    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [graphData]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus on selected node — only when the node actually changes
  useEffect(() => {
    if (!networkRef.current) return;

    if (!selectedNodeId) {
      // Node was deselected — zoom back out to full graph
      if (lastFocusedRef.current !== null) {
        lastFocusedRef.current = null;
        networkRef.current.unselectAll();
        networkRef.current.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
      }
      return;
    }

    // Only focus if this is a different node than what we last focused
    if (selectedNodeId === lastFocusedRef.current) return;

    lastFocusedRef.current = selectedNodeId;
    networkRef.current.focus(selectedNodeId, {
      scale: 1.5,
      animation: { duration: 600, easingFunction: 'easeInOutQuad' },
    });
    networkRef.current.selectNodes([selectedNodeId]);
  }, [selectedNodeId]);

  // Update highlights for paths
  useEffect(() => {
    if (!nodesRef.current || !edgesRef.current || !graphDataRef.current) return;

    const hasHighlights = highlightedNodeIds.size > 0;

    // Update nodes
    const nodeUpdates = graphDataRef.current.nodes.map((n) => {
      const isHighlighted = highlightedNodeIds.has(n.id);
      const dimmed = hasHighlights && !isHighlighted;
      return {
        id: n.id,
        opacity: dimmed ? 0.15 : 1,
        font: {
          color: dimmed ? '#3a3a5c' : '#e8e6e3',
          size: 13,
          face: "'IBM Plex Sans', system-ui, sans-serif",
          strokeWidth: 3,
          strokeColor: '#0b0d14',
        },
        shadow: {
          enabled: true,
          color: isHighlighted ? '#f59e0b50' : n.color + '30',
          size: isHighlighted ? 20 : 12,
          x: 0,
          y: 0,
        },
        borderWidth: isHighlighted ? 3 : 2,
      };
    });
    nodesRef.current.update(nodeUpdates);

    // Update edges
    const edgeUpdates = graphDataRef.current.edges.map((e, i) => {
      const edgeKey = `${e.from_id}->${e.to_id}`;
      const isHighlighted = highlightedEdgeKeys.has(edgeKey);
      const dimmed = hasHighlights && !isHighlighted;
      return {
        id: `edge-${i}`,
        color: {
          color: isHighlighted ? '#f59e0b' : dimmed ? '#1a1a30' : '#3a3a5c',
          highlight: '#f59e0b',
          hover: '#555580',
        },
        width: isHighlighted ? 3 : 1,
        font: {
          size: 9,
          color: isHighlighted ? '#f59e0b' : dimmed ? '#1a1a30' : '#5a5a7a',
          face: "'IBM Plex Sans', system-ui, sans-serif",
          align: 'middle' as const,
          strokeWidth: 2,
          strokeColor: '#0b0d14',
        },
      };
    });
    edgesRef.current.update(edgeUpdates);
  }, [highlightedNodeIds, highlightedEdgeKeys]);

  const handleZoomIn = useCallback(() => {
    if (!networkRef.current) return;
    const scale = networkRef.current.getScale();
    networkRef.current.moveTo({ scale: scale * 1.4, animation: { duration: 200, easingFunction: 'easeInOutQuad' } });
  }, []);

  const handleZoomOut = useCallback(() => {
    if (!networkRef.current) return;
    const scale = networkRef.current.getScale();
    networkRef.current.moveTo({ scale: scale / 1.4, animation: { duration: 200, easingFunction: 'easeInOutQuad' } });
  }, []);

  const handleZoomFit = useCallback(() => {
    if (!networkRef.current) return;
    lastFocusedRef.current = null;
    networkRef.current.unselectAll();
    networkRef.current.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  }, []);

  return (
    <div className="graph-canvas-wrapper">
      <div className="graph-canvas" ref={containerRef} />
      {!graphData && (
        <div className="graph-loading">
          <span className="graph-loading-text">Loading graph</span>
        </div>
      )}
      {graphData && (
        <div className="zoom-controls">
          <button className="zoom-btn" onClick={handleZoomIn} title="Zoom in">+</button>
          <button className="zoom-btn" onClick={handleZoomOut} title="Zoom out">{'\u2212'}</button>
          <div className="zoom-divider" />
          <button className="zoom-btn zoom-btn-fit" onClick={handleZoomFit} title="Fit to screen">{'\u2302'}</button>
        </div>
      )}
    </div>
  );
});

GraphCanvas.displayName = 'GraphCanvas';
export default GraphCanvas;
