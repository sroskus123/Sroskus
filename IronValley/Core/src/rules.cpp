#include "ironvalley/core/rules.hpp"

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
  check(e, r.round.preRoundUs >= 0, "round.preRoundDuration < 0");
  check(e, r.round.timeLimitUs >= 1, "round.timeLimit < 1 us");
  check(e, r.round.scoreTarget >= 1 && r.round.scoreTarget <= 1000000, "round.scoreTarget mimo rozsah");
  check(e, r.zone.pointIntervalUs >= 1, "zone.pointInterval < 1 us");
  check(e, r.zone.pointsPerAward >= 1 && r.zone.pointsPerAward <= 1000000, "zone.pointsPerAward mimo rozsah");
  check(e, !r.zone.locations.empty() && r.zone.locations.size() <= 16, "zone.locations musi mit 1..16 polozek");
  {
    std::set<std::string> ids;
    for (const ZoneLocation& z : r.zone.locations) {
      check(e, !z.id.empty(), "prazdne id oblasti");
      check(e, ids.insert(z.id).second, "duplicitni id oblasti");
    }
  }
  check(e, r.respawn.delayUs >= 0, "respawn.delay < 0");
  check(e, r.respawn.retryIntervalUs >= 1, "respawn.retryInterval < 1 us");
  check(e, r.respawn.minEnemyDistance >= 0.0 && r.respawn.minEnemyDistance <= 10000.0, "respawn.minEnemyDistance mimo rozsah");
  check(e, r.respawn.bodyClearance >= 0.0 && r.respawn.bodyClearance <= 100.0, "respawn.bodyClearance mimo rozsah");
  check(e, r.combat.maxHealth >= 1 && r.combat.maxHealth <= 1000000, "combat.maxHealth mimo rozsah");
  check(e, !r.weapons.empty(), "zadna zbran");
  {
    std::set<std::string> ids;
    for (const WeaponDef& w : r.weapons) {
      const std::string p = "weapons." + w.id + ": ";
      check(e, !w.id.empty() && ids.insert(w.id).second, p + "prazdne nebo duplicitni id");
      check(e, !w.slot.empty(), p + "prazdny slot");
      check(e, w.magazineCapacity >= 1 && w.magazineCapacity <= 1000, p + "magazineCapacity mimo 1..1000");
      check(e, w.startReserve >= 0 && w.maxReserve >= 0 && w.maxReserve <= 1000000 && w.startReserve <= w.maxReserve,
            p + "rezerva mimo rozsah");
      check(e, w.fireIntervalUs >= 1, p + "palebny interval < 1 us");
      check(e, !w.fireModes.empty() && w.fireModes.size() <= 2, p + "fireModes");
      check(e, !(w.fireModes.size() == 2 && w.fireModes[0] == w.fireModes[1]), p + "duplicitni fireModes");
      check(e, w.supportsFireMode(w.defaultFireMode), p + "defaultFireMode neni ve fireModes");
      check(e, w.damage >= 0 && w.damage <= 1000000, p + "damage mimo rozsah");
      check(e, w.tactical.durationUs >= 0 && w.tactical.insertUs >= 0 && w.tactical.insertUs <= w.tactical.durationUs,
            p + "reload.tactical");
      check(e, w.empty.durationUs >= 0 && w.empty.insertUs >= 0 && w.empty.insertUs <= w.empty.durationUs, p + "reload.empty");
      if (w.hasChamber) {
        check(e, w.empty.boltUs >= w.empty.insertUs && w.empty.boltUs <= w.empty.durationUs, p + "reload.empty.boltRelease");
        check(e, w.chamber.durationUs >= 0 && w.chamber.commitUs >= 0 && w.chamber.commitUs <= w.chamber.durationUs,
              p + "reload.chamber");
      }
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
