from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from conftest import ROOT, SKILL_ROOT


METHOD_NAMES = (
    "第一性原理",
    "奥卡姆剃刀",
    "苏格拉底式提问",
    "对抗性审查",
    "头脑风暴拓维",
    "费曼学习法",
    "MVP 最小可行学习法",
    "逆向拆解学习法",
    "闭环复盘法",
    "灰度认知 + 黑白执行",
)

ADAPTER_NAMES = (
    "工程与编程",
    "科学实验",
    "数据与数学",
    "商业与职业",
    "语言与沟通",
    "人文与社会",
    "设计与艺术",
    "工具与操作",
)


def read_all_references() -> str:
    reference_root = SKILL_ROOT / "references"
    chunks: list[str] = []
    for path in sorted(reference_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".json", ".yaml", ".yml"}:
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md 必须以 YAML frontmatter 开始"
    _, raw, body = text.split("---", 2)
    fields: dict[str, str] = {}
    current: str | None = None
    for line in raw.splitlines():
        match = re.match(r"^([a-zA-Z_][\w-]*):\s*(.*)$", line)
        if match:
            current = match.group(1)
            fields[current] = match.group(2).strip().strip("'\"")
        elif current and line.startswith((" ", "\t")):
            fields[current] += " " + line.strip()
    return fields, body.strip()


def test_required_independent_project_layout_exists():
    required = (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "agents" / "openai.yaml",
        SKILL_ROOT / "scripts" / "state_tool.py",
        SKILL_ROOT / "scripts" / "method_tool.py",
        ROOT / ".codex" / "config.toml",
        ROOT / "Learner_State" / "manifest.json",
        ROOT / "Learner_State" / "state.json",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"缺少实施计划中的项目资产: {missing}"
    for directory in ("events", "sessions", "evidence"):
        assert (ROOT / "Learner_State" / directory).is_dir()


def test_skill_frontmatter_is_discriminatory_and_body_routes_progressively():
    fields, body = parse_frontmatter(SKILL_ROOT / "SKILL.md")
    assert fields.get("name") == "real-world-learning-mentor"
    description = fields.get("description", "")
    assert "learn" in description.lower() or "teach" in description.lower()
    assert "resume" in description.lower() or "continue" in description.lower()
    assert "one-off" in description.lower() or "outsourc" in description.lower()

    assert len(body.splitlines()) < 320, "SKILL.md 应保持薄入口，不应内嵌全部教材"
    routes = (
        "references/adapters",
        "references/methodologies",
        "references/research",
        "references/assessment",
        "references/safety",
        "scripts/state_tool.py",
        "scripts/method_tool.py",
    )
    missing_routes = [route for route in routes if route not in body.replace("\\", "/")]
    assert not missing_routes, f"薄入口缺少渐进路由: {missing_routes}"
    assert re.search(r"学习意图|learn(?:ing)? intent", body, re.I)
    assert re.search(r"纯交付|one[- ]off|outsourc", body, re.I)


def test_openai_metadata_allows_implicit_invocation_without_absolute_state_path():
    text = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "display_name:" in text and "真实应用学习导师" in text
    assert "$real-world-learning-mentor" in text
    assert re.search(r"allow_implicit_invocation\s*:\s*true", text, re.I)
    assert "Learner_State" not in text, "UI 元数据不得绑定学习者状态"
    assert not re.search(r"(?i)[A-Z]:[\\/]", text), "UI 元数据不得绑定机器绝对路径"


def test_project_agent_configuration_is_parseable_and_has_exact_role_assignments():
    config = ROOT / ".codex" / "config.toml"
    tomllib.loads(config.read_text(encoding="utf-8"))
    expected = {
        "learning_architect": ("gpt-5.6-sol", "high"),
        "domain_researcher": ("gpt-5.6-terra", "high"),
        "learning_assessor": ("gpt-5.6-luna", "medium"),
        "state_integrity": ("gpt-5.6-sol", "high"),
        "adversarial_reviewer": ("gpt-5.5", "high"),
    }
    config_text = config.read_text(encoding="utf-8")
    for role, (model, reasoning) in expected.items():
        role_file = ROOT / ".codex" / "agents" / f"{role}.toml"
        assert role in config_text and role_file.is_file(), f"缺少子 Agent: {role}"
        parsed = tomllib.loads(role_file.read_text(encoding="utf-8"))
        flat = json.dumps(parsed, ensure_ascii=False).lower()
        assert model in flat
        assert reasoning in flat
        assert re.search(r"只读|read.only|must not (?:write|modify)|不得.*(?:写|修改)", flat, re.I)


def test_all_committed_json_and_toml_are_parseable():
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(
            part in {".git", "__pycache__", ".pytest_cache", "%USERPROFILE%", "node_modules"}
            for part in path.parts
        ):
            continue
        try:
            if path.suffix.lower() == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix.lower() == ".toml":
                tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - failure aggregation
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
    assert not failures, "无法解析的结构化文件:\n" + "\n".join(failures)


def test_method_registry_contains_ten_actionable_not_merely_named_methods():
    path = SKILL_ROOT / "references" / "methodologies" / "method-registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    methods = registry.get("methods")
    assert isinstance(methods, list) and len(methods) == 10
    ids = [method.get("id") for method in methods if isinstance(method, dict)]
    assert len(ids) == len(set(ids)) == 10 and all(isinstance(value, str) and value for value in ids)

    whole = json.dumps(methods, ensure_ascii=False)
    for expected in METHOD_NAMES:
        assert expected in whole, f"方法注册表缺少 {expected}"

    for method in methods:
        assert isinstance(method, dict)
        keys = set(method)
        assert keys & {"best_for", "use_when", "purpose", "solves", "trigger"}, f"{method.get('id')} 缺少适用问题"
        assert keys & {"guardrails", "constraints", "constraint", "failure_guards"}, f"{method.get('id')} 缺少防走偏约束"
        text = json.dumps(method, ensure_ascii=False)
        assert len(text) >= 120, f"{method.get('id')} 只有名称，没有机器可用语义"


def test_unknown_hardware_gate_is_explicit_and_evidence_graded():
    entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    adapter = (SKILL_ROOT / "references" / "adapters" / "engineering-programming.md").read_text(encoding="utf-8")
    combined = entry + "\n" + adapter
    for phrase in ("完全断电", "USB", "禁止", "compile-verified", "logic-verified", "hardware-verified"):
        assert phrase in combined


def test_eight_adapters_define_task_evidence_risk_and_mixed_selection_contracts():
    adapter_root = SKILL_ROOT / "references" / "adapters"
    assert adapter_root.is_dir()
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(adapter_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".md", ".json"}
    )
    for name in ADAPTER_NAMES:
        assert name in text, f"缺少领域适配器: {name}"
    assert re.search(r"真实任务|任务形态|authentic.task|task.shape", text, re.I)
    assert re.search(r"证据|evidence", text, re.I)
    assert re.search(r"风险|安全|risk|safety", text, re.I)
    assert re.search(r"一个主适配器.{0,80}一个辅助适配器|one primary.{0,80}one (?:secondary|supporting)", text, re.I | re.S)
    assert len(text) >= 1600, "适配器资料疑似只有名称列表，没有可执行接口"


def test_teaching_contract_encodes_behavioral_gates_not_only_section_titles():
    text = read_all_references()
    compact = re.sub(r"\s+", " ", text)

    rules = {
        "单轮一个任务": r"单轮.{0,120}(?:一个|1 个).{0,30}(?:当前|主)?任务",
        "单轮一到两个概念": r"单轮.{0,160}(?:1.?[–—-].?2|1.?到.?2|一到两个).{0,30}(?:概念|知识)",
        "最多一个核心问题": r"每轮.{0,80}(?:最多|不超过).{0,20}(?:一个|1 个).{0,20}(?:核心)?问题",
        "十五分钟首行动": r"15 分钟.{0,100}(?:开始|行动|完成)",
        "Applied 证据门": r"(?:Applied.{0,220}(?:证据不足|没有证据|不能标记|不得标记)|(?:证据不足|没有证据).{0,180}(?:不升级|Applied))",
        "Transferred 变化与减援": r"Transferred.{0,260}(?:场景|材料|受众|限制|工具).{0,220}(?:提示|帮助).{0,40}(?:减少|降低)",
        "准备不足只补薄弱点": r"准备(?:度)?.{0,180}(?:不足|未通过).{0,160}(?:只|仅).{0,50}(?:微课|薄弱|错误)",
        "安全门阻断": r"(?:安全门.{0,180}(?:不得|阻断|停止|禁止|不进入).{0,100}(?:实操|执行|下一步)|高风险.{0,160}安全门.{0,80}(?:不进入|不得|阻断).{0,50}实操)",
        "恢复摘要六行": r"恢复摘要.{0,100}(?:6|六)\s*行",
        "复盘应更轻": r"复盘.{0,180}(?:轻于|短于|不得超过|成本低于).{0,80}(?:主要|主任务|学习任务)",
    }
    missing = [label for label, pattern in rules.items() if not re.search(pattern, compact, re.I)]
    assert not missing, f"教学契约缺少可执行语义: {missing}"


def test_event_and_state_schemas_express_integrity_and_multitrack_semantics():
    schema_root = SKILL_ROOT / "references" / "schemas"
    schemas = [json.loads(path.read_text(encoding="utf-8")) for path in schema_root.glob("*.json")]
    assert schemas, "缺少 JSON Schema"
    combined = json.dumps(schemas, ensure_ascii=False)
    envelope_fields = {
        "schema_version",
        "event_id",
        "event_type",
        "timestamp",
        "revision",
        "idempotency_key",
        "actor",
        "track_id",
        "previous_hash",
        "payload",
        "event_hash",
    }
    assert all(field in combined for field in envelope_fields)
    for semantic in ("tracks", "methodology_preferences", "mastery", "evidence", "next_action"):
        assert semantic in combined, f"状态 Schema 缺少 {semantic}"


def test_skill_package_contains_no_user_state_or_machine_absolute_paths():
    forbidden_path = re.compile(r"(?i)(?:(?<![A-Za-z])[A-Z]:[\\/]|/Users/[^/]+|/home/[^/]+)")
    offenders: list[str] = []
    for path in SKILL_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".py", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8")
        if forbidden_path.search(text):
            offenders.append(str(path.relative_to(ROOT)))
        assert "password" not in path.name.lower() and "secret" not in path.name.lower()
    assert not offenders, f"Skill 包绑定了机器绝对路径: {offenders}"
