from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import METHOD_TOOL, ROOT, run_method


METHOD_IDS = {
    "first_principles",
    "occams_razor",
    "socratic_questioning",
    "adversarial_review",
    "brainstorm_transfer",
    "feynman",
    "mvp_learning",
    "reverse_decomposition",
    "closed_loop_review",
    "gray_cognition_black_white_execution",
}


def context_file(tmp_path: Path, value: dict, name: str = "学习情境.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def recommendation(tmp_path: Path, value: dict) -> dict:
    path = context_file(tmp_path, value)
    _, payload = run_method("recommend", "--context-json", str(path))
    return payload


def test_method_cli_exposes_only_the_two_planned_commands():
    completed = subprocess.run(
        [sys.executable, str(METHOD_TOOL), "--help"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "recommend" in completed.stdout and "validate-audit" in completed.stdout
    assert "--context-json" in subprocess.run(
        [sys.executable, str(METHOD_TOOL), "recommend", "--help"],
        text=True, encoding="utf-8", capture_output=True, check=False
    ).stdout


@pytest.mark.parametrize(
    ("context", "primary", "required_support"),
    [
        ({"preference_mode": "auto", "available_minutes": 15}, "mvp_learning", {"reverse_decomposition"}),
        ({"preference_mode": "auto", "goal_clarity": "unclear"}, "mvp_learning", set()),
        ({"preference_mode": "auto", "resources_known": False}, "mvp_learning", set()),
        ({"preference_mode": "auto", "authentic_outcome": "能拍出两张可比较照片"}, "reverse_decomposition", {"mvp_learning", "feynman"}),
        ({"preference_mode": "auto", "same_concept_error_count": 2}, "first_principles", {"feynman"}),
        ({"preference_mode": "auto", "can_do_cannot_explain": True}, "feynman", {"socratic_questioning"}),
        ({"preference_mode": "auto", "transfer_failure": True}, "brainstorm_transfer", {"closed_loop_review"}),
        ({"preference_mode": "auto", "high_risk": True}, "adversarial_review", {"gray_cognition_black_white_execution"}),
    ],
)
def test_auto_selector_follows_explainable_priority_rules(tmp_path, context, primary, required_support):
    result = recommendation(tmp_path, context)
    assert result["ok"] is True
    assert result["primary_method"] == primary
    assert required_support <= set(result["supporting_methods"])
    assert len(result["supporting_methods"]) <= 2
    assert set(result["background_audit_methods"]) == METHOD_IDS
    assert result["rationale"] and result["next_evidence_to_collect"]
    assert result["reconsider_when"]


def test_recommendation_output_has_stable_public_contract(tmp_path):
    result = recommendation(tmp_path, {"preference_mode": "auto"})
    required = {
        "selector_version",
        "preference_mode",
        "primary_method",
        "supporting_methods",
        "background_audit_methods",
        "confidence",
        "rationale",
        "next_evidence_to_collect",
        "reconsider_when",
    }
    assert required <= set(result)
    assert result["preference_mode"] == "auto"
    assert isinstance(result["confidence"], (int, float)) and 0 <= result["confidence"] <= 1
    assert result["primary_method"] not in result["supporting_methods"]


def test_locked_and_custom_modes_respect_order_and_cap_foreground_at_three(tmp_path):
    locked = recommendation(
        tmp_path,
        {"preference_mode": "locked", "ordered_methods": ["逆向拆解", "费曼"]},
    )
    assert locked["primary_method"] == "reverse_decomposition"
    assert locked["supporting_methods"] == ["feynman"]

    custom = recommendation(
        tmp_path,
        {
            "preference_mode": "custom",
            "ordered_methods": ["费曼", "苏格拉底", "MVP学习", "对抗审查", "闭环复盘"],
        },
    )
    assert custom["primary_method"] == "feynman"
    assert custom["supporting_methods"] == ["socratic_questioning", "mvp_learning"]
    assert 1 + len(custom["supporting_methods"]) <= 3
    assert set(custom["background_audit_methods"]) == METHOD_IDS


def test_invalid_mode_unknown_method_and_empty_locked_selection_fail_closed(tmp_path):
    for index, value in enumerate(
        (
            {"preference_mode": "mystery"},
            {"preference_mode": "locked", "ordered_methods": []},
            {"preference_mode": "custom", "ordered_methods": ["玄学速成法"]},
        )
    ):
        path = context_file(tmp_path, value, f"bad-{index}.json")
        _, error = run_method("recommend", "--context-json", str(path), ok=False)
        assert error.get("ok") is False
        assert error.get("error")


def test_frozen_mix_is_stable_until_explicit_reconsideration_trigger(tmp_path):
    current = {
        "recommendation_id": "stable-mix-1",
        "primary_method": "reverse_decomposition",
        "supporting_methods": ["mvp_learning", "feynman"],
        "confidence": 0.81,
        "frozen_for_session": True,
    }
    frozen = recommendation(
        tmp_path,
        {
            "preference_mode": "auto",
            "same_concept_error_count": 2,
            "current_method_mix": current,
            "reconsideration_triggers": [],
        },
    )
    assert frozen["recommendation_id"] == "stable-mix-1"
    assert frozen["primary_method"] == "reverse_decomposition"

    changed = recommendation(
        tmp_path,
        {
            "preference_mode": "auto",
            "same_concept_error_count": 2,
            "current_method_mix": current,
            "reconsideration_triggers": ["same_concept_error_twice"],
        },
    )
    assert changed["primary_method"] == "first_principles"


def valid_audit() -> dict:
    stages: dict[str, list[dict]] = {}
    for phase in ("research", "planning", "teaching", "review"):
        stages[phase] = [
            {
                "method_id": method_id,
                "status": "pass",
                "reason": f"{phase} check",
                "action": "none",
                "evidence_ref": f"evidence:{phase}:{method_id}",
            }
            for method_id in sorted(METHOD_IDS)
        ]
    return {"stages": stages}


def test_audit_validator_requires_all_ten_methods_in_all_four_phases(tmp_path):
    path = context_file(tmp_path, valid_audit(), "四阶段审查.json")
    _, result = run_method("validate-audit", "--audit-json", str(path))
    assert result["valid"] is True
    assert set(result["phases"]) == {"research", "planning", "teaching", "review"}
    assert result["method_count"] == 10

    broken = valid_audit()
    broken["stages"]["teaching"].pop()
    path = context_file(tmp_path, broken, "缺方法.json")
    _, error = run_method("validate-audit", "--audit-json", str(path), ok=False)
    assert error["ok"] is False
    assert "teaching" in error["error"]


def test_deferred_audit_requires_reason_and_all_records_require_evidence_fields(tmp_path):
    audit = valid_audit()
    audit["stages"]["review"][0]["status"] = "deferred_with_reason"
    audit["stages"]["review"][0]["reason"] = ""
    path = context_file(tmp_path, audit, "无理由延期.json")
    _, error = run_method("validate-audit", "--audit-json", str(path), ok=False)
    assert "reason" in error["error"]

    audit = valid_audit()
    del audit["stages"]["research"][0]["evidence_ref"]
    path = context_file(tmp_path, audit, "无证据引用.json")
    _, error = run_method("validate-audit", "--audit-json", str(path), ok=False)
    assert "evidence_ref" in error["error"]

