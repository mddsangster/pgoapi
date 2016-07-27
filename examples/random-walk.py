#!/usr/bin/env python
"""
pgoapi - Pokemon Go API
Copyright (c) 2016 tjado <https://github.com/tejado>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
OR OTHER DEALINGS IN THE SOFTWARE.

Author: tjado <https://github.com/tejado>
"""

import os
import re
import sys
import json
import time
import struct
import pprint
import logging
import requests
import argparse
import getpass
import random
import urllib
import math
import datetime

# add directory of this file to PATH, so that the package will be found
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)),".."))

# import Pokemon Go API lib
from pgoapi import pgoapi
from pgoapi import utilities as util

# other stuff
from google.protobuf.internal import encoder
from geopy.geocoders import GoogleV3
from s2sphere import Cell, CellId, LatLng

log = logging.getLogger(__name__)

def get_pos_by_name(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name, timeout=10)
    if not loc:
        return None
    log.info('Your given location: %s', loc.address.encode('utf-8'))
    log.info('lat/long/alt: %s %s %s', loc.latitude, loc.longitude, loc.altitude)

    return (loc.latitude, loc.longitude, loc.altitude)

def get_cell_ids(lat, long, radius = 10):
    origin = CellId.from_lat_lng(LatLng.from_degrees(lat, long)).parent(15)
    walk = [origin.id()]
    right = origin.next()
    left = origin.prev()

    # Search around provided radius
    for i in range(radius):
        walk.append(right.id())
        walk.append(left.id())
        right = right.next()
        left = left.prev()

    # Return everything
    return sorted(walk)

def encode(cellid):
    output = []
    encoder._VarintEncoder()(output.append, cellid)
    return ''.join(output)

def init_config():
    parser = argparse.ArgumentParser()
    config_file = "config.json"

    # If config file exists, load variables from json
    load   = {}
    if os.path.isfile(config_file):
        with open(config_file) as data:
            load.update(json.load(data))

    # Read passed in Arguments
    required = lambda x: not x in load
    parser.add_argument("-a", "--auth_service", help="Auth Service ('ptc' or 'google')",
        required=required("auth_service"))
    parser.add_argument("-u", "--username", help="Username", required=required("username"))
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-l", "--location", help="Location", required=required("location"))
    parser.add_argument("-k", "--key", help="Google Maps API Key", required=required("key"))
    parser.add_argument("-q", "--powerquotient", type=int, help="Minimum power quotient for keeping pokemon")
    parser.set_defaults(powerquotient=0)
    config = parser.parse_args()

    # Passed in arguments shoud trump
    for key in config.__dict__:
        if key in load and config.__dict__[key] == None:
            config.__dict__[key] = str(load[key])

    if config.__dict__["password"] is None:
        log.info("Secure Password Input (if there is no password prompt, use --password <pw>):")
        config.__dict__["password"] = getpass.getpass()

    if config.auth_service not in ['ptc', 'google']:
      log.error("Invalid Auth service specified! ('ptc' or 'google')")
      return None

    return config

def gmaps_dbug(coords, spins, catches, key):
    url_string = 'http://maps.googleapis.com/maps/api/staticmap?key=%s&size=800x800&path=' % (key)
    for coord in coords:
        url_string += '{},{}|'.format(coord['lat'], coord['lng'])
    url_string = url_string[:-1]
    for spin in spins:
        url_string += '&markers=color:blue%7C{},{}'.format(spin['latitude'], spin['longitude'])
    for catch in catches:
        url_string += '&markers=color:green%7C{},{}'.format(catch['latitude'], catch['longitude'])
    return url_string

def get_key_from_pokemon(pokemon):
    return '{}-{}'.format(pokemon['spawn_point_id'], pokemon['pokemon_data']['pokemon_id'])

def find_poi(api, lat, lng, balls):
    spins = []
    catches = []
    stardust = 0
    candy = 0
    xp = 0
    poi = {'pokemons': {}, 'forts': []}
    cell_ids = get_cell_ids(lat, lng)
    timestamps = [0,] * len(cell_ids)
    api.get_map_objects(latitude = lat, longitude = lng, since_timestamp_ms = timestamps, cell_id = cell_ids)
    response_dict = api.call()
    if 'status' in response_dict['responses']['GET_MAP_OBJECTS']:
        if response_dict['responses']['GET_MAP_OBJECTS']['status'] == 1:
            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'catchable_pokemons' in map_cell:
                    for pokemon in map_cell['catchable_pokemons']:
                        if math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng) < float("inf"):# 0.0004495:
                            api.encounter(encounter_id = pokemon['encounter_id'], spawn_point_id = pokemon['spawn_point_id'], player_latitude = lat, player_longitude = lng)
                            enc = api.call()
                            if enc['responses']['ENCOUNTER']['status'] == 1:
                                while True:
                                    if len(balls) == 0:
                                        break
                                    normalized_reticle_size = 1.950 - random.uniform(0,.5)
                                    normalized_hit_position = 1.0# + random.uniform(0,.1)
                                    spin_modifier = 1.0 - random.uniform(0,.1)
                                    #print (normalized_reticle_size, normalized_hit_position, spin_modifier)
                                    api.catch_pokemon(encounter_id = pokemon['encounter_id'], pokeball = balls.pop(0), normalized_reticle_size = normalized_reticle_size, spawn_point_id = pokemon['spawn_point_id'], hit_pokemon = True, spin_modifier = spin_modifier, normalized_hit_position = normalized_hit_position)
                                    ret = api.call()
                                    if "status" in ret['responses']['CATCH_POKEMON']:
                                        if ret['responses']['CATCH_POKEMON']['status'] == 1:
                                            print "CATCH_GOOD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng),normalized_reticle_size,spin_modifier)
                                            stardust += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["stardust"])
                                            candy += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["candy"])
                                            xp += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["xp"])
                                            catches.append(pokemon)
                                            break
                                        elif ret['responses']['CATCH_POKEMON']['status'] == 0 or ret['responses']['CATCH_POKEMON']['status'] == 3:
                                            break
                                    else:
                                        print "CATCH_BAD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng),normalized_reticle_size,spin_modifier)
                                        #print pokemon
                                        #print ret
                                        break
                if 'forts' in map_cell:
                    for fort in map_cell['forts']:
                        poi['forts'].append(fort)
                        if "type" in fort and fort["type"] == 1 and not "cooldown_complete_timestamp_ms" in fort:
                            if math.hypot(fort['latitude'] - lat, fort['longitude'] - lng) < 0.0004495:
                                api.fort_search(fort_id = fort['id'], fort_latitude = fort['latitude'], fort_longitude = fort['longitude'], player_latitude=lat, player_longitude=lng)
                                ret = api.call()
                                if ret["responses"]["FORT_SEARCH"]["result"] == 1:
                                    # print ret["responses"]["FORT_SEARCH"]
                                    xp += ret["responses"]["FORT_SEARCH"]['experience_awarded']
                                    spins.append(fort)
    # print('POI dictionary: \n\r{}'.format(pprint.PrettyPrinter(indent=4).pformat(poi)))
    return spins, catches, stardust, candy, xp

def main():
    config = init_config()
    if not config:
        return

    position = get_pos_by_name(config.location)
    if not position:
        log.error('Position could not be found by name')
        return

    # instantiate pgoapi
    api = pgoapi.PGoApi()

    # provide player position on the earth
    api.set_position(*position)

    if not api.login(config.auth_service, config.username, config.password):
        return

    api.get_player()
    player = api.call()["responses"]["GET_PLAYER"]["player_data"]
    username = player["username"]

    coords = []
    spins = []
    catches = []
    releases = 0
    stardust = 0
    candy = 0
    xp = 0
    incubators_loaded = 0
    eggs_hatched = 0

    m1 = random.choice([-1,1])
    m2 = random.choice([-1,1])

    start_time = time.time()

    last_walked = 0

    while True:
        inventory = 0
        mons = 0
        position = api.get_position()
        target_km = []
        api.get_inventory()
        items = api.call()["responses"]["GET_INVENTORY"]["inventory_delta"]["inventory_items"]
        walked = 0
        balls = []
        eggs = []
        incubators = []
        for item in items:
            if "pokemon_data" in item["inventory_item_data"]:
                if "is_egg" in item["inventory_item_data"]["pokemon_data"]:
                    eggs.append(item["inventory_item_data"]["pokemon_data"])
                    mons += 1
                else:
                    pq = 0
                    for iv in ["individual_attack","individual_defense","individual_stamina"]:
                        if iv in item["inventory_item_data"]["pokemon_data"]:
                            pq += item["inventory_item_data"]["pokemon_data"][iv]
                    pq = int(round(pq/45.0,2)*100)
                    if pq < config.powerquotient:
                        api.release_pokemon(pokemon_id = item["inventory_item_data"]["pokemon_data"]["id"])
                        ret = api.call()
                        if "result" in ret["responses"]["RELEASE_POKEMON"] and ret["responses"]["RELEASE_POKEMON"]["result"] == 1:
                            candy += ret["responses"]["RELEASE_POKEMON"]["candy_awarded"]
                            releases += 1
                        else:
                            mons += 1
                    else:
                        mons += 1
            if "item" in item["inventory_item_data"]:
                for i in [1,2,3]:
                    if item["inventory_item_data"]["item"]["item_id"] == i:
                        if "count" in item["inventory_item_data"]["item"]:
                            balls += [i]*item["inventory_item_data"]["item"]["count"]
                        else:
                            balls += [i]
                if "count" in item["inventory_item_data"]["item"]:
                    inventory += item["inventory_item_data"]["item"]["count"]
                else:
                    inventory += 1
            if "egg_incubators" in item["inventory_item_data"]:
                for ib in item["inventory_item_data"]["egg_incubators"]["egg_incubator"]:
                    incubators.append(ib)
                    if "target_km_walked" in ib:
                        target_km.append(ib["target_km_walked"])
            elif "player_stats" in item["inventory_item_data"]:
                walked = item["inventory_item_data"]["player_stats"]["km_walked"]
        if len(target_km) > 0:
            target_km = min(target_km)
            if walked >= target_km:
                api.get_hatched_eggs()
                ret = api.call()
                print ret
        else:
            target_km = -1

        for ib in incubators:
            if not 'pokemon_id' in ib:
                if len(eggs) > 0:
                    api.use_item_egg_incubator(item_id=ib['id'],pokemon_id=eggs.pop(0)['id'])
                    ret = api.call()
                    if "result" in ret["responses"]['USE_ITEM_EGG_INCUBATOR'] and ret["responses"]['USE_ITEM_EGG_INCUBATOR']["result"] == 1:
                        incubators_loaded += 1

        if last_walked != walked:
            m1 = random.choice([-1,1])
            m2 = random.choice([-1,1])
        last_walked = walked

        r = .0002 + random.gauss(.00005, .00005)
        pmod = random.choice([0,1,2])
        if pmod==0:
            newposition = (position[0]+(r*m1), position[1], 0)
        elif pmod==1:
            newposition = (position[0], position[1]+(r*m2), 0)
        elif pmod==2:
            newposition = (position[0]+(r*m1), position[1]+(r*m2), 0)

        api.set_position(*newposition)
        api.player_update(latitude = util.f2i(newposition[0]), longitude = util.f2i(newposition[1]))
        api.call()

        newspins, newcatches, newstardust, newcandy, newxp = find_poi(api, newposition[0], newposition[1], sorted(balls))
        spins += newspins
        catches += newcatches
        stardust += newstardust
        candy += newcandy
        xp += newxp
        coords.append({'lat': newposition[0], 'lng': newposition[1]})

        m, s = divmod(time.time()-start_time, 60)
        h, m = divmod(m, 60)

        sys.stdout.write("=========================================\n")
        sys.stdout.write(" username: %s\n" % (username))
        sys.stdout.write(" elapsed_time: %d:%02d:%02d\n" % (h, m, s))
        sys.stdout.write(" km_walked: %.1f\n" % (walked))
        sys.stdout.write(" target_km_walked: %.1f\n" % (target_km))
        sys.stdout.write(" spins: %d\n" % (len(spins)))
        sys.stdout.write(" inventory: %d/%d\n" % (inventory, player["max_item_storage"]))
        sys.stdout.write(" catches: %d\n" % len(catches))
        sys.stdout.write(" releases: %d\n" % releases)
        sys.stdout.write(" incubators_loaded: %d\n" % incubators_loaded)
        sys.stdout.write(" eggs_hatched: %d\n" % eggs_hatched)
        sys.stdout.write(" pokemon: %d/%d\n" % (mons, player["max_pokemon_storage"]))
        sys.stdout.write(" stardust: %d\n" % (stardust))
        sys.stdout.write(" candy: %d\n" % (candy))
        sys.stdout.write(" xp: %d\n" % (xp))
        sys.stdout.write(" position: (%.5f,%.5f)\n" % (newposition[0], newposition[1]))
        sys.stdout.write("=========================================\n")
        sys.stdout.flush()

        urllib.urlretrieve(gmaps_dbug(coords, spins, catches, config.key), "%s.png" % username)

        time.sleep(5)



if __name__ == '__main__':
    main()
