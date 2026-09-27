// Tenka fasada zapasu: kolo + respawn. Tik se deli v okamzicich pokusu o spawn: kazdy usek vyhodnoti oblast se stavem
// zivota na svem zacatku a respawny probehnou na jeho konci (respawnuty se pocita presne od okamziku spawnu).
// Stejne jako Web/src/core/match.js.
#pragma once

#include <cstdint>
#include <set>
#include <string>
#include <vector>

#include "ironvalley/core/respawn.hpp"
#include "ironvalley/core/round.hpp"

namespace iv::core {

struct MatchWorld {
  std::set<std::string> inZone;
  std::set<std::string> inactive;
  SpawnPredicate predicate;  // prazdny = vse bezpecne
};

class Match {
 public:
  /// Semeno kola = seed, semeno spawnu = seed XOR 0x9E3779B9.
  Match(const Rules& rules, std::uint32_t seed, std::vector<std::vector<Vec3>> spawnAreas);

  AddResult addParticipant(const std::string& id, int team, const std::vector<std::string>* loadout = nullptr) {
    return respawn_.addParticipant(id, team, loadout);
  }
  bool start() { return round_.start(); }
  KillResult kill(const std::string& id);
  DamageResult applyDamage(const std::string& victimId, long long amount, const std::string* attackerId);
  /// Vstupy sveta plati po cely tik. Ve stavu ended se nic nedeje. Zaporne dt = InvalidDt bez ucinku.
  InputResult update(Micros dtUs, const MatchWorld& world);
  /// Nove kolo: skore, oblast, casovace, odpocty respawnu i stav zbrani se vynuluji.
  void reset();

  const Round& round() const { return round_; }
  Round& round() { return round_; }
  const RespawnSystem& respawn() const { return respawn_; }
  RespawnSystem& respawn() { return respawn_; }

 private:
  std::vector<ZoneParticipant> zoneParticipants(const MatchWorld& world) const;

  Round round_;
  RespawnSystem respawn_;
};

}  // namespace iv::core
