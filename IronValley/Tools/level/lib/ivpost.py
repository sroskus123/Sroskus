"""
ivlayout_post -- second pass of build.py: environment, boundary, surfaces, trees (baked), then the
combat analyses that feed data back into layout.json (spawn-row selection per zone, lanes, cover
points, chokepoints, AI navigation data, performance budget).
"""
import json
import math
import os

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, LineString, Point
from skimage.graph import MCP_Geometric
import skfmm

import ivterrain as T
import ivraster as R
import ivbuildings as IB

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))       # IronValley/
WORK = os.path.join(ROOT, "Tools", "level", "_out")
ENV_JSON = os.path.join(ROOT, "Web", "src", "data", "environment.json")
RUN_SPEED = 3.5      # m/s (brief ANIM-01: run 3-4 m/s)
SPRINT_SPEED = 5.75  # m/s (sprint 5-6.5 m/s)
AGENT_R = 0.35


def r2(v):
    return round(float(v), 2)


# ------------------------------------------------------------------------------------------------
# sun position (NOAA simplified) -- fictional site 49.90 N, 15.10 E, 26 Sept 2026, CEST (UTC+2)
# ------------------------------------------------------------------------------------------------
def sun_position(lat, lon, doy, hour_utc):
    g = 2 * math.pi / 365.0 * (doy - 1 + (hour_utc - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    tst = hour_utc * 60 + eqt + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1, min(1, cz)))
    el = 90 - math.degrees(zen)
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180
    return az % 360, el


def environment():
    env = json.load(open(ENV_JSON))
    az, el = env["sun"]["azimuthDeg"], env["sun"]["elevationDeg"]
    d = [math.sin(math.radians(az)) * math.cos(math.radians(el)), math.cos(math.radians(az)) * math.cos(math.radians(el)),
         math.sin(math.radians(el))]
    az_chk, el_chk = sun_position(49.90, 15.10, 253, 15.0 + 5.0 / 60.0 - 2.0)
    return {
        "source": "Web/src/data/environment.json is the single source of truth for sun, sky, clouds, hemisphere fill and exposure; "
                  "this block copies those values for the level tools and adds the map fog override recorded as decision D9 in "
                  "Docs/ARCHITECTURE.md",
        "time": "10 September 2026, 15:05 CEST (fictional site 49.90 N 15.10 E): the environment.json sun (azimuth 222 deg, "
                "elevation 38 deg) matches this date/time within 0.3 deg (NOAA formula: azimuth %.1f, elevation %.1f)" % (az_chk, el_chk),
        "sun": {"azimuth_compass_deg": az, "elevation_deg": el, "direction_to_sun_world": [round(v, 4) for v in d],
                "color": env["sun"]["color"], "intensity_threejs": env["sun"]["intensity"],
                "shadow": {k: v for k, v in env["sun"].items() if k.startswith("shadow") and not k.startswith("_")},
                "ue5": {"DirectionalLight": "Atmosphere Sun Light, same direction, 75 000 lux (physical), source angle 0.53 deg",
                        "exposure": "manual EV100 14.0 outdoors; auto-exposure 11.5-14.5 for interiors, speed up 2.0 / down 1.2"}},
        "sky": dict({k: v for k, v in env["sky"].items() if not k.startswith("_")}, model="three.js Sky (Preetham) with the detailed cloud layer of Web/src/engine/clouds.js; "
                                      "UE5 SkyAtmosphere + Volumetric Cloud"),
        "clouds": dict({k: v for k, v in env["clouds"].items() if not k.startswith("_")}, look="fair-weather cumulus about 3/8 (cloudCoverage 0.4), no per-frame noise, cloudSpeed 0 "
                                            "(static) -> no temporal flicker"),
        "hemisphere": env["hemisphere"], "environmentIntensity": env["environmentIntensity"], "exposure": env["exposure"],
        "fog": {"environment_json_value": env["fog"],
                "map_override_D9": {"color": env["fog"]["color"], "type": "FogExp2 + exponential height fog (Web/src/engine/heightFog.js)",
                                    "density": 0.0012, "heightDensity": 0.0006, "heightFalloff": 0.08, "baseHeight": 0.0,
                                    "effect": "fog factor at eye height ~ 3.6 % at 60 m, ~10 % at 150 m (AI perception cap), ~40 % at "
                                              "600 m (near ridges), > 90 % beyond 1.4 km",
                                    "why": "the environment.json values (0.0045 / 0.0035) were tuned for the 80 m test range; on the 350 m "
                                           "map they would haze 59 % of the contrast at 150 m and erase the distant hills"}},
        "post": {"tone_mapping": "ACESFilmic (engine default), exposure from environment.json", "bloom": "<= 0.15 (sun glints only)",
                 "vignette": "<= 0.15", "grain": 0.0, "motion_blur": "off by default", "dof": "off in gameplay (ADS: weapon only)",
                 "colour_grading": "neutral, +5 % warm midtones at most", "rule": "effects never mask modelling faults (brief 3.3, ENV-04)"},
        "palette_ref": "Docs/ART_DIRECTION.md (hex palette and PBR ranges are binding there)",
    }


def _barrier_sections(hard_ring, layout):
    """split the barrier ring (hard polygon 0.5 m inwards) into typed sections; road crossings become roadblocks."""
    from shapely.geometry import LineString as _Ls, Point as _Pt
    ring = _Ls(list(hard_ring.exterior.coords))
    Lr = ring.length
    # roadblock spans where roads/tracks cross the ring
    blocks = []
    for rd in layout["roads"] + layout["tracks"]:
        if rd["id"] not in ("ROAD_A", "ROAD_B", "TRACK_C"):
            continue
        pl = _Ls([q[:2] for q in rd["polyline"]])
        x = pl.intersection(ring)
        pts = [x] if x.geom_type == "Point" else list(getattr(x, "geoms", []))
        for q in pts:
            s0 = ring.project(q)
            half = rd["width"] / 2 + rd.get("shoulders", {}).get("width", 0.5) + 2.5
            blocks.append((s0 - half, s0 + half, rd["id"]))

    def kind_at(pt):
        x, y = pt.x, pt.y
        if y > 145 and -30 < x < 70:
            return "quarry_fence_2m"
        if x > 90 and y < -75:
            return "farm_fence_timber_1p4m"
        if x > 55 and -60 < y < 125:
            return "pasture_fence_barbed_1p3m"
        return "deer_fence_2m"
    step = 2.0
    ss = np.arange(0.0, Lr, step)
    labels = []
    for s_ in ss:
        lab = None
        for a_, b_, rid in blocks:
            if a_ <= s_ <= b_ or a_ <= s_ + Lr <= b_ or a_ <= s_ - Lr <= b_:
                lab = "roadblock:" + rid
        labels.append(lab or kind_at(ring.interpolate(s_)))
    # rotate so the ring starts at a label change
    k0 = next((i for i in range(1, len(labels)) if labels[i] != labels[i - 1]), 0)
    order = list(range(k0, len(labels))) + list(range(0, k0))
    secs = []
    cur, start = labels[order[0]], order[0]
    run = [order[0]]
    for i in order[1:]:
        if labels[i] != cur:
            secs.append((cur, run))
            cur, run = labels[i], [i]
        else:
            run.append(i)
    secs.append((cur, run))
    out = []
    for lab, run in secs:
        pts = [ring.interpolate(ss[i]) for i in run] + [ring.interpolate((ss[run[-1]] + step) % Lr)]
        out.append((lab, [[r2(p_.x), r2(p_.y)] for p_ in pts]))
    return out


BARRIER_TYPES = {
    "deer_fence_2m": {"height": 2.0, "posts": "peeled larch posts every 3.0 m, knotted wire mesh 2.0 m", "blocks_bullets": False,
                      "blocks_vision": False, "sign": "sign_minefield", "explanation": "lesní oplocenka + cedule min"},
    "pasture_fence_barbed_1p3m": {"height": 1.3, "posts": "timber posts every 2.5 m, 4 strands of barbed wire", "blocks_bullets": False,
                                  "blocks_vision": False, "sign": "sign_minefield", "explanation": "pastevní ohradník s ostnatým drátem + cedule min"},
    "quarry_fence_2m": {"height": 2.0, "posts": "steel posts every 2.5 m, chain-link 2.0 m + 3 strands of barbed wire, locked quarry gate",
                        "blocks_bullets": False, "blocks_vision": False, "sign": "sign_quarry", "explanation": "oplocení štěrkovny"},
    "farm_fence_timber_1p4m": {"height": 1.4, "posts": "timber post-and-rail fence, 3 rails, posts every 2.0 m, between the farm "
                               "buildings", "blocks_bullets": False, "blocks_vision": False, "sign": "sign_minefield",
                               "explanation": "ohrada statku + cedule min"},
    "roadblock": {"height": 1.8, "posts": "jersey barriers 0.8 m + razor-wire coil on top to 1.8 m, steel boom gate (closed)",
                  "blocks_bullets": True, "blocks_vision": False, "sign": "sign_checkpoint", "explanation": "zátaras kordonu"},
}


def boundary(layout):
    soft = Polygon(layout["boundary"]["soft_polygon"])
    hard = soft.buffer(6.0, join_style=2, mitre_limit=2.0).simplify(0.5)
    hard_xy = [[r2(x), r2(y)] for x, y in list(hard.exterior.coords)[:-1]]
    hard_xy = [[max(-175, min(175, x)), max(-175, min(175, y))] for x, y in hard_xy]
    warn = soft.buffer(-8.0, join_style=2, mitre_limit=2.0).simplify(0.3)
    warn_xy = [[r2(x), r2(y)] for x, y in list(warn.exterior.coords)[:-1]]
    # review P1-EDGE: the barriers exist as data, 0.5 m inside the hard line, continuous round the whole map
    bring = Polygon(hard_xy).buffer(-0.5, join_style=2, mitre_limit=2.0)
    barriers = []
    for k, (lab, pts) in enumerate(_barrier_sections(bring, layout)):
        typ = "roadblock" if lab.startswith("roadblock") else lab
        bt = BARRIER_TYPES[typ]
        seg_len = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        signs = []
        from shapely.geometry import LineString as _Ls
        ls_ = _Ls(pts)
        n_s = int(seg_len // 25.0)
        for j in range(n_s + 1):
            if typ == "roadblock" and j > 0:
                break
            q = ls_.interpolate(min(seg_len, 12.5 + 25.0 * j) if typ != "roadblock" else seg_len / 2)
            signs.append({"pos": [r2(q.x), r2(q.y)], "text_id": bt["sign"], "facing": "inwards (towards the village)"})
        barriers.append({"id": f"BND_{k + 1:02d}_{typ.upper()}", "type": typ, "polyline": pts, "height": bt["height"],
                         "construction": bt["posts"], "blocks_movement": True, "blocks_bullets": bt["blocks_bullets"],
                         "blocks_vision": bt["blocks_vision"], "length_m": r2(seg_len), "signs": signs,
                         **({"road": lab.split(":")[1]} if typ == "roadblock" else {})})
    return {
        "soft_polygon": layout["boundary"]["soft_polygon"],
        "warning_polygon": warn_xy,
        "hard_polygon": hard_xy,
        "soft_area_m2": r2(soft.area),
        "barriers": barriers,
        "barrier_rule": "the barrier ring runs 0.5 m inside the hard polygon over its whole length (sections join end to end); the "
                        "invisible capsule wall therefore always stands directly behind a visible fence or roadblock; signs every 25 m "
                        "face the village; check_layout.py BND samples the hard line every 2 m",
        "rules": {
            "warning_band": "8 m wide band inside the soft line (between warning_polygon and soft_polygon): HUD 'Blížíš se k hranici "
                            "bojového prostoru' (no timer)",
            "soft": "crossing the soft line -> HUD 'Opouštíš bojový prostor! Vrať se: 10 s' countdown, desaturation + red vignette; at 0 "
                    "the player dies as 'Minové pole' (no kill credit, no score change, normal respawn delay)",
            "hard": "invisible collision wall 6 m outside the soft line (capsules only; bullets ignore it), 0.5 m behind the barrier "
                    "ring boundary.barriers (fences, roadblocks), never in open ground",
            "bots": "navmesh is cut 1 m inside the soft polygon; bots never path outside it; spawn points keep >= 10 m to the soft line "
                    "(outside the warning band)",
            "map": "the pre-round (loadout) map and the pause map draw the soft line as a red hatched outline, the three roadblocks and "
                   "the team's active spawn row for the round"},
        "player_text_cs": {"briefing": layout["meta"]["round_fiction"]["briefing_cs"],
                           "warning": "Blížíš se k hranici bojového prostoru.",
                           "leaving": "Opouštíš bojový prostor! Vrať se: {s} s",
                           "death": "Minové pole",
                           "sign_minefield": "POZOR! MINY / VOJENSKÝ PROSTOR - VSTUP ZAKÁZÁN",
                           "sign_checkpoint": "KONTROLNÍ STANOVIŠTĚ - STŮJ!",
                           "sign_quarry": "Štěrkovna Kalný Vrch - vstup zakázán",
                           "sign_road_a": "Nové Kalno 2 km",
                           "sign_hunting": "Honitba - vstup se psy zakázán",
                           "toponyms_note": "all names are fictional (review P2-REAL-TOPONYMS: the former 'Horní/Dolní Hamry' are real "
                                            "places and were replaced)"},
        "treatment": [
            {"section": "arm A end (WSW, behind spawn alfa)", "physical": "roadblock section BND_*_ROADBLOCK on ROAD_A (jersey barriers + razor "
             "wire + boom gate) joined to the deer fence of the spurs; team alfa truck, timber-yard hut and log stacks; the brook enters "
             "a culvert under a railway embankment 30 m further (backdrop)",
             "explanation": "own rear area: the road continues to the lower valley (church spire visible), signpost 'Nové Kalno 2 km' (fictional)"},
            {"section": "NW spur (A<->B, behind the workshop)", "physical": "deer fence 2 m (lesní oplocenka) on the barrier ring, forest edge "
             "of spruce/pine with birch, slope steepening to 25-30 deg, dense hazel understory",
             "explanation": "red-white 'POZOR! MINY / VOJENSKÝ PROSTOR' signs on the fence every 25 m, HUD warning band"},
            {"section": "arm B end (N, behind spawn bravo)", "physical": "quarry fence 2 m + roadblock on ROAD_B, 5.5 m gravel heaps, conveyor "
             "frame, quarry face backdrop, team bravo truck", "explanation": "own rear area; quarry gate 'Štěrkovna Kalný Vrch - vstup zakázán'"},
            {"section": "E spur (B<->C, behind the warehouse)", "physical": "pasture fence with barbed wire on the barrier ring, hedgerow, then a "
             "wooded slope", "explanation": "minefield signs every 25 m on the pasture fence, HUD warning band"},
            {"section": "arm C end (SE, behind spawn charlie)", "physical": "farm post-and-rail fence between barn and machinery shed + roadblock on "
             "TRACK_C", "explanation": "own rear area; the track continues uphill between fields to a ridge (backdrop)"},
            {"section": "S spur (C<->A, behind the house)", "physical": "deer fence on the barrier ring along the oak/hornbeam and spruce wood "
             "edge, slope 22-28 deg", "explanation": "minefield signs, hunting-ground sign 'Honitba', HUD warning band"},
        ],
    }


def surfaces(layout):
    return {
        "footstep_and_impact_types": ["asphalt", "gravel", "dirt", "mud", "grass", "forest_floor", "concrete", "paving", "wood",
                                      "metal", "water", "tiles", "stone"],
        "wet": "after a shower (ART_DIRECTION 1): asphalt, concrete and paving use their wet variants (darker, roughness -0.3, "
               "puddles in ruts, at kerbs and in the yard low spots); footsteps on wet asphalt add a light splash layer",
        "default": "grass",
        "resolution_rule": "highest priority wins; interiors use buildings.json room floor_material (mapped: concrete*->concrete, "
                           "terrazzo/tiles->tiles, timber*/parquet->wood, vinyl*->tiles); exterior stairs/bridges use their material",
        "regions": [
            {"surface": "water", "priority": 100, "from": "water[BROOK_WATER] polyline, width_at_surface"},
            {"surface": "metal", "priority": 95, "from": "buildings.json exterior_stairs (galvanised grating), roller doors, shipping container / skip roofs"},
            {"surface": "concrete", "priority": 90, "from": "bridge decks BR_MAIN, BR_FOOT_A, BR_FOOT_B (concrete slabs, ref. 02), loading "
                                                           "dock SK_DOCK, dock stairs and ramp, exterior steps, retaining-wall stairs"},
            {"surface": "water", "priority": 88, "from": "DITCH_C trickle (0.05 m): splash footsteps only, no speed change"},
            {"surface": "asphalt", "priority": 80, "from": "roads ROAD_A, ROAD_B (width)"},
            {"surface": "gravel", "priority": 78, "from": "road shoulders (0.75 m), paths with surface gravel"},
            {"surface": "dirt", "priority": 76, "from": "TRACK_C and TRACK_E_RING wheel ruts (2 x 0.5 m at +-0.8 m), paths with surface dirt"},
            {"surface": "grass", "priority": 75, "from": "TRACK_C and TRACK_E_RING centre strips (0.6 m)"},
            {"surface": "gravel", "priority": 75, "from": "TRACK_SKLAD_REAR"},
            {"surface": "concrete", "priority": 74, "from": "DRIVE_DUM"},
            {"surface": "mud", "priority": 70, "from": "ditch DITCH_A (bed + banks), DITCH_C banks, brook banks below water+0.4 m"},
            {"surface": "stone", "priority": 71, "from": "DITCH_C stone-pitched bed (0.6 m)"},
            {"surface": "dirt", "priority": 72, "from": "sunken lane UVOZ_S bed (bed_width) -- roots and leaf litter decals on the banks"},
            {"surface": "grass", "priority": 71, "from": "mill race MILLRACE bed and banks (dry, overgrown)"},
            {"surface": "paving", "priority": 60, "polygon_ref": "PAD_NAVES", "note": "granite setts on the square"},
            {"surface": "gravel", "priority": 60, "polygon_ref": "PAD_DILNA", "note": "yard + rear pad"},
            {"surface": "concrete", "priority": 60, "polygon_ref": "PAD_SKLAD_YARD"},
            {"surface": "gravel", "priority": 60, "polygon_ref": "PAD_SKLAD", "note": "rear yard"},
            {"surface": "grass", "priority": 55, "polygon_ref": "PAD_DUM_TERRACE", "note": "garden lawn; gravel paths 1.0 m around the house"},
            {"surface": "gravel", "priority": 58, "polygon": [p for p in layout["spawn_areas"][0]["polygon"]], "note": "spawn alfa timber yard"},
            {"surface": "gravel", "priority": 58, "polygon": [p for p in layout["spawn_areas"][1]["polygon"]], "note": "spawn bravo gravel works"},
            {"surface": "mud", "priority": 58, "polygon": [p for p in layout["spawn_areas"][2]["polygon"]], "note": "spawn charlie farmyard (mud + straw)"},
            {"surface": "dirt", "priority": 56, "from": "fields FLD_STUBBLE_C (stubble, ruts) and FLD_GARDEN_PLOTS (tilled strips)"},
            {"surface": "grass", "priority": 56, "from": "field FLD_HAY_E (mown hay meadow)"},
            {"surface": "forest_floor", "priority": 20, "from": "outside the soft boundary under forest canopy (spruce needles, pine litter, "
                                                                 "birch leaves)"},
            {"surface": "stone", "priority": 65, "from": "retaining walls (top), mill race lining, stone crosses"},
        ],
    }


# ------------------------------------------------------------------------------------------------
# trees
# ------------------------------------------------------------------------------------------------
SPECIES = {
    "lipa": {"name_cs": "lípa srdčitá", "latin": "Tilia cordata", "height": 18.0, "crown_radius": 6.5, "crown_base": 3.0, "trunk_radius": 0.40},
    "lipa_stara": {"name_cs": "lípa (památná, náves)", "latin": "Tilia platyphyllos", "height": 22.0, "crown_radius": 8.5, "crown_base": 3.6, "trunk_radius": 0.65},
    "javor": {"name_cs": "javor klen", "latin": "Acer pseudoplatanus", "height": 17.0, "crown_radius": 5.5, "crown_base": 3.0, "trunk_radius": 0.30},
    "jasan": {"name_cs": "jasan ztepilý", "latin": "Fraxinus excelsior", "height": 18.0, "crown_radius": 5.0, "crown_base": 4.0, "trunk_radius": 0.28},
    "dub": {"name_cs": "dub letní", "latin": "Quercus robur", "height": 18.0, "crown_radius": 6.5, "crown_base": 3.5, "trunk_radius": 0.45},
    "buk": {"name_cs": "buk lesní", "latin": "Fagus sylvatica", "height": 22.0, "crown_radius": 5.5, "crown_base": 5.0, "trunk_radius": 0.30},
    "habr": {"name_cs": "habr obecný", "latin": "Carpinus betulus", "height": 12.0, "crown_radius": 4.0, "crown_base": 2.0, "trunk_radius": 0.20},
    "olse": {"name_cs": "olše lepkavá", "latin": "Alnus glutinosa", "height": 14.0, "crown_radius": 3.5, "crown_base": 2.5, "trunk_radius": 0.22},
    "vrba": {"name_cs": "vrba křehká", "latin": "Salix fragilis", "height": 11.0, "crown_radius": 4.5, "crown_base": 2.0, "trunk_radius": 0.35},
    "briza": {"name_cs": "bříza bělokorá (vzrostlá, R15)", "latin": "Betula pendula", "height": 16.5, "crown_radius": 4.0, "crown_base": 3.5, "trunk_radius": 0.20},
    "briza_mlada": {"name_cs": "bříza mladá (R10)", "latin": "Betula pendula", "height": 12.5, "crown_radius": 2.4, "crown_base": 3.0, "trunk_radius": 0.11},
    "smrk": {"name_cs": "smrk ztepilý (R11)", "latin": "Picea abies", "height": 22.0, "crown_radius": 3.0, "crown_base": 0.8, "trunk_radius": 0.28,
             "leaf_type": "conifer", "note": "conical, branches to the ground: a spruce blocks vision near the ground like a shrub"},
    "borovice": {"name_cs": "borovice lesní", "latin": "Pinus sylvestris", "height": 20.0, "crown_radius": 3.5, "crown_base": 9.0, "trunk_radius": 0.25,
                 "leaf_type": "conifer", "note": "high flat crown, bare trunk (refs 01-03 woods)"},
    "jablon": {"name_cs": "jabloň (stará odrůda)", "latin": "Malus domestica", "height": 6.5, "crown_radius": 3.0, "crown_base": 1.7, "trunk_radius": 0.15},
    "hruska": {"name_cs": "hrušeň", "latin": "Pyrus communis", "height": 9.0, "crown_radius": 3.0, "crown_base": 2.0, "trunk_radius": 0.18},
    "svestka": {"name_cs": "švestka", "latin": "Prunus domestica", "height": 6.0, "crown_radius": 2.5, "crown_base": 1.6, "trunk_radius": 0.12},
    "orech": {"name_cs": "ořešák královský", "latin": "Juglans regia", "height": 12.0, "crown_radius": 6.0, "crown_base": 2.6, "trunk_radius": 0.30},
}
for s in SPECIES.values():
    s.setdefault("leaf_type", "deciduous")
    s["lods"] = "LOD0 < 35 m (full mesh, alpha-tested leaf cards), LOD1 35-90 m (merged cards), LOD2 90-250 m (cross impostor), impostor band beyond"
CONIFER_SHARE_INSIDE_MAX = 0.12


def poisson(mask_fn, bounds, rmin, seed, k=20):
    """Bridson Poisson-disk sampling in a rectangle; mask_fn(x,y)->bool accepts."""
    rng = np.random.default_rng(seed)
    x0, y0, x1, y1 = bounds
    cell = rmin / math.sqrt(2)
    gw = int((x1 - x0) / cell) + 1
    gh = int((y1 - y0) / cell) + 1
    grid = -np.ones((gh, gw), int)
    pts = []
    active = []
    # seed: several starting points
    tries = 0
    while len(pts) < 1 and tries < 10000:
        p = np.array([rng.uniform(x0, x1), rng.uniform(y0, y1)])
        tries += 1
        if mask_fn(p[0], p[1]):
            pts.append(p)
            active.append(0)
            grid[int((p[1] - y0) / cell), int((p[0] - x0) / cell)] = 0
    # scan-seeding so disconnected regions also get filled
    scan = [(x, y) for y in np.arange(y0, y1, rmin * 3) for x in np.arange(x0, x1, rmin * 3)]
    si = 0
    while active or si < len(scan):
        if not active:
            x, y = scan[si]
            si += 1
            p = np.array([x + rng.uniform(0, rmin), y + rng.uniform(0, rmin)])
            if not (x0 <= p[0] < x1 and y0 <= p[1] < y1) or not mask_fn(p[0], p[1]):
                continue
            gi, gj = int((p[1] - y0) / cell), int((p[0] - x0) / cell)
            ok = True
            for jj in range(max(0, gi - 2), min(gh, gi + 3)):
                for ii in range(max(0, gj - 2), min(gw, gj + 3)):
                    q = grid[jj, ii]
                    if q >= 0 and np.hypot(*(pts[q] - p)) < rmin:
                        ok = False
            if not ok:
                continue
            pts.append(p)
            grid[gi, gj] = len(pts) - 1
            active.append(len(pts) - 1)
            continue
        idx = active[int(rng.integers(len(active)))]
        base = pts[idx]
        found = False
        for _ in range(k):
            a = rng.uniform(0, 2 * math.pi)
            rr = rng.uniform(rmin, 2 * rmin)
            p = base + rr * np.array([math.cos(a), math.sin(a)])
            if not (x0 <= p[0] < x1 and y0 <= p[1] < y1):
                continue
            if not mask_fn(p[0], p[1]):
                continue
            gi, gj = int((p[1] - y0) / cell), int((p[0] - x0) / cell)
            ok = True
            for jj in range(max(0, gi - 2), min(gh, gi + 3)):
                for ii in range(max(0, gj - 2), min(gw, gj + 3)):
                    q = grid[jj, ii]
                    if q >= 0 and np.hypot(*(pts[q] - p)) < rmin:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                pts.append(p)
                grid[gi, gj] = len(pts) - 1
                active.append(len(pts) - 1)
                found = True
                break
        if not found:
            active.remove(idx)
    return pts


def exclusion_mask(layout, g):
    """1 m grid mask of places where scattered trees are NOT allowed."""
    ex = np.zeros(g.shape, bool)
    for rd in layout["roads"] + layout["tracks"]:
        pl = rd["polyline"]
        for a, b in zip(pl[:-1], pl[1:]):
            ex |= g.seg_mask(a[:2], b[:2], rd["width"] / 2 + 3.0)
    for p in layout["paths"]:
        for a, b in zip(p["xy"][:-1], p["xy"][1:]):
            ex |= g.seg_mask(a, b, p["width"] / 2 + 1.5)
    for b in layout["buildings"]:
        ex |= g.poly_mask(b["footprint_world"], pad=4.0)
    for b in layout["secondary_buildings"]:
        ex |= g.poly_mask(b["footprint_world"], pad=3.0)
    for p in layout["props"]:
        ex |= g.poly_mask(R.box_poly(p["position"][:2], p["size"], p["rotation_deg"]), pad=2.0)
    for z in layout["capture_zones"]:
        ex |= g.poly_mask(z["polygon"], pad=2.0)
    for t, sp in layout["spawn_spines"].items():
        pts = [spine_point(layout, t, s)[0].tolist() for s in np.arange(sp["s_range"][0] - 8, sp["s_range"][1] + 8.01, 3.0)]
        for a, b in zip(pts[:-1], pts[1:]):
            ex |= g.seg_mask(a, b, 5.0)
    for f in layout["fences_walls_hedges"]:
        for a, b in zip(f["polyline"][:-1], f["polyline"][1:]):
            ex |= g.seg_mask(a, b, 1.5)
    for rw in layout["retaining_walls"]:
        for a, b in zip(rw["polyline"][:-1], rw["polyline"][1:]):
            ex |= g.seg_mask(a, b, 2.5)
    for vb in layout.get("vegetation_blocks", []):
        if vb["type"] in ("shrub_belt", "windbreak_belt"):
            for a, b in zip(vb["polyline"][:-1], vb["polyline"][1:]):
                ex |= g.seg_mask(a, b, vb["width"] / 2 + 1.0)
        else:
            ex |= g.poly_mask(vb["polygon"], pad=1.0)
    for br in layout["bridges"]:
        ex |= g.seg_mask(br["ends"][0], br["ends"][1], 5.0)
    for ba in layout["boundary"].get("barriers", []):
        for a, b in zip(ba["polyline"][:-1], ba["polyline"][1:]):
            ex |= g.seg_mask(a, b, 1.2)
    for po in layout.get("utility_lines", {}).get("poles", []):
        ex |= g.disk_mask(po["pos"][:2], 1.6)
    for fl in layout.get("fields", []):
        ex |= g.poly_mask(fl["polygon"], pad=0.5)
    for st in layout["terrain"]["stamps"]:
        if st["kind"] == "pad":
            ex |= g.poly_mask(st["polygon"], pad=1.0)
        if st["kind"] == "channel":
            pl = st["polyline"]
            for a, b in zip(pl[:-1], pl[1:]):
                ex |= g.seg_mask(a[:2], b[:2], 4.0)
        if st["kind"] in ("ditch", "sunken_lane"):
            pl = st["polyline"]
            hw = st["bed_width"] / 2 + 3.0
            for a, b in zip(pl[:-1], pl[1:]):
                ex |= g.seg_mask(a[:2], b[:2], hw)
    return ex


def place_trees(layout):
    g = R.Grid(1.0)
    ex = exclusion_mask(layout, g)
    soft = layout["boundary"]["soft_polygon"]
    play = g.poly_mask(soft)
    play_in = ndimage.binary_erosion(play, iterations=2)
    open_areas = [
        [[-60, 150], [-12, 150], [40, 176], [70, 176], [70, 140], [45, 130], [40, 150], [-10, 145], [-40, 175], [-60, 176]],  # gravel works & arm B end fields
        [[100, -130], [176, -150], [176, -96], [140, -86], [120, -110]],  # farm fields SE
        [[-176, -48], [-150, -44], [-140, -62], [-176, -80]],  # arm A road corridor W
    ]
    open_m = np.zeros(g.shape, bool)
    for p in open_areas:
        open_m |= g.poly_mask(p)
    inst = []

    def add(sp, x, y, scale=1.0, yaw=None, tag=""):
        z = float(T.height_at(layout, x, y)[0]) - 0.10
        inst.append({"species": sp, "pos": [r2(x), r2(y), r2(z)], "scale": round(scale, 3),
                     "yaw_deg": r2(yaw if yaw is not None else (hash((round(x, 1), round(y, 1))) % 360)), "group": tag})

    rng = np.random.default_rng(20260926)
    # --- 1. explicit feature trees
    feats = [("lipa_stara", 8.5, 2.5, 1.0, "square linden"),
             ("jasan", -19.5, -12.0, 0.9, "by the bus stop"),
             ("lipa", -30.0, 4.6, 1.0, "workshop yard SW (brook side)"),
             ("javor", 14.0, -5.0, 0.85, "warehouse yard SE corner"),
             ("dub", -92.0, -18.0, 1.1, "arm A meadow between road and brook"),
             ("lipa", -87.0, -46.5, 0.95, "arm A behind the pub"),
             ("javor", 24.0, 63.0, 1.0, "arm B east verge"),
             ("lipa", -5.0, 82.0, 1.0, "arm B meadow"),
             ("dub", 27.0, 97.0, 1.05, "arm B east meadow"),
             ("dub", 62.0, -82.0, 1.0, "arm C meadow"),
             ("lipa", 97.0, -69.0, 0.95, "arm C north meadow"),
             ("orech", *R.xf([-8.0, -40.0], 350, (10.5, -9.0)), 0.9, "house rear yard walnut"),
             ("jablon", *R.xf([-8.0, -40.0], 350, (-5.0, 17.0)), 1.0, "house garden"),
             ("jablon", *R.xf([-8.0, -40.0], 350, (6.0, 15.5)), 1.0, "house garden"),
             ("hruska", *R.xf([-8.0, -40.0], 350, (-12.5, 6.0)), 1.0, "house garden"),
             ("smrk", *R.xf([21.5, -7.5], 55, (3.3, -1.8)), 0.85, "spruce beside the chapel (ref. 01)"),
             ("smrk", *R.xf([21.5, -7.5], 55, (-3.2, -3.6)), 0.8, "spruce behind the chapel (ref. 01)"),
             ("briza", -24.5, 10.5, 0.9, "birch by the brook NW of the square (ref. 02/03)"),
             ]
    for sp, x, y, sc, tag in feats:
        add(sp, x, y, sc, None, "feature:" + tag)
    # --- 2. riparian trees along the brook (both banks, outside yard/bridges/square)
    brook = [p for p in layout["water"][0]["polyline"]]
    bxy = [[p[0], p[1]] for p in brook]
    pts = np.array(bxy)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    s = 4.0
    while s < cs[-1] - 2:
        k = int(np.clip(np.searchsorted(cs, s) - 1, 0, len(seg) - 1))
        t = (s - cs[k]) / seg[k]
        p = pts[k] + t * (pts[k + 1] - pts[k])
        d = (pts[k + 1] - pts[k]) / seg[k]
        n = np.array([-d[1], d[0]])
        for side in (1, -1):
            if rng.random() < 0.35:
                continue
            off = side * (5.2 + rng.uniform(0, 1.6))
            q = p + n * off
            gi, gj = int(round(q[1] + 175)), int(round(q[0] + 175))
            if not (0 <= gi < g.shape[0] and 0 <= gj < g.shape[1]):
                continue
            # skip the square, bridges, zones, yards, paths
            if ex[gi, gj] and not _only_channel(layout, q):
                continue
            sp = "olse" if rng.random() < 0.6 else ("vrba" if rng.random() < 0.75 else "jasan")
            add(sp, q[0], q[1], rng.uniform(0.8, 1.1), None, "riparian")
        s += rng.uniform(9.0, 14.0)
    # --- 3. old orchard on the NW spur (above the mill-race terrace), inside the playable area
    orch = [[-54.0, 12.0], [-78.0, 12.0], [-72.0, 24.0], [-64.0, 36.0], [-60.0, 50.0], [-54.0, 64.0], [-46.0, 78.0], [-34.0, 74.0],
            [-31.0, 60.0], [-36.0, 52.0], [-44.0, 40.0], [-50.0, 28.0]]
    om = Polygon(orch)
    for ix in range(-80, -28, 6):
        for iy in range(6, 82, 6):
            x = ix + rng.uniform(-1.0, 1.0)
            y = iy + (4 if (ix // 8) % 2 else 0) + rng.uniform(-1.0, 1.0)
            if not om.contains(Point(x, y)) or rng.random() < 0.15:
                continue
            gi, gj = int(round(y + 175)), int(round(x + 175))
            if ex[gi, gj]:
                continue
            sp = ["jablon", "jablon", "hruska", "svestka"][int(rng.integers(4))]
            add(sp, x, y, rng.uniform(0.85, 1.15), None, "orchard_NW")
    # --- 4. fruit alley along track C
    tc = [[p[0], p[1]] for p in layout["tracks"][0]["polyline"]]
    P = np.array(tc)
    seg = np.hypot(*np.diff(P, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    s = 20.0
    while s < 116:
        k = int(np.clip(np.searchsorted(cs, s) - 1, 0, len(seg) - 1))
        t = (s - cs[k]) / seg[k]
        p = P[k] + t * (P[k + 1] - P[k])
        d = (P[k + 1] - P[k]) / seg[k]
        n = np.array([-d[1], d[0]])
        for off in (3.3, -6.7):
            q = p + n * off
            if rng.random() < 0.15:
                continue
            # keep clear of props/buildings/zones
            gi, gj = int(round(q[1] + 175)), int(round(q[0] + 175))
            clear = True
            for b in layout["secondary_buildings"] + [{"footprint_world": z["polygon"]} for z in layout["capture_zones"]]:
                if Polygon(b["footprint_world"]).buffer(2.0).contains(Point(q[0], q[1])):
                    clear = False
            for pr in layout["props"]:
                if Polygon(R.box_poly(pr["position"][:2], pr["size"], pr["rotation_deg"])).buffer(1.5).contains(Point(q[0], q[1])):
                    clear = False
            for pth in layout["paths"]:
                if LineString(pth["xy"]).buffer(pth["width"] / 2 + 1.0).contains(Point(q[0], q[1])):
                    clear = False
            for tr_ in layout["tracks"][1:]:  # driveway, ramps
                if LineString([v[:2] for v in tr_["polyline"]]).buffer(tr_["width"] / 2 + 1.0).contains(Point(q[0], q[1])):
                    clear = False
            if clear:
                add("jablon" if rng.random() < 0.7 else "hruska", q[0], q[1], rng.uniform(0.9, 1.15), None, "alley_C")
        s += 11.0
    # --- 5. forest band outside the soft boundary (+ spur wood edges), Poisson disk 5.5 m
    outside = ~ndimage.binary_dilation(play, iterations=3)

    def forest_ok(x, y):
        gi, gj = int(round(y + 175)), int(round(x + 175))
        if not (0 <= gi < g.shape[0] and 0 <= gj < g.shape[1]):
            return False
        return bool(outside[gi, gj] and not ex[gi, gj] and not open_m[gi, gj])
    fpts = poisson(forest_ok, (-175, -175, 175, 175), 5.5, seed=7)
    # refs 01-03: dark spruce/pine woods with birch edges; the edge band (<= 12 m outside the soft line) is birch-rich
    mix = [("smrk", 0.34), ("borovice", 0.14), ("buk", 0.14), ("briza", 0.12), ("dub", 0.08), ("habr", 0.07), ("javor", 0.06),
           ("jasan", 0.05)]
    mix_edge = [("briza", 0.30), ("briza_mlada", 0.20), ("smrk", 0.20), ("habr", 0.15), ("borovice", 0.15)]
    cum = np.cumsum([m[1] for m in mix])
    cum_e = np.cumsum([m[1] for m in mix_edge])
    softP = Polygon(soft)
    for p in fpts:
        u = rng.random()
        if softP.exterior.distance(Point(p[0], p[1])) <= 12.0:
            sp = mix_edge[int(np.searchsorted(cum_e, u))][0]
            add(sp, p[0], p[1], rng.uniform(0.8, 1.1), None, "forest_edge")
        else:
            sp = mix[int(np.searchsorted(cum, u))][0]
            add(sp, p[0], p[1], rng.uniform(0.8, 1.15), None, "forest")
    # spruce row along the E ring track (ref. 01 NE: tall narrow conifers by the dirt track east of the warehouse)
    te = next((t_ for t_ in layout["tracks"] if t_["id"] == "TRACK_E_RING"), None)
    if te:
        from shapely.geometry import LineString as _LsT
        Pt = np.array([q[:2] for q in te["polyline"]], float)
        seg = np.hypot(*np.diff(Pt, axis=0).T)
        cs_ = np.concatenate([[0], np.cumsum(seg)])
        blk = [Polygon(b["footprint_world"]).buffer(2.0) for b in layout["buildings"] + layout["secondary_buildings"]]
        blk += [Polygon(R.box_poly(pr["position"][:2], pr["size"], pr["rotation_deg"])).buffer(1.5) for pr in layout["props"]]
        blk += [_LsT(f["polyline"]).buffer(1.5) for f in layout["fences_walls_hedges"]]
        blk += [_LsT(v["polyline"]).buffer(v["width"] / 2 + 1.0) for v in layout["vegetation_blocks"] if "polyline" in v]
        blk += [Point(*po["pos"][:2]).buffer(2.0) for po in layout.get("utility_lines", {}).get("poles", [])]
        s_ = 4.0
        while s_ < 60.0:
            k = int(np.clip(np.searchsorted(cs_, s_) - 1, 0, len(seg) - 1))
            t = (s_ - cs_[k]) / seg[k]
            p = Pt[k] + t * (Pt[k + 1] - Pt[k])
            d = (Pt[k + 1] - Pt[k]) / seg[k]
            q = p + np.array([-d[1], d[0]]) * 3.4
            if softP.contains(Point(q[0], q[1])) and not any(b_.contains(Point(q[0], q[1])) for b_ in blk):
                add("smrk", q[0], q[1], rng.uniform(0.8, 0.95), None, "spruce_row_E")
            s_ += 6.0
    # --- 6. sparse meadow trees inside the playable area (spur slopes only), Poisson 22 m
    spur_m = np.zeros(g.shape, bool)
    for poly in ([[-97, 6], [-60, -2], [-45, 10], [-40, 60], [-52, 80], [-80, 22]],
                 [[35, 45], [70, 96], [92, 38], [86, -14], [60, -30], [58, 30]],
                 [[-50, -94], [-60, -45], [-20, -60], [30, -58], [70, -108], [10, -93]]):
        spur_m |= g.poly_mask(poly)

    def meadow_ok(x, y):
        gi, gj = int(round(y + 175)), int(round(x + 175))
        if not (0 <= gi < g.shape[0] and 0 <= gj < g.shape[1]):
            return False
        return bool(play_in[gi, gj] and spur_m[gi, gj] and not ex[gi, gj])
    mpts = poisson(meadow_ok, (-175, -175, 175, 175), 20.0, seed=11)
    mix2 = ["lipa", "javor", "dub", "briza", "briza_mlada", "hruska", "habr"]
    for p in mpts:
        sp = mix2[int(rng.integers(len(mix2)))]
        if softP.exterior.distance(Point(p[0], p[1])) <= 10.0 and rng.random() < 0.4:
            sp = "smrk"                       # forest-edge spruces reaching into the spur meadows (refs 01-03)
        add(sp, p[0], p[1], rng.uniform(0.75, 1.05), None, "meadow")
    # dedupe (keep >= 1.5 m apart)
    keep = []
    for t in inst:
        if all(math.hypot(t["pos"][0] - k["pos"][0], t["pos"][1] - k["pos"][1]) > 1.5 for k in keep[-400:]):
            keep.append(t)
    for i, t in enumerate(keep):
        t["id"] = f"TR{i:04d}"
    groups = {}
    for t in keep:
        k = t["group"].split(":")[0]
        groups[k] = groups.get(k, 0) + 1
    return {
        "species": SPECIES,
        "placement_rules": {
            "feature": "explicit hand-placed trees (square linden, garden trees, arm sightline breakers)",
            "riparian": "both brook banks, 5.2-6.8 m from the centre line, every 9-14 m, 35 % skipped; alder 60 %, willow 30 %, ash 10 %; "
                        "never within 5 m of bridges, zone polygons or yards",
            "orchard_NW": "old orchard on the NW spur between the mill-race terrace and the soft boundary, 6 m staggered grid, +-1 m jitter, 15 % missing; apple/pear/plum (low crowns 1.6-2.0 m: they break eye-level sightlines)",
            "alley_C": "fruit alley along TRACK_C every 11 m (NE side +3.3 m, SW side -6.7 m beyond the 1.25 m ditch), 15 % missing",
            "forest": "Poisson disk r = 5.5 m outside the soft boundary (+3 m), except open areas (gravel works, farm fields, road corridor A); "
                      "refs 01-03: Norway spruce 34 %, Scots pine 14 %, beech 14 %, birch 12 %, oak 8 %, hornbeam 7 %, maple 6 %, ash 5 %; "
                      "edge band <= 12 m outside the soft line: birch 30 %, young birch 20 %, spruce 20 %, hornbeam 15 %, pine 15 %; "
                      "understory: hazel/hornbeam shrubs (R13) at 2x density inside 12 m of the soft line (vision blocking, instanced)",
            "meadow": "Poisson disk r = 20 m on spur meadows inside the playable area (linden, maple, oak, birch, young birch, pear, hornbeam; "
                      "40 % spruce within 10 m of the soft line)",
            "spruce_row_E": "Norway spruces every 6 m, 3.4 m NE of TRACK_E_RING along its first 60 m (ref. 01)",
            "conifers_inside": f"conifers inside the playable area are limited to {int(CONIFER_SHARE_INSIDE_MAX * 100)} % of the trees "
                               "there and never within 3 m of a zone or spawn row (brief: deciduous village; refs: spruce woods and accents)",
            "exclusions": "roads +3 m, paths +1.5 m, main buildings +4 m, secondary +3 m, props +2 m, zones +2 m, spawns +3 m, "
                          "fences +1.5 m, retaining walls +2.5 m, bridges 5 m, pads +1 m, brook channel 4 m (riparian excepted), "
                          "boundary barriers +1.2 m, utility poles 1.6 m, fields +0.5 m",
            "seed": 20260926, "z": "terrain height at the trunk - 0.10 m (root flare buried)",
        },
        "counts": groups,
        "instances": keep,
    }


def _only_channel(layout, q):
    """True if q is excluded only because of the brook channel (allowed for riparian trees)."""
    g = R.Grid(1.0, q[0] - 2, q[0] + 2, q[1] - 2, q[1] + 2)
    x, y = q
    for b in layout["buildings"] + layout["secondary_buildings"]:
        if Polygon(b["footprint_world"]).buffer(4.0).contains(Point(x, y)):
            return False
    for z in layout["capture_zones"]:
        if Polygon(z["polygon"]).buffer(3.0).contains(Point(x, y)):
            return False
    for br in layout["bridges"]:
        if LineString(br["ends"]).buffer(6.0).contains(Point(x, y)):
            return False
    for st in layout["terrain"]["stamps"]:
        if st["kind"] == "pad" and Polygon(st["polygon"]).buffer(1.0).contains(Point(x, y)):
            return False
    for p in layout["paths"]:
        if LineString(p["xy"]).buffer(p["width"] / 2 + 1.0).contains(Point(x, y)):
            return False
    for rd in layout["roads"] + layout["tracks"]:
        if LineString([q_[:2] for q_ in rd["polyline"]]).buffer(rd["width"] / 2 + 2.5).contains(Point(x, y)):
            return False
    for pr in layout["props"]:
        if Polygon(R.box_poly(pr["position"][:2], pr["size"], pr["rotation_deg"])).buffer(2.0).contains(Point(x, y)):
            return False
    return True


def road_xy(layout, rid):
    for r in layout["roads"] + layout["tracks"]:
        if r["id"] == rid:
            return [[q[0], q[1]] for q in r["polyline"]]
    raise KeyError(rid)


def spine_point(layout, team, s):
    sp = layout["spawn_spines"][team]
    P = np.array(road_xy(layout, sp["road"]), float)
    S = np.array(sp["spine_polyline"], float)
    seg = np.hypot(*np.diff(P, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    k = int(np.clip(np.searchsorted(cs, s) - 1, 0, len(seg) - 1))
    t = (s - cs[k]) / seg[k]
    q = S[k] + t * (S[k + 1] - S[k])
    d = P[k + 1] - P[k]
    return q, d / np.linalg.norm(d)


def row_points_at(layout, team, s):
    """8 points: 2 lateral columns (+-1.5 m) x 4 ranks along the arm (-4.5..+4.5 m), facing the square."""
    q, d = spine_point(layout, team, s)
    n = np.array([-d[1], d[0]])
    f = -d
    yaw = math.degrees(math.atan2(-f[0], f[1])) % 360
    pts = []
    for rk in (-4.5, -1.5, 1.5, 4.5):
        for cl in (-1.5, 1.5):
            pts.append(q + d * rk + n * cl)
    return q, pts, yaw


def solve_spawns(layout, ras, walk, cost):
    g = ras["grid"]
    teams = list(layout["spawn_spines"].keys())
    zfields = {}
    for zn in layout["capture_zones"]:
        zc = snap(walk, g, *zn["center"])
        dc = fmm_field(cost, walk, g, zc)
        zm = zone_cells(ras, walk, zn)
        phi = np.ones(walk.shape)
        phi[zm] = -1.0
        speed = np.where(ras["water"], 0.75, 1.0)
        de = np.ma.filled(skfmm.travel_time(np.ma.MaskedArray(phi, ~walk), speed, dx=g.res), np.inf)
        zfields[zn["id"]] = (dc, de, zc)
    # candidate rows along each spine: every point >= 1.0 m from any obstacle, local slope < 15 deg
    clear = ndimage.distance_transform_edt(~ras["blocked"]) * g.res
    gy_, gx_ = np.gradient(ras["F"], g.res)
    flat = np.degrees(np.arctan(np.hypot(gx_, gy_))) < 15.0
    spawn_ok = (clear >= 1.0) & flat & walk
    cands = {t: [] for t in teams}
    for t in teams:
        a, b = layout["spawn_spines"][t]["s_range"]
        for s in np.arange(a, b + 0.01, 1.0):
            q, pts, yaw = row_points_at(layout, t, s)
            ok = True
            for pt in pts:
                j, i = g.ij(pt[0], pt[1])
                if not spawn_ok[j, i]:
                    ok = False
                    break
            if not ok:
                continue
            j, i = g.ij(q[0], q[1])
            c = snap(walk, g, q[0], q[1], 1.0)
            if c is None:
                continue
            d = {zid: (float(f[0][c]), float(f[1][c])) for zid, f in zfields.items()}
            cands[t].append((float(s), q, pts, yaw, d))
    fixed = {t: layout["spawn_spines"][t].get("fixed_rows") for t in teams}
    if all(fixed.values()):
        # design-fixed rows (the HESCO screens are built around them); distances are re-measured with the screens present
        solution = {}
        for zn in layout["capture_zones"]:
            zid = zn["id"]
            solution[zid] = {}
            for t in teams:
                sv = fixed[t][zid]
                c = [c for c in cands[t] if abs(c[0] - sv) < 1e-6]
                if not c:
                    raise RuntimeError(f"fixed spawn row {t} s={sv} for {zid} is not a valid row (obstacle/slope)")
                solution[zid][t] = c[0]
        return solution, zfields, cands
    solution = {}
    for zn in layout["capture_zones"]:
        zid = zn["id"]
        A = [np.array([[c[4][zid][0], c[4][zid][1]] for c in cands[t]]) for t in teams]
        best = None
        for i0 in range(len(A[0])):
            for i1 in range(len(A[1])):
                cen = np.array([A[0][i0, 0], A[1][i1, 0]])
                edg = np.array([A[0][i0, 1], A[1][i1, 1]])
                # vectorised over the third team
                c3 = A[2][:, 0]
                e3 = A[2][:, 1]
                cm = (cen.sum() + c3) / 3
                em = (edg.sum() + e3) / 3
                dev = np.maximum.reduce([np.abs(cen[0] / cm - 1), np.abs(cen[1] / cm - 1), np.abs(c3 / cm - 1),
                                         np.abs(edg[0] / em - 1), np.abs(edg[1] / em - 1), np.abs(e3 / em - 1)])
                # prefer balanced, then far from the zone (safety), then deep spawns
                mind = np.minimum(np.minimum(edg[0], edg[1]), e3)
                score = np.round(dev, 3) * 1000 - np.minimum(mind, 110) * 0.01
                k = int(np.argmin(score))
                if best is None or score[k] < best[0]:
                    best = (score[k], (i0, i1, k), dev[k])
        _, idx, dev = best
        solution[zid] = {t: cands[t][i] for t, i in zip(teams, idx)}

    # merge a team's rows for two zones when they are <= 6 m apart and both zones stay within +-5 %
    def zone_dev(zid, sel):
        cen = np.array([sel[t][4][zid][0] for t in teams])
        edg = np.array([sel[t][4][zid][1] for t in teams])
        return max(np.abs(cen / cen.mean() - 1).max(), np.abs(edg / edg.mean() - 1).max())
    zids = list(solution.keys())
    for t in teams:
        for a_ in range(len(zids)):
            for b_ in range(a_ + 1, len(zids)):
                za, zb = zids[a_], zids[b_]
                sa_, sb_ = solution[za][t][0], solution[zb][t][0]
                if abs(sa_ - sb_) > 6.0 or sa_ == sb_:
                    continue
                best_c = None
                for c in cands[t]:
                    if min(sa_, sb_) - 2 <= c[0] <= max(sa_, sb_) + 2:
                        ta = dict(solution[za]); ta[t] = c
                        tb = dict(solution[zb]); tb[t] = c
                        d = max(zone_dev(za, ta), zone_dev(zb, tb))
                        if best_c is None or d < best_c[0]:
                            best_c = (d, c)
                if best_c and best_c[0] <= 0.05:
                    solution[za][t] = best_c[1]
                    solution[zb][t] = best_c[1]
    return solution, zfields, cands


# ------------------------------------------------------------------------------------------------
# paths / distances
# ------------------------------------------------------------------------------------------------
OFFS = []
for dy in range(-3, 4):
    for dx in range(-3, 4):
        if (dx, dy) != (0, 0) and math.gcd(abs(dx), abs(dy)) == 1:
            OFFS.append((dy, dx))
OFFS = np.array(OFFS)


def fmm_field(cost, walk, g, src_ij):
    """geodesic travel 'distance' (metres at speed 1, water at 0.75) from a source cell via fast marching."""
    phi = np.ones(walk.shape)
    j, i = src_ij
    phi[max(0, j - 2):j + 3, max(0, i - 2):i + 3] = -1.0
    phi = np.ma.MaskedArray(phi, ~walk)
    speed = np.where(np.isfinite(cost), 1.0 / np.where(np.isfinite(cost), cost, 1.0), 1.0)
    t = skfmm.travel_time(phi, speed, dx=g.res)
    return np.ma.filled(t, np.inf)


def nav_cost(ras):
    g = ras["grid"]
    free = ~ras["blocked"]
    dist = ndimage.distance_transform_edt(free) * g.res
    walk = dist > AGENT_R
    cost = np.where(walk, 1.0, np.inf)
    cost = np.where(walk & ras["water"], 1.0 / 0.75, cost)
    return cost, walk


def snap(walk, g, x, y, rmax=6.0):
    j, i = g.ij(x, y)
    rr = int(rmax / g.res)
    sub = walk[max(0, j - rr):j + rr + 1, max(0, i - rr):i + rr + 1]
    jj, ii = np.nonzero(sub)
    if len(jj) == 0:
        return None
    jj = jj + max(0, j - rr)
    ii = ii + max(0, i - rr)
    k = np.argmin((jj - j) ** 2 + (ii - i) ** 2)
    return int(jj[k]), int(ii[k])


def rdp(pts, eps):
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts.tolist()
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.linalg.norm(ab)
    if L < 1e-9:
        d = np.linalg.norm(pts - a, axis=1)
    else:
        d = np.abs(np.cross(ab, pts - a)) / L
    k = int(np.argmax(d))
    if d[k] > eps:
        left = rdp(pts[:k + 1], eps)
        right = rdp(pts[k:], eps)
        return left[:-1] + right
    return [a.tolist(), b.tolist()]


def zone_cells(ras, walk, zn):
    g = ras["grid"]
    m = g.poly_mask(zn["polygon"]) & walk & (ras["F"] >= zn["z_min"]) & (ras["F"] <= zn["z_max"])
    return m


def compute_balance(layout, ras, cost, walk):
    g = ras["grid"]
    sol, zfields, cands = solve_spawns(layout, ras, walk, cost)
    teams = list(layout["spawn_spines"].keys())
    res = {"method": "geodesic distance by fast marching (Eikonal, scikit-fmm) on a 0.25 m walk grid (L0 walk surface incl. doors, "
                     "stairs as ramps, dock, bridges), walkable space eroded by the 0.35 m capsule radius (direction bias < 0.5 %), "
                     "brook water at 0.75 speed, steps > 0.40 m and slopes > 45 deg blocked, outside soft boundary blocked. "
                     "Spawn rows: per zone and team one 8-point row slides along the team's spawn spine (s = metres along its road "
                     "from the square); s is chosen by exhaustive search minimising the worst deviation of centre AND edge distance.",
           "run_speed_mps": RUN_SPEED, "sprint_speed_mps": SPRINT_SPEED, "zones": {},
           "spine_samples": {t: [[r2(c[0])] + [r2(c[4][z][0]) for z in zfields] for c in cands[t][::5]] for t in teams},
           "spine_samples_columns": ["s"] + list(zfields.keys())}
    spawn_areas = []
    rows_by_team = {t: [] for t in teams}
    for zid, sel in sol.items():
        for t in teams:
            s, q, pts, yaw, d = sel[t]
            rows_by_team[t].append((zid, s, q, pts, yaw))
    from shapely.geometry import MultiPoint
    for t in teams:
        cps = []
        rows = {}
        for zid, s, q, pts, yaw in rows_by_team[t]:
            key = r2(s)
            if key not in rows:
                rid = f"{t.upper()}_R{len(rows) + 1}"
                rp = MultiPoint([tuple(pt) for pt in pts]).convex_hull.buffer(1.5, join_style=2)
                rows[key] = {"row_id": rid, "s": key, "center": [r2(q[0]), r2(q[1])], "zones": [],
                             "polygon": [[r2(x), r2(y)] for x, y in list(rp.exterior.coords)[:-1]], "pts": pts, "yaw": yaw}
            rows[key]["zones"].append(zid)
        for key, rw in rows.items():
            for k, pt in enumerate(rw["pts"]):
                z = float(ras["F"][g.ij(pt[0], pt[1])])
                cps.append({"id": f"{rw['row_id']}_{k + 1}", "pos": [r2(pt[0]), r2(pt[1]), r2(z)], "yaw_deg": r2(rw["yaw"]),
                            "row": rw["row_id"], "zones": list(rw["zones"]), "rank": k // 2 + 1})
        hull = MultiPoint([c["pos"][:2] for c in cps]).convex_hull.buffer(3.0, join_style=2).simplify(0.3)
        poly = [[r2(x), r2(y)] for x, y in list(hull.exterior.coords)[:-1]]
        spawn_areas.append({"team": t, "polygon": poly, "polygon_role": "team staging area (convex hull of all rows + 3 m); "
                            "enemies inside it never count for respawn selection", "candidate_points": cps,
                            "rows": [{k: v for k, v in rw.items() if k not in ("pts", "yaw")} for rw in rows.values()],
                            "selection_rule": "use the 8 points tagged with the active zone; at round start all 6 members take distinct "
                                              "points (front ranks first); on respawn pick the free point with the largest distance to "
                                              "any visible enemy (>= 25 m, rules.json respawn.minEnemyDistance)"})
    layout["spawn_areas"] = spawn_areas
    for zn in layout["capture_zones"]:
        zid = zn["id"]
        dc, de, zc = zfields[zid]
        cen = np.array([sol[zid][t][4][zid][0] for t in teams])
        edg = np.array([sol[zid][t][4][zid][1] for t in teams])
        z = {"rows_s": {t: r2(sol[zid][t][0]) for t in teams},
             "distances_center_m": {t: r2(v) for t, v in zip(teams, cen)},
             "distances_edge_m": {t: r2(v) for t, v in zip(teams, edg)},
             "mean_center_m": r2(cen.mean()), "mean_edge_m": r2(edg.mean()),
             "deviation_center_pct": {t: r2(100 * (v / cen.mean() - 1)) for t, v in zip(teams, cen)},
             "deviation_edge_pct": {t: r2(100 * (v / edg.mean() - 1)) for t, v in zip(teams, edg)},
             "max_deviation_pct": r2(100 * max(np.abs(cen / cen.mean() - 1).max(), np.abs(edg / edg.mean() - 1).max())),
             "run_time_s_edge": {t: r2(v / RUN_SPEED) for t, v in zip(teams, edg)},
             "sprint_time_s_edge": {t: r2(v / SPRINT_SPEED) for t, v in zip(teams, edg)}}
        m = MCP_Geometric(cost, fully_connected=True)
        m.find_costs([zc])
        lanes = {}
        for t in teams:
            q = sol[zid][t][1]
            src = snap(walk, g, q[0], q[1])
            tb = m.traceback(src)[::-1]
            pts = [[g.xs[i], g.ys[j]] for j, i in tb]
            simp = rdp(pts, 0.4)
            lanes[t] = [[r2(pp[0]), r2(pp[1]), r2(ras["F"][g.ij(pp[0], pp[1])])] for pp in simp]
        z["primary_lanes"] = lanes
        z["center_cell"] = [r2(g.xs[zc[1]]), r2(g.ys[zc[0]])]
        res["zones"][zid] = z
    return res, sol


def via_path(cost, walk, g, a, via, b):
    """shortest path a -> via -> b; length from fast marching, polyline from 8-connected MCP traceback."""
    total = 0.0
    allpts = []
    for p_, q_ in ((a, via), (via, b)):
        d = fmm_field(cost, walk, g, p_)
        total += d[q_]
        m = MCP_Geometric(cost, fully_connected=True)
        m.find_costs([p_])
        tb = m.traceback(q_)
        allpts += [[g.xs[i], g.ys[j]] for j, i in tb]
    return total, allpts


def finish(layout):
    layout["environment"] = environment()
    layout["boundary"] = boundary(layout)
    bjson = {"buildings": IB.all_buildings()}
    layout["trees"] = place_trees(layout)
    if os.environ.get("FAST"):
        layout["spawn_areas"] = []
        layout["surfaces"] = {}
        return layout
    ras = R.build(layout, bjson, res=0.25, with_trees=True)
    cost, walk = nav_cost(ras)
    bal, sol = compute_balance(layout, ras, cost, walk)
    layout["surfaces"] = surfaces(layout)
    g = ras["grid"]
    zsr = {}
    for sa in layout["spawn_areas"]:
        for rw in sa["rows"]:
            for zid in rw["zones"]:
                zsr.setdefault(zid, {})[sa["team"]] = {"row": rw["row_id"], "s": rw["s"]}
    layout["zone_spawn_rows"] = zsr
    # flank lanes (via points on the ring paths / alternative approaches)
    VIA = {
        "zone_dilna": {"alfa": ("P_BANK_TERRACE ramp -> mill-race terrace -> RW stairs", [-45.6, 15.5]),
                       "bravo": ("footbridge B -> west bank -> gable door DL_D3", [-19.5, 45.0]),
                       "charlie": ("brook bed from the square culvert (low covered lane)", [-22.0, 4.0])},
        "zone_sklad": {"alfa": ("track C start -> warehouse yard S gate (P_SKLAD_S)", [30.0, -4.0]),
                       "bravo": ("E ring track -> rear yard at grade (SE corner) -> rear sliding door SK_SD3 / SK_D4", [59.0, 12.0]),
                       "charlie": ("E ring from track C -> rear yard at grade (SE corner)", [55.0, 2.5])},
        "zone_dvur": {"alfa": ("S ring path -> rear yard gate", [-26.0, -55.5]),
                      "bravo": ("square -> driveway (E) instead of the wall stairs", [14.6, -21.6]),
                      "charlie": ("S ring -> sunken lane (úvoz) -> north exit -> rear yard gate", [7.2, -58.0])},
    }
    for zid, z in bal["zones"].items():
        zc = snap(walk, g, *next(zz for zz in layout["capture_zones"] if zz["id"] == zid)["center"])
        fl = {}
        for team, (desc, via) in VIA[zid].items():
            q = sol[zid][team][1]
            src = snap(walk, g, q[0], q[1])
            vc = snap(walk, g, via[0], via[1])
            if vc is None:
                continue
            L, pts = via_path(cost, walk, g, src, vc, zc)
            simp = rdp(pts, 0.4)
            fl[team] = {"desc": desc, "length_m": r2(L), "extra_vs_primary_pct": r2(100 * (L / z["distances_center_m"][team] - 1)),
                        "via": via,
                        "waypoints": [[r2(p[0]), r2(p[1]), r2(ras["F"][g.ij(p[0], p[1])])] for p in simp]}
        for team_, f_ in fl.items():
            if f_["extra_vs_primary_pct"] > 10.0 and zid == "zone_sklad" and team_ == "bravo":
                f_["deep_flank"] = ("deliberate rear manoeuvre along the E ring track into the warehouse rear yard (entered at grade "
                                    "from the south-east since the 22 deg field ramp was removed); bravo's regular alternatives are the "
                                    "yard north end and the road B verge (both within 10 %)")
        z["flank_lanes"] = fl
    layout["balance"] = bal
    layout["lanes"] = {zid: {"primary": z["primary_lanes"], "flank": z["flank_lanes"]} for zid, z in bal["zones"].items()}
    # cover points around zones
    layout["cover_points"] = cover_points(layout, ras, walk)
    layout["chokepoints"] = chokepoints(layout)
    layout["ai_navigation"] = ai_nav(layout)
    fallback_rows(layout)
    layout["performance_budget_browser"] = perf_budget(layout)
    layout["qa_points"] = qa_points(layout)
    # keep raster products for analyze/draw
    os.makedirs(WORK, exist_ok=True)
    np.savez_compressed(os.path.join(WORK, "rasters_0p25.npz"), F=ras["F"].astype(np.float32),
                        blocked=ras["blocked"], walk=walk, water=ras["water"], solid=ras["solid"].astype(np.float32),
                        c0=np.where(np.isinf(ras["c0"]), 9999, ras["c0"]).astype(np.float32),
                        c1=np.where(np.isinf(ras["c1"]), -9999, ras["c1"]).astype(np.float32), H=ras["H"].astype(np.float32),
                        play=ras["play"])
    return layout


def yaw_of(fx, fy):
    return r2(math.degrees(math.atan2(-fx, fy)) % 360.0)


def cover_points(layout, ras, walk):
    """auto-generated cover points within 30 m of each zone: 0.60 m off the faces of hard-cover props, low walls,
    parapets, retaining walls, secondary and main buildings; + window firing positions inside the main buildings."""
    g = ras["grid"]
    objs = []
    for p in layout["props"]:
        if p["cover"] in ("low", "high") and p.get("blocks_bullets", True):
            objs.append((R.box_poly(p["position"][:2], p["size"], p["rotation_deg"]), p["cover"], p["id"]))
    for f in layout["fences_walls_hedges"]:
        if f["cover"] in ("low", "high"):
            for a, b in zip(f["polyline"][:-1], f["polyline"][1:]):
                d = np.array(b) - np.array(a)
                L = np.linalg.norm(d)
                n = np.array([-d[1], d[0]]) / L * 0.15
                objs.append(([list(np.array(a) + n), list(np.array(b) + n), list(np.array(b) - n), list(np.array(a) - n)], f["cover"], f["id"]))
    for sb in layout["secondary_buildings"]:
        if sb.get("embedded_in"):
            continue
        objs.append((sb["footprint_world"], "high", sb["id"]))
    for b in layout["buildings"]:
        objs.append((b["footprint_world"], "high", b["id"]))
    for rw in layout["retaining_walls"]:
        segs = rw.get("segments") or [[i, i + 1] for i in range(len(rw["polyline"]) - 1)]
        for i0, i1 in segs:
            a, b = rw["polyline"][i0], rw["polyline"][i1]
            d = np.array(b) - np.array(a)
            L = np.linalg.norm(d)
            n = np.array([-d[1], d[0]]) / L * rw["thickness"] / 2
            objs.append(([list(np.array(a) + n), list(np.array(b) + n), list(np.array(b) - n), list(np.array(a) - n)],
                         "low" if rw.get("parapet") else "high", rw["id"]))
    zones = [(z["id"], Polygon(z["polygon"])) for z in layout["capture_zones"]]
    out = []
    for poly, cls, oid in objs:
        P = np.array(poly)
        n = len(P)
        cx, cy = P.mean(axis=0)
        for k in range(n):
            a, b = P[k], P[(k + 1) % n]
            d = b - a
            L = np.linalg.norm(d)
            if L < 0.5:
                continue
            u = d / L
            nrm = np.array([u[1], -u[0]])
            if np.dot(nrm, (a + b) / 2 - [cx, cy]) < 0:
                nrm = -nrm
            cnt = max(1, int(L / 1.5))
            for s_ in (np.linspace(0.5, L - 0.5, cnt) if L > 1.0 else [L / 2]):
                q = a + u * s_ + nrm * 0.60
                near = [zid for zid, zp in zones if zp.distance(Point(q[0], q[1])) <= 30.0]
                if not near:
                    continue
                j, i = g.ij(q[0], q[1])
                if not (0 <= j < g.shape[0] and 0 <= i < g.shape[1]) or not walk[j, i]:
                    continue
                facing = -nrm   # from the cover point towards the obstacle = the threat direction it protects from
                left = np.array([-facing[1], facing[0]])
                if s_ < 1.0 or s_ > L - 1.0:
                    corner = a if s_ < 1.0 else b
                    peek = "left" if np.dot(corner - q, left) > 0 else "right"
                else:
                    peek = "over" if cls == "low" else "none"
                out.append({"pos": [r2(q[0]), r2(q[1]), r2(ras["F"][j, i])], "facing": [round(float(facing[0]), 3), round(float(facing[1]), 3)],
                            "facing_deg": yaw_of(facing[0], facing[1]), "height": "high" if cls == "high" else "low",
                            "peek": peek, "capacity": 1, "kind": "object", "object": oid, "zones": near,
                            "inside_zone": [zid for zid, zp in zones if zp.contains(Point(q[0], q[1]))]})
    keep = []
    for c in out:
        if all(math.hypot(c["pos"][0] - k["pos"][0], c["pos"][1] - k["pos"][1]) >= 1.2 or c["object"] != k["object"] for k in keep[-60:]):
            keep.append(c)
    # window firing positions (inside the main buildings, sill <= 1.25 m)
    bdefs = {b["id"]: b for b in IB.all_buildings()}
    import ivcheck as C
    for bp in layout["buildings"]:
        bd = bdefs[bp["id"]]
        wmap = {w["id"]: w for w in bd["walls"]}
        lv = {l["id"]: l for l in bd["levels"]}
        c0, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
        for o in bd["openings"]:
            if o["type"] != "window" or o["sill_height"] > 1.25 or not o.get("passes", {}).get("vision", True):
                continue
            w = wmap[o["wall_id"]]
            gg = C.opening_geom(w, o)
            nx, ny = gg["n"]              # left normal = into the building for external walls
            mx, my = gg["mid"]
            if w["kind"] != "external":
                # internal window (e.g. the dílna office overlooking the hall): the firing point stands on the side that is a
                # room of this level; skipped when both sides are rooms (an ordinary internal glazing between two rooms)
                rooms_l = [Polygon(r_["polygon"]) for r_ in bd["rooms"] if r_["level"] == w["level"]]
                d_ = w["thickness"] / 2 + 0.60
                sides = [sg for sg in (1, -1) if any(rp.contains(Point(mx + sg * nx * d_, my + sg * ny * d_)) for rp in rooms_l)]
                if len(sides) != 1:
                    continue
                nx, ny = nx * sides[0], ny * sides[0]
            inside = (mx + nx * (w["thickness"] / 2 + 0.60), my + ny * (w["thickness"] / 2 + 0.60))
            q = R.xf(c0, rot, inside)
            out_dir = R.xf([0, 0], rot, (-nx, -ny))
            zq = zf + lv[w["level"]]["floor_z"]
            near = [zid for zid, zp in zones if zp.distance(Point(q[0], q[1])) <= 35.0]
            if not near:
                continue
            keep.append({"pos": [r2(q[0]), r2(q[1]), r2(zq)], "facing": [round(out_dir[0], 3), round(out_dir[1], 3)],
                         "facing_deg": yaw_of(out_dir[0], out_dir[1]), "height": "window", "peek": "over",
                         "capacity": 1, "kind": "window", "object": f"{bp['id']}:{o['id']}", "level": w["level"],
                         "sill": o["sill_height"], "zones": near,
                         "inside_zone": [zid for zid, zp in zones if zp.contains(Point(q[0], q[1])) and
                                         next(z for z in layout["capture_zones"] if z["id"] == zid)["z_min"] <= zq <=
                                         next(z for z in layout["capture_zones"] if z["id"] == zid)["z_max"]]})
    for i, c in enumerate(keep):
        c["id"] = f"CP{i:04d}"
    return {"rule": "object points 0.60 m off obstacle faces (capsule r 0.35 + 0.25), spacing 1.5 m, within 30 m of a zone polygon, on "
                    "walkable cells; window points 0.60 m inside every window with sill <= 1.25 m within 35 m of a zone. facing_deg = yaw "
                    "(0 = north, CCW) of the threat direction the point protects from; valid when the threat bearing is within +-60 deg of "
                    "facing_deg and the crouched eye (1.05 m) is occluded. height low = crouch-only cover (0.8-1.5 m), high = standing "
                    "cover (>= 1.6 m), window = stand to fire over the sill. peek = side to lean out (left/right of facing), over = rise "
                    "over the top. capacity 1: runtime reservation, one bot per point (AI-02); a bot releases it when it leaves 1.5 m.",
            "points": keep}


def _bworld(layout, bid, p):
    bp = next(b for b in layout["buildings"] if b["id"] == bid)
    q = R.xf(bp["position"][:2], bp["rotation_deg"], p)
    return [r2(q[0]), r2(q[1])]


def chokepoints(layout):
    br = {b["id"]: b for b in layout["bridges"]}
    rw = {r["id"]: r for r in layout["retaining_walls"]}
    ck = [
        {"id": "CK_BR_MAIN", "at": br["BR_MAIN"]["ends"], "width": 4.5, "type": "bridge", "zone": "zone_dilna",
         "note": "square -> workshop yard; railings see-through: can be covered from the yard and from the square"},
        {"id": "CK_FOOT_A", "at": br["BR_FOOT_A"]["ends"], "width": 1.5, "type": "footbridge", "zone": "zone_dilna"},
        {"id": "CK_FOOT_B", "at": br["BR_FOOT_B"]["ends"], "width": 1.5, "type": "footbridge", "zone": "zone_dilna"},
        {"id": "CK_RW_DILNA_ST", "at": rw["RW_DILNA"]["stairs"][0]["bottom_center_world"], "width": 1.4, "type": "stair",
         "zone": "zone_dilna", "note": "rear pad <-> mill-race terrace"},
        {"id": "CK_RW_DUM_ST", "at": rw["RW_DUM"]["stairs"][0]["bottom_center_world"], "width": 1.5, "type": "stair",
         "zone": "zone_dvur", "note": "square -> terrace garden (the far team's direct entry)"},
        {"id": "CK_DRIVE", "at": [16.0, -19.8], "width": 3.2, "type": "ramp", "zone": "zone_dvur"},
        {"id": "CK_DUM_W_GATE", "at": _bworld(layout, "B_DUM", (-15.3, 3.0)), "width": 2.4, "type": "gate", "zone": "zone_dvur"},
        {"id": "CK_DUM_S_GATE", "at": _bworld(layout, "B_DUM", (-1.0, -13.2)), "width": 2.2, "type": "gate", "zone": "zone_dvur"},
        {"id": "CK_SKLAD_GATE", "at": [12.5, 17.0], "width": 7.0, "type": "yard gate", "zone": "zone_sklad"},
        {"id": "CK_DOCK_STEPS", "at": _bworld(layout, "B_SKLAD", (-13.0, 9.25)), "width": 1.5, "type": "stair", "zone": "zone_sklad"},
        {"id": "CK_DOCK_MID", "at": _bworld(layout, "B_SKLAD", (0.0, 11.5)), "width": 2.0, "type": "stair", "zone": "zone_sklad"},
        {"id": "CK_DOCK_RAMP", "at": _bworld(layout, "B_SKLAD", (15.5, 9.25)), "width": 3.0, "type": "ramp", "zone": "zone_sklad"},
        {"id": "CK_SKLAD_RAMP_E", "at": [61.0, 17.0], "width": 5.0, "type": "field ramp", "zone": "zone_sklad",
         "note": "rear yard <-> E ring through the 4 m cut bank"},
    ]
    for st in layout["terrain"]["stamps"]:
        if st["kind"] == "sunken_lane":
            for ex in st["exits"]:
                ck.append({"id": f"CK_{st['id']}_EXIT_{int(ex['s0'])}", "at_s": [ex["s0"], ex["s1"]], "width": r2(ex["s1"] - ex["s0"]),
                           "type": "sunken lane exit ramp", "zone": "zone_dvur", "note": ex.get("to", "")})
    # every building doorway and stair is a chokepoint with its clear width
    import ivcheck as C
    for bp in layout["buildings"]:
        bd = next(b for b in IB.all_buildings() if b["id"] == bp["id"])
        wmap = {w["id"]: w for w in bd["walls"]}
        for o in bd["openings"]:
            if o["type"] in ("door", "double_door") or (o["type"] == "roller_door" and o["passes"]["movement"]):
                gg = C.opening_geom(wmap[o["wall_id"]], o)
                ck.append({"id": f"CK_{o['id']}", "at": _bworld(layout, bp["id"], gg["mid"]), "width": o["clear_width"],
                           "type": o["type"], "building": bp["id"], "level": wmap[o["wall_id"]]["level"], "zone": bp["zone"]})
        for sd in bd["stairs"] + bd["exterior_stairs"]:
            ck.append({"id": f"CK_{sd['id']}", "at": _bworld(layout, bp["id"], sd["start"]), "width": sd["width"],
                       "type": "stair", "building": bp["id"], "zone": bp["zone"]})
    return ck


def ai_nav(layout):
    bj = IB.all_buildings()
    doors = []
    import ivcheck as C
    for bp in layout["buildings"]:
        bd = next(b for b in bj if b["id"] == bp["id"])
        wmap = {w["id"]: w for w in bd["walls"]}
        for o in bd["openings"]:
            if o["type"] not in ("door", "double_door", "roller_door"):
                continue
            w = wmap[o["wall_id"]]
            gg = C.opening_geom(w, o)
            mid = R.xf(bp["position"][:2], bp["rotation_deg"], gg["mid"])
            lvl = next(l for l in bd["levels"] if l["id"] == w["level"])
            passable = o["type"] != "roller_door" or o["passes"]["movement"]
            doors.append({"building": bp["id"], "opening": o["id"], "pos": [r2(mid[0]), r2(mid[1]), r2(bp["position"][2] + lvl["floor_z"])],
                          "clear_width": o["clear_width"], "clear_height": o["clear_height"], "initial_open_deg": o.get("open_deg"),
                          "passable_v1": passable, "level": w["level"],
                          "nav_corridor_m": r2(max(0.0, o["clear_width"] - 0.70))})
    return {
        "agent": {"radius": 0.35, "height": 1.80, "crouch_height": 1.20, "max_climb": 0.40, "max_slope_deg": 45.0,
                  "recast": {"tool": "recast-navigation (Node, WASM only in the build tool, ARCHITECTURE D4); JSON navmesh shipped",
                             "cs": 0.05, "ch": 0.05, "walkableRadius_cells": 7, "walkableHeight_cells": 36, "walkableClimb_cells": 8,
                             "walkableSlopeAngle": 45.0, "tileSize_cells": 256, "maxEdgeLen_cells": 240, "maxSimplificationError": 1.1,
                             "minRegionArea_cells": 16, "mergeRegionArea_cells": 40, "detailSampleDist_cells": 12,
                             "note": "radius 7 cells = 0.35 m = capsule; every walkable door and stair is >= 1.10 m clear, so the "
                                     "eroded corridor is >= 0.40 m (8 cells) with door leaves in their rest pose. A trial bake at "
                                     "cs 0.10 / radius 4 pinched the 0.30 m corridor of the house U-stair (contour simplification) -- "
                                     "do not bake coarser than cs 0.05. Validation bake: Tools/level/nav (results in navmesh_validation)",
                             "input_geometry": "terrain LOD0 + building construction boxes + slabs + stair ramp colliders + prop "
                                               "hulls + fences/hedge cores + retaining walls + bridges; doors in rest pose; roller "
                                               "doors per state; clipped 1 m inside the soft boundary",
                             "build_gate": "the build FAILS when any documented entrance (door, retaining-wall stair, dock stair, "
                                           "ramp, bridge, sunken-lane exit) is not on the main navmesh component or when the spawn "
                                           "-> zone path balance exceeds max/min 1.06"}},
        "rules": ["No crouch-only passages: every walkable space has >= 2.10 m headroom; every under-stair space below 2.10 m is "
                  "closed by walls, solid mass or collision fill (validated in 3D by check_layout.py).",
                  "Windows are capsule clip planes, never nav links; bots may shoot through them.",
                  "Roofs, racks, the warehouse office roof and all walls > 0.40 m are not climbable; the only off-mesh links are one-way "
                  "drops from the loading dock (1.10 m).",
                  "Upper floors, mezzanines and the balcony are outside every capture polygon; each has two independent ways down."],
        "areas": {"water": {"cost": 1.33}, "ditch": {"cost": 1.1}, "sunken_lane": {"cost": 1.0}, "stairs": {"cost": 1.2},
                  "default": {"cost": 1.0}},
        "perception": {"max_range_m": 150.0, "full_detection_m": 60.0,
                       "falloff": "detection rate falls linearly from 100 % at 60 m to 0 at 150 m; beyond 150 m bots do not detect",
                       "occluders": "the same proxies as bullets/vision (collision_semantics): hedges, shrub belts and copses block AI "
                                    "vision; tree crowns block 50 % of the checks; fog is visual only",
                       "reason": "no instant-aim sniper (brief par. 7); remaining 175-260 m slope-to-slope corridors are handled by this cap"},
        "doors": {"policy_v1": "all passable doors start open at open_deg (rest pose, validated clear of walls, furniture and stairs); "
                               "leaves are KINEMATIC bodies driven by a door state machine (never dynamic -> no jitter with capsules)",
                  "navmesh": "baked with the leaves in their rest pose; every doorway also has an off-mesh door_link across it",
                  "closed_door": "a closed leaf makes its door_link cost +2 m; the path follower stops 0.3 m before it, plays Interact "
                                 "(0.4 s), the leaf opens away from the user, the bot passes",
                  "reservation": "one agent per door portal per 1.2 s; others wait at the approach point or repath after 2.0 s",
                  "blocked_leaf": "if the leaf is blocked for more than 2.5 s the door_link is disabled for that bot for 20 s and it "
                                  "repaths (AI-02 recovery 2-3 s)",
                  "bots_never_close_doors": True, "closed_roller_door": "SK_RD2 is closed, padlocked and baked as a wall",
                  "list": doors},
        "offmesh_links": [
            {"type": "drop", "one_way": True, "where": "loading dock edge (1.10 m) along its whole length", "cost": 1.5},
            {"type": "door_link", "one_way": False, "where": "every doorway in ai_navigation.doors.list", "cost": "0 open / +2 m closed"},
        ],
        "cover": "use cover_points (baked, with facing_deg, peek, capacity 1) + runtime reservation; low cover requires crouch; "
                 "runtime edge sampling only as fallback",
        "stuck_recovery": "no progress > 0.5 m in 2.5 s -> repath with the blocked edge penalised x10 for 10 s; after 2 failures pick "
                          "the next lane (primary -> flank) or the nearest hold point; never teleport (AI-02)",
        "hold_points": hold_points(layout),
        "hold_room_state": "bots holding an upper floor (dílna office, house L1) use a 'hold room' state with one bot on the stair-watch "
                           "cover point (top of the flight) and the others on window points; they leave when the zone is lost",
        "lane_usage": "at round start each team splits 3 primary / 2 flank / 1 support (support follows the primary lane 15 m behind); "
                      "respawned bots re-roll with 60 % primary",
        "spawn_selection": {"round_start": "the 6 members take distinct points of the active row, front ranks first",
                            "respawn_score": "for each free point of the team's active row: -10 if any enemy has line of sight to it "
                                             "(ray from enemy eye 1.65 m to point + 1.2 m), -5 per enemy within 45 m, +1 per friendly "
                                             "within 30 m; highest score wins, ties broken by the round seed (Mulberry32 as in "
                                             "Shared/testvectors/rng.json)",
                            "hard_rule": "never spawn within rules.json respawn.minEnemyDistance (25 m) of a living enemy or inside "
                                         "bodyClearance (1.0 m) of any character; if the active row fails, use the team's other row, "
                                         "then any row of the team; the forward rows (s 84-92 m: ALFA_R2, BRAVO_R2, CHARLIE_R1) are the most exposed and always "
                                         "apply the hard rule"},
    }


def hold_points(layout):
    out = {}
    for z in layout["capture_zones"]:
        P = Polygon(z["polygon"])
        c = P.centroid
        out[z["id"]] = {"note": "positions inside the zone with cover; pick by threat direction", "count_rule": ">= 8 per zone",
                        "from_cover_points": "cover_points whose zones contain this id and that lie inside the polygon"}
    return out


def perf_budget(layout):
    soft = Polygon(layout["boundary"]["soft_polygon"])
    inst = layout["trees"]["instances"]
    inside = sum(1 for t in inst if soft.contains(Point(t["pos"][0], t["pos"][1])))
    near = sum(1 for t in inst if not soft.contains(Point(t["pos"][0], t["pos"][1])) and
               soft.exterior.distance(Point(t["pos"][0], t["pos"][1])) <= 25.0)
    far = len(inst) - inside - near
    split = {"terrain (7x7 chunks of 50 m, 1 splat material, frustum-culled)": 30,
             "main buildings exterior (merged per material, 3 x ~9)": 27,
             "building interiors (merged per room group, culled by portals)": 25,
             "secondary buildings (merged per material per 50 m chunk)": 20,
             "props (InstancedMesh per catalog type, ~48 types)": 48,
             "trees (InstancedMesh per species x LOD, 14 x 3 incl. impostor band)": 42,
             "understory / grass (instanced, 3 types x 2 LOD, 40 m radius)": 6,
             "characters (18 skinned bodies + gear + weapons + FPS arms)": 60,
             "water, decals, sky, clouds, zone marker": 12,
             "shadow pass (3 CSM cascades; trees beyond 60 m and props < 0.5 m do not cast)": 150,
             "post (tone map, AA, bloom)": 6}
    return {
        "target": "1080p, ~60 fps (95th percentile frame <= 25 ms) on a mid-range desktop GPU in Chromium/WebGL2 with 17 bots. "
                  "This is a BUDGET, not a measurement: PERF-01 = NOT TESTED until measured in the real browser build.",
        "draw_calls_worst_view": {"budget": 450, "sum_of_split": sum(split.values()), "split": split,
                                  "worst_view": "Dvůr terrace looking N over the square towards the workshop yard and arm B"},
        "triangles_visible": {"budget": 2000000, "split": {"terrain": 250000, "buildings": 300000, "props": 250000, "trees": 700000,
                                                           "characters (18 x 18 k)": 324000, "grass": 100000}},
        "trees": {"instances_total": len(inst), "inside_soft_boundary": inside, "outside_within_25_m": near, "outside_beyond_25_m": far,
                  "lod": "InstancedMesh per species and LOD: LOD0 < 35 m, LOD1 35-90 m, cross/octahedral impostor 90-250 m; trees "
                         "beyond 25 m outside the soft boundary are impostor-only (never LOD0)",
                  "update": "LOD bucketing every 4th frame on the main thread (no workers required)"},
        "textures": "no KTX2/Basis (its transcoder is WASM, ruled out by decision D3): pre-compressed DDS BC1/BC3/BC5 with mips for "
                    "desktop, JPEG/PNG fallback; 2k trim sheets for buildings, 1k for props, 4-layer terrain splat 2k + detail normal",
        "vram": "<= 700 MB textures + geometry",
        "cpu": "physics (cannon-es) only for door leaves (kinematic), ragdolls (max 6 active), small props (max 20 awake); BVH raycasts for "
               "hits; AI perception staggered at 10 Hz per bot, <= 60 perception rays per frame, <= 4 path requests per frame",
        "culling": "interiors culled when the camera is outside and the room's openings are out of the frustum; 3 zone-interior groups",
    }


def qa_points(layout):
    """named positions for QA (testovací body): zones, spawns, doorways (both sides), stairs (bottom/top), chokepoints, boundary."""
    out = []

    def add(pid, kind, pos, note=""):
        out.append({"id": pid, "kind": kind, "pos": [r2(pos[0]), r2(pos[1]), r2(pos[2])], "note": note})
    for z in layout["capture_zones"]:
        c = z["center"]
        zc = float(T.height_at(layout, c[0], c[1])[0])
        add(f"QA_{z['id']}_center", "zone", [c[0], c[1], max(zc, z['z_min'] + 0.3)], "zone centre (stand here: counts)")
        P = np.array(z["polygon"])
        for k, v in enumerate(P):
            add(f"QA_{z['id']}_corner{k + 1}", "zone_edge", [v[0], v[1], float(T.height_at(layout, v[0], v[1])[0])],
                "polygon vertex: step 0.5 m inside -> counts, 0.5 m outside -> does not")
    for sa in layout["spawn_areas"]:
        for rw in sa["rows"]:
            c = rw["center"]
            add(f"QA_{rw['row_id']}", "spawn_row", [c[0], c[1], float(T.height_at(layout, c[0], c[1])[0])],
                "row centre; active for " + ", ".join(rw["zones"]))
        for p in sa["candidate_points"]:
            add(f"QA_{p['id']}", "spawn_point", p["pos"], f"yaw {p['yaw_deg']}")
    import ivcheck as C
    bj = IB.all_buildings()
    for bp in layout["buildings"]:
        bd = next(b for b in bj if b["id"] == bp["id"])
        wmap = {w["id"]: w for w in bd["walls"]}
        lv = {l["id"]: l for l in bd["levels"]}
        c0, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
        for o in bd["openings"]:
            if o["type"] not in ("door", "double_door") and not (o["type"] == "roller_door" and o["passes"]["movement"]):
                continue
            w = wmap[o["wall_id"]]
            gg = C.opening_geom(w, o)
            nx, ny = gg["n"]
            zl = zf + lv[w["level"]]["floor_z"]
            for side, sg in (("L", 1), ("R", -1)):
                d = w["thickness"] / 2 + 0.8
                q = R.xf(c0, rot, (gg["mid"][0] + sg * nx * d, gg["mid"][1] + sg * ny * d))
                add(f"QA_{o['id']}_{side}", "doorway", [q[0], q[1], zl], f"{bp['id']} {w['level']} clear {o['clear_width']} x "
                    f"{o.get('clear_height', '')} m; walk through, check leaf, frame and capsule clearance")
        # zone z-band test: a walkable upper-floor point that lies inside the zone polygon but above z_max (must NOT count)
        zid = bp.get("zone")
        if zid:
            zz = next(z_ for z_ in layout["capture_zones"] if z_["id"] == zid)
            zp = Polygon(zz["polygon"])
            for l_ in bd["levels"]:
                if l_["floor_z"] <= 0:
                    continue
                for r_ in sorted([r_ for r_ in bd["rooms"] if r_["level"] == l_["id"]], key=lambda r_: -Polygon(r_["polygon"]).area):
                    cpt = Polygon(r_["polygon"]).representative_point()
                    q = R.xf(c0, rot, (cpt.x, cpt.y))
                    if zp.contains(Point(q[0], q[1])):
                        add(f"QA_{zid}_above_{r_['id']}", "zone_z", [q[0], q[1], zf + l_["floor_z"]],
                            f"inside the zone polygon but on {l_['id']} (floor z {zf + l_['floor_z']:.2f} > z_max {zz['z_max']}): must NOT count")
                        break
        for sd in bd["stairs"] + bd["exterior_stairs"]:
            b0 = R.xf(c0, rot, (sd["start"][0] - sd["direction_vector"][0] * 0.8, sd["start"][1] - sd["direction_vector"][1] * 0.8))
            t0 = R.xf(c0, rot, (sd["top_riser_center"][0] + sd["direction_vector"][0] * 0.8,
                                sd["top_riser_center"][1] + sd["direction_vector"][1] * 0.8))
            add(f"QA_{sd['id']}_bottom", "stair", [b0[0], b0[1], zf + sd["z_start"]], f"{sd['count']} x {sd['riser']:.3f} / {sd['tread']}")
            add(f"QA_{sd['id']}_top", "stair", [t0[0], t0[1], zf + sd["z_end"]], "walk up and down, check headroom and foot IK")
    for rw in layout["retaining_walls"]:
        for st in rw.get("stairs", []):
            b0, t0 = st["bottom_center_world"], st["top_center_world"]
            add(f"QA_{st['id']}_bottom", "stair", [b0[0], b0[1], rw["bottom_z"]], f"{st['risers']} x {st['riser']:.3f} / {st['tread']}")
            add(f"QA_{st['id']}_top", "stair", [t0[0], t0[1], rw["top_z"] - (0.60 if rw.get("parapet") else 0.10)], "")
    for ck in layout["chokepoints"]:
        if "at" in ck and ck["type"] in ("bridge", "footbridge", "ramp", "gate", "yard gate", "field ramp"):
            a = ck["at"] if not isinstance(ck["at"][0], list) else [(ck["at"][0][0] + ck["at"][1][0]) / 2, (ck["at"][0][1] + ck["at"][1][1]) / 2]
            add(f"QA_{ck['id']}", "chokepoint", [a[0], a[1], float(T.height_at(layout, a[0], a[1])[0])], f"width {ck['width']} m")
    for st in layout["terrain"]["stamps"]:
        if st["kind"] == "sunken_lane":
            pl = st["polyline"]
            P = np.array([[p[0], p[1]] for p in pl])
            seg = np.hypot(*np.diff(P, axis=0).T)
            cs = np.concatenate([[0], np.cumsum(seg)])
            for ex in st["exits"]:
                sm = (ex["s0"] + ex["s1"]) / 2
                x = float(np.interp(sm, cs, P[:, 0]))
                y = float(np.interp(sm, cs, P[:, 1]))
                add(f"QA_{st['id']}_exit_{int(ex['s0'])}", "chokepoint", [x, y, float(T.height_at(layout, x, y)[0])],
                    f"sunken lane exit to {ex['side']}: walk out, must not need a jump")
    soft = layout["boundary"]["soft_polygon"]
    for k in range(0, len(soft), 4):
        v = soft[k]
        add(f"QA_BOUNDARY_{k:02d}", "boundary", [v[0], v[1], float(T.height_at(layout, v[0], v[1])[0])],
            "walk out: warning band text, then countdown; check the visible barrier")
    return out
