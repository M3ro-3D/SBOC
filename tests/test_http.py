import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

class HTTPIntegration(unittest.TestCase):
    def test_controller_first_run_and_auth(self):
        with tempfile.TemporaryDirectory() as d:
            port=18139
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).parents[1]))
            p=subprocess.Popen([sys.executable,'-m','sboc.controller','--simulate','--host','127.0.0.1','--port',str(port),'--config',d+'/config.json'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            base=f'http://127.0.0.1:{port}'
            def req(path,body=None,cookie=None,origin=True):
                headers={}
                if body is not None:headers['Content-Type']='application/json';headers['Origin']=base if origin else 'http://evil.example'
                if cookie:headers['Cookie']='sbc_session='+cookie
                r=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
                try:
                    with urlopen(r,timeout=3) as response:return response.status,dict(response.headers),response.read().decode()
                except HTTPError as e:return e.code,dict(e.headers),e.read().decode()
            try:
                for i in range(50):
                    try:
                        status,_,_=req('/');break
                    except URLError:time.sleep(.1)
                self.assertEqual(status,200)
                status,_,_=req('/api/status');self.assertEqual(status,401)
                code=(Path(d)/'setup-code').read_text().strip()
                status,_,_=req('/api/setup',{'username':'admin','password':'passwordpassword','setup_code':'bad'})
                self.assertEqual(status,400)
                status,_,_=req('/api/setup',{'username':'admin','password':'passwordpassword','setup_code':code},origin=False)
                self.assertEqual(status,403)
                status,_,_=req('/api/setup',{'username':'admin','password':'passwordpassword','setup_code':code})
                self.assertEqual(status,200)
                status,_,_=req('/api/setup',{'username':'evil','password':'passwordpassword','setup_code':code})
                self.assertEqual(status,400)
                status,_,_=req('/api/login',{'username':'admin','password':'wrong'})
                self.assertEqual(status,401)
                status,h,_=req('/api/login',{'username':'admin','password':'passwordpassword'})
                self.assertEqual(status,200)
                cookie=h['Set-Cookie'].split(';')[0].split('=',1)[1]
                status,_,payload=req('/api/status',cookie=cookie)
                self.assertEqual(status,200)
                self.assertEqual(json.loads(payload)['config']['operation_mode'],'both')
                status,_,_=req('/api/config',{'brightness':81},cookie=cookie)
                self.assertEqual(status,400)
                status,_,_=req('/api/logout',{},cookie=cookie)
                self.assertEqual(status,200)
                status,_,_=req('/api/status',cookie=cookie)
                self.assertEqual(status,401)
            finally:
                p.terminate()
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill()
                p.stderr.close()
