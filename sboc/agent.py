"""Low-overhead Linux telemetry endpoint. No third-party dependencies."""
import argparse, json, os, platform, socket, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from pathlib import Path
from . import monitoring
from .securelink import AgentTrust

class Collector:
    def __init__(self):
        self.last = None
        self.net_last = None
        self.services = monitoring.snapshot_services()
        self.containers = monitoring.snapshot_containers()
        self.oom_count = 0
        self.oom_since = int((time.time()-60)*1000000)
        self.watch_services = []
        self.watch_containers = []
    def cpu(self):
        try:
            fields = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
            total, idle = sum(fields), fields[3] + (fields[4] if len(fields)>4 else 0)
            previous = self.last; self.last = (total, idle)
            if previous and total>previous[0]: return round(100*(1-(idle-previous[1])/(total-previous[0])), 1)
        except (OSError, ValueError, IndexError): pass
        return None
    def ram(self):
        try:
            d = {}
            for line in Path('/proc/meminfo').read_text().splitlines():
                k, _, v = line.partition(':'); d[k] = int(v.strip().split()[0])
            return round(100*(1-d['MemAvailable']/d['MemTotal']),1)
        except (OSError, ValueError, KeyError, IndexError): return None
    def temperature(self):
        try:
            for p in sorted(Path('/sys/class/thermal').glob('thermal_zone*/temp')):
                try:
                    t = float(p.read_text().strip()); t = t/1000 if abs(t)>1000 else t
                    if -20 <= t <= 130: return round(t,1)
                except (OSError,ValueError): continue
        except OSError: pass
        return None
    def disk(self):
        try:
            v=os.statvfs('/'); return round(100*(1-v.f_bavail/v.f_blocks),1) if v.f_blocks else None
        except OSError: return None
    def uptime(self):
        try: return int(float(Path('/proc/uptime').read_text().split()[0]))
        except (OSError, ValueError, IndexError): return None
    def network(self):
        """Physical network throughput (Ethernet and WLAN), KiB/s.

        Excludes loopback and virtual interfaces to avoid counting bridged
        traffic twice. Rate is unavailable until the second observation.
        """
        try:
            totals={}
            for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
                name,sep,rest=line.partition(':')
                name=name.strip()
                if not sep or name=='lo': continue
                interface=Path('/sys/class/net')/name
                # Real interfaces have a backing device; veth, bridges,
                # tunnels and virtual adapters generally do not.
                if not (interface/'device').exists(): continue
                fields=rest.split()
                totals[name]=(int(fields[0]),int(fields[8]))
            now=time.monotonic()
            previous=self.net_last
            self.net_last=(now,totals)
            if previous is None or now<=previous[0] or not totals: return None
            elapsed=now-previous[0]
            rx=tx=0
            for name,(received,sent) in totals.items():
                if name not in previous[1]: continue
                old_rx,old_tx=previous[1][name]
                if received>=old_rx: rx+=received-old_rx
                if sent>=old_tx: tx+=sent-old_tx
            return round((rx+tx)/elapsed/1024,1)
        except (OSError,ValueError,IndexError): return None
    def get(self):
        flags=monitoring.pi_flags()
        count,self.oom_since=monitoring.journal_oom(self.oom_since)
        if count is not None: self.oom_count += count
        services={n:monitoring.service_state(n) for n in self.watch_services if self.services is not None and n in self.services}
        containers={f'{r}:{n}':monitoring.container_state(r,n) for r,n in self.watch_containers if n in self.containers.get(r,[])}
        return {'schema':1,'host':socket.gethostname(),'platform':platform.machine(),
                'timestamp':int(time.time()),'metrics':{'cpu':self.cpu(),'temperature':self.temperature(),
                'ram':self.ram(),'disk':self.disk(),'network':self.network(),'uptime':self.uptime(),
                'throttling':flags['throttling'],'undervoltage':flags['undervoltage'],
                'filesystem_ro':monitoring.filesystem_readonly(),'oom_count':self.oom_count},
                'services':services,'containers':containers}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--host',default='0.0.0.0'); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--pairing-code',action='store_true'); parser.add_argument('--trust-dir',default='/var/lib/sboc-agent')
    args=parser.parse_args(); trust=AgentTrust(args.trust_dir)
    if args.pairing_code:
        print('SBOC. Kopplungscode:',trust.pairinfo['code']); return
    collector=Collector(); collector.started=int(time.time())
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlparse(self.path).path
            if path in ('/metrics','/catalog'):
                self.send_error(403,'Kopplung erforderlich');return
            self.send_error(404);return
        def do_POST(self):
            path=urlparse(self.path).path
            if path not in ('/pair/start','/pair/finish','/secure'):self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=10000:raise ValueError('Ungültige Anfragegröße')
                obj=json.loads(self.rfile.read(length))
                if path=='/pair/start':result=trust.start(obj)
                elif path=='/pair/finish':result=trust.finish(obj)
                else:
                    req,key,nonce=trust.decrypt(obj)
                    if req['path']=='/catalog':
                        payload={'services':collector.services,'containers':collector.containers,'captured_at':collector.started}
                    else:
                        q=req.get('query',{})
                        collector.watch_services=[n for n in q.get('service',[]) if n in (collector.services or [])][:40]
                        collector.watch_containers=[tuple(v.split(':',1)) for v in q.get('container',[]) if ':' in v][:40]
                        payload=collector.get()
                    result=trust.encrypt(key,nonce,payload)
                data=json.dumps(result).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            except (ValueError,KeyError,TypeError,PermissionError) as e:self.send_error(403,'Ungültige oder nicht autorisierte Anfrage')
            except Exception:self.send_error(500,'Interner Fehler')
        def log_message(self,*args): pass
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=='__main__': main()
