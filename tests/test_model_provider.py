import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from lockgate.groq_worker import ENDPOINT, _NoRedirect, request_completion
from lockgate.model_budget import ModelBudget, ProviderError
from lockgate.model_cli import main, run_remote_case
from lockgate.model_provider import BoundedGroqPlanner, communicate_with_deadline
from lockgate.replay import ROOT, SeededPlanner

MODEL = 'openai/gpt-oss-20b'
KEY = 'synthetic-private-test-key'
BUDGET = ModelBudget.from_file(ROOT / 'contracts/model.json')
ACTION = {'type': 'final', 'output': {'profile_id': 'demo', 'facts': {}, 'decision': 'UNKNOWN'}}


def completion():
    return {'model': MODEL, 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(ACTION)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 80, 'total_tokens': 180}}


class Response:
    def __init__(self, body):
        self.body = body
        self.status = 200
        self.headers = {'Content-Type': 'application/json'}
        self.read_limits = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        self.read_limits.append(limit)
        return self.body[:limit]


class ModelProviderTest(unittest.TestCase):
    def invoke_transport(self, value):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        response = Response(body)
        with patch('lockgate.groq_worker.build_opener') as factory:
            factory.return_value.open.return_value = response
            result = request_completion(MODEL, {'allowed_actions': ['final']}, BUDGET, KEY)
        return result, factory, response

    def test_transport_caps_tokens_disables_tools_and_keeps_key_out_of_payload(self):
        result, factory, response = self.invoke_transport(completion())
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['action'], ACTION)
        request = factory.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(payload['max_completion_tokens'], BUDGET.max_completion_tokens)
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertEqual(payload['tools'], [])
        self.assertFalse(payload['stream'])
        self.assertNotIn(KEY, request.data.decode())
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + KEY)
        self.assertEqual(response.read_limits, [BUDGET.max_response_bytes + 1])
        handlers = factory.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[-1], _NoRedirect)
        self.assertIsNone(handlers[-1].redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_truncation_tool_calls_model_changes_and_usage_overrun_are_rejected(self):
        cases = []
        value = completion(); value['choices'][0]['finish_reason'] = 'length'
        cases.append((value, 'TRUNCATED_COMPLETION'))
        value = completion(); value['choices'][0]['message']['tool_calls'] = [{'name': 'execute'}]
        cases.append((value, 'TOOL_OUTPUT_DENIED'))
        value = completion(); value['model'] = 'unrequested-model'
        cases.append((value, 'RESPONSE_MODEL_MISMATCH'))
        value = completion(); value['usage']['completion_tokens'] = BUDGET.max_completion_tokens + 1
        cases.append((value, 'REPORTED_TOKEN_CAP_EXCEEDED'))
        value = completion(); value['choices'][0]['message']['content'] = '{"type":"final","type":"tool"}'
        cases.append((value, 'INVALID_PROVIDER_RESPONSE'))
        for value, code in cases:
            with self.subTest(code=code):
                result, _, _ = self.invoke_transport(value)
                self.assertEqual(result['status'], 'ERROR')
                self.assertEqual(result['error_code'], code)
                self.assertNotIn('action', result)

    def test_oversized_response_and_action_are_rejected_and_missing_usage_is_unknown(self):
        result, _, _ = self.invoke_transport(b'x' * (BUDGET.max_response_bytes + 1))
        self.assertEqual(result['error_code'], 'RESPONSE_TOO_LARGE')
        value = completion(); value['choices'][0]['message']['content'] = 'x' * 16385
        result, _, _ = self.invoke_transport(value)
        self.assertEqual(result['error_code'], 'INVALID_OR_OVERSIZED_ACTION')
        value = completion(); value.pop('usage')
        result, _, _ = self.invoke_transport(value)
        self.assertEqual(result['status'], 'OK')
        self.assertIsNone(result['usage'])

    def test_http_errors_do_not_retry_or_echo_provider_bodies(self):
        for code in (302, 429, 500):
            with self.subTest(code=code), patch('lockgate.groq_worker.build_opener') as factory:
                factory.return_value.open.side_effect = HTTPError(ENDPOINT, code, KEY, {}, io.BytesIO(KEY.encode()))
                result = request_completion(MODEL, {}, BUDGET, KEY)
                self.assertEqual(result['error_code'], 'HTTP_' + str(code))
                self.assertEqual(factory.return_value.open.call_count, 1)
                self.assertNotIn(KEY, json.dumps(result))

    def test_oversized_request_and_disallowed_model_make_no_attempt(self):
        with patch('lockgate.groq_worker.build_opener') as factory:
            result = request_completion(MODEL, {'text': 'x' * 70000}, BUDGET, KEY)
            self.assertEqual(result['error_code'], 'REQUEST_TOO_LARGE')
            self.assertFalse(result['request_attempted'])
            factory.assert_not_called()
        with self.assertRaises(ValueError):
            BoundedGroqPlanner('groq/compound', KEY, BUDGET)
        with patch('lockgate.model_provider.subprocess.Popen') as spawn:
            planner = BoundedGroqPlanner(MODEL, KEY, BUDGET)
            with self.assertRaisesRegex(ProviderError, 'REQUEST_TOO_LARGE'):
                planner.next_action({'text': 'x' * 70000})
            self.assertEqual(planner.calls_used, 0)
            spawn.assert_not_called()

    def test_host_call_budget_environment_and_telemetry(self):
        result = {'status': 'OK', 'action': ACTION, 'request_attempted': True,
                  'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30},
                  'finish_reason': 'stop'}
        with patch.dict(os.environ, {'UNRELATED_PRIVATE_SECRET': 'do-not-inherit'}), \
                patch('lockgate.model_provider.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.returncode = 0
            process.communicate.return_value = (json.dumps(result).encode(), None)
            planner = BoundedGroqPlanner(MODEL, KEY, BUDGET)
            self.assertEqual(planner.next_action({}), ACTION)
            with self.assertRaisesRegex(ProviderError, 'CALL_BUDGET'):
                planner.next_action({})
            self.assertEqual(spawn.call_count, 1)
            self.assertNotIn(KEY, str(spawn.call_args.args))
            env = spawn.call_args.kwargs['env']
            self.assertEqual(env['GROQ_API_KEY'], KEY)
            self.assertNotIn('UNRELATED_PRIVATE_SECRET', env)
            telemetry = planner.telemetry()
            self.assertEqual(telemetry['calls_used'], 1)
            self.assertEqual(telemetry['usage']['total_tokens'], 30)
            self.assertIsNone(telemetry['cost_usd'])
            self.assertNotIn(KEY, json.dumps(telemetry))

    def test_failed_attempt_consumes_budget_and_keeps_error_sanitized(self):
        error = {'status': 'ERROR', 'error_code': 'HTTP_429', 'request_attempted': True,
                 'usage': None, 'finish_reason': None}
        with patch('lockgate.model_provider.subprocess.Popen') as spawn:
            spawn.return_value.returncode = 0
            spawn.return_value.communicate.return_value = (json.dumps(error).encode(), None)
            planner = BoundedGroqPlanner(MODEL, KEY, BUDGET)
            with self.assertRaisesRegex(ProviderError, 'HTTP_429'):
                planner.next_action({})
            with self.assertRaisesRegex(ProviderError, 'CALL_BUDGET'):
                planner.next_action({})
            self.assertEqual(spawn.call_count, 1)
            self.assertEqual(planner.telemetry()['error_code'], 'HTTP_429')

    def test_parent_really_kills_a_stalled_subprocess(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        with self.assertRaisesRegex(ProviderError, 'WALL_TIME_BUDGET'):
            communicate_with_deadline(process, b'', 0.1)
        self.assertIsNotNone(process.poll())

    def test_timeout_is_recorded_without_inventing_request_usage_or_cost(self):
        with patch('lockgate.model_provider.subprocess.Popen') as spawn:
            process = spawn.return_value
            process.communicate.side_effect = [subprocess.TimeoutExpired('worker', 20), (b'', None)]
            planner = BoundedGroqPlanner(MODEL, KEY, BUDGET)
            with self.assertRaisesRegex(ProviderError, 'WALL_TIME_BUDGET'):
                planner.next_action({})
            process.kill.assert_called_once()
            telemetry = planner.telemetry()
            self.assertEqual(telemetry['calls_used'], 1)
            self.assertEqual(telemetry['error_code'], 'WALL_TIME_BUDGET')
            self.assertIsNone(telemetry['request_attempted'])
            self.assertIsNone(telemetry['usage'])
            self.assertIsNone(telemetry['cost_usd'])

    def test_remote_case_mocked_protocol_integrates_gate_and_sanitized_trace(self):
        class Process:
            returncode = 0

            def communicate(self, payload, timeout):
                context = json.loads(payload)['context']
                action = SeededPlanner('honest').next_action(context)
                return json.dumps({'status': 'OK', 'action': action, 'request_attempted': True,
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 90, 'total_tokens': 190},
                    'finish_reason': 'stop'}).encode(), None

        with tempfile.TemporaryDirectory() as directory, \
                patch('lockgate.model_provider.subprocess.Popen', return_value=Process()):
            report = run_remote_case(directory, MODEL, KEY, 'demo-new', BUDGET)
            self.assertEqual(report['status'], 'EVALUATED')
            self.assertEqual(report['proposal_gate'], 'ACCEPTED')
            self.assertEqual(report['model_id'], MODEL)
            self.assertEqual(report['verified_decision']['source_proof_level'], 'E0_SYNTHETIC_TEXT_MATCH')
            self.assertEqual(report['authorized_actions'], [])
            self.assertNotIn(KEY, json.dumps(report))
            with sqlite3.connect(report['trace_db']) as db:
                events = db.execute('SELECT kind,data_json FROM events ORDER BY seq').fetchall()
                self.assertEqual(events[-1][0], 'MODEL_EVALUATION_FINISH')
                self.assertIn('MODEL_USAGE', [x[0] for x in events])
                self.assertNotIn(KEY, str(events))

    def test_cli_is_offline_by_default_and_missing_credentials_do_not_dispatch(self):
        with patch.object(sys, 'argv', ['model-cli']), \
                patch('lockgate.model_cli.run_replays', return_value={'status': 'REPLAY_PASSED'}), \
                patch('lockgate.model_cli.run_remote_case') as remote, \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main(), 0)
            remote.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(sys, 'argv', ['model-cli', '--provider', 'groq']), \
                patch('lockgate.model_cli.run_remote_case') as remote, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(), 2)
            self.assertEqual(json.loads(output.getvalue())['status'], 'NOT_CONFIGURED')
            remote.assert_not_called()

    def test_budget_rejects_boolean_or_excessive_limits(self):
        for key, value in (('max_calls', 2), ('wall_time_seconds', 31),
                           ('max_completion_tokens', True), ('max_response_bytes', 10**9)):
            data = asdict(BUDGET); data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                ModelBudget.from_dict(data)


if __name__ == '__main__':
    unittest.main()
