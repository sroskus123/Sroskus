#!/usr/bin/env python3
"""Nezavisla referencni kontrola hodnot zavislych na semeni ve sdilenych testovacich vektorech.

Tento skript nepouziva JS ani C++ jadro. Znovu implementuje (podle Docs/RULES.md) jen to, co je potreba:
  * generator mulberry32, pickIndex a michani Fisher-Yates (RULES.md, oddil 8),
  * vyber aktivni oblasti kola = pickIndex(pocet oblasti) z generatoru se semenem kola, kazde kolo dalsi cislo
    (oddil 4),
  * zivotni cyklus respawnu: odpocet, pokusy o spawn v presnych okamzicich uvnitr tiku, michani kandidatu,
    body pouzite ve stejnem update, predikat (blokovane body + vzdalenost od tel), poskozeni a friendly fire (oddil 5).

Pak prehraje soubory vektoru a porovna s nimi:
  * rng.json: vsechny vystupy generatoru a konecny stav,
  * round/match (rucni i fuzz): zoneIndex a zoneId vsude, kde je vektor ocekava,
  * respawn (rucni i fuzz): vysledky a udalosti operaci respawnu (vcetne indexu bodu spawnu) a pole zivotniho
    cyklu ucastniku ve stavu (state, health, respawnInUs, retryInUs, spawnPoint, spawnCount, deaths,
    failedSpawnAttempts, loadout, equipped, order).
Stav zbrani a otisky celeho stavu (snapshotDigest) nekontroluje - ty overuje JS/C++ spoustec.

Pouziti:  python3 Shared/testvectors/tools/seed_reference.py [--shared <adresar Shared>] [-v]
Navratovy kod 0 = vse sedi, 1 = neshoda, 2 = chyba vstupu.
"""

import argparse
import json
import math
import os
import sys

MASK32 = 0xFFFFFFFF
SPAWN_SEED_SALT = 0x9E3779B9


class Mulberry32:
    """mulberry32 s 32bitovym stavem; pick(n) = floor(u32 * n / 2^32); shuffle = Fisher-Yates od konce."""

    def __init__(self, seed):
        self.state = seed & MASK32

    def next_u32(self):
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32)) & MASK32
        return (t ^ (t >> 14)) & MASK32

    def pick(self, n):
        return (self.next_u32() * n) >> 32

    def shuffle(self, n):
        a = list(range(n))
        for i in range(n - 1, 0, -1):
            j = self.pick(i + 1)
            a[i], a[j] = a[j], a[i]
        return a


def merge_patch(target, patch):
    """JSON Merge Patch (RFC 7386)."""
    if not isinstance(patch, dict):
        return patch
    out = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge_patch(out.get(k), v)
    return out


def seconds_to_micros(s):
    return math.floor(s * 1000000 + 0.5)  # jako JS Math.round


def is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()  # JSON 30.0 je v JS cele cislo


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def expand_ticks(duration, mode, irregular_rngs):
    out = []
    prev = 0
    if "hz" in mode:
        hz = mode["hz"]
        k = 1
        while prev < duration:
            t = min((2 * k * 1000000 + hz) // (2 * hz), duration)
            out.append(t - prev)
            prev = t
            k += 1
    elif "dtUs" in mode:
        while prev < duration:
            t = min(prev + mode["dtUs"], duration)
            out.append(t - prev)
            prev = t
    elif "irregular" in mode:
        key = canonical(mode)
        if key not in irregular_rngs:
            irregular_rngs[key] = Mulberry32(mode["irregular"]["seed"])
        rng = irregular_rngs[key]
        lo, hi = mode["irregular"]["minUs"], mode["irregular"]["maxUs"]
        while prev < duration:
            t = min(prev + lo + rng.pick(hi - lo + 1), duration)
            out.append(t - prev)
            prev = t
    else:
        raise ValueError("neznamy rezim tiku %r" % (mode,))
    return out


class Rules:
    def __init__(self, raw):
        self.team_count = raw["teams"]["count"]
        self.team_size = raw["teams"]["size"]
        self.locations = [z["id"] for z in raw["zone"]["locations"]]
        r = raw["respawn"]
        self.delay = seconds_to_micros(r["delay"])
        self.retry = seconds_to_micros(r["retryInterval"])
        self.min_enemy = float(r["minEnemyDistance"])
        self.clearance = float(r["bodyClearance"])
        self.max_health = raw["combat"]["maxHealth"]
        self.friendly_fire = raw["combat"]["friendlyFire"]
        self.default_loadout = list(raw["loadout"]["default"])
        self.weapons = set(raw["weapons"].keys())


class RespawnModel:
    """Referencni model respawnu (Docs/RULES.md, oddil 5 a R13/R15)."""

    def __init__(self, rules, seed, areas):
        self.rules = rules
        self.rng = Mulberry32(seed)
        self.areas = areas
        self.order = []
        self.by_id = {}
        self.events = []

    def valid_loadout(self, lo):
        if not isinstance(lo, list) or not lo:
            return False
        seen = set()
        for w in lo:
            if not isinstance(w, str) or w not in self.rules.weapons or w in seen:
                return False
            seen.add(w)
        return True

    def reset_participant(self, p):
        p.update(state="respawning", health=0, respawnInUs=0, retryInUs=0, spawnPoint=-1, spawnCount=0,
                 deaths=0, failedSpawnAttempts=0, equipped=list(p["loadout"]))

    def add(self, pid, team, loadout):
        if not isinstance(pid, str) or not pid:
            return "invalid_id"
        if pid in self.by_id:
            return "duplicate_id"
        if not is_int(team) or team < 0 or team >= self.rules.team_count:
            return "invalid_team"
        lo = self.rules.default_loadout if loadout is None else loadout
        if not self.valid_loadout(lo):
            return "invalid_loadout"
        if sum(1 for p in self.order if p["team"] == team) >= self.rules.team_size:
            return "team_full"
        p = {"id": pid, "team": int(team), "loadout": list(lo)}
        self.reset_participant(p)
        self.order.append(p)
        self.by_id[pid] = p
        return "ok"

    def set_loadout(self, pid, lo):
        p = self.by_id.get(pid)
        if p is None:
            return "unknown_id"
        if not self.valid_loadout(lo):
            return "invalid_loadout"
        p["loadout"] = list(lo)
        return "ok"

    def kill(self, pid):
        p = self.by_id.get(pid)
        if p is None:
            return "unknown_id"
        if p["state"] != "alive":
            return "not_alive"
        p.update(state="dead", health=0, respawnInUs=self.rules.delay, retryInUs=0)
        p["deaths"] += 1
        self.events.append({"type": "killed", "id": pid, "point": -1})
        return "killed"

    def damage(self, victim_id, amount, attacker_id):
        v = self.by_id.get(victim_id) if isinstance(victim_id, str) else None
        if v is None:
            return {"result": "unknown_id", "applied": 0}
        attacker = None
        if attacker_id is not None:
            attacker = self.by_id.get(attacker_id) if isinstance(attacker_id, str) else None
            if attacker is None:
                return {"result": "unknown_id", "applied": 0}
        if not is_int(amount) or amount <= 0 or abs(amount) > 2 ** 53 - 1:
            return {"result": "invalid_amount", "applied": 0}
        amount = int(amount)
        if v["state"] != "alive":
            return {"result": "not_alive", "applied": 0}
        if attacker is not None and attacker is not v and attacker["team"] == v["team"] and not self.rules.friendly_fire:
            return {"result": "blocked_friendly_fire", "applied": 0}
        applied = min(amount, v["health"])
        v["health"] -= applied
        if v["health"] == 0:
            self.kill(victim_id)
            return {"result": "killed", "applied": applied}
        return {"result": "applied", "applied": applied}

    def safe(self, team, idx, world):
        if idx in world.get("blocked", {}).get(str(team), []):
            return False
        pt = self.areas[team][idx]
        enemy2 = self.rules.min_enemy * self.rules.min_enemy
        body2 = self.rules.clearance * self.rules.clearance
        for b in world.get("bodies", []):
            if b.get("alive") is not True:
                continue
            dx = b["pos"][0] - pt[0]
            dy = b["pos"][1] - pt[1]
            dz = b["pos"][2] - pt[2]
            d2 = dx * dx + dy * dy + dz * dz
            if b.get("team") != team and d2 < enemy2:
                return False
            if d2 < body2:
                return False
        return True

    def attempt(self, p, world, claims):
        team = p["team"]
        for idx in self.rng.shuffle(len(self.areas[team])):
            if idx in claims[team] or not self.safe(team, idx, world):
                continue
            claims[team].add(idx)
            p.update(state="alive", health=self.rules.max_health, respawnInUs=0, retryInUs=0, spawnPoint=idx,
                     equipped=list(p["loadout"]))
            p["spawnCount"] += 1
            self.events.append({"type": "spawned", "id": p["id"], "point": idx})
            return
        p["failedSpawnAttempts"] += 1
        p["retryInUs"] = self.rules.retry
        self.events.append({"type": "spawn_blocked", "id": p["id"], "point": -1})

    def pass_time(self, d, world, claims):
        for p in self.order:
            due = False
            if p["state"] == "dead":
                p["respawnInUs"] = max(0, p["respawnInUs"] - d)
                if p["respawnInUs"] == 0:
                    p["state"] = "respawning"
                    p["retryInUs"] = 0
                    due = True
            elif p["state"] == "respawning":
                p["retryInUs"] = max(0, p["retryInUs"] - d)
                due = p["retryInUs"] == 0
            if due:
                self.attempt(p, world, claims)

    def next_due(self):
        best = None
        for p in self.order:
            c = p["respawnInUs"] if p["state"] == "dead" else p["retryInUs"] if p["state"] == "respawning" else None
            if c is not None and (best is None or c < best):
                best = c
        return best

    def update(self, dt, world):
        # Pokusy v presnych okamzicich uvnitr tiku; body pouzite v tomto update se znovu nenabidnou.
        claims = [set() for _ in self.areas]
        self.pass_time(0, world, claims)
        remaining = dt
        while remaining > 0:
            nxt = self.next_due()
            step = remaining if nxt is None else min(remaining, nxt)
            self.pass_time(step, world, claims)
            remaining -= step

    def reset_round(self):
        for p in self.order:
            self.reset_participant(p)
        self.events = []
        return "ok"

    def snapshot(self):
        keys = ("team", "state", "health", "respawnInUs", "retryInUs", "spawnPoint", "spawnCount", "deaths",
                "failedSpawnAttempts", "loadout", "equipped")
        return {"order": [p["id"] for p in self.order],
                "participants": {p["id"]: {k: p[k] for k in keys} for p in self.order}}


class Checker:
    def __init__(self, verbose):
        self.verbose = verbose
        self.failures = []
        self.checks = 0

    def eq(self, where, expected, actual):
        self.checks += 1
        if expected != actual:
            self.failures.append("%s: ocekavano %s, reference %s" % (where, json.dumps(expected), json.dumps(actual)))

    def compare_subset(self, where, expected, actual, allowed):
        """expected je podmnozina stavu; porovnavaji se jen klice, ktere reference zna (allowed)."""
        for k, v in expected.items():
            if k not in allowed:
                continue
            if isinstance(allowed, dict) and isinstance(allowed[k], (dict, set)) and isinstance(v, dict):
                sub = actual.get(k, {}) if isinstance(actual, dict) else {}
                self.compare_subset(where + "." + k, v, sub, allowed[k])
            else:
                self.eq(where + "." + k, v, actual.get(k) if isinstance(actual, dict) else None)


LIFE_KEYS = {"team", "state", "health", "respawnInUs", "retryInUs", "spawnPoint", "spawnCount", "deaths",
             "failedSpawnAttempts", "loadout", "equipped"}
RESERVED = ("result", "events", "eventCounts", "snapshot", "snapshotDigest")
RESPAWN_OPS = ("add", "kill", "damage", "setLoadout", "tick", "run", "resetRound")


def life_allowed(participant_ids):
    return {"order": True, "participants": {pid: LIFE_KEYS for pid in participant_ids}}


def check_rng(case, ck):
    rng = Mulberry32(case.get("setup", {}).get("seed", 0))
    for i, s in enumerate(case["steps"]):
        op = s["op"]
        if op == "next":
            res = [rng.next_u32() for _ in range(s["count"])]
        elif op == "pick":
            res = [rng.pick(s["n"]) for _ in range(s["count"])]
        elif op == "shuffle":
            res = rng.shuffle(s["n"])
        else:
            raise ValueError("rng: neznama operace " + op)
        e = s.get("expect", {})
        where = "%s krok %d" % (case["id"], i)
        if "result" in e:
            ck.eq(where + " result", e["result"], res)
        if "state" in e:
            ck.eq(where + " state", e["state"], rng.state)


def check_zone_selection(case, rules, ck):
    kind = case["kind"]
    seed = case.get("setup", {}).get("seed", 1)
    rng = Mulberry32(seed)
    zone_index = rng.pick(len(rules.locations))
    for i, s in enumerate(case["steps"]):
        if s["op"] == "reset":
            zone_index = rng.pick(len(rules.locations))
        e = s.get("expect", {})
        where = "%s krok %d" % (case["id"], i)
        views = []
        if kind == "round":
            views = [e, e.get("snapshot", {})]
        else:
            views = [e.get("round", {}), e.get("snapshot", {}).get("round", {})]
        for v in views:
            if "zoneIndex" in v:
                ck.eq(where + " zoneIndex", v["zoneIndex"], zone_index)
            if "zoneId" in v:
                ck.eq(where + " zoneId", v["zoneId"], rules.locations[zone_index])


def run_respawn_case(case, rules, mode, ck):
    setup = case.get("setup", {})
    areas = setup["spawnAreas"]
    model = RespawnModel(rules, setup.get("seed", 1), areas)
    for p in setup.get("participants", []):
        if model.add(p["id"], p["team"], p.get("loadout")) != "ok":
            raise ValueError("%s: setup ucastnika %s selhal" % (case["id"], p["id"]))
    world = {}
    irregular = {}
    label = "" if mode is None else " [ticks %s]" % canonical(mode)

    def apply(s):
        op = s["op"]
        if op == "loop":
            for _ in range(s["count"]):
                for inner in s["steps"]:
                    apply(inner)
            return "ok"
        if op == "add":
            return model.add(s.get("id"), s.get("team"), s.get("loadout"))
        if op == "kill":
            return model.kill(s.get("id"))
        if op == "damage":
            return model.damage(s.get("id"), s.get("amount"), s.get("attacker"))
        if op == "setLoadout":
            return model.set_loadout(s.get("id"), s.get("loadout"))
        if op in ("tick", "run"):
            for key in ("bodies", "blocked"):
                if key in s:
                    world[key] = s[key]
            if op == "tick":
                dts = [s["dtUs"]] * s.get("repeat", 1)
            else:
                m = mode if s["ticks"] == "case" else s["ticks"]
                dts = expand_ticks(s["durationUs"], m, irregular)
            for dt in dts:
                model.update(dt, world)
            return "ok"
        if op == "resetRound":
            return model.reset_round()
        if op == "weapon":
            return None  # zbrane stav respawnu nemeni
        raise ValueError("%s: neznama operace %s" % (case["id"], op))

    for i, s in enumerate(case["steps"]):
        model.events = []
        result = apply(s)
        events = model.events
        snap = model.snapshot()
        e = s.get("expect", {})
        where = "%s%s krok %d (%s)" % (case["id"], label, i, s["op"])
        if s["op"] in RESPAWN_OPS:
            if "result" in e:
                ck.eq(where + " result", e["result"], result)
            if "events" in e:
                ck.eq(where + " events", e["events"], events)
        allowed = life_allowed(snap["order"])
        if "snapshot" in e:
            ck.compare_subset(where + " snapshot", e["snapshot"], snap, allowed)
        subset = {k: v for k, v in e.items() if k not in RESERVED}
        ck.compare_subset(where + " stav", subset, snap, allowed)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shared", default=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    try:
        with open(os.path.join(args.shared, "config", "rules.json"), encoding="utf-8") as f:
            base = json.load(f)
        vec_dir = os.path.join(args.shared, "testvectors")
        files = sorted(n for n in os.listdir(vec_dir) if n.endswith(".json"))
    except (OSError, ValueError) as exc:
        print("CHYBA: %s" % exc)
        return 2

    ck = Checker(args.verbose)
    counts = {"rng": 0, "zone": 0, "respawn": 0}
    for name in files:
        with open(os.path.join(vec_dir, name), encoding="utf-8") as f:
            doc = json.load(f)
        for case in doc.get("cases", []):
            kind = case.get("kind")
            before = len(ck.failures)
            try:
                if kind == "rng":
                    check_rng(case, ck)
                    counts["rng"] += 1
                elif kind in ("round", "match", "respawn"):
                    rules = Rules(merge_patch(base, case.get("rules", {})))
                    if kind in ("round", "match"):
                        check_zone_selection(case, rules, ck)
                        counts["zone"] += 1
                    if kind == "respawn":
                        for mode in case.get("tickModes", [None]):
                            run_respawn_case(case, rules, mode, ck)
                        counts["respawn"] += 1
                else:
                    continue
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                ck.failures.append("%s/%s: chyba pripadu: %r" % (name, case.get("id"), exc))
            if args.verbose:
                print("%s %s/%s" % ("OK  " if len(ck.failures) == before else "FAIL", name, case.get("id")))
    for msg in ck.failures[:40]:
        print("NESHODA " + msg)
    print("seed_reference: rng %d, vyber oblasti %d, respawn %d pripadu; %d porovnani, %d neshod"
          % (counts["rng"], counts["zone"], counts["respawn"], ck.checks, len(ck.failures)))
    return 0 if not ck.failures else 1


if __name__ == "__main__":
    sys.exit(main())
