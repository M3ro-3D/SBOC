import http.server
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import sys

from sboc.network_policy import lan_host, lan_urlopen
from sboc.security import Store
from sboc.securelink import AgentTrust, pair, secure_request, B, U
from sboc.controller import Controller, validate
from sboc.homeassistant import inspect
from sboc.mail import send as send_mail


class TestSecurity(unittest.TestCase):
    def test_bootstrap_and_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'events.sqlite3'
            store = Store(db)
            code = store.setup_code()
            self.assertGreaterEqual(len(code), 24)
            self.assertEqual((Path(tmp)/'setup-code').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError): store.setup('admin','secure-password-123','wrong')
            store.setup('admin','secure-password-123',code)
            self.assertFalse((Path(tmp)/'setup-code').exists())
            self.assertIsNone(store.login('admin','wrong'))
            token = store.login('admin','secure-password-123')
            self.assertEqual(store.user(token),'admin')
            Store(db)
            self.assertFalse((Path(tmp)/'setup-code').exists())
            store.logout(token)
            self.assertIsNone(store.user(token))

    def test_lan_policy(self):
        for host in ('127.0.0.1','8.8.8.8','169.254.169.254','0.0.0.0','224.0.0.1','::1','fe80::1'):
            with self.subTest(host=host), self.assertRaises(ValueError): lan_host(host, 80)
        for host in ('10.0.0.2','172.16.0.1','192.168.178.10','fd00::2'):
            with self.subTest(host=host): self.assertEqual(lan_host(host,80)[1],80)
        with patch('sboc.network_policy.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.168.1.2',80)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',80))]):
            with self.assertRaises(ValueError): lan_host('mixed.example',80)

    def test_pinned_request_and_redirect(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','http://127.0.0.1/secret');self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(self.headers['Host'].encode())
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        port=server.server_port
        original=socket.getaddrinfo
        real_create_connection=socket.create_connection
        def local(name,p,*args,**kwargs):
            if name=='sboc-test.lan':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.168.1.100',p))]
            return original(name,p,*args,**kwargs)
        try:
            with patch('sboc.network_policy.socket.getaddrinfo',side_effect=local):
                with patch('sboc.network_policy.socket.create_connection',side_effect=lambda target,timeout,*args: real_create_connection(('127.0.0.1',port),timeout)):
                    with lan_urlopen(urllib.request.Request(f'http://sboc-test.lan:{port}/')) as response:
                        self.assertEqual(response.read().decode(),f'sboc-test.lan:{port}')
                    with self.assertRaises(ValueError):lan_urlopen(urllib.request.Request(f'http://sboc-test.lan:{port}/redirect'))
        finally:server.shutdown()

    def test_pairing_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            trust=AgentTrust(Path(tmp))
            code=trust.pairinfo['code']
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_POST(self):
                    data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path=='/pair/start': response=trust.start(data)
                    elif self.path=='/pair/finish':response=trust.finish(data)
                    else:
                        payload,key,nonce=trust.decrypt(data)
                        response=trust.encrypt(key,nonce,{'path':payload['path'],'metrics':{'cpu':10}})
                    body=json.dumps(response).encode()
                    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                def log_message(self,*args):pass
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            original=socket.getaddrinfo
            real_create_connection=socket.create_connection
            def local(name,p,*args,**kwargs):
                if name=='sboc-agent.lan':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.168.1.50',p))]
                return original(name,p,*args,**kwargs)
            try:
                with patch('sboc.network_policy.socket.getaddrinfo',side_effect=local):
                    with patch('sboc.network_policy.socket.create_connection',side_effect=lambda target,timeout,*args: real_create_connection(('127.0.0.1',server.server_port),timeout)):
                        identity,key=pair('sboc-agent.lan',server.server_port,code)
                        self.assertEqual(identity,trust.pairinfo['id'])
                        self.assertNotEqual(code,trust.pairinfo['code'])
                        reply=secure_request('sboc-agent.lan',server.server_port,key,'/metrics')
                        self.assertEqual(reply['metrics']['cpu'],10)
            finally:server.shutdown()

    def test_config_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=Controller(Path(tmp)/'config.json',simulate=True)
            c.running=False
            c.cfg=validate({'devices':[{'id':'ha','host':'192.168.1.3','port':8123,'type':'haos','token':'private-token'}]})
            public=c.public_config()
            self.assertNotIn('token',public['devices'][0])
            self.assertTrue(public['devices'][0]['has_token'])

    def test_mail_tls_modes(self):
        settings={'host':'smtp.example.org','port':587,'mode':'starttls','username':'user','password':'pass','sender':'from@example.org','recipient':'to@example.org'}
        calls=[]
        class FakeSMTP:
            def __init__(self,*args,**kwargs):calls.append(('connect',args,kwargs))
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def starttls(self,**kwargs):calls.append(('starttls',))
            def login(self,*args):calls.append(('login',))
            def send_message(self,*args):calls.append(('send',))
        with patch('sboc.mail.smtplib.SMTP',FakeSMTP),patch('sboc.mail.smtplib.SMTP_SSL',FakeSMTP):
            send_mail(settings,'Test','Body')
            self.assertLess(calls.index(('starttls',)),calls.index(('login',)))
            calls.clear()
            settings['mode']='ssl';settings['port']=465
            send_mail(settings,'Test','Body')
            self.assertFalse(any(c[0]=='starttls' for c in calls))
            self.assertTrue(calls[0][2].get('context'))

if __name__=='__main__':unittest.main()
