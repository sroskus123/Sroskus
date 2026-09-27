// Stav jedne zbrane: munice (zasobnik / komora / rezerva), kadence, prebiti a jeho preruseni.
// Stejny automat jako Web/src/core/weapon.js; pravidla v Docs/RULES.md.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ironvalley/core/rules.hpp"
#include "ironvalley/core/time.hpp"

namespace iv::core {

enum class WeaponActivity { Ready, Reloading, Chambering };
enum class ReloadKind { None, Tactical, Empty };
enum class InterruptReason { Sprint, Switch, Death, Other };
/// Duvody vypnuti, ktere smi pouzit engine. Kazdy duvod je samostatny zamek (disable prida, enable odebere jen ten).
/// Zamek zivota (vlastnik neni alive, zbran mimo vybavu) drzi jen RespawnSystem a verejnym API nejde zmenit.
enum class DisableReason { Sprint, Switch, Menu, Results, Other };

enum class WeaponEventType {
  Shot,
  BoltLocked,
  DryFire,
  ReloadStart,
  MagInsert,
  BoltRelease,
  ReloadComplete,
  ReloadInterrupted,
  ChamberStart,
  ChamberCommit,
  ChamberComplete,
  ChamberInterrupted,
};

struct WeaponEvent {
  WeaponEventType type;
  Micros atUs;
  std::string detail;  // druh prebiti ("tactical"/"empty") nebo duvod preruseni, jinak prazdne
};

enum class ReloadResult {
  StartedTactical,
  StartedEmpty,
  StartedChamber,
  RejectedBusy,
  RejectedFull,
  RejectedNoReserve,
  RejectedDisabled,
};
enum class InterruptResult { None, Interrupted };

const char* toString(WeaponActivity v);
const char* toString(ReloadKind v);
const char* toString(InterruptReason v);
const char* toString(WeaponEventType v);
const char* toString(ReloadResult v);
const char* toString(InterruptResult v);
const char* toString(DisableReason v);
bool parseInterruptReason(const std::string& text, InterruptReason& out);
bool parseDisableReason(const std::string& text, DisableReason& out);

/// Kontrola definice zbrane (podmnozina validateRules); prazdny seznam = platna.
std::vector<std::string> validateWeaponDef(const WeaponDef& def);

class RespawnSystem;

class WeaponState {
 public:
  /// Neplatna definice (validateWeaponDef) = configError() neprazdne a zbran je netecna: update() vrati 0 bez zmeny,
  /// reload() RejectedDisabled, resupply() -1, setAmmo() false, enabled() false.
  explicit WeaponState(const WeaponDef& def);

  const std::string& configError() const { return configError_; }

  /// Pocatecni stav munice mimo vybavu (testy, ulozena hra). Jen ve stavu Ready. Vraci false pri neplatnych hodnotach.
  bool setAmmo(int magazine, int chamber, int reserve);

  /// Respawn: plna vychozi vybava, zruseni prebijeni (probihajici akce se nejdriv prerusi s duvodem Other a vyda
  /// udalost), nulove citace. Neodebrane udalosti zustavaji. Posledni pozorovany stav spouste (triggerPrev)
  /// a zamky se nemeni: spoust drzena pres reset neni novy stisk.
  void resetToLoadout();

  /// Posun casu o dtUs (neplatne dt, viz validDt = bez ucinku, vrati 0). trigger = stav spouste po cely tik.
  /// Vraci pocet vystrelu. Engine ma predavat skutecny stav spouste kazdy snimek i vypnute zbrani (smrt, menu).
  int update(Micros dtUs, bool trigger);

  /// Kdyz je zbran vypnuta (jakykoli zamek), vraci RejectedDisabled.
  ReloadResult reload();
  InterruptResult interrupt(InterruptReason reason);
  /// Prida zamek s timto duvodem: prerusi prebijeni/nabijeni (Sprint -> sprint, Switch -> switch, jinak other),
  /// zrusi platny stisk. Dokud trva jakykoli zamek, spoust se ignoruje a reload() vraci RejectedDisabled.
  /// Cas plyne dal.
  void disable(DisableReason reason);
  /// Odebere jen zamek s timto duvodem; ostatni zamky (i zamek zivota) trvaji. Vystrelit smi az novy stisk.
  void enable(DisableReason reason);
  /// false = rezim neni u teto zbrane povolen.
  bool setFireMode(FireMode mode);
  /// Doplneni rezervy do maxReserve. Vraci pridany pocet, -1 pri zapornem vstupu.
  int resupply(long long rounds);

  std::vector<WeaponEvent> takeEvents();

  const WeaponDef& def() const { return def_; }
  WeaponActivity activity() const { return state_; }
  ReloadKind reloadKind() const { return reloadKind_; }
  Micros actionUs() const { return actionUs_; }
  bool insertCommitted() const { return insertCommitted_; }
  bool boltReleased() const { return boltReleased_; }
  bool chamberCommitted() const { return chamberCommitted_; }
  int magazine() const { return magazine_; }
  int chamber() const { return chamber_; }
  int reserve() const { return reserve_; }
  FireMode fireMode() const { return fireMode_; }
  Micros cooldownUs() const { return cooldownUs_; }
  Micros clockUs() const { return clockUs_; }
  bool triggerPrev() const { return triggerPrev_; }
  bool holdValid() const { return holdValid_; }
  /// true = zadny zamek (a platna definice): zbran prijima spoust i prebiti.
  bool enabled() const { return locks_ == 0 && configError_.empty(); }
  bool lifeLocked() const { return (locks_ & kLifeBit) != 0; }
  bool disabledBy(DisableReason reason) const { return (locks_ & bitOf(reason)) != 0; }
  /// Aktivni zamky v pevnem poradi: "life", pak sprint, switch, menu, results, other.
  std::vector<std::string> disabledByNames() const;
  int shotsFired() const { return shotsFired_; }
  int resupplied() const { return resupplied_; }
  int dryFires() const { return dryFires_; }
  int reloadsStarted() const { return reloadsStarted_; }
  int reloadsCompleted() const { return reloadsCompleted_; }
  int reloadsInterrupted() const { return reloadsInterrupted_; }
  int chamberActions() const { return chamberActions_; }
  int initialTotal() const { return initialTotal_; }

  bool canFireRound() const { return def_.hasChamber ? chamber_ == 1 : magazine_ > 0; }
  bool needsChamberAction() const { return def_.hasChamber && chamber_ == 0 && magazine_ > 0; }
  bool isBusy() const { return state_ != WeaponActivity::Ready; }
  int totalAmmo() const { return magazine_ + chamber_ + reserve_; }

  /// Kontrola invariantu munice; prazdny seznam = v poradku.
  std::vector<std::string> invariantViolations() const;

 private:
  friend class RespawnSystem;
  static constexpr std::uint8_t kLifeBit = 1;
  static std::uint8_t bitOf(DisableReason reason) { return static_cast<std::uint8_t>(2u << static_cast<unsigned>(reason)); }
  /// Jen RespawnSystem: zamek zivota; detail = duvod preruseni probihajici akce.
  void setLifeLock(bool locked, InterruptReason detail);
  void addLock(std::uint8_t bit, InterruptReason interruptReason);
  void removeLock(std::uint8_t bit);
  void clearAction();
  void emit(WeaponEventType type, const std::string& detail = std::string());
  void pass(Micros us);
  void onPress();
  void fireRound();
  void startChamber();
  Micros nextMilestoneUs() const;
  void applyMilestone();

  WeaponDef def_;
  std::string configError_;
  std::vector<WeaponEvent> outbox_;
  WeaponActivity state_ = WeaponActivity::Ready;
  ReloadKind reloadKind_ = ReloadKind::None;
  Micros actionUs_ = 0;
  bool insertCommitted_ = false;
  bool boltReleased_ = false;
  bool chamberCommitted_ = false;
  int magazine_ = 0;
  int chamber_ = 0;
  int reserve_ = 0;
  FireMode fireMode_ = FireMode::Semi;
  Micros cooldownUs_ = 0;
  Micros clockUs_ = 0;
  bool triggerPrev_ = false;
  bool holdValid_ = false;
  std::uint8_t locks_ = 0;  // bit 0 = zivot, bit 1+DisableReason = zamky enginu
  int shotsFired_ = 0;
  int resupplied_ = 0;
  int dryFires_ = 0;
  int reloadsStarted_ = 0;
  int reloadsCompleted_ = 0;
  int reloadsInterrupted_ = 0;
  int chamberActions_ = 0;
  int initialTotal_ = 0;
};

}  // namespace iv::core
