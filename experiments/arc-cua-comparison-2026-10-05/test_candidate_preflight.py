"""Offline checks for refusing stale candidates and closing failed initialization."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run


class CandidatePreflight(unittest.TestCase):
    def test_outdated_candidate_refuses_before_arc_lookup(self):
        payload = {'current_version': '0.31.0', 'latest_version': '0.33.4', 'update_available': True}
        with patch.object(run.subprocess, 'check_output', return_value=json.dumps(payload)) as command:
            with self.assertRaisesRegex(RuntimeError, 'Update Cua Driver'):
                run.candidate_versions()
            command.assert_called_once()

    def test_inconsistent_update_flag_does_not_admit_stale_version(self):
        payload = {'current_version': '0.31.0', 'latest_version': '0.33.4', 'update_available': False}
        with patch.object(run.subprocess, 'check_output', return_value=json.dumps(payload)):
            with self.assertRaisesRegex(RuntimeError, 'Update Cua Driver'):
                run.candidate_versions()

    def test_old_running_daemon_refuses_even_with_new_cli(self):
        versions = {'native_version': '0.33.4', 'arc_version': '0.1.1'}
        arc = SimpleNamespace(server_info={'version': '0.1.1'})
        native = SimpleNamespace(server_info={'version': '0.31.0'})
        with self.assertRaisesRegex(RuntimeError, 'restart it'):
            run.verify_servers(versions, arc, native)

    def test_matching_servers_record_actual_versions(self):
        versions = {'native_version': '0.33.4', 'arc_version': '0.1.1'}
        arc = SimpleNamespace(server_info={'name': 'arc', 'version': '0.1.1'})
        native = SimpleNamespace(server_info={'name': 'cua-driver', 'version': '0.33.4'})
        run.verify_servers(versions, arc, native)
        self.assertEqual(versions['servers']['native'], native.server_info)

    def test_initialization_failure_closes_spawned_process(self):
        process = Mock()
        with patch.object(run.subprocess, 'Popen', return_value=process), \
             patch.object(run.MCP, 'request', side_effect=TimeoutError('initialization failed')):
            with self.assertRaises(TimeoutError):
                run.MCP(['synthetic-not-executed'], 'preflight-test')
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once()


if __name__ == '__main__':
    unittest.main()
