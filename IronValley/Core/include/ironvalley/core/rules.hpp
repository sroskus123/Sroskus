// Zkompilovana pravidla (casy v celych mikrosekundach). Plni je bud Core/json (nlohmann, testy a nastroje),
// nebo engine vlastnim JSON parserem (UE: FJsonObject) a pak zavola validateRules().
#pragma once

#include <string>
#include <vector>

#include "ironvalley/core/time.hpp"

namespace iv::core {

enum class FireMode { Semi, Auto };

const char* toString(FireMode mode);
bool parseFireMode(const std::string& text, FireMode& out);

struct TeamDef {
  std::string id;
  std::string name;
};

struct ZoneLocation {
  std::string id;
  std::string name;
};

struct TacticalTimeline {
  Micros durationUs = 0;
  Micros insertUs = 0;
};

struct EmptyTimeline {
  Micros durationUs = 0;
  Micros insertUs = 0;
  Micros boltUs = 0;  // 0 pro zbran bez komory
};

struct ChamberTimeline {
  Micros durationUs = 0;  // 0 pro zbran bez komory
  Micros commitUs = 0;
};

/// Nejnizsi kadence (ran/min) = nejdelsi palebny interval 60 s, stejna mez jako JS compileRules. JSON vrstva ji kontroluje
/// na kadenci pred prevodem na mikrosekundy (i engine s vlastnim parserem to musi udelat pred secondsToMicros);
/// validateRules() kontroluje jen vysledny interval proti kMaxFireIntervalUs, a proto neni prisnejsi.
constexpr double kMinRoundsPerMinute = 1.0;
constexpr Micros kMaxFireIntervalUs = 60 * kMicrosPerSecond;

struct WeaponDef {
  std::string id;
  std::string name;
  std::string slot;
  int magazineCapacity = 0;
  bool hasChamber = true;
  int startReserve = 0;
  int maxReserve = 0;
  Micros fireIntervalUs = 0;
  std::vector<FireMode> fireModes;
  FireMode defaultFireMode = FireMode::Semi;
  int damage = 0;
  TacticalTimeline tactical;
  EmptyTimeline empty;
  ChamberTimeline chamber;

  bool supportsFireMode(FireMode mode) const;
};

struct RoundRules {
  Micros preRoundUs = 0;
  Micros timeLimitUs = 0;
  int scoreTarget = 0;
};

struct ZoneRules {
  Micros pointIntervalUs = 0;
  int pointsPerAward = 1;
  std::vector<ZoneLocation> locations;
};

struct RespawnRules {
  Micros delayUs = 0;
  Micros retryIntervalUs = 0;
  double minEnemyDistance = 0.0;
  double bodyClearance = 0.0;
};

struct CombatRules {
  int maxHealth = 100;
  bool friendlyFire = false;
};

struct Rules {
  int teamCount = 0;
  int teamSize = 0;
  std::vector<TeamDef> teams;
  RoundRules round;
  ZoneRules zone;
  RespawnRules respawn;
  CombatRules combat;
  std::vector<std::string> defaultLoadout;
  std::vector<WeaponDef> weapons;  // poradi dle zdroje; hledani podle id

  const WeaponDef* findWeapon(const std::string& id) const;
};

/// Bezpecnostni kontrola zkompilovanych hodnot (bez vyjimek). Prazdny seznam = platne.
/// Je to podmnozina kontrol JSON vrstvy (ta navic kontroluje typy a hodnoty pred prevodem na mikrosekundy),
/// nikdy neni prisnejsi nez JS compileRules().
std::vector<std::string> validateRules(const Rules& rules);

}  // namespace iv::core
