import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from './api';
import type { GraphData, GraphStats, EntityDetail, ChatMessage } from './types';
import TopBar from './components/TopBar';
import GraphCanvas, { type GraphCanvasHandle } from './components/GraphCanvas';
import Legend from './components/Legend';
import LeftPanel from './components/LeftPanel';
import NodeDetailPanel from './components/NodeDetailPanel';
import './styles/App.css';

export default function App() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<EntityDetail | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());
  const [highlightedEdgeKeys, setHighlightedEdgeKeys] = useState<Set<string>>(new Set());
  const [leftTab, setLeftTab] = useState<'pathfinder' | 'chat'>('pathfinder');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  const graphRef = useRef<GraphCanvasHandle>(null);

  // Load graph data on mount
  useEffect(() => {
    Promise.all([api.getGraph(), api.getStats()])
      .then(([graph, graphStats]) => {
        setGraphData(graph);
        setStats(graphStats);
      })
      .catch((err) => console.error('Failed to load graph:', err));
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelectedNodeId(null);
        setNodeDetail(null);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const handleNodeClick = useCallback(async (nodeId: string) => {
    setSelectedNodeId(nodeId);
    try {
      const detail = await api.getEntity(nodeId);
      setNodeDetail(detail);
    } catch (err) {
      console.error('Failed to load entity:', err);
    }
  }, []);

  const handleBackgroundClick = useCallback(() => {
    setSelectedNodeId(null);
    setNodeDetail(null);
  }, []);

  const navigateToEntity = useCallback(async (entityId: string) => {
    setSelectedNodeId(entityId);
    graphRef.current?.focusNode(entityId);
    try {
      const detail = await api.getEntity(entityId);
      setNodeDetail(detail);
    } catch (err) {
      console.error('Failed to load entity:', err);
    }
  }, []);

  const clearHighlights = useCallback(() => {
    setHighlightedNodeIds(new Set());
    setHighlightedEdgeKeys(new Set());
  }, []);

  const handlePathsFound = useCallback((nodeIds: Set<string>, edgeKeys: Set<string>) => {
    setHighlightedNodeIds(nodeIds);
    setHighlightedEdgeKeys(edgeKeys);
  }, []);

  const handleFitToScreen = useCallback(() => {
    setSelectedNodeId(null);
    setNodeDetail(null);
    graphRef.current?.fitToScreen();
  }, []);

  const isDetailOpen = nodeDetail !== null;
  const typeColors = graphData?.type_colors || {};

  return (
    <div className={`app ${isDetailOpen ? 'detail-open' : ''}`}>
      <TopBar
        stats={stats}
        typeColors={typeColors}
        onEntitySelect={navigateToEntity}
        onFitToScreen={handleFitToScreen}
        onClearHighlights={clearHighlights}
      />

      <div className="left-panel">
        <LeftPanel
          activeTab={leftTab}
          onTabChange={setLeftTab}
          nodes={graphData?.nodes || []}
          typeColors={typeColors}
          onPathsFound={handlePathsFound}
          onClearPaths={clearHighlights}
          onEntitySelect={navigateToEntity}
          chatMessages={chatMessages}
          onChatMessagesChange={setChatMessages}
        />
      </div>

      <div className="graph-area">
        <GraphCanvas
          ref={graphRef}
          graphData={graphData}
          selectedNodeId={selectedNodeId}
          highlightedNodeIds={highlightedNodeIds}
          highlightedEdgeKeys={highlightedEdgeKeys}
          onNodeClick={handleNodeClick}
          onBackgroundClick={handleBackgroundClick}
        />
        <Legend stats={stats} typeColors={typeColors} />
      </div>

      <div className="right-panel">
        <NodeDetailPanel
          detail={nodeDetail}
          typeColors={typeColors}
          onClose={handleBackgroundClick}
          onEntitySelect={navigateToEntity}
        />
      </div>
    </div>
  );
}
