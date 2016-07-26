#!/usr/bin/env python

import sys, os
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)),"../"))

from twisted.internet import reactor
from twisted.internet import task
from httpRequest import httpRequest
from twisted.python import log

import argparse

import gpsoauth
from geopy.geocoders import GoogleV3

from pgoapi.utilities import f2i, h2f
from pgoapi import protos
import pgoapi.rpc_api
from POGOProtos.Networking.Requests_pb2 import RequestType
from POGOProtos.Networking.Envelopes_pb2 import RequestEnvelope

GOOGLE_LOGIN_ANDROID_ID = '9774d56d682e549c'
GOOGLE_LOGIN_SERVICE= 'audience:server:client_id:848232511240-7so421jotr2609rmqakceuu1luuq0ptb.apps.googleusercontent.com'
GOOGLE_LOGIN_APP = 'com.nianticlabs.pokemongo'
GOOGLE_LOGIN_CLIENT_SIG = '321187995bc7cdc2b5fc91b11a96e2baa8602c62'

API_ENTRY = 'https://pgorelease.nianticlabs.com/plfe/rpc'

def get_pos_by_name(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name)
    if not loc:
        return None
    log.msg('[get_pos_by_name] Your given location: %s' % loc.address.encode('utf-8'))
    log.msg('[get_pos_by_name] lat/long/alt: %s %s %s' % (loc.latitude, loc.longitude, loc.altitude))
    return (loc.latitude, loc.longitude, loc.altitude)

class PoGoAPI(object):

    def __init__(self):
        self._auth_token = None
        self._position_lat = 0
        self._position_lng = 0
        self._position_alt = 0

    def login(self, email, password, device_country='us', lang='en'):

        master_login_data =  {
            'accountType': 'HOSTED_OR_GOOGLE',
            'Email': email,
            'has_permission': 1,
            'add_account': 1,
            'EncryptedPasswd': gpsoauth.google.signature(email, password, gpsoauth.android_key_7_3_29),
            'service': 'ac2dm',
            'source': 'android',
            'androidId': GOOGLE_LOGIN_ANDROID_ID,
            'device_country': device_country,
            'operatorCountry': device_country,
            'lang': lang,
            'sdk_version': 17
        }

        oauth_data = {
            'accountType': 'HOSTED_OR_GOOGLE',
            'Email': email,
            'has_permission':  1,
            'EncryptedPasswd': None,
            'service': GOOGLE_LOGIN_SERVICE,
            'source': 'android',
            'androidId': GOOGLE_LOGIN_ANDROID_ID,
            'app': GOOGLE_LOGIN_APP,
            'client_sig': GOOGLE_LOGIN_CLIENT_SIG,
            'device_country': device_country,
            'operatorCountry': device_country,
            'lang': lang,
            'sdk_version': 17
        }

        d = httpRequest(gpsoauth.auth_url, master_login_data, {'Content-Type': ['application/x-www-form-urlencoded',]}, 'POST')
        d.addCallback(self.master_login_cb, oauth_data, self.oauth_cb)
        return d

    def master_login_cb(self, data, oauth_data, oauth_cb):
        response = gpsoauth.google.parse_auth_response(data)
        oauth_data["EncryptedPasswd"] = response["Token"]
        d = httpRequest(gpsoauth.auth_url, oauth_data, {'Content-Type': ['application/x-www-form-urlencoded',]}, 'POST')
        d.addCallback(oauth_cb)
        return d

    def oauth_cb(self, data):
        response = gpsoauth.google.parse_auth_response(data)
        self._auth_token = response["Auth"]
        request = RequestEnvelope()
        request.status_code = 2
        request.request_id = self.get_rpc_id()
        request.latitude, request.longitude, request.altitude = self.get_position()
        request.auth_info.provider = "google"
        request.auth_info.token.contents = self.get_token()
        request.auth_info.token.unknown2 = 59
        request.unknown12 = 989
        print request
        #request = self._build_sub_requests(request, subrequests)
        return response

    def get_token(self):
        return self._auth_token

    def set_position(self, lat, lng, alt):
        self._position_lat = f2i(lat)
        self._position_lng = f2i(lng)
        self._position_alt = f2i(alt)

    def get_rpc_id(self):
        return 8145806132888207460

    def get_position(self):
        return (self._position_lat, self._position_lng, self._position_alt)

if __name__ == '__main__':

    log.startLogging(sys.stdout)

    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", help="Username", required=True)
    parser.add_argument("-p", "--password", help="Password", required=True)
    parser.add_argument("-l", "--location", help="Location", required=True)
    config = parser.parse_args()

    api = PoGoAPI()

    position = get_pos_by_name(config.location)
    reactor.callLater(0, api.set_position, *position)

    d = task.deferLater(reactor, 0, api.login, config.username, config.password)
    def called(result):
        print result
    d.addCallback(called)
    reactor.run()
