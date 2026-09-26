#include "ironvalley/core/zone.hpp"

#include <set>

namespace iv::core {

const char* toString(ZoneStatus v) {
  switch (v) {
    case ZoneStatus::Empty: return "empty";
    case ZoneStatus::Contested: return "contested";
    case ZoneStatus::Controlled: return "controlled";
  }
  return "?";
}

const char* toString(InputResult v) {
  switch (v) {
    case InputResult::Ok: return "ok";
    case InputResult::InvalidId: return "invalid_id";
    case InputResult::InvalidTeam: return "invalid_team";
    case InputResult::DuplicateId: return "duplicate_id";
    case InputResult::InvalidDt: return "invalid_dt";
    case InputResult::InvalidConfig: return "invalid_config";
  }
  return "?";
}

InputResult validateParticipants(const std::vector<ZoneParticipant>& participants, int teamCount) {
  std::set<std::string> seen;
  for (const ZoneParticipant& p : participants) {
    if (p.id.empty()) return InputResult::InvalidId;
    if (p.team < 0 || p.team >= teamCount) return InputResult::InvalidTeam;
    if (!seen.insert(p.id).second) return InputResult::DuplicateId;
  }
  return InputResult::Ok;
}

ZoneScoring::ZoneScoring(const Rules& rules)
    : teamCount_(rules.teamCount), pointIntervalUs_(rules.zone.pointIntervalUs), pointsPerAward_(rules.zone.pointsPerAward) {
  const std::vector<std::string> errors = validateRules(rules);
  if (!errors.empty()) {
    // Neplatna pravidla (napr. vychozi Rules{} nebo chyba parseru enginu): zadne deleni nulou ani zaporne velikosti.
    configError_ = errors.front();
    teamCount_ = 0;
    pointIntervalUs_ = 1;
    pointsPerAward_ = 1;
  }
  reset();
}

void ZoneScoring::reset() {
  scores_.assign(static_cast<std::size_t>(teamCount_), 0);
  counts_.assign(static_cast<std::size_t>(teamCount_), 0);
  status_ = ZoneStatus::Empty;
  controller_ = -1;
  progressUs_ = 0;
}

InputResult ZoneScoring::evaluate(const std::vector<ZoneParticipant>& participants) {
  if (!configError_.empty()) return InputResult::InvalidConfig;
  const InputResult err = validateParticipants(participants, teamCount_);
  if (err != InputResult::Ok) return err;
  std::vector<int> counts(static_cast<std::size_t>(teamCount_), 0);
  for (const ZoneParticipant& p : participants)
    if (p.alive && p.active && p.inZone) counts[static_cast<std::size_t>(p.team)] += 1;
  int best = 0;
  int bestTeam = -1;
  bool tie = false;
  for (int t = 0; t < teamCount_; ++t) {
    const int c = counts[static_cast<std::size_t>(t)];
    if (c > best) {
      best = c;
      bestTeam = t;
      tie = false;
    } else if (c == best && best > 0) {
      tie = true;
    }
  }
  ZoneStatus status;
  int controller;
  if (best == 0) {
    status = ZoneStatus::Empty;
    controller = -1;
  } else if (tie) {
    status = ZoneStatus::Contested;
    controller = -1;
  } else {
    status = ZoneStatus::Controlled;
    controller = bestTeam;
  }
  if (controller != controller_ || controller == -1) progressUs_ = 0;
  counts_ = counts;
  status_ = status;
  controller_ = controller;
  return InputResult::Ok;
}

ZoneScoring::Advance ZoneScoring::advance(Micros dtUs, std::int64_t maxAwards) {
  if (!validDt(dtUs) || maxAwards < 1 || !configError_.empty()) return Advance{0, 0};  // chyba volajiciho: nic nemenit
  if (controller_ == -1) {
    progressUs_ = 0;
    return Advance{0, dtUs};
  }
  // progress < pointInterval <= 86400 s a dt <= 2^53 - 1, takze soucet ani soucin nize int64 nepretece.
  const Micros total = progressUs_ + dtUs;
  std::int64_t awards = total / pointIntervalUs_;
  if (awards >= maxAwards) {
    awards = maxAwards;
    const Micros used = awards * pointIntervalUs_ - progressUs_;
    addScore(awards);
    progressUs_ = 0;
    return Advance{awards, used};
  }
  addScore(awards);
  progressUs_ = total - awards * pointIntervalUs_;
  return Advance{awards, dtUs};
}

void ZoneScoring::addScore(std::int64_t awards) {
  std::int64_t& score = scores_[static_cast<std::size_t>(controller_)];
  const std::int64_t room = kMaxScore - score;
  score = awards > room / pointsPerAward_ ? kMaxScore : score + awards * pointsPerAward_;
}

InputResult ZoneScoring::tick(Micros dtUs, const std::vector<ZoneParticipant>& participants) {
  if (!configError_.empty()) return InputResult::InvalidConfig;
  if (!validDt(dtUs)) return InputResult::InvalidDt;
  const InputResult err = evaluate(participants);
  if (err != InputResult::Ok) return err;
  advance(dtUs);
  return InputResult::Ok;
}

}  // namespace iv::core
