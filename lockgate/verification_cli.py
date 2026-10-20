"""Trusted-host source text check, separate from the H0 planner."""
import argparse
import json
from pathlib import Path

from .verification import ClaimsPolicy, VerificationDenied, check_snapshot

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description='LOCKGATE H2 source-text check')
    parser.add_argument('--retrieval-summary', required=True)
    parser.add_argument('--policy', default=str(ROOT / 'contracts' / 'claims.json'))
    args = parser.parse_args()
    try:
        summary = json.loads(Path(args.retrieval_summary).read_text(encoding='utf-8'))
        result = check_snapshot(summary['manifest_path'], ClaimsPolicy.from_file(args.policy))
    except (KeyError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'HALTED', 'reason': str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'CHECKED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
