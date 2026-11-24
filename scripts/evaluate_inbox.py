"""Score inbox classifier output against the synthetic golden set.

Predictions are JSONL records with id, category and evidence_quotes fields.
The script makes no network calls and never uses real inbox content.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "infrastructure" / "evaluations" / "inbox-golden.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        records.append(value)
    return records


def score(gold: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item.get("id")): item for item in predictions}
    if len(by_id) != len(predictions):
        raise ValueError("Prediction IDs must be unique.")
    gold_ids = {str(item["id"]) for item in gold}
    extras = set(by_id) - gold_ids
    if extras:
        raise ValueError(f"Predictions contain unknown IDs: {', '.join(sorted(extras))}")

    correct = grounded = supplied_quotes = 0
    for item in gold:
        prediction = by_id.get(str(item["id"]))
        if prediction is None:
            continue
        correct += prediction.get("category") == item["expected_category"]
        quotes = prediction.get("evidence_quotes", [])
        if not isinstance(quotes, list):
            raise ValueError(f"{item['id']}: evidence_quotes must be a list")
        supplied_quotes += bool(quotes)
        source = str(item["email"]).casefold()
        grounded += bool(quotes) and all(
            isinstance(quote, str) and quote.casefold() in source for quote in quotes
        )

    total = len(gold)
    predicted = len(by_id)
    return {
        "gold_records": total,
        "predicted_records": predicted,
        "coverage": round(predicted / total, 4) if total else 0,
        "category_accuracy": round(correct / predicted, 4) if predicted else 0,
        "grounded_evidence_rate": round(grounded / predicted, 4) if predicted else 0,
        "records_with_evidence": supplied_quotes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path, help="JSONL predictions from an evaluation run")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH, help="Golden JSONL dataset")
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    parser.add_argument("--min-grounding", type=float, default=0.0)
    args = parser.parse_args()
    try:
        metrics = score(read_jsonl(args.gold), read_jsonl(args.predictions))
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        print(f"Evaluation input error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return int(
        metrics["category_accuracy"] < args.min_accuracy
        or metrics["grounded_evidence_rate"] < args.min_grounding
    )


if __name__ == "__main__":
    raise SystemExit(main())
