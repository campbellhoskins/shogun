export interface GraphNode {
  id: string;
  type: string;
  name: string;
  description: string;
  degree: number;
  color: string;
}

export interface GraphEdge {
  from_id: string;
  to_id: string;
  type: string;
  description: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  source_document: string;
  type_colors: Record<string, string>;
}

export interface GraphStats {
  source_document: string;
  entity_count: number;
  relationship_count: number;
  entity_types: Record<string, number>;
}

export interface EntitySummary {
  id: string;
  type: string;
  name: string;
  description: string;
}

export interface RelationshipDetail {
  direction: 'outgoing' | 'incoming';
  relationship_type: string;
  entity_id: string;
  entity_name: string;
  entity_type: string;
  description: string;
}

export interface EntityDetail {
  id: string;
  type: string;
  name: string;
  description: string;
  attributes: Record<string, unknown>;
  source_text: string;
  source_section: string;
  source_offset: number;
  relationships: RelationshipDetail[];
}

export interface PathStep {
  from_id: string;
  from_name: string;
  relationship_type: string;
  direction: 'forward' | 'backward';
  to_id: string;
  to_name: string;
}

export interface PathResponse {
  paths: PathStep[][];
  source_name: string;
  target_name: string;
}

export interface AgentAnswer {
  answer: string;
  referenced_entities: EntitySummary[];
  reasoning_path: string;
}

export interface ChatMessage {
  role: 'user' | 'agent';
  content: string;
  referenced_entities?: EntitySummary[];
  timestamp: number;
}
