#include "ironvalley/core/round.hpp"

#include <algorithm>

namespace iv::core {

const char* toString(RoundState v) {
  switch (v) {
    case RoundState::PreRound: return "pre_round";
    case RoundState::Running: return "running";
    case RoundState::Ended: return "ended";
  }
  return "?";
}

const char* toString(EndReason v) {
  switch (v) {
    case EndReason::None: return "none";
    case EndReason::ScoreTarget: return "score_target";
    case EndReason::TimeLimit: return "time_limit";
  }
  return "?";
}

Round::Round(const Rules& rules, std::uint32_t seed) : rules_(rules), rng_(seed), zone_(rules) {
  const std::vector<std::string> errors = validateRules(rules_);
  if (!errors.empty()) configError_ = errors.front();
  beginRound();
}

const std::string& Round::zoneId() const {
  static const std::string kNone;
  if (!configError_.empty()) return kNone;
  return rules_.zone.locations[static_cast<std::size_t>(zoneIndex_)].id;
}

void Round::beginRound() {
  roundNumber_ += 1;
  // Neplatna pravidla: zadny vyber z (mozna prazdneho) seznamu oblasti a zadny posun generatoru.
  zoneIndex_ = configError_.empty()
                   ? static_cast<int>(rng_.pickIndex(static_cast<std::uint32_t>(rules_.zone.locations.size())))
                   : 0;
  state_ = RoundState::PreRound;
  preRoundRemainingUs_ = rules_.round.preRoundUs;
  elapsedUs_ = 0;
  winner_ = -1;
  draw_ = false;
  endReason_ = EndReason::None;
  zone_.reset();
}

void Round::reset() { beginRound(); }

bool Round::start() {
  if (state_ != RoundState::PreRound || !configError_.empty()) return false;
  preRoundRemainingUs_ = 0;
  state_ = RoundState::Running;
  return true;
}

InputResult Round::tick(Micros dtUs, const std::vector<ZoneParticipant>& participants) {
  if (!configError_.empty()) return InputResult::InvalidConfig;
  if (!validDt(dtUs)) return InputResult::InvalidDt;
  const InputResult err = validateParticipants(participants, rules_.teamCount);
  if (err != InputResult::Ok) return err;
  if (state_ == RoundState::Ended) return InputResult::Ok;
  Micros remaining = dtUs;
  if (state_ == RoundState::PreRound) {
    const Micros use = std::min(remaining, preRoundRemainingUs_);
    preRoundRemainingUs_ -= use;
    remaining -= use;
    if (preRoundRemainingUs_ > 0) return InputResult::Ok;
    state_ = RoundState::Running;
  }
  zone_.evaluate(participants);
  const Micros use = std::min(remaining, rules_.round.timeLimitUs - elapsedUs_);
  const int c = zone_.controller();
  std::int64_t maxAwards = ZoneScoring::kUnlimited;
  if (c >= 0) {
    const std::int64_t need = rules_.round.scoreTarget - zone_.scores()[static_cast<std::size_t>(c)];
    const std::int64_t ppa = rules_.zone.pointsPerAward;
    maxAwards = (need + ppa - 1) / ppa;
  }
  const ZoneScoring::Advance res = zone_.advance(use, maxAwards);
  elapsedUs_ += res.usedUs;
  if (c >= 0 && zone_.scores()[static_cast<std::size_t>(c)] >= rules_.round.scoreTarget) {
    finish(EndReason::ScoreTarget, c, false);
  } else if (elapsedUs_ >= rules_.round.timeLimitUs) {
    finishByTime();
  }
  return InputResult::Ok;
}

void Round::finishByTime() {
  const std::vector<std::int64_t>& s = zone_.scores();
  std::int64_t best = -1;
  int bestTeam = -1;
  int count = 0;
  for (int t = 0; t < static_cast<int>(s.size()); ++t) {
    const std::int64_t v = s[static_cast<std::size_t>(t)];
    if (v > best) {
      best = v;
      bestTeam = t;
      count = 1;
    } else if (v == best) {
      count += 1;
    }
  }
  if (count == 1) finish(EndReason::TimeLimit, bestTeam, false);
  else finish(EndReason::TimeLimit, -1, true);
}

void Round::finish(EndReason reason, int winner, bool draw) {
  state_ = RoundState::Ended;
  endReason_ = reason;
  winner_ = winner;
  draw_ = draw;
  zone_.clearProgress();
}

}  // namespace iv::core
