import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from './api';
import type { GraphData, GraphStats, EntityDetail, ChatMessage, CascadeResponse, Scenario, ScenarioUpdate } from './types';
import TopBar from './components/TopBar';
import GraphCanvas, { type GraphCanvasHandle } from './components/GraphCanvas';
import Legend from './components/Legend';
import LeftPanel from './components/LeftPanel';
import type { LeftTabType } from './components/LeftPanel';
import NodeDetailPanel from './components/NodeDetailPanel';
import './styles/App.css';

export default function App() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<EntityDetail | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());
  const [highlightedEdgeKeys, setHighlightedEdgeKeys] = useState<Set<string>>(new Set());
  const [leftTab, setLeftTab] = useState<LeftTabType>('pathfinder');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [cascade, setCascade] = useState<CascadeResponse | null>(null);
  const [collapsedNodeIds, setCollapsedNodeIds] = useState<Set<string>>(new Set());
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  // Progressive reveal state for scenario walkthroughs
  const [scenarioActive, setScenarioActive] = useState(false);
  const [revealedNodeIds, setRevealedNodeIds] = useState<Set<string>>(new Set());
  const [revealedEdgeKeys, setRevealedEdgeKeys] = useState<Set<string>>(new Set());

  const graphRef = useRef<GraphCanvasHandle>(null);

  const resetState = useCallback(() => {
    setSelectedNodeId(null);
    setNodeDetail(null);
    setHighlightedNodeIds(new Set());
    setHighlightedEdgeKeys(new Set());
    setCascade(null);
    setChatMessages([]);
    setCollapsedNodeIds(new Set());
    setScenarios([]);
    setScenarioActive(false);
    setRevealedNodeIds(new Set());
    setRevealedEdgeKeys(new Set());
  }, []);

  const loadCurrentGraph = useCallback(() => {
    return Promise.all([api.getGraph(), api.getStats(), api.getScenarios()])
      .then(([graph, graphStats, scenariosResp]) => {
        setGraphData(graph);
        setStats(graphStats);
        setScenarios(scenariosResp.scenarios);
      });
  }, []);

  // Load graph data on mount
  useEffect(() => {
    loadCurrentGraph().catch((err) => console.error('Failed to load graph:', err));
  }, [loadCurrentGraph]);

  const handleGraphSwitch = useCallback(async (filename: string) => {
    resetState();
    setGraphData(null);
    setStats(null);
    try {
      await api.loadGraph(filename);
      await loadCurrentGraph();
    } catch (err) {
      console.error('Failed to switch graph:', err);
    }
  }, [resetState, loadCurrentGraph]);

  // Keyboard shortcuts — Escape clears selection (only when no scenario active)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // When scenario is active, ScenarioPanel handles Escape
        if (scenarioActive) return;
        setSelectedNodeId(null);
        setNodeDetail(null);
        setHighlightedNodeIds(new Set());
        setHighlightedEdgeKeys(new Set());
        setCascade(null);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [scenarioActive]);

  /** Compute the 1-hop neighborhood of a node from graphData. */
  const computeNeighborHighlight = useCallback((nodeId: string) => {
    if (!graphData) return { nodeIds: new Set<string>(), edgeKeys: new Set<string>() };

    const nodeIds = new Set<string>([nodeId]);
    const edgeKeys = new Set<string>();

    for (const edge of graphData.edges) {
      if (edge.from_id === nodeId) {
        nodeIds.add(edge.to_id);
        edgeKeys.add(`${edge.from_id}->${edge.to_id}`);
      }
      if (edge.to_id === nodeId) {
        nodeIds.add(edge.from_id);
        edgeKeys.add(`${edge.from_id}->${edge.to_id}`);
      }
    }

    return { nodeIds, edgeKeys };
  }, [graphData]);

  /** Shared logic: load entity detail, highlight neighborhood, cascade for TravelEvents. */
  const selectAndHighlight = useCallback(async (nodeId: string) => {
    // If the node is already highlighted, just show its detail — don't recompute
    if (highlightedNodeIds.has(nodeId) && highlightedNodeIds.size > 0) {
      setSelectedNodeId(nodeId);
      try {
        const detail = await api.getEntity(nodeId);
        setNodeDetail(detail);
      } catch (err) {
        console.error('Failed to load entity:', err);
      }
      return;
    }

    // New node not in current highlight — switch highlight to it
    setSelectedNodeId(nodeId);

    try {
      const detail = await api.getEntity(nodeId);
      setNodeDetail(detail);

      // TravelEvent: use BFS cascade for deeper downstream tracing
      if (detail.type === 'TravelEvent') {
        try {
          const cascadeResult = await api.getCascade(nodeId);
          setCascade(cascadeResult);
          setLeftTab('cascade');
          setHighlightedNodeIds(new Set(cascadeResult.node_ids));
          setHighlightedEdgeKeys(new Set(cascadeResult.edge_keys));
        } catch (err) {
          console.error('Failed to get cascade:', err);
          // Fall back to 1-hop highlight
          const { nodeIds, edgeKeys } = computeNeighborHighlight(nodeId);
          setHighlightedNodeIds(nodeIds);
          setHighlightedEdgeKeys(edgeKeys);
        }
      } else {
        // All other entity types: 1-hop neighborhood highlight
        setCascade(null);
        const { nodeIds, edgeKeys } = computeNeighborHighlight(nodeId);
        setHighlightedNodeIds(nodeIds);
        setHighlightedEdgeKeys(edgeKeys);
      }
    } catch (err) {
      console.error('Failed to load entity:', err);
    }
  }, [highlightedNodeIds, computeNeighborHighlight]);

  const handleNodeClick = useCallback(async (nodeId: string) => {
    if (scenarioActive) {
      // In scenario mode: show detail panel only, don't change highlights
      setSelectedNodeId(nodeId);
      try {
        const detail = await api.getEntity(nodeId);
        setNodeDetail(detail);
      } catch (err) {
        console.error('Failed to load entity:', err);
      }
      return;
    }
    await selectAndHighlight(nodeId);
  }, [scenarioActive, selectAndHighlight]);

  const handleBackgroundClick = useCallback(() => {
    setSelectedNodeId(null);
    setNodeDetail(null);
    if (!scenarioActive) {
      setHighlightedNodeIds(new Set());
      setHighlightedEdgeKeys(new Set());
      setCascade(null);
    }
  }, [scenarioActive]);

  const navigateToEntity = useCallback(async (entityId: string) => {
    graphRef.current?.focusNode(entityId);
    await selectAndHighlight(entityId);
  }, [selectAndHighlight]);

  const clearHighlights = useCallback(() => {
    setHighlightedNodeIds(new Set());
    setHighlightedEdgeKeys(new Set());
    setCascade(null);
  }, []);

  const handleClearCascade = useCallback(() => {
    setCascade(null);
    setHighlightedNodeIds(new Set());
    setHighlightedEdgeKeys(new Set());
  }, []);

  const handlePathsFound = useCallback((nodeIds: Set<string>, edgeKeys: Set<string>) => {
    setHighlightedNodeIds(nodeIds);
    setHighlightedEdgeKeys(edgeKeys);
  }, []);

  const handleNodeDoubleClick = useCallback((nodeId: string) => {
    if (!graphData) return;
    const node = graphData.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    // Only allow collapse on PolicySection and PolicyRule types
    if (node.type === 'PolicySection' || node.type === 'PolicyRule') {
      setCollapsedNodeIds((prev) => {
        const next = new Set(prev);
        if (next.has(nodeId)) next.delete(nodeId);
        else next.add(nodeId);
        return next;
      });
    }
  }, [graphData]);

  const handleFitToScreen = useCallback(() => {
    setSelectedNodeId(null);
    setNodeDetail(null);
    if (!scenarioActive) {
      setHighlightedNodeIds(new Set());
      setHighlightedEdgeKeys(new Set());
      setCascade(null);
    }
    graphRef.current?.fitToScreen();
  }, [scenarioActive]);

  // Scenario callbacks
  const handleScenarioActivate = useCallback((active: boolean) => {
    setScenarioActive(active);
    setSelectedNodeId(null);
    setNodeDetail(null);
    if (!active) {
      setRevealedNodeIds(new Set());
      setRevealedEdgeKeys(new Set());
      setHighlightedNodeIds(new Set());
      setHighlightedEdgeKeys(new Set());
      graphRef.current?.fitToScreen();
    }
  }, []);

  const handleScenarioStep = useCallback((update: ScenarioUpdate) => {
    setRevealedNodeIds(update.revealedNodeIds);
    setRevealedEdgeKeys(update.revealedEdgeKeys);
    setHighlightedNodeIds(update.currentNodeIds);
    setHighlightedEdgeKeys(update.currentEdgeKeys);
    // Fit camera to the current step's nodes
    const stepNodes = [...update.currentNodeIds];
    if (stepNodes.length > 0) {
      graphRef.current?.fitToNodes(stepNodes);
    }
  }, []);

  const isDetailOpen = nodeDetail !== null;
  const typeColors = graphData?.type_colors || {};

  return (
    <div className={`app ${isDetailOpen ? 'detail-open' : ''}`}>
      <TopBar
        stats={stats}
        typeColors={typeColors}
        graphTitle={graphData?.graph_title || ''}
        onEntitySelect={navigateToEntity}
        onFitToScreen={handleFitToScreen}
        onClearHighlights={clearHighlights}
        onGraphSwitch={handleGraphSwitch}
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
          cascade={cascade}
          onClearCascade={handleClearCascade}
          scenarios={scenarios}
          onScenarioActivate={handleScenarioActivate}
          onScenarioStep={handleScenarioStep}
        />
      </div>

      <div className="graph-area">
        <GraphCanvas
          ref={graphRef}
          graphData={graphData}
          selectedNodeId={selectedNodeId}
          highlightedNodeIds={highlightedNodeIds}
          highlightedEdgeKeys={highlightedEdgeKeys}
          collapsedNodeIds={collapsedNodeIds}
          scenarioActive={scenarioActive}
          revealedNodeIds={revealedNodeIds}
          revealedEdgeKeys={revealedEdgeKeys}
          onNodeClick={handleNodeClick}
          onBackgroundClick={handleBackgroundClick}
          onNodeDoubleClick={handleNodeDoubleClick}
        />
        <Legend stats={stats} typeColors={typeColors} />
      </div>

      <div className="right-panel">
        <NodeDetailPanel
          detail={nodeDetail}
          graphNode={nodeDetail && graphData ? graphData.nodes.find((n) => n.id === nodeDetail.id) : undefined}
          typeColors={typeColors}
          onClose={handleBackgroundClick}
          onEntitySelect={navigateToEntity}
        />
      </div>
    </div>
  );
}
