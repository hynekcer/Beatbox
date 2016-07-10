"""Example of an alternative HTTP library ('requests' package here)

This example can be used:
A) run the example

B) use the alternative http library in your app:
   >>> from demo_connection import RequestsConnectionFactory
   >>> svc = beatbox.Client()
   >>> svc.connection_factory = RequestsConnectionFactory
   >>> svc.login(...)

C) use with some customized parameters:
   >>> svc.connection_factory = lambda: RequestsConnectionFactory(timeout=30)

D) customize it it completely for your purpose, e.g:
     proxies, retrying broken connectons, logging, debugging etc.

    "Connection factory" must be a callable (function or class) that
    - accepts parameters (scheme, host, timeout=...)
    - creates an object (connection) with methods:
        request(method, url, raw_body, headers=None)
        getresponse()
        close()

    It can be therefore e.g. a function that returns HTTPSConnection or a descendant
    of HTTPSConnection or a descendant of any following *ConnectionFactory classes.
"""

import os
import sys
import beatbox
from beatbox.six import http_client
try:
    import requests
except ImportError:
    print("This example requires 'requests' package.")


class HttpConnectionFactory(http_client.HTTPSConnection):
    """Create a connection by http_client.HTTPSConnection"""
    # http is not useful for Salesforce any more

    def __init__(self, scheme, host, timeout=60, **kwargs):
        if beatbox.forceHttp or scheme.upper() == 'HTTP':
            raise Exception("HTTPS must be used for Salesforce")
        super(HttpConnectionFactory, self).__init__(host, timeout=timeout, **kwargs)
        self.headers = {}


class RequestsConnectionFactory(object):
    """Create a connection based on 'requests' package."""

    def __init__(self, scheme, host, timeout=1200):
        self.session = requests.Session()
        self.base = '%s://%s' % (scheme, host)
        adapter = requests.adapters.HTTPAdapter()  # retries etc.
        self.session.mount(self.base, adapter)

    def request(self, method, url, raw_body, headers=None):
        self.response = None
        self.response = self.session.request(method, url, data=raw_body, headers=headers)

    def getresponse(self):
        resp = self.response
        self.response = None
        return ResponseWrapper(resp)

    def close(self):
        try:
            self.session.close()
        except ReferenceError:
            pass  # probably yet deleted weakref if called in __dell__


class ResponseWrapper(object):
    """Simulated HTTPConnection response by requests."""

    def __init__(self, response):
        self.response = response

    def read(self):
        return self.response.content

    def getheader(self, name, default=None):
        if name.lower() == 'content-encoding':
            # the content has been decoded yet by the `requests` package
            return default
        else:
            return self.response.headers.get(name, default)


def main():
    svc = beatbox.Client()
    beatbox.gzipRequest = False
    if 'SF_SANDBOX' in os.environ:
        svc.serverUrl = svc.serverUrl.replace('login.salesforce', 'test.salesforce')
    username, password = sys.argv[1], sys.argv[2]

    svc.connection_factory = RequestsConnectionFactory
    svc.login(username, password)

    qr = svc.query("select Id, Name from Account limit 1")
    sf = beatbox._tPartnerNS
    row = qr[sf.records:][0]
    print('%s: %s' % (row[2], row[3]))

    svc.connection_factory = HttpConnectionFactory
    svc.login(username, password)

    qr = svc.query("select Id, Name from Account limit 1")
    sf = beatbox._tPartnerNS
    row = qr[sf.records:][0]
    print('%s: %s' % (row[2], row[3]))


if __name__ == "__main__":
    main()
