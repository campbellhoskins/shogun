import type { GraphNode, ChatMessage, CascadeResponse, Scenario } from '../types';
import PathFinder from './PathFinder';
import AgentChat from './AgentChat';
import CascadePanel from './CascadePanel';
import ScenarioPanel from './ScenarioPanel';
import '../styles/LeftPanel.css';

export type LeftTabType = 'pathfinder' | 'chat' | 'cascade' | 'scenarios';

interface Props {
  activeTab: LeftTabType;
  onTabChange: (tab: LeftTabType) => void;
  nodes: GraphNode[];
  typeColors: Record<string, string>;
  onPathsFound: (nodeIds: Set<string>, edgeKeys: Set<string>) => void;
  onClearPaths: () => void;
  onEntitySelect: (entityId: string) => void;
  chatMessages: ChatMessage[];
  onChatMessagesChange: (messages: ChatMessage[]) => void;
  cascade: CascadeResponse | null;
  onClearCascade: () => void;
  scenarios: Scenario[];
  onHighlight: (nodeIds: Set<string>, edgeKeys: Set<string>) => void;
  onClearHighlights: () => void;
}

export default function LeftPanel({
  activeTab,
  onTabChange,
  nodes,
  typeColors,
  onPathsFound,
  onClearPaths,
  onEntitySelect,
  chatMessages,
  onChatMessagesChange,
  cascade,
  onClearCascade,
  scenarios,
  onHighlight,
  onClearHighlights,
}: Props) {
  return (
    <div className="left-panel-inner">
      <div className="left-panel-tabs">
        <button
          className={`left-panel-tab ${activeTab === 'pathfinder' ? 'active' : ''}`}
          onClick={() => onTabChange('pathfinder')}
        >
          Path Finder
        </button>
        <button
          className={`left-panel-tab ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => onTabChange('chat')}
        >
          Agent
        </button>
        <button
          className={`left-panel-tab ${activeTab === 'cascade' ? 'active' : ''}`}
          onClick={() => onTabChange('cascade')}
        >
          Cascade
        </button>
        <button
          className={`left-panel-tab ${activeTab === 'scenarios' ? 'active' : ''}`}
          onClick={() => onTabChange('scenarios')}
        >
          Scenarios
        </button>
      </div>
      <div className="left-panel-content">
        {activeTab === 'pathfinder' ? (
          <PathFinder
            nodes={nodes}
            typeColors={typeColors}
            onPathsFound={onPathsFound}
            onClearPaths={onClearPaths}
            onEntitySelect={onEntitySelect}
          />
        ) : activeTab === 'chat' ? (
          <AgentChat
            messages={chatMessages}
            onMessagesChange={onChatMessagesChange}
            typeColors={typeColors}
            onEntitySelect={onEntitySelect}
          />
        ) : activeTab === 'cascade' ? (
          <CascadePanel
            cascade={cascade}
            typeColors={typeColors}
            onEntitySelect={onEntitySelect}
            onClearCascade={onClearCascade}
          />
        ) : (
          <ScenarioPanel
            scenarios={scenarios}
            onHighlight={onHighlight}
            onClearHighlights={onClearHighlights}
            onFocusNode={onEntitySelect}
          />
        )}
      </div>
    </div>
  );
}
