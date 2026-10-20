"""A deterministic control plane. The model proposes; this module enforces.

Demo trust level: evidence is synthetic fixture data, not independently checked
against an external website. Do not treat accepted demo outputs as verified facts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Contract:
    task_id: str
    goal: str
    allowed_tools: tuple[str, ...]
    max_steps: int
    max_repeated_action: int
    max_evidence_age_seconds: int
    required_output_fields: tuple[str, ...]
    exact_match_fields: tuple[str, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> "Contract":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        required = {"task_id", "goal", "allowed_tools", "max_steps", "max_repeated_action",
                    "max_evidence_age_seconds", "required_output_fields", "exact_match_fields"}
        if not required.issubset(data):
            raise ValueError(f"Missing contract fields: {sorted(required - set(data))}")
        if not (1 <= data["max_steps"] <= 100):
            raise ValueError("max_steps must be 1..100")
        if not (1 <= data["max_repeated_action"] <= data["max_steps"]):
            raise ValueError("Invalid max_repeated_action")
        if not (1 <= data["max_evidence_age_seconds"] <= 86400):
            raise ValueError("Invalid max_evidence_age_seconds")
        if "read_record" not in data["allowed_tools"]:
            raise ValueError("This proof-of-concept requires read_record")
        return cls(
            task_id=str(data["task_id"]), goal=str(data["goal"]),
            allowed_tools=tuple(data["allowed_tools"]), max_steps=data["max_steps"],
            max_repeated_action=data["max_repeated_action"],
            max_evidence_age_seconds=data["max_evidence_age_seconds"],
            required_output_fields=tuple(data["required_output_fields"]),
            exact_match_fields=tuple(data["exact_match_fields"]),
        )


class TraceStore:
    """Persistent append-only event log for local demo. No model write access."""
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY (run_id, seq))")
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts (receipt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, at_epoch REAL NOT NULL, source_type TEXT NOT NULL, record_id TEXT NOT NULL, content_sha256 TEXT NOT NULL)")
        self.db.commit()
        self.run_id = uuid.uuid4().hex[:16]
        self.seq = 0

    def event(self, kind: str, data: dict[str, Any]) -> None:
        # Caller must only submit non-sensitive metadata. Never log keys or prompts.
        self.seq += 1
        self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                        (self.run_id, self.seq, utcnow(), kind, canonical_json(data)))
        self.db.commit()

    def receipt(self, record_id: str, payload: dict[str, Any]) -> str:
        receipt_id = "ev_" + uuid.uuid4().hex[:16]
        self.db.execute("INSERT INTO receipts VALUES (?, ?, ?, ?, ?, ?)",
                        (receipt_id, self.run_id, time.time(), "synthetic_fixture",
                         record_id, hashlib.sha256(canonical_json(payload).encode()).hexdigest()))
        self.db.commit()
        return receipt_id

    def close(self) -> None:
        self.db.close()


class FixtureTools:
    """Read-only sandbox. These are synthetic records, NOT live web checks."""
    def __init__(self, fixture_path: str | Path) -> None:
        raw = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        self.records = {str(r["record_id"]): r for r in raw["records"]}

    def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "list_records":
            if args:
                raise ValueError("list_records takes no arguments")
            return {"records": [{"record_id": r["record_id"], "title": r["title"]}
                                for r in self.records.values()]}
        if tool == "read_record":
            if set(args) != {"record_id"} or not isinstance(args["record_id"], str):
                raise ValueError("read_record accepts only string record_id")
            record_id = args["record_id"]
            if record_id not in self.records:
                raise ValueError("Record not found")
            return {"record": self.records[record_id].copy(), "source_type": "synthetic_fixture"}
        raise PermissionError("Tool unregistered: " + tool)


class Planner(Protocol):
    def next_action(self, context: dict[str, Any]) -> dict[str, Any]: ...


class Harness:
    """All decisions to access tools, accept results, and stop are in code."""
    REGISTERED_TOOLS = frozenset({"list_records", "read_record"})

    def __init__(self, contract: Contract, planner: Planner, tools: FixtureTools, trace: TraceStore):
        self.contract = contract
        self.planner = planner
        self.tools = tools
        self.trace = trace
        self.observations: list[dict[str, Any]] = []
        self.receipts: dict[str, tuple[float, dict[str, Any]]] = {}
        self.last_action_key: str | None = None
        self.repeat_count = 0

    def _finish(self, status: str, reason: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        summary = {"run_id": self.trace.run_id, "status": status, "reason": reason,
                   "proof_level": "synthetic_fixture_grounding_only", "result": result}
        self.trace.event("FINISH", {"status": status, "reason": reason})
        return summary

    def _check_final(self, output: Any) -> tuple[bool, str]:
        if not isinstance(output, dict):
            return False, "OUTPUT_NOT_OBJECT"
        for field in self.contract.required_output_fields:
            if not isinstance(output.get(field), str) or not output[field].strip():
                return False, "REQUIRED_FIELD_MISSING:" + field
        cited = output.get("evidence_ids")
        if not isinstance(cited, list) or not cited or not all(isinstance(x, str) for x in cited):
            return False, "MISSING_EVIDENCE_RECEIPT"
        if len(cited) != len(set(cited)):
            return False, "DUPLICATE_EVIDENCE_RECEIPT"
        evidence = []
        for rid in cited:
            rec = self.receipts.get(rid)
            if rec is None:
                return False, "UNKNOWN_EVIDENCE_RECEIPT"
            if time.time() - rec[0] > self.contract.max_evidence_age_seconds:
                return False, "STALE_EVIDENCE_RECEIPT"
            evidence.append(rec[1])
        # All claimed exact-match fields must coexist in one witnessed record.
        if not any(all(output.get(field) == record.get(field)
                       for field in self.contract.exact_match_fields) for record in evidence):
            return False, "CLAIMS_NOT_GROUNDED_TO_SAME_SOURCE"
        return True, "ACCEPTED"

    def run(self) -> dict[str, Any]:
        self.trace.event("START", {"task_id": self.contract.task_id,
                                   "allowed_tools": list(self.contract.allowed_tools),
                                   "max_steps": self.contract.max_steps})
        for step in range(1, self.contract.max_steps + 1):
            ctx = {"goal": self.contract.goal, "allowed_tools": list(self.contract.allowed_tools),
                   "steps_remaining": self.contract.max_steps - step + 1,
                   # Planner-visible data must not alias authoritative receipts.
                   "observations": deepcopy(self.observations[-6:])}
            try:
                action = self.planner.next_action(ctx)
                if not isinstance(action, dict):
                    raise ValueError("Planner response must be JSON object")
            except Exception as exc:
                self.trace.event("MODEL_ERROR", {"step": step, "error_type": type(exc).__name__})
                return self._finish("HALTED", "MODEL_ERROR:" + type(exc).__name__)

            # Deliberately excludes arbitrary output from trace; no secrets/prompts.
            action_type = action.get("type")
            tool_name = action.get("tool")
            action_key = hashlib.sha256(canonical_json(action).encode()).hexdigest()
            self.repeat_count = self.repeat_count + 1 if action_key == self.last_action_key else 1
            self.last_action_key = action_key
            if self.repeat_count > self.contract.max_repeated_action:
                self.trace.event("LOOP_DETECTED", {"step": step, "count": self.repeat_count})
                return self._finish("HALTED", "REPEATED_ACTION_LIMIT")

            if action_type == "tool":
                self.trace.event("TOOL_REQUEST", {"step": step, "tool": str(tool_name)[:100]})
                if (not isinstance(tool_name, str) or tool_name not in self.REGISTERED_TOOLS
                        or tool_name not in self.contract.allowed_tools):
                    self.trace.event("POLICY_DENIAL", {"step": step, "reason": "UNAUTHORIZED_TOOL"})
                    return self._finish("HALTED", "UNAUTHORIZED_TOOL")
                args = action.get("args", {})
                if not isinstance(args, dict):
                    return self._finish("HALTED", "INVALID_TOOL_ARGS")
                try:
                    output = self.tools.execute(tool_name, args)
                except (ValueError, PermissionError) as exc:
                    self.trace.event("TOOL_DENIAL", {"step": step, "reason": type(exc).__name__})
                    self.observations.append({"error": "TOOL_ARGS_REJECTED", "tool": tool_name})
                    continue
                if tool_name == "read_record":
                    record = output["record"]
                    rid = self.trace.receipt(record["record_id"], record)
                    self.receipts[rid] = (time.time(), record)
                    output["evidence_id"] = rid
                self.trace.event("TOOL_OK", {"step": step, "tool": tool_name,
                                             "evidence_issued": "evidence_id" in output})
                self.observations.append({"tool": tool_name, "output": output})
                continue
            if action_type == "final":
                ok, reason = self._check_final(action.get("output"))
                self.trace.event("OUTPUT_GATE", {"step": step, "accepted": ok, "reason": reason})
                if ok:
                    return self._finish("ACCEPTED", reason, action["output"])
                self.observations.append({"error": "OUTPUT_REJECTED", "reason": reason})
                continue
            self.trace.event("ACTION_DENIAL", {"step": step, "reason": "INVALID_ACTION_TYPE"})
            return self._finish("HALTED", "INVALID_ACTION_TYPE")
        return self._finish("HALTED", "STEP_BUDGET_EXHAUSTED")
