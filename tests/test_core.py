import json, os, tempfile, unittest, pathlib, time
from unittest.mock import patch
from sboc.controller import validate, DEFAULT, effective_brightness, Controller
from sboc.security import Store
from sboc.securelink import AgentTrust, pair, secure_request, B, U, endpoint
from sboc.network_policy import _allowed, lan_host
from sboc.led_service import valid_pixels
from sboc.agent import Collector
from sboc.mail import validate_address

class ConfigurationTests(unittest.TestCase):
    def test_defaults(self):
        c=validate({}); self.assertEqual(len(c['mapping']),10);self.assertEqual(c['operation_mode'],'both')
    def test_bad_brightness(self):
        for v in [-1,81,True,'40']:
            with self.subTest(v=v),self.assertRaises(ValueError):validate({'brightness':v})
    def test_bad_threshold(self):
        for v in [[20,20,80],[30,20,80],['a',30,40]]:
            with self.subTest(v=v),self.assertRaises(ValueError):validate({'thresholds':{'cpu':v}})
    def test_night_overrides(self):
        c=validate({'night':{'enabled':True,'start':'22:00','end':'07:00'}})
        with patch('sboc.controller.time.localtime',return_value=time.struct_time((2026,11,9,23,30,0,0,0,0))):self.assertEqual(effective_brightness(c),0)
        with patch('sboc.controller.time.localtime',return_value=time.struct_time((2026,11,9,12,30,0,0,0,0))):self.assertEqual(effective_brightness(c),50)
    def test_modes(self):
        for m in ('led','mail','both','web'):self.assertEqual(validate({'operation_mode':m})['operation_mode'],m)
    def test_invalid_device(self):
        with self.assertRaises(ValueError):validate({'devices':[{'id':'bad id','host':'192.168.1.1'}]})
    def test_mapping(self):
        c=validate({'devices':[{'id':'pi','host':'192.168.1.1'}],'mapping':[{'device':'pi','metric':'cpu'}]+[None]*9})
        self.assertEqual(c['mapping'][0]['metric'],'cpu')
    def test_pixels(self):
        p=[[[0,0,0,0] for _ in range(10)] for _ in range(2)]
        self.assertTrue(valid_pixels(p));p[0][0][0]=256;self.assertFalse(valid_pixels(p))
    def test_mail_address(self):
        validate_address('a@example.org','test')
        for a in ('not-an-address','Some Name <a@example.org>','a@example.org\r\nBcc: x@y.z'):
            with self.subTest(a=a),self.assertRaises(ValueError):validate_address(a,'test')

class SecurityTests(unittest.TestCase):
    def test_lan(self):
        for a in ('192.168.1.1','10.0.0.1','172.20.1.1','fd00::1'):self.assertTrue(_allowed(a))
        for a in ('127.0.0.1','8.8.8.8','169.254.1.1','::1'):self.assertFalse(_allowed(a))
    def test_store_bootstrap_and_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(pathlib.Path(d)/'events.sqlite3');code=s.setup_code()
            with self.assertRaises(ValueError):s.setup('tester','thisisalongpassword','wrong')
            s.setup('tester','thisisalongpassword',code)
            self.assertTrue(s.configured());self.assertFalse((pathlib.Path(d)/'setup-code').exists())
            token=s.login('tester','thisisalongpassword');self.assertEqual(s.user(token),'tester')
            s.change_password('tester','thisisalongpassword','newlongpasswordhere','newlongpasswordhere')
            self.assertIsNone(s.user(token));self.assertTrue(s.login('tester','newlongpasswordhere'))
    def test_alert_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(pathlib.Path(d)/'events.sqlite3')
            self.assertTrue(s.transition('pi','offline',True))
            a=s.alerts()[0];self.assertTrue(s.acknowledge('pi','offline',a['since']))
            self.assertFalse(s.acknowledge('pi','offline',a['since']))
            self.assertTrue(s.transition('pi','offline',False))
            self.assertEqual(len(s.events()),3)
    def test_ipv6_agent_url(self):
        self.assertEqual(endpoint("fd00::1",8765,"/secure"),"http://[fd00::1]:8765/secure")
    def test_pair_crypto_replay_and_repair(self):
        with tempfile.TemporaryDirectory() as d:
            trust=AgentTrust(d)
            def fake_request(url,obj):
                if url.endswith('/pair/start'):return trust.start(obj)
                if url.endswith('/pair/finish'):return trust.finish(obj)
                if url.endswith('/secure'):
                    req,key,nonce=trust.decrypt(obj)
                    return trust.encrypt(key,nonce,{'schema':1,'metrics':{'cpu':42}})
                raise AssertionError(url)
            with patch('sboc.securelink.request',side_effect=fake_request):
                identity,key=pair('192.168.1.2',8765,trust.pairinfo['code'])
                self.assertEqual(identity,trust.pairinfo['id'])
                self.assertEqual(secure_request('192.168.1.2',8765,key,'/metrics')['metrics']['cpu'],42)
                with self.assertRaises(ValueError):pair('192.168.1.2',8765,'000000' if trust.pairinfo['code']!='000000' else '111111')
            trust2=AgentTrust(d)
            self.assertEqual(trust2.keys['key'],B(key))

class MonitoringTests(unittest.TestCase):
    def test_collector_linux(self):
        c=Collector(); a=c.get();self.assertEqual(a['schema'],1);self.assertIn('metrics',a)
        self.assertIn('ram',a['metrics']);self.assertIn('network',a['metrics'])
    def test_mail_mode_gating(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(str(pathlib.Path(d)/'config.json'),simulate=True)
            c.running=False;c.poll_thread.join(timeout=2);c.render_thread.join(timeout=2)
            c.cfg['operation_mode']='led'
            with patch.object(c.store,'mail',side_effect=AssertionError('mail must be disabled')):c.check_mail()
            c.cfg['operation_mode']='web'
            with patch.object(c.store,'mail',side_effect=AssertionError('mail must be disabled')):c.check_mail()
    def test_brightness_scale(self):
        pixels=[[(255,255,255,255)]*10 for _ in range(2)]
        self.assertEqual(Controller.scale(pixels,100)[0][0],(204,204,204,204))
        self.assertEqual(Controller.scale(pixels,0)[0][0],(0,0,0,0))

if __name__=='__main__':unittest.main()
