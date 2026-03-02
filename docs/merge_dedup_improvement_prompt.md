# Merge Dedup Prompt — Improvement Meta-Prompt

## SECTION A — Context and Feedback (paste this as the feedback/context)

### What This Prompt Does

This prompt is used in Stage 3 of a 3-stage ontology extraction pipeline for travel policy documents. Stages 1-2 have already:
1. Chunked the document into semantic sections
2. Extracted entities and relationships from each section independently

Stage 3 takes ALL entities from ALL sections, groups them by entity type, and asks the LLM to **deduplicate** — identify entities that refer to the same real-world thing despite appearing in different sections with different names, IDs, or descriptions. For example, "ED" and "Executive Director" extracted from different sections should be merged into one entity.

### How the Prompt is Assembled at Runtime

The prompt uses Python `.format()` with two variables:

- **`{entity_type}`** — The entity type being deduplicated (e.g., "Role", "Policy", "Organization", "Procedure", "Threshold", "Definition", etc.)

- **`{entities_block}`** — A JSON array of all entities of that type, formatted like:
  ```json
  [
    {
      "id": "s2_role_executive_director",
      "type": "Role",
      "name": "Executive Director",
      "description": "Senior executive role with policy approval authority",
      "attributes": {"role_type": "executive"},
      "source_text": "Directly involved in the implementation of the Policy are: General Meeting; Executive director.",
      "source_section": "2"
    },
    {
      "id": "s5_role_exec_dir",
      "type": "Role",
      "name": "Exec Director",
      "description": "The executive director approves all travel to high-risk destinations",
      "attributes": {"approval_level": "high"},
      "source_text": "The Executive Director shall approve all travel...",
      "source_section": "5"
    }
  ]
  ```

### How the Response is Parsed

The response is parsed as a JSON array. The parser:
1. Strips markdown code fences if present
2. Attempts `json.loads()` directly
3. Falls back to regex extraction of `[...]` array from surrounding text
4. No thinking/analysis tags are used — the prompt says "Return ONLY the JSON array"

**After parsing, for each entity in the returned array:**
- `merged_from` is used internally to build an `id_mapping` (old_id → new_id) for remapping all relationship references
- `source_anchors` is stored on the Entity model
- `source_anchor` (singular, primary) is set to the first element of `source_anchors`
- `merged_from` is then discarded — it does not appear in the final output

### Specific Quality Issues Found in Test Runs

**Issue 1: JSON parse failures on large groups.** When the entity type has 20+ entities (e.g., "Role" with 20, "PolicyRule" with 64), the LLM produces JSON with syntax errors — usually unescaped quotes inside description strings. The prompt needs to emphasize valid JSON output more strongly, possibly with a thinking/analysis step before the JSON output.

**Issue 2: Description degradation on pass-through entities.** When entities are NOT merged (just passed through), the LLM sometimes rewrites their description to be shorter/more generic than the original. For example, an entity with a rich description gets a bland one-liner. The prompt should emphasize: for entities with no duplicates, preserve the original description verbatim.

**Issue 3: Source text not always verbatim.** The prompt says to copy source_text values exactly, but the LLM sometimes paraphrases or truncates them. The source_text MUST be character-for-character identical to what was provided in the input — it's used for exact string matching against the original document downstream.

**Issue 4: No analysis step.** For groups with many entities (10+), the LLM jumps straight to JSON without reasoning about which entities might be duplicates. A structured thinking step (in XML tags that get stripped) would improve accuracy on larger groups.

### What NOT to Change

- **Output schema**: Must remain a JSON array of objects with these exact fields: `id`, `type`, `name`, `description`, `attributes`, `source_anchors`, `merged_from`
- **Variable names**: `{{entity_type}}` and `{{entities_block}}` must remain as the only two template variables
- **Conservative bias**: "When in doubt, do NOT merge" must remain — false negatives are better than false positives
- **`merged_from` requirement**: Every entity in the output MUST have a `merged_from` array, even singletons
- **`source_anchors` requirement**: Every entity MUST have a `source_anchors` array containing ALL source references from the original entities

### Entity Types This Prompt Handles

The type groups typically range from 2-60+ entities. Common types: Role, Procedure, Definition, Policy, Organization, RiskLevel, Threshold, Equipment, ContactInformation, IncidentCategory, BenefitOrPackage, Person, GovernanceBody, Training, Location, Requirement, Constraint.

---

## SECTION B — The Prompt to Improve (paste this as the prompt)

```
You are deduplicating entities of type "{{entity_type}}" extracted from different sections of the same policy document. Some of these entities may refer to the same real-world thing despite having different names, IDs, or descriptions (e.g., "ED" and "Executive Director" are the same role, or "John" and "John Smith" are the same person).

## Input Entities (JSON)

{{entities_block}}

## Task

Return a JSON array of deduplicated entities. For every group of entities that refer to the same real-world thing, merge them into ONE entity. Entities with no duplicates should pass through unchanged.

Rules:
- Pick the best, most complete name for each entity
- Combine descriptions — keep all unique facts from every duplicate
- Union all attributes — if two duplicates have different attribute keys, keep both
- Generate a clean ID in lowercase_snake_case with no section prefix
- Include a "merged_from" array listing ALL original IDs that went into this entity (even if it was just one — every entity must have merged_from)
- Include "source_anchors" — an array of ALL source references from the input entities. Copy the "source_text" and "source_section" values EXACTLY from the input JSON (verbatim, do not alter)
- When in doubt, do NOT merge — false negatives are better than false positives

Return ONLY the JSON array, no other text.

Output format:
[
  {
    "id": "clean_entity_id",
    "type": "{{entity_type}}",
    "name": "Best Name",
    "description": "Combined description with all unique facts",
    "attributes": {"key": "value"},
    "source_anchors": [
      {"source_text": "exact verbatim quote from input", "source_section": "2"},
      {"source_text": "another exact quote from input", "source_section": "5"}
    ],
    "merged_from": ["original_id_1", "original_id_2"]
  }
]
```

**Note to the prompt improver:** The template variables `{{entity_type}}` and `{{entities_block}}` must remain in double-brace format. Single `{` and `}` in the output format section are literal JSON braces and should remain as-is.

---

## SECTION C — Test Variable Values (use these to test the prompt in the Console)

### Test Case 1: Organization (4 entities — should merge to 1)

**`{{entity_type}}`** = `Organization`

**`{{entities_block}}`** =
```json
[
  {
    "id": "s0_org_technology_of_progress",
    "type": "Organization",
    "name": "TECHNOLOGY OF PROGRESS",
    "description": "NGO organization that owns and governs the Duty of Care Policy",
    "attributes": {"organization_type": "NGO", "location": "Kiyv", "year": "2023"},
    "source_text": "By decision of the General Meeting of NGO TECHNOLOGY OF PROGRESS",
    "source_section": "0"
  },
  {
    "id": "s1_org_ngo_technology_progress",
    "type": "Organization",
    "name": "NGO TECHNOLOGY OF PROGRESS",
    "description": "The organization whose activities are governed by this policy, committed to high standards of integrity and professionalism",
    "attributes": {"full_name": "NGO TECHNOLOGY OF PROGRESS", "alias": "Organization"},
    "source_text": "The activities of NGO TECHNOLOGY OF PROGRESS (hereafter \u2013 the \u201cOrganization\u201d) are based on such values as activeness and care, association and cooperation, responsibility and the rule of law.",
    "source_section": "1"
  },
  {
    "id": "s3_org_organization",
    "type": "Organization",
    "name": "Organization",
    "description": "The organization that owns the policy and assesses, monitors and responds to security risks",
    "attributes": {"security_activities": ["assesses", "monitors", "responds"], "risk_focus": "security risks affecting staff and program implementation"},
    "source_text": "This document also provides an overview of how the Organization assesses, monitors and responds to security risks that may affect staff and program implementation.",
    "source_section": "3"
  },
  {
    "id": "s5_role_organization",
    "type": "Organization",
    "name": "Organization",
    "description": "The organization whose policy this document represents and whose assets and security must be protected",
    "attributes": {},
    "source_text": "ensuring information security of the Organization, including intellectual property;",
    "source_section": "5"
  }
]
```

### Test Case 2: Requirement (11 entities — should stay mostly separate)

**`{{entity_type}}`** = `Requirement`

**`{{entities_block}}`** =
```json
[
  {
    "id": "s5_requirement_physical_safety",
    "type": "Requirement",
    "name": "Physical Safety Responsibility",
    "description": "Ensuring the physical safety of life and health of Personnel, including in cases of stay in high-risk areas",
    "attributes": {"includes_context": "high-risk areas"},
    "source_text": "ensuring the physical safety of life and health of Personnel, including in cases of stay in high- risk areas;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_org_info_security",
    "type": "Requirement",
    "name": "Organization Information Security Responsibility",
    "description": "Ensuring information security of the Organization, including intellectual property",
    "attributes": {"includes": "intellectual property"},
    "source_text": "ensuring information security of the Organization, including intellectual property;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_personnel_info_security",
    "type": "Requirement",
    "name": "Personnel Information Security Responsibility",
    "description": "Ensuring information security of Personnel of the Organization",
    "attributes": {},
    "source_text": "ensuring information security of Personnel of the Organization;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_material_assets",
    "type": "Requirement",
    "name": "Material Assets Preservation Responsibility",
    "description": "Ensuring the preservation of material assets of the Organization and Personnel within the activities of the Organization",
    "attributes": {},
    "source_text": "ensuring the preservation of material assets of the Organization and Personnel within the activities of the Organization;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_financial_security",
    "type": "Requirement",
    "name": "Financial Security Responsibility",
    "description": "Ensuring the financial security of the Organization",
    "attributes": {},
    "source_text": "ensuring the financial security of the Organization;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_policy_compliance",
    "type": "Requirement",
    "name": "Policy Compliance Responsibility",
    "description": "Ensuring this policy is complied with, along with other related policies",
    "attributes": {"scope": "this policy and other related policies"},
    "source_text": "ensuring this policy is complied with, along with other related policies;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_reasonable_care",
    "type": "Requirement",
    "name": "Reasonable Care and Duty of Care Responsibility",
    "description": "Taking reasonable care in the course of their work and accepting a duty of care for their own health and safety, as well as for the health and safety of others within the workplace",
    "attributes": {"scope": "own health and safety and others in workplace"},
    "source_text": "taking reasonable care in the course of their work and accepting a duty of care for their own health and safety, as well as for the health and safety of others within the workplace;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_secure_environment",
    "type": "Requirement",
    "name": "Secure Environment Participation Responsibility",
    "description": "Actively participate in building and maintaining a secure environment, through open communication, clear boundaries, managing complaints or disclosure, accurate documentation and notifying appropriate authorities of risk or harm in accordance with relevant procedures",
    "attributes": {"methods": ["open communication", "clear boundaries", "managing complaints or disclosure", "accurate documentation", "notifying appropriate authorities"]},
    "source_text": "actively participate in building and maintaining a secure environment, through open communication, clear boundaries, managing complaints or disclosure, accurate documentation and notifying appropriate authorities of risk or harm in accordance with relevant procedures;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_risk_reporting",
    "type": "Requirement",
    "name": "Risk Reporting Responsibility",
    "description": "Anticipating foreseeable harm and risks to self and/or others and immediately reporting any unsafe conditions or behaviors observed in the workplace to direct manager",
    "attributes": {"immediacy": "immediately", "scope": "self and/or others"},
    "source_text": "anticipating foreseeable harm and risks to self and/or others and immediately reporting any unsafe conditions or behaviors observed in the workplace to direct manager;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_risk_control",
    "type": "Requirement",
    "name": "Risk Control Implementation Responsibility",
    "description": "Where foreseeable harm or risk is identified, implementing preventative and risk control measures in consultation with direct manager (where practical) and in line with relevant procedures",
    "attributes": {"condition": "where foreseeable harm or risk is identified", "consultation_condition": "where practical"},
    "source_text": "where foreseeable harm or risk is identified, implementing preventative and risk control measures in consultation with direct manager (where practical) and in line with relevant procedures;",
    "source_section": "5"
  },
  {
    "id": "s5_requirement_reasonable_care_standard",
    "type": "Requirement",
    "name": "Reasonable Care Standard Responsibility",
    "description": "Taking the amount of care a reasonable person would expect",
    "attributes": {"standard": "reasonable person expectation"},
    "source_text": "taking the amount of care a reasonable person would expect.",
    "source_section": "5"
  }
]
```
