"""A single-use Groq proposer with parent-enforced worker lifetime."""
import hashlib
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .groq_worker import MAX_ACTION_BYTES, request_bytes
from .model_budget import ModelBudget, ProviderError

ROOT = Path(__file__).resolve().parent.parent


def communicate_with_deadline(process, payload: bytes, timeout: float) -> bytes:
    try:
        stdout, _ = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise ProviderError('WALL_TIME_BUDGET') from None
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode != 0:
        raise ProviderError('WORKER_FAILED')
    return stdout


class BoundedGroqPlanner:
    def __init__(self, model: str, api_key: str, budget: ModelBudget):
        if model not in budget.allowed_models:
            raise ValueError('Model is not in the trusted allowlist')
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError('GROQ_API_KEY is required')
        self.model = model
        self._api_key = api_key
        self.budget = budget
        self.calls_used = 0
        self._metadata = {'status': 'NOT_CALLED', 'error_code': None,
                          'request_attempted': False, 'usage': None,
                          'finish_reason': None, 'latency_seconds': None}

    def telemetry(self) -> dict:
        return {'provider_id': 'groq', 'model_id': self.model, 'calls_used': self.calls_used,
                'budget': asdict(self.budget),
                'budget_sha256': hashlib.sha256(json.dumps(asdict(self.budget), sort_keys=True,
                    separators=(',', ':')).encode()).hexdigest(), 'cost_usd': None,
                **deepcopy(self._metadata)}

    def next_action(self, context: dict) -> dict:
        if self.calls_used >= self.budget.max_calls:
            raise ProviderError('CALL_BUDGET')
        # Validate size before reserving an attempt or starting any process.
        try:
            request_size = len(request_bytes(self.model, context, self.budget))
            data = json.dumps({'model': self.model, 'context': context,
                               'budget': asdict(self.budget)}, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, RecursionError):
            self._metadata.update(status='ERROR', error_code='INVALID_CONTEXT')
            raise ProviderError('INVALID_CONTEXT') from None
        if request_size > self.budget.max_request_bytes or len(data) > 65536:
            self._metadata.update(status='ERROR', error_code='REQUEST_TOO_LARGE')
            raise ProviderError('REQUEST_TOO_LARGE')
        self.calls_used += 1  # Failures are not refunded; there are no retries.
        start = time.monotonic()
        self._metadata.update(status='ERROR', error_code='WORKER_FAILED', request_attempted=None)
        try:
            env = {'GROQ_API_KEY': self._api_key, 'PYTHONPATH': str(ROOT),
                   'PYTHONIOENCODING': 'utf-8'}
            if os.name == 'nt' and 'SystemRoot' in os.environ:
                env['SystemRoot'] = os.environ['SystemRoot']
            process = subprocess.Popen([sys.executable, '-m', 'lockgate.groq_worker'],
                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            raw = communicate_with_deadline(process, data, self.budget.wall_time_seconds)
            if len(raw) > self.budget.max_response_bytes:
                raise ProviderError('WORKER_OUTPUT_TOO_LARGE')
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('status') not in ('OK', 'ERROR'):
                raise ProviderError('INVALID_WORKER_OUTPUT')
            usage = value.get('usage')
            if usage is not None and (not isinstance(usage, dict)
                    or set(usage) != {'prompt_tokens', 'completion_tokens', 'total_tokens'}
                    or any(type(v) is not int or v < 0 for v in usage.values())):
                raise ProviderError('INVALID_WORKER_OUTPUT')
            attempted = value.get('request_attempted')
            finish = value.get('finish_reason')
            if type(attempted) is not bool or finish not in (None, 'stop', 'length', 'tool_calls', 'content_filter', 'other'):
                raise ProviderError('INVALID_WORKER_OUTPUT')
            self._metadata.update(status=value['status'], request_attempted=attempted,
                                  usage=usage, finish_reason=finish, error_code=None)
            if value['status'] == 'ERROR':
                code = value.get('error_code')
                if not isinstance(code, str) or not code or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789' for c in code):
                    raise ProviderError('INVALID_WORKER_OUTPUT')
                raise ProviderError(code)
            action = value.get('action')
            if not isinstance(action, dict) or len(json.dumps(action).encode('utf-8')) > MAX_ACTION_BYTES:
                raise ProviderError('INVALID_WORKER_OUTPUT')
            return action
        except ProviderError as exc:
            self._metadata.update(status='ERROR', error_code=exc.code)
            raise
        except (OSError, ValueError, TypeError):
            self._metadata.update(status='ERROR', error_code='WORKER_FAILED')
            raise ProviderError('WORKER_FAILED') from None
        finally:
            self._metadata['latency_seconds'] = round(time.monotonic() - start, 6)
