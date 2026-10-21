"""Pluggable intent providers; none has direct tool or database access."""
from __future__ import annotations



class DemoPlanner:
    """Exercise a normal workflow without an API key."""
    def next_action(self, context: dict) -> dict:
        reads = [x for x in context["observations"] if x.get("tool") == "read_record"]
        if not reads:
            return {"type": "tool", "tool": "read_record", "args": {"record_id": "demo-001"}}
        observation = reads[-1]["output"]
        record = observation["record"]
        return {"type": "final", "output": {
            "record_id": record["record_id"], "title": record["title"],
            "source_url": record["source_url"],
            "recommendation": "Review the official terms before any real application.",
            "evidence_ids": [observation["evidence_id"]]}}


class WrongToolPlanner:
    def next_action(self, context: dict) -> dict:
        return {"type": "tool", "tool": "send_email", "args": {"to": "someone@example.com"}}


class SkipProofPlanner:
    def next_action(self, context: dict) -> dict:
        return {"type": "final", "output": {"record_id": "demo-001",
            "title": "Synthetic Example Credit", "source_url": "https://example.org/fictional-credit",
            "recommendation": "Apply now", "evidence_ids": ["ev_forged"]}}


class LooperPlanner:
    def next_action(self, context: dict) -> dict:
        return {"type": "tool", "tool": "list_records", "args": {}}


