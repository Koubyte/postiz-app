"""Bounded, credential-free public HTTPS reads with pinned resolved addresses."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

class PublicFetchError(ValueError):
    pass

def public_bytes(url, limit=20 * 1024 * 1024):
    for _ in range(4):
        u = urlsplit(url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
            raise PublicFetchError('Une adresse HTTPS publique est requise.')
        addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(a[4][0] for a in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise PublicFetchError('Adresse réseau non publique refusée.')
        conn = http.client.HTTPSConnection(u.hostname, timeout=25, context=ssl.create_default_context())
        # Pin the verified address, retaining hostname verification and TLS SNI.
        conn.sock = conn._context.wrap_socket(socket.create_connection((ips[0], 443), timeout=25), server_hostname=u.hostname)
        try:
            path = u.path or '/'
            if u.query: path += '?' + u.query
            conn.request('GET', path, headers={'User-Agent':'PlaneteLaser-Editorial/1.0','Accept':'*/*','Accept-Encoding':'identity'})
            response = conn.getresponse()
            if response.status in (301,302,303,307,308):
                url = urljoin(url, response.getheader('Location') or '')
                continue
            if response.status != 200:
                raise PublicFetchError('La source publique ne répond pas correctement.')
            if int(response.getheader('Content-Length') or '0') > limit:
                raise PublicFetchError('Source trop volumineuse.')
            body = response.read(limit + 1)
            if len(body) > limit: raise PublicFetchError('Source trop volumineuse.')
            return body
        finally:
            conn.close()
    raise PublicFetchError('Trop de redirections.')
