// Bodovani kontrolni oblasti. Stejna pravidla jako Web/src/core/zone.js.
#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <vector>

#include "ironvalley/core/rules.hpp"
#include "ironvalley/core/time.hpp"

namespace iv::core {

struct ZoneParticipant {
  std::string id;
  int team = -1;
  bool alive = false;
  bool active = false;
  bool inZone = false;
};

enum class ZoneStatus { Empty, Contested, Controlled };
/// InvalidDt: zaporne dt (chyba volajiciho; JS jadro v tom pripade vyhodi RangeError). Stav se nemeni.
enum class InputResult { Ok, InvalidId, InvalidTeam, DuplicateId, InvalidDt };

const char* toString(ZoneStatus v);
const char* toString(InputResult v);

/// Kontrola vstupu tiku: prazdne id, tym mimo rozsah, duplicitni id (v tomto poradi, prvni chyba vyhrava).
InputResult validateParticipants(const std::vector<ZoneParticipant>& participants, int teamCount);

class ZoneScoring {
 public:
  static constexpr std::int64_t kUnlimited = std::numeric_limits<std::int64_t>::max();

  explicit ZoneScoring(const Rules& rules);

  void reset();
  /// Urci stav oblasti; zmena kontrolora (i na "nikdo") vynuluje postup. Pri chybe vstupu se stav nemeni.
  InputResult evaluate(const std::vector<ZoneParticipant>& participants);

  struct Advance {
    std::int64_t awards;
    Micros usedUs;
  };
  /// Nechá plynout dtUs platne kontroly; maxAwards >= 1 omezi pocet udeleni (konec kola pri cili).
  /// dtUs < 0 nebo maxAwards < 1 (chyba volajiciho) = bez ucinku, vrati {0, 0}.
  Advance advance(Micros dtUs, std::int64_t maxAwards = kUnlimited);
  /// evaluate + advance. dtUs < 0 = InvalidDt bez ucinku.
  InputResult tick(Micros dtUs, const std::vector<ZoneParticipant>& participants);

  ZoneStatus status() const { return status_; }
  int controller() const { return controller_; }
  const std::vector<int>& counts() const { return counts_; }
  const std::vector<int>& scores() const { return scores_; }
  Micros progressUs() const { return progressUs_; }
  void clearProgress() { progressUs_ = 0; }

 private:
  int teamCount_;
  Micros pointIntervalUs_;
  int pointsPerAward_;
  std::vector<int> scores_;
  std::vector<int> counts_;
  ZoneStatus status_ = ZoneStatus::Empty;
  int controller_ = -1;
  Micros progressUs_ = 0;
};

}  // namespace iv::core
