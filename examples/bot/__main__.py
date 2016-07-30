#!/usr/bin/env python

import os
import sys
import json
import argparse

from geopy.geocoders import GoogleV3

from bot import PoGoBot

def get_pos_by_name(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name, timeout=10)
    if not loc:
        return None
    return (loc.latitude, loc.longitude, loc.altitude)

def init_config():
    parser = argparse.ArgumentParser()
    config_file = "config.json"

    # If config file exists, load variables from json
    config = {}
    if os.path.isfile(config_file):
        with open(config_file) as data:
            config.update(json.load(data))

    # Read passed in Arguments
    required = lambda x: not x in config
    parser.add_argument("-a", "--auth_service", help="Auth Service ('ptc' or 'google')", required=required("auth_service"))
    parser.add_argument("-u", "--username", help="Username", required=required("username"))
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-l", "--location", help="Location", required=required("location"))
    parser.add_argument("-k", "--key", help="Google Maps API Key", required=required("key"))
    parser.add_argument("-q", "--powerquotient", type=int, help="Minimum power quotient for keeping pokemon")
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true')
    parser.set_defaults(DEBUG=False, powerquotient=0)
    args = parser.parse_args()

    # Passed in arguments shoud trump
    for key in args.__dict__:
        if args.__dict__[key] != None:
            config[key] = args.__dict__[key]

    if config["auth_service"] not in ['ptc', 'google']:
        log.error("Invalid Auth service specified! ('ptc' or 'google')")
        return None

    return config

if __name__ == '__main__':

    config = init_config()
    if not config:
        sys.exit(1)

    config["location"] = get_pos_by_name(config["location"])
    if not config["location"]:
        sys.exit(2)

    bot = PoGoBot(config)
    bot.login()
    bot.play()
