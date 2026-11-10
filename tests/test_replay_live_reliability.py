"""Regression tests for the SquadLoot live/replay reliability hotfix.

No game, Windows API, third-party download or remote server is required.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'SquadLoot-Windows-Client'))
from client_core import Core
from vision import (ManagedComponentStore, ManagedLiveEngine, ManagedReplayEngine,
                    _best_monitor_for_windows, _ppm_from_bgra,
                    managed_replay_data_file)


class TestMonitorSelection(unittest.TestCase):
    def test_detects_game_on_secondary_display(self):
        monitors = [(0, 0, 1920, 1080), (1920, 0, 2560, 1440)]
        self.assertEqual(_best_monitor_for_windows(
            monitors, [(2000, 100, 4480, 1440)]), 2)

    def test_preview_ppm_contains_correct_rgb(self):
        ppm = _ppm_from_bgra(bytes([0, 0, 255, 0, 0, 255, 0, 0]), 2, 1)
        self.assertEqual(ppm, b'P6\n2 1\n255\n' + bytes([255, 0, 0, 0, 255, 0]))

    def test_falls_back_when_game_window_missing(self):
        monitors = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
        self.assertEqual(_best_monitor_for_windows(monitors, []), 1)


class TestReplaySync(unittest.TestCase):
    def test_force_resends_already_sent_match(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data.json'
            data.write_text(json.dumps({'Matches': [{
                'SessionId': 'match-a', 'ReplayFile': 'game.replay',
                'PlayerName': 'Test', 'ChestsOpened': 12,
                'MatchStartUtc': '2026-11-10T18:00:00Z'}]}), encoding='utf-8')
            cfg = {'client_id': 'client-1', 'data_json': str(data)}
            core = Core(config=cfg, state={'sent': {}, 'replay_rounds': {}})
            class Api:
                def __init__(self):
                    self.calls = []
                def call(self, path, data=None):
                    self.calls.append((path, data))
                    return {'ok': True}
            api = Api()
            with patch('client_core.STATE', Path(temp) / 'state.json'):
                self.assertEqual(core.sync_matches(api), 1)
                self.assertEqual(core.sync_matches(api), 0)
                self.assertEqual(core.sync_matches(api, force=True), 1)
            self.assertEqual(len(api.calls), 2)
            self.assertEqual(api.calls[-1][1]['chests'], 12)

    def test_unsuccessful_api_response_is_not_marked_sent(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data.json'
            data.write_text(json.dumps({'Matches': [{
                'SessionId': 'match-b', 'ReplayFile': 'b.replay',
                'PlayerName': 'Test', 'ChestsOpened': 3}]}), encoding='utf-8')
            core = Core(config={'client_id': 'client-1', 'data_json': str(data)},
                        state={'sent': {}, 'replay_rounds': {}})
            class Api:
                def call(self, path, body=None):
                    return {'ok': False}
            with self.assertRaisesRegex(RuntimeError, 'nicht bestätigt'):
                core.sync_matches(Api())
            self.assertEqual(core.state['sent'], {})

    def test_replay_failure_does_not_block_live_and_state(self):
        core = Core(config={'client_id': 'client-x', 'name': 'Test'},
                    state={'sent': {}, 'replay_rounds': {}})
        core.round_id = 3
        events = []
        class Api:
            def call(self, path, body=None):
                events.append(path)
                if path == '/api/match':
                    raise RuntimeError('403 replay rejected')
                if path == '/api/state':
                    return {'round': {'id': 3}}
                return {'ok': True}
        with patch.object(core, 'credentials', return_value=Api()), \
             patch.object(core, 'watch_new_replay'), \
             patch.object(core, 'sync_matches', side_effect=RuntimeError('403 replay rejected')):
            core.poll_once()
        self.assertIn('/api/live', events)
        self.assertIn('/api/state', events)
        self.assertTrue(core.connected)
        self.assertIn('Replay-Upload', core.status)


class TestReplayWorkerFailures(unittest.TestCase):
    def test_already_running_external_counter_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            replay = folder / 'game.replay'
            replay.write_bytes(b'fake')
            aged = time.time() - 45
            import os
            os.utime(replay, (aged, aged))
            core = SimpleNamespace(
                config={'replay_dir': str(folder), 'data_json': str(folder / 'data.json')},
                stop=threading.Event())
            store = SimpleNamespace(ensure_replay=lambda: folder / 'ChestCounter.exe')
            engine = ManagedReplayEngine(core, store=store)
            mock_result = SimpleNamespace(returncode=0, stdout=b'Chest counter is already open',
                                          stderr=b'')
            with patch('vision._subprocess2.run', return_value=mock_result):
                self.assertFalse(engine.scan_once(force=True))
            self.assertIn('bereits geöffnet', engine.error)
            self.assertEqual(engine.finished, 0)



class TestManagedLiveWorker(unittest.TestCase):
    def test_live_uses_configured_monitor_2_and_pins_english(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            core = SimpleNamespace(
                config={'live_monitor': 2}, lock=threading.RLock(),
                vision=0, last_live=0, round_id=2)
            class Store:
                def ensure_visual(self, **kwargs):
                    return root
                def visual_python(self):
                    return root / 'runtime/python/python.exe'
                def german_available(self):
                    return False
            class Process:
                stdout = [
                    b'{"type":"connected","source":"desktop: monitor 2"}\n',
                    b'{"type":"counts","approx":3,"certain":2}\n',
                ]
                def wait(self, timeout=None):
                    return 0
                def poll(self):
                    return 0
            engine = ManagedLiveEngine(core, store=Store())
            with patch('vision._subprocess2.Popen', return_value=Process()) as mocked:
                engine._run()
            cmd = mocked.call_args.args[0]
            self.assertEqual(cmd[cmd.index('--monitor') + 1], '2')
            self.assertIn('languages = ["en"]',
                          (root / 'squadloot-live.toml').read_text(encoding='utf-8'))
            self.assertEqual(core.vision, 3)
            self.assertEqual(engine.state, 'Beendet')
            self.assertEqual(engine.monitor, 2)

    def test_live_reports_missing_capture_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            core = SimpleNamespace(
                config={'live_monitor': 'auto'}, lock=threading.RLock(),
                vision=0, last_live=0, round_id=2)
            class Store:
                def ensure_visual(self, **kwargs):
                    return root
                def visual_python(self):
                    return root / 'python.exe'
                def german_available(self):
                    return False
            class Process:
                stdout = [b'{"type":"error","text":"no desktop source"}\n']
                def wait(self, timeout=None):
                    return 0
                def poll(self):
                    return 0
            engine = ManagedLiveEngine(core, store=Store())
            with patch('vision.detect_fortnite_monitor', return_value=2), \
                 patch('vision._subprocess2.Popen', return_value=Process()):
                engine._run()
            self.assertEqual(engine.state, 'Fehler')
            self.assertIn('ohne Monitor-Verbindung', engine.error)



class TestCapturePerformance(unittest.TestCase):
    def test_patch_exact_original_and_preserve_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagedComponentStore(root=Path(tmp))
            source = (store.visual_root() / 'runtime/lib/fortnite_chest_counter'
                      / 'input/video_sources.py')
            source.parent.mkdir(parents=True, exist_ok=True)
            original = 'args = ["-framerate", "30", "-offset_x", str(x)]\n'
            source.write_text(original, encoding='utf-8')
            cache = source.parent / '__pycache__'
            cache.mkdir()
            stale = cache / 'video_sources.cpython-313.pyc'
            stale.write_bytes(b'official unchecked-hash bytecode')
            self.assertTrue(store.tune_visual_capture())
            self.assertFalse(stale.exists(), 'the source patch must invalidate unchecked bytecode')
            updated = source.read_text(encoding='utf-8')
            self.assertIn('"-framerate", str(fps)', updated)
            # Also purge any old cache if the patched source was already there.
            stale.write_bytes(b'old cache')
            self.assertFalse(store.tune_visual_capture())
            self.assertFalse(stale.exists())
            self.assertEqual(source.with_name(
                'video_sources.py.squadloot-original').read_text(encoding='utf-8'), original)
            compile(updated, str(source), 'exec')

    def test_reject_unrecognized_engine_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagedComponentStore(root=Path(tmp))
            source = (store.visual_root() / 'runtime/lib/fortnite_chest_counter'
                      / 'input/video_sources.py')
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('raise RuntimeError("other version")\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'Unbekannte'):
                store.tune_visual_capture()


class TestExpandedLive(unittest.TestCase):
    def test_english_rate_telemetry_and_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = SimpleNamespace(config={'live_language':'en','live_process_fps':20,
                'live_monitor':2,'live_diagnostics':False}, lock=threading.RLock(),
                live_wake=threading.Event(), vision=0, last_live=0, round_id=2)
            class Store:
                def ensure_visual(self, **kw): return root
                def tune_visual_capture(self): return True
                def german_available(self): return False
                def visual_python(self): return root / 'python.exe'
            class Process:
                stdout = [
                    b'{"type":"connected","source":"desktop: monitor 2"}\n',
                    b'{"type":"event","verdict":"approx","approx":1,"certain":0}\n',
                    b'{"type":"counts","approx":1,"certain":0}\n',
                    b'{"type":"types","breakdown":{"normal":{"approx":1,"certain":0}}}\n',
                    b'{"type":"status","fps":19.8,"ms_per_frame":13.5,"dropped":3}\n']
                def wait(self, timeout=None): return 0
                def poll(self): return 0
            engine = ManagedLiveEngine(core, store=Store())
            with patch('vision._subprocess2.Popen', return_value=Process()):
                engine._run()
            self.assertEqual(core.vision, 1)
            self.assertTrue(core.live_wake.is_set())
            self.assertEqual(engine.fps, 19.8)
            self.assertEqual(engine.frame_ms, 13.5)
            self.assertEqual(engine.dropped, 3)
            self.assertEqual(engine.chest_types['normal'], 1)
            cfg=(root/'squadloot-live.toml').read_text(encoding='utf-8')
            self.assertIn('process_fps = 20', cfg)
            self.assertIn('languages = ["en"]', cfg)
            self.assertIn('mode = "off"', cfg)

    def test_de_requires_genuine_popup_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=SimpleNamespace(config={'live_language':'de','live_monitor':2},
                  lock=threading.RLock(), vision=0,last_live=0,round_id=1)
            class Store:
                def ensure_visual(self, **kw): return Path(tmp)
                def tune_visual_capture(self): return True
                def german_available(self): return False
            engine=ManagedLiveEngine(core,store=Store())
            engine._run()
            self.assertEqual(engine.state,'Fehler')
            self.assertIn('TRUHE-Popup-Muster',engine.error)

    def test_diagnostic_recording_opt_in_and_type_markers(self):
        import io
        core=SimpleNamespace(config={},lock=threading.RLock(),
              vision=0,round_id=1,last_live=0)
        engine=ManagedLiveEngine(core)
        class Process:
            def __init__(self): self.stdin=io.BytesIO()
            def poll(self): return None
        process=Process()
        engine.state='Live-Tracking aktiv'
        engine.process=process
        self.assertFalse(engine.mark_missed('food'))
        self.assertTrue(engine.set_diagnostics(True))
        self.assertTrue(engine.mark_missed('food'))
        self.assertTrue(engine.mark_missed('destroyed'))
        self.assertTrue(engine.set_diagnostics(False))
        self.assertEqual(process.stdin.getvalue(),
            b'capture marks\nmark food box\nmark chest destroyed\ncapture off\n')



class TestReplayContainerCategories(unittest.TestCase):
    def test_verified_replay_separates_destroyed_ammo_food_and_other(self):
        from replay_reader import match_to_payload
        record = {
            'SessionId': 'mixed-categories',
            'ReplayFile': 'match.replay',
            'PlayerName': 'Tester',
            'IsBattleRoyale': True,
            'ChestsOpened': 3,
            'Chests': [
                {'Kind': 'Coffre', 'Destroyed': False},
                {'Kind': 'Coffre rare', 'Destroyed': True},
                {'Kind': 'Coffre', 'Destroyed': True}],
            'AmmoBoxesOpened': 7,
            'OtherContainersOpened': 9,
            'OtherInteractions': {
                'Caisse de munitions': 7,
                'Caisse de nourriture': 4,
                'Autre conteneur': 5,
            },
        }
        result = match_to_payload(record, 'pc')
        self.assertEqual(result['chests'], 3)
        self.assertEqual(result['destroyed'], 2)
        self.assertEqual(result['ammo'], 7)
        self.assertEqual(result['food'], 4)
        self.assertEqual(result['other'], 5)
        self.assertEqual(result['kinds']['Coffre rare'], 1)
        self.assertEqual(result['kinds']['Autre conteneur'], 5)

class TestReplayExtra(unittest.TestCase):
    def test_custom_legacy_json_basename_uses_actual_managed_output(self):
        with tempfile.TemporaryDirectory() as temp:
            alias = Path(temp) / 'other-name.json'
            correct = Path(temp) / 'data.json'
            self.assertEqual(managed_replay_data_file({'data_json': str(alias)}), correct)
            correct.write_text(json.dumps({'Matches': [{
                'SessionId': 'from-correct-json', 'ReplayFile': 'r.replay',
                'PlayerName': 'Tester', 'ChestsOpened': 11}]}), encoding='utf-8')
            core = Core(config={'client_id': 'pc', 'data_json': str(alias)},
                        state={'sent': {}, 'replay_rounds': {}})
            class Api:
                def call(self, path, body=None):
                    self.assertion = body
                    return {'ok': True}
            api = Api()
            with patch('client_core.STATE', Path(temp) / 'state.json'):
                self.assertEqual(core.sync_matches(api), 1)
            self.assertEqual(api.assertion['chests'], 11)

    def test_unreadable_replay_reports_warning_without_blocking_other_uploads(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            replay = folder / 'game.replay'
            replay.write_bytes(b'bad replay')
            import os
            aged = time.time() - 40
            os.utime(replay, (aged, aged))
            core = SimpleNamespace(
                config={'replay_dir': str(folder), 'data_json': str(folder / 'data.json')},
                stop=threading.Event())
            store = SimpleNamespace(ensure_replay=lambda: folder / 'ChestCounter.exe')
            engine = ManagedReplayEngine(core, store=store)
            fake = SimpleNamespace(returncode=0,
                stdout=b'Cannot read this replay: unknown replay format',
                stderr=b'')
            with patch('vision._subprocess2.run', return_value=fake):
                self.assertTrue(engine.scan_once(force=True))
            self.assertEqual(engine.finished, 1)
            self.assertIn('nicht lesbar', engine.error)

    def test_concurrent_sync_does_not_double_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data.json'
            data.write_text(json.dumps({'Matches': [{
                'SessionId': 'sync-lock', 'ReplayFile': 'g.replay',
                'PlayerName': 'Tester', 'ChestsOpened': 3}]}), encoding='utf-8')
            core = Core(config={'client_id': 'pc', 'data_json': str(data)},
                        state={'sent': {}, 'replay_rounds': {}})
            class Api:
                def __init__(self):
                    self.calls = 0
                def call(self, path, body=None):
                    self.calls += 1
                    time.sleep(.05)
                    return {'ok': True}
            api = Api()
            counts = []
            with patch('client_core.STATE', Path(temp) / 'state.json'):
                threads = [threading.Thread(target=lambda: counts.append(core.sync_matches(api)))
                           for _ in range(2)]
                for thread in threads: thread.start()
                for thread in threads: thread.join(3)
            self.assertEqual(sorted(counts), [0, 1])
            self.assertEqual(api.calls, 1)

    def test_replay_diagnostics_never_exposes_tokens(self):
        with tempfile.TemporaryDirectory() as temp:
            core = Core(config={'client_id': 'pc', 'token': 'not-for-logs',
                                'replay_dir': str(Path(temp) / 'missing'),
                                'data_json': str(Path(temp) / 'data.json')},
                        state={'sent': {}, 'replay_rounds': {}})
            report = core.replay_diagnostics()
            self.assertIn('Replay-Dateien auf diesem PC: 0', report)
            self.assertIn('Analyse-JSON:', report)
            self.assertNotIn('not-for-logs', report)


if __name__ == '__main__':
    unittest.main()
