// Stav jedne zbrane: munice (zasobnik / komora / rezerva), kadence, prebiti a jeho preruseni.
// Stejny automat jako Web/src/core/weapon.js; pravidla v Docs/RULES.md.
#pragma once

#include <string>
#include <vector>

#include "ironvalley/core/rules.hpp"
#include "ironvalley/core/time.hpp"

namespace iv::core {

enum class WeaponActivity { Ready, Reloading, Chambering };
enum class ReloadKind { None, Tactical, Empty };
enum class InterruptReason { Sprint, Switch, Death, Other };

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
bool parseInterruptReason(const std::string& text, InterruptReason& out);

class WeaponState {
 public:
  explicit WeaponState(const WeaponDef& def);

  /// Pocatecni stav munice mimo vybavu (testy, ulozena hra). Jen ve stavu Ready. Vraci false pri neplatnych hodnotach.
  bool setAmmo(int magazine, int chamber, int reserve);

  /// Respawn: plna vychozi vybava, zruseni prebijeni, nulove citace. Posledni pozorovany stav spouste (triggerPrev)
  /// a povoleni (enabled) se nemeni: spoust drzena pres reset neni novy stisk.
  void resetToLoadout();

  /// Posun casu o dtUs (zaporne dt = bez ucinku, vrati 0). trigger = stav spouste po cely tik. Vraci pocet vystrelu.
  /// Engine ma predavat skutecny stav spouste kazdy snimek i vypnute zbrani (smrt, menu).
  int update(Micros dtUs, bool trigger);

  /// Kdyz je zbran vypnuta, vraci RejectedDisabled.
  ReloadResult reload();
  InterruptResult interrupt(InterruptReason reason);
  /// Vypnuti (smrt, menu): prerusi prebijeni/nabijeni s danym duvodem, zrusi platny stisk; dokud je vypnuta,
  /// spoust se ignoruje a reload() vraci RejectedDisabled. Cas plyne dal.
  void disable(InterruptReason reason);
  /// Zapnuti (spawn, zavreni menu). Vystrelit smi az novy stisk. Na zapnute zbrani nic nedela.
  void enable();
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
  bool enabled() const { return enabled_; }
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
  void clearAction();
  void emit(WeaponEventType type, const std::string& detail = std::string());
  void pass(Micros us);
  void onPress();
  void fireRound();
  void startChamber();
  Micros nextMilestoneUs() const;
  void applyMilestone();

  WeaponDef def_;
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
  bool enabled_ = true;
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
