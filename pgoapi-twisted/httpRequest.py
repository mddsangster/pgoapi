import urllib
from twisted.internet import protocol
from twisted.internet import defer
from twisted.web.http_headers import Headers
from twisted.internet import reactor
from twisted.web.client import Agent, HTTPConnectionPool
from twisted.web.iweb import IBodyProducer
from zope.interface import implements
from twisted.internet.defer import succeed
from twisted.internet.ssl import ClientContextFactory

class WebClientContextFactory(ClientContextFactory):
    def getContext(self, hostname, port):
        return ClientContextFactory.getContext(self)

class StringProducer(object):
    implements(IBodyProducer)

    def __init__(self, body):
        self.body = body
        self.length = len(body)

    def startProducing(self, consumer):
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass

class SimpleReceiver(protocol.Protocol):
    def __init__(self, d):
        self.buf = ''; self.d = d

    def dataReceived(self, data):
        self.buf += data

    def connectionLost(self, reason):
        self.d.callback(self.buf)

def httpRequest(url, values=None, headers=None, method='POST'):

    contextFactory = WebClientContextFactory()
    pool = HTTPConnectionPool(reactor)
    agent = Agent(reactor, contextFactory, pool=pool)
    data = urllib.urlencode(values) if values else None

    d = agent.request(method, url, Headers(headers) if headers else {},
        StringProducer(data) if data else None
        )

    def handle_response(response):
        if response.code == 204:
            d = defer.succeed('')
        else:
            d = defer.Deferred()
            response.deliverBody(SimpleReceiver(d))
        return d

    d.addCallback(handle_response)
    return d
