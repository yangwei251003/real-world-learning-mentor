#!/usr/bin/env python3
"""Deterministic, local event ledger for learner progress.

The event files are authoritative. ``state.json`` and ``manifest.json`` are
derived caches and can be rebuilt after a crash. All successful output is JSON
on stdout; failures are JSON on stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64
EVENT_RE = re.compile(r"^(\d{12})_([0-9a-fA-F-]+)\.json$")
LEVELS = ["Seen", "Understood", "Applied", "Modified", "Diagnosed", "Transferred"]
SENSITIVE_KEYS = {
    "raw_chat",
    "chat_transcript",
    "password",
    "passwd",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
}
SENSITIVE_COMPACT_PARTS = {
    "apikey",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "bearertoken",
    "sessiontoken",
    "sessioncookie",
    "privatekey",
    "password",
    "passwd",
    "credential",
}


class StateError(RuntimeError):
    """Expected command failure that should be emitted as JSON."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise StateError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise StateError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise StateError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise StateError(f"missing file: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read valid JSON from {path}: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    """Acquire a small cross-platform exclusive lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    handle.seek(0)
                    if handle.read(1) == b"":
                        handle.seek(0)
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise StateError("timed out waiting for state lock")
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StateError("timed out waiting for state lock")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "last_event_hash": ZERO_HASH,
        "updated_at": None,
        "methodology_preferences": {
            "mode": "auto",
            "ordered_methods": [],
            "preferred_presets": [],
            "avoid_methods": [],
            "updated_at": None,
        },
        "tracks": {},
    }


def initial_manifest(created_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at,
        "updated_at": created_at,
        "current_revision": 0,
        "last_event_hash": ZERO_HASH,
    }


def event_paths(state_dir: Path) -> list[Path]:
    directory = state_dir / "events"
    if not directory.exists():
        return []
    paths = [path for path in directory.iterdir() if path.is_file() and EVENT_RE.match(path.name)]
    return sorted(paths, key=lambda path: path.name)


def reject_sensitive(value: Any, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            compact = re.sub(r"[^a-z0-9]", "", key_text)
            if (
                key_text in SENSITIVE_KEYS
                or compact in SENSITIVE_COMPACT_PARTS
                or "secret" in compact
                or "password" in compact
                or compact.endswith("credential")
                or compact.endswith("cookie")
            ):
                raise StateError(f"sensitive field is not allowed: {'.'.join(trail + (str(key),))}")
            reject_sensitive(child, trail + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive(child, trail + (str(index),))


def reject_unsafe_artifact_paths(value: Any) -> None:
    """Evidence may reference only project-relative artifacts, never arbitrary files."""

    if not isinstance(value, dict):
        return
    for field in ("artifact_ref", "relative_ref"):
        raw = value.get(field)
        if raw in (None, ""):
            continue
        if not isinstance(raw, str):
            raise StateError(f"{field} must be a relative string path")
        normalized = raw.replace("\\", "/")
        if (
            Path(raw).is_absolute()
            or re.match(r"^[A-Za-z]:/", normalized)
            or normalized.startswith("//")
            or ".." in normalized.split("/")
        ):
            raise StateError(f"{field} must stay within the project as a relative path")


def require_track(state: dict[str, Any], track_id: str | None) -> dict[str, Any]:
    if not track_id:
        raise StateError("track_id is required for this event")
    track = state["tracks"].get(track_id)
    if track is None:
        raise StateError(f"unknown track_id: {track_id}")
    return track


def append_unique(items: list[Any], value: Any, key: str | None = None) -> None:
    if key and isinstance(value, dict) and value.get(key) is not None:
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get(key) == value.get(key):
                items[index] = copy.deepcopy(value)
                return
    if value not in items:
        items.append(copy.deepcopy(value))


def validate_source_payload(payload: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    required = {
        "source_id",
        "title",
        "url",
        "publisher",
        "accessed_at",
        "version_or_date",
        "license",
        "supported_claim",
        "freshness_class",
        "expires_at",
        "conflict_status",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise StateError(f"source record missing required fields: {missing}")
    for field in ("source_id", "title", "publisher", "supported_claim"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise StateError(f"source field {field} must be a non-empty string")
    url = payload.get("url")
    if not isinstance(url, str) or not re.match(r"^https?://[^\s]+$", url):
        raise StateError("source url must be an absolute http(s) URL")
    parse_timestamp(payload["accessed_at"], "accessed_at")
    if payload["freshness_class"] not in {
        "per-session",
        "volatile-7-30d",
        "version-bound-180d",
        "stable-2y",
    }:
        raise StateError("source freshness_class is invalid")
    if payload["conflict_status"] not in {"none", "open", "resolved", "unverified"}:
        raise StateError("source conflict_status is invalid")
    result = copy.deepcopy(payload)
    expires_at = payload.get("expires_at")
    if expires_at is not None:
        expiry = parse_timestamp(expires_at, "expires_at")
        expired = expiry <= as_of
        result["is_expired_at_recording"] = expired
        if expired and payload.get("use_scope") in {"current", "volatile", "high-risk"}:
            raise StateError("expired source cannot support a current, volatile, or high-risk claim")
    else:
        result["is_expired_at_recording"] = False
    return result


def reduce_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(state)
    event_type = event["event_type"]
    payload = event["payload"]
    track_id = event.get("track_id")

    if event_type == "learning.track_begun":
        if not track_id:
            raise StateError("learning.track_begun requires track_id")
        if track_id in state["tracks"]:
            raise StateError(f"track already exists: {track_id}")
        state["tracks"][track_id] = {
            "track_id": track_id,
            "status": "active",
            "goal": payload["goal"],
            "authentic_outcome": payload["authentic_outcome"],
            "primary_adapter": payload["primary_adapter"],
            "secondary_adapter": payload.get("secondary_adapter"),
            "mvc": payload["mvc"],
            "route_stage": "Taste",
            "current_unit": None,
            "next_action": payload.get("next_action"),
            "readiness": {
                "status": "not_assessed",
                "score": None,
                "total": None,
                "required_score": None,
                "missed_concepts": [],
            },
            "safety_gates": [],
            "mastery": {},
            "evidence": [],
            "weak_points": [],
            "assignments": [],
            "due_reviews": [],
            "sources": [],
            "misconceptions": [],
            "methodology": {
                "recommendation_id": None,
                "selector_version": None,
                "primary_method": None,
                "supporting_methods": [],
                "confidence": None,
                "rationale": [],
                "evidence_basis": [],
                "frozen_for_session": False,
                "reconsider_triggers": [],
                "audit_summaries": [],
            },
            "event_summaries": [],
            "started_at": event["timestamp"],
            "updated_at": event["timestamp"],
            "completed_at": None,
        }
    elif event_type == "learning.method_preference_updated":
        preferences = copy.deepcopy(payload)
        preferences["updated_at"] = event["timestamp"]
        state["methodology_preferences"].update(preferences)
    elif event_type == "learning.method_mix_set":
        track = require_track(state, track_id)
        primary = payload.get("primary_method")
        supporting = payload.get("supporting_methods", [])
        if not primary or not isinstance(supporting, list):
            raise StateError("method mix requires primary_method and a supporting_methods list")
        if len(supporting) > 2:
            raise StateError("method mix allows at most two supporting methods")
        if primary in supporting or len(set(supporting)) != len(supporting):
            raise StateError("method mix methods must be unique")
        track["methodology"].update(copy.deepcopy(payload))
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.method_audit_recorded":
        track = require_track(state, track_id)
        try:
            from method_tool import MethodError, validate_audit

            validate_audit(payload)
        except (MethodError, ImportError) as exc:
            raise StateError(f"invalid method audit: {exc}") from exc
        append_unique(track["methodology"]["audit_summaries"], payload, "audit_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.evidence_recorded":
        track = require_track(state, track_id)
        if not payload.get("evidence_id"):
            raise StateError("evidence event requires evidence_id")
        if not payload.get("summary"):
            raise StateError("evidence event requires a minimal summary")
        allowed_verification = {
            "documented",
            "compile-verified",
            "logic-verified",
            "simulation-verified",
            "artifact-observed",
            "hardware-verified",
            "user-reported",
            "externally-verified",
        }
        verification = payload.get("verification_level", "user-reported")
        if verification not in allowed_verification:
            raise StateError(f"unsupported verification_level: {verification}")
        payload = copy.deepcopy(payload)
        payload["verification_level"] = verification
        reject_unsafe_artifact_paths(payload)
        append_unique(track["evidence"], payload, "evidence_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.mastery_updated":
        track = require_track(state, track_id)
        concept_id = payload.get("concept_id")
        level = payload.get("level")
        if not concept_id or level not in LEVELS:
            raise StateError(f"mastery event requires concept_id and level in {LEVELS}")
        existing = track["mastery"].get(concept_id)
        if existing and LEVELS.index(level) < LEVELS.index(existing["level"]):
            if not payload.get("allow_regression"):
                raise StateError("mastery regression requires allow_regression=true")
        if LEVELS.index(level) >= LEVELS.index("Applied"):
            evidence_ids = payload.get("evidence_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                raise StateError(f"{level} mastery requires at least one evidence_id")
            known_ids = {item.get("evidence_id") for item in track["evidence"]}
            unknown = sorted(set(evidence_ids) - known_ids)
            if unknown:
                raise StateError(f"mastery references unknown evidence_ids: {unknown}")
        if level == "Transferred":
            if payload.get("changed_dimension") not in {
                "context",
                "material",
                "audience",
                "constraint",
                "tool",
            }:
                raise StateError("Transferred mastery requires a changed_dimension")
            if payload.get("assistance_reduced") is not True:
                raise StateError("Transferred mastery requires assistance_reduced=true")
            evidence_by_id = {item.get("evidence_id"): item for item in track["evidence"]}
            referenced = [evidence_by_id[item] for item in payload["evidence_ids"]]
            independently_checkable = {
                "artifact-observed",
                "compile-verified",
                "logic-verified",
                "simulation-verified",
                "hardware-verified",
                "externally-verified",
            }
            if not any(item.get("verification_level") in independently_checkable for item in referenced):
                raise StateError(
                    "Transferred mastery requires at least one independently checkable transfer artifact"
                )
            if not any(
                item.get("transfer_context")
                or item.get("changed_dimension")
                or item.get("kind") == "transfer-performance"
                for item in referenced
            ):
                raise StateError(
                    "Transferred mastery requires evidence that records the changed transfer context"
                )
        track["mastery"][concept_id] = copy.deepcopy(payload)
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.readiness_assessed":
        track = require_track(state, track_id)
        score = payload.get("score")
        total = payload.get("total")
        required_score = payload.get("required_score")
        if not all(isinstance(item, int) for item in (score, total, required_score)):
            raise StateError("readiness requires integer score, total and required_score")
        if total < 1 or not (0 <= score <= total) or not (0 <= required_score <= total):
            raise StateError("invalid readiness score bounds")
        computed_passed = score >= required_score
        if "passed" in payload and bool(payload["passed"]) != computed_passed:
            raise StateError("readiness passed flag conflicts with score")
        track["readiness"] = {
            "status": "passed" if computed_passed else "remediation_required",
            "score": score,
            "total": total,
            "required_score": required_score,
            "missed_concepts": copy.deepcopy(payload.get("missed_concepts", [])),
            "assessed_at": event["timestamp"],
        }
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.safety_gate_recorded":
        track = require_track(state, track_id)
        status = payload.get("status")
        if status not in {"passed", "blocked"}:
            raise StateError("safety gate status must be passed or blocked")
        if not payload.get("gate_id") or payload.get("risk_level") not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise StateError("safety gate requires gate_id and risk_level")
        if status == "passed" and (not payload.get("risk_category") or not payload.get("action_id")):
            raise StateError("a passed safety gate requires risk_category and action_id")
        if payload.get("expires_at") is not None:
            parse_timestamp(payload["expires_at"], "expires_at")
        append_unique(track["safety_gates"], payload, "gate_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.assignment_set":
        track = require_track(state, track_id)
        append_unique(track["assignments"], payload, "assignment_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.weak_point_recorded":
        track = require_track(state, track_id)
        append_unique(track["weak_points"], payload, "weak_point_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.source_recorded":
        track = require_track(state, track_id)
        payload = validate_source_payload(payload, parse_timestamp(event["timestamp"], "timestamp"))
        append_unique(track["sources"], payload, "source_id")
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.session_progressed":
        track = require_track(state, track_id)
        if payload.get("requires_readiness") and track["readiness"]["status"] != "passed":
            raise StateError("readiness gate is not passed; provide targeted remediation first")
        if payload.get("risk_level") in {"medium", "high", "critical"}:
            safety_gate_id = payload.get("safety_gate_id")
            risk_category = payload.get("risk_category")
            action_id = payload.get("action_id")
            if not safety_gate_id or not risk_category or not action_id:
                raise StateError(
                    "risky practice requires a safety gate id, risk_category, and action_id"
                )
            gate = next(
                (item for item in track["safety_gates"] if item.get("gate_id") == safety_gate_id),
                None,
            )
            if (
                gate is None
                or gate.get("status") != "passed"
                or gate.get("risk_level") != payload.get("risk_level")
                or gate.get("risk_category") != risk_category
                or gate.get("action_id") != action_id
            ):
                raise StateError("no matching passed safety gate exists for this risky action")
            if gate.get("expires_at") is not None:
                if parse_timestamp(gate["expires_at"], "expires_at") <= parse_timestamp(
                    event["timestamp"], "timestamp"
                ):
                    raise StateError("the matching safety gate has expired")
        allowed = {"route_stage", "current_unit", "next_action", "due_reviews", "misconceptions"}
        for key in allowed:
            if key in payload:
                track[key] = copy.deepcopy(payload[key])
        track["updated_at"] = event["timestamp"]
    elif event_type == "learning.track_finished":
        track = require_track(state, track_id)
        track["status"] = "completed"
        track["completion_outcome"] = payload["outcome"]
        track["completion_summary"] = payload["summary"]
        track["completed_at"] = event["timestamp"]
        track["updated_at"] = event["timestamp"]
    else:
        track = require_track(state, track_id)
        append_unique(
            track["event_summaries"],
            {
                "event_id": event["event_id"],
                "event_type": event_type,
                "timestamp": event["timestamp"],
                "summary": payload.get("summary") if isinstance(payload, dict) else None,
            },
            "event_id",
        )
        track["event_summaries"] = track["event_summaries"][-20:]
        track["updated_at"] = event["timestamp"]

    state["revision"] = event["revision"]
    state["last_event_hash"] = event["event_hash"]
    state["updated_at"] = event["timestamp"]
    return state


def validate_event_shape(event: dict[str, Any], expected_revision: int, previous_hash: str) -> None:
    required = {
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
    missing = sorted(required - event.keys())
    if missing:
        raise StateError(f"event revision {expected_revision} missing fields: {missing}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise StateError(f"unsupported event schema at revision {expected_revision}")
    if event["revision"] != expected_revision:
        raise StateError(
            f"revision gap: expected {expected_revision}, found {event['revision']}"
        )
    if event["previous_hash"] != previous_hash:
        raise StateError(f"previous_hash mismatch at revision {expected_revision}")
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    if event["event_hash"] != sha256_json(unhashed):
        raise StateError(f"event_hash mismatch at revision {expected_revision}")


def replay(state_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = initial_state()
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    previous_hash = ZERO_HASH
    paths = event_paths(state_dir)
    for expected_revision, path in enumerate(paths, start=1):
        match = EVENT_RE.match(path.name)
        assert match is not None
        if int(match.group(1)) != expected_revision:
            raise StateError(
                f"event filename gap: expected revision {expected_revision}, found {path.name}"
            )
        event = read_json(path)
        if not isinstance(event, dict):
            raise StateError(f"event must be an object: {path}")
        validate_event_shape(event, expected_revision, previous_hash)
        if event["event_id"] in seen_ids:
            raise StateError(f"duplicate event_id: {event['event_id']}")
        if event["idempotency_key"] in seen_keys:
            raise StateError(f"duplicate idempotency_key: {event['idempotency_key']}")
        seen_ids.add(event["event_id"])
        seen_keys.add(event["idempotency_key"])
        state = reduce_event(state, event)
        events.append(event)
        previous_hash = event["event_hash"]
    return state, events


def ensure_initialized(state_dir: Path) -> None:
    required = [state_dir / "events", state_dir / "sessions", state_dir / "evidence"]
    if not (state_dir / "manifest.json").exists() or not (state_dir / "state.json").exists():
        raise StateError(f"state is not initialized: {state_dir}")
    for path in required:
        if not path.is_dir():
            raise StateError(f"missing state directory: {path}")


def validate_derived(state_dir: Path) -> dict[str, Any]:
    ensure_initialized(state_dir)
    replayed, events = replay(state_dir)
    stored_state = read_json(state_dir / "state.json")
    manifest = read_json(state_dir / "manifest.json")
    if stored_state != replayed:
        raise StateError("state.json diverges from authoritative event replay")
    expected_manifest_fields = {
        "current_revision": replayed["revision"],
        "last_event_hash": replayed["last_event_hash"],
        "schema_version": SCHEMA_VERSION,
    }
    for key, expected in expected_manifest_fields.items():
        if manifest.get(key) != expected:
            raise StateError(f"manifest {key} mismatch: expected {expected!r}")
    return {
        "valid": True,
        "revision": replayed["revision"],
        "last_event_hash": replayed["last_event_hash"],
        "event_count": len(events),
        "track_count": len(replayed["tracks"]),
    }


def find_idempotent(events: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for event in events:
        if event["idempotency_key"] == key:
            return event
    return None


def record_event(
    state_dir: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    track_id: str | None,
    actor: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"learning\.[a-z0-9_]+", event_type):
        raise StateError("event_type must match learning.<lowercase_name>")
    if not idempotency_key.strip():
        raise StateError("idempotency_key must not be empty")
    if len(canonical_bytes(payload)) > 262_144:
        raise StateError("payload exceeds 256 KiB; save a summary or reference instead")
    reject_sensitive(payload)
    with file_lock(state_dir / ".state.lock"):
        ensure_initialized(state_dir)
        validate_derived(state_dir)
        state, events = replay(state_dir)
        duplicate = find_idempotent(events, idempotency_key)
        if duplicate is not None:
            same = (
                duplicate["event_type"] == event_type
                and duplicate["track_id"] == track_id
                and duplicate["payload"] == payload
            )
            if not same:
                raise StateError("idempotency_key was already used for different content")
            return {
                "ok": True,
                "idempotent": True,
                "event": duplicate,
                "revision": state["revision"],
            }
        if state["revision"] != expected_revision:
            raise StateError(
                f"revision conflict: expected {expected_revision}, current {state['revision']}"
            )
        timestamp = utc_now()
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": timestamp,
            "revision": state["revision"] + 1,
            "idempotency_key": idempotency_key,
            "actor": actor,
            "track_id": track_id,
            "previous_hash": state["last_event_hash"],
            "payload": payload,
        }
        event["event_hash"] = sha256_json(event)
        next_state = reduce_event(state, event)
        event_name = f"{event['revision']:012d}_{event['event_id']}.json"
        atomic_write_json(state_dir / "events" / event_name, event)
        atomic_write_json(state_dir / "state.json", next_state)
        manifest = read_json(state_dir / "manifest.json")
        manifest.update(
            {
                "schema_version": SCHEMA_VERSION,
                "updated_at": timestamp,
                "current_revision": next_state["revision"],
                "last_event_hash": next_state["last_event_hash"],
            }
        )
        atomic_write_json(state_dir / "manifest.json", manifest)
        return {
            "ok": True,
            "idempotent": False,
            "event": event,
            "revision": next_state["revision"],
        }


def parse_json_argument(raw: str) -> dict[str, Any]:
    path = Path(raw)
    try:
        if raw != "-" and path.is_file():
            value = read_json(path)
        else:
            value = json.loads(sys.stdin.read() if raw == "-" else raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError("payload must be a JSON object")
    return value


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = args.state_dir
    with file_lock(state_dir / ".state.lock"):
        manifest_path = state_dir / "manifest.json"
        state_path = state_dir / "state.json"
        if manifest_path.exists() or state_path.exists():
            result = validate_derived(state_dir)
            return {"ok": True, "created": False, **result}
        for name in ("events", "sessions", "evidence"):
            (state_dir / name).mkdir(parents=True, exist_ok=True)
        created_at = utc_now()
        atomic_write_json(state_path, initial_state())
        atomic_write_json(manifest_path, initial_manifest(created_at))
        return {"ok": True, "created": True, "revision": 0, "state_dir": str(state_dir)}


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    # Initialization creates the lock; acquiring it changes no state bytes and
    # prevents observing the short event/state/manifest commit window.
    ensure_initialized(args.state_dir)
    with file_lock(args.state_dir / ".state.lock"):
        validate_derived(args.state_dir)
        state = read_json(args.state_dir / "state.json")
    if args.track_id:
        track = state.get("tracks", {}).get(args.track_id)
        if track is None:
            raise StateError(f"unknown track_id: {args.track_id}")
        return {
            "ok": True,
            "revision": state.get("revision"),
            "track": track,
            "methodology_preferences": state.get("methodology_preferences"),
        }
    return {"ok": True, "state": state}


def command_validate(args: argparse.Namespace) -> dict[str, Any]:
    ensure_initialized(args.state_dir)
    with file_lock(args.state_dir / ".state.lock"):
        return {"ok": True, **validate_derived(args.state_dir)}


def common_write_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "state_dir": args.state_dir,
        "actor": args.actor,
        "expected_revision": args.expected_revision,
        "idempotency_key": args.idempotency_key,
    }


def command_begin(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "goal": args.goal,
        "authentic_outcome": args.authentic_outcome,
        "primary_adapter": args.primary_adapter,
        "mvc": args.mvc,
    }
    if args.secondary_adapter:
        payload["secondary_adapter"] = args.secondary_adapter
    if args.next_action:
        payload["next_action"] = args.next_action
    return record_event(
        event_type="learning.track_begun",
        payload=payload,
        track_id=args.track_id,
        **common_write_kwargs(args),
    )


def command_record(args: argparse.Namespace) -> dict[str, Any]:
    return record_event(
        event_type=args.event_type,
        payload=parse_json_argument(args.payload),
        track_id=args.track_id,
        **common_write_kwargs(args),
    )


def command_finish(args: argparse.Namespace) -> dict[str, Any]:
    return record_event(
        event_type="learning.track_finished",
        payload={"outcome": args.outcome, "summary": args.summary},
        track_id=args.track_id,
        **common_write_kwargs(args),
    )


def command_rebuild(args: argparse.Namespace) -> dict[str, Any]:
    with file_lock(args.state_dir / ".state.lock"):
        if not (args.state_dir / "events").is_dir():
            raise StateError(f"missing authoritative events directory: {args.state_dir / 'events'}")
        replayed, events = replay(args.state_dir)
        if args.replace_derived:
            timestamp = utc_now()
            try:
                manifest = read_json(args.state_dir / "manifest.json")
                if not isinstance(manifest, dict):
                    raise StateError("manifest must be an object")
            except StateError:
                manifest = initial_manifest(timestamp)
            manifest.update(
                {
                    "schema_version": SCHEMA_VERSION,
                    "updated_at": timestamp,
                    "current_revision": replayed["revision"],
                    "last_event_hash": replayed["last_event_hash"],
                }
            )
            atomic_write_json(args.state_dir / "state.json", replayed)
            atomic_write_json(args.state_dir / "manifest.json", manifest)
        return {
            "ok": True,
            "replaced": bool(args.replace_derived),
            "revision": replayed["revision"],
            "event_count": len(events),
            "track_count": len(replayed["tracks"]),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(handler=command_init)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--track-id")
    status_parser.set_defaults(handler=command_status)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.set_defaults(handler=command_validate)

    def add_write_options(subparser: argparse.ArgumentParser, *, track_required: bool = True) -> None:
        subparser.add_argument("--track-id", required=track_required)
        subparser.add_argument("--expected-revision", required=True, type=int)
        subparser.add_argument("--idempotency-key", required=True)
        subparser.add_argument("--actor", default="main-agent")

    begin_parser = subparsers.add_parser("begin")
    add_write_options(begin_parser)
    begin_parser.add_argument("--goal", required=True)
    begin_parser.add_argument("--authentic-outcome", required=True)
    begin_parser.add_argument("--primary-adapter", required=True)
    begin_parser.add_argument("--secondary-adapter")
    begin_parser.add_argument("--mvc", required=True)
    begin_parser.add_argument("--next-action")
    begin_parser.set_defaults(handler=command_begin)

    record_parser = subparsers.add_parser("record")
    add_write_options(record_parser, track_required=False)
    record_parser.add_argument("--event-type", required=True)
    record_parser.add_argument("--payload", required=True)
    record_parser.set_defaults(handler=command_record)

    finish_parser = subparsers.add_parser("finish")
    add_write_options(finish_parser)
    finish_parser.add_argument("--outcome", required=True)
    finish_parser.add_argument("--summary", required=True)
    finish_parser.set_defaults(handler=command_finish)

    rebuild_parser = subparsers.add_parser("rebuild")
    rebuild_parser.add_argument("--replace-derived", action="store_true")
    rebuild_parser.set_defaults(handler=command_rebuild)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = build_parser().parse_args(argv)
        args.state_dir = args.state_dir.resolve()
        result = args.handler(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except StateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed without leaking a traceback by default
        print(
            json.dumps(
                {"ok": False, "error": f"unexpected state-tool failure: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
