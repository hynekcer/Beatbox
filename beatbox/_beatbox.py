"""beatbox: Makes the salesforce.com SOAP API easily accessible."""
# The name of module is "_beatbox" because the same name in the package
# "beatbox" would be problematic.
from __future__ import print_function

import gzip
import datetime
import re
import functools
import time
from collections import namedtuple
from xml.sax.saxutils import XMLGenerator
from xml.sax.saxutils import quoteattr
from xml.sax.xmlreader import AttributesNSImpl

import beatbox
from beatbox.six import BytesIO, http_client, text_type, urlparse, xrange
from beatbox import xmltramp
from beatbox.xmltramp import islst

__version__ = "0.96"
__author__ = "Simon Fell"
__credits__ = "Mad shouts to the sforce possie"
__copyright__ = "(C) 2006-2015 Simon Fell. GNU GPL 2."

# global constants for namespace strings, used during serialization
_partnerNs = "urn:partner.soap.sforce.com"
_sobjectNs = "urn:sobject.partner.soap.sforce.com"
_envNs = "http://schemas.xmlsoap.org/soap/envelope/"
_noAttrs = AttributesNSImpl({}, {})

# global constants for xmltramp namespaces, used to access response data
_tPartnerNS = xmltramp.Namespace(_partnerNs)
_tSObjectNS = xmltramp.Namespace(_sobjectNs)
_tSoapNS = xmltramp.Namespace(_envNs)


def makeConnection(scheme, host, timeout=1200):
    kwargs = {'timeout': timeout}
    if beatbox.forceHttp or scheme.upper() == 'HTTP':
        return http_client.HTTPConnection(host, **kwargs)
    return http_client.HTTPSConnection(host, **kwargs)


class Client(object):
    """The main sforce client proxy class."""
    def __init__(self):
        self.batchSize = 500
        self.serverUrl = "https://login.salesforce.com/services/Soap/u/36.0"
        self.__conn = None
        self.timeout = 15
        self.headers = {}

    def __del__(self):
        if self.__conn:
            self.__conn.close()

    def login(self, username, password):
        """"Login.  returns the loginResult structure"""
        lr = LoginRequest(self.serverUrl, username, password).post()
        self.useSession(str(lr[_tPartnerNS.sessionId]), str(lr[_tPartnerNS.serverUrl]))
        return lr

    def portalLogin(self, username, password, orgId, portalId):
        """Perform a portal login.

        orgId is always needed, portalId is needed for new style portals
        is not required for the old self service portal
        for the self service portal, only the login request will work, self service users don't
        get API access, for new portals, the users should have API acesss, and can call the rest
        of the API.
        """
        lr = PortalLoginRequest(self.serverUrl, username, password, orgId, portalId).post()
        self.useSession(str(lr[_tPartnerNS.sessionId]), str(lr[_tPartnerNS.serverUrl]))
        return lr

    def useSession(self, sessionId, serverUrl):
        """Initialize from an existing sessionId & serverUrl

        Useful if we're being launched via a custom link
        """
        self.sessionId = sessionId
        self.__serverUrl = serverUrl
        (scheme, host, path, params, query, frag) = urlparse(self.__serverUrl)
        self.__conn = makeConnection(scheme, host)

    def logout(self):
        """Calls logout which invalidates the current sessionId.

        In general its better to not call this and just let the sessions expire on their own.
        """
        return LogoutRequest(self.__serverUrl, self.sessionId, self.headers).post(self.__conn, True)

    def query(self, soql):
        """Set the batchSize property on the Client instance to change the batchsize for query/queryMore."""
        return QueryRequest(self.__serverUrl, self.sessionId, self.headers, self.batchSize, soql).post(self.__conn)

    def queryAll(self, soql):
        """Query include deleted and archived rows."""
        return QueryRequest(self.__serverUrl, self.sessionId, self.headers, self.batchSize, soql, "queryAll").post(self.__conn)

    def queryMore(self, queryLocator):
        return QueryMoreRequest(self.__serverUrl, self.sessionId, self.headers, self.batchSize, queryLocator).post(self.__conn)

    def search(self, sosl):
        return SearchRequest(self.__serverUrl, self.sessionId, self.headers, sosl).post(self.__conn)

    def getUpdated(self, sObjectType, start, end):
        return GetUpdatedRequest(self.__serverUrl, self.sessionId, self.headers, sObjectType, start, end).post(self.__conn)

    def getDeleted(self, sObjectType, start, end):
        return GetDeletedRequest(self.__serverUrl, self.sessionId, self.headers, sObjectType, start, end).post(self.__conn)

    def retrieve(self, fields, sObjectType, ids):
        """ids can be 1 or a list, returns a single save result or a list"""
        return RetrieveRequest(self.__serverUrl, self.sessionId, self.headers, fields, sObjectType, ids).post(self.__conn)

    def create(self, sObjects):
        """sObjects can be 1 or a list, returns a single save result or a list"""
        return CreateRequest(self.__serverUrl, self.sessionId, self.headers, sObjects).post(self.__conn)

    def update(self, sObjects):
        """sObjects can be 1 or a list, returns a single save result or a list"""
        return UpdateRequest(self.__serverUrl, self.sessionId, self.headers, sObjects).post(self.__conn)

    def upsert(self, externalIdName, sObjects):
        """sObjects can be 1 or a list, returns a single upsert result or a list"""
        return UpsertRequest(self.__serverUrl, self.sessionId, self.headers, externalIdName, sObjects).post(self.__conn)

    def delete(self, ids):
        """ids can be 1 or a list, returns a single delete result or a list"""
        return DeleteRequest(self.__serverUrl, self.sessionId, self.headers, ids).post(self.__conn)

    def undelete(self, ids):
        """ids can be 1 or a list, returns a single delete result or a list"""
        return UndeleteRequest(self.__serverUrl, self.sessionId, self.headers, ids).post(self.__conn)

    def convertLead(self, leadConverts):
        """
        leadConverts can be 1 or a list of dictionaries, each dictionary should be filled out as per
        the LeadConvert type in the WSDL.
          <element name="accountId"              type="tns:ID" nillable="true"/>
          <element name="contactId"              type="tns:ID" nillable="true"/>
          <element name="convertedStatus"        type="xsd:string"/>
          <element name="doNotCreateOpportunity" type="xsd:boolean"/>
          <element name="leadId"                 type="tns:ID"/>
          <element name="opportunityName"        type="xsd:string" nillable="true"/>
          <element name="overwriteLeadSource"    type="xsd:boolean"/>
          <element name="ownerId"                type="tns:ID"     nillable="true"/>
          <element name="sendNotificationEmail"  type="xsd:boolean"/>
        """
        return ConvertLeadRequest(self.__serverUrl, self.sessionId, self.headers, leadConverts).post(self.__conn)

    def describeSObjects(self, sObjectTypes):
        """sObjectTypes can be 1 or a list, returns a single describe result or a list of them"""
        return DescribeSObjectsRequest(self.__serverUrl, self.sessionId, self.headers, sObjectTypes).post(self.__conn)

    def describeGlobal(self):
        return AuthenticatedRequest(self.__serverUrl, self.sessionId, self.headers, "describeGlobal").post(self.__conn)

    def describeLayout(self, sObjectType):
        return DescribeLayoutRequest(self.__serverUrl, self.sessionId, self.headers, sObjectType).post(self.__conn)

    def describeTabs(self):
        return AuthenticatedRequest(self.__serverUrl, self.sessionId, self.headers, "describeTabs").post(self.__conn, True)

    def describeSearchScopeOrder(self):
        return AuthenticatedRequest(self.__serverUrl, self.sessionId, self.headers, "describeSearchScopeOrder"
                                    ).post(self.__conn, True)

    def describeQuickActions(self, actions):
        return DescribeQuickActionsRequest(self.__serverUrl, self.sessionId, self.headers, actions).post(self.__conn, True)

    def describeAvailableQuickActions(self, parentType=None):
        return DescribeAvailableQuickActionsRequest(self.__serverUrl, self.sessionId, self.headers, parentType
                                                    ).post(self.__conn, True)

    def performQuickActions(self, actions):
        return PerformQuickActionsRequest(self.__serverUrl, self.sessionId, self.headers, actions).post(self.__conn, True)

    def getServerTimestamp(self):
        return str(AuthenticatedRequest(self.__serverUrl, self.sessionId, self.headers, "getServerTimestamp"
                                        ).post(self.__conn)[_tPartnerNS.timestamp])

    def resetPassword(self, userId):
        return ResetPasswordRequest(self.__serverUrl, self.sessionId, self.headers, userId).post(self.__conn)

    def setPassword(self, userId, password):
        SetPasswordRequest(self.__serverUrl, self.sessionId, self.headers, userId, password).post(self.__conn)

    def getUserInfo(self):
        return AuthenticatedRequest(self.__serverUrl, self.sessionId, self.headers, "getUserInfo").post(self.__conn)

    @property
    def iterclient(self):
        """Easy access to IterClient methods"""
        client = IterClient()
        vars(client).update(vars(self))
        return client


class IterClient(Client):

    def __init__(self):
        super(IterClient, self).__init__()

    def gatherRecords(self, queryHandle):
        while 1:
            for elem in queryHandle[_tPartnerNS.records:]:
                yield elem
            if str(queryHandle[_tPartnerNS.done]) == 'true':
                break
            else:
                queryHandle = self.queryMore(queryHandle.queryLocator)

    def chunkRequests(self, collection, chunkLength=None):
        if not islst(collection):
            yield [collection]
        else:
            if chunkLength is None:
                chunkLength = self.batchSize
            for i in xrange(0, len(collection), chunkLength):
                yield collection[i:i + chunkLength]

    def query(self, soql):
        return self.gatherRecords(super(IterClient, self).query(soql))

    def queryAll(self, soql):
        return self.gatherRecords(super(IterClient, self).queryAll(soql))

    def retrieve(self, fields, sObjectType, ids, chunkLength=None):
        """ids can be 1 or a list, returns a single save result or a list"""
        for chunk in self.chunkRequests(ids, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).retrieve(fields, sObjectType, chunk)]
            else:
                responses = super(IterClient, self).retrieve(fields, sObjectType, chunk)
            for response in responses:
                yield response

    def create(self, sObjects, chunkLength=None):
        for chunk in self.chunkRequests(sObjects, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).create(chunk)]
            else:
                responses = super(IterClient, self).create(chunk)
            for response in responses:
                yield response

    def update(self, sObjects, chunkLength=None):
        for chunk in self.chunkRequests(sObjects, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).update(chunk)]
            else:
                responses = super(IterClient, self).update(chunk)
            for response in responses:
                yield response

    def upsert(self, externalIdName, sObjects, chunkLength=None):
        for chunk in self.chunkRequests(sObjects, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).upsert(externalIdName, chunk)]
            else:
                responses = super(IterClient, self).upsert(externalIdName, chunk)

            for response in responses:
                yield response

    def delete(self, ids, chunkLength=None):
        for chunk in self.chunkRequests(ids, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).delete(chunk)]
            else:
                responses = super(IterClient, self).delete(chunk)
            for response in responses:
                yield response

    def undelete(self, ids, chunkLength=None):
        for chunk in self.chunkRequests(ids, chunkLength=chunkLength):
            if len(chunk) == 1:
                responses = [super(IterClient, self).undelete(chunk)]
            else:
                responses = super(IterClient, self).undelete(chunk)
            for response in responses:
                yield response


# === End of public interface ===

# (everything below is private, even without leading underscore)


# Error types

class SoapFaultError(Exception):
    """Exception class for soap faults."""
    def __init__(self, faultCode, faultString):
        self.faultCode = faultCode
        self.faultString = faultString

    def __str__(self):
        return repr(self.faultCode) + " " + repr(self.faultString)


class SoapInvalidSession(SoapFaultError):
    pass  # a new login should help


class SoapInvalidLogin(SoapFaultError):
    pass  # a new login can't help


# Authentication class

class AuthInfo(object):

    # If the login failed, e.g due to changed password, it should not be retried
    # too frequently to prevent assount locking. The best is to fix password,
    # allowed IP addres range etc. and restart the process (web server) or to call
    # login method explicitely.
    safe_login_retry_delay = 600

    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory
        self.session_id = None
        self.worker_server_url = None
        self.is_sandbox = None
        self._auth_request_body = None
        self.failed_timestamp = None

    def login(self, username, password, is_sandbox=None):
        self.is_sandbox = is_sandbox
        self._auth_request_body = LoginRequest(username, password)
        self.failed_timestamp = None
        return self.reauth()

    def portalLogin(self, username, password, orgId, portalId, is_sandbox=None):
        self.is_sandbox = is_sandbox
        self._auth_request_body = PortalLoginRequest(username, password, orgId, portalId)
        self.failed_timestamp = None
        return self.reauth()

    def useSession(self, sessionId, serverUrl):
        self.session_id = sessionId
        self.worker_server_url = serverUrl
        self._auth_request_body = None
        self.failed_timestamp = None

    def reauth(self):
        """Get a new sessionId (re-authenticate)

        If the last login failed (not expired) then the login request
        is never repeated automatically, until a succesfull login or
        until a safe delay expires - to prevent account locking.
        The login request is never repeated automatically after logout in the same process.
        """
        if not self._auth_request_body:
            raise RuntimeError("Connection to SFDC not authenticated")
        if self.failed_timestamp and time.time() < self.failed_timestamp < self.safe_login_retry_delay:
            raise SoapInvalidLogin("The same Login shouldn't be retried automatically too soon after failed login")
        if self.is_sandbox is not None:
            self.login_server_url = re.sub(r'(?<=https://)(test|login)(?=\.salesforce\.com/)',
                                           'test' if self.is_sandbox else 'login', self.login_server_url)
        conn = SoapLoginConnection(self.login_server_url, connection_factory=self.connection_factory)
        try:
            lr = conn.post(self._auth_request_body)
        except SoapInvalidLogin:
            self.failed_timestamp = time.time()
            raise
        finally:
            conn.close()
        self.useSession(str(lr[_tPartnerNS.sessionId]), str(lr[_tPartnerNS.serverUrl]))
        return lr

    def invalidate(self):
        """Forget auth information"""
        self._auth_request_body = None
        self.session_id = None


# TODO move...
class AuthInfoMinimal(object):
    """Prototype of authentication data and methods

    The class must implement at least one authentication method that sets
    attributes `session_id` and `worker_server_url`, e.g. login or some
    OAuth2 methods.
    All other attributes are considered private.
    An optional method `reauth` can be implemented that allows to
    automatically renew an expired session_id from some private data.
    """

    def __init__(self):
        self.session_id = None
        self.worker_server_url = None

    def login(self, username, password, is_sandbox=False):
        # self.session_id = ...
        # self._auth_request_body = ...
        raise NotImplementedError("An authenication method is to be implemented")


# classes for network connection (to worker server, to login server and a universal code)

class BaseSoapConnection(object):
    """Universal client for SOAP requests to the login server or worker server."""

    def __init__(self, auth=None, login_server_url=None, connection_factory=None):
        self.auth = auth
        self.login_server_url = login_server_url
        self.connection_factory = connection_factory or makeConnection
        self.conn = None

    @property
    def server_url(self):
        return self.auth.worker_server_url if self.auth else self.login_server_url

    def connect(self):
        """Connect if not connected"""
        if self.conn is None:
            (scheme, host, path, params, query, frag) = urlparse(self.server_url)
            self.conn = self.connection_factory(scheme, host)

    def post2r(self, envelope_creator_method, obj, *args, **kwargs):
        """Call post method and exception handling with possible 2x retry"""
        retry = 1
        while True:
            envelope = envelope_creator_method(obj, *args, **kwargs)
            try:
                return self.post(envelope)
            except SoapInvalidSession:
                # the request is not retried (should not be) if login request after INVALID_LOGIN
                if retry < 2 and hasattr(self.auth, 'reauth'):
                    self.auth.reauth()
                    retry += 1
                else:
                    raise

    def post(self, envelope):
        """Complete the envelope and send the request

        does all the grunt work,
          serializes the envelope object,
          makes a http request,
          passes the response to xmltramp
          checks for soap fault
          todo: check for mU='1' headers
          returns the relevant result from the body child
        """
        http_headers = {"User-Agent": "BeatBox/" + __version__,
                        "SOAPAction": '""',
                        "Content-Type": "text/xml; charset=utf-8"}
        if beatbox.gzipResponse:
            http_headers['accept-encoding'] = 'gzip'
        if beatbox.gzipRequest:
            http_headers['content-encoding'] = 'gzip'

        closed = self.conn is None
        if closed:
            self.connect()

        rawRequest = envelope.makeEnvelope()

        print("**** req: %s **" % rawRequest[:2000])

        # Possible network exceptions in these two commands are:
        # ConnectionResetError (builtin exception raised from ssl module in Python 3)
        # http.client.CannotSendRequest
        self.conn.request("POST", self.server_url, rawRequest, http_headers)
        response = self.conn.getresponse()

        rawResponse = response.read()
        if response.getheader('content-encoding', '') == 'gzip':
            rawResponse = gzip.GzipFile(fileobj=BytesIO(rawResponse)).read()
        if closed and isinstance(self, SoapLoginConnection):
            self.close()
        tramp = xmltramp.parse(rawResponse)

        out = tramp.__repr__(1, 1)
        print("*** resp: %s **" % (out if len(out) <= 2000 else out[:1500] + ' ** ... ** ' + out[-500:]),
              b'<size>' in rawResponse)

        response_body = tramp[_tSoapNS.Body]
        try:
            fault = response_body[_tSoapNS.Fault]
        except KeyError:
            pass
        else:
            faultString = str(fault.faultstring)
            faultCode = str(fault.faultcode).split(':')[-1]
            error_map = {'sf:INVALID_SESSION_ID': SoapInvalidSession,
                         'sf:INVALID_LOGIN': SoapInvalidLogin,
                         }
            raise error_map.get(faultCode, SoapFaultError)(faultCode, faultString)
        return envelope.decode_response(response_body)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self):
        self.close()


class SoapLoginConnection(BaseSoapConnection):
    """Client for SOAP requests to the login server."""

    def __init__(self, login_server_url, connection_factory=None):
        super(SoapLoginConnection, self).__init__(login_server_url=login_server_url,
                                                  connection_factory=connection_factory)


class SoapWorkerConnection(BaseSoapConnection):
    """Client for SOAP requests to the worker server."""

    def __init__(self, auth, connection_factory=None):
        super(SoapWorkerConnection, self).__init__(auth=auth,
                                                   connection_factory=connection_factory)


# classes for writing XML output (used by SoapEnvelope)

class BeatBoxXmlGenerator(XMLGenerator):
    """Fixed version of XmlGenerator, handles unqualified attributes correctly."""
    def __init__(self, destination, encoding):
        self._out = destination
        XMLGenerator.__init__(self, destination, encoding)

    def makeName(self, name):
        if name[0] is None:
            # if the name was not namespace-scoped, use the qualified part
            return name[1]
        # else try to restore the original prefix from the namespace
        return self._current_context[name[0]] + ":" + name[1]

    def startElementNS(self, name, qname, attrs):
        self._write(text_type('<' + self.makeName(name)))

        for pair in self._undeclared_ns_maps:
            self._write(text_type(' xmlns:%s="%s"' % pair))
        self._undeclared_ns_maps = []

        for (name, value) in attrs.items():
            self._write(text_type(' %s=%s' % (self.makeName(name), quoteattr(value))))
        self._write(text_type('>'))


class XmlWriter(object):
    """General purpose xml writer, does a bunch of useful stuff above & beyond XmlGenerator."""
    def __init__(self, doGzip):
        self.__buf = BytesIO()
        if doGzip:
            self.__gzip = gzip.GzipFile(mode='wb', fileobj=self.__buf)
            stm = self.__gzip
        else:
            stm = self.__buf
            self.__gzip = None
        self.xg = BeatBoxXmlGenerator(stm, "utf-8")
        self.xg.startDocument()
        self.__elems = []

    def startPrefixMapping(self, prefix, namespace):
        self.xg.startPrefixMapping(prefix, namespace)

    def endPrefixMapping(self, prefix):
        self.xg.endPrefixMapping(prefix)

    def startElement(self, namespace, name, attrs=_noAttrs):
        self.xg.startElementNS((namespace, name), name, attrs)
        self.__elems.append((namespace, name))

    def writeStringElement(self, namespace, name, value, attrs=_noAttrs):
        """If value is a list, then it writes out repeating elements, one for each value"""
        if islst(value):
            for v in value:
                self.writeStringElement(namespace, name, v, attrs)
        else:
            self.startElement(namespace, name, attrs)
            self.characters(value)
            self.endElement()

    def endElement(self):
        e = self.__elems[-1]
        self.xg.endElementNS(e, e[1])
        del self.__elems[-1]

    def characters(self, s):
        # todo base64 ?
        if isinstance(s, datetime.datetime):
            # todo, timezones
            s = s.isoformat()
        elif isinstance(s, datetime.date):
            # todo, try isoformat
            s = "%04d-%02d-%02d" % (s.year, s.month, s.day)
        elif isinstance(s, int):
            s = str(s)
        elif isinstance(s, float):
            s = str(s)
        self.xg.characters(s)

    def endDocument(self):
        self.xg.endDocument()
        if (self.__gzip is not None):
            self.__gzip.close()
        return self.__buf.getvalue()


class SoapFaultError(Exception):
    """Exception class for soap faults."""
    def __init__(self, faultCode, faultString):
        self.faultCode = faultCode
        self.faultString = faultString

    def __str__(self):
        return repr(self.faultCode) + " " + repr(self.faultString)


class SoapWriter(XmlWriter):
    """SOAP specific stuff ontop of XmlWriter."""
    __xsiNs = "http://www.w3.org/2001/XMLSchema-instance"

    def __init__(self):
        XmlWriter.__init__(self, beatbox.gzipRequest)
        self.startPrefixMapping("s", _envNs)
        self.startPrefixMapping("p", _partnerNs)
        self.startPrefixMapping("o", _sobjectNs)
        self.startPrefixMapping("x", SoapWriter.__xsiNs)
        self.startElement(_envNs, "Envelope")

    def writeStringElement(self, namespace, name, value, attrs=_noAttrs):
        if value is None:
            if attrs:
                attrs[(SoapWriter.__xsiNs, "nil")] = 'true'
            else:
                attrs = {(SoapWriter.__xsiNs, "nil"): 'true'}
            value = ""
        XmlWriter.writeStringElement(self, namespace, name, value, attrs)

    def endDocument(self):
        self.endElement()  # envelope
        self.endPrefixMapping("o")
        self.endPrefixMapping("p")
        self.endPrefixMapping("s")
        self.endPrefixMapping("x")
        return XmlWriter.endDocument(self)


class SoapEnvelope(object):
    """Processing for a single soap request / response."""
    def __init__(self, serverUrl, operationName, clientId="BeatBox/" + __version__):
        self.serverUrl = serverUrl
        self.operationName = operationName
        self.clientId = clientId

    def writeHeaders(self, writer):
        pass

    def writeBody(self, writer):
        pass

    def makeEnvelope(self):
        s = SoapWriter()
        s.startElement(_envNs, "Header")
        s.characters("\n")
        s.startElement(_partnerNs, "CallOptions")
        s.writeStringElement(_partnerNs, "client", self.clientId)
        s.endElement()
        s.characters("\n")
        self.writeHeaders(s)
        s.endElement()  # Header
        s.startElement(_envNs, "Body")
        s.characters("\n")
        s.startElement(_partnerNs, self.operationName)
        self.writeBody(s)
        s.endElement()  # operation
        s.endElement()  # body
        return s.endDocument()

    def post(self, conn=None, alwaysReturnList=False):
        """Complete the envelope and send the request

        does all the grunt work,
          serializes the request,
          makes a http request,
          passes the response to tramp
          checks for soap fault
          todo: check for mU='1' headers
          returns the relevant result from the body child
        """
        headers = {"User-Agent": "BeatBox/" + __version__,
                   "SOAPAction": '""',
                   "Content-Type": "text/xml; charset=utf-8"}
        if gzipResponse:
            headers['accept-encoding'] = 'gzip'
        if gzipRequest:
            headers['content-encoding'] = 'gzip'
        close = False
        (scheme, host, path, params, query, frag) = urlparse(self.serverUrl)
        if conn is None:
            conn = makeConnection(scheme, host)
            close = True
        rawRequest = self.makeEnvelope()
        # print(rawRequest)
        conn.request("POST", self.serverUrl, rawRequest, headers)
        response = conn.getresponse()
        rawResponse = response.read()
        if response.getheader('content-encoding', '') == 'gzip':
            rawResponse = gzip.GzipFile(fileobj=BytesIO(rawResponse)).read()
        if close:
            conn.close()
        tramp = xmltramp.parse(rawResponse)
        try:
            faultString = str(tramp[_tSoapNS.Body][_tSoapNS.Fault].faultstring)
            faultCode = str(tramp[_tSoapNS.Body][_tSoapNS.Fault].faultcode).split(':')[-1]
            raise SoapFaultError(faultCode, faultString)
        except KeyError:
            pass
        # first child of body is XXXXResponse
        result = tramp[_tSoapNS.Body][0]
        # it contains either a single child, or for a batch call multiple children
        if alwaysReturnList or len(result) > 1:
            return result[:]
        else:
            return result[0]


class LoginRequest(SoapEnvelope):
    def __init__(self, serverUrl, username, password):
        SoapEnvelope.__init__(self, serverUrl, "login")
        self.__username = username
        self.__password = password

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "username", self.__username)
        s.writeStringElement(_partnerNs, "password", self.__password)


class PortalLoginRequest(LoginRequest):
    def __init__(self, serverUrl, username, password, orgId, portalId):
        LoginRequest.__init__(self, serverUrl, username, password)
        self.__orgId = orgId
        self.__portalId = portalId

    def writeHeaders(self, s):
        s.startElement(_partnerNs, "LoginScopeHeader")
        s.writeStringElement(_partnerNs, "organizationId", self.__orgId)
        if (not (self.__portalId is None or self.__portalId == "")):
            s.writeStringElement(_partnerNs, "portalId", self.__portalId)
        s.endElement()


class AuthenticatedRequest(SoapEnvelope):
    """Base class for all methods that require an autheticated request."""
    def __init__(self, serverUrl, sessionId, headers, operationName):
        SoapEnvelope.__init__(self, serverUrl, operationName)
        self.sessionId = sessionId
        self.headers = headers

    def writeHeaders(self, s):
        s.startElement(_partnerNs, "SessionHeader")
        s.writeStringElement(_partnerNs, "sessionId", self.sessionId)
        s.endElement()
        for headerName, headerFields in self.headers.items():
            s.startElement(_partnerNs, headerName)
            for key, value in headerFields.items():
                s.writeStringElement(_partnerNs, key, value)
            s.endElement()

    def writeDict(self, s, elemName, d):
        if islst(d):
            for o in d:
                self.writeDict(s, elemName, o)
        else:
            s.startElement(_partnerNs, elemName)
            for fn in d.keys():
                if (isinstance(d[fn], dict)):
                    self.writeDict(s, d[fn], fn)
                else:
                    s.writeStringElement(_sobjectNs, fn, d[fn])
            s.endElement()

    def writeSObjects(self, s, sObjects, elemName="sObjects"):
        if islst(sObjects):
            for o in sObjects:
                self.writeSObjects(s, o, elemName)
        else:
            s.startElement(_partnerNs, elemName)
            # type has to go first
            s.writeStringElement(_sobjectNs, "type", sObjects['type'])
            for fn in sObjects.keys():
                if (fn != 'type'):
                    if (isinstance(sObjects[fn], dict)):
                        self.writeSObjects(s, sObjects[fn], fn)
                    else:
                        s.writeStringElement(_sobjectNs, fn, sObjects[fn])
            s.endElement()


class LogoutRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "logout")


class QueryOptionsRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, batchSize, operationName):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, operationName)
        self.batchSize = batchSize

    def writeHeaders(self, s):
        AuthenticatedRequest.writeHeaders(self, s)
        s.startElement(_partnerNs, "QueryOptions")
        s.writeStringElement(_partnerNs, "batchSize", self.batchSize)
        s.endElement()


class QueryRequest(QueryOptionsRequest):
    def __init__(self, serverUrl, sessionId, headers, batchSize, soql, operationName="query"):
        QueryOptionsRequest.__init__(self, serverUrl, sessionId, headers, batchSize, operationName)
        self.__query = soql

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "queryString", self.__query)


class QueryMoreRequest(QueryOptionsRequest):
    def __init__(self, serverUrl, sessionId, headers, batchSize, queryLocator):
        QueryOptionsRequest.__init__(self, serverUrl, sessionId, headers, batchSize, "queryMore")
        self.__queryLocator = queryLocator

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "queryLocator", self.__queryLocator)


class SearchRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sosl):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "search")
        self.__query = sosl

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "searchString", self.__query)


class GetUpdatedRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjectType, start, end, operationName="getUpdated"):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, operationName)
        self.__sObjectType = sObjectType
        self.__start = start
        self.__end = end

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "sObjectType", self.__sObjectType)
        s.writeStringElement(_partnerNs, "startDate", self.__start)
        s.writeStringElement(_partnerNs, "endDate", self.__end)


class GetDeletedRequest(GetUpdatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjectType, start, end):
        GetUpdatedRequest.__init__(self, serverUrl, sessionId, headers, sObjectType, start, end, "getDeleted")


class UpsertRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, externalIdName, sObjects):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "upsert")
        self.__externalIdName = externalIdName
        self.__sObjects = sObjects

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "externalIDFieldName", self.__externalIdName)
        self.writeSObjects(s, self.__sObjects)


class UpdateRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjects, operationName="update"):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, operationName)
        self.__sObjects = sObjects

    def writeBody(self, s):
        self.writeSObjects(s, self.__sObjects)


class CreateRequest(UpdateRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjects):
        UpdateRequest.__init__(self, serverUrl, sessionId, headers, sObjects, "create")


class DeleteRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, ids, operationName="delete"):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, operationName)
        self.__ids = ids

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "id", self.__ids)


class UndeleteRequest(DeleteRequest):
    def __init__(self, serverUrl, sessionId, headers, ids):
        DeleteRequest.__init__(self, serverUrl, sessionId, headers, ids, "undelete")


class RetrieveRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, fields, sObjectType, ids):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "retrieve")
        self.__fields = fields
        self.__sObjectType = sObjectType
        self.__ids = ids

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "fieldList", self.__fields)
        s.writeStringElement(_partnerNs, "sObjectType", self.__sObjectType)
        s.writeStringElement(_partnerNs, "ids", self.__ids)


class ResetPasswordRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, userId):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "resetPassword")
        self.__userId = userId

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "userId", self.__userId)


class SetPasswordRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, userId, password):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "setPassword")
        self.__userId = userId
        self.__password = password

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "userId", self.__userId)
        s.writeStringElement(_partnerNs, "password", self.__password)


class ConvertLeadRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, leadConverts):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "convertLead")
        self.__leads = leadConverts

    def writeBody(self, s):
        self.writeDict(s, "leadConverts", self.__leads)


class DescribeSObjectsRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjectTypes):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "describeSObjects")
        self.__sObjectTypes = sObjectTypes

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "sObjectType", self.__sObjectTypes)


class DescribeLayoutRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, sObjectType):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "describeLayout")
        self.__sObjectType = sObjectType

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "sObjectType", self.__sObjectType)


class DescribeQuickActionsRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, actions):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "describeQuickActions")
        self.__actions = actions

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "action", self.__actions)


class DescribeAvailableQuickActionsRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, parentType):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "describeAvailableQuickActions")
        self.__parentType = parentType

    def writeBody(self, s):
        s.writeStringElement(_partnerNs, "parentType", self.__parentType)


class PerformQuickActionsRequest(AuthenticatedRequest):
    def __init__(self, serverUrl, sessionId, headers, actions):
        AuthenticatedRequest.__init__(self, serverUrl, sessionId, headers, "performQuickActions")
        self.__actions = actions

    def writeBody(self, s):
        if (islst(self.__actions)):
            for action in self.__actions:
                self.writeQuckAction(s, action)
        else:
            self.writeQuickAction(s, self.__actions)

    def writeQuickAction(self, s, action):
        s.startElement(_partnerNs, "quickActions")
        s.writeStringElement(_partnerNs, "parentId", action.get("parentId"))
        s.writeStringElement(_partnerNs, "quickActionName", action["quickActionName"])
        self.writeSObjects(s, action["records"], "records")
        s.endElement()
