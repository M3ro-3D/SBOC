"""Privileged LED-only service. No HTTP or configuration access."""
import argparse
import json
import os
import socket
from pathlib import Path
from .leds import LEDs

MAX_MESSAGE = 2048

def valid_pixels(value):
    return (type(value) is list and len(value) == 2 and
            all(type(side) is list and len(side) == 10 and
                all(type(pixel) in (list, tuple) and len(pixel) == 4 and
                    all(type(component) is int and 0 <= component <= 255 for component in pixel)
                    for pixel in side) for side in value))

def serve(path, group):
    import grp
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as check:
            try:
                check.connect(str(target))
            except (ConnectionRefusedError, FileNotFoundError):
                target.unlink()
            else:
                raise RuntimeError('LED service already running')
    leds = LEDs()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(target))
        os.chown(target, 0, grp.getgrnam(group).gr_gid)
        os.chmod(target, 0o660)
        server.listen(4)
        try:
            while True:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2)
                    try:
                        data = b''
                        while b'\n' not in data and len(data) <= MAX_MESSAGE:
                            chunk = conn.recv(1024)
                            if not chunk:
                                break
                            data += chunk
                        if len(data) > MAX_MESSAGE or b'\n' not in data:
                            raise ValueError('invalid message size')
                        obj = json.loads(data.split(b'\n', 1)[0])
                        if obj == {'cmd': 'status'}:
                            reply = {'available': leds.available, 'error': leds.error}
                        elif type(obj) is dict and obj.get('cmd') == 'show' and valid_pixels(obj.get('pixels')):
                            leds.show(obj['pixels'])
                            reply = {'available': leds.available, 'error': leds.error}
                        else:
                            raise ValueError('invalid command')
                        conn.sendall(json.dumps(reply).encode() + b'\n')
                    except (ValueError, UnicodeError, TimeoutError, OSError) as exc:
                        try:
                            conn.sendall(json.dumps({'error': str(exc), 'available': False}).encode() + b'\n')
                        except OSError:
                            pass
        finally:
            leds.off()
            target.unlink(missing_ok=True)

class LEDClient:
    def __init__(self, path='/run/sboc-led/led.sock'):
        self.path = path
        self.available = False
        self.error = 'LED-Dienst nicht erreichbar'
        self.pixels = [[(0, 0, 0, 0)] * 10 for _ in range(2)]
        self._call({'cmd': 'status'})

    def _call(self, request):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.6)
                client.connect(self.path)
                client.sendall(json.dumps(request, separators=(',', ':')).encode() + b'\n')
                response = b''
                while b'\n' not in response and len(response) < MAX_MESSAGE:
                    part = client.recv(1024)
                    if not part:
                        break
                    response += part
            result = json.loads(response.split(b'\n', 1)[0])
            self.available = bool(result.get('available'))
            self.error = result.get('error')
        except (OSError, ValueError, TypeError) as exc:
            self.available = False
            self.error = 'LED-Dienst nicht erreichbar: ' + str(exc)

    def show(self, pixels):
        if not valid_pixels(pixels):
            raise ValueError('Ungültige LED-Daten')
        self.pixels = [list(side) for side in pixels]
        self._call({'cmd': 'show', 'pixels': pixels})

    def off(self):
        self.show([[(0, 0, 0, 0)] * 10 for _ in range(2)])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', default='/run/sboc-led/led.sock')
    parser.add_argument('--group', default='sboc-web')
    args = parser.parse_args()
    serve(args.socket, args.group)

if __name__ == '__main__':
    main()
