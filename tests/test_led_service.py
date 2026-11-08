import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import grp

from sboc.led_service import LEDClient, valid_pixels, serve

class FakeLEDs:
    def __init__(self):
        self.available = True
        self.error = None
        self.frames = []
    def show(self, pixels):
        self.frames.append(pixels)
    def off(self):
        pass

class TestLEDService(unittest.TestCase):
    def test_pixel_validation(self):
        valid = [[[0, 10, 255, 0] for _ in range(10)] for _ in range(2)]
        self.assertTrue(valid_pixels(valid))
        self.assertFalse(valid_pixels([[[256, 0, 0, 0]] * 10] * 2))
        self.assertFalse(valid_pixels([[[0, 0, 0, 0]] * 11] * 2))
        self.assertFalse(valid_pixels({'cmd': 'show'}))
        self.assertFalse(valid_pixels([[[True, 0, 0, 0]] * 10] * 2))

    def test_socket_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'led.sock')
            # The test runs unprivileged; only the privileged ownership operation is mocked.
            with patch('sboc.led_service.LEDs', FakeLEDs), patch('sboc.led_service.os.chown') as chown:
                group = grp.getgrgid(os.getgid()).gr_name
                threading.Thread(target=serve, args=(path, group), daemon=True).start()
                client = None
                for _ in range(100):
                    if Path(path).exists():
                        client = LEDClient(path)
                        if client.available:
                            break
                    time.sleep(.01)
                self.assertIsNotNone(client, 'LED socket was not created')
                self.assertTrue(client.available, client.error)
                chown.assert_called_once_with(Path(path), 0, os.getgid())
                pixels = [[[12, 34, 56, 78] for _ in range(10)] for _ in range(2)]
                client.show(pixels)
                self.assertTrue(client.available)
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(path)
                    sock.sendall(json.dumps({'cmd':'show', 'pixels': [[[999,0,0,0]]*10]*2}).encode() + b'\n')
                    result = json.loads(sock.recv(1024))
                    self.assertFalse(result['available'])
                client.off()
                self.assertTrue(client.available)
