/** Node shape mapping by entity type for vis-network */
export const TYPE_SHAPES: Record<string, string> = {
  PolicyRule: 'hexagon',
  Policy: 'hexagon',
  Role: 'triangle',
  Person: 'dot',
  Definition: 'diamond',
  Threshold: 'square',
  Procedure: 'dot',
  RiskLevel: 'triangleDown',
  Destination: 'star',
  Location: 'star',
  ApprovalRequirement: 'diamond',
  Requirement: 'diamond',
  InsuranceRequirement: 'diamond',
  VaccinationRequirement: 'diamond',
  IncidentCategory: 'triangleDown',
  Incident: 'triangleDown',
  CommunicationRequirement: 'diamond',
  ContactInformation: 'dot',
  Equipment: 'square',
  Vendor: 'dot',
  Organization: 'hexagon',
  GovernanceBody: 'triangle',
  Training: 'dot',
  BenefitOrPackage: 'dot',
};

export const DEFAULT_SHAPE = 'dot';

/** vis-network physics configuration */
export const PHYSICS_OPTIONS = {
  solver: 'forceAtlas2Based' as const,
  forceAtlas2Based: {
    gravitationalConstant: -80,
    centralGravity: 0.01,
    springLength: 150,
    springConstant: 0.02,
    damping: 0.4,
  },
  stabilization: {
    iterations: 200,
  },
};
