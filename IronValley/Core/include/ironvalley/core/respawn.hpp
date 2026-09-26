// Zivotni cyklus ucastnika: alive -> dead -> respawning -> alive, bezpecny spawn, zdravi, vybava.
// Stejne jako Web/src/core/respawn.js.
#pragma once

#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "ironvalley/core/rng.hpp"
#include "ironvalley/core/rules.hpp"
#include "ironvalley/core/weapon.hpp"

namespace iv::core {

struct Vec3 {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;
};

struct Body {
  int team = -1;
  bool alive = false;
  Vec3 pos;
};

/// Referencni cast predikatu spawnu: zadny zivy nepritel blize nez minEnemyDistance, zadne zive telo blize nez
/// bodyClearance (3D, ostra nerovnost). Viditelnost a kolize s geometrii kontroluje engine ve svem predikatu.
bool spawnPointSafe(const Vec3& point, int team, const std::vector<Body>& bodies, const RespawnRules& rules);

struct SpawnQuery {
  const std::string& participantId;
  int team;
  int candidateIndex;
  const Vec3& point;
};
using SpawnPredicate = std::function<bool(const SpawnQuery&)>;

enum class LifeState { Alive, Dead, Respawning };
enum class AddResult { Ok, InvalidId, DuplicateId, InvalidTeam, InvalidLoadout, TeamFull, InvalidConfig };
enum class KillResult { Killed, NotAlive, UnknownId, RoundEnded };
enum class DamageCode { Applied, Killed, BlockedFriendlyFire, NotAlive, InvalidAmount, UnknownId, RoundEnded };
enum class LoadoutResult { Ok, UnknownId, InvalidLoadout };
enum class InputLockResult { Ok, UnknownId };

const char* toString(LifeState v);
const char* toString(AddResult v);
const char* toString(KillResult v);
const char* toString(DamageCode v);
const char* toString(LoadoutResult v);
const char* toString(InputLockResult v);

struct DamageResult {
  DamageCode code;
  int applied;
};

struct RespawnEvent {
  std::string type;  // "spawned" | "spawn_blocked" | "killed"
  std::string id;
  int point;  // index kandidatniho bodu nebo -1
};

struct Participant {
  std::string id;
  int team = -1;
  LifeState state = LifeState::Respawning;
  int health = 0;
  Micros respawnInUs = 0;
  Micros retryInUs = 0;
  int spawnPoint = -1;
  int spawnCount = 0;
  int deaths = 0;
  int failedSpawnAttempts = 0;
  std::vector<std::string> loadout;  // pro pristi spawn
  /// Zamky vstupu enginu na urovni ucastnika (menu, vysledky ...), plati pro vsechny jeho zbrane vcetne pozdeji
  /// vytvorenych. Respawn ani reset kola je nemeni.
  std::vector<DisableReason> inputLocks;
  /// Prave vybavene zbrane v poradi loadoutu (nevlastnici ukazatele do armory).
  std::vector<std::pair<std::string, WeaponState*>> weapons;
  /// Vsechny zbrane, ktere ucastnik kdy dostal. Objekty lezi na halde a nikdy se nenahrazuji ani neruseji, takze
  /// WeaponState* ziskany pres RespawnSystem::weapon() plati po celou dobu zivota RespawnSystem (respawn, reset kola,
  /// pridani dalsich ucastniku i zmena vybavy). Zbran mimo vybavu nebo mrtveho ucastnika ma zamek zivota.
  std::vector<std::pair<std::string, std::unique_ptr<WeaponState>>> armory;
};

class RespawnSystem {
 public:
  /// spawnAreas[team] = kandidatni body. Pravidla se kontroluji (validateRules). Pri neplatne konfiguraci je
  /// configError() neprazdne, addParticipant vraci InvalidConfig a update/advance nic nedelaji.
  RespawnSystem(const Rules& rules, std::uint32_t seed, std::vector<std::vector<Vec3>> spawnAreas);

  const std::string& configError() const { return configError_; }

  AddResult addParticipant(const std::string& id, int team, const std::vector<std::string>* loadout = nullptr);
  LoadoutResult setLoadout(const std::string& id, const std::vector<std::string>& loadout);
  /// Zamek vstupu enginu pro vsechny zbrane ucastnika (i pozdeji vytvorene). Odebere ho jen enableInput se stejnym
  /// duvodem; zamek zivota (mrtvy ucastnik) tim nezmizi.
  InputLockResult disableInput(const std::string& id, DisableReason reason);
  InputLockResult enableInput(const std::string& id, DisableReason reason);
  KillResult kill(const std::string& id);
  /// attackerId == nullptr: prostredi. Neplatna castka (<= 0) -> InvalidAmount.
  DamageResult applyDamage(const std::string& victimId, long long amount, const std::string* attackerId);
  /// Posun casu; predikat muze byt prazdny (vse bezpecne). Pokusy o spawn probehnou v presnych okamzicich uvnitr
  /// tiku (vysledek nezavisi na deleni casu na tiky). Bod pouzity pro spawn je rezervovany po dobu retryInterval.
  /// Neplatne dt (viz validDt) = bez ucinku.
  void update(Micros dtUs, const SpawnPredicate& predicate);

  /// Nikdo neceka na spawn (navratova hodnota nextAttemptInUs).
  static constexpr Micros kNoAttempt = std::numeric_limits<Micros>::max();
  /// Za kolik mikrosekund probehne nejblizsi pokus o spawn (0 = ted), kNoAttempt = nikdo neceka.
  Micros nextAttemptInUs() const;
  /// Jeden usek bez deleni: odpocty i rezervace bodu klesnou o dtUs, kdo dosahne nuly, zkusi spawn na konci useku.
  /// Volajici zajisti dtUs <= nextAttemptInUs(). Neplatne dt = bez ucinku.
  void advance(Micros dtUs, const SpawnPredicate& predicate);
  /// Nove kolo: vsichni cekaji na okamzity spawn, odpocty, rezervace bodu, stav zbrani a citace vynulovany.
  /// Zamky vstupu enginu zustavaji.
  void resetRound();

  /// Zbyvajici rezervace bodu [tym][index] v us (0 = bod lze nabidnout).
  const std::vector<std::vector<Micros>>& reservedUs() const { return reservedUs_; }

  std::vector<RespawnEvent> takeEvents();

  const std::vector<Participant>& participants() const { return order_; }
  /// Ukazatel na ucastnika plati jen do dalsiho addParticipant (ucastnici lezi ve vektoru).
  const Participant* participant(const std::string& id) const;
  Participant* participant(const std::string& id);
  /// Vybavena zbran ucastnika, nebo nullptr. Ukazatel plati po celou dobu zivota RespawnSystem (viz Participant::armory).
  WeaponState* weapon(const std::string& id, const std::string& weaponId);

 private:
  bool validLoadout(const std::vector<std::string>& loadout) const;
  void resetParticipant(Participant& p);
  void rebuildWeapons(Participant& p);
  bool trySpawn(Participant& p, const SpawnPredicate& predicate);
  WeaponState* armoryWeapon(Participant& p, const std::string& weaponId);

  Rules rules_;
  Rng rng_;
  std::vector<std::vector<Vec3>> spawnAreas_;
  std::vector<std::vector<Micros>> reservedUs_;
  std::vector<Participant> order_;
  std::vector<RespawnEvent> outbox_;
  std::string configError_;
};

}  // namespace iv::core
