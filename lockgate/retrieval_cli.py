"""Trusted-host, read-only retrieval command; not available to the planner."""
import argparse
import json
from pathlib import Path

from .retrieval import RetrievalDenied, RetrievalPolicy, fetch_official_page

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description='LOCKGATE H1 official-page snapshot')
    parser.add_argument('--url', default='https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-FAQ.html')
    parser.add_argument('--policy', default=str(ROOT / 'contracts/retrieval.json'))
    parser.add_argument('--output-dir', default='runtime/snapshots')
    args = parser.parse_args()
    try:
        result = fetch_official_page(args.url, RetrievalPolicy.from_file(args.policy),
                                     args.output_dir)
    except (RetrievalDenied, ValueError) as exc:
        print(json.dumps({'status': 'HALTED', 'reason': str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
