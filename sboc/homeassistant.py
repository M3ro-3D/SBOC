"""Read Home Assistant System Monitor entities via the authenticated REST API."""
import json
import math
import unicodedata
from urllib.request import Request
from .network_policy import lan_urlopen

UNITS = {'cpu': '%', 'ram': '%', 'disk': '%', 'temperature': '°C', 'network': 'KiB/s'}


def _get(base, token, path):
    req = Request(base + path, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    with lan_urlopen(req, timeout=5) as response:
        if response.status != 200:
            raise ValueError('Home Assistant HTTP ' + str(response.status))
        return json.loads(response.read(2000000))


def _normalized(value):
    text = unicodedata.normalize('NFKD', str(value).lower())
    return ''.join(c for c in text if not unicodedata.combining(c)).replace('ß', 'ss')


def _candidates(metric, state):
    entity = state.get('entity_id', '')
    if not entity.startswith('sensor.system_monitor_'):
        return False
    attributes = state.get('attributes') or {}
    unit = attributes.get('unit_of_measurement')
    if unit != UNITS[metric]:
        return False
    name = _normalized(entity[len('sensor.system_monitor_'):] + ' ' + attributes.get('friendly_name', ''))
    if metric == 'ram':
        return ('arbeitsspeicher' in name or 'memory' in name or 'ram' in name) and ('auslastung' in name or 'use_percent' in name or 'usage' in name or 'percent' in name)
    if metric == 'cpu':
        return ('cpu' in name or 'prozessor' in name) and ('auslastung' in name or 'usage' in name or 'use' in name or 'last' in name)
    if metric == 'temperature':
        return ('cpu' in name or 'prozessor' in name) and ('temperatur' in name or 'temperature' in name)
    if metric == 'disk':
        return ('disk' in name or 'festplatte' in name or 'speicherplatz' in name or 'datentrager' in name) and ('auslastung' in name or 'use_percent' in name or 'usage' in name or 'percent' in name)
    # Network metrics may be per-interface and receive/transmit; do not guess which one is desired.
    return False


def discover_entities(states):
    """Return only unambiguous matches. Explicit configuration always wins."""
    result = {}
    for metric in UNITS:
        matches = [s['entity_id'] for s in states if isinstance(s, dict) and _candidates(metric, s)]
        if len(matches) == 1:
            result[metric] = matches[0]
    return result


def read_metrics(device):
    token = device.get('token', '')
    if not token:
        raise ValueError('Home Assistant token missing')
    base = f"{device.get('scheme', 'http')}://{device['host']}:{device['port']}"
    states = _get(base, token, '/api/states')
    if not isinstance(states, list):
        raise ValueError('Unexpected Home Assistant response')
    by_id = {s.get('entity_id'): s for s in states if isinstance(s, dict)}
    auto = discover_entities(states)
    metrics = {key: None for key in UNITS}
    for metric, unit in UNITS.items():
        entity = (device.get('entities') or {}).get(metric) or auto.get(metric)
        state = by_id.get(entity)
        if not state or (state.get('attributes') or {}).get('unit_of_measurement') != unit:
            continue
        try:
            value = float(state['state'])
            if math.isfinite(value):
                metrics[metric] = round(value, 2)
        except (ValueError, TypeError, KeyError):
            pass
    return {'schema': 1, 'metrics': metrics, 'services': {}, 'containers': {}}


def inspect(scheme, host, port, token):
    """Check HA credentials and return real sensor choices without guessing IDs."""
    base=f'{scheme}://{host}:{port}'
    info=_get(base,token,'/api/config')
    states=_get(base,token,'/api/states')
    if not isinstance(states,list): raise ValueError('Ungültige Sensorantwort')
    sensors=[]
    for item in states:
        if not isinstance(item,dict): continue
        entity=item.get('entity_id','')
        if not entity.startswith('sensor.'): continue
        attrs=item.get('attributes') or {}
        sensors.append({'entity_id':entity,'name':attrs.get('friendly_name') or entity,'unit':attrs.get('unit_of_measurement') or ''})
    return {'name':info.get('location_name') or 'homeassistant','sensors':sensors,'automatic':discover_entities(states)}
