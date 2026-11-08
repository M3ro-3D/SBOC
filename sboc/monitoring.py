"""Agent-side Linux diagnostics. Unavailable signals are explicitly None."""
import os, re, subprocess, time, json
from pathlib import Path

def command(args, timeout=3):
    try:
        p=subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return p.stdout if p.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired): return None

def snapshot_services():
    out=command(['systemctl','list-unit-files','--type=service','--no-legend','--no-pager'],8)
    if out is None: return None
    return sorted(set(x.split()[0] for x in out.splitlines() if x.split() and x.split()[0].endswith('.service')))[:1500]

def snapshot_containers():
    found={}
    for runtime in ('docker','podman'):
        out=command([runtime,'ps','-a','--format','{{.Names}}'],8)
        if out is not None: found[runtime]=sorted(set(x.strip() for x in out.splitlines() if x.strip()))[:1000]
    return found

def service_state(name):
    if not re.fullmatch(r'[a-zA-Z0-9_.@-]{1,180}\.service',name): return None
    return command(['systemctl','is-active',name]) or 'inactive'

def container_state(runtime,name):
    if runtime not in ('docker','podman') or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,180}',name): return None
    out=command([runtime,'inspect','--format','{{.State.Running}}',name],4)
    return None if out is None else out.strip()=='true'

def pi_flags():
    # vcgencmd returns hex bitfield: 0 current under-voltage, 2 current throttled.
    out=command(['vcgencmd','get_throttled'])
    if not out or '0x' not in out: return {'undervoltage':None,'throttling':None}
    try:
        bits=int(out.strip().split('0x')[-1],16)
        return {'undervoltage':bool(bits & 1),'throttling':bool(bits & 4)}
    except ValueError: return {'undervoltage':None,'throttling':None}

def filesystem_readonly():
    try:
        with open('/proc/self/mountinfo') as f:
            for line in f:
                parts=line.split()
                if len(parts)>5 and parts[4]=='/': return 'ro' in parts[5].split(',')
    except OSError: pass
    return None

def journal_oom(since_us):
    """Return (new OOM count, highest journal timestamp), or (None, unchanged)."""
    out=command(['journalctl','-k','--since',f'@{int(since_us/1000000)}','--no-pager','--output=json'],5)
    if out is None: return None,since_us
    count=0; latest=since_us
    for line in out.splitlines():
        try:
            entry=json.loads(line); stamp=int(entry.get('__REALTIME_TIMESTAMP',0))
            if stamp<=since_us: continue
            latest=max(latest,stamp)
            msg=str(entry.get('MESSAGE',''))
            if re.search(r'Out of memory: Killed process|oom-kill:|Killed process \d+',msg,re.I): count+=1
        except (ValueError,TypeError): continue
    return count,latest
