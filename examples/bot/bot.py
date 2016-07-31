from __future__ import print_function

import os
import sys
import time
import json
import math
import random

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../.."))
from pgoapi import pgoapi
import pgoapi.exceptions

from s2sphere import CellId, LatLng

from gmap import Map

class PoGoBot(object):

    def __init__(self, config):
        self.config = config
        self.softbanned = False
        self.unsoftban = 0
        self.api = pgoapi.PGoApi()
        self.api.set_position(*self.config["location"])
        self.angle = random.uniform(0,360)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/pokemon.json"), "r") as infile:
            self.pokemon_info = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/items.json"), "r") as infile:
            self.item_names = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/family_ids.json"), "r") as infile:
            self.family_ids = json.load(infile)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../data/evoreq.json"), "r") as infile:
            self.evoreq = json.load(infile)

        self.coords = [{'latitude': self.config["location"][0], 'longitude': self.config["location"][1]}]
        self.catches = []
        self.spins = []

        self.last_move_time = time.time()
        self.change_dir_time = self.last_move_time + random.uniform(60,300)

    def pokemon_id_to_name(self, id):
        return (list(filter(lambda j: int(j['Number']) == id, self.pokemon_info))[0]['Name'])

    def login(self, retries=-1):
        ret = False
        attempts = 0
        while True:
            sys.stdout.write("Performing authentication (attempt %d)..." % (attempts+1))
            if not self.api.login(self.config["auth_service"],
                                  self.config["username"],
                                  self.config["password"]):
                sys.stdout.write("failed.\n")
                attempts += 1
                if retries>=0 and attempts < retries:
                    time.sleep(1)
                else:
                    break
            else:
                sys.stdout.write("succeeded.\n")
                ret = True
                break
        return ret

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
                time.sleep(delay)
                if ret and "RECYCLE_INVENTORY_ITEM" in ret['responses'] and ret["responses"]['RECYCLE_INVENTORY_ITEM']["result"] == 1:
                    if first:
                        sys.stdout.write("  %s max inventory...\n" % status)
                        sys.stdout.write("    Recycled:\n")
                        first = False
                    sys.stdout.write("      %d x %s\n" % (count, self.item_names[il]))

    def process_inventory(self, inventory):
        ni = {
            "items": {},
            "candies": {},
            "pokemon": {},
            "eggs": [],
            "stats": {},
            #"applied": {},
            "incubators": {}
        }
        balls = []
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
                    ni["eggs"].append(item["pokemon_data"])
                else:
                    fam = str(item["pokemon_data"]["pokemon_id"])
                    if not fam in ni["pokemon"]:
                        ni["pokemon"][fam] = []
                    ni["pokemon"][fam].append(item)
            elif "egg_incubators" in item:
                for incubator in item["egg_incubators"]["egg_incubator"]:
                    ni["incubators"][str(incubator["id"])] = incubator
            elif "player_stats" in item:
                ni["stats"] = item["player_stats"]
        self.balls = sorted(balls)
        self.inventory = ni

    def get_trainer_info(self, delay):
        sys.stdout.write("Getting trainer information...\n")
        req = self.api.create_request()
        req.get_player()
        req.get_inventory()
        ret = req.call()
        if ret and ret["responses"]:
            self.process_player(ret["responses"]["GET_PLAYER"])
            self.process_inventory(ret["responses"]["GET_INVENTORY"])
        sys.stdout.write("  Trainer level: %d\n" % self.inventory["stats"]["level"])
        sys.stdout.write("  Experience: %d\n" % self.inventory["stats"]["experience"])
        sys.stdout.write("  Next level experience needed: %d\n" % (self.inventory["stats"]["next_level_xp"]-self.inventory["stats"]["experience"]))
        sys.stdout.write("  Kilometers walked: %.2f\n" % self.inventory["stats"]["km_walked"])
        sys.stdout.write("  Stardust: %d\n" % [cur["amount"] for cur in self.player["currencies"] if cur["name"] == "STARDUST"][0])
        sys.stdout.write("  Hatched eggs: %d\n" % self.inventory["stats"]["eggs_hatched"])
        sys.stdout.write("  Forts spun: %d\n" % self.inventory["stats"]["poke_stop_visits"])
        sys.stdout.write("  Unique pokedex entries: %d\n" % (self.inventory["stats"]["unique_pokedex_entries"]))
        sys.stdout.write("  Pokemon storage: %d/%d\n" % (sum([len(p) for p in self.inventory["pokemon"]]) + sum([len(p) for p in self.inventory["eggs"]]), self.player["max_pokemon_storage"]))
        sys.stdout.write("  Item storage: %d/%d\n" % (sum(self.inventory["items"].values()), self.player["max_item_storage"]))
        first = True
        for i in self.inventory["items"]:
            if first:
                sys.stdout.write("  Inventory:\n")
                first = False
            sys.stdout.write("      %d x %s\n" % (self.inventory["items"][i], self.item_names[str(i)]))
        first = True
        for ib in self.inventory["incubators"]:
            if 'pokemon_id' in self.inventory["incubators"][ib]:
                if first:
                    sys.stdout.write("  Loaded incubators:\n")
                    first = False
                ib = self.inventory["incubators"][ib]
                sys.stdout.write("    Remaining km: %f\n" % (ib["target_km_walked"]-self.inventory["stats"]["km_walked"]))

    def check_status_code(self, r, c):
        return (r and "status_code" in r and r["status_code"] == c)

    def get_hatched_eggs(self, delay):
        sys.stdout.write("Getting hatched eggs...\n")
        ret = self.api.get_hatched_eggs()
        if self.check_status_code(ret, 1):
            print(ret)
        time.sleep(delay)

    def get_rewards(self, delay):
        sys.stdout.write("Getting level-up rewards...\n")
        ret = self.api.level_up_rewards(level=self.inventory["stats"]["level"])
        if self.check_status_code(ret, 1) and ret["responses"]["LEVEL_UP_REWARDS"]["result"] == 1:
            print(ret)
        time.sleep(delay)

    def get_cell_ids(self, lat, lng, radius=10):
        origin = CellId.from_lat_lng(LatLng.from_degrees(lat, lng)).parent(15)
        walk = [origin.id()]
        right = origin.next()
        left = origin.prev()
        for _ in range(radius):
            walk.append(right.id())
            walk.append(left.id())
            right = right.next()
            left = left.prev()
        return sorted(walk)

    def get_pois(self, delay):
        sys.stdout.write("Getting POIs...\n")
        pois = {"pokemon": [], "forts": []}
        lat, lng, alt = self.api.get_position()
        cell_ids = self.get_cell_ids(lat, lng)
        timestamps = [0,] * len(cell_ids)
        ret = self.api.get_map_objects(latitude=lat, longitude=lng, since_timestamp_ms=timestamps, cell_id=cell_ids)
        if ret and ret["responses"] and "GET_MAP_OBJECTS" in ret["responses"] and ret["responses"]["GET_MAP_OBJECTS"]["status"] == 1:
            for map_cell in ret["responses"]["GET_MAP_OBJECTS"]["map_cells"]:
                if "wild_pokemons" in map_cell:
                    for pokemon in map_cell["wild_pokemons"]:
                        pois["pokemon"].append(pokemon)
                if 'forts' in map_cell:
                    for fort in map_cell['forts']:
                        pois['forts'].append(fort)
        self.pois = pois
        time.sleep(delay)


    def spin_forts(self, delay):
        sys.stdout.write("Spinning forts...\n")
        lat, lng, alt = self.api.get_position()
        for fort in self.pois["forts"]:
            if "type" in fort and fort["type"] == 1 and not "cooldown_complete_timestamp_ms" in fort:
                if math.hypot(fort['latitude'] - lat, fort['longitude'] - lng) < 0.0004495:
                    ret = self.api.fort_search(fort_id=fort['id'], fort_latitude=fort['latitude'], fort_longitude=fort['longitude'], player_latitude=lat, player_longitude=lng)
                    time.sleep(delay)
                    if ret and ret["responses"] and "FORT_SEARCH" in ret["responses"] and ret["responses"]["FORT_SEARCH"]["result"] == 1:
                        self.spins.append(fort)
                        sys.stdout.write("  Spun fort and got:\n")
                        sys.stdout.write("    Experience: %d\n" % ret["responses"]["FORT_SEARCH"]["experience_awarded"])
                        sys.stdout.write("    Items:\n")
                        ni = {}
                        for item in ret["responses"]["FORT_SEARCH"]["items_awarded"]:
                            if not item["item_id"] in ni:
                                ni[item["item_id"]] = 1
                            else:
                                ni[item["item_id"]] += 1
                        for item in ni:
                            sys.stdout.write("      %d x %s\n" % (ni[item], self.item_names[str(item)]))

    def catch_pokemon(self, eid, spid, kind, pokemon, balls, delay):
        ret = True
        sys.stdout.write("  Encountered a %s %s...\n" % (kind, self.pokemon_id_to_name(pokemon["pokemon_data"]["pokemon_id"])))
        while True:
            normalized_reticle_size = 1.950 - random.uniform(0, .15)
            normalized_hit_position = 1.0
            spin_modifier = 1.0 - random.uniform(0, .1)
            if len(balls) == 0:
                break
            ball = balls.pop(0)
            sys.stdout.write("    Throwing a %s..." % self.item_names[str(ball)])
            ret = self.api.catch_pokemon(encounter_id=eid, spawn_point_id=spid, pokeball=ball, normalized_reticle_size = normalized_reticle_size, hit_pokemon=True, spin_modifier=spin_modifier, normalized_hit_position=normalized_hit_position)
            time.sleep(delay)
            if self.check_status_code(ret, 3):
                sys.stdout.write("softbanned.\n")
                ret = False
                break
            elif self.check_status_code(ret, 1):
                if ret["responses"]["CATCH_POKEMON"]["status"] == 1:
                    sys.stdout.write("success.\n")
                    self.catches.append(pokemon)
                    sys.stdout.write("      Experience: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["xp"]))
                    sys.stdout.write("      Stardust: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["stardust"]))
                    sys.stdout.write("      Candies: %d\n" % sum(ret["responses"]["CATCH_POKEMON"]["capture_award"]["candy"]))
                    break
                elif ret["responses"]["CATCH_POKEMON"]["status"] == 0:
                    sys.stdout.write("error.\n")
                    break
                elif ret["responses"]["CATCH_POKEMON"]["status"] == 2:
                    sys.stdout.write("escape.\n")
                elif ret["responses"]["CATCH_POKEMON"]["status"] == 3:
                    sys.stdout.write("flee.\n")
                    break
                elif ret["responses"]["CATCH_POKEMON"]["status"] == 4:
                    sys.stdout.write("missed.\n")
        return ret

    def catch_wild_pokemon(self, delay):
        sys.stdout.write("Catching wild pokemon...\n")
        lat, lng, alt = self.api.get_position()
        ret = True
        for pokemon in self.pois["pokemon"]:
            ret = self.api.encounter(encounter_id=pokemon['encounter_id'], spawn_point_id=pokemon['spawn_point_id'], player_latitude = lat, player_longitude = lng)
            time.sleep(delay)
            if not self.catch_pokemon(pokemon['encounter_id'], pokemon['spawn_point_id'], "wild", pokemon, self.balls, delay):
                ret = False
                break
        return ret

    def catch_incense_pokemon(self, delay):
        sys.stdout.write("Catching incense pokemon...\n")
        lat, lng, alt = self.api.get_position()
        ret = self.api.get_incense_pokemon(player_latitude=lat, player_longitude=lng)
        time.sleep(delay)
        if ret and "GET_INCENSE_POKEMON" in ret["responses"] and ret["responses"]["GET_INCENSE_POKEMON"]["result"] == 1:
            pokemon = ret["responses"]["GET_INCENSE_POKEMON"]
            ret = api.incense_encounter(encounter_id=pokemon["encounter_id"], encounter_location=pokemon["encounter_location"])
            time.sleep(delay)
            if ret and "INCENSE_ENCOUNTER" in enc["responses"] and ret["responses"]["INCENSE_ENCOUNTER"]["result"] == 1:
                self.catch_pokemon(pokemon["encounter_id"], pokemon["encounter_location"], "incense", pokemon, self.balls, delay)

    def move(self, mph=5):
        sys.stdout.write("Moving...\n")
        now = time.time()
        delta = now - self.last_move_time
        if now > self.change_dir_time:
            self.angle = (self.angle + random.uniform(95,135)) % 360
            self.change_dir_time = now + 120 + random.uniform(30,90)
        lat, lng, alt = self.api.get_position()
        r = 1.0/69.0/60.0/60.0*mph*delta
        lat += math.cos(self.angle)*r
        lng += math.sin(self.angle)*r
        self.api.set_position(lat, lng, alt)
        self.coords.append({'latitude': lat, 'longitude': lng})
        self.last_move_time = now

    def save_map(self):
        sys.stdout.write("Saving map...\n")
        lat, lng, alt = self.api.get_position()
        map = Map()
        map._player = [lat, lng]
        for coord in self.coords:
            map.add_position((coord['latitude'], coord['longitude']))
        for catch in self.catches:
            map.add_point((catch['latitude'], catch['longitude']), "http://pokeapi.co/media/sprites/pokemon/%d.png" % catch["pokemon_data"]["pokemon_id"])
        for spin in self.spins:
            map.add_point((spin['latitude'], spin['longitude']), "http://maps.google.com/mapfiles/ms/icons/blue.png")

        with open("%s.html" % self.player["username"], "w") as out:
            print(map, file=out)

    def save_config(self):
        sys.stdout.write("Saving config...\n")
        lat, lng, alt = self.api.get_position()
        self.config["location"] = "%f,%f" % (lat, lng)
        with open("config.json", "w") as out:
            json.dump(self.config, out, indent=2, sort_keys=True)

    def load_incubators(self):
        sys.stdout.write("Loading incubators...\n")
        for ib in self.inventory["incubators"]:
            if not 'pokemon_id' in self.inventory["incubators"][ib]:
                ib = self.inventory["incubators"][ib]
                if len(self.inventory["eggs"]) > 0:
                    bestegg = (None,0)
                    for egg in self.inventory["eggs"]:
                        if egg["egg_km_walked_target"] > bestegg[1]:
                            bestegg = (egg, egg["egg_km_walked_target"])
                    ret = self.api.use_item_egg_incubator(item_id=ib['id'], pokemon_id=bestegg[0]['id'])
                    if ret and "USE_ITEM_EGG_INCUBATOR" in ret['responses'] and ret["responses"]['USE_ITEM_EGG_INCUBATOR']["result"] == 1:
                        print(ret)

    def calc_pq(self, pokemon):
        pq = 0
        for iv in ["individual_attack", "individual_defense", "individual_stamina"]:
            if iv in pokemon["pokemon_data"]:
                pq += pokemon["pokemon_data"][iv]
        return int(round(pq/45.0,2)*100)

    def process_candies(self):
        sys.stdout.write("Processing candies...\n")
        self.enabled_evolutions = {}
        self.pokemon_deficit = {}
        if len(self.inventory["candies"]) > 0:
            for family, count in self.inventory["candies"].iteritems():
                if family in self.evoreq:
                    evos, extra = divmod(count, self.evoreq[family])
                    if evos > 0:
                        self.enabled_evolutions[family] = evos
                        if not family in self.inventory["pokemon"]:
                            self.pokemon_deficit[family] = evos
                        else:
                            self.pokemon_deficit[family] = evos - len(self.inventory["pokemon"][family])
            if len(self.enabled_evolutions.keys()) > 0:
                sys.stdout.write("  Enabled evolutions:\n")
                for family, evos in self.enabled_evolutions.iteritems():
                    sys.stdout.write("    %d x %s\n" % (evos, self.pokemon_id_to_name(self.family_ids[str(family)])))
            if len(self.pokemon_deficit.keys()) > 0:
                sys.stdout.write("  Pokemon evolution deficit:\n")
                for family, deficit in self.pokemon_deficit.iteritems():
                    sys.stdout.write("    %d x %s\n" % (deficit, self.pokemon_id_to_name(self.family_ids[str(family)])))

    def transfer_pokemon(self, delay):
        if sum(self.inventory["pokemon"].values()) > self.config["minpokemon"]:
            sys.stdout.write("Transfering pokemon...\n")
            transferable_pokemon = []
            for pid in self.inventory["pokemon"]:
                count = 0
                for pokemon in self.inventory["pokemon"][pid]:
                    pq = self.calc_pq(pokemon)
                    if pq < self.config["powerquotient"]:
                        if pid in self.pokemon_deficit:
                            if self.pokemon_deficit[pid] < 0:
                                if count < abs(self.pokemon_deficit[pid]):
                                    transferable_pokemon.append((pokemon, pq))
                                    count += 1
                                else:
                                    break
                        else:
                            transferable_pokemon.append((pokemon, pq))
            for pokemon, pq in transferable_pokemon:
                ret = self.api.release_pokemon(pokemon_id=pokemon["pokemon_data"]["id"])
                time.sleep(delay)
                if ret and "RELEASE_POKEMON" in ret['responses'] and ret["responses"]["RELEASE_POKEMON"]["result"] == 1:
                    sys.stdout.write("    A %s with a power quotient of %d was released.\n" % (self.pokemon_id_to_name(self.family_ids[str(pokemon["pokemon_data"]["pokemon_id"])]), pq))

    def play(self):
        delay = 2
        while True:
            self.save_config()
            self.get_hatched_eggs(delay)
            self.get_trainer_info(delay)
            self.get_rewards(delay)
            time.sleep(5)
            self.get_pois(delay)
            if not self.config["nospin"]:
                self.spin_forts(delay)
            if not self.config["nocatch"]:
                if not self.softbanned:
                    self.softbanned = not self.catch_wild_pokemon(delay)
                    if not self.softbanned:
                        self.catch_incense_pokemon(delay)
                    else:
                        sys.stdout.write("Detected softban...\n")
                        self.unsoftban = time.time() + 600
                        sys.stdout.write("  Catching disabled for 10 minutes.\n")
                else:
                    if time.time() > self.unsoftban:
                        sys.stdout.write("Lifting softban...\n")
                        self.softbanned = False
                        self.unsoftban = 0
            self.load_incubators()
            self.prune_inventory(delay)
            self.process_candies()
            if self.config["minpokemon"] >= 0:
                self.transfer_pokemon(delay)
            self.save_map()
            self.move(self.config["speed"])

    def run(self):
        while True:
            try:
                self.login()
                self.play()
            except pgoapi.exceptions.NotLoggedInException:
                pass
