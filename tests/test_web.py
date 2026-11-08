import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

class TestWeb(unittest.TestCase):
    def test_first_setup_login_and_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            port_sock=socket.socket();port_sock.bind(('127.0.0.1',0));port=port_sock.getsockname()[1];port_sock.close()
            config=Path(tmp)/'config.json'
            proc=subprocess.Popen([sys.executable,'-m','sboc.controller','--simulate','--host','127.0.0.1','--port',str(port),'--config',str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                for _ in range(80):
                    if (Path(tmp)/'setup-code').exists():break
                    time.sleep(.05)
                code=(Path(tmp)/'setup-code').read_text().strip()
                def get(path,cookie=None):
                    con=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                    headers={'Cookie':cookie} if cookie else {}
                    con.request('GET',path,headers=headers);r=con.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;con.close();return status,data,headers
                def post(path,payload,cookie=None):
                    con=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                    headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{port}'}
                    if cookie:headers['Cookie']=cookie
                    con.request('POST',path,body=json.dumps(payload),headers=headers);r=con.getresponse();data=r.read();headers=dict(r.getheaders());status=r.status;con.close();return status,json.loads(data),headers
                for _ in range(80):
                    try:get('/');break
                    except OSError:time.sleep(.05)
                self.assertEqual(get('/api/status')[0],401)
                self.assertEqual(post('/api/setup',{'username':'admin','password':'a-strong-password','setup_code':'wrong'})[0],400)
                self.assertEqual(post('/api/setup',{'username':'admin','password':'a-strong-password','setup_code':code})[0],200)
                self.assertFalse((Path(tmp)/'setup-code').exists())
                self.assertEqual(post('/api/login',{'username':'admin','password':'bad'})[0],401)
                status,data,headers=post('/api/login',{'username':'admin','password':'a-strong-password'})
                self.assertEqual(status,200)
                cookie=headers['Set-Cookie'].split(';',1)[0]
                self.assertIn('HttpOnly',headers['Set-Cookie'])
                self.assertIn('SameSite=Strict',headers['Set-Cookie'])
                self.assertEqual(get('/api/status',cookie)[0],200)
                self.assertEqual(post('/api/logout',{},cookie)[0],200)
                self.assertEqual(get('/api/status',cookie)[0],401)
            finally:
                proc.terminate()
                try:proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.communicate()
