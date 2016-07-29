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

from __future__ import print_function

import os
import sys
import json
import time
import logging
import argparse
import getpass
import random
import math

# add directory of this file to PATH, so that the package will be found
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

# import Pokemon Go API lib
from pgoapi import pgoapi
from pgoapi import utilities as util

# other stuff
from google.protobuf.internal import encoder
from geopy.geocoders import GoogleV3
from s2sphere import CellId, LatLng

log = logging.getLogger(__name__)

class Map(object):
    def __init__(self):
        self._points = []
        self._positions = []
        self._player = None
    def add_point(self, coordinates, color="#FF0000"):
        self._points.append((coordinates, color))
    def add_position(self, coordinates):
        self._positions.append(coordinates)
    def __str__(self):
        centerLat = sum((x[0] for x in self._positions)) / len(self._positions)
        centerLon = sum((x[1] for x in self._positions)) / len(self._positions)
        pathCode = """
            var walkPathCoords = [{path}];
            var walkPath = new google.maps.Polyline({{
                path: walkPathCoords,
                geodesic: true,
                strokeColor: '#7F00FF',
                strokeOpacity: 0.5,
                strokeWeight: 4}});
            walkPath.setMap(map);
        """.format(path=",".join(["new google.maps.LatLng(%f,%f)" % (p[0], p[1]) for p in self._positions]))
        markersCode = "\n".join(
            ["""var marker = new google.maps.Marker({{
                position: {{lat: {lat}, lng: {lng}}},
                map: map
                }});
                marker.setIcon('{icon}');""".format(lat=x[0][0], lng=x[0][1], icon=x[1]) for x in self._points
            ])
        playerCode = """var marker = new google.maps.Marker({{
                        position: {{lat: {lat}, lng: {lng}}},
                        map: map
                        }});
                        marker.setIcon('http://maps.google.com/mapfiles/ms/icons/purple-dot.png');""".format(lat=self._player[0], lng=self._player[1])
        return """
            <script src="https://maps.googleapis.com/maps/api/js?v=3.exp&sensor=false"></script>
            <div id="map-canvas" style="height: 100%; width: 100%"></div>
            <script type="text/javascript">
                var map;
                function show_map() {{
                    map = new google.maps.Map(document.getElementById("map-canvas"), {{
                        zoom: 16,
                        center: new google.maps.LatLng({centerLat}, {centerLon})
                    }});
                    {pathCode}
                    {playerCode}
                    {markersCode}
                    var bounds = new google.maps.LatLngBounds();
                    var arrayLength = walkPathCoords.length;
                    for (var i = 0; i < arrayLength; i++) {{
                        bounds.extend(walkPathCoords[i]);
                    }}
                    map.fitBounds(bounds);
                }}
                google.maps.event.addDomListener(window, 'load', show_map);
            </script>
        """.format(centerLat=centerLat, centerLon=centerLon,
                   pathCode=pathCode, playerCode=playerCode,
                   markersCode=markersCode)

def get_pos_by_name(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name, timeout=10)
    if not loc:
        return None
    log.info('Your given location: %s', loc.address.encode('utf-8'))
    log.info('lat/long/alt: %s %s %s', loc.latitude, loc.longitude, loc.altitude)

    return (loc.latitude, loc.longitude, loc.altitude)

def get_cell_ids(lat, lng, radius=10):
    origin = CellId.from_lat_lng(LatLng.from_degrees(lat, lng)).parent(15)
    walk = [origin.id()]
    right = origin.next()
    left = origin.prev()

    # Search around provided radius
    for _ in range(radius):
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
    load = {}
    if os.path.isfile(config_file):
        with open(config_file) as data:
            load.update(json.load(data))

    # Read passed in Arguments
    required = lambda x: not x in load
    parser.add_argument("-a", "--auth_service", help="Auth Service ('ptc' or 'google')", required=required("auth_service"))
    parser.add_argument("-u", "--username", help="Username", required=required("username"))
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-l", "--location", help="Location", required=required("location"))
    parser.add_argument("-k", "--key", help="Google Maps API Key", required=required("key"))
    parser.add_argument("-q", "--powerquotient", type=int, help="Minimum power quotient for keeping pokemon")
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true')
    parser.set_defaults(DEBUG=False, powerquotient=0)
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
    while True:
        api.get_map_objects(latitude=lat, longitude=lng, since_timestamp_ms=timestamps, cell_id=cell_ids)
        response_dict = api.call()
        if "GET_MAP_OBJECTS" in response_dict['responses']:
            break
    if 'status' in response_dict['responses']['GET_MAP_OBJECTS']:
        if response_dict['responses']['GET_MAP_OBJECTS']['status'] == 1:
            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'wild_pokemons' in map_cell:
                    for pokemon in map_cell['wild_pokemons']:
                        if math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng) < float("inf"):# 0.0004495:
                            while True:
                                api.encounter(encounter_id=pokemon['encounter_id'], spawn_point_id=pokemon['spawn_point_id'], player_latitude = lat, player_longitude = lng)
                                enc = api.call()
                                if "ENCOUNTER" in enc['responses']:
                                    break
                            if enc['responses']['ENCOUNTER']['status'] == 1:
                                while True:
                                    if len(balls) == 0:
                                        break
                                    normalized_reticle_size = 1.950 - random.uniform(0, .5)
                                    normalized_hit_position = 1.0# + random.uniform(0,.1)
                                    spin_modifier = 1.0 - random.uniform(0, .1)
                                    #print (normalized_reticle_size, normalized_hit_position, spin_modifier)
                                    while True:
                                        api.catch_pokemon(encounter_id=pokemon['encounter_id'], spawn_point_id = pokemon['spawn_point_id'], pokeball=balls.pop(0), normalized_reticle_size = normalized_reticle_size, hit_pokemon=True, spin_modifier=spin_modifier, normalized_hit_position=normalized_hit_position)
                                        ret = api.call()
                                        if "CATCH_POKEMON" in ret['responses']:
                                            break
                                    if "status" in ret['responses']['CATCH_POKEMON']:
                                        if ret['responses']['CATCH_POKEMON']['status'] == 1:
                                            print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                                            print("CATCH_GOOD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng), normalized_reticle_size, spin_modifier))
                                            print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                                            stardust += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["stardust"])
                                            candy += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["candy"])
                                            xp += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["xp"])
                                            catches.append(pokemon)
                                            break
                                        elif ret['responses']['CATCH_POKEMON']['status'] == 0 or ret['responses']['CATCH_POKEMON']['status'] == 3:
                                            break
                                    else:
                                        print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                                        print("CATCH_BAD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng), normalized_reticle_size, spin_modifier))
                                        print(pokemon)
                                        print(ret)
                                        print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                                        break
                if 'forts' in map_cell:
                    for fort in map_cell['forts']:
                        poi['forts'].append(fort)
                        if "type" in fort and fort["type"] == 1 and not "cooldown_complete_timestamp_ms" in fort:
                            if math.hypot(fort['latitude'] - lat, fort['longitude'] - lng) < 0.0004495:
                                while True:
                                    api.fort_search(fort_id=fort['id'], fort_latitude=fort['latitude'], fort_longitude=fort['longitude'], player_latitude=lat, player_longitude=lng)
                                    ret = api.call()
                                    if "FORT_SEARCH" in ret['responses']:
                                        break
                                if ret["responses"]["FORT_SEARCH"]["result"] == 1:
                                    if 'experience_awarded' in ret["responses"]["FORT_SEARCH"]:
                                        xp += ret["responses"]["FORT_SEARCH"]['experience_awarded']
                                    spins.append(fort)
    # print('POI dictionary: \n\r{}'.format(pprint.PrettyPrinter(indent=4).pformat(poi)))
    return spins, catches, stardust, candy, xp

def main():

    #logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(module)10s] [%(levelname)5s] %(message)s')
    # log level for http request class
    #logging.getLogger("requests").setLevel(logging.WARNING)
    # log level for main pgoapi class
    #logging.getLogger("pgoapi").setLevel(logging.INFO)
    # log level for internal pgoapi class
    #logging.getLogger("rpc_api").setLevel(logging.DEBUG)

    config = init_config()
    if not config:
        return

    #if config.debug:
        #logging.getLogger("requests").setLevel(logging.DEBUG)
        #logging.getLogger("pgoapi").setLevel(logging.DEBUG)
        #logging.getLogger("rpc_api").setLevel(logging.DEBUG)

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

    coords = []
    spins = []
    catches = []
    recycled_items = 0
    releases = 0
    stardust = 0
    candy = 0
    xp = 0
    incubators_loaded = 0
    eggs_hatched = 0

    ang = random.uniform(0,360)

    start_time = time.time()

    last_walked = 0

    username = "unknown"
    stats = None

    while True:
        api.get_player()
        player = api.call()["responses"]["GET_PLAYER"]["player_data"]
        username = player["username"]
        total_stardust = 0
        for cur in player["currencies"]:
            if cur["name"] == "STARDUST":
                total_stardust = cur["amount"]
        inventory = 0
        mons = 0
        position = api.get_position()
        target_km = []
        while True:
            api.get_inventory()
            ret = api.call()
            if "GET_INVENTORY" in ret['responses']:
                items = ret["responses"]["GET_INVENTORY"]["inventory_delta"]["inventory_items"]
                break
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
                    for iv in ["individual_attack", "individual_defense", "individual_stamina"]:
                        if iv in item["inventory_item_data"]["pokemon_data"]:
                            pq += item["inventory_item_data"]["pokemon_data"][iv]
                    pq = int(round(pq/45.0,2)*100)
                    if pq < config.powerquotient:
                        while True:
                            api.release_pokemon(pokemon_id=item["inventory_item_data"]["pokemon_data"]["id"])
                            ret = api.call()
                            if "RELEASE_POKEMON" in ret['responses']:
                                break
                        if "result" in ret["responses"]["RELEASE_POKEMON"] and ret["responses"]["RELEASE_POKEMON"]["result"] == 1:
                            candy += ret["responses"]["RELEASE_POKEMON"]["candy_awarded"]
                            releases += 1
                        else:
                            mons += 1
                    else:
                        mons += 1
            if "item" in item["inventory_item_data"]:
                if item["inventory_item_data"]["item"]["item_id"] in [1,2,3]:
                    if "count" in item["inventory_item_data"]["item"]:
                        balls += [item["inventory_item_data"]["item"]["item_id"]]*item["inventory_item_data"]["item"]["count"]
                    else:
                        balls += [item["inventory_item_data"]["item"]["item_id"]]
                if "count" in item["inventory_item_data"]["item"]:
                    inventory += item["inventory_item_data"]["item"]["count"]
                else:
                    inventory += 1
                if item["inventory_item_data"]["item"]["item_id"] in [101,201,701]:
                    if "count" in item["inventory_item_data"]["item"]:
                        ri = item["inventory_item_data"]["item"]["count"]
                    else:
                        ri = 1
                    while True:
                        api.recycle_inventory_item(item_id=item["inventory_item_data"]["item"]["item_id"], count=ri)
                        ret =api.call()
                        if "RECYCLE_INVENTORY_ITEM" in ret['responses']:
                            break
                    if ret["responses"]['RECYCLE_INVENTORY_ITEM']["result"] == 1:
                        recycled_items += ri
                        inventory -= ri

            if "egg_incubators" in item["inventory_item_data"]:
                for ib in item["inventory_item_data"]["egg_incubators"]["egg_incubator"]:
                    incubators.append(ib)
                    if "target_km_walked" in ib:
                        target_km.append(ib["target_km_walked"])
            elif "player_stats" in item["inventory_item_data"]:
                stats = item["inventory_item_data"]["player_stats"]
                walked = item["inventory_item_data"]["player_stats"]["km_walked"]
        if len(target_km) > 0:
            target_km = min(target_km)
            if walked >= target_km:
                while True:
                    api.get_hatched_eggs()
                    ret = api.call()
                    if "GET_HATCHED_EGGS" in ret['responses']:
                        break
                print(ret)
                if "success" in ret['responses']['GET_HATCHED_EGGS'] and ret["responses"]['GET_HATCHED_EGGS']["success"]:
                    stardust += sum(ret['responses']["GET_HATCHED_EGGS"]["stardust_awarded"])
                    candy += sum(ret['responses']["GET_HATCHED_EGGS"]["candy_awarded"])
                    xp += sum(ret['responses']["GET_HATCHED_EGGS"]["experience_awarded"])
                    eggs_hatched += 1
        else:
            target_km = -1

        for ib in incubators:
            if not 'pokemon_id' in ib:
                if len(eggs) > 0:
                    while True:
                        api.use_item_egg_incubator(item_id=ib['id'],pokemon_id=eggs.pop(0)['id'])
                        ret = api.call()
                        if "USE_ITEM_EGG_INCUBATOR" in ret['responses']:
                            break
                    if "result" in ret["responses"]['USE_ITEM_EGG_INCUBATOR'] and ret["responses"]['USE_ITEM_EGG_INCUBATOR']["result"] == 1:
                        incubators_loaded += 1

        if last_walked != walked:
            ang = random.uniform(0,360)
        last_walked = walked

        r = .00015 + random.gauss(.00005, .00001)
        angtmp = (ang + random.gauss(0,.15)) % 360
        newposition = (position[0]+math.cos(angtmp)*r, position[1]+math.sin(angtmp)*r, 0)
        #ang = angtmp

        lat = util.f2i(newposition[0])
        lng = util.f2i(newposition[1])
        api.set_position(*newposition)
        api.player_update(latitude = lat, longitude = lng)
        api.call()

        normalized_reticle_size = 1.950 - random.uniform(0, .3)
        normalized_hit_position = 1.0# + random.uniform(0,.1)
        spin_modifier = 1.0 - random.uniform(0, .1)
        print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        while True:
            api.get_incense_pokemon(player_latitude=newposition[0], player_longitude=newposition[1])
            ret = api.call()
            if "GET_INCENSE_POKEMON" in ret['responses']:
                break
        print(ret)
        if ret["responses"]["GET_INCENSE_POKEMON"]["result"] == 1:
            pokemon = ret["responses"]["GET_INCENSE_POKEMON"]
            while True:
                api.incense_encounter(encounter_id=pokemon['encounter_id'], encounter_location=pokemon['encounter_location'])
                enc = api.call()
                if "INCENSE_ENCOUNTER" in enc['responses']:
                    break
            print(enc)
            if enc['responses']['INCENSE_ENCOUNTER']['result'] == 1:
                api.catch_pokemon(encounter_id=pokemon['encounter_id'], spawn_point_id=pokemon['encounter_location'], pokeball=balls.pop(0), normalized_reticle_size = normalized_reticle_size, hit_pokemon=True, spin_modifier=spin_modifier, normalized_hit_position=normalized_hit_position)
                ret = api.call()
                print(ret)
        print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")

        # while True:
        #     if len(balls) == 0:
        #         break
        #     normalized_reticle_size = 1.950 - random.uniform(0, .5)
        #     normalized_hit_position = 1.0# + random.uniform(0,.1)
        #     spin_modifier = 1.0 - random.uniform(0, .1)
        #     api.get_incense_pokemon()
        #     ret = api.call()
        #     print(("A",ret))
        #     if ret["responses"]["GET_INCENSE_POKEMON"]["result"] == 1:
        #         pokemon = ret["responses"]["GET_INCENSE_POKEMON"]
        #         api.incense_encounter(encounter_id=pokemon['encounter_id'], encounter_location=pokemon['encounter_location'])
        #         enc = api.call()
        #         print(("B",enc))
        #         if enc['responses']['INCENSE_ENCOUNTER']['result'] == 1:
        #             print(("C",pokemon))
        #             api.catch_pokemon(encounter_id=pokemon['encounter_id'], pokeball=balls.pop(0), normalized_reticle_size = normalized_reticle_size, spawn_point_id = pokemon['spawn_point_id'], hit_pokemon=True, spin_modifier=spin_modifier, normalized_hit_position=normalized_hit_position)
        #             ret = api.call()
        #             if "status" in ret['responses']['CATCH_POKEMON']:
        #                 if ret['responses']['CATCH_POKEMON']['status'] == 1:
        #                     print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        #                     print("INCENSE_CATCH_GOOD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng), normalized_reticle_size, spin_modifier))
        #                     print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        #                     stardust += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["stardust"])
        #                     candy += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["candy"])
        #                     xp += sum(ret['responses']["CATCH_POKEMON"]['capture_award']["xp"])
        #                     catches.append(pokemon)
        #                     break
        #                 elif ret['responses']['CATCH_POKEMON']['status'] == 0 or ret['responses']['CATCH_POKEMON']['status'] == 3:
        #                     break
        #             else:
        #                 print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        #                 print("INCENSE_CATCH_BAD=%f,%f,%f" % (math.hypot(pokemon['latitude'] - lat, pokemon['longitude'] - lng), normalized_reticle_size, spin_modifier))
        #                 print(pokemon)
        #                 print(ret)
        #                 print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        #                 break
        #     else:
        #         break

        newspins, newcatches, newstardust, newcandy, newxp = find_poi(api, newposition[0], newposition[1], sorted(balls))
        spins += newspins
        catches += newcatches
        stardust += newstardust
        candy += newcandy
        xp += newxp
        coords.append({'lat': newposition[0], 'lng': newposition[1]})

        m, s = divmod(time.time()-start_time, 60)
        h, m = divmod(m, 60)

        api.level_up_rewards(level=stats["level"])
        api.call()

        sys.stdout.write("=========================================\n")
        sys.stdout.write(" username: %s\n" % (username))
        sys.stdout.write(" level: %s\n" % (stats["level"]))
        sys.stdout.write(" levelup_xp_needed: %d\n" % (stats["next_level_xp"]-stats["experience"]))
        sys.stdout.write(" elapsed_time: %d:%02d:%02d\n" % (h, m, s))
        sys.stdout.write(" inventory: %d/%d\n" % (inventory, player["max_item_storage"]))
        sys.stdout.write(" pokemon: %d/%d\n" % (mons, player["max_pokemon_storage"]))
        sys.stdout.write(" total_stardust: %d\n" % (total_stardust))
        sys.stdout.write(" km_walked: %.1f\n" % (walked))
        sys.stdout.write(" target_km_walked: %.1f\n" % (target_km))
        sys.stdout.write(" spins: %d\n" % (len(spins)))
        sys.stdout.write(" recycled_items: %d\n" % (recycled_items))
        sys.stdout.write(" catches: %d\n" % len(catches))
        sys.stdout.write(" releases: %d\n" % releases)
        sys.stdout.write(" incubators_loaded: %d\n" % incubators_loaded)
        sys.stdout.write(" eggs_hatched: %d\n" % eggs_hatched)
        sys.stdout.write(" earned_stardust: %d\n" % (stardust))
        sys.stdout.write(" earned_candy: %d\n" % (candy))
        sys.stdout.write(" earned_xp: %d\n" % (xp))
        sys.stdout.write(" position: (%.5f,%.5f)\n" % (newposition[0], newposition[1]))
        sys.stdout.write("=========================================\n")
        sys.stdout.flush()

        map = Map()
        map._player = newposition
        for coord in coords:
            map.add_position((coord['lat'], coord['lng']))
        for spin in spins:
            map.add_point((spin['latitude'], spin['longitude']), "http://maps.google.com/mapfiles/ms/icons/blue-dot.png")
        for catch in catches:
            map.add_point((catch['latitude'], catch['longitude']), "http://maps.google.com/mapfiles/ms/icons/green-dot.png")
        with open("%s.html" % username, "w") as out:
            print(map, file=out)

        time.sleep(5)



if __name__ == '__main__':
    main()
