"""State-machine and release regressions. No Fortnite or Windows needed."""
import importlib.util
from pathlib import Path
import json
import tempfile
import unittest
import zipfile
import hashlib
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'SquadLoot-Windows-Client'))
from vision import SearchInteraction, WindowsInput

spec=importlib.util.spec_from_file_location('squadloot_release',ROOT/'scripts'/'build_release.py')
release=importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class LiveVisionTests(unittest.TestCase):
    def test_requires_interaction_key(self):
        d=SearchInteraction(threshold=.85)
        self.assertFalse(d.update(.94,False,1.0))
        self.assertFalse(d.update(.96,False,1.4))
        self.assertFalse(d.update(.10,False,1.8))
        self.assertFalse(d.update(.10,False,2.2))
        self.assertEqual(d.last_event,-1000)

    def test_counts_prompt_and_key_and_disappearance(self):
        d=SearchInteraction(threshold=.85)
        self.assertFalse(d.update(.91,False,1))
        self.assertFalse(d.update(.93,True,1.3))
        self.assertFalse(d.update(.1,False,1.7))
        self.assertTrue(d.update(.1,False,2.0))
        self.assertFalse(d.update(.1,False,2.2))
        self.assertEqual(d.last_event,2.0)

    def test_rejects_old_key(self):
        d=SearchInteraction()
        d.update(.95,False,1.0)
        d.update(.95,True,1.5)
        d.update(.1,False,5.0)
        self.assertFalse(d.update(.1,False,5.5))

    def test_rejects_fast_fake_prompt(self):
        d=SearchInteraction()
        d.update(.95,True,1.0)
        d.update(.2,False,1.1)
        self.assertFalse(d.update(.2,False,1.2))

    def test_key_input_fails_closed_outside_windows(self):
        inp=WindowsInput()
        # Only on Linux in Actions, Windows must be manually tested.
        if inp.user32 is None:
            self.assertFalse(inp.key_pressed('E'))
            self.assertFalse(inp.fortnite_focused())


class DistributionTests(unittest.TestCase):
    def test_packs_both_client_and_server_updates(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)
            pi=release.build('1.3.0','LevinGamer8/SquadLoot',out)
            manifest=json.loads((out/'latest.json').read_text())
            self.assertEqual(manifest['client_version'],'1.3.0')
            self.assertEqual(manifest['package_sha256'],hashlib.sha256(pi.read_bytes()).hexdigest())
            client=out/'SquadLoot-Windows-1.3.0-update.zip'
            self.assertEqual(manifest['client_package_sha256'],hashlib.sha256(client.read_bytes()).hexdigest())
            with zipfile.ZipFile(client) as z:
                self.assertIn('vision.py',z.namelist())
                self.assertIn('app.py',z.namelist())
                self.assertEqual(z.read('VERSION').decode().strip(),'1.3.0')
            full=out/'SquadLoot-Windows-Client-v1.3.0.zip'
            with zipfile.ZipFile(full) as z:
                self.assertIn('SquadLoot-Windows-Client/STARTEN.cmd',z.namelist())
                self.assertNotIn('SquadLoot-Windows-Client/config.json',z.namelist())


if __name__=='__main__':unittest.main()
