"""Run the offline H4 matrix without secrets, network, or API inference."""
import argparse
import json

from .replay import run_replays


def main() -> int:
    parser = argparse.ArgumentParser(description='LOCKGATE H4 offline proposal replay')
    parser.add_argument('--output-dir', default='runtime/replay')
    args = parser.parse_args()
    try:
        report = run_replays(args.output_dir)
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({'status': 'HALTED', 'error_type': type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'REPLAY_PASSED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
