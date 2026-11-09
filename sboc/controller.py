from . import __version__ as APP_VERSION
"""SBOC.: polling, LED rendering and small local web interface."""
import argparse, colorsys, copy, json, math, os, re, socket, subprocess, threading, time, secrets, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse
from .common import read_json, write_json
from .leds import LEDs
from .led_service import LEDClient
from .security import Store
from .mail import send as send_mail, mail_error, validate_address
from .securelink import pair as pair_agent, secure_request, B, U
from .homeassistant import read_metrics as read_ha_metrics, inspect as inspect_ha
from .network_policy import lan_host

DEFAULT={'enabled':True,'brightness':50,'night':{'enabled':False,'start':'22:00','end':'07:00','brightness':0},
         'interval':60,'failures':3,'devices':[], 'mapping':[None for _ in range(10)],
         'thresholds':{'temperature':[40,50,60],'cpu':[20,50,80],'ram':[20,50,80],'disk':[60,80,95],'network':[100,1000,10000],'network':[100,1000,10000]},
         'operation_mode':'both', 'operation_mode':'both', 'led_reverse':[False,False], 'led_swap':False, 'device_colors':{}, 'test_effect':'orientation',
         'status_colors':['#0000FF','#00FF00','#FFA000','#FF0000'], 'silent':{'enabled':False,'delay':60}, 'overrides':{}, 'watches':{}, 'setup_complete':False, 'setup_step':0}
COLORS=[(0,0,255,0),(0,255,0,0),(255,160,0,0),(255,0,0,0)]
METRICS=('temperature','cpu','ram','disk','network')
ALERTS=('throttling','undervoltage','filesystem_ro','oom','offline')
DUMMY='__static__'
EFFECTS=('reactor','rainbow','comet','scanner','breathing','sparkle','meteor','dual_chase','orientation')

def validate(obj):
    if not isinstance(obj,dict): raise ValueError('Expected JSON object')
    cfg=copy.deepcopy(DEFAULT)
    if not isinstance(obj.get('enabled',True),bool): raise ValueError('enabled must be boolean')
    cfg['enabled']=obj.get('enabled',True)
    for key,lo,hi in [('brightness',0,80),('interval',10,3600),('failures',1,30)]:
        v=obj.get(key,cfg[key]);
        if type(v)!=int or not lo<=v<=hi: raise ValueError(f'{key}: must be {lo}..{hi}')
        cfg[key]=v
    night=obj.get('night',cfg['night'])
    if not isinstance(night,dict): raise ValueError('night must be object')
    if not isinstance(night.get('enabled',False),bool): raise ValueError('night enabled must be boolean')
    cfg['night']['enabled']=night.get('enabled',False)
    for key in ('start','end'):
        v=night.get(key,cfg['night'][key]);
        if not isinstance(v,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v): raise ValueError('night times must be HH:MM')
        cfg['night'][key]=v
    nb=night.get('brightness',0)
    if type(nb)!=int or not 0<=nb<=80: raise ValueError('night brightness 0..80')
    cfg['night']['brightness']=nb
    mode=obj.get('operation_mode','both')
    if mode not in ('led','mail','both','web'): raise ValueError('invalid operation mode')
    cfg['operation_mode']=mode
    mode=obj.get('operation_mode','both')
    if mode not in ('led','mail','both','web'): raise ValueError('invalid operation mode')
    cfg['operation_mode']=mode
    devices=obj.get('devices',[])
    if not isinstance(devices,list) or len(devices)>100: raise ValueError('invalid devices')
    ids=set()
    for dev in devices:
        if not isinstance(dev,dict): raise ValueError('invalid device')
        ident=dev.get('id'); host=dev.get('host')
        if not isinstance(ident,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,48}',ident) or ident in ids: raise ValueError('invalid or duplicate device id')
        if not isinstance(host,str) or not re.fullmatch(r'[a-zA-Z0-9.:-]{1,253}',host): raise ValueError('invalid hostname')
        kind=dev.get('type','agent')
        if kind not in ('agent','haos'): raise ValueError('Ungültiger Gerätetyp')
        port=dev.get('port',8123 if kind=='haos' else 8765)
        if type(port)!=int or not 1<=port<=65535: raise ValueError('invalid port')
        entry={'id':ident,'host':host,'port':port,'type':kind}
        if kind=='agent':
            identity=dev.get('agent_identity','')
            if not isinstance(identity,str) or (identity and not re.fullmatch(r'[0-9a-f]{32}',identity)):raise ValueError('Ungültige Agent-Identität')
            entry['agent_identity']=identity
        if kind=='haos':
            scheme=dev.get('scheme','http')
            if scheme not in ('http','https'): raise ValueError('Ungültiges HA-Protokoll')
            entry['scheme']=scheme
        if kind=='haos':
            token=dev.get('token','')
            if not isinstance(token,str) or len(token)>2048: raise ValueError('Ungültiger HA-Token')
            entities=dev.get('entities',{})
            if not isinstance(entities,dict): raise ValueError('Ungültige HA-Sensoren')
            entry['token']=token
            entry['entities']={}
            for metric in METRICS:
                entity=entities.get(metric,'')
                if not isinstance(entity,str) or (entity and not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+',entity)): raise ValueError('Ungültige Entity-ID für '+metric)
                entry['entities'][metric]=entity
        ids.add(ident); cfg['devices'].append(entry)
    raw_colors=obj.get('device_colors',{})
    if not isinstance(raw_colors,dict): raise ValueError('invalid device colors')
    for ident,color in raw_colors.items():
        if ident not in ids or not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('invalid device color')
        cfg['device_colors'][ident]=color.upper()
    mapping=obj.get('mapping',cfg['mapping'])
    if not isinstance(mapping,list) or len(mapping)!=10: raise ValueError('mapping must have 10 rows')
    cfg['mapping']=[]
    for row in mapping:
        if isinstance(row,list) and len(row)==2:
            left,right=row
            device=(left or right or {}).get('device') if isinstance(left or right,dict) else None
            metric=(right or left or {}).get('metric') if isinstance(right or left,dict) else None
            row={'device':device,'metric':metric,'color':'#56c5ee'} if device else None
        if row is None:
            cfg['mapping'].append(None);continue
        if not isinstance(row,dict) or row.get('device') not in (ids | {DUMMY}) or row.get('metric') not in (*METRICS,'static'): raise ValueError('invalid row assignment')
        color=row.get('color','#56c5ee')
        status_color=row.get('status_color',color)
        if not isinstance(status_color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',status_color): raise ValueError('invalid status color')
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('invalid row color')
        # Migration: a legacy per-row color becomes the device's global color.
        # First assigned row wins if old rows had conflicting colors.
        if row['device']!=DUMMY and row['device'] not in cfg['device_colors']:
            cfg['device_colors'][row['device']]=color.upper()
        left_device=row.get('left_device',row['device']); right_device=row.get('right_device',row['device'])
        if left_device not in (ids | {DUMMY}) or right_device not in (ids | {DUMMY}): raise ValueError('invalid side device')
        cfg['mapping'].append({'device':row['device'],'left_device':left_device,'right_device':right_device,'metric':row['metric'],'color':color.upper(),'status_color':status_color.upper(),'right_off':bool(row.get('right_off',False))})
    for ident in ids: cfg['device_colors'].setdefault(ident,'#56C5EE')
    thresholds=obj.get('thresholds',cfg['thresholds'])
    if not isinstance(thresholds,dict): raise ValueError('invalid thresholds')
    for metric in METRICS:
        values=thresholds.get(metric,cfg['thresholds'][metric])
        if not isinstance(values,list) or len(values)!=3 or any(type(x) not in (int,float) for x in values) or not values[0]<values[1]<values[2]: raise ValueError('invalid thresholds for '+metric)
        cfg['thresholds'][metric]=values
    palette=obj.get('status_colors',cfg['status_colors'])
    if not isinstance(palette,list) or len(palette)!=4 or any(not isinstance(c,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',c) for c in palette): raise ValueError('Ungültige Statusfarben')
    cfg['status_colors']=[c.upper() for c in palette]
    reverse=obj.get('led_reverse',[False,False])
    if not isinstance(reverse,list) or len(reverse)!=2 or any(type(v)!=bool for v in reverse): raise ValueError('led_reverse must be two booleans')
    cfg['led_reverse']=reverse
    if type(obj.get('led_swap',False)) is not bool: raise ValueError('led_swap must be boolean')
    cfg['led_swap']=obj.get('led_swap',False)
    effect=obj.get('test_effect','orientation')
    if effect not in EFFECTS: raise ValueError('invalid test effect')
    cfg['test_effect']=effect
    silent=obj.get('silent',cfg['silent'])
    if not isinstance(silent,dict) or type(silent.get('enabled',False))!=bool or type(silent.get('delay',60))!=int or not 0<=silent.get('delay',60)<=3600: raise ValueError('Silent-Modus ungültig')
    cfg['silent']={'enabled':silent.get('enabled',False),'delay':silent.get('delay',60)}
    watches=obj.get('watches',{})
    if not isinstance(watches,dict): raise ValueError('Ungültige Überwachungen')
    for ident,watch in watches.items():
        if ident not in ids or not isinstance(watch,dict): raise ValueError('Ungültige Geräteüberwachung')
        services=watch.get('services',[]); containers=watch.get('containers',[])
        if not isinstance(services,list) or not isinstance(containers,list) or len(services)>40 or len(containers)>40: raise ValueError('Zu viele Dienste/Container')
        if any(not isinstance(x,str) or not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,180}\.service',x) for x in services): raise ValueError('Ungültiger Dienstname')
        if any(not isinstance(x,str) or not re.fullmatch(r'(docker|podman):[a-zA-Z0-9_.-]{1,180}',x) for x in containers): raise ValueError('Ungültiger Containername')
        cfg['watches'][ident]={'services':services,'containers':containers}
    overrides=obj.get('overrides',{})
    if not isinstance(overrides,dict): raise ValueError('Ungültige Übersteuerungen')
    for index,override in overrides.items():
        if str(index) not in map(str,range(10)) or not isinstance(override,dict): raise ValueError('Ungültige Übersteuerung')
        kind=override.get('kind','none'); effect=override.get('effect','pulse'); color=override.get('color','#FF3030')
        if kind not in (*ALERTS,'none') and not (isinstance(kind,str) and (kind.startswith('service:') or kind.startswith('container:'))): raise ValueError('Ungültiger Warnungstyp')
        if effect not in ('static','pulse','blink') or not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('Ungültiger Warneffekt')
        cfg['overrides'][str(index)]={'kind':kind,'effect':effect,'color':color.upper()}
    if type(obj.get('setup_complete',False)) is not bool: raise ValueError('Ungültiger Einrichtungsstatus')
    cfg['setup_complete']=obj.get('setup_complete',False)
    step=obj.get('setup_step',0)
    if type(step) is not int or not 0<=step<=4: raise ValueError('Ungültiger Einrichtungsschritt')
    cfg['setup_step']=step
    return cfg

def effective_brightness(cfg,now=None):
    if not cfg['enabled']: return 0
    result=cfg['brightness']; n=cfg['night']
    if not n['enabled']: return result
    current=time.strftime('%H:%M',time.localtime(now))
    start,end=n['start'],n['end']
    active=(start<=current<end) if start<end else (current>=start or current<end) if start>end else True
    return 0 if active else result

def discovery():
    # New and legacy agents may coexist during a rolling upgrade.
    result=[]
    for service_type in ('_sboc._tcp', '_spoc._tcp', '_sbc-monitor._tcp'):
        try:
            p=subprocess.run(['avahi-browse','-rtp',service_type],capture_output=True,text=True,timeout=4,check=False)
            for line in p.stdout.splitlines():
                parts=line.split(';')
                if len(parts)>8 and parts[0]=='=' and parts[2]=='IPv4':
                    result.append({'name':parts[3],'host':parts[7],'port':int(parts[8])})
        except (OSError,ValueError,subprocess.TimeoutExpired):
            continue
    unique={}
    for d in result:
        key=(d['host'],d['port'])
        unique[key]=d
    return list(unique.values())

class Controller:
    def __init__(self,path,simulate=False):
        self.path=Path(path); self.cfg=validate(read_json(path,DEFAULT)); self.lock=threading.RLock()
        self.trust_path=self.path.parent/'agent-trust.json'; self.agent_keys=read_json(self.trust_path,{}); self.store=Store(self.path.parent/'events.sqlite3'); self.catalogs={}; self.oom_seen={}; self.active_since={}; self.last_mail_check=0
        self.leds=LEDs(enabled=False) if simulate else LEDClient(); self.data={}; self.failed={}; self.last_poll=0
        self.test_started=None; self.test_effect=None; self.test_orientation=None; self.running=True
        threading.Thread(target=self.poll_loop,daemon=True).start()
        threading.Thread(target=self.render_loop,daemon=True).start()
    def pair(self,obj):
        host=obj.get('host','');port=obj.get('port',8765)
        if not isinstance(host,str) or not re.fullmatch(r'[a-zA-Z0-9.:-]{1,253}',host) or type(port)!=int or not 1<=port<=65535:raise ValueError('Ungültiger Agent-Host')
        lan_host(host,port)
        ident,key=pair_agent(host,port,obj.get('code',''))
        with self.lock:
            self.agent_keys[ident]=B(key)
            write_json(self.trust_path,self.agent_keys)
        return ident
    def public_config(self):
        with self.lock:
            cfg=copy.deepcopy(self.cfg)
            for d in cfg['devices']:
                if d.get('type')=='haos':d.pop('token',None);d['has_token']=bool(next((x.get('token') for x in self.cfg['devices'] if x['id']==d['id']),''))
            return cfg
    def update(self,obj):
        if not isinstance(obj,dict):raise ValueError('Ungültige Konfiguration')
        obj=copy.deepcopy(obj)
        with self.lock:
            old={d['id']:d for d in self.cfg['devices']}
            for d in obj.get('devices',[]):
                if d.get('type')=='haos' and not d.get('token') and d.get('id') in old and old[d['id']].get('type')=='haos':
                    d['token']=old[d['id']].get('token','')
        cfg=validate(obj)
        with self.lock:
            write_json(self.path,cfg); self.cfg=cfg
    def poll_loop(self):
        while self.running:
            with self.lock: devices=list(self.cfg['devices']); interval=self.cfg['interval']
            for d in devices:
                try:
                    if d.get('type')=='haos':
                        payload=read_ha_metrics(d)
                    else:
                        watch=self.cfg.get('watches',{}).get(d['id'],{})
                        query=urllib.parse.urlencode([('service',x) for x in watch.get('services',[])]+[('container',x) for x in watch.get('containers',[])])
                        key=self.agent_keys.get(d.get('agent_identity',''))
                        if not key:raise ValueError('Agent nicht gekoppelt')
                        payload=secure_request(d['host'],d['port'],U(key),'/metrics',{'service':watch.get('services',[]),'container':watch.get('containers',[])})
                    if payload.get('schema')!=1 or not isinstance(payload.get('metrics'),dict): raise ValueError('Invalid agent payload')
                    with self.lock: self.data[d['id']]=payload; self.failed[d['id']]=0
                    self.observe(d['id'],payload)
                except (OSError,ValueError,KeyError):
                    with self.lock:
                        self.failed[d['id']]=self.failed.get(d['id'],0)+1
                        if self.failed[d['id']]>=self.cfg['failures']: self.store.transition(d['id'],'offline',True)
            with self.lock: self.last_poll=int(time.time())
            self.check_mail()
            for _ in range(interval*10):
                if not self.running: return
                time.sleep(.1)
    def observe(self,device,payload):
        metrics=payload.get('metrics',{})
        self.store.transition(device,'offline',False)
        for kind in ('throttling','undervoltage','filesystem_ro'):
            if type(metrics.get(kind)) is bool: self.store.transition(device,kind,metrics[kind])
        oom=metrics.get('oom_count')
        if type(oom)==int:
            prior=self.oom_seen.get(device)
            if prior is not None and oom>prior:
                self.store.transition(device,'oom',True,f'{oom-prior} OOM-Ereignis(se)')
                self.active_since[(device,'oom')]=time.time()+max(120,self.cfg['silent']['delay']+self.cfg['interval']+5)
            self.oom_seen[device]=oom
            if self.active_since.get((device,'oom'),float('inf'))<time.time():
                self.store.transition(device,'oom',False)
                self.active_since.pop((device,'oom'),None)
        for name,state in payload.get('services',{}).items():
            if state is not None: self.store.transition(device,'service:'+name,state!='active')
        for name,state in payload.get('containers',{}).items():
            if state is not None: self.store.transition(device,'container:'+name,state is False)
    def check_mail(self):
        settings=self.store.mail()
        if not settings.get('enabled'): return
        for alert in self.store.alerts():
            if alert['active']:
                if alert['notified'] or time.time()-alert['since']<settings.get('delay',60): continue
            elif not settings.get('recovery',True) or alert['notified']!=-1: continue
            try:
                send_mail(settings,('SBOC.: ' + ('Warnung: ' if alert['active'] else 'Entwarnung: ')+alert['kind']+' auf '+alert['device']),f"Gerät: {alert['device']}\nStörung: {alert['kind']}\nZeitpunkt: {time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(alert['since']))}")
                self.store.notified(alert['device'],alert['kind'])
            except Exception as exc: print('SMTP-Versand fehlgeschlagen:',str(exc),flush=True)
    def active_alarm_rows(self):
        with self.lock:
            cfg=copy.deepcopy(self.cfg)
        result=[]
        for alarm in self.store.alerts():
            if not alarm['active']: continue
            rows=[i+1 for i,item in enumerate(cfg['mapping']) if item and alarm['device'] in (item['left_device'],item['right_device'])]
            result.append(dict(alarm,rows=rows,silent_trigger=bool(cfg['silent']['enabled'] and rows and not alarm['acknowledged'] and time.time()-alarm['since']>=cfg['silent']['delay'])))
        return result
    def critical(self,device,delay):
        now=time.time()
        for a in self.store.alerts():
            if a['device']==device and a['active'] and not a['acknowledged'] and now-a['since']>=delay: return True
        return False
    def test_pixels(self, elapsed, effect='reactor'):
        """All effects operate on logical rows, so the two sides remain synchronized."""
        def hsv(h, saturation=1.0, value=1.0):
            r,g,b=colorsys.hsv_to_rgb(h % 1.0, saturation, max(0.0,min(1.0,value)))
            return (round(255*r),round(255*g),round(255*b),0)
        rows=[]
        for row in range(10):
            distance=min(abs(row-4),abs(row-5))
            if effect=='reactor':
                wave=elapsed % 2.25
                front=wave/.29
                intensity=math.exp(-1.15*max(0,front-distance)) if front>=distance else 0
                c=hsv((int(elapsed/2.25)%12)/12,0.85,intensity)
            elif effect=='rainbow':
                c=hsv(elapsed*.085+row/10)
            elif effect=='comet':
                pos=(elapsed*3.0)%14-2
                gap=(pos-row)%14
                c=hsv(elapsed*.065,0.8,math.exp(-.75*gap) if gap<9 else 0)
            elif effect=='scanner':
                pos=abs((elapsed*3.0)%18-9)
                c=hsv(.52,0.9,math.exp(-1.0*abs(row-pos)))
            elif effect=='breathing':
                intensity=.04+.96*(.5-.5*math.cos(elapsed*2*math.pi/3.8))
                c=hsv(elapsed*.045,.9,intensity)
            elif effect=='sparkle':
                # Deterministic twinkles, smoothly rising/fading without random state.
                tick=int(elapsed*5)
                best=0.0
                for t in range(max(0,tick-5),tick+1):
                    position=(t*7+3)%10
                    if position==row:
                        age=elapsed-t/5
                        best=max(best,math.exp(-age*3.0)*max(0,min(1,age*15)))
                c=hsv(.58+row*.022,.6,best)
            elif effect=='meteor':
                # Two inward-moving tails, meeting at the middle.
                front=(elapsed*2.5)%7
                gap=distance-front
                intensity=math.exp(-1.1*abs(gap)) if gap>=-3 else 0
                c=hsv(.06+elapsed*.045,.95,intensity)
            elif effect=='dual_chase':
                pos=(elapsed*2.8)%10
                gap=min((row-pos)%10,(pos-row)%10)
                c=hsv(elapsed*.11+row*.02,.9,math.exp(-1.4*gap))
            elif effect=='orientation':
                c=(0,0,0,0)
            else:
                c=(0,0,0,0)
            rows.append(c)
        if effect=='orientation':
            left=[(0,0,0,0) for _ in range(10)];right=left.copy()
            left[0]=(0,255,0,0);right[0]=(255,0,0,0)
            return [left,right]
        return [[rows[row] for row in range(10)] for _ in range(2)]
    def render_loop(self):
        while self.running:
            with self.lock:
                cfg=copy.deepcopy(self.cfg); data=copy.deepcopy(self.data); failed=dict(self.failed); started=self.test_started; test_effect=self.test_effect; test_orientation=self.test_orientation
            b=effective_brightness(cfg) if cfg['operation_mode'] in ('led','both') else 0 if cfg['operation_mode'] in ('led','both') else 0
            if started is not None:
                pixels=self.test_pixels(time.monotonic()-started,test_effect or cfg['test_effect'])
                wiring=test_orientation or {'swap':cfg['led_swap'],'reverse':cfg['led_reverse']}
                if wiring['swap']: pixels.reverse()
                pixels=[[side[9-i if wiring['reverse'][index] else i] for i in range(10)] for index,side in enumerate(pixels)]
                # A manual OFF remains authoritative even during test.
                self.leds.show(self.scale(pixels,b)); time.sleep(.04); continue
            pixels=[[(0,0,0,0) for _ in range(10)] for _ in range(2)]
            for row,item in enumerate(cfg['mapping']):
                if item is None: continue
                device=item['right_device']; left_device=item['left_device']; metric=item['metric']
                if cfg['silent']['enabled'] and not any(self.critical(d,cfg['silent']['delay']) for d in (device,left_device) if d!=DUMMY): continue
                h=item['color'] if left_device==DUMMY else cfg['device_colors'].get(left_device,'#56C5EE'); left=tuple(int(h[i:i+2],16) for i in (1,3,5))+(0,)
                value=data.get(device,{}).get('metrics',{}).get(metric)
                if metric=='static':
                    h=item['status_color']; right=tuple(int(h[i:i+2],16) for i in (1,3,5))+(0,)
                elif device==DUMMY: right=(0,0,0,0)
                elif failed.get(device,0)>=cfg['failures']:
                    right=(255,0,0,0) if int(time.monotonic()*2)%2==0 else (0,0,0,0)
                elif not isinstance(value,(int,float)) or isinstance(value,bool): right=(0,0,0,0)
                else:
                    t=cfg['thresholds'][metric]; h=cfg['status_colors'][sum(value>=x for x in t)]; right=tuple(int(h[i:i+2],16) for i in (1,3,5))+(0,)
                if item.get('right_off'): right=(0,0,0,0)
                override=cfg['overrides'].get(str(row),{})
                kind=override.get('kind','none')
                if device!=DUMMY and not item.get('right_off') and kind!='none':
                    alert=next((a for a in self.store.alerts() if a['device']==device and a['kind']==kind and a['active']),None)
                    if alert:
                        h=override['color']; base=tuple(int(h[i:i+2],16) for i in (1,3,5))+(0,)
                        effect=override['effect']; phase=time.monotonic()
                        factor=1 if effect=='static' else (0.12+0.88*(0.5+0.5*math.sin(phase*2.5))) if effect=='pulse' else (1 if int(phase*2)%2==0 else 0)
                        right=tuple(int(x*factor) for x in base)
                for side,color in enumerate((left,right)):
                    physical=1-side if cfg['led_swap'] else side
                    pos=9-row if cfg['led_reverse'][physical] else row
                    pixels[physical][pos]=color
            self.leds.show(self.scale(pixels,b)); time.sleep(.1)
    @staticmethod
    def scale(pixels,brightness):
        # brightness is capped at 80% of full PWM
        factor=min(max(brightness,0),80)/100
        return [[tuple(max(0,min(255,round(c*factor))) for c in p) for p in side] for side in pixels]
    def status(self):
        with self.lock:
            return {'config':self.public_config(),'metrics':copy.deepcopy(self.data),'failed':dict(self.failed),
                    'last_poll':self.last_poll,'led_available':self.leds.available,'led_error':self.leds.error,
                    'test_running':self.test_started is not None,'configured':self.store.configured(),'active_alarms':self.active_alarm_rows()}

HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SBOC.</title><link rel="icon" type="image/png" href="/assets/m3ro-favicon.png"><style>
:root{--bg:#f7f7f3;--ink:#111;--line:#999999;--inner-line:#dddddd;--muted:#62625d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px system-ui,sans-serif}header{background:white;border-bottom:1px solid var(--line);position:relative;z-index:5}.head{max-width:1150px;margin:auto;padding:15px 22px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}.brand{font-weight:800;font-size:25px;margin-right:auto}.brand small{font-size:12px;font-weight:400;color:var(--muted)}button,input,select{font:inherit}button{background:#111;color:white;border:1px solid #111;padding:10px 15px;cursor:pointer;font-weight:600}button.secondary{background:white;color:#111}button:disabled{opacity:.4}input,select{border:1px solid #aaa;padding:10px;max-width:100%;background:white;color:#111}input[type=color]{width:56px;height:40px;padding:3px}input[type=range]{accent-color:#111}nav{display:flex;gap:10px;max-width:1150px;margin:auto;padding:0 22px}nav button{background:transparent;color:#555;border:0;border-bottom:3px solid transparent}nav button.active{color:#111;border-bottom-color:var(--flow-line)}main{max-width:1150px;margin:30px auto;padding:0 22px 90px}.page{display:none}.page.active{display:block}h1{font-size:30px;margin:0 0 8px}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:12px 0}.muted{color:var(--muted);line-height:1.5}[hidden]{display:none!important}section{background:white;border:1px solid var(--line);padding:24px;margin:22px 0;scroll-margin-top:125px}.row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600}.field input,.field select{min-width:140px}.device-row{display:flex;align-items:center;gap:15px;justify-content:space-between;border-bottom:1px solid #ddd;padding:13px 0;flex-wrap:wrap}.device-row:last-child{border:0}.device-info{flex:1;min-width:180px}.device-info small{display:block;color:var(--muted);margin-top:5px}.steps{position:fixed;right:16px;top:50%;transform:translateY(-50%);background:white;border:1px solid #bbb;z-index:4;display:none;padding:8px;box-shadow:0 5px 20px #0001}.steps a{display:block;color:#111;text-decoration:none;padding:10px 8px;font-size:12px}.steps a:hover{background:#eee}body.config-mode .steps{display:block}.shell{display:grid;grid-template-columns:minmax(240px,420px) minmax(280px,1fr);gap:22px;align-items:start}.case{background:#ededeb;border:1px solid #ccc;border-radius:12px;padding:15px}.case svg{display:block;width:100%;height:auto}.led-cell{cursor:pointer;outline:none}.led-cell:focus .led-outline,.led-cell:hover .led-outline{stroke:#fff;stroke-width:3}.led-cell.selected .led-outline{stroke:#111;stroke-width:3}.panel{border:1px solid var(--inner-line);padding:18px;background:#fafaf8;display:grid;gap:12px}.panel .field select{width:100%}.notice{position:fixed;bottom:12px;left:50%;transform:translateX(-50%);background:white;border:1px solid #111;padding:12px 18px;z-index:8;display:none}.notice:not(:empty){display:block}.notice.error{color:#a00;border-color:#a00}.pill{background:#eee;padding:4px 9px;font-size:12px}.checks{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.checks label{padding:9px;border:1px solid #ddd}.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:14px 0}.formgrid .field input,.formgrid .field select{width:100%}@media(max-width:850px){.shell{grid-template-columns:1fr}.steps{right:0;top:auto;bottom:0;transform:none;display:none!important}body.config-mode .steps{display:flex!important;left:0;overflow:auto;justify-content:space-around}.steps a{white-space:nowrap}main{padding-bottom:125px}section{padding:16px}.brand{font-size:20px}}

/* Balanced CURNT-style header and centered content */
.head{max-width:1050px;display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:16px}
.head .brand{grid-column:2;grid-row:1;margin:0;font-size:27px;text-align:center;white-space:nowrap}
.head #state{grid-column:1;grid-row:1;justify-self:start;font-size:12px}
.head #logout{grid-column:3;grid-row:1;justify-self:end}
nav{max-width:1050px;justify-content:center}
main{max-width:1050px}
#page-config>h1,#page-config>p{text-align:center}
#page-config>section{max-width:980px;margin-left:auto!important;margin-right:auto!important}
#devicesSection>p:first-of-type{text-align:center}
#catalog{max-width:650px;margin:18px auto 0;max-height:350px;overflow-y:auto;overflow-x:hidden;border:1px solid var(--inner-line);padding:0 16px}
#catalog:empty{display:none}
#catalog h3{position:sticky;top:0;background:var(--bg);padding:12px 0;margin:0;z-index:1}
#catalog .device-row{width:100%;display:flex;flex-wrap:nowrap;justify-content:space-between;align-items:center;gap:16px;text-align:left;min-height:43px;padding:9px 0;overflow-wrap:anywhere}
#catalog .device-row input[type=checkbox]{flex:0 0 auto;margin-left:12px;order:2;width:17px;height:17px}
.wizard-footer button{min-height:46px;padding:12px 22px;line-height:20px}
@media(max-width:600px){.head{grid-template-columns:minmax(0,1fr) auto;gap:8px}.head .brand{grid-column:1/-1;grid-row:1;font-size:22px}.head #state{grid-column:1;grid-row:2;font-size:11px}.head #logout{grid-column:2;grid-row:2}#catalog{padding:0 10px}}

/* Shared flow layout: consistent borders and connectors; form controls stay 1px. */
:root{--flow-line:#999999;--flow-width:2px;--flow-gap:28px}
html{scrollbar-gutter:stable}
header{border-bottom:1px solid var(--inner-line)}
#page-config,#page-status{max-width:1080px;margin:auto}
#page-status>section,#page-config>section{position:relative;margin:0;border:var(--flow-width) solid var(--flow-line);padding:26px 28px 30px;background:var(--bg)}
#page-status>section+section,#page-config>section+section{margin-top:32px}
/* Bridge touches both adjacent outer borders; position from the top border, not bottom:100%. */
#page-status>section+section::before,#page-config>section+section::before{content:"";position:absolute;left:50%;top:calc(-32px - var(--flow-width));height:calc(32px + var(--flow-width));width:var(--flow-width);transform:translateX(-50%);background:var(--flow-line)}
nav{justify-content:center;position:relative}
nav button.active{position:relative}
/* The bridge is a real element between header and main, not a pseudo-element on a tab. */
.flow-bridge{height:var(--flow-gap);position:relative}
.flow-bridge-stem{position:absolute;top:0;bottom:0;width:var(--flow-width);background:var(--flow-line);transform:translateX(-50%)}
/* Navigation stem retains its existing width; only match the outer frame color. */
#flowBridgeStem{background:var(--flow-line);width:var(--flow-width)}
body.wizard-mode .flow-bridge{display:none}
main{margin-top:0}
.head{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;max-width:1080px}
.brand{margin:0;text-align:center}.head #logout{justify-self:end}.head #state{justify-self:start}
#page-config>section h2{text-align:center;font-size:20px;text-transform:uppercase;margin:0 0 24px}
.wizard-footer{display:flex;justify-content:center;border-top:1px solid var(--inner-line);margin-top:25px;padding-top:22px}
.wizard-footer button{min-width:220px}.steps{min-width:190px;border:var(--flow-width) solid var(--flow-line);padding:12px}.steps a{font-size:15px;line-height:1.35;padding:11px 10px}.steps a.focused{border-left:3px solid var(--flow-line);padding-left:7px}.steps .save-all{width:100%;margin-top:10px;padding:9px 10px;font-size:13px;min-height:38px}.steps #dirtyIndicator{display:block;font-size:11px;padding:8px 2px}
body.wizard-mode .steps,body.wizard-mode.config-mode .steps{display:none!important}
body.wizard-mode #page-status{display:none!important}body.wizard-mode #page-config{display:block!important}
body.wizard-mode nav{display:none}body.wizard-mode #page-config>section.wizard-hidden{display:none!important}
body.wizard-mode .wizard-footer:not([hidden]){display:flex}body.wizard-mode #page-config>section.wizard-complete{opacity:.85}
@media(max-width:850px){#page-config>section{padding:18px 14px}.steps{min-width:0}}

/* Outer flow elements share --flow-line and --flow-width. */
.ha-editor{margin:16px 0;padding:18px;border:1px solid var(--inner-line);background:var(--bg)}
.ha-editor[hidden]{display:none!important}.ha-editor .formgrid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.ha-editor select{width:100%;min-width:0}.ha-editor .row{justify-content:flex-end}
#devhost.ha-url{min-width:260px;flex:1}
#devicesSection>.row:first-of-type{justify-content:center}
/* Form controls: align to the same bottom edge, not to their labels */
.form-action-row{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap}
.form-action-row>button{height:42px;min-height:42px;padding:8px 16px}
.form-action-row>.field select{height:42px}
.compact-settings{max-width:740px;margin:16px auto 22px}
.compact-settings .field{font-size:14px}
.compact-settings input:not([type=checkbox]),.compact-settings select{height:42px}
.inline-settings{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:12px 0}
.inline-settings label{display:inline-flex;align-items:center;gap:8px}
.inline-settings input[type=number]{width:100px}
.config-note{color:var(--muted);font-size:13px;line-height:1.5;margin:8px 0 16px}
#thresholds{max-width:750px;margin:16px auto}
.threshold-row{display:grid;grid-template-columns:minmax(130px,1.4fr) repeat(3,minmax(95px,1fr));align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}
.threshold-row input{width:100%;min-width:0;height:40px}
.threshold-row .unit{color:var(--muted);font-size:12px}
.palette{display:flex;gap:18px;flex-wrap:wrap;justify-content:center;margin:15px auto}
.palette label{display:flex;align-items:center;gap:8px;font-size:14px}
.palette input{width:52px;height:38px}
.mail-options{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin:15px 0}
.mail-options label{display:flex;align-items:center;gap:8px;font-size:14px}
@media(max-width:650px){.threshold-row{grid-template-columns:minmax(100px,1.4fr) repeat(3,minmax(60px,1fr));gap:5px}.threshold-row input{padding:5px}}
/* Fill the viewport without manufacturing extra scroll space. */
body:has(.sboc-footer){min-height:100vh;min-height:100dvh;display:flex;flex-direction:column}
body:has(.sboc-footer)>main{flex:1 0 auto;width:100%;margin-bottom:0}
body:has(#page-status.active)>main{padding-bottom:0}
.sboc-footer{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:12px 0 14px;flex-shrink:0}.sboc-footer img{width:64px;height:auto;object-fit:contain}.sboc-version{font-size:12px;color:#888}.steps a.focused{border-left:3px solid var(--flow-line);padding-left:7px;font-weight:700}
.head .brand{font-size:42px;font-weight:800;line-height:1.15}.head #logout{font-size:12px;padding:6px 10px;min-height:32px}
/* Mobile: compact header, compact save action and clear active section. */
@media(max-width:600px){
 html{scrollbar-gutter:auto}
 .head{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;padding:12px 14px;align-items:center}
 .head #state{grid-column:1;grid-row:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
 .head .brand{grid-column:2;grid-row:1;font-size:25px;line-height:1.1}
 .head #logout{grid-column:3;grid-row:1;font-size:11px;padding:7px 9px;min-height:34px;white-space:nowrap}
 body.config-mode .steps{display:flex!important;align-items:center;justify-content:flex-start;gap:2px;padding:7px 9px;overflow-x:auto;overflow-y:hidden;min-width:0;max-width:100%;border-width:1px;background:var(--bg);scrollbar-width:thin}
 .steps a{flex:0 0 auto;padding:10px 9px;font-size:13px;line-height:1.2;border:0;border-bottom:3px solid transparent}
 .steps a.focused{padding:10px 9px;border:0;border-bottom:3px solid #111;font-weight:700}
 .steps .save-all{position:sticky;right:0;flex:0 0 auto;width:auto;margin:0 0 0 auto;min-height:36px;padding:7px 10px;font-size:12px;white-space:nowrap;z-index:2}
 .steps #dirtyIndicator{display:none}
 body.config-mode main{padding-bottom:85px}
}
@media(max-width:380px){
 .head{gap:6px;padding:10px 9px}
 .head #state{font-size:10px}
 .head .brand{font-size:22px}
 .head #logout{padding:6px 7px}
}
/* Mobile LED editor: viewport anchored, never changes the rack geometry. */
@media(max-width:850px){
 #ledSection .shell{display:block;min-width:0}
 #ledSection .case{position:relative;width:100%;max-width:none;margin:0;padding:8px;overflow:visible}
 #ledSection .case svg{width:100%;max-width:560px;margin:auto}
 #ledSection .panel.mobile-led-editor{position:fixed;z-index:120;left:12px;right:12px;top:12px;width:auto;max-height:calc(100dvh - 24px);overflow-y:auto;overscroll-behavior:contain;box-shadow:0 12px 36px #0007;border:2px solid #222;padding:12px;background:#fafaf8;gap:8px}
 #ledSection .panel.mobile-led-editor[hidden]{display:none!important}
 #ledSection .panel.mobile-led-editor .field{gap:3px}
 #ledSection .panel.mobile-led-editor .field select{min-width:0;width:100%;height:38px}
 #ledSection .panel.mobile-led-editor .field input[type=color]{height:36px}
 #ledSection .panel.mobile-led-editor #selectedTitle{margin:0;padding-right:80px}
 #ledSection .led-editor-close{position:sticky;float:right;right:0;top:0;z-index:1;min-height:32px;padding:4px 9px;font-size:12px}
 #ledSection .led-editor-backdrop{position:fixed;inset:0;z-index:119;background:#0005}
 #ledSection .led-editor-backdrop[hidden]{display:none!important}
}

</style></head><body><header><div class="head"><span id="state" class="muted">Verbinde …</span><div class="brand">SBOC.</div><button class="secondary" id="logout">Abmelden</button></div><nav><button class="active" data-page="status">Status</button><button data-page="config">Konfiguration</button><button data-page="settings">Benutzereinstellungen</button></nav></header><div class="flow-bridge" id="flowBridge" aria-hidden="true"><div class="flow-bridge-stem" id="flowBridgeStem"></div></div>
<aside class="steps" id="jumpMenu"><a href="#devicesSection">Geräte</a><a href="#modeSection">Modus</a><a href="#ledSection">LEDs</a><a href="#mailSection">E-Mail</a><a href="#systemSection">System</a><button id="saveAll" class="save-all">Alles speichern</button><span id="dirtyIndicator" class="muted" hidden>Ungespeicherte Änderungen</span></aside>
<main><div class="page active" id="page-status"><section><h2>Geräteübersicht</h2><div id="statusDevices"></div></section><section><div class="row" style="justify-content:space-between"><h2>Ereignisse</h2><button class="secondary" id="loadEvents">Aktualisieren</button></div><div id="activeAlarms"></div><div id="events" class="muted">Noch keine Ereignisse geladen.</div></section></div>
<div class="page" id="page-settings"><section><h2>User Settings</h2><p class="muted">Manage your account and preferred interface language.</p><h3>Language</h3><label class="field">Interface language<select id="userLanguage"><option value="en">English</option><option value="de">Deutsch</option></select></label><button id="saveLanguage">Save language</button><h3>Change password</h3><form id="passwordForm" autocomplete="off"><div class="formgrid"><label class="field">Current password<input id="currentPassword" type="password" autocomplete="current-password" required></label><label class="field">New password<input id="newPassword" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></label><label class="field">Confirm new password<input id="confirmPassword" type="password" autocomplete="new-password" minlength="12" maxlength="256" required></label></div><button type="submit">Change password</button></form><p class="muted">After changing your password, sign in again.</p></section></div>
<div class="page" id="page-config"><p id="wizardIntro" class="muted" hidden></p>
<section id="devicesSection"><h2>1 · Geräte einrichten</h2><p class="muted">Agent suchen oder manuell hinzufügen, Gerätefarbe und Überwachung zentral festlegen.</p><div class="row"><button id="discover" class="secondary">Geräte suchen</button><button id="manualToggle" class="secondary">Gerät manuell hinzufügen</button></div><div id="manualFields" hidden><div class="row"><select id="devtype" aria-label="Gerätetyp"><option value="agent">Linux-Agent</option><option value="haos">Home Assistant OS</option></select><input id="devname" placeholder="Geräte-ID" aria-label="Geräte-ID"><input id="devhost" placeholder="IP oder Hostname" aria-label="IP oder Hostname"><button id="add">Hinzufügen</button></div></div><div id="haFields" hidden class="ha-editor"><label class="field">Home-Assistant-Zugriffstoken<input id="haToken" type="password" autocomplete="off" placeholder="Langlebiger Zugriffstoken"></label><p class="config-note">Den Token unter Home Assistant → Benutzerprofil → Sicherheit erstellen. <a href="https://www.home-assistant.io/docs/authentication/" target="_blank" rel="noopener noreferrer">Anleitung von Home Assistant</a>. Die Verbindung wird vor dem Hinzufügen geprüft.</p></div><div id="haEditor" class="ha-editor" hidden><h3 id="haEditorTitle">Home Assistant bearbeiten</h3><div class="formgrid"><label class="field">Home-Assistant-Adresse<input id="haEditUrl" placeholder="http://homeassistant.local:8123"></label><label class="field">Neuer Zugriffstoken (optional)<input id="haEditToken" type="password" autocomplete="off" placeholder="Bisherigen Token beibehalten"></label></div><p class="config-note">Neuen Token erstellen: <a href="https://www.home-assistant.io/docs/authentication/" target="_blank" rel="noopener noreferrer">Home Assistant – Benutzerprofil und Sicherheit</a>.</p><button id="haRefresh" class="secondary">Verbindung und Sensoren prüfen</button><p class="config-note">Gefundene System-Monitor-Sensoren werden automatisch zugeordnet. Bei Bedarf kannst du eine andere Entität auswählen.</p><div id="haSensorFields" class="formgrid"></div><div class="row"><button id="haCancel" class="secondary">Schließen</button><button id="haApply">Sensorzuordnung übernehmen</button></div></div><div id="found"></div><div id="devices"></div><h3>Systemdienste und Container</h3><div class="form-action-row"><label class="field">Gerät<select id="watchDevice"></select></label><button class="secondary" id="loadCatalog">Liste anzeigen</button></div><p class="muted">Die verfügbaren Dienste und Container werden nur beim Start des Agents ermittelt. Neue Einträge erscheinen nach <code>sudo systemctl restart sboc-agent</code> auf dem jeweiligen Gerät. Ein kompletter Geräteneustart ist nicht nötig. Ausgewählte Zustände werden regelmäßig geprüft.</p><div id="catalog"></div><div class="wizard-footer" hidden><button class="wizard-next">Einstellungen übernehmen</button></div></section>
<section id="modeSection"><h2>2 · Betriebsmodus</h2><div class="checks"><label><input type="radio" name="mode" value="led"> Nur LEDs</label><label><input type="radio" name="mode" value="mail"> Nur E-Mail</label><label><input type="radio" name="mode" value="both"> LEDs und E-Mail</label><label><input type="radio" name="mode" value="web"> Nur Webüberwachung</label></div><div class="wizard-footer" hidden><button class="wizard-next">Einstellungen übernehmen</button></div></section>
<section id="ledSection"><h2>3 · LED-Konfiguration</h2><h3>Lichttest</h3><div class="form-action-row"><label class="field">Effekt<select id="effect"><option value="orientation">Links-/Rechts-Test</option><option value="reactor">Warp-Reaktor</option><option value="rainbow">Regenbogen</option><option value="comet">Komet</option><option value="scanner">Scanner</option><option value="breathing">Atmen</option><option value="sparkle">Sternenfunkeln</option><option value="meteor">Meteor</option><option value="dual_chase">Lichtjagd</option></select></label><button id="test">Starten</button><button class="secondary" id="stoptest">Stoppen</button></div><p class="config-note" id="effectDescription">Orientierungstest: Nur links oben leuchtet grün, rechts oben rot. Alle anderen LEDs bleiben aus.</p><h3>Verdrahtung</h3><div class="row"><label><input type="checkbox" id="swap"> Links und rechts tauschen</label><label><input type="checkbox" id="revleft"> GPIO12 umkehren</label><label><input type="checkbox" id="revright"> GPIO13 umkehren</label></div><h3>LED-Zuordnung</h3><div class="shell"><div class="case"><svg id="caseSvg" viewBox="0 0 360 530" role="group" aria-label="Gehäuse mit 20 einzeln auswählbaren LEDs"><path d="M42 25 L66 5 H294 L318 25 V498 L294 518 H66 L42 498 Z" fill="#d8d8d4" stroke="#74746e" stroke-width="2"/><path d="M66 5 H294 L318 25 H42 Z" fill="#eeeeeb" stroke="#777"/><path d="M42 498 L66 518 H294 L318 498 Z" fill="#eeeeeb" stroke="#777"/><rect x="63" y="30" width="234" height="463" fill="#383d42" rx="3"/><g id="caseLeds"></g></svg><p class="muted" style="text-align:center">LED direkt anklicken oder mit Tab und Enter auswählen.</p></div><div class="panel"><h3 id="selectedTitle">LED 1 · links</h3><label class="field" id="ledDeviceField">Gerät / feste Farbe<select id="ledDevice"></select></label><label class="field" id="ledColorField">Dummy-Farbe<input type="color" id="ledColor" value="#56c5ee"></label><div id="rightFields"><p class="muted" id="rightDeviceInfo"></p><label class="field">Messwert<select id="ledMetric"></select></label><label class="field" id="statusColorField">Feste Statusfarbe<input type="color" id="ledStatusColor" value="#56c5ee"></label><label class="field">Übersteuerung<select id="ledOverride"></select></label><label class="field">Effekt<select id="ledEffect"><option value="static">Statisch</option><option value="pulse">Pulsieren</option><option value="blink">Blinken</option></select></label><label class="field">Warnfarbe<input type="color" id="ledWarnColor" value="#ff3030"></label></div></div></div><h3>Beleuchtung</h3><div class="row"><button id="power">Licht ausschalten</button><label class="field">Helligkeit (max. 80 %)<input id="brightness" type="range" min="0" max="80" value="50"></label><span id="bval">50 %</span></div><h3>Silent-Modus</h3><p class="config-note">Die LEDs eines Geräts leuchten nur bei einem kritischen Zustand. Dieser muss für die eingestellte Zeit ununterbrochen bestehen, damit kurze Spitzen keine Anzeige auslösen.</p><div class="inline-settings"><label><input type="checkbox" id="silentEnabled"> Aktiv</label><label>Auslöseverzögerung (s) <input id="silentDelay" type="number" min="0" max="3600"></label></div><h3>Nachtsteuerung</h3><p class="config-note">LEDs werden im definierten Zeitraum ausgeschaltet. Auch kritische Zustände werden nicht angezeigt.</p><div class="form-action-row compact-settings" style="margin-left:0;margin-right:auto;justify-content:flex-start"><label style="height:42px;display:flex;align-items:center;gap:8px"><input type="checkbox" id="night"> Aktiv</label><label class="field">Von<input type="time" id="start"></label><label class="field">Bis<input type="time" id="end"></label></div><div class="wizard-footer" hidden><button class="wizard-next">Einstellungen übernehmen</button></div></section>
<section id="mailSection"><h2>4 · E-Mail-Benachrichtigungen</h2><div class="mail-options"><label><input id="mailEnabled" type="checkbox"> E-Mail aktivieren</label><label><input id="mailRecovery" type="checkbox"> Entwarnung senden</label></div><div class="formgrid"><label class="field">SMTP-Server<input id="mailHost"></label><label class="field">Port<input id="mailPort" type="number" value="587"></label><label class="field">Verschlüsselung<select id="mailMode"><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select></label><label class="field">Username<input id="mailUser"></label><label class="field">Passwort (leer = unverändert)<input id="mailPassword" type="password" autocomplete="new-password"></label><label class="field">Absender-E-Mail-Adresse<input id="mailSender" type="email"></label><label class="field">Empfänger<input id="mailRecipient" type="email"></label><label class="field">Verzögerung (s)<input id="mailDelay" type="number" min="0" value="60"></label></div><div class="row"><button class="secondary" id="mailTest">Testmail senden</button></div><div class="wizard-footer" hidden><button class="wizard-next">Einstellungen übernehmen</button></div></section>
<section id="systemSection"><h2>5 · Systemeinstellungen</h2>
<div class="formgrid compact-settings"><label class="field">Agent-Abfrageintervall (Sekunden)<input id="interval" type="number" min="10" max="3600"><span class="config-note">Wie oft der Controller die Messwerte der Agents abfragt.</span></label><label class="field">Fehlversuche bis „Offline“<input id="failures" type="number" min="1" max="30"><span class="config-note">Nach dieser Anzahl aufeinanderfolgender Fehlversuche gilt der Agent als nicht erreichbar. Zugeordnete LEDs blinken rot, sofern die Beleuchtung aktiv ist.</span></label></div>
<h3 style="text-align:center">Statusfarben</h3><p class="config-note" style="text-align:center">Die vier Farben gelten für alle Messwerte. Gerätefarben werden separat festgelegt.</p><div class="palette" id="palette"></div>
<h3 style="text-align:center">Schwellwerte</h3><p class="config-note" style="text-align:center">Ab dem jeweiligen Wert wechselt die Anzeige zur nächsten Farbstufe. Die Werte müssen aufsteigend sein.</p><div id="thresholds"></div><div class="wizard-footer" hidden><button class="wizard-next">Einstellungen übernehmen</button></div></section>
</div><p class="notice" id="message" role="status"></p></main><footer class="sboc-footer"><img alt="M3ro" src="/assets/m3ro-gray.png"><span class="sboc-version">Version @@VERSION@@</span></footer>
<script>

const UI_EN={"Konfiguration": "Configuration", "Benutzereinstellungen": "User Settings", "Abmelden": "Sign out", "Verbinde …": "Connecting…", "Geräte": "Devices", "Modus": "Mode", "Alles speichern": "Save all", "Ungespeicherte Änderungen": "Unsaved changes", "Geräteübersicht": "Device overview", "Ereignisse": "Events", "Aktualisieren": "Refresh", "Noch keine Ereignisse geladen.": "No events loaded yet.", "Geräte einrichten": "Set up devices", "Geräte suchen": "Find devices", "Gerät manuell hinzufügen": "Add device manually", "Hinzufügen": "Add", "Gerätetyp": "Device type", "Geräte-ID": "Device ID", "IP oder Hostname": "IP address or hostname", "Home-Assistant-Zugriffstoken": "Home Assistant access token", "Langlebiger Zugriffstoken": "Long-lived access token", "Anleitung von Home Assistant": "Home Assistant guide", "Home Assistant bearbeiten": "Edit Home Assistant", "Home-Assistant-Adresse": "Home Assistant address", "Neuer Zugriffstoken (optional)": "New access token (optional)", "Bisherigen Token beibehalten": "Keep existing token", "Schließen": "Close", "Verbindung und Sensoren prüfen": "Check connection and sensors", "Sensorzuordnung übernehmen": "Apply sensor mapping", "Systemdienste und Container": "System services and containers", "Gerät": "Device", "Liste anzeigen": "Show list", "Betriebsmodus": "Operating mode", "Nur LEDs": "LEDs only", "Nur E-Mail": "Email only", "LEDs und E-Mail": "LEDs and email", "Nur Webüberwachung": "Web monitoring only", "Einstellungen übernehmen": "Apply settings", "LED-Konfiguration": "LED configuration", "Lichttest": "LED test", "Effekt": "Effect", "Links-/Rechts-Test": "Left/right test", "Warp-Reaktor": "Warp reactor", "Regenbogen": "Rainbow", "Komet": "Comet", "Scanner": "Scanner", "Atmen": "Breathing", "Sternenfunkeln": "Twinkle", "Meteor": "Meteor", "Lichtjagd": "Light chase", "Starten": "Start", "Stoppen": "Stop", "Verdrahtung": "Wiring", "Links und rechts tauschen": "Swap left and right", "umkehren": "reverse", "LED-Zuordnung": "LED mapping", "links": "left", "rechts": "right", "Gerät / feste Farbe": "Device / fixed color", "Dummy-Farbe": "Placeholder color", "Messwert": "Metric", "Feste Statusfarbe": "Fixed status color", "Übersteuerung": "Override", "Statisch": "Static", "Pulsieren": "Pulse", "Blinken": "Blink", "Warnfarbe": "Warning color", "Beleuchtung": "Lighting", "Licht ausschalten": "Turn off LEDs", "Helligkeit (max. 80 %)": "Brightness (max. 80%)", "Silent-Modus": "Silent mode", "Aktiv": "Enabled", "Auslöseverzögerung (s)": "Trigger delay (s)", "Nachtsteuerung": "Night mode", "Von": "From", "Bis": "Until", "E-Mail-Benachrichtigungen": "Email notifications", "E-Mail aktivieren": "Enable email", "Entwarnung senden": "Send recovery notification", "SMTP-Server": "SMTP server", "Verschlüsselung": "Encryption", "Benutzername": "Username", "Passwort (leer = unverändert)": "Password (blank = unchanged)", "Absender-E-Mail-Adresse": "Sender email address", "Empfänger": "Recipient", "Verzögerung (s)": "Delay (s)", "Testmail senden": "Send test email", "System": "System", "Statusfarben": "Status colors", "Schwellwerte": "Thresholds", "Temperatur": "Temperature", "CPU-Auslastung": "CPU usage", "Speicherplatz": "Disk usage", "Netzwerk (KiB/s)": "Network (KiB/s)", "Feste Farbe": "Fixed color", "Einrichtungscode": "Setup code", "Anmelden": "Sign in", "Konto anlegen": "Create account", "Passwort": "Password", "Fehler": "Error", "Einrichtung abgeschlossen": "Setup complete", "LEDs bereit": "LEDs ready", "LED-Ausgabe nicht bereit": "LED output unavailable", "Alle Änderungen gespeichert": "All changes saved", "Gerät bereits vorhanden": "Device already exists", "Testmail versendet": "Test email sent", "Keine neuen Agents gefunden. Du kannst ein Gerät manuell hinzufügen.": "No new agents found. You can add a device manually.", "Kopplung fehlgeschlagen: ": "Pairing failed: ", "Verbindung erfolgreich": "Connection successful", "Gerät hinzugefügt. Bitte Alles speichern wählen.": "Device added. Select Save all to apply changes.", "Ungültiger Ursprung": "Invalid origin", "Nicht angemeldet": "Not signed in", "Nicht gefunden": "Not found", "Ungültige Größe": "Invalid request size", "Anmeldung fehlgeschlagen": "Sign-in failed", "Zu viele Versuche. Bitte später erneut versuchen.": "Too many attempts. Please try again later."};
Object.assign(UI_EN,{"Agent suchen oder manuell hinzufügen, Gerätefarbe und Überwachung zentral festlegen.":"Discover agents or add devices manually, then configure their colors and monitoring settings.","Den Token unter Home Assistant → Benutzerprofil → Sicherheit erstellen.":"Create a long-lived access token in Home Assistant under your profile → Security.","Die Verbindung wird vor dem Hinzufügen geprüft.":"The connection is checked before the device is added.","Neuen Token erstellen:":"Create a new token:","Home Assistant – Benutzerprofil und Sicherheit":"Home Assistant – Profile and Security","Gefundene System-Monitor-Sensoren werden automatisch zugeordnet. Bei Bedarf kannst du eine andere Entität auswählen.":"Detected system monitoring sensors are assigned automatically. You can select different entities if needed.","Die verfügbaren Dienste und Container werden nur beim Start des Agents ermittelt. Neue Einträge erscheinen nach":"Available services and containers are discovered when the agent starts. To discover new entries, run","auf dem jeweiligen Gerät. Ein kompletter Geräteneustart ist nicht nötig. Ausgewählte Zustände werden regelmäßig geprüft.":"on the device. You do not need to reboot the device. Selected services and containers are checked regularly.","Orientierungstest: Nur links oben leuchtet grün, rechts oben rot. Alle anderen LEDs bleiben aus.":"Orientation test: Only the top-left LED lights up green and the top-right LED lights up red. All other LEDs remain off.","LED direkt anklicken oder mit Tab und Enter auswählen.":"Click an LED to select it, or use Tab and Enter.","Die LEDs eines Geräts leuchten nur bei einem kritischen Zustand. Dieser muss für die eingestellte Zeit ununterbrochen bestehen, damit kurze Spitzen keine Anzeige auslösen.":"Device LEDs light up only when a critical condition persists for the configured delay. Brief spikes will not trigger an alert.","LEDs werden im definierten Zeitraum ausgeschaltet. Auch kritische Zustände werden nicht angezeigt.":"LEDs stay off during the scheduled hours, including when a critical condition occurs.","Systemeinstellungen":"System settings","Agent-Abfrageintervall (Sekunden)":"Agent polling interval (seconds)","Wie oft der Controller die Messwerte der Agents abfragt.":"How often the controller requests measurements from agents.","Fehlversuche bis „Offline“":"Failed checks before marking offline","Nach dieser Anzahl aufeinanderfolgender Fehlversuche gilt der Agent als nicht erreichbar. Zugeordnete LEDs blinken rot, sofern die Beleuchtung aktiv ist.":"After this many consecutive failed checks, the agent is considered offline. Its LEDs flash red if lighting is enabled.","Die vier Farben gelten für alle Messwerte. Gerätefarben werden separat festgelegt.":"These four colors apply to all metrics. Device colors are configured separately.","Ab dem jeweiligen Wert wechselt die Anzeige zur nächsten Farbstufe. Die Werte müssen aufsteigend sein.":"Each threshold switches the indicator to the next severity level. Thresholds must increase from left to right.","Niedrig":"Low","Normal":"Normal","Erhöht":"Elevated","Kritisch":"Critical","Ab Normal":"Normal from","Ab Erhöht":"Elevated from","Ab Kritisch":"Critical from","Aus":"Off","Feste Farbe (Dummy)":"Fixed color (placeholder)","Keine":"None","CPU-Throttling":"CPU throttling","Unterspannung":"Undervoltage","Dateisystem schreibgeschützt":"Read-only file system","OOM-Killer":"Out-of-memory killer","Dienst: ":"Service: ","Container: ":"Container: ","Gerät: ":"Device: ","Neu koppeln":"Pair again","Koppeln":"Pair","Entfernen":"Remove","Bearbeiten":"Edit","Orientierungstest":"Orientation test","Warp-Reaktor: Laufender Lichteffekt über die LED-Streifen.":"Warp reactor: A moving light effect along the LED strips.","Regenbogen: Wechselnde Regenbogenfarben.":"Rainbow: A cycling rainbow of colors.","Komet: Ein Lichtpunkt zieht mit Nachleuchten über die LEDs.":"Comet: A moving light with a fading trail.","Scanner: Ein Lichtpunkt bewegt sich hin und her.":"Scanner: A light moves back and forth.","Atmen: Die Helligkeit steigt und sinkt langsam.":"Breathing: The LEDs slowly brighten and dim.","Sternenfunkeln: Einzelne LEDs funkeln.":"Twinkle: Individual LEDs sparkle.","Meteor: Ein Lichtschweif bewegt sich über die LEDs.":"Meteor: A streak of light moves along the LEDs.","Lichtjagd: Lichtpunkte laufen über beide Streifen.":"Light chase: Moving lights travel along both strips.","LEDs bereit":"LEDs ready","LED-Ausgabe nicht bereit":"LED output unavailable","Licht einschalten":"Turn on LEDs","Lichttest läuft":"LED test running","RAM-Auslastung":"RAM usage","Netzwerk":"Network","Speicher":"Disk","Warte auf Messwerte":"Waiting for measurements","Offline":"Offline","Bitte zuerst mindestens ein Gerät hinzufügen.":"Add at least one device first.","Vollständige Home-Assistant-Adresse eingeben, z. B. http://homeassistant.local:8123":"Enter a complete Home Assistant URL, e.g. http://homeassistant.local:8123","HA-Zugriffstoken fehlt":"Home Assistant access token is required","Sechsstelliger Kopplungscode vom Agent (sudo sboc-pairing-code):":"Enter the six-digit agent pairing code (sudo sboc-pairing-code):","Gerät hinzugefügt. Bitte Alles speichern wählen.":"Device added. Select Save all to apply changes.","Alle Änderungen gespeichert":"All changes saved"});
const UI_DE=Object.fromEntries(Object.entries(UI_EN).map(([de,en])=>[en,de]));
let uiLanguage='en';
const originalText=new WeakMap(), renderedText=new WeakMap(), originalAttrs=new WeakMap();
function t(value){if(uiLanguage==='de')return value;return UI_EN[value]||value}
function translateText(value,lang){
  const trimmed=value.trim();if(!trimmed)return value;
  const dict=lang==='en'?UI_EN:UI_DE;
  if(dict[trimmed])return value.replace(trimmed,dict[trimmed]);
  // Preserve punctuation and numeric step prefixes.
  const numbered=trimmed.match(/^(\\d+ · )(.+)$/);
  if(numbered&&dict[numbered[2]])return value.replace(trimmed,numbered[1]+dict[numbered[2]]);
  let translated=value;
  for(const [source,target] of Object.entries(dict).sort((a,b)=>b[0].length-a[0].length)){
    if(source.length>=14 && translated.includes(source))translated=translated.split(source).join(target);
  }
  return translated;
}
function localize(root=document){
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode())){
    if(node.parentElement?.closest('script,style,code'))continue;
    if(!originalText.has(node)||node.nodeValue!==renderedText.get(node))originalText.set(node,node.nodeValue);
    const translated=translateText(originalText.get(node),uiLanguage);
    renderedText.set(node,translated);if(node.nodeValue!==translated)node.nodeValue=translated;
  }
  const elements=[...(root.querySelectorAll?root.querySelectorAll('*'):[])];
  for(const el of elements){for(const attr of ['placeholder','title','aria-label']){
    if(!el.hasAttribute(attr))continue;
    let originals=originalAttrs.get(el);if(!originals){originals={};originalAttrs.set(el,originals)}
    if(!(attr in originals))originals[attr]=el.getAttribute(attr);
    el.setAttribute(attr,translateText(originals[attr],uiLanguage));
  }}
}
function applyLanguage(lang){uiLanguage=lang==='de'?'de':'en';document.documentElement.lang=uiLanguage;localize();}

new MutationObserver(records=>{for(const r of records){
  if(r.type==='characterData'){
    const n=r.target;if(n.parentElement&&!n.parentElement.closest('script,style,code')){
      if(n.nodeValue!==renderedText.get(n)){originalText.set(n,n.nodeValue);const translated=translateText(n.nodeValue,uiLanguage);renderedText.set(n,translated);if(n.nodeValue!==translated)n.nodeValue=translated;}
    }
  }else for(const n of r.addedNodes){if(n.nodeType===1)localize(n);else if(n.nodeType===3&&n.parentElement&&!n.parentElement.closest('script,style,code')){originalText.set(n,n.nodeValue);const translated=translateText(n.nodeValue,uiLanguage);renderedText.set(n,translated);if(n.nodeValue!==translated)n.nodeValue=translated;}}
}}).observe(document.body,{subtree:true,childList:true,characterData:true});
const $=id=>document.getElementById(id),E=(tag,txt='',cl='')=>{const n=document.createElement(tag);n.textContent=txt;if(cl)n.className=cl;return n};let cfg=null,status=null,selected={row:0,side:0},timer=null,editingHA=null;const names={cpu:'CPU-Auslastung',temperature:'Temperatur',ram:'RAM',disk:'Speicherplatz',network:'Netzwerk (KiB/s)',static:'Feste Farbe'};const metrics=Object.keys(names).filter(k=>k!=='static');
async function api(path,method='GET',obj){const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:obj===undefined?undefined:JSON.stringify(obj)});const j=await r.json();if(!r.ok)throw Error(j.error||'Error');return j}
function notice(t,error=false){const e=$('message');e.textContent=t;e.classList.toggle('error',error);clearTimeout(timer);if(!error)timer=setTimeout(()=>e.textContent='',2800)}
let dirty=false, wizard=false, wizardStep=0, mailDraft=null, saving=false;
function markDirty(){dirty=true;$('dirtyIndicator').hidden=false}
async function persistAll(){
  if(saving)return false;
  saving=true;
  try{
    captureForms();
    const result=await api('/api/config','POST',cfg);
    cfg=result.config;
    if(mailDraft){await api('/api/mail','POST',mailDraft);mailDraft=null;$('mailPassword').value=''}
    dirty=false;$('dirtyIndicator').hidden=true;notice('Alle Änderungen gespeichert');return true;
  }catch(e){notice(e.message,true);return false}finally{saving=false}
}
function save(){markDirty();draw()}
function captureForms(){if($('catalog').querySelectorAll('input[type=checkbox]').length)collectWatches();
  cfg.operation_mode=document.querySelector('[name=mode]:checked')?.value||cfg.operation_mode;
  cfg.led_swap=$('swap').checked;cfg.led_reverse=[$('revleft').checked,$('revright').checked];
  cfg.night={enabled:$('night').checked,start:$('start').value,end:$('end').value,brightness:0};
  cfg.silent={enabled:$('silentEnabled').checked,delay:Number($('silentDelay').value)};
  cfg.interval=Number($('interval').value);cfg.failures=Number($('failures').value);
  cfg.brightness=Number($('brightness').value);cfg.test_effect=$('effect').value;
  mailDraft=mailForm();
}
$('saveAll').onclick=persistAll;

function options(select,items,value){select.replaceChildren();for(const [id,label] of items){const o=E('option',label);o.value=id;select.append(o)}select.value=value??items[0]?.[0]??''}
function alignFlowBridge(){
 const bridge=$('flowBridge'),tab=document.querySelector('nav button.active');
 if(!bridge||!tab)return;
 const t=tab.getBoundingClientRect(),r=bridge.getBoundingClientRect();
 $('flowBridgeStem').style.left=(t.left+t.width/2-r.left)+'px';
}
function updateJumpFocus(){
 const links=[...document.querySelectorAll('#jumpMenu a[href^="#"]')];
 if(!document.body.classList.contains('config-mode'))return;
 const visible=links.map(a=>({a,el:document.querySelector(a.getAttribute('href'))})).filter(x=>x.el&&!x.el.hidden&&getComputedStyle(x.el).display!=='none');
 if(!visible.length)return;
 const focusLine=window.innerHeight*0.35;
 let current=visible[0];
 for(const x of visible){if(x.el.getBoundingClientRect().top<=focusLine)current=x;}
 links.forEach(a=>a.classList.toggle('focused',a===current.a));
}
window.addEventListener('scroll',updateJumpFocus,{passive:true});
window.addEventListener('resize',updateJumpFocus);
document.querySelectorAll('#jumpMenu a[href^="#"]').forEach(a=>a.addEventListener('click',()=>{document.querySelectorAll('#jumpMenu a').forEach(x=>x.classList.toggle('focused',x===a));}));
// Navigation geometry can change after the first paint (font loading, translations,
// viewport changes). Keep the connector aligned to the actual active tab.
let bridgeAlignmentFrame=0;
function scheduleFlowBridgeAlignment(){
 if(bridgeAlignmentFrame)cancelAnimationFrame(bridgeAlignmentFrame);
 bridgeAlignmentFrame=requestAnimationFrame(()=>{
  bridgeAlignmentFrame=requestAnimationFrame(()=>{bridgeAlignmentFrame=0;alignFlowBridge()});
 });
}
window.addEventListener('resize',scheduleFlowBridgeAlignment);
window.addEventListener('load',scheduleFlowBridgeAlignment);
if(document.fonts&&document.fonts.ready)document.fonts.ready.then(scheduleFlowBridgeAlignment);
if(typeof ResizeObserver!=='undefined'){
 const flowObserver=new ResizeObserver(scheduleFlowBridgeAlignment);
 const navigation=document.querySelector('nav');
 if(navigation)flowObserver.observe(navigation);
 document.querySelectorAll('nav button[data-page]').forEach(button=>flowObserver.observe(button));
}
scheduleFlowBridgeAlignment();requestAnimationFrame(updateJumpFocus);
for(const b of document.querySelectorAll('[data-page]'))b.onclick=()=>{const config=b.dataset.page==='config';requestAnimationFrame(updateJumpFocus);document.body.classList.toggle('config-mode',config);document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id==='page-'+b.dataset.page));scheduleFlowBridgeAlignment();window.scrollTo(0,0)};
function mapped(row){return cfg.mapping[row]||{device:'__off__',left_device:'__off__',right_device:'__off__',metric:'static',color:'#56c5ee',status_color:'#56c5ee'}}
function color(row,side){const x=cfg.mapping[row];if(!x)return '#30363b';const dev=side===0?x.left_device:x.right_device;if(dev==='__off__')return '#30363b';if(side===0)return dev==='__static__'?x.color:cfg.device_colors[dev]||'#56c5ee';if(x.right_off)return '#30363b';if(x.metric==='static')return x.status_color;if(dev==='__static__')return '#333333';const val=status?.metrics?.[dev]?.metrics?.[x.metric];if(typeof val!=='number')return '#777';const t=cfg.thresholds[x.metric]||[20,50,80];return cfg.status_colors[t.filter(v=>val>=v).length]}
function drawCase(){const g=$('caseLeds');g.replaceChildren();for(let row=0;row<10;row++){const y=48+row*43;const rail=document.createElementNS('http://www.w3.org/2000/svg','rect');for(const [k,v] of Object.entries({x:78,y,width:204,height:23,rx:3,fill:'#ffffff',stroke:'#999999'}))rail.setAttribute(k,v);g.append(rail);for(let side=0;side<2;side++){const a=document.createElementNS('http://www.w3.org/2000/svg','g');a.setAttribute('class','led-cell'+(selected.row===row&&selected.side===side?' selected':''));a.setAttribute('tabindex','0');a.setAttribute('role','button');a.setAttribute('aria-label',`LED ${row+1} ${side?'rechts':'links'}`);const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');for(const [k,v] of Object.entries({x:side?189:82,y:y+3,width:89,height:17,rx:2,fill:color(row,side),stroke:'#555','stroke-width':1,class:'led-outline'}))rect.setAttribute(k,v);a.append(rect);a.onclick=()=>selectLed(row,side,true);a.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectLed(row,side,true)}};g.append(a)}const number=document.createElementNS('http://www.w3.org/2000/svg','text');for(const [k,v] of Object.entries({x:180,y:y+15,'text-anchor':'middle','font-size':11,'font-weight':600,fill:'#333','pointer-events':'none'}))number.setAttribute(k,v);number.textContent=String(row+1);g.append(number)}}
function placeMobileLedEditor(open){
 const panel=document.querySelector('#ledSection .panel');
 const shell=document.querySelector('#ledSection .shell');
 const rack=document.querySelector('#ledSection .case');
 if(!panel||!shell||!rack)return;
 let backdrop=document.querySelector('#ledSection .led-editor-backdrop');
 if(!backdrop){backdrop=document.createElement('div');backdrop.className='led-editor-backdrop';backdrop.hidden=true;document.body.append(backdrop)}
 const closeEditor=()=>{panel.hidden=true;panel.dataset.open='0';backdrop.hidden=true};
 backdrop.onclick=closeEditor;
 if(!panel.querySelector('.led-editor-close')){
  const close=document.createElement('button');close.type='button';close.className='led-editor-close secondary';close.textContent='Schließen';close.onclick=closeEditor;panel.prepend(close);
 }
 if(window.matchMedia('(max-width:850px)').matches){
  if(panel.parentElement!==rack)rack.append(panel);
  panel.classList.add('mobile-led-editor');
  if(open)panel.dataset.open='1';
  panel.hidden=panel.dataset.open!=='1';backdrop.hidden=panel.hidden;
  if(!panel.hidden){
   panel.style.top='12px';
   const led=rack.querySelectorAll('.led-cell')[selected.row*2+selected.side];
   const rect=led?.getBoundingClientRect();
   const viewport=window.visualViewport;
   const top=viewport?.offsetTop||0;
   const bottom=top+(viewport?.height||window.innerHeight);
   const available=Math.max(160,bottom-top-24);
   panel.style.maxHeight=available+'px';
   const panelHeight=Math.min(panel.scrollHeight+4,available);
   const below=(rect?.bottom||top)+8;
   const above=(rect?.top||bottom)-panelHeight-8;
   let y=(bottom-below>=panelHeight)?below:(above>=top+12?above:Math.max(top+12,Math.min(below,bottom-panelHeight-12)));
   panel.style.top=Math.round(y)+'px';
  }
 }else{
  backdrop.hidden=true;
  if(panel.parentElement!==shell)shell.append(panel);
  panel.classList.remove('mobile-led-editor');panel.hidden=false;panel.style.top='';panel.style.maxHeight='';panel.dataset.open='0';
 }
}
window.addEventListener('resize',()=>placeMobileLedEditor(false));
if(window.visualViewport)window.visualViewport.addEventListener('resize',()=>placeMobileLedEditor(false));
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&window.matchMedia('(max-width:850px)').matches){const panel=document.querySelector('#ledSection .panel');if(panel&&!panel.hidden){panel.hidden=true;panel.dataset.open='0';const bg=document.querySelector('.led-editor-backdrop');if(bg)bg.hidden=true}}});

function selectLed(row,side,openEditor=false){selected={row,side};const x=mapped(row);$('selectedTitle').textContent=`LED ${row+1} · ${side?'rechts':'links'}`;options($('ledDevice'),[['__off__','Aus'],['__static__','Feste Farbe (Dummy)'],...cfg.devices.map(d=>[d.id,d.id])],x.left_device);options($('ledMetric'),[['off','Aus'],...metrics.map(m=>[m,names[m]]),['static','Feste Farbe (Dummy)']],x.right_off?'off':x.metric);$('ledColor').value=x.color;$('ledStatusColor').value=x.status_color;const ov=cfg.overrides[String(row)]||{kind:'none',effect:'pulse',color:'#ff3030'};const device=x.left_device;const w=cfg.watches[device]||{services:[],containers:[]};options($('ledOverride'),[['none','Keine'],['throttling','CPU-Throttling'],['undervoltage','Unterspannung'],['filesystem_ro','Dateisystem schreibgeschützt'],['oom','OOM-Killer'],['offline','Offline'],...w.services.map(v=>['service:'+v,'Dienst: '+v]),...w.containers.map(v=>['container:'+v,'Container: '+v])],ov.kind);$('ledEffect').value=ov.effect;$('ledWarnColor').value=ov.color;$('rightFields').hidden=side===0;$('ledDeviceField').hidden=side===1;$('ledColorField').hidden=side===1;$('rightDeviceInfo').textContent=device==='__off__'?'Aus':device==='__static__'?'Feste Farbe (Dummy)':('Gerät: '+device);updateColorVisibility();drawCase();placeMobileLedEditor(openEditor)}
function updateColorVisibility(){$('ledColorField').hidden=selected.side!==0||$('ledDevice').value!=='__static__';$('statusColorField').hidden=$('ledMetric').value!=='static';const active=$('ledOverride').value!=='none';$('ledEffect').closest('label').hidden=!active;$('ledWarnColor').closest('label').hidden=!active}$('ledDevice').onchange=updateColorVisibility;$('ledMetric').onchange=updateColorVisibility;$('ledOverride').onchange=updateColorVisibility;
function applySelected(){const i=selected.row,x=mapped(i);if(selected.side===0){if($('ledDevice').value==='__off__'){cfg.mapping[i]=null;delete cfg.overrides[String(i)];markDirty();drawCase();return}x.left_device=$('ledDevice').value;x.color=$('ledColor').value;if(x.right_device!==x.left_device){x.right_device=x.left_device;x.device=x.left_device;x.metric='static';x.right_off=true;delete cfg.overrides[String(i)]}x.device=x.left_device}else{if(x.left_device==='__off__'){notice('Bitte zuerst links ein Gerät oder Dummy auswählen',true);return}x.right_device=x.left_device;x.device=x.left_device;x.metric=$('ledMetric').value==='off'?'static':$('ledMetric').value;x.right_off=$('ledMetric').value==='off';x.status_color=$('ledStatusColor').value;cfg.overrides[String(i)]={kind:$('ledOverride').value,effect:$('ledEffect').value,color:$('ledWarnColor').value}}cfg.mapping[i]=x;markDirty();drawCase()}
for(const id of ['ledDevice','ledColor','ledMetric','ledStatusColor','ledOverride','ledEffect','ledWarnColor'])$(id).addEventListener('change',()=>{applySelected();selectLed(selected.row,selected.side)});

function draw(){if(!cfg)return;const ds=$('devices'),ss=$('statusDevices');ds.replaceChildren();ss.replaceChildren();for(const d of cfg.devices){const m=status?.metrics?.[d.id]?.metrics||{};const line=E('div','','device-row'),info=E('div','','device-info');const title=E('strong',d.id+' · '+(d.type==='haos'?haUrl(d)+' · HAOS':d.host));const detail=E('small',`CPU ${m.cpu??'—'} % · ${t('Temperatur')} ${m.temperature??'—'} °C · RAM ${m.ram??'—'} % · ${t('Speicher')} ${m.disk??'—'} % · ${t('Netzwerk')} ${m.network??'—'} KiB/s`);info.append(title,detail);const picker=document.createElement('input');picker.type='color';picker.value=cfg.device_colors[d.id]||'#56c5ee';picker.title='Gerätefarbe';picker.onchange=()=>{cfg.device_colors[d.id]=picker.value;markDirty();drawCase()};const del=E('button','Entfernen','secondary');del.onclick=()=>{if(!confirm(`Gerät ${d.id} entfernen?`))return;cfg.devices=cfg.devices.filter(x=>x.id!==d.id);cfg.mapping=cfg.mapping.map(x=>x&&[x.left_device,x.right_device].includes(d.id)?null:x);delete cfg.device_colors[d.id];delete cfg.watches[d.id];save()};line.append(info);if(d.type!=='haos'){
const link=E('button',d.agent_identity?'Neu koppeln':'Koppeln','secondary');link.onclick=async()=>{const code=prompt('Sechsstelliger Kopplungscode vom Agent (sudo sboc-pairing-code):');if(!code)return;try{const r=await api('/api/agent/pair','POST',{host:d.host,port:d.port,code:code.trim()});d.agent_identity=r.agent_identity;save();notice('Agent gekoppelt – bitte Änderungen speichern')}catch(e){notice('Kopplung fehlgeschlagen: '+e.message,true)}};line.append(link)}if(d.type==='haos'){const edit=E('button','Bearbeiten','secondary');edit.onclick=()=>openHAEditor(d);line.append(edit)}line.append(picker,del);ds.append(line);const summary=E('div','','device-row'),badge=E('span',status?.failed?.[d.id]>=cfg.failures?'Offline':'Online','pill');summary.append(E('strong',d.id),E('span',detail.textContent),badge);ss.append(summary)}if(!cfg.devices.length)ss.append(E('p','Noch keine Geräte eingerichtet.','muted'));const previousWatch=$('watchDevice').value;$('watchDevice').replaceChildren(...cfg.devices.filter(d=>d.type!=='haos').map(d=>{const o=E('option',d.id);o.value=d.id;return o}));if(cfg.devices.some(d=>d.id===previousWatch&&d.type!=='haos'))$('watchDevice').value=previousWatch;$('state').textContent=t(status?.led_available?'LEDs bereit':'LED-Ausgabe nicht bereit')+' · '+(status?.last_poll?new Date(status.last_poll*1000).toLocaleTimeString() : t('Warte auf Messwerte'));document.querySelectorAll('[name=mode]').forEach(x=>x.checked=x.value===cfg.operation_mode);showMode();$('swap').checked=cfg.led_swap;$('revleft').checked=cfg.led_reverse[0];$('revright').checked=cfg.led_reverse[1];$('power').textContent=cfg.enabled?'Licht ausschalten':'Licht einschalten';$('brightness').value=cfg.brightness;$('bval').textContent=cfg.brightness+' %';$('effect').value='orientation';updateEffectDescription();$('night').checked=cfg.night.enabled;$('start').value=cfg.night.start;$('end').value=cfg.night.end;$('silentEnabled').checked=cfg.silent.enabled;$('silentDelay').value=cfg.silent.delay;$('interval').value=cfg.interval;$('failures').value=cfg.failures;const pal=$('palette');pal.replaceChildren();['Niedrig','Normal','Erhöht','Kritisch'].forEach((name,i)=>{const label=E('label',name+' ');const input=E('input');input.type='color';input.value=cfg.status_colors[i];input.oninput=()=>{cfg.status_colors[i]=input.value;markDirty();drawCase()};label.append(input);pal.append(label)});const th=$('thresholds');th.replaceChildren();const head=E('div','','threshold-row');['Messwert','Ab Normal','Ab Erhöht','Ab Kritisch'].forEach(x=>head.append(E('strong',x)));th.append(head);for(const metric of metrics){const div=E('div','','threshold-row');const cell=E('div');cell.append(E('strong',names[metric]));cell.append(E('div',metric==='temperature'?'°C':metric==='network'?'KiB/s':'%','unit'));div.append(cell);for(let i=0;i<3;i++){const n=E('input');n.type='number';n.step='0.1';n.setAttribute('aria-label',names[metric]+' Grenzwert '+(i+1));n.value=cfg.thresholds[metric][i];n.onchange=()=>{cfg.thresholds[metric][i]=Number(n.value);markDirty()};div.append(n)}th.append(div)}selectLed(selected.row,selected.side)}
function showMode(){const mode=document.querySelector('[name=mode]:checked')?.value||'both';$('ledSection').hidden=!['led','both'].includes(mode);$('mailSection').hidden=!['mail','both'].includes(mode);document.querySelectorAll('.steps a').forEach(a=>a.hidden=(a.hash==='#ledSection'&&$('ledSection').hidden)||(a.hash==='#mailSection'&&$('mailSection').hidden))}document.querySelectorAll('[name=mode]').forEach(x=>x.onchange=showMode);document.querySelectorAll('[name=mode]').forEach(x=>x.addEventListener('change',()=>{cfg.operation_mode=x.value;markDirty();showMode();updateWizard()}));
const effectDescriptions={orientation:'Orientierungstest: Nur links oben leuchtet grün, rechts oben rot. Alle anderen LEDs bleiben aus.',reactor:'Warp-Reaktor: Laufender Lichteffekt über die LED-Streifen.',rainbow:'Regenbogen: Wechselnde Regenbogenfarben.',comet:'Komet: Ein Lichtpunkt zieht mit Nachleuchten über die LEDs.',scanner:'Scanner: Ein Lichtpunkt bewegt sich hin und her.',breathing:'Atmen: Die Helligkeit steigt und sinkt langsam.',sparkle:'Sternenfunkeln: Einzelne LEDs funkeln.',meteor:'Meteor: Ein Lichtschweif bewegt sich über die LEDs.',dual_chase:'Lichtjagd: Lichtpunkte laufen über beide Streifen.'};
function updateEffectDescription(){$('effectDescription').textContent=effectDescriptions[$('effect').value]||''}
$('effect').addEventListener('change',updateEffectDescription);
for(const id of ['swap','revleft','revright','night','start','end','silentEnabled','silentDelay','interval','failures','effect','brightness'])$(id).addEventListener('change',markDirty);
$('power').onclick=()=>{cfg.enabled=!cfg.enabled;$('power').textContent=cfg.enabled?'Licht ausschalten':'Licht einschalten';markDirty()};
$('test').onclick=async()=>{try{await api('/api/test','POST',{effect:$('effect').value,swap:$('swap').checked,reverse:[$('revleft').checked,$('revright').checked]});notice('Lichttest läuft')}catch(e){notice(e.message,true)}};$('stoptest').onclick=async()=>{try{await api('/api/test/stop','POST',{});notice('Lichttest gestoppt')}catch(e){notice(e.message,true)}};
$('brightness').oninput=()=>{$('bval').textContent=$('brightness').value+' %';cfg.brightness=Number($('brightness').value);markDirty()};
const haMetricLabels={cpu:'CPU-Auslastung',temperature:'Temperatur',ram:'RAM-Auslastung',disk:'Speicherplatz',network:'Netzwerk'};
let haEditorDevice=null;
function haUrl(d){return (d.scheme||'http')+'://'+d.host+':'+d.port}
function revealManual(){ $('manualFields').hidden=false; }
$('manualToggle').onclick=()=>{ $('manualFields').hidden=!$('manualFields').hidden; };
function setDeviceType(){const ha=$('devtype').value==='haos';$('haFields').hidden=!ha;$('devhost').placeholder=ha?'http://homeassistant.local:8123':'IP oder Hostname';$('devhost').classList.toggle('ha-url',ha);if(ha&&!$('devhost').value.trim())$('devhost').value='http://homeassistant.local:8123';if(!ha&&$('devhost').value==='http://homeassistant.local:8123')$('devhost').value='';$('devname').placeholder=ha?'Gerätename (optional)':'Geräte-ID'}
$('devtype').onchange=setDeviceType;setDeviceType();
function parseHAUrl(text){const u=new URL(text);if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password||u.pathname!=='/'||u.search||u.hash)throw Error('Vollständige Home-Assistant-Adresse eingeben, z. B. http://homeassistant.local:8123');return {host:u.hostname,port:Number(u.port)||(u.protocol==='https:'?443:80),scheme:u.protocol.slice(0,-1)}}
function makeHASelects(device,states){const box=$('haSensorFields');box.replaceChildren();const units={cpu:'%',temperature:'°C',ram:'%',disk:'%',network:'KiB/s'};for(const metric of metrics){const label=E('label',haMetricLabels[metric],'field'),sel=E('select');sel.dataset.metric=metric;const options=[['','Automatisch erkennen / nicht verfügbar'],...states.filter(x=>x.unit===units[metric]).map(x=>[x.entity_id,x.name+' · '+x.entity_id])];for(const [id,name] of options){const o=E('option',name);o.value=id;sel.append(o)}const current=device.entities?.[metric]||'';if(current&&!options.some(x=>x[0]===current)){const o=E('option',current+' (bisherige Zuordnung)');o.value=current;sel.append(o)}sel.value=current;label.append(sel);box.append(label)}}
async function openHAEditor(d){haEditorDevice=d.id;$('haEditUrl').value=haUrl(d);$('haEditToken').value='';$('haEditorTitle').textContent=d.id+' · Home-Assistant-Sensoren';$('haEditor').hidden=false;try{const j=await api('/api/ha/inspect','POST',{url:haUrl(d),device_id:d.id});makeHASelects(d,j.sensors||[])}catch(e){makeHASelects(d,[]);notice('Sensorliste nicht abrufbar: '+e.message,true)}$('haEditor').scrollIntoView({behavior:'smooth',block:'center'})}
$('haRefresh').onclick=async()=>{const d=cfg.devices.find(x=>x.id===haEditorDevice);if(!d)return;try{parseHAUrl($('haEditUrl').value.trim());const j=await api('/api/ha/inspect','POST',{url:$('haEditUrl').value.trim(),token:$('haEditToken').value.trim(),device_id:d.id});makeHASelects(d,j.sensors||[]);notice('Verbindung erfolgreich')}catch(e){notice(e.message,true)}};
$('haCancel').onclick=()=>{$('haEditor').hidden=true;haEditorDevice=null};
$('haApply').onclick=async()=>{const d=cfg.devices.find(x=>x.id===haEditorDevice);if(!d)return;let parsed;try{parsed=parseHAUrl($('haEditUrl').value.trim());if($('haEditToken').value.trim()||haUrl(d)!==$('haEditUrl').value.trim()){await api('/api/ha/inspect','POST',{url:$('haEditUrl').value.trim(),token:$('haEditToken').value.trim(),device_id:d.id})}}catch(e){notice(e.message,true);return}Object.assign(d,parsed);if($('haEditToken').value.trim())d.token=$('haEditToken').value.trim();d.entities={};for(const sel of $('haSensorFields').querySelectorAll('select'))d.entities[sel.dataset.metric]=sel.value;$('haEditor').hidden=true;haEditorDevice=null;save()};
$('add').onclick=async()=>{const ha=$('devtype').value==='haos',raw=$('devhost').value.trim();let id=$('devname').value.trim(),entry;try{if(ha){const u=parseHAUrl(raw),token=$('haToken').value.trim();if(!token)throw Error('HA-Zugriffstoken eingeben');$('add').disabled=true;const probe=await api('/api/ha/inspect','POST',{url:raw,token});if(!id)id=(probe.name||'homeassistant').toLowerCase().replace(/[^a-z0-9_-]+/g,'_').slice(0,48)||'homeassistant';entry={id,...u,type:'haos',token,entities:{}}}else{if(!id||!raw)throw Error('Geräte-ID und Host eingeben');const code=prompt('Kopplungscode vom Agent eingeben (sudo sboc-pairing-code):');if(!code)throw Error('Kopplung abgebrochen');const result=await api('/api/agent/pair','POST',{host:raw,port:8765,code:code.trim()});entry={id,host:raw,port:8765,type:'agent',agent_identity:result.agent_identity}}if(!/^[a-zA-Z0-9_-]{1,48}$/.test(id))throw Error('Gerätename: nur Buchstaben, Zahlen, _ und - (max. 48)');if(cfg.devices.some(d=>d.id===id))throw Error('Geräte-ID bereits vorhanden');cfg.devices.push(entry);$('devname').value='';$('haToken').value='';save();notice('Gerät hinzugefügt. Bitte Alles speichern wählen.')}catch(e){notice(e.message,true)}finally{$('add').disabled=false}};
$('discover').onclick=async()=>{try{const found=(await api('/api/discover')).devices,container=$('found');container.replaceChildren();const seen=new Set();for(const d of found){const key=d.name+':'+d.port;if(seen.has(key))continue;seen.add(key);const line=E('div','','device-row');line.append(E('span',d.name+' · '+d.host+':'+d.port));const b=E('button','Übernehmen');b.onclick=async()=>{const id=d.name.toLowerCase().replace(/[^a-z0-9_-]/g,'_').slice(0,48);if(cfg.devices.some(x=>x.id===id))return notice('Gerät bereits vorhanden',true);try{const code=prompt('Kopplungscode für '+d.name+' eingeben (auf Agent: sudo sboc-pairing-code):');if(!code)return;const result=await api('/api/agent/pair','POST',{host:d.host,port:d.port,code:code.trim()});cfg.devices.push({id,host:d.host,port:d.port,type:'agent',agent_identity:result.agent_identity});save()}catch(e){notice('Kopplung fehlgeschlagen: '+e.message,true)}};line.append(b);container.append(line)}if(!found.length){container.append(E('p','Keine neuen Agents gefunden. Du kannst ein Gerät manuell hinzufügen.'))}}catch(e){notice(e.message,true)}};
$('loadCatalog').onclick=async()=>{try{const id=$('watchDevice').value;if(!id)return;const j=await api('/api/catalog?device='+encodeURIComponent(id)),w=cfg.watches[id]||{services:[],containers:[]},c=$('catalog');c.replaceChildren();for(const [kind,items] of [['services',j.catalog.services||[]],['containers',Object.entries(j.catalog.containers||{}).flatMap(([r,names])=>names.map(n=>r+':'+n))]]){c.append(E('h3',kind==='services'?'Systemdienste':'Container'));for(const name of items){const l=E('label',name,'device-row'),check=document.createElement('input');check.type='checkbox';check.dataset.kind=kind;check.dataset.name=name;check.checked=w[kind].includes(name);l.append(check);c.append(l)}}}catch(e){notice(e.message,true)}};function collectWatches(){const id=$('watchDevice').value;if(!id)return;cfg.watches[id]={services:[],containers:[]};for(const input of $('catalog').querySelectorAll('input:checked'))cfg.watches[id][input.dataset.kind].push(input.dataset.name);markDirty()};
function renderAlarms(){
 const host=$('activeAlarms');if(!host)return;
 host.replaceChildren();const alarms=status?.active_alarms||[];
 if(!alarms.length){host.append(E('p','Keine aktiven Alarme','muted'));return}
 for(const a of alarms){
  const row=E('div','','device-row'),info=E('div','','device-info');
  info.append(E('strong',a.device+' · '+a.kind));
  const led=a.rows.length?'LED-Zeilen '+a.rows.join(', '):'Keine LED-Zuordnung';
  info.append(E('small',led+' · seit '+new Date(a.since*1000).toLocaleString()+(a.acknowledged?' · quittiert':a.silent_trigger?' · Silent Mode ausgelöst':' · aktiv')));
  row.append(info);
  if(!a.acknowledged){
   const button=E('button','Quittieren','secondary');
   button.onclick=async()=>{try{await api('/api/alerts/ack','POST',{device:a.device,kind:a.kind,since:a.since});status=await api('/api/status');renderAlarms();drawCase()}catch(e){notice(e.message,true)}};
   row.append(button);
  }
  host.append(row);
 }
}
$('loadEvents').onclick=async()=>{try{const ev=(await api('/api/events')).events;$('events').replaceChildren(...ev.map(x=>E('div',new Date(x.ts*1000).toLocaleString()+' · '+x.device+' · '+x.kind+' · '+x.phase,'device-row')))}catch(e){notice(e.message,true)}};
function mailForm(){return {enabled:$('mailEnabled').checked,host:$('mailHost').value,port:Number($('mailPort').value),mode:$('mailMode').value,username:$('mailUser').value,password:$('mailPassword').value,sender:$('mailSender').value,recipient:$('mailRecipient').value,delay:Number($('mailDelay').value),recovery:$('mailRecovery').checked}}document.querySelectorAll('#mailSection input,#mailSection select').forEach(x=>x.addEventListener('change',markDirty));$('mailTest').onclick=async()=>{try{await api('/api/mail/test','POST',{});notice('Testmail versendet')}catch(e){notice(e.message,true)}};

const sectionIds=['devicesSection','modeSection','ledSection','mailSection','systemSection'];
function activeSections(){const m=document.querySelector('[name=mode]:checked')?.value||cfg.operation_mode;return sectionIds.filter(id=>(id!=='ledSection'||['led','both'].includes(m))&&(id!=='mailSection'||['mail','both'].includes(m)))}
function updateWizard(){
 document.body.classList.toggle('wizard-mode',wizard);
 if(!wizard)return;
 document.body.classList.remove('config-mode');
 const visible=activeSections(),position=Math.min(wizardStep,visible.length-1);
 for(const id of sectionIds){const s=$(id),idx=visible.indexOf(id);s.classList.toggle('wizard-hidden',idx<0||idx>position);s.classList.toggle('wizard-complete',idx>=0&&idx<position);const footer=s.querySelector('.wizard-footer');footer.hidden=idx!==position;footer.querySelector('button').textContent=position===visible.length-1?'Einrichtung abschließen':'Einstellungen übernehmen'}
 document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page==='config'));
 $('page-status').classList.remove('active');$('page-config').classList.add('active');$('wizardIntro').hidden=false;
}
document.querySelectorAll('.wizard-next').forEach(b=>b.onclick=async()=>{
 const active=activeSections(),index=active.indexOf(b.closest('section').id);
 if(index<0)return;
 if(index===0&&cfg.devices.length===0){notice('Bitte zuerst mindestens ein Gerät hinzufügen.',true);return}
 if(index===0&&$('catalog').querySelectorAll('input[type=checkbox]').length)collectWatches();
 cfg.setup_step=Math.min(index+1,4);cfg.setup_complete=index===active.length-1;
 if(!(await persistAll()))return;
 if(cfg.setup_complete){wizard=false;updateWizard();$('wizardIntro').hidden=true;document.querySelector('[data-page="status"]').click();notice('Einrichtung abgeschlossen')}
 else{wizardStep=index+1;updateWizard();const next=$(active[index+1]);next?.scrollIntoView({behavior:'smooth',block:'start'})}
});
window.addEventListener('beforeunload',e=>{if(dirty&&!wizard){e.preventDefault();e.returnValue=''}});
$('saveLanguage').onclick=async()=>{try{const result=await api('/api/user/language','POST',{language:$('userLanguage').value});applyLanguage(result.language);if(cfg)draw();notice(t('Language saved'))}catch(e){notice(e.message,true)}};
$('passwordForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/user/password','POST',{current:$('currentPassword').value,password:$('newPassword').value,confirmation:$('confirmPassword').value});$('passwordForm').reset();alert(t('Password changed. Please sign in again.'));location.reload()}catch(err){notice(err.message,true)}};
async function init(){try{const prefs=await api('/api/user');$('userLanguage').value=prefs.language;applyLanguage(prefs.language);status=await api('/api/status');cfg=status.config;wizard=!cfg.setup_complete;wizardStep=cfg.setup_step||0;draw();updateWizard();const m=(await api('/api/mail')).settings;for(const [id,v] of [['mailEnabled',m.enabled],['mailHost',m.host],['mailPort',m.port],['mailMode',m.mode],['mailUser',m.username],['mailSender',m.sender],['mailRecipient',m.recipient],['mailDelay',m.delay],['mailRecovery',m.recovery]])if(v!==undefined){if(id==='mailEnabled'||id==='mailRecovery')$(id).checked=v;else $(id).value=v};$('loadEvents').click();renderAlarms()}catch(e){notice(e.message,true)}}$('logout').onclick=async()=>{await api('/api/logout','POST',{});location.reload()};init();setInterval(async()=>{try{status=await api('/api/status');$('state').textContent=t(status.led_available?'LEDs bereit':'LED-Ausgabe nicht bereit')+' · '+new Date().toLocaleTimeString();renderAlarms();drawCase()}catch(e){}},5000);
</script></body></html>'''
AUTH_HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SBOC.</title><link rel="icon" type="image/png" href="/assets/m3ro-favicon.png"><style>
@font-face{font-family:'Sora';src:url('/assets/fonts/Sora-Regular.ttf') format('truetype');font-weight:400;font-display:swap}
@font-face{font-family:'Sora';src:url('/assets/fonts/Sora-SemiBold.ttf') format('truetype');font-weight:600;font-display:swap}
@font-face{font-family:'Sora';src:url('/assets/fonts/Sora-Bold.ttf') format('truetype');font-weight:700;font-display:swap}
@font-face{font-family:'Sora';src:url('/assets/fonts/Sora-ExtraBold.ttf') format('truetype');font-weight:800;font-display:swap}
*{box-sizing:border-box}
body{font-family:Sora,system-ui,sans-serif;background:#f7f7f3;color:#0c0c0b;margin:0;min-height:100vh}
.auth-wrap{min-height:100vh}
.auth-wrap main{max-width:420px;margin:12vh auto 0;padding:24px}
.auth-wrap main h1{font-size:54px;font-weight:800;letter-spacing:.035em;line-height:normal;margin:0 0 28px;text-align:left}
.auth-wrap label{display:block;font-size:16px;font-weight:600;margin:14px 0}
.auth-wrap [hidden]{display:none!important}
.auth-wrap input{display:block;width:100%;box-sizing:border-box;padding:11px;margin-top:6px;border:1px solid #8e8e87;border-radius:0;background:#fff;font:inherit}
.auth-wrap button{padding:11px 18px;background:#0c0c0b;color:#fff;border:1px solid #0c0c0b;border-radius:0;font:inherit;cursor:pointer}
#setup-note{font-size:15px;color:#62625d;margin:0 0 20px}
#error{color:#b42318;font-size:15px}
.m3ro-signature{position:absolute;top:calc(76vh + 110px);left:50%;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:2px}
.m3ro{display:block;width:64px;height:auto;object-fit:contain}
.sboc-version{font-size:12px;color:#888}
@media(max-height:640px){.m3ro-signature{position:static;transform:none;margin:130px auto 35px}}
@media(max-width:480px){
 .auth-wrap{min-height:100vh;min-height:100dvh;display:flex;flex-direction:column}
 .auth-wrap main{width:100%;margin:0 auto;padding:clamp(28px,7vh,64px) 20px 18px;flex:0 0 auto}
 .auth-wrap main h1{font-size:clamp(38px,12vw,54px)}
 .m3ro-signature{position:static;top:auto;left:auto;transform:none;margin:auto auto 0;padding:20px 0 max(18px,env(safe-area-inset-bottom));flex:0 0 auto}
}
@media(max-width:480px) and (max-height:650px){
 .auth-wrap main{padding-top:18px}
 .auth-wrap main h1{margin-bottom:16px}
 .m3ro-signature{padding-top:12px}
}
</style></head><body><div class="auth-wrap"><main><h1>SBOC.</h1><p id="setup-note" hidden>Administratorkonto anlegen. Passwort mindestens 12 Zeichen. Einrichtungscode auf dem Controller mit <code>sudo sboc-setup-code</code> anzeigen.</p><label id="setup-code-field" hidden>Setup code<input id="setup-code" autocomplete="off"></label><form id="form"><label>Username<input id="username" required minlength="3" maxlength="48" autocomplete="username"></label><label>Password<input id="password" type="password" required minlength="12" autocomplete="current-password"></label><button id="submit">Sign in</button></form><p id="error" role="alert"></p></main><div class="m3ro-signature"><img class="m3ro" src="/assets/m3ro-gray.png" alt="M3ro"><span class="sboc-version" style="font-size:12px;color:#888">Version @@VERSION@@</span></div></div><script>const setup='@@MODE@@'==='setup';document.getElementById('submit').textContent=setup?'Create account':'Sign in';document.getElementById('setup-note').hidden=!setup;document.getElementById('setup-code-field').hidden=!setup;if(!setup)document.getElementById('password').minLength=1;document.getElementById('form').onsubmit=async e=>{e.preventDefault();const submit=document.getElementById('submit');submit.disabled=true;try{const r=await fetch(setup?'/api/setup':'/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value,setup_code:document.getElementById('setup-code').value})});const j=await r.json();if(!r.ok)throw Error(j.error||'Error');location.reload()}catch(e){document.getElementById('error').textContent=e.message}finally{submit.disabled=false}};</script></html>'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='/var/lib/sboc/config.json');p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8088);p.add_argument('--simulate',action='store_true');args=p.parse_args()
    controller=Controller(args.config,args.simulate)
    class Handler(BaseHTTPRequestHandler):
        failures={}
        def cookie(self):
            for part in self.headers.get('Cookie','').split(';'):
                if part.strip().startswith('sbc_session='): return part.strip().split('=',1)[1]
            return ''
        def authed(self): return controller.store.user(self.cookie()) is not None
        def origin_ok(self):
            origin=self.headers.get('Origin')
            if not origin: return False
            return urllib.parse.urlparse(origin).netloc==self.headers.get('Host') and urllib.parse.urlparse(origin).scheme=='http'
        def headers_common(self):
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        def send(self,obj,status=200,cookie=None):
            payload=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.headers_common()
            if cookie is not None:self.send_header('Set-Cookie',cookie)
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def page(self,content):
            payload=content.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.headers_common();self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            path=urllib.parse.urlparse(self.path).path
            if path.startswith('/assets/fonts/') and path.split('/')[-1] in ('Sora-Regular.ttf','Sora-SemiBold.ttf','Sora-Bold.ttf','Sora-ExtraBold.ttf'):
                from pathlib import Path
                font_path=Path(__file__).resolve().parent/'assets'/'fonts'/path.split('/')[-1]
                if not font_path.is_file(): self.send_error(404); return
                payload=font_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','font/ttf')
                self.send_header('Cache-Control','public, max-age=86400')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif path in ('/assets/m3ro-gray.png','/assets/m3ro-favicon.png','/favicon.ico'):
                name='m3ro-gray.png' if path.endswith('gray.png') else 'm3ro-favicon.png'
                from pathlib import Path
                payload=(Path(__file__).resolve().parent/'assets'/name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','image/png')
                self.send_header('Cache-Control','public, max-age=3600')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif path=='/':
                if not controller.store.configured():self.page(AUTH_HTML.replace('@@MODE@@','setup').replace('@@VERSION@@',APP_VERSION))
                elif not self.authed():self.page(AUTH_HTML.replace('@@MODE@@','login').replace('@@VERSION@@',APP_VERSION))
                else:self.page(HTML.replace('@@VERSION@@',APP_VERSION))
            elif path=='/api/user' and self.authed():self.send({'language':controller.store.language(controller.store.user(self.cookie()))})
            elif path=='/api/status' and self.authed():self.send(controller.status())
            elif path=='/api/events' and self.authed():self.send({'events':controller.store.events()})
            elif path=='/api/mail' and self.authed():
                settings=controller.store.mail();settings.pop('password',None);self.send({'settings':settings})
            elif path=='/api/catalog' and self.authed():
                ident=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('device',[''])[0]
                d=next((x for x in controller.cfg['devices'] if x['id']==ident),None)
                if not d:self.send({'error':'Gerät unbekannt'},404);return
                if d.get('type')=='haos':self.send({'error':'Home Assistant OS stellt hier keine Agent-Dienste oder Container bereit.'},400);return
                try:
                    key=controller.agent_keys.get(d.get('agent_identity',''))
                    if not key:raise ValueError('Agent nicht gekoppelt')
                    catalog=secure_request(d['host'],d['port'],U(key),'/catalog')
                    self.send({'catalog':catalog})
                except Exception as e:self.send({'error':'Agent nicht erreichbar: '+str(e)},502)
            elif path=='/api/discover' and self.authed():self.send({'devices':discovery()})
            else:self.send({'error':'Nicht angemeldet' if not self.authed() else 'Nicht gefunden'},401 if not self.authed() else 404)
        def do_POST(self):
            try:
                if not self.origin_ok():self.send({'error':'Ungültiger Ursprung'},403);return
                size=int(self.headers.get('Content-Length','0'))
                if size<0 or size>100000:self.send({'error':'Ungültige Größe'},413);return
                obj=json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(obj,dict):raise ValueError('JSON-Objekt erwartet')
                path=urllib.parse.urlparse(self.path).path
                if path=='/api/setup':
                    controller.store.setup(obj.get('username'),obj.get('password'),obj.get('setup_code'));self.send({'ok':True});return
                if path=='/api/login':
                    ip=self.client_address[0];now=time.monotonic()
                    # Keep the in-memory throttle bounded under rotating source IPs.
                    if len(self.failures)>=1024:
                        self.failures={k:recent for k,v in self.failures.items() if (recent:=[t for t in v if now-t<300])}
                        if len(self.failures)>=1024:
                            # Evict the oldest entry; do not reset all limits.
                            oldest=min(self.failures,key=lambda k:self.failures[k][-1])
                            self.failures.pop(oldest,None)
                    attempts=[t for t in self.failures.get(ip,[]) if now-t<300]
                    if len(attempts)>=5:self.send({'error':'Zu viele Versuche. Bitte später erneut versuchen.'},429);return
                    token=controller.store.login(obj.get('username',''),obj.get('password',''))
                    if not token:
                        attempts.append(now);self.failures[ip]=attempts;self.send({'error':'Anmeldung fehlgeschlagen'},401);return
                    self.failures.pop(ip,None)
                    self.send({'ok':True},cookie=f'sbc_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200');return
                if not self.authed():self.send({'error':'Nicht angemeldet'},401);return
                if path=='/api/user/language':
                    controller.store.set_language(controller.store.user(self.cookie()),obj.get('language'));self.send({'language':obj.get('language')})
                elif path=='/api/user/password':
                    controller.store.change_password(controller.store.user(self.cookie()),obj.get('current'),obj.get('password'),obj.get('confirmation'));self.send({'ok':True},cookie='sbc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                elif path=='/api/logout':controller.store.logout(self.cookie());self.send({'ok':True},cookie='sbc_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                elif path=='/api/ha/inspect':
                    try:
                        address=urllib.parse.urlsplit(obj.get('url',''))
                        if address.scheme not in ('http','https') or not address.hostname or address.username or address.password or address.path not in ('','/') or address.query or address.fragment: raise ValueError('Vollständige HA-Adresse mit http:// oder https:// eingeben')
                        token=obj.get('token','')
                        if not token and obj.get('device_id'):
                            with controller.lock:
                                dev=next((d for d in controller.cfg['devices'] if d['id']==obj['device_id'] and d.get('type')=='haos'),None)
                                token=dev.get('token','') if dev else ''
                        if not token:raise ValueError('Zugriffstoken eingeben')
                        lan_host(address.hostname,address.port or (443 if address.scheme=='https' else 80))
                        self.send(inspect_ha(address.scheme, address.hostname, address.port or (443 if address.scheme=='https' else 80), token))
                    except Exception as e:self.send({'error':'Home Assistant: '+str(e)},400)
                elif path=='/api/alerts/ack':
                    device=obj.get('device');kind=obj.get('kind');since=obj.get('since')
                    if not isinstance(device,str) or not isinstance(kind,str) or type(since)!=int:raise ValueError('Ungültige Alarmkennung')
                    if controller.store.acknowledge(device,kind,since):self.send({'ok':True})
                    else:self.send({'error':'Alarm nicht mehr aktiv oder bereits quittiert'},409)
                elif path=='/api/config':controller.update(obj);self.send({'config':controller.public_config()})
                elif path=='/api/agent/pair':self.send({'agent_identity':controller.pair(obj)})
                elif path=='/api/test':
                    effect=obj.get('effect',controller.cfg['test_effect'])
                    swap=obj.get('swap',controller.cfg['led_swap'])
                    reverse=obj.get('reverse',controller.cfg['led_reverse'])
                    if effect not in EFFECTS or type(swap)!=bool or not isinstance(reverse,list) or len(reverse)!=2 or any(type(v)!=bool for v in reverse):raise ValueError('Ungültiger Lichttest')
                    with controller.lock:
                        controller.test_effect=effect
                        controller.test_orientation={'swap':swap,'reverse':reverse}
                        controller.test_started=time.monotonic()
                    self.send({'ok':True})
                elif path=='/api/test/stop':
                    with controller.lock:controller.test_started=None;controller.test_effect=None;controller.test_orientation=None
                    self.send({'ok':True})
                elif path=='/api/mail':
                    current=controller.store.mail()
                    if not obj.get('password'):obj['password']=current.get('password','')
                    if obj.get('mode') not in ('starttls','ssl') or type(obj.get('port'))!=int or not 1<=obj['port']<=65535 or type(obj.get('delay'))!=int or not 0<=obj['delay']<=86400:raise ValueError('SMTP-Konfiguration ungültig')
                    for key in ('host','username','sender','recipient','password'):
                        if not isinstance(obj.get(key,''),str) or len(obj.get(key,''))>256:raise ValueError('Ungültiges SMTP-Feld')
                    validate_address(obj.get('sender',''), 'Absender')
                    validate_address(obj.get('recipient',''), 'Empfänger')
                    controller.store.set_mail(obj);self.send({'ok':True})
                elif path=='/api/mail/test':
                    settings=controller.store.mail()
                    try:
                        send_mail(settings,'SBOC. – Testnachricht','SMTP-Versand funktioniert.')
                    except ValueError:
                        raise
                    except Exception as exc:
                        print('SMTP-Test fehlgeschlagen:',type(exc).__name__,flush=True)
                        self.send({'error':mail_error(exc)},502)
                    else:
                        self.send({'ok':True})
                else:self.send({'error':'Nicht gefunden'},404)
            except (ValueError,TypeError,KeyError) as e:self.send({'error':str(e)},400)
            except Exception as e:self.send({'error':'Serverfehler'},500);print('HTTP error:',e,flush=True)
        def log_message(self,*args):pass
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=='__main__':main()
