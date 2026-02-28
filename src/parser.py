from __future__ import annotations

import json

from anthropic import Anthropic

from src.models import OntologyGraph
from src.pipeline import extract_ontology

# Legacy prompt kept for A/B comparison
LEGACY_EXTRACTION_SYSTEM_PROMPT = """\
You are an expert ontology engineer specializing in corporate travel compliance.

Your task: Given a corporate travel policy document, extract ALL entities and relationships into a structured ontology graph.

## Entity Types to Extract

- **PolicyRule**: A specific rule, requirement, or restriction stated in the policy (e.g., "Level 4 travel prohibited", "Manager approval required for Level 2")
- **RiskLevel**: A destination risk classification tier (Level 1 through Level 4)
- **ApprovalRequirement**: Who must approve travel and under what conditions
- **InsuranceRequirement**: Specific insurance coverage minimums or requirements
- **VaccinationRequirement**: Required vaccinations for specific destinations or regions
- **Destination**: A specific country, region, or destination category mentioned
- **Role**: An organizational role involved in the policy (e.g., Travel Risk Manager, CSO, direct manager)
- **Person**: A specific named individual mentioned in the policy
- **Vendor**: An approved or mentioned vendor (airline, hotel chain, security firm, etc.)
- **Procedure**: A defined process or workflow (e.g., evacuation procedure, check-in procedure)
- **IncidentCategory**: A classification of incidents (Category 1, 2, 3)
- **CommunicationRequirement**: Check-in frequency or communication obligations
- **Equipment**: Required equipment or technology (satellite phone, GPS tracker, etc.)

## Relationship Types to Use

- **requires**: Entity A requires Entity B (e.g., RiskLevel 3 requires VP approval)
- **applies_to**: Rule applies to a destination, role, or risk level
- **triggers**: An event or condition triggers a procedure or escalation
- **escalates_to**: One role escalates to another in the chain
- **prohibits**: A rule prohibits an action
- **permits**: A rule permits an action under conditions
- **provides**: An entity provides a service or coverage
- **classified_as**: A destination is classified as a risk level
- **managed_by**: A process is managed by a role
- **part_of**: Entity is part of a larger entity or process

## Output Format

Return a JSON object with exactly this structure:
{
  "entities": [
    {
      "id": "unique_snake_case_id",
      "type": "EntityType",
      "name": "Human Readable Name",
      "description": "Brief description of this entity as stated in the policy",
      "attributes": {"key": "value"}
    }
  ],
  "relationships": [
    {
      "source_id": "entity_id_1",
      "target_id": "entity_id_2",
      "type": "relationship_type",
      "description": "Brief description of this relationship"
    }
  ]
}

## Guidelines

- Extract EVERY distinct rule, requirement, threshold, and procedure — be thorough.
- Each entity must have a unique, descriptive snake_case ID.
- Use attributes to capture specific values (e.g., {"coverage_amount": "$500,000", "risk_level": "2"}).
- Every entity should participate in at least one relationship.
- Capture the approval chain and escalation hierarchy as explicit relationships.
- Return ONLY the JSON object, no other text.
"""


def parse_policy(policy_text: str, client: Anthropic | None = None) -> OntologyGraph:
    """Parse a policy document into an OntologyGraph.

    Delegates to the Source-Anchored Extraction pipeline.
    For the legacy single-pass extraction, use parse_policy_legacy().
    """
    return extract_ontology(policy_text, client=client)


def parse_policy_legacy(
    policy_text: str, client: Anthropic | None = None
) -> OntologyGraph:
    """Legacy single-pass extraction. Kept for comparison/benchmarking."""
    if client is None:
        client = Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16384,
        system=LEGACY_EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the complete ontology graph from this corporate "
                    f"travel duty of care policy:\n\n{policy_text}"
                ),
            }
        ],
    )

    raw_text = response.content[0].text

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)

    data = json.loads(raw_text)
    return OntologyGraph(**data)
