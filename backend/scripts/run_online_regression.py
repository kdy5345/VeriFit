"""정답 세트와 Analyzer를 비교한다. --live만 유료 Gemini API를 호출한다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from app.agent.nodes import get_online_agent, validate_input
from app.core.config import settings
from app.schemas.agent import AnalyzedUserInput


GOLD_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "online_gold.json"


def semantic(analysis):
    return {"monthly_deposit_won": analysis.monthly_deposit_won, "term_months": analysis.term_months,
            "facts": {fact.code.value: fact.to_user_fact().model_dump() for fact in analysis.facts}}


def run(live=False, limit=None):
    # A model regression must make fresh calls, not measure cached answers.
    previous_cache = settings.cache_enabled
    settings.cache_enabled = False
    try:
        return _run(live, limit)
    finally:
        settings.cache_enabled = previous_cache


def _run(live=False, limit=None):
    cases = json.loads(GOLD_PATH.read_text(encoding="utf-8"))["cases"]
    if limit is not None:
        cases = cases[:limit]
    results = []
    for case in cases:
        expected = AnalyzedUserInput.model_validate(case["expected"])
        try:
            actual = get_online_agent().analyze(case["message"]) if live else expected
            validated = validate_input({"message": case["message"], "analysis": actual})
            errors = validated["errors"]
            passed = semantic(actual) == semantic(expected) and not errors
            results.append({"id": case["id"], "passed": passed, "validation_errors": errors,
                            "expected": semantic(expected), "actual": semantic(actual)})
        except Exception as exc:
            results.append({"id": case["id"], "passed": False, "error": str(exc)})
    prompt_file = Path(__file__).parents[1] / "app" / "services" / "online_agent_llm.py"
    return {"mode": "live_analyzer" if live else "gold_contract_only", "model": settings.online_agent_model,
            "prompt_source_hash": hashlib.sha256(prompt_file.read_bytes()).hexdigest(),
            "total": len(results), "passed": sum(r["passed"] for r in results), "cases": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="실제 Gemini 호출. 기본 실행은 정답 계약만 검증합니다.")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit는 1 이상이어야 합니다.")
    report = run(args.live, args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["passed"] == report["total"] else 1)
