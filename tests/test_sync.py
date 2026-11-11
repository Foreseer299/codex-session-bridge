"""Metadata reconciliation against isolated, synthetic records."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class Reconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = Path(self.tmp.name) / 'config.json'
        config.write_text(json.dumps({'paseoHome': self.tmp.name, 'paseoCli': '/example/paseo', 'node': '/example/node'}))
        spec = importlib.util.spec_from_file_location('bridge_sync', Path(__file__).resolve().parents[1] / 'scripts/sync.py')
        self.sync = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'CODEX_SESSION_BRIDGE_CONFIG': str(config)}):
            spec.loader.exec_module(self.sync)
        self.thread = {'id': 'test-thread', 'name': 'Old title', 'archived': False}
        self.agent = {'id': 'test-agent', 'title': 'Old title', 'provider': 'codex', 'cwd': self.tmp.name}
        self.previous = {'nativeTitle': 'Old title', 'paseoTitle': 'Old title', 'nativeArchived': False, 'paseoArchived': False}

    def test_paseo_title_updates_native(self):
        self.agent['title'] = 'New title'
        with patch.object(self.sync, 'codex_metadata', return_value=True) as native:
            state = self.sync.reconcile_metadata(self.thread, self.agent, self.previous, True, {})
        native.assert_called_once_with('thread/name/set', 'test-thread', name='New title')
        self.assertEqual(state['nativeTitle'], 'New title')

    def test_native_title_updates_paseo(self):
        self.thread['name'] = 'Desktop title'
        with patch.object(self.sync, 'paseo', return_value=SimpleNamespace(returncode=0)) as paseo:
            state = self.sync.reconcile_metadata(self.thread, self.agent, self.previous, False, {})
        paseo.assert_called_once_with('agent', 'update', 'test-agent', '--name=Desktop title')
        self.assertEqual(state['paseoTitle'], 'Desktop title')

    def test_paseo_archive_updates_native(self):
        self.agent['archivedAt'] = '2026-01-01T00:00:00Z'
        with patch.object(self.sync, 'codex_metadata', return_value=True) as native:
            state = self.sync.reconcile_metadata(self.thread, self.agent, self.previous, True, {})
        native.assert_called_once_with('thread/archive', 'test-thread')
        self.assertTrue(state['nativeArchived'])

    def test_new_native_restore_event_wins_over_older_local_archive(self):
        self.agent['archivedAt'] = '2026-01-01T00:00:00Z'
        events = {'archive': {'version': 'new-event', 'at': 2000000000000, 'value': False}}
        with patch.object(self.sync, 'paseo', return_value=SimpleNamespace(returncode=0)) as paseo:
            state = self.sync.reconcile_metadata(self.thread, self.agent, self.previous, True, events)
        paseo.assert_called_once_with('agent', 'import', 'test-thread', '--provider', 'codex', '--cwd', self.tmp.name)
        self.assertFalse(state['paseoArchived'])

    def test_failed_update_does_not_commit_success_state(self):
        self.thread['name'] = 'New title'
        with patch.object(self.sync, 'paseo', return_value=SimpleNamespace(returncode=1)):
            self.assertIsNone(self.sync.reconcile_metadata(self.thread, self.agent, self.previous, False, {}))

    def test_database_history_does_not_require_old_rollout_file(self):
        record = {'cwd': self.tmp.name, 'source': 'cli', 'path': '/does-not-exist/old-rollout.jsonl'}
        self.assertTrue(self.sync.is_root_codex_thread(record))
        self.assertFalse(self.sync.is_root_codex_thread({**record, 'parentThreadId': 'parent'}))
        self.assertFalse(self.sync.is_root_codex_thread({**record, 'ephemeral': True}))
