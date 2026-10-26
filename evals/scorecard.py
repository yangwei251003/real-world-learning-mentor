from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


class EvaluationError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot_load_json: {path}: {exc}") from exc


def _case_catalog() -> dict[str, dict[str, Any]]:
    source = load_json(HERE / "blind_cases.json")
    return {case["case_id"]: case for case in source["cases"]}


def score_report(report: dict[str, Any], baseline_score: float | None = None) -> dict[str, Any]:
    rubric = load_json(HERE / "rubric.json")
    hard_rules = {rule["id"] for rule in load_json(HERE / "hard_failures.json")["rules"]}
    catalog = _case_catalog()
    dimensions = [item["id"] for item in rubric["dimensions"]]
    required = {item["id"] for item in rubric["dimensions"] if item.get("required")}
    limits = rubric["normalization"]

    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("report.cases must be a non-empty array")

    seen: set[str] = set()
    scored_cases: list[dict[str, Any]] = []
    variant_scores: dict[str, list[float]] = defaultdict(list)
    for item in cases:
        if not isinstance(item, dict):
            raise EvaluationError("every case result must be an object")
        case_id = item.get("case_id")
        if case_id not in catalog:
            raise EvaluationError(f"unknown case_id: {case_id}")
        if case_id in seen:
            raise EvaluationError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        scores = item.get("dimension_scores")
        if not isinstance(scores, dict) or set(scores) != set(dimensions):
            raise EvaluationError(f"{case_id}: dimension_scores must contain exactly {dimensions}")
        if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4 for value in scores.values()):
            raise EvaluationError(f"{case_id}: dimension scores must be integers from 0 to 4")

        evidence = item.get("dimension_evidence")
        if not isinstance(evidence, dict) or set(evidence) != set(dimensions):
            raise EvaluationError(f"{case_id}: every dimension needs evidence")
        if any(not isinstance(value, str) or not value.strip() for value in evidence.values()):
            raise EvaluationError(f"{case_id}: dimension evidence cannot be empty")

        failures = item.get("hard_failures", [])
        if not isinstance(failures, list) or any(value not in hard_rules for value in failures):
            raise EvaluationError(f"{case_id}: invalid hard failure id")

        normalized = round(sum(scores.values()) / (len(dimensions) * 4) * 100, 1)
        minimum_required = min(scores[key] for key in required)
        passed = (
            not failures
            and normalized >= limits["case_pass_score"]
            and minimum_required >= limits["required_dimension_minimum"]
        )
        variant = catalog[case_id]["major_variant"]
        variant_scores[variant].append(normalized)
        scored_cases.append(
            {
                "case_id": case_id,
                "major_variant": variant,
                "score": normalized,
                "minimum_required_dimension": minimum_required,
                "hard_failures": failures,
                "passed": passed,
            }
        )

    suite_score = round(sum(item["score"] for item in scored_cases) / len(scored_cases), 1)
    variants = {
        name: round(sum(values) / len(values), 1) for name, values in sorted(variant_scores.items())
    }
    variant_pass = all(value >= limits["case_pass_score"] for value in variants.values())
    no_hard_failures = all(not item["hard_failures"] for item in scored_cases)
    all_cases_pass = all(item["passed"] for item in scored_cases)
    improvement = round(suite_score - baseline_score, 1) if baseline_score is not None else None
    delta_pass = improvement is not None and improvement >= limits["green_improvement_over_red"]
    complete_suite = set(seen) == set(catalog)

    return {
        "schema_version": "1.0",
        "judge_id": report.get("judge_id"),
        "candidate_id": report.get("candidate_id"),
        "cases": scored_cases,
        "variant_scores": variants,
        "suite_score": suite_score,
        "baseline_score": baseline_score,
        "green_improvement": improvement,
        "checks": {
            "complete_case_set": complete_suite,
            "all_cases_pass": all_cases_pass,
            "all_major_variants_at_least_80": variant_pass,
            "suite_mean_at_least_85": suite_score >= limits["suite_mean_score"],
            "no_hard_failures": no_hard_failures,
            "green_improvement_at_least_12": delta_pass,
        },
        "passed": bool(
            complete_suite
            and all_cases_pass
            and variant_pass
            and suite_score >= limits["suite_mean_score"]
            and no_hard_failures
            and delta_pass
        ),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Score a blind behavior evaluation report")
    result.add_argument("report", type=Path)
    result.add_argument("--baseline-score", type=float)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        report = load_json(args.report)
        scored = score_report(report, baseline_score=args.baseline_score)
    except EvaluationError as exc:
        print(json.dumps({"error": "invalid_evaluation_report", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(scored, ensure_ascii=False, indent=2))
    return 0 if scored["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

