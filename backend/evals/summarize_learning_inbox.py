from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = ROOT / "runtime" / "learning_inbox"


def iter_records(inbox_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not inbox_dir.exists():
        return records
    for path in sorted(inbox_dir.glob("learning-*.jsonl")):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counter = Counter(str(record.get("reason") or "unknown") for record in records)
    stage_counter = Counter(str(record.get("stage") or "unknown") for record in records)
    question_counter = Counter(str(record.get("question") or "") for record in records)
    return {
        "total": len(records),
        "by_reason": dict(reason_counter.most_common()),
        "by_stage": dict(stage_counter.most_common()),
        "top_questions": [
            {"question": question, "count": count}
            for question, count in question_counter.most_common(10)
            if question
        ],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Summarize Hotel AI learning inbox samples.")
    parser.add_argument("--inbox", default=str(DEFAULT_INBOX), help="Path to learning_inbox directory.")
    args = parser.parse_args()
    summary = summarize(iter_records(Path(args.inbox)))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
