# Email Update to Arjun

**Subject: Following Up — Duty of Care Ontology Graph Project**

Hi Arjun,

Really enjoyed our conversation — I haven't been able to stop thinking about the ontology graph idea since we spoke. I went ahead and built a working system that does this for duty of care policies, and wanted to share where I landed.

**What I built:**

I took a real corporate duty of care policy PDF and built a five-stage pipeline that parses it into clean markdown, runs a first-pass structural analysis of the whole document, semantically chunks it into sections, extracts entities and relationships from each section, and then merges everything back together — deduplicating cross-section references and extracting relationships that exist across the full document. The output is a structured ontology graph where every policy rule, role, threshold, escalation procedure, and obligation is a node or edge rather than just text sitting in a vector store.

**Why this matters more than RAG:**

The thing I kept coming back to after our call is that duty of care decisions are fundamentally *graph traversal* problems. The answer to "what are we obligated to do here?" is almost never in a single paragraph — it requires tracing a chain across the policy: incident type → triggered obligations → required roles → escalation thresholds → specific actions and timelines. RAG retrieves relevant chunks, but it can't reliably follow that full chain across sections. An ontology graph encodes the logic explicitly.

The use case I keep envisioning is a travel management agent that receives information about an incident happening while a traveler is on an itinerary — say a security event at a destination, or a medical emergency — and then uses the graph to traverse edges and fully understand exactly what the TMC is liable to uphold and what duties they must perform. Not by searching for keywords in a document, but by walking the actual structure of obligations, roles, and escalation paths that the policy defines. That's where the graph approach really separates itself from retrieval.

**How this connects to the bigger picture:**

This is a microcosm of what Shogun would deploy at scale. Every acquired TMC has its own duty of care policies, booking rules, fare rules, and expense policies — all living as unstructured PDFs or internal wikis. The same pipeline pattern extends directly to those document types. Once you have the ontology graph, agents can make autonomous compliance decisions (or flag the ones that need human review) far more reliably than with retrieval alone, because the decision logic is explicit in the graph structure rather than implicit in prose.

**A question for you:**

I'm curious how you envision agents actually using these graphs for decisions operationally. Do you see it as more of a deterministic decision-tree approach — where the graph encodes hard rules and the agent just traverses them — or a hybrid where the agent applies its own reasoning but with tool access to the graph as a structured knowledge base? The distinction matters architecturally: a pure decision tree is more auditable but brittle to edge cases, while agent reasoning with graph tools is more flexible but needs more guardrails. Would love to hear your thinking on where the right balance is for travel compliance.

I also have the project running with an interactive frontend where you can explore the graph visually and ask questions against it. Happy to demo whenever works.

Looking forward to it.

Best,
[Your name]
