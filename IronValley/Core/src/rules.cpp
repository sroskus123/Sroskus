#include "ironvalley/core/rules.hpp"

#include "ironvalley/core/weapon.hpp"

#include <set>

namespace iv::core {

const char* toString(FireMode mode) { return mode == FireMode::Auto ? "auto" : "semi"; }

bool parseFireMode(const std::string& text, FireMode& out) {
  if (text == "semi") {
    out = FireMode::Semi;
    return true;
  }
  if (text == "auto") {
    out = FireMode::Auto;
    return true;
  }
  return false;
}

bool WeaponDef::supportsFireMode(FireMode mode) const {
  for (FireMode m : fireModes)
    if (m == mode) return true;
  return false;
}

const WeaponDef* Rules::findWeapon(const std::string& id) const {
  for (const WeaponDef& w : weapons)
    if (w.id == id) return &w;
  return nullptr;
}

namespace {

void check(std::vector<std::string>& errors, bool ok, const std::string& what) {
  if (!ok) errors.push_back(what);
}

// Horni mez casu kola, oblasti a respawnu = 86400 s, stejne jako JS compileRules (LIMIT_SECONDS).
constexpr Micros kMaxConfigUs = 86400LL * kMicrosPerSecond;

}  // namespace

std::vector<std::string> validateRules(const Rules& r) {
  std::vector<std::string> e;
  check(e, r.teamCount >= 2 && r.teamCount <= 8, "teams.count mimo 2..8");
  check(e, r.teamSize >= 1 && r.teamSize <= 64, "teams.size mimo 1..64");
  check(e, static_cast<int>(r.teams.size()) == r.teamCount, "teams.list neodpovida teams.count");
  {
    std::set<std::string> ids;
    for (const TeamDef& t : r.teams) {
      check(e, !t.id.empty(), "prazdne id tymu");
      check(e, ids.insert(t.id).second, "duplicitni id tymu");
    }
  }
  check(e, r.round.preRoundUs >= 0 && r.round.preRoundUs <= kMaxConfigUs, "round.preRoundDuration mimo 0..86400 s");
  check(e, r.round.timeLimitUs >= 1 && r.round.timeLimitUs <= kMaxConfigUs, "round.timeLimit mimo 1 us..86400 s");
  check(e, r.round.scoreTarget >= 1 && r.round.scoreTarget <= 1000000, "round.scoreTarget mimo rozsah");
  check(e, r.zone.pointIntervalUs >= 1 && r.zone.pointIntervalUs <= kMaxConfigUs, "zone.pointInterval mimo 1 us..86400 s");
  check(e, r.zone.pointsPerAward >= 1 && r.zone.pointsPerAward <= 1000000, "zone.pointsPerAward mimo rozsah");
  check(e, !r.zone.locations.empty() && r.zone.locations.size() <= 16, "zone.locations musi mit 1..16 polozek");
  {
    std::set<std::string> ids;
    for (const ZoneLocation& z : r.zone.locations) {
      check(e, !z.id.empty(), "prazdne id oblasti");
      check(e, ids.insert(z.id).second, "duplicitni id oblasti");
    }
  }
  check(e, r.respawn.delayUs >= 0 && r.respawn.delayUs <= kMaxConfigUs, "respawn.delay mimo 0..86400 s");
  check(e, r.respawn.retryIntervalUs >= 1 && r.respawn.retryIntervalUs <= kMaxConfigUs, "respawn.retryInterval mimo 1 us..86400 s");
  check(e, r.respawn.minEnemyDistance >= 0.0 && r.respawn.minEnemyDistance <= 10000.0, "respawn.minEnemyDistance mimo rozsah");
  check(e, r.respawn.bodyClearance >= 0.0 && r.respawn.bodyClearance <= 100.0, "respawn.bodyClearance mimo rozsah");
  check(e, r.combat.maxHealth >= 1 && r.combat.maxHealth <= 1000000, "combat.maxHealth mimo rozsah");
  check(e, !r.weapons.empty(), "zadna zbran");
  {
    std::set<std::string> ids;
    for (const WeaponDef& w : r.weapons) {
      const std::string p = "weapons." + w.id + ": ";
      check(e, !w.id.empty() && ids.insert(w.id).second, p + "prazdne nebo duplicitni id");
      for (const std::string& msg : validateWeaponDef(w)) e.push_back(p + msg);
    }
  }
  check(e, !r.defaultLoadout.empty(), "loadout.default je prazdny");
  {
    std::set<std::string> ids;
    for (const std::string& id : r.defaultLoadout) {
      check(e, r.findWeapon(id) != nullptr, "loadout.default: neznama zbran " + id);
      check(e, ids.insert(id).second, "loadout.default: duplicitni zbran " + id);
    }
  }
  return e;
}

}  // namespace iv::core
