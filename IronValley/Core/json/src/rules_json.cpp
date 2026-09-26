#include "ironvalley/core/rules_json.hpp"

#include <cmath>
#include <optional>
#include <set>

namespace iv::core {

using nlohmann::json;

namespace {

constexpr double kLimitSeconds = 86400.0;

const json* member(const json* parent, const char* key) {
  if (parent == nullptr || !parent->is_object()) return nullptr;
  auto it = parent->find(key);
  return it == parent->end() ? nullptr : &*it;
}

/// Replika tridy Checker z Web/src/core/rules.js (stejne podminky, jina jen zneni chyb).
class Checker {
 public:
  std::vector<std::string> errors;

  void fail(const std::string& path, const std::string& msg) { errors.push_back(path + ": " + msg); }

  const json* obj(const json* parent, const char* key, const std::string& path) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_object()) {
      fail(path, "ocekavan objekt");
      return nullptr;
    }
    return v;
  }

  std::optional<double> num(const json* parent, const char* key, const std::string& path, double min, double max,
                            bool minExclusive = false) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_number() || !std::isfinite(v->get<double>())) {
      fail(path, "ocekavano cislo");
      return std::nullopt;
    }
    const double d = v->get<double>();
    if (minExclusive ? !(d > min) : !(d >= min)) {
      fail(path, "pod minimem");
      return std::nullopt;
    }
    if (!(d <= max)) {
      fail(path, "nad maximem");
      return std::nullopt;
    }
    return d;
  }

  /// JS Number.isInteger: i 30.0 je cele cislo.
  std::optional<long long> integer(const json* parent, const char* key, const std::string& path, long long min, long long max) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_number()) {
      fail(path, "ocekavano cele cislo");
      return std::nullopt;
    }
    const double d = v->get<double>();
    if (!std::isfinite(d) || std::floor(d) != d) {
      fail(path, "ocekavano cele cislo");
      return std::nullopt;
    }
    if (d < static_cast<double>(min) || d > static_cast<double>(max)) {
      fail(path, "mimo rozsah");
      return std::nullopt;
    }
    return static_cast<long long>(d);
  }

  std::optional<bool> boolean(const json* parent, const char* key, const std::string& path) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_boolean()) {
      fail(path, "ocekavana logicka hodnota");
      return std::nullopt;
    }
    return v->get<bool>();
  }

  std::optional<std::string> str(const json* parent, const char* key, const std::string& path, bool allowEmpty = false) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_string() || (!allowEmpty && v->get<std::string>().empty())) {
      fail(path, "ocekavan neprazdny text");
      return std::nullopt;
    }
    return v->get<std::string>();
  }

  template <typename T>
  std::optional<std::vector<T>> idList(const json* parent, const char* key, const std::string& path, std::size_t minLen,
                                       std::size_t maxLen) {
    const json* v = member(parent, key);
    if (v == nullptr || !v->is_array()) {
      fail(path, "ocekavano pole");
      return std::nullopt;
    }
    if (v->size() < minLen || v->size() > maxLen) {
      fail(path, "delka mimo rozsah");
      return std::nullopt;
    }
    std::vector<T> out;
    std::set<std::string> seen;
    for (std::size_t i = 0; i < v->size(); ++i) {
      const json* item = &(*v)[i];
      const std::string p = path + "[" + std::to_string(i) + "]";
      auto id = str(item, "id", p + ".id");
      auto name = str(item, "name", p + ".name", true);
      if (id && !seen.insert(*id).second) fail(p + ".id", "duplicitni id");
      out.push_back(T{id.value_or(""), name.value_or("")});
    }
    return out;
  }
};

void compileWeapon(Checker& c, const std::string& id, const json& raw, const std::string& path, WeaponDef& w) {
  w.id = id;
  if (!raw.is_object()) {
    c.fail(path, "ocekavan objekt");
    return;
  }
  const json* r = &raw;
  w.name = c.str(r, "name", path + ".name", true).value_or("");
  w.slot = c.str(r, "slot", path + ".slot").value_or("");
  auto mag = c.integer(r, "magazineCapacity", path + ".magazineCapacity", 1, 1000);
  auto hasChamber = c.boolean(r, "hasChamber", path + ".hasChamber");
  auto startReserve = c.integer(r, "startReserve", path + ".startReserve", 0, 1000000);
  auto maxReserve = c.integer(r, "maxReserve", path + ".maxReserve", 0, 1000000);
  if (startReserve && maxReserve && *startReserve > *maxReserve) c.fail(path + ".startReserve", "vetsi nez maxReserve");
  w.magazineCapacity = static_cast<int>(mag.value_or(0));
  w.hasChamber = hasChamber.value_or(false);
  w.startReserve = static_cast<int>(startReserve.value_or(0));
  w.maxReserve = static_cast<int>(maxReserve.value_or(0));
  auto rpm = c.num(r, "roundsPerMinute", path + ".roundsPerMinute", 0.0, 100000.0, true);
  if (rpm) {
    w.fireIntervalUs = secondsToMicros(60.0 / *rpm);
    if (w.fireIntervalUs < 1) c.fail(path + ".roundsPerMinute", "interval kratsi nez 1 us");
  }
  const json* modes = member(r, "fireModes");
  std::vector<std::string> modeTexts;
  if (modes == nullptr || !modes->is_array() || modes->empty()) {
    c.fail(path + ".fireModes", "ocekavano neprazdne pole");
  } else {
    std::set<std::string> seen;
    for (const json& m : *modes) {
      FireMode fm;
      const std::string text = m.is_string() ? m.get<std::string>() : std::string("\x01<not-a-string>");
      modeTexts.push_back(text);
      if (!m.is_string() || !parseFireMode(text, fm)) {
        c.fail(path + ".fireModes", "neznamy rezim");
      } else if (!seen.insert(text).second) {
        c.fail(path + ".fireModes", "duplicitni rezim");
      } else {
        w.fireModes.push_back(fm);
      }
    }
  }
  auto def = c.str(r, "defaultFireMode", path + ".defaultFireMode");
  if (def && modes != nullptr && modes->is_array()) {
    bool found = false;
    for (const json& m : *modes)
      if (m.is_string() && m.get<std::string>() == *def) found = true;
    if (!found) c.fail(path + ".defaultFireMode", "neni ve fireModes");
    FireMode fm;
    if (parseFireMode(*def, fm)) w.defaultFireMode = fm;
  }
  w.damage = static_cast<int>(c.integer(r, "damage", path + ".damage", 0, 1000000).value_or(0));

  const json* reload = c.obj(r, "reload", path + ".reload");
  const json* tac = c.obj(reload, "tactical", path + ".reload.tactical");
  const json* emp = c.obj(reload, "empty", path + ".reload.empty");
  w.tactical = TacticalTimeline{};
  w.empty = EmptyTimeline{};
  w.chamber = ChamberTimeline{};
  if (tac != nullptr) {
    auto d = c.num(tac, "duration", path + ".reload.tactical.duration", 0.0, 60.0, true);
    auto ins = c.num(tac, "insertCommit", path + ".reload.tactical.insertCommit", 0.0, 60.0);
    if (d && ins) {
      w.tactical.durationUs = secondsToMicros(*d);
      w.tactical.insertUs = secondsToMicros(*ins);
      if (w.tactical.insertUs > w.tactical.durationUs) c.fail(path + ".reload.tactical.insertCommit", "musi byt <= duration");
    }
  }
  const bool chamberTrue = hasChamber.has_value() && *hasChamber;
  if (emp != nullptr) {
    auto d = c.num(emp, "duration", path + ".reload.empty.duration", 0.0, 60.0, true);
    auto ins = c.num(emp, "insertCommit", path + ".reload.empty.insertCommit", 0.0, 60.0);
    std::optional<double> bolt = 0.0;
    if (chamberTrue) bolt = c.num(emp, "boltRelease", path + ".reload.empty.boltRelease", 0.0, 60.0);
    if (d && ins && bolt) {
      w.empty.durationUs = secondsToMicros(*d);
      w.empty.insertUs = secondsToMicros(*ins);
      w.empty.boltUs = chamberTrue ? secondsToMicros(*bolt) : 0;
      if (w.empty.insertUs > w.empty.durationUs) c.fail(path + ".reload.empty.insertCommit", "musi byt <= duration");
      if (chamberTrue) {
        if (w.empty.boltUs < w.empty.insertUs) c.fail(path + ".reload.empty.boltRelease", "musi byt >= insertCommit");
        if (w.empty.boltUs > w.empty.durationUs) c.fail(path + ".reload.empty.boltRelease", "musi byt <= duration");
      }
    }
  }
  if (chamberTrue) {
    const json* ch = c.obj(reload, "chamber", path + ".reload.chamber");
    if (ch != nullptr) {
      auto d = c.num(ch, "duration", path + ".reload.chamber.duration", 0.0, 60.0, true);
      auto cm = c.num(ch, "commit", path + ".reload.chamber.commit", 0.0, 60.0);
      if (d && cm) {
        w.chamber.durationUs = secondsToMicros(*d);
        w.chamber.commitUs = secondsToMicros(*cm);
        if (w.chamber.commitUs > w.chamber.durationUs) c.fail(path + ".reload.chamber.commit", "musi byt <= duration");
      }
    }
  }
}

}  // namespace

bool rulesFromJson(const json& raw, Rules& r, std::vector<std::string>& errors) {
  Checker c;
  r = Rules{};
  if (!raw.is_object()) {
    errors.push_back("$: ocekavan objekt");
    return false;
  }
  const json* root = &raw;
  const json* teams = c.obj(root, "teams", "teams");
  auto count = c.integer(teams, "count", "teams.count", 2, 8);
  auto size = c.integer(teams, "size", "teams.size", 1, 64);
  r.teamCount = static_cast<int>(count.value_or(0));
  r.teamSize = static_cast<int>(size.value_or(0));
  if (teams != nullptr) {
    auto list = c.idList<TeamDef>(teams, "list", "teams.list", 1, 8);
    if (list) {
      r.teams = *list;
      if (count && static_cast<long long>(list->size()) != *count) c.fail("teams.list", "pocet neodpovida teams.count");
    }
  }

  const json* round = c.obj(root, "round", "round");
  auto pre = c.num(round, "preRoundDuration", "round.preRoundDuration", 0.0, kLimitSeconds);
  auto limit = c.num(round, "timeLimit", "round.timeLimit", 0.0, kLimitSeconds, true);
  r.round.preRoundUs = pre ? secondsToMicros(*pre) : 0;
  r.round.timeLimitUs = limit ? secondsToMicros(*limit) : 0;
  r.round.scoreTarget = static_cast<int>(c.integer(round, "scoreTarget", "round.scoreTarget", 1, 1000000).value_or(0));
  if (limit && r.round.timeLimitUs < 1) c.fail("round.timeLimit", "alespon 1 us");

  const json* zone = c.obj(root, "zone", "zone");
  auto interval = c.num(zone, "pointInterval", "zone.pointInterval", 0.0, kLimitSeconds, true);
  r.zone.pointIntervalUs = interval ? secondsToMicros(*interval) : 0;
  r.zone.pointsPerAward = static_cast<int>(c.integer(zone, "pointsPerAward", "zone.pointsPerAward", 1, 1000000).value_or(0));
  if (zone != nullptr) {
    auto locs = c.idList<ZoneLocation>(zone, "locations", "zone.locations", 1, 16);
    if (locs) r.zone.locations = *locs;
  }
  if (interval && r.zone.pointIntervalUs < 1) c.fail("zone.pointInterval", "alespon 1 us");

  const json* resp = c.obj(root, "respawn", "respawn");
  auto delay = c.num(resp, "delay", "respawn.delay", 0.0, kLimitSeconds);
  auto retry = c.num(resp, "retryInterval", "respawn.retryInterval", 0.0, kLimitSeconds, true);
  r.respawn.delayUs = delay ? secondsToMicros(*delay) : 0;
  r.respawn.retryIntervalUs = retry ? secondsToMicros(*retry) : 0;
  r.respawn.minEnemyDistance = c.num(resp, "minEnemyDistance", "respawn.minEnemyDistance", 0.0, 10000.0).value_or(0.0);
  r.respawn.bodyClearance = c.num(resp, "bodyClearance", "respawn.bodyClearance", 0.0, 100.0).value_or(0.0);
  if (retry && r.respawn.retryIntervalUs < 1) c.fail("respawn.retryInterval", "alespon 1 us");

  const json* combat = c.obj(root, "combat", "combat");
  r.combat.maxHealth = static_cast<int>(c.integer(combat, "maxHealth", "combat.maxHealth", 1, 1000000).value_or(0));
  r.combat.friendlyFire = c.boolean(combat, "friendlyFire", "combat.friendlyFire").value_or(false);

  const json* weapons = c.obj(root, "weapons", "weapons");
  if (weapons != nullptr) {
    if (weapons->empty()) c.fail("weapons", "alespon jedna zbran");
    for (auto it = weapons->begin(); it != weapons->end(); ++it) {
      if (it.key().empty()) {
        c.fail("weapons", "prazdne id zbrane");
        continue;
      }
      WeaponDef w;
      compileWeapon(c, it.key(), it.value(), "weapons." + it.key(), w);
      r.weapons.push_back(std::move(w));
    }
  }

  const json* loadout = c.obj(root, "loadout", "loadout");
  if (loadout != nullptr) {
    const json* list = member(loadout, "default");
    if (list == nullptr || !list->is_array() || list->empty()) {
      c.fail("loadout.default", "ocekavano neprazdne pole");
    } else {
      std::set<std::string> seen;
      for (const json& wid : *list) {
        if (!wid.is_string() || r.findWeapon(wid.get<std::string>()) == nullptr) {
          c.fail("loadout.default", "neznama zbran");
        } else if (!seen.insert(wid.get<std::string>()).second) {
          c.fail("loadout.default", "duplicitni zbran");
        }
        r.defaultLoadout.push_back(wid.is_string() ? wid.get<std::string>() : std::string());
      }
    }
  }

  errors = c.errors;
  if (errors.empty()) {
    // Bezpecnostni kontrola jadra (podmnozina vyse uvedenych kontrol) - ma byt vzdy prazdna.
    for (const std::string& e : validateRules(r)) errors.push_back("core: " + e);
  }
  return errors.empty();
}

json rulesToJson(const Rules& r) {
  json out;
  out["teamCount"] = r.teamCount;
  out["teamSize"] = r.teamSize;
  out["teams"] = json::array();
  for (const TeamDef& t : r.teams) out["teams"].push_back({{"id", t.id}, {"name", t.name}});
  out["round"] = {{"preRoundUs", r.round.preRoundUs}, {"timeLimitUs", r.round.timeLimitUs}, {"scoreTarget", r.round.scoreTarget}};
  json locs = json::array();
  for (const ZoneLocation& z : r.zone.locations) locs.push_back({{"id", z.id}, {"name", z.name}});
  out["zone"] = {{"pointIntervalUs", r.zone.pointIntervalUs}, {"pointsPerAward", r.zone.pointsPerAward}, {"locations", locs}};
  out["respawn"] = {{"delayUs", r.respawn.delayUs},
                    {"retryIntervalUs", r.respawn.retryIntervalUs},
                    {"minEnemyDistance", r.respawn.minEnemyDistance},
                    {"bodyClearance", r.respawn.bodyClearance}};
  out["combat"] = {{"maxHealth", r.combat.maxHealth}, {"friendlyFire", r.combat.friendlyFire}};
  out["loadout"] = {{"default", r.defaultLoadout}};
  json weapons = json::object();
  for (const WeaponDef& w : r.weapons) {
    json modes = json::array();
    for (FireMode m : w.fireModes) modes.push_back(toString(m));
    weapons[w.id] = {{"id", w.id},
                     {"name", w.name},
                     {"slot", w.slot},
                     {"magazineCapacity", w.magazineCapacity},
                     {"hasChamber", w.hasChamber},
                     {"startReserve", w.startReserve},
                     {"maxReserve", w.maxReserve},
                     {"fireIntervalUs", w.fireIntervalUs},
                     {"fireModes", modes},
                     {"defaultFireMode", toString(w.defaultFireMode)},
                     {"damage", w.damage},
                     {"tactical", {{"durationUs", w.tactical.durationUs}, {"insertUs", w.tactical.insertUs}}},
                     {"empty", {{"durationUs", w.empty.durationUs}, {"insertUs", w.empty.insertUs}, {"boltUs", w.empty.boltUs}}},
                     {"chamber", {{"durationUs", w.chamber.durationUs}, {"commitUs", w.chamber.commitUs}}}};
  }
  out["weapons"] = weapons;
  return out;
}

json mergePatch(const json& target, const json& patch) {
  json result = target;
  result.merge_patch(patch);
  return result;
}

}  // namespace iv::core
