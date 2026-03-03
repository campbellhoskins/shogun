/** Node shape mapping by entity type for vis-network (21 schema types) */
export const TYPE_SHAPES: Record<string, string> = {
  // Core Policy — hexagons
  Policy: 'hexagon',
  PolicySection: 'hexagon',
  PolicyRule: 'hexagon',
  PolicyException: 'hexagon',
  // Actors & Stakeholders — triangles
  TravelerRole: 'triangle',
  Stakeholder: 'triangle',
  ServiceProvider: 'triangle',
  // Travel Options — squares/stars
  TransportationMode: 'square',
  ClassOfService: 'square',
  Accommodation: 'square',
  BusinessContext: 'square',
  TravelEvent: 'star',
  GeographicScope: 'square',
  // Financial — dots
  ExpenseCategory: 'dot',
  ReimbursementLimit: 'dot',
  PaymentMethod: 'dot',
  PriorityOrder: 'dot',
  // Compliance — diamonds
  Constraint: 'diamond',
  Requirement: 'diamond',
  Consequence: 'diamond',
};

export const DEFAULT_SHAPE = 'dot';

/** Entity group display order and member types */
export const ENTITY_GROUPS: Record<string, string[]> = {
  'Core Policy': ['Policy', 'PolicySection', 'PolicyRule', 'PolicyException'],
  'Actors & Stakeholders': ['TravelerRole', 'Stakeholder', 'ServiceProvider'],
  'Travel Options': ['TransportationMode', 'ClassOfService', 'Accommodation', 'BusinessContext', 'TravelEvent', 'GeographicScope'],
  'Financial': ['ExpenseCategory', 'ReimbursementLimit', 'PaymentMethod', 'PriorityOrder'],
  'Compliance': ['Constraint', 'Requirement', 'Consequence'],
};

/** Hierarchical left-to-right layout configuration */
export const LAYOUT_OPTIONS = {
  hierarchical: {
    enabled: true,
    direction: 'LR' as const,
    sortMethod: 'directed' as const,
    levelSeparation: 250,
    nodeSpacing: 120,
    treeSpacing: 200,
    blockShifting: true,
    edgeMinimization: true,
    parentCentralization: true,
  },
};

/** vis-network physics configuration for hierarchical layout */
export const PHYSICS_OPTIONS = {
  solver: 'hierarchicalRepulsion' as const,
  hierarchicalRepulsion: {
    centralGravity: 0.0,
    springLength: 150,
    springConstant: 0.01,
    nodeDistance: 140,
    damping: 0.09,
    avoidOverlap: 0.5,
  },
  stabilization: {
    iterations: 200,
  },
};
