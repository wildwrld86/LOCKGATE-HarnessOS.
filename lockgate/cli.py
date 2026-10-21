"""Run with: python -m lockgate.cli --mode demo"""
import argparse
import json
from pathlib import Path
from .core import Contract, FixtureTools, Harness, TraceStore
from .providers import DemoPlanner, WrongToolPlanner, SkipProofPlanner, LooperPlanner

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = {"demo": DemoPlanner, "wrong-tool": WrongToolPlanner,
             "skip-proof": SkipProofPlanner, "loop": LooperPlanner}


def main() -> int:
    p = argparse.ArgumentParser(description="LOCKGATE // ZERO demonstration harness")
    p.add_argument("--mode", choices=PROVIDERS, default="demo")
    p.add_argument("--contract", default=str(ROOT / "contracts" / "demo.json"))
    p.add_argument("--fixtures", default=str(ROOT / "fixtures" / "opportunities.json"))
    p.add_argument("--db", default="runtime/traces.sqlite3")
    args = p.parse_args()
    store = TraceStore(args.db)
    try:
        run = Harness(Contract.from_file(args.contract), PROVIDERS[args.mode](),
                      FixtureTools(args.fixtures), store).run()
        print(json.dumps(run, indent=2))
        return 0 if run["status"] == "ACCEPTED" else 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
