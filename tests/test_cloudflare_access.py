import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'SquadLoot-Windows-Client'))
from client_core import Api, Core

TOKEN='unittest-supersecret-long-key-12345678'

class AccessTests(unittest.TestCase):
    def test_service_headers_sent_beside_squad_bearer(self):
        captured=[]
        def fake_urlopen(req,data=None,timeout=None):
            captured.append((dict((k.lower(),v) for k,v in req.header_items()),data,timeout))
            return io.BytesIO(b'{"ok":true}')
        client=Api('https://squadloot.megacraft.de',TOKEN,'cf-service-id','cf-service-secret')
        with patch('client_core.urllib.request.urlopen',side_effect=fake_urlopen):
            self.assertTrue(client.call('/api/state')['ok'])
        head=captured[0][0]
        self.assertEqual(head['authorization'],'Bearer '+TOKEN)
        self.assertEqual(head['cf-access-client-id'],'cf-service-id')
        self.assertEqual(head['cf-access-client-secret'],'cf-service-secret')
    def test_empty_optional_access_credentials(self):
        client=Api('https://squadloot.megacraft.de',TOKEN)
        self.assertEqual(client.cf_access_client_id,'')
        self.assertEqual(client.cf_access_client_secret,'')
    def test_only_one_access_field_rejected(self):
        with self.assertRaisesRegex(ValueError,'beide'):
            Api('https://squadloot.megacraft.de',TOKEN,'missing-secret','')
    def test_core_config_forwards_credentials(self):
        core=Core(config={'server_url':'https://squadloot.megacraft.de','token':TOKEN,'name':'Test','client_id':'one',
                          'cf_access_client_id':'CF_ID','cf_access_client_secret':'CF_SECRET'},state={'sent':{},'replay_rounds':{}})
        api=core.credentials()
        self.assertEqual(api.cf_access_client_id,'CF_ID')
        self.assertEqual(api.cf_access_client_secret,'CF_SECRET')

if __name__=='__main__': unittest.main()
