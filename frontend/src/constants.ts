/** Node shape mapping by entity type for vis-network.
 *
 * Covers both the original policy schema types AND the duty-of-care
 * entity types from src/schemas.py (Organization, Service, etc.)
 */
export const TYPE_SHAPES: Record<string, string> = {
  // ── Original Policy Schema ──────────────────────────────
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

  // ── Duty-of-Care Schema (src/schemas.py) ────────────────
  // Contractual — hexagons
  Agreement: 'hexagon',
  Obligation: 'hexagon',
  Regulation: 'hexagon',
  // Organizations & Roles — triangles
  Organization: 'triangle',
  ContactRole: 'triangle',
  Traveler: 'triangle',
  // Services & Platforms — squares
  Service: 'square',
  Platform: 'square',
  BookingChannel: 'square',
  Booking: 'square',
  // Risk & Incidents — stars/diamonds
  Incident: 'star',
  SeverityLevel: 'diamond',
  RiskCategory: 'diamond',
  // Alerts & Communication — triangleDown
  Alert: 'triangleDown',
  TravelerResponseStatus: 'triangleDown',
  // Data — dots
  DataElement: 'dot',
};

export const DEFAULT_SHAPE = 'dot';

/** Entity group display order and member types.
 *
 * Covers both old policy types and new duty-of-care schema types.
 * Types not listed here fall into an auto-generated "Other" group.
 */
export const ENTITY_GROUPS: Record<string, string[]> = {
  // Original policy groups
  'Core Policy': ['Policy', 'PolicySection', 'PolicyRule', 'PolicyException'],
  'Actors & Stakeholders': ['TravelerRole', 'Stakeholder', 'ServiceProvider'],
  'Travel Options': ['TransportationMode', 'ClassOfService', 'Accommodation', 'BusinessContext', 'TravelEvent', 'GeographicScope'],
  'Financial': ['ExpenseCategory', 'ReimbursementLimit', 'PaymentMethod', 'PriorityOrder'],
  'Compliance': ['Constraint', 'Requirement', 'Consequence'],
  // Duty-of-care groups
  'Contractual': ['Agreement', 'Obligation', 'Regulation'],
  'Organizations & Roles': ['Organization', 'ContactRole', 'Traveler'],
  'Services & Platforms': ['Service', 'Platform', 'BookingChannel', 'Booking'],
  'Risk & Incidents': ['Incident', 'SeverityLevel', 'RiskCategory'],
  'Alerts & Data': ['Alert', 'TravelerResponseStatus', 'DataElement'],
};

/** Force-directed layout — works for any graph topology.
 *
 * The old hierarchical LR layout only works for tree-shaped data.
 * For knowledge graphs (flat, many cross-links), force-directed is correct.
 */
export const LAYOUT_OPTIONS = {
  hierarchical: false as const,
};

/** vis-network physics for force-directed layout */
export const PHYSICS_OPTIONS = {
  solver: 'forceAtlas2Based' as const,
  forceAtlas2Based: {
    gravitationalConstant: -80,
    centralGravity: 0.01,
    springLength: 160,
    springConstant: 0.08,
    damping: 0.4,
    avoidOverlap: 0.8,
  },
  stabilization: {
    iterations: 300,
    updateInterval: 25,
  },
  maxVelocity: 50,
  minVelocity: 0.75,
};
