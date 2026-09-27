#include "ironvalley/core/match.hpp"

#include <algorithm>
#include <utility>

namespace iv::core {

Match::Match(const Rules& rules, std::uint32_t seed, std::vector<std::vector<Vec3>> spawnAreas)
    : round_(rules, seed), respawn_(rules, deriveSeed(seed, kSpawnSeedSalt), std::move(spawnAreas)) {}

KillResult Match::kill(const std::string& id) {
  if (round_.state() == RoundState::Ended) return KillResult::RoundEnded;
  return respawn_.kill(id);
}

DamageResult Match::applyDamage(const std::string& victimId, long long amount, const std::string* attackerId) {
  if (round_.state() == RoundState::Ended) return DamageResult{DamageCode::RoundEnded, 0};
  return respawn_.applyDamage(victimId, amount, attackerId);
}

std::vector<ZoneParticipant> Match::zoneParticipants(const MatchWorld& world) const {
  std::vector<ZoneParticipant> participants;
  participants.reserve(respawn_.participants().size());
  for (const Participant& p : respawn_.participants()) {
    ZoneParticipant z;
    z.id = p.id;
    z.team = p.team;
    z.alive = p.state == LifeState::Alive;
    z.active = world.inactive.count(p.id) == 0;
    z.inZone = world.inZone.count(p.id) != 0;
    participants.push_back(std::move(z));
  }
  return participants;
}

InputResult Match::update(Micros dtUs, const MatchWorld& world) {
  if (dtUs < 0) return InputResult::InvalidDt;
  if (round_.state() == RoundState::Ended) return InputResult::Ok;
  SpawnClaims claims = respawn_.newClaims();  // jeden rozsah "bod pouzity v tomto update" pro cely tik
  respawn_.advance(0, world.predicate, claims);  // kdo ma spawn ted, pocita se od zacatku tiku
  Micros remaining = dtUs;
  do {
    const Micros step = std::min(remaining, respawn_.nextAttemptInUs());
    const Micros pre0 = round_.preRoundRemainingUs();
    const Micros elapsed0 = round_.elapsedUs();
    const InputResult r = round_.tick(step, zoneParticipants(world));
    if (r != InputResult::Ok) return r;
    // Kolo mohlo skoncit uprostred useku (cil): respawny dobehnou jen do okamziku konce, pak stoji.
    const Micros used = pre0 - round_.preRoundRemainingUs() + (round_.elapsedUs() - elapsed0);
    respawn_.advance(used, world.predicate, claims);
    remaining -= step;
  } while (remaining > 0 && round_.state() != RoundState::Ended);
  return InputResult::Ok;
}

void Match::reset() {
  round_.reset();
  respawn_.resetRound();
}

}  // namespace iv::core
