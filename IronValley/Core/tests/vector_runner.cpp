// Spoustec sdilenych testovacich vektoru Shared/testvectors/*.json nad C++ jadrem.
// Semantika je 1:1 shodna s Web/tests/unit/support/vector_runner.mjs (format: Shared/testvectors/README.md).
//
// Pouziti: ivcore_vectors --rules <rules.json> <soubor.json>...
//          ivcore_vectors --rules <rules.json> --malformed <malformed/cases.json>
//            (kazdy kontrolni pripad "good" musi projit a kazdy chybny "bad" skoncit chybou pripadu)
// Navratovy kod 0 = vsechny pripady PASS.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "ironvalley/core/core.hpp"
#include "ironvalley/core/rules_json.hpp"

using nlohmann::json;
using namespace iv::core;

namespace {

struct CaseError : std::runtime_error {
  using std::runtime_error::runtime_error;
};

json loadJson(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("nelze otevrit " + path);
  std::stringstream ss;
  ss << in.rdbuf();
  return json::parse(ss.str());
}

// ------------------------------------------------------------------ pomocne cteni hodnot (semantika JS)

bool isTrue(const json& step, const char* key) {
  auto it = step.find(key);
  return it != step.end() && it->is_boolean() && it->get<bool>();
}

/// Cele cislo z JSON; neceleciselna nebo chybejici hodnota -> fallback.
long long intOr(const json& v, long long fallback) {
  if (!v.is_number()) return fallback;
  const double d = v.get<double>();
  if (!(d == d) || d != static_cast<double>(static_cast<long long>(d))) return fallback;
  if (v.is_number_integer()) return v.get<long long>();
  return static_cast<long long>(d);
}

long long intField(const json& step, const char* key, long long fallback) {
  auto it = step.find(key);
  return it == step.end() ? fallback : intOr(*it, fallback);
}

Micros dtField(const json& step, const char* key) {
  auto it = step.find(key);
  if (it == step.end() || !it->is_number_integer() || it->get<long long>() < 0) {
    throw CaseError(std::string("neplatne ") + key);
  }
  return it->get<long long>();
}

std::string strField(const json& step, const char* key) {
  auto it = step.find(key);
  return it != step.end() && it->is_string() ? it->get<std::string>() : std::string();
}

// ------------------------------------------------------------------ tiky

std::vector<Micros> expandTicks(Micros durationUs, const json& mode, Rng* irregular) {
  if (durationUs < 0) throw CaseError("run: neplatne durationUs");
  std::vector<Micros> out;
  Micros prev = 0;
  if (mode.contains("hz")) {
    const long long hz = mode["hz"].get<long long>();
    if (hz < 1) throw CaseError("run: hz < 1");
    for (long long k = 1; prev < durationUs; ++k) {
      Micros t = (2 * k * 1000000 + hz) / (2 * hz);
      if (t > durationUs) t = durationUs;
      out.push_back(t - prev);
      prev = t;
    }
  } else if (mode.contains("dtUs")) {
    const long long dt = mode["dtUs"].get<long long>();
    if (dt < 1) throw CaseError("run: dtUs < 1");
    while (prev < durationUs) {
      const Micros t = std::min<Micros>(prev + dt, durationUs);
      out.push_back(t - prev);
      prev = t;
    }
  } else if (mode.contains("irregular")) {
    const long long minUs = mode["irregular"]["minUs"].get<long long>();
    const long long maxUs = mode["irregular"]["maxUs"].get<long long>();
    if (minUs < 0 || maxUs < 1 || maxUs < minUs || irregular == nullptr) throw CaseError("run: neplatne irregular");
    while (prev < durationUs) {
      const Micros dt = minUs + irregular->pickIndex(static_cast<std::uint32_t>(maxUs - minUs + 1));
      const Micros t = std::min<Micros>(prev + dt, durationUs);
      out.push_back(t - prev);
      prev = t;
    }
  } else {
    throw CaseError("run: neznamy rezim tiku " + mode.dump());
  }
  return out;
}

// ------------------------------------------------------------------ porovnani

bool numbersEqual(const json& a, const json& b) {
  if (a.is_number_integer() && b.is_number_integer()) return a.get<long long>() == b.get<long long>();
  return a.get<double>() == b.get<double>();
}

void exactMismatches(const json& e, const json& a, const std::string& where, std::vector<std::string>& out) {
  if (e.is_number() && a.is_number()) {
    if (!numbersEqual(e, a)) out.push_back(where + ": ocekavano " + e.dump() + ", je " + a.dump());
    return;
  }
  if (e.is_object() && a.is_object()) {
    std::set<std::string> ek, ak;
    for (auto it = e.begin(); it != e.end(); ++it) ek.insert(it.key());
    for (auto it = a.begin(); it != a.end(); ++it) ak.insert(it.key());
    if (ek != ak) {
      out.push_back(where + ": klice se lisi (ocekavano " + e.dump() + ", je " + a.dump() + ")");
      return;
    }
    for (const std::string& k : ek) exactMismatches(e[k], a[k], where + "." + k, out);
    return;
  }
  if (e.is_array() && a.is_array()) {
    if (e.size() != a.size()) {
      out.push_back(where + ": delka " + std::to_string(e.size()) + " != " + std::to_string(a.size()) + " (" + a.dump() + ")");
      return;
    }
    for (std::size_t i = 0; i < e.size(); ++i) exactMismatches(e[i], a[i], where + "[" + std::to_string(i) + "]", out);
    return;
  }
  if (e.type() != a.type() || e != a) out.push_back(where + ": ocekavano " + e.dump() + ", je " + a.dump());
}

void subsetMismatches(const json& e, const json& a, const std::string& where, std::vector<std::string>& out) {
  if (e.is_object()) {
    if (!a.is_object()) {
      out.push_back(where + ": ocekavan objekt, je " + a.dump());
      return;
    }
    for (auto it = e.begin(); it != e.end(); ++it) {
      auto f = a.find(it.key());
      subsetMismatches(it.value(), f == a.end() ? json() : *f, where + "." + it.key(), out);
    }
    return;
  }
  if (e.is_array()) {
    if (!a.is_array()) {
      out.push_back(where + ": ocekavano pole, je " + a.dump());
      return;
    }
    if (a.size() != e.size()) {
      out.push_back(where + ": delka " + std::to_string(e.size()) + " != " + std::to_string(a.size()) + " (" + a.dump() + ")");
      return;
    }
    for (std::size_t i = 0; i < e.size(); ++i) subsetMismatches(e[i], a[i], where + "[" + std::to_string(i) + "]", out);
    return;
  }
  exactMismatches(e, a, where, out);
}

/// FNV-1a 64 nad kanonickym JSON (serazene klice, bez mezer) = snapshotDigest() v JS.
std::string snapshotDigest(const json& snapshot) {
  const std::string text = snapshot.dump();
  std::uint64_t h = 0xcbf29ce484222325ull;
  for (unsigned char c : text) {
    h ^= c;
    h *= 0x100000001b3ull;
  }
  char buf[17];
  std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
  return buf;
}

struct StepOut {
  json result;
  json events = json::array();
  json snapshot;
};

std::vector<std::string> checkExpect(const json& expect, const StepOut& out) {
  std::vector<std::string> p;
  if (expect.is_null()) return p;
  if (expect.contains("result")) exactMismatches(expect["result"], out.result, "result", p);
  if (expect.contains("events")) exactMismatches(expect["events"], out.events, "events", p);
  if (expect.contains("eventCounts")) {
    std::map<std::string, long long> counts;
    for (const json& ev : out.events) counts[ev["type"].get<std::string>()] += 1;
    for (auto it = expect["eventCounts"].begin(); it != expect["eventCounts"].end(); ++it) {
      const long long want = it.value().get<long long>();
      const long long have = counts.count(it.key()) ? counts[it.key()] : 0;
      if (want != have) p.push_back("eventCounts." + it.key() + ": ocekavano " + std::to_string(want) + ", je " + std::to_string(have));
    }
  }
  if (expect.contains("snapshot")) exactMismatches(expect["snapshot"], out.snapshot, "snapshot", p);
  if (expect.contains("snapshotDigest")) {
    const std::string d = snapshotDigest(out.snapshot);
    if (d != expect["snapshotDigest"].get<std::string>()) {
      p.push_back("snapshotDigest: ocekavano " + expect["snapshotDigest"].get<std::string>() + ", je " + d + " (" + out.snapshot.dump() + ")");
    }
  }
  json subset = json::object();
  for (auto it = expect.begin(); it != expect.end(); ++it) {
    const std::string& k = it.key();
    if (k == "result" || k == "events" || k == "eventCounts" || k == "snapshot" || k == "snapshotDigest") continue;
    subset[k] = it.value();
  }
  subsetMismatches(subset, out.snapshot, "snapshot", p);
  return p;
}

// ------------------------------------------------------------------ snimky stavu (stejne klice jako JS)

json weaponSnapshot(const WeaponState& w) {
  return json{{"weapon", w.def().id},
              {"state", toString(w.activity())},
              {"reloadKind", toString(w.reloadKind())},
              {"actionUs", w.actionUs()},
              {"insertCommitted", w.insertCommitted()},
              {"boltReleased", w.boltReleased()},
              {"chamberCommitted", w.chamberCommitted()},
              {"magazine", w.magazine()},
              {"chamber", w.chamber()},
              {"reserve", w.reserve()},
              {"fireMode", toString(w.fireMode())},
              {"cooldownUs", w.cooldownUs()},
              {"clockUs", w.clockUs()},
              {"triggerPrev", w.triggerPrev()},
              {"holdValid", w.holdValid()},
              {"enabled", w.enabled()},
              {"disabledBy", w.disabledByNames()},
              {"shotsFired", w.shotsFired()},
              {"resupplied", w.resupplied()},
              {"dryFires", w.dryFires()},
              {"reloadsStarted", w.reloadsStarted()},
              {"reloadsCompleted", w.reloadsCompleted()},
              {"reloadsInterrupted", w.reloadsInterrupted()},
              {"chamberActions", w.chamberActions()},
              {"initialTotal", w.initialTotal()}};
}

json weaponEvents(std::vector<WeaponEvent> events) {
  json out = json::array();
  for (const WeaponEvent& e : events) out.push_back(json{{"type", toString(e.type)}, {"atUs", e.atUs}, {"detail", e.detail}});
  return out;
}

json respawnEvents(std::vector<RespawnEvent> events) {
  json out = json::array();
  for (const RespawnEvent& e : events) out.push_back(json{{"type", e.type}, {"id", e.id}, {"point", e.point}});
  return out;
}

json zoneSnapshot(const ZoneScoring& z) {
  return json{{"status", toString(z.status())},
              {"controller", z.controller()},
              {"counts", z.counts()},
              {"progressUs", z.progressUs()},
              {"scores", z.scores()}};
}

json roundSnapshot(const Round& r) {
  json z = zoneSnapshot(r.zone());
  return json{{"state", toString(r.state())},
              {"roundNumber", r.roundNumber()},
              {"zoneIndex", r.zoneIndex()},
              {"zoneId", r.zoneId()},
              {"preRoundRemainingUs", r.preRoundRemainingUs()},
              {"elapsedUs", r.elapsedUs()},
              {"remainingUs", r.remainingUs()},
              {"winner", r.winner()},
              {"draw", r.draw()},
              {"endReason", toString(r.endReason())},
              {"status", z["status"]},
              {"controller", z["controller"]},
              {"counts", z["counts"]},
              {"progressUs", z["progressUs"]},
              {"scores", z["scores"]}};
}

json respawnSnapshot(const RespawnSystem& rs) {
  json order = json::array();
  json participants = json::object();
  for (const Participant& p : rs.participants()) {
    order.push_back(p.id);
    json weapons = json::object();
    json equipped = json::array();
    for (const auto& entry : p.weapons) {
      weapons[entry.first] = weaponSnapshot(*entry.second);
      equipped.push_back(entry.first);
    }
    json inputLocks = json::array();  // pevne poradi jako JS DISABLE_REASONS
    for (DisableReason r : {DisableReason::Sprint, DisableReason::Switch, DisableReason::Menu, DisableReason::Results,
                            DisableReason::Other}) {
      if (std::find(p.inputLocks.begin(), p.inputLocks.end(), r) != p.inputLocks.end()) inputLocks.push_back(toString(r));
    }
    participants[p.id] = json{{"team", p.team},
                              {"state", toString(p.state)},
                              {"health", p.health},
                              {"respawnInUs", p.respawnInUs},
                              {"retryInUs", p.retryInUs},
                              {"spawnPoint", p.spawnPoint},
                              {"spawnCount", p.spawnCount},
                              {"deaths", p.deaths},
                              {"failedSpawnAttempts", p.failedSpawnAttempts},
                              {"loadout", p.loadout},
                              {"equipped", equipped},
                              {"inputLocks", inputLocks},
                              {"weapons", weapons}};
  }
  return json{{"order", order}, {"participants", participants}, {"reservedUs", rs.reservedUs()}};
}

// ------------------------------------------------------------------ kontrola tvaru vektoru
// Stejna pravidla jako validateCaseShape / validateStep ve Web/tests/unit/support/vector_runner.mjs: neznamy nebo
// spatne umisteny klic (preklep "expcet", "expect" uvnitr "do"/"loop", "trigger": "true") je chyba pripadu,
// ne tichy PASS.

using KeyList = std::vector<std::string>;
using OpTable = std::map<std::string, KeyList>;

const std::set<std::string>& fileKeys() {
  static const std::set<std::string> k{"schema", "version", "suite", "description", "cases", "generated", "generator", "masterSeed"};
  return k;
}

const std::map<std::string, KeyList>& setupKeys() {
  static const std::map<std::string, KeyList> k{{"weapon", {"weapon", "magazine", "chamber", "reserve", "fireMode"}},
                                                {"zone", {}},
                                                {"round", {"seed"}},
                                                {"respawn", {"seed", "spawnAreas", "participants"}},
                                                {"match", {"seed", "spawnAreas", "participants"}},
                                                {"rng", {"seed"}},
                                                {"rules", {}}};
  return k;
}

const OpTable& opTable(const std::string& kind) {
  static const OpTable weapon{{"tick", {"dtUs", "trigger", "repeat"}},
                              {"run", {"durationUs", "trigger", "ticks"}},
                              {"reload", {}},
                              {"interrupt", {"reason"}},
                              {"disable", {"reason"}},
                              {"enable", {"reason"}},
                              {"setFireMode", {"mode"}},
                              {"resupply", {"rounds"}},
                              {"resetToLoadout", {}}};
  static const OpTable zone{{"tick", {"dtUs", "participants", "repeat"}}, {"run", {"durationUs", "ticks", "participants"}}, {"reset", {}}};
  static const OpTable round{{"tick", {"dtUs", "participants", "repeat"}},
                             {"run", {"durationUs", "ticks", "participants"}},
                             {"reset", {}},
                             {"start", {}}};
  static const OpTable life{{"add", {"id", "team", "loadout"}},
                            {"kill", {"id"}},
                            {"damage", {"id", "amount", "attacker"}},
                            {"setLoadout", {"id", "loadout"}},
                            {"weapon", {"id", "weapon", "do"}},
                            {"weaponEvents", {"id", "weapon"}},
                            {"disableInput", {"id", "reason"}},
                            {"enableInput", {"id", "reason"}}};
  static const OpTable respawn = [] {
    OpTable t = life;
    t["tick"] = {"dtUs", "repeat", "bodies", "blocked"};
    t["run"] = {"durationUs", "ticks", "bodies", "blocked"};
    t["resetRound"] = {};
    return t;
  }();
  static const OpTable match = [] {
    OpTable t = life;
    t["tick"] = {"dtUs", "repeat", "bodies", "blocked", "inZone", "inactive"};
    t["run"] = {"durationUs", "ticks", "bodies", "blocked", "inZone", "inactive"};
    t["reset"] = {};
    t["start"] = {};
    return t;
  }();
  static const OpTable rules{{"compile", {"overrides"}}};
  static const OpTable rng{{"next", {"count"}}, {"pick", {"n", "count"}}, {"shuffle", {"n"}}};
  static const OpTable none;
  if (kind == "weapon") return weapon;
  if (kind == "zone") return zone;
  if (kind == "round") return round;
  if (kind == "respawn") return respawn;
  if (kind == "match") return match;
  if (kind == "rules") return rules;
  if (kind == "rng") return rng;
  return none;
}

/// Cele cislo ve smyslu JS Number.isInteger (i 30.0).
bool isIntegral(const json& v) {
  if (v.is_number_integer()) return true;
  if (!v.is_number_float()) return false;
  const double d = v.get<double>();
  return std::isfinite(d) && d == std::floor(d);
}

void checkKeys(const json& obj, const std::set<std::string>& allowed, const std::string& where) {
  for (auto it = obj.begin(); it != obj.end(); ++it)
    if (allowed.count(it.key()) == 0) throw CaseError(where + ": neznamy klic \"" + it.key() + "\"");
}

void checkTickMode(const json& mode, const std::string& where) {
  if (!mode.is_object()) throw CaseError(where + ": rezim tiku musi byt objekt");
  if (mode.size() != 1 || !(mode.contains("hz") || mode.contains("dtUs") || mode.contains("irregular"))) {
    throw CaseError(where + ": rezim tiku musi mit prave jeden klic hz | dtUs | irregular, je " + mode.dump());
  }
  if (mode.contains("irregular")) {
    if (!mode["irregular"].is_object()) throw CaseError(where + ": irregular musi byt objekt");
    checkKeys(mode["irregular"], {"seed", "minUs", "maxUs"}, where + ".irregular");
  }
}

void checkZoneParticipant(const json& p, const std::string& where) {
  if (p.is_array()) {
    if (p.size() != 5 || !p[0].is_string() || !isIntegral(p[1]) || !p[2].is_boolean() || !p[3].is_boolean() || !p[4].is_boolean()) {
      throw CaseError(where + ": ucastnik musi byt [id, tym, alive, active, inZone] (text, cele cislo, 3x bool), je " + p.dump());
    }
    return;
  }
  if (!p.is_object()) throw CaseError(where + ": ucastnik musi byt pole nebo objekt");
  checkKeys(p, {"id", "team", "alive", "active", "inZone"}, where);
  auto boolAt = [&p](const char* k) { return p.contains(k) && p[k].is_boolean(); };
  if (!p.contains("id") || !p["id"].is_string() || !p.contains("team") || !isIntegral(p["team"]) || !boolAt("alive") ||
      !boolAt("active") || !boolAt("inZone")) {
    throw CaseError(where + ": ucastnik ma spatne typy " + p.dump());
  }
}

void validateCaseShape(const json& testCase) {
  if (!testCase.is_object()) throw CaseError("pripad musi byt objekt");
  const std::string where = "pripad " + (testCase.contains("id") && testCase["id"].is_string() ? testCase["id"].get<std::string>() : "?");
  checkKeys(testCase, {"id", "kind", "description", "rules", "setup", "tickModes", "steps"}, where);
  if (!testCase.contains("id") || !testCase["id"].is_string() || testCase["id"].get<std::string>().empty()) {
    throw CaseError(where + ": chybi id");
  }
  const std::string kind = testCase.contains("kind") && testCase["kind"].is_string() ? testCase["kind"].get<std::string>() : "";
  auto sk = setupKeys().find(kind);
  if (sk == setupKeys().end()) throw CaseError(where + ": neznamy druh \"" + kind + "\"");
  if (!testCase.contains("steps") || !testCase["steps"].is_array()) throw CaseError(where + ": steps musi byt pole");
  if (testCase.contains("rules") && !testCase["rules"].is_object()) throw CaseError(where + ": rules musi byt objekt");
  if (testCase.contains("setup")) {
    const json& setup = testCase["setup"];
    if (!setup.is_object()) throw CaseError(where + ": setup musi byt objekt");
    checkKeys(setup, std::set<std::string>(sk->second.begin(), sk->second.end()), where + ".setup");
    if (setup.contains("participants")) {
      if (!setup["participants"].is_array()) throw CaseError(where + ".setup.participants musi byt pole");
      for (std::size_t i = 0; i < setup["participants"].size(); ++i) {
        const json& p = setup["participants"][i];
        const std::string w = where + ".setup.participants[" + std::to_string(i) + "]";
        if (!p.is_object()) throw CaseError(w + ": ocekavan objekt");
        checkKeys(p, {"id", "team", "loadout"}, w);
      }
    }
  }
  if (testCase.contains("tickModes")) {
    const json& modes = testCase["tickModes"];
    if (!modes.is_array() || modes.empty()) throw CaseError(where + ": tickModes musi byt neprazdne pole");
    for (std::size_t i = 0; i < modes.size(); ++i) checkTickMode(modes[i], where + ".tickModes[" + std::to_string(i) + "]");
  }
}

void validateStep(const std::string& kind, const json& step, const std::string& where, bool nested) {
  if (!step.is_object()) throw CaseError(where + ": krok musi byt objekt");
  if (!step.contains("op") || !step["op"].is_string()) throw CaseError(where + ": chybi op");
  const std::string op = step["op"].get<std::string>();
  const OpTable& table = opTable(kind);
  std::set<std::string> keys{"op"};
  if (op == "loop") {
    keys.insert({"count", "steps"});
  } else {
    auto it = table.find(op);
    if (it == table.end()) throw CaseError(where + ": neznama operace \"" + op + "\" pro " + kind);
    keys.insert(it->second.begin(), it->second.end());
  }
  if (!nested) keys.insert("expect");
  for (auto it = step.begin(); it != step.end(); ++it) {
    if (keys.count(it.key()) != 0) continue;
    if (it.key() == "expect") throw CaseError(where + ": \"expect\" uvnitr vnoreneho kroku (loop/do) se nekontroluje - patri do vnejsiho kroku");
    throw CaseError(where + ": neznamy klic \"" + it.key() + "\" v operaci " + op);
  }
  if (step.contains("expect") && !step["expect"].is_object()) throw CaseError(where + ": expect musi byt objekt");
  if (step.contains("trigger") && !step["trigger"].is_boolean()) throw CaseError(where + ": trigger musi byt true/false, je " + step["trigger"].dump());
  if (step.contains("repeat") && !(isIntegral(step["repeat"]) && step["repeat"].get<double>() >= 0)) {
    throw CaseError(where + ": repeat musi byt cele >= 0");
  }
  if (step.contains("ticks") && !(step["ticks"].is_string() && step["ticks"].get<std::string>() == "case")) {
    checkTickMode(step["ticks"], where + ".ticks");
  }
  if (step.contains("participants")) {
    if (!step["participants"].is_array()) throw CaseError(where + ": participants musi byt pole");
    for (std::size_t i = 0; i < step["participants"].size(); ++i) {
      checkZoneParticipant(step["participants"][i], where + ".participants[" + std::to_string(i) + "]");
    }
  }
  if (step.contains("bodies")) {
    if (!step["bodies"].is_array()) throw CaseError(where + ": bodies musi byt pole");
    for (std::size_t i = 0; i < step["bodies"].size(); ++i) {
      const json& b = step["bodies"][i];
      const std::string w = where + ".bodies[" + std::to_string(i) + "]";
      if (!b.is_object()) throw CaseError(w + ": ocekavan objekt");
      checkKeys(b, {"team", "alive", "pos"}, w);
      bool posOk = b.contains("pos") && b["pos"].is_array() && b["pos"].size() == 3;
      if (posOk)
        for (const json& x : b["pos"]) posOk = posOk && x.is_number();
      if (!b.contains("team") || !isIntegral(b["team"]) || !b.contains("alive") || !b["alive"].is_boolean() || !posOk) {
        throw CaseError(w + ": {team: cele, alive: bool, pos: [x,y,z]}, je " + b.dump());
      }
    }
  }
  if (step.contains("blocked")) {
    if (!step["blocked"].is_object()) throw CaseError(where + ": blocked musi byt objekt {tym: [indexy]}");
    for (auto it = step["blocked"].begin(); it != step["blocked"].end(); ++it) {
      bool ok = it.value().is_array();
      if (ok)
        for (const json& x : it.value()) ok = ok && isIntegral(x);
      if (!ok) throw CaseError(where + ": blocked." + it.key() + " musi byt pole celych cisel");
    }
  }
  for (const char* key : {"inZone", "inactive"}) {
    if (!step.contains(key)) continue;
    bool ok = step[key].is_array();
    if (ok)
      for (const json& x : step[key]) ok = ok && x.is_string();
    if (!ok) throw CaseError(where + ": " + key + " musi byt pole id");
  }
  if (op == "loop") {
    if (!step.contains("count") || !isIntegral(step["count"]) || step["count"].get<double>() < 0 || !step.contains("steps") ||
        !step["steps"].is_array()) {
      throw CaseError(where + ": loop {count: cele >= 0, steps: []}");
    }
    for (std::size_t i = 0; i < step["steps"].size(); ++i) {
      validateStep(kind, step["steps"][i], where + ".steps[" + std::to_string(i) + "]", true);
    }
  }
  if (op == "weapon" && (kind == "respawn" || kind == "match")) {
    const json& d = step.contains("do") ? step["do"] : json();
    if (!d.is_object() || (d.contains("op") && d["op"] == "loop")) throw CaseError(where + ": do musi byt jeden krok zbrane");
    validateStep("weapon", d, where + ".do", true);
  }
}

// ------------------------------------------------------------------ session

std::vector<ZoneParticipant> parseParticipants(const json& list) {
  std::vector<ZoneParticipant> out;
  if (!list.is_array()) return out;
  for (const json& p : list) {
    ZoneParticipant z;
    auto boolAt = [](const json& v) { return v.is_boolean() && v.get<bool>(); };
    if (p.is_array()) {
      z.id = p.size() > 0 && p[0].is_string() ? p[0].get<std::string>() : std::string();
      z.team = p.size() > 1 ? static_cast<int>(intOr(p[1], -1)) : -1;
      z.alive = p.size() > 2 && boolAt(p[2]);
      z.active = p.size() > 3 && boolAt(p[3]);
      z.inZone = p.size() > 4 && boolAt(p[4]);
    } else {
      z.id = strField(p, "id");
      z.team = static_cast<int>(intField(p, "team", -1));
      z.alive = isTrue(p, "alive");
      z.active = isTrue(p, "active");
      z.inZone = isTrue(p, "inZone");
    }
    out.push_back(z);
  }
  return out;
}

Vec3 parseVec3(const json& v) {
  if (!v.is_array() || v.size() != 3) throw CaseError("ocekavan bod [x,y,z]");
  return Vec3{v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
}

std::vector<std::vector<Vec3>> parseAreas(const json& v) {
  std::vector<std::vector<Vec3>> out;
  if (!v.is_array()) throw CaseError("spawnAreas");
  for (const json& area : v) {
    std::vector<Vec3> pts;
    for (const json& p : area) pts.push_back(parseVec3(p));
    out.push_back(pts);
  }
  return out;
}

std::optional<std::vector<std::string>> parseLoadout(const json& step) {
  auto it = step.find("loadout");
  if (it == step.end() || it->is_null()) return std::nullopt;
  std::vector<std::string> out;
  if (!it->is_array()) return std::vector<std::string>{std::string("\x01")};  // JS: neni pole -> neplatny loadout
  for (const json& w : *it) out.push_back(w.is_string() ? w.get<std::string>() : std::string("\x01"));
  return out;
}

class Session {
 public:
  Session(const json& testCase, const json& baseRaw, const json& mode) : mode_(mode) {
    validateCaseShape(testCase);
    kind_ = testCase.at("kind").get<std::string>();
    caseRaw_ = mergePatch(baseRaw, testCase.value("rules", json::object()));
    const json setup = testCase.value("setup", json::object());
    if (kind_ != "rules") {
      std::vector<std::string> errors;
      if (!rulesFromJson(caseRaw_, rules_, errors)) throw CaseError("neplatna pravidla pripadu: " + errors.front());
    }
    if (kind_ == "weapon") {
      const WeaponDef* def = rules_.findWeapon(setup.at("weapon").get<std::string>());
      if (def == nullptr) throw CaseError("neznama zbran");
      weapon_ = std::make_unique<WeaponState>(*def);
      if (setup.contains("magazine") || setup.contains("chamber") || setup.contains("reserve")) {
        const int mag = static_cast<int>(intField(setup, "magazine", weapon_->magazine()));
        const int ch = static_cast<int>(intField(setup, "chamber", weapon_->chamber()));
        const int res = static_cast<int>(intField(setup, "reserve", weapon_->reserve()));
        if (!weapon_->setAmmo(mag, ch, res)) throw CaseError("setup: neplatny stav munice");
      }
      if (setup.contains("fireMode")) {
        FireMode fm;
        if (!parseFireMode(setup["fireMode"].get<std::string>(), fm) || !weapon_->setFireMode(fm)) throw CaseError("setup: fireMode");
      }
    } else if (kind_ == "zone") {
      zone_ = std::make_unique<ZoneScoring>(rules_);
    } else if (kind_ == "round") {
      round_ = std::make_unique<Round>(rules_, static_cast<std::uint32_t>(intField(setup, "seed", 1)));
    } else if (kind_ == "respawn" || kind_ == "match") {
      const auto seed = static_cast<std::uint32_t>(intField(setup, "seed", 1));
      if (kind_ == "respawn") {
        respawn_ = std::make_unique<RespawnSystem>(rules_, seed, parseAreas(setup.at("spawnAreas")));
        if (!respawn_->configError().empty()) throw CaseError(respawn_->configError());
      } else {
        match_ = std::make_unique<Match>(rules_, seed, parseAreas(setup.at("spawnAreas")));
        if (!match_->respawn().configError().empty()) throw CaseError(match_->respawn().configError());
      }
      for (const json& p : setup.value("participants", json::array())) {
        auto lo = parseLoadout(p);
        const AddResult r = respawnSys().addParticipant(p.at("id").get<std::string>(), static_cast<int>(intField(p, "team", -1)),
                                                        lo ? &*lo : nullptr);
        if (r != AddResult::Ok) throw CaseError("setup: pridani selhalo");
      }
    } else if (kind_ == "rng") {
      rng_ = std::make_unique<Rng>(static_cast<std::uint32_t>(intField(setup, "seed", 0)));
    } else if (kind_ != "rules") {
      throw CaseError("neznamy druh " + kind_);
    }
  }

  StepOut step(const json& s, std::vector<std::string>& problems) {
    validateStep(kind_, s, "krok " + (s.is_object() && s.contains("op") ? s["op"].dump() : std::string("?")), false);
    StepOut out = doStep(s, problems);
    out.snapshot = snapshot();
    return out;
  }

 private:
  RespawnSystem& respawnSys() { return kind_ == "respawn" ? *respawn_ : match_->respawn(); }

  json snapshot() {
    if (kind_ == "weapon") return weaponSnapshot(*weapon_);
    if (kind_ == "zone") return zoneSnapshot(*zone_);
    if (kind_ == "round") return roundSnapshot(*round_);
    if (kind_ == "respawn") return respawnSnapshot(*respawn_);
    if (kind_ == "match") return json{{"round", roundSnapshot(match_->round())}, {"respawn", respawnSnapshot(match_->respawn())}};
    if (kind_ == "rng") return json{{"state", rng_->state()}};
    return lastCompiled_;
  }

  Rng* irregularRng(const json& mode) {
    if (!mode.is_object() || !mode.contains("irregular")) return nullptr;
    const std::string key = mode.dump();
    auto it = irregular_.find(key);
    if (it == irregular_.end()) {
      it = irregular_.emplace(key, Rng(static_cast<std::uint32_t>(mode["irregular"]["seed"].get<long long>()))).first;
    }
    return &it->second;
  }

  std::vector<Micros> tickList(const json& s) {
    std::vector<Micros> dts;
    const std::string op = s.at("op").get<std::string>();
    if (op == "tick") {
      const long long reps = intField(s, "repeat", 1);
      const Micros dt = dtField(s, "dtUs");
      for (long long i = 0; i < reps; ++i) dts.push_back(dt);
    } else {
      const json& ticks = s.at("ticks");
      const json mode = ticks.is_string() && ticks.get<std::string>() == "case" ? mode_ : ticks;
      if (!mode.is_object()) throw CaseError("run: \"ticks\":\"case\" bez tickModes");
      dts = expandTicks(dtField(s, "durationUs"), mode, irregularRng(mode));
    }
    return dts;
  }

  static void weaponInvariant(std::vector<std::string>& problems, const std::string& label, const WeaponState& w) {
    for (const std::string& v : w.invariantViolations()) problems.push_back(label + ": invariant: " + v);
  }

  void allWeaponsInvariant(std::vector<std::string>& problems) {
    // Vsechny zbrane, ktere ucastnik kdy dostal (i ty mimo aktualni vybavu).
    for (const Participant& p : respawnSys().participants())
      for (const auto& e : p.armory) weaponInvariant(problems, "po kroku " + p.id + "/" + e.first, *e.second);
  }

  json weaponStep(WeaponState& w, const json& s, std::vector<std::string>& problems, const std::string& label) {
    const std::string op = s.at("op").get<std::string>();
    if (op == "tick" || op == "run") {
      long long shots = 0;
      const bool trigger = isTrue(s, "trigger");
      for (Micros dt : tickList(s)) {
        shots += w.update(dt, trigger);
        weaponInvariant(problems, label, w);
      }
      return shots;
    }
    if (op == "reload") return toString(w.reload());
    if (op == "interrupt") {
      InterruptReason reason;
      if (!parseInterruptReason(strField(s, "reason"), reason)) return "invalid_reason";
      return toString(w.interrupt(reason));
    }
    if (op == "disable" || op == "enable") {
      DisableReason reason;
      if (!parseDisableReason(strField(s, "reason"), reason)) return "invalid_reason";
      if (op == "disable") w.disable(reason);
      else w.enable(reason);
      return "ok";
    }
    if (op == "setFireMode") {
      FireMode fm;
      if (!parseFireMode(strField(s, "mode"), fm)) return "rejected";
      return w.setFireMode(fm) ? "ok" : "rejected";
    }
    if (op == "resupply") return w.resupply(intField(s, "rounds", -1));
    if (op == "resetToLoadout") {
      w.resetToLoadout();
      return "ok";
    }
    throw CaseError("neznama operace zbrane " + op);
  }

  SpawnPredicate makePredicate() {
    const json blocked = world_.value("blocked", json::object());
    std::vector<Body> bodies;
    for (const json& b : world_.value("bodies", json::array())) {
      bodies.push_back(Body{static_cast<int>(intField(b, "team", -1)), isTrue(b, "alive"), parseVec3(b.at("pos"))});
    }
    const RespawnRules rr = rules_.respawn;
    return [blocked, bodies, rr](const SpawnQuery& q) {
      const std::string key = std::to_string(q.team);
      if (blocked.contains(key)) {
        for (const json& idx : blocked[key])
          if (idx.is_number_integer() && idx.get<long long>() == q.candidateIndex) return false;
      }
      return spawnPointSafe(q.point, q.team, bodies, rr);
    };
  }

  static std::set<std::string> idSet(const json& v) {
    std::set<std::string> out;
    if (v.is_array())
      for (const json& id : v)
        if (id.is_string()) out.insert(id.get<std::string>());
    return out;
  }

  StepOut doStep(const json& s, std::vector<std::string>& problems) {
    StepOut out;
    const std::string op = s.at("op").get<std::string>();
    if (op == "loop") {
      const long long count = intField(s, "count", 0);
      for (long long i = 0; i < count; ++i) {
        for (const json& inner : s.at("steps")) {
          StepOut o = doStep(inner, problems);
          for (const json& e : o.events) out.events.push_back(e);
        }
      }
      out.result = "ok";
      return out;
    }
    if (kind_ == "weapon") {
      out.result = weaponStep(*weapon_, s, problems, "weapon");
      out.events = weaponEvents(weapon_->takeEvents());
      return out;
    }
    if (kind_ == "zone" || kind_ == "round") {
      if (op == "tick" || op == "run") {
        if (s.contains("participants")) world_["participants"] = s["participants"];
        const std::vector<ZoneParticipant> parts = parseParticipants(world_.value("participants", json::array()));
        InputResult result = InputResult::Ok;
        for (Micros dt : tickList(s)) {
          const InputResult r = kind_ == "zone" ? zone_->tick(dt, parts) : round_->tick(dt, parts);
          if (r != InputResult::Ok && result == InputResult::Ok) result = r;
        }
        out.result = toString(result);
        return out;
      }
      if (op == "reset") {
        if (kind_ == "zone") zone_->reset();
        else round_->reset();
        out.result = "ok";
        return out;
      }
      if (kind_ == "round" && op == "start") {
        out.result = round_->start() ? "ok" : "rejected";
        return out;
      }
      throw CaseError("neznama operace " + op + " pro " + kind_);
    }
    if (kind_ == "respawn" || kind_ == "match") {
      RespawnSystem& rs = respawnSys();
      std::optional<json> events;
      if (op == "add") {
        auto lo = parseLoadout(s);
        out.result = toString(rs.addParticipant(strField(s, "id"), static_cast<int>(intField(s, "team", -1)), lo ? &*lo : nullptr));
      } else if (op == "kill") {
        out.result = toString(kind_ == "respawn" ? respawn_->kill(strField(s, "id")) : match_->kill(strField(s, "id")));
      } else if (op == "damage") {
        const long long amount = intField(s, "amount", 0);
        std::string attacker;
        const std::string* attackerPtr = nullptr;
        if (s.contains("attacker") && !s["attacker"].is_null()) {
          attacker = strField(s, "attacker");
          attackerPtr = &attacker;
        }
        const std::string victim = strField(s, "id");
        const DamageResult r = kind_ == "respawn" ? respawn_->applyDamage(victim, amount, attackerPtr)
                                                  : match_->applyDamage(victim, amount, attackerPtr);
        out.result = json{{"result", toString(r.code)}, {"applied", r.applied}};
      } else if (op == "setLoadout") {
        auto lo = parseLoadout(s);
        out.result = toString(rs.setLoadout(strField(s, "id"), lo ? *lo : std::vector<std::string>{}));
      } else if (op == "tick" || op == "run") {
        for (const char* key : {"bodies", "blocked", "inZone", "inactive"})
          if (s.contains(key)) world_[key] = s[key];
        const SpawnPredicate predicate = makePredicate();
        InputResult result = InputResult::Ok;
        MatchWorld mw;
        if (kind_ == "match") {
          mw.inZone = idSet(world_.value("inZone", json::array()));
          mw.inactive = idSet(world_.value("inactive", json::array()));
          mw.predicate = predicate;
        }
        for (Micros dt : tickList(s)) {
          if (kind_ == "respawn") {
            respawn_->update(dt, predicate);
          } else {
            const InputResult r = match_->update(dt, mw);
            if (r != InputResult::Ok && result == InputResult::Ok) result = r;
          }
        }
        out.result = toString(result);
      } else if (op == "resetRound" && kind_ == "respawn") {
        respawn_->resetRound();
        out.result = "ok";
      } else if (op == "reset" && kind_ == "match") {
        match_->reset();
        out.result = "ok";
      } else if (op == "start" && kind_ == "match") {
        out.result = match_->start() ? "ok" : "rejected";
      } else if (op == "weapon") {
        const std::string id = strField(s, "id");
        const std::string wid = strField(s, "weapon");
        WeaponState* w = rs.weapon(id, wid);
        if (w == nullptr) throw CaseError("zbran " + id + "/" + wid + " neexistuje");
        w->takeEvents();
        out.result = weaponStep(*w, s.at("do"), problems, id + "/" + wid);
        events = weaponEvents(w->takeEvents());
      } else if (op == "weaponEvents") {
        // Udalosti nashromazdene od posledniho kroku "weapon" (napr. preruseni pri resetu nebo smrti).
        const std::string id = strField(s, "id");
        const std::string wid = strField(s, "weapon");
        WeaponState* w = rs.weapon(id, wid);
        if (w == nullptr) throw CaseError("zbran " + id + "/" + wid + " neexistuje");
        out.result = "ok";
        events = weaponEvents(w->takeEvents());
      } else if (op == "disableInput" || op == "enableInput") {
        const std::string id = strField(s, "id");
        DisableReason reason;
        if (rs.participant(id) == nullptr) {
          out.result = "unknown_id";
        } else if (!parseDisableReason(strField(s, "reason"), reason)) {
          out.result = "invalid_reason";
        } else if (kind_ == "respawn") {
          out.result = toString(op == "disableInput" ? respawn_->disableInput(id, reason) : respawn_->enableInput(id, reason));
        } else {
          out.result = toString(op == "disableInput" ? match_->disableInput(id, reason) : match_->enableInput(id, reason));
        }
      } else {
        throw CaseError("neznama operace " + op + " pro " + kind_);
      }
      const json sysEvents = respawnEvents(rs.takeEvents());
      allWeaponsInvariant(problems);
      out.events = events ? *events : sysEvents;
      return out;
    }
    if (kind_ == "rng") {
      json arr = json::array();
      if (op == "next") {
        for (long long i = 0; i < intField(s, "count", 0); ++i) arr.push_back(rng_->nextU32());
      } else if (op == "pick") {
        const auto n = static_cast<std::uint32_t>(intField(s, "n", 1));
        for (long long i = 0; i < intField(s, "count", 0); ++i) arr.push_back(rng_->pickIndex(n));
      } else if (op == "shuffle") {
        for (int v : rng_->shuffledIndices(static_cast<int>(intField(s, "n", 0)))) arr.push_back(v);
      } else {
        throw CaseError("neznama operace " + op + " pro rng");
      }
      out.result = arr;
      return out;
    }
    if (kind_ == "rules") {
      if (op != "compile") throw CaseError("neznama operace " + op + " pro rules");
      const json raw = mergePatch(caseRaw_, s.value("overrides", json::object()));
      Rules compiled;
      std::vector<std::string> errors;
      if (rulesFromJson(raw, compiled, errors)) {
        lastCompiled_ = rulesToJson(compiled);
        out.result = "valid";
      } else {
        lastCompiled_ = json::object();
        out.result = "invalid";
      }
      return out;
    }
    throw CaseError("neznamy druh " + kind_);
  }

  std::string kind_;
  json mode_;
  json caseRaw_;
  Rules rules_;
  json world_ = json::object();
  json lastCompiled_ = json::object();
  std::map<std::string, Rng> irregular_;
  std::unique_ptr<WeaponState> weapon_;
  std::unique_ptr<ZoneScoring> zone_;
  std::unique_ptr<Round> round_;
  std::unique_ptr<RespawnSystem> respawn_;
  std::unique_ptr<Match> match_;
  std::unique_ptr<Rng> rng_;
};

std::vector<std::string> checkCase(const json& testCase, const json& baseRaw, long long& stepsChecked) {
  std::vector<std::string> failures;
  json modes = testCase.contains("tickModes") ? testCase["tickModes"] : json::array({json()});
  for (const json& mode : modes) {
    const std::string label = mode.is_null() ? "" : " [ticks " + mode.dump() + "]";
    try {
      Session session(testCase, baseRaw, mode);
      const json& steps = testCase.at("steps");
      for (std::size_t i = 0; i < steps.size(); ++i) {
        const json& step = steps[i];
        std::vector<std::string> problems;
        const StepOut out = session.step(step, problems);
        const std::string where = "krok " + std::to_string(i) + " (" + step.at("op").get<std::string>() + ")" + label + ": ";
        for (const std::string& p : problems) failures.push_back(where + p);
        for (const std::string& p : checkExpect(step.value("expect", json()), out)) failures.push_back(where + p);
        stepsChecked += 1;
      }
    } catch (const CaseError& e) {
      failures.push_back(label + " chyba pripadu: " + e.what());
    } catch (const std::exception& e) {
      failures.push_back(label + " vyjimka: " + e.what());
    }
  }
  return failures;
}

}  // namespace

/// Kontrola spoustece: pripad bez chyby projde, tentyz pripad s preklepem / spatnym klicem skonci chybou pripadu.
int runMalformed(const std::string& path, const json& baseRaw) {
  int passed = 0;
  int failed = 0;
  long long steps = 0;
  const json data = loadJson(path);
  for (const json& pair : data.at("cases")) {
    const std::string id = pair.value("id", "?");
    const std::vector<std::string> good = checkCase(pair.at("good"), baseRaw, steps);
    const std::vector<std::string> bad = checkCase(pair.at("bad"), baseRaw, steps);
    bool caseError = !bad.empty();
    for (const std::string& f : bad) caseError = caseError && f.find("chyba pripadu") != std::string::npos;
    if (good.empty() && caseError) {
      ++passed;
      std::cout << "PASS " << id << ": " << bad.front() << "\n";
    } else {
      ++failed;
      std::cout << "FAIL " << id << (good.empty() ? "" : " (kontrolni pripad neprosel: " + good.front() + ")")
                << (caseError ? "" : " (chybny pripad nebyl odmitnut chybou pripadu)") << "\n";
    }
  }
  std::cout << "souhrn chybnych pripadu: " << passed << " PASS, " << failed << " FAIL\n";
  return failed == 0 && passed > 0 ? 0 : 1;
}

int main(int argc, char** argv) {
  std::string rulesPath;
  std::string malformedPath;
  std::vector<std::string> files;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--rules" && i + 1 < argc) rulesPath = argv[++i];
    else if (a == "--malformed" && i + 1 < argc) malformedPath = argv[++i];
    else files.push_back(a);
  }
  if (!rulesPath.empty() && !malformedPath.empty()) {
    try {
      return runMalformed(malformedPath, loadJson(rulesPath));
    } catch (const std::exception& e) {
      std::cerr << "FAIL " << malformedPath << ": " << e.what() << "\n";
      return 1;
    }
  }
  if (rulesPath.empty() || files.empty()) {
    std::cerr << "pouziti: ivcore_vectors --rules <rules.json> <vektory.json>...\n";
    return 2;
  }
  json baseRaw;
  try {
    baseRaw = loadJson(rulesPath);
  } catch (const std::exception& e) {
    std::cerr << "FAIL nelze nacist pravidla: " << e.what() << "\n";
    return 1;
  }
  int passed = 0;
  int failed = 0;
  long long stepsChecked = 0;
  for (const std::string& file : files) {
    json data;
    try {
      data = loadJson(file);
    } catch (const std::exception& e) {
      std::cerr << "FAIL " << file << ": " << e.what() << "\n";
      ++failed;
      continue;
    }
    if (!data.is_object() || data.value("schema", "") != "ironvalley.testvectors" || !data.contains("cases") ||
        !data["cases"].is_array() || data["cases"].empty()) {
      std::cerr << "FAIL " << file << ": neplatna hlavicka\n";
      ++failed;
      continue;
    }
    bool headerOk = true;
    for (auto it = data.begin(); it != data.end(); ++it) {
      if (fileKeys().count(it.key()) == 0) {
        std::cout << "FAIL " << file << ": neznamy klic hlavicky \"" << it.key() << "\"\n";
        headerOk = false;
      }
    }
    if (!headerOk) {
      ++failed;
      continue;
    }
    for (const json& testCase : data["cases"]) {
      const std::string id = testCase.value("id", "?");
      const std::vector<std::string> failures = checkCase(testCase, baseRaw, stepsChecked);
      if (failures.empty()) {
        ++passed;
        std::cout << "PASS " << id << "\n";
      } else {
        ++failed;
        std::cout << "FAIL " << id << "\n";
        for (std::size_t i = 0; i < failures.size() && i < 12; ++i) std::cout << "    " << failures[i] << "\n";
      }
    }
  }
  std::cout << "souhrn: " << passed << " PASS, " << failed << " FAIL, kontrolovanych kroku " << stepsChecked << "\n";
  return failed == 0 ? 0 : 1;
}
