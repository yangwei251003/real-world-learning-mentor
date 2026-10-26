from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from conftest import (
    ROOT,
    STATE_TOOL,
    file_snapshot,
    find_revision,
    run_state,
)


ENVELOPE_FIELDS = {
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


def begin_track(
    state_dir: Path,
    revision: int,
    track_id: str = "摄影-生活记录",
    key: str = "begin-photo-1",
    goal: str = "学会拍清楚家里的晚餐",
    outcome: str = "同一桌面场景的两张可比较照片",
) -> dict:
    _, result = run_state(
        state_dir,
        "begin",
        "--track-id",
        track_id,
        "--goal",
        goal,
        "--authentic-outcome",
        outcome,
        "--primary-adapter",
        "design-art",
        "--secondary-adapter",
        "tools-operations",
        "--mvc",
        "能在一个变化条件下拍摄、比较并说明选择",
        "--next-action",
        "拍同一场景两张照片并保留原图参数",
        "--expected-revision",
        str(revision),
        "--idempotency-key",
        key,
    )
    return result


def record(
    state_dir: Path,
    revision: int,
    event_type: str,
    payload: dict,
    *,
    track_id: str | None = "摄影-生活记录",
    key: str,
    ok: bool = True,
) -> dict:
    args = [
        "record",
        "--event-type",
        event_type,
        "--payload",
        json.dumps(payload, ensure_ascii=False),
        "--expected-revision",
        str(revision),
        "--idempotency-key",
        key,
    ]
    if track_id is not None:
        args += ["--track-id", track_id]
    _, result = run_state(state_dir, *args, ok=ok)
    return result


def event_files(state_dir: Path) -> list[Path]:
    return sorted((state_dir / "events").glob("*.json"))


def test_state_cli_exposes_planned_commands_and_json_errors():
    completed = subprocess.run(
        [sys.executable, str(STATE_TOOL), "--help"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    for command in ("init", "status", "validate", "begin", "record", "finish", "rebuild"):
        assert command in completed.stdout

    failed = subprocess.run(
        [sys.executable, str(STATE_TOOL), "--state-dir", "unused", "record"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert failed.returncode != 0
    error = json.loads(failed.stderr)
    assert error.get("ok") is False and error.get("error")


def test_init_status_validate_and_utf8_multitrack_isolation(tmp_path):
    state_dir = tmp_path / "中文 学习档案"
    _, initialized = run_state(state_dir, "init")
    assert find_revision(initialized) == 0
    assert {"manifest.json", "state.json"} <= {path.name for path in state_dir.iterdir() if path.is_file()}
    assert all((state_dir / name).is_dir() for name in ("events", "sessions", "evidence"))

    first = begin_track(state_dir, 0)
    assert find_revision(first) == 1
    second = begin_track(
        state_dir,
        1,
        track_id="Python-账单整理",
        key="begin-python-1",
        goal="用 Python 整理家庭账单",
        outcome="生成按类别汇总的中文账单结果",
    )
    assert find_revision(second) == 2

    preference = record(
        state_dir,
        2,
        "learning.method_preference_updated",
        {
            "mode": "locked",
            "ordered_methods": ["reverse_decomposition", "feynman"],
            "preferred_presets": [],
            "avoid_methods": ["socratic_questioning"],
        },
        track_id=None,
        key="shared-preference-1",
    )
    assert find_revision(preference) == 3

    _, photo = run_state(state_dir, "status", "--track-id", "摄影-生活记录")
    _, python = run_state(state_dir, "status", "--track-id", "Python-账单整理")
    assert photo["track"]["goal"] == "学会拍清楚家里的晚餐"
    assert python["track"]["goal"] == "用 Python 整理家庭账单"
    assert photo["methodology_preferences"]["mode"] == "locked"
    assert python["methodology_preferences"]["mode"] == "locked"
    assert "Python-账单整理" not in json.dumps(photo["track"], ensure_ascii=False)

    _, valid = run_state(state_dir, "validate")
    assert valid["valid"] is True and valid["track_count"] == 2


def test_status_is_strictly_read_only(initialized_state):
    state_dir, _ = initialized_state
    before = file_snapshot(state_dir)
    _, status = run_state(state_dir, "status")
    after = file_snapshot(state_dir)
    assert status["state"]["revision"] == 0
    assert after == before, "status 不得创建锁、修复快照或更新时间戳"


def test_event_envelope_hash_chain_and_revision_are_auditable(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    record(
        state_dir,
        1,
        "learning.evidence_recorded",
        {"evidence_id": "照片-1", "summary": "同一桌面完成两张原图", "verification_level": "user-reported"},
        key="evidence-photo-1",
    )
    events = [json.loads(path.read_text(encoding="utf-8")) for path in event_files(state_dir)]
    assert len(events) == 2
    previous = "0" * 64
    for expected_revision, event in enumerate(events, start=1):
        assert set(event) == ENVELOPE_FIELDS
        assert event["revision"] == expected_revision
        assert event["previous_hash"] == previous
        unhashed = {key: value for key, value in event.items() if key != "event_hash"}
        digest = hashlib.sha256(
            json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert event["event_hash"] == digest
        previous = digest


def test_idempotent_retry_precedes_revision_check_and_conflicts_fail_closed(initialized_state):
    state_dir, _ = initialized_state
    first = begin_track(state_dir, 0, key="same-request")
    duplicate = begin_track(state_dir, 0, key="same-request")
    assert duplicate["idempotent"] is True
    assert find_revision(duplicate) == find_revision(first) == 1
    assert len(event_files(state_dir)) == 1

    _, different = run_state(
        state_dir,
        "begin",
        "--track-id", "摄影-生活记录",
        "--goal", "不同目标",
        "--authentic-outcome", "不同结果",
        "--primary-adapter", "design-art",
        "--mvc", "不同能力",
        "--expected-revision", "0",
        "--idempotency-key", "same-request",
        ok=False,
    )
    assert "idempotency" in different["error"].lower()

    _, stale = run_state(
        state_dir,
        "begin",
        "--track-id", "another-track",
        "--goal", "另一目标",
        "--authentic-outcome", "另一结果",
        "--primary-adapter", "engineering-programming",
        "--mvc", "另一能力",
        "--expected-revision", "0",
        "--idempotency-key", "fresh-key",
        ok=False,
    )
    assert "revision conflict" in stale["error"].lower()
    assert len(event_files(state_dir)) == 1


def test_concurrent_writers_are_serialized_and_all_events_survive(tmp_path):
    state_dir = tmp_path / "并发状态"
    run_state(state_dir, "init")

    def worker(index: int) -> int:
        key = f"parallel-pref-{index}"
        for _ in range(30):
            status_process = subprocess.run(
                [sys.executable, str(STATE_TOOL), "--state-dir", str(state_dir), "status"],
                cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
            )
            assert status_process.returncode == 0, status_process.stderr
            revision = json.loads(status_process.stdout)["state"]["revision"]
            payload = json.dumps(
                {"mode": "auto", "ordered_methods": [], "preferred_presets": [f"p{index}"], "avoid_methods": []},
                ensure_ascii=False,
            )
            written = subprocess.run(
                [
                    sys.executable, str(STATE_TOOL), "--state-dir", str(state_dir), "record",
                    "--event-type", "learning.method_preference_updated", "--payload", payload,
                    "--expected-revision", str(revision), "--idempotency-key", key,
                ],
                cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
            )
            if written.returncode == 0:
                return json.loads(written.stdout)["revision"]
            error = json.loads(written.stderr)
            assert "revision conflict" in error["error"].lower(), error
        raise AssertionError(f"worker {index} exhausted revision retries")

    with ThreadPoolExecutor(max_workers=8) as pool:
        revisions = list(pool.map(worker, range(8)))
    assert len(set(revisions)) == 8
    _, valid = run_state(state_dir, "validate")
    assert valid["revision"] == valid["event_count"] == 8
    assert len(event_files(state_dir)) == 8


def test_event_tampering_breaks_validation_without_rewriting_anything(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    event_path = event_files(state_dir)[0]
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["payload"]["goal"] = "篡改后的目标"
    event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    before = file_snapshot(state_dir)
    _, error = run_state(state_dir, "validate", ok=False)
    assert "event_hash mismatch" in error["error"]
    assert file_snapshot(state_dir) == before


def test_status_fails_closed_on_same_revision_snapshot_divergence_then_explicit_rebuild_recovers(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    state_path = state_dir / "state.json"
    snapshot = json.loads(state_path.read_text(encoding="utf-8"))
    snapshot["tracks"]["摄影-生活记录"]["goal"] = "被篡改但 revision 未变"
    tampered = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    state_path.write_text(tampered, encoding="utf-8")

    _, error = run_state(state_dir, "status", ok=False)
    assert "diverge" in error["error"].lower()
    assert state_path.read_text(encoding="utf-8") == tampered

    _, rebuilt = run_state(state_dir, "rebuild", "--replace-derived")
    assert rebuilt["replaced"] is True and rebuilt["revision"] == 1
    _, status = run_state(state_dir, "status", "--track-id", "摄影-生活记录")
    assert status["track"]["goal"] == "学会拍清楚家里的晚餐"


def test_rebuild_can_recover_a_missing_or_truncated_derived_snapshot(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    state_path = state_dir / "state.json"
    state_path.write_text("{crash", encoding="utf-8")
    _, rebuilt = run_state(state_dir, "rebuild", "--replace-derived")
    assert rebuilt["revision"] == 1 and rebuilt["event_count"] == 1
    _, valid = run_state(state_dir, "validate")
    assert valid["valid"] is True


@pytest.mark.parametrize(
    "field",
    [
        "password",
        "api_key",
        "raw_chat",
        "access_token",
        "apiKey",
        "clientSecret",
        "bearerToken",
        "sessionCookie",
    ],
)
def test_sensitive_fields_are_rejected_without_ledger_pollution(initialized_state, field):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    error = record(
        state_dir,
        1,
        "learning.evidence_recorded",
        {"evidence_id": "bad", "summary": "不应写入", field: "TOP-SECRET"},
        key=f"bad-{field}",
        ok=False,
    )
    assert "sensitive" in error["error"].lower()
    assert len(event_files(state_dir)) == 1


def test_evidence_keeps_utf8_summary_relative_reference_and_hash_but_rejects_absolute_path(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    summary = "晚餐照片对比：靠窗版本主体更清楚。" + "观察" * 500
    result = record(
        state_dir,
        1,
        "learning.evidence_recorded",
        {
            "evidence_id": "晚餐照片-01",
            "kind": "image-comparison",
            "summary": summary,
            "verification_level": "user-reported",
            "artifact_ref": "evidence/晚餐照片-01.sha256",
            "artifact_hash": "a" * 64,
        },
        key="utf8-evidence",
    )
    assert find_revision(result) == 2
    _, status = run_state(state_dir, "status", "--track-id", "摄影-生活记录")
    saved = status["track"]["evidence"][0]
    assert saved["summary"] == summary and saved["artifact_ref"].startswith("evidence/")

    error = record(
        state_dir,
        2,
        "learning.evidence_recorded",
        {
            "evidence_id": "absolute-ref",
            "summary": "不应保存机器位置",
            "artifact_ref": r"C:\Users\Kevin\Desktop\private.jpg",
        },
        key="absolute-evidence",
        ok=False,
    )
    assert "absolute" in error["error"].lower() or "relative" in error["error"].lower()
    assert len(event_files(state_dir)) == 2


def test_only_learning_namespace_events_are_accepted(initialized_state):
    state_dir, _ = initialized_state
    begin_track(state_dir, 0)
    error = record(
        state_dir,
        1,
        "system.secret_written",
        {"summary": "invalid namespace"},
        key="wrong-namespace",
        ok=False,
    )
    assert "event_type" in error["error"] or "learning" in error["error"]
    assert len(event_files(state_dir)) == 1
