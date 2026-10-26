from __future__ import annotations

import json
from pathlib import Path

from conftest import find_revision, run_state


TRACK = "统计-家庭用电"


def init_track(tmp_path: Path) -> tuple[Path, int]:
    state_dir = tmp_path / "学习门状态"
    run_state(state_dir, "init")
    _, begun = run_state(
        state_dir,
        "begin",
        "--track-id", TRACK,
        "--goal", "用统计判断家庭用电异常",
        "--authentic-outcome", "解释一份 30 天数据中的异常日期",
        "--primary-adapter", "data-math",
        "--mvc", "能计算、解释并检查一个异常判断",
        "--next-action", "先圈出看起来异常的一天并说明理由",
        "--expected-revision", "0",
        "--idempotency-key", "begin-statistics",
    )
    return state_dir, find_revision(begun)


def record(state_dir: Path, revision: int, event_type: str, payload: dict, key: str, ok: bool = True):
    _, result = run_state(
        state_dir,
        "record",
        "--track-id", TRACK,
        "--event-type", event_type,
        "--payload", json.dumps(payload, ensure_ascii=False),
        "--expected-revision", str(revision),
        "--idempotency-key", key,
        ok=ok,
    )
    return result


def revision(state_dir: Path) -> int:
    _, payload = run_state(state_dir, "status")
    return payload["state"]["revision"]


def test_applied_and_higher_mastery_require_known_evidence(tmp_path):
    state_dir, current = init_track(tmp_path)
    rejected = record(
        state_dir,
        current,
        "learning.mastery_updated",
        {"concept_id": "mean", "level": "Applied"},
        "applied-without-evidence",
        ok=False,
    )
    assert "evidence" in rejected["error"].lower()
    assert revision(state_dir) == current

    rejected = record(
        state_dir,
        current,
        "learning.mastery_updated",
        {"concept_id": "mean", "level": "Diagnosed", "evidence_ids": ["missing"]},
        "unknown-evidence",
        ok=False,
    )
    assert "unknown" in rejected["error"].lower()
    assert revision(state_dir) == current

    evidence = record(
        state_dir,
        current,
        "learning.evidence_recorded",
        {
            "evidence_id": "calc-1",
            "kind": "worked-analysis",
            "summary": "独立算出均值，并指出一处抄录错误",
            "verification_level": "user-reported",
        },
        "evidence-calc-1",
    )
    current = find_revision(evidence)
    applied = record(
        state_dir,
        current,
        "learning.mastery_updated",
        {"concept_id": "mean", "level": "Applied", "evidence_ids": ["calc-1"]},
        "applied-with-evidence",
    )
    assert find_revision(applied) == current + 1


def test_transferred_requires_condition_change_and_reduced_assistance(tmp_path):
    state_dir, current = init_track(tmp_path)
    evidence = record(
        state_dir,
        current,
        "learning.evidence_recorded",
        {
            "evidence_id": "transfer-1",
            "kind": "transfer-performance",
            "summary": "换用另一周数据完成判断，并提交计算记录",
            "verification_level": "artifact-observed",
            "transfer_context": "从训练周数据换为另一周家庭用电数据",
        },
        "transfer-evidence",
    )
    current = find_revision(evidence)

    for index, payload in enumerate(
        (
            {"concept_id": "outlier", "level": "Transferred", "evidence_ids": ["transfer-1"]},
            {"concept_id": "outlier", "level": "Transferred", "evidence_ids": ["transfer-1"], "changed_dimension": "context"},
            {"concept_id": "outlier", "level": "Transferred", "evidence_ids": ["transfer-1"], "changed_dimension": "invalid", "assistance_reduced": True},
        )
    ):
        rejected = record(
            state_dir, current, "learning.mastery_updated", payload, f"bad-transfer-{index}", ok=False
        )
        assert "transferred" in rejected["error"].lower()
        assert revision(state_dir) == current

    accepted = record(
        state_dir,
        current,
        "learning.mastery_updated",
        {
            "concept_id": "outlier",
            "level": "Transferred",
            "evidence_ids": ["transfer-1"],
            "changed_dimension": "context",
            "assistance_reduced": True,
        },
        "valid-transfer",
    )
    assert find_revision(accepted) == current + 1


def test_readiness_failure_blocks_practice_until_targeted_remediation_and_reassessment(tmp_path):
    state_dir, current = init_track(tmp_path)
    failed = record(
        state_dir,
        current,
        "learning.readiness_assessed",
        {
            "score": 2,
            "total": 5,
            "required_score": 4,
            "passed": False,
            "missed_concepts": ["均值与中位数", "公开数据隐私"],
        },
        "readiness-failed",
    )
    current = find_revision(failed)
    blocked = record(
        state_dir,
        current,
        "learning.session_progressed",
        {"requires_readiness": True, "route_stage": "Follow", "next_action": "直接分析完整数据"},
        "practice-too-early",
        ok=False,
    )
    assert "readiness" in blocked["error"].lower()
    assert revision(state_dir) == current

    passed = record(
        state_dir,
        current,
        "learning.readiness_assessed",
        {"score": 4, "total": 5, "required_score": 4, "passed": True, "missed_concepts": []},
        "readiness-reassessed",
    )
    current = find_revision(passed)
    progressed = record(
        state_dir,
        current,
        "learning.session_progressed",
        {"requires_readiness": True, "route_stage": "Follow", "next_action": "先计算前三天均值"},
        "practice-after-readiness",
    )
    assert find_revision(progressed) == current + 1


def test_risky_practice_requires_a_passed_safety_gate_not_merely_a_warning(tmp_path):
    state_dir, current = init_track(tmp_path)
    blocked = record(
        state_dir,
        current,
        "learning.session_progressed",
        {"risk_level": "high", "route_stage": "Follow", "next_action": "进行高风险实操"},
        "risk-without-gate",
        ok=False,
    )
    assert "safety gate" in blocked["error"].lower()
    assert revision(state_dir) == current

    denied_gate = record(
        state_dir,
        current,
        "learning.safety_gate_recorded",
        {"gate_id": "high-energy", "risk_level": "high", "risk_category": "energy", "action_id": "sandbox-analysis", "status": "blocked", "reason": "保护条件未确认"},
        "blocked-gate",
    )
    current = find_revision(denied_gate)
    blocked_again = record(
        state_dir,
        current,
        "learning.session_progressed",
        {"risk_level": "high", "risk_category": "energy", "action_id": "sandbox-analysis", "safety_gate_id": "high-energy", "route_stage": "Follow", "next_action": "仍尝试实操"},
        "risk-after-blocked-gate",
        ok=False,
    )
    assert "safety gate" in blocked_again["error"].lower()

    allowed_gate = record(
        state_dir,
        current,
        "learning.safety_gate_recorded",
        {"gate_id": "high-energy", "risk_level": "high", "risk_category": "energy", "action_id": "sandbox-analysis", "status": "passed", "reason": "已改为安全沙盒"},
        "passed-gate",
    )
    current = find_revision(allowed_gate)
    progressed = record(
        state_dir,
        current,
        "learning.session_progressed",
        {"risk_level": "high", "risk_category": "energy", "action_id": "sandbox-analysis", "safety_gate_id": "high-energy", "route_stage": "Follow", "next_action": "在已确认沙盒内执行"},
        "risk-after-passed-gate",
    )
    assert find_revision(progressed) == current + 1


def test_unrelated_low_risk_gate_cannot_authorize_high_risk_action(tmp_path):
    state_dir, current = init_track(tmp_path)
    gate = record(
        state_dir, current, "learning.safety_gate_recorded",
        {"gate_id": "low-photo", "risk_level": "low", "risk_category": "privacy", "action_id": "crop-public-image", "status": "passed", "reason": "使用公开图片"},
        "low-gate",
    )
    current = find_revision(gate)
    rejected = record(
        state_dir, current, "learning.session_progressed",
        {"risk_level": "high", "risk_category": "energy", "action_id": "open-battery-pack", "safety_gate_id": "low-photo", "route_stage": "Follow", "next_action": "拆开电池包"},
        "unrelated-gate", ok=False,
    )
    assert "matching" in rejected["error"].lower()
    assert revision(state_dir) == current


def test_transferred_rejects_only_vague_self_report(tmp_path):
    state_dir, current = init_track(tmp_path)
    evidence = record(
        state_dir, current, "learning.evidence_recorded",
        {"evidence_id": "vague-transfer", "summary": "我感觉挺好，应该会了", "verification_level": "user-reported"},
        "vague-evidence",
    )
    current = find_revision(evidence)
    rejected = record(
        state_dir, current, "learning.mastery_updated",
        {"concept_id": "outlier", "level": "Transferred", "evidence_ids": ["vague-transfer"], "changed_dimension": "context", "assistance_reduced": True},
        "vague-transfer-mastery", ok=False,
    )
    assert "independently checkable" in rejected["error"].lower()
    assert revision(state_dir) == current


def test_source_and_method_audit_events_fail_closed(tmp_path):
    state_dir, current = init_track(tmp_path)
    bad_source = record(
        state_dir, current, "learning.source_recorded",
        {"source_id": "bare-source"}, "bare-source", ok=False,
    )
    assert "required fields" in bad_source["error"].lower()
    bad_audit = record(
        state_dir, current, "learning.method_audit_recorded",
        {"audit_id": "empty-audit", "stages": {}}, "empty-audit", ok=False,
    )
    assert "invalid method audit" in bad_audit["error"].lower()
    assert revision(state_dir) == current


def test_valid_source_and_full_method_audit_are_recorded(tmp_path):
    state_dir, current = init_track(tmp_path)
    source = record(
        state_dir,
        current,
        "learning.source_recorded",
        {
            "source_id": "official-current",
            "title": "Official current guide",
            "url": "https://example.com/official-guide",
            "publisher": "Example Authority",
            "accessed_at": "2026-08-26T00:00:00Z",
            "version_or_date": "2026-08-01",
            "license": "factual reference only",
            "supported_claim": "Supports the current tool step",
            "freshness_class": "volatile-7-30d",
            "expires_at": "2099-09-01T00:00:00Z",
            "conflict_status": "none",
            "use_scope": "current",
        },
        "valid-source",
    )
    current = find_revision(source)
    method_ids = [
        "first_principles", "occams_razor", "socratic_questioning",
        "adversarial_review", "brainstorm_transfer", "feynman",
        "mvp_learning", "reverse_decomposition", "closed_loop_review",
        "gray_cognition_black_white_execution",
    ]
    records = [
        {"method_id": method_id, "status": "pass", "reason": "checked", "action": "none", "evidence_ref": None}
        for method_id in method_ids
    ]
    audit = record(
        state_dir,
        current,
        "learning.method_audit_recorded",
        {"audit_id": "full-audit", "stages": {phase: records for phase in ("research", "planning", "teaching", "review")}},
        "valid-audit",
    )
    assert find_revision(audit) == current + 1


def test_expired_source_cannot_support_current_claim(tmp_path):
    state_dir, current = init_track(tmp_path)
    rejected = record(
        state_dir,
        current,
        "learning.source_recorded",
        {
            "source_id": "expired-current",
            "title": "Old current guide",
            "url": "https://example.com/old-guide",
            "publisher": "Example Authority",
            "accessed_at": "2025-01-01T00:00:00Z",
            "version_or_date": "2024",
            "license": "factual reference only",
            "supported_claim": "Claims to support a current tool step",
            "freshness_class": "volatile-7-30d",
            "expires_at": "2025-02-01T00:00:00Z",
            "conflict_status": "none",
            "use_scope": "current",
        },
        "expired-source",
        ok=False,
    )
    assert "expired source" in rejected["error"].lower()
    assert revision(state_dir) == current


def test_invalid_readiness_claim_cannot_override_computed_score(tmp_path):
    state_dir, current = init_track(tmp_path)
    rejected = record(
        state_dir,
        current,
        "learning.readiness_assessed",
        {"score": 1, "total": 5, "required_score": 4, "passed": True},
        "false-readiness-pass",
        ok=False,
    )
    assert "conflict" in rejected["error"].lower()
    assert revision(state_dir) == current


def test_method_mix_state_rejects_more_than_one_primary_or_two_supporting_methods(tmp_path):
    state_dir, current = init_track(tmp_path)
    valid = record(
        state_dir,
        current,
        "learning.method_mix_set",
        {
            "selector_version": "1.0.0",
            "preference_mode": "auto",
            "primary_method": "reverse_decomposition",
            "supporting_methods": ["mvp_learning", "feynman"],
            "background_audit_methods": ["first_principles"],
            "confidence": 0.86,
            "rationale": ["已有明确真实成果"],
            "next_evidence_to_collect": "完成第一检查点",
            "reconsider_when": ["连续错误两次"],
            "frozen_for_session": True,
        },
        "valid-method-mix",
    )
    current = find_revision(valid)
    rejected = record(
        state_dir,
        current,
        "learning.method_mix_set",
        {
            "primary_method": "reverse_decomposition",
            "supporting_methods": ["mvp_learning", "feynman", "socratic_questioning"],
        },
        "too-many-methods",
        ok=False,
    )
    assert "support" in rejected["error"].lower() or "method" in rejected["error"].lower()
    assert revision(state_dir) == current
