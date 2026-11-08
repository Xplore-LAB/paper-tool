import json,unittest
from unittest.mock import patch
from paper_tool import core as m

class AuthCacheTests(unittest.TestCase):
    def authorize(self, remember):
        z=object.__new__(m.ZoteroLocal); z.base=m.BASE; z.server_id='test'; z.key=''
        with patch.object(m,'request_bytes',return_value=(200,{},json.dumps({'key':'dummy','remember':remember}).encode(),'')),patch('paper_tool.auth.save') as save:
            z.authorize()
            self.assertEqual(z.key,'dummy')
            if remember:save.assert_called_once_with('test','dummy')
            else:save.assert_not_called()
    def test_persistent_grant_saved(self):self.authorize(True)
    def test_single_use_grant_not_saved(self):self.authorize(False)
    def test_cached_grant_reloaded(self):
        def connect(z):z.server_id='test'
        with patch.dict('os.environ',{'ZOTERO_LOCAL_API_KEY':''}),patch.object(m.ZoteroLocal,'_connect',connect),patch('paper_tool.auth.load',return_value='cached'):
            self.assertEqual(m.ZoteroLocal().key,'cached')
