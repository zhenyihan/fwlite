#!/usr/bin/env python
# coding:utf-8
import sys
import time
import traceback
import socket
import logging
try:
    import urllib.parse as urlparse
    urlquote = urlparse.quote
    urlunquote = urlparse.unquote
    from ipaddress import ip_address
except ImportError:
    import urlparse
    import urllib2
    urlquote = urllib2.quote
    urlunquote = urllib2.unquote
    from ipaddr import IPAddress as ip_address
from util import ip_to_country_code

ASIA = ('AE', 'AF', 'AL', 'AZ', 'BD', 'BH', 'BN', 'BT', 'CN', 'CY', 'HK', 'ID',
        'IL', 'IN', 'IQ', 'IR', 'JO', 'JP', 'KH', 'KP', 'KR', 'KW', 'KZ', 'LA',
        'LB', 'LU', 'MN', 'MO', 'MV', 'MY', 'NP', 'OM', 'PH', 'PK', 'QA', 'SA',
        'SG', 'SY', 'TH', 'TJ', 'TM', 'TW', 'UZ', 'VN', 'YE')
AFRICA = ('AO', 'BI', 'BJ', 'BW', 'CF', 'CG', 'CM', 'CV', 'DZ', 'EG', 'ET', 'GA', 'GH',
          'GM', 'GN', 'GQ', 'KE', 'LY', 'MA', 'MG', 'ML', 'MR', 'MU', 'MZ', 'NA', 'NE',
          'NG', 'RW', 'SD', 'SN', 'SO', 'TN', 'TZ', 'UG', 'ZA', 'ZM', 'ZR', 'ZW')
NA = ('BM', 'BS', 'CA', 'CR', 'CU', 'GD', 'GT', 'HN', 'HT', 'JM', 'MX', 'NI', 'PA', 'US', 'VE')
SA = ('AR', 'BO', 'BR', 'CL', 'CO', 'EC', 'GY', 'PE', 'PY', 'UY')
EU = ('AT', 'BE', 'BG', 'CH', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GB',
      'GR', 'HR', 'HU', 'IE', 'IS', 'IT', 'LT', 'LV', 'MC', 'MD', 'MT', 'NL',
      'NO', 'PL', 'PT', 'RO', 'RU', 'SE', 'SK', 'SM', 'UA', 'UK', 'VA', 'YU')
PACIFIC = ('AU', 'CK', 'FJ', 'GU', 'NZ', 'PG', 'TO')

continent_list = [ASIA, AFRICA, NA, SA, EU, PACIFIC]

logger = logging.getLogger('parent_proxy')
logger.setLevel(logging.INFO)
hdr = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s %(name)s:%(levelname)s %(message)s',
                              datefmt='%H:%M:%S')
hdr.setFormatter(formatter)
logger.addHandler(hdr)


class default_0_dict(dict):
    def __missing__(self, key):
        return 0


class ParentProxy(object):
    via = None
    DEFAULT_TIMEOUT = 8
    avg_resp_time = 0
    avg_resp_time_ts = 0
    avg_resp_time_by_host = default_0_dict()
    avg_resp_time_by_host_ts = default_0_dict()

    def __init__(self, name, proxy):
        '''
        name: str, name of parent proxy
        proxy: "http://127.0.0.1:8087<|more proxies> <optional int: httppriority> <optional int: httpspriority>"
        '''
        proxy, _, priority = proxy.partition(' ')
        httppriority, _, httpspriority = priority.partition(' ')
        httpspriority, _, timeout = httpspriority.partition(' ')
        httppriority = httppriority or 99
        httpspriority = httpspriority or httppriority
        timeout = timeout or self.DEFAULT_TIMEOUT

        if proxy == 'direct':
            proxy = ''
        elif proxy and '//' not in proxy:
            proxy = 'http://' + proxy
        self.name = name
        proxy_list = proxy.split('|')
        self.proxy = proxy_list[0]
        if len(proxy_list) > 1:
            self.via = ParentProxy('via', '|'.join(proxy_list[1:]))
            self.via.name = '%s://%s:%s' % (self.via.scheme, self.via.hostname, self.via.port)
        self.parse = urlparse.urlparse(self.proxy)
        self.httppriority = int(httppriority)
        self.httpspriority = int(httpspriority)
        self.timeout = int(timeout)
        self.country_code = urlparse.parse_qs(self.parse.query).get('location', [''])[0] or None
        self.last_ckeck = 0
        if self.parse.scheme.lower() == 'sni':
            self.httppriority = -1

    def get_location(self):
        if self.country_code:
            return self.country_code
        if time.time() - self.last_ckeck < 300:
            return self.country_code
        try:
            self.last_ckeck = time.time()
            ip = ip_address(socket.getaddrinfo(self.parse.hostname, 0)[0][4][0])

            if ip.is_loopback or ip.is_private:
                from connection import create_connection
                from httputil import read_reaponse_line, read_headers
                try:
                    soc = create_connection(('bot.whatismyipaddress.com', 80), ctimeout=None, parentproxy=self)
                    soc.sendall(b'GET / HTTP/1.1\r\nConnection: keep_alive\r\nHost: bot.whatismyipaddress.com\r\nAccept-Encoding: identity\r\nUser-Agent: Python-urllib/2.7\r\n\r\n')
                    f = soc.makefile()
                    line, version, status, reason = read_reaponse_line(f)
                    _, headers = read_headers(f)
                    assert status == 200
                    ip = soc.recv(int(headers['Content-Length']))
                    if not ip:
                        soc.close()
                        raise ValueError('%s: ip address is empty' % self.name)
                    self.country_code = ip_to_country_code(ip)
                    soc.close()
                except Exception:
                    sys.stderr.write(traceback.format_exc())
                    sys.stderr.flush()
                    self.country_code = None
            else:
                self.country_code = ip_to_country_code(ip)
        finally:
            return self.country_code

    def priority(self, method=None, host=None, country_code=None):
        if any([host, country_code]) and not all([host, country_code]):
            raise ValueError('host and country_code should be provided together.')
        result = self.httpspriority if method is 'CONNECT' else self.httppriority
        if country_code == self.get_location():
            result -= 2
        else:
            for continent in continent_list:
                if self.get_location() in continent and country_code in continent:
                    result -= 1
                    break
        score = self.get_avg_resp_time() + self.get_avg_resp_time(host)
        result += score * 5
        logger.debug('proxy %s to %s response time penalty is %.3f' % (self.name, host, score * 5))
        return result

    def log(self, host, rtime):
        self.avg_resp_time = 0.87 * self.get_avg_resp_time() + (1 - 0.87) * rtime
        self.avg_resp_time_by_host[host] = 0.87 * self.get_avg_resp_time(host) + (1 - 0.87) * rtime
        self.avg_resp_time_ts = self.avg_resp_time_by_host_ts[host] = time.time()
        logger.debug('%s to %s: %.3fs %.3fs' % (self.name, host, rtime, self.avg_resp_time))

    def get_avg_resp_time(self, host=None):
        if host is None:
            if time.time() - self.avg_resp_time_ts > 360:
                self.avg_resp_time *= 0.93
                self.avg_resp_time_ts = time.time()
            return self.avg_resp_time
        if time.time() - self.avg_resp_time_by_host_ts[host] > 360:
            self.avg_resp_time_by_host[host] *= 0.93
            self.avg_resp_time_by_host_ts[host] = time.time()
        return self.avg_resp_time_by_host[host] or self.avg_resp_time

    @property
    def scheme(self):
        return self.parse.scheme

    @property
    def username(self):
        return urlunquote(self.parse.username) if self.parse.username else None

    @property
    def password(self):
        return urlunquote(self.parse.password) if self.parse.password else None

    @property
    def hostname(self):
        return self.parse.hostname

    @property
    def port(self):
        return self.parse.port

    @classmethod
    def set_via(cls, proxy):
        cls.via = proxy

    def get_via(self):
        if self.via == self:
            return None
        return self.via

    def __str__(self):
        return self.name or ('%s://%s:%s' % (self.parse.scheme, self.parse.hostname, self.parse.port))

    def __repr__(self):
        return '<ParentProxy: %s %s %s>' % (self.name or 'direct', self.httppriority, self.httpspriority)


class ParentProxyList(object):
    def __init__(self):
        self.direct = None
        self.local = None
        self._httpparents = set()
        self._httpsparents = set()
        self.dict = {}

    def addstr(self, name, proxy):
        self.add(ParentProxy(name, proxy))

    def add(self, parentproxy):
        if parentproxy.parse.scheme:
            s = '%s://%s:%s' % (parentproxy.parse.scheme, parentproxy.parse.hostname, parentproxy.parse.port)
        else:
            s = 'None'
        logger.info('add parent: %s: %s' % (parentproxy.name, s))
        assert isinstance(parentproxy, ParentProxy)
        self.dict[parentproxy.name] = parentproxy
        if parentproxy.name == 'direct':
            self.direct = parentproxy
            return
        if parentproxy.name == 'local':
            self.local = parentproxy
            return
        if 0 <= parentproxy.httppriority <= 100:
            self._httpparents.add(parentproxy)
        if 0 <= parentproxy.httpspriority <= 100:
            self._httpsparents.add(parentproxy)

    def remove(self, name):
        if name == 'direct' or name not in self.dict:
            return 1
        a = self.dict.get(name)
        del self.dict[name]
        self._httpparents.discard(a)
        self._httpsparents.discard(a)

    def httpparents(self):
        return list(self._httpparents)

    def httpsparents(self):
        return list(self._httpsparents)

    def get(self, key):
        return self.dict.get(key)
