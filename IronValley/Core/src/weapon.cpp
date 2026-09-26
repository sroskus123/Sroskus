#include "ironvalley/core/weapon.hpp"

#include <algorithm>

namespace iv::core {

const char* toString(WeaponActivity v) {
  switch (v) {
    case WeaponActivity::Ready: return "ready";
    case WeaponActivity::Reloading: return "reloading";
    case WeaponActivity::Chambering: return "chambering";
  }
  return "?";
}

const char* toString(ReloadKind v) {
  switch (v) {
    case ReloadKind::None: return "none";
    case ReloadKind::Tactical: return "tactical";
    case ReloadKind::Empty: return "empty";
  }
  return "?";
}

const char* toString(InterruptReason v) {
  switch (v) {
    case InterruptReason::Sprint: return "sprint";
    case InterruptReason::Switch: return "switch";
    case InterruptReason::Death: return "death";
    case InterruptReason::Other: return "other";
  }
  return "?";
}

const char* toString(WeaponEventType v) {
  switch (v) {
    case WeaponEventType::Shot: return "shot";
    case WeaponEventType::BoltLocked: return "bolt_locked";
    case WeaponEventType::DryFire: return "dry_fire";
    case WeaponEventType::ReloadStart: return "reload_start";
    case WeaponEventType::MagInsert: return "mag_insert";
    case WeaponEventType::BoltRelease: return "bolt_release";
    case WeaponEventType::ReloadComplete: return "reload_complete";
    case WeaponEventType::ReloadInterrupted: return "reload_interrupted";
    case WeaponEventType::ChamberStart: return "chamber_start";
    case WeaponEventType::ChamberCommit: return "chamber_commit";
    case WeaponEventType::ChamberComplete: return "chamber_complete";
    case WeaponEventType::ChamberInterrupted: return "chamber_interrupted";
  }
  return "?";
}

const char* toString(ReloadResult v) {
  switch (v) {
    case ReloadResult::StartedTactical: return "started_tactical";
    case ReloadResult::StartedEmpty: return "started_empty";
    case ReloadResult::StartedChamber: return "started_chamber";
    case ReloadResult::RejectedBusy: return "rejected_busy";
    case ReloadResult::RejectedFull: return "rejected_full";
    case ReloadResult::RejectedNoReserve: return "rejected_no_reserve";
    case ReloadResult::RejectedDisabled: return "rejected_disabled";
  }
  return "?";
}

const char* toString(InterruptResult v) { return v == InterruptResult::Interrupted ? "interrupted" : "none"; }

const char* toString(DisableReason v) {
  switch (v) {
    case DisableReason::Sprint: return "sprint";
    case DisableReason::Switch: return "switch";
    case DisableReason::Menu: return "menu";
    case DisableReason::Results: return "results";
    case DisableReason::Other: return "other";
  }
  return "?";
}

bool parseDisableReason(const std::string& text, DisableReason& out) {
  if (text == "sprint") out = DisableReason::Sprint;
  else if (text == "switch") out = DisableReason::Switch;
  else if (text == "menu") out = DisableReason::Menu;
  else if (text == "results") out = DisableReason::Results;
  else if (text == "other") out = DisableReason::Other;
  else return false;
  return true;
}

namespace {

void check(std::vector<std::string>& errors, bool ok, const char* what) {
  if (!ok) errors.emplace_back(what);
}

/// Duvod preruseni probihajici akce pri vypnuti danym duvodem.
InterruptReason interruptFor(DisableReason reason) {
  switch (reason) {
    case DisableReason::Sprint: return InterruptReason::Sprint;
    case DisableReason::Switch: return InterruptReason::Switch;
    default: return InterruptReason::Other;
  }
}

}  // namespace

std::vector<std::string> validateWeaponDef(const WeaponDef& w) {
  std::vector<std::string> e;
  check(e, !w.id.empty(), "prazdne id");
  check(e, !w.slot.empty(), "prazdny slot");
  check(e, w.magazineCapacity >= 1 && w.magazineCapacity <= 1000, "magazineCapacity mimo 1..1000");
  check(e, w.startReserve >= 0 && w.maxReserve >= 0 && w.maxReserve <= 1000000 && w.startReserve <= w.maxReserve,
        "rezerva mimo rozsah");
  check(e, w.fireIntervalUs >= 1, "palebny interval < 1 us");
  check(e, !w.fireModes.empty() && w.fireModes.size() <= 2, "fireModes");
  check(e, !(w.fireModes.size() == 2 && w.fireModes[0] == w.fireModes[1]), "duplicitni fireModes");
  check(e, w.supportsFireMode(w.defaultFireMode), "defaultFireMode neni ve fireModes");
  check(e, w.damage >= 0 && w.damage <= 1000000, "damage mimo rozsah");
  check(e, w.tactical.durationUs >= 0 && w.tactical.insertUs >= 0 && w.tactical.insertUs <= w.tactical.durationUs,
        "reload.tactical");
  check(e, w.empty.durationUs >= 0 && w.empty.insertUs >= 0 && w.empty.insertUs <= w.empty.durationUs, "reload.empty");
  if (w.hasChamber) {
    check(e, w.empty.boltUs >= w.empty.insertUs && w.empty.boltUs <= w.empty.durationUs, "reload.empty.boltRelease");
    check(e, w.chamber.durationUs >= 0 && w.chamber.commitUs >= 0 && w.chamber.commitUs <= w.chamber.durationUs,
          "reload.chamber");
  }
  return e;
}

bool parseInterruptReason(const std::string& text, InterruptReason& out) {
  if (text == "sprint") out = InterruptReason::Sprint;
  else if (text == "switch") out = InterruptReason::Switch;
  else if (text == "death") out = InterruptReason::Death;
  else if (text == "other") out = InterruptReason::Other;
  else return false;
  return true;
}

WeaponState::WeaponState(const WeaponDef& def) : def_(def) {
  const std::vector<std::string> errors = validateWeaponDef(def_);
  if (!errors.empty()) configError_ = "weapons." + def_.id + ": " + errors.front();
  resetToLoadout();
}

std::vector<std::string> WeaponState::disabledByNames() const {
  std::vector<std::string> out;
  if (lifeLocked()) out.emplace_back("life");
  for (DisableReason r : {DisableReason::Sprint, DisableReason::Switch, DisableReason::Menu, DisableReason::Results,
                          DisableReason::Other}) {
    if (disabledBy(r)) out.emplace_back(toString(r));
  }
  return out;
}

void WeaponState::resetToLoadout() {
  // Probihajici akce musi skoncit udalosti (animace a zvuk), ne tichym zrusenim; schranka udalosti se nemaze.
  if (state_ != WeaponActivity::Ready) interrupt(InterruptReason::Other);
  magazine_ = def_.magazineCapacity;
  chamber_ = def_.hasChamber ? 1 : 0;
  reserve_ = def_.startReserve;
  fireMode_ = def_.defaultFireMode;
  state_ = WeaponActivity::Ready;
  clearAction();
  cooldownUs_ = 0;
  clockUs_ = 0;
  holdValid_ = false;  // triggerPrev_ a zamky se zamerne nemeni (viz hlavicka)
  shotsFired_ = 0;
  resupplied_ = 0;
  dryFires_ = 0;
  reloadsStarted_ = 0;
  reloadsCompleted_ = 0;
  reloadsInterrupted_ = 0;
  chamberActions_ = 0;
  initialTotal_ = magazine_ + chamber_ + reserve_;
}

bool WeaponState::setAmmo(int magazine, int chamber, int reserve) {
  const bool ok = configError_.empty() && state_ == WeaponActivity::Ready && magazine >= 0 && magazine <= def_.magazineCapacity && chamber >= 0 &&
                  chamber <= (def_.hasChamber ? 1 : 0) && reserve >= 0 && reserve <= def_.maxReserve;
  if (!ok) return false;
  magazine_ = magazine;
  chamber_ = chamber;
  reserve_ = reserve;
  shotsFired_ = 0;
  resupplied_ = 0;
  initialTotal_ = magazine + chamber + reserve;
  return true;
}

void WeaponState::clearAction() {
  reloadKind_ = ReloadKind::None;
  actionUs_ = 0;
  insertCommitted_ = false;
  boltReleased_ = false;
  chamberCommitted_ = false;
}

void WeaponState::emit(WeaponEventType type, const std::string& detail) { outbox_.push_back(WeaponEvent{type, clockUs_, detail}); }

std::vector<WeaponEvent> WeaponState::takeEvents() {
  std::vector<WeaponEvent> out;
  out.swap(outbox_);
  return out;
}

int WeaponState::update(Micros dtUs, bool trigger) {
  if (!validDt(dtUs) || !configError_.empty()) return 0;
  const int shotsBefore = shotsFired_;
  // Stisk = hrana pusteno -> drzeno. Zamcena zbran stisk ignoruje, ale stav spouste sleduje dal (GUN-03).
  if (!trigger) holdValid_ = false;
  else if (!triggerPrev_ && locks_ == 0) onPress();
  triggerPrev_ = trigger;
  // Vypnuta zbran nema platny stisk ani probihajici akci (disable ji prerusil), takze nize jen plyne cas.

  Micros remaining = dtUs;
  for (;;) {
    if (state_ != WeaponActivity::Ready) {
      const Micros toNext = nextMilestoneUs() - actionUs_;
      if (toNext > remaining) {
        pass(remaining);
        break;
      }
      pass(toNext);
      remaining -= toNext;
      applyMilestone();
      continue;
    }
    if (trigger && holdValid_ && canFireRound()) {
      const Micros wait = cooldownUs_;
      if (wait >= remaining) {  // vystrel presne na konci tiku patri dalsimu tiku
        pass(remaining);
        break;
      }
      pass(wait);
      remaining -= wait;
      fireRound();
      continue;
    }
    pass(remaining);
    break;
  }
  return shotsFired_ - shotsBefore;
}

void WeaponState::pass(Micros us) {
  clockUs_ += us;
  cooldownUs_ = cooldownUs_ > us ? cooldownUs_ - us : 0;
  if (state_ != WeaponActivity::Ready) actionUs_ += us;
}

void WeaponState::onPress() {
  if (state_ != WeaponActivity::Ready) {
    holdValid_ = false;
    return;
  }
  if (canFireRound()) {
    holdValid_ = true;
  } else if (needsChamberAction()) {
    holdValid_ = false;
    startChamber();
  } else {
    holdValid_ = false;
    dryFires_ += 1;
    emit(WeaponEventType::DryFire);
  }
}

void WeaponState::fireRound() {
  if (def_.hasChamber) {
    chamber_ = 0;
    if (magazine_ > 0) {
      magazine_ -= 1;
      chamber_ = 1;
    }
  } else {
    magazine_ -= 1;
  }
  shotsFired_ += 1;
  cooldownUs_ = def_.fireIntervalUs;
  if (fireMode_ == FireMode::Semi) holdValid_ = false;
  emit(WeaponEventType::Shot);
  if (!canFireRound() && def_.hasChamber) emit(WeaponEventType::BoltLocked);
}

void WeaponState::startChamber() {
  state_ = WeaponActivity::Chambering;
  clearAction();
  emit(WeaponEventType::ChamberStart);
}

Micros WeaponState::nextMilestoneUs() const {
  if (state_ == WeaponActivity::Chambering) return chamberCommitted_ ? def_.chamber.durationUs : def_.chamber.commitUs;
  if (reloadKind_ == ReloadKind::Tactical) return insertCommitted_ ? def_.tactical.durationUs : def_.tactical.insertUs;
  if (!insertCommitted_) return def_.empty.insertUs;
  if (def_.hasChamber && !boltReleased_) return def_.empty.boltUs;
  return def_.empty.durationUs;
}

void WeaponState::applyMilestone() {
  if (state_ == WeaponActivity::Chambering) {
    if (!chamberCommitted_) {
      // Commit nabiti: jediny okamzik, kdy naboj prejde ze zasobniku do komory.
      if (chamber_ == 0 && magazine_ > 0) {
        magazine_ -= 1;
        chamber_ = 1;
      }
      chamberCommitted_ = true;
      emit(WeaponEventType::ChamberCommit);
    } else {
      state_ = WeaponActivity::Ready;
      chamberActions_ += 1;
      clearAction();
      emit(WeaponEventType::ChamberComplete);
    }
    return;
  }
  if (!insertCommitted_) {
    // Commit vlozeni zasobniku: vyjmuty zasobnik vraci naboje do rezervy ("retained magazine"), novy se naplni z rezervy.
    const int pool = reserve_ + magazine_;
    const int fresh = std::min(def_.magazineCapacity, pool);
    magazine_ = fresh;
    reserve_ = pool - fresh;
    insertCommitted_ = true;
    emit(WeaponEventType::MagInsert);
    return;
  }
  if (reloadKind_ == ReloadKind::Empty && def_.hasChamber && !boltReleased_) {
    // Commit uvolneni zaveru: naboj ze zasobniku do komory.
    if (chamber_ == 0 && magazine_ > 0) {
      magazine_ -= 1;
      chamber_ = 1;
    }
    boltReleased_ = true;
    emit(WeaponEventType::BoltRelease);
    return;
  }
  const ReloadKind kind = reloadKind_;
  state_ = WeaponActivity::Ready;
  reloadsCompleted_ += 1;
  clearAction();
  emit(WeaponEventType::ReloadComplete, toString(kind));
}

ReloadResult WeaponState::reload() {
  if (!enabled()) return ReloadResult::RejectedDisabled;
  if (state_ != WeaponActivity::Ready) return ReloadResult::RejectedBusy;
  if (def_.hasChamber && chamber_ == 0 && magazine_ > 0 && (magazine_ == def_.magazineCapacity || reserve_ == 0)) {
    holdValid_ = false;
    startChamber();
    return ReloadResult::StartedChamber;
  }
  if (reserve_ == 0) return ReloadResult::RejectedNoReserve;
  if (magazine_ == def_.magazineCapacity && (!def_.hasChamber || chamber_ == 1)) return ReloadResult::RejectedFull;
  const bool tactical = def_.hasChamber ? chamber_ == 1 : magazine_ > 0;
  state_ = WeaponActivity::Reloading;
  clearAction();
  reloadKind_ = tactical ? ReloadKind::Tactical : ReloadKind::Empty;
  holdValid_ = false;
  reloadsStarted_ += 1;
  emit(WeaponEventType::ReloadStart, toString(reloadKind_));
  return tactical ? ReloadResult::StartedTactical : ReloadResult::StartedEmpty;
}

InterruptResult WeaponState::interrupt(InterruptReason reason) {
  if (state_ == WeaponActivity::Ready) return InterruptResult::None;
  if (state_ == WeaponActivity::Reloading) {
    reloadsInterrupted_ += 1;
    emit(WeaponEventType::ReloadInterrupted, toString(reason));
  } else {
    emit(WeaponEventType::ChamberInterrupted, toString(reason));
  }
  state_ = WeaponActivity::Ready;
  clearAction();
  holdValid_ = false;
  return InterruptResult::Interrupted;
}

void WeaponState::disable(DisableReason reason) { addLock(bitOf(reason), interruptFor(reason)); }

void WeaponState::enable(DisableReason reason) { removeLock(bitOf(reason)); }

void WeaponState::setLifeLock(bool locked, InterruptReason detail) {
  if (locked) addLock(kLifeBit, detail);
  else removeLock(kLifeBit);
}

void WeaponState::addLock(std::uint8_t bit, InterruptReason interruptReason) {
  if (state_ != WeaponActivity::Ready) interrupt(interruptReason);
  holdValid_ = false;
  locks_ = static_cast<std::uint8_t>(locks_ | bit);
}

void WeaponState::removeLock(std::uint8_t bit) {
  if ((locks_ & bit) == 0) return;
  locks_ = static_cast<std::uint8_t>(locks_ & ~bit);
  holdValid_ = false;
}

bool WeaponState::setFireMode(FireMode mode) {
  if (!def_.supportsFireMode(mode)) return false;
  if (mode != fireMode_) {
    fireMode_ = mode;
    holdValid_ = false;
  }
  return true;
}

int WeaponState::resupply(long long rounds) {
  if (rounds < 0 || !configError_.empty()) return -1;
  const long long room = static_cast<long long>(def_.maxReserve - reserve_);
  const int added = static_cast<int>(std::min(rounds, room));
  reserve_ += added;
  resupplied_ += added;
  return added;
}

std::vector<std::string> WeaponState::invariantViolations() const {
  std::vector<std::string> v;
  if (magazine_ < 0 || magazine_ > def_.magazineCapacity) v.push_back("magazine mimo rozsah: " + std::to_string(magazine_));
  if (chamber_ < 0 || chamber_ > (def_.hasChamber ? 1 : 0)) v.push_back("chamber mimo rozsah: " + std::to_string(chamber_));
  if (reserve_ < 0 || reserve_ > def_.maxReserve) v.push_back("reserve mimo rozsah: " + std::to_string(reserve_));
  const int expected = initialTotal_ - shotsFired_ + resupplied_;
  if (totalAmmo() != expected) {
    v.push_back("soucet munice " + std::to_string(totalAmmo()) + " != " + std::to_string(expected));
  }
  return v;
}

}  // namespace iv::core
