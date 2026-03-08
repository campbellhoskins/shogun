Complete Pipeline Assessment and Remediation Plan
1. The Operational Problem
The knowledge graph is intended to support TMC agents making real-time decisions during travel incidents: determining response obligations, timing requirements, escalation paths, outreach procedures, and authorization constraints based on the duty of care policy. An agent facing a Level 3 security incident in a traveler's destination needs to traverse the graph and get actionable answers — not parse natural language descriptions.
Current effectiveness for this use case: ~30-40%. The graph functions as a contractual reference map but fails as an operational decision engine.

2. Current Pipeline Limitations
2.1 Entity Collapse
The extraction produces a single severity_level entity representing all four levels. Since the entire operational response pivots on which level applies — different timing obligations, different escalation contacts, different service activations, different Crisis Bridge requirements — collapsing them into one entity makes level-specific graph traversal impossible. An agent cannot query "what are my Level 3 obligations?" and get a structured answer.
The same collapse affects alert templates (all levels and channels merged into generic service entities), traveler response statuses (extracted but without structured action/timing data), and contact roles (extracted but without structured severity-level linkage).
2.2 Typed Attributes Not Populated
The entity schemas already contain well-designed typed attribute fields. SeverityLevelEntity has alert_time_target, client_escalation_time_target, status_update_cadence, and crisis_bridge_required. ObligationEntity has conditionality, obligated_party, and obligation_type. AlertEntity has channel, alert_type, and attempt_number.
None of these fields are populated in the extraction output. The LLM produces bare entities with only id, type, name, and description because the entity extraction prompt only asks for those four fields. All operational data — SLO timing, conditional triggers, channel configuration, authorization requirements — gets stuffed into the unstructured description string where it cannot be queried programmatically.
2.3 Structural Relationship Bias
Approximately 75% of extracted relationships serve contractual and document-navigation purposes (DEFINED_IN, PARTY_TO, INCORPORATES, COMPLIES_WITH, ASSIGNED_TO). Only ~25% directly support real-time agent decisions (ACTIVATED_AT, ESCALATED_TO, TRIGGERS_ACTION, REQUIRES_AUTHORIZATION_FROM). The extraction prompt provides no guidance on prioritization, so the LLM defaults to what looks important in a legal document — structural hierarchy, not operational logic.
2.4 No Procedural Sequencing
The graph captures what must happen but not in what order. The welfare check outreach sequence (SMS → Email → Push → Voice), the escalation procedure (attempt contact → log outcome → escalate if non-responsive), and the Crisis Bridge workflow (establish bridge → deliver SITREPs → coordinate response) are all described in the document but not represented as ordered steps in the graph. The relationship types lack any sequencing mechanism.
2.5 Missing Conditional Logic
Escalation paths depend on conditions that the graph cannot represent. Corporate Security is contacted only for security-related incidents at Level 3+. The After-Hours Duty Contact is engaged only outside Business Hours. Human Resources is engaged only for employee welfare, injury, or fatality incidents. These conditions exist in entity descriptions but not in queryable form.

3. Root Cause Analysis
The pipeline has three layers where problems originate:
LayerIssueEffectPromptsEntity extraction prompt does not expose typed attribute fields to the LLMAttributes exist in Pydantic schemas but are never populatedPromptsNo decomposition guidance for multi-instance entity typesLLM creates one severity_level instead of fourPromptsNo operational prioritization in relationship extractionStructural relationships dominate over operational onesSchema gapsTravelerResponseStatusEntity has no action/timing attributesTMC follow-up actions are not queryableSchema gapsContactRoleEntity has no severity-level or condition attributesEscalation routing is not queryableSchema gapsServiceEntity has no activation threshold or authorization attributesService activation logic is not queryableSchema gapsAlertEntity has no severity-level linkage or channel priority orderAlert-to-level and channel-sequence lookup is not possibleMerge pipelineAttribute conflict resolution turns typed fields into listsSchema type violations on merged entitiesMerge pipelineSemantic dedup does not see typed attributesCannot distinguish structurally different instances of the same typeMerge pipelineNo anti-merge rules for decomposed instancesDedup may re-collapse the four severity levels into one

4. Proposed Changes
4.1 Schema Additions
These are targeted attribute additions to four existing entity schemas. No new entity types are needed.
TravelerResponseStatusEntity — Add four fields:
pythonCopytmc_action: str = Field(
    default="",
    description=(
        "The specific follow-up action the TMC must take when a traveler "
        "returns this status (e.g., 'Attempt live contact within 15 minutes; "
        "provide assistance per Section 3.5')."
    ),
)
action_time_target: str = Field(
    default="",
    description=(
        "Time constraint on the TMC's follow-up action, if any "
        "(e.g., '15 minutes' for NEED ASSISTANCE live contact)."
    ),
)
closes_outreach: Optional[bool] = Field(
    default=None,
    description=(
        "Whether this response removes the traveler from active outreach "
        "for this incident (True for SAFE and NOT IN AREA)."
    ),
)
triggers_escalation: Optional[bool] = Field(
    default=None,
    description=(
        "Whether this status triggers escalation to Client contacts "
        "(True for NO RESPONSE after outreach window)."
    ),
)
ContactRoleEntity — Add three fields:
pythonCopyescalation_severity_levels: list[int] = Field(
    default=[],
    description=(
        "Severity levels at which this contact role is engaged "
        "(e.g., [3, 4] for Corporate Security)."
    ),
)
escalation_condition: str = Field(
    default="",
    description=(
        "Additional condition beyond severity level that triggers "
        "engagement (e.g., 'security-related incidents', 'outside "
        "Business Hours', 'employee welfare, injury, or fatality')."
    ),
)
roster_position: str = Field(
    default="",
    description=(
        "Role in escalation sequence: Primary | Backup | Conditional | CrisisOnly"
    ),
)
ServiceEntity — Add three fields:
pythonCopyactivation_severity_threshold: Optional[int] = Field(
    default=None,
    description=(
        "Minimum severity level at which this service activates "
        "(e.g., 2 for Incident Response, 4 for Crisis Bridge). "
        "None if always active."
    ),
)
requires_client_authorization: Optional[bool] = Field(
    default=None,
    description=(
        "Whether this service requires express Client authorization "
        "before the TMC may proceed."
    ),
)
authorization_details: str = Field(
    default="",
    description=(
        "Specific actions within this service that require authorization "
        "and any SOW exceptions."
    ),
)
AlertEntity — Add two fields:
pythonCopyseverity_level: Optional[int] = Field(
    default=None,
    description=(
        "The severity level this alert template corresponds to (1-4), "
        "enabling direct lookup of which alert type applies at which severity."
    ),
)
channel_priority_order: Optional[int] = Field(
    default=None,
    description=(
        "Priority rank of this channel in the outreach sequence "
        "(1=highest priority, attempted first). Default order: "
        "1=SMS, 2=Email, 3=MobileAppPush, 4=VoiceCall."
    ),
)
4.2 Entity Extraction Prompt Changes
Change 1: Expose typed attributes in the entity type reference.
Replace the flat entity type list with a schema-aware reference that shows the LLM what attributes each type has and expects. This is the single highest-impact change — it bridges the gap between the Pydantic schemas and the LLM's extraction behavior.
xmlCopy<entity_types>
Each entity type has specific typed attributes beyond the base fields
(id, type, name, description, source_anchor). You MUST populate these
attributes when extracting entities of that type.

SeverityLevel
  IMPORTANT: Create a SEPARATE entity for EACH severity level in the
  document. Do NOT collapse multiple levels into one entity.
  Attributes:
    level (int): 1, 2, 3, or 4
    classification (str): Advisory | Monitor | ActionRequired | Crisis
    alert_time_target (str): SLO for traveler outreach initiation
    client_escalation_time_target (str): SLO for client escalation
    status_update_cadence (str): Required status update frequency
    crisis_bridge_required (bool): Whether Crisis Bridge is mandatory

TravelerResponseStatus
  Attributes:
    tmc_action (str): Specific follow-up action the TMC must take
    action_time_target (str): Time constraint on follow-up action
    closes_outreach (bool): Whether this response ends active outreach
    triggers_escalation (bool): Whether this triggers Client escalation

ContactRole
  Attributes:
    escalation_severity_levels (list[int]): Levels triggering engagement
    escalation_condition (str): Condition beyond severity for engagement
    roster_position (str): Primary | Backup | Conditional | CrisisOnly

Service
  Attributes:
    activation_severity_threshold (int): Minimum severity for activation
    requires_client_authorization (bool): Whether authorization needed
    authorization_details (str): Actions requiring authorization

Alert
  Attributes:
    alert_type (str): Advisory | WelfareCheck | EscalationNotification | SITREP
    severity_level (int): Which severity level this alert applies to
    channel (str): SMS | Email | VoiceCall | MobileAppPush
    channel_priority_order (int): Priority rank in outreach sequence
    content (str): Message template or reference

Obligation
  Attributes:
    obligation_type (str): Operational | Data | Policy | Financial | Authorization
    obligated_party (str): TMC | Client
    conditionality (str): When the obligation applies
    section_reference (str): Document section defining this obligation

Booking
  Attributes:
    capture_method (str): DirectBooking | EmailParsing | SupplierFeed
    segments (list[str]): Segment types (air, hotel, rail, car, ground)
    status (str): Active | Modified | Cancelled

Organization, Agreement, Traveler, Incident, Regulation, Platform,
BookingChannel, RiskCategory, DataElement
  (Base fields only: id, type, name, description)
</entity_types>
Change 2: Add decomposition rules.
Add to the entity extraction system prompt to prevent entity collapse:
xmlCopy<decomposition_rules>
SEVERITY LEVELS: If the document defines multiple severity levels
(e.g., Level 1 through Level 4), create a SEPARATE entity for each
level. Each level carries distinct obligations and must be
independently addressable in the graph.

ALERT TEMPLATES: If the document provides message templates per
severity level and per channel, extract each template as a separate
Alert entity with severity_level, channel, and channel_priority_order
populated.

TRAVELER RESPONSE STATUSES: Extract each status as a separate entity
with tmc_action, action_time_target, closes_outreach, and
triggers_escalation populated from the document's response action
tables.

CONTACT ROLES: Extract each escalation roster role with
escalation_severity_levels and escalation_condition populated
from the escalation tables and procedures.
</decomposition_rules>
Change 3: Add attribute population quality instruction.
Add to the entity extraction system prompt to prevent empty typed fields:
xmlCopy<attribute_quality>
ATTRIBUTE POPULATION IS MANDATORY for typed entity schemas.

When extracting a SeverityLevel entity, leaving alert_time_target
empty when the document specifies "within 60 minutes" is a critical
extraction failure — it forces downstream consumers to parse the
description string, defeating the purpose of typed attributes.

Rule: If the document text provides a value that maps to a typed
attribute field, that field MUST be populated. The description field
captures context and nuance; typed attributes capture queryable facts.

ANTI-PATTERN: Putting "SLO for outreach is within 30 minutes" in
description while leaving alert_time_target="" empty.

CORRECT: alert_time_target="within 30 minutes" AND description
captures additional context like exceptions or conditions.
</attribute_quality>
Change 4: Add operational use-case context.
Add to both entity and relationship system prompts:
xmlCopy<graph_purpose>
This knowledge graph will be used by TMC agents during live incident
response to answer operational questions such as:
- "A Level 3 security incident just occurred — what are my timing
  obligations and who do I escalate to?"
- "The traveler replied NEED ASSISTANCE — what do I do next and
  how quickly?"
- "This booking was made off-channel — what services can I provide?"
- "It has been 90 minutes with no response — what is my next step?"

Prioritize extracting entities and relationships that support these
real-time decisions. Document-structural facts (which section defines
a term, which agreement incorporates another) are lower priority.
</graph_purpose>
Change 5: Update the output schema to include typed attributes.
The current output schema instruction only lists id, type, name, description, source_anchor. It must be updated to include typed attributes:
xmlCopy<output_schema>
Produce a single JSON object with one key: "entities" containing an array.

Each entity requires:
- id: lowercase_with_underscores, descriptive
- type: one of the types above
- name: concise human-readable name
- description: what this entity represents, grounded in section text
- source_anchor: object with source_text and source_section
- All typed attributes defined for the entity's type (see entity_types
  above). Populate every attribute for which the section text provides
  a value.

Produce ONLY the JSON object.
</output_schema>
4.3 Relationship Extraction Prompt Changes
Change 1: Add operational prioritization.
xmlCopy<operational_priority>
EXTRACTION PRIORITY ORDER:
1. HIGHEST — Operational relationships: ACTIVATED_AT, ESCALATED_TO,
   TRIGGERS_ACTION, REQUIRES_AUTHORIZATION_FROM, SENT_TO, TRIGGERED_BY
2. HIGH — Service delivery: PROVIDES, ENABLED_BY, ENABLES_COVERAGE,
   REQUIRES_DATA, RESPONDS_WITH
3. MEDIUM — Classification: CLASSIFIED_AS, CATEGORIZED_AS, IMPACTS,
   BOOKED_THROUGH, HAS_BOOKING, ENGAGES
4. LOWER — Structural: DEFINED_IN, PARTY_TO, INCORPORATES,
   COMPLIES_WITH, ASSIGNED_TO, DESIGNATED_BY, RELATES_TO, OPERATES

Extract ALL valid relationships, but if you find yourself generating
many DEFINED_IN or PARTY_TO relationships without corresponding
operational relationships from the same text, re-read for operational
content you may have missed.
</operational_priority>
Change 2: Add attribute-awareness guidance.
xmlCopy<attribute_awareness>
Entity schemas carry typed attributes that encode many operational
facts (SLO timing, activation thresholds, channel priority, TMC
actions, conditional triggers). Do NOT create relationships solely
to duplicate information already captured in entity attributes.

Focus relationships on connections BETWEEN entities that attributes
cannot capture: which services activate at which severity levels,
which contact roles receive escalations at which levels, which
incidents impact which travelers, which response statuses trigger
which services, which booking channels enable which services.
</attribute_awareness>

5. Downstream Problems These Changes Create
The changes in Section 4 produce richer, more operationally useful entities. However, they interact badly with the current merge pipeline in five specific ways.
5.1 Typed Attribute Wording Variation Produces Schema-Violating Lists
The problem. When severity_level_3 is extracted from multiple sections, each section's LLM call populates alert_time_target with natural language wording variation. SEC-05 produces "within 60 minutes", SEC-06 produces "60 minutes", SEC-03 produces "initiate Traveler outreach within 60 minutes". These are semantically identical but string-unequal.
The current merge logic treats string-unequal values as conflicts and stores them as a list:
pythonCopyif len(unique_values) == 1:
    entity_dict[k] = unique_values[0]
else:
    entity_dict[k] = unique_values  # str field becomes list[str]
This violates the Pydantic schema type declarations. alert_time_target: str receives a list[str]. crisis_bridge_required: Optional[bool] receives [True, None]. The validate_entity call either rejects the entity (falling back to the canonical-only version, losing merged attributes) or coerces unpredictably.
The fix. Replace the equal-weight conflict resolution with a primary-source-wins strategy. The section where an entity is defined (not merely referenced) provides authoritative attribute values. Other sections can only fill gaps where the primary source left attributes empty.
pythonCopydef _merge_entity_group(group: list[BaseEntitySchema]) -> BaseEntitySchema:
    group.sort(key=lambda e: len(e.description), reverse=True)
    
    # Identify the primary source: the section that defines the entity
    # (longest source_anchor text as proxy for definitional context)
    primary = max(group, key=lambda e: len(e.source_anchor.source_text or ""))
    
    # Start with primary's typed attributes as authoritative
    merged_attrs = {}
    for k, v in get_typed_attributes(primary).items():
        if v is not None and v != "" and v != []:
            merged_attrs[k] = v
    
    # Fill gaps only — never override primary's values
    for e in group:
        if e is primary:
            continue
        for k, v in get_typed_attributes(e).items():
            if k not in merged_attrs and v is not None and v != "" and v != []:
                merged_attrs[k] = v
    
    # Build merged entity with authoritative attributes
    entity_dict = {
        "id": primary.id,
        "type": primary.type,
        "name": primary.name,
        "description": _merge_descriptions(group),
        "source_anchor": _merge_source_anchors(group)[0].model_dump(),
        "source_anchors": [a.model_dump() for a in _merge_source_anchors(group)],
        "appears_in": sorted(set(s for e in group for s in e.appears_in)),
    }
    entity_dict.update(merged_attrs)
    
    entity, warnings = validate_entity(entity_dict)
    return entity if entity is not None else primary
This guarantees every typed field contains a single value of the correct type. No lists, no schema violations, no validation fallbacks.
5.2 Semantic Dedup Re-Collapses Decomposed Entities
The problem. The semantic dedup LLM sees four SeverityLevel entities with similar names (severity_level_1 through severity_level_4), similar descriptions ("A tier within the incident classification system..."), and the same type. The current dedup rules say to merge entities with "Name Match with Variation: Names that differ only in abbreviation, punctuation, suffix" and "Description Overlap: Descriptions that describe the same real-world thing." Numeric suffixes and similar descriptions give the LLM strong incentive to merge these back into one entity, directly undoing the decomposition.
The same risk applies to per-level per-channel alert entities, which share type and similar descriptions but differ by severity_level and channel attributes.
The fix. Two changes to the semantic dedup step.
First, add anti-merge rules to the dedup system prompt:
xmlCopy<critical_anti_merge_rules>
NUMBERED OR LEVELED ENTITIES: Entities that represent different
levels, tiers, or ranks within a classification system are NEVER
duplicates, even though they share the same type and similar
descriptions.
  - severity_level_1 through severity_level_4 are FOUR DISTINCT entities
  - alert_level_3_sms and alert_level_4_sms are DISTINCT

CHANNEL-SPECIFIC ENTITIES: Entities of the same type that differ
by communication channel are NEVER duplicates:
  - alert_level_3_sms and alert_level_3_email are DISTINCT

PARAMETERIZED INSTANCES: If two entities have the same type but
different values in any typed attribute field (level, channel,
severity_level, classification, escalation_severity_levels),
they are NOT duplicates regardless of name or description similarity.
</critical_anti_merge_rules>
Second, include typed attributes in the dedup input so the LLM can see structural differences:
pythonCopydef _build_dedup_entity_list(entities: list[BaseEntitySchema]) -> str:
    entity_dicts = []
    for e in entities:
        d = {
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description[:200],  # truncate to reduce noise
            "appears_in": e.appears_in,
        }
        typed = get_typed_attributes(e)
        if typed:
            d["attributes"] = {
                k: v for k, v in typed.items()
                if v is not None and v != "" and v != []
            }
        entity_dicts.append(d)
    return json.dumps(entity_dicts, indent=2)
When the dedup LLM sees {"level": 3, "classification": "ActionRequired"} next to {"level": 4, "classification": "Crisis"}, the structural difference is unambiguous.
5.3 Partial Attribute Extraction Creates Lossy Merges
The problem. Each section provides a different slice of information about the same entity. SEC-05 defines severity_level_3 with complete SLO attributes. SEC-06 references it in the context of escalation procedures and may extract partial or hallucinated attribute values. SEC-17 references it in the context of message templates.
If a non-defining section extracts a slightly wrong value for a field (hallucinating from local context), and the merge treats all sections equally, the wrong value may either override or conflict with the correct value from the defining section.
The fix. The primary-source-wins merge strategy from Fix 5.1 solves this. Additionally, the entity extraction prompt should instruct the LLM to only populate attributes for which the current section provides direct textual evidence:
xmlCopy<attribute_grounding>
Only populate a typed attribute if the CURRENT SECTION TEXT provides
a specific value for it. Do not infer or extrapolate attribute values
from context, from knowledge of other sections, or from the entity's
description in a pre-registration block.

If this section references a severity level but does not state its
SLO timing, leave alert_time_target empty. The defining section will
provide the authoritative value and the merge step will fill it in.
</attribute_grounding>
5.4 Description Concatenation Bloat
The problem. A severity_level_3 entity appearing in seven sections accumulates seven description strings via concatenation. The merged description becomes 500+ words of repetitive paraphrases. This makes the semantic dedup input massive and harder for the dedup LLM to process accurately, increasing incorrect merge risk.
The fix. Truncate descriptions in the dedup input to ~200 characters. The dedup step needs enough to judge entity identity, not the full provenance trail:
pythonCopy"description": (e.description[:200] + "...") if len(e.description) > 200 else e.description
Optionally, cap concatenated descriptions in the merge step itself by keeping only the primary source's description plus a count of corroborating sections:
pythonCopyif len(descriptions) > 1:
    combined_description = (
        descriptions[0] + 
        f" [Referenced in {len(descriptions) - 1} additional section(s).]"
    )
5.5 Pre-Registration Must Cover Decomposed Entities
The problem. The pre-registration system coordinates entity IDs across sections. With decomposed entities, many more IDs need coordination. If severity_level_3 is not pre-registered, different sections may independently generate level_3_action_required, severity_3, severity_level_three, and severity_level_3 — creating ID inconsistency that semantic dedup must resolve, with risk of incorrect merges.
The fix. The pipeline's analysis pass that generates pre-registration candidates must explicitly enumerate all decomposed instances. For a document with four severity levels, six contact roles, four response statuses, and twelve-plus alert templates, the pre-registration list should include every expected instance with its exact canonical ID.
If the pre-registration is generated by an LLM, add guidance:
xmlCopy<pre_registration_decomposition>
When the document defines a multi-level classification (e.g., four
severity levels), pre-register each level as a separate entity with
a consistent naming pattern (severity_level_1, severity_level_2,
severity_level_3, severity_level_4).

When the document provides templates per level and per channel,
pre-register each combination (alert_level_3_sms,
alert_level_3_email, alert_level_4_sms, etc.).
</pre_registration_decomposition>

6. Implementation Sequence
These changes have dependencies. The recommended order:
StepChangeRationale1Add typed attributes to four entity schemasNo downstream impact; purely additive2Update entity extraction prompt with schema-aware type reference, decomposition rules, and attribute quality instructionsProduces richer entities; existing merge can handle them (with degraded quality) until Step 43Update relationship extraction prompt with operational prioritization and attribute-awareness guidanceCan be done in parallel with Step 24Replace merge attribute conflict resolution with primary-source-wins strategyRequired before deploying Steps 2-3 to production; prevents schema violations5Update semantic dedup prompt with anti-merge rules and typed-attribute-aware inputRequired before deploying Steps 2-3 to production; prevents re-collapse6Update pre-registration to enumerate decomposed entity instancesImproves ID consistency; reduces dedup burden7Add description truncation in dedup inputPolish; reduces error rate
Steps 4 and 5 are blockers. Deploying the extraction improvements (Steps 2-3) without the merge fixes (Steps 4-5) will produce worse results than the current pipeline because schema violations and entity re-collapse will destroy the richer data before it reaches the graph.

7. Expected Outcome
After all changes are implemented, the graph supports the target agent workflow through direct traversal:
Agent query: "Level 3 security incident in Tokyo — what do I do?"

Retrieve severity_level_3 entity → read alert_time_target="within 60 minutes", client_escalation_time_target="within 60 minutes", crisis_bridge_required=False directly from typed attributes
Follow ACTIVATED_AT edges pointing to severity_level_3 → get welfare_checks_service (activation_severity_threshold=3), incident_response_and_traveler_assistance (activation_severity_threshold=2)
Follow ESCALATED_TO edges from severity_level_3 → get primary_travel_program_owner (roster_position=Primary), corporate_security (escalation_condition="security-related incidents", escalation_severity_levels=[3,4])
Find alert entities where severity_level=3 → get ordered outreach templates with channel_priority_order for SMS(1), Email(2), Push(3), Voice(4)
When traveler responds → retrieve response status entity → read tmc_action and action_time_target directly from typed attributes

Every step is a structured attribute lookup or graph edge traversal. No natural language parsing required.