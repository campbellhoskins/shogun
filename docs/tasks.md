# Tasks

## 1. Run prompts to determine best schema for duty of care documents

**Status:** Complete

**Goal:** Feed all travel duty of care policy documents through an LLM to discover the optimal set of entity types and relationship types for this specific document domain — rather than using a generic schema.

**Why this matters:** The current extraction prompt defines entity types (Role, Threshold, Procedure, etc.) and relationship types (requires, applies_to, triggers, etc.) based on manual inspection of one or two documents. If we pass all available travel duty of care policies through an LLM and ask it to analyze the recurring structural patterns, we can derive a schema that is purpose-built for this document class. A domain-specific schema means:
- Higher extraction recall (no entities missed because a type wasn't in the list)
- Lower noise (no generic types that never appear in practice)
- Consistent extraction across different organizations' policies
- A reusable schema definition that can be applied to any new travel duty of care document

**Approach:**
1. Use already-parsed markdowns in `data/parser_1/` (no need to re-parse PDFs)
2. Pass all documents to the LLM in a single call asking it to identify every distinct category of entity and relationship needed to fully represent travel duty of care policies as a knowledge graph
3. Compare the LLM-derived schema against the current hardcoded types in `src/extraction.py` — identify what's missing, what's redundant, and what should be renamed
4. Output a final schema definition (JSON) that can be plugged into the extraction prompt

**Input documents (travel duty of care only):**
- `data/231123_Duty_of_Care_Policy.pdf` — NGO "Technology of Progress" (Kyiv, 2023)
- `data/080425_POLICY_ON_THE_DUTY_OF_CARE_EN.pdf` — Same NGO (updated 2025)
- `data/Duty-of-Care-Policy.pdf` — 3ie (international development org, global)

Education/school duty of care documents have been removed from the project — they are a different document class not relevant to the travel industry use case.

**Progress:**
- [x] First pass ran (`scripts/discover_schema.py`) with all 5 docs including education — produced generic schema
- [x] Removed education docs from project (St Leonard's College, Maribyrnong College)
- [x] Re-ran with only the 3 travel docs — produced travel-specific schema
- [ ] Compare against current `src/extraction.py` types and integrate into extraction prompt

**Output:** `data/duty_of_care_schema.json` — travel-specific entity types and relationship types with definitions, ready to integrate into the extraction prompt.
