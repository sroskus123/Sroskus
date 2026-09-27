// Stavovy automat kola: pre_round -> running -> ended (-> reset -> pre_round). Stejne jako Web/src/core/round.js.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ironvalley/core/rng.hpp"
#include "ironvalley/core/rules.hpp"
#include "ironvalley/core/zone.hpp"

namespace iv::core {

enum class RoundState { PreRound, Running, Ended };
enum class EndReason { None, ScoreTarget, TimeLimit };

const char* toString(RoundState v);
const char* toString(EndReason v);

class Round {
 public:
  Round(const Rules& rules, std::uint32_t seed);

  /// Nove kolo: skore, postup, casovace a vysledek vynulovany; dalsi oblast ze stejne posloupnosti semene.
  void reset();
  /// Okamzity start z pre_round. false = kolo neni v pre_round.
  bool start();
  /// Tik kola. Pri chybe vstupu (vcetne zaporneho dt = InvalidDt) se stav nemeni.
  InputResult tick(Micros dtUs, const std::vector<ZoneParticipant>& participants);

  RoundState state() const { return state_; }
  int roundNumber() const { return roundNumber_; }
  int zoneIndex() const { return zoneIndex_; }
  const std::string& zoneId() const { return rules_.zone.locations[static_cast<std::size_t>(zoneIndex_)].id; }
  Micros preRoundRemainingUs() const { return preRoundRemainingUs_; }
  Micros elapsedUs() const { return elapsedUs_; }
  Micros remainingUs() const { return rules_.round.timeLimitUs - elapsedUs_; }
  int winner() const { return winner_; }
  bool draw() const { return draw_; }
  EndReason endReason() const { return endReason_; }
  const ZoneScoring& zone() const { return zone_; }

 private:
  void beginRound();
  void finish(EndReason reason, int winner, bool draw);
  void finishByTime();

  Rules rules_;
  Rng rng_;
  ZoneScoring zone_;
  RoundState state_ = RoundState::PreRound;
  int roundNumber_ = 0;
  int zoneIndex_ = 0;
  Micros preRoundRemainingUs_ = 0;
  Micros elapsedUs_ = 0;
  int winner_ = -1;
  bool draw_ = false;
  EndReason endReason_ = EndReason::None;
};

}  // namespace iv::core
