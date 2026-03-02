import type { GraphNode, ChatMessage } from '../types';
import PathFinder from './PathFinder';
import AgentChat from './AgentChat';
import '../styles/LeftPanel.css';

interface Props {
  activeTab: 'pathfinder' | 'chat';
  onTabChange: (tab: 'pathfinder' | 'chat') => void;
  nodes: GraphNode[];
  typeColors: Record<string, string>;
  onPathsFound: (nodeIds: Set<string>, edgeKeys: Set<string>) => void;
  onClearPaths: () => void;
  onEntitySelect: (entityId: string) => void;
  chatMessages: ChatMessage[];
  onChatMessagesChange: (messages: ChatMessage[]) => void;
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
        ) : (
          <AgentChat
            messages={chatMessages}
            onMessagesChange={onChatMessagesChange}
            typeColors={typeColors}
            onEntitySelect={onEntitySelect}
          />
        )}
      </div>
    </div>
  );
}
