import tempfile, unittest, pathlib, json, time
from unittest.mock import patch
from sboc.controller import Controller, validate
from sboc.homeassistant import read_metrics
from sboc.leds import LEDs
from sboc.security import Store

class Regression(unittest.TestCase):
    def test_existing_config_survives_update_and_ha_token_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=validate({'devices':[{'id':'ha','host':'192.168.1.2','type':'haos','token':'private-token'}]})
            path=pathlib.Path(d)/'config.json';path.write_text(json.dumps(cfg))
            c=Controller(path,simulate=True);c.running=False;c.poll_thread.join(timeout=2);c.render_thread.join(timeout=2)
            self.assertNotIn('token',c.public_config()['devices'][0])
            public=c.public_config();public['brightness']=67
            c.update(public)
            self.assertEqual(c.cfg['devices'][0]['token'],'private-token')
            self.assertEqual(c.cfg['brightness'],67)
            self.assertEqual(json.loads(path.read_text())['devices'][0]['token'],'private-token')
    def test_no_smtp_when_led_only(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(str(pathlib.Path(d)/'config.json'),simulate=True);c.running=False;c.poll_thread.join(timeout=2);c.render_thread.join(timeout=2)
            c.cfg['operation_mode']='led'
            c.store.transition('pi','offline',True)
            c.store.set_mail({'enabled':True,'host':'smtp.example','sender':'a@example.org','recipient':'b@example.org','delay':0})
            with patch('sboc.controller.send_mail',side_effect=AssertionError('must not send')):c.check_mail()
    def test_silent_and_night_modes_do_not_suppress_alarm_or_recovery_mail(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(str(pathlib.Path(d)/'config.json'),simulate=True)
            c.running=False
            c.poll_thread.join(timeout=2)
            c.render_thread.join(timeout=2)
            c.cfg['operation_mode']='both'
            c.cfg['silent']={'enabled':True,'delay':3600}
            c.cfg['night']={'enabled':True,'start':'00:00','end':'23:59'}
            c.store.set_mail({'enabled':True,'host':'smtp.example','sender':'a@example.org',
                              'recipient':'b@example.org','delay':0,'recovery':True})
            c.store.transition('pi','offline',True)
            with patch('sboc.controller.send_mail') as send:
                c.check_mail()
                self.assertEqual(send.call_count,1)
                self.assertIn('Warnung',send.call_args.args[1])
                c.store.transition('pi','offline',False)
                c.check_mail()
                self.assertEqual(send.call_count,2)
                self.assertIn('Entwarnung',send.call_args.args[1])

    def test_mail_only_mode_ignores_silent(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(str(pathlib.Path(d)/'config.json'),simulate=True)
            c.running=False
            c.poll_thread.join(timeout=2)
            c.render_thread.join(timeout=2)
            c.cfg['operation_mode']='mail'
            c.cfg['silent']={'enabled':True,'delay':3600}
            c.store.set_mail({'enabled':True,'host':'smtp.example','sender':'a@example.org',
                              'recipient':'b@example.org','delay':0,'recovery':True})
            c.store.transition('pi','offline',True)
            with patch('sboc.controller.send_mail') as send:
                c.check_mail()
                send.assert_called_once()

    def test_led_off_in_simulation(self):
        led=LEDs(enabled=False)
        led.show([[(255,0,0,0)]*10 for _ in range(2)])
        led.off()
        self.assertTrue(all(all(c==0 for c in pixel) for side in led.pixels for pixel in side))
    def test_service_catalog_startup_only(self):
        from sboc.agent import Collector
        with patch('sboc.monitoring.snapshot_services',return_value=['ssh.service']),patch('sboc.monitoring.snapshot_containers',return_value={'docker':['app']}):
            c=Collector()
        self.assertEqual(c.services,['ssh.service']);self.assertEqual(c.containers['docker'],['app'])

if __name__=='__main__':unittest.main()
