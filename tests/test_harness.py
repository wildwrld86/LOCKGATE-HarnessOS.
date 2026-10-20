import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lockgate.core import Contract, FixtureTools, Harness, TraceStore
from lockgate.providers import DemoPlanner, WrongToolPlanner, SkipProofPlanner, LooperPlanner

ROOT = Path(__file__).resolve().parent.parent


class HarnessTest(unittest.TestCase):
    def run_case(self, planner):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "traces.db"
            store = TraceStore(db)
            try:
                result = Harness(Contract.from_file(ROOT / "contracts/demo.json"), planner,
                                 FixtureTools(ROOT / "fixtures/opportunities.json"), store).run()
            finally:
                store.close()
            with sqlite3.connect(db) as conn:
                events = [x[0] for x in conn.execute("SELECT kind FROM events ORDER BY seq")]
            return result, events

    def test_happy_path(self):
        result, events = self.run_case(DemoPlanner())
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertIn("TOOL_OK", events)
        self.assertIn("OUTPUT_GATE", events)
        self.assertEqual(result["proof_level"], "synthetic_fixture_grounding_only")

    def test_disallowed_tool_denied(self):
        result, events = self.run_case(WrongToolPlanner())
        self.assertEqual(result["reason"], "UNAUTHORIZED_TOOL")
        self.assertIn("POLICY_DENIAL", events)
        self.assertNotIn("TOOL_OK", events)

    def test_forged_proof_rejected(self):
        result, events = self.run_case(SkipProofPlanner())
        self.assertEqual(result["reason"], "REPEATED_ACTION_LIMIT")
        self.assertIn("OUTPUT_GATE", events)
        self.assertNotEqual(result["status"], "ACCEPTED")

    def test_loop_stopped(self):
        result, events = self.run_case(LooperPlanner())
        self.assertEqual(result["reason"], "REPEATED_ACTION_LIMIT")
        self.assertIn("LOOP_DETECTED", events)

    def test_conflicting_fields_rejected(self):
        class MismatchPlanner(DemoPlanner):
            def next_action(self, context):
                action = super().next_action(context)
                if action["type"] == "final":
                    action["output"]["source_url"] = "https://not-the-source.invalid"
                return action
        result, events = self.run_case(MismatchPlanner())
        self.assertNotEqual(result["status"], "ACCEPTED")
        self.assertIn("OUTPUT_GATE", events)

    def test_contract_rejects_unbounded_budget(self):
        data = json.loads((ROOT / "contracts/demo.json").read_text())
        data["max_steps"] = 1000000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                Contract.from_file(path)

    def test_planner_cannot_rewrite_witnessed_evidence(self):
        class MutatingPlanner(DemoPlanner):
            def next_action(self, context):
                for observation in context["observations"]:
                    if observation.get("tool") == "read_record":
                        observation["output"]["record"]["source_url"] = "https://forged.invalid"
                return super().next_action(context)

        result, events = self.run_case(MutatingPlanner())
        self.assertEqual(result["status"], "HALTED")
        self.assertIn("OUTPUT_GATE", events)
        self.assertIsNone(result["result"])


if __name__ == "__main__":
    unittest.main()
