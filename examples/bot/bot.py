from __future__ import print_function

import os
import sys
import time
import json
import math as pymath
import random
import numpy as np

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../.."))
from pgoapi import pgoapi
import pgoapi.exceptions

from s2sphere import LatLng, Angle, Cap, RegionCoverer, math

from gmap import Map
from tsp import mk_matrix, nearest_neighbor, length, localsearch, multistart_localsearch

def get_angle((y1, x1), (y2, x2)):
    return pymath.degrees(pymath.atan2(y2-y1, x2-x1))

def get_distance((x1, y1), (x2, y2)):
    distance = pymath.sqrt(((x2-x1)**2)+((y2-y1)**2))
    return distance

def get_key_from_pokemon(pokemon):
    return '{}-{}'.format(pokemon['spawn_point_id'], pokemon['pokemon_data']['pokemon_id'])

def angle_between_points((lat1, lng1), (lat2, lng2)):
    xDiff = lng2 - lng1
    yDiff = lat2 - lat1
    return pymath.degrees(pymath.atan2(yDiff, xDiff))

def point_in_poly(x, y, poly):
    if (x,y) in poly: return True
    for i in range(len(poly)):
        p1 = None
        p2 = None
        if i==0:
            p1 = poly[0]
            p2 = poly[1]
        else:
            p1 = poly[i-1]
            p2 = poly[i]
        if p1[1] == p2[1] and p1[1] == y and x > min(p1[0], p2[0]) and x < max(p1[0], p2[0]):
            return True
    n = len(poly)
    inside = False
    p1x,p1y = poly[0]
    for i in range(n+1):
        p2x,p2y = poly[i % n]
        if y > min(p1y,p2y):
            if y <= max(p1y,p2y):
                if x <= max(p1x,p2x):
                    if p1y != p2y:
                        xints = (y-p1y)*(p2x-p1x)/(p2y-p1y)+p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x,p1y = p2x,p2y
    if inside: return True
    else: return False

class PoGoBot(object):

    def __init__(self, config):
        self.config = config
        self.softbanned = False
        self.unsoftban = 0
        self.api = pgoapi.PGoApi()
        self.api.set_position(*self.config["location"])
        self.api.set_authentication(provider=self.config["auth_service"],
                                    username=self.config["username"],
                                    password=self.config["password"])
        self.api.activate_signature(os.path.expanduser(self.config["encrypt"]))
        self.angle = random.uniform(0,360)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/pokemon.json"), "r") as infile:
            self.pokemon_info = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/items.json"), "r") as infile:
            self.item_names = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/family_ids.json"), "r") as infile:
            self.family_ids = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/evoreq.json"), "r") as infile:
            self.evoreq = json.load(infile)

        seen = set()
        seen_add = seen.add
        seen_twice = set(x for x in self.family_ids.values() if x in seen or seen_add(x))
        self.evolvables = map(str, seen_twice)

        self.coords = [{'latitude': self.config["location"][0], 'longitude': self.config["location"][1]}]
        self.catches = []
        self.spins = []
        self.pois = {"pokestops": {}, "gyms": {}, "pokemon": {}, "spawn_points": set()}
        self.target = None
        self.visited = {}
        self.inventory = self.empty_inventory()
        self.scan_stats = {}
        self.cell_timestamps = {}
        self.incense_encounters = {}
        self.lure_encounters = {}

        self.last_move_time = time.time()
        self.change_dir_time = self.last_move_time + random.uniform(60,300)

    def pokemon_id_to_name(self, id):
        return (list(filter(lambda j: int(j['Number']) == id, self.pokemon_info))[0]['Name'])

    def process_player(self, player):
        self.player = player["player_data"]

    def prune_inventory(self, delay):
        sys.stdout.write("Pruning inventory...\n")
        first = True
        if sum(self.inventory["items"].values()) < self.player["max_item_storage"]:
            status = "Below"
            limit = "inventory_limits"
        else:
            status = "At"
            limit = "inventory_minimum"
        for il in self.config[limit]:
            if il in self.inventory["items"] and self.inventory["items"][il] > self.config[limit][il]:
                count = self.inventory["items"][il] - self.config[limit][il]
                ret = self.api.recycle_inventory_item(item_id=int(il), count=count)
                if ret["responses"]['RECYCLE_INVENTORY_ITEM']["result"] == 1:
                    if first:
                        sys.stdout.write("  %s max inventory...\n" % status)
                        sys.stdout.write("    Recycled:\n")
                        first = False
                    sys.stdout.write("      %d x %s\n" % (count, self.item_names[il]))
                else:
                    print(ret)
                time.sleep(delay)

    def empty_inventory(self):
        return {
            "items": {},
            "candies": {},
            "pokemon": {},
            "eggs": {},
            "stats": {},
            "applied": [],
            "incubators": {}
        }

    def process_inventory(self, inventory):
        ni = self.empty_inventory()
        balls = []
        mon = 0
        for item in inventory["inventory_delta"]["inventory_items"]:
            item = item["inventory_item_data"]
            if "item" in item:
                if "count" in item["item"]:
                    if item["item"]["item_id"] in [1,2,3]:
                        balls = balls + [item["item"]["item_id"]] * item["item"]["count"]
                    ni["items"][str(item["item"]["item_id"])] = item["item"]["count"]
            elif "candy" in item:
                if "candy" in item["candy"]:
                    ni["candies"][str(item["candy"]["family_id"])] = item["candy"]["candy"]
            elif "pokemon_data" in item:
                if "is_egg" in item["pokemon_data"] and item["pokemon_data"]["is_egg"]:
                    ni["eggs"][item["pokemon_data"]["id"]] = item["pokemon_data"]
                else:
                    mon += 1
                    fam = str(item["pokemon_data"]["pokemon_id"])
                    if not fam in ni["pokemon"]:
                        ni["pokemon"][fam] = []
                    ni["pokemon"][fam].append(item)
            elif "egg_incubators" in item:
                for incubator in item["egg_incubators"]["egg_incubator"]:
                    ni["incubators"][incubator["id"]] = incubator
            elif "player_stats" in item:
                ni["stats"] = item["player_stats"]
            elif "applied_items" in item:
                for itm in item["applied_items"]["item"]:
                    if (itm["expire_ms"]/1000) > time.time():
                        ni["applied"].append(itm)
            else:
                pass
        self.balls = sorted(balls)
        if self.config["best_balls_first"]:
            self.balls = self.balls[::-1]
        self.inventory = ni

    def get_trainer_info(self, hatched, delay):
        req = self.api.create_request()
        req.get_player()
        req.get_inventory()
        ret = req.call()
        if ret and ret["responses"]:
            self.process_player(ret["responses"]["GET_PLAYER"])
            self.process_inventory(ret["responses"]["GET_INVENTORY"])
        if hatched:
            pokemon, stardust, candy, xp = hatched
            sys.stdout.write("  Hatched %d eggs:...\n" % len(pokemon))
            sys.stdout.write("    Pokemon:\n")
            for p in pokemon:
                found = False
                for _,fam in self.inventory["pokemon"].iteritems():
                    for pp in fam:
                        if pp["pokemon_data"]["id"] == p:
                            sys.stdout.write("      %s\n" % p)
                            found = True
                            break
                    if found:
                        break
            sys.stdout.write("    Experience: %d\n" % sum(xp))
            sys.stdout.write("    Stardust: %d\n" % sum(stardust))
            sys.stdout.write("    Candy: %d\n" % sum(candy))
        sys.stdout.write("Getting trainer information...\n")
        sys.stdout.write("  Trainer level: %d\n" % self.inventory["stats"]["level"])
        sys.stdout.write("  Experience: %d\n" % self.inventory["stats"]["experience"])
        sys.stdout.write("  Next level experience needed: %d\n" % (self.inventory["stats"]["next_level_xp"]-self.inventory["stats"]["experience"]))
        sys.stdout.write("  Kilometers walked: %.2f\n" % self.inventory["stats"]["km_walked"])
        sys.stdout.write("  Stardust: %d\n" % [cur["amount"] for cur in self.player["currencies"] if cur["name"] == "STARDUST"][0])
        sys.stdout.write("  Hatched eggs: %d\n" % self.inventory["stats"]["eggs_hatched"])
        sys.stdout.write("  Pokestops visited: %d\n" % self.inventory["stats"]["poke_stop_visits"])
        sys.stdout.write("  Unique pokedex entries: %d\n" % (self.inventory["stats"]["unique_pokedex_entries"]))
        sys.stdout.write("  Pokemon storage: %d/%d\n" % (sum([len(v) for k,v in self.inventory["pokemon"].iteritems()]) + len(self.inventory["eggs"]), self.player["max_pokemon_storage"]))
        sys.stdout.write("  Egg storage: %d/%d\n" % (len(self.inventory["eggs"]), 9))
        first = True
        for _,ib in self.inventory["incubators"].iteritems():
            if 'pokemon_id' in ib:
                if first:
                    sys.stdout.write("  Loaded incubators:\n")
                    first = False
                sys.stdout.write("    Remaining km: %.2f\n" % (ib["target_km_walked"]-self.inventory["stats"]["km_walked"]))
        sys.stdout.write("  Item storage: %d/%d\n" % (sum(self.inventory["items"].values()), self.player["max_item_storage"]))
        first = True
        for i in self.inventory["items"]:
            if first:
                sys.stdout.write("  Inventory:\n")
                first = False
            sys.stdout.write("    %d x %s\n" % (self.inventory["items"][i], self.item_names[str(i)]))
        first = True
        for i in self.inventory["applied"]:
            if first:
                sys.stdout.write("  Applied items:\n")
                first = False
            sys.stdout.write("    %s has %.2f minutes left\n" % (self.item_names[str(i["item_id"])], ((i["expire_ms"]/1000)-time.time())/60))

    def get_hatched_eggs(self, delay):
        pokemon = []
        stardust = 0
        candy = 0
        xp = 0
        sys.stdout.write("Getting hatched eggs...\n")
        ret = self.api.get_hatched_eggs()
        if 'pokemon_id' in ret["responses"]["GET_HATCHED_EGGS"]:
            hatched = (
                ret["responses"]["GET_HATCHED_EGGS"]["pokemon_id"],
                ret["responses"]["GET_HATCHED_EGGS"]["stardust_awarded"],
                ret["responses"]["GET_HATCHED_EGGS"]["candy_awarded"],
                ret["responses"]["GET_HATCHED_EGGS"]["experience_awarded"]
            )
        else:
            hatched = None
        time.sleep(delay)
        return hatched

    def get_rewards(self, delay):
        sys.stdout.write("Getting level-up rewards...\n")
        ret = self.api.level_up_rewards(level=self.inventory["stats"]["level"])
        if ret["responses"]["LEVEL_UP_REWARDS"]["result"] == 1:
            sys.stdout.write("  Items:\n")
            ni = {}
            for item in ret["responses"]["LEVEL_UP_REWARDS"]["items_awarded"]:
                if not item["item_id"] in ni:
                    ni[item["item_id"]] = 1
                else:
                    ni[item["item_id"]] += 1
            for item in ni:
                sys.stdout.write("    %d x %s\n" % (ni[item], self.item_names[str(item)]))
        time.sleep(delay)

    EARTH_RADIUS = 6371 * 1000
    def get_cell_ids(self, lat, long, radius=500, level=15):
        # Max values allowed by server according to this comment:
        # https://github.com/AeonLucid/POGOProtos/issues/83#issuecomment-235612285
        if radius > 1500:
            radius = 1500  # radius = 1500 is max allowed by the server
        region = Cap.from_axis_angle(LatLng.from_degrees(lat, long).to_point(), Angle.from_degrees(360*radius/(2*math.pi*self.EARTH_RADIUS)))
        coverer = RegionCoverer()
        coverer.min_level = level
        coverer.max_level = level
        sys.stdout.write("  Requesting level %d to %d S2 cells...\n" % (coverer.min_level, coverer.max_level))
        cells = coverer.get_covering(region)
        cells = cells[:100]  # len(cells) = 100 is max allowed by the server
        return sorted([x.id() for x in cells])

    def get_pois(self, delay):
        sys.stdout.write("Getting POIs...\n")
        lat, lng, alt = self.api.get_position()
        level = 17#random.randint(15,17)
        if not level in self.scan_stats:
            self.scan_stats[level] = {"wild_pokemons": 0}
        cell_ids = self.get_cell_ids(lat, lng, level=level, radius=self.config["radius"])
        for cid in cell_ids:
            if not cid in self.cell_timestamps:
                self.cell_timestamps[cid] = 0
        timestamps = [self.cell_timestamps[cid] for cid in cell_ids]
        # for i in xrange(len(timestamps)):
        #     sys.stdout.write("    Cell %s, last timestamp: %d\n" % (cell_ids[i], timestamps[i]))
        ret = self.api.get_map_objects(latitude=lat, longitude=lng, since_timestamp_ms=timestamps, cell_id=cell_ids)
        newpokemon = 0
        newpokestops = 0
        newgyms = 0
        newsp = 0
        if ret and ret["responses"] and "GET_MAP_OBJECTS" in ret["responses"] and ret["responses"]["GET_MAP_OBJECTS"]["status"] == 1:
            for map_cell in ret["responses"]["GET_MAP_OBJECTS"]["map_cells"]:
                self.cell_timestamps[map_cell["s2_cell_id"]] = map_cell["current_timestamp_ms"]
                if "wild_pokemons" in map_cell:
                    self.scan_stats[level]["wild_pokemons"] += 1
                    for pokemon in map_cell["wild_pokemons"]:
                        pid = get_key_from_pokemon(pokemon)
                        if not pid in self.pois["pokemon"]:
                            newpokemon += 1
                        pokemon['time_till_hidden_ms'] = time.time() + pokemon['time_till_hidden_ms']/1000
                        self.pois["pokemon"][pid] = pokemon
                if 'forts' in map_cell:
                    for fort in map_cell['forts']:
                        if "bounds" in self.config and not point_in_poly(fort["latitude"], fort["longitude"], self.config["bounds"]):
                            continue
                        if "type" in fort and fort["type"] == 1:
                            if not fort["id"] in self.pois['pokestops']:
                                newpokestops += 1
                            self.pois['pokestops'][fort["id"]] = fort
                        elif not "type" in fort:
                            if not fort["id"] in self.pois['gyms']:
                                newgyms += 1
                            self.pois['gyms'][fort["id"]] = fort
                if 'spawn_points' in map_cell:
                    for sp in map_cell['spawn_points']:
                        if "bounds" in self.config and not point_in_poly(sp["latitude"], sp["longitude"], self.config["bounds"]):
                            continue
                        self.pois["spawn_points"].add((sp["latitude"],sp["longitude"]))
                if 'nearby_pokemons' in map_cell:
                    pass#print("nearby_pokemons", map_cell['nearby_pokemons'])
                if 'catchable_pokemons' in map_cell:
                    pass#print('catchable_pokemons', map_cell['catchable_pokemons'])
        if newpokemon > 0:
            sys.stdout.write("    Found %d new pokemon.\n" % newpokemon)
        if newpokestops > 0:
            sys.stdout.write("    Found %d new pokestops.\n" % newpokestops)
        if newgyms > 0:
            sys.stdout.write("    Found %d new gyms.\n" % newgyms)
        # if len(self.scan_stats.keys()) > 0:
        #     sys.stdout.write("  Scan stats by level:\n")
        #     for level, stat in self.scan_stats.iteritems():
        #         sys.stdout.write('    %s {"wild_pokemons": %d}\n' % (level, stat["wild_pokemons"]))
        time.sleep(delay)

    def prune_expired_pokemon(self):
        sys.stdout.write("Pruning expired pokemon...\n")
        expired = []
        for k, pokemon in self.pois["pokemon"].iteritems():
            if pokemon['time_till_hidden_ms'] <= time.time():
                expired.append(k)
        if len(expired) > 0:
            for k in expired:
                del self.pois["pokemon"][k]
            sys.stdout.write("  %d pokemon expired.\n" % len(expired))

    def spin_pokestop(self, pokestop, lat, lng, alt, delay):
        status = 0
        ret = self.api.fort_search(fort_id=pokestop['id'], fort_latitude=pokestop['latitude'], fort_longitude=pokestop['longitude'], player_latitude=lat, player_longitude=lng)
        if "experience_awarded" in ret["responses"]["FORT_SEARCH"]:
            self.spins.append(pokestop)
            self.visited[pokestop["id"]] = time.time()
            if pokestop["id"] == self.target:
                self.target = None
            sys.stdout.write("  Spun pokestop and got:\n")
            xp = ret["responses"]["FORT_SEARCH"]["experience_awarded"]
            sys.stdout.write("    Experience: %d\n" % xp)
            if "items_awarded" in ret["responses"]["FORT_SEARCH"]:
                sys.stdout.write("    Items:\n")
                ni = {}
                for item in ret["responses"]["FORT_SEARCH"]["items_awarded"]:
                    if not item["item_id"] in ni:
                        ni[item["item_id"]] = 1
                    else:
                        ni[item["item_id"]] += 1
                for item in ni:
                    sys.stdout.write("      %d x %s\n" % (ni[item], self.item_names[str(item)]))
            status = 1
        else:
            if ret["responses"]["FORT_SEARCH"]["result"] == 3:
                print(pokestop)
            elif len(ret["responses"]["FORT_SEARCH"].keys()) == 1 and ret["responses"]["FORT_SEARCH"]["result"] == 1:
                status = -1
        return status

    def spin_pokestops(self, delay):
        sys.stdout.write("Spinning pokestops...\n")
        lat, lng, alt = self.api.get_position()
        path_resets = 0
        for pid, pokestop in self.pois["pokestops"].iteritems():
            if get_distance((pokestop['latitude'], pokestop['longitude']), (lat, lng)) < 0.0004435:
                if not pid in self.visited and not "cooldown_complete_timestamp_ms" in pokestop:
                    s = self.spin_pokestop(pokestop, lat, lng, alt, delay)
                    time.sleep(delay)
                    if s == -1:
                        sys.stdout.write("  Softban detected, attempting 40 spin fix.\n")
                        for i in xrange(40):
                            sys.stdout.write("    Spin %d...\n" % (i+1))
                            s = self.spin_pokestop(pokestop, lat, lng, alt, delay)
                            time.sleep(delay)
                            if s == 1:
                                break

    def clean_encounter(self, kind, upid):
        if kind == "incense" and upid in self.incense_encounters.keys():
            del self.incense_encounters[upid]
        elif kind == "lure" and upid in self.lure_encounters.keys():
            del self.lure_encounters[upid]
        elif kind == "wild" and upid in self.pois["pokemon"].keys():
            del self.pois["pokemon"][upid]

    def catch_pokemon(self, pokemon, kind, balls, delay, upid=None):
        ret = True
        minball = 1
        eid = pokemon["encounter_id"]
        spid = pokemon["spawn_point_id"]
        pid = pokemon["pokemon_data"]["pokemon_id"]
        if "capture_probability" in pokemon:
            pcap = pokemon["capture_probability"]["capture_probability"][0]
            sys.stdout.write("    Pokeball capture probability is %.2f...\n" % pcap)
            if pcap < .25 and "701" in self.inventory["items"]:
                sys.stdout.write("      Using a %s..." % self.item_names["701"])
                ret = self.api.use_item_capture(item_id=701, encounter_id=eid, spawn_point_id=spid)
                if "item_capture_mult" in ret["responses"]["USE_ITEM_CAPTURE"]:
                    sys.stdout.write("success.\n")
                    sys.stdout.write("        Capture multiplier %.2f...\n" % ret["responses"]["USE_ITEM_CAPTURE"]["item_capture_mult"])
                    pcap = pcap * ret["responses"]["USE_ITEM_CAPTURE"]["item_capture_mult"]
                    sys.stdout.write("        New capture probability is %.2f...\n" % pcap)
                else:
                    sys.stdout.write("failed.\n")
                    print(ret)
                time.sleep(delay)
            if pcap < .3:
                minball = 2
            elif pcap < .15:
                minball = 3
        while True:
            normalized_reticle_size = 1.950 - random.uniform(0, .15)
            normalized_hit_position = 1.0
            spin_modifier = 1.0 - random.uniform(0, .1)
            if len(balls) == 0:
                break
            if minball in balls:
                ball = balls.pop(balls.index(minball))
            else:
                ball = balls.pop()
            sys.stdout.write("    Throwing a %s..." % self.item_names[str(ball)])
            ret = self.api.catch_pokemon(encounter_id=eid, spawn_point_id=spid, pokeball=ball, normalized_reticle_size = normalized_reticle_size, hit_pokemon=True, spin_modifier=spin_modifier, normalized_hit_position=normalized_hit_position)
            if ret["responses"]["CATCH_POKEMON"]["status"] == 1:
                sys.stdout.write("success.\n")
                self.catches.append((kind,pokemon))
                if upid:
                    self.clean_encounter(kind, upid)
                sys.stdout.write("      Experience: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["xp"]))
                sys.stdout.write("      Stardust: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["stardust"]))
                sys.stdout.write("      Candies: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["candy"]))
                break
            elif ret["responses"]["CATCH_POKEMON"]["status"] == 0:
                sys.stdout.write("error.\n")
                break
            elif ret["responses"]["CATCH_POKEMON"]["status"] == 2:
                sys.stdout.write("escape.\n")
                if not self.config["best_balls_first"]:
                    minball += 1
                if minball > 3:
                    minball = 3
                time.sleep(delay)
            elif ret["responses"]["CATCH_POKEMON"]["status"] == 3:
                sys.stdout.write("flee.\n")
                if upid:
                    self.clean_encounter(kind, upid)
                break
            elif ret["responses"]["CATCH_POKEMON"]["status"] == 4:
                sys.stdout.write("missed.\n")
                time.sleep(delay)
        time.sleep(delay)

    def catch_wild_pokemon(self, delay):
        sys.stdout.write("Looking for wild pokemon encounters...\n")
        lat, lng, alt = self.api.get_position()
        for pid, pokemon in self.pois["pokemon"].iteritems():
            ret = self.api.encounter(encounter_id=pokemon['encounter_id'],
                                     spawn_point_id=pokemon['spawn_point_id'],
                                     player_latitude = lat,
                                     player_longitude = lng)
            time.sleep(delay)
            if ret["responses"]["ENCOUNTER"]["status"] == 1:
                pokemon = ret["responses"]["ENCOUNTER"]["wild_pokemon"]
                sys.stdout.write("  Encountered a wild %s...\n" % self.pokemon_id_to_name(pokemon["pokemon_data"]["pokemon_id"]))
                if not self.catch_pokemon(pokemon, "wild", self.balls, delay, pid):
                    break
            else:
                print(ret)


    def catch_lure_pokemon(self, delay):
        sys.stdout.write("Lookng for lure pokemon encounters...\n")
        for fid, fort in self.pois["pokestops"].iteritems():
            if "lure_info" in fort:
                lat, lng, alt = self.api.get_position()
                ret = self.api.disk_encounter(encounter_id=fort["lure_info"]["encounter_id"],
                                              fort_id=fort["lure_info"]["fort_id"],
                                              player_latitude=lat,
                                              player_longitude=lng)
                time.sleep(delay)
                pokemon = {
                    "spawn_point_id": fort["lure_info"]["fort_id"],
                    "pokemon_data": {"pokemon_id": fort["lure_info"]["active_pokemon_id"]},
                    "latitude": fort["latitude"],
                    "longitude": fort["longitude"]
                }
                pid = get_key_from_pokemon(pokemon)
                if ret["responses"]["DISK_ENCOUNTER"]["result"] == 1:
                    pokemon = ret["responses"]["DISK_ENCOUNTER"]
                    pokemon['encounter_id'] = fort["lure_info"]["encounter_id"]
                    pokemon["spawn_point_id"] = fort["lure_info"]["fort_id"]
                    pokemon["latitude"] = fort["latitude"]
                    pokemon["longitude"] = fort["longitude"]
                    sys.stdout.write("  Encountered a lured %s...\n" % self.pokemon_id_to_name(pokemon["pokemon_data"]["pokemon_id"]))
                    if not self.catch_pokemon(pokemon, "lure", self.balls, delay, pid):
                        break
                if ret["responses"]["DISK_ENCOUNTER"]["result"] == 2:
                    self.lure_encounters[pid] = pokemon
                else:
                    print(ret)

    def catch_incense_pokemon(self, delay):
        sys.stdout.write("Lookng for incense encounters...\n")
        lat, lng, alt = self.api.get_position()
        ret = self.api.get_incense_pokemon(player_latitude=lat,
                                           player_longitude=lng)
        time.sleep(delay)
        if ret["responses"]["GET_INCENSE_POKEMON"]["result"] == 1:
            pokemon = ret["responses"]["GET_INCENSE_POKEMON"]
            pokemon['spawn_point_id'] = pokemon["encounter_location"]
            pokemon['pokemon_data'] = {"pokemon_id": pokemon["pokemon_id"]}
            ret = self.api.incense_encounter(encounter_id=pokemon["encounter_id"],
                                             encounter_location=pokemon["spawn_point_id"])
            time.sleep(delay)
            pid = get_key_from_pokemon(pokemon)
            if ret["responses"]["INCENSE_ENCOUNTER"]["result"] == 1:
                sys.stdout.write("  Encountered an incense %s...\n" % self.pokemon_id_to_name(pokemon["pokemon_id"]))
                self.catch_pokemon(pokemon, "incense", self.balls, delay, pid)
            elif ret["responses"]["INCENSE_ENCOUNTER"]["result"] == 2:
                self.incense_encounters[pid] = pokemon
            else:
                print(ret)

    def update_path(self):
        sys.stdout.write("Updating path...\n")
        lat, lng, alt = self.api.get_position()
        if self.target == None:
            sys.stdout.write("  Picking new target...\n")
            coord = [(lat, lng)]
            fids = []
            for fid, pokestop in self.pois["pokestops"].iteritems():
                if not pokestop["id"] in self.visited and not "cooldown_complete_timestamp_ms" in pokestop:
                    fids.append(fid)
                    coord.append((pokestop["latitude"], pokestop["longitude"]))
            l = len(fids)
            if l > 0:
                n, D = mk_matrix(coord, get_distance)
                tour = nearest_neighbor(n, 0, D)
                tour.remove(0)
                tour[:] = [t-1 for t in tour]
                lures = []
                for i in xrange(min(len(tour),5)):
                    if 'active_fort_modifier' in self.pois["pokestops"][fids[tour[i]]]:
                        lures.append(i)
                if len(lures) > 0 and min(lures) > 0:
                    sys.stdout.write("    Prioritizing pokestop with lure...\n")
                    i = min(lures)
                else:
                    i = np.random.poisson(self.config["noise"],1)[0]
                self.target = fids[tour[i]]
        remove = []
        for k,v in self.visited.iteritems():
            if v + self.config["revisit"] <= time.time():
                remove.append(k)
        for k in remove:
            del self.visited[k]

    def move(self, mph=5):
        sys.stdout.write("Moving...\n")
        now = time.time()
        delta = now - self.last_move_time
        lat, lng, alt = self.api.get_position()
        r = 1.0/69.0/60.0/60.0*mph*delta
        if len(self.incense_encounters.keys()) > 0:
            sys.stdout.write("  Heading towards nearby incense pokemon...\n")
            nearest = (None, float("inf"))
            for pid, pokemon in self.incense_encounters.iteritems():
                d = get_distance((pokemon['latitude'], pokemon['longitude']), (lat, lng))
                if d < nearest[1]:
                    nearest = (pokemon, d)
            if nearest[1] < r:
                lat = nearest[0]["latitude"]
                lng = nearest[0]["longitude"]
            else:
                self.angle = get_angle((lat, lng), (nearest[0]["latitude"], nearest[0]["longitude"]))
                lat = lat + pymath.sin(pymath.radians(self.angle)) * r
                lng = lng + pymath.cos(pymath.radians(self.angle)) * r
        elif len(self.lure_encounters.keys()) > 0:
            sys.stdout.write("  Heading towards nearby lure pokemon...\n")
            nearest = (None, float("inf"))
            for pid, pokemon in self.lure_encounters.iteritems():
                d = get_distance((pokemon['latitude'], pokemon['longitude']), (lat, lng))
                if d < nearest[1]:
                    nearest = (pokemon, d)
            if nearest[1] < r:
                lat = nearest[0]["latitude"]
                lng = nearest[0]["longitude"]
            else:
                self.angle = get_angle((lat, lng), (nearest[0]["latitude"], nearest[0]["longitude"]))
                lat = lat + pymath.sin(pymath.radians(self.angle)) * r
                lng = lng + pymath.cos(pymath.radians(self.angle)) * r
        elif len(self.pois["pokemon"]) > 0:
            sys.stdout.write("  Heading towards nearby wild pokemon...\n")
            nearest = (None, float("inf"))
            for pid, pokemon in self.pois["pokemon"].iteritems():
                d = get_distance((pokemon['latitude'], pokemon['longitude']), (lat, lng))
                if d < nearest[1]:
                    nearest = (pokemon, d)
            if nearest[1] < r:
                lat = nearest[0]["latitude"]
                lng = nearest[0]["longitude"]
            else:
                self.angle = get_angle((lat, lng), (nearest[0]["latitude"], nearest[0]["longitude"]))
                lat = lat + pymath.sin(pymath.radians(self.angle)) * r
                lng = lng + pymath.cos(pymath.radians(self.angle)) * r
        else:
            sys.stdout.write("  Heading to a pokestop...\n")
            target = None
            if self.target:
                target = self.pois["pokestops"][self.target]
                self.angle = get_angle((lat, lng), (target["latitude"], target["longitude"]))
            else:
                self.angle = random.uniform(0,360)
            if target and get_distance((lng, lat), (target["longitude"], target["latitude"])) < r:
                lat = target["latitude"]
                lng = target["longitude"]
                sys.stdout.write("    Visited a pokestop...\n")
                self.visited[self.target] = time.time()
                self.target = None
            else:
                lat = lat + pymath.sin(pymath.radians(self.angle)) * r
                lng = lng + pymath.cos(pymath.radians(self.angle)) * r
        self.api.set_position(lat, lng, alt)
        self.coords.append({'latitude': lat, 'longitude': lng})
        self.last_move_time = now

    def save_map(self):
        sys.stdout.write("Saving map...\n")
        lat, lng, alt = self.api.get_position()
        map = Map()
        map._player = [lat, lng]
        if "bounds" in self.config:
            for bound in self.config["bounds"]:
                map.add_bound(bound)
        for coord in self.coords:
            map.add_position((coord['latitude'], coord['longitude']))
        for _,catch in self.catches:
            pid = catch["pokemon_data"]["pokemon_id"]
            lat = catch["latitude"]
            lng = catch["longitude"]
            map.add_point((lat, lng), "http://pokeapi.co/media/sprites/pokemon/%d.png" % pid)
        for spin in self.spins:
            map.add_point((spin['latitude'], spin['longitude']), "http://maps.google.com/mapfiles/ms/icons/blue.png")
        for sp in self.pois["spawn_points"]:
            map.add_point(sp, "http://www.andrew.cmu.edu/user/rhope/darkgray-dot-4x4.png")
        for _, pokestop in self.pois["pokestops"].iteritems():
            if pokestop["id"] in self.visited:
                map.add_point((pokestop['latitude'], pokestop['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/gray-circle.png")
            else:
                if 'active_fort_modifier' in pokestop:
                    map.add_point((pokestop['latitude'], pokestop['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/red-circle.png")
                else:
                    map.add_point((pokestop['latitude'], pokestop['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/green-circle.png")
        for _, gym in self.pois["gyms"].iteritems():
            map.add_point((gym['latitude'], gym['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/blue-circle.png")
        # for _, pokemon in self.pois["pokemon"].iteritems():
        #     map.add_point((pokemon['latitude'], pokemon['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/red-circle.png")
        # for _, sp in self.spawnpoints.iteritems():
        #     map.add_point((sp['latitude'], sp['longitude']), "http://www.srh.noaa.gov/images/tsa/timeline/gray-circle.png")
        if self.target:
            target = self.pois["pokestops"][self.target]
            map.add_point((target['latitude'], target['longitude']), "http://maps.google.com/mapfiles/ms/icons/green.png")

        with open("maptrace.html", "w") as out:
            print(map, file=out)

    def save_config(self):
        sys.stdout.write("Saving config...\n")
        self.config["location"] = self.api.get_position()
        with open("config.json", "w") as out:
            json.dump(self.config, out, indent=2, sort_keys=True)

    def load_incubators(self):
        sys.stdout.write("Loading incubators...\n")
        for _,ib in self.inventory["incubators"].iteritems():
            if not 'pokemon_id' in ib:
                if len(self.inventory["eggs"]) > 0:
                    bestegg = (None, 0)
                    for eid, egg in self.inventory["eggs"].iteritems():
                        if egg["egg_km_walked_target"] > bestegg[1]:
                            good = True
                            for _,ib2 in self.inventory["incubators"].iteritems():
                                if "pokemon_id" in ib2 and eid == ib2["pokemon_id"]:
                                    good = False
                                    break
                            if good:
                                bestegg = (egg, egg["egg_km_walked_target"])
                    ret = self.api.use_item_egg_incubator(item_id=ib['id'], pokemon_id=bestegg[0]['id'])
                    if ret["responses"]['USE_ITEM_EGG_INCUBATOR']["result"] == 1:
                        sys.stdout.write("  A %fkm egg was loaded.\n" % bestegg[1])
                        del self.inventory["eggs"][eid]
                    else:
                        print(ret)


    def calc_pq(self, pokemon):
        pq = 0
        for iv in ["individual_attack", "individual_defense", "individual_stamina"]:
            if iv in pokemon["pokemon_data"]:
                pq += pokemon["pokemon_data"][iv]
        return int(round(pq/45.0,2)*100)

    def circle_poly(x,y,r):
        for i in range(100):
            ang = i/100 * pymath.pi * 2
            yield (x + r * pymath.cos(ang), y + r * pymath.sin(ang))

    def process_candies(self):
        sys.stdout.write("Processing candies...\n")
        self.enabled_evolutions = {}
        if len(self.inventory["candies"]) > 0:
            for family, count in self.inventory["candies"].iteritems():
                if family in self.evoreq:
                    evos, extra = divmod(count, self.evoreq[family])
                    if evos > 0:
                        self.enabled_evolutions[family] = evos
            if len(self.enabled_evolutions.keys()) > 0:
                sys.stdout.write("  Candy cost met for evolutions:\n")
                for family, evos in self.enabled_evolutions.iteritems():
                    extra = ""
                    isize = 0
                    if family in self.inventory["pokemon"]:
                        isize = len(self.inventory["pokemon"][family])
                        if isize < evos:
                            extra = " (%d more pokemon needed)" % (evos-isize)
                    else:
                        extra = " (%d more pokemon needed)" % evos
                    sys.stdout.write("    %d x %s%s\n" % (evos, self.pokemon_id_to_name(self.family_ids[str(family)]), extra))

    def transfer_pokemon(self, delay):
        t = 0
        if (sum([len(v) for k,v in self.inventory["pokemon"].iteritems()]) + len(self.inventory["eggs"])) > self.config["minpokemon"]:
            sys.stdout.write("Transfering pokemon...\n")
            transferable_pokemon = []
            for pid in self.inventory["pokemon"]:
                if "whitelist" in self.config and pid in self.config["whitelist"]:
                    continue
                if pid in self.evolvables:
                    if pid not in self.enabled_evolutions:
                        for pokemon in self.inventory["pokemon"][pid]:
                            pq = self.calc_pq(pokemon)
                            if pq < self.config["powerquotient"]:
                                transferable_pokemon.append((pokemon, pq))
                    else:
                        isize = len(self.inventory["pokemon"][pid])
                        if isize > self.enabled_evolutions[pid]:
                            count = isize - self.enabled_evolutions[pid]
                            for pokemon in self.inventory["pokemon"][pid]:
                                pq = self.calc_pq(pokemon)
                                if pq < self.config["powerquotient"]:
                                    transferable_pokemon.append((pokemon, pq))
                                    count -= 1
                                if count == 0:
                                    break
                else:
                    for pokemon in self.inventory["pokemon"][pid]:
                        pq = self.calc_pq(pokemon)
                        if pq < self.config["powerquotient"]:
                            transferable_pokemon.append((pokemon, pq))
            for pokemon, pq in transferable_pokemon:
                ret = self.api.release_pokemon(pokemon_id=pokemon["pokemon_data"]["id"])
                if ret and "RELEASE_POKEMON" in ret['responses'] and ret["responses"]["RELEASE_POKEMON"]["result"] == 1:
                    sys.stdout.write("  A %s with a power quotient of %d was released.\n" % (self.pokemon_id_to_name(pokemon["pokemon_data"]["pokemon_id"]), pq))
                    t += 1
                time.sleep(delay)
        return t

    def evolve_pokemon(self, delay):
        e = 0
        evolveable_pokemon = []
        lowcost = []
        if len(self.inventory["eggs"]) + sum([len(self.inventory["pokemon"][p]) for p in self.inventory["pokemon"]]) == self.player["max_pokemon_storage"]:
            sys.stdout.write("Evolving pokemon...\n")
            for pid, evos in self.enabled_evolutions.iteritems():
                if pid in self.inventory["pokemon"] and self.evoreq[pid] < 50:
                    while evos > 0 and len(self.inventory["pokemon"][pid]) > 0:
                        lowcost.append(self.inventory["pokemon"][pid].pop())
                        evos -= 1
            sys.stdout.write("  Found %d low cost pokemon evolutions...\n" % len(lowcost))
            evolveable_pokemon = [] + lowcost
            sys.stdout.write("  There are %d total evolveable pokemon...\n" % len(evolveable_pokemon))
            if len(evolveable_pokemon) > 100 and "301" in self.inventory["items"]:
                sys.stdout.write("  Using a lucky egg...")
                ret = self.api.use_item_xp_boost(item_id=301)
                if ret["responses"]["USE_ITEM_XP_BOOST"]["result"] == 1:
                    sys.stdout.write("success.\n")
                else:
                    sys.stdout.write("failed.\n")
                time.sleep(delay)
            for pokemon in evolveable_pokemon:
                ret = self.api.evolve_pokemon(pokemon_id=pokemon["pokemon_data"]["id"])
                if ret["responses"]["EVOLVE_POKEMON"]["result"] == 1:
                    sys.stdout.write("    A %s was evolved.\n" % (self.pokemon_id_to_name(self.family_ids[str(pokemon["pokemon_data"]["pokemon_id"])])))
                    sys.stdout.write("      Experience: %d\n" % ret["responses"]["EVOLVE_POKEMON"]["experience_awarded"])
                    e += 1
                time.sleep(delay)
        return e

    def kill_time(self, delay):
        sys.stdout.write("Killing time...\n")
        time.sleep(delay)

    def play(self):
        delay = 1
        last_map = 0
        self.api.get_player()
        time.sleep(delay)
        throttlesleep = 10
        lastthrottle = None
        self.save_map()
        while True:
            try:
                self.save_config()
                hatched = self.get_hatched_eggs(delay)
                self.get_trainer_info(hatched, delay)
                self.get_rewards(delay)
                self.process_candies()
                if self.evolve_pokemon(delay):
                    self.last_move_time = time.time()
                    continue
                if self.config["minpokemon"] >= 0:
                    if self.transfer_pokemon(delay):
                        self.last_move_time = time.time()
                        continue
                self.kill_time(delay)
                if last_map + 5 < time.time():
                    self.get_pois(delay)
                    last_map = time.time()
                self.prune_expired_pokemon()
                self.kill_time(delay)
                if not self.config["nospin"]:
                    self.spin_pokestops(1)
                if not self.config["nocatch"]:
                    self.catch_wild_pokemon(delay)
                    self.catch_incense_pokemon(delay)
                    self.catch_lure_pokemon(delay)
                self.load_incubators()
                self.prune_inventory(delay)
                self.update_path()
                self.save_map()
                self.move(self.config["speed"])
            except pgoapi.exceptions.ServerSideRequestThrottlingException as e:
                if lastthrottle != None and time.time()-lastthrottle < throttlesleep:
                    throttlesleep += 1
                sys.stdout.write("Throttling exeption, taking a %d second timeout!\n" % throttlesleep)
                time.sleep(throttlesleep)
                lastthrottle = time.time()


    def run(self):
        self.play()
