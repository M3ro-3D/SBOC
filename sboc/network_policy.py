"""LAN-only endpoint checks and DNS-pinned HTTP(S) requests.

Only the agent and Home Assistant use this transport. SMTP is deliberately
excluded: mail servers are commonly public Internet services.
"""
import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request


def _allowed(address):
    ip = ipaddress.ip_address(address.split('%', 1)[0])
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip in ipaddress.ip_network('10.0.0.0/8') or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')
    # ULA is supported. IPv6 link-local requires a scope ID for reliable routing,
    # and is not supported by SBOC's host field.
    return ip in ipaddress.ip_network('fc00::/7')


def lan_host(host, port):
    if not isinstance(host, str) or not host or any(c in host for c in '/\\@?#%'):
        raise ValueError('Ungültiger Hostname')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Ungültiger Port')
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError('Hostname nicht auflösbar') from exc
    if not records:
        raise ValueError('Hostname nicht auflösbar')
    addresses = [record[4][0] for record in records]
    if not all(_allowed(address) for address in addresses):
        raise ValueError('Nur private LAN-Adressen sind erlaubt')
    return addresses[0], port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP-Weiterleitungen sind nicht erlaubt')


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, *, pinned, **kwargs):
        super().__init__(host, **kwargs)
        self.pinned = pinned

    def connect(self):
        self.sock = socket.create_connection((self.pinned, self.port), self.timeout, self.source_address)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, *, pinned, **kwargs):
        super().__init__(host, **kwargs)
        self.pinned = pinned

    def connect(self):
        raw = socket.create_connection((self.pinned, self.port), self.timeout, self.source_address)
        try:
            # Verify the original hostname against the certificate, not the IP.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, pinned):
        super().__init__()
        self.pinned = pinned

    def http_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTP(host, pinned=self.pinned, **kw), req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pinned):
        super().__init__()
        self.pinned = pinned

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _PinnedHTTPS(host, pinned=self.pinned, context=self._context, **kw), req)


def lan_urlopen(req, timeout=6):
    url = req.full_url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Ungültiges Netzwerkziel')
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    address, _ = lan_host(parts.hostname, port)
    opener = urllib.request.build_opener(_NoRedirect(), _HTTPHandler(address), _HTTPSHandler(address), urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)
