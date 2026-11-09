"""Local controller accounts, sessions and SQLite events."""
import hashlib, hmac, json, secrets, sqlite3, threading, time, os
from pathlib import Path

class Store:
    def __init__(self, path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.bootstrap_path=self.path.parent/'setup-code'
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS user_preferences (username TEXT PRIMARY KEY, language TEXT NOT NULL DEFAULT 'en');
            CREATE TABLE IF NOT EXISTS sessions (tokenhash TEXT PRIMARY KEY, username TEXT NOT NULL, expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, device TEXT NOT NULL, kind TEXT NOT NULL, phase TEXT NOT NULL, details TEXT);
            CREATE TABLE IF NOT EXISTS alerts (device TEXT NOT NULL, kind TEXT NOT NULL, active INTEGER NOT NULL, since INTEGER NOT NULL, notified INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(device,kind));
            CREATE TABLE IF NOT EXISTS mail_settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            ''')
        with self.lock,self.db() as db:
            cols={row[1] for row in db.execute('PRAGMA table_info(alerts)')}
            if 'acknowledged' not in cols:
                db.execute('ALTER TABLE alerts ADD COLUMN acknowledged INTEGER NOT NULL DEFAULT 0')
        self._ensure_bootstrap()
    def _ensure_bootstrap(self):
        # Existing installations remain configured and need no bootstrap code.
        if self.configured():
            self.bootstrap_path.unlink(missing_ok=True)
            return
        if not self.bootstrap_path.exists():
            code=secrets.token_urlsafe(24)
            fd=os.open(self.bootstrap_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:
                stream.write(code+'\n')
    def setup_code(self):
        return self.bootstrap_path.read_text().strip() if self.bootstrap_path.exists() else None
    def db(self):
        con=sqlite3.connect(str(self.path),timeout=10)
        con.execute('PRAGMA journal_mode=WAL')
        return con
    def configured(self):
        with self.lock,self.db() as db: return db.execute('SELECT EXISTS(SELECT 1 FROM accounts)').fetchone()[0]==1
    def setup(self,username,password,code=None):
        if not isinstance(code,str) or not self.setup_code() or not hmac.compare_digest(code,self.setup_code()):
            raise ValueError('Einrichtungscode ungültig (sudo sboc-setup-code)')
        if not isinstance(username,str) or not (3<=len(username)<=48) or not all(x.isalnum() or x in '_-.' for x in username): raise ValueError('Benutzername: 3–48 Zeichen, Buchstaben/Ziffern/_.-')
        if not isinstance(password,str) or len(password)<12 or len(password)>256: raise ValueError('Passwort: 12–256 Zeichen')
        salt=secrets.token_bytes(24); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
        with self.lock,self.db() as db:
            # UNIQUE index and immediate transaction prevent concurrent first-account creation.
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM accounts LIMIT 1').fetchone(): raise ValueError('Einrichtung bereits abgeschlossen')
            db.execute('INSERT INTO accounts VALUES(?,?,?)',(username,salt.hex(),digest.hex()))
        self.bootstrap_path.unlink(missing_ok=True)
    def login(self,username,password):
        with self.lock,self.db() as db:
            row=db.execute('SELECT salt,digest FROM accounts WHERE username=?',(username,)).fetchone()
            if not row: return None
            expected=bytes.fromhex(row[1]); actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(row[0]),600000)
            if not hmac.compare_digest(expected,actual): return None
            token=secrets.token_urlsafe(40); expires=int(time.time())+12*3600
            db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),username,expires))
            return token
    def user(self,token):
        if not token: return None
        with self.lock,self.db() as db:
            row=db.execute('SELECT username FROM sessions WHERE tokenhash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
            return row[0] if row else None
    def language(self, username):
        with self.lock,self.db() as db:
            row=db.execute('SELECT language FROM user_preferences WHERE username=?',(username,)).fetchone()
            return row[0] if row and row[0] in ('en','de') else 'en'
    def set_language(self, username, language):
        if language not in ('en','de'): raise ValueError('Unsupported language')
        with self.lock,self.db() as db:
            if not db.execute('SELECT 1 FROM accounts WHERE username=?',(username,)).fetchone(): raise ValueError('Account not found')
            db.execute('INSERT INTO user_preferences(username,language) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET language=excluded.language',(username,language))
    def change_password(self, username, current, new, confirmation):
        if not all(isinstance(x,str) for x in (current,new,confirmation)): raise ValueError('Invalid password')
        if not 12 <= len(new) <= 256: raise ValueError('New password must contain 12–256 characters')
        if new != confirmation: raise ValueError('New passwords do not match')
        with self.lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT salt,digest FROM accounts WHERE username=?',(username,)).fetchone()
            if not row: raise ValueError('Account not found')
            digest=hashlib.pbkdf2_hmac('sha256',current.encode(),bytes.fromhex(row[0]),600000)
            if not hmac.compare_digest(bytes.fromhex(row[1]),digest): raise ValueError('Current password is incorrect')
            salt=secrets.token_bytes(24)
            new_digest=hashlib.pbkdf2_hmac('sha256',new.encode(),salt,600000)
            db.execute('UPDATE accounts SET salt=?,digest=? WHERE username=?',(salt.hex(),new_digest.hex(),username))
            # Invalidate all other sessions; the current session is also invalidated.
            db.execute('DELETE FROM sessions WHERE username=?',(username,))
    def logout(self,token):
        with self.lock,self.db() as db: db.execute('DELETE FROM sessions WHERE tokenhash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    def transition(self,device,kind,active,details=''):
        now=int(time.time())
        with self.lock,self.db() as db:
            old=db.execute('SELECT active,since,notified FROM alerts WHERE device=? AND kind=?',(device,kind)).fetchone()
            if old and bool(old[0])==bool(active): return False
            if not old and not active: return False
            pending=(-1 if old and old[2]==1 else 1) if not active else 0
            db.execute('INSERT INTO alerts(device,kind,active,since,notified,acknowledged) VALUES(?,?,?,?,?,0) ON CONFLICT(device,kind) DO UPDATE SET active=excluded.active,since=excluded.since,notified=excluded.notified,acknowledged=0',(device,kind,int(active),now,pending))
            db.execute('INSERT INTO events(ts,device,kind,phase,details) VALUES(?,?,?,?,?)',(now,device,kind,'begin' if active else 'end',details))
            return True
    def alerts(self):
        with self.lock,self.db() as db:
            return [dict(zip(('device','kind','active','since','notified','acknowledged'),row)) for row in db.execute('SELECT device,kind,active,since,notified,acknowledged FROM alerts')]
    def acknowledge(self,device,kind,since):
        with self.lock,self.db() as db:
            cur=db.execute('UPDATE alerts SET acknowledged=1 WHERE device=? AND kind=? AND since=? AND active=1 AND acknowledged=0',(device,kind,since))
            if cur.rowcount:
                db.execute('INSERT INTO events(ts,device,kind,phase,details) VALUES(?,?,?,?,?)',(int(time.time()),device,kind,'acknowledged','User acknowledged alarm'))
            return cur.rowcount == 1
    def notified(self,device,kind):
        with self.lock,self.db() as db: db.execute('UPDATE alerts SET notified=1 WHERE device=? AND kind=?',(device,kind))
    def events(self,limit=200):
        with self.lock,self.db() as db:
            return [dict(zip(('ts','device','kind','phase','details'),row)) for row in db.execute('SELECT ts,device,kind,phase,details FROM events ORDER BY id DESC LIMIT ?', (min(limit,500),))]
    def mail(self):
        with self.lock,self.db() as db:
            row=db.execute('SELECT data FROM mail_settings WHERE id=1').fetchone()
            return json.loads(row[0]) if row else {}
    def set_mail(self,data):
        with self.lock,self.db() as db: db.execute('INSERT INTO mail_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(json.dumps(data),))
