import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import factory
from ledger_view import snapshot, server

class LedgerViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        factory.initialize_db(self.home)
        with factory.connect(self.home) as con:
            con.execute('INSERT INTO tickets(id,ticket,state,updated) VALUES(?,?,?,?)',
                        ('A',json.dumps({'title':'<script>alert(1)</script>'}),'PENDING',1))
            for n in range(7):factory.record(con,'A','PENDING',{'action':'fixture','reason':str(n)})
    def tearDown(self):self.tmp.cleanup()
    def test_cursor_has_no_gaps_and_reads_do_not_write(self):
        before=(self.home/'ledger.sqlite3').read_bytes()
        cursor=0;sequences=[]
        while True:
            data=snapshot(self.home,cursor,3);sequences += [e['sequence'] for e in data['events']]
            cursor=data['cursor']
            if not data['has_more']:break
        self.assertEqual(sequences,list(range(1,8)))
        self.assertEqual(snapshot(self.home,cursor)['events'],[])
        self.assertEqual(before,(self.home/'ledger.sqlite3').read_bytes())
    def test_missing_ledger_not_created_and_limits_rejected(self):
        with self.assertRaises(sqlite3.Error):snapshot(self.home/'absent')
        self.assertFalse((self.home/'absent').exists())
        for after,limit in [(-1,1),(0,0),(0,501)]:
            with self.assertRaises(ValueError):snapshot(self.home,after,limit)
    def test_http_snapshot_safe_origin_and_no_mutation(self):
        httpd=server(self.home,0);thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urlopen(base+'/api/snapshot?limit=2') as response:
                data=json.load(response)
                self.assertEqual(data['cursor'],2);self.assertTrue(data['has_more'])
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
            for req in [Request(base+'/',headers={'Host':'evil.example'}),
                        Request(base+'/',headers={'Origin':'https://evil.example'}),
                        Request(base+'/',headers={'Sec-Fetch-Site':'cross-site'})]:
                with self.assertRaises(HTTPError) as error:urlopen(req)
                self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/approve',data=b'{}'))
            self.assertEqual(error.exception.code,501)
            with urlopen(base+'/app.js') as response:
                js=response.read().decode();self.assertNotIn('innerHTML',js);self.assertIn('textContent',js)
        finally:httpd.shutdown();httpd.server_close();thread.join()
