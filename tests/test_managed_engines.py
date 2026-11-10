"""SquadLoot 1.5.4: self-managed headless live and replay regressions.

Tests do NOT download any third-party executables and do not start Fortnite.
Windows+Fortnite hardware tests remain necessary before calling it verified.
"""
import io
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'SquadLoot-Windows-Client'
sys.path.insert(0,str(CLIENT))
from vision import (ManagedLiveEngine, ManagedReplayEngine,
                    ManagedComponentStore, _safe_archive_member)
from client_core import Core


class StubCore:
    def __init__(self, folder):
        self.lock=threading.RLock()
        self.stop=threading.Event()
        self.round_id=10
        self.vision=0
        self.last_live=10.0
        self.config={'replay_dir':str(folder), 'data_json':str(folder/'data.json')}


class StubStore:
    def __init__(self,exe):
        self.exe=exe
    def ensure_replay(self,*args,**kwargs):
        return self.exe


class LivePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.core=StubCore(Path(self.tmp.name))
        self.engine=ManagedLiveEngine(self.core,store=StubStore('unused'))
        self.engine.round_id=10

    def tearDown(self):
        self.tmp.cleanup()

    def test_approx_includes_certain_once(self):
        self.assertTrue(self.engine.feed_message(
            {'type':'event','verdict':'approx','approx':1,'certain':0}))
        self.assertTrue(self.engine.feed_message(
            {'type':'event','verdict':'certain','approx':2,'certain':1}))
        self.assertEqual(self.core.vision,2)
        self.assertEqual(self.engine.certain,1)
        self.assertFalse(self.engine.feed_message(
            {'type':'counts','approx':2,'certain':1}))
        self.assertEqual(self.core.vision,2)

    def test_reset_and_round_boundary_do_not_double_count(self):
        self.engine.feed_message({'type':'counts','approx':5,'certain':2})
        self.assertEqual(self.core.vision,5)
        self.core.round_id=11
        self.assertFalse(self.engine.feed_message(
            {'type':'counts','approx':5,'certain':2}))
        self.assertEqual(self.core.vision,0)
        self.engine.feed_message({'type':'counts','approx':6,'certain':2})
        self.assertEqual(self.core.vision,1)
        self.engine.feed_message({'type':'counts','approx':0,'certain':0})
        self.assertEqual(self.core.vision,1)
        self.engine.feed_message({'type':'counts','approx':1,'certain':0})
        self.assertEqual(self.core.vision,2)

    def test_rejects_invalid_and_rejected_events(self):
        for event in ({'type':'event','verdict':'rejected','approx':1,'certain':0},
                      {'type':'counts','approx':'4','certain':1},
                      {'type':'counts','approx':3,'certain':4},
                      {'type':'status','approx':99,'certain':99}):
            self.assertFalse(self.engine.feed_message(event))
        self.assertEqual(self.core.vision,0)
        self.engine.feed_message({'type':'counts','approx':1,'certain':0})
        self.engine.reset_counts()
        self.assertEqual(self.core.vision,0)
        self.engine.feed_message({'type':'counts','approx':2,'certain':0})
        self.assertEqual(self.core.vision,1)


class ManagedPackageTests(unittest.TestCase):
    def test_zip_paths_are_restricted(self):
        for name in ('/tmp/evil', 'runtime/../evil', 'runtime\\evil',
                     'C:/evil', 'runtime//evil', 'runtime/./bad'):
            with self.assertRaises(ValueError):
                _safe_archive_member(name)
        self.assertEqual(_safe_archive_member('runtime/python/python.exe'),
                         ['runtime','python','python.exe'])

    def test_extraction_needs_real_runtime_members_and_denies_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            z=Path(tmp)/'valid.zip'
            out=Path(tmp)/'out'
            with zipfile.ZipFile(z,'w') as f:
                f.writestr('runtime/python/python.exe',b'python')
                f.writestr('runtime/lib/fortnite_chest_counter/counter.py',b'code')
                f.writestr('runtime/ffmpeg/ffmpeg.exe',b'ffmpeg')
                f.writestr('Fortnite Visual Chest Counter.exe',b'GUI excluded')
            ManagedComponentStore.unpack_visual_zip(z,out)
            self.assertTrue((out/'runtime/python/python.exe').is_file())
            self.assertFalse((out/'Fortnite Visual Chest Counter.exe').exists())
            bad=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(bad,'w') as f:
                f.writestr('runtime/../evil',b'X')
            with self.assertRaises(ValueError):
                ManagedComponentStore.unpack_visual_zip(bad,Path(tmp)/'badout')


class ReplayEngineTests(unittest.TestCase):
    def test_auto_scan_is_headless_and_uses_own_managed_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            replay=directory/'Game.replay'
            replay.write_bytes(b'fortnite-encrypted-replay')
            older=time.time()-40
            os.utime(replay,(older,older))
            core=StubCore(directory)
            exe=directory/'ChestCounter.exe'
            exe.write_bytes(b'fake exe')
            engine=ManagedReplayEngine(core,store=StubStore(exe))
            fake=SimpleNamespace(returncode=0,stderr=b'',stdout=b'')
            with patch('vision._subprocess2.run',return_value=fake) as runner:
                self.assertTrue(engine.scan_once())
                args=runner.call_args.args[0]
                self.assertIn('--once',args)
                self.assertIn('--demos',args)
                self.assertIn(str(directory),args)
                self.assertIn('--data',args)
                self.assertEqual(args[0],str(exe))
                self.assertFalse(engine.scan_once())
                self.assertTrue(engine.scan_once(force=True))

    def test_cli_failure_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            replay=directory/'Game.replay'
            replay.write_bytes(b'replay')
            older=time.time()-40
            os.utime(replay,(older,older))
            engine=ManagedReplayEngine(StubCore(directory),
                                       store=StubStore(directory/'exe'))
            result=SimpleNamespace(returncode=4,stderr=b'bad replay',stdout=b'')
            with patch('vision._subprocess2.run',return_value=result):
                self.assertFalse(engine.scan_once(force=True))
                self.assertIn('Exit 4',engine.error)


class ReleaseCompatibilityTests(unittest.TestCase):
    def test_existing_update_allowlist_is_untouched(self):
        from update_manager import ALLOWED_FILES, UPDATE_MAX_BYTES
        self.assertIn('vision.py',ALLOWED_FILES)
        self.assertIn('client_core.py',ALLOWED_FILES)
        self.assertIn('app.py',ALLOWED_FILES)
        self.assertLessEqual(UPDATE_MAX_BYTES,4*1024*1024)
        # Neither .exe nor runtime ZIP is embedded in the small auto-update.
        self.assertNotIn('ChestCounter.exe',ALLOWED_FILES)
        self.assertNotIn('Fortnite-Visual-Chest-Counter-v0.2.3.zip',ALLOWED_FILES)

    def test_one_click_ui_has_no_old_manual_setups(self):
        source=(CLIENT/'app.py').read_text(encoding='utf-8')
        for forbidden in ('PNG-Vorlage', 'OBS-Ordner wählen',
                          'Deutsch kalibrieren', 'Erkennung starten',
                          'Pfad zur ChestCounter.exe'):
            self.assertNotIn(forbidden,source)
        self.assertIn('self.live_engine = ManagedLiveEngine(self.core)',source)
        self.assertIn('self.core.replay_engine.start()',source)
        self.assertIn('Live-Test starten',source)


if __name__ == '__main__':
    unittest.main()
