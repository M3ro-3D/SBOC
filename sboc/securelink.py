"""Certificate-free authenticated X25519 pairing and AES-GCM transport."""
import base64, hashlib, hmac, json, os, secrets, threading, time
from pathlib import Path
from urllib.request import Request
from .network_policy import lan_urlopen
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

B=lambda v: base64.b64encode(v).decode('ascii')
U=lambda v: base64.b64decode(v, validate=True)
def canonical(v): return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def mac(key, payload): return hmac.new(key,payload,hashlib.sha256).digest()
def derive(shared, code, salt): return HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,info=b'SBOC-pair-v1:'+code.encode()).derive(shared)
from cryptography.hazmat.primitives import hashes

def pub(priv): return priv.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
def endpoint(host, port, path):
    # Bracket IPv6 literals when constructing URLs.
    return f'http://[{host}]:{port}{path}' if ":" in host else f'http://{host}:{port}{path}'

def request(url, obj):
    data=canonical(obj)
    with lan_urlopen(Request(url,data=data,headers={'Content-Type':'application/json'},method='POST'),timeout=6) as r:
        return json.loads(r.read(250000))

def pair(host,port,code):
    if not isinstance(code,str) or len(code)!=6 or not code.isascii() or not code.isdigit(): raise ValueError('Sechsstelligen Kopplungscode eingeben')
    private=X25519PrivateKey.generate(); cp=pub(private); challenge=secrets.token_bytes(16)
    a=request(endpoint(host,port,'/pair/start'),{'public':B(cp),'challenge':B(challenge)})
    ap=U(a['public']); salt=U(a['salt']); ident=a['id']; ticket=a['ticket']
    key=derive(private.exchange(X25519PublicKey.from_public_bytes(ap)),code,salt)
    transcript=b'SBOC-pair-v1'+cp+ap+challenge+salt+ident.encode()
    if not hmac.compare_digest(U(a['proof']),mac(key,b'agent'+transcript)):raise ValueError('Kopplungscode falsch oder Agent nicht vertrauenswürdig')
    proof=B(mac(key,b'controller'+transcript))
    r=request(endpoint(host,port,'/pair/finish'),{'ticket':ticket,'proof':proof})
    if not r.get('ok'):raise ValueError('Kopplung fehlgeschlagen')
    return ident,key

def secure_request(host,port,key,path,query=None):
    nonce=os.urandom(12)
    body=canonical({'path':path,'query':query or {}})
    payload={'nonce':B(nonce),'data':B(AESGCM(key).encrypt(nonce,body,b'SBOC-request-v1'))}
    r=request(endpoint(host,port,'/secure'),payload)
    reply=json.loads(AESGCM(key).decrypt(U(r['nonce']),U(r['data']),b'SBOC-response-v1'+nonce))
    return reply

class AgentTrust:
    def __init__(self,path):
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.pending={};self.seen={};self.failures=[]
        self.codefile=self.path/'pairing.json';self.keyfile=self.path/'trust.json'
        if not self.codefile.exists():self._write(self.codefile,{'code':f'{secrets.randbelow(1000000):06d}','id':secrets.token_hex(16)})
        self.pairinfo=json.loads(self.codefile.read_text());self.keys=json.loads(self.keyfile.read_text()) if self.keyfile.exists() else {}
    @staticmethod
    def _write(path,data):
        tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(data,f)
        os.replace(tmp,path)
    def start(self,obj):
        with self.lock:
            now=time.monotonic();self.failures=[x for x in self.failures if now-x<300]
            if len(self.failures)>=10:raise ValueError('Kopplung vorübergehend gesperrt')
            self.failures.append(now)
            cp=U(obj['public']);challenge=U(obj['challenge'])
            if len(cp)!=32 or len(challenge)!=16:raise ValueError('Ungültige Kopplungsdaten')
            private=X25519PrivateKey.generate();ap=pub(private);salt=os.urandom(16)
            key=derive(private.exchange(X25519PublicKey.from_public_bytes(cp)),self.pairinfo['code'],salt)
            ident=self.pairinfo['id'];transcript=b'SBOC-pair-v1'+cp+ap+challenge+salt+ident.encode()
            ticket=secrets.token_urlsafe(24)
            self.pending={ticket:(key,transcript,now)}
            return {'public':B(ap),'salt':B(salt),'id':ident,'ticket':ticket,'proof':B(mac(key,b'agent'+transcript))}
    def finish(self,obj):
        with self.lock:
            key,transcript,ts=self.pending.pop(obj['ticket'])
            if time.monotonic()-ts>120 or not hmac.compare_digest(U(obj['proof']),mac(key,b'controller'+transcript)):
                raise ValueError('Ungültige Kopplung')
            self.keys={'key':B(key)};self._write(self.keyfile,self.keys)
            self.pairinfo['code']=f'{secrets.randbelow(1000000):06d}';self._write(self.codefile,self.pairinfo)
            return {'ok':True}
    def decrypt(self,obj):
        with self.lock:
            if not self.keys:raise PermissionError('Agent noch nicht gekoppelt')
            key=U(self.keys['key']);nonce=U(obj['nonce'])
            if len(nonce)!=12:raise ValueError('Ungültiger Nonce')
            now=time.monotonic();self.seen={n:t for n,t in self.seen.items() if now-t<300}
            if nonce in self.seen:raise ValueError('Wiederholte Anfrage')
            request=json.loads(AESGCM(key).decrypt(nonce,U(obj['data']),b'SBOC-request-v1'))
            if request.get('path') not in ('/metrics','/catalog'):raise ValueError('Unbekannte Anfrage')
            self.seen[nonce]=now
            return request,key,nonce
    @staticmethod
    def encrypt(key,request_nonce,obj):
        nonce=os.urandom(12)
        return {'nonce':B(nonce),'data':B(AESGCM(key).encrypt(nonce,canonical(obj),b'SBOC-response-v1'+request_nonce))}
