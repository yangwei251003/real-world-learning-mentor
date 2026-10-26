#!/usr/bin/env python3
"""Explainable method-mix recommendation and four-phase audit validation."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any


SELECTOR_VERSION = "1.0.0"
PHASES = ("research", "planning", "teaching", "review")
STATUSES = {"pass", "adjusted", "deferred_with_reason"}
DEFAULT_METHOD_IDS = (
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
)


class MethodError(RuntimeError):
    pass


def load_json(raw: str) -> Any:
    try:
        if raw == "-":
            return json.load(sys.stdin)
        path = Path(raw)
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodError(f"invalid JSON input: {exc}") from exc


def registry_path() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "methodologies" / "method-registry.json"


def load_registry() -> tuple[list[dict[str, Any]], dict[str, str]]:
    path = registry_path()
    if not path.is_file():
        raise MethodError(f"method registry is missing: {path}")
    value = load_json(str(path))
    methods = value.get("methods") if isinstance(value, dict) else None
    if not isinstance(methods, list) or len(methods) != 10:
        raise MethodError("method registry must contain exactly 10 methods")
    aliases: dict[str, str] = {}
    for item in methods:
        method_id = item.get("id")
        if not isinstance(method_id, str):
            raise MethodError("every method requires a string id")
        aliases[method_id.lower()] = method_id
        for alias in item.get("aliases", []):
            aliases[str(alias).strip().lower()] = method_id
        name = item.get("name")
        if name:
            aliases[str(name).strip().lower()] = method_id
    return methods, aliases


def normalize_method(value: str, aliases: dict[str, str]) -> str:
    key = value.strip().lower()
    if key not in aliases:
        raise MethodError(f"unknown learning method: {value}")
    return aliases[key]


def normalize_requested(context: dict[str, Any], aliases: dict[str, str]) -> tuple[str, list[str]]:
    mode = str(context.get("preference_mode", context.get("mode", "auto"))).lower()
    if mode not in {"auto", "locked", "custom"}:
        raise MethodError("preference_mode must be auto, locked, or custom")
    raw = context.get("ordered_methods", context.get("preferred_methods", []))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise MethodError("ordered_methods must be a list")
    requested: list[str] = []
    for item in raw:
        method = normalize_method(str(item), aliases)
        if method not in requested:
            requested.append(method)
    if mode == "locked" and not requested:
        primary = context.get("primary_method")
        if primary:
            requested = [normalize_method(str(primary), aliases)]
    if mode in {"locked", "custom"} and not requested:
        raise MethodError(f"{mode} mode requires at least one method")
    return mode, requested[:3]


def truthy(context: dict[str, Any], *keys: str) -> bool:
    return any(bool(context.get(key)) for key in keys)


def current_mix_if_frozen(context: dict[str, Any], all_ids: list[str]) -> dict[str, Any] | None:
    current = context.get("current_method_mix")
    if not isinstance(current, dict) or not current.get("frozen_for_session"):
        return None
    triggers = context.get("reconsideration_triggers", [])
    if triggers:
        return None
    primary = current.get("primary_method")
    supporting = current.get("supporting_methods", [])
    if primary not in all_ids or any(item not in all_ids for item in supporting):
        return None
    return {
        "selector_version": SELECTOR_VERSION,
        "recommendation_id": current.get("recommendation_id", str(uuid.uuid4())),
        "preference_mode": context.get("preference_mode", "auto"),
        "primary_method": primary,
        "supporting_methods": supporting[:2],
        "background_audit_methods": all_ids,
        "confidence": current.get("confidence", 0.8),
        "rationale": ["当前学习单元尚无重评触发条件，保持方法组合稳定。"],
        "next_evidence_to_collect": "完成当前检查点并记录结果、错误或独立解释。",
        "reconsider_when": ["学习阶段改变", "同类错误连续两次", "时间、资源或目标改变", "用户主动要求"],
        "frozen_for_session": True,
    }


def choose_auto(context: dict[str, Any]) -> tuple[str, list[str], list[str], float]:
    repeated = int(context.get("same_concept_error_count", context.get("repeated_error_count", 0)) or 0)
    minutes = context.get("available_minutes")
    goal_clear = context.get("goal_clarity", "clear") not in {"unclear", "low", False}
    resources_known = context.get("resources_known", True)
    high_risk = truthy(context, "high_risk", "high_cost", "irreversible")
    cannot_explain = truthy(context, "can_do_cannot_explain", "explanation_gap")
    transfer_failed = truthy(context, "transfer_failure", "cannot_transfer")
    authentic_outcome = truthy(context, "authentic_outcome", "clear_outcome", "practice_preference")

    if repeated >= 2:
        return (
            "first_principles",
            ["feynman", "adversarial_review" if high_risk else "mvp_learning"],
            ["同一概念已连续出错，需要回到底层因果并用通俗复述暴露误解。"],
            0.92,
        )
    if cannot_explain:
        return (
            "feynman",
            ["socratic_questioning", "mvp_learning"],
            ["当前主要差距是能做但说不清，需要复述与一个轻量追问。"],
            0.9,
        )
    if transfer_failed:
        return (
            "brainstorm_transfer",
            ["reverse_decomposition", "closed_loop_review"],
            ["当前案例已经会做，下一步应改变场景并复盘可迁移结构。"],
            0.86,
        )
    if high_risk:
        return (
            "adversarial_review",
            ["reverse_decomposition", "gray_cognition_black_white_execution"],
            ["任务风险或成本较高，必须先反向审查约束、停止条件和替代方案。"],
            0.94,
        )
    if (isinstance(minutes, (int, float)) and minutes <= 20) or not goal_clear or not resources_known:
        return (
            "mvp_learning",
            ["reverse_decomposition", "gray_cognition_black_white_execution"],
            ["时间、目标或资源仍有限，先取得一个最小真实结果和证据。"],
            0.84,
        )
    if authentic_outcome:
        return (
            "reverse_decomposition",
            ["mvp_learning", "feynman"],
            ["已有明确真实成果，适合从结果逆推最小行动并补必要原理。"],
            0.86,
        )
    return (
        "reverse_decomposition",
        ["mvp_learning", "feynman"],
        ["新手默认先看见知识的真实用途，再用小任务和通俗解释建立理解。"],
        0.72,
    )


def recommend(context: dict[str, Any]) -> dict[str, Any]:
    methods, aliases = load_registry()
    all_ids = [item["id"] for item in methods]
    mode, requested = normalize_requested(context, aliases)
    frozen = current_mix_if_frozen(context, all_ids)
    if frozen is not None and mode == "auto":
        return frozen

    if mode == "locked":
        primary, supporting = requested[0], requested[1:3]
        rationale = ["按用户锁定的方法组织本学习单元；安全与质量后台审查保持启用。"]
        confidence = 1.0
    elif mode == "custom":
        primary, supporting = requested[0], requested[1:3]
        rationale = ["按用户给定顺序激活最多三个方法，其余方法保持后台审查。"]
        confidence = 1.0
    else:
        primary, supporting, rationale, confidence = choose_auto(context)

    # Preserve one primary and no more than two unique supporting methods.
    supporting = [item for item in supporting if item != primary]
    supporting = list(dict.fromkeys(supporting))[:2]
    return {
        "selector_version": SELECTOR_VERSION,
        "recommendation_id": str(uuid.uuid4()),
        "preference_mode": mode,
        "primary_method": primary,
        "supporting_methods": supporting,
        "background_audit_methods": all_ids,
        "confidence": confidence,
        "rationale": rationale[:3],
        "next_evidence_to_collect": "完成第一个真实检查点，并记录结果、一个困难或独立解释。",
        "reconsider_when": ["学习阶段改变", "同类错误连续两次", "时间、资源或目标改变", "用户主动要求"],
        "frozen_for_session": True,
    }


def validate_audit(value: Any) -> dict[str, Any]:
    methods, _ = load_registry()
    method_ids = {item["id"] for item in methods}
    if not isinstance(value, dict) or not isinstance(value.get("stages"), dict):
        raise MethodError("audit must be an object with a stages object")
    stages = value["stages"]
    errors: list[str] = []
    for phase in PHASES:
        records = stages.get(phase)
        if not isinstance(records, list):
            errors.append(f"{phase}: expected a list of 10 records")
            continue
        seen: set[str] = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"{phase}[{index}]: record must be an object")
                continue
            method_id = record.get("method_id")
            status = record.get("status")
            if method_id not in method_ids:
                errors.append(f"{phase}[{index}]: unknown method_id {method_id!r}")
            elif method_id in seen:
                errors.append(f"{phase}: duplicate method_id {method_id}")
            seen.add(method_id)
            if status not in STATUSES:
                errors.append(f"{phase}[{index}]: invalid status {status!r}")
            for field in ("reason", "action", "evidence_ref"):
                if field not in record:
                    errors.append(f"{phase}[{index}]: missing {field}")
            if status == "deferred_with_reason" and not str(record.get("reason", "")).strip():
                errors.append(f"{phase}[{index}]: deferred record requires a reason")
        missing = sorted(method_ids - seen)
        if missing:
            errors.append(f"{phase}: missing methods {missing}")
    if errors:
        raise MethodError("; ".join(errors))
    return {"valid": True, "phases": list(PHASES), "method_count": len(method_ids)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    recommend_parser = subparsers.add_parser("recommend")
    recommend_parser.add_argument("--context-json", required=True)
    audit_parser = subparsers.add_parser("validate-audit")
    audit_parser.add_argument("--audit-json", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = build_parser().parse_args(argv)
        if args.command == "recommend":
            value = load_json(args.context_json)
            if not isinstance(value, dict):
                raise MethodError("context must be a JSON object")
            result = recommend(value)
        else:
            result = validate_audit(load_json(args.audit_json))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
        return 0
    except MethodError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
