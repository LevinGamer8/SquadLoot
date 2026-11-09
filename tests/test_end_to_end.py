import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'SquadLoot-Windows-Client'))
spec=importlib.util.spec_from_file_location('squadserver',ROOT/'SquadLoot-Pi-Server'/'app'/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from client_core import Api,validate_url,Core
from replay_reader import match_to_payload,load_matches,fingerprint

TOKEN='unittest-supersecret-long-key-12345678'


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        server.DB_PATH=Path(cls.tmp.name)/'test.sqlite3'
        server.TOKEN=TOKEN
        server.init_database()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
        cls.api=Api(cls.url,TOKEN)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(2)
        cls.tmp.cleanup()

    def test_01_private_endpoint_requires_token(self):
        wrong=Api(self.url,'a'*26)
        with self.assertRaisesRegex(RuntimeError,'401'):
            wrong.call('/api/state')
        self.assertIn('round',self.api.call('/api/state'))

    def test_02_four_clients_live_and_replay_reconciliation(self):
        names=['Du','Mate1','Mate2','Mate3']
        expected=[17,12,21,9]
        rid=None
        for i,name in enumerate(names):
            res=self.api.call('/api/round/join',{'client_id':f'computer{i}','name':name,'local_replay':f'replay_{i}'})
            if rid is None:rid=res['round_id']
            self.assertEqual(rid,res['round_id'])
            self.api.call('/api/live',{'client_id':f'computer{i}','name':name,'round_id':rid,'manual':expected[i], 'vision':2})
        state=self.api.call('/api/state')
        self.assertEqual(state['round']['chests_total'],59)
        self.assertEqual(len(state['round']['members']),4)
        self.assertTrue(state['round']['provisional'])
        for i,name in enumerate(names):
            self.api.call('/api/match',{
                'client_id':f'computer{i}','session_id':'game-2026-11-09-xy','name':name,
                'account_id':f'account{i}','started':'2026-11-09T18:30:00Z','mode':'Playlist_NoBuild',
                'chests':expected[i],'destroyed':i,'reopened':i//2,'ammo':4,'food':2,'other':0,
                'treasure_count':1 if i==0 else 0,
                'treasure_names':['Gizmo'] if i==0 else [],'round_id':rid,'kinds':{'Coffre':expected[i]}})
        state=self.api.call('/api/state')
        self.assertEqual(state['round']['chests_total'],59)
        self.assertFalse(state['round']['provisional'])
        self.assertEqual(state['history'][0]['players'],4)
        self.assertEqual(state['history'][0]['chests'],59)
        self.assertEqual(state['history'][0]['destroyed'],sum(range(4)))
        self.assertEqual(state['history'][0]['treasures'],1)
        # Re-submission updates existing row rather than doubling it.
        self.api.call('/api/match',{'client_id':'computer0','session_id':'game-2026-11-09-xy',
            'name':'Du','account_id':'account0','started':'2026-11-09T18:30:00Z',
            'chests':17,'treasure_count':1,'treasure_names':['Gizmo'],'round_id':rid})
        self.assertEqual(self.api.call('/api/state')['history'][0]['players'],4)

    def test_03_next_round_auto_join_and_manual_next(self):
        a=self.api.call('/api/round/join',{'client_id':'computer0','name':'Du','local_replay':'replay_next_0'})['round_id']
        b=self.api.call('/api/round/join',{'client_id':'computer1','name':'Mate1','local_replay':'replay_next_1'})['round_id']
        self.assertEqual(a,b)
        self.assertNotEqual(a,1)
        c=self.api.call('/api/round/next',{})['round_id']
        d=self.api.call('/api/round/join',{'client_id':'computer2','name':'Mate2','local_replay':'replay_next_2'})['round_id']
        self.assertEqual(c,d)

    def test_04_replay_normalization_two_accounts_and_idempotency(self):
        m={'SessionId':'gameZZ','ReplayFile':'Replay77.replay','MatchStartUtc':'2026-11-09T19:00:00Z',
            'PlayerName':'MainAccount','EpicId':'epic-sensitive','IsBattleRoyale':True,
            'Playlist':'Playlist_NoBuild','ChestsOpened':17,'AmmoBoxesOpened':7,'OtherContainersOpened':4,
            'Chests':[{'Kind':'Coffre enterré','Destroyed':False}]*16+[{'Kind':'Coffre rare','Destroyed':True}],
            'OtherInteractions':{'Caisse de nourriture':4,'Caisse de munitions':7},
            'LootInteractions':[{'IsChest':True,'Reopened':True}],
            'TreasureFinds':[{'Item':'Gizmo','DisplayName':'Gizmo'}],
            'TeamTreasureFinds':[{'Item':'Kollege fand etwas'}]}
        payload=match_to_payload(m,'pc0')
        self.assertEqual(payload['chests'],17)
        self.assertEqual(payload['destroyed'],1)
        self.assertEqual(payload['reopened'],1)
        self.assertEqual(payload['ammo'],7)
        self.assertEqual(payload['food'],4)
        self.assertEqual(payload['other'],0)
        self.assertEqual(payload['treasure_count'],1)
        self.assertNotIn('epic-sensitive',json.dumps(payload))
        self.assertIsNone(match_to_payload({'IsBattleRoyale':False,'PlayerName':'Other'},'pc1'))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.json'
            path.write_text(json.dumps({'Matches':[m,{**m,'SessionId':'new','PlayerName':'SecondAccount'}]}),encoding='utf-8')
            self.assertEqual(len(load_matches(path,'pc0')),2)
            self.assertEqual(fingerprint(payload),fingerprint(match_to_payload(m,'pc0')))

    def test_05_require_https_over_public(self):
        with self.assertRaisesRegex(ValueError,'HTTPS'):
            validate_url('http://loot.example.net')
        self.assertEqual(validate_url('https://loot.example.net/'),'https://loot.example.net')
        self.assertEqual(validate_url('http://10.10.10.2:8765'),'http://10.10.10.2:8765')


class VisionAlgorithmTests(unittest.TestCase):
    def test_prompt_requires_interaction_then_disappearance(self):
        from vision import SearchInteraction
        p=SearchInteraction()
        self.assertFalse(p.update(.92,False,0))
        self.assertFalse(p.update(.96,True,.4))
        self.assertFalse(p.update(.21,False,.8))
        self.assertTrue(p.update(.30,False,1.2))
        self.assertFalse(p.update(.08,False,1.4))


class CoreIntegrationTests(unittest.TestCase):
    def test_client_detects_active_replay_and_syncs_after_match(self):
        from unittest.mock import patch
        from client_core import Core, Api, save_json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            demos=home/'Demos';demos.mkdir()
            replay=demos/'Replay_123.replay';replay.write_bytes(b'replay-encrypted')
            data=home/'data.json'
            client_id='pc-testing'
            config={'client_id':client_id,'name':'ErsterAccount',
                    'server_url':'http://127.0.0.1','token':TOKEN,'data_json':str(data),'replay_dir':str(demos)}
            state={'sent':{},'replay_rounds':{}}
            class StubApi:
                def __init__(self):self.calls=[]
                def call(self,path,body=None):
                    self.calls.append((path,body))
                    if path=='/api/round/join':return {'round_id':42}
                    return {'ok':True}
            stub=StubApi()
            with patch('client_core.STATE',home/'state.json'):
                c=Core(config=config,state=state)
                c.watch_new_replay(stub)
                self.assertEqual(c.round_id,42)
                c.adjust('manual',1)
                c.send_live(stub)
                self.assertEqual(stub.calls[-1][1]['manual'],1)
                row={'SessionId':'session123','ReplayFile':'Replay_123.replay',
                     'PlayerName':'ErsterAccount','MatchStartUtc':'2026-11-09T18:40:00Z',
                     'ChestsOpened':17,'Chests':[{'Kind':'Coffre','Destroyed':False} for _ in range(17)]}
                data.write_text(json.dumps({'Matches':[row]}),encoding='utf-8')
                count=c.sync_matches(stub)
                self.assertEqual(count,1)
                self.assertEqual(stub.calls[-1][1]['round_id'],42)
                self.assertEqual(stub.calls[-1][1]['chests'],17)
                self.assertEqual(c.sync_matches(stub),0)
                # Replay re-analyzed with corrected counts; must upsert same row.
                row['ChestsOpened']=18
                data.write_text(json.dumps({'Matches':[row]}),encoding='utf-8')
                self.assertEqual(c.sync_matches(stub),1)

if __name__=="__main__":
    unittest.main(verbosity=2)
