"""Evaluate the ontology graph + reasoning agent against a Q&A test set.

Usage:
    uv run python -m src.eval --graph <graph_id> --qa <qa_path> [--out results.json]

Example:
    uv run python -m src.eval --graph 1-1 --qa data/231123_Duty_of_Care_Policy.qa.small.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

from src.build_graph import load_graph_file, list_graphs
from src.graph import build_graph
from src.agent import ask

JUDGE_SYSTEM_PROMPT = """\
You are an impartial judge evaluating whether an agent's answer to a question is correct, given the ground truth answer.

Score the agent's answer on these criteria:

1. **Factual Accuracy** (0-3): Does the answer contain the correct facts?
   - 0: Completely wrong or contradicts the ground truth
   - 1: Partially correct but missing key facts or contains errors
   - 2: Mostly correct with minor omissions or imprecisions
   - 3: Fully correct, all key facts present

2. **Completeness** (0-2): Does the answer cover everything in the ground truth?
   - 0: Misses most of the expected content
   - 1: Covers some but not all key points
   - 2: Covers all key points from the ground truth

3. **No Hallucination** (0-1): Does the answer avoid stating things not in the policy?
   - 0: Contains fabricated details not in the ground truth or policy
   - 1: Only states things consistent with the ground truth

Return a JSON object with exactly this structure:
{
  "accuracy": 0-3,
  "completeness": 0-2,
  "no_hallucination": 0-1,
  "total": 0-6,
  "pass": true/false,
  "explanation": "Brief explanation of the score"
}

A "pass" requires total >= 4 (out of 6).

Return ONLY the JSON object."""


def judge_answer(
    question: str,
    ground_truth: str,
    agent_answer: str,
    client: Anthropic,
) -> dict:
    """Use a separate LLM call to judge the agent's answer against ground truth."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"## Question\n{question}\n\n"
                    f"## Ground Truth Answer\n{ground_truth}\n\n"
                    f"## Agent's Answer\n{agent_answer}"
                ),
            }
        ],
    )

    raw = response.content[0].text
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {
            "accuracy": 0,
            "completeness": 0,
            "no_hallucination": 0,
            "total": 0,
            "pass": False,
            "explanation": f"Judge failed to return valid JSON: {raw[:200]}",
        }


def main() -> None:
    load_dotenv()

    if "--graph" not in sys.argv or "--qa" not in sys.argv:
        print("Usage: uv run python -m src.eval --graph <graph_id> --qa <qa_path> [--out results.json]")
        print("\nAvailable graphs:")
        for g in list_graphs():
            print(f"  {g['graph_id']}  (v{g['prompt_version']}, {g['node_count']} nodes, {g['edge_count']} edges)")
        sys.exit(1)

    graph_id = sys.argv[sys.argv.index("--graph") + 1]
    qa_path = Path(sys.argv[sys.argv.index("--qa") + 1])
    out_path = None

    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            out_path = Path(sys.argv[idx + 1])

    if not qa_path.is_absolute():
        qa_path = Path.cwd() / qa_path

    # Load graph
    print(f"Graph: {graph_id}")
    ontology, metadata = load_graph_file(graph_id)
    g = build_graph(ontology)
    print(f"  Prompt version: v{metadata['prompt_version']}")
    print(f"  Policy: {metadata['policy_file']}")
    print(f"  {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

    print(f"Test set: {qa_path.name}")
    qa_pairs = json.loads(qa_path.read_text(encoding="utf-8"))
    print(f"  {len(qa_pairs)} questions loaded")

    client = Anthropic()
    parse_time = metadata.get("parse_time_seconds", 0)

    # Run eval
    print(f"\nRunning evaluation ({len(qa_pairs)} questions)...\n")
    results = []
    passed = 0
    total_score = 0
    max_possible = len(qa_pairs) * 6

    for i, qa in enumerate(qa_pairs):
        question = qa["question"]
        ground_truth = qa["answer"]
        difficulty = qa.get("difficulty", "?")

        # Get agent answer
        try:
            agent_response = ask(question, g, client=client)
            agent_answer = agent_response.answer
        except Exception as e:
            agent_answer = f"ERROR: {e}"

        # Judge it
        try:
            judgment = judge_answer(question, ground_truth, agent_answer, client)
        except Exception as e:
            judgment = {
                "accuracy": 0, "completeness": 0, "no_hallucination": 0,
                "total": 0, "pass": False, "explanation": f"Judge error: {e}",
            }

        score = judgment.get("total", 0)
        did_pass = judgment.get("pass", False)
        total_score += score
        if did_pass:
            passed += 1

        status = "PASS" if did_pass else "FAIL"
        print(f"  [{status}] {i+1:3d}/{len(qa_pairs)} [{difficulty:6s}] ({score}/6) {question[:80]}")
        if not did_pass:
            print(f"         Reason: {judgment.get('explanation', '')[:120]}")

        results.append({
            "question": question,
            "ground_truth": ground_truth,
            "agent_answer": agent_answer,
            "difficulty": difficulty,
            "judgment": judgment,
        })

    # Summary
    pct = (passed / len(qa_pairs) * 100) if qa_pairs else 0
    avg_score = (total_score / len(qa_pairs)) if qa_pairs else 0

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{len(qa_pairs)} passed ({pct:.1f}%)")
    print(f"  Average score: {avg_score:.2f}/6.00 ({total_score}/{max_possible})")
    print(f"  Graph: {metadata['graph_id']} (v{metadata['prompt_version']}, {g.number_of_nodes()} nodes, {g.number_of_edges()} edges)")

    # Breakdown by difficulty
    for diff in ("easy", "medium", "hard"):
        subset = [r for r in results if r["difficulty"] == diff]
        if subset:
            diff_passed = sum(1 for r in subset if r["judgment"].get("pass", False))
            diff_pct = diff_passed / len(subset) * 100
            diff_avg = sum(r["judgment"].get("total", 0) for r in subset) / len(subset)
            print(f"  {diff:8s}: {diff_passed}/{len(subset)} passed ({diff_pct:.1f}%), avg {diff_avg:.2f}/6")

    print("=" * 60)

    # Save results
    if out_path is None:
        out_path = Path.cwd() / "output" / "eval_results.json"
    out_path.parent.mkdir(exist_ok=True)

    summary = {
        "graph_id": metadata["graph_id"],
        "prompt_version": metadata["prompt_version"],
        "policy": metadata["policy_file"],
        "test_set": qa_path.name,
        "total_questions": len(qa_pairs),
        "passed": passed,
        "pass_rate": round(pct, 1),
        "average_score": round(avg_score, 2),
        "max_score": 6,
        "total_points": total_score,
        "max_points": max_possible,
        "graph_nodes": g.number_of_nodes(),
        "graph_edges": g.number_of_edges(),
        "parse_time_seconds": round(parse_time, 1),
        "results": results,
    }

    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetailed results saved to {out_path}")


if __name__ == "__main__":
    main()
