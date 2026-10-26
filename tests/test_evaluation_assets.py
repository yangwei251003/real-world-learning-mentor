from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT


EVALS = ROOT / "evals"


def load(name: str):
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


def load_scorecard_module():
    path = EVALS / "scorecard.py"
    spec = importlib.util.spec_from_file_location("mentor_scorecard", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blind_catalog_has_unique_cases_required_domains_and_no_answer_leakage():
    payload = load("blind_cases.json")
    cases = payload["cases"]
    assert len(cases) >= 20
    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert all(case.get("major_variant") and case.get("domain") and case.get("setup") for case in cases)
    assert all(isinstance(case.get("turns"), list) and case["turns"] for case in cases)

    required_domains = {"STM32", "Python", "摄影", "英语口语", "经济学", "统计", "产品设计", "营销", "历史"}
    assert required_domains <= {case["domain"] for case in cases}
    for prefix in "ABCDEFGHIJ":
        assert any(case_id.startswith(prefix) for case_id in ids), f"缺少 Case {prefix}"

    candidate_text = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("must_observe", "must_not_observe", "dimension_scores", "hard_failure_watch"):
        assert forbidden not in candidate_text


def test_evaluator_assertions_cover_every_blind_case_exactly_once():
    cases = load("blind_cases.json")["cases"]
    assertions = load("blind_assertions.json")["assertions"]
    case_ids = {case["case_id"] for case in cases}
    assertion_ids = [item["case_id"] for item in assertions]
    assert len(assertion_ids) == len(set(assertion_ids))
    assert set(assertion_ids) == case_ids
    for item in assertions:
        assert len(item.get("must_observe", [])) >= 2
        assert len(item.get("must_not_observe", [])) >= 2
        assert item.get("focus_dimensions")


def test_every_referenced_state_fixture_has_a_unique_constructible_definition():
    cases = load("blind_cases.json")["cases"]
    fixture_payload = load("state_fixtures.json")
    fixtures = fixture_payload["fixtures"]
    ids = [item["fixture_id"] for item in fixtures]
    assert len(ids) == len(set(ids))
    assert {case["state_fixture"] for case in cases if case.get("state_fixture")} == set(ids)
    for fixture in fixtures:
        assert fixture["kind"] in {"valid-ledger", "fault-injection"}
        if fixture["kind"] == "valid-ledger":
            assert fixture.get("operations") and fixture["operations"][0]["command"] == "begin"
            assert all(operation["command"] in {"begin", "record", "finish"} for operation in fixture["operations"])
        else:
            assert fixture.get("base_fixture") in ids
            assert fixture.get("fault_injection", {}).get("expected_integrity_result") == "fail-closed"


def test_fixture_builder_materializes_valid_and_intentionally_corrupt_states(tmp_path):
    builder = EVALS / "build_state_fixture.py"
    valid_dir = tmp_path / "有效夹具"
    valid = subprocess.run(
        [sys.executable, str(builder), "resume-python-valid", "--state-dir", str(valid_dir)],
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["integrity"] == "valid"

    bad_dir = tmp_path / "损坏夹具"
    bad = subprocess.run(
        [sys.executable, str(builder), "resume-python-tampered", "--state-dir", str(bad_dir)],
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert bad.returncode == 0, bad.stderr
    assert json.loads(bad.stdout)["integrity"] == "intentionally-invalid"


def test_rubric_has_nine_required_dimensions_with_behavioral_anchors():
    rubric = load("rubric.json")
    dimensions = rubric["dimensions"]
    assert len(dimensions) == 9
    assert [item["id"] for item in dimensions] == [f"D{i}" for i in range(1, 10)]
    assert all(item["required"] for item in dimensions)
    for item in dimensions:
        assert all(len(item[key]) >= 14 for key in ("zero", "two", "four"))
    limits = rubric["normalization"]
    assert limits == {
        "formula": "round(sum(dimension_scores) / 36 * 100, 1)",
        "case_pass_score": 80,
        "suite_mean_score": 85,
        "required_dimension_minimum": 3,
        "green_improvement_over_red": 12,
        "hard_failure_override": True,
    }


def test_hard_failures_are_unique_and_cover_method_safety_evidence_and_freshness():
    rules = load("hard_failures.json")["rules"]
    ids = [item["id"] for item in rules]
    assert len(ids) >= 11 and len(ids) == len(set(ids))
    assert ids == [f"HF{i:02d}" for i in range(1, len(ids) + 1)]
    text = json.dumps(rules, ensure_ascii=False)
    for concept in ("第一性原理", "奥卡姆", "苏格拉底", "对抗审查", "费曼", "MVP", "逆向拆解", "复盘", "安全门", "证据", "连续性", "新鲜度"):
        assert concept in text


def test_red_baseline_is_honest_structured_and_covers_a_to_j():
    baseline = load("red_baseline.json")
    assert baseline["evidence_level"] == "structured_pre_skill_hypothesis"
    assert "不伪装" in baseline["integrity_note"]
    assert len(baseline["common_observations"]) >= 8
    cases = baseline["cases"]
    assert [item["case"] for item in cases] == list("ABCDEFGHIJ")
    assert all(item["typical_failure"] and len(item["observable_evidence"]) >= 3 for item in cases)


def complete_report(score: int = 4) -> dict:
    cases = load("blind_cases.json")["cases"]
    return {
        "judge_id": "judge-independent-1",
        "candidate_id": "candidate-green",
        "cases": [
            {
                "case_id": case["case_id"],
                "dimension_scores": {f"D{i}": score for i in range(1, 10)},
                "dimension_evidence": {f"D{i}": f"case evidence for D{i}" for i in range(1, 10)},
                "hard_failures": [],
            }
            for case in cases
        ],
    }


def test_scorecard_enforces_full_suite_thresholds_and_red_delta():
    module = load_scorecard_module()
    result = module.score_report(complete_report(), baseline_score=70)
    assert result["suite_score"] == 100
    assert result["green_improvement"] == 30
    assert all(result["checks"].values())
    assert result["passed"] is True


def test_any_hard_failure_overrides_perfect_scores():
    module = load_scorecard_module()
    report = complete_report()
    report["cases"][0]["hard_failures"] = ["HF12"]
    result = module.score_report(report, baseline_score=50)
    assert result["suite_score"] == 100
    assert result["checks"]["no_hard_failures"] is False
    assert result["passed"] is False


def test_scorecard_rejects_missing_dimensions_and_unknown_cases():
    module = load_scorecard_module()
    report = complete_report()
    del report["cases"][0]["dimension_scores"]["D9"]
    with pytest.raises(module.EvaluationError):
        module.score_report(report)
    report = complete_report()
    report["cases"][0]["case_id"] = "not-a-case"
    with pytest.raises(module.EvaluationError):
        module.score_report(report)
