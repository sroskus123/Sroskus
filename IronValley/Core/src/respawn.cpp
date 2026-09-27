#include "ironvalley/core/respawn.hpp"

#include <algorithm>
#include <cmath>
#include <set>

namespace iv::core {

const char* toString(LifeState v) {
  switch (v) {
    case LifeState::Alive: return "alive";
    case LifeState::Dead: return "dead";
    case LifeState::Respawning: return "respawning";
  }
  return "?";
}

const char* toString(AddResult v) {
  switch (v) {
    case AddResult::Ok: return "ok";
    case AddResult::InvalidId: return "invalid_id";
    case AddResult::DuplicateId: return "duplicate_id";
    case AddResult::InvalidTeam: return "invalid_team";
    case AddResult::InvalidLoadout: return "invalid_loadout";
    case AddResult::TeamFull: return "team_full";
    case AddResult::InvalidConfig: return "invalid_config";
  }
  return "?";
}

const char* toString(KillResult v) {
  switch (v) {
    case KillResult::Killed: return "killed";
    case KillResult::NotAlive: return "not_alive";
    case KillResult::UnknownId: return "unknown_id";
    case KillResult::RoundEnded: return "round_ended";
  }
  return "?";
}

const char* toString(DamageCode v) {
  switch (v) {
    case DamageCode::Applied: return "applied";
    case DamageCode::Killed: return "killed";
    case DamageCode::BlockedFriendlyFire: return "blocked_friendly_fire";
    case DamageCode::NotAlive: return "not_alive";
    case DamageCode::InvalidAmount: return "invalid_amount";
    case DamageCode::UnknownId: return "unknown_id";
    case DamageCode::RoundEnded: return "round_ended";
  }
  return "?";
}

const char* toString(LoadoutResult v) {
  switch (v) {
    case LoadoutResult::Ok: return "ok";
    case LoadoutResult::UnknownId: return "unknown_id";
    case LoadoutResult::InvalidLoadout: return "invalid_loadout";
  }
  return "?";
}

const char* toString(InputLockResult v) { return v == InputLockResult::Ok ? "ok" : "unknown_id"; }

bool spawnPointSafe(const Vec3& point, int team, const std::vector<Body>& bodies, const RespawnRules& rules) {
  const double enemy2 = rules.minEnemyDistance * rules.minEnemyDistance;
  const double body2 = rules.bodyClearance * rules.bodyClearance;
  for (const Body& b : bodies) {
    if (!b.alive) continue;
    const double dx = b.pos.x - point.x;
    const double dy = b.pos.y - point.y;
    const double dz = b.pos.z - point.z;
    const double d2 = dx * dx + dy * dy + dz * dz;  // stejne poradi operaci jako JS (bez FMA, viz CMake)
    if (b.team != team && d2 < enemy2) return false;
    if (d2 < body2) return false;
  }
  return true;
}

RespawnSystem::RespawnSystem(const Rules& rules, std::uint32_t seed, std::vector<std::vector<Vec3>> spawnAreas)
    : rules_(rules), rng_(seed), spawnAreas_(std::move(spawnAreas)) {
  const std::vector<std::string> errors = validateRules(rules_);
  if (!errors.empty()) {
    configError_ = errors.front();
    spawnAreas_.clear();
    return;
  }
  if (static_cast<int>(spawnAreas_.size()) != rules_.teamCount) {
    configError_ = "spawnAreas musi mit jednu oblast pro kazdy tym";
    return;
  }
  for (const auto& area : spawnAreas_) {
    if (area.empty()) {
      configError_ = "kazda spawnova oblast musi mit alespon jeden bod";
      return;
    }
    for (const Vec3& p : area) {
      if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z)) {
        configError_ = "neplatny spawnovy bod";
        return;
      }
    }
  }
  for (const auto& area : spawnAreas_) reservedUs_.emplace_back(area.size(), 0);
}

bool RespawnSystem::validLoadout(const std::vector<std::string>& loadout) const {
  if (loadout.empty()) return false;
  std::set<std::string> seen;
  for (const std::string& w : loadout) {
    if (rules_.findWeapon(w) == nullptr || !seen.insert(w).second) return false;
  }
  return true;
}

const Participant* RespawnSystem::participant(const std::string& id) const {
  for (const Participant& p : order_)
    if (p.id == id) return &p;
  return nullptr;
}

Participant* RespawnSystem::participant(const std::string& id) {
  for (Participant& p : order_)
    if (p.id == id) return &p;
  return nullptr;
}

WeaponState* RespawnSystem::weapon(const std::string& id, const std::string& weaponId) {
  Participant* p = participant(id);
  if (p == nullptr) return nullptr;
  for (auto& entry : p->weapons)
    if (entry.first == weaponId) return entry.second;
  return nullptr;
}

AddResult RespawnSystem::addParticipant(const std::string& id, int team, const std::vector<std::string>* loadout) {
  if (!configError_.empty()) return AddResult::InvalidConfig;
  if (id.empty()) return AddResult::InvalidId;
  if (participant(id) != nullptr) return AddResult::DuplicateId;
  if (team < 0 || team >= rules_.teamCount) return AddResult::InvalidTeam;
  const std::vector<std::string>& lo = loadout != nullptr ? *loadout : rules_.defaultLoadout;
  if (!validLoadout(lo)) return AddResult::InvalidLoadout;
  int members = 0;
  for (const Participant& p : order_)
    if (p.team == team) members += 1;
  if (members >= rules_.teamSize) return AddResult::TeamFull;
  Participant p;
  p.id = id;
  p.team = team;
  p.loadout = lo;
  resetParticipant(p);
  order_.push_back(std::move(p));
  return AddResult::Ok;
}

void RespawnSystem::resetParticipant(Participant& p) {
  p.state = LifeState::Respawning;
  p.health = 0;
  p.respawnInUs = 0;
  p.retryInUs = 0;
  p.spawnPoint = -1;
  p.spawnCount = 0;
  p.deaths = 0;
  p.failedSpawnAttempts = 0;
  rebuildWeapons(p);
}

WeaponState* RespawnSystem::armoryWeapon(Participant& p, const std::string& weaponId) {
  for (auto& entry : p.armory)
    if (entry.first == weaponId) return entry.second.get();
  p.armory.emplace_back(weaponId, std::make_unique<WeaponState>(*rules_.findWeapon(weaponId)));
  WeaponState* w = p.armory.back().second.get();
  w->setLifeLock(true, InterruptReason::Other);
  for (DisableReason r : p.inputLocks) w->disable(r);  // nova zbran prevezme zamky vstupu ucastnika
  return w;
}

// Vybava podle loadoutu v plnem vychozim stavu, vsechny zbrane se zamkem zivota (odemkne je az spawn). Existujici
// objekty se resetuji na miste; nic se nekopiruje ani nerusi, takze ukazatele drzene enginem zustavaji platne.
void RespawnSystem::rebuildWeapons(Participant& p) {
  for (auto& entry : p.armory) entry.second->setLifeLock(true, InterruptReason::Other);
  p.weapons.clear();
  for (const std::string& wid : p.loadout) {
    WeaponState* w = armoryWeapon(p, wid);
    w->resetToLoadout();
    p.weapons.emplace_back(wid, w);
  }
}

LoadoutResult RespawnSystem::setLoadout(const std::string& id, const std::vector<std::string>& loadout) {
  Participant* p = participant(id);
  if (p == nullptr) return LoadoutResult::UnknownId;
  if (!validLoadout(loadout)) return LoadoutResult::InvalidLoadout;
  p->loadout = loadout;
  return LoadoutResult::Ok;
}

InputLockResult RespawnSystem::disableInput(const std::string& id, DisableReason reason) {
  Participant* p = participant(id);
  if (p == nullptr) return InputLockResult::UnknownId;
  if (std::find(p->inputLocks.begin(), p->inputLocks.end(), reason) == p->inputLocks.end()) p->inputLocks.push_back(reason);
  for (auto& entry : p->armory) entry.second->disable(reason);
  return InputLockResult::Ok;
}

InputLockResult RespawnSystem::enableInput(const std::string& id, DisableReason reason) {
  Participant* p = participant(id);
  if (p == nullptr) return InputLockResult::UnknownId;
  p->inputLocks.erase(std::remove(p->inputLocks.begin(), p->inputLocks.end(), reason), p->inputLocks.end());
  for (auto& entry : p->armory) entry.second->enable(reason);
  return InputLockResult::Ok;
}

KillResult RespawnSystem::kill(const std::string& id) {
  Participant* p = participant(id);
  if (p == nullptr) return KillResult::UnknownId;
  if (p->state != LifeState::Alive) return KillResult::NotAlive;
  p->state = LifeState::Dead;
  p->health = 0;
  p->respawnInUs = rules_.respawn.delayUs;
  p->retryInUs = 0;
  p->deaths += 1;
  for (auto& entry : p->weapons) entry.second->setLifeLock(true, InterruptReason::Death);
  outbox_.push_back(RespawnEvent{"killed", id, -1});
  return KillResult::Killed;
}

DamageResult RespawnSystem::applyDamage(const std::string& victimId, long long amount, const std::string* attackerId) {
  Participant* v = participant(victimId);
  if (v == nullptr) return DamageResult{DamageCode::UnknownId, 0};
  const Participant* attacker = nullptr;
  if (attackerId != nullptr) {
    attacker = participant(*attackerId);
    if (attacker == nullptr) return DamageResult{DamageCode::UnknownId, 0};
  }
  if (amount <= 0) return DamageResult{DamageCode::InvalidAmount, 0};
  if (v->state != LifeState::Alive) return DamageResult{DamageCode::NotAlive, 0};
  if (attacker != nullptr && attacker != v && attacker->team == v->team && !rules_.combat.friendlyFire) {
    return DamageResult{DamageCode::BlockedFriendlyFire, 0};
  }
  const int applied = static_cast<int>(std::min<long long>(amount, v->health));
  v->health -= applied;
  if (v->health == 0) {
    kill(victimId);
    return DamageResult{DamageCode::Killed, applied};
  }
  return DamageResult{DamageCode::Applied, applied};
}

void RespawnSystem::update(Micros dtUs, const SpawnPredicate& predicate) {
  if (!configError_.empty() || !validDt(dtUs)) return;
  advance(0, predicate);
  Micros remaining = dtUs;
  while (remaining > 0) {
    const Micros step = std::min(remaining, nextAttemptInUs());  // > 0: retryInterval >= 1 us (validateRules)
    advance(step, predicate);
    remaining -= step;
  }
}

Micros RespawnSystem::nextAttemptInUs() const {
  Micros best = kNoAttempt;
  for (const Participant& p : order_) {
    if (p.state == LifeState::Dead) best = std::min(best, p.respawnInUs);
    else if (p.state == LifeState::Respawning) best = std::min(best, p.retryInUs);
  }
  return best;
}

void RespawnSystem::advance(Micros dtUs, const SpawnPredicate& predicate) {
  if (!configError_.empty() || !validDt(dtUs)) return;
  if (dtUs > 0) {
    for (auto& area : reservedUs_)
      for (Micros& r : area) r = r > dtUs ? r - dtUs : 0;
  }
  for (Participant& p : order_) {
    bool attempt = false;
    if (p.state == LifeState::Dead) {
      p.respawnInUs = p.respawnInUs > dtUs ? p.respawnInUs - dtUs : 0;
      if (p.respawnInUs > 0) continue;
      p.state = LifeState::Respawning;
      p.retryInUs = 0;
      attempt = true;
    } else if (p.state == LifeState::Respawning) {
      p.retryInUs = p.retryInUs > dtUs ? p.retryInUs - dtUs : 0;
      attempt = p.retryInUs == 0;
    }
    if (attempt) trySpawn(p, predicate);
  }
}

bool RespawnSystem::trySpawn(Participant& p, const SpawnPredicate& predicate) {
  const std::vector<Vec3>& area = spawnAreas_[static_cast<std::size_t>(p.team)];
  std::vector<Micros>& reserved = reservedUs_[static_cast<std::size_t>(p.team)];
  const std::vector<int> order = rng_.shuffledIndices(static_cast<int>(area.size()));
  for (int idx : order) {
    if (reserved[static_cast<std::size_t>(idx)] > 0) continue;
    const Vec3& point = area[static_cast<std::size_t>(idx)];
    const bool ok = predicate ? predicate(SpawnQuery{p.id, p.team, idx, point}) : true;
    if (!ok) continue;
    reserved[static_cast<std::size_t>(idx)] = rules_.respawn.retryIntervalUs;
    p.state = LifeState::Alive;
    p.health = rules_.combat.maxHealth;
    p.respawnInUs = 0;
    p.retryInUs = 0;
    p.spawnPoint = idx;
    p.spawnCount += 1;
    rebuildWeapons(p);
    for (auto& entry : p.weapons) entry.second->setLifeLock(false, InterruptReason::Other);
    outbox_.push_back(RespawnEvent{"spawned", p.id, idx});
    return true;
  }
  p.failedSpawnAttempts += 1;
  p.retryInUs = rules_.respawn.retryIntervalUs;
  outbox_.push_back(RespawnEvent{"spawn_blocked", p.id, -1});
  return false;
}

void RespawnSystem::resetRound() {
  for (auto& area : reservedUs_) std::fill(area.begin(), area.end(), Micros{0});
  for (Participant& p : order_) resetParticipant(p);
  outbox_.clear();
}

std::vector<RespawnEvent> RespawnSystem::takeEvents() {
  std::vector<RespawnEvent> out;
  out.swap(outbox_);
  return out;
}

}  // namespace iv::core
