#!/usr/bin/env python

from twisted.internet import reactor
from twisted.internet.ssl import ClientContextFactory
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from zope.interface import implements

from twisted.internet.defer import succeed
from twisted.web.iweb import IBodyProducer

from twisted.python import log

import sys
import argparse
import json
import pprint
import urllib

import gpsoauth
from geopy.geocoders import GoogleV3

def get_pos_by_name(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name)
    if not loc:
        return None

    log.msg('[get_pos_by_name] Your given location: %s' % loc.address.encode('utf-8'))
    log.msg('[get_pos_by_name] lat/long/alt: %s %s %s' % (loc.latitude, loc.longitude, loc.altitude))

    return (loc.latitude, loc.longitude, loc.altitude)

def cbBody(body, callback):
    callback(body)

def cbResponse(response, callback, printHeaders=False):
    print "RESPONSE"
    if printHeaders:
        print pprint.pformat(list(response.headers.getAllRawHeaders()))
    d = readBody(response)
    d.addCallback(cbBody, callback)
    return d

def cbShutdown(response):
    print "ERROR"
    print response
    reactor.stop()

def printInfo(data):
    print "DATA"
    print data
    # pprint.PrettyPrinter(indent=2).pprint(json.loads(data))

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

GOOGLE_LOGIN_ANDROID_ID = '9774d56d682e549c'
GOOGLE_LOGIN_SERVICE= 'audience:server:client_id:848232511240-7so421jotr2609rmqakceuu1luuq0ptb.apps.googleusercontent.com'
GOOGLE_LOGIN_APP = 'com.nianticlabs.pokemongo'
GOOGLE_LOGIN_CLIENT_SIG = '321187995bc7cdc2b5fc91b11a96e2baa8602c62'

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", help="Username", required=True)
    parser.add_argument("-p", "--password", help="Password", required=True)
    parser.add_argument("-l", "--location", help="Location", required=True)
    config = parser.parse_args()

    log.startLogging(sys.stdout)

    position = get_pos_by_name(config.location)

    contextFactory = WebClientContextFactory()
    agent = Agent(reactor, contextFactory)

    email = config.username
    password = config.password
    service = 'ac2dm'
    device_country = 'us'
    lang = 'en'
    sdk_version = 17
    android_key_7_3_29 = gpsoauth.android_key_7_3_29
    android_id = GOOGLE_LOGIN_ANDROID_ID

    data =  urllib.urlencode({
        'accountType': 'HOSTED_OR_GOOGLE',
        'Email':   email,
        'has_permission':  1,
        'add_account': 1,
        'EncryptedPasswd': gpsoauth.google.signature(email, password, android_key_7_3_29),
        'service': service,
        'source':  'android',
        'androidId':   android_id,
        'device_country':  device_country,
        'operatorCountry': device_country,
        'lang':    lang,
        'sdk_version': sdk_version
    })

    print
    print data
    print

    d = agent.request('POST', gpsoauth.auth_url, Headers({
        'Content-Type': ['application/x-www-form-urlencoded'],
        'Content-Length': [str(len(data))],
        'User-Agent': [gpsoauth.useragent]
        }), StringProducer(data))
    d.addCallback(cbResponse, printInfo, True)
    #d.addErrback(cbShutdown)

    reactor.run()
