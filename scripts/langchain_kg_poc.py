"""LangChain LLMGraphTransformer PoC — Compare off-the-shelf KG extraction
against Shogun's custom 4-stage pipeline.

Runs 4 experiments (2 schema modes x 2 chunking modes) using the same LLM
(claude-sonnet-4-20250514) on the same input document.

Usage:
    uv run python scripts/langchain_kg_poc.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer

# ---------------------------------------------------------------------------
# Shogun schema types (read-only import for comparison metrics)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.schemas import VALID_ENTITY_TYPES, VALID_RELATIONSHIP_TYPES

INPUT_PATH = Path(__file__).parent.parent / "data" / "duty_of_care.md"
OUTPUT_DIR = Path(__file__).parent.parent / "data"

# Shogun entity types (LangChain uses these as allowed_nodes)
SHOGUN_ENTITY_TYPES = sorted(VALID_ENTITY_TYPES)

# Shogun relationship types (LangChain uses these as allowed_relationships)
SHOGUN_RELATIONSHIP_TYPES = sorted(VALID_RELATIONSHIP_TYPES)


# ---------------------------------------------------------------------------
# Document loading helpers
# ---------------------------------------------------------------------------


def load_as_single_doc(path: Path) -> list[Document]:
    """Load entire markdown file as a single LangChain Document."""
    text = path.read_text(encoding="utf-8")
    return [Document(page_content=text, metadata={"source": path.name})]


def chunk_by_sections(text: str) -> list[Document]:
    """Split markdown on ## headers into individual Documents.

    Each chunk includes its header and all content until the next ## header.
    """
    # Split on lines starting with ## (level 2 headers)
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    docs = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        # Extract header for metadata
        first_line = part.split("\n", 1)[0].strip()
        docs.append(
            Document(
                page_content=part,
                metadata={"source": INPUT_PATH.name, "chunk_index": i, "header": first_line},
            )
        )
    return docs


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def deduplicate_nodes(nodes: list[dict]) -> list[dict]:
    """Merge duplicate entities across chunks by (id_lower, type).

    Keeps the first occurrence's properties and merges any additional
    properties from duplicates.
    """
    seen: dict[tuple[str, str], dict] = {}
    for node in nodes:
        key = (node["id"].lower(), node["type"])
        if key not in seen:
            seen[key] = node.copy()
        else:
            # Merge properties from duplicate
            existing_props = seen[key].get("properties", {})
            new_props = node.get("properties", {})
            for k, v in new_props.items():
                if k not in existing_props or not existing_props[k]:
                    existing_props[k] = v
            seen[key]["properties"] = existing_props
    return list(seen.values())


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------


def run_experiment(
    llm: ChatAnthropic,
    docs: list[Document],
    name: str,
    allowed_nodes: list[str] | None = None,
    allowed_relationships: list[str] | None = None,
) -> dict:
    """Run a single LLMGraphTransformer experiment.

    Tries structured output mode first. If it fails, falls back to
    prompt-based mode (ignore_tool_usage=True).
    """
    print(f"\n{'='*60}")
    print(f"  Experiment: {name}")
    print(f"  Documents: {len(docs)}")
    print(f"  Schema: {'guided' if allowed_nodes else 'free'}")
    print(f"{'='*60}")

    mode_used = "structured_output"
    graph_docs = None

    # Try structured output mode first
    try:
        print("  Trying structured output mode...")
        transformer = LLMGraphTransformer(
            llm=llm,
            allowed_nodes=allowed_nodes or [],
            allowed_relationships=allowed_relationships or [],
            node_properties=True,
            relationship_properties=True,
        )
        start = time.time()
        graph_docs = transformer.convert_to_graph_documents(docs)
        elapsed = time.time() - start
        print(f"  Structured output mode succeeded ({elapsed:.1f}s)")
    except Exception as e:
        print(f"  Structured output failed: {e}")
        print("  Falling back to prompt-based mode...")
        mode_used = "prompt_based"

    # Fallback: prompt-based mode
    if graph_docs is None:
        try:
            transformer = LLMGraphTransformer(
                llm=llm,
                allowed_nodes=allowed_nodes or [],
                allowed_relationships=allowed_relationships or [],
                node_properties=False,  # Not supported in prompt-based mode
                relationship_properties=False,
                ignore_tool_usage=True,
            )
            start = time.time()
            graph_docs = transformer.convert_to_graph_documents(docs)
            elapsed = time.time() - start
            print(f"  Prompt-based mode succeeded ({elapsed:.1f}s)")
        except Exception as e:
            print(f"  Prompt-based mode also failed: {e}")
            return {
                "name": name,
                "error": str(e),
                "mode": "failed",
                "nodes": [],
                "relationships": [],
            }

    # Collect all nodes and relationships across graph documents
    all_nodes = []
    all_rels = []
    for gd in graph_docs:
        for node in gd.nodes:
            all_nodes.append({
                "id": node.id,
                "type": node.type,
                "properties": dict(node.properties) if node.properties else {},
            })
        for rel in gd.relationships:
            all_rels.append({
                "source_id": rel.source.id,
                "source_type": rel.source.type,
                "target_id": rel.target.id,
                "target_type": rel.target.type,
                "type": rel.type,
                "properties": dict(rel.properties) if rel.properties else {},
            })

    # Deduplicate nodes
    raw_node_count = len(all_nodes)
    deduped_nodes = deduplicate_nodes(all_nodes)

    # Node type distribution
    node_types = Counter(n["type"] for n in deduped_nodes)
    rel_types = Counter(r["type"] for r in all_rels)

    result = {
        "name": name,
        "mode": mode_used,
        "elapsed_seconds": round(elapsed, 2),
        "document_count": len(docs),
        "raw_node_count": raw_node_count,
        "deduped_node_count": len(deduped_nodes),
        "relationship_count": len(all_rels),
        "node_type_count": len(node_types),
        "relationship_type_count": len(rel_types),
        "node_type_distribution": dict(node_types.most_common()),
        "relationship_type_distribution": dict(rel_types.most_common()),
        "nodes": deduped_nodes,
        "relationships": all_rels,
    }

    print_summary(result)
    return result


# ---------------------------------------------------------------------------
# Comparison metrics
# ---------------------------------------------------------------------------


def compute_comparison(results: dict[str, dict]) -> dict:
    """Compute cross-experiment comparison metrics."""
    comparison = {}

    experiment_names = list(results.keys())

    # Pairwise Jaccard similarity of node type sets
    node_type_jaccard = {}
    for i, a in enumerate(experiment_names):
        for b in experiment_names[i + 1 :]:
            set_a = set(results[a].get("node_type_distribution", {}).keys())
            set_b = set(results[b].get("node_type_distribution", {}).keys())
            if set_a | set_b:
                jaccard = len(set_a & set_b) / len(set_a | set_b)
            else:
                jaccard = 0.0
            node_type_jaccard[f"{a} vs {b}"] = round(jaccard, 3)

    # Pairwise Jaccard similarity of relationship type sets
    rel_type_jaccard = {}
    for i, a in enumerate(experiment_names):
        for b in experiment_names[i + 1 :]:
            set_a = set(results[a].get("relationship_type_distribution", {}).keys())
            set_b = set(results[b].get("relationship_type_distribution", {}).keys())
            if set_a | set_b:
                jaccard = len(set_a & set_b) / len(set_a | set_b)
            else:
                jaccard = 0.0
            rel_type_jaccard[f"{a} vs {b}"] = round(jaccard, 3)

    # Shogun type coverage per experiment
    shogun_coverage = {}
    for name, res in results.items():
        if res.get("error"):
            shogun_coverage[name] = {"entity_coverage": 0, "relationship_coverage": 0}
            continue
        extracted_entity_types = set(res.get("node_type_distribution", {}).keys())
        extracted_rel_types = set(res.get("relationship_type_distribution", {}).keys())

        entity_overlap = extracted_entity_types & set(SHOGUN_ENTITY_TYPES)
        rel_overlap = extracted_rel_types & set(SHOGUN_RELATIONSHIP_TYPES)

        shogun_coverage[name] = {
            "entity_types_matched": sorted(entity_overlap),
            "entity_coverage_pct": round(
                len(entity_overlap) / len(SHOGUN_ENTITY_TYPES) * 100, 1
            ),
            "relationship_types_matched": sorted(rel_overlap),
            "relationship_coverage_pct": round(
                len(rel_overlap) / len(SHOGUN_RELATIONSHIP_TYPES) * 100, 1
            ),
        }

    # Graph density per experiment
    density = {}
    for name, res in results.items():
        n = res.get("deduped_node_count", 0)
        r = res.get("relationship_count", 0)
        if n > 1:
            # density = edges / (nodes * (nodes - 1)) for directed graph
            density[name] = round(r / (n * (n - 1)), 4)
        else:
            density[name] = 0.0

    # Avg properties per node
    avg_props = {}
    for name, res in results.items():
        nodes = res.get("nodes", [])
        if nodes:
            total_props = sum(len(n.get("properties", {})) for n in nodes)
            avg_props[name] = round(total_props / len(nodes), 2)
        else:
            avg_props[name] = 0.0

    # Summary table
    summary_table = {}
    for name, res in results.items():
        summary_table[name] = {
            "mode": res.get("mode", "unknown"),
            "elapsed_seconds": res.get("elapsed_seconds", 0),
            "documents": res.get("document_count", 0),
            "nodes": res.get("deduped_node_count", 0),
            "relationships": res.get("relationship_count", 0),
            "node_types": res.get("node_type_count", 0),
            "rel_types": res.get("relationship_type_count", 0),
            "density": density.get(name, 0),
            "avg_props_per_node": avg_props.get(name, 0),
        }

    comparison = {
        "summary": summary_table,
        "node_type_jaccard": node_type_jaccard,
        "rel_type_jaccard": rel_type_jaccard,
        "shogun_type_coverage": shogun_coverage,
        "graph_density": density,
        "avg_properties_per_node": avg_props,
        "shogun_schema_info": {
            "entity_type_count": len(SHOGUN_ENTITY_TYPES),
            "entity_types": SHOGUN_ENTITY_TYPES,
            "relationship_type_count": len(SHOGUN_RELATIONSHIP_TYPES),
            "relationship_types": SHOGUN_RELATIONSHIP_TYPES,
        },
    }

    return comparison


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def print_summary(result: dict) -> None:
    """Print formatted summary for a single experiment."""
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
        return

    print(f"\n  Mode: {result['mode']}")
    print(f"  Time: {result['elapsed_seconds']}s")
    print(f"  Nodes: {result['deduped_node_count']} (raw: {result['raw_node_count']})")
    print(f"  Relationships: {result['relationship_count']}")
    print(f"  Node types ({result['node_type_count']}):")
    for t, c in sorted(result["node_type_distribution"].items(), key=lambda x: -x[1]):
        print(f"    {t}: {c}")
    print(f"  Relationship types ({result['relationship_type_count']}):")
    for t, c in sorted(
        result["relationship_type_distribution"].items(), key=lambda x: -x[1]
    ):
        print(f"    {t}: {c}")


def print_comparison(comparison: dict) -> None:
    """Print the cross-experiment comparison."""
    print(f"\n{'='*60}")
    print("  CROSS-EXPERIMENT COMPARISON")
    print(f"{'='*60}")

    print("\n  Summary:")
    print(
        f"  {'Experiment':<30} {'Nodes':>6} {'Rels':>6} {'NTypes':>7} "
        f"{'RTypes':>7} {'Density':>8} {'Time':>6}"
    )
    print(f"  {'-'*74}")
    for name, s in comparison["summary"].items():
        print(
            f"  {name:<30} {s['nodes']:>6} {s['relationships']:>6} "
            f"{s['node_types']:>7} {s['rel_types']:>7} "
            f"{s['density']:>8.4f} {s['elapsed_seconds']:>5.1f}s"
        )

    print("\n  Node Type Jaccard Similarity:")
    for pair, j in comparison["node_type_jaccard"].items():
        print(f"    {pair}: {j:.3f}")

    print("\n  Relationship Type Jaccard Similarity:")
    for pair, j in comparison["rel_type_jaccard"].items():
        print(f"    {pair}: {j:.3f}")

    print("\n  Shogun Schema Coverage:")
    for name, cov in comparison["shogun_type_coverage"].items():
        entity_pct = cov.get("entity_coverage_pct", 0)
        rel_pct = cov.get("relationship_coverage_pct", 0)
        entity_matched = cov.get("entity_types_matched", [])
        rel_matched = cov.get("relationship_types_matched", [])
        print(f"    {name}:")
        print(
            f"      Entities: {entity_pct}% "
            f"({len(entity_matched)}/{len(SHOGUN_ENTITY_TYPES)})"
        )
        if entity_matched:
            print(f"        Matched: {', '.join(entity_matched)}")
        print(
            f"      Relationships: {rel_pct}% "
            f"({len(rel_matched)}/{len(SHOGUN_RELATIONSHIP_TYPES)})"
        )
        if rel_matched:
            print(f"        Matched: {', '.join(rel_matched)}")


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------


def save_experiment(result: dict, output_path: Path) -> None:
    """Save experiment result to JSON, stripping full node/rel lists for the
    comparison file but keeping them in individual files."""
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("LangChain LLMGraphTransformer PoC")
    print(f"Input: {INPUT_PATH}")
    print(f"Shogun entity types: {len(SHOGUN_ENTITY_TYPES)}")
    print(f"Shogun relationship types: {len(SHOGUN_RELATIONSHIP_TYPES)}")

    # Load document
    text = INPUT_PATH.read_text(encoding="utf-8")
    single_doc = load_as_single_doc(INPUT_PATH)
    chunked_docs = chunk_by_sections(text)
    print(f"Single doc chars: {len(text)}")
    print(f"Chunked into {len(chunked_docs)} sections")

    # Initialize LLM (same model as Shogun pipeline)
    llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)

    # ---- Experiment 1: whole_doc_schema_free ----
    exp1 = run_experiment(
        llm=llm,
        docs=single_doc,
        name="whole_doc_schema_free",
    )

    # ---- Experiment 2: whole_doc_schema_guided ----
    exp2 = run_experiment(
        llm=llm,
        docs=single_doc,
        name="whole_doc_schema_guided",
        allowed_nodes=SHOGUN_ENTITY_TYPES,
        allowed_relationships=SHOGUN_RELATIONSHIP_TYPES,
    )

    # ---- Experiment 3: chunked_schema_free ----
    exp3 = run_experiment(
        llm=llm,
        docs=chunked_docs,
        name="chunked_schema_free",
    )

    # ---- Experiment 4: chunked_schema_guided ----
    exp4 = run_experiment(
        llm=llm,
        docs=chunked_docs,
        name="chunked_schema_guided",
        allowed_nodes=SHOGUN_ENTITY_TYPES,
        allowed_relationships=SHOGUN_RELATIONSHIP_TYPES,
    )

    # Collect results
    results = {
        exp1["name"]: exp1,
        exp2["name"]: exp2,
        exp3["name"]: exp3,
        exp4["name"]: exp4,
    }

    # Save individual experiment results
    for name, result in results.items():
        save_experiment(result, OUTPUT_DIR / f"langchain_kg_{name}.json")

    # Compute and save comparison
    comparison = compute_comparison(results)
    comp_path = OUTPUT_DIR / "langchain_kg_comparison.json"
    comp_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n  Saved comparison: {comp_path}")

    # Print comparison
    print_comparison(comparison)

    print(f"\n{'='*60}")
    print("  DONE — All 4 experiments complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
