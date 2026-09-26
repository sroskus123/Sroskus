// Stav jedne zbrane: munice (zasobnik / komora / rezerva), rychlost palby, prebiti a jeho preruseni.
// Presna pravidla a politiky: Docs/RULES.md, oddil "Zbran". Stejny automat je v C++ (Core/src/weapon.cpp).
//
// Cas je v celych mikrosekundach. Tik [t, t+dt]:
//  - milniky akci (vlozeni zasobniku, uvolneni zaveru, nabiti, konec akce) naplanovane na cas <= t+dt probehnou
//    v tomto tiku (uzavreny interval), takze snimek v case T uz obsahuje vse, co bylo naplanovano na <= T;
//  - vystrely pokryvaji polootevreny interval [t, t+dt): vystrel presne v case t+dt patri dalsimu tiku,
//    kde se znovu cte spoust (600 ran/min drzenych presne 1 s = 10 vystrelu).
// Obe pravidla jsou nezavisla na tom, jak je stejny cas rozdelen na tiky.

import { assertDtMicros } from './time.js';

export const INTERRUPT_REASONS = Object.freeze(['sprint', 'switch', 'death', 'other']);

/**
 * Duvody vypnuti, ktere smi pouzit engine. Kazdy duvod je samostatny zamek: disable(d) zamek prida, enable(d) odebere
 * jen tento zamek a zbran prijima vstup, az kdyz nezbude zadny (Docs/RULES.md, oddil 6).
 */
export const DISABLE_REASONS = Object.freeze(['sprint', 'switch', 'menu', 'results', 'other']);

/**
 * Zamek "zivot" drzi jen RespawnSystem (vlastnik neni alive nebo zbran neni ve vybave). Klic je symbol, ktery
 * index.js neexportuje, takze engine ho verejnym API nezapne ani nevypne (GUN-03).
 */
export const LIFE_LOCK = Symbol('ironvalley.weapon.lifeLock');

// Poradi zamku ve snimku (disabledBy) a jejich bity.
const LOCK_ORDER = Object.freeze(['life', ...DISABLE_REASONS]);
const LOCK_BIT = Object.freeze(Object.fromEntries(LOCK_ORDER.map((name, i) => [name, 1 << i])));
// Duvod preruseni probihajici akce, kdyz ji vypnuti prerusi.
const LOCK_INTERRUPT = Object.freeze({ sprint: 'sprint', switch: 'switch', menu: 'other', results: 'other', other: 'other' });

export class WeaponState {
  /**
   * @param def zkompilovana definice zbrane (rules.weapons[id])
   * @param ammo volitelne {magazine, chamber, reserve} - pocatecni stav mimo vybavu (testy, ulozena hra)
   */
  constructor(def, ammo = null) {
    this.def = def;
    this.outbox = [];
    // Vstup a zamky nejsou soucasti vybavy, resetToLoadout je nemeni (viz nize).
    this.triggerPrev = false; // stav spouste pri poslednim update (posledni pozorovany vstup)
    this.locks = 0; // bitova maska zamku (LOCK_BIT); 0 = zbran prijima spoust a prebiti
    this.state = 'ready';
    this.clearAction();
    this.resetToLoadout();
    if (ammo) {
      if (this.setAmmo(ammo) !== 'ok') throw new RangeError('WeaponState: neplatny pocatecni stav munice');
    }
  }

  /**
   * Respawn: plna vychozi vybava, zruseni prebijeni, nulove citace (novy zivot).
   * Probihajici akce se nejdriv prerusi s duvodem 'other' (udalost reload_interrupted / chamber_interrupted), aby
   * animace a zvuk vzdy dostaly konec akce. Neodebrane udalosti ve schrance zustavaji (takeEvents je vrati).
   * Posledni pozorovany stav spouste (triggerPrev) zustava: spoust drzena pres reset neni novy stisk,
   * takze po resetu vystreli az dalsi stisk (Docs/RULES.md, R8/R20). Zamky (disable) ridi vlastnik a engine.
   */
  resetToLoadout() {
    const d = this.def;
    if (this.state !== 'ready') this.interrupt('other');
    this.magazine = d.magazineCapacity;
    this.chamber = d.hasChamber ? 1 : 0;
    this.reserve = d.startReserve;
    this.fireMode = d.defaultFireMode;
    this.state = 'ready';
    this.clearAction();
    this.cooldownUs = 0;
    this.clockUs = 0;
    this.holdValid = false;
    this.shotsFired = 0;
    this.resupplied = 0;
    this.dryFires = 0;
    this.reloadsStarted = 0;
    this.reloadsCompleted = 0;
    this.reloadsInterrupted = 0;
    this.chamberActions = 0;
    this.initialTotal = this.magazine + this.chamber + this.reserve;
  }

  /** Nastavi pocatecni stav munice (jen ve stavu ready). Novy stav je vychozim bodem pro kontrolu souctu. */
  setAmmo({ magazine = this.magazine, chamber = this.chamber, reserve = this.reserve } = {}) {
    const d = this.def;
    const ok =
      this.state === 'ready' &&
      Number.isInteger(magazine) && magazine >= 0 && magazine <= d.magazineCapacity &&
      Number.isInteger(chamber) && chamber >= 0 && chamber <= (d.hasChamber ? 1 : 0) &&
      Number.isInteger(reserve) && reserve >= 0 && reserve <= d.maxReserve;
    if (!ok) return 'invalid';
    this.magazine = magazine;
    this.chamber = chamber;
    this.reserve = reserve;
    this.shotsFired = 0;
    this.resupplied = 0;
    this.initialTotal = magazine + chamber + reserve;
    return 'ok';
  }

  clearAction() {
    this.reloadKind = 'none';
    this.actionUs = 0;
    this.insertCommitted = false;
    this.boltReleased = false;
    this.chamberCommitted = false;
  }

  /** Muze zbran prave ted vystrelit naboj (bez ohledu na spoust a kadenci)? */
  canFireRound() {
    return this.def.hasChamber ? this.chamber === 1 : this.magazine > 0;
  }

  /** Komora je prazdna, ale v zasobniku jsou naboje: dalsi stisk spouste provede nabiti (chamber). */
  get needsChamberAction() {
    return this.def.hasChamber && this.chamber === 0 && this.magazine > 0;
  }

  get isBusy() {
    return this.state !== 'ready';
  }

  /** true = zadny zamek: zbran prijima spoust i prebiti. */
  get enabled() {
    return this.locks === 0;
  }

  /** Aktivni zamky v pevnem poradi ('life', pak DISABLE_REASONS). */
  get disabledBy() {
    return LOCK_ORDER.filter((name) => (this.locks & LOCK_BIT[name]) !== 0);
  }

  get totalAmmo() {
    return this.magazine + this.chamber + this.reserve;
  }

  /** Vrati a vyprazdni udalosti (vystrel, vlozeni zasobniku, ...) pro zvuk, animace a HUD. */
  takeEvents() {
    const out = this.outbox;
    this.outbox = [];
    return out;
  }

  emit(type, detail = '') {
    this.outbox.push({ type, atUs: this.clockUs, detail });
  }

  /**
   * Posun casu o dtUs. trigger = stav spouste po celou dobu tiku.
   * Vraci pocet vystrelu v tomto tiku (udalosti viz takeEvents()).
   */
  update(dtUs, trigger) {
    assertDtMicros(dtUs);
    const held = trigger === true;
    const shotsBefore = this.shotsFired;
    // Stisk = hrana pusteno -> drzeno mezi dvema update. Vypnuta zbran (smrt, menu) stisk ignoruje, ale stav spouste
    // dal sleduje, takze spoust drzena pres smrt/menu/respawn po zapnuti nevystreli, dokud se nepusti (GUN-03).
    if (!held) this.holdValid = false;
    else if (!this.triggerPrev && this.enabled) this.onPress();
    this.triggerPrev = held;
    // Vypnuta zbran nema platny stisk ani probihajici akci (disable ji prerusil), takze nize jen plyne cas.

    let remaining = dtUs;
    for (;;) {
      if (this.state !== 'ready') {
        const toNext = this.nextMilestoneUs() - this.actionUs;
        if (toNext > remaining) {
          this.pass(remaining);
          break;
        }
        this.pass(toNext);
        remaining -= toNext;
        this.applyMilestone();
        continue;
      }
      if (held && this.holdValid && this.canFireRound()) {
        const wait = this.cooldownUs;
        if (wait >= remaining) {
          this.pass(remaining);
          break;
        }
        this.pass(wait);
        remaining -= wait;
        this.fireRound();
        continue;
      }
      this.pass(remaining);
      break;
    }
    return this.shotsFired - shotsBefore;
  }

  pass(us) {
    this.clockUs += us;
    this.cooldownUs = this.cooldownUs > us ? this.cooldownUs - us : 0;
    if (this.state !== 'ready') this.actionUs += us;
  }

  onPress() {
    if (this.state !== 'ready') {
      this.holdValid = false;
      return;
    }
    if (this.canFireRound()) {
      this.holdValid = true;
    } else if (this.needsChamberAction) {
      this.holdValid = false;
      this.startChamber();
    } else {
      this.holdValid = false;
      this.dryFires += 1;
      this.emit('dry_fire');
    }
  }

  fireRound() {
    const d = this.def;
    if (d.hasChamber) {
      this.chamber = 0;
      if (this.magazine > 0) {
        this.magazine -= 1;
        this.chamber = 1;
      }
    } else {
      this.magazine -= 1;
    }
    this.shotsFired += 1;
    this.cooldownUs = d.fireIntervalUs;
    if (this.fireMode === 'semi') this.holdValid = false;
    this.emit('shot');
    if (!this.canFireRound() && d.hasChamber) this.emit('bolt_locked');
  }

  startChamber() {
    this.state = 'chambering';
    this.clearAction();
    this.emit('chamber_start');
  }

  nextMilestoneUs() {
    const d = this.def;
    if (this.state === 'chambering') return this.chamberCommitted ? d.chamber.durationUs : d.chamber.commitUs;
    const t = this.reloadKind === 'tactical' ? d.tactical : d.empty;
    if (!this.insertCommitted) return t.insertUs;
    if (this.reloadKind === 'empty' && d.hasChamber && !this.boltReleased) return t.boltUs;
    return t.durationUs;
  }

  applyMilestone() {
    const d = this.def;
    if (this.state === 'chambering') {
      if (!this.chamberCommitted) {
        // Commit nabiti: jediny okamzik, kdy naboj prejde ze zasobniku do komory.
        if (this.chamber === 0 && this.magazine > 0) {
          this.magazine -= 1;
          this.chamber = 1;
        }
        this.chamberCommitted = true;
        this.emit('chamber_commit');
      } else {
        this.state = 'ready';
        this.chamberActions += 1;
        this.clearAction();
        this.emit('chamber_complete');
      }
      return;
    }
    if (!this.insertCommitted) {
      // Commit vlozeni zasobniku: vyjmuty zasobnik vraci naboje do rezervy (politika "retained magazine"),
      // novy zasobnik se naplni z rezervy. Jedina atomicka transakce.
      const pool = this.reserve + this.magazine;
      const fresh = Math.min(d.magazineCapacity, pool);
      this.magazine = fresh;
      this.reserve = pool - fresh;
      this.insertCommitted = true;
      this.emit('mag_insert');
      return;
    }
    if (this.reloadKind === 'empty' && d.hasChamber && !this.boltReleased) {
      // Commit uvolneni zaveru: naboj ze zasobniku do komory.
      if (this.chamber === 0 && this.magazine > 0) {
        this.magazine -= 1;
        this.chamber = 1;
      }
      this.boltReleased = true;
      this.emit('bolt_release');
      return;
    }
    const kind = this.reloadKind;
    this.state = 'ready';
    this.reloadsCompleted += 1;
    this.clearAction();
    this.emit('reload_complete', kind);
  }

  /** Pozadavek na prebiti. Vraci vysledek jako text (viz Docs/RULES.md). */
  reload() {
    const d = this.def;
    if (!this.enabled) return 'rejected_disabled';
    if (this.state !== 'ready') return 'rejected_busy';
    if (d.hasChamber && this.chamber === 0 && this.magazine > 0 && (this.magazine === d.magazineCapacity || this.reserve === 0)) {
      this.holdValid = false;
      this.startChamber();
      return 'started_chamber';
    }
    if (this.reserve === 0) return 'rejected_no_reserve';
    if (this.magazine === d.magazineCapacity && (!d.hasChamber || this.chamber === 1)) return 'rejected_full';
    const kind = (d.hasChamber ? this.chamber === 1 : this.magazine > 0) ? 'tactical' : 'empty';
    this.state = 'reloading';
    this.clearAction();
    this.reloadKind = kind;
    this.holdValid = false;
    this.reloadsStarted += 1;
    this.emit('reload_start', kind);
    return `started_${kind}`;
  }

  /** Preruseni prebijeni / nabijeni (sprint, vymena zbrane, smrt). Munice se meni jen commity, ktere uz probehly. */
  interrupt(reason) {
    if (!INTERRUPT_REASONS.includes(reason)) return 'invalid_reason';
    if (this.state === 'ready') return 'none';
    if (this.state === 'reloading') {
      this.reloadsInterrupted += 1;
      this.emit('reload_interrupted', reason);
    } else {
      this.emit('chamber_interrupted', reason);
    }
    this.state = 'ready';
    this.clearAction();
    this.holdValid = false;
    return 'interrupted';
  }

  /**
   * Zamek s duvodem z DISABLE_REASONS (menu, vysledkova obrazovka, sprint, vymena zbrane ...). Probihajici
   * prebijeni/nabijeni se prerusi (sprint -> 'sprint', switch -> 'switch', jinak 'other'; pravidla jako interrupt),
   * platny stisk se zrusi. Dokud trva jakykoli zamek, spoust se ignoruje (jeji stav se dal sleduje) a reload() vraci
   * rejected_disabled; cas (hodiny zbrane, dobeh intervalu) plyne dal. Opakovane vypnuti stejnym duvodem nic nemeni.
   */
  disable(reason) {
    if (!DISABLE_REASONS.includes(reason)) return 'invalid_reason';
    this.addLock(LOCK_BIT[reason], LOCK_INTERRUPT[reason]);
    return 'ok';
  }

  /**
   * Odebere jen zamek s timto duvodem; ostatni zamky (jiny duvod, zamek zivota) trvaji. Az zmizi posledni zamek,
   * zbran prijima vstup, ale vystrelit smi az novy stisk (spoust drzena pri posledni aktualizaci se musi pustit).
   * Odebrani zamku, ktery neni nastaven, nic nedela.
   */
  enable(reason) {
    if (!DISABLE_REASONS.includes(reason)) return 'invalid_reason';
    this.removeLock(LOCK_BIT[reason]);
    return 'ok';
  }

  /** Jen pro RespawnSystem: zamek zivota (smrt, cekani na spawn, zbran mimo vybavu). detail = duvod preruseni. */
  [LIFE_LOCK](locked, detail = 'other') {
    if (locked) this.addLock(LOCK_BIT.life, detail);
    else this.removeLock(LOCK_BIT.life);
  }

  addLock(bit, interruptReason) {
    if (this.state !== 'ready') this.interrupt(interruptReason);
    this.holdValid = false;
    this.locks |= bit;
  }

  removeLock(bit) {
    if ((this.locks & bit) === 0) return;
    this.locks &= ~bit;
    this.holdValid = false;
  }

  setFireMode(mode) {
    if (!this.def.fireModes.includes(mode)) return 'rejected';
    if (mode !== this.fireMode) {
      this.fireMode = mode;
      this.holdValid = false;
    }
    return 'ok';
  }

  /** Doplneni rezervy (az do maxReserve). Vraci skutecne pridany pocet, -1 pri neplatnem vstupu. */
  resupply(rounds) {
    if (!Number.isSafeInteger(rounds) || rounds < 0) return -1;
    const added = Math.min(rounds, this.def.maxReserve - this.reserve);
    this.reserve += added;
    this.resupplied += added;
    return added;
  }

  snapshot() {
    return {
      weapon: this.def.id,
      state: this.state,
      reloadKind: this.reloadKind,
      actionUs: this.actionUs,
      insertCommitted: this.insertCommitted,
      boltReleased: this.boltReleased,
      chamberCommitted: this.chamberCommitted,
      magazine: this.magazine,
      chamber: this.chamber,
      reserve: this.reserve,
      fireMode: this.fireMode,
      cooldownUs: this.cooldownUs,
      clockUs: this.clockUs,
      triggerPrev: this.triggerPrev,
      holdValid: this.holdValid,
      enabled: this.enabled,
      disabledBy: this.disabledBy,
      shotsFired: this.shotsFired,
      resupplied: this.resupplied,
      dryFires: this.dryFires,
      reloadsStarted: this.reloadsStarted,
      reloadsCompleted: this.reloadsCompleted,
      reloadsInterrupted: this.reloadsInterrupted,
      chamberActions: this.chamberActions,
      initialTotal: this.initialTotal,
    };
  }
}

/** Kontrola invariantu munice. Vraci seznam poruseni (prazdny = v poradku). */
export function weaponInvariantViolations(snap, def) {
  const v = [];
  const nonNegInt = (x) => Number.isSafeInteger(x) && x >= 0;
  if (!nonNegInt(snap.magazine) || snap.magazine > def.magazineCapacity) v.push(`magazine mimo rozsah: ${snap.magazine}`);
  if (!nonNegInt(snap.chamber) || snap.chamber > (def.hasChamber ? 1 : 0)) v.push(`chamber mimo rozsah: ${snap.chamber}`);
  if (!nonNegInt(snap.reserve) || snap.reserve > def.maxReserve) v.push(`reserve mimo rozsah: ${snap.reserve}`);
  const expected = snap.initialTotal - snap.shotsFired + snap.resupplied;
  const total = snap.magazine + snap.chamber + snap.reserve;
  if (total !== expected) v.push(`soucet munice ${total} != ${expected} (pocatek ${snap.initialTotal} - vystrely ${snap.shotsFired} + doplneni ${snap.resupplied})`);
  return v;
}
