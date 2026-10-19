import argparse
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

from search_articles import MODEL_NAME, detect_teams, load_aliases, search

QUESTIONS_PATH = Path("config/eval_questions.json")
RESULTS_DIR = Path("data/eval")
TOP_K = 5


def normalize(text):
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def mentions_any(text, terms):
    return any(normalize(term) in text for term in terms)


def score_question(results, team_terms, topic_terms):
    entity_hits = []
    relevant_hits = []
    for r in results:
        text = normalize(f"{r['title']} {r['chunk_text']}")
        has_team = mentions_any(text, team_terms)
        entity_hits.append(has_team)
        relevant_hits.append(has_team and mentions_any(text, topic_terms))

    first_relevant = next((i for i, hit in enumerate(relevant_hits, start=1) if hit), None)
    return {
        "hit": first_relevant is not None,
        "precision": sum(relevant_hits) / TOP_K,
        "entity_precision": sum(entity_hits) / TOP_K,
        "reciprocal_rank": 1 / first_relevant if first_relevant else 0.0,
        "relevant_flags": relevant_hits,
    }


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score retrieval quality on a fixed question set")
    parser.add_argument("--label", default="baseline", help="Name for this run, e.g. baseline, entity_filter")
    parser.add_argument("--entity-filter", action="store_true", help="Filter search by teams detected in each question")
    args = parser.parse_args()

    project = os.getenv("GCP_PROJECT")
    if not project:
        print("[ERR] GCP_PROJECT is not set")
        sys.exit(1)

    spec = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    topics = spec["topics"]
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    bq = bigquery.Client(project=project)
    aliases = load_aliases(bq, project) if args.entity_filter else []

    per_question = []
    for q in spec["questions"]:
        teams = detect_teams(q["question"], aliases) if args.entity_filter else {}
        vector = model.encode(f"query: {q['question']}", normalize_embeddings=True).tolist()
        results = search(bq, project, vector, None, TOP_K, list(teams))
        scores = score_question(results, q["team"], topics[q["topic"]])
        per_question.append({"id": q["id"], "question": q["question"], "teams_detected": list(teams.values()),
                             **scores, "result_titles": [r["title"] for r in results]})
        flags = "".join("Y" if f else "." for f in scores["relevant_flags"])
        detected = ",".join(teams.values()) if teams else "-"
        print(f"{q['id']} [{flags}] P@5={scores['precision']:.1f} EP@5={scores['entity_precision']:.1f} RR={scores['reciprocal_rank']:.2f}  teams={detected:<16} {q['question'].encode('ascii', 'replace').decode()}")

    n = len(per_question)
    summary = {
        "label": args.label,
        "entity_filter": args.entity_filter,
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "questions": n,
        "hit_at_5": sum(q["hit"] for q in per_question) / n,
        "precision_at_5": sum(q["precision"] for q in per_question) / n,
        "entity_precision_at_5": sum(q["entity_precision"] for q in per_question) / n,
        "mrr": sum(q["reciprocal_rank"] for q in per_question) / n,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{args.label}_{summary['run_at'].replace(':', '')}.json"
    out.write_text(json.dumps({"summary": summary, "questions": per_question}, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(f"label                 {summary['label']}")
    print(f"entity_filter         {summary['entity_filter']}")
    print(f"hit@5                 {summary['hit_at_5']:.2f}")
    print(f"precision@5           {summary['precision_at_5']:.2f}")
    print(f"entity_precision@5    {summary['entity_precision_at_5']:.2f}")
    print(f"mrr                   {summary['mrr']:.2f}")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()